from __future__ import annotations

"""
L1 组件级 runner —— 逐 MCP 工具的隔离评测。

每个 COMPONENT 任务：
  1. 判断是否应 skip（requires_api+offline / requires_llm+无 key）。
  2. 开 eval_sandbox 建立隔离环境。
  3. 若 gold 含 seed_graph，把 fixture 复制进隔离图谱（绝不读真实图谱）。
  4. 加载历史 failure cards -> 派生 pre-hints；将 lessons + hints 注入 ctx。
  5. 按 target.tool 取 adapter，在 tracer.span 内调用（带 timeout）。
  6. 调用失败时让 critic 判定是否重试一次（每任务硬上限 max_retries=1）。
  7. 把 ToolCallResult 收敛成 TaskResult；critic 元数据写入 raw["_critic"] 供审计。
"""

import asyncio
import logging
import os

from ..adapters.base import AdapterContext, ToolCallResult, get_adapter
from ..critic import decide_after_failure, derive_pre_hints
from ..dataset import Dataset
from ..failure_lookup import load_all_cards, lookup
from ..isolation import eval_sandbox
from ..schema import EvalLayer, TaskResult, TaskSpec
from ..tracer import Tracer

logger = logging.getLogger("AcademicAgent.Eval.Layer1")

# 每任务最多一次 critic 引导的重试。提高它的代价是延迟与 token，谨慎。
_MAX_CRITIC_RETRIES = 1


def _should_skip(task: TaskSpec, offline: bool) -> str | None:
    """返回 skip 原因；不应 skip 时返回 None。

    --offline 同时跳过 requires_api 与 requires_llm（LLM 也是网络调用），
    使离线 smoke run 完全确定、不触达任何外部服务。
    """
    if offline and (task.requires_api or task.requires_llm):
        return "requires external API/LLM but --offline set"
    if task.requires_llm and not os.getenv("MINIMAX_API_KEY"):
        return "requires LLM but MINIMAX_API_KEY not set"
    return None


async def _invoke_adapter(
    adapter, args: dict, ctx: AdapterContext, timeout_s: int, tool: str,
) -> ToolCallResult:
    """单次 adapter 调用，把超时与抛异常都收敛为 ToolCallResult.failure。"""
    try:
        return await asyncio.wait_for(adapter(args, ctx), timeout=timeout_s)
    except asyncio.TimeoutError:
        return ToolCallResult.failure(
            tool, f"task timed out after {timeout_s}s", "timeout",
        )
    except Exception as exc:  # noqa: BLE001 — adapter 抛出的任何异常都收敛为失败
        return ToolCallResult.failure(
            tool, f"adapter raised: {exc}", "tool_exception",
        )


async def run_component_task(
    task: TaskSpec,
    dataset: Dataset,
    run_dir,
    tracer: Tracer,
    offline: bool = False,
) -> TaskResult:
    """运行单个 L1 组件级任务。"""
    layer = task.layer.value
    cap = task.capability.value
    tool_name = task.target.tool or ""

    skip_reason = _should_skip(task, offline)
    if skip_reason:
        logger.info("  [skipped ] %s — %s", task.task_id, skip_reason)
        return TaskResult(
            task_id=task.task_id, layer=layer, capability=cap,
            status="skipped", skip_reason=skip_reason,
        )

    adapter = get_adapter(tool_name)
    if adapter is None:
        return TaskResult(
            task_id=task.task_id, layer=layer, capability=cap,
            status="failed", error=f"no adapter for tool {tool_name!r}",
            error_category="tool_exception",
        )

    gold = dataset.gold_for(task)

    # ---- 失败卡片 runtime 注入 -------------------------------------------------
    # run_dir 形如 data/evaluation/runs/<run_id>；failure_cards 与之同级。
    # 加载本身失败不影响主流程（degrade to 空 lessons）。
    try:
        cards_dir = run_dir.parent.parent / "failure_cards"
        all_cards = load_all_cards(cards_dir)
        lessons = lookup(all_cards, capability=cap, tool=tool_name, top_k=5)
    except Exception as exc:  # noqa: BLE001 — 历史卡片读取异常绝不阻塞当前 run
        logger.warning("加载历史失败卡片失败 (%s)；本任务无 lesson 注入", exc)
        lessons = []
    pre_hints = derive_pre_hints(lessons, tool=tool_name)
    if pre_hints:
        logger.info(
            "  [lesson  ] %s — 注入 pre-hints: %s (基于 %d 张历史卡片)",
            task.task_id, pre_hints, len(lessons),
        )

    with eval_sandbox(run_dir, task.task_id) as sandbox:
        # 需要 seed 图谱的能力（gap_detection / kg_query）：把 fixture 拷进隔离图谱
        if gold and gold.get("seed_graph"):
            try:
                sandbox.seed_graph_from(dataset.path / gold["seed_graph"])
            except FileNotFoundError:
                # 兼容 gold 里写的是相对项目根的路径
                sandbox.seed_graph_from(gold["seed_graph"])

        ctx = AdapterContext(
            sandbox=sandbox, gold=gold, offline=offline,
            dataset_path=dataset.path,
            lessons=list(lessons), hints=dict(pre_hints),
        )

        # ---- 调用循环：1 次主调用 + 至多 _MAX_CRITIC_RETRIES 次受限重试 ---------
        retries_used = 0
        applied_hints_log: list[dict] = [dict(pre_hints)] if pre_hints else []
        decision_reasons: list[str] = []
        tool_result: ToolCallResult

        while True:
            async with tracer.span(task.task_id, "tool_call", tool_name) as span:
                tool_result = await _invoke_adapter(
                    adapter, task.target.args, ctx, task.timeout_s, tool_name,
                )
                span.set_result(
                    ok=tool_result.ok,
                    input_summary=str(task.target.args)[:200],
                    output_summary=tool_result.text[:300],
                    error=tool_result.error,
                    error_category=tool_result.error_category,
                    tokens_in=tool_result.tokens_in,
                    tokens_out=tool_result.tokens_out,
                )

            if tool_result.ok or retries_used >= _MAX_CRITIC_RETRIES:
                break

            decision = decide_after_failure(
                error_category=tool_result.error_category,
                lessons=lessons,
                retries_used=retries_used,
                max_retries=_MAX_CRITIC_RETRIES,
            )
            decision_reasons.append(decision.reason)
            if not decision.should_retry:
                break
            ctx.hints.update(decision.hints)
            applied_hints_log.append(dict(decision.hints))
            retries_used += 1
            logger.info(
                "  [retry   ] %s — %s; hints=%s",
                task.task_id, decision.reason, decision.hints,
            )

    status = "ok" if tool_result.ok else "failed"
    logger.info("  [%-8s] %s", status, task.task_id)

    raw_out: dict = dict(tool_result.raw or {})
    # 把 critic 决策痕迹写入 raw 供审计（不动 TaskResult schema 以保持向后兼容）
    if lessons or retries_used or applied_hints_log or decision_reasons:
        raw_out["_critic"] = {
            "lesson_card_ids": [lesson.card_id for lesson in lessons],
            "pre_hints": pre_hints,
            "retries_used": retries_used,
            "applied_hints": applied_hints_log,
            "decisions": decision_reasons,
            "lesson_assisted_ok": (
                tool_result.ok and (retries_used > 0 or bool(pre_hints))
            ),
        }

    return TaskResult(
        task_id=task.task_id, layer=layer, capability=cap, status=status,
        raw=raw_out,
        tokens_in=tool_result.tokens_in, tokens_out=tool_result.tokens_out,
        error=tool_result.error, error_category=tool_result.error_category,
    )


async def run_layer1(
    tasks: list[TaskSpec],
    dataset: Dataset,
    run_dir,
    tracer: Tracer,
    offline: bool = False,
) -> list[TaskResult]:
    """顺序运行所有 L1 组件级任务。"""
    component_tasks = [t for t in tasks if t.layer == EvalLayer.COMPONENT]
    results: list[TaskResult] = []
    for task in component_tasks:
        results.append(
            await run_component_task(task, dataset, run_dir, tracer, offline)
        )
    return results

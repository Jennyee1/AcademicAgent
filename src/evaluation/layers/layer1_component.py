from __future__ import annotations

"""
L1 组件级 runner —— 逐 MCP 工具的隔离评测。

每个 COMPONENT 任务：
  1. 判断是否应 skip（requires_api+offline / requires_llm+无 key）。
  2. 开 eval_sandbox 建立隔离环境。
  3. 若 gold 含 seed_graph，把 fixture 复制进隔离图谱（绝不读真实图谱）。
  4. 按 target.tool 取 adapter，在 tracer.span 内调用（带 timeout）。
  5. 把 ToolCallResult 收敛成 TaskResult。
"""

import asyncio
import logging
import os

from ..adapters.base import AdapterContext, get_adapter
from ..dataset import Dataset
from ..isolation import eval_sandbox
from ..schema import EvalLayer, TaskResult, TaskSpec
from ..tracer import Tracer

logger = logging.getLogger("AcademicAgent.Eval.Layer1")


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

    skip_reason = _should_skip(task, offline)
    if skip_reason:
        logger.info("  [skipped ] %s — %s", task.task_id, skip_reason)
        return TaskResult(
            task_id=task.task_id, layer=layer, capability=cap,
            status="skipped", skip_reason=skip_reason,
        )

    adapter = get_adapter(task.target.tool or "")
    if adapter is None:
        return TaskResult(
            task_id=task.task_id, layer=layer, capability=cap,
            status="failed", error=f"no adapter for tool {task.target.tool!r}",
            error_category="tool_exception",
        )

    gold = dataset.gold_for(task)

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
        )

        result_holder: dict = {}
        async with tracer.span(task.task_id, "tool_call", task.target.tool or "") as span:
            from ..adapters.base import ToolCallResult
            try:
                tool_result = await asyncio.wait_for(
                    adapter(task.target.args, ctx), timeout=task.timeout_s,
                )
            except asyncio.TimeoutError:
                tool_result = ToolCallResult.failure(
                    task.target.tool or "", f"task timed out after {task.timeout_s}s",
                    "timeout",
                )
            except Exception as exc:  # noqa: BLE001 — adapter 抛出的任何异常都收敛为失败
                tool_result = ToolCallResult.failure(
                    task.target.tool or "", f"adapter raised: {exc}", "tool_exception",
                )
            result_holder["r"] = tool_result
            span.set_result(
                ok=tool_result.ok,
                input_summary=str(task.target.args)[:200],
                output_summary=tool_result.text[:300],
                error=tool_result.error,
                error_category=tool_result.error_category,
                tokens_in=tool_result.tokens_in,
                tokens_out=tool_result.tokens_out,
            )

    tool_result = result_holder["r"]
    status = "ok" if tool_result.ok else "failed"
    logger.info("  [%-8s] %s", status, task.task_id)
    return TaskResult(
        task_id=task.task_id, layer=layer, capability=cap, status=status,
        raw=tool_result.raw,
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

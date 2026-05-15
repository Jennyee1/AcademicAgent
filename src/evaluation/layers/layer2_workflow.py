from __future__ import annotations

"""
L2 工作流 runner —— 确定性脚本化多步工作流。

每个 WORKFLOW 任务：
  1. skip 判断（requires_api/llm）。
  2. 开**一个共享** eval_sandbox（sidecar 图谱跨步骤累积）。
  3. 若 gold 含 seed_graph，先 seed。
  4. 取 WorkflowSpec，按固定顺序逐步执行：
     args = step.args_fn(accumulated)；调 adapter（event_type="workflow_step"）；
     accumulated.update(step.capture(result.raw))。
  5. 运行终态断言（针对最终 sidecar 图谱与累积输出）。
  6. 收敛成 TaskResult，raw 含 actual_tool_sequence / step_ok / all_steps_ok /
     final_assertion_results。

无 LLM 决策、序列固定 —— 这是 L2 可复现的根本原因。
"""

import asyncio
import logging
import os

from ..adapters.base import AdapterContext, ToolCallResult, get_adapter
from ..dataset import Dataset
from ..isolation import eval_sandbox
from ..schema import EvalLayer, TaskResult, TaskSpec
from ..tracer import Tracer
from ..workflows.registry import get_workflow

logger = logging.getLogger("AcademicAgent.Eval.Layer2")


def _should_skip(task: TaskSpec, offline: bool) -> str | None:
    if offline and (task.requires_api or task.requires_llm):
        return "requires external API/LLM but --offline set"
    if task.requires_llm and not os.getenv("MINIMAX_API_KEY"):
        return "requires LLM but MINIMAX_API_KEY not set"
    return None


def _eval_final_assertions(
    assertions: list[dict],
    sandbox,
    accumulated: dict,
) -> list[bool]:
    """对最终 sidecar 状态 + 累积输出评估终态断言，返回逐条 bool。"""
    if not assertions:
        return []
    # 懒加载图谱（部分断言需要）
    node_count = edge_count = 0
    try:
        from src.knowledge.graph_store import KnowledgeGraphStore
        store = KnowledgeGraphStore(graph_path=sandbox.graph_path)
        node_count, edge_count = store.node_count, store.edge_count
    except Exception:  # noqa: BLE001
        pass

    results: list[bool] = []
    for a in assertions:
        check = a.get("check", "")
        if check == "graph_min_nodes":
            results.append(node_count >= int(a.get("value", 0)))
        elif check == "graph_min_edges":
            results.append(edge_count >= int(a.get("value", 0)))
        elif check == "step_captured_min":
            key = a.get("key", "")
            val = accumulated.get(key, 0)
            try:
                results.append(float(val) >= float(a.get("value", 0)))
            except (TypeError, ValueError):
                results.append(bool(val))
        elif check == "captured_nonempty":
            results.append(bool(accumulated.get(a.get("key", ""))))
        else:
            logger.warning("未知终态断言 check: %s", check)
            results.append(False)
    return results


async def run_workflow_task(
    task: TaskSpec,
    dataset: Dataset,
    run_dir,
    tracer: Tracer,
    offline: bool = False,
) -> TaskResult:
    """运行单个 L2 工作流任务。"""
    layer = task.layer.value
    cap = task.capability.value

    skip_reason = _should_skip(task, offline)
    if skip_reason:
        logger.info("  [skipped ] %s — %s", task.task_id, skip_reason)
        return TaskResult(task_id=task.task_id, layer=layer, capability=cap,
                          status="skipped", skip_reason=skip_reason)

    spec = get_workflow(task.target.workflow or "")
    if spec is None:
        return TaskResult(task_id=task.task_id, layer=layer, capability=cap,
                          status="failed",
                          error=f"unknown workflow {task.target.workflow!r}",
                          error_category="tool_exception")

    gold = dataset.gold_for(task)
    accumulated: dict = dict(task.target.args or {})
    actual_sequence: list[str] = []
    step_ok: list[bool] = []
    step_details: list[dict] = []
    total_tokens_in = total_tokens_out = 0

    with eval_sandbox(run_dir, task.task_id) as sandbox:
        if gold and gold.get("seed_graph"):
            try:
                sandbox.seed_graph_from(dataset.path / gold["seed_graph"])
            except FileNotFoundError:
                sandbox.seed_graph_from(gold["seed_graph"])

        ctx = AdapterContext(sandbox=sandbox, gold=gold, offline=offline,
                             dataset_path=dataset.path)

        for step in spec.steps:
            adapter = get_adapter(step.tool)
            actual_sequence.append(step.tool)
            if adapter is None:
                step_ok.append(False)
                step_details.append({"step": step.name, "tool": step.tool,
                                      "ok": False, "error": "no adapter"})
                continue
            args = step.args_fn(accumulated)
            async with tracer.span(task.task_id, "workflow_step", step.tool) as span:
                try:
                    res = await asyncio.wait_for(
                        adapter(args, ctx), timeout=task.timeout_s,
                    )
                except asyncio.TimeoutError:
                    res = ToolCallResult.failure(step.tool, "step timed out", "timeout")
                except Exception as exc:  # noqa: BLE001
                    res = ToolCallResult.failure(
                        step.tool, f"adapter raised: {exc}", "tool_exception")
                span.set_result(
                    ok=res.ok, input_summary=str(args)[:160],
                    output_summary=res.text[:240], error=res.error,
                    error_category=res.error_category,
                    tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                )
            step_ok.append(res.ok)
            total_tokens_in += res.tokens_in
            total_tokens_out += res.tokens_out
            step_details.append({"step": step.name, "tool": step.tool,
                                 "ok": res.ok, "error": res.error[:200]})
            if res.ok:
                try:
                    accumulated.update(step.capture(res.raw))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("step %s capture 失败: %s", step.name, exc)

        final_assertions = (gold or {}).get("final_assertions", [])
        final_results = _eval_final_assertions(final_assertions, sandbox, accumulated)

    all_ok = bool(step_ok) and all(step_ok)
    # 任务整体状态：所有步骤成功 = ok；否则 failed
    status = "ok" if all_ok else "failed"
    error = "" if all_ok else "one or more workflow steps failed"
    error_cat = "" if all_ok else "tool_exception"
    logger.info("  [%-8s] %s (%d/%d steps ok)",
                status, task.task_id, sum(step_ok), len(step_ok))

    return TaskResult(
        task_id=task.task_id, layer=layer, capability=cap, status=status,
        raw={
            "actual_tool_sequence": actual_sequence,
            "step_ok": step_ok,
            "all_steps_ok": all_ok,
            "step_details": step_details,
            "final_assertion_results": final_results,
        },
        tokens_in=total_tokens_in, tokens_out=total_tokens_out,
        error=error, error_category=error_cat,
    )


async def run_layer2(
    tasks: list[TaskSpec],
    dataset: Dataset,
    run_dir,
    tracer: Tracer,
    offline: bool = False,
) -> list[TaskResult]:
    """顺序运行所有 L2 工作流任务。"""
    wf_tasks = [t for t in tasks if t.layer == EvalLayer.WORKFLOW]
    results: list[TaskResult] = []
    for task in wf_tasks:
        results.append(await run_workflow_task(task, dataset, run_dir, tracer, offline))
    return results

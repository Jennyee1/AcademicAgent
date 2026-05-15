from __future__ import annotations

"""
L3 端到端 runner —— 接口骨架（本期不实现）。

L3 用一个固定 model+prompt 版本的 LLM 驱动真实 Agent 循环
（plan -> tool call -> observe -> synthesize），评测多步任务完成度。
依赖 LLM driver、非确定性、消耗 token —— 已与用户确认延后实现。

实现时：仍在 eval_sandbox 内运行（SCHOLARMIND_DATA_DIR 被覆盖），
即使驱动真实 MCP server 也写入 sidecar，不污染真实数据。
"""

from ..dataset import Dataset
from ..schema import EvalLayer, TaskResult, TaskSpec
from ..tracer import Tracer


async def run_e2e_task(
    task: TaskSpec,
    dataset: Dataset,
    run_dir,
    tracer: Tracer,
    offline: bool = False,
) -> TaskResult:
    """运行单个 L3 端到端任务（未实现）。"""
    raise NotImplementedError(
        "Layer 3 (LLM-driven end-to-end) 已规划但本期未实现。"
        "见 docs/evaluation/implementation_plan.md。"
    )


async def run_layer3(
    tasks: list[TaskSpec],
    dataset: Dataset,
    run_dir,
    tracer: Tracer,
    offline: bool = False,
) -> list[TaskResult]:
    """运行所有 L3 任务。本期：若存在 E2E 任务则全部标记 skipped。"""
    e2e_tasks = [t for t in tasks if t.layer == EvalLayer.E2E]
    results: list[TaskResult] = []
    for task in e2e_tasks:
        results.append(TaskResult(
            task_id=task.task_id, layer=task.layer.value,
            capability=task.capability.value, status="skipped",
            skip_reason="Layer 3 (e2e) not implemented this iteration",
        ))
    return results

from __future__ import annotations

"""
L2 脚本化工作流注册表。

WorkflowSpec 是一条固定有序的工具调用链。每个 WorkflowStep 的 args_fn
接收「前序步骤输出的累积字典」，把上一步的产物穿到下一步 ——
但**没有 LLM 决策、序列完全固定**，这是 L2 可复现的根本原因。

具体工作流在 survey_flow.py / learn_flow.py 中定义，import 时自动注册。
"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class WorkflowStep:
    """工作流中的一步。

    tool      : adapter 工具名（须在 dataset.KNOWN_TOOLS 中）
    args_fn   : (prev_outputs: dict) -> dict，生成本步的工具参数
    capture   : (tool_result_raw: dict) -> dict，从本步结果里提取要传给后续步骤的键值
    """
    name: str
    tool: str
    args_fn: Callable[[dict], dict]
    capture: Callable[[dict], dict] = lambda raw: {}


@dataclass
class WorkflowSpec:
    """一条完整的脚本化工作流。"""
    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)


WORKFLOW_REGISTRY: dict[str, WorkflowSpec] = {}


def register_workflow(spec: WorkflowSpec) -> WorkflowSpec:
    WORKFLOW_REGISTRY[spec.name] = spec
    return spec


def get_workflow(name: str) -> WorkflowSpec | None:
    # 触发具体工作流模块的注册
    from . import survey_flow, learn_flow  # noqa: F401
    return WORKFLOW_REGISTRY.get(name)


def all_workflows() -> dict[str, WorkflowSpec]:
    from . import survey_flow, learn_flow  # noqa: F401
    return dict(WORKFLOW_REGISTRY)

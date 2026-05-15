from __future__ import annotations

"""
learn_flow —— 学习路径工作流（离线可跑）。

固定序列：detect_gaps -> get_concept_importance -> analyze_knowledge。
全部在一个共享 sidecar 图谱上运行 —— 该图谱由 layer2 runner 用 gold 里的
seed_graph fixture 预先 seed，因此完全离线、确定性可复现。
"""

from .registry import WorkflowSpec, WorkflowStep, register_workflow

register_workflow(WorkflowSpec(
    name="learn_flow",
    description="在 seed 图谱上跑「盲区检测 -> 概念重要性 -> 学习路径」三步链路",
    steps=[
        WorkflowStep(
            name="detect_gaps",
            tool="detect_gaps",
            args_fn=lambda prev: {},
            capture=lambda raw: {"gap_count": len(raw.get("gaps", []))},
        ),
        WorkflowStep(
            name="get_concept_importance",
            tool="get_concept_importance",
            args_fn=lambda prev: {"top_n": 5},
            capture=lambda raw: {"top_concepts": raw.get("top_concepts", [])},
        ),
        WorkflowStep(
            name="analyze_knowledge",
            tool="analyze_knowledge",
            args_fn=lambda prev: {"max_items": 10},
            capture=lambda raw: {"path_length": raw.get("path_length", 0)},
        ),
    ],
))

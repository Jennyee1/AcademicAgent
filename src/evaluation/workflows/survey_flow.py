from __future__ import annotations

"""
survey_flow —— 文献调研工作流（需要 API + LLM）。

固定序列：search_papers -> get_paper_details -> add_paper_to_graph -> query_knowledge。
args_fn 把上一步的产物（paper_id、abstract、title）穿到下一步 ——
但序列与穿线规则完全固定、无 LLM 决策，这是 L2 可复现的根本原因。

初始 prev_outputs = task.target.args（任务自带的 query 等输入）。
"""

from .registry import WorkflowSpec, WorkflowStep, register_workflow

register_workflow(WorkflowSpec(
    name="survey_flow",
    description="检索论文 -> 取详情 -> 抽取入隔离图谱 -> 在图谱中回查，端到端文献调研链路",
    steps=[
        WorkflowStep(
            name="search_papers",
            tool="search_papers",
            args_fn=lambda prev: {
                "query": prev.get("query", "LLM agent"),
                "limit": int(prev.get("limit", 3)),
            },
            capture=lambda raw: {
                "first_paper_id": (raw.get("retrieved_ids") or [""])[0],
                "first_title": (raw.get("retrieved") or [""])[0],
            },
        ),
        WorkflowStep(
            name="get_paper_details",
            tool="get_paper_details",
            args_fn=lambda prev: {"paper_id": prev.get("first_paper_id", "")},
            capture=lambda raw: {
                "abstract": (raw.get("paper") or {}).get("abstract", "") or "",
                "detail_title": raw.get("title", ""),
            },
        ),
        WorkflowStep(
            name="add_paper_to_graph",
            tool="add_paper_to_graph",
            args_fn=lambda prev: {
                "text": prev.get("abstract") or prev.get("first_title", ""),
                "paper_title": prev.get("detail_title") or prev.get("first_title", ""),
            },
            capture=lambda raw: {"node_count": raw.get("node_count", 0)},
        ),
        WorkflowStep(
            name="query_knowledge",
            tool="query_knowledge",
            args_fn=lambda prev: {
                "query": prev.get("detail_title") or prev.get("first_title", "agent"),
            },
            capture=lambda raw: {"matched": raw.get("matched_labels", [])},
        ),
    ],
))

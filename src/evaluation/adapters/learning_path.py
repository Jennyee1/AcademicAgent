from __future__ import annotations

"""
learning_path adapter —— 封装图谱分析与学习路径能力。

全部在 ctx.sandbox.graph_path 上操作。该图谱通常由 layer runner 用
gold 中的 seed_graph fixture 预先 seed —— 绝不读真实图谱，保证确定性可复现。
"""

from .base import AdapterContext, ToolCallResult, register_adapter


def _load_analyzer(ctx: AdapterContext):
    from src.knowledge.graph_analyzer import KnowledgeGraphAnalyzer
    from src.knowledge.graph_store import KnowledgeGraphStore
    store = KnowledgeGraphStore(graph_path=ctx.sandbox.graph_path)
    return store, KnowledgeGraphAnalyzer(store)


@register_adapter("detect_gaps")
async def detect_gaps(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """检测知识盲区。

    raw: {"detected_gap_types": [...], "detected_gap_labels": [...], "gaps": [...]}
    """
    store, analyzer = _load_analyzer(ctx)
    if store.node_count == 0:
        return ToolCallResult.failure(
            "detect_gaps", "sidecar graph is empty (seed graph not provided?)",
            "tool_exception",
        )
    gaps = analyzer.detect_knowledge_gaps()
    return ToolCallResult(
        ok=True, tool="detect_gaps",
        raw={
            "detected_gap_types": sorted({g.gap_type for g in gaps}),
            "detected_gap_labels": [g.label for g in gaps],
            "gaps": [
                {"label": g.label, "gap_type": g.gap_type, "severity": g.severity,
                 "node_type": g.node_type}
                for g in gaps
            ],
        },
        text=f"{len(gaps)} gaps over {store.node_count} nodes",
    )


@register_adapter("get_concept_importance")
async def get_concept_importance(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """计算概念重要性排序。

    raw: {"top_concepts": [labels], "importance": [...]}
    """
    store, analyzer = _load_analyzer(ctx)
    if store.node_count == 0:
        return ToolCallResult.failure(
            "get_concept_importance", "sidecar graph is empty", "tool_exception",
        )
    top_n = int(args.get("top_n", 10))
    importance = analyzer.compute_importance()
    top = importance[:top_n]
    return ToolCallResult(
        ok=True, tool="get_concept_importance",
        raw={
            "top_concepts": [c.label for c in top],
            "importance": [
                {"label": c.label, "score": round(c.importance_score, 4),
                 "pagerank": round(c.pagerank, 4)}
                for c in top
            ],
        },
        text=f"top {len(top)} concepts by importance",
    )


@register_adapter("analyze_knowledge")
async def analyze_knowledge(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """生成完整学习路径报告（盲区 + 路径 + 健康度）。

    raw: {"detected_gap_types", "detected_gap_labels", "top_concepts",
          "path_length", "health"}
    """
    store, analyzer = _load_analyzer(ctx)
    if store.node_count == 0:
        return ToolCallResult.failure(
            "analyze_knowledge", "sidecar graph is empty", "tool_exception",
        )
    focus = args.get("focus_area", "")
    max_items = int(args.get("max_items", 15))
    result = analyzer.generate_learning_path(focus_area=focus, max_items=max_items)
    return ToolCallResult(
        ok=True, tool="analyze_knowledge",
        raw={
            "detected_gap_types": sorted({g.gap_type for g in result.gaps}),
            "detected_gap_labels": [g.label for g in result.gaps],
            "top_concepts": [item.label for item in result.path],
            "path_length": len(result.path),
            "health": result.graph_health,
        },
        text=f"learning path: {len(result.path)} items, {len(result.gaps)} gaps",
    )

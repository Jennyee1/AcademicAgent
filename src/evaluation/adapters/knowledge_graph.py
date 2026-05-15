from __future__ import annotations

"""
knowledge_graph adapter —— 封装知识图谱抽取与查询能力。

关键点（直接修复「静默 0.0」问题）：
  add_paper_to_graph 跑 KnowledgeExtractor，若 extraction_confidence==0.0
  且 raw_llm_output 不是合法 JSON（即它其实是一段异常文本，如 MiniMax 400
  "description too long"），则置 ok=False / error_category="llm_api_error"，
  而不是伪装成「成功但空」的抽取。

所有操作都在 ctx.sandbox.graph_path 上进行 —— 绝不碰真实 data/knowledge_graph.json。
"""

import json

from .base import AdapterContext, ToolCallResult, register_adapter


def _looks_like_api_error(raw_output: str) -> bool:
    """raw_llm_output 在抽取失败时存的是 str(exception)。
    若它不是合法 JSON，就认为这是一段 API 错误文本而非真实的空抽取。"""
    if not raw_output:
        return True
    text = raw_output.strip()
    try:
        json.loads(text)
        return False
    except Exception:  # noqa: BLE001
        # 进一步：尝试宽松提取 { } 块
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                json.loads(text[start:end + 1])
                return False
            except Exception:  # noqa: BLE001
                pass
        return True


@register_adapter("add_paper_to_graph")
async def add_paper_to_graph(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """从文本抽取实体/关系并写入隔离图谱。

    raw: {"nodes": [...], "edges": [...], "confidence": float,
          "node_count": int, "edge_count": int}
    """
    from src.knowledge.extractor import KnowledgeExtractor
    from src.knowledge.graph_store import KnowledgeGraphStore

    text = args.get("text", "")
    paper_title = args.get("paper_title", "")
    paper_year = args.get("paper_year", "")

    store = KnowledgeGraphStore(graph_path=ctx.sandbox.graph_path)
    extractor = KnowledgeExtractor()

    try:
        result = await extractor.extract_from_text(
            text=text, paper_title=paper_title, paper_year=paper_year,
        )
    except Exception as exc:  # noqa: BLE001 — extractor 理论上自吞异常，这里兜底
        return ToolCallResult.failure(
            "add_paper_to_graph", f"extractor raised: {exc}", "llm_api_error",
        )

    tokens_in = max(0, len(text) // 4)
    tokens_out = max(0, len(result.raw_llm_output or "") // 4)

    # —— 显式暴露 MiniMax API 报错（不伪装成空成功）——
    if result.extraction_confidence == 0.0 and not result.nodes and not result.edges:
        if _looks_like_api_error(result.raw_llm_output):
            return ToolCallResult(
                ok=False, tool="add_paper_to_graph",
                raw={"nodes": [], "edges": [], "confidence": 0.0,
                     "node_count": 0, "edge_count": 0,
                     "raw_llm_output": (result.raw_llm_output or "")[:500]},
                error=f"extraction returned 0 confidence; raw output looks like an "
                      f"API error: {(result.raw_llm_output or '')[:200]}",
                error_category="llm_api_error",
                tokens_in=tokens_in, tokens_out=tokens_out,
            )
        # 合法 JSON 但确实空 —— 归类为 empty_extraction（仍是失败，需要可见）
        return ToolCallResult(
            ok=False, tool="add_paper_to_graph",
            raw={"nodes": [], "edges": [], "confidence": 0.0,
                 "node_count": 0, "edge_count": 0},
            error="extraction produced no nodes or edges",
            error_category="empty_extraction",
            tokens_in=tokens_in, tokens_out=tokens_out,
        )

    # 写入隔离图谱
    for node in result.nodes:
        store.add_node(node)
    for edge in result.edges:
        store.add_edge(edge)
    if result.nodes or result.edges:
        store.save(ctx.sandbox.graph_path)

    return ToolCallResult(
        ok=True, tool="add_paper_to_graph",
        raw={
            "nodes": [n.to_dict() for n in result.nodes],
            "edges": [e.to_dict() for e in result.edges],
            "confidence": result.extraction_confidence,
            "node_count": result.node_count,
            "edge_count": result.edge_count,
        },
        text=f"{paper_title!r}: {result.node_count} nodes, {result.edge_count} edges, "
             f"conf={result.extraction_confidence}",
        tokens_in=tokens_in, tokens_out=tokens_out,
    )


@register_adapter("query_knowledge")
async def query_knowledge(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """在隔离图谱（通常已 seed）上做关键词检索。

    raw: {"matched_labels": [...], "matched_node_ids": [...]}
    """
    from src.knowledge.graph_store import KnowledgeGraphStore

    query = args.get("query", "")
    store = KnowledgeGraphStore(graph_path=ctx.sandbox.graph_path)
    nodes = store.search_nodes(query)
    return ToolCallResult(
        ok=True, tool="query_knowledge",
        raw={
            "matched_labels": [n.label for n in nodes],
            "matched_node_ids": [n.node_id for n in nodes],
        },
        text=f"query={query!r} -> {len(nodes)} nodes",
    )


@register_adapter("get_related_concepts")
async def get_related_concepts(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """取某概念的多跳邻居。

    raw: {"neighbors": [labels]}
    """
    from src.knowledge.graph_store import KnowledgeGraphStore

    concept = args.get("concept_name", "")
    depth = int(args.get("depth", 2))
    store = KnowledgeGraphStore(graph_path=ctx.sandbox.graph_path)
    # 先按关键词定位起点节点
    matches = store.search_nodes(concept)
    if not matches:
        return ToolCallResult(
            ok=True, tool="get_related_concepts",
            raw={"neighbors": []},
            text=f"concept {concept!r} not found in graph",
        )
    start = matches[0]
    neighbors = store.query_neighbors(start.node_id, depth=depth)
    labels = [node.label for node, _edge in neighbors]
    return ToolCallResult(
        ok=True, tool="get_related_concepts",
        raw={"neighbors": labels, "start": start.label},
        text=f"{concept!r} -> {len(labels)} related concepts",
    )


@register_adapter("get_graph_stats")
async def get_graph_stats(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """隔离图谱的统计摘要。"""
    from src.knowledge.graph_store import KnowledgeGraphStore

    store = KnowledgeGraphStore(graph_path=ctx.sandbox.graph_path)
    stats = store.get_stats()
    return ToolCallResult(
        ok=True, tool="get_graph_stats",
        raw={"stats": stats,
             "node_count": stats.get("total_nodes", 0),
             "edge_count": stats.get("total_edges", 0)},
        text=f"{stats.get('total_nodes', 0)} nodes, {stats.get('total_edges', 0)} edges",
    )

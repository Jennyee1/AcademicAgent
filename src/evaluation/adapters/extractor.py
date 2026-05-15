from __future__ import annotations

"""
extractor adapter —— KnowledgeExtractor.extract_from_text 的薄封装。

与 knowledge_graph.add_paper_to_graph 的区别：本 adapter 不经过 graph_store
的去重/合并，直接评测「纯抽取」结果。同样把 API 报错显式暴露为 llm_api_error。
"""

import asyncio

from .base import AdapterContext, ToolCallResult, register_adapter
from .knowledge_graph import _looks_like_api_error


@register_adapter("extract_from_text")
async def extract_from_text(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """纯抽取：raw = {"nodes": [...], "edges": [...], "confidence": float}。

    runtime hint 消费：
      - retry_delay_ms : 调用前 sleep N ms（critic 在 transient llm_api_error 后注入）
    """
    from src.knowledge.extractor import KnowledgeExtractor

    text = args.get("text", "")
    paper_title = args.get("paper_title", "")
    paper_year = args.get("paper_year", "")

    delay_ms = int(ctx.hints.get("retry_delay_ms", 0) or 0)
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    extractor = KnowledgeExtractor()
    try:
        result = await extractor.extract_from_text(
            text=text, paper_title=paper_title, paper_year=paper_year,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult.failure(
            "extract_from_text", f"extractor raised: {exc}", "llm_api_error",
        )

    tokens_in = max(0, len(text) // 4)
    tokens_out = max(0, len(result.raw_llm_output or "") // 4)

    if result.extraction_confidence == 0.0 and not result.nodes and not result.edges:
        if _looks_like_api_error(result.raw_llm_output):
            return ToolCallResult(
                ok=False, tool="extract_from_text",
                raw={"nodes": [], "edges": [], "confidence": 0.0},
                error=f"0 confidence; raw output looks like API error: "
                      f"{(result.raw_llm_output or '')[:200]}",
                error_category="llm_api_error",
                tokens_in=tokens_in, tokens_out=tokens_out,
            )
        return ToolCallResult(
            ok=False, tool="extract_from_text",
            raw={"nodes": [], "edges": [], "confidence": 0.0},
            error="extraction produced no nodes or edges",
            error_category="empty_extraction",
            tokens_in=tokens_in, tokens_out=tokens_out,
        )

    return ToolCallResult(
        ok=True, tool="extract_from_text",
        raw={
            "nodes": [n.to_dict() for n in result.nodes],
            "edges": [e.to_dict() for e in result.edges],
            "confidence": result.extraction_confidence,
        },
        text=f"{paper_title!r}: {result.node_count} nodes, {result.edge_count} edges",
        tokens_in=tokens_in, tokens_out=tokens_out,
    )

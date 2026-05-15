from __future__ import annotations

"""
paper_search adapter —— 封装论文检索能力。

直接走 Semantic Scholar / arXiv HTTP（与 MCP server 同源），
返回结构化论文列表供 retrieval 指标计算；timeout/429 映射到 error_category。
"""

import xml.etree.ElementTree as ET

from .base import AdapterContext, ToolCallResult, register_adapter

_S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_PAPER = "https://api.semanticscholar.org/graph/v1/paper"
_ARXIV = "https://export.arxiv.org/api/query"


def _classify_http_error(exc: Exception) -> tuple[str, str]:
    """返回 (error_category, error_text)。httpx 在函数内懒加载，故按类名判别。"""
    import httpx  # 懒加载：缺 httpx 时不应拖垮其他离线 adapter
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", f"request timed out: {exc}"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return "rate_limit", "HTTP 429 rate limited"
        return "network", f"HTTP {code}: {exc}"
    if isinstance(exc, httpx.HTTPError):
        return "network", f"network error: {exc}"
    return "tool_exception", str(exc)


@register_adapter("search_papers")
async def search_papers(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """关键词检索论文（Semantic Scholar）。

    raw: {"retrieved": [titles], "retrieved_ids": [paper_ids], "papers": [...]}
    """
    if ctx.offline:
        return ToolCallResult.failure(
            "search_papers", "offline mode: external API skipped", "network"
        )
    import httpx
    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                _S2_SEARCH,
                params={"query": query, "limit": limit,
                        "fields": "paperId,title,year,authors,abstract"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        cat, text = _classify_http_error(exc)
        return ToolCallResult.failure("search_papers", text, cat)

    papers = data.get("data", []) or []
    titles = [p.get("title", "") for p in papers]
    ids = [p.get("paperId", "") for p in papers]
    return ToolCallResult(
        ok=True, tool="search_papers",
        raw={"retrieved": titles, "retrieved_ids": ids, "papers": papers},
        text=f"query={query!r} -> {len(papers)} papers",
    )


@register_adapter("get_paper_details")
async def get_paper_details(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """获取单篇论文详情。"""
    if ctx.offline:
        return ToolCallResult.failure(
            "get_paper_details", "offline mode: external API skipped", "network"
        )
    import httpx
    paper_id = args.get("paper_id", "")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_S2_PAPER}/{paper_id}",
                params={"fields": "paperId,title,year,abstract,authors,externalIds,"
                                  "citationCount,referenceCount"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        cat, text = _classify_http_error(exc)
        return ToolCallResult.failure("get_paper_details", text, cat)

    return ToolCallResult(
        ok=True, tool="get_paper_details",
        raw={"paper": data, "title": data.get("title", ""),
             "paper_id": data.get("paperId", "")},
        text=f"paper {paper_id} -> {data.get('title', '')!r}",
    )


@register_adapter("get_related_papers")
async def get_related_papers(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """获取引用/被引论文。"""
    if ctx.offline:
        return ToolCallResult.failure(
            "get_related_papers", "offline mode: external API skipped", "network"
        )
    import httpx
    paper_id = args.get("paper_id", "")
    relation = args.get("relation", "references")
    limit = int(args.get("limit", 5))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_S2_PAPER}/{paper_id}/{relation}",
                params={"fields": "paperId,title,year", "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        cat, text = _classify_http_error(exc)
        return ToolCallResult.failure("get_related_papers", text, cat)

    items = data.get("data", []) or []
    related = [it.get("citedPaper") or it.get("citingPaper") or {} for it in items]
    titles = [p.get("title", "") for p in related]
    ids = [p.get("paperId", "") for p in related]
    return ToolCallResult(
        ok=True, tool="get_related_papers",
        raw={"retrieved": titles, "retrieved_ids": ids, "relation": relation},
        text=f"{relation} of {paper_id} -> {len(related)} papers",
    )


@register_adapter("search_arxiv")
async def search_arxiv(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """检索 arXiv 预印本（Atom XML）。"""
    if ctx.offline:
        return ToolCallResult.failure(
            "search_arxiv", "offline mode: external API skipped", "network"
        )
    import httpx
    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                _ARXIV,
                params={"search_query": f"all:{query}", "max_results": limit,
                        "sortBy": "relevance"},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception as exc:  # noqa: BLE001
        cat, text = _classify_http_error(exc)
        return ToolCallResult.failure("search_arxiv", text, cat)

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    titles, ids = [], []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        id_el = entry.find("atom:id", ns)
        titles.append((title_el.text or "").strip() if title_el is not None else "")
        ids.append((id_el.text or "").strip() if id_el is not None else "")
    return ToolCallResult(
        ok=True, tool="search_arxiv",
        raw={"retrieved": titles, "retrieved_ids": ids},
        text=f"arxiv query={query!r} -> {len(titles)} papers",
    )

import sys
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

"""
ScholarMind - 论文搜索 MCP Server
=================================

功能：
  1. search_papers       — 关键词搜索论文（Semantic Scholar API）
  2. get_paper_details    — 获取单篇论文详细信息
  3. get_related_papers   — 获取引用/被引论文
  4. search_arxiv         — 搜索 arXiv 预印本

技术要点（学习笔记）：
  - 这是一个 MCP Server，作为独立进程运行
  - Claude Code 通过 stdio 与它通信
  - @mcp.tool() 装饰器注册工具函数
  - 函数的 docstring 决定了 Claude 何时调用这个工具
  - type hints 决定了参数的 JSON Schema

工程设计原则：
  1. 所有论文数据来自真实 API，绝不由 LLM 生成 → 防止幻觉
  2. 每篇论文包含可验证的唯一标识（Paper ID / DOI / arXiv ID）
  3. 错误信息返回人类可读文本，让 Claude 能据此调整策略
  4. 请求限流 + 超时控制 → 防止天价账单和无限阻塞
"""

import os
import json
import asyncio
import logging
from typing import Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ============================================================
# 环境加载与日志配置
# ============================================================
load_dotenv()  # 从 .env 文件加载 API Key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ScholarMind.PaperSearch")

# ============================================================
# MCP Server 初始化
# ============================================================
mcp = FastMCP(
    "ScholarMind-PaperSearch",
    instructions=(
        "学术论文搜索与检索服务。"
        "通过 Semantic Scholar API 和 arXiv API 搜索真实论文，"
        "确保每篇论文都可以通过 DOI/arXiv ID 验证真实性。"
    ),
)

# ============================================================
# 常量配置
# ============================================================
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
# 【踩坑记录】arXiv API 已从 HTTP 迁移到 HTTPS
ARXIV_API_BASE = "https://export.arxiv.org/api/query"

# 从环境变量读取 API Key（可选，有 Key 限额更大）
# 【踩坑记录 #2】.env.example 中的中文占位符 "你的key" 会被 load_dotenv 原样加载，
# httpx 将其作为 HTTP header 发送时尝试 ASCII 编码 → UnicodeEncodeError。
# 防御策略：验证 Key 必须是纯 ASCII 且不是已知占位符，否则视为未配置。
_raw_ss_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
SS_API_KEY = None
if _raw_ss_key:
    try:
        _raw_ss_key.encode("ascii")  # HTTP header 必须是 ASCII
        # 排除已知的占位符值
        if _raw_ss_key not in ("你的key", "your_key_here", ""):
            SS_API_KEY = _raw_ss_key
            logger.info("Semantic Scholar API Key 已配置 ✓")
        else:
            logger.info("Semantic Scholar API Key 为占位符，将使用无 Key 模式（限流更严格）")
    except UnicodeEncodeError:
        logger.warning(
            "Semantic Scholar API Key 包含非 ASCII 字符（可能是 .env 占位符），"
            "已自动忽略。请在 .env 中填入真实 Key 或留空。"
        )

# 请求配置
REQUEST_TIMEOUT = 30.0  # 秒
MAX_RESULTS_PER_SEARCH = 10  # 单次搜索最大返回数

# 重试配置
# 【工程思考】Exponential Backoff 是外部 API 集成的标准模式
# 初始等 1 秒，然后 2 秒、4 秒...指数增长
# 这样既能快速重试偶发错误，又不会在持续限流时频繁骚扰 API
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # 秒

# ============================================================
# 主动限速器 (Proactive Rate Limiter)
#
# 【踩坑记录 #3】Semantic Scholar 无 Key 模式限额仅 1 req/s。
# 如果只靠被动的 Exponential Backoff（429 触发后才等待），
# 用户连续调用两次 MCP 工具就会立即触发限流。
#
# 解决方案：主动限速 — 在每次请求前检查距上次请求的时间间隔，
# 不足则自动 sleep。这比被动 backoff 更友好：
#   - 被动策略：请求 → 429 → 等 1s → 请求 → 429 → 等 2s（用户感知到报错）
#   - 主动策略：请求 → 等 1.5s → 请求 → 成功（用户无感知）
# ============================================================
import time

# 无 Key: 限额 1 req/s → 保守设 1.5s 间隔
# 有 Key: 限额 ~10 req/s → 设 0.2s 间隔
MIN_REQUEST_INTERVAL = 0.2 if SS_API_KEY else 1.5
_last_request_time: float = 0.0  # 上次请求的时间戳


async def _rate_limit_wait():
    """主动限速：确保两次请求间隔不低于 MIN_REQUEST_INTERVAL"""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        wait = MIN_REQUEST_INTERVAL - elapsed
        logger.debug(f"主动限速: 等待 {wait:.1f}s")
        await asyncio.sleep(wait)
    _last_request_time = time.monotonic()


# ============================================================
# HTTP 请求工具函数
#
# 【工程思考】为什么封装统一请求函数？
# 1. 集中处理 API Key 注入
# 2. 统一超时和错误处理
# 3. 主动限速 + 被动重试双重保护
# ============================================================
async def _semantic_scholar_request(
    endpoint: str, params: dict | None = None
) -> dict:
    """
    向 Semantic Scholar API 发送请求（带主动限速 + Exponential Backoff 重试）

    双重限流保护：
    1. 主动：请求前自动等待至 MIN_REQUEST_INTERVAL（无感知）
    2. 被动：遇到 429 时 Exponential Backoff 重试（1s → 2s → 4s）

    Raises:
        httpx.HTTPStatusError: 重试耗尽后仍失败
        httpx.TimeoutException: 请求超时
    """
    # 主动限速（在发请求之前等待，从源头避免 429）
    await _rate_limit_wait()

    url = f"{SEMANTIC_SCHOLAR_BASE}/{endpoint}"
    headers = {}
    if SS_API_KEY:
        headers["x-api-key"] = SS_API_KEY

    last_exception = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            last_exception = e
            if e.response.status_code == 429 and attempt < MAX_RETRIES:
                wait_time = INITIAL_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"API 限流 (429), 等待 {wait_time}s 后重试 "
                    f"(第 {attempt + 1}/{MAX_RETRIES} 次)"
                )
                await asyncio.sleep(wait_time)
                _last_request_time = time.monotonic()  # 重试后刷新时间戳
                continue
            raise

    raise last_exception  # type: ignore


def _format_authors(authors: list[dict], max_display: int = 3) -> str:
    """格式化作者列表，超过 max_display 人时显示 et al."""
    names = [a.get("name", "Unknown") for a in authors[:max_display]]
    result = ", ".join(names)
    if len(authors) > max_display:
        result += " et al."
    return result


def _truncate(text: str | None, max_len: int = 300) -> str:
    """安全截断文本，处理 None"""
    if not text:
        return "（无）"
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ============================================================
# MCP 工具定义
#
# 【工程思考】工具设计三原则：
# 1. docstring 越详细越好 → Claude 靠它决定何时调用
# 2. 返回格式化 markdown → Claude 能直接展示给用户
# 3. 异常返回友好提示 → Claude 能据此调整策略（如换关键词）
# ============================================================


@mcp.tool()
async def search_papers(
    query: str,
    limit: int = 5,
    year_range: str | None = None,
    fields_of_study: str | None = None,
) -> str:
    """
    通过 Semantic Scholar API 搜索学术论文。搜索结果来自真实的学术数据库，
    每篇论文都有唯一的 Paper ID 可以验证。

    适合使用的场景：
    - 用户说"帮我找关于xxx的论文"
    - 用户说"xxx领域有哪些最新研究"
    - 进行文献综述时需要收集相关论文
    - 验证某个研究方向是否有已有工作

    不适合使用的场景：
    - 用户已经提供了论文 PDF，不需要再搜索
    - 用户在讨论已知论文的细节

    Args:
        query: 搜索关键词。使用英文效果最好。
               例如 "ISAC channel estimation" 或 "RIS aided sensing MIMO"
        limit: 返回论文数量，1-10 之间，默认 5
        year_range: 可选的发表年份过滤，格式 "2020-2025" 或 "2024-"
        fields_of_study: 可选的学科过滤，如 "Computer Science"、"Engineering"

    Returns:
        格式化的论文搜索结果（Markdown），每篇包含标题、作者、年份、引用数、
        Paper ID 和摘要摘录。
    """
    logger.info(f"搜索论文: query='{query}', limit={limit}, year='{year_range}'")

    # 参数校验
    limit = max(1, min(limit, MAX_RESULTS_PER_SEARCH))

    params = {
        "query": query,
        "limit": limit,
        "fields": "title,authors,year,citationCount,abstract,url,venue,externalIds",
    }
    if year_range:
        params["year"] = year_range
    if fields_of_study:
        params["fieldsOfStudy"] = fields_of_study

    try:
        data = await _semantic_scholar_request("paper/search", params)
        papers = data.get("data", [])

        if not papers:
            return (
                f"## 未找到结果\n\n"
                f"关键词 \"{query}\" 未找到相关论文。\n"
                f"**建议**：\n"
                f"- 尝试使用更通用的英文关键词\n"
                f"- 减少过滤条件（如去掉年份限制）\n"
                f"- 尝试同义词（如 'sensing' → 'radar'）"
            )

        # 格式化结果
        results = []
        for i, paper in enumerate(papers, 1):
            authors = _format_authors(paper.get("authors", []))
            abstract = _truncate(paper.get("abstract"), 250)

            # 提取可验证的外部 ID
            ext_ids = paper.get("externalIds") or {}
            doi = ext_ids.get("DOI", "")
            arxiv_id = ext_ids.get("ArXiv", "")
            paper_id = paper.get("paperId", "N/A")

            # 构建验证链接
            verify_links = []
            if doi:
                verify_links.append(f"[DOI](https://doi.org/{doi})")
            if arxiv_id:
                verify_links.append(f"[arXiv](https://arxiv.org/abs/{arxiv_id})")
            verify_str = " | ".join(verify_links) if verify_links else "无外部链接"

            result = (
                f"### [{i}] {paper.get('title', 'N/A')}\n"
                f"- **作者**: {authors}\n"
                f"- **年份**: {paper.get('year', 'N/A')} "
                f"| **期刊/会议**: {paper.get('venue', 'N/A') or '未知'}\n"
                f"- **引用数**: {paper.get('citationCount', 0)}\n"
                f"- **Paper ID**: `{paper_id}`\n"
                f"- **验证链接**: {verify_str}\n"
                f"- **摘要**: {abstract}"
            )
            results.append(result)

        total = data.get("total", len(papers))
        header = (
            f"## 🔍 搜索结果: \"{query}\"\n\n"
            f"共找到约 {total} 篇相关论文，展示前 {len(papers)} 篇：\n"
        )

        logger.info(f"搜索完成: 返回 {len(papers)} 篇论文 (共约 {total} 篇)")
        return header + "\n\n---\n\n".join(results)

    except httpx.TimeoutException:
        logger.warning(f"搜索超时: query='{query}'")
        return (
            "⚠️ **搜索超时**\n\n"
            "Semantic Scholar API 响应超时（30秒）。\n"
            "可能原因：网络不稳定或 API 服务繁忙。\n"
            "建议稍后重试。"
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error(f"API 错误: status={status}, query='{query}'")
        if status == 429:
            return (
                "⚠️ **请求频率过高**\n\n"
                "Semantic Scholar API 限流。请等待约 1 分钟后重试。\n"
                "提示：设置 SEMANTIC_SCHOLAR_API_KEY 可提高限额。"
            )
        return f"⚠️ **API 错误** (HTTP {status})\n\n请稍后重试。"
    except Exception as e:
        logger.exception(f"未知错误: {e}")
        return f"⚠️ **未知错误**: {type(e).__name__}: {e}"


@mcp.tool()
async def get_paper_details(paper_id: str) -> str:
    """
    获取一篇论文的完整详细信息。需要先通过 search_papers 获取 Paper ID。

    适合使用的场景：
    - 用户想深入了解搜索结果中的某篇论文
    - 需要获取论文的完整摘要、PDF 链接或引用信息

    Args:
        paper_id: Semantic Scholar 的论文 ID（从 search_papers 结果中获取的 Paper ID）

    Returns:
        论文的完整详细信息，包括摘要、TL;DR、引用统计、PDF 链接和外部 ID。
    """
    logger.info(f"获取论文详情: paper_id='{paper_id}'")

    fields = (
        "title,authors,year,abstract,citationCount,referenceCount,"
        "url,venue,publicationDate,fieldsOfStudy,tldr,"
        "openAccessPdf,externalIds"
    )

    try:
        paper = await _semantic_scholar_request(
            f"paper/{paper_id}", {"fields": fields}
        )

        authors = _format_authors(paper.get("authors", []), max_display=10)

        # TL;DR (Semantic Scholar 的 AI 生成摘要)
        tldr_obj = paper.get("tldr")
        tldr_text = tldr_obj.get("text", "无自动摘要") if tldr_obj else "无自动摘要"

        # PDF 链接
        pdf_obj = paper.get("openAccessPdf")
        pdf_url = pdf_obj.get("url", "无公开 PDF") if pdf_obj else "无公开 PDF"

        # 外部标识（用于验证论文真实性）
        ext_ids = paper.get("externalIds") or {}
        doi = ext_ids.get("DOI", "N/A")
        arxiv_id = ext_ids.get("ArXiv", "N/A")

        # 研究领域
        fields_list = paper.get("fieldsOfStudy") or []
        fields_str = ", ".join(fields_list) if fields_list else "未分类"

        result = (
            f"## 📄 {paper.get('title', 'N/A')}\n\n"
            f"| 属性 | 值 |\n"
            f"|:---|:---|\n"
            f"| **作者** | {authors} |\n"
            f"| **年份** | {paper.get('year', 'N/A')} |\n"
            f"| **发表于** | {paper.get('venue', 'N/A') or '未知'} |\n"
            f"| **发表日期** | {paper.get('publicationDate', 'N/A')} |\n"
            f"| **引用数** | {paper.get('citationCount', 0)} |\n"
            f"| **参考文献数** | {paper.get('referenceCount', 0)} |\n"
            f"| **研究领域** | {fields_str} |\n"
            f"| **DOI** | {doi} |\n"
            f"| **arXiv ID** | {arxiv_id} |\n"
            f"| **PDF 链接** | {pdf_url} |\n"
            f"| **Semantic Scholar** | {paper.get('url', 'N/A')} |\n\n"
            f"### TL;DR\n{tldr_text}\n\n"
            f"### 完整摘要\n{paper.get('abstract', '无摘要')}"
        )

        logger.info(f"获取详情成功: '{paper.get('title', '')[:50]}'")
        return result

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"⚠️ **论文未找到**\n\nPaper ID `{paper_id}` 不存在。请检查 ID 是否正确。"
        return f"⚠️ **API 错误** (HTTP {e.response.status_code})"
    except Exception as e:
        logger.exception(f"获取详情失败: {e}")
        return f"⚠️ **获取失败**: {type(e).__name__}: {e}"


@mcp.tool()
async def get_related_papers(
    paper_id: str,
    relation: str = "references",
    limit: int = 5,
) -> str:
    """
    获取与指定论文相关的论文列表（引用或被引用关系）。

    适合使用的场景：
    - 用户想扩展阅读某篇论文的相关工作
    - 追溯某篇论文的理论基础（references）
    - 查看某篇论文的影响力和后续发展（citations）

    Args:
        paper_id: 源论文的 Semantic Scholar Paper ID
        relation: 关系类型
                  - "references": 该论文引用了谁（向前追溯，了解理论基础）
                  - "citations": 谁引用了该论文（向后追踪，了解后续发展）
        limit: 返回数量，1-10，默认 5

    Returns:
        相关论文列表，按引用数降序排列。
    """
    logger.info(
        f"获取相关论文: paper_id='{paper_id}', relation='{relation}', limit={limit}"
    )

    if relation not in ("references", "citations"):
        return "⚠️ relation 参数必须是 'references' 或 'citations'"

    limit = max(1, min(limit, MAX_RESULTS_PER_SEARCH))
    endpoint = f"paper/{paper_id}/{relation}"
    params = {
        "fields": "title,authors,year,citationCount,abstract",
        "limit": limit,
    }

    try:
        data = await _semantic_scholar_request(endpoint, params)
        items = data.get("data", [])

        if not items:
            relation_cn = "引用的论文" if relation == "references" else "引用它的论文"
            return f"未找到该论文{relation_cn}。"

        # 提取论文对象（references 和 citations 的数据结构略有不同）
        key = "citedPaper" if relation == "references" else "citingPaper"

        results = []
        for i, item in enumerate(items, 1):
            paper = item.get(key, {})
            if not paper or not paper.get("title"):
                continue

            authors = _format_authors(paper.get("authors", []))
            abstract = _truncate(paper.get("abstract"), 150)

            result = (
                f"**[{i}]** {paper.get('title', 'N/A')}\n"
                f"   - 作者: {authors} | 年份: {paper.get('year', 'N/A')} "
                f"| 引用数: {paper.get('citationCount', 0)}\n"
                f"   - 摘要: {abstract}"
            )
            results.append(result)

        relation_cn = "参考文献（该论文引用的）" if relation == "references" else "后续引用（引用该论文的）"
        header = f"## 📚 {relation_cn}\n\n"

        logger.info(f"获取相关论文完成: 返回 {len(results)} 篇")
        return header + "\n\n".join(results)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"⚠️ Paper ID `{paper_id}` 不存在。"
        return f"⚠️ API 错误 (HTTP {e.response.status_code})"
    except Exception as e:
        logger.exception(f"获取相关论文失败: {e}")
        return f"⚠️ **获取失败**: {type(e).__name__}: {e}"


@mcp.tool()
async def search_arxiv(
    query: str,
    limit: int = 5,
    sort_by: str = "relevance",
) -> str:
    """
    通过 arXiv API 搜索预印本论文。arXiv 是物理、数学、计算机科学等领域的
    开放获取预印本平台，很多最新研究会先在这里发布。

    与 search_papers 的区别：
    - arXiv 偏向最新的预印本（可能尚未正式发表）
    - search_papers（Semantic Scholar）覆盖更广、引用数据更全
    - 建议两者结合使用以获得全面的文献覆盖

    Args:
        query: 搜索关键词（英文），例如 "integrated sensing communication"
        limit: 返回数量，1-10，默认 5
        sort_by: 排序方式
                 - "relevance": 按相关性（默认）
                 - "lastUpdatedDate": 按最近更新
                 - "submittedDate": 按提交时间

    Returns:
        arXiv 论文列表，每篇包含标题、作者、arXiv ID 和摘要。
    """
    logger.info(f"arXiv 搜索: query='{query}', limit={limit}")

    limit = max(1, min(limit, MAX_RESULTS_PER_SEARCH))
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(ARXIV_API_BASE, params=params)
            response.raise_for_status()
            xml_text = response.text

        # 简易 XML 解析（arXiv 返回 Atom XML）
        # 【工程思考】为什么不用 lxml？
        # 减少依赖。arXiv 的 XML 结构简单，用标准库 xml 足够。
        # 如果后续需要复杂解析，再引入 feedparser 或 lxml。
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        entries = root.findall("atom:entry", ns)

        if not entries:
            return f"## arXiv 搜索未找到结果\n\n关键词: \"{query}\""

        results = []
        for i, entry in enumerate(entries, 1):
            title = entry.findtext("atom:title", "N/A", ns).strip().replace("\n", " ")

            # 提取作者
            author_elems = entry.findall("atom:author/atom:name", ns)
            authors = ", ".join(a.text for a in author_elems[:3])
            if len(author_elems) > 3:
                authors += " et al."

            # 提取 arXiv ID
            entry_id = entry.findtext("atom:id", "", ns)
            arxiv_id = entry_id.split("/abs/")[-1] if "/abs/" in entry_id else entry_id

            # 发布日期
            published = entry.findtext("atom:published", "N/A", ns)[:10]

            # 摘要
            summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
            summary = _truncate(summary, 250)

            # PDF 链接
            pdf_link = ""
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    pdf_link = link.get("href", "")
                    break

            result = (
                f"### [{i}] {title}\n"
                f"- **作者**: {authors}\n"
                f"- **发布日期**: {published}\n"
                f"- **arXiv ID**: `{arxiv_id}`\n"
                f"- **链接**: [arXiv]({entry_id})"
                f"{f' | [PDF]({pdf_link})' if pdf_link else ''}\n"
                f"- **摘要**: {summary}"
            )
            results.append(result)

        header = f"## 📄 arXiv 搜索结果: \"{query}\"\n\n展示 {len(results)} 篇：\n"

        logger.info(f"arXiv 搜索完成: 返回 {len(results)} 篇")
        return header + "\n\n---\n\n".join(results)

    except httpx.TimeoutException:
        return "⚠️ **arXiv 搜索超时**，请稍后重试。"
    except Exception as e:
        logger.exception(f"arXiv 搜索失败: {e}")
        return f"⚠️ **arXiv 搜索失败**: {type(e).__name__}: {e}"


# ============================================================
# 启动入口
# ============================================================
if __name__ == "__main__":
    logger.info("ScholarMind Paper Search MCP Server 启动中...")
    mcp.run()

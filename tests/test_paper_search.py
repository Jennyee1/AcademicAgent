"""
论文搜索 MCP Server 测试
========================

测试策略:
- 真实 API 调用测试（需要网络）→ 标记为 integration
- 格式和错误处理测试 → 可离线运行

运行方式:
  pytest tests/test_paper_search.py -v
  pytest tests/test_paper_search.py -v -m integration  # 仅跑联网测试

【踩坑记录 #3】Semantic Scholar 无 API Key 模式限流严格（1 req/s）
  - 多个测试连续发请求会触发 429 Rate Limit
  - 解决方案：
    1. 测试间加 asyncio.sleep() 冷却（RATE_LIMIT_DELAY）
    2. 429 响应视为"基础设施限制"而非代码 bug，用 pytest.skip 标记
    3. 使用 conftest fixture 统一管理冷却时间
  - 根因：无 API Key 时 Semantic Scholar 限额仅 1 req/s，
    而 pytest 连续执行 5 个测试 → 必然超限
"""

import pytest
import asyncio

# Guard: paper_search.py depends on httpx
httpx = pytest.importorskip("httpx", reason="httpx not installed")

# Import after guard
from src.mcp_servers.paper_search import (
    search_papers,
    get_paper_details,
    get_related_papers,
    search_arxiv,
    _format_authors,
    _truncate,
)

# ============================================================
# 限流控制常量
# ============================================================
# 【工程思考】为什么需要 RATE_LIMIT_DELAY？
# Semantic Scholar 无 Key 模式限额 1 req/s，而 Exponential Backoff
# 重试本身要消耗 1+2+4=7 秒。在测试之间加间隔，从源头减少 429。
RATE_LIMIT_DELAY = 3.0  # 秒，测试间冷却时间

# 429 限流时的断言错误提示（用于 skip 标记）
RATE_LIMIT_HINT = "⚠️ Semantic Scholar API 限流 (429)"


def _is_rate_limited(result: str) -> bool:
    """判断返回结果是否是 429 限流响应"""
    return "请求频率过高" in result or "API 错误" in result and "429" in result


# ============================================================
# 单元测试（离线）
# ============================================================

class TestHelpers:
    """测试辅助函数"""

    def test_format_authors_single(self):
        authors = [{"name": "Alice"}]
        assert _format_authors(authors) == "Alice"

    def test_format_authors_multiple(self):
        authors = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        assert _format_authors(authors) == "A, B, C"

    def test_format_authors_truncated(self):
        authors = [{"name": f"Author{i}"} for i in range(5)]
        result = _format_authors(authors, max_display=3)
        assert "et al." in result
        # 只展示前3个
        assert "Author0" in result
        assert "Author2" in result
        assert "Author3" not in result

    def test_format_authors_empty(self):
        assert _format_authors([]) == ""

    def test_truncate_short(self):
        assert _truncate("hello", 10) == "hello"

    def test_truncate_long(self):
        result = _truncate("a" * 500, 100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_truncate_none(self):
        assert _truncate(None) == "（无）"

    def test_truncate_empty(self):
        assert _truncate("") == "（无）"


# ============================================================
# 集成测试（需要网络）
#
# 【工程思考】集成测试的 3 层容错策略：
# 1. 测试间 sleep(RATE_LIMIT_DELAY) → 预防 429
# 2. 429 响应 → pytest.skip（基础设施问题，非代码 bug）
# 3. 超时 → pytest.skip（网络问题，非代码 bug）
# ============================================================

@pytest.mark.integration
class TestSearchPapersIntegration:
    """论文搜索集成测试 - 需要网络连接"""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """基本搜索功能"""
        result = await search_papers("OFDM channel estimation", limit=3)
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        assert "搜索结果" in result
        assert "[1]" in result  # 至少有第一条结果

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self):
        """年份过滤"""
        await asyncio.sleep(RATE_LIMIT_DELAY)
        result = await search_papers("ISAC", limit=3, year_range="2023-2025")
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        assert "搜索结果" in result

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """无结果处理"""
        await asyncio.sleep(RATE_LIMIT_DELAY)
        result = await search_papers(
            "xyznonexistentqueryxyz123456", limit=1
        )
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        assert "未找到" in result or "搜索结果" in result

    @pytest.mark.asyncio
    async def test_search_contains_paper_id(self):
        """搜索结果包含可验证的 Paper ID"""
        await asyncio.sleep(RATE_LIMIT_DELAY)
        result = await search_papers("deep learning", limit=2)
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        assert "Paper ID" in result

    @pytest.mark.asyncio
    async def test_search_contains_verification_links(self):
        """搜索结果包含验证链接（DOI 或 arXiv）"""
        await asyncio.sleep(RATE_LIMIT_DELAY)
        result = await search_papers("transformer attention", limit=3)
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        # 大多数论文应有 DOI 或 arXiv 链接
        assert "DOI" in result or "arXiv" in result or "验证链接" in result


@pytest.mark.integration
class TestArxivSearchIntegration:
    """arXiv 搜索集成测试"""

    @pytest.mark.asyncio
    async def test_arxiv_search_returns_results(self):
        """arXiv 基本搜索"""
        result = await search_arxiv("integrated sensing communication", limit=3)
        assert "arXiv" in result
        assert "[1]" in result

    @pytest.mark.asyncio
    async def test_arxiv_contains_arxiv_id(self):
        """arXiv 搜索结果包含 arXiv ID"""
        result = await search_arxiv("MIMO beamforming", limit=2)
        assert "arXiv ID" in result


@pytest.mark.integration
class TestPaperDetailsIntegration:
    """论文详情集成测试"""

    @pytest.mark.asyncio
    async def test_get_details_valid_id(self):
        """获取有效论文的详情"""
        await asyncio.sleep(RATE_LIMIT_DELAY)
        # "Attention Is All You Need" 的 Semantic Scholar ID
        result = await get_paper_details("204e3073870fae3d05bcbc2f6a8e263d9b72e776")
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        assert "Attention" in result
        assert "DOI" in result

    @pytest.mark.asyncio
    async def test_get_details_invalid_id(self):
        """获取无效 ID 应返回友好错误"""
        await asyncio.sleep(RATE_LIMIT_DELAY)
        result = await get_paper_details("invalid_id_12345")
        if _is_rate_limited(result):
            pytest.skip(RATE_LIMIT_HINT)
        assert "⚠️" in result or "错误" in result or "未找到" in result

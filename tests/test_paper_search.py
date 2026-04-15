"""
论文搜索 MCP Server 测试
========================

测试策略:
- 真实 API 调用测试（需要网络）→ 标记为 integration
- 格式和错误处理测试 → 可离线运行

运行方式:
  pytest tests/test_paper_search.py -v
  pytest tests/test_paper_search.py -v -m integration  # 仅跑联网测试
"""

import pytest
import asyncio

# 导入被测函数
# 注意: MCP tool 函数可以直接 import 调用
from src.mcp_servers.paper_search import (
    search_papers,
    get_paper_details,
    get_related_papers,
    search_arxiv,
    _format_authors,
    _truncate,
)


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
# ============================================================

@pytest.mark.integration
class TestSearchPapersIntegration:
    """论文搜索集成测试 - 需要网络连接"""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """基本搜索功能"""
        result = await search_papers("OFDM channel estimation", limit=3)
        assert "搜索结果" in result
        assert "[1]" in result  # 至少有第一条结果

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self):
        """年份过滤"""
        result = await search_papers("ISAC", limit=3, year_range="2023-2025")
        assert "搜索结果" in result

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """无结果处理"""
        result = await search_papers(
            "xyznonexistentqueryxyz123456", limit=1
        )
        assert "未找到" in result or "搜索结果" in result

    @pytest.mark.asyncio
    async def test_search_contains_paper_id(self):
        """搜索结果包含可验证的 Paper ID"""
        result = await search_papers("deep learning", limit=2)
        assert "Paper ID" in result

    @pytest.mark.asyncio
    async def test_search_contains_verification_links(self):
        """搜索结果包含验证链接（DOI 或 arXiv）"""
        result = await search_papers("transformer attention", limit=3)
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
        # "Attention Is All You Need" 的 Semantic Scholar ID
        result = await get_paper_details("204e3073870fae3d05bcbc2f6a8e263d9b72e776")
        assert "Attention" in result
        assert "DOI" in result

    @pytest.mark.asyncio
    async def test_get_details_invalid_id(self):
        """获取无效 ID 应返回友好错误"""
        result = await get_paper_details("invalid_id_12345")
        assert "⚠️" in result or "错误" in result or "未找到" in result

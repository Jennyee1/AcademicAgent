"""
多模态分析模块 + 论文结构解析器 测试
=====================================

测试策略:
- FigureType / FigureAnalysisResult 数据类: 离线
- PaperStructureParser: 离线（纯文本操作）
- _extract_json: 离线（核心鲁棒性测试）
- FigureAnalyzer.analyze: 需要 API Key → integration

Usage:
  pytest tests/test_multimodal.py -v
  pytest tests/test_multimodal.py -v -m integration  (with API)
"""

import pytest

# Guard: multimodal.py depends on anthropic SDK
anthropic = pytest.importorskip("anthropic", reason="anthropic SDK not installed")

from src.core.multimodal import (
    FigureType,
    FigureAnalysisResult,
    FigureAnalyzer,
    PaperStructureParser,
)


class TestFigureType:
    """图表类型枚举测试"""

    def test_all_types_exist(self):
        assert FigureType.BLOCK_DIAGRAM == "block_diagram"
        assert FigureType.PERFORMANCE_CURVE == "performance_curve"
        assert FigureType.TABLE == "table"
        assert FigureType.EQUATION == "equation"
        assert FigureType.UNKNOWN == "unknown"

    def test_from_string(self):
        assert FigureType("block_diagram") == FigureType.BLOCK_DIAGRAM
        assert FigureType("table") == FigureType.TABLE


class TestFigureAnalysisResult:
    """分析结果数据类测试"""

    def test_to_markdown(self):
        result = FigureAnalysisResult(
            figure_type=FigureType.BLOCK_DIAGRAM,
            description="OFDM transceiver block diagram",
            key_findings=["Uses 64-QAM modulation", "CP length is 16"],
            entities=[
                {"name": "OFDM Modulator", "type": "module"},
                {"name": "Channel Estimator", "type": "module"},
            ],
        )
        md = result.to_markdown()
        assert "block_diagram" in md
        assert "OFDM transceiver" in md
        assert "64-QAM" in md
        assert "Channel Estimator" in md

    def test_empty_result(self):
        result = FigureAnalysisResult(
            figure_type=FigureType.UNKNOWN,
            description="",
            key_findings=[],
            entities=[],
        )
        md = result.to_markdown()
        assert "（无）" in md


class TestExtractJSON:
    """JSON 提取鲁棒性测试 - 核心防 Silent Regression"""

    def setup_method(self):
        self.analyzer = FigureAnalyzer()

    def test_pure_json(self):
        text = '{"figure_type": "table", "description": "Results"}'
        result = self.analyzer._extract_json(text)
        assert result["figure_type"] == "table"

    def test_json_in_code_block(self):
        text = 'Here is the result:\n```json\n{"type": "ok"}\n```'
        result = self.analyzer._extract_json(text)
        assert result["type"] == "ok"

    def test_json_with_surrounding_text(self):
        text = 'I found: {"answer": 42} and more text'
        result = self.analyzer._extract_json(text)
        assert result["answer"] == 42

    def test_invalid_json_returns_empty(self):
        text = "This is not JSON at all"
        result = self.analyzer._extract_json(text)
        assert result == {}

    def test_nested_json(self):
        text = '{"entities": [{"name": "A", "type": "B"}], "count": 1}'
        result = self.analyzer._extract_json(text)
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "A"


class TestPaperStructureParser:
    """论文结构解析测试"""

    def setup_method(self):
        self.parser = PaperStructureParser()

    def test_basic_sections(self):
        text = """
Abstract
This paper presents a novel approach...

1. Introduction
In recent years, ISAC has gained attention...

3. Proposed Method
We propose a deep learning based...

4. Experiments
We evaluate on two datasets...

5. Conclusion
In this paper, we proposed...

References
[1] Zhang et al...
"""
        sections = self.parser.parse_sections(text)
        assert "abstract" in sections
        assert "introduction" in sections
        assert "method" in sections
        assert "experiments" in sections
        assert "conclusion" in sections

    def test_abstract_content(self):
        text = "Abstract\nThis is the abstract content.\n\n1. Introduction\nIntro text."
        sections = self.parser.parse_sections(text)
        assert "abstract content" in sections["abstract"]

    def test_no_sections(self):
        text = "Just some random text without section headers"
        sections = self.parser.parse_sections(text)
        assert "preamble" in sections

    def test_section_summary(self):
        sections = {"abstract": "word " * 50, "method": "word " * 100}
        summary = self.parser.get_section_summary(sections)
        assert "abstract" in summary
        assert "method" in summary

    def test_roman_numeral_sections(self):
        """通信领域论文常用数字编号"""
        text = """
Abstract
Test abstract.

I. Introduction
Intro content.

II. System Model
Model content.

III. Proposed Algorithm
Algorithm content.

IV. Simulation Results
Results content.

V. Conclusion
Conclusion content.
"""
        sections = self.parser.parse_sections(text)
        # Should identify at least abstract and conclusion
        assert "abstract" in sections
        assert "conclusion" in sections

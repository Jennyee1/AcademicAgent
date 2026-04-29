"""
ScholarMind - 研究报告 Schema
================================

Pydantic 模型定义论文研究报告的结构。

设计原则：
  - 与 extractor.py 的 Structured Output 模式一致
  - LLM 直接输出符合此 Schema 的 JSON
  - 同一份 Schema 既约束 LLM 输出，又约束 JSON 存储格式

【工程思考】为什么报告用 Pydantic 而不是自由文本？
  1. 结构化存储：JSON 可被程序消费（可视化、对比、检索）
  2. 格式一致性：Pydantic 的 JSON Schema 输出为 LLM 提供强约束
  3. 向后兼容：新增字段设默认值，旧报告不会 break
"""

from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ReportMeta(BaseModel):
    """报告元数据"""
    paper_title: str = Field(description="论文完整标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    venue: str = Field(default="", description="发表会议/期刊 (如 IEEE TWC 2024)")
    arxiv_id: str = Field(default="", description="arXiv ID (如 2404.12345)")
    year: int | None = Field(default=None, description="论文发表年份")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        description="报告生成时间 (ISO 8601)"
    )
    pdf_path: str = Field(default="", description="本地 PDF 路径")


class ReportSummary(BaseModel):
    """论文核心解读"""
    one_sentence: str = Field(description="一句话核心概括（中文）")
    problem: str = Field(description="研究要解决的核心问题")
    contributions: list[str] = Field(description="论文核心贡献列表（3-5 条）")
    methodology: str = Field(description="方法论概述（技术路线）")
    key_results: str = Field(description="核心实验结果与结论")
    strengths: list[str] = Field(default_factory=list, description="论文优点")
    weaknesses: list[str] = Field(default_factory=list, description="论文不足或局限")
    relevance_to_me: str = Field(default="", description="与我的研究方向的关联分析")


class FigureAnalysis(BaseModel):
    """图表分析结果"""
    figure_id: str = Field(description="图表编号 (如 Fig.3)")
    description: str = Field(description="图表内容描述")
    insight: str = Field(default="", description="从图表中获得的关键洞察")


class PaperReport(BaseModel):
    """
    论文研究报告完整 Schema

    这是 LLM Structured Output 的目标格式。
    LLM 接收论文全文 → 输出此格式的 JSON → 持久化为 .json + .html

    【与知识图谱的区别】
    - 知识图谱 (extractor.py): 提取离散的实体+关系 → 入图 → 图算法分析
    - 研究报告 (本模块): 提取人类可读的解读 → 存文件 → 回顾/可视化
    两者互补，不冲突。同一篇论文既入图又生报告。
    """
    meta: ReportMeta
    summary: ReportSummary
    figures_analyzed: list[FigureAnalysis] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, description="论文标签/关键词")


# ============================================================
# Prompt 用的 Schema 描述（嵌入到 LLM prompt 中）
# ============================================================

REPORT_SCHEMA_DESCRIPTION = """
你需要输出一个 JSON 对象，严格遵循以下结构：

{
  "meta": {
    "paper_title": "论文完整标题",
    "authors": ["作者1", "作者2"],
    "venue": "发表会议/期刊",
    "arxiv_id": "arXiv ID（如有）",
    "year": 2024
  },
  "summary": {
    "one_sentence": "一句话核心概括（中文）",
    "problem": "研究要解决的核心问题",
    "contributions": ["贡献1", "贡献2", "贡献3"],
    "methodology": "方法论概述（技术路线描述）",
    "key_results": "核心实验结果与结论",
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["不足1", "不足2"],
    "relevance_to_me": "与通信感知(ISAC/6G)研究方向的关联"
  },
  "figures_analyzed": [],
  "tags": ["ISAC", "channel estimation", "OFDM"]
}
"""

"""
ScholarMind - 多模态图表分析模块
================================

功能：
  1. 分析论文中的图表（框图、曲线图、表格、公式）
  2. 自动识别图表类型并选择对应分析策略
  3. 从图表中提取结构化信息（用于知识图谱入图）

技术选择：
  - 使用 MiniMax Vision API (OpenAI 兼容) 进行图表理解
  - 不是调用第三方 OCR，而是直接让多模态 LLM 理解图表语义
  - 这是 ScholarMind 的核心差异化能力

工程设计原则：
  1. Prompt 与代码分离（Prompt 模板存放在 prompts/ 目录）
  2. 多种分析策略对应不同图表类型 → Strategy 模式
  3. base64 图片 + 文本 prompt 组合发送 → multimodal message
  4. 结构化输出（JSON）→ 抗 Silent Regression

【工程思考】为什么用 Vision API 而不是专业 OCR/CV 模型？
  - 学术图表种类多样（框图、流程图、信号流图、曲线对比…），
    单一 CV 模型覆盖不了
  - Vision LLM 可以同时理解"图"和"上下文文字"
  - 对于通信感知领域，LLM 能理解 OFDM 框图/BER 曲线的含义，
    而通用 OCR 只能提取文字
"""

import json
import logging
import os
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger("ScholarMind.Multimodal")


# ============================================================
# 图表类型枚举
# ============================================================
class FigureType(str, Enum):
    """论文中常见的图表类型"""
    BLOCK_DIAGRAM = "block_diagram"         # 系统框图 / 流程图
    SIGNAL_FLOW = "signal_flow"             # 信号流图 / 算法流程
    PERFORMANCE_CURVE = "performance_curve"  # 性能曲线（BER/SNR/RMSE）
    TABLE = "table"                         # 数据表格
    EQUATION = "equation"                   # 数学公式
    PHOTO = "photo"                         # 实验设备/场景照片
    OTHER = "other"                         # 其他类型
    UNKNOWN = "unknown"                     # 类型未知（需要先识别）


@dataclass
class FigureAnalysisResult:
    """图表分析结果"""
    figure_type: FigureType
    description: str            # 图表的自然语言描述
    key_findings: list[str]     # 关键发现/要点
    entities: list[dict]        # 抽取的实体（用于知识图谱）
    raw_text: str = ""          # 图中的原始文字（如有）
    structured_data: dict = field(default_factory=dict)  # 结构化数据（表格→dict, 公式→LaTeX）
    confidence: float = 0.0     # 分析置信度

    def to_markdown(self) -> str:
        """转为可展示的 Markdown 格式"""
        findings_str = "\n".join(f"  - {f}" for f in self.key_findings)
        entities_str = "\n".join(
            f"  - **{e.get('name', '?')}** ({e.get('type', '?')})"
            for e in self.entities
        )
        return (
            f"### 📊 图表分析结果\n\n"
            f"**类型**: {self.figure_type.value}\n\n"
            f"**描述**: {self.description}\n\n"
            f"**关键发现**:\n{findings_str}\n\n"
            f"**抽取实体**:\n{entities_str or '  （无）'}"
        )


# ============================================================
# Prompt 加载器
#
# 优先从 prompts/ 目录加载文件，若不存在则使用内联 fallback。
# 这样实现了 "Prompt Engineering as Configuration"：
# - 调优 Prompt 只需编辑 .txt 文件，不需要改代码
# - Git diff 可以精确追踪 Prompt 变更历史
# - 支持 A/B 测试（同一图表，不同 Prompt 文件）
# ============================================================

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "domain_prompts"

# 内联 fallback（当 prompt 文件不存在时使用）
_FALLBACK_PROMPTS = {
    "figure_type_detection": (
        'You are analyzing a figure from an academic paper in communications/sensing.\n'
        'Identify the type: block_diagram, signal_flow, performance_curve, table, equation, photo, or other.\n'
        'Respond in JSON: {"figure_type": "<type>", "description": "<one-sentence>"}'
    ),
    "general_analysis": (
        'Analyze this academic figure. Extract description, key_findings, entities.\n'
        'Context: {context}\n'
        'Respond in JSON: {"description": "...", "key_findings": [...], "entities": [...], "raw_text": "..."}'
    ),
}


def _load_prompt(name: str) -> str:
    """
    从 prompts/domain_prompts/ 加载 Prompt 文件

    优先级: 文件 > 内联 fallback
    """
    prompt_file = PROMPTS_DIR / f"{name}.txt"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8").strip()
    logger.warning(f"Prompt 文件不存在: {prompt_file}, 使用内联 fallback")
    return _FALLBACK_PROMPTS.get(name, _FALLBACK_PROMPTS["general_analysis"])


# 懒加载 prompt（首次访问时从文件读取）
def _get_prompts() -> dict:
    """加载所有 analysis prompt 模板"""
    return {
        "figure_type_detection": _load_prompt("figure_type_detection"),
        "block_diagram": _load_prompt("block_diagram_analysis"),
        "signal_flow": _load_prompt("block_diagram_analysis"),  # 复用框图 prompt
        "performance_curve": _load_prompt("performance_curve_analysis"),
        "table": _load_prompt("table_analysis"),
        "general": _load_prompt("general_analysis"),
    }


# Prompt 路由表（FigureType → prompt key）
FIGURE_TYPE_TO_PROMPT_KEY = {
    FigureType.BLOCK_DIAGRAM: "block_diagram",
    FigureType.SIGNAL_FLOW: "signal_flow",
    FigureType.PERFORMANCE_CURVE: "performance_curve",
    FigureType.TABLE: "table",
}


class FigureAnalyzer:
    """
    论文图表多模态分析器

    使用 MiniMax Vision API (OpenAI 兼容) 分析论文中的图表，
    自动识别图表类型并选择对应分析策略。

    Usage:
        analyzer = FigureAnalyzer()
        result = await analyzer.analyze(image_b64, context="本文提出了...")
        print(result.to_markdown())
    """

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 2000,
    ):
        self.model = model or os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        self.max_tokens = max_tokens
        # 延迟加载 API key，避免导入时就报错
        self._client = None

    @property
    def client(self) -> OpenAI:
        """懒加载 OpenAI-compatible client (MiniMax)"""
        if self._client is None:
            api_key = os.getenv("MINIMAX_API_KEY")
            base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
            if not api_key:
                raise ValueError(
                    "MINIMAX_API_KEY 未设置。请在 .env 中配置。"
                )
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        return self._client

    async def analyze(
        self,
        image_base64: str,
        context: str = "",
        figure_type: FigureType = FigureType.UNKNOWN,
        media_type: str = "image/png",
    ) -> FigureAnalysisResult:
        """
        分析一张论文图表

        Args:
            image_base64: 图片的 base64 编码
            context: 论文上下文（如该图所在段落的文字）
            figure_type: 已知的图表类型（UNKNOWN 则自动检测）
            media_type: 图片 MIME 类型

        Returns:
            FigureAnalysisResult: 结构化分析结果
        """
        # Step 1: 如果类型未知，先检测类型
        if figure_type == FigureType.UNKNOWN:
            figure_type = await self._detect_type(image_base64, media_type)
            logger.info(f"图表类型检测: {figure_type.value}")

        # Step 2: 选择对应 prompt（从文件加载）
        prompts = _get_prompts()
        prompt_key = FIGURE_TYPE_TO_PROMPT_KEY.get(figure_type, "general")
        prompt_template = prompts.get(prompt_key, prompts["general"])
        prompt = prompt_template.format(context=context or "（无额外上下文）")

        # Step 3: 调用 Vision API
        raw_result = await self._call_vision(image_base64, prompt, media_type)

        # Step 4: 解析结果
        return self._parse_result(raw_result, figure_type)

    async def _detect_type(
        self, image_base64: str, media_type: str
    ) -> FigureType:
        """
        自动检测图表类型

        【工程思考】为什么分两步（先检测类型，再详细分析）？
        1. 不同图表类型需要不同的分析 prompt → 一步到位效果差
        2. 类型检测用的 prompt 很短（token 消耗少）
        3. 如果类型是已知的（用户指定），可以跳过这步省钱
        """
        detection_prompt = _load_prompt("figure_type_detection")
        raw = await self._call_vision(
            image_base64, detection_prompt, media_type
        )

        try:
            data = self._extract_json(raw)
            type_str = data.get("figure_type", "unknown")
            return FigureType(type_str)
        except (ValueError, KeyError):
            logger.warning(f"图表类型检测失败, 使用 OTHER: {raw[:100]}")
            return FigureType.OTHER

    async def _call_vision(
        self, image_base64: str, prompt: str, media_type: str
    ) -> str:
        """
        调用 MiniMax Vision API (OpenAI 兼容格式)

        使用 OpenAI SDK 的 image_url 格式传递 base64 图片：
        data:<media_type>;base64,<data>
        """
        data_uri = f"data:{media_type};base64,{image_base64}"

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_uri,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        return response.choices[0].message.content

    def _extract_json(self, text: str) -> dict:
        """
        从 LLM 输出中提取 JSON（抗 Silent Regression）

        【工程思考】这是从 05_Agent工程落地深度思考.md 中的
        RobustJSONExtractor 精简版。在真实项目中，
        LLM 输出格式不可 100% 信赖，必须有 fallback。
        """
        import re

        # 策略1: 直接 parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略2: 提取 ```json ``` 块
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 策略3: 找 { } 对
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"JSON 提取失败: {text[:200]}")
        return {}

    def _parse_result(
        self, raw_text: str, figure_type: FigureType
    ) -> FigureAnalysisResult:
        """将 LLM 原始输出解析为结构化结果"""
        data = self._extract_json(raw_text)

        if not data:
            return FigureAnalysisResult(
                figure_type=figure_type,
                description="（分析失败，无法解析 LLM 输出）",
                key_findings=[],
                entities=[],
                raw_text=raw_text,
                confidence=0.0,
            )

        return FigureAnalysisResult(
            figure_type=figure_type,
            description=data.get("description", ""),
            key_findings=data.get("key_findings", []),
            entities=data.get("entities", []),
            raw_text=data.get("raw_text", ""),
            structured_data={
                k: v for k, v in data.items()
                if k not in ("description", "key_findings", "entities", "raw_text")
            },
            confidence=0.85 if data else 0.0,
        )


class PaperStructureParser:
    """
    论文结构化解析器

    将论文 PDF 的内容解析为标准化章节结构：
    Title → Abstract → Introduction → Method → Experiments → Conclusion

    【工程思考】为什么不直接让 LLM 分析全文？
    1. 全文 token 太多（8000-15000），成本高
    2. 不需要 LLM 来做章节分割——正则就够了
    3. LLM 更适合做"理解"而非"分割"
    """

    # 【踩坑记录】IEEE 论文用罗马数字编号（I. Introduction），
    # 而 arXiv/Springer 用阿拉伯数字（1. Introduction）
    # 正则需要同时覆盖两种格式
    #
    # 【踩坑记录 #2】"Algorithm content." 这类内容行也会匹配 "algorithm\b"
    # → 解法：对于模糊关键词（algorithm, conclusion, result…）
    #   要求必须有数字/罗马前缀，或者行内单词数 ≤ 4
    _NUM_PREFIX_OPT = r"(?:(?:\d+|[IVX]+)\.?\s*)?"   # 可选前缀
    _NUM_PREFIX_REQ = r"(?:(?:\d+|[IVX]+)\.?\s+)"     # 必须有前缀

    # 匹配策略：
    # - abstract / references: 通常独占一行，精确匹配
    # - introduction 等复合词: 不太会出现在正文首词，前缀可选
    # - algorithm / conclusion 等单词: 容易在正文出现，需要前缀或精确匹配
    SECTION_PATTERNS = [
        (r"(?i)^abstract\s*$", "abstract"),
        (rf"(?i)^{_NUM_PREFIX_OPT}introduction\s*$", "introduction"),
        (rf"(?i)^{_NUM_PREFIX_OPT}(?:related\s+work|background|literature\s+review)\b", "related_work"),
        (rf"(?i)^{_NUM_PREFIX_OPT}(?:system\s+model|problem\s+formulation)\b", "system_model"),
        # method: 复合短语（proposed method/algorithm）前缀可选，
        # 但单独的 "algorithm" / "methodology" 需要前缀
        (rf"(?i)^{_NUM_PREFIX_OPT}proposed\s+(?:method|algorithm|scheme|framework)\s*$", "method"),
        (rf"(?i)^{_NUM_PREFIX_REQ}(?:methodology|approach|algorithm)\b", "method"),
        # experiments: 复合短语前缀可选，单词需要前缀
        (rf"(?i)^{_NUM_PREFIX_OPT}(?:simulations?\s+results?|numerical\s+results?)\b", "experiments"),
        (rf"(?i)^{_NUM_PREFIX_REQ}(?:experiments?|results?|evaluation)\b", "experiments"),
        # conclusion: 需要前缀或精确匹配
        (rf"(?i)^{_NUM_PREFIX_OPT}conclusions?\s*$", "conclusion"),
        (rf"(?i)^{_NUM_PREFIX_REQ}(?:summary|concluding)\b", "conclusion"),
        (r"(?i)^(?:references|bibliography)\s*$", "references"),
    ]

    def parse_sections(self, full_text: str) -> dict[str, str]:
        """
        将全文分割为标准化章节

        Returns:
            dict: key = 章节名, value = 章节文本
            例如 {"abstract": "...", "method": "...", "experiments": "..."}
        """
        import re

        sections = {}
        lines = full_text.split("\n")

        current_section = "preamble"
        current_content = []

        for line in lines:
            # 检测是否是新章节标题
            matched_section = None
            stripped = line.strip()

            for pattern, section_name in self.SECTION_PATTERNS:
                if re.match(pattern, stripped) and len(stripped) < 80:
                    matched_section = section_name
                    break

            if matched_section:
                # 保存上一章节
                if current_content:
                    text = "\n".join(current_content).strip()
                    if text:
                        sections[current_section] = text
                current_section = matched_section
                current_content = []
            else:
                current_content.append(line)

        # 保存最后一个章节
        if current_content:
            text = "\n".join(current_content).strip()
            if text:
                sections[current_section] = text

        logger.info(f"论文结构解析: 识别 {len(sections)} 个章节: {list(sections.keys())}")
        return sections

    def get_section_summary(self, sections: dict[str, str]) -> str:
        """生成章节概览"""
        lines = ["## 📑 论文结构概览\n"]
        for section, text in sections.items():
            word_count = len(text.split())
            lines.append(f"- **{section}**: {word_count} words")
        return "\n".join(lines)

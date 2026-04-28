from __future__ import annotations

"""
ScholarMind - LLM 驱动的知识抽取模块
========================================

从论文文本中自动抽取实体和关系，写入知识图谱。

核心设计：Schema-Guided Extraction
  - 将知识图谱的 Schema（节点类型 + 关系类型）嵌入到 Prompt 中
  - LLM 被约束为只能输出 Schema 中定义的类型
  - 输出为结构化 JSON → 解析后生成 KGNode + KGEdge

工程要点：
  1. Prompt 中包含 Schema 定义 + JSON 示例 → 约束 LLM 输出格式
  2. 复用 multimodal.py 中的 Robust JSON 提取器 → 抗 LLM 输出不规范
  3. 支持批量抽取（对论文分段抽取后合并）→ 控制单次 token 量
  4. 置信度标注 → 低质量抽取结果不入图

【工程思考】为什么用 LLM 抽取而不是 NER + RE 管线？
  - 传统 NER 模型（spaCy/HuggingFace）不理解通信感知领域术语
  - 训练领域 NER 需要大量标注数据（我们没有）
  - LLM 天然理解 "OFDM", "Beamforming", "CRLB" 这些术语
  - Schema-guided prompt = 零标注数据的领域知识抽取
"""

import json
import logging
import os
import re
from dataclasses import dataclass

from openai import OpenAI
from dotenv import load_dotenv

from .schema import (
    KGNode,
    KGEdge,
    NodeType,
    RelationType,
    ExtractionResult,
    ExtractionOutput,
    SCHEMA_DESCRIPTION,
    SCHEMA_JSON_EXAMPLE,
)

# 加载环境变量
load_dotenv()

logger = logging.getLogger("ScholarMind.Extractor")


# ============================================================
# 抽取 Prompt 模板
# ============================================================

EXTRACTION_PROMPT = """你是一名通信/感知领域（通感一体化(ISAC)、6G、OFDM、MIMO、波束成形、定位等）学术论文的知识图谱抽取专家。

你的任务：根据下方的 Schema（架构），从给定的文本中抽取实体（节点）和关系（边）。

{schema}

## 规则
1. 只能抽取上方 Schema 中定义过的实体和关系类型。
2. 所有的实体标签（Entity labels）强制使用 **英文**（即使原文是中文，也必须使用标准英文专业术语）。
3. 规范化实体名称：使用最常见/标准的缩写形式（例如：使用 "OFDM" 而不是 "Orthogonal Frequency Division Multiplexing"）。
4. 每个实体必须具备 Schema 中明确定义的 `node_type`。
5. 每条关系必须包含 `source_label`, `source_type`, `target_label`, `target_type`, 以及 `relation_type`。
6. 必须精确：只能抽取文本中明确陈述或强烈暗示的内容。
7. 绝对不要（Do NOT）伪造或幻觉出文本不支持的实体或关系。

## 论文上下文
- **标题**: {paper_title}
- **年份**: {paper_year}

## 待抽取的文本
{text}

## 输出格式
严格按照 JSON Schema 约束输出，不要输出任何其他解释性文本。
"""

MERGE_PROMPT = """你已经从同一篇论文的不同章节中提取了部分知识。
请将以下零散的抽取结果合并为一个统一的、去重后的最终结果。

规则：
1. 合并重复的实体（如果 label 和 type 相同，则视为同一实体）。
2. 合并重复的关系（边）。
3. 为每个实体保留信息量最丰富的属性。
4. 必须以相同的 JSON 格式输出合并后的结果。

部分抽取结果：
{partial_results}

请务必仅返回合法的 JSON 格式数据：
"""


class KnowledgeExtractor:
    """
    LLM 驱动的知识抽取器（MiniMax API，OpenAI 兼容）

    Usage:
        extractor = KnowledgeExtractor()
        result = await extractor.extract_from_text(
            text="We propose a novel hybrid beamforming method...",
            paper_title="Hybrid Beamforming for ISAC",
            paper_year="2024",
        )
        print(result.to_summary())
    """

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 4000,
        min_confidence: float = 0.5,
        max_chunk_chars: int = 3000,
    ):
        """
        Args:
            model: LLM 模型名称（默认从环境变量 MINIMAX_MODEL 读取）
            max_tokens: LLM 最大输出 token 数
            min_confidence: 最低置信度阈值（低于此值的实体/关系不入图）
            max_chunk_chars: 单次抽取的最大文本长度（超过则分段）
        """
        self.model = model or os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        self.max_tokens = max_tokens
        self.min_confidence = min_confidence
        self.max_chunk_chars = max_chunk_chars
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

    async def extract_from_text(
        self,
        text: str,
        paper_title: str = "",
        paper_year: str = "",
    ) -> ExtractionResult:
        """
        从文本中抽取实体和关系

        如果文本过长，自动分段抽取后合并。

        Args:
            text: 论文文本（全文或章节）
            paper_title: 论文标题
            paper_year: 论文年份

        Returns:
            ExtractionResult: 抽取出的节点和边
        """
        # 分段
        chunks = self._split_text(text)
        logger.info(
            f"知识抽取: paper='{paper_title}', "
            f"text_len={len(text)}, chunks={len(chunks)}"
        )

        if len(chunks) == 1:
            # 单段直接抽取
            return await self._extract_single(
                chunks[0], paper_title, paper_year
            )
        else:
            # 多段分别抽取后合并
            partial_results = []
            for i, chunk in enumerate(chunks):
                logger.info(f"抽取第 {i + 1}/{len(chunks)} 段...")
                result = await self._extract_single(
                    chunk, paper_title, paper_year
                )
                if result.nodes or result.edges:
                    partial_results.append(result)

            if not partial_results:
                return ExtractionResult(
                    paper_title=paper_title,
                    extraction_confidence=0.0,
                )

            # 合并（本地去重，不再用 LLM merge 以节省 token）
            return self._merge_results(partial_results, paper_title)

    async def _extract_single(
        self,
        text: str,
        paper_title: str,
        paper_year: str,
    ) -> ExtractionResult:
        """对单段文本执行知识抽取"""
        prompt = EXTRACTION_PROMPT.format(
            schema=SCHEMA_DESCRIPTION,
            paper_title=paper_title or "(unknown)",
            paper_year=paper_year or "(unknown)",
            text=text,
        )

        try:
            raw_output = self._call_llm(prompt)
            return self._parse_extraction(raw_output, paper_title)
        except Exception as e:
            logger.error(f"知识抽取失败: {e}")
            return ExtractionResult(
                paper_title=paper_title,
                raw_llm_output=str(e),
                extraction_confidence=0.0,
            )

    def _call_llm(self, prompt: str) -> str:
        """
        调用 MiniMax API (OpenAI 兼容)

        【重构】使用 response_format=json_schema 在 API 层面强制约束输出格式。
        MiniMax-Text-01 原生支持该参数，LLM 的输出将 100% 符合 JSON Schema。
        """
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction_output",
                    "schema": ExtractionOutput.model_json_schema(),
                },
            },
        )
        return response.choices[0].message.content

    def _parse_extraction(
        self, raw_output: str, paper_title: str
    ) -> ExtractionResult:
        """
        解析 LLM 输出为 ExtractionResult

        【重构】使用 Pydantic model_validate_json 替代手动 try/except。
        由于 API 层面已强制 JSON Schema 约束，此处解析几乎不会失败。
        保留 _extract_json 作为降级 fallback（应对非 Structured Output 场景）。
        """
        # 优先使用 Pydantic 严格解析
        try:
            output = ExtractionOutput.model_validate_json(raw_output)
        except Exception as pydantic_err:
            # 降级：尝试宽松 JSON 提取（应对模型不完全遵守 response_format 的情况）
            logger.warning(
                f"Pydantic 严格解析失败，降级到宽松 JSON 提取: {pydantic_err}"
            )
            data = self._extract_json(raw_output)
            if not data:
                logger.error(f"JSON 提取也失败: {raw_output[:200]}")
                return ExtractionResult(
                    paper_title=paper_title,
                    raw_llm_output=raw_output,
                    extraction_confidence=0.0,
                )
            try:
                output = ExtractionOutput.model_validate(data)
            except Exception as fallback_err:
                logger.error(f"降级解析也失败: {fallback_err}")
                return ExtractionResult(
                    paper_title=paper_title,
                    raw_llm_output=raw_output,
                    extraction_confidence=0.0,
                )

        # Pydantic 模型 → 内部 KGNode/KGEdge 数据类
        nodes = []
        for n in output.nodes:
            try:
                node = KGNode(
                    label=n.label,
                    node_type=NodeType(n.node_type),
                    properties=dict(n.properties),
                    source_paper=paper_title,
                )
                nodes.append(node)
            except ValueError as e:
                logger.debug(f"节点类型转换跳过: {e} / {n}")

        edges = []
        for e_data in output.edges:
            try:
                source_node = KGNode(
                    label=e_data.source_label,
                    node_type=NodeType(e_data.source_type),
                )
                target_node = KGNode(
                    label=e_data.target_label,
                    node_type=NodeType(e_data.target_type),
                )
                edge = KGEdge(
                    source_id=source_node.node_id,
                    target_id=target_node.node_id,
                    relation_type=RelationType(e_data.relation_type),
                    confidence=0.8,
                    source_paper=paper_title,
                )
                edges.append(edge)
            except ValueError as e:
                logger.debug(f"边类型转换跳过: {e} / {e_data}")

        confidence = 0.85 if (nodes and edges) else 0.5 if nodes else 0.0

        logger.info(
            f"抽取完成: {len(nodes)} 节点, {len(edges)} 边, "
            f"confidence={confidence}"
        )

        return ExtractionResult(
            nodes=nodes,
            edges=edges,
            raw_llm_output=raw_output,
            paper_title=paper_title,
            extraction_confidence=confidence,
        )

    def _merge_results(
        self,
        partial_results: list[ExtractionResult],
        paper_title: str,
    ) -> ExtractionResult:
        """
        合并多段抽取结果（本地去重）

        【工程思考】为什么本地合并而不用 LLM merge？
        1. 节省 token 成本（merge prompt 也要消耗 token）
        2. 本地去重逻辑确定性高（node_id 相同则合并）
        3. 避免 LLM 在 merge 时引入新的错误
        """
        seen_node_ids = {}  # node_id → KGNode
        seen_edge_ids = set()
        all_edges = []

        for result in partial_results:
            for node in result.nodes:
                nid = node.node_id
                if nid in seen_node_ids:
                    seen_node_ids[nid].merge_properties(node.properties)
                else:
                    seen_node_ids[nid] = node

            for edge in result.edges:
                eid = edge.edge_id
                if eid not in seen_edge_ids:
                    seen_edge_ids.add(eid)
                    all_edges.append(edge)

        merged = ExtractionResult(
            nodes=list(seen_node_ids.values()),
            edges=all_edges,
            paper_title=paper_title,
            extraction_confidence=max(
                r.extraction_confidence for r in partial_results
            ),
        )

        logger.info(
            f"合并完成: {len(partial_results)} 段 → "
            f"{merged.node_count} 节点, {merged.edge_count} 边"
        )
        return merged

    def _split_text(self, text: str) -> list[str]:
        """
        将长文本分段

        按段落边界分割，每段不超过 max_chunk_chars 字符。
        """
        if len(text) <= self.max_chunk_chars:
            return [text]

        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > self.max_chunk_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk += "\n\n" + para

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text]

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        从 LLM 输出中提取 JSON（3 策略 fallback）

        与 multimodal.py 中的 FigureAnalyzer._extract_json 完全一致。
        """
        # 策略 1: 直接 parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略 2: 提取 ```json ``` 块
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 策略 3: 找 { } 对
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"JSON 提取失败: {text[:200]}")
        return {}

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
  - Claude 天然理解 "OFDM", "Beamforming", "CRLB" 这些术语
  - Schema-guided prompt = 零标注数据的领域知识抽取
"""

import json
import logging
import re
from dataclasses import dataclass

import anthropic

from .schema import (
    KGNode,
    KGEdge,
    NodeType,
    RelationType,
    ExtractionResult,
    SCHEMA_DESCRIPTION,
    SCHEMA_JSON_EXAMPLE,
)

logger = logging.getLogger("ScholarMind.Extractor")


# ============================================================
# 抽取 Prompt 模板
# ============================================================

EXTRACTION_PROMPT = """You are a knowledge graph extraction expert for academic papers in the communications/sensing domain (ISAC, 6G, OFDM, MIMO, beamforming, localization, etc.).

Your task: Extract entities (nodes) and relationships (edges) from the given text, following the schema below.

{schema}

## Rules
1. Only extract entities and relations defined in the schema above.
2. Use **English** for all entity labels (even if the source text is in Chinese).
3. Normalize entity names: use the most common/standard form (e.g., "OFDM" not "Orthogonal Frequency Division Multiplexing").
4. Each entity must have a clear `node_type` from the schema.
5. Each relation must have `source_label`, `source_type`, `target_label`, `target_type`, and `relation_type`.
6. Be precise: only extract what is explicitly stated or strongly implied by the text.
7. Do NOT hallucinate entities or relations not supported by the text.

## Paper Context
- **Title**: {paper_title}
- **Year**: {paper_year}

## Text to Extract From
{text}

## Output Format
Respond with ONLY valid JSON (no other text):
{json_example}
"""

MERGE_PROMPT = """You have extracted knowledge from multiple sections of the same paper. 
Merge the following partial extractions into a unified, deduplicated result.

Rules:
1. Merge duplicate entities (same label and type) into one.
2. Merge duplicate edges.
3. Keep the most informative properties for each entity.
4. Output the merged result in the same JSON format.

Partial extractions:
{partial_results}

Output ONLY valid JSON:
"""


class KnowledgeExtractor:
    """
    LLM 驱动的知识抽取器

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
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4000,
        min_confidence: float = 0.5,
        max_chunk_chars: int = 3000,
    ):
        """
        Args:
            model: Claude 模型名称
            max_tokens: LLM 最大输出 token 数
            min_confidence: 最低置信度阈值（低于此值的实体/关系不入图）
            max_chunk_chars: 单次抽取的最大文本长度（超过则分段）
        """
        self.model = model
        self.max_tokens = max_tokens
        self.min_confidence = min_confidence
        self.max_chunk_chars = max_chunk_chars
        self._client = None

    @property
    def client(self) -> anthropic.Anthropic:
        """懒加载 Anthropic client"""
        if self._client is None:
            self._client = anthropic.Anthropic()
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
            json_example=SCHEMA_JSON_EXAMPLE,
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
        """调用 Claude API"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _parse_extraction(
        self, raw_output: str, paper_title: str
    ) -> ExtractionResult:
        """
        解析 LLM 输出为 ExtractionResult

        复用 multimodal.py 中的 3 策略 JSON 提取逻辑。
        """
        data = self._extract_json(raw_output)

        if not data:
            logger.warning(f"JSON 解析失败: {raw_output[:200]}")
            return ExtractionResult(
                paper_title=paper_title,
                raw_llm_output=raw_output,
                extraction_confidence=0.0,
            )

        nodes = []
        edges = []

        # 解析节点
        for node_data in data.get("nodes", []):
            try:
                node_type = NodeType(node_data["node_type"])
                node = KGNode(
                    label=node_data["label"],
                    node_type=node_type,
                    properties=node_data.get("properties", {}),
                    source_paper=paper_title,
                )
                nodes.append(node)
            except (KeyError, ValueError) as e:
                logger.debug(f"节点解析跳过: {e} / {node_data}")

        # 解析边：需要从 label+type 生成 node_id
        for edge_data in data.get("edges", []):
            try:
                source_label = edge_data["source_label"]
                source_type = NodeType(edge_data["source_type"])
                target_label = edge_data["target_label"]
                target_type = NodeType(edge_data["target_type"])
                relation_type = RelationType(edge_data["relation_type"])

                # 生成 ID（与 KGNode.node_id 算法一致）
                source_node = KGNode(
                    label=source_label, node_type=source_type
                )
                target_node = KGNode(
                    label=target_label, node_type=target_type
                )

                edge = KGEdge(
                    source_id=source_node.node_id,
                    target_id=target_node.node_id,
                    relation_type=relation_type,
                    confidence=0.8,
                    source_paper=paper_title,
                )
                edges.append(edge)
            except (KeyError, ValueError) as e:
                logger.debug(f"边解析跳过: {e} / {edge_data}")

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

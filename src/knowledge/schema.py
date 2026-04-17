from __future__ import annotations

"""
ScholarMind - 知识图谱 Schema 定义
====================================

定义通信感知（ISAC/6G）领域的知识图谱结构：
  - 节点类型（Paper, Author, Concept, Method, Dataset, Metric, Tool）
  - 关系类型（PROPOSES, USES, IMPROVES, COMPARES_WITH, ...）
  - 数据类（KGNode, KGEdge, ExtractionResult）

设计原则：
  1. Schema-first: 先定义 Schema，再用 Schema 引导 LLM 抽取
  2. 领域定制: 节点/关系类型针对通信感知领域优化
  3. 可扩展: 新增类型只需在枚举中追加，不改动存储/抽取逻辑

【工程思考】为什么要有 Schema？
  - 无 Schema 的自由抽取会导致同义词泛滥（如 "OFDM", "ofdm", "正交频分复用"）
  - Schema 约束让 LLM 输出规范化，便于去重和图谱合并
  - Schema 也是知识图谱可视化和查询的基础
"""

import re
import hashlib
from enum import Enum
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 节点类型枚举
# ============================================================
class NodeType(str, Enum):
    """知识图谱中的节点类型"""

    PAPER = "paper"
    """论文：知识图谱的核心节点"""

    AUTHOR = "author"
    """作者：论文的创作者"""

    CONCEPT = "concept"
    """概念：领域术语/技术概念（如 OFDM, MIMO, RIS, ISAC）"""

    METHOD = "method"
    """方法/算法：论文提出或使用的具体方法"""

    DATASET = "dataset"
    """数据集：实验使用的数据集"""

    METRIC = "metric"
    """评估指标：如 BER, RMSE, CRLB, Throughput"""

    TOOL = "tool"
    """工具/框架：如 MATLAB, Python, ns-3, TensorFlow"""


class RelationType(str, Enum):
    """知识图谱中的关系类型"""

    # 论文 → 方法
    PROPOSES = "proposes"
    """论文提出了某个方法"""

    # 论文/方法 → 概念/方法/数据集/工具
    USES = "uses"
    """使用了某个概念/方法/数据集/工具"""

    # 方法 → 方法
    IMPROVES = "improves"
    """改进了某个已有方法"""

    EXTENDS = "extends"
    """扩展了某个已有方法"""

    # 论文 → 论文
    COMPARES_WITH = "compares_with"
    """与某篇论文进行了对比实验"""

    CITES = "cites"
    """引用了某篇论文"""

    # 论文 → 作者
    AUTHORED_BY = "authored_by"
    """由某作者撰写"""

    # 方法 → 指标
    EVALUATED_BY = "evaluated_by"
    """用某个指标进行评估"""

    # 概念 → 概念（层级关系）
    BELONGS_TO = "belongs_to"
    """属于更大的概念类别（如 OFDM belongs_to 多载波技术）"""

    RELATED_TO = "related_to"
    """与某个概念相关（通用关系，无法归入上述类别时使用）"""

    # 方法 → 数据集
    TESTED_ON = "tested_on"
    """在某个数据集上进行了测试"""


# ============================================================
# 数据类定义
# ============================================================
@dataclass
class KGNode:
    """
    知识图谱节点

    Attributes:
        node_id: 唯一标识符（自动从 label + node_type 生成）
        label: 节点显示名称（如 "OFDM", "Hybrid Beamforming"）
        node_type: 节点类型
        properties: 附加属性（如论文的 year, venue; 方法的 complexity）
        source_paper: 该节点来源的论文标题（用于溯源）

    【工程思考】为什么 node_id 自动生成？
    保证不同论文中提到的相同概念映射到同一个节点 ID。
    例如 Paper A 和 Paper B 都提到 "OFDM"，应该合并到同一个节点。
    """

    label: str
    node_type: NodeType
    properties: dict[str, Any] = field(default_factory=dict)
    source_paper: str = ""

    @property
    def node_id(self) -> str:
        """
        根据 label 和 node_type 生成唯一 ID

        算法：type_normalized_label
        例如：concept_ofdm, method_hybrid_beamforming, paper_xxxx(hash)
        """
        normalized = self._normalize_label(self.label)
        if self.node_type == NodeType.PAPER:
            # 论文标题可能很长，用 hash 截短
            short_hash = hashlib.md5(
                normalized.encode("utf-8")
            ).hexdigest()[:8]
            return f"{self.node_type.value}_{short_hash}"
        return f"{self.node_type.value}_{normalized}"

    @staticmethod
    def _normalize_label(label: str) -> str:
        """
        标签标准化：小写 + 去除特殊字符 + 空格转下划线

        用于保证 "OFDM" == "ofdm" == "Ofdm" 映射到同一节点
        """
        label = label.lower().strip()
        # 只保留字母、数字、空格
        label = re.sub(r"[^a-z0-9\s\u4e00-\u9fff]", "", label)
        # 多个空格合并为一个下划线
        label = re.sub(r"\s+", "_", label)
        return label

    def merge_properties(self, other_properties: dict[str, Any]) -> None:
        """
        合并另一个同 ID 节点的属性（去重合并）

        【工程思考】为什么需要合并？
        同一个概念可能从不同论文中被抽取，每次抽取的属性可能不同。
        例如从 Paper A 抽取了 OFDM 的定义，从 Paper B 抽取了 OFDM 的应用场景。
        """
        for key, value in other_properties.items():
            if key not in self.properties:
                self.properties[key] = value
            elif isinstance(self.properties[key], list) and isinstance(value, list):
                # 列表类型合并去重
                existing = set(str(v) for v in self.properties[key])
                for v in value:
                    if str(v) not in existing:
                        self.properties[key].append(v)
            elif isinstance(self.properties[key], str) and isinstance(value, str):
                # 字符串类型，保留更长的（通常信息更丰富）
                if len(value) > len(self.properties[key]):
                    self.properties[key] = value

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON 持久化）"""
        return {
            "node_id": self.node_id,
            "label": self.label,
            "node_type": self.node_type.value,
            "properties": self.properties,
            "source_paper": self.source_paper,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KGNode":
        """从字典反序列化"""
        return cls(
            label=data["label"],
            node_type=NodeType(data["node_type"]),
            properties=data.get("properties", {}),
            source_paper=data.get("source_paper", ""),
        )


@dataclass
class KGEdge:
    """
    知识图谱边（关系）

    Attributes:
        source_id: 源节点 ID
        target_id: 目标节点 ID
        relation_type: 关系类型
        properties: 附加属性（如关系的描述、上下文）
        confidence: 抽取置信度（0.0 ~ 1.0）
        source_paper: 该关系来源的论文标题
    """

    source_id: str
    target_id: str
    relation_type: RelationType
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8
    source_paper: str = ""

    @property
    def edge_id(self) -> str:
        """边的唯一标识"""
        return f"{self.source_id}--{self.relation_type.value}-->{self.target_id}"

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type.value,
            "properties": self.properties,
            "confidence": self.confidence,
            "source_paper": self.source_paper,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KGEdge":
        """从字典反序列化"""
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation_type=RelationType(data["relation_type"]),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 0.8),
            source_paper=data.get("source_paper", ""),
        )


@dataclass
class ExtractionResult:
    """
    LLM 实体/关系抽取结果

    由 extractor.py 的 extract_from_text() 返回。
    包含抽取出的节点、边，以及 LLM 原始输出（用于调试）。
    """

    nodes: list[KGNode] = field(default_factory=list)
    edges: list[KGEdge] = field(default_factory=list)
    raw_llm_output: str = ""
    paper_title: str = ""
    extraction_confidence: float = 0.0

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_summary(self) -> str:
        """生成抽取结果的摘要"""
        node_types = {}
        for node in self.nodes:
            t = node.node_type.value
            node_types[t] = node_types.get(t, 0) + 1

        edge_types = {}
        for edge in self.edges:
            t = edge.relation_type.value
            edge_types[t] = edge_types.get(t, 0) + 1

        node_summary = ", ".join(f"{t}: {c}" for t, c in node_types.items())
        edge_summary = ", ".join(f"{t}: {c}" for t, c in edge_types.items())

        return (
            f"## 📊 知识抽取结果\n\n"
            f"**来源论文**: {self.paper_title}\n"
            f"**节点数**: {self.node_count} ({node_summary})\n"
            f"**关系数**: {self.edge_count} ({edge_summary})\n"
            f"**置信度**: {self.extraction_confidence:.2f}\n"
        )


# ============================================================
# Schema 描述（用于 Prompt 嵌入）
#
# 【工程思考】这段文字会被嵌入到抽取 Prompt 中，
# 引导 LLM 按照我们定义的 Schema 输出结构化结果。
# 如果 Schema 变更，这里也要同步更新。
# ============================================================
SCHEMA_DESCRIPTION = """
## 知识图谱 Schema

### 节点类型 (Node Types)
- **paper**: 论文（属性: title, year, venue, doi, abstract）
- **author**: 作者（属性: name, affiliation）
- **concept**: 领域概念/术语（属性: name, definition, domain）
  - 示例: OFDM, MIMO, RIS, ISAC, Beamforming, Channel Estimation
- **method**: 方法/算法（属性: name, category, complexity, description）
  - 示例: Hybrid Beamforming, MUSIC Algorithm, UKF-based Localization
- **dataset**: 数据集（属性: name, description, link）
- **metric**: 评估指标（属性: name, formula, unit）
  - 示例: BER, RMSE, CRLB, Spectral Efficiency, Throughput
- **tool**: 工具/框架（属性: name, language, link）
  - 示例: MATLAB, Python, ns-3, TensorFlow

### 关系类型 (Relation Types)
- **proposes**: 论文提出了某个方法 (paper → method)
- **uses**: 使用了某个概念/方法/数据集/工具 (paper/method → *)
- **improves**: 改进了某个已有方法 (method → method)
- **extends**: 扩展了某个已有方法 (method → method)
- **compares_with**: 与某篇论文进行对比 (paper → paper)
- **cites**: 引用了某篇论文 (paper → paper)
- **authored_by**: 由某作者撰写 (paper → author)
- **evaluated_by**: 用某指标评估 (method → metric)
- **belongs_to**: 属于更大概念类别 (concept → concept)
- **related_to**: 通用相关关系 (any → any)
- **tested_on**: 在某数据集上测试 (method → dataset)
""".strip()

SCHEMA_JSON_EXAMPLE = """
{
  "nodes": [
    {"label": "Hybrid Beamforming for ISAC Systems", "node_type": "paper", "properties": {"year": 2024, "venue": "IEEE TWC"}},
    {"label": "Hybrid Beamforming", "node_type": "method", "properties": {"category": "signal processing", "description": "..."}},
    {"label": "ISAC", "node_type": "concept", "properties": {"definition": "Integrated Sensing and Communication", "domain": "6G"}},
    {"label": "RMSE", "node_type": "metric", "properties": {"formula": "sqrt(mean((x-x_hat)^2))", "unit": "meters"}}
  ],
  "edges": [
    {"source_label": "Hybrid Beamforming for ISAC Systems", "source_type": "paper", "target_label": "Hybrid Beamforming", "target_type": "method", "relation_type": "proposes"},
    {"source_label": "Hybrid Beamforming for ISAC Systems", "source_type": "paper", "target_label": "ISAC", "target_type": "concept", "relation_type": "uses"},
    {"source_label": "Hybrid Beamforming", "source_type": "method", "target_label": "RMSE", "target_type": "metric", "relation_type": "evaluated_by"}
  ]
}
""".strip()

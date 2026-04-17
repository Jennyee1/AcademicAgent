"""
ScholarMind - 知识图谱模块测试
================================

测试 Schema 定义、图谱存储 CRUD、序列化/反序列化、查询功能。
不依赖 LLM API（纯本地测试）。
"""

import json
import tempfile
from pathlib import Path

import pytest

# 直接导入，避免通过 __init__.py 拉入 extractor（依赖 anthropic SDK）
from src.knowledge.schema import (
    NodeType,
    RelationType,
    KGNode,
    KGEdge,
    ExtractionResult,
)
from src.knowledge.graph_store import KnowledgeGraphStore


# ============================================================
# Schema 测试
# ============================================================


class TestNodeType:
    """节点类型枚举测试"""

    def test_all_types_exist(self):
        """验证所有预期的节点类型都已定义"""
        expected = {"paper", "author", "concept", "method", "dataset", "metric", "tool"}
        actual = {t.value for t in NodeType}
        assert actual == expected

    def test_string_conversion(self):
        """枚举值可正确转换为字符串"""
        assert NodeType.PAPER.value == "paper"
        assert NodeType("concept") == NodeType.CONCEPT


class TestRelationType:
    """关系类型枚举测试"""

    def test_all_types_exist(self):
        """验证所有预期的关系类型都已定义"""
        expected = {
            "proposes", "uses", "improves", "extends",
            "compares_with", "cites", "authored_by",
            "evaluated_by", "belongs_to", "related_to", "tested_on",
        }
        actual = {t.value for t in RelationType}
        assert actual == expected


class TestKGNode:
    """KGNode 数据类测试"""

    def test_node_id_generation(self):
        """验证节点 ID 的自动生成"""
        node = KGNode(label="OFDM", node_type=NodeType.CONCEPT)
        assert node.node_id == "concept_ofdm"

    def test_node_id_normalization(self):
        """验证标签标准化（大小写不敏感、去特殊字符）"""
        n1 = KGNode(label="OFDM", node_type=NodeType.CONCEPT)
        n2 = KGNode(label="ofdm", node_type=NodeType.CONCEPT)
        n3 = KGNode(label="Ofdm", node_type=NodeType.CONCEPT)
        assert n1.node_id == n2.node_id == n3.node_id

    def test_node_id_with_spaces(self):
        """验证带空格的标签标准化"""
        node = KGNode(
            label="Hybrid Beamforming",
            node_type=NodeType.METHOD,
        )
        assert node.node_id == "method_hybrid_beamforming"

    def test_paper_node_id_uses_hash(self):
        """论文节点使用 hash 避免 ID 过长"""
        node = KGNode(
            label="A Very Long Paper Title About ISAC Systems",
            node_type=NodeType.PAPER,
        )
        assert node.node_id.startswith("paper_")
        assert len(node.node_id) < 20  # hash 比完整标题短得多

    def test_merge_properties(self):
        """验证属性合并"""
        node = KGNode(
            label="OFDM",
            node_type=NodeType.CONCEPT,
            properties={"definition": "short def"},
        )
        node.merge_properties({"definition": "a much longer definition here"})
        # 保留更长的字符串
        assert "longer" in node.properties["definition"]

    def test_merge_list_properties(self):
        """验证列表类型属性合并去重"""
        node = KGNode(
            label="OFDM",
            node_type=NodeType.CONCEPT,
            properties={"domains": ["5G", "WiFi"]},
        )
        node.merge_properties({"domains": ["WiFi", "6G"]})
        assert "5G" in node.properties["domains"]
        assert "6G" in node.properties["domains"]
        # WiFi 不应重复
        wifi_count = sum(1 for d in node.properties["domains"] if d == "WiFi")
        assert wifi_count == 1

    def test_serialization(self):
        """验证序列化/反序列化"""
        node = KGNode(
            label="MIMO",
            node_type=NodeType.CONCEPT,
            properties={"domain": "wireless"},
            source_paper="Test Paper",
        )
        data = node.to_dict()
        restored = KGNode.from_dict(data)
        assert restored.label == "MIMO"
        assert restored.node_type == NodeType.CONCEPT
        assert restored.properties["domain"] == "wireless"
        assert restored.node_id == node.node_id


class TestKGEdge:
    """KGEdge 数据类测试"""

    def test_edge_id(self):
        """验证边 ID 的格式"""
        edge = KGEdge(
            source_id="concept_ofdm",
            target_id="concept_mimo",
            relation_type=RelationType.RELATED_TO,
        )
        assert edge.edge_id == "concept_ofdm--related_to-->concept_mimo"

    def test_serialization(self):
        """验证边的序列化/反序列化"""
        edge = KGEdge(
            source_id="paper_abc123",
            target_id="method_beamforming",
            relation_type=RelationType.PROPOSES,
            confidence=0.9,
        )
        data = edge.to_dict()
        restored = KGEdge.from_dict(data)
        assert restored.relation_type == RelationType.PROPOSES
        assert restored.confidence == 0.9
        assert restored.edge_id == edge.edge_id


class TestExtractionResult:
    """抽取结果测试"""

    def test_empty_result(self):
        """空结果的属性"""
        result = ExtractionResult()
        assert result.node_count == 0
        assert result.edge_count == 0

    def test_summary_output(self):
        """摘要输出格式"""
        result = ExtractionResult(
            nodes=[
                KGNode(label="OFDM", node_type=NodeType.CONCEPT),
                KGNode(label="BER", node_type=NodeType.METRIC),
            ],
            edges=[
                KGEdge(
                    source_id="concept_ofdm",
                    target_id="metric_ber",
                    relation_type=RelationType.EVALUATED_BY,
                ),
            ],
            paper_title="Test Paper",
            extraction_confidence=0.85,
        )
        summary = result.to_summary()
        assert "Test Paper" in summary
        assert "2" in summary  # 2 nodes
        assert "1" in summary  # 1 edge


# ============================================================
# GraphStore 测试
# ============================================================


class TestKnowledgeGraphStore:
    """知识图谱存储引擎测试"""

    @pytest.fixture
    def store(self):
        """创建一个空的图谱存储"""
        return KnowledgeGraphStore()

    @pytest.fixture
    def populated_store(self, store):
        """创建一个预填充的图谱"""
        # 添加节点
        store.add_node(KGNode(label="OFDM", node_type=NodeType.CONCEPT))
        store.add_node(KGNode(label="MIMO", node_type=NodeType.CONCEPT))
        store.add_node(
            KGNode(
                label="Hybrid Beamforming",
                node_type=NodeType.METHOD,
            )
        )
        store.add_node(KGNode(label="BER", node_type=NodeType.METRIC))
        store.add_node(
            KGNode(
                label="Some ISAC Paper",
                node_type=NodeType.PAPER,
            )
        )

        # 添加边
        paper_node = KGNode(label="Some ISAC Paper", node_type=NodeType.PAPER)
        method_node = KGNode(
            label="Hybrid Beamforming", node_type=NodeType.METHOD
        )

        store.add_edge(
            KGEdge(
                source_id=paper_node.node_id,
                target_id=method_node.node_id,
                relation_type=RelationType.PROPOSES,
            )
        )
        store.add_edge(
            KGEdge(
                source_id="concept_ofdm",
                target_id="concept_mimo",
                relation_type=RelationType.RELATED_TO,
            )
        )
        store.add_edge(
            KGEdge(
                source_id=method_node.node_id,
                target_id="metric_ber",
                relation_type=RelationType.EVALUATED_BY,
            )
        )
        return store

    def test_add_node(self, store):
        """验证添加节点"""
        node_id = store.add_node(
            KGNode(label="OFDM", node_type=NodeType.CONCEPT)
        )
        assert node_id == "concept_ofdm"
        assert store.node_count == 1

    def test_add_duplicate_node_merges(self, store):
        """验证重复节点合并"""
        store.add_node(
            KGNode(
                label="OFDM",
                node_type=NodeType.CONCEPT,
                properties={"domain": "wireless"},
            )
        )
        store.add_node(
            KGNode(
                label="OFDM",
                node_type=NodeType.CONCEPT,
                properties={"definition": "multi-carrier"},
            )
        )
        assert store.node_count == 1  # 应该合并，不是新增
        node = store.get_node("concept_ofdm")
        assert node is not None
        assert "domain" in node.properties
        assert "definition" in node.properties

    def test_add_edge(self, store):
        """验证添加边"""
        store.add_node(KGNode(label="OFDM", node_type=NodeType.CONCEPT))
        store.add_node(KGNode(label="MIMO", node_type=NodeType.CONCEPT))
        edge_id = store.add_edge(
            KGEdge(
                source_id="concept_ofdm",
                target_id="concept_mimo",
                relation_type=RelationType.RELATED_TO,
            )
        )
        assert edge_id != ""
        assert store.edge_count == 1

    def test_add_edge_missing_node(self, store):
        """验证添加边时源/目标节点不存在的情况"""
        store.add_node(KGNode(label="OFDM", node_type=NodeType.CONCEPT))
        edge_id = store.add_edge(
            KGEdge(
                source_id="concept_ofdm",
                target_id="concept_nonexistent",
                relation_type=RelationType.RELATED_TO,
            )
        )
        assert edge_id == ""  # 应该失败
        assert store.edge_count == 0

    def test_query_by_type(self, populated_store):
        """验证按类型查询"""
        concepts = populated_store.query_by_type(NodeType.CONCEPT)
        assert len(concepts) == 2  # OFDM + MIMO

    def test_search_nodes(self, populated_store):
        """验证关键词搜索"""
        results = populated_store.search_nodes("ofdm")
        assert len(results) >= 1
        assert any(n.label == "OFDM" for n in results)

    def test_search_nodes_case_insensitive(self, populated_store):
        """验证大小写不敏感搜索"""
        results1 = populated_store.search_nodes("OFDM")
        results2 = populated_store.search_nodes("ofdm")
        assert len(results1) == len(results2)

    def test_query_neighbors(self, populated_store):
        """验证邻居查询"""
        neighbors = populated_store.query_neighbors("concept_ofdm", depth=1)
        assert len(neighbors) >= 1
        labels = [n.label for n, e in neighbors]
        assert "MIMO" in labels

    def test_remove_node(self, populated_store):
        """验证删除节点（含关联边）"""
        initial_edges = populated_store.edge_count
        removed = populated_store.remove_node("concept_ofdm")
        assert removed is True
        assert populated_store.get_node("concept_ofdm") is None
        assert populated_store.edge_count < initial_edges

    def test_save_and_load(self, populated_store):
        """验证 JSON 持久化"""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            temp_path = Path(f.name)

        try:
            # 保存
            populated_store.save(temp_path)
            assert temp_path.exists()

            # 验证 JSON 可读
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["metadata"]["node_count"] == populated_store.node_count

            # 加载到新实例
            new_store = KnowledgeGraphStore()
            new_store.load(temp_path)
            assert new_store.node_count == populated_store.node_count
            assert new_store.edge_count == populated_store.edge_count
        finally:
            temp_path.unlink(missing_ok=True)

    def test_get_stats(self, populated_store):
        """验证统计摘要"""
        stats = populated_store.get_stats()
        assert stats["total_nodes"] == 5
        assert stats["total_edges"] == 3
        assert "concept" in stats["node_types"]
        assert "proposes" in stats["edge_types"]

    def test_to_markdown(self, populated_store):
        """验证 Markdown 输出"""
        md = populated_store.to_markdown()
        assert "知识图谱概览" in md
        assert "节点类型分布" in md
        assert "关系类型分布" in md

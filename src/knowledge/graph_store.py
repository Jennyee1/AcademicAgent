from __future__ import annotations

"""
ScholarMind - 知识图谱存储模块
================================

基于 NetworkX DiGraph 的知识图谱存储引擎。

功能：
  1. 节点/边的 CRUD（去重合并）
  2. 多种查询方式（邻居、类型、关键词）
  3. JSON 持久化（save/load）
  4. 图谱统计与可视化摘要

设计原则：
  - MVP 阶段用 NetworkX + JSON 文件，<100 篇论文场景足够
  - API 设计对标 Neo4j，后续迁移成本低
  - 所有写操作自动去重（同 ID 节点合并属性）

【工程思考】为什么用 DiGraph（有向图）而不是 Graph（无向图）？
  因为学术关系是有方向的：
  - Paper A `proposes` Method B（反过来不成立）
  - Method X `improves` Method Y（反过来语义不同）
  - Concept A `belongs_to` Concept B（层级关系有方向）
"""

import json
import logging
from pathlib import Path
from collections import Counter

import networkx as nx

from .schema import KGNode, KGEdge, NodeType, RelationType

logger = logging.getLogger("ScholarMind.GraphStore")


class KnowledgeGraphStore:
    """
    知识图谱存储引擎

    Usage:
        store = KnowledgeGraphStore()
        store.add_node(KGNode(label="OFDM", node_type=NodeType.CONCEPT))
        store.add_node(KGNode(label="MIMO", node_type=NodeType.CONCEPT))
        store.add_edge(KGEdge(
            source_id="concept_ofdm",
            target_id="concept_mimo",
            relation_type=RelationType.RELATED_TO,
        ))
        store.save("data/knowledge_graph.json")

    【工程思考】为什么不直接用 networkx.readwrite.json_graph？
    因为我们需要保留自定义的 KGNode/KGEdge 元信息，
    而 networkx 的 JSON 序列化会丢失自定义类。
    """

    def __init__(self, graph_path: str | Path | None = None):
        """
        初始化知识图谱存储

        Args:
            graph_path: JSON 持久化文件路径。如果文件存在则自动加载。
        """
        self._graph = nx.DiGraph()
        self._nodes: dict[str, KGNode] = {}  # node_id → KGNode
        self._edges: dict[str, KGEdge] = {}  # edge_id → KGEdge
        self._graph_path = Path(graph_path) if graph_path else None

        if self._graph_path and self._graph_path.exists():
            self.load(self._graph_path)
            logger.info(
                f"加载知识图谱: {self.node_count} 节点, {self.edge_count} 边"
            )

    # ============================================================
    # 写操作
    # ============================================================

    def add_node(self, node: KGNode) -> str:
        """
        添加节点（自动去重合并）

        如果同 ID 节点已存在，合并其属性。
        返回节点 ID。
        """
        node_id = node.node_id

        if node_id in self._nodes:
            # 已存在 → 合并属性
            existing = self._nodes[node_id]
            existing.merge_properties(node.properties)
            # 更新 source_paper（追加来源）
            if node.source_paper and node.source_paper not in existing.properties.get(
                "source_papers", []
            ):
                if "source_papers" not in existing.properties:
                    existing.properties["source_papers"] = []
                    if existing.source_paper:
                        existing.properties["source_papers"].append(
                            existing.source_paper
                        )
                existing.properties["source_papers"].append(node.source_paper)
            logger.debug(f"节点合并: {node_id} (label={node.label})")
        else:
            # 新节点
            self._nodes[node_id] = node
            self._graph.add_node(
                node_id,
                label=node.label,
                node_type=node.node_type.value,
            )
            logger.debug(f"新增节点: {node_id} (label={node.label})")

        return node_id

    def add_edge(self, edge: KGEdge) -> str:
        """
        添加边（自动去重）

        如果同 ID 边已存在，更新置信度（取较高值）。
        返回边 ID。
        """
        edge_id = edge.edge_id

        # 确保源节点和目标节点存在
        if edge.source_id not in self._nodes:
            logger.warning(f"源节点不存在: {edge.source_id}，边 {edge_id} 未添加")
            return ""
        if edge.target_id not in self._nodes:
            logger.warning(f"目标节点不存在: {edge.target_id}，边 {edge_id} 未添加")
            return ""

        if edge_id in self._edges:
            # 已存在 → 更新置信度
            existing = self._edges[edge_id]
            existing.confidence = max(existing.confidence, edge.confidence)
            logger.debug(f"边去重: {edge_id}")
        else:
            # 新边
            self._edges[edge_id] = edge
            self._graph.add_edge(
                edge.source_id,
                edge.target_id,
                relation_type=edge.relation_type.value,
                confidence=edge.confidence,
            )
            logger.debug(f"新增边: {edge_id}")

        return edge_id

    def remove_node(self, node_id: str) -> bool:
        """删除节点及其关联的所有边"""
        if node_id not in self._nodes:
            return False

        # 删除关联边
        edges_to_remove = [
            eid
            for eid, edge in self._edges.items()
            if edge.source_id == node_id or edge.target_id == node_id
        ]
        for eid in edges_to_remove:
            del self._edges[eid]

        del self._nodes[node_id]
        self._graph.remove_node(node_id)
        logger.info(f"删除节点: {node_id} (关联边: {len(edges_to_remove)} 条)")
        return True

    # ============================================================
    # 查询操作
    # ============================================================

    def get_node(self, node_id: str) -> KGNode | None:
        """根据 ID 获取节点"""
        return self._nodes.get(node_id)

    def query_neighbors(
        self,
        node_id: str,
        depth: int = 1,
        relation_type: RelationType | None = None,
    ) -> list[tuple[KGNode, KGEdge]]:
        """
        查询节点的邻居（支持多跳）

        Args:
            node_id: 起始节点 ID
            depth: 查询深度（1=直接邻居, 2=两跳邻居...）
            relation_type: 可选，过滤特定关系类型

        Returns:
            list of (邻居节点, 连接边) 元组
        """
        if node_id not in self._graph:
            return []

        results = []
        visited = {node_id}

        # BFS
        current_level = {node_id}
        for _ in range(depth):
            next_level = set()
            for nid in current_level:
                # 出边（successor）
                for successor in self._graph.successors(nid):
                    if successor not in visited:
                        edge_data = self._graph.edges[nid, successor]
                        if relation_type and edge_data.get(
                            "relation_type"
                        ) != relation_type.value:
                            continue
                        node = self._nodes.get(successor)
                        edge = self._find_edge(nid, successor)
                        if node and edge:
                            results.append((node, edge))
                        visited.add(successor)
                        next_level.add(successor)
                # 入边（predecessor）
                for predecessor in self._graph.predecessors(nid):
                    if predecessor not in visited:
                        edge_data = self._graph.edges[predecessor, nid]
                        if relation_type and edge_data.get(
                            "relation_type"
                        ) != relation_type.value:
                            continue
                        node = self._nodes.get(predecessor)
                        edge = self._find_edge(predecessor, nid)
                        if node and edge:
                            results.append((node, edge))
                        visited.add(predecessor)
                        next_level.add(predecessor)
            current_level = next_level

        return results

    def query_by_type(self, node_type: NodeType) -> list[KGNode]:
        """查询指定类型的所有节点"""
        return [
            node
            for node in self._nodes.values()
            if node.node_type == node_type
        ]

    def search_nodes(self, keyword: str) -> list[KGNode]:
        """
        关键词搜索节点

        在节点的 label 和 properties 中搜索关键词（大小写不敏感）
        """
        keyword_lower = keyword.lower()
        results = []
        for node in self._nodes.values():
            # 搜索 label
            if keyword_lower in node.label.lower():
                results.append(node)
                continue
            # 搜索 properties 中的字符串值
            for value in node.properties.values():
                if isinstance(value, str) and keyword_lower in value.lower():
                    results.append(node)
                    break
        return results

    def get_edges_for_node(self, node_id: str) -> list[KGEdge]:
        """获取与某节点相关的所有边"""
        return [
            edge
            for edge in self._edges.values()
            if edge.source_id == node_id or edge.target_id == node_id
        ]

    def _find_edge(
        self, source_id: str, target_id: str
    ) -> KGEdge | None:
        """查找两个节点之间的边"""
        for edge in self._edges.values():
            if edge.source_id == source_id and edge.target_id == target_id:
                return edge
        return None

    # ============================================================
    # 持久化
    # ============================================================

    def save(self, path: str | Path | None = None) -> Path:
        """
        保存知识图谱到 JSON 文件

        【工程思考】为什么用 JSON 而不是 pickle/GraphML？
        1. JSON 人类可读，方便调试和 Git diff
        2. 跨语言兼容（未来可能有 JS 前端可视化）
        3. 数据量小（<100 篇论文），性能不是问题
        """
        save_path = Path(path) if path else self._graph_path
        if not save_path:
            raise ValueError("未指定保存路径")

        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "metadata": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "version": "1.0",
            },
            "nodes": [node.to_dict() for node in self._nodes.values()],
            "edges": [edge.to_dict() for edge in self._edges.values()],
        }

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(
            f"知识图谱已保存: {save_path} "
            f"({self.node_count} 节点, {self.edge_count} 边)"
        )
        return save_path

    def load(self, path: str | Path) -> None:
        """从 JSON 文件加载知识图谱"""
        load_path = Path(path)
        if not load_path.exists():
            raise FileNotFoundError(f"图谱文件不存在: {load_path}")

        with open(load_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 清空当前图谱
        self._graph.clear()
        self._nodes.clear()
        self._edges.clear()

        # 加载节点
        for node_data in data.get("nodes", []):
            node = KGNode.from_dict(node_data)
            self._nodes[node.node_id] = node
            self._graph.add_node(
                node.node_id,
                label=node.label,
                node_type=node.node_type.value,
            )

        # 加载边
        for edge_data in data.get("edges", []):
            edge = KGEdge.from_dict(edge_data)
            self._edges[edge.edge_id] = edge
            if (
                edge.source_id in self._graph
                and edge.target_id in self._graph
            ):
                self._graph.add_edge(
                    edge.source_id,
                    edge.target_id,
                    relation_type=edge.relation_type.value,
                    confidence=edge.confidence,
                )

        logger.info(
            f"知识图谱已加载: {load_path} "
            f"({self.node_count} 节点, {self.edge_count} 边)"
        )

    # ============================================================
    # 统计与摘要
    # ============================================================

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def get_stats(self) -> dict:
        """获取图谱统计信息"""
        node_type_counts = Counter(
            node.node_type.value for node in self._nodes.values()
        )
        edge_type_counts = Counter(
            edge.relation_type.value for edge in self._edges.values()
        )

        # 高度中心性（最"重要"的节点）
        top_nodes = []
        if self._graph.nodes():
            degree_dict = dict(self._graph.degree())
            sorted_nodes = sorted(
                degree_dict.items(), key=lambda x: x[1], reverse=True
            )[:10]
            for node_id, degree in sorted_nodes:
                node = self._nodes.get(node_id)
                if node:
                    top_nodes.append(
                        {
                            "label": node.label,
                            "type": node.node_type.value,
                            "degree": degree,
                        }
                    )

        return {
            "total_nodes": self.node_count,
            "total_edges": self.edge_count,
            "node_types": dict(node_type_counts),
            "edge_types": dict(edge_type_counts),
            "top_nodes": top_nodes,
            "connected_components": (
                nx.number_weakly_connected_components(self._graph)
                if self._graph.nodes()
                else 0
            ),
        }

    def to_markdown(self) -> str:
        """生成图谱的 Markdown 摘要"""
        stats = self.get_stats()

        node_table = "\n".join(
            f"| {t} | {c} |"
            for t, c in stats["node_types"].items()
        )
        edge_table = "\n".join(
            f"| {t} | {c} |"
            for t, c in stats["edge_types"].items()
        )

        top_nodes_str = "\n".join(
            f"  - **{n['label']}** ({n['type']}, 度={n['degree']})"
            for n in stats["top_nodes"][:5]
        )

        return (
            f"## 📊 知识图谱概览\n\n"
            f"| 统计项 | 值 |\n"
            f"|:---|:---|\n"
            f"| **总节点数** | {stats['total_nodes']} |\n"
            f"| **总关系数** | {stats['total_edges']} |\n"
            f"| **连通分量** | {stats['connected_components']} |\n\n"
            f"### 节点类型分布\n"
            f"| 类型 | 数量 |\n|:---|:---|\n{node_table}\n\n"
            f"### 关系类型分布\n"
            f"| 类型 | 数量 |\n|:---|:---|\n{edge_table}\n\n"
            f"### 核心节点 (Top 5)\n"
            f"{top_nodes_str}\n"
        )

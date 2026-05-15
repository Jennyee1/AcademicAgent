from __future__ import annotations

"""
ScholarMind - 知识图谱存储模块
================================

基于 NetworkX DiGraph 的知识图谱存储引擎。

功能：
  1. 节点/边的 CRUD（去重合并）
  2. 多种查询方式（邻居、类型、关键词、TF-IDF 语义检索）
  3. JSON 持久化（save/load）
  4. 图谱统计与可视化摘要
  5. Markdown 导出（MemU 可审计范式）

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
        store.add_node(KGNode(label="ReAct", node_type=NodeType.CONCEPT))
        store.add_node(KGNode(label="MemGPT", node_type=NodeType.CONCEPT))
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
            # 在真实的业务场景（如内容安全风控）中，我们需要引入 证据积累模型 或 多源冲突消解机制，而不是简单的取最大值
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

    # ============================================================
    # 语义检索（ReMe hybrid retrieval 思想）
    # ============================================================
    def semantic_search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        基于 TF-IDF 的语义检索——零 API 调用、零 Token 消耗、零新依赖。

        【工程思考】为什么用 TF-IDF 而不是 Embedding？
          - 在 <500 节点规模下，TF-IDF 与 Embedding 检索质量差距很小
          - TF-IDF 纯本地计算，不需要外部 API 或 ChromaDB
          - 框架灵感：ReMe 的 hybrid retrieval，兼顾精确度和成本

        Args:
            query: 搜索查询（支持中英文）
            top_k: 返回前 K 个最相关的节点

        Returns:
            排序后的节点字典列表，包含 similarity 分数
        """
        nodes = list(self._nodes.values())
        if not nodes:
            return []

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            logger.warning("scikit-learn 未安装，回退到关键词匹配")
            return self._keyword_fallback(query, top_k)

        # 构建语料：label + description + source_paper
        corpus = []
        for n in nodes:
            desc = n.properties.get("description", "")
            if isinstance(desc, dict):
                desc = str(desc)
            text = f"{n.label} {desc} {n.source_paper}"
            corpus.append(text)

        # TF-IDF 向量化 + 余弦相似度
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(corpus + [query])
        similarities = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])[0]

        # 取 Top K
        top_indices = similarities.argsort()[-top_k:][::-1]
        results = []
        for i in top_indices:
            if similarities[i] > 0:  # 只返回有相关性的
                node = nodes[i]
                results.append({
                    "node_id": node.node_id,
                    "label": node.label,
                    "type": node.node_type.value,
                    "similarity": round(float(similarities[i]), 4),
                    "source_paper": node.source_paper,
                    "first_seen_year": node.first_seen_year,
                })
        return results

    def _keyword_fallback(self, query: str, top_k: int) -> list[dict]:
        """关键词匹配回退（无 scikit-learn 时使用）"""
        query_lower = query.lower()
        results = []
        for node in self._nodes.values():
            label_lower = node.label.lower()
            desc = str(node.properties.get("description", "")).lower()
            if query_lower in label_lower or query_lower in desc:
                results.append({
                    "node_id": node.node_id,
                    "label": node.label,
                    "type": node.node_type.value,
                    "similarity": 1.0 if query_lower in label_lower else 0.5,
                    "source_paper": node.source_paper,
                    "first_seen_year": node.first_seen_year,
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    # ============================================================
    # Markdown 导出（MemU 可审计范式）
    # ============================================================
    def export_to_markdown(self, output_dir: str | Path) -> dict[str, int]:
        """
        将知识图谱导出为人类可读的 Markdown 文件。

        【MemU 思想】知识图谱的“可审计视图”：
          - knowledge_graph.json → 机器读（NetworkX 图算法）
          - knowledge_export/*.md → 人读（用户浏览自己的知识库）

        Args:
            output_dir: 输出目录（如 memory/knowledge_export/）

        Returns:
            导出统计：{"concepts": N, "papers": N, "methods": N, ...}
        """
        output_dir = Path(output_dir)
        stats = {}

        # 按节点类型分组导出
        type_groups: dict[str, list[KGNode]] = {}
        for node in self._nodes.values():
            type_name = node.node_type.value
            if type_name not in type_groups:
                type_groups[type_name] = []
            type_groups[type_name].append(node)

        for type_name, nodes in type_groups.items():
            type_dir = output_dir / f"{type_name}s"
            type_dir.mkdir(parents=True, exist_ok=True)
            stats[type_name] = len(nodes)

            for node in nodes:
                # 文件名安全化
                safe_name = node.label.replace("/", "_").replace("\\", "_")[:50]
                filepath = type_dir / f"{safe_name}.md"

                # 查找该节点的关联节点
                neighbors = []
                for edge in self._edges.values():
                    if edge.source_id == node.node_id:
                        target = self._nodes.get(edge.target_id)
                        if target:
                            neighbors.append(
                                f"- **{edge.relation_type.value}** → [{target.label}](../{target.node_type.value}s/{target.label.replace('/', '_')[:50]}.md)"
                            )
                    elif edge.target_id == node.node_id:
                        source = self._nodes.get(edge.source_id)
                        if source:
                            neighbors.append(
                                f"- [{source.label}](../{source.node_type.value}s/{source.label.replace('/', '_')[:50]}.md) **{edge.relation_type.value}** →"
                            )

                # 生成 Markdown
                lines = [
                    f"# {node.label}\n",
                    f"**类型**: {node.node_type.value}",
                ]
                if node.first_seen_year:
                    lines.append(f"**首次出现**: {node.first_seen_year} 年")
                if node.superseded_by:
                    lines.append(f"**已被取代**: {node.superseded_by}")
                if node.source_paper:
                    lines.append(f"**来源论文**: {node.source_paper}")

                # 属性
                if node.properties:
                    lines.append("\n## 属性")
                    for k, v in node.properties.items():
                        lines.append(f"- **{k}**: {v}")

                # 关联
                if neighbors:
                    lines.append("\n## 关联关系")
                    lines.extend(neighbors)

                filepath.write_text("\n".join(lines), encoding="utf-8")

        logger.info(f"知识图谱已导出到 {output_dir}，统计: {stats}")
        return stats

    # ============================================================
    # 交互式可视化（pyvis）
    # ============================================================

    def visualize(self, output_path: str = "data/kg_visualization.html") -> str:
        """
        生成交互式知识图谱 HTML（pyvis 力导向图 + 图例 + 说明 + 筛选）

        在浏览器中打开生成的 HTML 即可交互：
        - 拖拽节点 / 缩放画布
        - 悬停查看详情（类型、年份、录入时间）
        - 通过图例按类型筛选节点

        Args:
            output_path: HTML 输出路径

        Returns:
            输出文件的绝对路径
        """
        try:
            from pyvis.network import Network
        except ImportError:
            logger.error("pyvis 未安装。请运行: pip install pyvis")
            return ""

        if self.node_count == 0:
            logger.warning("知识图谱为空，无法生成可视化")
            return ""

        net = Network(
            height="650px",
            width="100%",
            directed=True,
            notebook=False,
            bgcolor="#f8fafc",
            font_color="#1e293b",
        )

        # 节点颜色映射（按类型区分，明亮风格）
        color_map = {
            "paper":   "#2563eb",  # 蓝色 — 论文
            "concept": "#dc2626",  # 红色 — 概念
            "method":  "#0891b2",  # 青色 — 方法
            "author":  "#6b7280",  # 灰色 — 作者
            "metric":  "#d97706",  # 琥珀 — 指标
            "dataset": "#7c3aed",  # 紫色 — 数据集
            "tool":    "#059669",  # 绿色 — 工具
        }

        type_labels = {
            "paper": "📄 论文", "concept": "💡 概念", "method": "⚙️ 方法",
            "author": "👤 作者", "metric": "📏 指标", "dataset": "📊 数据集",
            "tool": "🔧 工具",
        }

        # 统计各类型数量
        type_counts: dict[str, int] = {}
        for node in self._nodes.values():
            t = node.node_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        # 构建每个类型的节点列表（供图例下拉用）
        import json as _json
        type_node_lists: dict[str, list[dict]] = {}
        for t in type_labels:
            type_node_lists[t] = []

        # 添加节点
        for node_id, node in self._nodes.items():
            node_type_str = node.node_type.value
            color = color_map.get(node_type_str, "#94a3b8")

            degree = self._graph.degree(node_id) if node_id in self._graph else 1

            # 构建 tooltip 数据（用 JSON 存储，由自定义 JS 解析渲染）
            tooltip_data = {
                "name": node.label,
                "type": type_labels.get(node_type_str, node_type_str),
                "color": color,
            }
            if node.first_seen_year:
                tooltip_data["year"] = node.first_seen_year
            if node.created_at:
                tooltip_data["added"] = node.created_at[:10]
            if node.source_paper:
                tooltip_data["source"] = node.source_paper[:60]
            for key in ("description", "definition", "category"):
                val = node.properties.get(key)
                if val and isinstance(val, str):
                    tooltip_data["desc"] = val[:100] + ("..." if len(val) > 100 else "")
                    break
            tooltip_data["degree"] = degree
            tooltip_data["ntype"] = node_type_str

            # 将 JSON 存入 title（自定义 JS 会解析它）
            title_json = _json.dumps(tooltip_data, ensure_ascii=False)

            # 节点大小
            size = max(12, min(55, 8 + degree * 4))
            if node_type_str == "author":
                size = max(10, min(20, 8 + degree * 2))

            # 字号按度数缩放：度越高字越大
            short_label = node.label if len(node.label) <= 22 else node.label[:19] + "..."
            font_size = max(12, min(30, 10 + degree * 2))

            net.add_node(
                node_id,
                label=short_label,
                color=color,
                title=title_json,
                size=size,
                font={"size": font_size,
                      "color": "#1e293b",
                      "strokeWidth": 3,
                      "strokeColor": "#ffffff"},
                borderWidth=2,
                borderWidthSelected=4,
            )

            # 收集到类型列表
            if node_type_str in type_node_lists:
                type_node_lists[node_type_str].append({
                    "id": node_id,
                    "label": node.label,
                    "degree": degree,
                })

        # 按度数排序每个类型的列表
        for t in type_node_lists:
            type_node_lists[t].sort(key=lambda x: x["degree"], reverse=True)

        # 添加边
        for edge in self._edges.values():
            if edge.source_id in self._nodes and edge.target_id in self._nodes:
                rel_label = edge.relation_type.value.replace("_", " ")
                net.add_edge(
                    edge.source_id,
                    edge.target_id,
                    title=rel_label,
                    label="",
                    color="#94a3b888",
                    arrows="to",
                    width=1.5,
                )

        # 物理引擎配置
        net.set_options("""
        {
            "physics": {
                "forceAtlas2Based": {
                    "gravitationalConstant": -80,
                    "centralGravity": 0.008,
                    "springLength": 160,
                    "springConstant": 0.04,
                    "avoidOverlap": 0.8
                },
                "solver": "forceAtlas2Based",
                "stabilization": {"iterations": 200}
            },
            "edges": {
                "smooth": {"type": "continuous"},
                "font": {"size": 0}
            },
            "interaction": {
                "hover": true,
                "tooltipDelay": 9999999,
                "zoomView": true,
                "dragView": true
            },
            "nodes": {
                "shape": "dot",
                "font": {"face": "Segoe UI, Microsoft YaHei, sans-serif"}
            }
        }
        """)

        # 生成 pyvis 的原始 HTML
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        net.save_graph(str(output))

        # 读取并注入自定义包装
        raw_html = output.read_text(encoding="utf-8")

        # --- 构建图例 HTML（含下拉列表）---
        legend_items = ""
        for t, label in type_labels.items():
            c = color_map.get(t, "#94a3b8")
            count = type_counts.get(t, 0)
            if count <= 0:
                continue
            nodes_in_type = type_node_lists.get(t, [])
            dropdown_items = "".join(
                f'<div class="dropdown-node" data-node-id="{n["id"]}">'
                f'{n["label"]} <span class="dd-degree">度={n["degree"]}</span></div>'
                for n in nodes_in_type
            )
            legend_items += (
                f'<div class="legend-group" data-type="{t}">'
                f'<label class="legend-item">'
                f'<input type="checkbox" class="type-toggle" data-type="{t}" checked '
                f'style="margin:0 2px 0 0;cursor:pointer;">'
                f'<span class="legend-dot" style="background:{c}"></span>'
                f'{label} ({count})</label>'
                f'<div class="legend-dropdown">{dropdown_items}</div>'
                f'</div>'
            )

        # 年份分布
        years = {}
        for n in self._nodes.values():
            if n.first_seen_year:
                y = str(n.first_seen_year)
                years[y] = years.get(y, 0) + 1
        year_info = " · ".join(f"{y}年: {c}个" for y, c in sorted(years.items()))

        # JSON for JS interaction
        type_nodes_json = _json.dumps(type_node_lists, ensure_ascii=False)

        custom_css = """
        <style>
          body { margin: 0; font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f5f7fb; }
          .kg-header { background: linear-gradient(135deg, #2563eb, #0891b2); color: white; padding: 1.2rem 2rem; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
          .kg-header h1 { font-size: 1.3rem; margin: 0 0 0.3rem; }
          .kg-header .meta { opacity: 0.85; font-size: 0.85rem; }
          .kg-header .nav-back { color: white; text-decoration: none; font-size: 0.85rem; opacity: 0.8; }
          .kg-header .nav-back:hover { opacity: 1; text-decoration: underline; }
          .kg-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; background: white; padding: 0.6rem 2rem; border-bottom: 1px solid #e2e8f0; font-size: 0.85rem; }
          .legend-group { position: relative; display: inline-block; }
          .legend-item { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 6px; color: #374151; cursor: pointer; transition: background 0.15s; }
          .legend-item:hover { background: #f0f4f8; }
          .legend-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
          .legend-dropdown { display: none; position: absolute; top: 100%; left: 0; z-index: 999; background: white; border: 1px solid #e2e8f0; border-radius: 10px; box-shadow: 0 8px 30px rgba(0,0,0,0.12); min-width: 240px; max-height: 280px; overflow-y: auto; padding: 6px 0; }
          .legend-group:hover .legend-dropdown { display: block; }
          .dropdown-node { padding: 6px 14px; cursor: pointer; font-size: 0.82rem; transition: background 0.1s; display: flex; justify-content: space-between; align-items: center; }
          .dropdown-node:hover { background: #eff6ff; color: #2563eb; }
          .dd-degree { font-size: 0.7rem; color: #94a3b8; }
          .kg-tip { background: #fffbeb; border-top: 1px solid #fde68a; padding: 0.5rem 2rem; font-size: 0.78rem; color: #92400e; }
          .kg-footer { text-align: center; padding: 0.6rem; font-size: 0.72rem; color: #94a3b8; border-top: 1px solid #e2e8f0; background: white; }
          #mynetwork { border: none !important; }
          /* 自定义 tooltip 浮层 */
          #kg-tooltip {
            display: none; position: fixed; z-index: 10000;
            background: white; border: 1px solid #e2e8f0; border-radius: 12px;
            box-shadow: 0 8px 30px rgba(0,0,0,0.12); padding: 14px 18px;
            min-width: 220px; max-width: 340px; pointer-events: none;
            font-size: 0.85rem; line-height: 1.6;
          }
          #kg-tooltip .tt-name { font-size: 1.05rem; font-weight: 700; margin-bottom: 6px; }
          #kg-tooltip .tt-type { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600; margin-bottom: 8px; }
          #kg-tooltip .tt-row { display: flex; align-items: center; gap: 6px; color: #475569; font-size: 0.82rem; margin: 3px 0; }
          #kg-tooltip .tt-row .tt-icon { width: 16px; text-align: center; flex-shrink: 0; }
          #kg-tooltip .tt-desc { margin-top: 8px; padding-top: 8px; border-top: 1px solid #f1f5f9; color: #64748b; font-size: 0.8rem; }
          #kg-tooltip .tt-bar { height: 3px; border-radius: 2px; margin-top: 8px; }
        </style>
        """

        header_html = f"""
        {custom_css}
        <div class="kg-header">
          <a class="nav-back" href="dashboard.html">← 返回 Dashboard</a>
          <h1>🕸️ 知识图谱交互式可视化</h1>
          <div class="meta">{self.node_count} 个节点 · {self.edge_count} 条关系 · {len(type_counts)} 种类型 · 全连通</div>
        </div>
        <div class="kg-bar">
          <span style="font-weight:600;color:#2563eb;margin-right:4px;">图例：</span>
          {legend_items}
          <span style="margin-left:auto;color:#6b7280;font-size:0.78rem;">年份: {year_info}</span>
        </div>
        <div class="kg-tip">
          💡 <b>操作提示</b>：滚轮缩放 · 拖拽画布 · 拖拽节点 · 悬停节点查看详情 · 悬停图例展开列表 · 点击列表项定位高亮
          <span style="margin-left:auto;display:inline-flex;align-items:center;gap:6px;">
            🔤 字号：<input type="range" id="fontSlider" min="6" max="40" value="22" style="width:100px;cursor:pointer;"><span id="fontVal" style="min-width:28px">22</span>
          </span>
        </div>
        <div id="kg-tooltip"></div>
        """

        footer_html = f"""
        <div class="kg-footer">
          ScholarMind 知识图谱 · {self.node_count} nodes / {self.edge_count} edges · 节点大小=连接度 · 度≥4 显示标签
        </div>
        """

        # 自定义 JS：tooltip 浮层 + 图例交互
        custom_js = f"""
        <script>
        (function() {{
          var tooltip = document.getElementById('kg-tooltip');
          var net = network;  // pyvis 暴露的全局变量

          // --- 1. 自定义 Tooltip ---
          net.on('hoverNode', function(params) {{
            var nodeId = params.node;
            var nodeData = net.body.data.nodes.get(nodeId);
            if (!nodeData || !nodeData.title) return;
            try {{
              var d = JSON.parse(nodeData.title);
              var html = '<div class="tt-name" style="color:' + (d.color||'#333') + '">' + d.name + '</div>';
              html += '<span class="tt-type" style="background:' + (d.color||'#333') + '22;color:' + (d.color||'#333') + '">' + (d.type||'') + '</span>';
              if (d.year) html += '<div class="tt-row"><span class="tt-icon">📅</span> 首次出现: ' + d.year + ' 年</div>';
              if (d.added) html += '<div class="tt-row"><span class="tt-icon">🕐</span> 录入时间: ' + d.added + '</div>';
              if (d.source) html += '<div class="tt-row"><span class="tt-icon">📎</span> 来源: ' + d.source + '</div>';
              html += '<div class="tt-row"><span class="tt-icon">🔗</span> 连接数: ' + (d.degree||0) + '</div>';
              if (d.desc) html += '<div class="tt-desc">📝 ' + d.desc + '</div>';
              html += '<div class="tt-bar" style="background:' + (d.color||'#333') + '"></div>';
              tooltip.innerHTML = html;
              tooltip.style.display = 'block';
            }} catch(e) {{}}
          }});

          net.on('blurNode', function() {{
            tooltip.style.display = 'none';
          }});

          // 鼠标移动时更新 tooltip 位置
          document.getElementById('mynetwork').addEventListener('mousemove', function(e) {{
            if (tooltip.style.display === 'block') {{
              var x = e.clientX + 15;
              var y = e.clientY + 15;
              if (x + 350 > window.innerWidth) x = e.clientX - 260;
              if (y + 200 > window.innerHeight) y = e.clientY - 180;
              tooltip.style.left = x + 'px';
              tooltip.style.top = y + 'px';
            }}
          }});

          // --- 2. 图例下拉：点击节点项 → 高亮并聚焦 ---
          document.querySelectorAll('.dropdown-node').forEach(function(el) {{
            el.addEventListener('click', function(e) {{
              e.stopPropagation();
              var nodeId = this.getAttribute('data-node-id');
              net.selectNodes([nodeId]);
              net.focus(nodeId, {{
                scale: 1.5,
                animation: {{duration: 600, easingFunction: 'easeInOutQuad'}}
              }});
            }});
          }});

          // --- 3. 字号滑块 ---
          var slider = document.getElementById('fontSlider');
          var fontVal = document.getElementById('fontVal');
          // 记录每个节点的原始字号和类型
          var origFonts = {{}};
          var nodeTypes = {{}};
          var hiddenTypes = {{}};
          net.body.data.nodes.forEach(function(node) {{
            origFonts[node.id] = (node.font && node.font.size) || 14;
            try {{ nodeTypes[node.id] = JSON.parse(node.title).ntype || ''; }} catch(e) {{ nodeTypes[node.id] = ''; }}
          }});

          if (slider) {{
            slider.addEventListener('input', function() {{
              var scale = parseInt(this.value) / 22.0;  // 22 是基准
              fontVal.textContent = parseInt(this.value);
              var allNodes = net.body.data.nodes;
              var updates = [];
              allNodes.forEach(function(node) {{
                var hidden = hiddenTypes[nodeTypes[node.id]];
                var newSize = hidden ? 0 : Math.round(origFonts[node.id] * scale);
                updates.push({{id: node.id, font: {{size: newSize}}}});
              }});
              allNodes.update(updates);
            }});
          }}

          // --- 4. Checkbox 切换类型标签显示/隐藏 ---
          document.querySelectorAll('.type-toggle').forEach(function(cb) {{
            cb.addEventListener('change', function() {{
              var type = this.getAttribute('data-type');
              var show = this.checked;
              hiddenTypes[type] = !show;
              var scale = slider ? parseInt(slider.value) / 22.0 : 1.0;
              var allNodes = net.body.data.nodes;
              var updates = [];
              allNodes.forEach(function(node) {{
                if (nodeTypes[node.id] === type) {{
                  var newSize = show ? Math.round(origFonts[node.id] * scale) : 0;
                  updates.push({{id: node.id, font: {{size: newSize}}}});
                }}
              }});
              allNodes.update(updates);
            }});
          }});
        }})();
        </script>
        """

        # 注入到 pyvis 生成的 HTML 中
        enhanced = raw_html.replace("<body>", f"<body>\n{header_html}\n", 1)
        enhanced = enhanced.replace("</body>", f"\n{footer_html}\n{custom_js}\n</body>", 1)

        output.write_text(enhanced, encoding="utf-8")
        logger.info(f"知识图谱可视化已保存: {output} ({self.node_count} 节点, {self.edge_count} 边)")
        return str(output.resolve())

from __future__ import annotations

import sys
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

"""
ScholarMind - 学习路径规划 MCP Server
========================================

功能：
  1. analyze_knowledge     — 生成学习路径推荐
  2. detect_gaps           — 检测知识盲区
  3. get_concept_importance — 查看概念重要性排名

技术架构：
  用户请求 → Claude Code → MCP Protocol → 本 Server
                                          ├── graph_analyzer.py (图分析算法)
                                          └── graph_store.py (图谱数据)

【工程思考】为什么学习路径单独一个 MCP Server？
  1. 职责分离: knowledge_graph.py 负责"存", learning_path.py 负责"用"
  2. 可独立演进: 学习路径算法可能频繁调优，不影响图谱存取
  3. 可独立部署: 未来可能用 GPU 做图分析，需要单独进程
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.knowledge.graph_store import KnowledgeGraphStore
from src.knowledge.graph_analyzer import KnowledgeGraphAnalyzer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ScholarMind.LearningPath")

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(Path(__file__).parent.parent.parent / "data")))
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"

# ============================================================
# 全局实例
# ============================================================
mcp = FastMCP(
    "ScholarMind-LearningPath",
    instructions=(
        "个性化学习路径规划服务。"
        "基于知识图谱的结构分析，检测知识盲区，"
        "推荐最优学习路径。帮助研究生高效掌握领域知识。"
    ),
)

graph_store = KnowledgeGraphStore(graph_path=GRAPH_PATH)
analyzer = KnowledgeGraphAnalyzer(graph_store)


# ============================================================
# MCP Tools
# ============================================================


@mcp.tool()
async def analyze_knowledge(
    focus_area: str = "",
    max_items: int = 15,
) -> str:
    """
    分析知识图谱并生成个性化学习路径。

    适合使用的场景：
    - 用户说"我接下来应该学什么？"
    - 用户说"帮我规划学习路径"
    - 用户说"我的知识图谱健康度如何？"
    - 需要基于已读论文生成学习建议

    Args:
        focus_area: 可选，聚焦领域（如 "beamforming", "channel estimation"）。
                    留空则分析全部知识。
        max_items: 最大推荐条目数，默认 15

    Returns:
        完整的学习路径报告（包含健康度、盲区、推荐路径）
    """
    logger.info(f"学习路径分析请求: focus='{focus_area}', max={max_items}")

    if graph_store.node_count == 0:
        return (
            "📭 **知识图谱为空**\n\n"
            "还没有任何论文被加入图谱。\n\n"
            "**开始步骤**：\n"
            "1. 使用论文搜索工具找到感兴趣的论文\n"
            "2. 使用论文分析工具解析论文内容\n"
            "3. 使用 `add_paper_to_graph` 将论文知识加入图谱\n"
            "4. 重复 2-3 步至少 3 篇论文\n"
            "5. 再回来使用本工具生成学习路径"
        )

    if graph_store.node_count < 5:
        result = analyzer.generate_learning_path(focus_area, max_items)
        warning = (
            "> ⚠️ **注意**: 当前图谱仅有 "
            f"{graph_store.node_count} 个节点，"
            "建议至少积累 3 篇论文的知识后再生成学习路径，"
            "结果会更准确。\n\n"
        )
        return warning + result.to_markdown()

    result = analyzer.generate_learning_path(focus_area, max_items)
    return result.to_markdown()


@mcp.tool()
async def detect_gaps() -> str:
    """
    检测知识图谱中的知识盲区。

    适合使用的场景：
    - 用户说"我哪些知识薄弱？"
    - 用户说"我还有什么不了解的？"
    - 需要发现知识图谱中的薄弱环节

    Returns:
        知识盲区列表（按严重程度排序）
    """
    logger.info("知识盲区检测请求")

    if graph_store.node_count == 0:
        return (
            "📭 **知识图谱为空**，无法检测盲区。\n\n"
            "请先添加论文到知识图谱。"
        )

    gaps = analyzer.detect_knowledge_gaps()

    if not gaps:
        return (
            "🎉 **暂未发现明显知识盲区！**\n\n"
            "你的知识图谱看起来很健康。继续保持，多读论文！\n\n"
            f"当前图谱: {graph_store.node_count} 个节点, "
            f"{graph_store.edge_count} 个关系"
        )

    result = f"## ⚠️ 知识盲区检测报告\n\n"
    result += f"发现 **{len(gaps)}** 个知识盲区：\n\n"

    # 按类型分组
    by_type: dict[str, list] = {}
    for gap in gaps:
        if gap.gap_type not in by_type:
            by_type[gap.gap_type] = []
        by_type[gap.gap_type].append(gap)

    type_names = {
        "foundation_gap": "🔴 基础概念缺失",
        "isolated_concept": "🟡 孤立概念",
        "single_source": "🟠 单源依赖",
    }

    for gap_type, gap_list in by_type.items():
        result += f"### {type_names.get(gap_type, gap_type)} ({len(gap_list)})\n\n"
        for gap in gap_list:
            severity_bar = "█" * int(gap.severity * 10) + "░" * (10 - int(gap.severity * 10))
            result += (
                f"- **{gap.label}** ({gap.node_type})\n"
                f"  - 严重程度: [{severity_bar}] {gap.severity:.2f}\n"
                f"  - 原因: {gap.reason}\n"
                f"  - 📌 建议: {gap.suggested_action}\n\n"
            )

    return result


@mcp.tool()
async def get_concept_importance(top_n: int = 10) -> str:
    """
    获取知识图谱中概念的重要性排名。

    基于 PageRank + 度中心性 + 介数中心性的综合评分。

    适合使用的场景：
    - 用户说"哪些概念最重要？"
    - 用户说"我的核心知识有哪些？"
    - 需要了解知识图谱的焦点在哪里

    Args:
        top_n: 返回前 N 个最重要的概念，默认 10

    Returns:
        概念重要性排名表
    """
    logger.info(f"概念重要性排名请求: top_n={top_n}")

    if graph_store.node_count == 0:
        return "📭 **知识图谱为空**，无法计算重要性。"

    importance = analyzer.compute_importance()

    if not importance:
        return "知识图谱中没有可分析的节点。"

    result = f"## 🏆 概念重要性排名 (Top {min(top_n, len(importance))})\n\n"
    result += "| 排名 | 概念 | 类型 | 综合评分 | PageRank | 度 | 入度 | 介数中心性 |\n"
    result += "|:---|:---|:---|:---|:---|:---|:---|:---|\n"

    for i, imp in enumerate(importance[:top_n]):
        result += (
            f"| {i + 1} | **{imp.label}** | {imp.node_type} | "
            f"{imp.importance_score:.3f} | {imp.pagerank:.4f} | "
            f"{imp.degree} | {imp.in_degree} | {imp.betweenness:.4f} |\n"
        )

    # 类型分布摘要
    type_counts = Counter(imp.node_type for imp in importance[:top_n])
    result += f"\n**Top {top_n} 类型分布**: "
    result += ", ".join(f"{t}: {c}" for t, c in type_counts.most_common())
    result += "\n"

    return result


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    logger.info("ScholarMind Learning Path MCP Server 启动中...")
    logger.info(f"图谱路径: {GRAPH_PATH}")
    logger.info(
        f"当前图谱: {graph_store.node_count} 节点, "
        f"{graph_store.edge_count} 边"
    )
    mcp.run()

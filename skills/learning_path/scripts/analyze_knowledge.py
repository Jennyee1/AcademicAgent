#!/usr/bin/env python3
"""
ScholarMind Learning Path — CLI Wrapper
=========================================

CLI interface for knowledge graph analysis, used by the Antigravity learning_path Skill.

Usage:
    python analyze_knowledge.py --action learning_path
    python analyze_knowledge.py --action learning_path --focus "beamforming"
    python analyze_knowledge.py --action detect_gaps
    python analyze_knowledge.py --action importance --top 10
"""

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

# Add project root to path (scripts/ -> learning_path/ -> skills/ -> project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os

DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(PROJECT_ROOT / "data")))
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"

from src.knowledge.graph_store import KnowledgeGraphStore
from src.knowledge.graph_analyzer import KnowledgeGraphAnalyzer


def get_analyzer() -> tuple[KnowledgeGraphStore, KnowledgeGraphAnalyzer]:
    """Initialize graph store and analyzer."""
    store = KnowledgeGraphStore(graph_path=GRAPH_PATH)
    analyzer = KnowledgeGraphAnalyzer(store)
    return store, analyzer


def cmd_learning_path(focus: str, max_items: int) -> None:
    """Generate learning path."""
    store, analyzer = get_analyzer()

    if store.node_count == 0:
        print("📭 知识图谱为空，无法生成学习路径。")
        print("请先通过 knowledge-graph MCP 工具添加论文。")
        return

    result = analyzer.generate_learning_path(focus_area=focus, max_items=max_items)
    print(result.to_markdown())


def cmd_detect_gaps() -> None:
    """Detect knowledge gaps."""
    store, analyzer = get_analyzer()

    if store.node_count == 0:
        print("📭 知识图谱为空，无法检测盲区。")
        return

    gaps = analyzer.detect_knowledge_gaps()

    if not gaps:
        print(f"🎉 暂未发现明显知识盲区！")
        print(f"当前图谱: {store.node_count} 个节点, {store.edge_count} 个关系")
        return

    print(f"## ⚠️ 知识盲区检测报告\n")
    print(f"发现 **{len(gaps)}** 个知识盲区：\n")

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
        print(f"### {type_names.get(gap_type, gap_type)} ({len(gap_list)})\n")
        for gap in gap_list:
            severity_bar = "█" * int(gap.severity * 10) + "░" * (10 - int(gap.severity * 10))
            print(f"- **{gap.label}** ({gap.node_type})")
            print(f"  - 严重程度: [{severity_bar}] {gap.severity:.2f}")
            print(f"  - 原因: {gap.reason}")
            print(f"  - 📌 建议: {gap.suggested_action}\n")


def cmd_importance(top_n: int) -> None:
    """Get concept importance ranking."""
    store, analyzer = get_analyzer()

    if store.node_count == 0:
        print("📭 知识图谱为空，无法计算重要性。")
        return

    importance = analyzer.compute_importance()

    if not importance:
        print("知识图谱中没有可分析的节点。")
        return

    display_n = min(top_n, len(importance))
    print(f"## 🏆 概念重要性排名 (Top {display_n})\n")
    print("| 排名 | 概念 | 类型 | 综合评分 | PageRank | 度 | 入度 | 介数中心性 |")
    print("|:---|:---|:---|:---|:---|:---|:---|:---|")

    for i, imp in enumerate(importance[:top_n]):
        print(
            f"| {i + 1} | **{imp.label}** | {imp.node_type} | "
            f"{imp.importance_score:.3f} | {imp.pagerank:.4f} | "
            f"{imp.degree} | {imp.in_degree} | {imp.betweenness:.4f} |"
        )

    type_counts = Counter(imp.node_type for imp in importance[:top_n])
    print(f"\n**Top {top_n} 类型分布**: " + ", ".join(f"{t}: {c}" for t, c in type_counts.most_common()))


def main():
    parser = argparse.ArgumentParser(
        description="ScholarMind Learning Path CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  learning_path  Generate personalized learning path (with health, gaps, recommendations)
  detect_gaps    Detect knowledge gaps (foundation, isolated, single-source)
  importance     Get concept importance ranking (PageRank + centrality)
        """,
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["learning_path", "detect_gaps", "importance"],
        help="Action to perform",
    )
    parser.add_argument("--focus", default="", help="Focus area for learning path (e.g., 'beamforming')")
    parser.add_argument("--max-items", type=int, default=15, help="Max items in learning path")
    parser.add_argument("--top", type=int, default=10, help="Top N for importance ranking")

    args = parser.parse_args()

    try:
        if args.action == "learning_path":
            cmd_learning_path(args.focus, args.max_items)
        elif args.action == "detect_gaps":
            cmd_detect_gaps()
        elif args.action == "importance":
            cmd_importance(args.top)
    except FileNotFoundError as e:
        print(f"⚠️ 知识图谱文件不存在: {e}", file=sys.stderr)
        print("请先通过 knowledge-graph MCP 工具添加论文。")
        sys.exit(1)
    except Exception as e:
        print(f"⚠️ 分析失败: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

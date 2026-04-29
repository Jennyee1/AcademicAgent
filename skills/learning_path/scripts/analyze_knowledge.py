#!/usr/bin/env python3
"""
ScholarMind Learning Path — CLI Wrapper
=========================================

CLI interface for knowledge graph analysis, used by the Antigravity learning_path Skill.

Usage:
    python analyze_knowledge.py --action learning_path
    python analyze_knowledge.py --action learning_path --focus "beamforming"
    python analyze_knowledge.py --action learning_path --save    # 持久化为 JSON + HTML
    python analyze_knowledge.py --action detect_gaps
    python analyze_knowledge.py --action detect_gaps --save
    python analyze_knowledge.py --action importance --top 10
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

# Add project root to path (scripts/ -> learning_path/ -> skills/ -> project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os

DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(PROJECT_ROOT / "data")))
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"
REPORTS_DIR = DATA_DIR / "reports" / "learning_paths"

from src.knowledge.graph_store import KnowledgeGraphStore
from src.knowledge.graph_analyzer import KnowledgeGraphAnalyzer


def get_analyzer() -> tuple[KnowledgeGraphStore, KnowledgeGraphAnalyzer]:
    """Initialize graph store and analyzer."""
    store = KnowledgeGraphStore(graph_path=GRAPH_PATH)
    analyzer = KnowledgeGraphAnalyzer(store)
    return store, analyzer


def cmd_learning_path(focus: str, max_items: int, save: bool = False) -> None:
    """Generate learning path."""
    store, analyzer = get_analyzer()

    if store.node_count == 0:
        print("📭 知识图谱为空，无法生成学习路径。")
        print("请先通过 knowledge-graph MCP 工具添加论文。")
        return

    result = analyzer.generate_learning_path(focus_area=focus, max_items=max_items)
    print(result.to_markdown())

    if save:
        report_data = _build_report_data(result, store, focus)
        _save_report(report_data, "learning_path")


def cmd_detect_gaps(save: bool = False) -> None:
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

    if save:
        # Build result-like data for gap report
        from src.knowledge.graph_analyzer import LearningPathResult
        result = LearningPathResult(
            gaps=gaps,
            graph_health={
                "node_count": store.node_count,
                "edge_count": store.edge_count,
            },
        )
        report_data = _build_report_data(result, store, "")
        _save_report(report_data, "gap_detection")


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


# ============================================================
# 报告持久化
# ============================================================

def _build_report_data(result, store, focus: str) -> dict:
    """将 LearningPathResult 转为可序列化的字典"""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "focus_area": focus,
        "graph_health": result.graph_health,
        "node_count": store.node_count,
        "edge_count": store.edge_count,
        "gaps": [
            {
                "label": g.label,
                "node_type": g.node_type,
                "gap_type": g.gap_type,
                "severity": g.severity,
                "reason": g.reason,
                "suggested_action": g.suggested_action,
            }
            for g in result.gaps
        ],
        "path": [
            {
                "order": p.order,
                "label": p.label,
                "node_type": p.node_type,
                "priority": p.priority,
                "reason": p.reason,
                "prerequisites": p.prerequisites,
                "related_papers": p.related_papers[:3],
            }
            for p in result.path
        ] if hasattr(result, 'path') and result.path else [],
    }


def _save_report(report_data: dict, report_type: str) -> None:
    """保存报告为 JSON + HTML"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    base_name = f"{date}_{report_type}"

    # JSON
    json_path = REPORTS_DIR / f"{base_name}.json"
    json_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # HTML
    html_path = REPORTS_DIR / f"{base_name}.html"
    html_content = _render_learning_path_html(report_data, report_type)
    html_path.write_text(html_content, encoding="utf-8")

    print(f"\n📁 报告已保存:")
    print(f"   📄 JSON: {json_path}")
    print(f"   🌐 HTML: {html_path}")


def _render_learning_path_html(data: dict, report_type: str) -> str:
    """渲染学习路径 / 盲区检测的 HTML 报告"""
    title = "学习路径报告" if report_type == "learning_path" else "知识盲区检测报告"
    generated_at = data.get("generated_at", "")[:19]

    # 图谱健康度
    health = data.get("graph_health", {})
    health_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in health.items())

    # 盲区
    gaps = data.get("gaps", [])
    gap_icon_map = {"foundation_gap": "🔴", "isolated_concept": "🟡", "single_source": "🟠"}
    gaps_html = ""
    if gaps:
        gap_items = []
        for g in gaps:
            icon = gap_icon_map.get(g["gap_type"], "⚪")
            severity_pct = int(g["severity"] * 100)
            gap_items.append(
                f"<div class='gap-item'>"
                f"<div class='gap-header'>{icon} <strong>{g['label']}</strong> ({g['node_type']})</div>"
                f"<div class='severity-bar'><div class='severity-fill' style='width:{severity_pct}%'></div></div>"
                f"<p class='gap-reason'>{g['reason']}</p>"
                f"<p class='gap-action'>📌 {g['suggested_action']}</p>"
                f"</div>"
            )
            gaps_html = f"<section><h2>⚠️ 知识盲区 ({len(gaps)})</h2>{''.join(gap_items)}</section>"

    # 学习路径
    path = data.get("path", [])
    path_html = ""
    if path:
        priority_colors = {"critical": "#e17055", "important": "#fdcb6e", "supplementary": "#00b894"}
        path_rows = []
        for p in path:
            color = priority_colors.get(p["priority"], "#888")
            prereqs = ", ".join(p.get("prerequisites", [])[:3]) or "-"
            path_rows.append(
                f"<tr>"
                f"<td>{p['order']}</td>"
                f"<td><strong>{p['label']}</strong></td>"
                f"<td>{p['node_type']}</td>"
                f"<td><span class='priority-badge' style='background:{color}22;color:{color}'>{p['priority']}</span></td>"
                f"<td>{p['reason']}</td>"
                f"<td>{prereqs}</td>"
                f"</tr>"
            )
        path_html = (
            "<section><h2>📚 推荐学习路径</h2>"
            "<table><thead><tr><th>#</th><th>概念</th><th>类型</th><th>优先级</th><th>原因</th><th>前置知识</th></tr></thead>"
            f"<tbody>{''.join(path_rows)}</tbody></table></section>"
        )

    focus_html = f"<p class='focus'>🔍 聚焦领域: <strong>{data['focus_area']}</strong></p>" if data.get("focus_area") else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - ScholarMind</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            line-height: 1.8; color: #1a1a2e;
            background: linear-gradient(135deg, #00b89411, #00cec911);
            min-height: 100vh;
        }}
        .container {{ max-width: 900px; margin: 0 auto; padding: 40px 24px; }}
        header {{
            background: linear-gradient(135deg, #00b894, #00cec9);
            color: white; padding: 36px 32px; border-radius: 16px;
            margin-bottom: 32px; box-shadow: 0 8px 32px rgba(0,184,148,0.3);
        }}
        header h1 {{ font-size: 1.5em; margin-bottom: 8px; }}
        .focus {{ font-size: 1em; opacity: 0.9; margin-top: 8px; }}
        section {{
            background: white; padding: 28px 32px; margin-bottom: 20px;
            border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }}
        section h2 {{
            font-size: 1.2em; margin-bottom: 16px; color: #00b894;
            border-bottom: 2px solid #00b89422; padding-bottom: 8px;
        }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
        th {{ background: #f8f9fa; text-align: left; padding: 10px 12px; border-bottom: 2px solid #ddd; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f8f9ff; }}
        .gap-item {{
            background: #fafafa; padding: 16px; border-radius: 8px;
            margin-bottom: 12px; border-left: 4px solid #e17055;
        }}
        .gap-header {{ font-size: 1.05em; margin-bottom: 8px; }}
        .severity-bar {{
            height: 8px; background: #eee; border-radius: 4px;
            margin: 6px 0; overflow: hidden;
        }}
        .severity-fill {{ height: 100%; background: linear-gradient(90deg, #fdcb6e, #e17055); border-radius: 4px; }}
        .gap-reason {{ color: #666; font-size: 0.9em; }}
        .gap-action {{ color: #00b894; font-size: 0.9em; margin-top: 4px; }}
        .priority-badge {{
            padding: 2px 10px; border-radius: 12px; font-size: 0.85em; font-weight: 600;
        }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }}
        .stat-card {{
            background: #f8f9ff; padding: 16px; border-radius: 8px; text-align: center;
        }}
        .stat-card .value {{ font-size: 1.8em; font-weight: 700; color: #00b894; }}
        .stat-card .label {{ font-size: 0.85em; color: #888; }}
        footer {{ text-align: center; margin-top: 32px; color: #aaa; font-size: 0.85em; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>🎯 {title}</h1>
        {focus_html}
        <p style="opacity:0.8;font-size:0.9em;margin-top:4px;">节点: {data.get('node_count', '?')} · 关系: {data.get('edge_count', '?')}</p>
    </header>

    <section>
        <h2>📊 图谱健康度</h2>
        <div class="stats">
            <div class="stat-card"><div class="value">{data.get('node_count', 0)}</div><div class="label">节点数</div></div>
            <div class="stat-card"><div class="value">{data.get('edge_count', 0)}</div><div class="label">关系数</div></div>
            <div class="stat-card"><div class="value">{len(gaps)}</div><div class="label">盲区数</div></div>
            <div class="stat-card"><div class="value">{len(path)}</div><div class="label">推荐条目</div></div>
        </div>
    </section>

    {gaps_html}
    {path_html}

    <footer>
        <p>ScholarMind 学习路径报告 · 生成于 {generated_at}</p>
    </footer>
</div>
</body>
</html>"""


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
    parser.add_argument("--save", action="store_true", help="保存报告到 data/reports/learning_paths/ (JSON + HTML)")

    args = parser.parse_args()

    try:
        if args.action == "learning_path":
            cmd_learning_path(args.focus, args.max_items, save=args.save)
        elif args.action == "detect_gaps":
            cmd_detect_gaps(save=args.save)
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

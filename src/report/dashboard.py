#!/usr/bin/env python3
"""
ScholarMind - 统一仪表盘生成器
================================

汇总知识图谱、研究报告、学习路径三个维度的数据，
生成一个 HTML 仪表盘入口页面。

用法（CLI）：
  python src/report/dashboard.py

用法（Python API）：
  from src.report.dashboard import generate_dashboard
  generate_dashboard()

【工程思考】为什么是一个静态 HTML 而不是 Web 服务？
  - Plugin 架构下不应该启动长期运行的 Web 服务
  - 静态 HTML 可以直接用浏览器打开，零配置
  - Chart.js 通过 CDN 引入，HTML 内嵌所有数据，完全自包含
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = Path(os.getenv("SCHOLARMIND_DATA_DIR", str(PROJECT_ROOT / "data")))

logger = logging.getLogger("ScholarMind.Dashboard")

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def load_paper_reports(reports_dir: Path) -> list[dict]:
    """加载所有论文研究报告 JSON"""
    papers_dir = reports_dir / "papers"
    if not papers_dir.exists():
        return []
    reports = []
    for f in sorted(papers_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_filename"] = f.stem
            reports.append(data)
        except Exception as e:
            logger.warning(f"加载报告失败 {f}: {e}")
    return reports


def load_learning_path_reports(reports_dir: Path) -> list[dict]:
    """加载所有学习路径报告 JSON"""
    lp_dir = reports_dir / "learning_paths"
    if not lp_dir.exists():
        return []
    reports = []
    for f in sorted(lp_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_filename"] = f.stem
            reports.append(data)
        except Exception as e:
            logger.warning(f"加载学习路径报告失败 {f}: {e}")
    return reports


def load_paper_watch(watch_dir: Path) -> dict | None:
    """加载最新的论文追踪摘要"""
    if not watch_dir.exists():
        return None
    files = sorted(watch_dir.glob("*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return None


def build_kg_growth(graph_store) -> dict:
    """利用 created_at 双时态数据构建图谱增长时间线"""
    daily = {}
    for node in graph_store._nodes.values():
        if node.created_at:
            date = node.created_at[:10]
            daily[date] = daily.get(date, 0) + 1
    # 累计
    dates = sorted(daily.keys())
    cumulative = []
    total = 0
    for d in dates:
        total += daily[d]
        cumulative.append({"date": d, "count": total, "daily": daily[d]})
    return {"timeline": cumulative, "total": total}


def build_gap_evolution(lp_reports: list[dict]) -> list[dict]:
    """从历史学习路径报告中提取盲区演进数据"""
    evolution = []
    for r in lp_reports:
        gaps = r.get("gaps", [])
        evolution.append({
            "date": r.get("generated_at", "")[:10],
            "total_gaps": len(gaps),
            "critical": sum(1 for g in gaps if g.get("severity", 0) > 0.7),
            "node_count": r.get("node_count", 0),
            "edge_count": r.get("edge_count", 0),
        })
    return evolution


def generate_dashboard(
    output_path: str = "data/dashboard.html",
    graph_path: str | None = None,
) -> str:
    """
    生成三维一体仪表盘 HTML

    Returns:
        输出文件的绝对路径
    """
    from src.knowledge.graph_store import KnowledgeGraphStore

    # 加载数据
    kg_path = graph_path or str(DATA_DIR / "knowledge_graph.json")
    store = KnowledgeGraphStore(graph_path=kg_path)

    reports_dir = DATA_DIR / "reports"
    paper_reports = load_paper_reports(reports_dir)
    lp_reports = load_learning_path_reports(reports_dir)
    watch_data = load_paper_watch(DATA_DIR / "paper_watch")
    kg_growth = build_kg_growth(store)
    gap_evolution = build_gap_evolution(lp_reports)

    # KG 可视化路径
    kg_viz_path = "kg_visualization.html"
    if store.node_count > 0:
        store.visualize(str(DATA_DIR / kg_viz_path))

    # 渲染 HTML
    html = _render_dashboard(
        store=store,
        paper_reports=paper_reports,
        lp_reports=lp_reports,
        watch_data=watch_data,
        kg_growth=kg_growth,
        gap_evolution=gap_evolution,
        kg_viz_path=kg_viz_path,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    print(f"\n✅ 仪表盘已生成: {output.resolve()}")
    return str(output.resolve())


def _render_dashboard(
    store,
    paper_reports: list[dict],
    lp_reports: list[dict],
    watch_data: dict | None,
    kg_growth: dict,
    gap_evolution: list[dict],
    kg_viz_path: str,
) -> str:
    """渲染仪表盘 HTML"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 研究报告列表
    paper_rows = []
    for r in paper_reports:
        meta = r.get("meta", {})
        tags_html = " ".join(f"<span class='tag'>{t}</span>" for t in r.get("tags", [])[:3])
        html_file = r.get("_filename", "") + ".html"
        paper_rows.append(
            f"<tr>"
            f"<td>{meta.get('generated_at', '')[:10]}</td>"
            f"<td><a href='reports/papers/{html_file}'>{meta.get('paper_title', '?')[:50]}</a></td>"
            f"<td>{meta.get('year', '-')}</td>"
            f"<td>{tags_html}</td>"
            f"</tr>"
        )
    papers_table = "".join(paper_rows) if paper_rows else "<tr><td colspan='4' class='empty'>暂无研究报告。运行 /paper-analysis 开始分析论文</td></tr>"

    # 学习路径报告列表
    lp_rows = []
    for r in lp_reports:
        gaps = r.get("gaps", [])
        path_items = r.get("path", [])
        html_file = r.get("_filename", "") + ".html"
        lp_rows.append(
            f"<tr>"
            f"<td>{r.get('generated_at', '')[:10]}</td>"
            f"<td><a href='reports/learning_paths/{html_file}'>{r.get('focus_area', '') or '全局'}</a></td>"
            f"<td>{len(gaps)}</td>"
            f"<td>{len(path_items)}</td>"
            f"<td>{r.get('node_count', '-')}</td>"
            f"</tr>"
        )
    lp_table = "".join(lp_rows) if lp_rows else "<tr><td colspan='5' class='empty'>暂无学习路径报告。运行 /knowledge-build --save 生成</td></tr>"

    # 论文追踪
    watch_html = ""
    if watch_data:
        watch_papers = watch_data.get("papers", [])[:5]
        watch_row_parts = []
        for p in watch_papers:
            arxiv_id = p.get("arxiv_id", "")
            title_short = p.get("title", "")[:55]
            authors_short = ", ".join(p.get("authors", [])[:2])
            pub_date = p.get("published", "")
            watch_row_parts.append(
                f"<tr><td>{pub_date}</td>"
                f"<td><a href='https://arxiv.org/abs/{arxiv_id}' target='_blank'>{title_short}...</a></td>"
                f"<td>{authors_short}</td></tr>"
            )
        watch_rows = "".join(watch_row_parts)
        topics_str = ", ".join(watch_data.get("query_topics", []))
        days_str = watch_data.get("time_window_days", "?")
        total_str = watch_data.get("total_count", 0)
        watch_html = f"""
        <section>
            <h2>📰 最近论文追踪</h2>
            <p class="subtitle">关键词: {topics_str} · 最近 {days_str} 天 · 共 {total_str} 篇</p>
            <table><thead><tr><th>日期</th><th>标题</th><th>作者</th></tr></thead>
            <tbody>{watch_rows}</tbody></table>
        </section>
        """

    # Chart.js 数据
    growth_labels = json.dumps([d["date"] for d in kg_growth.get("timeline", [])])
    growth_data = json.dumps([d["count"] for d in kg_growth.get("timeline", [])])
    growth_daily = json.dumps([d["daily"] for d in kg_growth.get("timeline", [])])

    gap_labels = json.dumps([d["date"] for d in gap_evolution])
    gap_totals = json.dumps([d["total_gaps"] for d in gap_evolution])
    gap_criticals = json.dumps([d["critical"] for d in gap_evolution])
    gap_nodes = json.dumps([d["node_count"] for d in gap_evolution])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ScholarMind Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', 'PingFang SC', sans-serif;
            background: #0f0f23;
            color: #e0e0e0;
            line-height: 1.6;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}
        h1 {{
            text-align: center;
            font-size: 2em;
            background: linear-gradient(90deg, #667eea, #00b894, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .subtitle {{ text-align: center; color: #888; margin-bottom: 32px; font-size: 0.9em; }}

        /* 统计卡片 */
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 32px; }}
        .stat-card {{
            background: #1a1a3e;
            padding: 24px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #333;
            transition: transform 0.2s;
        }}
        .stat-card:hover {{ transform: translateY(-2px); border-color: #667eea; }}
        .stat-card .value {{ font-size: 2.2em; font-weight: 700; }}
        .stat-card .label {{ font-size: 0.85em; color: #888; margin-top: 4px; }}
        .c1 .value {{ color: #FF6B6B; }}
        .c2 .value {{ color: #4ECDC4; }}
        .c3 .value {{ color: #FFEAA7; }}
        .c4 .value {{ color: #DDA0DD; }}
        .c5 .value {{ color: #45B7D1; }}

        /* 图表区 */
        .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 32px; }}
        .chart-box {{
            background: #1a1a3e;
            padding: 24px;
            border-radius: 12px;
            border: 1px solid #333;
        }}
        .chart-box h3 {{ color: #667eea; margin-bottom: 12px; font-size: 1em; }}
        canvas {{ max-height: 260px; }}

        /* 表格区 */
        section {{
            background: #1a1a3e;
            padding: 28px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }}
        section h2 {{ color: #00b894; margin-bottom: 16px; font-size: 1.2em; }}
        section .subtitle {{ text-align: left; margin-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 10px; border-bottom: 2px solid #333; color: #aaa; font-size: 0.85em; }}
        td {{ padding: 10px; border-bottom: 1px solid #222; font-size: 0.9em; }}
        tr:hover {{ background: #222244; }}
        a {{ color: #667eea; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .tag {{
            display: inline-block; background: #667eea22; color: #667eea;
            padding: 2px 8px; border-radius: 10px; font-size: 0.8em; margin: 2px;
        }}
        .empty {{ color: #666; text-align: center; padding: 20px; }}

        /* KG 链接 */
        .kg-link {{
            display: inline-block;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 12px 28px;
            border-radius: 8px;
            font-weight: 600;
            text-decoration: none;
            transition: opacity 0.2s;
        }}
        .kg-link:hover {{ opacity: 0.85; text-decoration: none; }}

        footer {{ text-align: center; color: #555; font-size: 0.8em; margin-top: 32px; }}

        @media (max-width: 768px) {{
            .charts {{ grid-template-columns: 1fr; }}
            .stats {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>🧠 ScholarMind Dashboard</h1>
    <p class="subtitle">知识图谱 · 研究报告 · 学习路径 — 三维一体研究仪表盘</p>

    <!-- 统计卡片 -->
    <div class="stats">
        <div class="stat-card c1"><div class="value">{store.node_count}</div><div class="label">图谱节点</div></div>
        <div class="stat-card c2"><div class="value">{store.edge_count}</div><div class="label">图谱关系</div></div>
        <div class="stat-card c3"><div class="value">{len(paper_reports)}</div><div class="label">研究报告</div></div>
        <div class="stat-card c4"><div class="value">{len(lp_reports)}</div><div class="label">学习路径报告</div></div>
        <div class="stat-card c5"><div class="value">{watch_data.get('total_count', 0) if watch_data else 0}</div><div class="label">追踪论文</div></div>
    </div>

    <!-- 图表 -->
    <div class="charts">
        <div class="chart-box">
            <h3>📈 知识图谱增长 (created_at 双时态)</h3>
            <canvas id="growthChart"></canvas>
        </div>
        <div class="chart-box">
            <h3>🔄 盲区消除进度</h3>
            <canvas id="gapChart"></canvas>
        </div>
    </div>

    <!-- 知识图谱入口 -->
    <section style="text-align:center;">
        <h2>🕸️ 知识图谱交互可视化</h2>
        <p style="margin-bottom:16px;color:#aaa;">{store.node_count} 个节点 · {store.edge_count} 条关系 · pyvis 力导向图</p>
        <a class="kg-link" href="{kg_viz_path}">🔗 打开交互式知识图谱</a>
    </section>

    <!-- 研究报告列表 -->
    <section>
        <h2>📄 研究报告</h2>
        <table>
            <thead><tr><th>日期</th><th>论文标题</th><th>年份</th><th>标签</th></tr></thead>
            <tbody>{papers_table}</tbody>
        </table>
    </section>

    <!-- 学习路径报告列表 -->
    <section>
        <h2>🎯 学习路径报告</h2>
        <table>
            <thead><tr><th>日期</th><th>聚焦领域</th><th>盲区数</th><th>推荐条目</th><th>图谱节点</th></tr></thead>
            <tbody>{lp_table}</tbody>
        </table>
    </section>

    {watch_html}

    <footer>
        <p>ScholarMind Dashboard · 生成于 {now[:19]} · Powered by Chart.js + pyvis</p>
    </footer>
</div>

<script>
// 图谱增长折线图
const growthCtx = document.getElementById('growthChart').getContext('2d');
new Chart(growthCtx, {{
    type: 'line',
    data: {{
        labels: {growth_labels},
        datasets: [{{
            label: '累计节点数',
            data: {growth_data},
            borderColor: '#667eea',
            backgroundColor: '#667eea22',
            fill: true,
            tension: 0.3,
        }}, {{
            label: '日新增',
            data: {growth_daily},
            borderColor: '#00b894',
            backgroundColor: '#00b89444',
            type: 'bar',
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#aaa' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
            y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }}
        }}
    }}
}});

// 盲区消除进度
const gapCtx = document.getElementById('gapChart').getContext('2d');
new Chart(gapCtx, {{
    type: 'line',
    data: {{
        labels: {gap_labels},
        datasets: [{{
            label: '总盲区数',
            data: {gap_totals},
            borderColor: '#FFEAA7',
            backgroundColor: '#FFEAA722',
            fill: true,
            tension: 0.3,
        }}, {{
            label: '严重盲区',
            data: {gap_criticals},
            borderColor: '#e17055',
            backgroundColor: '#e1705522',
            fill: true,
            tension: 0.3,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#aaa' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }} }},
            y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#333' }}, beginAtZero: true }}
        }}
    }}
}});
</script>
</body>
</html>"""


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    generate_dashboard()


if __name__ == "__main__":
    main()

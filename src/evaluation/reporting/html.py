from __future__ import annotations

"""HTML 评测报告生成器 —— 确定性，嵌入式模板，无外部依赖。"""

import json
from html import escape
from pathlib import Path


def _load(run_dir: Path, name: str, default):
    p = run_dir / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _color(value: float) -> str:
    if value >= 0.7:
        return "#16a34a"
    if value >= 0.4:
        return "#d97706"
    return "#dc2626"


_CSS = """
body { margin:0; font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
       background:#f5f7fb; color:#1e293b; }
.header { background:linear-gradient(135deg,#667eea,#764ba2); color:#fff;
          padding:1.6rem 2rem; }
.header h1 { margin:0 0 .3rem; font-size:1.4rem; }
.header .meta { opacity:.85; font-size:.85rem; }
.banner { padding:.7rem 2rem; font-weight:600; }
.banner.ok { background:#dcfce7; color:#166534; }
.banner.bad { background:#fee2e2; color:#991b1b; }
.wrap { padding:1.5rem 2rem; }
.cards { display:flex; flex-wrap:wrap; gap:1rem; margin-bottom:1.5rem; }
.card { background:#fff; border-radius:12px; padding:1rem 1.4rem; min-width:150px;
        box-shadow:0 1px 4px rgba(0,0,0,.06); }
.card .label { font-size:.78rem; color:#64748b; }
.card .value { font-size:1.5rem; font-weight:700; margin-top:.2rem; }
h2 { font-size:1.05rem; margin:1.6rem 0 .6rem; color:#475569; }
table { width:100%; border-collapse:collapse; background:#fff; border-radius:10px;
        overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.06); font-size:.85rem; }
th,td { padding:.5rem .8rem; text-align:left; border-bottom:1px solid #f1f5f9; }
th { background:#f8fafc; color:#475569; font-weight:600; }
.bar { height:8px; border-radius:4px; background:#e2e8f0; }
.bar > span { display:block; height:100%; border-radius:4px; }
.gate-PASS { color:#16a34a; font-weight:700; }
.gate-WARN { color:#d97706; font-weight:700; }
.gate-FAIL { color:#dc2626; font-weight:700; }
.footer { text-align:center; padding:1rem; color:#94a3b8; font-size:.75rem; }
"""


def generate_html_report(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    config = _load(run_dir, "config.json", {})
    summary = _load(run_dir, "run_summary.json", {})
    metrics = _load(run_dir, "metrics.json", [])
    gate = _load(run_dir, "gate_result.json", None)

    totals = summary.get("totals", {})
    headline = summary.get("headline", {})
    cost = summary.get("cost", {})
    contaminated = bool(totals.get("contaminated"))

    parts: list[str] = []
    parts.append(f"<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
                 f"<title>评测报告 {escape(summary.get('run_id', ''))}</title>"
                 f"<style>{_CSS}</style></head><body>")

    parts.append(
        f"<div class='header'><h1>🧪 AcademicAgent 评测报告</h1>"
        f"<div class='meta'>{escape(summary.get('run_id', run_dir.name))} · "
        f"数据集 {escape(str(config.get('dataset_version', '-')))} · "
        f"代码 {escape(str(config.get('code_hash', '-')))} · "
        f"模型 {escape(str(config.get('model', '-')))} · "
        f"{escape(str(config.get('timestamp', '-')))}</div></div>"
    )

    # 隔离横幅
    if contaminated:
        parts.append("<div class='banner bad'>🔴 CONTAMINATED — "
                     "本次 run 改动了受保护文件，结果不可信</div>")
    else:
        parts.append("<div class='banner ok'>🟢 隔离正常 — "
                     "主知识图谱与长期记忆未被改动</div>")

    parts.append("<div class='wrap'>")

    # 概览卡片
    gate_overall = gate.get("overall", "-") if gate else "-"
    parts.append("<div class='cards'>")
    for label, value in [
        ("完成率", headline.get("completion_rate", 0)),
        ("工具成功率", headline.get("tool_success_rate", 0)),
        ("p90 延迟 (ms)", headline.get("p90_latency_ms", 0)),
        ("总成本 (USD)", headline.get("total_cost_usd", 0)),
        ("任务 ok/fail/skip",
         f"{totals.get('ok',0)}/{totals.get('failed',0)}/{totals.get('skipped',0)}"),
        ("门禁", gate_overall),
    ]:
        parts.append(f"<div class='card'><div class='label'>{escape(label)}</div>"
                     f"<div class='value'>{escape(str(value))}</div></div>")
    parts.append("</div>")

    # 门禁明细
    if gate:
        parts.append(f"<h2>回归门禁: <span class='gate-{gate_overall}'>"
                     f"{escape(gate_overall)}</span></h2>")
        parts.append("<table><tr><th>指标</th><th>状态</th><th>值</th>"
                     "<th>阈值</th><th>原因</th></tr>")
        for c in gate.get("metric_checks", []) + gate.get("budget_checks", []):
            st = c.get("status", "-")
            parts.append(
                f"<tr><td>{escape(str(c.get('metric','-')))}</td>"
                f"<td class='gate-{st}'>{escape(st)}</td>"
                f"<td>{escape(str(c.get('value','-')))}</td>"
                f"<td>{escape(str(c.get('min', c.get('limit','-'))))}</td>"
                f"<td>{escape(str(c.get('reason','')))}</td></tr>"
            )
        parts.append("</table>")

    # 各能力
    by_cap = summary.get("by_capability", {})
    if by_cap:
        parts.append("<h2>各能力完成情况</h2><table>"
                     "<tr><th>能力</th><th>总数</th><th>成功</th><th>失败</th>"
                     "<th>跳过</th><th>完成率</th></tr>")
        for cap, s in sorted(by_cap.items()):
            parts.append(
                f"<tr><td>{escape(cap)}</td><td>{s['total']}</td><td>{s['ok']}</td>"
                f"<td>{s['failed']}</td><td>{s['skipped']}</td>"
                f"<td>{s['completion_rate']}</td></tr>"
            )
        parts.append("</table>")

    # 指标聚合
    by_metric = summary.get("by_metric", {})
    if by_metric:
        parts.append("<h2>指标聚合</h2><table>"
                     "<tr><th>指标</th><th>均值</th><th>n</th><th></th></tr>")
        for name, s in sorted(by_metric.items()):
            mean = s.get("mean", 0)
            pct = max(0, min(100, mean * 100)) if isinstance(mean, (int, float)) else 0
            parts.append(
                f"<tr><td>{escape(name)}</td><td>{mean}</td><td>{s.get('n',0)}</td>"
                f"<td><div class='bar'><span style='width:{pct:.0f}%;"
                f"background:{_color(mean if isinstance(mean,(int,float)) else 0)}'>"
                f"</span></div></td></tr>"
            )
        parts.append("</table>")

    # per-task 指标
    if metrics:
        parts.append("<h2>per-task 指标明细</h2><table>"
                     "<tr><th>task_id</th><th>指标</th><th>值</th>"
                     "<th>分子/分母</th><th>notes</th></tr>")
        for m in metrics:
            v = m.get("value", 0)
            parts.append(
                f"<tr><td>{escape(str(m.get('task_id','-')))}</td>"
                f"<td>{escape(str(m.get('metric','-')))}</td>"
                f"<td style='color:{_color(v if isinstance(v,(int,float)) else 0)}'>"
                f"{v}</td>"
                f"<td>{m.get('numerator',0)}/{m.get('denominator',0)}</td>"
                f"<td>{escape(str(m.get('notes',''))[:80])}</td></tr>"
            )
        parts.append("</table>")

    # 延迟
    latency = summary.get("latency", {})
    if latency:
        parts.append("<h2>工具延迟 (ms)</h2><table>"
                     "<tr><th>工具</th><th>mean</th><th>median</th><th>p90</th>"
                     "<th>max</th><th>count</th></tr>")
        for tool, s in sorted(latency.items()):
            parts.append(
                f"<tr><td>{escape(tool)}</td><td>{s.get('mean',0)}</td>"
                f"<td>{s.get('median',0)}</td><td>{s.get('p90',0)}</td>"
                f"<td>{s.get('max',0)}</td><td>{s.get('count',0)}</td></tr>"
            )
        parts.append("</table>")

    parts.append("<h2>成本</h2>"
                 f"<p>总成本 <b>{cost.get('total_usd',0)}</b> USD · "
                 f"tokens_in {cost.get('tokens_in',0)} / tokens_out {cost.get('tokens_out',0)} · "
                 f"估算方式 <code>{escape(str(cost.get('method','-')))}</code> · "
                 f"单任务均价 {cost.get('avg_cost_usd_per_task',0)} USD</p>")

    if (run_dir / "failures.md").exists():
        parts.append("<h2>失败卡片</h2><p>详见同目录 "
                     "<code>failures.md</code>（结构化卡片：分类 / 复现命令 / "
                     "根因假设 / 修复候选 / 回归测试建议）。</p>")

    parts.append("</div><div class='footer'>AcademicAgent 评测子系统 · "
                 "本地优先 · 确定性报告</div></body></html>")

    out = run_dir / "report.html"
    out.write_text("".join(parts), encoding="utf-8")
    return out

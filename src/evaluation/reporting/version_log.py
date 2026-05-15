from __future__ import annotations

"""
版本迭代日志（本地镜像）—— 向 docs/experiments/eval_runs.md 追加一行 run 摘要。

这是 Notion「版本迭代日志」的本地副本：即使没有 Notion，数据飞轮也能跑。
每次 run 一行：日期、run_id、code_hash、headline 指标、门禁结论、run 目录链接。
"""

import json
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_LOG_PATH = _PROJECT_ROOT / "docs" / "experiments" / "eval_runs.md"

_HEADER = """# 评测 Run 版本迭代日志

本文件由 `src/evaluation/reporting/version_log.py` 自动追加，是 Notion
「版本迭代日志」的本地镜像 —— 没有 Notion 时数据飞轮也能运转。

| 日期 | run_id | code | 完成率 | 工具成功率 | 成本(USD) | 门禁 | ok/fail/skip | run 目录 |
|:---|:---|:---|---:|---:|---:|:---:|:---:|:---|
"""


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def append_version_log(run_dir: str | Path, log_path: str | Path | None = None) -> Path | None:
    """把一个 run 的摘要追加到 eval_runs.md。失败返回 None（非致命）。"""
    run_dir = Path(run_dir)
    log_path = Path(log_path) if log_path else _LOG_PATH
    summary = _load(run_dir / "run_summary.json")
    if summary is None:
        return None
    gate = _load(run_dir / "gate_result.json") or {}

    headline = summary.get("headline", {})
    totals = summary.get("totals", {})
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    contaminated = totals.get("contaminated")
    gate_overall = gate.get("overall", "-")
    gate_cell = "🔴CONTAMINATED" if contaminated else {
        "PASS": "🟢PASS", "WARN": "🟡WARN", "FAIL": "🔴FAIL",
    }.get(gate_overall, gate_overall)

    row = (
        f"| {date} | {summary.get('run_id','-')} | "
        f"{summary.get('code_hash','-')} | "
        f"{headline.get('completion_rate',0)} | "
        f"{headline.get('tool_success_rate',0)} | "
        f"{headline.get('total_cost_usd',0)} | {gate_cell} | "
        f"{totals.get('ok',0)}/{totals.get('failed',0)}/{totals.get('skipped',0)} | "
        f"`{run_dir}` |\n"
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(_HEADER, encoding="utf-8")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(row)
    return log_path

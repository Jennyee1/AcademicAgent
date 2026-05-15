from __future__ import annotations

"""
回归门禁 —— 把评测变成 demo / 提交前可跑的硬门禁。

读取 run_summary.json + thresholds.yaml + 可选 baseline，对每个指标判定
PASS / WARN / FAIL，写出 gate_result.json，并给出整体退出码：
任一 FAIL 或 run 被标记 contaminated -> 非零退出码。
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("AcademicAgent.Eval.Gate")

_DEFAULT_THRESHOLDS = Path(__file__).resolve().parent / "thresholds.yaml"


def load_thresholds(path: str | Path | None = None) -> dict:
    """加载 thresholds.yaml。"""
    path = Path(path) if path else _DEFAULT_THRESHOLDS
    if not path.exists():
        logger.warning("thresholds 文件不存在: %s，门禁将只做污染检查", path)
        return {"metrics": {}, "budget": {}}
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {"metrics": {}, "budget": {}}
    except Exception as exc:  # noqa: BLE001
        logger.warning("thresholds 解析失败: %s", exc)
        return {"metrics": {}, "budget": {}}


def _check_metric(
    name: str,
    cfg: dict,
    summary_by_metric: dict,
    baseline_by_metric: dict | None,
) -> dict:
    """对单个指标判定 PASS/WARN/FAIL。"""
    entry = summary_by_metric.get(name)
    if entry is None:
        return {"metric": name, "status": "SKIP", "reason": "本次 run 无该指标数据"}
    value = entry.get("mean", 0.0)
    min_v = cfg.get("min")
    tol = cfg.get("regression_tolerance")
    warn_only = bool(cfg.get("warn_only", False))

    status = "PASS"
    reasons = []

    if min_v is not None and value < min_v:
        status = "WARN" if warn_only else "FAIL"
        reasons.append(f"value {value:.4f} < min {min_v}")

    if tol is not None and baseline_by_metric:
        base = baseline_by_metric.get(name, {}).get("mean")
        if base is not None and value < base - tol:
            new_status = "WARN" if warn_only else "FAIL"
            # FAIL 优先于 WARN
            if status != "FAIL":
                status = new_status
            reasons.append(
                f"regression: value {value:.4f} < baseline {base:.4f} - tol {tol}"
            )

    return {
        "metric": name, "status": status, "value": round(value, 4),
        "min": min_v, "n": entry.get("n", 0),
        "reason": "; ".join(reasons) if reasons else "ok",
    }


def run_gate(
    run_summary: dict,
    thresholds: dict,
    baseline: dict | None = None,
) -> dict[str, Any]:
    """执行门禁判定，返回 gate_result（不落盘，由调用方写文件）。"""
    metrics_cfg = thresholds.get("metrics", {}) or {}
    budget_cfg = thresholds.get("budget", {}) or {}
    summary_by_metric = run_summary.get("by_metric", {}) or {}
    baseline_by_metric = (baseline or {}).get("by_metric") if baseline else None

    checks: list[dict] = []
    for name, cfg in metrics_cfg.items():
        checks.append(_check_metric(name, cfg, summary_by_metric, baseline_by_metric))

    # 预算检查（延迟 / 成本）
    budget_checks: list[dict] = []
    latency = run_summary.get("latency", {}).get("__all__", {})
    p90_ms = latency.get("p90", 0.0)
    p90_limit_s = budget_cfg.get("p90_latency_s")
    if p90_limit_s is not None:
        ok = p90_ms <= p90_limit_s * 1000.0
        budget_checks.append({
            "metric": "p90_latency_s", "status": "PASS" if ok else "FAIL",
            "value": round(p90_ms / 1000.0, 2), "limit": p90_limit_s,
            "reason": "ok" if ok else f"p90 {p90_ms/1000.0:.1f}s > {p90_limit_s}s",
        })
    avg_cost = run_summary.get("cost", {}).get("avg_cost_usd_per_task", 0.0)
    cost_limit = budget_cfg.get("avg_cost_usd_per_task")
    if cost_limit is not None:
        ok = avg_cost <= cost_limit
        budget_checks.append({
            "metric": "avg_cost_usd_per_task", "status": "PASS" if ok else "FAIL",
            "value": round(avg_cost, 6), "limit": cost_limit,
            "reason": "ok" if ok else f"avg cost {avg_cost:.4f} > {cost_limit}",
        })

    # 污染：硬失败
    contaminated = bool(run_summary.get("totals", {}).get("contaminated", False))

    all_checks = checks + budget_checks
    n_fail = sum(1 for c in all_checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in all_checks if c["status"] == "WARN")
    n_pass = sum(1 for c in all_checks if c["status"] == "PASS")

    overall = "PASS"
    if contaminated or n_fail > 0:
        overall = "FAIL"
    elif n_warn > 0:
        overall = "WARN"

    exit_code = 1 if overall == "FAIL" else 0

    return {
        "run_id": run_summary.get("run_id", ""),
        "overall": overall,
        "exit_code": exit_code,
        "contaminated": contaminated,
        "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail,
                    "total": len(all_checks)},
        "metric_checks": checks,
        "budget_checks": budget_checks,
        "baseline_used": bool(baseline),
    }


def gate_from_run_dir(
    run_dir: str | Path,
    thresholds_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """从 run 目录读取 run_summary.json 跑门禁，写 gate_result.json。"""
    run_dir = Path(run_dir)
    summary_file = run_dir / "run_summary.json"
    if not summary_file.exists():
        raise FileNotFoundError(f"run_summary.json 不存在: {summary_file}")
    run_summary = json.loads(summary_file.read_text(encoding="utf-8"))
    thresholds = load_thresholds(thresholds_path)
    baseline = None
    if baseline_path and Path(baseline_path).exists():
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    result = run_gate(run_summary, thresholds, baseline)
    if write:
        (run_dir / "gate_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result

from __future__ import annotations

"""
Notion 同步 —— 把评测 run 镜像到 Notion。

本地优先：data/evaluation/runs/ 永远是事实来源，Notion 只是镜像。
**所有 Notion 调用都经 _safe() 包裹**：捕获一切异常 -> 记 run_dir/notion_sync.log
-> 返回 None。Notion 失败永不抛错、不改退出码、不阻断本地 artifact。

三个目标：
  1. 每个 run 一个实验子页（标题 "Eval Run <run_id>"，正文 = 指标 + 失败摘要）。
  2. 版本迭代日志（向父页面追加一行 run 摘要）。
  3. 阈值突破高亮（run 页内的红/绿 callout）。

直接走 Notion REST API（集成 token），使评测 CLI 自包含、无需宿主 Agent 的 MCP。
配置：data/evaluation/notion_config.json 或环境变量 NOTION_API_KEY / NOTION_PARENT_PAGE_ID。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("AcademicAgent.Eval.Notion")

_API = "https://api.notion.com/v1"


def _load_config() -> dict:
    """配置优先级：notion_config.json > 环境变量。"""
    import os
    cfg_path = (
        Path(__file__).resolve().parent.parent.parent
        / "data" / "evaluation" / "notion_config.json"
    )
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cfg = {}
    cfg.setdefault("api_key", os.getenv("NOTION_API_KEY", ""))
    cfg.setdefault("parent_page_id", os.getenv("NOTION_PARENT_PAGE_ID", ""))
    cfg.setdefault("notion_version", "2022-06-28")
    cfg.setdefault("enabled", bool(cfg.get("api_key")))
    return cfg


# ------------------------------------------------------------------ #
# Notion block 构造器
# ------------------------------------------------------------------ #

def _rich(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": str(text)[:1900]}}]


def _heading(text: str, level: int = 2) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rich(text)}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _rich(text)}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rich(text)}}


def _callout(text: str, emoji: str, color: str) -> dict:
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": _rich(text), "icon": {"emoji": emoji},
                        "color": color}}


def _code(text: str, language: str = "plain text") -> dict:
    return {"object": "block", "type": "code",
            "code": {"rich_text": _rich(text), "language": language}}


class NotionSync:
    """Notion 同步器。所有外部调用均优雅降级。"""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or _load_config()
        self.api_key = self.config.get("api_key", "")
        self.parent_page_id = self.config.get("parent_page_id", "")
        self.notion_version = self.config.get("notion_version", "2022-06-28")
        self.enabled = bool(self.config.get("enabled")) and bool(self.api_key)
        self._log_path: Path | None = None

    # -------------------- 基础设施 -------------------- #

    def _log(self, msg: str) -> None:
        logger.info("[notion] %s", msg)
        if self._log_path:
            try:
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(f"{ts} {msg}\n")
            except Exception:  # noqa: BLE001
                pass

    def _safe(self, label: str, fn: Callable, *args, **kwargs) -> Any:
        """包裹一切 Notion 调用：异常 -> 记日志 -> 返回 None。"""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._log(f"FAIL {label}: {exc}")
            return None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.notion_version,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict | None:
        import httpx
        resp = httpx.post(f"{_API}{path}", headers=self._headers(),
                          json=payload, timeout=30.0)
        if resp.status_code >= 300:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _patch(self, path: str, payload: dict) -> dict | None:
        import httpx
        resp = httpx.patch(f"{_API}{path}", headers=self._headers(),
                           json=payload, timeout=30.0)
        if resp.status_code >= 300:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    # -------------------- 公开入口 -------------------- #

    def sync_run(self, run_dir: str | Path) -> dict | None:
        """把一个 run 镜像到 Notion。返回同步结果 dict（失败返回 None，永不抛错）。"""
        run_dir = Path(run_dir)
        self._log_path = run_dir / "notion_sync.log"

        if not self.enabled:
            self._log("SKIP Notion 同步未启用（缺 api_key 或 enabled=false）")
            return None
        if not self.parent_page_id:
            self._log("SKIP 缺少 parent_page_id")
            return None

        summary = self._read_json(run_dir / "run_summary.json")
        if summary is None:
            self._log("SKIP run_summary.json 不存在")
            return None
        gate = self._read_json(run_dir / "gate_result.json") or {}
        config = self._read_json(run_dir / "config.json") or {}
        run_id = summary.get("run_id", run_dir.name)

        # 幂等：已同步过则只追加一条「re-synced」说明
        state = self._read_json(run_dir / "notion_sync.json")
        if state and state.get("notion_page_id"):
            page_id = state["notion_page_id"]
            self._safe("re-sync note", self._patch,
                       f"/blocks/{page_id}/children",
                       {"children": [_paragraph(
                           f"🔁 re-synced at "
                           f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
                       )]})
            self._log(f"OK 已存在 run 页 {page_id}，追加 re-sync 说明")
            return {"notion_page_id": page_id, "resynced": True}

        # 1) 创建 run 实验子页
        page = self._safe("create run page", self._create_run_page,
                          run_id, summary, gate, config, run_dir)
        if not page:
            self._log("FAIL run 页创建失败，停止后续同步（本地结果不受影响）")
            return None
        page_id = page.get("id", "")
        self._log(f"OK 创建 run 页 {page_id}")

        # 2) 版本迭代日志：向父页面追加一行
        self._safe("append version log", self._append_version_log,
                   run_id, summary, gate)

        # 3) 持久化 page_id（幂等）
        result = {
            "notion_page_id": page_id,
            "notion_url": page.get("url", ""),
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            (run_dir / "notion_sync.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"WARN notion_sync.json 写入失败: {exc}")
        return result

    # -------------------- 内部构造 -------------------- #

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def _create_run_page(self, run_id, summary, gate, config, run_dir) -> dict | None:
        totals = summary.get("totals", {})
        headline = summary.get("headline", {})
        cost = summary.get("cost", {})
        contaminated = bool(totals.get("contaminated"))
        gate_overall = gate.get("overall", "-")

        children: list[dict] = []

        # 阈值/隔离 callout
        if contaminated:
            children.append(_callout(
                "CONTAMINATED — 本次 run 改动了受保护文件，结果不可信",
                "🔴", "red_background"))
        elif gate_overall == "FAIL":
            fails = [c for c in (gate.get("metric_checks", []) +
                                 gate.get("budget_checks", []))
                     if c.get("status") == "FAIL"]
            children.append(_callout(
                "门禁 FAIL — " + "; ".join(
                    f"{c['metric']}({c.get('reason','')})" for c in fails[:5]),
                "🔴", "red_background"))
        elif gate_overall == "WARN":
            children.append(_callout("门禁 WARN — 存在低于阈值的 warn_only 指标",
                                     "🟡", "yellow_background"))
        else:
            children.append(_callout("门禁 PASS · 隔离正常 — 主知识图谱与长期记忆未被改动",
                                     "🟢", "green_background"))

        # 元数据
        children.append(_heading("运行元数据", 2))
        for k, v in [
            ("数据集版本", config.get("dataset_version", "-")),
            ("代码版本", config.get("code_hash", "-")),
            ("模型", config.get("model", "-")),
            ("离线模式", config.get("offline", "-")),
            ("时间", config.get("timestamp", "-")),
        ]:
            children.append(_bullet(f"{k}: {v}"))

        # 总览
        children.append(_heading("总览", 2))
        children.append(_bullet(
            f"任务: {totals.get('total',0)} 总 / {totals.get('ok',0)} ok / "
            f"{totals.get('failed',0)} failed / {totals.get('skipped',0)} skipped"))
        children.append(_bullet(f"完成率: {headline.get('completion_rate',0)}"))
        children.append(_bullet(f"工具成功率: {headline.get('tool_success_rate',0)}"))
        children.append(_bullet(f"p90 延迟: {headline.get('p90_latency_ms',0)} ms"))
        children.append(_bullet(
            f"总成本: {headline.get('total_cost_usd',0)} USD "
            f"(估算方式: {cost.get('method','-')})"))
        children.append(_bullet(f"门禁结论: {gate_overall}"))

        # 指标聚合
        by_metric = summary.get("by_metric", {})
        if by_metric:
            children.append(_heading("指标聚合", 2))
            for name, s in sorted(by_metric.items()):
                children.append(_bullet(
                    f"{name}: mean={s.get('mean',0)} (n={s.get('n',0)}, "
                    f"min={s.get('min',0)}, max={s.get('max',0)})"))

        # 失败摘要
        failures_md = run_dir / "failures.md"
        if failures_md.exists():
            text = failures_md.read_text(encoding="utf-8")
            head = "\n".join(text.splitlines()[:30])
            children.append(_heading("失败卡片摘要", 2))
            children.append(_code(head, "markdown"))

        children.append(_paragraph(
            f"本地事实来源: {run_dir}（report.html / failures.md / traces.jsonl）"))

        payload = {
            "parent": {"page_id": self.parent_page_id},
            "properties": {
                "title": {"title": _rich(f"Eval Run {run_id}")},
            },
            "children": children[:100],
        }
        return self._post("/pages", payload)

    def _append_version_log(self, run_id, summary, gate) -> dict | None:
        totals = summary.get("totals", {})
        headline = summary.get("headline", {})
        line = (
            f"📌 {run_id} · code {summary.get('code_hash','-')} · "
            f"完成率 {headline.get('completion_rate',0)} · "
            f"工具成功率 {headline.get('tool_success_rate',0)} · "
            f"成本 {headline.get('total_cost_usd',0)} USD · "
            f"门禁 {gate.get('overall','-')} · "
            f"{totals.get('ok',0)}/{totals.get('failed',0)}/{totals.get('skipped',0)} "
            f"(ok/fail/skip)"
        )
        return self._patch(
            f"/blocks/{self.parent_page_id}/children",
            {"children": [_bullet(line)]},
        )


def sync_run_dir(run_dir: str | Path) -> dict | None:
    """函数式入口。"""
    return NotionSync().sync_run(run_dir)

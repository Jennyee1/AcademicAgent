from __future__ import annotations

"""
AcademicAgent Evaluation — Trace 记录器
========================================

把 TraceEvent 记录追加写入 JSONL 文件。append-only、零缓冲、低开销。

Usage:
    tracer = Tracer(run_id="2026-05-14_1830_smoke", traces_path=Path(...))

    async with tracer.span("task_001", "tool_call", "search_papers") as span:
        result = await do_something()
        span.set_result(
            ok=True,
            output_summary=f"{len(result)} items",
            tokens_in=1200, tokens_out=300,
        )
"""

import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schema import TraceEvent


class _Span:
    """调用方在 tracer.span() 代码块内填充的可变结果容器。"""

    def __init__(self) -> None:
        self.ok: bool = True
        self.input_summary: str = ""
        self.output_summary: str = ""
        self.error: str = ""
        self.error_category: str = ""
        self.cost_usd: float = 0.0
        self.tokens_in: int = 0
        self.tokens_out: int = 0

    def set_result(
        self,
        ok: bool,
        input_summary: str = "",
        output_summary: str = "",
        error: str = "",
        error_category: str = "",
        cost_usd: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        self.ok = ok
        self.input_summary = input_summary
        self.output_summary = output_summary
        self.error = error
        self.error_category = error_category
        self.cost_usd = cost_usd
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


class Tracer:
    """把 TraceEvent 记录写入 JSONL 文件。"""

    def __init__(self, run_id: str, traces_path: Path) -> None:
        self.run_id = run_id
        self._path = Path(traces_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def span(
        self,
        task_id: str,
        event_type: str,
        tool_name: str = "",
    ):
        """计时一段代码并写出 TraceEvent。

        span 在记录异常后会重新抛出（ok=False）。
        调用方可以用 span.set_result() 覆盖默认的 ok=True。
        """
        span = _Span()
        t0 = time.perf_counter()
        exc_to_raise = None
        try:
            yield span
        except Exception as exc:  # noqa: BLE001
            if not span.error:
                span.set_result(
                    ok=False,
                    error=str(exc),
                    error_category="tool_exception",
                )
            exc_to_raise = exc
        finally:
            latency_ms = (time.perf_counter() - t0) * 1000
            event = TraceEvent(
                run_id=self.run_id,
                task_id=task_id,
                ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                event_type=event_type,
                tool_name=tool_name,
                ok=span.ok,
                latency_ms=round(latency_ms, 2),
                cost_usd=span.cost_usd,
                tokens_in=span.tokens_in,
                tokens_out=span.tokens_out,
                input_summary=span.input_summary,
                output_summary=span.output_summary,
                error=span.error,
                error_category=span.error_category,
            )
            self._append(event)
        if exc_to_raise is not None:
            raise exc_to_raise

    def _append(self, event: TraceEvent) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def load_events(self) -> list[TraceEvent]:
        """读取 JSONL 文件中所有事件。"""
        if not self._path.exists():
            return []
        events = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(TraceEvent.from_dict(json.loads(line)))
        return events

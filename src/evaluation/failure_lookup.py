from __future__ import annotations

"""
失败卡片 runtime 查询 —— 把历史失败卡片转化为可被 adapter / critic 消费的 lessons。

数据来源: `data/evaluation/failure_cards/*.jsonl` (由 failure_cards.write_failure_artifacts
写入)。本模块只负责加载与排序匹配，不做任何动作决策 —— 那部分在 critic.py。

匹配策略 (MVP, 故意保持简单):
  - capability 硬匹配 (精确, 缺失时跳过该过滤)
  - tool 软匹配: repro_command / task_id / tags 文本包含
  - 排序: severity (P0 < P1 < P2) 再按"越新越优先"(假定 cards_dir glob 后行号
    越大越新)

未来若 detail 文本爆炸再换 embedding / TF-IDF。
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("AcademicAgent.Eval.FailureLookup")


@dataclass(frozen=True)
class FailureLesson:
    """从失败卡片提炼出来供 runtime 消费的紧凑视图。"""
    card_id: str
    task_id: str
    layer: str
    capability: str
    tool: str
    category: str
    severity: str
    root_cause_hypothesis: str
    fix_candidate: str
    tags: tuple[str, ...]

    @classmethod
    def from_card(cls, d: dict, tool: str = "") -> FailureLesson:
        return cls(
            card_id=d.get("card_id", ""),
            task_id=d.get("task_id", ""),
            layer=d.get("layer", ""),
            capability=d.get("capability", ""),
            tool=tool,
            category=d.get("category", ""),
            severity=d.get("severity", "P2"),
            root_cause_hypothesis=d.get("root_cause_hypothesis", ""),
            fix_candidate=d.get("fix_candidate", ""),
            tags=tuple(d.get("tags", [])),
        )


def load_all_cards(cards_dir) -> list[dict]:
    """加载 cards_dir 下所有 *.jsonl 失败卡片。目录不存在返回空列表。"""
    d = Path(cards_dir)
    if not d.exists() or not d.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.jsonl")):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    out.append(json.loads(line))
        except Exception as exc:  # noqa: BLE001 — 单个文件坏了不应阻塞 lookup
            logger.warning("无法加载失败卡片 %s: %s", p, exc)
    return out


_SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def _tool_hit(card: dict, tool: str) -> bool:
    if not tool:
        return True
    blob_parts = [
        card.get("repro_command", ""),
        card.get("task_id", ""),
        " ".join(card.get("tags", []) or []),
    ]
    blob = " ".join(blob_parts).lower()
    return tool.lower() in blob


def lookup(
    cards: list[dict],
    *,
    capability: str = "",
    tool: str = "",
    top_k: int = 5,
) -> list[FailureLesson]:
    """过滤+排序与即将进行的调用相关的 lessons。

    Args:
        cards: load_all_cards 的返回值
        capability: 仅匹配该 capability 的卡片 (留空则不过滤)
        tool: 工具名;不命中的卡片会被降权但仍可保留
        top_k: 返回前 K 张

    Returns:
        FailureLesson 列表, 按 (是否命中 tool, severity, 新鲜度) 排序
    """
    if not cards:
        return []
    scored: list[tuple[int, int, int, dict]] = []
    for i, c in enumerate(cards):
        if capability and c.get("capability") and c.get("capability") != capability:
            continue
        tool_match = _tool_hit(c, tool)
        # tool 未命中时降权 (rank +100), 但不丢弃 —— 允许跨工具的同类警示
        tool_rank = 0 if tool_match else 100
        sev_rank = _SEV_ORDER.get(c.get("severity", "P2"), 9)
        recency_rank = -i  # 越新 (i 越大) 越优先 —— 用 -i 让 sort 升序时新的更靠前
        scored.append((tool_rank, sev_rank, recency_rank, c))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [FailureLesson.from_card(c, tool=tool) for _, _, _, c in scored[:top_k]]

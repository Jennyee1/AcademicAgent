from __future__ import annotations

"""Phase: runtime self-correction —— failure_lookup 加载与匹配。"""

import json
from pathlib import Path

from src.evaluation.failure_lookup import FailureLesson, load_all_cards, lookup


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---- load_all_cards ---------------------------------------------------------


def test_load_all_cards_missing_dir_returns_empty(tmp_path: Path):
    assert load_all_cards(tmp_path / "noexist") == []


def test_load_all_cards_empty_dir_returns_empty(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    assert load_all_cards(tmp_path / "empty") == []


def test_load_all_cards_reads_multiple_files(tmp_path: Path):
    _write_jsonl(tmp_path / "run_a.jsonl",
                 [{"card_id": "a#1", "category": "rate_limit"}])
    _write_jsonl(tmp_path / "run_b.jsonl",
                 [{"card_id": "b#1", "category": "timeout"},
                  {"card_id": "b#2", "category": "rate_limit"}])
    cards = load_all_cards(tmp_path)
    assert {c["card_id"] for c in cards} == {"a#1", "b#1", "b#2"}


def test_load_all_cards_skips_blank_lines(tmp_path: Path):
    (tmp_path / "x.jsonl").write_text(
        '{"card_id":"x1","category":"x"}\n\n   \n{"card_id":"x2","category":"y"}\n',
        encoding="utf-8",
    )
    cards = load_all_cards(tmp_path)
    assert [c["card_id"] for c in cards] == ["x1", "x2"]


def test_load_all_cards_tolerates_corrupt_file(tmp_path: Path):
    (tmp_path / "ok.jsonl").write_text(
        '{"card_id":"ok1","category":"x"}\n', encoding="utf-8",
    )
    (tmp_path / "bad.jsonl").write_text("this is not json\n", encoding="utf-8")
    cards = load_all_cards(tmp_path)
    # 损坏文件被跳过，正常文件仍加载
    assert [c["card_id"] for c in cards] == ["ok1"]


# ---- lookup -----------------------------------------------------------------


def _card(**overrides) -> dict:
    base = {
        "card_id": "c#0",
        "task_id": "t#0",
        "layer": "layer1_component",
        "capability": "retrieval",
        "category": "rate_limit",
        "severity": "P1",
        "repro_command": "",
        "trace_excerpt": "",
        "root_cause_hypothesis": "",
        "fix_candidate": "",
        "regression_test_suggestion": "",
        "detail": "",
        "tags": [],
    }
    base.update(overrides)
    return base


def test_lookup_empty_cards_returns_empty():
    assert lookup([], capability="retrieval", tool="search_papers") == []


def test_lookup_filters_by_capability():
    cards = [
        _card(card_id="r1", capability="retrieval"),
        _card(card_id="k1", capability="kg_extraction"),
    ]
    out = lookup(cards, capability="retrieval", tool="")
    assert [lesson.card_id for lesson in out] == ["r1"]
    assert all(isinstance(lesson, FailureLesson) for lesson in out)


def test_lookup_orders_by_severity_p0_first():
    cards = [
        _card(card_id="low", severity="P2"),
        _card(card_id="high", severity="P0"),
        _card(card_id="mid", severity="P1"),
    ]
    out = lookup(cards, capability="retrieval", tool="", top_k=5)
    assert [lesson.card_id for lesson in out] == ["high", "mid", "low"]


def test_lookup_tool_match_outranks_non_match():
    cards = [
        # 命中 tool（repro_command 含 "search_papers"），但严重度低
        _card(card_id="match_p2", severity="P2",
              repro_command="python -m ... search_papers ..."),
        # 不命中 tool，但严重度高
        _card(card_id="other_p0", severity="P0",
              repro_command="python -m ... unrelated_tool ...",
              tags=["other"]),
    ]
    out = lookup(cards, capability="retrieval", tool="search_papers", top_k=5)
    # 命中 tool 的卡片应排在前面，即便其 severity 较低（tool 命中权重最高）
    assert out[0].card_id == "match_p2"
    assert out[1].card_id == "other_p0"


def test_lookup_respects_top_k():
    cards = [_card(card_id=f"c{i}") for i in range(20)]
    out = lookup(cards, capability="retrieval", tool="", top_k=3)
    assert len(out) == 3


def test_lookup_tool_match_via_tags():
    cards = [
        _card(card_id="t1", tags=["search_papers", "rate_limit"], severity="P2"),
        _card(card_id="t2", tags=["other"], severity="P2"),
    ]
    out = lookup(cards, capability="retrieval", tool="search_papers", top_k=5)
    # tags 里包含 tool 名时也算命中
    assert out[0].card_id == "t1"

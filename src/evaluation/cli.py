from __future__ import annotations

"""
AcademicAgent 评测统一 CLI。

子命令：
  run              运行评测（按档位/层/任务过滤），落盘 artifacts + 门禁 + 报告
  gate             对一个 run 目录跑回归门禁，返回非零退出码表示 FAIL
  report           对一个 run 目录重新生成 HTML/MD 报告
  sync             把一个 run 目录同步到 Notion（本地优先，失败不阻断）
  list             列出数据集中的任务
  validate         校验数据集，返回非零退出码表示有问题
  promote-failures 把失败卡片转成新 gold 任务的候选（数据飞轮）
  lessons          查询历史失败卡片 -> 紧凑 lesson 列表（供宿主 Agent SOP 注入）

示例：
  python -m src.evaluation.cli run --dataset data/evaluation/datasets/smoke \\
      --out data/evaluation/runs --tier smoke --offline
  python -m src.evaluation.cli gate --run data/evaluation/runs/<run_id> --tier smoke
  python -m src.evaluation.cli validate --dataset data/evaluation/datasets/smoke
  python -m src.evaluation.cli lessons --capability retrieval --tool search_papers --top 3
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .dataset import load_dataset
from .schema import EvalLayer, Tier

logger = logging.getLogger("AcademicAgent.Eval.CLI")

_LAYER_MAP = {
    "component": EvalLayer.COMPONENT, "l1": EvalLayer.COMPONENT,
    "workflow": EvalLayer.WORKFLOW, "l2": EvalLayer.WORKFLOW,
    "e2e": EvalLayer.E2E, "l3": EvalLayer.E2E,
}


# ------------------------------------------------------------------ #
# run
# ------------------------------------------------------------------ #

def _cmd_run(args: argparse.Namespace) -> int:
    from .runner import run_evaluation

    tier = Tier(args.tier) if args.tier else None
    layers = None
    if args.layers:
        layers = [_LAYER_MAP[x.strip().lower()] for x in args.layers.split(",")]
    task_ids = [t.strip() for t in args.task.split(",")] if args.task else None

    summary = asyncio.run(run_evaluation(
        dataset_path=args.dataset, out_dir=args.out, tier=tier, layers=layers,
        offline=args.offline, run_id=args.run_id, model=args.model,
        enable_e2e=args.enable_e2e, notion=args.notion, task_ids=task_ids,
    ))
    totals = summary["totals"]
    print(f"\nrun 完成: {summary['run_id']}")
    print(f"  目录: data/evaluation/runs/{summary['run_id']}")
    print(f"  任务: {totals['total']} 总 / {totals['ok']} ok / "
          f"{totals['failed']} failed / {totals['skipped']} skipped")
    if totals.get("contaminated"):
        print("  [!] CONTAMINATED — 受保护文件被改动")
    # run 后顺带打印门禁结论
    gate_file = Path(args.out) / summary["run_id"] / "gate_result.json"
    if gate_file.exists():
        gate = json.loads(gate_file.read_text(encoding="utf-8"))
        print(f"  门禁: {gate['overall']} "
              f"(pass {gate['summary']['pass']} / warn {gate['summary']['warn']} "
              f"/ fail {gate['summary']['fail']})")
        return gate["exit_code"]
    return 0


# ------------------------------------------------------------------ #
# gate
# ------------------------------------------------------------------ #

def _cmd_gate(args: argparse.Namespace) -> int:
    from .gate import gate_from_run_dir

    result = gate_from_run_dir(
        args.run, thresholds_path=args.thresholds, baseline_path=args.baseline,
    )
    print(f"门禁结论: {result['overall']}  "
          f"(pass {result['summary']['pass']} / warn {result['summary']['warn']} "
          f"/ fail {result['summary']['fail']})")
    for c in result["metric_checks"] + result["budget_checks"]:
        if c["status"] in ("FAIL", "WARN"):
            print(f"  [{c['status']}] {c['metric']}: {c.get('reason', '')}")
    if result["contaminated"]:
        print("  [!] CONTAMINATED")
    return result["exit_code"]


# ------------------------------------------------------------------ #
# report
# ------------------------------------------------------------------ #

def _cmd_report(args: argparse.Namespace) -> int:
    from .reporting.html import generate_html_report
    from .reporting.markdown import generate_markdown_report

    run_dir = Path(args.run)
    html = generate_html_report(run_dir)
    md = generate_markdown_report(run_dir)
    print(f"报告已生成: {html}  {md}")
    return 0


# ------------------------------------------------------------------ #
# sync
# ------------------------------------------------------------------ #

def _cmd_sync(args: argparse.Namespace) -> int:
    from .notion_sync import NotionSync

    result = NotionSync().sync_run(args.run)
    if result is None:
        print("Notion 同步未执行或失败（详见 run 目录下 notion_sync.log）。"
              "本地结果不受影响。")
        return 0
    print(f"Notion 同步完成: {result.get('notion_url', result.get('notion_page_id'))}")
    return 0


# ------------------------------------------------------------------ #
# list
# ------------------------------------------------------------------ #

def _cmd_list(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    tier = Tier(args.tier) if args.tier else None
    tasks = dataset.filter(tier=tier)
    print(f"数据集 {args.dataset}  版本 {dataset.version.version}  共 {len(tasks)} 任务"
          + (f"（档位 {tier.value}）" if tier else ""))
    for t in tasks:
        target = (t.target.tool or t.target.workflow or "e2e")
        flags = []
        if t.requires_api:
            flags.append("api")
        if t.requires_llm:
            flags.append("llm")
        flag_str = f" [{'/'.join(flags)}]" if flags else ""
        print(f"  {t.task_id:22s} {t.layer.value:18s} {t.capability.value:16s} "
              f"{target:22s}{flag_str}")
    return 0


# ------------------------------------------------------------------ #
# validate
# ------------------------------------------------------------------ #

def _cmd_validate(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    problems = dataset.validate()
    if not problems:
        print(f"[OK] 数据集校验通过: {args.dataset} "
              f"({len(dataset.tasks)} 任务, 版本 {dataset.version.version})")
        return 0
    print(f"[FAIL] 数据集校验失败: {args.dataset}")
    for p in problems:
        print(f"  - {p}")
    return 1


# ------------------------------------------------------------------ #
# promote-failures
# ------------------------------------------------------------------ #

def _cmd_promote_failures(args: argparse.Namespace) -> int:
    """把失败卡片转成新 gold 任务候选 —— 数据飞轮。

    本期实现：打印每张卡片的摘要 + 建议的回归测试，输出一个候选清单。
    人工挑选后再编辑数据集（保留对 gold label 的最终判断权）。
    """
    cards_path = Path(args.cards)
    if not cards_path.exists():
        print(f"失败卡片文件不存在: {cards_path}")
        return 1
    cards = [json.loads(line) for line in cards_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cards:
        print("没有失败卡片。")
        return 0
    print(f"# 失败卡片 -> 回归任务候选（共 {len(cards)} 张）\n")
    for c in cards:
        print(f"## [{c['severity']}] {c['card_id']} — {c['task_id']} ({c['category']})")
        print(f"   回归测试建议: {c['regression_test_suggestion']}")
        print(f"   复现: {c['repro_command']}")
        print()
    print("下一步：人工挑选要纳入回归集的卡片，编辑 datasets/<tier>/tasks.jsonl 与对应 gold 文件。")
    return 0


# ------------------------------------------------------------------ #
# lessons
# ------------------------------------------------------------------ #

def _cmd_lessons(args: argparse.Namespace) -> int:
    """查询历史失败卡片 -> 紧凑 lesson 列表。

    用途：宿主 Agent (Antigravity/Claude Code) 在执行 workflow 前调用本命令，
    把"历史教训"作为 anti-pattern hint 注入到当前会话的 prompt 里。

    输出格式 --format text|json。text 适合人读 + 直接粘到 prompt；
    json 适合脚本化消费。
    """
    from .failure_lookup import load_all_cards, lookup

    cards = load_all_cards(args.cards_dir)
    if not cards:
        if args.format == "json":
            print("[]")
        else:
            print(f"# 历史失败教训 — 空（{args.cards_dir} 暂无卡片）")
        return 0

    lessons = lookup(
        cards, capability=args.capability or "", tool=args.tool or "",
        top_k=args.top,
    )
    if args.format == "json":
        print(json.dumps(
            [
                {
                    "card_id": le.card_id,
                    "capability": le.capability,
                    "category": le.category,
                    "severity": le.severity,
                    "root_cause": le.root_cause_hypothesis,
                    "fix_candidate": le.fix_candidate,
                    "tags": list(le.tags),
                }
                for le in lessons
            ],
            ensure_ascii=False, indent=2,
        ))
        return 0

    # text 格式
    header_parts = []
    if args.capability:
        header_parts.append(f"capability={args.capability}")
    if args.tool:
        header_parts.append(f"tool={args.tool}")
    header = " ".join(header_parts) if header_parts else "all"
    print(f"# 历史失败教训 — {header}（top {len(lessons)}/{len(cards)}）\n")
    if not lessons:
        print("（过滤后无匹配卡片）")
        return 0
    for le in lessons:
        print(f"## [{le.severity}] {le.card_id} — {le.category}")
        if le.root_cause_hypothesis:
            print(f"  根因假设: {le.root_cause_hypothesis}")
        if le.fix_candidate:
            print(f"  修复候选: {le.fix_candidate}")
        if le.tags:
            print(f"  标签: {', '.join(le.tags)}")
        print()
    return 0


# ------------------------------------------------------------------ #
# parser
# ------------------------------------------------------------------ #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.evaluation.cli",
        description="AcademicAgent 评测统一 CLI",
    )
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="command", required=True)

    # run
    pr = sub.add_parser("run", help="运行评测")
    pr.add_argument("--dataset", required=True)
    pr.add_argument("--out", default="data/evaluation/runs")
    pr.add_argument("--tier", choices=["smoke", "full"], default=None)
    pr.add_argument("--layers", default=None,
                    help="逗号分隔: component,workflow,e2e（默认 component,workflow）")
    pr.add_argument("--task", default=None, help="只跑指定 task_id（逗号分隔）")
    pr.add_argument("--offline", action="store_true", help="跳过所有需要 API/LLM 的任务")
    pr.add_argument("--run-id", default=None)
    pr.add_argument("--model", default=None)
    pr.add_argument("--notion", action="store_true", help="run 后自动同步到 Notion")
    pr.add_argument("--enable-e2e", action="store_true", help="启用 L3 端到端层（本期未实现）")
    pr.set_defaults(func=_cmd_run)

    # gate
    pg = sub.add_parser("gate", help="对 run 目录跑回归门禁")
    pg.add_argument("--run", required=True, help="run 目录")
    pg.add_argument("--tier", default=None, help="（仅用于提示，门禁本身读 run_summary.json）")
    pg.add_argument("--thresholds", default=None, help="thresholds.yaml 路径")
    pg.add_argument("--baseline", default=None, help="baseline run_summary.json 路径")
    pg.set_defaults(func=_cmd_gate)

    # report
    prp = sub.add_parser("report", help="重新生成报告")
    prp.add_argument("--run", required=True)
    prp.set_defaults(func=_cmd_report)

    # sync
    ps = sub.add_parser("sync", help="同步 run 到 Notion")
    ps.add_argument("--run", required=True)
    ps.set_defaults(func=_cmd_sync)

    # list
    pl = sub.add_parser("list", help="列出数据集任务")
    pl.add_argument("--dataset", required=True)
    pl.add_argument("--tier", choices=["smoke", "full"], default=None)
    pl.set_defaults(func=_cmd_list)

    # validate
    pv = sub.add_parser("validate", help="校验数据集")
    pv.add_argument("--dataset", required=True)
    pv.set_defaults(func=_cmd_validate)

    # promote-failures
    pf = sub.add_parser("promote-failures", help="失败卡片 -> 回归任务候选")
    pf.add_argument("--cards", required=True, help="failure_cards/<run_id>.jsonl 路径")
    pf.set_defaults(func=_cmd_promote_failures)

    # lessons
    pls = sub.add_parser(
        "lessons",
        help="查询历史失败卡片 -> 紧凑 lesson 列表（供宿主 Agent SOP 注入）",
    )
    pls.add_argument(
        "--cards-dir", default="data/evaluation/failure_cards",
        help="失败卡片目录（默认 data/evaluation/failure_cards）",
    )
    pls.add_argument("--capability", default=None,
                     help="按能力过滤，如 retrieval / kg_extraction / kg_query / ...")
    pls.add_argument("--tool", default=None,
                     help="按工具名过滤（软匹配 repro_command / tags）")
    pls.add_argument("--top", type=int, default=5, help="返回 top-K（默认 5）")
    pls.add_argument("--format", choices=["text", "json"], default="text",
                     help="输出格式：text 给人 + 粘 prompt；json 给脚本")
    pls.set_defaults(func=_cmd_lessons)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

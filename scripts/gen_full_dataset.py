from __future__ import annotations

"""
一次性脚本：生成 data/evaluation/datasets/full/ 完整档评测数据集。

full 档 ~32 任务，覆盖全部能力。kg_extraction 的论文摘要片段内联在 tasks.jsonl
中（即「fixture」），retrieval/figure 需网络或 Vision，gap/kg_query/code 离线可跑。
gold label 由人工复核（这是脚手架，不是终稿）。
"""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL = ROOT / "data" / "evaluation" / "datasets" / "full"
SMOKE = ROOT / "data" / "evaluation" / "datasets" / "smoke"
FIX = FULL / "fixtures"


# --------------------------------------------------------------- #
# 论文摘要片段（KG 抽取的离线 fixture）
# --------------------------------------------------------------- #
ABSTRACTS = {
    "react": ("ReAct", "2022",
        "We propose ReAct, a paradigm that synergizes reasoning and acting in "
        "language models. ReAct prompts LLMs to generate interleaved verbal "
        "reasoning traces and task-specific actions. ReAct is evaluated on "
        "question answering and fact verification, and outperforms imitation "
        "and reinforcement learning baselines.",
        [{"label": "ReAct", "node_type": "method"},
         {"label": "language model", "node_type": "concept"},
         {"label": "reasoning trace", "node_type": "concept"},
         {"label": "question answering", "node_type": "dataset"}],
        [{"source_label": "ReAct", "relation_type": "uses", "target_label": "language model"},
         {"source_label": "ReAct", "relation_type": "tested_on", "target_label": "question answering"}]),
    "memgpt": ("MemGPT", "2023",
        "We present MemGPT, inspired by hierarchical memory systems in operating "
        "systems. MemGPT manages memory tiers to provide the appearance of large "
        "context within a fixed-context LLM, moving information between in-context "
        "storage and external archival and recall memory.",
        [{"label": "MemGPT", "node_type": "method"},
         {"label": "hierarchical memory", "node_type": "concept"},
         {"label": "archival memory", "node_type": "concept"},
         {"label": "context window", "node_type": "concept"}],
        [{"source_label": "MemGPT", "relation_type": "uses", "target_label": "hierarchical memory"},
         {"source_label": "MemGPT", "relation_type": "uses", "target_label": "context window"}]),
    "toolformer": ("Toolformer", "2023",
        "We introduce Toolformer, a model trained to decide which APIs to call, "
        "when, with what arguments, and how to incorporate results into future "
        "token prediction. Toolformer improves zero-shot performance across tasks.",
        [{"label": "Toolformer", "node_type": "method"},
         {"label": "API", "node_type": "tool"},
         {"label": "zero-shot performance", "node_type": "metric"}],
        [{"source_label": "Toolformer", "relation_type": "uses", "target_label": "API"},
         {"source_label": "Toolformer", "relation_type": "evaluated_by", "target_label": "zero-shot performance"}]),
    "reflexion": ("Reflexion", "2023",
        "Reflexion reinforces language agents through linguistic feedback rather "
        "than weight updates. Agents verbally reflect on feedback and store "
        "reflective text in episodic memory to improve subsequent trials. "
        "Reflexion is evaluated on HumanEval coding tasks.",
        [{"label": "Reflexion", "node_type": "method"},
         {"label": "linguistic feedback", "node_type": "concept"},
         {"label": "episodic memory", "node_type": "concept"},
         {"label": "HumanEval", "node_type": "dataset"}],
        [{"source_label": "Reflexion", "relation_type": "uses", "target_label": "episodic memory"},
         {"source_label": "Reflexion", "relation_type": "tested_on", "target_label": "HumanEval"}]),
    "autogen": ("AutoGen", "2023",
        "AutoGen is a framework that enables building LLM applications via "
        "multiple agents that converse to solve tasks. AutoGen agents are "
        "customizable and can use tools and human feedback in multi-agent "
        "conversation patterns.",
        [{"label": "AutoGen", "node_type": "method"},
         {"label": "multi-agent conversation", "node_type": "concept"},
         {"label": "tool use", "node_type": "concept"}],
        [{"source_label": "AutoGen", "relation_type": "uses", "target_label": "multi-agent conversation"},
         {"source_label": "AutoGen", "relation_type": "uses", "target_label": "tool use"}]),
    "generative_agents": ("Generative Agents", "2023",
        "Generative Agents are computational agents that simulate believable "
        "human behavior. They use a memory stream to record experiences, "
        "retrieval to surface relevant memories, reflection to synthesize "
        "higher-level inferences, and planning to translate inferences into "
        "actions.",
        [{"label": "Generative Agents", "node_type": "method"},
         {"label": "memory stream", "node_type": "concept"},
         {"label": "reflection", "node_type": "concept"},
         {"label": "planning", "node_type": "concept"}],
        [{"source_label": "Generative Agents", "relation_type": "uses", "target_label": "memory stream"},
         {"source_label": "Generative Agents", "relation_type": "uses", "target_label": "reflection"},
         {"source_label": "Generative Agents", "relation_type": "uses", "target_label": "planning"}]),
    "voyager": ("Voyager", "2023",
        "Voyager is an LLM-powered embodied lifelong learning agent in Minecraft. "
        "It uses an automatic curriculum, a skill library of executable code, and "
        "an iterative prompting mechanism that incorporates environment feedback.",
        [{"label": "Voyager", "node_type": "method"},
         {"label": "automatic curriculum", "node_type": "concept"},
         {"label": "skill library", "node_type": "concept"}],
        [{"source_label": "Voyager", "relation_type": "uses", "target_label": "automatic curriculum"},
         {"source_label": "Voyager", "relation_type": "uses", "target_label": "skill library"}]),
    "hugginggpt": ("HuggingGPT", "2023",
        "HuggingGPT uses an LLM as a controller to manage and connect various AI "
        "models from machine learning communities to solve tasks. The LLM plans "
        "tasks, selects models, executes subtasks, and summarizes responses.",
        [{"label": "HuggingGPT", "node_type": "method"},
         {"label": "task planning", "node_type": "concept"},
         {"label": "model selection", "node_type": "concept"}],
        [{"source_label": "HuggingGPT", "relation_type": "uses", "target_label": "task planning"},
         {"source_label": "HuggingGPT", "relation_type": "uses", "target_label": "model selection"}]),
    "tot": ("Tree of Thoughts", "2023",
        "Tree of Thoughts generalizes chain-of-thought prompting by exploring "
        "coherent units of text as intermediate steps toward problem solving, "
        "enabling deliberate decision making with lookahead and backtracking.",
        [{"label": "Tree of Thoughts", "node_type": "method"},
         {"label": "chain-of-thought", "node_type": "concept"},
         {"label": "deliberate decision making", "node_type": "concept"}],
        [{"source_label": "Tree of Thoughts", "relation_type": "improves", "target_label": "chain-of-thought"}]),
    "rag": ("Retrieval-Augmented Generation", "2020",
        "Retrieval-Augmented Generation combines a parametric seq2seq model with "
        "a non-parametric memory in the form of a dense vector index of Wikipedia "
        "accessed with a neural retriever, improving knowledge-intensive tasks.",
        [{"label": "Retrieval-Augmented Generation", "node_type": "method"},
         {"label": "dense vector index", "node_type": "concept"},
         {"label": "neural retriever", "node_type": "concept"}],
        [{"source_label": "Retrieval-Augmented Generation", "relation_type": "uses", "target_label": "neural retriever"}]),
}

RETRIEVAL_QUERIES = {
    "react": ("ReAct synergizing reasoning and acting in language models",
              ["ReAct: Synergizing Reasoning and Acting in Language Models"]),
    "memgpt": ("MemGPT towards LLMs as operating systems memory management",
               ["MemGPT: Towards LLMs as Operating Systems"]),
    "toolformer": ("Toolformer language models can teach themselves to use tools",
                   ["Toolformer: Language Models Can Teach Themselves to Use Tools"]),
    "reflexion": ("Reflexion language agents with verbal reinforcement learning",
                  ["Reflexion: Language Agents with Verbal Reinforcement Learning"]),
    "autogen": ("AutoGen enabling next-gen LLM applications via multi-agent conversation",
                ["AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation"]),
    "generative_agents": ("Generative Agents interactive simulacra of human behavior",
                          ["Generative Agents: Interactive Simulacra of Human Behavior"]),
    "voyager": ("Voyager open-ended embodied agent with large language models",
                ["Voyager: An Open-Ended Embodied Agent with Large Language Models"]),
    "tot": ("Tree of Thoughts deliberate problem solving with large language models",
            ["Tree of Thoughts: Deliberate Problem Solving with Large Language Models"]),
}


def task(tid, layer, cap, target, gold_file, metrics, *, tier="full",
         req_api=False, req_llm=False, timeout=90, tags=None, notes=""):
    return {
        "task_id": tid, "layer": layer, "capability": cap, "tier": tier,
        "target": target,
        "gold": {"gold_file": gold_file, "gold_key": tid, "metrics": metrics},
        "timeout_s": timeout, "requires_api": req_api, "requires_llm": req_llm,
        "tags": tags or [], "notes": notes,
    }


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    # 复用 smoke 的 seed 图谱
    shutil.copy2(SMOKE / "fixtures" / "seed_graph_agents.json",
                 FIX / "seed_graph_agents.json")

    tasks: list[dict] = []
    kg_gold: list[dict] = []
    retrieval_gold: list[dict] = []
    kg_query_gold: list[dict] = []
    gap_gold: list[dict] = []
    code_gold: list[dict] = []
    figure_gold: list[dict] = []
    workflow_gold: list[dict] = []

    # --- KG extraction (10) ---
    for key, (title, year, text, nodes, edges) in ABSTRACTS.items():
        tid = f"full_kg_{key}"
        tasks.append(task(
            tid, "layer1_component", "kg_extraction",
            {"tool": "add_paper_to_graph",
             "args": {"text": text, "paper_title": title, "paper_year": year}},
            "kg_gold.jsonl",
            ["kg_node_f1", "kg_edge_f1", "schema_validity_rate", "extraction_nonempty_rate"],
            req_llm=True, timeout=120, tags=["kg", key],
            notes=f"{title} 摘要的实体/关系抽取",
        ))
        kg_gold.append({"task_id": tid, "expected_nodes": nodes,
                        "expected_edges": edges,
                        "min_kg_node_f1": 0.3, "min_kg_edge_f1": 0.2})

    # --- retrieval (8) ---
    for key, (query, titles) in RETRIEVAL_QUERIES.items():
        tid = f"full_search_{key}"
        tasks.append(task(
            tid, "layer1_component", "retrieval",
            {"tool": "search_papers", "args": {"query": query, "limit": 5}},
            "retrieval_gold.jsonl", ["recall_at_5", "mrr"],
            req_api=True, timeout=45, tags=["search", key],
            notes=f"Semantic Scholar 检索 {key}",
        ))
        retrieval_gold.append({"task_id": tid, "query": query,
                               "gold_paper_ids": [], "gold_titles": titles,
                               "min_recall_at_5": 0.5})

    # --- kg_query (4) ---
    kg_query_specs = [
        ("full_kgq_react", "ReAct", ["ReAct"]),
        ("full_kgq_memory", "memory", ["memory"]),
        ("full_kgq_toolformer", "Toolformer", ["Toolformer"]),
        ("full_kgq_planning", "planning", ["planning"]),
    ]
    for tid, query, expected in kg_query_specs:
        tasks.append(task(
            tid, "layer1_component", "kg_query",
            {"tool": "query_knowledge", "args": {"query": query}},
            "kg_query_gold.jsonl", ["query_hit_rate"],
            timeout=45, tags=["kg_query", "offline", "fixture"],
            notes=f"在 seed 图谱上查询 {query!r}",
        ))
        kg_query_gold.append({
            "task_id": tid, "seed_graph": "fixtures/seed_graph_agents.json",
            "expected_labels": expected,
        })

    # --- gap_detection (4) ---
    gap_specs = [
        ("full_gap_isolated", ["isolated_concept"], ["planning"]),
        ("full_gap_foundation", ["foundation_gap"], ["tool use"]),
        ("full_gap_single_source", ["single_source"], []),
        ("full_gap_any", ["isolated_concept"], ["planning"]),
    ]
    for tid, gtypes, glabels in gap_specs:
        tasks.append(task(
            tid, "layer1_component", "gap_detection",
            {"tool": "detect_gaps", "args": {}},
            "gap_gold.jsonl", ["gap_type_match"],
            timeout=60, tags=["gap", "offline", "fixture"],
            notes=f"在 seed 图谱上检测盲区，期望含 {gtypes}",
        ))
        gap_gold.append({
            "task_id": tid, "seed_graph": "fixtures/seed_graph_agents.json",
            "expected_gap_types": gtypes, "expected_gap_labels": glabels,
            "expected_top_concepts": [],
        })

    # --- code_exec (5) ---
    code_specs = [
        ("full_code_template_agent", {"tool": "run_template",
            "args": {"template_name": "agent_eval_toy"}},
         {"expect_success": True, "expect_stdout_contains": [], "expect_artifact": True},
         ["code_success_rate", "artifact_produced_rate"]),
        ("full_code_template_rag", {"tool": "run_template",
            "args": {"template_name": "rag_retrieval_eval"}},
         {"expect_success": True, "expect_stdout_contains": [], "expect_artifact": True},
         ["code_success_rate", "artifact_produced_rate"]),
        ("full_code_numpy", {"tool": "run_code",
            "args": {"code": "import numpy as np\nprint('mean', float(np.arange(5).mean()))"}},
         {"expect_success": True, "expect_stdout_contains": ["mean 2.0"], "expect_artifact": False},
         ["code_success_rate", "stdout_assertion_pass"]),
        ("full_code_list_templates", {"tool": "list_code_templates", "args": {}},
         {"expect_success": True, "expect_stdout_contains": [], "expect_artifact": False},
         ["code_success_rate"]),
        ("full_code_safety", {"tool": "run_code",
            "args": {"code": "import math\nprint('sqrt2', round(math.sqrt(2), 4))"}},
         {"expect_success": True, "expect_stdout_contains": ["sqrt2 1.4142"],
          "expect_artifact": False},
         ["code_success_rate", "stdout_assertion_pass"]),
    ]
    for tid, target, gold, metrics in code_specs:
        tasks.append(task(
            tid, "layer1_component", "code_exec", target,
            "code_gold.jsonl", metrics, timeout=60, tags=["code", "offline"],
            notes="离线代码执行评测",
        ))
        code_gold.append({"task_id": tid, **gold})

    # --- figure_analysis (3) ---
    # analyze_pdf / get_paper_structure 是离线纯文本，无能力指标，仅追踪完成度。
    fig_specs = [
        ("full_fig_pdf_memgpt", {"tool": "analyze_pdf",
            "args": {"pdf_path": "data/papers/MemGPT.pdf"}}, [], False),
        ("full_fig_structure_survey", {"tool": "get_paper_structure",
            "args": {"pdf_path": "data/papers/LLM_Agent_Survey.pdf"}}, [], False),
        ("full_fig_page_react", {"tool": "analyze_page",
            "args": {"pdf_path": "data/papers/arxiv_2210_03629.pdf", "page_num": 0}},
         ["figure_type_accuracy"], True),
    ]
    for tid, target, metrics, req_llm in fig_specs:
        tasks.append(task(
            tid, "layer1_component", "figure_analysis", target,
            "figure_gold.jsonl", metrics, req_llm=req_llm, timeout=120,
            tags=["figure", "pdf"], notes="PDF/图表分析",
        ))
        figure_gold.append({
            "task_id": tid,
            "pdf_path": target["args"]["pdf_path"],
            "expect_figure_type": "block_diagram",
            "expect_entities_contains": [],
            "notes": "expect_figure_type 为占位猜测，需人工复核",
        })

    # --- workflow (2) ---
    tasks.append(task(
        "full_wf_learn", "layer2_workflow", "workflow",
        {"workflow": "learn_flow"},
        "workflow_gold.jsonl",
        ["workflow_completion_rate", "tool_sequence_match", "step_success_rate",
         "final_assertion_pass"],
        timeout=120, tags=["workflow", "offline", "fixture"],
        notes="离线 L2：seed 图谱上的学习路径链路",
    ))
    workflow_gold.append({
        "task_id": "full_wf_learn", "workflow": "learn_flow",
        "seed_graph": "fixtures/seed_graph_agents.json",
        "expected_tool_sequence": ["detect_gaps", "get_concept_importance", "analyze_knowledge"],
        "final_assertions": [{"check": "step_captured_min", "key": "path_length", "value": 1}],
    })
    tasks.append(task(
        "full_wf_survey", "layer2_workflow", "workflow",
        {"workflow": "survey_flow",
         "args": {"query": "Reflexion language agents verbal reinforcement", "limit": 3}},
        "workflow_gold.jsonl",
        ["workflow_completion_rate", "tool_sequence_match", "step_success_rate",
         "final_assertion_pass"],
        req_api=True, req_llm=True, timeout=240, tags=["workflow", "survey"],
        notes="在线 L2：检索->详情->抽取->回查",
    ))
    workflow_gold.append({
        "task_id": "full_wf_survey", "workflow": "survey_flow",
        "expected_tool_sequence": ["search_papers", "get_paper_details",
                                   "add_paper_to_graph", "query_knowledge"],
        "final_assertions": [{"check": "graph_min_nodes", "value": 1}],
    })

    # --- 写盘 ---
    def write_jsonl(name, rows):
        with open(FULL / name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    write_jsonl("tasks.jsonl", tasks)
    write_jsonl("kg_gold.jsonl", kg_gold)
    write_jsonl("retrieval_gold.jsonl", retrieval_gold)
    write_jsonl("kg_query_gold.jsonl", kg_query_gold)
    write_jsonl("gap_gold.jsonl", gap_gold)
    write_jsonl("code_gold.jsonl", code_gold)
    write_jsonl("figure_gold.jsonl", figure_gold)
    write_jsonl("workflow_gold.jsonl", workflow_gold)

    tasks_text = (FULL / "tasks.jsonl").read_text(encoding="utf-8")
    sha = hashlib.sha256(tasks_text.encode("utf-8")).hexdigest()
    by_layer: dict[str, int] = {}
    for t in tasks:
        by_layer[t["layer"]] = by_layer.get(t["layer"], 0) + 1
    version = {
        "version": "1.0.0",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "task_count_by_layer": by_layer,
        "tasks_sha256": sha,
        "notes": "full 档：由 scripts/gen_full_dataset.py 生成。gold label 需人工复核。",
    }
    (FULL / "dataset_version.json").write_text(
        json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"full 数据集已生成: {len(tasks)} 任务")
    for layer, n in by_layer.items():
        print(f"  {layer}: {n}")


if __name__ == "__main__":
    main()

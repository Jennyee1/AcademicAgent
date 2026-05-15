# 评测数据集说明（Dataset Card）

## 概述

AcademicAgent 评测数据集分两档，位于 `data/evaluation/datasets/`：

| 档位 | 任务数 | 用途 | 离线可跑 |
|:---|---:|:---|:---|
| `smoke` | 12 | 回归门禁、提交/demo 前快速验证（<2min） | 4 个任务完全离线 |
| `full` | 36 | 完整能力评测、初步有效性验证 | 16 个任务完全离线 |

## 目录结构

```
datasets/<tier>/
  tasks.jsonl            每行一条 TaskSpec
  dataset_version.json   版本号 + 按层任务数 + tasks.jsonl 的 sha256
  retrieval_gold.jsonl   按 task_id 索引的 gold（检索）
  kg_gold.jsonl          知识图谱抽取 gold
  kg_query_gold.jsonl    图谱查询 gold
  gap_gold.jsonl         盲区检测 gold
  code_gold.jsonl        代码执行 gold
  figure_gold.jsonl      图表分析 gold
  workflow_gold.jsonl    L2 工作流 gold
  fixtures/              seed 图谱等固定 fixture
```

## TaskSpec 字段

| 字段 | 说明 |
|:---|:---|
| `task_id` | 唯一标识 |
| `layer` | `layer1_component` / `layer2_workflow` / `layer3_e2e` |
| `capability` | retrieval / kg_extraction / kg_query / gap_detection / code_exec / figure_analysis / workflow |
| `tier` | smoke / full |
| `target` | L1: `{tool, args}`；L2: `{workflow, args}`；L3: `{e2e_prompt}` |
| `gold` | `{gold_file, gold_key, metrics}` —— 指向 gold 文件 + 要计算的指标名 |
| `requires_api` | 需要外部 HTTP API（Semantic Scholar）；`--offline` 时跳过 |
| `requires_llm` | 需要 LLM API key（MiniMax）；`--offline` 或无 key 时跳过 |

## full 档任务分布

| 能力 | 数量 | 数据来源 | 离线 |
|:---|---:|:---|:---|
| kg_extraction | 10 | ReAct / MemGPT / Toolformer / Reflexion / AutoGen / Generative Agents / Voyager / HuggingGPT / Tree of Thoughts / RAG 摘要片段（内联） | 否（需 LLM） |
| retrieval | 8 | Semantic Scholar 在线检索 | 否（需 API） |
| kg_query | 4 | seed 图谱 fixture | 是 |
| gap_detection | 4 | seed 图谱 fixture | 是 |
| code_exec | 5 | 代码模板 + 内联片段 | 是 |
| figure_analysis | 3 | `data/papers/*.pdf` | 2 离线 / 1 需 Vision |
| workflow (L2) | 2 | learn_flow（离线）+ survey_flow（在线） | 1 离线 |

## gold label 复核约定

- gold label 由人工保留最终判断权。`scripts/gen_full_dataset.py` 生成的是**脚手架**，
  不是终稿 —— 特别是 `figure_gold.jsonl` 的 `expect_figure_type` 为占位猜测。
- 失败案例可通过 `python -m src.evaluation.cli promote-failures --cards <jsonl>`
  转为回归任务候选，人工挑选后纳入数据集 —— 这是数据飞轮。

## 复现性

- `dataset_version.json` 记录 `tasks.jsonl` 的 sha256；`cli validate` 会校验一致性。
- KG 抽取的论文摘要内联在 tasks.jsonl 中，离线确定（不依赖外部检索）。
- gap/kg_query 用固定 seed 图谱 fixture，图算法结果确定。
- 每次 run 的 `config.json` 记录数据集版本、代码 git hash、模型、环境。

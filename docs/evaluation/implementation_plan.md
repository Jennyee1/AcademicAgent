# AcademicAgent 评测子系统 — 架构与使用（As-Built）

> 本文档描述 **已落地** 的评测子系统。它取代了早期的规划草案。
> 配套文档：[`metric_catalog.md`](metric_catalog.md)、[`dataset_card.md`](dataset_card.md)、
> 实验记录 [`../experiments/2026-05-15_eval_redesign.md`](../experiments/2026-05-15_eval_redesign.md)。

## 1. 设计目标

在**不污染主知识图谱（`data/knowledge_graph.json`）和长期记忆（`memory/MEMORY.md`、
`memory/USER.md`）**的前提下，为面向 LLM Agent 研究的多模态知识 Agent 提供
**分层、可复现、可解释、可持续改进**的评测闭环。

## 2. 分层评测

| 层 | 模块 | 说明 |
|:---|:---|:---|
| L1 组件级 | `layers/layer1_component.py` | 逐 MCP 工具，通过 `adapters/` 隔离调用 |
| L2 工作流 | `layers/layer2_workflow.py` + `workflows/` | 固定有序工具链，**无 LLM 决策**，可复现 |
| L3 端到端 | `layers/layer3_e2e.py` | 接口骨架（本期未实现 LLM driver） |

## 3. Sidecar 隔离（核心）

`isolation.py` 三重保险兑现「绝不污染真实数据」：
1. 每任务在 `run_dir/sidecar/<task_id>/` 下建隔离目录树。
2. 进入上下文覆盖 `SCHOLARMIND_DATA_DIR`，退出还原。
3. adapters 用隔离路径直接构造 `KnowledgeGraphStore(graph_path=...)` /
   `CodeSandbox(work_dir=...)`，绕开 MCP server 的模块级单例。
4. **污染守卫**：run 前后比对受保护文件 sha256，变化则标记 `CONTAMINATED`，门禁硬失败。

MCP 调用策略：**进程内直接调用底层类**，不 spawn MCP stdio server。

## 4. 模块结构 `src/evaluation/`

```
schema.py        数据模型（EvalLayer / Capability / Tier / TaskSpec / TraceEvent / ...）
isolation.py     sidecar 隔离 + 污染检测
dataset.py       数据集加载与校验
tracer.py        JSONL trace 记录器
adapters/        对 Agent 真实组件的类型化封装（唯一 import 业务代码处）
metrics/         纯函数指标 + METRIC_REGISTRY
layers/          L1 / L2 / L3 runner
workflows/       L2 脚本化工作流定义
aggregate.py     per-task 指标 -> run_summary.json
gate.py          回归门禁（阈值 + baseline 对比）
failure_cards.py 结构化失败卡片（数据飞轮）
cost.py          基于 token 的成本估算
reporting/       HTML/MD 报告 + 版本迭代日志
notion_sync.py   Notion 镜像（本地优先 + 优雅降级）
cli.py           统一 CLI
thresholds.yaml  回归门禁阈值（git 跟踪）
```

模块边界：只有 `adapters/` import 业务代码；`metrics/` 为纯函数；`runner.py` 仅编排。

## 5. run artifact 布局

```
data/evaluation/runs/<run_id>/
  config.json          可复现元数据（数据集版本、code hash、模型、环境）
  traces.jsonl         逐事件 trace
  task_results.json    每任务结构化结果
  metrics.json         per-task 指标明细
  run_summary.json     聚合结果（事实来源）
  latency_stats.json   延迟分布
  cost.json            成本（含估算方式）
  gate_result.json     门禁判定
  failures.md          失败卡片（人类可读）
  report.html / .md    评测报告
  notion_sync.json/.log Notion 同步状态/日志
  sidecar/<task_id>/   每任务隔离的图谱/记忆/沙箱
data/evaluation/failure_cards/<run_id>.jsonl   失败卡片（机器可读，供飞轮）
data/evaluation/baselines/                     baseline 快照
docs/experiments/eval_runs.md                  版本迭代日志（Notion 的本地镜像）
```

## 6. CLI

```bash
# 运行评测（离线 smoke，回归门禁用）
python -m src.evaluation.cli run --dataset data/evaluation/datasets/smoke \
    --tier smoke --offline

# 完整档 + 自动同步 Notion
python -m src.evaluation.cli run --dataset data/evaluation/datasets/full \
    --tier full --notion

# 回归门禁（返回非零退出码表示 FAIL）
python -m src.evaluation.cli gate --run data/evaluation/runs/<run_id> \
    --baseline data/evaluation/baselines/smoke_baseline.json

# 其它
python -m src.evaluation.cli validate --dataset data/evaluation/datasets/smoke
python -m src.evaluation.cli list --dataset data/evaluation/datasets/full --tier full
python -m src.evaluation.cli report --run data/evaluation/runs/<run_id>
python -m src.evaluation.cli sync --run data/evaluation/runs/<run_id>
python -m src.evaluation.cli promote-failures --cards data/evaluation/failure_cards/<run_id>.jsonl
```

`--offline` 跳过所有 `requires_api` / `requires_llm` 任务，使 smoke run 完全确定、
不触达任何外部服务 —— 适合作为提交/demo 前的手动门禁。

## 7. 可解释性与数据飞轮

- 每个指标带 `numerator` / `denominator` / `notes`，可人工复核。
- 每个失败任务、每个低于阈值的指标、每次污染事件，都产出结构化 `FailureCard`：
  分类、严重度（P0/P1/P2）、精确复现命令、trace 摘要、根因假设（确定性规则表，非 LLM）、
  修复候选、回归测试建议。
- 失败卡片写 jsonl，`cli promote-failures` 把它们转为新 gold 任务候选 —— 数据飞轮。

## 8. Notion 同步

本地优先：`data/evaluation/runs/` 永远是事实来源。`notion_sync.py` 通过 Notion REST API
镜像三个目标：每 run 一个实验子页、父页面的版本迭代日志、阈值突破红/绿 callout。
所有调用经 `_safe()` 包裹 —— Notion 失败永不抛错、不改退出码、不阻断本地 artifact。
配置见 `data/evaluation/notion_config.json`（gitignored）。

## 9. 已知问题

- **MiniMax extraction 400 bug**：`ExtractionOutput` 的 json_schema property description
  超过 MiniMax 200 字符上限，导致 KG 抽取报错。评测现在稳定暴露它为
  `failed/llm_api_error`（非静默 0.0），`smoke_kg_long` 是回归锚点。修复在评测范围之外。
- L3 端到端的 LLM driver 延后实现。
- full 档 gold label（尤其 `figure_gold.jsonl`）需人工复核校准。

## 10. 如何回答「你的 Agent 怎么证明有效？」

1. **系统可靠性**：`tool_success_rate`、延迟分布、成本（含估算方式）。
2. **学术质量**：检索 `recall@k` / `mrr`、KG 抽取 F1、Schema 合法率。
3. **工作流价值**：L2 工作流完成率、工具序列匹配；以及由失败卡片驱动的持续改进记录。
4. **自纠错能力**：`lesson_assisted_rate` 软指标（见 §11）—— 量化"被 critic 救活"的任务占比。

## 11. Runtime self-correction —— 失败卡片飞轮的双向闭环

§7 的失败卡片是**离线**飞轮：失败 → 卡片 → `promote-failures` → 新 gold。
本节描述与之并行的**在线**飞轮：让 runtime 能读取历史卡片、在调用时避坑、在失败后受限重试。

### 11.1 组件

```
src/evaluation/
  failure_lookup.py   加载 + 按 (capability, tool, severity, 新鲜度) 排序匹配
  critic.py           确定性 (no-LLM) 控制器:
                        - derive_pre_hints()      调用前预防
                        - decide_after_failure()  失败后决策重试 + 修正动作
  layers/layer1_component.py
                       在 adapter 调用前注入 lessons + pre-hints；
                       失败后过 critic；每任务硬上限 max_retries=1；
                       critic 决策痕迹写 raw["_critic"] 供审计
  adapters/base.py    AdapterContext 增 lessons / hints 字段
  adapters/{extractor,paper_search}.py
                       消费 backoff_ms / retry_delay_ms hint
  aggregate.py        新增软指标 lesson_assisted_rate (warn-only)
```

### 11.2 Hint 约定

| hint key | 含义 | 触发源 |
|:---|:---|:---|
| `backoff_ms` | 调用前 sleep N ms | 历史 `rate_limit` lesson / 失败后 critic |
| `retry_delay_ms` | 同上，用于 transient `llm_api_error` / `network` | 失败后 critic |

未识别的 key 一律忽略 —— 向前兼容。adapter 实现自行决定如何应用 hint。

### 11.3 critic 决策表（确定性规则，与 `failure_cards._RULES` 同风格）

| 错误类别 | 决策 | 修正动作 |
|:---|:---|:---|
| `rate_limit` | 重试 1 次 | `backoff_ms=5000` |
| `timeout` | 重试 1 次 | `retry_delay_ms=1500` |
| `llm_api_error` 且历史含"description ... 200 字符上限" | **不重试** | 已知不可修，省 token |
| `llm_api_error`（其它） | 重试 1 次 | `retry_delay_ms=2000` |
| `network` | 重试 1 次 | `retry_delay_ms=1000` |
| `empty_extraction` | 不重试 | 无 prompt 级 hint 通道 |
| 其它 | 不重试 | 保守默认 |

预算 `_MAX_CRITIC_RETRIES = 1`。提高它的代价是延迟与 token，须明确动机。

### 11.4 宿主 Agent SOP 注入（路径 B）

CLI 新增：

```bash
python -m src.evaluation.cli lessons \
    --capability retrieval --tool search_papers --top 3 \
    [--format text|json]
```

四个 workflow 的"前置准备"段已加上调用：宿主 Agent（Antigravity / Claude Code）在
执行 SOP 前先把命令输出作为 anti-pattern hint 注入到当前会话 prompt。这与
路径 A（evaluation runtime 自己消费 hints）是同一查找逻辑、不同消费者。

### 11.5 lesson_assisted_rate 软指标

`aggregate.py` 在 `by_metric` 中新增 `lesson_assisted_rate`：

- numerator   = 任务成功 **且**（pre_hints 非空 或 critic 触发了重试）
- denominator = 所有非 skipped 任务

趋势上升 → critic 在挽救更多任务（飞轮起效）。
趋势下降 → 要么底层 bug 被根治（好），要么 critic 失效（坏）—— 须结合
`completion_rate` 一起解读。**warn-only**，不进硬门禁，避免"为了好看而故意触发 critic"
反向激励。

### 11.6 测试

- `tests/test_failure_lookup.py` — 11 例，覆盖目录缺失/空、损坏文件容错、按 capability
  过滤、severity 排序、tool 命中加权、tags 命中、top_k。
- `tests/test_runtime_critic.py` — 11 例，含 critic 单测 + 三个端到端场景：
  - **(A)** 历史 lesson → pre-hint → 首次成功（预防）
  - **(B)** 运行时 `rate_limit` → critic 重试 → 第二次成功（自纠错）
  - **(C)** 命中已知不可修模式 → 不重试（节省 token）

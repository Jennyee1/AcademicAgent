# 评测指标目录（Metric Catalog）

本文件描述 AcademicAgent 评测子系统的全部指标。所有指标都是 `src/evaluation/metrics/`
下的**纯函数**，返回 `MetricResult`（带 `value` / `numerator` / `denominator` / `notes`，
天然可解释、可人工复核）。

指标通过名字注册在 `METRIC_REGISTRY`（`src/evaluation/metrics/__init__.py`）中，
任务的 `gold.metrics` 字段按名字声明要计算哪些指标。

## 通用指标（所有层）

| 指标 | 含义 | 计算 |
|:---|:---|:---|
| `tool_success_rate` | 工具调用成功率 | ok 的 tool_call/workflow_step 事件数 / 总事件数 |
| `completion_rate` | 任务完成率 | status==ok 的任务数 / 非 skipped 任务数 |
| `latency_p50` / `p90` | 延迟分位数 | 按工具聚合的 tool_call 延迟分布（latency_stats.json）|
| `cost_usd_total` | 总成本 | token 数 × PRICE_TABLE，记录 `cost_estimation_method` |

## L1 组件级 — 按能力

### retrieval（论文检索）
| 指标 | 含义 |
|:---|:---|
| `recall_at_5` / `recall_at_10` | top-k 命中的不同 gold 数 / gold 总数 |
| `precision_at_5` / `precision_at_10` | top-k 命中数 / k |
| `mrr` | 首个 gold 命中的倒数排名 |
| `ndcg_at_5` / `ndcg_at_10` | 二元相关性的归一化折损累积增益 |

匹配优先用外部 ID（paper_id），其次归一化标题；大小写、空白不敏感。

### kg_extraction（知识图谱抽取）
| 指标 | 含义 |
|:---|:---|
| `kg_node_f1` | (归一化 label, node_type) 对的 F1 |
| `kg_edge_f1` | (src_label, relation_type, tgt_label) 三元组的 F1 |
| `schema_validity_rate` | 抽取项 node_type/relation_type 属于合法 Schema 枚举的占比 |
| `extraction_nonempty_rate` | 是否抽到任何节点/边（专门暴露「静默产出 0 节点」）|

> **已知回归锚点**：MiniMax 对 json_schema 的 property description 有 200 字符上限，
> 导致 KG 抽取 400 报错。adapter 会把它显式暴露为 `failed/llm_api_error`，
> 而非伪装成「成功但空」。`smoke_kg_long` 是该回归的固定锚点任务。

### kg_query（图谱查询）
| 指标 | 含义 |
|:---|:---|
| `query_hit_rate` | query_knowledge 返回结果覆盖期望节点的比例 |
| `neighbor_recall` | get_related_concepts 返回邻居对期望邻居的召回率 |

### gap_detection（盲区检测）
| 指标 | 含义 |
|:---|:---|
| `gap_type_match` | 检出盲区类型对期望类型的覆盖率 |
| `gap_label_recall` | 检出盲区涉及节点标签对期望标签的召回率 |
| `top_concept_overlap` | importance top 概念与期望 top 概念的重叠率 |

> 用固定的 seed graph fixture，PageRank/中心性确定性可复现。

### code_exec（代码执行）
| 指标 | 含义 |
|:---|:---|
| `code_success_rate` | 执行结果与 `expect_success` 一致则 1.0 |
| `stdout_assertion_pass` | stdout 包含全部 `expect_stdout_contains` 子串的比例 |
| `artifact_produced_rate` | 是否按 `expect_artifact` 产出文件 |

### figure_analysis（图表分析）
| 指标 | 含义 |
|:---|:---|
| `figure_type_accuracy` | 图表类型分类是否正确 |
| `figure_entity_recall` | 图表中抽取实体对期望实体的召回率 |

> v1 仅确定性指标，不做 LLM-as-judge。`analyze_pdf` / `get_paper_structure`
> 是离线纯文本操作，通常不带能力指标，仅追踪完成度。

## L2 工作流

| 指标 | 含义 |
|:---|:---|
| `workflow_completion_rate` | 整条工作流是否所有步骤都成功 |
| `tool_sequence_match` | 实际工具序列与期望序列的逐位匹配率 |
| `step_success_rate` | 各步骤成功的占比 |
| `final_assertion_pass` | 终态断言（针对最终 sidecar 状态）通过的占比 |

## L3 端到端

接口已预留（`src/evaluation/layers/layer3_e2e.py`），本期未实现 LLM driver。
规划指标：`e2e_goal_satisfied`、`tool_call_efficiency`、`e2e_cost_usd`。

## 回归门禁

`thresholds.yaml` 为每个指标配置 `min` / `regression_tolerance` / `warn_only`。
`gate.py` 读 `run_summary.json` + 阈值 + 可选 baseline，判定 PASS/WARN/FAIL：
任一 FAIL 或 run 被标记 `contaminated` → 非零退出码。

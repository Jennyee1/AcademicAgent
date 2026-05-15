# 电动试验记录本

日期：2026-05-12  
项目：AcademicAgent  
目标：把实验上下文保存在聊天窗口之外，减少重复 prompt 和上下文重建成本，让评测改进可以持续积累。

## 为什么需要它

这个项目已经采用“文件即记忆”的思路来保存 Agent 的知识。评测闭环也应该采用同样的思想来保存研发记忆：

- 每个实验都有持久化 run record
- 每次运行都有输入、输出、指标、失败案例和后续改进建议
- 记录本本地优先，再同步到 Notion 或其他外部知识库
- AI IDE 的新会话应先读取历史实验记录，再决定下一步修改

## 当前集成状态

- 已确认可通过 `conda.bat activate specSen_torch` 激活环境
- 当前会话没有可用的 Notion MCP resources
- 因此第一版采用本地优先的 Markdown / JSONL
- 后续可以增加 adapter，把本地记录同步到 Notion，并把告警推送到手机

## 记录本工作流

### 1. 写代码之前

创建或更新一个实验页面：

```text
docs/experiments/YYYY-MM-DD_short_name.md
```

必填信息：

- objective：实验目标
- hypothesis：假设
- code scope：代码影响范围
- data scope：数据影响范围
- risks：风险
- expected metrics：预期指标
- acceptance criteria：验收标准

### 2. 实验运行中

把 trace event 追加到：

```text
data/evaluation/runs/<run_id>/traces.jsonl
```

重要事件包括：

- command started
- command finished
- tool call started / finished
- model call started / finished
- metric threshold crossed
- failure detected
- alert sent / alert failed

### 3. 长实验运行中

持续监控：

- 已运行时间
- 输出是否卡住
- 异常率
- 当前成本估算
- 当前成功/失败任务数量

告警策略：

- warning：p90 延迟或失败率超过阈值
- critical：进程崩溃、长时间无输出、成本超过预算

### 4. 实验结束后

补充记录：

- 最终指标
- 失败案例
- 根因分析
- 已做 patch
- 已运行测试
- 下一轮实验建议

### 5. 下一轮实验开始前

AI IDE 应读取：

- 最新实验记录
- 最新 `metrics.json`
- 最新 `failures.md`
- 相关 implementation plan 章节

这样下一轮不会依赖被压缩过的聊天历史，也更不容易产生上下文幻觉。

## Notion 与手机推送设计

本地文件应作为 source of truth。外部服务只是 sink。

```text
local run files -> sync adapter -> Notion experiment page
                -> alert adapter -> phone push service
```

推荐 adapter：

- `NotionExperimentSink`：从本地 run metadata 创建或更新 Notion 页面
- `PhoneAlertSink`：通过 MCP 兼容的推送服务发送 warning / critical 事件
- `ExperimentMonitor`：监听运行中的进程或 trace 文件，并产生事件

失败策略：

- Notion 同步失败时，实验继续运行，并写入 `notion_sync_failed` trace
- 手机推送失败时，实验继续运行，并写入 `alert_failed` trace
- 评测不依赖第三方记录本服务是否可用

## Run Record 模板

```markdown
# Experiment: <name>

Date:
Run ID:
Owner:
Environment:
Git status:

## Objective

## Hypothesis

## Scope

## Dataset

## Commands

## Metrics

## Observations

## Failures

## Decisions

## Next Steps
```

## 最小验收标准

- 写代码前至少有一份记录实验计划的文件
- 每次 run 至少有一个目录保存机器可读的 traces 和 metrics
- 每次 run 结束后有一份解释结果的人类可读报告
- 下一次 AI 会话可以从文件继续，而不是依赖上一轮聊天记忆

---

## 实验 #001 — 评测闭环基础设施完成

**日期**: 2026-05-13  
**阶段**: Phase 0–3（Schema + Harness + Trace Wrapper + 报告生成器）  
**目标**: 建立完整的评测系统，验证 sidecar 隔离保证

### 实现内容

| 文件 | 说明 |
|---|---|
| `src/evaluation/schema.py` | TaskSpec, TraceEvent, MetricResult, RunConfig 数据类 |
| `src/evaluation/tracer.py` | JSONL trace writer，asynccontextmanager 计时 |
| `src/evaluation/metrics.py` | 纯函数指标：tool_success_rate, recall@k, precision@k, MRR, kg_node_f1, kg_edge_f1, schema_validity_rate, latency_stats, completion_rate |
| `src/evaluation/runner.py` | EvalRunner 类 + CLI：`python -m src.evaluation.runner` |
| `src/evaluation/reporter.py` | HTML + Markdown 报告生成（内嵌 Jinja2 模板）|
| `data/evaluation/datasets/smoke/tasks.jsonl` | 7 条 smoke 任务（4 KG + 2 search + 1 multi-step placeholder）|
| `data/evaluation/datasets/smoke/kg_gold.jsonl` | 3 条 KG 抽取 gold 标注 |
| `data/evaluation/datasets/smoke/retrieval_gold.jsonl` | 2 条检索 gold 标注 |
| `tests/test_evaluation_schema.py` | Schema 单元测试 |
| `tests/test_evaluation_metrics.py` | Metrics 单元测试 |

### 运行方式

```bash
# 跳过外部 API（仍需 MINIMAX_API_KEY 做 KG 抽取）
python -m src.evaluation.runner \
    --dataset data/evaluation/datasets/smoke \
    --out data/evaluation/runs \
    --skip-api

# 完整运行（需要 MINIMAX + Semantic Scholar）
python -m src.evaluation.runner \
    --dataset data/evaluation/datasets/smoke \
    --out data/evaluation/runs
```

### 隔离保证

- 每个 `kg_extraction` task 使用独立的 `temp_kg_<task_id>.json`
- `data/knowledge_graph.json`（主图谱）在评测期间不会被修改
- `--skip-api` 可以在无网络环境下测试 KG 抽取路径

### 指标阈值参考（Phase 5 目标）

```
completion_rate        >= 0.70
tool_call_success_rate >= 0.90
retrieval_recall_at_5  >= 0.70
kg_edge_f1             >= 0.55
p90_latency_s          <= 180
```

### 下一步

- [ ] 运行第一次 smoke test，记录基准指标
- [ ] 人工审查 kg_gold.jsonl 的期望值是否合理
- [ ] Phase 4：Notion sync adapter 和手机推送
- [ ] Phase 5：Regression Gate（阈值检查 + CI 集成）

---

## 实验记录模板

复制以下模板开始新记录：

```markdown
## 实验 #XXX — <实验名称>

**日期**: YYYY-MM-DD  
**阶段**: Phase N  
**目标**: 

### 运行命令

\`\`\`bash
python -m src.evaluation.runner \
    --dataset data/evaluation/datasets/smoke \
    --out data/evaluation/runs \
    --run-id YYYY-MM-DD_HHMM_smoke \
    --skip-api
\`\`\`

### 指标摘要

| 指标 | 值 | 目标 | 达标? |
|---|---|---|---|
| completion_rate | 0.xxx | ≥ 0.70 | ✓/✗ |
| tool_success_rate | 0.xxx | ≥ 0.90 | ✓/✗ |
| kg_node_f1 (avg) | 0.xxx | ≥ 0.55 | ✓/✗ |
| kg_edge_f1 (avg) | 0.xxx | ≥ 0.55 | ✓/✗ |
| p90_latency (ms) | XXXX | ≤ 180000 | ✓/✗ |

### 观察

### 结论

### 下一步

- [ ] 
```

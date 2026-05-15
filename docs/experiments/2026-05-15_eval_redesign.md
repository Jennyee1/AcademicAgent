# 实验记录：评测子系统重构

- **日期**: 2026-05-15
- **环境**: `specSen_torch`
- **代码版本**: 见各 run 的 `config.json` `code_hash`
- **范围**: 推翻旧评测，重建为分层、可复现、可解释、可持续改进的评测闭环

## 目标

在不污染主知识图谱（`data/knowledge_graph.json`）和长期记忆（`memory/MEMORY.md`、
`memory/USER.md`）的前提下，为 AcademicAgent 建立工程级评测闭环。

## 旧评测的问题

- `runner.py` 直接调 `KnowledgeExtractor` 与 Semantic Scholar HTTP，绕过 MCP 工具层，
  只覆盖约 20 个工具中的 2 个。
- toy 级：7 任务、3 组 gold；无多步工作流、无记忆/学习路径/代码执行/图表分析评测。
- 不可解释、无飞轮：失败只写一行 `failures.md`；KG 抽取因 MiniMax 400 bug 静默产出
  0.0 指标，掩盖了真实问题。
- 无成本统计、无回归门禁、无 Notion 记录。

## 重构后的架构

分层评测：
- **L1 组件级**：逐 MCP 工具，通过 `adapters/` 类型化封装隔离调用。
- **L2 工作流**：`workflows/` 里固定有序的工具链（无 LLM 决策），可复现。
- **L3 端到端**：接口骨架已留（`layers/layer3_e2e.py`），本期未实现 LLM driver。

核心约束的兑现 —— **sidecar 隔离**（`isolation.py`）：
1. 每任务在 `run_dir/sidecar/<task_id>/` 下建隔离目录树。
2. 进入时覆盖 `SCHOLARMIND_DATA_DIR`，退出还原。
3. adapters 用隔离路径直接构造 `KnowledgeGraphStore(graph_path=...)` / `CodeSandbox(work_dir=...)`，
   绕开 MCP server 的模块级单例。
4. 污染守卫：run 前后比对受保护文件的 sha256，变化则标记 `CONTAMINATED`，门禁硬失败。

可解释：每个指标带 numerator/denominator/notes；每个失败产出结构化 `FailureCard`
（分类、复现命令、根因假设、修复候选、回归测试建议）。

数据飞轮：失败卡片写 `data/evaluation/failure_cards/<run_id>.jsonl`，
`cli promote-failures` 把它们转为新 gold 任务候选。

## 验证结果（2026-05-15）

| 验证项 | 结果 |
|:---|:---|
| 离线 smoke run（`--offline`） | 4 ok / 0 failed / 8 skipped，`contaminated: false` |
| 离线 full run | 16 ok / 0 failed / 20 skipped，门禁 PASS |
| MiniMax bug 暴露 | 在线 KG 任务全部 `failed/llm_api_error`，失败卡片根因假设精确命中（property description 200 字符上限），**非静默 0.0** |
| 隔离 | 在线 run 后 `data/knowledge_graph.json` sha256 不变；`git status` 受保护文件无改动 |
| L2 工作流 | `learn_flow` 在共享 sidecar 内跑通，`actual_tool_sequence` 匹配 gold，终态断言通过 |
| 门禁 FAIL 路径 | 人为收紧阈值后 `cli gate` 返回退出码 1 |
| Notion 同步 | 创建 run 实验页 + 父页面追加版本迭代日志；无 key / 坏 key 时优雅降级返回 None，不阻断本地结果；幂等：重同步不重复建页 |
| 单测 | `pytest tests/test_evaluation_*.py` 全通过 |

## 已知问题 / 下一步

- **MiniMax extraction 400 bug**（`src/knowledge/extractor.py`）：`ExtractionOutput`
  的 json_schema property description 超过 MiniMax 的 200 字符上限。评测现在能稳定暴露
  它（`smoke_kg_long` 是回归锚点）。修复在评测范围之外，待单独处理。
- Semantic Scholar 无 key 时易触发 429；retrieval 任务标记 `requires_api`，CI 用
  `--offline` 跳过。
- L3 端到端的 LLM driver 延后实现。
- full 档 gold label（尤其 `figure_gold.jsonl`）需人工复核校准。

## 实用循环

```
Plan -> Code -> Run -> Trace -> Metrics -> Gate -> Failure Cards -> Notebook/Notion -> Next
```

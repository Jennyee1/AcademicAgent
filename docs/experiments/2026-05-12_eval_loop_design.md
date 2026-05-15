# Experiment: 评测闭环设计

日期：2026-05-12  
Run ID：`2026-05-12_eval_loop_design`  
环境：`specSen_torch`  
项目：AcademicAgent

## Objective

为 AcademicAgent 设计一套评测闭环，用来回答：“这个 Agent 怎么证明有效？”

## Hypothesis

如果把评测作为 sidecar harness 独立于主流程运行，就可以在不污染个人知识图谱的前提下，衡量多步任务完成率、工具可靠性、检索质量、知识图谱抽取、记忆使用、延迟、成本和失败改进。

## Scope

本记录只覆盖规划和架构设计。当前不修改 `src/knowledge/extractor.py`，因为该文件在开始前已经存在未提交改动。

## Current Findings

- 论文搜索已经作为独立 MCP server 存在，可以通过 trace wrapper 评测
- 知识图谱写入当前会落到 `data/knowledge_graph.json`，因此评测必须使用临时图谱文件
- 现有 report 代码可以作为评测报告生成器的风格参考，但指标报告应尽量确定性生成，避免默认依赖 LLM
- 当前会话没有可用 Notion MCP resources，所以试验记录本先采用本地优先 Markdown

## Metrics to Implement

- 多步任务完成率
- 工具调用成功率
- 检索 Precision / Recall / MRR
- 知识图谱节点/边 Precision、Recall、F1
- 记忆命中率和错误记忆使用率
- 平均、median、p90 响应延迟
- 单次任务成本估算
- 失败分类与改进记录

## Design Decisions

- 评测数据放在 `data/evaluation/`
- 实验记录放在 `docs/experiments/`
- benchmark 论文默认不进入主知识图谱，除非用户明确 promote
- Notion 和手机推送是可选 sink，不是 source of truth

## Next Steps

1. 增加 `src/evaluation/schema.py`，定义 task spec、trace event、metric record 和 run summary
2. 增加 `src/evaluation/metrics.py`，实现确定性指标计算
3. 增加一个带少量人工标注样例的 smoke dataset
4. 增加 CLI runner，输出 `traces.jsonl`、`metrics.json`、`failures.md` 和 `report.md`
5. 本地评测稳定后，再接入 Notion / notification sink

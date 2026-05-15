from __future__ import annotations

"""
AcademicAgent 评测子系统
=========================

分层、可复现、可解释、可持续改进的评测闭环。

- schema       : 数据模型（EvalLayer / Capability / Tier / TaskSpec / TraceEvent / ...）
- isolation    : sidecar 隔离（绝不污染主知识图谱与长期记忆）
- dataset      : 数据集加载与校验
- adapters     : 对 Agent 真实组件的类型化封装
- metrics      : 纯函数指标 + METRIC_REGISTRY
- layers       : L1 组件级 / L2 工作流 / L3 端到端 runner
- runner       : 薄层编排器，串联各层并落盘
- aggregate    : per-task 指标 -> run_summary.json
- gate         : 回归门禁
- failure_cards: 结构化失败卡片（数据飞轮）
- cost         : 基于 token 的成本估算
- reporting    : HTML/MD 报告 + 版本迭代日志
- notion_sync  : Notion 镜像（本地优先 + 优雅降级）

本地优先：data/evaluation/runs/ 永远是事实来源。
"""

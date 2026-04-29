"""
ScholarMind - 研究报告模块
===========================

将 LLM 的论文分析结构化、持久化为可审计的 JSON + HTML 报告。

核心问题：
  LLM 在对话中生成的论文解读（贡献、方法论、实验结果）是一次性消费品，
  关掉对话就丢了。本模块将这些解读结构化存储，支持：
  1. 历史回顾（"上周读了哪些论文？"）
  2. 对比分析（"这两篇论文的方法有什么区别？"）
  3. 可视化仪表盘（研究进度追踪）

架构：
  schema.py    → Pydantic 报告 Schema（LLM Structured Output）
  generator.py → 调 LLM 生成报告 + 保存 JSON/HTML
  templates/   → Jinja2 HTML 模板
"""

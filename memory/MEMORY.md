# ScholarMind 经验记忆
<!-- 预算：≤800 Token。新增经验时，删除最旧或最低价值的条目保持预算 -->
<!-- 维护规则：新进旧出，用 replace 而非无限 append -->

## 搜索策略

- [2026-05-06] arXiv API 限流严格（429），连续请求至少间隔 10s。建议：单次搜索用精确标题 `ti:"..."` 语法
- [2026-05-06] Semantic Scholar API 无 Key 模式 read_url_content 也会 429。建议：优先用 arXiv

## 解析经验

- [2026-05-06] graph_store API: `add_node(KGNode(...))` + `add_edge(KGEdge(...))`, 不支持 `add_paper/add_concept` 快捷方法。NodeType/RelationType 为枚举
- [2026-05-06] 诊断报告命名规则: `knowledge_diagnosis_N.html`, dashboard 手动追加行

## 已知问题

- [2026-05-06] Windows PowerShell 终端不支持 emoji 输出（GBK 编码）。建议：设置 `$env:PYTHONIOENCODING='utf-8'` 或用 `io.TextIOWrapper`
- [2026-05-06] data/ 下已有论文已迁移到 data/papers/，注册表在 data/paper_registry.json

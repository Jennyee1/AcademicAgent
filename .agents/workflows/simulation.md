---
description: 使用模板或自定义代码运行论文方法验证和科研实验
---

# Simulation (实验验证) Workflow

用于运行 Agent 评测、RAG 检索评测、数值仿真以及自定义科研实验的工作流。

## 步骤

1. **列出可用的模板**:
   - 使用 `code-execution` MCP 工具：调用 `list_code_templates`
   - 目前可用: `agent_eval_toy`, `rag_retrieval_eval`, `ofdm_basic`, `mimo_beamforming`, `aoa_music`

2. **选择模板或编写自定义代码**:
   - 如果用户想要使用模板: 使用 `explain_template` 展示细节和参数
   - 如果用户需要自定义代码: 协助编写 Python 代码

3. **修改参数** (如果使用模板):
   - 询问用户需要修改哪些参数
   - 格式如: `"N_tasks=100, success_threshold=0.7"`

4. **运行实验**:
   - 模板: 使用 `run_template(template_name, parameter_overrides)`
   - 自定义代码: 使用 `run_code(code, timeout, description)`

5. **分析结果**:
   - 检查 stdout 获取数值结果
   - 检查 output_files 获取生成的绘图
   - 对任何生成的 `.png` 文件使用 `view_file` 工具以查看并解释图表

6. **按需迭代**:
   - "需要调整参数重新跑吗？"
   - "需要添加新的对比曲线吗？"
   - "要把实验结果和论文报告的指标对比吗？"

7. **与知识库关联**:
   - 如果实验结果与知识图谱中的概念相关，建议添加见解
   - "这个实验结果验证了论文中的哪个结论？"

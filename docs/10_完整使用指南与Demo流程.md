# 🎯 ScholarMind 完整使用指南与 Demo 流程

> **你的系统有 5 个 MCP Server，共 19 个工具。**
> 本文档告诉你**每个工具能做什么、怎么试用、完整的学术研究工作流是什么**。

---

## 📐 一、系统全景图

```
                 ┌─ ① 论文搜索 (paper_search) ─── 搜论文
你（用户）──────►│─ ② 论文阅读 (paper_reader)  ─── 读论文（PDF 解析 + AI 分析）
  通过           │─ ③ 知识图谱 (knowledge_graph)── 建图谱（从论文文本抽取知识）
MCP Inspector    │─ ④ 学习路径 (learning_path)  ── 规划学习（盲区检测 + 路径推荐）
                 └─ ⑤ 代码执行 (code_execution)  ── 跑仿真（OFDM / MUSIC 模板）
```

**核心工作流**：搜论文 → 读论文 → 入图谱 → 分析图谱 → 跑仿真

---

## 🔧 二、如何启动每个 MCP Server

MCP Inspector 一次只能连一个 Server。要体验不同功能，需要**切换 Server**：

```powershell
# 先 Ctrl+C 关掉当前的 mcp dev，再启动新的

# ① 论文搜索（你已经在用的）
mcp dev src/mcp_servers/paper_search.py

# ② 论文阅读（需要 PDF 文件 + Anthropic API Key）
mcp dev src/mcp_servers/paper_reader.py

# ③ 知识图谱（需要 Anthropic API Key，用于 LLM 知识抽取）
mcp dev src/mcp_servers/knowledge_graph.py

# ④ 学习路径（纯本地计算，读取知识图谱数据）
mcp dev src/mcp_servers/learning_path.py

# ⑤ 代码执行（纯本地，在沙箱里跑 Python）
mcp dev src/mcp_servers/code_execution.py
```

---

## 🗺️ 三、5 个 Server × 19 个工具完整清单

### Server ① 论文搜索 (`paper_search.py`) — 4 个工具

| 工具 | 功能 | 是否需要 API Key | 是否需要网络 |
|:-----|:-----|:----------------|:------------|
| `search_papers` | Semantic Scholar 论文搜索 | SS Key 可选 | ✅ 是 |
| `search_arxiv` | arXiv 预印本搜索 | 无需 | ✅ 是 |
| `get_paper_details` | 获取单篇论文完整详情 | SS Key 可选 | ✅ 是 |
| `get_related_papers` | 获取引用/被引论文 | SS Key 可选 | ✅ 是 |

### Server ② 论文阅读 (`paper_reader.py`) — 4 个工具

| 工具 | 功能 | 是否需要 API Key | 是否需要网络 |
|:-----|:-----|:----------------|:------------|
| `analyze_pdf` | 解析 PDF 结构（元数据+章节+图表统计） | 无需 | ❌ 否 |
| `get_paper_structure` | 只获取论文章节结构（纯文本，零成本） | 无需 | ❌ 否 |
| `analyze_figure` | AI 分析论文中某张图表 | **Anthropic Key** | ✅ 是 |
| `analyze_page` | AI 分析论文整页（含公式、图表、文字） | **Anthropic Key** | ✅ 是 |

### Server ③ 知识图谱 (`knowledge_graph.py`) — 4 个工具

| 工具 | 功能 | 是否需要 API Key | 是否需要网络 |
|:-----|:-----|:----------------|:------------|
| `add_paper_to_graph` | 从论文文本中抽取知识实体并入图 | **Anthropic Key** | ✅ 是 |
| `query_knowledge` | 关键词搜索知识图谱 | 无需 | ❌ 否 |
| `get_graph_stats` | 查看图谱概览（节点数/边数/类型分布） | 无需 | ❌ 否 |
| `get_related_concepts` | 查询某概念的多跳关联网络 | 无需 | ❌ 否 |

### Server ④ 学习路径 (`learning_path.py`) — 3 个工具

| 工具 | 功能 | 是否需要 API Key | 是否需要网络 |
|:-----|:-----|:----------------|:------------|
| `analyze_knowledge` | 生成个性化学习路径推荐 | 无需 | ❌ 否 |
| `detect_gaps` | 检测知识盲区（三种类型） | 无需 | ❌ 否 |
| `get_concept_importance` | PageRank 概念重要性排名 | 无需 | ❌ 否 |

### Server ⑤ 代码执行 (`code_execution.py`) — 4 个工具

| 工具 | 功能 | 是否需要 API Key | 是否需要网络 |
|:-----|:-----|:----------------|:------------|
| `list_code_templates` | 查看可用的仿真模板 | 无需 | ❌ 否 |
| `explain_template` | 模板详细说明 + 完整代码 | 无需 | ❌ 否 |
| `run_template` | 运行预置模板（可修改参数） | 无需 | ❌ 否 |
| `run_code` | 安全沙箱中执行任意 Python 代码 | 无需 | ❌ 否 |

---

## 🚀 四、完整 Demo 流程（按步骤跟着做）

### Demo 1：论文搜索 + 引用追踪（Server ①）

```powershell
mcp dev src/mcp_servers/paper_search.py
```

**Step 1** — 搜索论文
```
工具: search_papers
参数: query = "OFDM channel estimation"
      limit = 3
```

**Step 2** — 查看详情（从 Step 1 结果中复制一个 Paper ID）
```
工具: get_paper_details
参数: paper_id = "（从上面结果复制 Paper ID）"
```

**Step 3** — 追踪引用（这篇论文引用了谁）
```
工具: get_related_papers
参数: paper_id = "（同上）"
      relation = "references"
      limit = 5
```

**Step 4** — 搜索 arXiv 最新预印本
```
工具: search_arxiv
参数: query = "integrated sensing and communication"
      limit = 3
      sort_by = "lastUpdatedDate"
```

---

### Demo 2：代码执行 + 仿真模板（Server ⑤）⭐ 无需 API Key

```powershell
# Ctrl+C 关掉 paper_search，启动 code_execution
mcp dev src/mcp_servers/code_execution.py
```

**Step 1** — 查看有什么模板
```
工具: list_code_templates
参数: （无需参数）
```

**Step 2** — 了解 OFDM 模板详情
```
工具: explain_template
参数: template_name = "ofdm_basic"
```

**Step 3** — 运行 OFDM 仿真 🎯
```
工具: run_template
参数: template_name = "ofdm_basic"
```
> 你会看到完整的 BER 计算结果和 matplotlib 图表输出！

**Step 4** — 运行 MUSIC 算法仿真
```
工具: run_template
参数: template_name = "aoa_music"
```

**Step 5** — 运行自定义代码
```
工具: run_code
参数: code = "import numpy as np\nx = np.linspace(0, 2*np.pi, 100)\nprint(f'sin peak: {np.sin(x).max():.4f}')\nprint(f'mean: {np.mean(np.sin(x)):.6f}')"
```

---

### Demo 3：PDF 论文分析（Server ②）

```powershell
mcp dev src/mcp_servers/paper_reader.py
```

**Step 1** — 分析 PDF 结构（无需 API Key）
```
工具: analyze_pdf
参数: pdf_path = "C:/Users/user/Desktop/某篇论文.pdf"
```
> 把 pdf_path 替换成你电脑上真实的 PDF 路径

**Step 2** — 获取论文章节结构（无需 API Key）
```
工具: get_paper_structure
参数: pdf_path = "C:/Users/user/Desktop/某篇论文.pdf"
```

**Step 3** — AI 分析图表（需要 Anthropic API Key）
```
工具: analyze_figure
参数: pdf_path = "C:/Users/user/Desktop/某篇论文.pdf"
      page_num = 3
      figure_index = 0
      context = "This figure shows the system model of OFDM transceiver"
```

---

### Demo 4：构建知识图谱（Server ③）— 需要 Anthropic API Key

```powershell
mcp dev src/mcp_servers/knowledge_graph.py
```

**Step 1** — 把一段论文文本加入图谱
```
工具: add_paper_to_graph
参数: 
  text = "We propose a novel OFDM-based integrated sensing and communication (ISAC) system. The system uses MIMO beamforming for simultaneous data transmission and target detection. Channel estimation is performed using pilot-aided least squares method. The proposed method achieves 15dB improvement in sensing SNR compared to conventional approaches. Performance is evaluated using bit error rate (BER) and detection probability metrics."
  paper_title = "OFDM-ISAC System Design"
  paper_year = "2024"
```
> LLM 会自动抽取：OFDM (concept), ISAC (concept), MIMO (concept), Beamforming (method), Channel Estimation (method), BER (metric)... 并建立它们之间的关系

**Step 2** — 加入第二篇论文的知识
```
工具: add_paper_to_graph
参数:
  text = "This paper presents a deep learning approach for channel estimation in massive MIMO systems. The proposed neural network architecture combines CNN and LSTM layers to capture both spatial and temporal channel features. Compared to traditional least squares and MMSE estimators, the DL-based method reduces MSE by 5dB at low SNR regimes. The model is trained on the COST2100 channel model dataset."
  paper_title = "DL-based Channel Estimation for Massive MIMO"
  paper_year = "2025"
```

**Step 3** — 查看知识图谱概览
```
工具: get_graph_stats
参数: （无需参数）
```
> 你会看到节点类型分布、关系类型分布、核心节点排名！

**Step 4** — 搜索图谱中的概念
```
工具: query_knowledge
参数: query = "channel estimation"
```

**Step 5** — 探索关联网络
```
工具: get_related_concepts
参数: concept_name = "OFDM"
      depth = 2
```

---

### Demo 5：学习路径规划（Server ④）— 需要先有图谱数据

```powershell
mcp dev src/mcp_servers/learning_path.py
```

> ⚠️ **前提**：需要先通过 Demo 4 往知识图谱中加入至少 2-3 篇论文的知识

**Step 1** — 生成学习路径
```
工具: analyze_knowledge
参数: focus_area = ""
      max_items = 10
```

**Step 2** — 检测知识盲区
```
工具: detect_gaps
参数: （无需参数）
```

**Step 3** — 查看概念重要性排名
```
工具: get_concept_importance
参数: top_n = 10
```

---

## 📊 五、各功能的依赖关系与推荐顺序

```
无需任何 Key 即可体验:
  ┌──► ⑤ 代码执行（跑 OFDM/MUSIC 仿真）        ← 🌟 推荐先试
  │
  ├──► ① 论文搜索（search_arxiv 不限流）
  │
  └──► ② PDF 结构解析（analyze_pdf / get_paper_structure）

需要 Anthropic API Key:
  ┌──► ② AI 图表分析（analyze_figure / analyze_page）
  │
  └──► ③ 知识图谱入库（add_paper_to_graph）
          │
          ▼
       ④ 学习路径（需要图谱有数据，但算法本身不需要 Key）
```

**推荐体验顺序**：
1. **⑤ 代码执行**（完全离线，立刻能看到仿真结果）
2. **① 论文搜索**（体验 arXiv 搜索，不限流）
3. **② PDF 分析**（如果有本地 PDF）
4. **③ → ④ 知识图谱 + 学习路径**（需要 Anthropic Key）

---

## 🔮 六、知识图谱使用进阶

### 6.1 图谱数据存在哪里？

图谱数据自动保存到：
```
e:\Materials\AntiG\AcademicAgent\data\knowledge_graph.json
```

每次 `add_paper_to_graph` 后自动保存。你可以直接打开这个 JSON 文件查看原始数据。

### 6.2 图谱的生长过程

```
第 1 篇论文 → 图谱中出现 5~10 个孤立的概念节点
第 2 篇论文 → 节点开始产生连接（共享概念如 OFDM/MIMO）
第 3 篇论文 → 网络结构初具雏形，PageRank 开始有意义
第 5 篇论文 → 可以检测出有意义的知识盲区
第 10 篇论文 → 学习路径推荐变得精准
```

### 6.3 查看图谱的方式

| 方式 | 如何操作 | 信息量 |
|:-----|:---------|:-------|
| MCP Inspector | `get_graph_stats` 工具 | 统计摘要 |
| MCP Inspector | `query_knowledge` 搜索 | 特定概念详情 |
| MCP Inspector | `get_related_concepts` | 关联网络 |
| JSON 文件 | 打开 `data/knowledge_graph.json` | 全部原始数据 |
| pytest 测试 | `pytest tests/test_knowledge_graph.py` | 验证功能正常 |

---

## ❓ 七、常见问题

### Q1: MCP Inspector 只能看到 4 个工具？
A: 因为你只启动了一个 Server。每个 `mcp dev` 命令启动一个 Server。Ctrl+C 关掉再启动另一个就能看到不同的工具。

### Q2: 知识图谱是空的怎么办？
A: 需要通过 `add_paper_to_graph` 往里面添加论文内容。按 Demo 4 的步骤操作。

### Q3: 没有 Anthropic API Key 能体验什么？
A: 可以完整体验：
- 论文搜索（search_papers, search_arxiv）
- PDF 结构解析（analyze_pdf, get_paper_structure）
- 代码执行（全部 4 个工具）
- 学习路径（如果图谱有数据的话）

### Q4: 如何一次使用所有 Server？
A: MCP Inspector 是单 Server 调试工具。要同时使用所有 Server，需要安装 Claude Code（`npm install -g @anthropic-ai/claude-code`），然后在项目目录运行 `claude`，它会自动加载 `.claude/mcp.json` 中注册的全部 5 个 Server。

### Q5: 数据会丢失吗？
A: 不会。知识图谱保存在 `data/knowledge_graph.json`，代码执行结果保存在 `data/sandbox/` 目录。都是本地文件。

---

## 🎓 八、面试时如何演示

如果面试官要现场看效果，推荐这个 **3 分钟 Demo 流程**：

```
1. 启动 code_execution → 运行 OFDM 模板 → 展示 BER 曲线输出    (1 分钟)
2. 启动 paper_search → 搜索 ISAC 论文 → 展示真实论文数据        (1 分钟)  
3. 展示 knowledge_graph.json 数据结构 → 解释 PageRank 算法       (1 分钟)
```

**核心话术**：
> "这个 Agent 的特点是：论文数据来自真实 API 而非 LLM 编造，每篇都附带可验证的 DOI；知识图谱用 PageRank 量化概念重要性；代码执行有 4 层安全沙箱隔离。"

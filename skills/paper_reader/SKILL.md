---
name: paper_reader
description: 解析并分析学术 PDF 论文 — 深度多模态提取文本与图表，支持结构化解析和视觉分析
---

# Paper Reader（论文阅读器）Skill

## 什么时候使用

当用户提出以下需求时使用此 Skill：
- 提供了一篇 PDF 论文并要求"分析"、"阅读"或"总结"它
- 想要理解论文中的图表或公式
- 询问论文的结构或各个章节
- 提到了一个本地的 PDF 文件路径

## 前置条件

- Python 环境，且已安装依赖：`pip install -r requirements.txt`

## 操作指南

### 0. 📥 下载论文 PDF

当用户通过 `paper-search` MCP 工具搜索到论文后，使用此命令下载 PDF：

```bash
python skills/paper_reader/scripts/parse_pdf.py --action download --url "<arXiv_ID_or_URL>"
```

支持两种格式：
- **arXiv ID**：`--url "2210.03629"` → 自动拼接为 `https://arxiv.org/pdf/2210.03629.pdf`
- **完整 URL**：`--url "https://arxiv.org/pdf/2210.03629.pdf"`
- 可选：`--filename "ReAct.pdf"` 自定义文件名（默认从 arXiv ID 自动生成）

PDF 文件保存到 `data/` 目录。下载完成后，使用下方的深度解析命令分析论文。

### 1. 🌟 深度多模态解析（推荐首选）


一次性提取文本 + 章节结构 + 所有嵌入图片，是论文分析的最佳起点。

```bash
python skills/paper_reader/scripts/parse_pdf.py --action deep --pdf "<pdf_path>"
```

返回结构化 JSON，包含：
- **metadata**: 标题、页数、文件大小、总字符数
- **sections**: 各章节名称、字数、预览文本
- **text**: 全文文本（用于 LLM 理解和知识图谱入图）
- **figures**: 提取的图片列表（自动过滤了 icon/logo 等噪声图片）

⚠️ **Token 成本控制规则**：
- 深度解析后，**禁止自动 `view_file` 查看图片**
- 只向用户报告"共提取了 N 张图表"以及路径列表
- 仅当用户**明确要求**分析某张图表时，才使用 `view_file` 查看
- 每次 `view_file` 查看一张图片约消耗 500~1500 Vision Token

**设计原理**：文本用文本提取（零 Vision 开销），图片只提取嵌入的 figure（不做全页渲染），最大化信息密度、最小化 token 消耗。

### 2. 提取论文结构（零成本，无 API 消耗）

当用户想要快速了解论文各个章节时：

```bash
python skills/paper_reader/scripts/parse_pdf.py --action structure --pdf "<pdf_path>"
```

这将返回包含章节名称和字数的 JSON 数据。请将其格式化为表格形式呈现。

### 3. 提取全文

当用户需要论文的全部文本内容时：

```bash
python skills/paper_reader/scripts/parse_pdf.py --action text --pdf "<pdf_path>"
```

返回全文内容。可以将其用于知识抽取（传递给 `add_paper_to_graph` MCP 工具）。

### 4. 从指定页面提取图片

当用户**明确要求**分析某个具体的图表时：

```bash
python skills/paper_reader/scripts/parse_pdf.py --action images --pdf "<pdf_path>" --page <page_num>
```

此命令会将提取出的图片保存到 `data/scholarmind_images/` 并返回它们的文件路径。

**图表分析触发条件**（仅当以下情况之一成立时才使用 `view_file` 查看图片）：
- ✅ 用户明确说了"分析图表"、"看看这张图"、"解释 Figure X"
- ✅ 用户提问的内容无法仅从文本中回答（如"这个系统框图的架构是什么"）
- ✅ 用户要求将图表信息加入知识图谱

**禁止触发**的情况：
- ❌ 用户只是说"分析论文"或"总结论文" → 文本已足够，无需看图
- ❌ 深度解析后自动查看所有图片 → 严禁，Token 浪费严重

分析图片时，结合论文 text 中引用该图表的上下文段落（如 "As shown in Fig. 2..."）能显著提升分析质量。

### 5. 将整页渲染为图片（仅在必要时使用）

当页面包含复杂公式、矢量图或扫描版 PDF 时，才需要全页渲染：

```bash
python skills/paper_reader/scripts/parse_pdf.py --action render --pdf "<pdf_path>" --page <page_num> --dpi 200
```

将渲染后的页面保存到 `data/scholarmind_images/` 并返回路径。请使用 `view_file` 查看渲染出的页面图片并进行分析。

### 6. 获取 PDF 元数据

```bash
python skills/paper_reader/scripts/parse_pdf.py --action metadata --pdf "<pdf_path>"
```

返回标题、作者、页数、文件大小以及该文档是否为扫描版 PDF。

## 输出格式

始终以结构化的 Markdown 格式展示结果：
- 元数据：呈现为表格
- 结构：呈现为带有字数的有序列表
- 图片：**仅列出路径和数量**，不要自动查看。告知用户可以要求分析特定图片
- 对于扫描版 PDF：提醒用户，并建议使用"整页渲染 + 视觉分析"的方式

## Workflow 集成推荐

在分析完一篇论文后，主动建议下一步操作：
1. "要把这篇论文加入知识图谱吗？" → 使用 `add_paper_to_graph` MCP 工具，将 deep 解析的全文文本传入
2. "需要分析某张具体图表吗？（共提取了 N 张图）" → 仅在用户同意后，再使用 `view_file` 查看指定图片
3. "需要运行相关仿真吗？" → 使用 `code-execution` MCP 工具

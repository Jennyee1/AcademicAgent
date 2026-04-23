---
name: paper_reader
description: 解析并分析学术 PDF 论文 — 提取文本、结构、图片，并渲染页面用于视觉分析
---

# Paper Reader（论文阅读器）Skill

## 什么时候使用

当用户提出以下需求时使用此 Skill：
- 提供了一篇 PDF 论文并要求“分析”、“阅读”或“总结”它
- 想要理解论文中的图表或公式
- 询问论文的结构或各个章节
- 提到了一个本地的 PDF 文件路径

## 前置条件

- Python 环境，且已安装 PyMuPDF：`pip install PyMuPDF`
- 项目根目录：`e:/Materials/AntiG/AcademicAgent`

## 操作指南

### 1. 提取论文结构（零成本，无 API 消耗）

当用户想要快速了解论文各个章节时：

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/paper_reader/scripts/parse_pdf.py --action structure --pdf "<pdf_path>"
```

这将返回包含章节名称和字数的 JSON 数据。请将其格式化为表格形式呈现。

### 2. 提取全文

当用户需要论文的全部文本内容时：

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/paper_reader/scripts/parse_pdf.py --action text --pdf "<pdf_path>"
```

返回全文内容。可以将其用于知识抽取（传递给 `add_paper_to_graph` MCP 工具）。

### 3. 从指定页面提取图片

当用户想要分析某个具体的图表时：

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/paper_reader/scripts/parse_pdf.py --action images --pdf "<pdf_path>" --page <page_num>
```

此命令会将提取出的图片保存到 `data/scholarmind_images/` 并返回它们的文件路径。请对保存的图片使用 `view_file` 工具，以利用你内置的视觉能力进行分析。

### 4. 将整页渲染为图片

当用户需要全页分析（包括公式、排版、矢量图）时：

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/paper_reader/scripts/parse_pdf.py --action render --pdf "<pdf_path>" --page <page_num> --dpi 200
```

将渲染后的页面保存到 `data/scholarmind_images/` 并返回路径。请使用 `view_file` 查看渲染出的页面图片并进行分析。

### 5. 获取 PDF 元数据

```bash
cd e:/Materials/AntiG/AcademicAgent && python skills/paper_reader/scripts/parse_pdf.py --action metadata --pdf "<pdf_path>"
```

返回标题、作者、页数、文件大小以及该文档是否为扫描版 PDF。

## 输出格式

始终以结构化的 Markdown 格式展示结果：
- 元数据：呈现为表格
- 结构：呈现为带有字数的有序列表
- 图片：使用 `view_file` 显示图片，然后描述你所看到的内容
- 对于扫描版 PDF：提醒用户，并建议使用“整页渲染 + 视觉分析”的方式

## Workflow 集成推荐

在分析完一篇论文后，主动建议下一步操作：
1. "要把这篇论文加入知识图谱吗？" → 使用 `add_paper_to_graph` MCP 工具
2. "需要分析某张具体图表吗？" → 使用提取图片 + 视觉分析
3. "需要运行相关仿真吗？" → 使用 `code-execution` MCP 工具

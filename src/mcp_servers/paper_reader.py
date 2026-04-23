import sys
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

"""
ScholarMind - 论文阅读与分析 MCP Server
========================================

功能：
  1. analyze_pdf         — 分析本地 PDF 论文（结构化解析）
  2. analyze_figure      — 分析论文中的指定图表
  3. get_paper_structure  — 获取论文章节结构
  4. analyze_page        — 分析论文指定页面（整页 Vision）

技术架构：
  PDF → PDFParser(提取文本+图片)  →  FigureAnalyzer(Vision分析)
                                  →  PaperStructureParser(章节分割)
                                  →  格式化输出给 Claude

工程要点：
  - 本地 PDF 路径由用户指定，不走网络（隐私安全）
  - 图片分析走 Anthropic Vision API（需要 API Key）
  - 整页渲染 DPI 默认 200（平衡质量和 token 消耗）
  - 每张图片分析消耗约 1000-2000 tokens
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.core.pdf_parser import PDFParser
from src.core.multimodal import FigureAnalyzer, PaperStructureParser, FigureType

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ScholarMind.PaperReader")

mcp = FastMCP(
    "ScholarMind-PaperReader",
    instructions=(
        "论文阅读与多模态分析服务。"
        "支持本地 PDF 论文的结构化解析、图表 AI 分析、整页理解。"
        "所有分析基于真实 PDF 内容，不编造信息。"
    ),
)

# 全局分析器实例
figure_analyzer = FigureAnalyzer()
structure_parser = PaperStructureParser()


@mcp.tool()
async def analyze_pdf(pdf_path: str) -> str:
    """
    分析一篇本地 PDF 论文，返回结构化概览。

    适合使用的场景：
    - 用户说"帮我分析这篇论文"并提供了 PDF 路径
    - 需要快速了解一篇论文的结构和核心内容
    - 初次阅读时需要论文概览

    Args:
        pdf_path: 本地 PDF 文件路径（绝对路径或相对路径）

    Returns:
        论文元数据 + 章节结构概览 + 图表统计
    """
    logger.info(f"分析 PDF: {pdf_path}")

    try:
        with PDFParser(pdf_path) as parser:
            # 元数据
            meta = parser.get_metadata()

            # 扫描版检测
            is_scanned = parser.is_scanned_pdf()
            if is_scanned:
                return (
                    f"⚠️ **检测到扫描版 PDF**\n\n"
                    f"文件: {meta.file_path}\n"
                    f"页数: {meta.page_count}\n\n"
                    f"该 PDF 是扫描版（图片型），无法直接提取文字。\n"
                    f"建议使用 `analyze_page` 工具逐页进行 Vision 分析。"
                )

            # 全文提取
            full_text = parser.extract_full_text()

            # 章节结构
            sections = structure_parser.parse_sections(full_text)
            structure_summary = structure_parser.get_section_summary(sections)

            # 图表统计
            all_images = parser.extract_all_images()
            image_stats = f"共提取 **{len(all_images)}** 张嵌入图表"

            # 摘要提取
            abstract = sections.get("abstract", "（未识别到摘要章节）")
            if len(abstract) > 500:
                abstract = abstract[:500] + "..."

            result = (
                f"## 📄 论文分析: {meta.title or parser.pdf_path.name}\n\n"
                f"| 属性 | 值 |\n"
                f"|:---|:---|\n"
                f"| **文件** | {meta.file_path} |\n"
                f"| **页数** | {meta.page_count} |\n"
                f"| **大小** | {meta.file_size_mb:.2f} MB |\n"
                f"| **文字量** | {len(full_text):,} 字符 |\n"
                f"| **嵌入图表** | {len(all_images)} 张 |\n\n"
                f"{structure_summary}\n\n"
                f"### 摘要\n{abstract}\n\n"
                f"---\n"
                f"💡 **下一步**：\n"
                f"- 使用 `analyze_figure` 分析特定图表\n"
                f"- 使用 `analyze_page` 进行整页 Vision 分析"
            )

            logger.info(
                f"PDF 分析完成: {meta.page_count} 页, "
                f"{len(sections)} 章节, {len(all_images)} 图"
            )
            return result

    except FileNotFoundError:
        return f"⚠️ **文件不存在**: `{pdf_path}`\n\n请检查路径是否正确。"
    except RuntimeError as e:
        return f"⚠️ **PDF 打开失败**: {e}\n\n可能是文件损坏或被加密。"
    except Exception as e:
        logger.exception(f"PDF 分析失败: {e}")
        return f"⚠️ **分析失败**: {type(e).__name__}: {e}"


@mcp.tool()
async def analyze_figure(
    pdf_path: str,
    page_num: int,
    figure_index: int = 0,
    context: str = "",
) -> str:
    """
    分析论文中指定页面的某张图表。使用 Claude Vision 进行多模态理解。

    适合使用的场景：
    - 用户说"帮我分析第X页的图/表"
    - 需要理解论文中某个系统框图或性能曲线
    - 从图表中提取关键数据点或方法名称

    Args:
        pdf_path: PDF 文件路径
        page_num: 页面编号（从 0 开始）
        figure_index: 该页第几张图（从 0 开始，默认第一张）
        context: 可选的论文上下文信息（如该图所在段落的文字），
                 提供上下文会显著提升分析质量

    Returns:
        图表类型、描述、关键发现和抽取实体
    """
    logger.info(f"分析图表: pdf={pdf_path}, page={page_num}, idx={figure_index}")

    try:
        with PDFParser(pdf_path) as parser:
            images = parser.extract_images_from_page(page_num)

            if not images:
                return (
                    f"⚠️ 第 {page_num} 页没有嵌入图片。\n\n"
                    f"**建议**：尝试使用 `analyze_page` 进行整页分析，"
                    f"某些图表可能是矢量图而非嵌入图片。"
                )

            if figure_index >= len(images):
                return (
                    f"⚠️ 第 {page_num} 页只有 {len(images)} 张图，"
                    f"图片索引 {figure_index} 超出范围（从 0 开始）。"
                )

            target_image = images[figure_index]

            # 调用多模态分析
            result = await figure_analyzer.analyze(
                image_base64=target_image.base64_data,
                context=context,
                media_type=f"image/{target_image.format}",
            )

            header = (
                f"## 🔬 图表分析 (第 {page_num} 页, 图 {figure_index + 1})\n\n"
                f"- **图片尺寸**: {target_image.width}x{target_image.height}\n"
                f"- **大小**: {target_image.size_kb:.1f} KB\n\n"
            )

            return header + result.to_markdown()

    except FileNotFoundError:
        return f"⚠️ **文件不存在**: `{pdf_path}`"
    except ValueError as e:
        return f"⚠️ **参数错误**: {e}"
    except Exception as e:
        logger.exception(f"图表分析失败: {e}")
        return f"⚠️ **分析失败**: {type(e).__name__}: {e}"


@mcp.tool()
async def analyze_page(
    pdf_path: str,
    page_num: int,
    context: str = "",
    dpi: int = 200,
) -> str:
    """
    将论文的指定页面整页渲染为图片，然后用 Claude Vision 分析。

    与 analyze_figure 的区别：
    - analyze_figure: 只分析单张嵌入图片
    - analyze_page: 分析整个页面（包括文字、公式、图表、布局）

    适合使用的场景：
    - 页面包含复杂公式需要理解
    - 需要同时理解图表和周围的文字说明
    - 扫描版 PDF（无法提取文字，只能用 Vision）
    - 需要理解表格的完整格式

    Args:
        pdf_path: PDF 文件路径
        page_num: 页面编号（从 0 开始）
        context: 可选的分析上下文/指导性问题
        dpi: 渲染分辨率（150=快速, 200=标准, 300=高清）

    Returns:
        整页的多模态分析结果
    """
    logger.info(f"整页分析: pdf={pdf_path}, page={page_num}, dpi={dpi}")

    try:
        with PDFParser(pdf_path) as parser:
            # 渲染整页为图片
            page_b64 = parser.render_page_as_image(page_num, dpi=dpi)

            # 构建分析 prompt
            page_text = parser.extract_page_text(page_num)
            full_context = context
            if page_text:
                full_context += f"\n\n该页面的文本内容：\n{page_text[:1000]}"

            # Vision 分析
            result = await figure_analyzer.analyze(
                image_base64=page_b64,
                context=full_context,
                media_type="image/png",
            )

            return (
                f"## 📖 第 {page_num} 页分析\n\n"
                + result.to_markdown()
            )

    except FileNotFoundError:
        return f"⚠️ **文件不存在**: `{pdf_path}`"
    except ValueError as e:
        return f"⚠️ **参数错误**: {e}"
    except Exception as e:
        logger.exception(f"整页分析失败: {e}")
        return f"⚠️ **分析失败**: {type(e).__name__}: {e}"


@mcp.tool()
async def get_paper_structure(pdf_path: str) -> str:
    """
    获取论文的章节结构和摘要。不使用 Vision API（纯文本分析，零成本）。

    适合使用的场景：
    - 需要快速了解论文有哪些章节
    - 只需要文字内容不需要图表分析
    - 想节省 API 成本时（不调用 Vision）

    Args:
        pdf_path: PDF 文件路径

    Returns:
        论文章节列表和字数统计
    """
    logger.info(f"获取论文结构: {pdf_path}")

    try:
        with PDFParser(pdf_path) as parser:
            full_text = parser.extract_full_text()
            sections = structure_parser.parse_sections(full_text)

            result = structure_parser.get_section_summary(sections)

            # 为每个章节添加摘录
            result += "\n\n---\n"
            for section, text in sections.items():
                if section in ("preamble", "references"):
                    continue
                preview = text[:300] + "..." if len(text) > 300 else text
                result += f"\n### {section}\n{preview}\n"

            return result

    except Exception as e:
        logger.exception(f"结构解析失败: {e}")
        return f"⚠️ **解析失败**: {type(e).__name__}: {e}"


if __name__ == "__main__":
    logger.info("ScholarMind Paper Reader MCP Server 启动中...")
    mcp.run()

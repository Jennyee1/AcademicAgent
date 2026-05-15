from __future__ import annotations

"""
paper_reader adapter —— 封装 PDF 解析与图表多模态分析能力。

analyze_pdf / get_paper_structure 是纯文本操作（离线可跑）；
analyze_figure / analyze_page 需要 MiniMax Vision（requires_llm），
Vision 失败映射到 error_category="llm_api_error"。
"""

from .base import AdapterContext, ToolCallResult, register_adapter


@register_adapter("analyze_pdf")
async def analyze_pdf(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """PDF 元数据 + 结构概览（纯文本，离线可跑）。"""
    from src.core.pdf_parser import PDFParser

    pdf_path = args.get("pdf_path", "")
    try:
        with PDFParser(pdf_path) as parser:
            meta = parser.get_metadata()
            images = parser.extract_all_images()
            scanned = parser.is_scanned_pdf()
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult.failure(
            "analyze_pdf", f"pdf parse failed: {exc}", "tool_exception",
        )
    return ToolCallResult(
        ok=True, tool="analyze_pdf",
        raw={
            "page_count": meta.page_count,
            "image_count": len(images),
            "is_scanned": scanned,
            "title": meta.title,
        },
        text=f"{pdf_path}: {meta.page_count} pages, {len(images)} images",
    )


@register_adapter("get_paper_structure")
async def get_paper_structure(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """论文章节结构（纯文本，零 Vision 成本）。"""
    from src.core.multimodal import PaperStructureParser
    from src.core.pdf_parser import PDFParser

    pdf_path = args.get("pdf_path", "")
    try:
        with PDFParser(pdf_path) as parser:
            full_text = parser.extract_full_text()
        sections = PaperStructureParser().parse_sections(full_text)
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult.failure(
            "get_paper_structure", f"structure parse failed: {exc}", "tool_exception",
        )
    return ToolCallResult(
        ok=True, tool="get_paper_structure",
        raw={"sections": list(sections.keys()), "section_count": len(sections)},
        text=f"{pdf_path}: {len(sections)} sections",
    )


async def _analyze_image(tool: str, image_b64: str, media_type: str,
                         context: str) -> ToolCallResult:
    from src.core.multimodal import FigureAnalyzer

    try:
        analyzer = FigureAnalyzer()
        result = await analyzer.analyze(
            image_base64=image_b64, context=context, media_type=media_type,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult.failure(
            tool, f"vision analysis failed: {exc}", "llm_api_error",
        )
    entities = [
        e.get("name", "") if isinstance(e, dict) else str(e)
        for e in (result.entities or [])
    ]
    figure_type = (
        result.figure_type.value
        if hasattr(result.figure_type, "value")
        else str(result.figure_type)
    )
    return ToolCallResult(
        ok=True, tool=tool,
        raw={
            "figure_type": figure_type,
            "entities": entities,
            "description": result.description,
            "confidence": result.confidence,
        },
        text=f"figure_type={figure_type}, {len(entities)} entities",
    )


@register_adapter("analyze_figure")
async def analyze_figure(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """对 PDF 某页的某张图做多模态分析。"""
    from src.core.pdf_parser import PDFParser

    pdf_path = args.get("pdf_path", "")
    page_num = int(args.get("page_num", 0))
    figure_index = int(args.get("figure_index", 0))
    context = args.get("context", "")
    try:
        with PDFParser(pdf_path) as parser:
            images = parser.extract_images_from_page(page_num)
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult.failure(
            "analyze_figure", f"pdf parse failed: {exc}", "tool_exception",
        )
    if not images or figure_index >= len(images):
        return ToolCallResult.failure(
            "analyze_figure",
            f"no figure at page {page_num} index {figure_index}",
            "tool_exception",
        )
    img = images[figure_index]
    return await _analyze_image(
        "analyze_figure", img.base64_data, f"image/{img.format}", context,
    )


@register_adapter("analyze_page")
async def analyze_page(args: dict, ctx: AdapterContext) -> ToolCallResult:
    """整页渲染后做多模态分析（覆盖公式/表格/混合排版）。"""
    from src.core.pdf_parser import PDFParser

    pdf_path = args.get("pdf_path", "")
    page_num = int(args.get("page_num", 0))
    context = args.get("context", "")
    dpi = int(args.get("dpi", 200))
    try:
        with PDFParser(pdf_path) as parser:
            image_b64 = parser.render_page_as_image(page_num, dpi=dpi)
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult.failure(
            "analyze_page", f"page render failed: {exc}", "tool_exception",
        )
    return await _analyze_image("analyze_page", image_b64, "image/png", context)

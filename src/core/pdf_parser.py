"""
ScholarMind - PDF 论文解析器
============================

功能：
  1. 提取论文全文文本
  2. 提取论文中的图片（用于后续多模态分析）
  3. 将整页渲染为图片（用于 Claude Vision 分析）
  4. 提取 PDF 元数据

技术选择：
  - PyMuPDF (fitz): 最成熟的 Python PDF 库
    - 优点: 速度快、功能全、支持图片提取和页面渲染
    - 缺点: C 扩展依赖，安装偶尔有兼容性问题
  - 备选: pdfplumber（纯文本提取更精确）、pypdf（更轻量）

工程笔记：
  - 学术 PDF 的典型特征：双栏排版、大量公式、嵌入图表
  - PyMuPDF 的 get_text() 在双栏 PDF 上可能混合两栏文字
    → 解法: 使用 get_text("blocks") 按文本块提取，再按位置排序
  - 扫描版 PDF 无法提取文字 → 需要 OCR fallback（Phase 1 实现）
"""

import base64
import logging
from pathlib import Path
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger("ScholarMind.PDFParser")

# 【Token 经济学】Vision LLM 的分辨率甜点
# Claude 推荐长边 ≤ 1568px，超过后 API 后端会强制 resize，
# 意味着你白白浪费了 CPU 渲染的高清像素和传输带宽。
# 参考: https://docs.anthropic.com/en/docs/build-with-claude/vision
MAX_LONG_EDGE = 1568


@dataclass
class PDFMetadata:
    """PDF 文档元数据"""
    title: str = ""
    author: str = ""
    page_count: int = 0
    file_size_mb: float = 0.0
    file_path: str = ""

    def summary(self) -> str:
        return (
            f"标题: {self.title or '(未知)'}\n"
            f"作者: {self.author or '(未知)'}\n"
            f"页数: {self.page_count}\n"
            f"文件大小: {self.file_size_mb:.2f} MB"
        )


@dataclass
class ExtractedImage:
    """从 PDF 提取的图片"""
    page_num: int               # 所在页码 (0-indexed)
    index: int                  # 该页第几张图 (0-indexed)
    format: str                 # 图片格式 (png, jpeg, etc.)
    base64_data: str            # base64 编码的图片数据
    width: int = 0
    height: int = 0

    @property
    def size_kb(self) -> float:
        """估算图片大小 (KB)"""
        return len(self.base64_data) * 3 / 4 / 1024


@dataclass
class ParsedPage:
    """解析后的单页内容"""
    page_num: int               # 页码 (0-indexed)
    text: str                   # 文本内容
    images: list[ExtractedImage] = field(default_factory=list)
    page_image_b64: str = ""    # 整页渲染图（用于 Vision 分析）


class PDFParser:
    """
    PDF 论文解析器

    使用方式:
        parser = PDFParser("path/to/paper.pdf")
        text = parser.extract_full_text()
        images = parser.extract_all_images()
        page_img = parser.render_page_as_image(0)  # 渲染第1页
        parser.close()

    或使用 context manager:
        with PDFParser("paper.pdf") as parser:
            text = parser.extract_full_text()
    """

    def __init__(self, pdf_path: str):
        """
        初始化 PDF 解析器

        Args:
            pdf_path: PDF 文件路径

        Raises:
            FileNotFoundError: PDF 文件不存在
            RuntimeError: PDF 文件无法打开（损坏或加密）
        """
        self.pdf_path = Path(pdf_path)

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        try:
            self.doc = fitz.open(str(self.pdf_path))
        except Exception as e:
            raise RuntimeError(f"无法打开 PDF 文件: {e}") from e

        logger.info(
            f"PDF 已加载: {self.pdf_path.name} "
            f"({len(self.doc)} 页, {self.pdf_path.stat().st_size / 1024 / 1024:.1f} MB)"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """释放 PDF 文档资源"""
        if self.doc:
            self.doc.close()

    # ---- 元数据提取 ----

    def get_metadata(self) -> PDFMetadata:
        """提取 PDF 元数据"""
        meta = self.doc.metadata or {}
        return PDFMetadata(
            title=meta.get("title", ""),
            author=meta.get("author", ""),
            page_count=len(self.doc),
            file_size_mb=round(self.pdf_path.stat().st_size / 1024 / 1024, 2),
            file_path=str(self.pdf_path),
        )

    # ---- 文本提取 ----

    def extract_full_text(self) -> str:
        """
        提取全文文本

        【工程设计笔记】
        - 使用 get_text("text") 而非 get_text("blocks")
          因在一般场景下够用，且代码简单
        - 如果后续发现双栏混排问题，可切换到 blocks 模式
        - 返回的文本保留了段落间的空行
        """
        pages_text = []
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text("text")
            if text.strip():
                pages_text.append(text)

        full_text = "\n\n".join(pages_text)
        logger.info(f"文本提取完成: {len(full_text)} 字符")
        return full_text

    def extract_page_text(self, page_num: int) -> str:
        """提取指定页面的文本"""
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(
                f"页码超出范围: {page_num} (共 {len(self.doc)} 页)"
            )
        return self.doc[page_num].get_text("text")

    # ---- 图片提取 ----

    def extract_images_from_page(self, page_num: int) -> list[ExtractedImage]:
        """
        提取指定页面中嵌入的图片

        【工程设计笔记】
        - get_images(full=True) 返回该页所有嵌入图片的引用
        - 然后通过 extract_image(xref) 获取实际图片数据
        - 部分 PDF (如扫描版) 整页就是一张大图 → 用 render 模式更合适
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"页码超出范围: {page_num}")

        page = self.doc[page_num]
        images = []

        for img_index, img_ref in enumerate(page.get_images(full=True)):
            xref = img_ref[0]
            try:
                base_image = self.doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_b64 = base64.b64encode(image_bytes).decode("utf-8")

                images.append(ExtractedImage(
                    page_num=page_num,
                    index=img_index,
                    format=base_image.get("ext", "png"),
                    base64_data=image_b64,
                    width=base_image.get("width", 0),
                    height=base_image.get("height", 0),
                ))
            except Exception as e:
                logger.warning(
                    f"图片提取失败: page={page_num}, img={img_index}, error={e}"
                )

        logger.info(f"第 {page_num} 页提取 {len(images)} 张图片")
        return images

    def extract_all_images(self) -> list[ExtractedImage]:
        """
        提取所有页面的图片

        【工程说明】这里仍返回 list 而非 generator，因为：
        1. 下游 cmd_deep() 需要 len() 统计总数
        2. 嵌入图片的 base64 通常远小于全页渲染（几十 KB vs 几 MB）
        3. 一篇论文嵌入图通常 10~30 张，内存压力可控
        如果未来需要处理图册类 PDF（数百张图），可改为 generator。
        """
        all_images = []
        for page_num in range(len(self.doc)):
            all_images.extend(self.extract_images_from_page(page_num))
        logger.info(f"全文共提取 {len(all_images)} 张图片")
        return all_images

    # ---- 页面渲染 ----

    def render_page_as_image(
        self, page_num: int, dpi: int = 200
    ) -> str:
        """
        将整页渲染为 PNG 图片（base64 编码）

        用途：直接发送给 Vision LLM 进行整页分析
        - 可以理解图表、公式、表格等所有视觉元素
        - 比单独提取图片更保留上下文信息

        【Token 经济学优化】
        自动将渲染分辨率上限卡在 Vision LLM 的甜点尺寸（长边 ≤ 1568px）。
        超过此尺寸的图片会被 API 后端强制 resize，白白浪费 CPU 和带宽。
        实际 DPI 由页面物理尺寸和 MAX_LONG_EDGE 动态计算。

        Args:
            page_num: 页码 (0-indexed)
            dpi: 期望渲染分辨率，默认 200
                 会被自动 cap 到 MAX_LONG_EDGE 对应的等效 DPI

        Returns:
            PNG 图片的 base64 编码字符串
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"页码超出范围: {page_num}")

        page = self.doc[page_num]

        # 动态计算最优 DPI：卡在 Vision LLM 的分辨率甜点
        # PDF 标准: 1 point = 1/72 inch
        page_rect = page.rect
        width_inch = page_rect.width / 72
        height_inch = page_rect.height / 72
        long_edge_inch = max(width_inch, height_inch)

        # 用户请求的 DPI 对应的长边像素
        requested_long_edge = long_edge_inch * dpi

        if requested_long_edge > MAX_LONG_EDGE:
            # 超出甜点 → 降低 DPI 使长边恰好等于 MAX_LONG_EDGE
            effective_dpi = MAX_LONG_EDGE / long_edge_inch
            logger.info(
                f"DPI 自动降级: {dpi} → {effective_dpi:.0f} "
                f"(页面 {page_rect.width:.0f}x{page_rect.height:.0f}pt, "
                f"长边 cap 到 {MAX_LONG_EDGE}px)"
            )
        else:
            effective_dpi = dpi

        mat = fitz.Matrix(effective_dpi / 72, effective_dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        image_bytes = pix.tobytes("png")
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        size_kb = len(image_bytes) / 1024
        logger.info(
            f"页面渲染: page={page_num}, dpi={effective_dpi:.0f}, "
            f"size={pix.width}x{pix.height}, {size_kb:.1f} KB"
        )
        return b64

    # ---- 结构化解析 ----

    def parse_all_pages(
        self, render_pages: bool = False, dpi: int = 200
    ):
        """
        解析所有页面（生成器版本，逐页 yield）

        【OOM 防御】重构为 Generator，避免将所有页面数据同时堆在内存中。
        - 修改前: 50 页 × render_pages=True × ~4MB/页 = 200MB 瞬时内存
        - 修改后: 任意时刻内存中只有 1 页的数据，处理完即释放

        调用方如果需要 list，可以 list(parser.parse_all_pages())。
        但推荐用 for page in parser.parse_all_pages() 流式消费。

        Args:
            render_pages: 是否同时渲染页面图片（耗时长，按需开启）
            dpi: 渲染分辨率（会被 MAX_LONG_EDGE 自动 cap）

        Yields:
            ParsedPage: 每页的文本、图片和可选的页面渲染图
        """
        for page_num in range(len(self.doc)):
            page = ParsedPage(
                page_num=page_num,
                text=self.extract_page_text(page_num),
                images=self.extract_images_from_page(page_num),
            )
            if render_pages:
                page.page_image_b64 = self.render_page_as_image(page_num, dpi)
            yield page

    # ---- 辅助检测 ----

    def is_scanned_pdf(self, sample_pages: int = 3) -> bool:
        """
        检测 PDF 是否为扫描版（图片型，非可选择文字）

        【工程笔记】
        扫描版 PDF 的特征：
        - 每页几乎没有可提取的文字
        - 每页有一张与页面同尺寸的大图
        检测方法：抽样前几页，如果文字量极少则判定为扫描版

        Returns:
            True 表示很可能是扫描版 PDF
        """
        sample_pages = min(sample_pages, len(self.doc))
        text_lengths = []

        for i in range(sample_pages):
            text = self.doc[i].get_text("text").strip()
            text_lengths.append(len(text))

        avg_text_len = sum(text_lengths) / len(text_lengths) if text_lengths else 0
        is_scanned = avg_text_len < 100  # 平均每页少于100字符

        if is_scanned:
            logger.warning(
                f"检测到扫描版 PDF (平均文字量: {avg_text_len:.0f} 字符/页)"
            )

        return is_scanned

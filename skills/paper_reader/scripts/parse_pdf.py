#!/usr/bin/env python3
"""
ScholarMind Paper Reader — CLI Wrapper
=======================================

CLI interface for PDF parsing, used by the Antigravity paper_reader Skill.

Usage:
    python parse_pdf.py --action text --pdf paper.pdf
    python parse_pdf.py --action structure --pdf paper.pdf
    python parse_pdf.py --action metadata --pdf paper.pdf
    python parse_pdf.py --action images --pdf paper.pdf --page 0
    python parse_pdf.py --action render --pdf paper.pdf --page 0 --dpi 200
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Fix Windows GBK encoding: force UTF-8 for stdout/stderr
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Add project root to path (scripts/ -> paper_reader/ -> skills/ -> project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.pdf_parser import PDFParser
from src.core.multimodal import PaperStructureParser

# 图片大小过滤阈值（过小的图片通常是 icon/logo，不是论文图表）
MIN_IMAGE_SIZE_KB = 5.0
MIN_IMAGE_DIMENSION = 100  # 宽或高至少 100px

DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "data" / "scholarmind_images"


def ensure_output_dir() -> Path:
    """Ensure output directory exists."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def cmd_download(url_or_id: str, filename: str = "") -> None:
    """
    Download a PDF from arXiv ID or direct URL.

    Supports:
      - arXiv ID: "2210.03629" → https://arxiv.org/pdf/2210.03629.pdf
      - Direct URL: "https://arxiv.org/pdf/2210.03629.pdf"
      - Any other PDF URL
    """
    import urllib.request
    import ssl
    import re

    # Windows SSL workaround (same as download_agents.py)
    ssl._create_default_https_context = ssl._create_unverified_context

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Detect arXiv ID vs full URL
    arxiv_id_pattern = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")

    if arxiv_id_pattern.match(url_or_id):
        # It's an arXiv ID
        arxiv_id = url_or_id
        download_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        if not filename:
            filename = f"arxiv_{arxiv_id.replace('.', '_')}.pdf"
    elif url_or_id.startswith("http"):
        # It's a full URL
        download_url = url_or_id
        if not filename:
            # Extract filename from URL
            url_path = url_or_id.split("?")[0].split("/")[-1]
            filename = url_path if url_path.endswith(".pdf") else f"paper_{hash(url_or_id) % 10000:04d}.pdf"
    else:
        print(json.dumps({
            "status": "error",
            "message": f"无法识别的格式: '{url_or_id}'。请提供 arXiv ID (如 2210.03629) 或完整的 PDF URL。",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    dest = DATA_DIR / filename

    # Skip if already exists
    if dest.exists():
        size_kb = dest.stat().st_size / 1024
        print(json.dumps({
            "status": "skipped",
            "message": f"文件已存在: {dest}",
            "path": str(dest),
            "size_kb": round(size_kb, 1),
        }, ensure_ascii=False, indent=2))
        return

    # Download
    try:
        urllib.request.urlretrieve(download_url, str(dest))
        size_kb = dest.stat().st_size / 1024
        print(json.dumps({
            "status": "ok",
            "message": f"下载成功",
            "url": download_url,
            "path": str(dest),
            "size_kb": round(size_kb, 1),
        }, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "message": f"下载失败: {type(e).__name__}: {e}",
            "url": download_url,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

def cmd_metadata(pdf_path: str) -> None:
    """Extract PDF metadata."""
    with PDFParser(pdf_path) as parser:
        meta = parser.get_metadata()
        is_scanned = parser.is_scanned_pdf()

        result = {
            "title": meta.title or "(未知)",
            "author": meta.author or "(未知)",
            "page_count": meta.page_count,
            "file_size_mb": meta.file_size_mb,
            "file_path": meta.file_path,
            "is_scanned": is_scanned,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_text(pdf_path: str) -> None:
    """Extract full text."""
    with PDFParser(pdf_path) as parser:
        text = parser.extract_full_text()
        # Output as JSON for structured parsing
        result = {
            "total_chars": len(text),
            "text": text,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_structure(pdf_path: str) -> None:
    """Extract paper section structure."""
    structure_parser = PaperStructureParser()

    with PDFParser(pdf_path) as parser:
        full_text = parser.extract_full_text()
        sections = structure_parser.parse_sections(full_text)

        result = {
            "section_count": len(sections),
            "sections": {
                name: {
                    "word_count": len(text.split()),
                    "char_count": len(text),
                    "preview": text[:300] + "..." if len(text) > 300 else text,
                }
                for name, text in sections.items()
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_images(pdf_path: str, page_num: int) -> None:
    """Extract images from a specific page and save to disk."""
    out_dir = ensure_output_dir()

    with PDFParser(pdf_path) as parser:
        images = parser.extract_images_from_page(page_num)

        if not images:
            print(json.dumps({
                "status": "no_images",
                "message": f"第 {page_num} 页没有嵌入图片。建议使用 --action render 进行整页渲染。",
            }, ensure_ascii=False, indent=2))
            return

        saved = []
        for img in images:
            import base64
            filename = f"page{page_num}_fig{img.index}.{img.format}"
            filepath = out_dir / filename
            img_bytes = base64.b64decode(img.base64_data)
            filepath.write_bytes(img_bytes)
            saved.append({
                "path": str(filepath),
                "format": img.format,
                "width": img.width,
                "height": img.height,
                "size_kb": img.size_kb,
            })

        print(json.dumps({
            "status": "ok",
            "page": page_num,
            "image_count": len(saved),
            "images": saved,
        }, ensure_ascii=False, indent=2))


def cmd_deep(pdf_path: str) -> None:
    """
    深度多模态解析：一次性提取文本 + 章节结构 + 所有嵌入图片。

    设计原理:
      - 文本用文本提取（零 Vision token 消耗）
      - 图片只提取嵌入的 figure（不做全页渲染，节省 token）
      - 自动过滤过小的图片（icon/logo/装饰图，< 5KB 或 < 100px）
      - 返回结构化 JSON，宿主 LLM 可按需用 view_file 查看图片
    """
    import base64
    out_dir = ensure_output_dir()
    structure_parser = PaperStructureParser()

    with PDFParser(pdf_path) as parser:
        # 1. 元数据
        meta = parser.get_metadata()
        is_scanned = parser.is_scanned_pdf()

        if is_scanned:
            print(json.dumps({
                "status": "scanned_pdf",
                "message": "检测到扫描版 PDF，无法提取文字。建议使用 --action render 逐页渲染后用 view_file 分析。",
                "page_count": meta.page_count,
            }, ensure_ascii=False, indent=2))
            return

        # 2. 全文文本
        full_text = parser.extract_full_text()

        # 3. 章节结构
        sections = structure_parser.parse_sections(full_text)
        section_info = {
            name: {"char_count": len(text), "preview": text[:200] + "..." if len(text) > 200 else text}
            for name, text in sections.items()
        }

        # 4. 提取所有嵌入图片（过滤噪声图片）
        all_images = parser.extract_all_images()
        saved_figures = []
        skipped = 0

        for img in all_images:
            # 过滤过小的图片（icon、logo、装饰性小图）
            if img.size_kb < MIN_IMAGE_SIZE_KB:
                skipped += 1
                continue
            if img.width < MIN_IMAGE_DIMENSION and img.height < MIN_IMAGE_DIMENSION:
                skipped += 1
                continue

            filename = f"page{img.page_num}_fig{img.index}.{img.format}"
            filepath = out_dir / filename
            img_bytes = base64.b64decode(img.base64_data)
            filepath.write_bytes(img_bytes)

            saved_figures.append({
                "path": str(filepath),
                "page": img.page_num,
                "index": img.index,
                "format": img.format,
                "width": img.width,
                "height": img.height,
                "size_kb": round(img.size_kb, 1),
            })

        # 5. 输出完整结果
        result = {
            "status": "ok",
            "metadata": {
                "title": meta.title or "(未知)",
                "page_count": meta.page_count,
                "file_size_mb": meta.file_size_mb,
                "total_chars": len(full_text),
            },
            "sections": section_info,
            "text": full_text,
            "figures": {
                "total_extracted": len(all_images),
                "saved": len(saved_figures),
                "skipped_small": skipped,
                "images": saved_figures,
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_render(pdf_path: str, page_num: int, dpi: int) -> None:
    """Render a page as PNG image and save to disk."""
    out_dir = ensure_output_dir()

    with PDFParser(pdf_path) as parser:
        b64_data = parser.render_page_as_image(page_num, dpi=dpi)

        import base64
        filename = f"page{page_num}_rendered_dpi{dpi}.png"
        filepath = out_dir / filename
        img_bytes = base64.b64decode(b64_data)
        filepath.write_bytes(img_bytes)

        print(json.dumps({
            "status": "ok",
            "page": page_num,
            "dpi": dpi,
            "path": str(filepath),
            "size_kb": len(img_bytes) / 1024,
        }, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="ScholarMind Paper Reader CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  download   Download PDF from arXiv ID or URL
  metadata   Extract PDF metadata (title, author, pages, scanned?)
  text       Extract full text content
  structure  Parse section structure with word counts
  images     Extract embedded images from a specific page
  render     Render entire page as PNG image for vision analysis
  deep       Deep multimodal parse: text + structure + all figures in one shot
        """,
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["download", "metadata", "text", "structure", "images", "render", "deep"],
        help="Action to perform",
    )
    parser.add_argument("--pdf", default="", help="Path to PDF file (required for all except download)")
    parser.add_argument("--url", default="", help="arXiv ID (e.g. 2210.03629) or full PDF URL for download")
    parser.add_argument("--filename", default="", help="Custom filename for downloaded PDF")
    parser.add_argument("--page", type=int, default=0, help="Page number (0-indexed)")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for page rendering (150/200/300)")

    args = parser.parse_args()

    try:
        if args.action == "download":
            if not args.url:
                print(json.dumps({"status": "error", "message": "--url is required for download action"}, ensure_ascii=False), file=sys.stderr)
                sys.exit(1)
            cmd_download(args.url, args.filename)
        elif not args.pdf:
            print(json.dumps({"status": "error", "message": "--pdf is required for this action"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        elif args.action == "metadata":
            cmd_metadata(args.pdf)
        elif args.action == "text":
            cmd_text(args.pdf)
        elif args.action == "structure":
            cmd_structure(args.pdf)
        elif args.action == "images":
            cmd_images(args.pdf, args.page)
        elif args.action == "deep":
            cmd_deep(args.pdf)
        elif args.action == "render":
            cmd_render(args.pdf, args.page, args.dpi)
    except FileNotFoundError:
        print(json.dumps({
            "status": "error",
            "message": f"文件不存在: {args.pdf}",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "message": f"{type(e).__name__}: {e}",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

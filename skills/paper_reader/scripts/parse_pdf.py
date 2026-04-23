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

# Add project root to path (scripts/ -> paper_reader/ -> skills/ -> project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.pdf_parser import PDFParser
from src.core.multimodal import PaperStructureParser


OUTPUT_DIR = PROJECT_ROOT / "data" / "scholarmind_images"


def ensure_output_dir() -> Path:
    """Ensure output directory exists."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


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
  metadata   Extract PDF metadata (title, author, pages, scanned?)
  text       Extract full text content
  structure  Parse section structure with word counts
  images     Extract embedded images from a specific page
  render     Render entire page as PNG image for vision analysis
        """,
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["metadata", "text", "structure", "images", "render"],
        help="Action to perform",
    )
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--page", type=int, default=0, help="Page number (0-indexed)")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for page rendering (150/200/300)")

    args = parser.parse_args()

    try:
        if args.action == "metadata":
            cmd_metadata(args.pdf)
        elif args.action == "text":
            cmd_text(args.pdf)
        elif args.action == "structure":
            cmd_structure(args.pdf)
        elif args.action == "images":
            cmd_images(args.pdf, args.page)
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

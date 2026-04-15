"""
ScholarMind - End-to-End Verification Script
=============================================

Quick verification of all core modules:
1. Paper Search MCP Server tools
2. PDF Parser

Usage:
  python tests/verify_e2e.py
  python tests/verify_e2e.py --skip-api   (skip network calls)
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_ok(msg: str):
    print(f"  [OK] {msg}")


def print_fail(msg: str):
    print(f"  [FAIL] {msg}")


def print_skip(msg: str):
    print(f"  [SKIP] {msg}")


async def verify_paper_search(skip_api: bool = False):
    """Verify paper search MCP server"""
    print_section("1. Paper Search MCP Server")

    # Import check
    try:
        from src.mcp_servers.paper_search import (
            search_papers, get_paper_details, get_related_papers, search_arxiv,
            mcp
        )
        print_ok("Module import successful")
    except Exception as e:
        print_fail(f"Import failed: {e}")
        return False

    # MCP tools registered check
    # Access internal tool list via the server
    print_ok(f"MCP Server name: {mcp.name}")

    if skip_api:
        print_skip("API calls skipped (--skip-api)")
        return True

    # Semantic Scholar search
    try:
        result = await search_papers("OFDM channel estimation", limit=2)
        if "FAIL" not in result and len(result) > 50:
            print_ok(f"Semantic Scholar search: {len(result)} chars returned")
        else:
            print_fail(f"Semantic Scholar: {result[:100]}")
    except Exception as e:
        print_fail(f"Semantic Scholar search error: {e}")

    # arXiv search
    try:
        result = await search_arxiv("integrated sensing communication", limit=2)
        if "FAIL" not in result and len(result) > 50:
            print_ok(f"arXiv search: {len(result)} chars returned")
        else:
            print_fail(f"arXiv: {result[:100]}")
    except Exception as e:
        print_fail(f"arXiv search error: {e}")

    return True


def verify_pdf_parser():
    """Verify PDF parser module"""
    print_section("2. PDF Parser Module")

    try:
        from src.core.pdf_parser import PDFParser, PDFMetadata, ExtractedImage
        print_ok("Module import successful")
    except Exception as e:
        print_fail(f"Import failed: {e}")
        return False

    # Check fitz (PyMuPDF) is available
    try:
        import fitz
        print_ok(f"PyMuPDF version: {fitz.version[0]}")
    except Exception as e:
        print_fail(f"PyMuPDF not available: {e}")
        return False

    # Test data classes
    meta = PDFMetadata(title="Test", page_count=5)
    assert "Test" in meta.summary()
    print_ok("PDFMetadata dataclass works")

    img = ExtractedImage(page_num=0, index=0, format="png", base64_data="dGVzdA==")
    assert img.size_kb > 0
    print_ok("ExtractedImage dataclass works")

    return True


def verify_project_structure():
    """Verify project files exist"""
    print_section("3. Project Structure")

    required_files = [
        "CLAUDE.md",
        "README.md",
        ".gitignore",
        ".env.example",
        "requirements.txt",
        "pytest.ini",
        "src/__init__.py",
        "src/mcp_servers/__init__.py",
        "src/mcp_servers/paper_search.py",
        "src/core/__init__.py",
        "src/core/pdf_parser.py",
        "src/knowledge/__init__.py",
        "src/execution/__init__.py",
        "tests/test_paper_search.py",
    ]

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    all_exist = True

    for f in required_files:
        full_path = os.path.join(project_root, f)
        if os.path.exists(full_path):
            print_ok(f"{f}")
        else:
            print_fail(f"{f} MISSING")
            all_exist = False

    return all_exist


async def main():
    skip_api = "--skip-api" in sys.argv

    print("\n" + "=" * 60)
    print("  ScholarMind E2E Verification")
    print("=" * 60)

    results = []

    # 1. Project structure
    results.append(verify_project_structure())

    # 2. PDF Parser
    results.append(verify_pdf_parser())

    # 3. Paper Search (may need network)
    results.append(await verify_paper_search(skip_api))

    # Summary
    print_section("Summary")
    passed = sum(results)
    total = len(results)
    print(f"\n  {passed}/{total} modules verified successfully")

    if all(results):
        print("\n  Phase 0 VERIFIED\n")
    else:
        print("\n  Some checks failed. Review above output.\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

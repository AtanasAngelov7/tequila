"""Unit tests for Sprint 13 D1 — DocumentsPlugin (PDF, DOCX, XLSX, CSV tools)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


# ── PDF tools ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_create_and_read_pages(tmp_dir: Path):
    pytest.importorskip("fitz", reason="PyMuPDF not installed")
    pytest.importorskip("fpdf", reason="fpdf2 not installed")
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    out = str(tmp_dir / "test.pdf")
    result = await TOOL_FN_MAP["pdf_create"](
        output_path=out,
        content="Hello World",
        title="Test",
    )
    assert os.path.exists(out), f"pdf_create result: {result}"

    text_result = await TOOL_FN_MAP["pdf_read_pages"](path=out, start=1, end=1)
    assert isinstance(text_result, dict)
    assert "Hello World" in str(text_result)


@pytest.mark.asyncio
async def test_pdf_open_returns_metadata(tmp_dir: Path):
    pytest.importorskip("fitz", reason="PyMuPDF not installed")
    pytest.importorskip("fpdf", reason="fpdf2 not installed")
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    out = str(tmp_dir / "info.pdf")
    await TOOL_FN_MAP["pdf_create"](output_path=out, content="Info test")
    info = await TOOL_FN_MAP["pdf_open"](path=out)
    assert isinstance(info, dict)
    assert "page_count" in info


# ── DOCX tools ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_docx_create_and_open(tmp_dir: Path):
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    out = str(tmp_dir / "test.docx")
    result = await TOOL_FN_MAP["docx_create"](
        output_path=out,
        title="My Doc",
        content="Paragraph one.\nParagraph two.",
    )
    assert os.path.exists(out), f"docx_create result: {result}"

    opened = await TOOL_FN_MAP["docx_open"](path=out)
    assert isinstance(opened, dict)
    assert "Paragraph one" in opened.get("text", "")


# ── XLSX tools ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xlsx_create_and_open(tmp_dir: Path):
    pytest.importorskip("openpyxl", reason="openpyxl not installed")
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    out = str(tmp_dir / "test.xlsx")
    result = await TOOL_FN_MAP["xlsx_create"](
        output_path=out,
        sheets=[{"name": "Sheet1", "headers": ["Name", "Score"], "rows": [["Alice", 100], ["Bob", 90]]}],
    )
    assert os.path.exists(out), f"xlsx_create result: {result}"

    data = await TOOL_FN_MAP["xlsx_open"](path=out)
    assert isinstance(data, dict)
    assert data["sheet_count"] == 1


@pytest.mark.asyncio
async def test_xlsx_open_lists_sheets(tmp_dir: Path):
    pytest.importorskip("openpyxl", reason="openpyxl not installed")
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    out = str(tmp_dir / "sheets.xlsx")
    await TOOL_FN_MAP["xlsx_create"](
        output_path=out,
        sheets=[{"name": "Data", "headers": ["x", "y"], "rows": []}],
    )
    result = await TOOL_FN_MAP["xlsx_open"](path=out)
    sheet_names = [s["name"] for s in result["sheets"]]
    assert "Data" in sheet_names


# ── CSV tools ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_open(tmp_dir: Path):
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    csv_file = tmp_dir / "test.csv"
    csv_file.write_text("name,age\nAlice,30\nBob,25\n")
    result = await TOOL_FN_MAP["csv_open"](path=str(csv_file), max_rows=100)
    assert isinstance(result, dict)
    assert "Alice" in str(result)
    assert "Bob" in str(result)


@pytest.mark.asyncio
async def test_csv_to_xlsx(tmp_dir: Path):
    pytest.importorskip("openpyxl", reason="openpyxl not installed")
    from app.plugins.builtin.documents.tools import TOOL_FN_MAP

    csv_file = tmp_dir / "data.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n")
    out = str(tmp_dir / "out.xlsx")
    result = await TOOL_FN_MAP["csv_to_xlsx"](csv_path=str(csv_file), output_path=out)
    assert os.path.exists(out), f"csv_to_xlsx result: {result}"


# ── DocumentsPlugin ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_documents_plugin_metadata():
    from app.plugins.builtin.documents.plugin import DocumentsPlugin

    p = DocumentsPlugin()
    assert p.plugin_id == "documents"
    assert p.plugin_type in ("connector", "builtin")


@pytest.mark.asyncio
async def test_documents_plugin_get_tools_returns_list():
    from app.plugins.builtin.documents.plugin import DocumentsPlugin

    p = DocumentsPlugin()
    tools = await p.get_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    # Each tool dict should have name and description
    for tool in tools:
        assert "name" in tool
        assert "description" in tool

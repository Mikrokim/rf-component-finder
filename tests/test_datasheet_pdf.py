"""Tests for rf_finder/datasheet/pdf.py — datasheet PDF (by URL) to text.

The page-joining core is exercised with fake page objects (each exposing
``extract_text()``), so no real PDF file is needed. The URL path is exercised
with a stubbed ``httpx.get`` (and a stubbed parse core for the success case), so
the tests never touch the network or need a real PDF.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import httpx
import pytest

from rf_finder.datasheet import pdf
from rf_finder.datasheet.pdf import (
    DatasheetFetchError,
    _join_page_text,
    datasheet_text_from_url,
)


@dataclass
class _FakePage:
    """Stand-in for a pdfplumber page: returns canned ``extract_text()``."""

    text: str | None

    def extract_text(self) -> str | None:
        return self.text


@dataclass
class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response``."""

    content: bytes
    headers: dict = field(default_factory=dict)

    def raise_for_status(self) -> None:
        return None


def test_pages_are_joined_with_blank_line():
    pages = [_FakePage("PAGE ONE"), _FakePage("PAGE TWO")]

    assert _join_page_text(pages) == "PAGE ONE\n\nPAGE TWO"


def test_empty_and_none_pages_are_skipped():
    # Image-only pages yield None or whitespace; they must not add blank blocks.
    pages = [_FakePage("REAL"), _FakePage(None), _FakePage("   "), _FakePage("MORE")]

    assert _join_page_text(pages) == "REAL\n\nMORE"


def test_no_extractable_text_gives_empty_string():
    assert _join_page_text([_FakePage(None), _FakePage("")]) == ""


def test_successful_fetch_parses_downloaded_bytes(monkeypatch):
    # httpx returns real-looking PDF bytes; the pure parse core is stubbed so the
    # test needs no real PDF. We assert the bytes reach the parser via a BytesIO.
    seen = {}

    def fake_get(url, **kwargs):
        return _FakeResponse(b"%PDF-1.4 fake body", {"Content-Type": "application/pdf"})

    def fake_parse(source, *, pages=None):
        seen["is_stream"] = isinstance(source, io.BytesIO)
        seen["body"] = source.read()
        return "EXTRACTED TEXT"

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(pdf, "_text_from_stream", fake_parse)

    assert datasheet_text_from_url("http://x/ds.pdf") == "EXTRACTED TEXT"
    assert seen["is_stream"] is True
    assert seen["body"] == b"%PDF-1.4 fake body"


def test_http_error_raises_datasheet_fetch_error(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(DatasheetFetchError):
        datasheet_text_from_url("http://x/ds.pdf")


def test_non_pdf_response_raises_datasheet_fetch_error(monkeypatch):
    # An HTML error page served with status 200 must not reach the PDF parser.
    def fake_get(url, **kwargs):
        return _FakeResponse(b"<html>not found</html>", {"Content-Type": "text/html"})

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(DatasheetFetchError):
        datasheet_text_from_url("http://x/ds.pdf")

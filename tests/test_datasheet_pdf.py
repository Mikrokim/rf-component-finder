"""Tests for rf_finder/datasheet/pdf.py — PDF-to-text for the extractor.

The page-joining logic is exercised with fake page objects (each exposing
``extract_text()``), so no real PDF file is needed — matching how the extractor
tests inject a mock runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from rf_finder.datasheet.pdf import _join_page_text, datasheet_text_from_pdf


@dataclass
class _FakePage:
    """Stand-in for a pdfplumber page: returns canned ``extract_text()``."""

    text: str | None

    def extract_text(self) -> str | None:
        return self.text


def test_pages_are_joined_with_blank_line():
    pages = [_FakePage("PAGE ONE"), _FakePage("PAGE TWO")]

    assert _join_page_text(pages) == "PAGE ONE\n\nPAGE TWO"


def test_empty_and_none_pages_are_skipped():
    # Image-only pages yield None or whitespace; they must not add blank blocks.
    pages = [_FakePage("REAL"), _FakePage(None), _FakePage("   "), _FakePage("MORE")]

    assert _join_page_text(pages) == "REAL\n\nMORE"


def test_no_extractable_text_gives_empty_string():
    assert _join_page_text([_FakePage(None), _FakePage("")]) == ""


def test_missing_path_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        datasheet_text_from_pdf(tmp_path / "nope.pdf")

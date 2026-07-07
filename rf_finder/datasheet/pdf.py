"""Turn a datasheet PDF into the raw text ``extract_rf_parameters`` consumes.

``extract_rf_parameters`` takes already-extracted text; real datasheets are
PDFs.  This module bridges the two with ``pdfplumber`` (already a project
dependency): open the PDF, pull each page's text, join it.

The page-joining logic lives in the tiny, dependency-free ``_join_page_text``
helper so it can be unit-tested with fake page objects, without needing a real
PDF file — mirroring how ``extractor`` keeps its parsing testable.
"""

from __future__ import annotations

from pathlib import Path


def _join_page_text(pages) -> str:
    """Join the text of ``pages`` (objects with ``.extract_text()``).

    Pages that yield no text (e.g. image-only pages) are skipped; the rest are
    separated by a blank line so the model sees clear page boundaries.
    """
    parts = []
    for page in pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def datasheet_text_from_pdf(
    path: str | Path, *, pages: list[int] | None = None
) -> str:
    """Extract raw text from a datasheet PDF file.

    ``path`` is the path to the PDF (``str`` or ``Path``).  ``pages`` optionally
    restricts extraction to a list of 0-based page indices (e.g. ``[0, 1]`` for
    the first two pages); ``None`` reads every page.

    Returns the concatenated page text, ready to hand to
    ``extract_rf_parameters``.  Raises ``FileNotFoundError`` when ``path`` does
    not exist.
    """
    import pdfplumber

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Datasheet PDF not found: {path}")

    with pdfplumber.open(path) as pdf:
        selected = pdf.pages if pages is None else [pdf.pages[i] for i in pages]
        return _join_page_text(selected)

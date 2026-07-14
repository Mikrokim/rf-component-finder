"""Turn a datasheet PDF, fetched by URL, into the raw text ``extract_rf_parameters`` consumes.

``extract_rf_parameters`` takes already-extracted text; real datasheets are
per-part PDFs whose link (``Candidate.datasheet_url``) the adapters scrape from
the manufacturer page.  This module bridges the two: download the PDF from its
URL, hand its bytes to ``pdfplumber`` (already a project dependency), and join
each page's text.

The layer is split so each concern is testable on its own:
  - ``_join_page_text`` — dependency-free page joining, unit-tested with fake
    page objects (no real PDF needed).
  - ``_text_from_stream`` — the pure PDF→text core; ``pdfplumber.open`` accepts
    any binary stream, so it works the same on a downloaded ``BytesIO`` as on a
    local file, with no network of its own.
  - ``datasheet_text_from_url`` — the only public entry point: fetch + parse.

The download is kept in memory (``io.BytesIO``); no temporary file is written.
Any failure (network, HTTP status, non-PDF response, unparseable PDF) is raised
as ``DatasheetFetchError`` so the orchestration layer can catch it per-candidate,
leave that candidate unenriched, and carry on with the rest of the run.
"""

from __future__ import annotations

import io

# A desktop-browser UA, matching the adapters — some CDNs reject default clients.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class DatasheetFetchError(Exception):
    """Raised when a datasheet PDF cannot be downloaded or parsed.

    Carries the offending ``url`` and the underlying cause so the orchestration
    layer can report it and move on without aborting the whole search.
    """

    def __init__(self, url: str, cause: Exception | None = None):
        self.url = url
        self.cause = cause
        super().__init__(
            f"Could not fetch datasheet: {url}" + (f" ({cause})" if cause else "")
        )


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


def _text_from_stream(source, *, pages: list[int] | None = None) -> str:
    """Pure PDF→text core.

    ``source`` is anything ``pdfplumber.open`` accepts — a path or a binary
    stream (e.g. the ``io.BytesIO`` of a downloaded PDF).  ``pages`` optionally
    restricts extraction to a list of 0-based page indices; ``None`` reads every
    page.  No network or filesystem assumptions live here, so it is unit-testable
    with an in-memory PDF and never touches the wire.
    """
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        selected = pdf.pages if pages is None else [pdf.pages[i] for i in pages]
        return _join_page_text(selected)


def datasheet_text_from_url(
    url: str, *, pages: list[int] | None = None, timeout: float = 30.0
) -> str:
    """Download the datasheet PDF at ``url`` and return its joined page text.

    The PDF is fetched into memory (``io.BytesIO``) and parsed — no temporary
    file is written.  ``pages`` optionally restricts extraction to a list of
    0-based page indices; ``None`` reads every page.

    Raises ``DatasheetFetchError`` on any failure — a network/HTTP error, a
    response that is not a PDF (e.g. an HTML error page served with status 200),
    or an unparseable PDF — so the caller can leave the candidate unenriched and
    continue the run.
    """
    import httpx

    try:
        response = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/pdf,*/*"},
            follow_redirects=True,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DatasheetFetchError(url, exc) from exc

    body = response.content
    # Guard against an HTML error page returned with a 200: a real PDF starts
    # with the "%PDF" signature. Trust the signature over the Content-Type header.
    content_type = response.headers.get("Content-Type", "")
    if not body[:5].startswith(b"%PDF") and "pdf" not in content_type.lower():
        raise DatasheetFetchError(
            url, ValueError(f"response is not a PDF (Content-Type: {content_type!r})")
        )

    try:
        return _text_from_stream(io.BytesIO(body), pages=pages)
    except Exception as exc:  # unparseable/corrupt PDF
        raise DatasheetFetchError(url, exc) from exc

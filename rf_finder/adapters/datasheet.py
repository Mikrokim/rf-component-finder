"""Shared datasheet engine: PDF→text and pattern-driven parameter extraction.

Adapters whose HTML tables omit a parameter (e.g. AmcomUSA omits OIP3) recover it
from the PDF datasheet.  The mechanics are identical across manufacturers — only
*which* parameters (declared per adapter via ``Adapter.datasheet_params``) and
*where* the PDF lives differ — so the generic, reusable parts live here:

  * ``extract_pdf_text`` — turn PDF bytes into text (manufacturer-agnostic).
  * ``PATTERNS``         — a shared library of tolerant label→value regexes,
                           keyed by canonical parameter name.
  * ``parse_params``     — apply the patterns for a requested set of params.

Nothing here is OIP3-specific: OIP3 is simply the one entry currently in
``PATTERNS``.  A new datasheet parameter is added with one ``PATTERNS`` entry
(once, for every adapter) rather than new extraction code per adapter.
"""

from __future__ import annotations

import io
import re

from rf_finder.models import RawValue

# ---------------------------------------------------------------------------
# Pattern library: canonical name -> (compiled regex, source unit).
# Each regex must expose the numeric value as group(1).
# ---------------------------------------------------------------------------

PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    # IP3 / OIP3 (but NOT IIP3) followed — within a short non-numeric gap that
    # may contain a "dBm" token in either order — by the first signed number.
    # Tolerant to both real AmcomUSA layouts: "IP3 35 dBm" and "IP3 dBm +25".
    "OIP3": (
        re.compile(
            r"(?<![A-Za-z])O?IP3\b"       # IP3 or OIP3, not preceded by a letter (skips IIP3)
            r"[^0-9+\-\n]{0,12}"           # up to 12 non-numeric chars (e.g. " dBm ")
            r"([+-]?\d+(?:\.\d+)?)",       # the value
            re.IGNORECASE,
        ),
        "dBm",
    ),
}


def parse_params(text: str, wanted: set[str]) -> dict[str, RawValue]:
    """Extract the *wanted* canonical parameters from datasheet *text*.

    Only names present in both *wanted* and ``PATTERNS`` are attempted; anything
    not found is simply absent from the result, so callers can merge it freely.
    """
    found: dict[str, RawValue] = {}

    for name in wanted:
        rule = PATTERNS.get(name)
        if rule is None:
            continue
        pattern, unit = rule
        match = pattern.search(text)
        if match:
            try:
                found[name] = RawValue(value=float(match.group(1)), unit=unit)
            except ValueError:
                pass

    return found


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Return the concatenated text of every page in a PDF byte stream.

    Raises ``ImportError`` if ``pdfplumber`` is unavailable; the caller decides
    whether to treat that as fatal.
    """
    import pdfplumber  # local import: keeps the dependency optional at module load

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)

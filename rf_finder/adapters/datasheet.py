"""Shared datasheet engine: PDF→text and pattern-driven parameter extraction.

Adapters whose HTML tables omit a parameter recover it from the PDF datasheet.
The mechanics are identical across manufacturers — only *which* parameters
(declared per adapter via ``Adapter.datasheet_params``) and *where* the PDF
lives differ — so the generic, reusable parts live here:

  * ``extract_pdf_text`` — turn PDF bytes into text (manufacturer-agnostic).
  * ``PATTERNS``         — a shared library of tolerant label→value regexes,
                           keyed by canonical parameter name.
  * ``parse_params``     — apply the patterns for a requested set of params.

The patterns are written to be **generic**, not tuned to one manufacturer's
phrasing.  Two principles keep them robust to real datasheet text:

  1. Anchor on the *unit/shape* of the value, not on a label word — a
     ``N°C to M°C`` span is a temperature range wherever it appears; an
     ``N × N <unit>`` span is a package size.  (Labels move around or sit on a
     different PDF line than their value, so requiring them misses real cases.)
  2. Normalise numbers via ``_num`` — datasheets use a Unicode minus (``−``),
     en/em dashes as signs, and stray spaces (``+ 125``); a plain ``float`` on
     the raw token would fail on all of those.

Two value shapes are supported, matching the ontology's comparison rules:
scalar params (IP3, MSL, Size) and range params (Temperature, ``contains`` —
parsed as ``(low, high)``).  A pattern may read its unit inline (``unit_group``)
so e.g. Size in inches normalises correctly via ``units.to_canonical``.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from rf_finder.models import RawValue


@dataclass(frozen=True)
class _Spec:
    """One canonical parameter's datasheet-extraction rule.

    Attributes
    ----------
    regex:      compiled pattern; exposes the value as group(1) (and group(2)
                for a range), and optionally a unit token at ``unit_group``.
    unit:       source unit assumed when ``unit_group`` is unset/empty.
    is_range:   True -> value is a (low, high) tuple (for ``contains`` params).
    unit_group: group index holding an inline unit token, or None.
    """

    regex: re.Pattern[str]
    unit: str
    is_range: bool = False
    unit_group: int | None = None


# Inline unit tokens a datasheet may use for length, mapped to units.py keys.
_LENGTH_UNIT_ALIASES: dict[str, str] = {
    '"': "in", "in": "in", "inch": "in", "inches": "in",
    "mm": "mm", "cm": "cm", "mil": "mil",
}

# A signed number token tolerant of a Unicode minus / en–em dash sign and of a
# stray space between the sign and the digits (e.g. "+ 125", "−55").
_SIGNED = r"[+\-−–—]?\s*\d+(?:\.\d+)?"

# Length unit alternation, longest-first so "inches" wins over "inch"/"in".
_LEN_UNIT = r"mm|cm|mil|inches|inch|in|\""


def _num(token: str) -> float:
    """Parse a numeric token, normalising Unicode signs and stray spaces.

    Datasheets write "−55" (U+2212), "+ 125" (space after sign), or en/em dashes
    as a minus.  Map all of those to something ``float`` accepts.
    """
    cleaned = (
        token.strip()
        .replace("−", "-")   # Unicode MINUS SIGN
        .replace("–", "-")   # EN DASH (used as a minus by some tools)
        .replace("—", "-")   # EM DASH
        .replace(" ", "")
    )
    return float(cleaned)


# ---------------------------------------------------------------------------
# Pattern library: canonical name -> extraction spec.
# ---------------------------------------------------------------------------

PATTERNS: dict[str, _Spec] = {
    # IP3 / OIP3 (but NOT IIP3) followed — within a short non-numeric gap that
    # may contain a "dBm"/"=" token — by the first signed number.
    "IP3": _Spec(
        re.compile(
            r"(?<![A-Za-z])O?IP3\b"        # IP3 or OIP3, not preceded by a letter (skips IIP3)
            r"[^0-9+\-\n]{0,12}"            # up to 12 non-numeric chars (e.g. " dBm ", ": ", " = ")
            r"(" + _SIGNED + r")",          # the value
            re.IGNORECASE,
        ),
        "dBm",
    ),

    # MSL / Moisture Sensitivity Level: a digit 1–5 (optionally with a JEDEC
    # letter suffix, e.g. "2a") shortly after the label.  Dimensionless.
    "MSL": _Spec(
        re.compile(
            r"(?:MSL|moisture\s+sensitivity(?:\s+level)?)\b"
            r"[^0-9\n]{0,30}"             # label text up to the rating (no digits between)
            r"([1-5])(?![0-9.])",         # the level; allow a trailing letter (2a/3a), reject 2.x / 12
            re.IGNORECASE,
        ),
        "",
    ),

    # Operating temperature range: two numbers around a range separator, with a
    # trailing "°C"/"C" as the temperature signal.  Anchored on the unit, NOT on
    # the word "temperature" (which often sits on a different PDF line than its
    # value).  Tolerant of a Unicode minus and a space in "+ 125" (see _num).
    # A plain hyphen is excluded as a separator to avoid colliding with a sign.
    "Temperature": _Spec(
        re.compile(
            r"(" + _SIGNED + r")"                       # low
            r"(?:\s*°?\s*[Cc])?\s*"                 # optional °C on the low side
            r"(?:to|thru|through|~|–|—|…|\.\.\.)\s*"   # range separator
            r"(" + _SIGNED + r")"                       # high
            r"\s*°?\s*[Cc]",                        # required °C/C — the temperature signal
            re.IGNORECASE,
        ),
        "degC",
        is_range=True,
    ),

    # Package size: first dimension of an "N [unit] × N [unit]" string, with a
    # required trailing unit as the size signal.  Handles the unit after either
    # or both dimensions ("2 mm × 2 mm"), the inch mark ('1.25" x 1.25"'), the
    # '×' multiplication sign, and an optional third dimension (height).  Parts
    # are near-square, so group(1) (first dimension) stands in for the bounding
    # size used by the `max` rule; the trailing unit (group 2) is normalised.
    "Size": _Spec(
        re.compile(
            r"(\d+(?:\.\d+)?)\s*"                        # group1: first dimension
            r"(?:" + _LEN_UNIT + r")?\s*"                # optional unit after first dim
            r"[x×*]\s*\d+(?:\.\d+)?\s*"             # 'x'/'×' second dimension
            r"(?:[x×*]\s*\d+(?:\.\d+)?\s*)?"        # optional third dimension (height)
            r"(" + _LEN_UNIT + r")",                     # group2: trailing unit (the size signal)
            re.IGNORECASE,
        ),
        "mm",
        unit_group=2,
    ),
}


def parse_params(text: str, wanted: set[str]) -> dict[str, RawValue]:
    """Extract the *wanted* canonical parameters from datasheet *text*.

    Only names present in both *wanted* and ``PATTERNS`` are attempted; anything
    not found is simply absent from the result, so callers can merge it freely.
    Range params (e.g. Temperature) yield a ``(low, high)`` tuple value.
    """
    found: dict[str, RawValue] = {}

    for name in wanted:
        spec = PATTERNS.get(name)
        if spec is None:
            continue
        match = spec.regex.search(text)
        if match is None:
            continue

        try:
            if spec.is_range:
                value: float | tuple[float, float] = (
                    _num(match.group(1)),
                    _num(match.group(2)),
                )
            else:
                value = _num(match.group(1))
        except (ValueError, IndexError):
            continue

        unit = spec.unit
        if spec.unit_group is not None:
            token = (match.group(spec.unit_group) or "").strip().lower()
            unit = _LENGTH_UNIT_ALIASES.get(token, spec.unit)

        found[name] = RawValue(value=value, unit=unit)

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

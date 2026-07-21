"""Deterministic, model-free extraction of the explicit datasheet parameters
(TEMPERATURE, SIZE, MSL) from datasheet text.

Design: regex *locates* a labeled region, code *decodes* the value from it. Each
function returns a value or ``None`` — never a silent guess. Given identical
input text the output is identical (no model, no randomness). Validated against a
source-verified gold set (TEMP 7/7, SIZE 7/7) and a 32-datasheet corpus.

VDD is intentionally not handled here — it needs table-structure or semantic
disambiguation and stays on the LLM/hybrid path.
"""
from __future__ import annotations

import re

# --- shared -----------------------------------------------------------------
# Some vendor PDFs encode the degree sign as a private-use glyph (U+F0B0); the
# extractors normalise it to a real "°" before matching.
_DEG = chr(0xF0B0)

# --- TEMPERATURE ------------------------------------------------------------
_T_ANCHOR = re.compile(
    r"oper(?:ating|ation)\s+(?:case\s+|junction\s+|ambient\s+)?"
    r"(?:temp(?:erature|\.)?|range)", re.I)
# tier-2 fallback: a bare "Temperature Range" (some ADI parts), accepted only when
# its left context is not a storage/junction/mounting/reflow label.
_T_ANCHOR2 = re.compile(r"(?:specified\s+)?temperature\s+range", re.I)
_T_NEG = re.compile(r"storage|junction|mounting|solder|channel|reflow|peak|"
                    r"\bT[_ ]?(?:stg|j|ch|sto)\b", re.I)
_T_UNIT = re.compile(r"°\s*[CF]|℃|℉|\d\s*[CF]\b", re.I)
_T_DIGITS = re.compile(r"\d{1,3}")
_T_UNIT_AFTER = re.compile(r"\s*(?:°|℃|℉|[CF]\b)", re.I)
_T_SPAN = 70

# tier-0: some parts state the range as two SEPARATE labels — "Maximum Operating
# Temperature 85 °C" and "Minimum Operating Temperature -54 °C" — not "A to B".
# Read each label's own unit-adjacent number and pair them; a following Storage
# value can't leak in because each label captures a single number. The gap before
# the number must not swallow the sign, so it excludes sign characters.
_T_OP = r"operating\s+(?:case\s+|junction\s+|ambient\s+)?temp\w*"
_T_GAP = r"[^\d+\-−–—‒]{0,6}"
_T_MAXOP = re.compile(rf"max(?:imum)?\s+{_T_OP}{_T_GAP}([+-−–—‒]?\d{{1,3}})\s*(?:°|℃|℉|[CF]\b)", re.I)
_T_MINOP = re.compile(rf"min(?:imum)?\s+{_T_OP}{_T_GAP}([+-−–—‒]?\d{{1,3}})\s*(?:°|℃|℉|[CF]\b)", re.I)


def _signed_int(s: str) -> int:
    return -int(re.sub(r"\D", "", s)) if s[0] in "-−–—‒" else int(re.sub(r"\D", "", s))


def _temp_split(text: str):
    """(min, max) from separate 'Maximum/Minimum Operating Temperature' labels."""
    mx, mn = _T_MAXOP.search(text), _T_MINOP.search(text)
    if mx and mn:
        hi, lo = _signed_int(mx.group(1)), _signed_int(mn.group(1))
        return (min(lo, hi), max(lo, hi))
    return None


def _temp_nums(span: str) -> list[int]:
    """Temperature-plausible numbers in a span, accepting only signed or
    unit-adjacent digits (so a footnote superscript is skipped). En/em dash count
    as a minus sign."""
    out: list[int] = []
    for m in _T_DIGITS.finditer(span):
        n = int(m.group())
        if not -100 <= n <= 400:
            continue
        pre = span[m.start() - 1] if m.start() else " "
        signed = pre in "+-−–—‒"
        has_unit = bool(_T_UNIT_AFTER.match(span[m.end(): m.end() + 4]))
        if signed or has_unit:
            out.append(-n if pre in "-−–—‒" else n)
    return out


def _temp_from(text: str, matches, check_left: bool):
    for m in matches:
        if check_left and _T_NEG.search(text[max(0, m.start() - 25):m.start()]):
            continue
        span = text[m.start(): m.end() + _T_SPAN]
        if not _T_UNIT.search(span):
            continue
        nums = _temp_nums(span)
        if len(nums) >= 2:
            return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return None


def temp_range(text: str):
    """Operating temperature as ``(min, max)``, or ``None`` if none is stated.

    Selects the operating range and never the storage range.
    """
    text = text.replace(_DEG, "°")
    r = _temp_split(text)                                             # tier 0: split labels
    if r is None:
        r = _temp_from(text, _T_ANCHOR.finditer(text), check_left=False)   # tier 1: operating
    if r is None:
        r = _temp_from(text, _T_ANCHOR2.finditer(text), check_left=True)   # tier 2: bare range
    return r


# --- SIZE -------------------------------------------------------------------
_S_U = r"µm|μm|um|mm|nm|mils?|[\"″”“′]|inch|in"
_S_DIM = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:{_S_U})?\s*(?:\([LWHlwh]\))?\s*"
    rf"[x×]\s*(\d+(?:\.\d+)?)\s*(?:{_S_U})?", re.I)
_S_UNIT = re.compile(_S_U, re.I)
_S_PREFER = re.compile(
    r"package|die size|die\b|body|module|chip|outline dimension|dimensions?:|size", re.I)
_S_DISTRACT = re.compile(
    r"thru\s*hole|diameter|tolerance|deep|dimensions in mils|drill|bond\s*pad|"
    r"mttf|hours|cycles|\bx\s*10\b", re.I)
# an eval-board bill-of-materials / discrete-component row (a capacitor, a
# capacitance value): its dimension is the component's, not the product's. A
# digit before the F unit keeps this off a package unit like "µm", and Ω is
# deliberately excluded so a "50Ω" impedance next to a die size is not caught.
_S_BOM = re.compile(
    r"\bCAP\b|capacitor|\bBOM\b|bill\s+of\s+material|\d\s*[µuμ]F\b|\d\s*[np]F\b", re.I)


def size_dims(text: str):
    """Physical part size as ``(a, b)`` from an ``A×B`` pattern, or ``None``.

    A candidate is a size only when its context has a length unit or a size
    keyword and no distractor (thru-hole, bond pad, MTTF, ...), and neither
    dimension is zero. A package/die/chip context is preferred over a bare match.
    """
    cands = []
    for m in _S_DIM.finditer(text):
        a, b = float(m.group(1)), float(m.group(2))
        if a == 0 or b == 0:
            continue
        ctx = text[max(0, m.start() - 50):m.end() + 20]
        if _S_DISTRACT.search(ctx) or _S_BOM.search(ctx):
            continue
        if not (_S_UNIT.search(ctx) or _S_PREFER.search(ctx)):
            continue
        score = 1 if _S_PREFER.search(ctx) else 0
        cands.append((score, a, b))
    if not cands:
        return None
    cands.sort(key=lambda c: -c[0])
    return (cands[0][1], cands[0][2])


# --- MSL --------------------------------------------------------------------
_M_ANCHOR = re.compile(r"moisture\s+sensitivity(?:\s+level)?|\bMSL", re.I)
# a STANDALONE 1-6 level digit — not part of a bigger number, so reflow
# temperatures (260/150/320) are skipped rather than read as the level.
_M_LEVEL = re.compile(r"(?<![0-9])([1-6][aA]?)(?![0-9])")


def msl_level(text: str):
    """MSL level as a string ('1'..'6', optionally with a letter), or ``None``."""
    for m in _M_ANCHOR.finditer(text):
        sm = _M_LEVEL.search(text[m.end(): m.end() + 35])
        if sm:
            return sm.group(1)
    return None

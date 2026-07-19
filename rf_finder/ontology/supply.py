"""Shared supply-voltage (VDD) parsing.

Manufacturer sites express a part's supply voltage in several textual forms.
This module is the single source of truth that turns any of them into the
normalized shape the Verifier compares under the ``contains`` rule, so every
adapter (and the datasheet fallback) behaves identically.

Supported forms (all positive) and their normalized value:

    "5"        single value            -> (5.0, 5.0)      continuous interval
    "8+"/"+8"  value with a plus sign   -> (8.0, 8.0)      the sign is ignored
    "10-15"    range                    -> (10.0, 15.0)    continuous interval
    "3/5/8"    discrete supply options  -> [3.0, 5.0, 8.0] pick-one list

A single value is stored as a degenerate ``(v, v)`` interval so intervals and
lists are the only two candidate shapes downstream.

Anything carrying a **negative** value is intentionally NOT supported: a lone
negative rail ("-7.5") or a dual positive/negative supply ("+3/-3") belongs to
control parts (attenuators, phase shifters) rather than the amplifier drain
supply this project matches. Such a cell returns ``None`` — VDD is simply left
UNKNOWN for that part (never filtered, never a wrong match), exactly as a
missing value behaves. Unparseable or sentinel cells return ``None`` too.
"""

from __future__ import annotations

import re

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "na", "—", "tbd", "none"})

# An unsigned number: "8", "8.5", ".5". Signs are handled separately so we can
# tell a range hyphen ("10-15") from a minus sign ("-7.5").
_UNSIGNED_NUM = re.compile(r"\d+\.?\d*|\.\d+")

# A minus that acts as a SIGN (not a range hyphen): it starts a value token —
# at the string start or right after a separator / opening paren / whitespace.
# Matches the leading "-" of "-7.5" and the "/-3" in "+3/-3", but NOT the hyphen
# in "10-15" (which sits between two digits).
_NEGATIVE_SIGN = re.compile(r"(?:^|[\s,/(])-\s*\.?\d")

# Range spelled with a word, e.g. "2 to 4.5".
_TO_RANGE = re.compile(r"\bto\b", re.IGNORECASE)


def parse_vdd(text: str | None) -> tuple[float, float] | list[float] | None:
    """Parse a supply-voltage cell into a normalized VDD value, else ``None``.

    Returns a ``(low, high)`` interval for a single value or a range, a
    ``list[float]`` of options for a discrete ``/``- or ``,``-separated cell,
    or ``None`` for a missing/negative/unrecognised cell (VDD stays UNKNOWN).
    """
    if text is None:
        return None
    t = text.strip()
    if not t or t.lower() in _MISSING_SENTINELS:
        return None

    # Negative rails (single "-7.5" or dual "+3/-3") are out of scope -> UNKNOWN.
    if _NEGATIVE_SIGN.search(t):
        return None

    # Discrete options: "/" or "," separated (e.g. "3/5/8", "5, 8").
    if "/" in t or "," in t:
        nums = [float(m.group()) for m in _UNSIGNED_NUM.finditer(t)]
        if not nums:
            return None
        # De-duplicate, ascending, so the value is stable regardless of order.
        return sorted(set(nums))

    # Word range: "2 to 4.5".
    if _TO_RANGE.search(t):
        nums = [float(m.group()) for m in _UNSIGNED_NUM.finditer(t)]
        if len(nums) < 2:
            return None
        return (min(nums), max(nums))

    nums = [float(m.group()) for m in _UNSIGNED_NUM.finditer(t)]
    if not nums:
        return None

    # Hyphen range: "10-15". Any hyphen left here sits between two numbers (a
    # sign-minus was already rejected above), so two numbers + a "-" is a range.
    if "-" in t and len(nums) == 2:
        return (min(nums), max(nums))

    # Single value ("5", "+8", "8+", "18 Vdc"): take the first number; a trailing
    # plus or unit is ignored. Extra stray numbers are not expected for a single
    # supply, so we key off the first token only.
    return (nums[0], nums[0])

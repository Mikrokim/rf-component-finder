"""Unit tests for the shared VDD parser (rf_finder.ontology.supply)."""

import pytest

from rf_finder.ontology.supply import parse_vdd


# --- Form 1: single value ---------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("5", (5.0, 5.0)),
        ("4", (4.0, 4.0)),
        ("28", (28.0, 28.0)),
        ("3.3", (3.3, 3.3)),
        ("18 Vdc", (18.0, 18.0)),   # trailing unit ignored
        ("24.0.", (24.0, 24.0)),    # malformed trailing dot tolerated
    ],
)
def test_single_value(text, expected):
    assert parse_vdd(text) == expected


# --- Form 2: value with a plus sign (sign ignored) --------------------------
@pytest.mark.parametrize("text", ["+8", "8+", "+8 ", " 8+"])
def test_plus_sign_is_ignored(text):
    assert parse_vdd(text) == (8.0, 8.0)


# --- Form 3: range ----------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("10-15", (10.0, 15.0)),
        ("2.5-3.5", (2.5, 3.5)),
        ("2 to 4.5", (2.0, 4.5)),
        ("15-10", (10.0, 15.0)),    # reversed -> normalised low<=high
    ],
)
def test_range(text, expected):
    assert parse_vdd(text) == expected


# --- Form 4: discrete options ----------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("3/5/8", [3.0, 5.0, 8.0]),
        ("5/8", [5.0, 8.0]),
        ("3, 5, 8", [3.0, 5.0, 8.0]),
        ("8/5/3", [3.0, 5.0, 8.0]),   # order-independent
        ("5/5/8", [5.0, 8.0]),        # de-duplicated
    ],
)
def test_discrete_options(text, expected):
    assert parse_vdd(text) == expected


# --- Negative rails are out of scope -> None (UNKNOWN) ----------------------
@pytest.mark.parametrize("text", ["-7.5", "+3/-3", "+5/-5", "-3", "-0.75", "8/-0.75"])
def test_negative_returns_none(text):
    assert parse_vdd(text) is None


# --- Missing / unparseable -> None ------------------------------------------
@pytest.mark.parametrize("text", [None, "", "  ", "-", "N/A", "n/a", "TBD", "none", "Die", "abc"])
def test_missing_returns_none(text):
    assert parse_vdd(text) is None


# --- Shape guarantees (never a bare float, only tuple|list|None) -------------
@pytest.mark.parametrize("text", ["5", "8+", "10-15", "3/5/8"])
def test_shape_is_tuple_or_list(text):
    out = parse_vdd(text)
    assert isinstance(out, (tuple, list))
    if isinstance(out, tuple):
        assert len(out) == 2 and all(isinstance(x, float) for x in out)
    else:
        assert all(isinstance(x, float) for x in out)

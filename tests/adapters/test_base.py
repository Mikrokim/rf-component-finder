"""Unit tests for shared adapter helpers in rf_finder.adapters.base."""

from __future__ import annotations

from rf_finder.adapters.base import drop_paramless, freq_range_from_bandwidth
from rf_finder.models import Candidate, RawValue


def _cand(model: str, raw_params: dict) -> Candidate:
    return Candidate(
        model=model,
        manufacturer="Test",
        url=f"https://example.com/{model}",
        raw_params=raw_params,
        source="table",
    )


# ---------------------------------------------------------------------------
# drop_paramless
# ---------------------------------------------------------------------------

def test_drop_paramless_removes_only_empty() -> None:
    withdata = _cand("A", {"Gain": RawValue(10.0, "dB")})
    empty = _cand("B", {})
    kept = drop_paramless([withdata, empty])
    assert kept == [withdata]


def test_drop_paramless_keeps_all_when_none_empty() -> None:
    cands = [
        _cand("A", {"Gain": RawValue(10.0, "dB")}),
        _cand("B", {"freq_range": RawValue((0.0, 4e9), "Hz")}),
    ]
    assert drop_paramless(cands) == cands


def test_drop_paramless_empty_input() -> None:
    assert drop_paramless([]) == []


def test_drop_paramless_removes_secondary_only() -> None:
    """A candidate with only secondary params (VDD) and no RF param is dropped."""
    vdd_only = _cand("V", {"VDD": RawValue((2.7, 5.0), "V")})
    has_rf = _cand("R", {"Gain": RawValue(10.0, "dB"), "VDD": RawValue((5.0, 5.0), "V")})
    kept = drop_paramless([vdd_only, has_rf])
    assert kept == [has_rf]  # vdd_only dropped; has_rf kept (it has Gain)


# ---------------------------------------------------------------------------
# freq_range_from_bandwidth
# ---------------------------------------------------------------------------

def test_freq_range_from_bandwidth_builds_dc_to_bw() -> None:
    assert freq_range_from_bandwidth(400000000.0) == RawValue((0.0, 400000000.0), "Hz")

"""Unit tests for shared adapter helpers in rf_finder.adapters.base."""

from __future__ import annotations

from rf_finder.adapters.base import Adapter, drop_paramless, freq_range_from_bandwidth
from rf_finder.models import Candidate, QuerySpec, RawValue


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


# ---------------------------------------------------------------------------
# Adapter.resolve_datasheet_url — default (case-1) behaviour
# ---------------------------------------------------------------------------

class _FakeAdapter(Adapter):
    """Minimal concrete adapter that never touches the network."""

    manufacturer = "Fake"
    supported_components = ["amplifier"]

    def search(self, spec: QuerySpec) -> list[Candidate]:  # pragma: no cover - unused
        return []


def test_resolve_datasheet_url_default_returns_candidate_link() -> None:
    """The default returns the candidate's own datasheet_url (case-1 adapters)."""
    cand = Candidate(
        model="A",
        manufacturer="Fake",
        url="https://example.com/A",
        raw_params={"Gain": RawValue(10.0, "dB")},
        source="table",
        datasheet_url="https://example.com/pdfs/A.pdf",
    )
    assert _FakeAdapter().resolve_datasheet_url(cand) == "https://example.com/pdfs/A.pdf"


def test_resolve_datasheet_url_default_returns_none_when_absent() -> None:
    """The default returns None when the candidate has no datasheet_url — no request."""
    cand = _cand("B", {"Gain": RawValue(10.0, "dB")})  # built without datasheet_url
    assert _FakeAdapter().resolve_datasheet_url(cand) is None

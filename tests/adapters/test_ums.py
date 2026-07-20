"""Offline unit tests for the UMS adapter (ums-plan.md §7).

All tests parse local HTML fixtures — no network. The ``test_search_live`` test
is marked ``@pytest.mark.network`` and is skipped in the default
``-m "not network"`` run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.ums import UmsAdapter
from rf_finder.models import Candidate, RawValue

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_LNA = _FIXTURES / "ums_amplifier_lna.html"
_HPA = _FIXTURES / "ums_amplifier_hpa.html"


def _parse(fixture: Path) -> list[Candidate]:
    return UmsAdapter()._parse_html(fixture.read_text(encoding="utf-8"))


def _by_model(fixture: Path, model: str) -> Candidate:
    return next(c for c in _parse(fixture) if c.model == model)


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------

def test_lna_parses_all_rows():
    assert len(_parse(_LNA)) == 3


def test_model_manufacturer_source():
    c = _parse(_LNA)[0]
    assert c.manufacturer == "UMS"
    assert c.source == "table"
    assert c.model == "CHA2292-99F"


def test_freq_range_combined_ghz():
    """RF Bandwidth (Min)/(Max) combine into a GHz RawValue tuple (no conversion)."""
    rv = _by_model(_LNA, "CHA2292-99F").raw_params["freq_range"]
    assert isinstance(rv, RawValue)
    assert rv.unit == "GHz"
    assert rv.value == (16.0, 24.0)


def test_url_and_model_link():
    c = _by_model(_LNA, "CHA2292-99F")
    assert c.url == "https://www.ums-rf.com/products/cha2292-99f/"


# ---------------------------------------------------------------------------
# Header-label mapping (not positional) + per-category column differences
# ---------------------------------------------------------------------------

def test_lna_maps_nf_not_ip3_or_psat():
    """LNA table has Noise Figure but no IP3/Psat columns."""
    c = _by_model(_LNA, "CHA2292-99F")
    assert c.raw_params["Gain"] == RawValue(26.0, "dB")
    assert c.raw_params["NF"] == RawValue(2.8, "dB")
    assert c.raw_params["P1dB"] == RawValue(11.0, "dBm")
    assert c.raw_params["VDD"] == RawValue(5.0, "V")
    assert "IP3" not in c.raw_params
    assert "Psat" not in c.raw_params


def test_hpa_maps_ip3_and_psat_not_nf():
    """HPA table has IP3 + Sat. Output Power but no Noise Figure column."""
    c = _by_model(_HPA, "CHA5659-98F")
    assert c.raw_params["freq_range"] == RawValue((36.0, 43.5), "GHz")
    assert c.raw_params["Gain"] == RawValue(22.0, "dB")
    assert c.raw_params["IP3"] == RawValue(38.5, "dBm")
    assert c.raw_params["P1dB"] == RawValue(30.0, "dBm")
    assert c.raw_params["Psat"] == RawValue(31.0, "dBm")
    assert c.raw_params["VDD"] == RawValue(6.0, "V")
    assert "NF" not in c.raw_params


def test_skipped_columns_not_mapped():
    """Bias (mA), Gain Flatness, Case are not ontology params -> absent."""
    c = _by_model(_LNA, "CHA2292-99F")
    assert set(c.raw_params) == {"freq_range", "Gain", "NF", "P1dB", "VDD"}


# ---------------------------------------------------------------------------
# Missing-value handling ("-" sentinel -> param absent, never None)
# ---------------------------------------------------------------------------

def test_dash_cell_makes_param_absent_lna():
    """CHA1008-99F has P-1dB OUT = '-' -> P1dB must be absent (Verifier -> UNKNOWN)."""
    c = _by_model(_LNA, "CHA1008-99F")
    assert "P1dB" not in c.raw_params
    assert c.raw_params["NF"] == RawValue(1.4, "dB")  # other cols still parsed


def test_dash_cell_makes_param_absent_hpa():
    """CHA8200-99F has IP3 = '-' -> IP3 absent; Psat still present."""
    c = _by_model(_HPA, "CHA8200-99F")
    assert "IP3" not in c.raw_params
    assert c.raw_params["Psat"] == RawValue(30.0, "dBm")


# ---------------------------------------------------------------------------
# Failure mode
# ---------------------------------------------------------------------------

def test_no_table_raises_adaptererror():
    with pytest.raises(AdapterError):
        UmsAdapter()._parse_html("<html><body><p>no product table</p></body></html>")


# ---------------------------------------------------------------------------
# Integration (network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_live():
    from rf_finder.models import ParamConstraint, QuerySpec

    spec = QuerySpec(
        component_type="amplifier",
        constraints=[
            ParamConstraint(
                canonical_name="freq_range",
                comparison="contains",
                value=None,
                range=(2.0, 6.0),
                unit="GHz",
            ),
        ],
    )
    results = UmsAdapter().search(spec)
    assert len(results) > 140  # ~156 amplifiers across 5 sub-types
    assert all(c.manufacturer == "UMS" for c in results)


# ---------------------------------------------------------------------------
# Datasheet link (case 1: the row's a.doc-link, already in the fetched page)
# ---------------------------------------------------------------------------

def test_datasheet_url_from_the_row_doc_link() -> None:
    """Absolute PDF on the same host — no extra request, no absolutize."""
    cands = UmsAdapter()._parse_html(
        (_FIXTURES / "ums_amplifier_hpa.html").read_text(encoding="utf-8")
    )
    cand = next(c for c in cands if c.model == "CHA5659-98F")
    assert cand.datasheet_url == (
        "https://www.ums-rf.com/wp-content/uploads/2017/01/CHA5659-98F-Full-0301.pdf"
    )
    assert cand.url != cand.datasheet_url  # the product page is a separate link


def test_row_without_a_doc_link_stays_none() -> None:
    cands = UmsAdapter()._parse_html(
        (_FIXTURES / "ums_amplifier_hpa.html").read_text(encoding="utf-8")
    )
    cand = next(c for c in cands if c.model == "CHA8200-99F")
    assert cand.datasheet_url is None

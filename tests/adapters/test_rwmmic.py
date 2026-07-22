"""Offline unit tests for the RWM (rwmmic.com) adapter.

All tests use a local JSON fixture trimmed from the live ``api/all-products``
response — no network access required.  The ``test_search_live`` test is marked
``@pytest.mark.network`` and is skipped in the default ``-m "not network"`` run.

Facts exercised (see the adapter docstring):
  * amplifier categories are selected by the "Amplifier" name substring, so the
    PIN-Switch group in the fixture is excluded;
  * fields are mapped by NAME, so LNA "Gain (dB)"/"Voltage (V)" and GaN-PA
    "Small Signal Gain (dB)"/"Vd (V)" both reach canonical Gain/VDD.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.rwmmic import RwmmicAdapter
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rwmmic_products.json"


def _load_candidates() -> list[Candidate]:
    return RwmmicAdapter()._parse_json(FIXTURE.read_text(encoding="utf-8"))


def _by_model(model: str) -> Candidate:
    return next(c for c in _load_candidates() if c.model == model)


# ---------------------------------------------------------------------------
# Category selection
# ---------------------------------------------------------------------------

def test_only_amplifier_categories_returned():
    """The fixture's PIN-Switch group must be excluded; only the 4 amps remain."""
    cands = _load_candidates()
    assert len(cands) == 4
    assert {c.model for c in cands} == {"RWLA1001", "RWLA1002", "RW5001", "RW5002"}
    assert not any(c.model.startswith("RWSWP") for c in cands)


def test_manufacturer_and_source():
    c = _load_candidates()[0]
    assert c.manufacturer == "RWM"
    assert c.source == "table"


# ---------------------------------------------------------------------------
# LNA row — "Gain (dB)" / "Voltage (V)"
# ---------------------------------------------------------------------------

def test_lna_scalar_and_freq_mapping():
    c = _by_model("RWLA1001")
    assert c.raw_params["freq_range"] == RawValue(value=(0.01, 3.5), unit="GHz")
    assert c.raw_params["Gain"] == RawValue(value=30.5, unit="dB")
    assert c.raw_params["NF"] == RawValue(value=0.6, unit="dB")
    assert c.raw_params["P1dB"] == RawValue(value=18.0, unit="dBm")
    assert c.raw_params["VDD"] == RawValue(value=(5.0, 5.0), unit="V")


def test_ip3_absent_rwmmic_does_not_publish_it():
    assert "IP3" not in _by_model("RWLA1001").raw_params


# ---------------------------------------------------------------------------
# GaN PA row — "Small Signal Gain (dB)" -> Gain, "Vd (V)" -> VDD, Psat
# ---------------------------------------------------------------------------

def test_pa_gain_unknown_small_signal_gain_not_treated_as_gain():
    """GaN PA has only 'Small Signal Gain (dB)' / 'Power Gain (dB)', no exact
    'Gain (dB)' — so canonical Gain must be UNKNOWN (absent)."""
    assert "Gain" not in _by_model("RW5001").raw_params


def test_pa_vd_maps_to_vdd_and_psat_present():
    c = _by_model("RW5001")
    assert c.raw_params["VDD"] == RawValue(value=(28.0, 28.0), unit="V")
    assert c.raw_params["Psat"] == RawValue(value=44.5, unit="dBm")
    assert c.raw_params["freq_range"] == RawValue(value=(0.8, 2.0), unit="GHz")


def test_gain_matched_by_exact_label_only():
    """Only a field literally labelled 'Gain (dB)' sets Gain; look-alikes do not."""
    ad = RwmmicAdapter()
    exact = ad._parse_json(
        '{"data":[{"category":{"id":73,"name":"Low Noise Amplifiers (packaged)"},'
        '"products":[{"name":"A","field_values":[{"field_name":"Gain (dB)","value":"20"}]}]}]}'
    )
    assert exact[0].raw_params["Gain"] == RawValue(value=20.0, unit="dB")
    lookalikes = ad._parse_json(
        '{"data":[{"category":{"id":76,"name":"GaN Power Amplifiers (bare die)"},'
        '"products":[{"name":"B","field_values":['
        '{"field_name":"Small Signal Gain (dB)","value":"29.5"},'
        '{"field_name":"Power Gain (dB)","value":"19.5"}]}]}]}'
    )
    assert "Gain" not in lookalikes[0].raw_params


def test_pa_unmapped_fields_are_skipped():
    """PAE ('55%') is not an ontology param -> absent, no crash."""
    assert "PAE" not in _by_model("RW5001").raw_params


# ---------------------------------------------------------------------------
# URL + robustness
# ---------------------------------------------------------------------------

def test_dc_coupled_low_edge_parsed_as_zero():
    """A DC-coupled part (Freq Low 'DC') keeps freq_range with a 0.0 GHz low edge."""
    from rf_finder.adapters.rwmmic import _parse_float
    assert _parse_float("DC") == 0.0
    cands = RwmmicAdapter()._parse_json(
        '{"data":[{"category":{"id":70,"name":"Distributed Amplifiers"},'
        '"products":[{"name":"RWDC1","field_values":['
        '{"field_name":"Freq Low (GHz)","value":"DC"},'
        '{"field_name":"Freq High (GHz)","value":"40"}]}]}]}'
    )
    assert cands[0].raw_params["freq_range"] == RawValue(value=(0.0, 40.0), unit="GHz")


def test_lone_multi_value_field_expands_to_points():
    """Even when only ONE field is multi-valued, it expands into per-point rows."""
    cands = RwmmicAdapter()._parse_json(
        '{"data":[{"category":{"id":73,"name":"Low Noise Amplifiers (packaged)"},'
        '"products":[{"name":"RWX","field_values":['
        '{"field_name":"Gain (dB)","value":"27/25"}]}]}]}'
    )
    assert [c.model for c in cands] == ["RWX (op 1/2)", "RWX (op 2/2)"]
    assert [c.raw_params["Gain"].value for c in cands] == [27.0, 25.0]


def test_mismatched_value_counts_fall_back_safely():
    """If fields disagree on count (2 vs 3), don't guess: one row, multi-fields UNKNOWN."""
    cands = RwmmicAdapter()._parse_json(
        '{"data":[{"category":{"id":73,"name":"Low Noise Amplifiers (packaged)"},'
        '"products":[{"name":"RWBAD","field_values":['
        '{"field_name":"Gain (dB)","value":"27/25"},'
        '{"field_name":"P1dB (dBm)","value":"10/11/12"},'
        '{"field_name":"NF (dB)","value":"1.5"}]}]}]}'
    )
    assert len(cands) == 1
    assert cands[0].model == "RWBAD"          # not expanded
    assert cands[0].raw_params["NF"].value == 1.5   # single value still kept
    assert "Gain" not in cands[0].raw_params        # ambiguous multi -> UNKNOWN
    assert "P1dB" not in cands[0].raw_params


def test_url_is_catalogue_page_text_fragment():
    # rwmmic has no per-part page, so the link points at the shared catalogue
    # page with a Scroll-to-Text-Fragment directive that highlights this part.
    c = _by_model("RWLA1001")
    assert c.url == "https://www.rwmmic.com/product.html#:~:text=RWLA1001"


def test_bad_json_raises_adaptererror():
    with pytest.raises(AdapterError):
        RwmmicAdapter()._parse_json("not valid json {{")


def test_missing_data_array_raises_adaptererror():
    with pytest.raises(AdapterError):
        RwmmicAdapter()._parse_json('{"success": true}')


# ---------------------------------------------------------------------------
# Coupled multi-value operating points (one Candidate per point)
# ---------------------------------------------------------------------------

# RW3010: two coupled bias points (Vd 5 V / 6 V).
_RW3010 = (
    '{"data":[{"category":{"id":102,"name":"Power Amplifiers (bare die)"},'
    '"products":[{"name":"RW3010","field_values":['
    '{"field_name":"Freq Low (GHz)","value":"8"},'
    '{"field_name":"Freq High (GHz)","value":"12"},'
    '{"field_name":"Gain (dB)","value":"24/23.5"},'
    '{"field_name":"P1dB (dBm)","value":"27/29"},'
    '{"field_name":"Psat (dBm)","value":"28.5/29.5"},'
    '{"field_name":"Voltage (V)","value":"5/6"}]}]}]}'
)

# RWDA1013: three points; "DC" freq low + single NF are shared across all.
_RWDA1013 = (
    '{"data":[{"category":{"id":70,"name":"Distributed Amplifiers"},'
    '"products":[{"name":"RWDA1013","field_values":['
    '{"field_name":"Freq Low (GHz)","value":"DC"},'
    '{"field_name":"Freq High (GHz)","value":"40"},'
    '{"field_name":"Gain (dB)","value":"15/13.5/14.5"},'
    '{"field_name":"NF (dB)","value":"2.5"},'
    '{"field_name":"P1dB (dBm)","value":"14/13/16"},'
    '{"field_name":"Psat (dBm)","value":"17/17/18"},'
    '{"field_name":"Voltage (V)","value":"5/5/8"}]}]}]}'
)


def test_two_operating_points_are_coupled():
    """RW3010 -> two self-consistent candidates; values never cross conditions."""
    cands = RwmmicAdapter()._parse_json(_RW3010)
    assert len(cands) == 2
    a, b = cands
    assert a.model == "RW3010 (op 1/2)"
    assert b.model == "RW3010 (op 2/2)"
    # Point 1 = Vd 5 V:  Gain 24, P1dB 27, Psat 28.5
    assert a.raw_params["VDD"].value == (5.0, 5.0)
    assert a.raw_params["Gain"].value == 24.0
    assert a.raw_params["P1dB"].value == 27.0
    assert a.raw_params["Psat"].value == 28.5
    # Point 2 = Vd 6 V:  Gain 23.5, P1dB 29, Psat 29.5
    assert b.raw_params["VDD"].value == (6.0, 6.0)
    assert b.raw_params["Gain"].value == 23.5
    assert b.raw_params["P1dB"].value == 29.0
    assert b.raw_params["Psat"].value == 29.5
    # Both share the single-valued frequency band.
    assert a.raw_params["freq_range"].value == (8.0, 12.0)
    assert b.raw_params["freq_range"].value == (8.0, 12.0)
    # The forbidden mix (Gain 24 with P1dB 29) exists in no single candidate.
    assert not any(
        c.raw_params["Gain"].value == 24.0 and c.raw_params["P1dB"].value == 29.0
        for c in cands
    )


def test_three_operating_points_with_shared_singles():
    """RWDA1013 -> three candidates; DC freq low (0.0) and NF 2.5 shared."""
    cands = RwmmicAdapter()._parse_json(_RWDA1013)
    assert len(cands) == 3
    assert [c.model for c in cands] == [
        "RWDA1013 (op 1/3)",
        "RWDA1013 (op 2/3)",
        "RWDA1013 (op 3/3)",
    ]
    # Shared single values on every point.
    assert all(c.raw_params["freq_range"].value == (0.0, 40.0) for c in cands)
    assert all(c.raw_params["NF"].value == 2.5 for c in cands)
    # Per-point coupled values, aligned by position.
    assert [c.raw_params["Gain"].value for c in cands] == [15.0, 13.5, 14.5]
    assert [c.raw_params["P1dB"].value for c in cands] == [14.0, 13.0, 16.0]
    assert [c.raw_params["Psat"].value for c in cands] == [17.0, 17.0, 18.0]
    assert [c.raw_params["VDD"].value for c in cands] == [(5.0, 5.0), (5.0, 5.0), (8.0, 8.0)]


def test_single_value_product_still_one_candidate():
    """A part with no "/" values yields exactly one candidate with its plain PN."""
    cands = _load_candidates()
    lnas = [c for c in cands if c.model == "RWLA1001"]
    assert len(lnas) == 1  # unchanged label, single operating point


# ---------------------------------------------------------------------------
# Integration test (network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_live():
    """Live search against the rwmmic.com JSON API (requires network)."""
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
    results = RwmmicAdapter().search(spec)
    assert len(results) > 300  # ~371 amplifiers in the catalogue
    assert all(c.manufacturer == "RWM" for c in results)

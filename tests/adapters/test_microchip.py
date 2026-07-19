"""Offline unit tests for the Microchip adapter (microchip-plan.md §5–§7).

All tests drive ``_build_candidate`` / helpers against a local JSON fixture — no
network.  The ``test_search_live`` test is marked ``@pytest.mark.network`` and is
skipped in the default ``-m "not network"`` run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rf_finder.adapters.base import ADAPTERS, AdapterError
from rf_finder.adapters.microchip import (
    MicrochipAdapter,
    _is_amplifier,
    _parse_bias_volts,
    _parse_freq,
    _parse_size_mm,
    _sse_json,
)
from rf_finder.models import Candidate, RawValue

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "microchip_amplifiers.json"
_RECORDS = {r["product"]["partNumber"]: r for r in json.loads(_FIXTURE.read_text("utf-8"))}


def _build(part: str) -> Candidate | None:
    r = _RECORDS[part]
    return MicrochipAdapter()._build_candidate(part, r["product"], r["physical"], r["feed"])


# ---------------------------------------------------------------------------
# Candidate construction — real captures
# ---------------------------------------------------------------------------

def test_lna_maps_all_present_params():
    """MMA044AA: Bias string -> VDD, OIP3 -> IP3, p1db(dBM) -> P1dB, no NF."""
    c = _build("MMA044AA")
    assert c.manufacturer == "Microchip"
    assert c.source == "table"
    assert c.url == "https://www.microchipdirect.com/product/MMA044AA"
    assert c.raw_params["freq_range"] == RawValue((6.0, 18.0), "GHz")
    assert c.raw_params["Gain"] == RawValue(21.0, "dB")
    assert c.raw_params["IP3"] == RawValue(30.0, "dBm")
    assert c.raw_params["P1dB"] == RawValue(16.0, "dBm")
    assert c.raw_params["VDD"] == RawValue(4.0, "V")
    assert c.raw_params["Size"] == RawValue(1.351, "mm")  # largest package edge
    assert "NF" not in c.raw_params
    assert "Psat" not in c.raw_params
    assert "MSL" not in c.raw_params  # msl was null


def test_datasheet_url_from_mcp_no_extra_request():
    """Case 1: the MCP payload carries ``datasheetUrl`` -> Candidate.datasheet_url.

    ``_build_candidate`` is pure (dicts in, Candidate out) — it makes NO request,
    so the link rides along with the other params from the same MCP data.
    """
    c = _build("MMA044AA")
    assert c.datasheet_url == (
        "https://ww1.microchip.com/downloads/aemDocuments/documents/RFDS/"
        "ProductDocuments/DataSheets/"
        "MMA044AA-5-GHz-20-GHz+GaAs-pHEMT-MMIC-Wideband-LNA-DS00004231B.pdf"
    )


def test_datasheet_url_absent_stays_none():
    """A part whose MCP payload has no ``datasheetUrl`` -> datasheet_url is None."""
    c = _build("SYNTH-PA1")
    assert c.datasheet_url is None


def test_dc_freq_edge_becomes_zero():
    """MMA015AA: Freq Min = 'DC' -> 0.0 GHz; NF present here."""
    c = _build("MMA015AA")
    assert c.raw_params["freq_range"] == RawValue((0.0, 14.0), "GHz")
    assert c.raw_params["NF"] == RawValue(2.6, "dB")
    assert c.raw_params["VDD"] == RawValue(4.0, "V")  # "4V, 80mA" (space)
    assert c.raw_params["Size"] == RawValue(0.76, "mm")


def test_power_amp_misspelled_type_still_accepted():
    """MMA052AA product_type 'Distributed Power-Amplifer (Driver)' matches 'amplif'."""
    c = _build("MMA052AA")
    assert c is not None
    assert c.raw_params["freq_range"] == RawValue((0.0, 26.0), "GHz")
    assert c.raw_params["VDD"] == RawValue(10.0, "V")
    assert c.raw_params["IP3"] == RawValue(35.0, "dBm")
    assert c.raw_params["P1dB"] == RawValue(27.0, "dBm")


def test_pout_and_voltage_schema():
    """SYNTH-PA1: Pout (dBm) -> Psat; Voltage (V) -> VDD (no Bias); MSL parsed."""
    c = _build("SYNTH-PA1")
    assert c.raw_params["Psat"] == RawValue(40.0, "dBm")
    assert c.raw_params["VDD"] == RawValue(28.0, "V")
    assert c.raw_params["MSL"] == RawValue(3.0, "")
    assert c.raw_params["Size"] == RawValue(5.0, "mm")
    assert "NF" not in c.raw_params
    assert "IP3" not in c.raw_params


# ---------------------------------------------------------------------------
# product_type gate (drops text-search pollution)
# ---------------------------------------------------------------------------

def test_opamp_feed_without_product_type_is_rejected():
    assert _build("MCP664") is None


def test_non_amplifier_product_type_is_rejected():
    assert _build("MASW-EXAMPLE") is None  # "SP4T Switch"


def test_is_amplifier_markers():
    assert _is_amplifier({"product_type": "Low Noise Amplifier"})
    assert _is_amplifier({"product_type": "Distributed Power-Amplifer (Driver)"})
    assert not _is_amplifier({"product_type": "SP4T Switch"})
    assert not _is_amplifier({"Aol (dB)": "120"})  # no product_type key


# ---------------------------------------------------------------------------
# Helper parsers
# ---------------------------------------------------------------------------

def test_parse_freq_dc():
    assert _parse_freq("DC") == 0.0
    assert _parse_freq("0.0001") == 0.0001
    assert _parse_freq("") is None


def test_parse_bias_volts():
    assert _parse_bias_volts("4V,102mA") == 4.0
    assert _parse_bias_volts("11V, 410 mA") == 11.0
    assert _parse_bias_volts("410 mA") is None


def test_parse_size_mm_takes_largest_edge():
    assert _parse_size_mm("1.351 x 1.121 x 0.1 mm") == 1.351
    assert _parse_size_mm("5x5x1mm") == 5.0
    assert _parse_size_mm(None) is None
    assert _parse_size_mm("N/A") is None          # no numeric tokens
    assert _parse_size_mm("1.2.3 x 4 mm") == 4.0  # malformed token skipped, not raised


def test_sse_json_extracts_data_line():
    payload = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'
    assert _sse_json(payload)["result"]["ok"] is True


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_adapter_self_registers():
    assert "Microchip" in ADAPTERS
    assert isinstance(ADAPTERS["Microchip"], MicrochipAdapter)


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
                range=(6.0, 12.0),
                unit="GHz",
            ),
        ],
    )
    results = MicrochipAdapter().search(spec)
    assert len(results) > 20  # low hundreds enumerated; tens are RF amplifiers
    assert all(c.manufacturer == "Microchip" for c in results)
    assert all("freq_range" in c.raw_params for c in results)

"""Tests for AmcomUSA table parsing — column→canonical mapping (REQ-3.4, REQ-3.7).

Focus: the SCALAR_COLUMN_MAP, including the supply-voltage column that is
published as either ``Vd (V)`` (LNA / GaN) or ``Bias (V)`` (Driver / SSPA) and
maps to canonical ``VDD``.
"""

from rf_finder.adapters.amcomusa import AmcomUSAAdapter


_CATEGORY = {"name": "Low Noise Amplifiers", "slug": "low-noise-amplifier-modules"}


def _table(header_cells: str, data_cells: str) -> str:
    return (
        '<table id="allPnTable"><thead><tr>'
        f"{header_cells}"
        "</tr></thead><tbody><tr>"
        f"{data_cells}"
        "</tr></tbody></table>"
    )


def _parse_one(header_cells: str, data_cells: str):
    cands = AmcomUSAAdapter()._parse_table_html(
        _table(header_cells, data_cells), _CATEGORY
    )
    assert len(cands) == 1
    return cands[0]


class TestVddMapping:
    def test_vd_column_maps_to_vdd(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th>"
            "<th>Gain (dB)</th><th>Vd (V)</th>",
            '<td name="product"><a href="/product-details/x">X</a></td>'
            "<td>2</td><td>6</td><td>20</td><td>5</td>",
        )
        assert cand.raw_params["VDD"].value == 5.0
        assert cand.raw_params["VDD"].unit == "V"

    def test_bias_column_maps_to_vdd(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th><th>Bias (V)</th>",
            '<td name="product"><a href="/product-details/y">Y</a></td>'
            "<td>2</td><td>6</td><td>8</td>",
        )
        assert cand.raw_params["VDD"].value == 8.0
        assert cand.raw_params["VDD"].unit == "V"

    def test_signed_single_supply_parses(self):
        cand = _parse_one(
            "<th>Product</th><th>Vd (V)</th>",
            '<td name="product"><a href="/product-details/z">Z</a></td><td>+5</td>',
        )
        assert cand.raw_params["VDD"].value == 5.0

    def test_dual_supply_string_is_unknown(self):
        # "+8 / -0.75" is not a single float -> VDD stays absent (UNKNOWN), correct.
        cand = _parse_one(
            "<th>Product</th><th>Vd (V)</th>",
            '<td name="product"><a href="/product-details/d">D</a></td>'
            "<td>+8 / -0.75</td>",
        )
        assert "VDD" not in cand.raw_params

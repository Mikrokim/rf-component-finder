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


class TestTableMapping:
    def test_maps_scalar_and_frequency_columns(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th>"
            "<th>Gain (dB)</th><th>P1dB (dBm)</th>",
            '<td name="product"><a href="/product-details/x">X</a></td>'
            "<td>2</td><td>6</td><td>20</td><td>25</td>",
        )
        assert cand.model == "X"
        assert cand.raw_params["freq_range"].value == (2.0, 6.0)
        assert cand.raw_params["Gain"].value == 20.0
        assert cand.raw_params["P1dB"].value == 25.0

    def test_missing_cell_is_skipped(self):
        cand = _parse_one(
            "<th>Product</th><th>NF (dB)</th>",
            '<td name="product"><a href="/product-details/y">Y</a></td><td>-</td>',
        )
        assert "NF" not in cand.raw_params


class TestVddMapping:
    def test_vd_column_maps_to_vdd(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th>"
            "<th>Gain (dB)</th><th>Vd (V)</th>",
            '<td name="product"><a href="/product-details/x">X</a></td>'
            "<td>2</td><td>6</td><td>20</td><td>5</td>",
        )
        assert cand.raw_params["VDD"].value == (5.0, 5.0)
        assert cand.raw_params["VDD"].unit == "V"

    def test_bias_column_maps_to_vdd(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th><th>Bias (V)</th>",
            '<td name="product"><a href="/product-details/y">Y</a></td>'
            "<td>2</td><td>6</td><td>8</td>",
        )
        assert cand.raw_params["VDD"].value == (8.0, 8.0)
        assert cand.raw_params["VDD"].unit == "V"

    def test_dual_supply_string_is_unknown(self):
        # "+8 / -0.75" is not a single float -> VDD stays absent (UNKNOWN), correct.
        cand = _parse_one(
            "<th>Product</th><th>Vd (V)</th>",
            '<td name="product"><a href="/product-details/d">D</a></td>'
            "<td>+8 / -0.75</td>",
        )
        assert "VDD" not in cand.raw_params


_PDF_HREF = (
    "http://d2f6h2rm95zg9t.cloudfront.net/86467119/"
    "AM001019SF_1H_Sept_2025_78916787.pdf"
)


class TestDatasheetLink:
    """The datasheet PDF link (case 1) lives in the row's trailing empty-header cell."""

    def test_reads_the_absolute_pdf_from_the_trailing_cell(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th><th></th>",
            '<td name="product"><a href="/product-details/x">X</a></td>'
            "<td>2</td><td>6</td>"
            f"<td class='pn-pdf'><center><a data-name='datasheet' "
            f"href='{_PDF_HREF}' target='_blank'><i class='fa'></i></a></center></td>",
        )
        assert cand.datasheet_url == _PDF_HREF
        # It must not leak into the product URL, which stays the product page.
        assert cand.url.endswith("/product-details/x")

    def test_row_without_a_pdf_anchor_has_no_datasheet_url(self):
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th><th></th>",
            '<td name="product"><a href="/product-details/y">Y</a></td>'
            "<td>2</td><td>6</td><td class='pn-pdf'></td>",
        )
        assert cand.datasheet_url is None

    def test_ignores_a_non_pdf_anchor(self):
        """Only a .pdf href counts — a product/detail link in the row is not a datasheet."""
        cand = _parse_one(
            "<th>Product</th><th>Fmin (GHz)</th><th>Fmax (GHz)</th><th></th>",
            '<td name="product"><a href="/product-details/z">Z</a></td>'
            "<td>2</td><td>6</td>"
            "<td><a href='/rfq/z'>Request quote</a></td>",
        )
        assert cand.datasheet_url is None

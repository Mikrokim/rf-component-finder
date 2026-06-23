"""Tests for rf_finder/ontology/units.py — T3 Units conversion (REQ-2.5)."""

import math

import pytest

from rf_finder.ontology.units import to_canonical


# ---------------------------------------------------------------------------
# Frequency → GHz
# ---------------------------------------------------------------------------

class TestFrequencyToGHz:
    """Conversion table: Hz / kHz / MHz / GHz → GHz."""

    def test_ghz_identity(self):
        assert to_canonical(6.0, "GHz", "GHz") == pytest.approx(6.0)

    def test_mhz_to_ghz(self):
        # spec-specified example: 6000 MHz → 6.0 GHz
        assert to_canonical(6000.0, "MHz", "GHz") == pytest.approx(6.0)

    def test_mhz_to_ghz_partial(self):
        assert to_canonical(500.0, "MHz", "GHz") == pytest.approx(0.5)

    def test_khz_to_ghz(self):
        assert to_canonical(1_000_000.0, "kHz", "GHz") == pytest.approx(1.0)

    def test_hz_to_ghz(self):
        assert to_canonical(1_000_000_000.0, "Hz", "GHz") == pytest.approx(1.0)

    def test_zero_frequency(self):
        assert to_canonical(0.0, "MHz", "GHz") == pytest.approx(0.0)

    def test_fractional_mhz(self):
        assert to_canonical(2400.5, "MHz", "GHz") == pytest.approx(2.4005)

    def test_unknown_freq_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown frequency unit"):
            to_canonical(1.0, "THz", "GHz")


# ---------------------------------------------------------------------------
# Power → dBm
# ---------------------------------------------------------------------------

class TestPowerToDBm:
    """Conversion table: W / mW / dBm → dBm."""

    def test_dbm_identity(self):
        assert to_canonical(26.0, "dBm", "dBm") == pytest.approx(26.0)

    def test_dbm_identity_negative(self):
        assert to_canonical(-10.0, "dBm", "dBm") == pytest.approx(-10.0)

    def test_mw_to_dbm(self):
        # 1 mW → 0 dBm
        assert to_canonical(1.0, "mW", "dBm") == pytest.approx(0.0)

    def test_mw_to_dbm_1000(self):
        # 1000 mW → 30 dBm
        assert to_canonical(1000.0, "mW", "dBm") == pytest.approx(30.0)

    def test_w_to_dbm(self):
        # 1 W = 1000 mW → 30 dBm
        assert to_canonical(1.0, "W", "dBm") == pytest.approx(30.0)

    def test_w_to_dbm_small(self):
        # 0.001 W = 1 mW → 0 dBm
        assert to_canonical(0.001, "W", "dBm") == pytest.approx(0.0)

    def test_mw_dbm_round_trip(self):
        """dBm/mW round-trip: spec-required example."""
        dbm_in = 23.0
        mw = 10 ** (dbm_in / 10.0)          # dBm → mW manually
        dbm_out = to_canonical(mw, "mW", "dBm")
        assert dbm_out == pytest.approx(dbm_in, rel=1e-6)

    def test_zero_mw_raises(self):
        with pytest.raises(ValueError, match="non-positive"):
            to_canonical(0.0, "mW", "dBm")

    def test_negative_mw_raises(self):
        with pytest.raises(ValueError, match="non-positive"):
            to_canonical(-1.0, "mW", "dBm")

    def test_zero_w_raises(self):
        with pytest.raises(ValueError, match="non-positive"):
            to_canonical(0.0, "W", "dBm")

    def test_unknown_power_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown power unit"):
            to_canonical(1.0, "uW", "dBm")


# ---------------------------------------------------------------------------
# Ratio → dB
# ---------------------------------------------------------------------------

class TestRatioToDB:
    """dB is a dimensionless ratio (gain, NF); dB → dB is the identity."""

    def test_db_identity(self):
        # e.g. a gain of 18 dB stays 18 dB
        assert to_canonical(18.0, "dB", "dB") == pytest.approx(18.0)

    def test_db_identity_negative(self):
        # gain/NF may be negative; must not be rejected
        assert to_canonical(-3.5, "dB", "dB") == pytest.approx(-3.5)

    def test_db_identity_zero(self):
        assert to_canonical(0.0, "dB", "dB") == pytest.approx(0.0)

    def test_non_db_source_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown ratio unit"):
            to_canonical(10.0, "dBm", "dB")


# ---------------------------------------------------------------------------
# Unsupported canonical unit
# ---------------------------------------------------------------------------

class TestUnsupportedCanonical:
    def test_unknown_canonical_raises(self):
        with pytest.raises(ValueError, match="Unsupported canonical unit"):
            to_canonical(1.0, "MHz", "Hz")

    def test_dbw_canonical_raises(self):
        with pytest.raises(ValueError, match="Unsupported canonical unit"):
            to_canonical(1.0, "W", "dBW")

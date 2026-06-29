"""Analog Devices RF amplifier adapter (REQ-3.1, design.md §6.1–6.2, T8).

Fetch strategy: single HTTP GET to /cdp/pst2/data/standard/3003.js. The endpoint
returns the full RF Amplifiers dataset; no server-side filtering is applied.
This adapter returns all rows and lets the Verifier apply constraints.

Field-id -> ontology mapping confirmed from ADI view metadata:
    0    Part#                       -> model
    279  Frequency Response min (Hz) -> freq_range low
    278  Frequency Response max (Hz) -> freq_range high
    2930 OP1dB typ (dBm)             -> P1dB
    2922 OIP3 typ (dBm)              -> IP3
    2913 Gain typ (dB)               -> Gain
    2921 Noise Figure typ (dB)       -> NF
    4709 Saturated Output Power (dBm)-> Psat
"""

from __future__ import annotations

import json
import time

import httpx

from rf_finder.adapters.base import (
    Adapter,
    AdapterError,
    drop_paramless,
    freq_range_from_bandwidth,
    register,
)
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CAT_ID = 3003
_DATA_URL = f"https://www.analog.com/cdp/pst2/data/standard/{_CAT_ID}.js"
_PRODUCT_URL = "https://www.analog.com/en/products/{model}.html"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "NA"})

_MIN_DELAY_SECONDS = 5.0

# ADI field-id holding a single -3 dB Bandwidth (Hz). Wideband / differential
# amplifiers (e.g. AD8131, ADA49xx) carry this instead of a 279/278 frequency
# band. Used only as a fallback: for true RF parts 1519 merely mirrors the upper
# freq edge, so 279/278 take precedence when present.
_BANDWIDTH_FID = "1519"

# ---------------------------------------------------------------------------
# Field-id -> (canonical_name, unit)
# ---------------------------------------------------------------------------

FIELD_MAP: dict[str, tuple[str, str | None]] = {
    "0":    ("model",     None),
    "279":  ("freq_low",  "Hz"),
    "278":  ("freq_high", "Hz"),
    "2930": ("P1dB",      "dBm"),
    "2922": ("IP3",       "dBm"),
    "2913": ("Gain",      "dB"),
    "2921": ("NF",        "dB"),
    "4709": ("Psat",      "dBm"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell_value(row: dict, fid: str) -> str | None:
    """Return the raw string stored at row[fid]["value"][0], or None."""
    cell = row.get(fid)
    if not isinstance(cell, dict):
        return None
    vals = cell.get("value")
    if not isinstance(vals, list) or not vals:
        return None
    first = vals[0]
    if isinstance(first, str):
        return first.strip() or None
    return str(first)


def _parse_float(raw: str | None) -> float | None:
    """Return None for missing/sentinel values; otherwise parse to float."""
    if raw is None:
        return None
    text = raw.strip()
    if not text or text in _MISSING_SENTINELS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register
class AnalogDevicesAdapter(Adapter):
    """Fetches Analog Devices RF Amplifiers (catId 3003) parametric JSON."""

    manufacturer = "Analog Devices"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the full RF-amplifier dataset and return all rows as Candidates."""
        elapsed = time.time() - self._last_fetch_time
        if self._last_fetch_time and elapsed < _MIN_DELAY_SECONDS:
            time.sleep(_MIN_DELAY_SECONDS - elapsed)

        try:
            response = httpx.get(
                _DATA_URL,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": (
                        "application/javascript,application/json,text/javascript,"
                        "*/*;q=0.1"
                    ),
                    "Accept-Language": "en-US,en;q=0.5",
                },
                follow_redirects=True,
                timeout=30.0,
            )
            response.raise_for_status()
            self._last_fetch_time = time.time()
        except httpx.HTTPError as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"HTTP error fetching {_DATA_URL}",
                cause=exc,
            ) from exc

        return drop_paramless(self._parse_json(response.text))

    def _parse_json(self, text: str) -> list[Candidate]:
        """Parse the parametric JSON body into Candidates."""
        try:
            doc = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="response body is not valid JSON",
                cause=exc,
            ) from exc

        rows = doc.get("data")
        if not isinstance(rows, list):
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="parametric JSON has no 'data' array",
            )

        candidates: list[Candidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            model = _cell_value(row, "0")
            if not model:
                continue

            raw_params: dict[str, RawValue] = {}

            f_low = _parse_float(_cell_value(row, "279"))
            f_high = _parse_float(_cell_value(row, "278"))
            if f_low is not None and f_high is not None:
                raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="Hz")
            else:
                # No frequency-response band: fall back to a -3 dB Bandwidth
                # (wideband / differential parts) and convert it to a range.
                bw = _parse_float(_cell_value(row, _BANDWIDTH_FID))
                if bw is not None:
                    raw_params["freq_range"] = freq_range_from_bandwidth(bw)

            for fid, (canonical, unit) in FIELD_MAP.items():
                if canonical in ("model", "freq_low", "freq_high"):
                    continue
                value = _parse_float(_cell_value(row, fid))
                if value is not None:
                    raw_params[canonical] = RawValue(value=value, unit=unit)  # type: ignore[arg-type]

            candidates.append(
                Candidate(
                    model=str(model),
                    manufacturer=self.manufacturer,
                    url=_PRODUCT_URL.format(model=str(model).lower()),
                    raw_params=raw_params,
                    source="table",
                )
            )

        return candidates

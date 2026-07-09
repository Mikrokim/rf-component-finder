"""VectraWave MMIC amplifier adapter (REQ-3.1, design.md §6.1–6.2, T8).

Fetch strategy: single HTTP GET to /search-engine-mmic. The page is
server-rendered (Divi "Table Maker" plugin): each product section is a
``div.dvmd_table_maker`` module holding a **transposed** table — products are
columns, parameters are rows (``dvmd_tm_trow`` / ``dvmd_tm_tcell`` /
``dvmd_tm_cdata``). Data is in the raw HTML; a JS lib only styles it, so
``httpx`` + ``selectolax`` suffice. No API, no per-product fetches.

Only amplifier sections are parsed (High/Medium Power, Low Noise, Wideband);
attenuators, phase shifters, and Core Chips are skipped. Per-section column
labels are mapped to the ontology by row label.

Parameters not on the page (Temperature, Size) and ones VectraWave never
publishes (IP3, MSL) are left to the datasheet fallback / stay UNKNOWN. See
specs/.../adapters/vectrawave/t8-plan.md.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from rf_finder import http
from rf_finder.adapters.base import Adapter, AdapterError, drop_paramless, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = "https://vectrawave.com"
_PAGE_URL = _BASE + "/search-engine-mmic"

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "NA", "TBD", "tbd"})

# A section heading is one of the catalogue's component categories.
_SECTION_KEYWORDS = ("amplifier", "attenuator", "phase shifter", "core chip")
# Only these sections are amplifiers we map (Core Chips deferred — VW-OQ-2).
_AMP_SECTION_KEYWORDS = (
    "high power amplifier",
    "medium power amplifier",
    "low noise amplifier",
    "wideband amplifier",
)

# Normalised row label -> (canonical_name, unit). "freq_low"/"freq_high" and
# "VDD" are special-cased in the parse loop (combined into ranges); all others
# are scalars. The "datasheet" row is special-cased (href). Labels not in this
# map are ignored — including "controlvoltage v" (a phase-shifter control, NOT
# supply), "technology", "pae %", "status", "idd", etc.
ROW_MAP: dict[str, tuple[str, str]] = {
    "frequencymin ghz": ("freq_low",  "GHz"),
    "frequencymax ghz": ("freq_high", "GHz"),
    "gain db":          ("Gain",      "dB"),
    "op1db dbm":        ("P1dB",      "dBm"),
    "psat dbm":         ("Psat",      "dBm"),
    "pout dbm":         ("Psat",      "dBm"),   # Pout = rated/saturated output power == Psat
    "nf db":            ("NF",        "dB"),
    "voltage v":        ("VDD",       "V"),     # supply voltage
    "drainvoltage v":   ("VDD",       "V"),     # same supply, different section label
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    t = re.sub(r"[()/,.:\\]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _num(text: str) -> float | None:
    """Return None for missing/sentinel; else the first numeric value.

    Handles VectraWave's messier cells: ``"DC"`` (a DC-coupled lower band edge)
    -> 0.0; leading-sign supply values like ``"+8"``; and a malformed trailing
    dot (``"24.0."``) or trailing unit is tolerated by extracting the first
    numeric token rather than a strict ``float()`` parse.
    """
    t = (text or "").strip()
    if not t or t in _MISSING_SENTINELS:
        return None
    if t.upper() == "DC":
        return 0.0
    m = _NUM_RE.search(t)
    return float(m.group()) if m else None


def _vdd(text: str) -> tuple[float, float] | None:
    """Supply voltage -> a ``(low, high)`` band, else None.

    A single value -> ``(v, v)``; a dual/multi-rail supply such as ``"+3/-3"``
    yields ``(min, max)`` of all listed values (``(-3.0, 3.0)``), which behaves
    correctly under the ontology's ``contains`` rule.
    """
    t = (text or "").strip()
    if not t or t in _MISSING_SENTINELS:
        return None
    nums = [float(x) for x in _NUM_RE.findall(t)]
    if not nums:
        return None
    return (min(nums), max(nums))


def _is_amplifier_section(heading: str) -> bool:
    h = heading.lower()
    return any(k in h for k in _AMP_SECTION_KEYWORDS)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register
class VectraWaveAdapter(Adapter):
    """Scrapes VectraWave /search-engine-mmic (transposed Divi tables)."""

    manufacturer = "VectraWave"
    supported_components = {"amplifier"}

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the MMIC page (cache-first) and return amplifier candidates.

        The shared provider owns the User-Agent, delay, timeout and retries (it
        covers the site's intermittent TLS/connect errors); a ``None`` body means
        unreachable with no cached copy → skip this source.
        """
        result = http.fetch(
            self.manufacturer,
            _PAGE_URL,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        if result.text is None:
            return []

        return drop_paramless(self._parse_html(result.text))

    def _parse_html(self, html: str) -> list[Candidate]:
        """Parse all amplifier-section tables; return combined Candidates.

        Raises AdapterError if no ``div.dvmd_table_maker`` modules are found.
        """
        tree = HTMLParser(html)
        modules = tree.css("div.dvmd_table_maker")
        if not modules:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="no dvmd_table_maker modules found in HTML",
            )

        # Section headings (component categories), in document order; aligned
        # by index with the modules.
        section_heads = [
            h.text(strip=True)
            for h in tree.css("h1,h2,h3,h4,h5")
            if any(k in h.text(strip=True).lower() for k in _SECTION_KEYWORDS)
        ]

        candidates: list[Candidate] = []
        for idx, module in enumerate(modules):
            heading = section_heads[idx] if idx < len(section_heads) else ""
            if not _is_amplifier_section(heading):
                continue  # skip attenuator / phase shifter / core chips
            candidates.extend(self._parse_module(module))
        return candidates

    def _parse_module(self, module) -> list[Candidate]:
        """Parse one transposed section table into Candidates."""
        rows = [
            (r.css("[class*=dvmd_tm_tcell]"))
            for r in module.css("[class*=dvmd_tm_trow]")
        ]
        row_texts = [[c.text(strip=True) for c in cells] for cells in rows]

        # Product-header row: first cell empty, remaining cells are part numbers.
        products: list[str] = []
        for texts in row_texts:
            if texts and not texts[0] and any(texts[1:]):
                products = texts
                break
        if not products:
            return []

        n_cols = len(products)
        raw_params: dict[int, dict[str, RawValue]] = {i: {} for i in range(1, n_cols)}
        urls: dict[int, str] = {i: "" for i in range(1, n_cols)}
        freq_low: dict[int, float] = {}
        freq_high: dict[int, float] = {}

        for cells, texts in zip(rows, row_texts):
            if not texts or not texts[0]:
                continue  # repeated product-header / spacer row
            key = _normalize(texts[0])

            # Datasheet row: each product cell holds an <a href> to its PDF.
            if key == "datasheet":
                for i in range(1, min(n_cols, len(cells))):
                    a = cells[i].css_first("a")
                    if a is not None:
                        urls[i] = self._abs_url(a.attributes.get("href", ""))
                continue

            mapped = ROW_MAP.get(key)
            if mapped is None:
                continue  # unmapped label (technology, pae, controlvoltage, ...)
            canonical, unit = mapped

            for i in range(1, min(n_cols, len(texts))):
                if canonical == "VDD":
                    vdd = _vdd(texts[i])
                    if vdd is not None:
                        raw_params[i]["VDD"] = RawValue(value=vdd, unit="V")
                    continue
                v = _num(texts[i])
                if v is None:
                    continue
                if canonical == "freq_low":
                    freq_low[i] = v
                elif canonical == "freq_high":
                    freq_high[i] = v
                else:
                    raw_params[i][canonical] = RawValue(value=v, unit=unit)

        out: list[Candidate] = []
        for i in range(1, n_cols):
            model = (products[i] or "").strip()
            if not model:
                continue
            rp = raw_params[i]
            if i in freq_low and i in freq_high:
                rp["freq_range"] = RawValue(value=(freq_low[i], freq_high[i]), unit="GHz")
            out.append(
                Candidate(
                    model=model,
                    manufacturer=self.manufacturer,
                    url=urls[i] or _PAGE_URL,
                    raw_params=rp,
                    source="table",
                )
            )
        return out

    @staticmethod
    def _abs_url(href: str) -> str:
        if not href:
            return ""
        if href.startswith("http"):
            return href
        return _BASE + "/" + href.lstrip("/")

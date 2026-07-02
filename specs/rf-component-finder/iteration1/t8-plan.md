# T8 Plan — Mini-Circuits Adapter

> **Task:** T8 from tasks.md — `adapters/minicircuits.py`
> **Phase:** Plan only (Phase A). No code written.
> **Date:** 2026-06-21
> **Investigator:** Phase A planning agent
> **Resolves open items:** I-1, I-2 (design.md §12)

---

## 1. Request Mechanism Finding (resolves I-1)

### Method used

Live `httpx.get` to `https://www.minicircuits.com/WebStore/Amplifiers.html` with a
browser-style User-Agent and Accept header. Response captured, parsed, and a
follow-up POST to the same URL with freq-filter form fields was also tested.

### Findings

| Question | Answer |
|----------|--------|
| Base URL | `https://www.minicircuits.com/WebStore/Amplifiers.html` |
| Method for initial load | **HTTP GET, no query parameters needed** |
| HTML rendering | **Fully server-side rendered** — all product rows are present in the initial GET response body |
| Response body size | ~3.75 MB |
| Table rows in initial GET | **781 rows** |
| AJAX / XHR for table data? | **No** — the one `.ajax` occurrence is a language-switch call unrelated to the table |
| Server-side freq filter? | **No** — POSTing `Amplifiers.freqLow=2000&Amplifiers.freqHigh=6000` returns the same 781 rows; the filter inputs exist but filtering is **client-side JavaScript only** |
| JavaScript required to see the table? | **No** — the table is in the raw HTML |

### Conclusion: httpx (not playwright)

Because the complete results table is present in the initial server-side-rendered
GET response, `httpx` is sufficient. `playwright` is not needed for this adapter.

The adapter will:
1. Send a single `httpx.get` to `https://www.minicircuits.com/WebStore/Amplifiers.html`
2. Parse the returned HTML for table rows
3. Apply no server-side frequency filter (it cannot — server ignores the filter)
4. Return **all** rows as `Candidate` objects; the Verifier applies the frequency
   (and all other scalar) constraints

> **Design note:** This deviates from the design.md §6.2 statement "The adapter
> passes the query's frequency band to the page's F Low / F High filters to narrow
> server-side where possible." That aspiration is not achievable — the server does
> not filter. The adapter must scrape the full table. This has no impact on
> correctness (the Verifier still filters correctly) but means the full 3.75 MB
> page is fetched every time; the cache (T10) mitigates this.

---

## 2. robots.txt Summary

URL: `https://www.minicircuits.com/robots.txt` (HTTP 200, fetched live)

```
User-agent: *
Disallow: /WebStore/diy_page.html
Disallow: /*?subcategories=G
Disallow: /*?conn_1=
Disallow: /WebStore/modelSearch.html          ← DISALLOWED
Disallow: /WebStore/orderConfirmation.html
Disallow: /WebStore/orderDetail.html
Disallow: /WebStore/orderHistory.html
Disallow: /WebStore/orderSummary.html
Disallow: /WebStore/orderSummaryQC.html
Disallow: /WebStore/orderSummaryQC.html
Disallow: /WebStore/orderSummary_tejas.html
Disallow: /WebStore/quote.html
Disallow: /WebStore/registrationConfirm
Disallow: /WebStore/softwaredownload/login.html
Disallow: /WebStore/checkout.html
Disallow: /WebStore/checkout_tejas.html
Disallow: /WebStore/checkoutQC.html
Disallow: /WebStore/ezorderconfirmation.html
Disallow: /WebStore/ezsamplecheckout.html
Disallow: /WebStore/ezsamplequestion.html
Disallow: /WebStore/*Login
Disallow: /WebStore/*Accounts
Disallow: /WebStore/*Password
Disallow: /WebStore/*Registration
Disallow: /WebStore/*Cart
Sitemap: https://www.minicircuits.com/sitemap.xml
```

**Key conclusions:**

- `/WebStore/Amplifiers.html` is **NOT disallowed** — scraping allowed.
- `/WebStore/modelSearch.html` **IS disallowed** — the per-model detail page
  (`modelSearch.html?model=XXXX`) must **not** be fetched by the adapter.
- **Impact on `Candidate.url`:** The URL field on each Candidate was planned as
  `https://www.minicircuits.com/WebStore/modelSearch.html?model=XXXX`. Because
  that path is disallowed in robots.txt, the adapter must NOT fetch it.
  However, the field can still be **set** to that URL string (for human use in
  the report output — the user clicks it), as long as the adapter code never
  issues an HTTP request to it. The canonical URL string per product IS the
  `modelSearch.html?model=XXXX` pattern (as observed in the live page's `<a>` tags),
  and populating it for the reporter is acceptable. The adapter just must not
  programmatically fetch those pages. This plan records the URL but does not
  fetch it. If policy requires strict adherence (no-store of disallowed paths),
  an alternative is to use a blank URL or the Amplifiers page; see §9 Risks.

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/minicircuits.py` | **Create** | The Mini-Circuits adapter (main deliverable) |
| `tests/adapters/test_minicircuits.py` | **Create** | Offline unit tests using the HTML fixture |
| `tests/fixtures/minicircuits_amplifiers.html` | **Create** | Saved snapshot of the results table HTML (I-2) |

No existing files need to be edited for T8 itself. (T10 will later wire the
HTTP fetch through the cache, editing `minicircuits.py` at that stage.)

---

## 4. HTML Structure and CSS Selector

### Table tag and location

```html
<table class="tbl_amp tbl_amp_header" id="maintable">
  <thead>
    <th class="bg_color" colspan="14" id="filter_tool"> ... filter inputs ... </th>
    <th>Model Number</th>
    <th>F Low <br/>(MHz)</th>
    <th>F High <br/>(MHz)</th>
    <th>Gain (dB) Typ.</th>
    <th>NF (dB) Typ.</th>
    <th>P1dB (dBm) Typ.</th>
    <th>PSAT (dBm) Typ.</th>
    <th>OIP3 (dBm) Typ.</th>
    <th>Input VSWR (:1) Typ.</th>
    <th>Output VSWR (:1) Typ.</th>
    <th>Voltage (V)</th>
    <th>Current (mA)</th>
    <th>Case Style</th>
    <th>Connector Type</th>
    <th>Option</th>
    <!-- th[16+] empty (action buttons) -->
  </thead>
  <tbody>
    <tr>
      <td><a target="_blank" class="1st_col"
             href="modelSearch.html?model=ADCA3270">ADCA3270</a></td>
      <td><output class="2nd_col">45</output></td>
      <td><output>1218</output></td>
      <td><output>25</output></td>
      ...
    </tr>
    ...
  </tbody>
</table>
```

### CSS selector strategy

Using `selectolax` (already planned in pyproject.toml, D-1):

```python
from selectolax.parser import HTMLParser

tree = HTMLParser(html)
table = tree.css_first("table#maintable")

# Header row: skip th[0] (merged filter cell), read th[1..14]
headers = [th.text(strip=True) for th in table.css("thead th")]
# headers[0] will be the big merged filter cell — skip it
# headers[1] = "Model Number", headers[2] = "F Low\n(MHz)", etc.

# Data rows
for row in table.css("tbody tr"):
    cells = row.css("td")
    # cell[0]: model name is in the <a> tag; also get href for URL
    # cell[1..]: <output> or plain text
```

**Note on column 0 / model link:** The model name lives inside an `<a>` tag,
and the `href` attribute contains the relative URL for the product page.
Use `.css_first("a")` on the first `<td>` to get both text and href.

**Note on empty/missing values:** Several cells contain `"-"` for parameters
not specified. These should be stored as `None` in `raw_params` (key absent),
not as a `RawValue`. The Verifier will mark them `UNKNOWN`.

**Header de-duplication:** `selectolax` `.text(strip=True)` strips HTML tags
and collapses whitespace, converting `F Low <br/>(MHz)` to `F Low  (MHz)` or
similar. A normalize step is needed: strip/collapse whitespace, then match
against the canonical mapping table.

---

## 5. Column Mapping

The confirmed column headers (from live inspection, TH indices 1–14) map as follows.
This confirms and extends the design.md §6.2 table with two additional observed columns:

| TH index | Raw header text (after text extraction) | Canonical param | Source unit | Stored as | Notes |
|----------|-----------------------------------------|-----------------|-------------|-----------|-------|
| 1 | `Model Number` | `model` (Candidate field) | — | string | Used as `Candidate.model` |
| 2 | `F Low (MHz)` | `freq_range` (low bound) | MHz | combined below | |
| 3 | `F High (MHz)` | `freq_range` (high bound) | MHz | `RawValue((low, high), "MHz")` | Combine cols 2+3 |
| 4 | `Gain (dB) Typ.` | `Gain` | dB | `RawValue(value, "dB")` | |
| 5 | `NF (dB) Typ.` | `NF` | dB | `RawValue(value, "dB")` | |
| 6 | `P1dB (dBm) Typ.` | `P1dB` | dBm | `RawValue(value, "dBm")` | |
| 7 | `PSAT (dBm) Typ.` | `Psat` | dBm | `RawValue(value, "dBm")` | header reads "PSAT" |
| 8 | `OIP3 (dBm) Typ.` | `IP3` | dBm | `RawValue(value, "dBm")` | header reads "OIP3" |
| 9 | `Input VSWR (:1) Typ.` | — | — | skip | Not in ontology this iter |
| 10 | `Output VSWR (:1) Typ.` | — | — | skip | Not in ontology this iter |
| 11 | `Voltage (V)` | `VDD` | V | mapped | alias: Voltage → VDD |
| 12 | `Current (mA)` | `current` | mA | skip | Not in ontology this iter |
| 13 | `Case Style` | — | — | skip | Metadata only |
| 14 | `Connector Type` | — | — | skip | Metadata only |
| 15 | `Option` | — | — | skip | Metadata only |

**Amendment vs. design.md §6.2:** Two columns not listed in the spec were
observed: `Input VSWR (:1) Typ.` (index 9) and `Output VSWR (:1) Typ.` (index 10).
These are skipped this iteration (not in the amplifier ontology). The indices
shift the Voltage column from the design's implied index to index 11.

**Header matching strategy:** Use a hard-coded `COLUMN_MAP` dict mapping
normalized header text to `(canonical_name, unit)`. Normalization: lowercase,
strip, collapse whitespace, strip `(`, `)`, `typ.` suffixes. This is more robust
than index-based access, which would break if Mini-Circuits adds a column.

---

## 6. Candidate Construction (Pseudocode)

```python
COLUMN_MAP = {
    "model number":    ("model",      None),
    "f low mhz":       ("freq_low",   "MHz"),   # intermediate
    "f high mhz":      ("freq_high",  "MHz"),   # intermediate
    "gain db typ":     ("Gain",       "dB"),
    "nf db typ":       ("NF",         "dB"),
    "p1db dbm typ":    ("P1dB",       "dBm"),
    "psat dbm typ":    ("Psat",       "dBm"),
    "oip3 dbm typ":    ("IP3",        "dBm"),
    # all others → skip
}

BASE_URL = "https://www.minicircuits.com/WebStore/"

def _normalize_header(raw: str) -> str:
    """Lowercase, strip HTML entities, collapse whitespace, remove punctuation."""
    text = re.sub(r"[().,]", " ", raw.lower())
    return re.sub(r"\s+", " ", text).strip()

def _parse_float(cell_text: str) -> float | None:
    """Return None for '-', empty, or non-numeric; float otherwise."""
    t = cell_text.strip()
    if t in ("", "-", "N/A", "n/a"):
        return None
    try:
        return float(t)
    except ValueError:
        return None

def _build_candidate(row_cells: list[str], headers: list[str], model_href: str) -> Candidate | None:
    """Build one Candidate from a parsed table row. Returns None if model name missing."""
    # Map header → cell value
    row = {_normalize_header(h): cell for h, cell in zip(headers, row_cells)}

    model_name = row.get("model number", "").strip()
    if not model_name:
        return None

    # Product URL (built from observed href pattern; not fetched)
    url = BASE_URL + model_href if model_href else BASE_URL + f"modelSearch.html?model={model_name}"

    # Build raw_params
    raw_params: dict[str, RawValue] = {}

    # Frequency range: combine low + high
    f_low  = _parse_float(row.get("f low mhz", "-"))
    f_high = _parse_float(row.get("f high mhz", "-"))
    if f_low is not None and f_high is not None:
        raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="MHz")

    # Scalar params
    for header_key, (canonical, unit) in COLUMN_MAP.items():
        if canonical in ("model", "freq_low", "freq_high"):
            continue   # handled above
        val = _parse_float(row.get(header_key, "-"))
        if val is not None:
            raw_params[canonical] = RawValue(value=val, unit=unit)

    return Candidate(
        model=model_name,
        manufacturer="Mini-Circuits",
        url=url,
        raw_params=raw_params,
        source="table",
    )
```

### Key field assignments for one example row

Row: `['ADCA3270', '45', '1218', '25', '3', '-', '-', '-', '1.43', '1.2', '24', '350/480', 'DL3631', '-', '']`

```python
Candidate(
    model="ADCA3270",
    manufacturer="Mini-Circuits",
    url="https://www.minicircuits.com/WebStore/modelSearch.html?model=ADCA3270",
    raw_params={
        "freq_range": RawValue(value=(45.0, 1218.0), unit="MHz"),
        "Gain":       RawValue(value=25.0,            unit="dB"),
        "NF":         RawValue(value=3.0,             unit="dB"),
        # P1dB, Psat, IP3 are "-" for this model → absent from raw_params
    },
    source="table",
)
```

Note: `Current (mA)` for ADCA3270 is `"350/480"` (dual values). This is
non-parseable as float. `_parse_float` returns `None` → key absent. Acceptable
this iteration because `current` is not in the ontology anyway.

---

## 7. Test Plan

### Fixture file

**Path:** `tests/fixtures/minicircuits_amplifiers.html`

**Content:** A minimal but representative slice of the live page HTML containing:
- The `<table id="maintable">` element
- The complete `<thead>` with all column `<th>` tags
- At least 10 representative `<tbody>` rows covering:
  - A row with all major params present (model, freq, gain, NF, P1dB, PSAT, OIP3)
  - A row where P1dB / PSAT / OIP3 are `"-"` (missing params → absent from raw_params)
  - A row with unusually high frequency (e.g. > 40 GHz) to test unit handling
  - A row where current cell is `"350/480"` (non-parseable → absent)

The fixture is captured by running the adapter's fetch function once and saving
the response (can be scripted as a one-shot during I-2 implementation).

### Test assertions (offline, no network)

```python
# tests/adapters/test_minicircuits.py

import pytest
from pathlib import Path
from rf_finder.adapters.minicircuits import MiniCircuitsAdapter
from rf_finder.models import Candidate, RawValue

FIXTURE = Path(__file__).parent.parent / "fixtures" / "minicircuits_amplifiers.html"

def test_parse_fixture_returns_candidates():
    adapter = MiniCircuitsAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    candidates = adapter._parse_html(html)   # internal parse method, not search()
    assert len(candidates) >= 10

def test_candidate_model_and_manufacturer():
    candidates = _load_candidates()
    c = candidates[0]
    assert c.manufacturer == "Mini-Circuits"
    assert c.source == "table"
    assert c.model  # non-empty

def test_freq_range_is_rawvalue_tuple_in_mhz():
    candidates = _load_candidates()
    # Find a candidate with known freq range
    c = next(x for x in candidates if x.model == "ADCA3270")
    rv = c.raw_params["freq_range"]
    assert isinstance(rv.value, tuple)
    assert rv.unit == "MHz"
    assert rv.value == (45.0, 1218.0)

def test_missing_param_is_absent_not_none():
    """Cells containing '-' must be absent from raw_params (not stored as None)."""
    candidates = _load_candidates()
    # ADCA3270 has P1dB = '-'
    c = next(x for x in candidates if x.model == "ADCA3270")
    assert "P1dB" not in c.raw_params

def test_present_scalar_param():
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ADCA3270")
    gain = c.raw_params["Gain"]
    assert gain == RawValue(value=25.0, unit="dB")

def test_candidate_url_contains_model():
    candidates = _load_candidates()
    c = candidates[0]
    assert c.model in c.url
    assert "minicircuits.com" in c.url

def test_adapter_raises_adaptererror_on_bad_html():
    from rf_finder.adapters.base import AdapterError
    adapter = MiniCircuitsAdapter()
    with pytest.raises(AdapterError):
        adapter._parse_html("<html><body>no table here</body></html>")
```

### Integration test (marked network, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    from rf_finder.models import QuerySpec, ParamConstraint
    spec = QuerySpec(
        component_type="amplifier",
        constraints=[
            ParamConstraint("freq_range", "contains", None, (2.0, 6.0), "GHz"),
        ],
    )
    adapter = MiniCircuitsAdapter()
    results = adapter.search(spec)
    assert len(results) > 0
    assert all(c.manufacturer == "Mini-Circuits" for c in results)
```

---

## 8. Rate Limiting Strategy

Because the adapter fetches only **one URL** per `search()` call
(`/WebStore/Amplifiers.html`), and all 781 products are returned in that single
response, rate limiting is straightforward:

- **Single request per search call** — no pagination, no per-product fetches.
- **Minimum inter-request delay:** 1 second between consecutive adapter calls
  (read from `config.yaml` under `rate_limits.minicircuits.delay_seconds`,
  default `1.0`). Implemented as a `time.sleep()` before the request if the
  last fetch timestamp is within the delay window.
- **Cache (T10):** The SQLite cache (TTL: 7 days, configurable) will serve
  responses after the first fetch, so the delay is only incurred on cache miss.
  The rate limit applies to live HTTP calls, not cache reads.
- **User-Agent:** Send a descriptive but honest User-Agent string, e.g.:
  `"rf-component-finder/1.0 (research tool; contact: <email>)"` or the
  browser-style UA used in testing. Choose the browser UA for compatibility —
  Mini-Circuits may return 403 for bot UAs.
- **No parallel fetching:** Only one adapter is planned for this iteration;
  no concurrent fetches needed.

---

## 9. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Mini-Circuits adds a column, shifting indices | Medium | Use header-name matching (`COLUMN_MAP`) rather than fixed indices |
| R2 | `"-"` is not the only sentinel for missing values (e.g. `"N/A"`, `"TBD"`, empty) | Low | `_parse_float` handles empty and common sentinels; log unexpected strings |
| R3 | `modelSearch.html` URL in `Candidate.url` is technically disallowed by robots.txt | Medium | The adapter populates the URL field for reporter display only and never fetches it. If strict policy required, use the Amplifiers.html page as the URL fallback. This needs an explicit decision at implementation time. |
| R4 | The site returns a dynamic bot-challenge page (Cloudflare, CAPTCHA) rather than the product HTML | Low-Medium | The live probe succeeded with a browser UA; monitor for changes. If it breaks, playwright with a real browser may be needed. |
| R5 | Cell values like `"350/480"` (dual-range current) appear for numeric fields in ontology | Low | Only `current` exhibits this in the sample; `current` is not in the ontology. If a mapped param has this format, `_parse_float` returns None → key absent → UNKNOWN in Verifier. |
| R6 | Page size (~3.75 MB) causes slow test runs with the fixture | Low | The fixture should be a trimmed slice, not the full 3.75 MB page — only the `<table id="maintable">` element and a sample of rows is needed. |
| R7 | `selectolax` not yet in pyproject.toml | Low | T1 spec lists it as a dependency (D-1). Confirm it is installed in the venv before T8 implementation. |
| R8 | The `search()` method must accept a `QuerySpec` but cannot apply freq filtering server-side | Resolved | Return all rows; Verifier applies constraints. Document in adapter docstring. |

### Open questions for implementation

- **OQ-1:** Should `Candidate.url` be set to the disallowed `modelSearch.html?model=XXX`
  URL, or to the allowed `Amplifiers.html` page? Recommend the model-specific URL
  (for user value in the report) with a note that the adapter never fetches it.
  Needs sign-off from the implementer.

- **OQ-2:** Should the adapter log a warning if the page row count changes
  significantly between runs (possible sign of site redesign)? Recommend yes —
  log a warning if row count deviates > 20% from the cached count.

---

## Summary

- **Fetch strategy:** Single `httpx.get` to `/WebStore/Amplifiers.html` — no JS, no AJAX, no POST needed.
- **Parsing:** `selectolax` on `table#maintable`, header-name column mapping.
- **robots.txt:** Amplifiers.html is allowed; modelSearch.html is disallowed (URL populated but not fetched).
- **Key deviation from design.md §6.2:** Server-side frequency filtering is not available; the adapter scrapes all rows and the Verifier filters.
- **Files to create:** `rf_finder/adapters/minicircuits.py`, `tests/adapters/test_minicircuits.py`, `tests/fixtures/minicircuits_amplifiers.html`.

# T8 Plan — Analog Devices Adapter

> **Task:** T8 from tasks.md — `adapters/analogdevices.py` (second adapter under
> the same T8 "site adapter" task as Mini-Circuits).
> **Phase:** Plan only (Phase A). No code written in this document.
> **Date:** 2026-06-29
> **Investigator:** Phase A planning agent
> **Resolves open items:** I-1 (request mechanism), I-2 (data fixture) for ADI.
> Manufacturer-specific requirements: [requirements.md](requirements.md).

---

## 1. Request Mechanism Finding (resolves I-1)

### Method used

Live `httpx.get` to the Analog Devices parametric-search-table (PST2) data
endpoint with a browser-style User-Agent. Analog Devices serves each parametric
category's full dataset as a static-looking `.js` URL whose body is actually
JSON.

### Findings

| Question | Answer |
|----------|--------|
| Data URL | `https://www.analog.com/cdp/pst2/data/standard/3003.js` |
| `catId` | **3003** = the "RF Amplifiers" parametric category |
| Method for initial load | **HTTP GET, no query parameters needed** |
| Body format | **JSON** (despite the `.js` extension); top-level key `data` is an array of row objects |
| Server-side rendering / JS? | **No JS execution required** — the GET returns the complete dataset as data, not HTML |
| AJAX / XHR for table data? | The endpoint **is** the data feed the page's JS consumes; we call it directly |
| Server-side freq filter? | **No** — the endpoint returns the full category dataset; no filtering parameters are honored |
| Per-row shape | `row[fieldId] = {"value": [...], "displayValue": "..."}`; raw numeric value lives at `row[fid]["value"][0]` |

### Conclusion: httpx (not playwright)

Because the complete dataset is returned as JSON from a single GET, `httpx` is
sufficient and `playwright` is not needed. The adapter will:

1. Send a single `httpx.get` to `/cdp/pst2/data/standard/3003.js`.
2. `json.loads` the body and read the `data` array.
3. Apply **no** server-side filtering (the endpoint does not support it).
4. Return **all** rows as `Candidate` objects; the Verifier applies the
   frequency (and all other scalar) constraints (REQ-4.1).

> **Design note:** Like Mini-Circuits, this deviates from any
> "narrow server-side where possible" aspiration in design.md §6.2 — ADI's
> endpoint returns the whole category. No correctness impact (the Verifier
> filters); the cache (T10) mitigates re-fetching the full dataset.

---

## 2. robots.txt Summary

URL: `https://www.analog.com/robots.txt`

> **TO VERIFY (not yet fetched in this plan):** Confirm before first live run
> that the data endpoint path family `/cdp/pst2/data/...` and the product page
> path family `/en/products/...` are **not** Disallowed for `User-agent: *`, and
> note any `Crawl-delay`. Record the verbatim relevant rules here once fetched,
> mirroring §2 of the Mini-Circuits plan. (NFR-6 — scraping SHALL respect
> robots.txt.)

**Paths this adapter touches:**

- **Fetched programmatically:** `/cdp/pst2/data/standard/3003.js` — the only URL
  the adapter requests.
- **Populated but never fetched:** `Candidate.url` =
  `https://www.analog.com/en/products/{model}.html` (lowercased model) — set for
  human/reporter display only; the adapter issues no HTTP request to it.

If robots.txt disallows the data endpoint, escalate as a blocking risk (see §9
R3) before any live fetch.

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/analogdevices.py` | **Create** | The Analog Devices adapter (main deliverable) |
| `tests/adapters/test_analogdevices.py` | **Create** | Offline unit tests using the JSON fixture |
| `tests/fixtures/analogdevices_rfamps.json` | **Create** | Saved/trimmed snapshot of the PST2 `3003.js` body (I-2) |

No existing files need to be edited for T8 itself. (T10 will later wire the HTTP
fetch through the cache.)

---

## 4. JSON Structure and Parsing Strategy

### Response shape

```json
{
  "data": [
    {
      "0":    {"value": ["ADL5243"],    "displayValue": "ADL5243"},
      "279":  {"value": ["100000000"],  "displayValue": "100 MHz"},
      "278":  {"value": ["4000000000"], "displayValue": "4 GHz"},
      "2930": {"value": ["25.3"],       "displayValue": "25.3 dBm"},
      "2922": {"value": ["40"],         "displayValue": "40 dBm"},
      "2913": {"value": [""],           "displayValue": ""},
      "2921": {"value": ["3.1"],        "displayValue": "3.1 dB"},
      "4709": {"value": [""],           "displayValue": ""}
    }
  ]
}
```

### Parse strategy (`json`, no HTML parser)

```python
import json

doc = json.loads(body)          # AdapterError if not valid JSON
rows = doc["data"]              # AdapterError if "data" missing / not a list

for row in rows:
    model = _cell_value(row, "0")     # row["0"]["value"][0], stripped
    if not model:                     # skip rows with no Part#
        continue
    ...
```

- **Numeric value access:** raw value is `row[fid]["value"][0]`; the parallel
  `displayValue` (e.g. `"4 GHz"`) is **ignored** — we always parse the canonical
  `value` and carry the unit from the field map.
- **Missing sentinels:** `""`, `"-"`, `"n/a"`, `"N/A"`, `"NA"` → treated as
  absent (key omitted from `raw_params`).
- **Scientific notation:** values like `"2e-11"`, `"1.7e9"` parse via `float()`.

---

## 5. Field Mapping (field-id → ontology)

Confirmed from ADI view metadata for catId 3003. **Note: ADI columns are keyed
by numeric field-id, not by header text** — the opposite of Mini-Circuits.

| Field id | ADI meaning | Canonical param | Source unit | Stored as |
|----------|-------------|-----------------|-------------|-----------|
| `0` | Part# | `model` (Candidate field) | — | string |
| `279` | Frequency Response min (Hz) | `freq_range` (low) | Hz | combined below |
| `278` | Frequency Response max (Hz) | `freq_range` (high) | Hz | `RawValue((low, high), "Hz")` |
| `2930` | OP1dB typ | `P1dB` | dBm | `RawValue(value, "dBm")` |
| `2922` | OIP3 typ | `IP3` | dBm | `RawValue(value, "dBm")` |
| `2913` | Gain typ | `Gain` | dB | `RawValue(value, "dB")` |
| `2921` | Noise Figure typ | `NF` | dB | `RawValue(value, "dB")` |
| `4709` | Saturated Output Power | `Psat` | dBm | `RawValue(value, "dBm")` |

**Unit note (deviation from Mini-Circuits):** ADI frequencies are in **Hz**,
not MHz. `freq_range` is stored as `RawValue((low, high), "Hz")`; the Verifier
converts to the ontology's canonical frequency unit (REQ-2.5, REQ-4.1).

**DC-coupled parts:** `279` may be `"0"` (e.g. ADH465S). `0` is a valid
frequency and **must be kept** — `_parse_float("0") == 0.0` — yielding a
`(0.0, high)` range rather than dropping the part to UNKNOWN.

**freq_range construction:** built when **both** `279` and `278` parse to a
number. Otherwise, fall back to the single **-3 dB Bandwidth** (`fid 1519`):
wideband/differential parts (AD8131, ADA49xx) carry no `279`/`278` band, so their
bandwidth is mapped to a `(0, BW)` range via the shared
`base.freq_range_from_bandwidth()` helper. For true RF parts `1519` merely mirrors
the upper freq edge, so `279`/`278` take precedence and `1519` is used only as a
fallback.

**Paramless filter:** after parsing, `search()` drops any candidate whose
`raw_params` is empty (via the shared `base.drop_paramless()`). ADI lists ~80
non-RF parts in catId 3003 with no parametric data at all; without this they
would surface as all-UNKNOWN `partial` noise. The filter is intentionally silent
(see §9 R8).

---

## 6. Candidate Construction (Pseudocode)

```python
FIELD_MAP = {
    "0":    ("model",     None),
    "279":  ("freq_low",  "Hz"),   # intermediate
    "278":  ("freq_high", "Hz"),   # intermediate
    "2930": ("P1dB",      "dBm"),
    "2922": ("IP3",       "dBm"),
    "2913": ("Gain",      "dB"),
    "2921": ("NF",        "dB"),
    "4709": ("Psat",      "dBm"),
}
PRODUCT_URL = "https://www.analog.com/en/products/{model}.html"

def _cell_value(row, fid):
    cell = row.get(fid)
    if not isinstance(cell, dict): return None
    vals = cell.get("value")
    if not isinstance(vals, list) or not vals: return None
    return str(vals[0]).strip() or None

def _parse_float(raw):
    if raw is None: return None
    t = raw.strip()
    if not t or t in {"", "-", "n/a", "N/A", "NA"}: return None
    try: return float(t)
    except ValueError: return None

def _build_candidate(row):
    model = _cell_value(row, "0")
    if not model: return None          # skip rows with no Part#

    raw_params = {}
    f_low  = _parse_float(_cell_value(row, "279"))
    f_high = _parse_float(_cell_value(row, "278"))
    if f_low is not None and f_high is not None:
        raw_params["freq_range"] = RawValue((f_low, f_high), "Hz")

    for fid, (canonical, unit) in FIELD_MAP.items():
        if canonical in ("model", "freq_low", "freq_high"): continue
        val = _parse_float(_cell_value(row, fid))
        if val is not None:
            raw_params[canonical] = RawValue(val, unit)

    return Candidate(
        model=model,
        manufacturer="Analog Devices",
        url=PRODUCT_URL.format(model=model.lower()),
        raw_params=raw_params,
        source="table",
    )
```

### Example rows (from the fixture)

```python
# ADL5243 — Gain ("2913") and Psat ("4709") empty -> absent
Candidate(
    model="ADL5243",
    manufacturer="Analog Devices",
    url="https://www.analog.com/en/products/adl5243.html",
    raw_params={
        "freq_range": RawValue((100000000.0, 4000000000.0), "Hz"),
        "P1dB":       RawValue(25.3, "dBm"),
        "IP3":        RawValue(40.0, "dBm"),
        "NF":         RawValue(3.1,  "dB"),
    },
    source="table",
)

# ADH465S — DC-coupled (low edge 0 Hz), all RF params present
Candidate(
    model="ADH465S",
    raw_params={
        "freq_range": RawValue((0.0, 20000000000.0), "Hz"),
        "P1dB": RawValue(22.0, "dBm"), "IP3": RawValue(30.0, "dBm"),
        "Gain": RawValue(17.0, "dB"),  "NF":  RawValue(2.5,  "dB"),
        "Psat": RawValue(24.0, "dBm"),
    },
    ...
)
```

---

## 7. Test Plan

### Fixture file

**Path:** `tests/fixtures/analogdevices_rfamps.json`

**Content:** A trimmed, representative slice of the live `3003.js` body — the
`{"data": [...]}` wrapper plus a handful of rows covering:

- A row with some scalar fields empty (`ADL5243`: Gain & Psat empty → absent).
- A row with a scalar field present (`ADL5320`: Gain = 13.2 dB).
- A DC-coupled row (`ADH465S`: freq_low `"0"` → `(0, high)`; all RF params present).

### Test assertions (offline, no network)

Tests call the internal `_parse_json(text)` method directly (never `search()`):

```python
FIXTURE = Path(__file__).parent.parent / "fixtures" / "analogdevices_rfamps.json"

def _load_candidates():
    return AnalogDevicesAdapter()._parse_json(FIXTURE.read_text(encoding="utf-8"))

def test_parse_fixture_returns_candidates():
    assert len(_load_candidates()) == 3

def test_candidate_model_and_manufacturer():
    c = _load_candidates()[0]
    assert c.manufacturer == "Analog Devices"
    assert c.source == "table"
    assert c.model == "ADL5243"

def test_freq_range_is_rawvalue_tuple_in_hz():
    c = next(x for x in _load_candidates() if x.model == "ADL5243")
    assert c.raw_params["freq_range"] == RawValue((100000000.0, 4000000000.0), "Hz")

def test_missing_scalar_params_are_absent():
    c = next(x for x in _load_candidates() if x.model == "ADL5243")
    assert "Gain" not in c.raw_params and "Psat" not in c.raw_params

def test_freq_range_with_zero_low_edge():           # DC-coupled
    c = next(x for x in _load_candidates() if x.model == "ADH465S")
    assert c.raw_params["freq_range"] == RawValue((0.0, 20000000000.0), "Hz")

def test_candidate_url_contains_lowercased_model():
    c = _load_candidates()[0]
    assert "analog.com" in c.url and "adl5243" in c.url
```

Plus inline-JSON edge cases (no fixture needed):

- Sentinels `""`, `"-"`, `"NA"`, `"N/A"`, `"n/a"` → param absent.
- `freq_low` empty but `freq_high` present → no `freq_range`.
- Row with no mapped fields → empty `raw_params`.
- Row with no field `"0"` (no Part#) → skipped entirely.
- `_parse_float` / `_cell_value` helper unit tests (scientific notation, empty
  `value` list, missing cell).

### Error handling

```python
def test_invalid_json_raises_adaptererror():
    with pytest.raises(AdapterError):
        AnalogDevicesAdapter()._parse_json("not valid json {{")

def test_missing_data_array_raises_adaptererror():
    with pytest.raises(AdapterError):
        AnalogDevicesAdapter()._parse_json('{"categoryId": "3003"}')
```

### Integration test (marked network, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    results = AnalogDevicesAdapter().search(QuerySpec(component_type="amplifier", constraints=[]))
    assert len(results) > 0
    assert all(c.manufacturer == "Analog Devices" for c in results)
```

---

## 8. Rate Limiting Strategy

- **Single request per `search()` call** — one GET to `3003.js` returns the whole
  category; no pagination, no per-product fetches.
- **Minimum inter-request delay:** **5 seconds** between consecutive live fetches
  (more conservative than Mini-Circuits' 1 s, since ADI is a larger vendor with
  stricter edge protection). Implemented as a `time.sleep()` before the request
  if the last fetch is within the delay window
  (`config.yaml` → `rate_limits.analogdevices.delay_seconds`, default `5.0`).
- **Cache (T10):** SQLite cache serves responses after the first fetch; the delay
  only applies on cache miss / live HTTP, not cache reads.
- **User-Agent:** browser-style UA (plain bot UAs may be rejected by ADI's CDN);
  `Accept: application/javascript,application/json,text/javascript,*/*;q=0.1`.
- **No parallel fetching.**

---

## 9. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | ADI reassigns `catId` 3003 → endpoint URL 404s | Low-Medium | Hard-coded `_CAT_ID`; on HTTP error raise `AdapterError` with context (REQ-3.6). Revisit if it breaks (see [requirements.md](requirements.md) ADI-OQ-1). |
| R2 | Numeric field-ids (`279`, `2930`, …) change meaning between responses | Medium | Hard-coded `FIELD_MAP`; consider resolving ids from view metadata at runtime if instability observed (ADI-OQ-2). |
| R3 | robots.txt disallows `/cdp/pst2/data/...` | Unknown — **must verify (see §2)** | Confirm before first live run; if disallowed, do not fetch and escalate. |
| R4 | `.js` body is wrapped (JSONP / leading assignment) rather than bare JSON | Low | `json.loads` raises → `AdapterError`. If observed, strip the wrapper before parsing. |
| R5 | CDN returns a bot-challenge page instead of JSON | Low-Medium | Browser UA used; non-JSON body → `AdapterError`. Monitor. |
| R6 | Frequency stored in Hz but Verifier assumes MHz/GHz | Resolved | `RawValue` carries the `"Hz"` unit; Verifier converts via the ontology (REQ-2.5). |
| R7 | DC-coupled `freq_low = "0"` wrongly dropped as "missing" | Resolved | `_parse_float("0") == 0.0`; range becomes `(0, high)`. Covered by test. |
| R8 | Silent `drop_paramless` filter masks a parse break: if a schema change empties every row's `raw_params`, all rows are dropped and the run shows "no results" rather than an error | Low-Medium | Accepted trade-off (kept silent for simplicity). The dropped parts are genuinely unusable. If parser stability becomes a concern, surface a warning when the drop exceeds ~50% of fetched rows. |

### Open questions for implementation

- **OQ-1:** Should `Candidate.url` use the lowercased-model product page
  (`/en/products/{model}.html`) even though it is not fetched and may 404 for
  some part-number formats? Recommend yes (user value), with the adapter never
  fetching it. Confirm the lowercasing rule against a sample of real part numbers.
- **OQ-2:** Should the adapter log a warning if the `data` row count deviates
  significantly between runs (sign of an endpoint/category change)? Recommend yes.

---

## Summary

- **Fetch strategy:** Single `httpx.get` to `/cdp/pst2/data/standard/3003.js` — JSON body, no JS, no AJAX, no filtering.
- **Parsing:** `json.loads` → `data` array; values read from `row[fid]["value"][0]`, mapped by numeric **field-id** (not header text).
- **Units:** frequencies in **Hz**; DC-coupled low edge `0` preserved.
- **robots.txt:** **must be verified** for `/cdp/pst2/data/...` before live runs (§2); product URL populated but never fetched.
- **Rate limit:** 5 s min inter-request delay (vs 1 s for Mini-Circuits).
- **Files to create:** `rf_finder/adapters/analogdevices.py`, `tests/adapters/test_analogdevices.py`, `tests/fixtures/analogdevices_rfamps.json`.

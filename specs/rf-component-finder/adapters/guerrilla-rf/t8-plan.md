# T8 Plan — Guerrilla RF Adapter

> **Task:** T8 from tasks.md — `adapters/guerrillarf.py` (third adapter under the
> same T8 "site adapter" task as Mini-Circuits and Analog Devices).
> **Phase:** Plan only (Phase A). No code written in this document.
> **Date:** 2026-06-30
> **Investigator:** Phase A planning agent
> **Resolves open items:** I-1 (request mechanism), I-2 (data fixture) for GRF.
> Manufacturer-specific requirements: [requirements.md](requirements.md).

---

## 1. Request Mechanism Finding (resolves I-1)

### Source chosen: the amplifiers listing page (HTML), not the JSON API

Two candidate sources were investigated and verified live:

| Source | Params | Notes |
|--------|--------|-------|
| `/api/products.json` | freq, Gain, NF, P1dB, Psat, IP3 (6) | clean JSON, 1 request, but **no VDD**; freq as a `"low-high"` string |
| **`/products/amplifiers.html`** | **+ VDD** (7) | two server-rendered tables; Min/Max freq as separate clean columns; also a `Package` column |

The listing page is a **superset**: everything the API has, plus **VDD** (a real
range), plus cleaner Min/Max frequency columns — all in **one request**. It is
therefore the chosen source; the JSON API is not used.

### Findings (`/products/amplifiers.html`)

| Question | Answer |
|----------|--------|
| URL | `https://www.guerrilla-rf.com/products/amplifiers.html` (the no-`.html` form serves the same page) |
| Method | **HTTP GET** |
| Rendering | **Server-rendered** — both tables' rows are in the raw HTML. A `DataTables` JS lib only *wraps* the tables for sorting/paging at runtime; the data needs no JS. `httpx` + `selectolax` suffice (no playwright). |
| Tables | Two: `table#genericAmpFunctionTbl` (137 LNA/gain-block rows) and `table#satPATbl` (22 saturated-PA rows) |
| Server-side filtering | None needed; the whole amplifier list is on one page, already amplifier-only |

### Conclusion

`httpx.get` the page once, parse **both** tables with `selectolax`, map columns by
header name, and return `Candidate` objects. The Verifier applies constraints.

---

## 2. robots.txt Summary

URL: `https://www.guerrilla-rf.com/robots.txt` (fetched live).

```
User-agent: *
Disallow: /config/ /handlers/ /interceptors/ /layouts/ /logs/
Disallow: /models/ /modules/ /modules_app/ /views/ /api/
Allow: /api/products.json
Allow: /
Sitemap: https://www.guerrilla-rf.com/sitemap.xml          (no Crawl-delay)
```
Plus an explicit allow-list for AI crawlers (ClaudeBot, Claude-Web, anthropic-ai, …).

**Key conclusion:** `/products/amplifiers.html` is under the general `Allow: /`
with **no** Disallow on `/products/` — scraping it is compliant (NFR-6). (The
`/api/` family is Disallowed except `products.json`; we no longer use the API.)

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/guerrillarf.py` | **Create** | The Guerrilla RF adapter (main deliverable) |
| `tests/adapters/test_guerrillarf.py` | **Create** | Offline unit tests using the HTML fixture |
| `tests/fixtures/guerrillarf_amplifiers.html` | **Create** | Trimmed snapshot of the two-table page (I-2) |

Reuses the shared `drop_paramless` helper in `base.py`. No bandwidth case here.

---

## 4. HTML Structure

```html
<table id="genericAmpFunctionTbl" class="table ... display">   <!-- LNA / gain blocks -->
  <thead><tr>
    <th>Product</th><th>Min Freq (GHz)</th><th>Max Freq (GHz)</th>
    <th>Gain(dB)</th><th>NF(dB)</th><th>OP1dB (dBm)</th><th>OIP3 (dBm)</th>
    <th>Reference Conditions</th><th>Vdd Range (V)</th><th>Idd Range (mA)</th>
    <th>Features</th><th>Package (mm)</th><th>Description</th><th>Parametric Charts</th>
  </tr></thead>
  <tbody>
    <tr>
      <td><a href="https://www.guerrilla-rf.com/products/detail/sku/GRF2003">GRF2003</a></td>
      <td>0.1</td><td>10.0</td><td>12.0</td><td>3.5</td><td>15.0</td><td>29.0</td>
      <td>5V/55mA/5.5GHz</td><td>2.7-5.0</td><td>40-80</td>
      <td>...</td><td>1.5 DFN-6</td><td>Ultra Broadband Gain Block</td><td></td>
    </tr> ...
  </tbody>
</table>

<table id="satPATbl" ...>   <!-- saturated power amplifiers -->
  <thead><tr>
    <th>Product</th><th>Min Freq (GHz)</th><th>Max Freq (GHz)</th>
    <th>Gain (dB)</th><th>OP1dB (dBm)</th><th>Psat (dBm)</th><th>PAE (%)</th>
    <th>Reference Conditions</th><th>Vdd Range (V)</th><th>Iccq (mA)</th> ...
  </tr></thead> ...
</table>
```

- **Model + URL:** the first cell holds `<a href="…/detail/sku/{MODEL}">{MODEL}</a>`
  — text is the model; `href` is the full product URL (used directly as `Candidate.url`).
- The two tables have **different** columns (LNA table has NF/OIP3; PA table has
  Psat/PAE, no NF/OIP3). ⇒ map by **header name**, not column index, and parse
  both tables.
- Empty cell (`""`) = "not specified" → key omitted.

---

## 5. Column Mapping (header → ontology)

Headers are normalised (lowercase, strip punctuation/whitespace) before matching,
because spacing varies between tables (`Gain(dB)` vs `Gain (dB)`).

| Header (either table) | Canonical param | Source unit | Stored as |
|-----------------------|-----------------|-------------|-----------|
| `Product` | `model` + `url` | — | from the `<a>` text / `href` |
| `Min Freq (GHz)` + `Max Freq (GHz)` | `freq_range` | GHz | `RawValue((min, max), "GHz")` |
| `Gain(dB)` / `Gain (dB)` | `Gain` | dB | `RawValue(value, "dB")` |
| `NF(dB)` | `NF` | dB | `RawValue(value, "dB")` (LNA table) |
| `OP1dB (dBm)` | `P1dB` | dBm | `RawValue(value, "dBm")` |
| `OIP3 (dBm)` | `IP3` | dBm | `RawValue(value, "dBm")` (LNA table) |
| `Psat (dBm)` | `Psat` | dBm | `RawValue(value, "dBm")` (PA table) |
| `Vdd Range (V)` | `VDD` | V | split `"low-high"` → `RawValue((low, high), "V")` |

**freq_range:** built from the separate Min/Max columns when both parse (DC parts
use `"0"`; the `0` low edge is kept). If either is missing, no `freq_range`.

**VDD:** the `Vdd Range (V)` cell is a `"low-high"` string (e.g. `2.7-5.0`,
`28-40`). Split into two floats → `RawValue((low, high), "V")`; the ontology
compares VDD with `contains`. A single value or unparseable cell → no VDD.

**Parameters left to the datasheet fallback (separately owned):**

- **Size** — the `Package (mm)` column is a package-type *label* (`1.5 DFN-6`,
  `7x6.5 DFN-6`, `SOIC-8`), not a clean dimension (square-side vs rectangle-edge
  vs no number on ~4 parts). Exact dimensions are datasheet-only. ⇒ datasheet.
- **MSL**, **Temperature** — datasheet PDF only (on no page).

This yields **7 reliable parameters in one request** (freq, Gain, NF, P1dB, Psat,
IP3, **VDD**); only Size/MSL/Temperature need the datasheet. No per-product
detail-page fetches and no JSON API are needed.

---

## 6. Candidate Construction (Pseudocode)

```python
PAGE_URL = "https://www.guerrilla-rf.com/products/amplifiers.html"
DETAIL_FALLBACK = "https://www.guerrilla-rf.com/products/detail/sku/{model}"

# normalised header -> (canonical, unit). "model"/"freq_low"/"freq_high" special.
COLUMN_MAP = {
    "product":        ("model",     None),
    "min freq ghz":   ("freq_low",  "GHz"),
    "max freq ghz":   ("freq_high", "GHz"),
    "gain db":        ("Gain",      "dB"),
    "nf db":          ("NF",        "dB"),
    "op1db dbm":      ("P1dB",      "dBm"),
    "oip3 dbm":       ("IP3",       "dBm"),
    "psat dbm":       ("Psat",      "dBm"),
    "vdd range v":    ("VDD",       "V"),
}

def _norm(h): return re.sub(r"\s+", " ", re.sub(r"[()/,.:\\]", " ", h.lower())).strip()
def _num(s):  ...   # "" / non-numeric -> None
def _range(s):      # "2.7-5.0" -> (2.7, 5.0); else None
    parts = (s or "").split("-")
    if len(parts) != 2: return None
    lo, hi = _num(parts[0]), _num(parts[1])
    return (lo, hi) if lo is not None and hi is not None else None

# for each <table id in {genericAmpFunctionTbl, satPATbl}>:
#   build header->index from <thead>; for each <tbody><tr>:
#     model = first cell <a> text; url = <a> href (or DETAIL_FALLBACK)
#     freq_range from min/max cols; VDD from "vdd range v" col via _range;
#     scalar params via COLUMN_MAP + _num
# search(): fetch page -> parse both tables -> drop_paramless(...)
```

### Example rows

```python
# GRF2003 (LNA table)
Candidate(model="GRF2003", manufacturer="Guerrilla RF",
    url="https://www.guerrilla-rf.com/products/detail/sku/GRF2003",
    raw_params={
        "freq_range": RawValue((0.1, 10.0), "GHz"),
        "Gain": RawValue(12.0, "dB"), "NF": RawValue(3.5, "dB"),
        "P1dB": RawValue(15.0, "dBm"), "IP3": RawValue(29.0, "dBm"),
        "VDD": RawValue((2.7, 5.0), "V"),
    }, source="table")

# GRF0005 (PA table) — DC-coupled, no NF/IP3 column; Psat present
Candidate(model="GRF0005", ...,
    raw_params={
        "freq_range": RawValue((0.0, 12.0), "GHz"),
        "Gain": RawValue(18.9, "dB"), "Psat": RawValue(38.7, "dBm"),
        "VDD": RawValue((28.0, 40.0), "V"),
    }, source="table")
```

---

## 7. Test Plan

### Fixture file

**Path:** `tests/fixtures/guerrillarf_amplifiers.html` — a trimmed page with both
`<table id="genericAmpFunctionTbl">` and `<table id="satPATbl">`, each with their
`<thead>` and a few representative `<tbody>` rows:

- A full LNA row (GRF2003: freq, Gain, NF, P1dB, IP3, VDD).
- An LNA row with an empty scalar (→ that param absent).
- A PA row (GRF0005: DC-coupled `0` low edge; Psat present; no NF/IP3 column; VDD `28-40`).
- A row with an empty `Vdd Range` (→ no VDD).

### Assertions (offline, no network) — call an internal `_parse_html(html)`:

```python
def test_parses_both_tables()              # rows from LNA + PA tables
def test_model_url_manufacturer_source()   # model + detail URL from <a>; "Guerrilla RF"; "table"
def test_freq_range_from_min_max_ghz()     # (0.1, 10.0) GHz
def test_dc_coupled_zero_low_edge()        # GRF0005 -> (0.0, 12.0)
def test_vdd_range_parsed()                # "2.7-5.0" -> RawValue((2.7,5.0),"V")
def test_pa_row_has_psat_no_nf()           # PA table: Psat present, NF absent
def test_empty_scalar_absent()
def test_empty_vdd_omitted()
def test_missing_table_raises_adaptererror()
```

Plus helper tests for `_norm`, `_num`, `_range`.

### Integration test (marked network, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    res = GuerrillaRFAdapter().search(QuerySpec("amplifier", []))
    assert res and all(c.manufacturer == "Guerrilla RF" for c in res)
    assert any("VDD" in c.raw_params for c in res)   # VDD now comes from the table
```

---

## 8. Rate Limiting Strategy

- **One request per `search()` call** — the whole amplifier list (both tables) is
  on a single page; no pagination, no per-product fetches.
- **Minimum inter-request delay:** **2 seconds** (`config.yaml` →
  `rate_limits.guerrillarf.delay_seconds`, default `2.0`); robots.txt sets no
  Crawl-delay.
- **Cache (T10):** SQLite cache serves the page after the first fetch.
- **User-Agent:** browser-style UA (consistent with the other adapters).

---

## 9. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Page layout / table `id`s change | Medium | Parse by `<table id>` then header-name mapping (not column index); missing tables → `AdapterError` (REQ-3.6). |
| R2 | Header spelling/spacing differs between the two tables | Resolved | `_norm` normalises before matching `COLUMN_MAP`. |
| R3 | `Min/Max Freq` or `Vdd Range` format changes | Low-Medium | `_num`/`_range` parse defensively; non-conforming → param omitted (UNKNOWN), never a crash. |
| R4 | Rows are JS-injected rather than server-rendered | Low | Verified: 137+22 rows are in the raw HTML; DataTables only wraps them. If this changes, a saved fixture still tests parsing; live fetch would need review. |
| R5 | A non-amplifier sneaks onto the page | Low | The page is the vendor's curated amplifier list (two amplifier tables); no category field needed. |
| R6 | Paramless rows (e.g. a header/spacer row) | Resolved | `search()` applies the shared `drop_paramless` filter. |

### Open questions for implementation

- **OQ-1:** Confirm Min/Max Freq columns are always GHz (headers say `(GHz)`).
- **OQ-2:** `Vdd Range` for some GaN parts encodes two discrete bias points
  (e.g. "28 and 40 V") as a range string. Treating it as a `(low, high)` band for
  the `contains` rule is acceptable; revisit if precision matters.
- **OQ-3:** Size precision — `Package (mm)` is approximate; exact size stays a
  datasheet-fallback concern.

---

## Summary

- **Source:** single `httpx.get` to `/products/amplifiers.html` — two
  server-rendered tables (`genericAmpFunctionTbl`, `satPATbl`), parsed with
  `selectolax` (no JS, robots-allowed). Replaces the JSON API.
- **Parsing:** map by normalised header across both tables; model + URL from the
  first cell's `<a>`; `""` = missing.
- **Scope (7 params, one request):** Frequency (Min/Max → GHz), Gain, NF, P1dB
  (`OP1dB`), Psat, IP3 (`OIP3`), and **VDD** (`Vdd Range` → range). No JSON API,
  no per-product detail fetches.
- **Datasheet fallback (survivors only):** Size (`Package` too ambiguous), MSL,
  Temperature.
- **Reuses** shared `drop_paramless`.
- **Files to create:** `rf_finder/adapters/guerrillarf.py`,
  `tests/adapters/test_guerrillarf.py`, `tests/fixtures/guerrillarf_amplifiers.html`.

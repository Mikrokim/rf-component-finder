# T8 Plan — Qorvo Adapter

> **Task:** T8 from tasks.md — `adapters/qorvo.py` (a new "site adapter" under the
> same T8 pattern as Mini-Circuits, Analog Devices, Guerrilla RF, VectraWave).
> **Phase:** Plan only (Phase A). No code written in this document.
> **Date:** 2026-07-01
> **Investigator:** Phase A planning (findings verified live via `httpx`/`selectolax`).
> **Resolves open items:** request mechanism and data-fixture for Qorvo.
> Manufacturer-specific requirements: [requirements.md](requirements.md).

---

## 1. Request Mechanism Finding

### Source chosen: the full product-list page (HTML), NO query parameters

Three candidate sources were investigated and verified live:

| Source | Verdict |
|--------|---------|
| `/products/product-list/?categoryID=ca0003` (parametric filter) | ❌ **robots-disallowed** (`Disallow: /*?*` blocks any query string) |
| `/api/...` endpoints | ❌ **robots-disallowed** (`Disallow: /api`) |
| Subcategory pages `/products/amplifiers/low-noise-amplifiers` | ❌ tables are **JS-loaded** ("Loading Product Tables") — not in raw HTML |
| **`/products/product-list/`** (no query params) | ✅ **chosen** — server-rendered, robots-allowed, all products in one GET |

### Findings (`/products/product-list/`)

| Question | Answer |
|----------|--------|
| URL | `https://www.qorvo.com/products/product-list/` — **no query string** (the query-param form is robots-disallowed) |
| Method | **HTTP GET** |
| Response | HTTP 200, ~5.3 MB, `Content-Type: text/html` |
| Rendering | **Server-rendered** — all rows present in raw HTML (verified: no "Loading Product Tables" placeholder; `selectolax` sees 77 tables / 1000 part rows). No JavaScript, no playwright. |
| Content | **ALL** Qorvo products: 77 category tables (amplifiers, switches, filters, PMICs, …). The adapter filters to the amplifier categories. |
| Server-side filtering | None available compliantly; the adapter filters client-side by category title. |

### Conclusion

One `httpx.get` to `/products/product-list/`, parse with `selectolax`, keep only
the amplifier category tables, map columns by header name, return `Candidate`
objects. The Verifier applies the user's constraints.

---

## 2. robots.txt Summary

URL: `https://www.qorvo.com/robots.txt` (fetched live).

```
User-agent: *
Disallow: /*?*                 # any URL with a query string
Disallow: /block-diagram-print
Disallow: /compare-product
Disallow: /api
Disallow: /*.pdsc

Allow: /*?year=all&company=all&type=all
Allow: /*?topic=all&technology=all

Sitemap: https://www.qorvo.com/sitemap.xml        (no Crawl-delay)
```

**Key conclusion:** `/products/product-list/` (no query string) matches **none**
of the Disallow rules and there is no blanket `Disallow: /`, so fetching it is
compliant (NFR-6). The parametric `?categoryID=…` form and the `/api` family are
off-limits — we deliberately do **not** use them.

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/qorvo.py` | **Create** | The Qorvo adapter (main deliverable) |
| `tests/adapters/test_qorvo.py` | **Create** | Offline unit tests using the HTML fixture |
| `tests/fixtures/qorvo_product_list.html` | **Create** | Trimmed snapshot: a few amplifier category blocks + one non-amplifier block (to prove filtering) |

Reuses the shared `drop_paramless` helper in `base.py`. DC-low handling is
inline (`"DC"` → `0.0`), not the `freq_range_from_bandwidth` helper.

---

## 4. HTML Structure

The listing lives in `div.static-tables-container`. Each category is one block:

```html
<div class="static-tables-container container">
  <div id="pst_ta0004" class="pst pst-open pst-mini">
    <div class="pst-header">
      <h3 class="pst-header-title">Low Noise Amplifiers <span class="pst-header-amount">(69)</span></h3>
    </div>
    <table class="pst-table">
      <tbody id="results_ta0004">
        <tr>                                <!-- HEADER ROW: <th> cells -->
          <th>...<div class="pst-col-header-title">Frequency Min</div>
                 <div class="pst-col-header-subtitle">GHz</div>...</th>
          ...
        </tr>
        <tr>                                <!-- DATA ROW: <td> cells -->
          <td><div class="pst-part-ref">
                <a href="/products/p/CMD263" class="pst-part-ref-name">CMD263</a></div></td>
          <td><div class="pst-data">5</div></td>          <!-- Frequency Min -->
          <td><div class="pst-data">11</div></td>         <!-- Frequency Max -->
          <td><div class="pst-data">23</div></td>         <!-- Gain -->
          ...
        </tr>
      </tbody>
    </table>
  </div>
  ...  (77 blocks total)
</div>
```

- **Category name:** `h3.pst-header-title` text (strip the trailing `(N)` badge).
  This is the **only** signal for "is this an amplifier?" — filter on it.
- **Column header:** each `<th>` has a `div.pst-col-header-title` (name) and an
  optional `div.pst-col-header-subtitle` (**unit**, e.g. `GHz`, `dBm`). Map by
  the normalised title; read the unit from the subtitle (**do not hard-code** —
  frequency is GHz in most categories but **MHz** in CATV/Driver/Gain-Block).
- **Model + URL:** first cell's `<a class="pst-part-ref-name" href="/products/p/{MODEL}">`
  — text is the model; `href` (prefixed with the origin) is `Candidate.url`.
- **Cell value:** `div.pst-data` text. Empty / `"N/A"` = not specified → key omitted.
- The first `<tr>` in each `<tbody>` is the header (`<th>` cells, no `<a>`); skip
  rows with no `<td>` / no part-ref anchor.

---

## 5. Amplifier Category Filter (Layer 1)

Keep a block only if its `h3` title (badge stripped) is one of these **12 core
amplifier categories** (verified present on the page, ~435 parts total):

```
CATV Amplifiers                     Low Noise Amplifiers
CATV Hybrid Amplifiers              Low Noise Amplifiers with Bypass
Digital Variable Gain Amplifiers    Low Phase Noise Amplifiers
Distributed Amplifiers              Power Amplifiers
Driver Amplifiers                   Spatium Amplifiers
Gain Block Amplifiers               High Frequency Amplifiers
```

**Deliberately excluded (borderline):**
- `2.4 GHz / 5 GHz Wi-Fi Power Amplifiers`, `Infrastructure Power Amplifier
  Modules` — these are **modules** with a different, messy column schema (values
  like `"22.5/22.0 (High Power Mode, w/o DPD)"`); out of scope for v1.
- `RF Power Amplifier Bias Controllers` — **not amplifiers** (bias controllers).

Matching is exact against a normalised (lower/trim) title set, so a new Qorvo
category won't be silently mis-included.

---

## 6. Column Mapping (header title → ontology)

Headers are normalised (lowercase, strip punctuation/whitespace). Unit comes
from the `pst-col-header-subtitle`, per column.

| Header title (any amp category) | Canonical param | Unit source | Stored as |
|---------------------------------|-----------------|-------------|-----------|
| `Part #` | `model` + `url` | — | `<a>` text / `href` |
| `Frequency Min` + `Frequency Max` | `freq_range` | subtitle (**GHz or MHz**) | `RawValue((min, max), unit)` |
| `Gain` | `Gain` | dB | `RawValue(value, "dB")` |
| `OP1dB` | `P1dB` | dBm | `RawValue(value, "dBm")` |
| `OIP3` | `IP3` | dBm | `RawValue(value, "dBm")` |
| `NF` | `NF` | dB | `RawValue(value, "dB")` |
| `Psat` | `Psat` | dBm (Spatium: **W**) | `RawValue(value, unit)` |
| `Voltage` (or `Vd`) | `VDD` | V | `"X to Y"` → `RawValue((low, high), "V")`; single → `(v, v)` |

**Special-cased `Gain` headers:** Spatium uses `Power Gain` / `Small Signal
Gain` (prefer `Small Signal Gain` → `Gain`); Digital VGA uses `Gain @ 0 dB
Atten` → `Gain`. All other categories have a plain `Gain`.

**freq_range:** built from the separate Min/Max columns. **`"DC"` in the min cell
→ `0.0`** (DC-coupled part; e.g. CMD192 = `DC–20 GHz`). If either edge is missing
(and not `"DC"`), no `freq_range`.

**VDD:** cell is `"X to Y"` (note: **" to " separator**, not `-` like Guerrilla),
e.g. `"2 to 4.5"`, `"5 to 8"`; or a single value like `"30"` → `(30, 30)`. GaN
parts label it `Vd` (drain) — map that to `VDD`; ignore `Vg` (gate, can be
negative). The ontology compares VDD with `contains`.

**Out of scope for v1 (Option A — leave UNKNOWN, consistent with the other
adapters):** `Size`, `MSL`, `Temperature`.
- `Size` — the page's `Package [mm]` is a package-outline string (`"6.0 x 6.0 x
  0.85"`, often `"N/A"` for bare **Die** parts, `""` for many); the die's true
  size is datasheet-only (`Die Dimensions`). The ontology's `Size` is a scalar
  with `max` compare, so it needs a reduction rule — deferred.
- `MSL`, `Temperature` — **not on any HTML page**; datasheet-PDF only (verified:
  TGA2227 datasheet has `Operating Temperature Range -40 to +85 °C`; MSL is
  absent for die parts). A datasheet fallback is a possible v2, not v1.

This yields **up to 7 params in one request** (freq, Gain, P1dB, IP3, NF, Psat,
VDD), coverage varying per category (a missing param → UNKNOWN; `drop_paramless`
keeps any part with ≥1 RF param). No per-product fetches, no JSON API.

---

## 7. Candidate Construction (Pseudocode)

```python
PAGE_URL = "https://www.qorvo.com/products/product-list/"     # NO query string
ORIGIN   = "https://www.qorvo.com"

AMP_CATEGORIES = frozenset({           # normalised h3 titles (badge stripped)
    "catv amplifiers", "catv hybrid amplifiers",
    "digital variable gain amplifiers", "distributed amplifiers",
    "driver amplifiers", "gain block amplifiers", "high frequency amplifiers",
    "low noise amplifiers", "low noise amplifiers with bypass",
    "low phase noise amplifiers", "power amplifiers", "spatium amplifiers",
})

# normalised header title -> (canonical, expect_unit_from_subtitle)
COLUMN_MAP = {
    "op1db": "P1dB", "oip3": "IP3", "nf": "NF", "psat": "Psat",
    "gain": "Gain", "small signal gain": "Gain", "gain @ 0 db atten": "Gain",
}
FREQ_MIN, FREQ_MAX = "frequency min", "frequency max"
VDD_HEADERS = {"voltage", "vd"}

def _norm(h):   ...  # lower, strip punctuation/whitespace
def _num(s):         # robust scalar parse (Qorvo cells are messier than any other source):
    ...              #   "" / "N/A" -> None;  "DC" -> 0.0
    ...              #   strip a leading >, <, >=, <=, ~ ("> 40" -> 40.0; "< 3.5" -> 3.5)
    ...              #   then take the FIRST numeric token via regex, so trailing
    ...              #   qualifiers/units/alternatives are ignored:
    ...              #     "35 (S21)" -> 35;  "13.4 @ 1950 MHz" -> 13.4;  "18 Vdc" -> 18
    ...              #     "9, 11" -> 9;  "5/8" -> 5   (first value; see R4/R9)
def _nums(s):        # every numeric token in s (for _vdd); strips >/< first
    ...
def _vdd(s):         # "2 to 4.5" -> (2.0, 4.5);  "30" -> (30.0, 30.0)
    ...              # multi-value supply -> (min, max) of all tokens:
    ...              #   "3, 5, 8" -> (3.0, 8.0);  "5/8" -> (5.0, 8.0);  "6, 28" -> (6.0, 28.0)
    ...              # "18 Vdc" -> (18.0, 18.0);  none found -> None

# for each div.pst block:
#   title = _norm(h3 text without "(N)");  if title not in AMP_CATEGORIES: skip
#   build header index: {norm(title): (col_index, subtitle_unit)}
#   for each tbody <tr> with <td> cells and a part-ref <a>:
#     model = <a> text;  url = ORIGIN + href
#     freq_range from FREQ_MIN/FREQ_MAX cols (+ their subtitle unit; "DC"->0)
#     VDD from first present of VDD_HEADERS via _vdd
#     scalar params via COLUMN_MAP + _num (+ subtitle unit)
#     append Candidate(..., source="table")
# search(): fetch page -> parse -> drop_paramless(...)
```

### Example rows (real, from the live page)

```python
# CMD263 — Low Noise Amplifiers
Candidate(model="CMD263", manufacturer="Qorvo",
    url="https://www.qorvo.com/products/p/CMD263",
    raw_params={
        "freq_range": RawValue((5.0, 11.0), "GHz"),
        "Gain": RawValue(23.0, "dB"), "NF": RawValue(1.4, "dB"),
        "P1dB": RawValue(11.0, "dBm"), "IP3": RawValue(23.0, "dBm"),
        "VDD": RawValue((2.0, 4.5), "V"),
    }, source="table")

# CMD192 — Distributed Amplifiers (DC-coupled -> 0 low edge; Vd range)
Candidate(model="CMD192", ...,
    raw_params={
        "freq_range": RawValue((0.0, 20.0), "GHz"),
        "Gain": RawValue(19.5, "dB"), "NF": RawValue(1.9, "dB"),
        "P1dB": RawValue(24.5, "dBm"), "Psat": RawValue(26.0, "dBm"),
        "IP3": RawValue(31.0, "dBm"), "VDD": RawValue((5.0, 8.0), "V"),
    }, source="table")

# QPA2311 — Power Amplifiers (no NF/IP3 column; Psat present; single VDD)
Candidate(model="QPA2311", ...,
    raw_params={
        "freq_range": RawValue((5.3, 5.9), "GHz"),
        "Psat": RawValue(47.0, "dBm"), "Gain": RawValue(19.0, "dB"),
        "VDD": RawValue((30.0, 30.0), "V"),
    }, source="table")
```

---

## 8. Test Plan

### Fixture file

**Path:** `tests/fixtures/qorvo_product_list.html` — a trimmed
`div.static-tables-container` with a few representative blocks:

- **Low Noise Amplifiers** block: a clean row (CMD263) and a `Die` row with
  `Package = N/A` (proves Size is ignored, part still kept).
- **Distributed Amplifiers** block: CMD192 with `Frequency Min = "DC"` (→ 0.0)
  and `Vd = "5 to 8"`.
- **Power Amplifiers** block: QPA2311 (no NF/IP3 columns; single `Voltage = "30"`).
- A **non-amplifier** block (e.g. `Discrete Switches`) — must be filtered out.
- A row with an empty scalar cell → that param absent.

### Assertions (offline, no network) — call an internal `_parse_html(html)`:

```python
def test_only_amplifier_categories_kept()   # switch block filtered out
def test_model_url_manufacturer_source()    # /products/p/ URL; "Qorvo"; "table"
def test_freq_range_ghz()                    # (5.0, 11.0) GHz
def test_freq_min_dc_zero_low_edge()         # CMD192 "DC" -> (0.0, 20.0)
def test_freq_unit_from_subtitle()           # a CATV row parsed as MHz, not GHz
def test_vdd_range_to_separator()            # "5 to 8" -> RawValue((5.0,8.0),"V")
def test_vdd_single_value()                  # "30" -> (30.0, 30.0)
def test_vd_maps_to_vdd_vg_ignored()         # GaN: Vd used, negative Vg skipped
def test_pa_row_has_psat_no_nf()             # Power Amp: Psat present, NF/IP3 absent
def test_na_and_empty_cells_omitted()        # "N/A" / "" -> param absent
def test_size_msl_temperature_never_emitted()# v1 leaves these out
def test_missing_container_raises_adaptererror()
```

Plus helper tests for `_norm`, `_num` (incl. `"DC"`, `"1,000"`, parenthetical
junk), and `_vdd`.

### Integration test (marked network, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    res = QorvoAdapter().search(QuerySpec("amplifier", []))
    assert res and all(c.manufacturer == "Qorvo" for c in res)
    assert any("freq_range" in c.raw_params for c in res)
    assert len(res) > 300          # ~435 amplifiers expected
```

---

## 9. Rate Limiting Strategy

- **One request per `search()` call** — the entire catalog (all amplifier
  categories) is on a single page; no pagination, no per-product fetches.
- **Minimum inter-request delay:** **2 seconds** (`config.yaml` →
  `rate_limits.qorvo.delay_seconds`, default `2.0`); robots.txt sets no
  Crawl-delay.
- **Large response (~5.3 MB):** the **T10 SQLite cache** serves the page after
  the first fetch, so repeated searches don't re-download it.
- **User-Agent:** browser-style UA (consistent with the other adapters).

---

## 10. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Page layout / class names (`pst`, `pst-table`, `pst-data`) change | Medium | Parse by class + header-name mapping (not column index); no container → `AdapterError` (REQ-3.6). |
| R2 | Category title text changes / a new amp category is added | Medium | Exact normalised-title match against `AMP_CATEGORIES`; unknown titles are skipped, not mis-parsed. **Trade-off:** a renamed category silently drops until the set is updated. |
| R3 | Frequency unit differs per category (GHz vs MHz) | Resolved | Unit read from each column's `pst-col-header-subtitle`, never hard-coded. |
| R4 | Messy cell formats: `> 40` / `< 3.5` (guaranteed min/max), `35 (S21)`, `13.4 @ 1950 MHz`, `18 Vdc`, `"DC"`, `"1,000"` | Med | `_num` strips `>`/`<` and takes the leading numeric token, so all of these parse to a usable number (`"> 40"`→40 is the guaranteed value — conservatively correct for `min`/`max`); non-conforming → param omitted (UNKNOWN), never a crash. |
| R5 | VDD as a range/list: `"X to Y"`, `"5/8"`, `"3, 5, 8"`, `"6, 28"` (multiple supply options / GaN bias points) | Low | `_vdd` takes `(min, max)` of all numeric tokens → a `(low, high)` band for the `contains` rule (same stance as Guerrilla OQ-2). |
| R9 | Multi-band freq as a list: `"9, 11"` in Frequency Max (4 parts) | Low | `_num` takes the first value only → the 2nd band is dropped (known limitation). Too rare (4 parts) to special-case in v1; documented, not silently truncated. |
| R6 | Rows/tables are JS-injected rather than server-rendered | Low | Verified: 1000 rows are in raw HTML. A saved fixture still tests parsing if this changes. |
| R7 | Paramless / header / spacer rows | Resolved | `search()` applies the shared `drop_paramless` filter. |
| R8 | 5.3 MB page is heavy | Low | One request per search + T10 cache; no per-product fetches. |

### Open questions for implementation

- **OQ-1:** Spatium `Gain` choice — plan uses `Small Signal Gain`; confirm that's
  the more comparable figure vs `Power Gain`.
- **OQ-2:** Confirm no amplifier category ever splits Min/Max freq into a single
  combined column (all 12 verified as separate Min + Max today).
- **OQ-3:** Whether to add `Size` (packaged parts only) in a later iteration.

---

## Summary

- **Source:** single `httpx.get` to `/products/product-list/` (**no query
  string**) — one server-rendered page (~5.3 MB, 77 `pst-table` blocks), parsed
  with `selectolax` (no JS, robots-allowed). Parametric `?…` URL and `/api` are
  robots-disallowed and unused.
- **Selection (Layer 1):** keep only the **12 amplifier category** blocks by
  `h3` title (~435 parts); everything else (switches, filters, …) skipped. Then
  shared `drop_paramless`. The **Verifier** applies the user's constraints.
- **Parsing:** map by normalised header title across categories; unit from the
  per-column subtitle (GHz/MHz/dBm/…); model + URL from `pst-part-ref-name`;
  `"N/A"`/`""` = missing; `"DC"` → 0; VDD `"X to Y"` → range.
- **Scope (v1, Option A):** up to 7 params (freq, Gain, P1dB, IP3, NF, Psat,
  VDD). `Size`, `MSL`, `Temperature` left UNKNOWN (datasheet-only), consistent
  with the other adapters.
- **Reuses** shared `drop_paramless`.
- **Files to create:** `rf_finder/adapters/qorvo.py`,
  `tests/adapters/test_qorvo.py`, `tests/fixtures/qorvo_product_list.html`.

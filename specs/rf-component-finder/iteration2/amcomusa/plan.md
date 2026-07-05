# AmcomUSA Adapter — Plan

> **Task:** AmcomUSA adapter — `adapters/amcomusa.py` (Iteration 2, extends design.md §6.1–6.2)
> **Phase:** Plan (Phase A). Documents the confirmed request/parse strategy.
> **Date:** 2026-07-02
> **Investigator:** Phase A planning agent
> **SDD trace:** REQ-3.1, REQ-3.4, REQ-3.5, REQ-3.6, REQ-4.1, NFR-4, NFR-6 · design.md §6.1–6.2
> **Pattern:** Mirrors the Mini-Circuits adapter (server-side-rendered HTML table scrape).

---

## 1. Request Mechanism Finding

### Method used

Live `httpx.get` (browser User-Agent + Accept header) to a category listing page,
e.g. `https://www.amcomusa.com/categories/low-noise-amplifier-modules`. Response
captured and parsed; scripts inspected for any AJAX/JSON data source.

### Findings

| Question | Answer |
|----------|--------|
| Base URL | `https://www.amcomusa.com` |
| Method for initial load | **HTTP GET per category page, no query parameters** |
| HTML rendering | **Fully server-side rendered** (ASP.NET WebForms) — all product rows present in the initial GET body |
| Table element | `<table id="allPnTable">` |
| Rows per category | ~48 (varies by category) |
| AJAX / XHR / JSON API for table data? | **No** — the only scripts are plugins / gtag; no `serverSide`/`ajaxSource` |
| Where do cell values live? | **In the cell text** — NOT in a `ddtf-value` attribute (the attribute is absent live; read text, prefer `ddtf-value` only if present for forward-compat) |
| Server-side spec filter? | **No** — no filter form; return all rows |
| JavaScript required to see the table? | **No** |

### Conclusion: httpx (not playwright)

The complete per-category table is in the initial GET, so `httpx` + `selectolax`
suffices. `playwright` is not needed.

The adapter will:
1. GET each amplifier category page in turn.
2. Parse `table#allPnTable` on each; map columns → canonical by header name.
3. Apply no server-side filtering; return **all** rows as `Candidate`s; the
   Verifier applies all constraints (REQ-4.1).

> **Design note (vs design.md §6.2):** Unlike Mini-Circuits' single amplifier
> page, AmcomUSA splits amplifiers across **multiple category pages**, so the
> adapter fetches ~9 pages per search. Each is fetched independently for
> resilience (NFR-4): a failed page is skipped; `AdapterError` is raised only if
> **all** pages fail.

---

## 2. robots.txt Summary

URL: `https://www.amcomusa.com/robots.txt` (HTTP 200, fetched live)

```
User-agent: *
Allow: /
Disallow: /admin
Disallow: /privacy
```

**Key conclusions:**
- `/categories/*` and `/product-details/*` are **allowed** — scraping permitted.
- Only `/admin` and `/privacy` are disallowed; the adapter touches neither.
- `Candidate.url` is set to the product-details page (allowed) for reporter use.

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/amcomusa.py` | **Create** | The AmcomUSA adapter (main deliverable) |
| `tests/test_amcomusa.py` | **Create** | Offline unit tests (inline HTML builder for column→canonical mapping) |

No existing files edited except `__main__.py` (add the registration import).

---

## 4. HTML Structure and Parsing Strategy

### Two page shapes

1. **Table categories (8):** a `<table id="allPnTable">` with a `<thead>` whose
   **last** `<tr>` holds the real column headers (earlier rows are filter/search
   rows). Data cells align 1:1 with the header columns; the value is the cell
   **text** (a `ddtf-value` attribute is read in preference *if present*, for
   forward-compat). The part number lives in `<td name="product"> → <a>` (text =
   model, href = product URL).

2. **Card category (1) — Rackmount HPAs:** no parametric table, only product
   cards. Only a part number + product link are recoverable, so those Candidates
   carry empty `raw_params` and verify as `partial`.

### Selector strategy (`selectolax`)

```python
tree = HTMLParser(html)
table = tree.css_first("table#allPnTable")          # None -> category has no table (skip)
thead = table.css_first("thead")
header_row = thead.css("tr")[-1]                    # LAST header row = real columns
col_names = [_normalize_header(th.text(strip=True)) for th in header_row.css("th")]
for row in table.css_first("tbody").css("tr"):
    pn_cell = row.css_first('td[name="product"]')   # part number + href
    cells = row.css("td")                           # data cells, aligned to col_names
```

### Header normalization

Lowercase, replace `().,:/\` with spaces, collapse whitespace. Frequency headers
carry the unit (`Fmin (GHz)` / `Fmin (MHz)`), so the unit is detected per column.

---

## 5. Column Mapping

Headers differ per category (Pout vs Psat; MHz vs GHz; Vd vs Bias), so mapping is
by **normalized header name**, never by fixed index (REQ-3.4).

| Normalized header | Canonical param | Source unit | Notes |
|-------------------|-----------------|-------------|-------|
| `fmin …` | `freq_range` (low) | MHz or GHz (per header) | combine with Fmax |
| `fmax …` | `freq_range` (high) | MHz or GHz (per header) | combine with Fmin |
| `gain db` | `Gain` | dB | |
| `nf db` | `NF` | dB | |
| `p1db dbm` | `P1dB` | dBm | |
| `pout dbm` / `psat dbm` | `Psat` | dBm | both map to Psat |
| `oip3 dbm` | `IP3` | dBm | |
| `vd v` / `bias v` | `VDD` | V | both map to VDD |
| Package, ECCN, Connector, … | — | — | skipped |

- **Frequency unit** is taken from the header (`MHz` vs `GHz`); the Verifier
  normalises to canonical GHz.
- **Dual-supply cells** like `"+8 / -0.75"` are not a single float → `_parse_float`
  returns None → VDD stays UNKNOWN (correct).

---

## 6. Candidate Construction (Pseudocode)

```python
SCALAR_COLUMN_MAP = {
    "nf db": ("NF","dB"), "gain db": ("Gain","dB"), "p1db dbm": ("P1dB","dBm"),
    "pout dbm": ("Psat","dBm"), "psat dbm": ("Psat","dBm"), "oip3 dbm": ("IP3","dBm"),
    "vd v": ("VDD","V"), "bias v": ("VDD","V"),
}
_MISSING = {"", "-", "n/a", "N/A", "TBD", "tbd"}

def _parse_float(t):
    t = t.strip()
    return None if (not t or t in _MISSING) else _try_float(t)

for row in tbody_rows:
    a = row.css_first('td[name="product"] a') or cells[0].css_first("a")
    model = a.text(strip=True)                       # skip row if empty
    url = absolutise(a.attributes["href"])           # product-details page
    raw = {}; f_low=f_high=None; f_unit="GHz"
    for i, cell in enumerate(cells):
        norm = col_names[i]
        val = _parse_float(cell.text(strip=True))
        if val is None: continue
        if norm.startswith("fmin"): f_low, f_unit = val, unit_of(norm)
        elif norm.startswith("fmax"): f_high, f_unit = val, unit_of(norm)
        elif norm in SCALAR_COLUMN_MAP:
            canon, u = SCALAR_COLUMN_MAP[norm]; raw[canon] = RawValue(val, u)
    if f_low is not None and f_high is not None:
        raw["freq_range"] = RawValue((f_low, f_high), f_unit)
    yield Candidate(model, "AmcomUSA", url, raw, source="table")
```

---

## 7. Test Plan

**Offline unit tests** (`tests/test_amcomusa.py`) build small inline `allPnTable`
snippets and call `_parse_table_html` directly — no network:

- `test_maps_scalar_and_frequency_columns` — Fmin/Fmax → freq_range; Gain/P1dB mapped.
- `test_missing_cell_is_skipped` — a `"-"` cell → param absent (not None).
- `test_vd_column_maps_to_vdd` / `test_bias_column_maps_to_vdd` — both supply
  headers → canonical VDD (V).
- `test_dual_supply_string_is_unknown` — `"+8 / -0.75"` → VDD absent.

**Integration test** (marked `@pytest.mark.network`, skipped by default): a live
`search()` returns amplifier Candidates with `manufacturer == "AmcomUSA"`.

---

## 8. Rate Limiting Strategy

- ~9 category-page GETs per search (no per-product fetches for table categories).
- **Minimum inter-request delay:** 1.5 s between live fetches (`_MIN_DELAY_SECONDS`).
- **Retry:** transient failures (e.g. SSL `UNEXPECTED_EOF`) retried up to 3× with
  a 1 s backoff, keeping the rate-limit clock honest between attempts.
- **User-Agent:** browser-style UA (plain bot UAs may be rejected by the CDN).
- **Cache (T10):** once implemented, responses are served from cache on repeat.

---

## 9. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | A category page changes its column set | Medium | Header-name mapping (not index) |
| R2 | New missing-value sentinel beyond `-`/`N/A`/`TBD` | Low | `_parse_float` handles the common set; extend as needed |
| R3 | A category slug 404s or is a parent page without a table | Medium | `table#allPnTable` absent → skip that category (empty list), continue others (NFR-4) |
| R4 | Rackmount HPAs (cards) yield paramless Candidates | Resolved | Emit model+URL only → verify as `partial` |
| R5 | Dual-supply / range cells for a mapped param | Low | `_parse_float` → None → param UNKNOWN |

### Open questions
- **OQ-1:** Should the card-only Rackmount category be included at all, or dropped?
  Recommend include (model+URL, `partial`) so the part is discoverable.

---

## Summary

- **Fetch:** one `httpx.get` per amplifier category page (~9); server-side-rendered
  HTML, no JS/AJAX/API.
- **Parse:** `selectolax` on `table#allPnTable`; header-name column mapping; values
  in cell **text**.
- **robots.txt:** category & product pages allowed (only `/admin`, `/privacy` blocked).
- **Resilience (NFR-4):** per-category isolation; fail only if every page fails.
- **Files:** `rf_finder/adapters/amcomusa.py`, `tests/test_amcomusa.py`, plus the
  `__main__.py` registration import.

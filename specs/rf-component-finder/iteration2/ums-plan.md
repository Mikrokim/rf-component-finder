# UMS-RF Adapter — Investigation & Plan

> **Task:** UMS (United Monolithic Semiconductors, ums-rf.com) amplifier adapter
> (iteration 2; counterpart to the MACOM and iteration-1 Mini-Circuits adapters).
> **Phase:** Plan only (Phase A). **No code written.**
> **Date:** 2026-06-29
> **Investigator:** Phase A planning (live network inspection of www.ums-rf.com)
> **Methodology:** Spec-Driven Development (SDD) — same flow that produced
> [macom-plan.md](macom-plan.md) and [iteration1/t8-plan.md](../iteration1/t8-plan.md).
> **Decision rule applied:** REQ-3.3 — *prefer an official API; else a parametric
> URL search; else scrape the results table.*

---

## 0. Executive summary

| | Finding |
|---|---|
| **Official API?** | **Partial / unusable for specs.** A WordPress REST API exists (`/wp-json/wp/v2/product`, **274 products**, paginated) but returns only id/slug/title/excerpt — the spec fields (ACF/meta) are **not exposed** (`"acf":[]`). Useful only as an index / count sanity-check, **not** for specs. |
| **Parametric URL query?** | **Yes — this is the chosen method.** The Product Finder is a pure URL-driven form: `/products/?function=<slug>&…` triggers **server-side** filtering and renders a full **parametric HTML table** (one column per spec). |
| **HTML scraping?** | **Yes**, of the server-rendered parametric table. **Plain `httpx`; no JavaScript, no Playwright** (unlike MACOM — the data is real server-rendered HTML, not embedded JSON). |
| **Chosen method** | One `httpx` GET **per amplifier sub-type** to `/products/?function=<slug>&<full-range params>` → parse the `<thead>` labels + `<tr class="product-row">` cells → map by header label to canonical params. |
| **Fetch cost** | **5 GETs** cover **all 156 amplifiers** (LNA 47, HPA 61, MPA 36, Analog VGA 7, Digital VGA 5). No per-product fetches. |
| **Architecture fit** | Identical to MACOM / Mini-Circuits: fetch all rows, map columns, return every `Candidate`; the Verifier filters. Self-registers; no core change (NFR-3). |

**The two key insights:**

1. **The plain `/products/` page is the WRONG source.** Unfiltered, it renders a
   "catalog" template whose rows carry **only** Reference / Description / Case —
   *no* numeric specs. Adding a **`?function=<slug>`** query switches the page to
   the **"archive-product" template**, which renders the full parametric table
   (Gain, NF, P1dB, IP3, Psat, RF Bandwidth, Bias…) as real `<td>` cells. **You
   must use the `?function=` URL to get specs.**
2. **The frequency/power sliders are broken server-side.** Passing a *narrowed*
   `frequency-min/max` or `power-min/max` returns **0 rows**. So we always send
   the **full default range** (`frequency-min=0&frequency-max=105.5&power-min=0&power-max=200&power-unit=watt`)
   and let the **Verifier** do all numeric filtering. Only `function` (and
   `reference`) filter reliably. This fits the architecture (return all, Verifier
   filters) anyway.

---

## 1. Request Mechanism Finding (resolves REQ-3.3 for UMS)

### Method used

Live `Invoke-WebRequest`/`httpx` GETs with a browser-style User-Agent against:
the site root, `/robots.txt`, `/sitemap_index.xml`, `/products/` (unfiltered and
`?function=`-filtered), a sample product page, the WP REST API
(`/wp-json/`, `/wp-json/wp/v2/product`), and the Finder's JS bundles
(`products-form.js`, `archive-product.js`). Responses captured and parsed.

### Findings

| Question | Answer |
|----------|--------|
| Platform | **WordPress 7.0**, custom post type **`product`**, theme `ums`. No Cloudflare. |
| Entry URL (specs) | `https://www.ums-rf.com/products/?function=<slug>&frequency-min=0&frequency-max=105.5&power-min=0&power-max=200&power-unit=watt` |
| Method for load | **HTTP GET** with query string; **server-side** rendering of the filtered table. |
| Official/public API? | **WP REST exists** (`/wp-json/wp/v2/product`, 274 products) but **exposes no specs** (`acf` empty). Not usable for parametric data. |
| Server-side parametric filter via URL? | **Yes for `function`** (e.g. `amplifier-lna` → 47 rows). **No for frequency/power** (sliders return 0 rows — broken). |
| Is the parametric data in the raw HTML? | **Yes** — as real `<td class="characteristic-cell">` cells in the `?function=`-filtered page. The **unfiltered** `/products/` page has **no** spec columns (catalog view only). |
| JS required to *see* the data? | **No.** `archive-product.js` only adds **column-sort** behavior; the data and the `<thead>` labels are server-rendered. |
| Front-end stack | WordPress + custom theme; Cookiebot/Matomo. Listing is server-rendered HTML. |
| Rows per category | LNA 47, HPA 61, MPA 36, Analog VGA 7, Digital VGA 5 (= **156** amplifiers). All rows present in raw HTML (some `hidden-row` via CSS "View more" — ignore that class). |

### Conclusion: httpx (not Playwright)

The full dataset for each amplifier sub-type is in the initial GET response as
server-rendered table cells. `httpx` is sufficient; Playwright is **not** needed
(there is no client-rendered grid to wait for — contrast MACOM, where the *data*
was JS-embedded). This matches design.md §6.2 / D-1: Playwright is a fallback only
for genuinely JS-rendered data.

---

## 2. robots.txt Summary

URL: `https://www.ums-rf.com/robots.txt` (HTTP 200, fetched live). **No Cloudflare.**

```
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php

Sitemap: https://www.ums-rf.com/sitemap_index.xml
```

**Key conclusions:**

- **The `/products/` path is allowed** — only `/wp-admin/` is disallowed.
  Scraping the product listing (filtered or not) is permitted.
- **No `Crawl-delay` directive** is specified. We still **self-impose** a modest
  polite delay between the handful of category GETs (config default; see §8 and
  §9 OQ-U3), then serve from cache.
- The sitemap splits products across `product-sitemap1.xml` / `product-sitemap2.xml`
  (consistent with the 274 REST count) — a possible enumeration cross-check, not
  needed for the chosen method.
- A **browser-style User-Agent** returns clean 200s. No bot-challenge observed;
  identity is an honest product-search retriever (see §9 R2 / OQ-U1).

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/ums.py` | **Create** | The UMS adapter (main deliverable). `manufacturer = "UMS"`, `supported_components = {"amplifier"}`. |
| `tests/adapters/test_ums.py` | **Create** | Offline unit tests using saved HTML fixtures. |
| `tests/fixtures/ums_amplifier_lna.html` | **Create** | Trimmed snapshot of an `?function=amplifier-lna` table (NF-bearing columns). |
| `tests/fixtures/ums_amplifier_hpa.html` | **Create** | Trimmed snapshot of an `?function=amplifier-hpa` table (IP3 + Psat columns, no NF) — proves per-category column differences. |

No existing core files need editing. The adapter self-registers via the
`@register` decorator (design.md §6.1), so no core change is required (NFR-3).
Config/cache wiring (rate limit + cache) follows the same path the MACOM /
Mini-Circuits adapters use.

> **Naming note (OQ-U2):** `manufacturer` value — `"UMS"` (common name) vs
> `"UMS-RF"` (domain) vs `"United Monolithic Semiconductors"` (legal). *Recommend:*
> `"UMS"`. File `ums.py`. Confirm at implementation.

---

## 4. Data Extraction (HTML structure)

### Where the data lives

The `?function=<slug>`-filtered page renders, per category, a `<table>` whose
**`<thead>` holds the column labels** and whose **`<tbody>` holds one
`<tr class="product-row">` per part**. The spec `<th>` cells contain nested
sort-caret markup, so header text must be parsed **nested-tolerantly** (strip
inner tags). The plain Reference/Description/Case `<th>`s are simple text.

One row (HPA example, `CHA5659-98F`):

```html
<tr class="product-row status-active">
  <td class="reference-cell">
    <a href="https://www.ums-rf.com/products/cha5659-98f/" class="product-link">CHA5659-98F</a>
    <div class="technical-doc-link"><a href="https://…/CHA5659-98F-Full-0301.pdf" class="doc-link"></a></div>
  </td>
  <td class="status-cell"><h3 class="product-subtitle">…GHz … Power Amplifier</h3></td>
  <td class="characteristic-cell">800</td>   <!-- Bias (mA) -->
  <td class="characteristic-cell">6</td>     <!-- Bias (V)  -->
  <td class="characteristic-cell">22</td>    <!-- Gain (dB) -->
  <td class="characteristic-cell">38.5</td>  <!-- IP3 (dBm) -->
  <td class="characteristic-cell">30</td>    <!-- P-1dB OUT (dBm) -->
  <td class="characteristic-cell">36</td>    <!-- RF Bandwidth (GHz) (Min) -->
  <td class="characteristic-cell">43.5</td>  <!-- RF Bandwidth (GHz) (Max) -->
  <td class="characteristic-cell">31</td>    <!-- Sat. Output Power (dBm) -->
  <td class="characteristic-cell">Die</td>   <!-- Case -->
</tr>
```

### Extraction strategy

1. Parse `<thead>` → ordered list of header labels (nested-tolerant strip).
   The `characteristic-cell` columns correspond to **`headers[2:]`** (everything
   after Reference, Description). **Map by header label, NOT by fixed position** —
   categories have different column sets (§5).
2. For each `<tr class="product-row">`:
   - `reference` ← text of `a.product-link` (→ `Candidate.model`).
   - `subtitle` ← `h3.product-subtitle` (description; embeds the band as text).
   - `datasheet` ← `a.doc-link` href (reserved for the datasheet-confidence path).
   - `url` ← `a.product-link` href (`/products/<slug>/`; report link, never fetched).
   - cells ← ordered `td.characteristic-cell` text values; `zip(headers[2:], cells)`.
3. For each `(label, value)`, look up the canonical mapping (§5); **skip when the
   cell is empty or `"-"`** (→ param absent → Verifier marks UNKNOWN, not FAIL).

> **Why not parse the unfiltered `/products/` page or the per-product page?** The
> unfiltered catalog has no spec columns. The per-product page *does* have a spec
> grid (`div.ums-characteristics-grid`, `spec-label`/`spec-value` pairs), but using
> it would require **one fetch per part** (156+). The `?function=` table gives the
> same specs for a whole category in **one** request — strictly better. (The
> per-product grid is documented as a back-pocket alternative — see §9 R4.)

---

## 5. Spec → Canonical Ontology Mapping (REQ-3.4)

Confirmed by reading the `<thead>` of **all five** amplifier sub-type pages. Only
the amplifier-ontology params ([ontology/parameters.py](../../../rf_finder/ontology/parameters.py))
are mapped; all other columns are **skipped**. The map is keyed by the
**normalized** header label (lowercase, strip, collapse whitespace) → `(canonical, unit)`.

| UMS column header (normalized) | Source unit | Canonical param | Notes |
|---|---|---|---|
| `rf bandwidth (ghz) (min)` + `(max)` | GHz | `freq_range` | Combine into `RawValue((min,max), "GHz")`. Already GHz (no MHz conversion, unlike MACOM). |
| `gain (db)` | dB | `Gain` | |
| `noise figure (db)` | dB | `NF` | LNA / Analog VGA / Digital VGA only. |
| `p-1db out (dbm)` | dBm | `P1dB` | All sub-types. |
| `ip3 (dbm)` | dBm | `IP3` | HPA / MPA only. |
| `sat. output power (dbm)` | dBm | `Psat` | HPA / MPA / Digital VGA only. |
| `bias (v)` | V | `VDD` | All sub-types. Ontology comparison is `between` (scalar value checked within the user's band). |

**Skipped columns** (not in this iteration's ontology): `Bias (mA)`,
`Gain Control Range (dB)`, `Gain Flatness (+/-dB)`, `Dynamic Range (dB)` (Digital
VGA), `Case` (package form — Die/QFN/…, not the `Size` ontology param, which is mm).

### Per-sub-type coverage (confirmed from live `<thead>`s)

| Canonical | LNA | HPA | MPA | Analog VGA | Digital VGA |
|---|:--:|:--:|:--:|:--:|:--:|
| `freq_range` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `Gain` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `P1dB` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `VDD` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `NF` | ✅ | — | — | ✅ | ✅ |
| `IP3` | — | ✅ | ✅ | — | — |
| `Psat` | — | ✅ | ✅ | — | ✅ |

### Form-parameter → source (all 10 amplifier ontology params)

| Form parameter | Source | Detail |
|---|---|---|
| **Frequency** | ✅ GET (all) | RF Bandwidth (GHz) Min/Max |
| **Gain** | ✅ GET (all) | Gain (dB) |
| **P1dB** | ✅ GET (all) | P-1dB OUT (dBm) |
| **VDD** | ✅ GET (all) | Bias (V) |
| **Psat** | ⚠️ GET (HPA/MPA/Digital VGA) | else datasheet |
| **IP3** | ⚠️ GET (HPA/MPA) | else datasheet |
| **NF** | ⚠️ GET (LNA/Analog VGA/Digital VGA) | else datasheet |
| **Size** | ❌ Datasheet | table has only *Case* (package form), not mm |
| **MSL (1–5)** | ❌ Datasheet | no table column |
| **Temperature (op/storage)** | ❌ Datasheet | no table column |

**7 of 10** params are reachable from the GETs (4 universal, 3 sub-type-dependent);
**3** (Size, MSL, Temperature) require datasheet-PDF parsing → **deferred** (§9 OQ-U4),
resolving to UNKNOWN per the existing Verifier rule (never a wrongful FAIL).

**Mapping strategy:** a hard-coded `SPEC_MAP` keyed by normalized header label →
`(canonical, unit)`. Robust to column reordering and to the per-category column
differences (label-based, not positional). UMS uses the ontology's own names
directly (`IP3`, `Psat`, `NF`) — no MACOM-style synonym/encoding ambiguity.

---

## 6. Candidate Construction (pseudocode)

```python
BASE = "https://www.ums-rf.com"

AMPLIFIER_SLUGS = [
    "amplifier-lna", "amplifier-hpa", "amplifier-mpa",
    "amplifier-analogvga", "amplifier-digitalvga",
]

# Full default range — narrowing freq/power returns 0 rows (broken server-side).
RANGE_QS = "frequency-min=0&frequency-max=105.5&power-min=0&power-max=200&power-unit=watt"

SPEC_MAP = {                                   # normalized header -> (canonical, unit)
    "gain (db)":                 ("Gain",  "dB"),
    "noise figure (db)":         ("NF",    "dB"),
    "p-1db out (dbm)":           ("P1dB",  "dBm"),
    "ip3 (dbm)":                 ("IP3",   "dBm"),
    "sat. output power (dbm)":   ("Psat",  "dBm"),
    "bias (v)":                  ("VDD",   "V"),
    # RF Bandwidth (Min)/(Max) handled specially -> freq_range
}
FREQ_MIN_HDR = "rf bandwidth (ghz) (min)"
FREQ_MAX_HDR = "rf bandwidth (ghz) (max)"

def _category_url(slug):
    return f"{BASE}/products/?function={slug}&{RANGE_QS}"

def _parse_table(html, slug) -> list[Candidate]:
    headers = [_norm(h) for h in _thead_labels(html)]   # nested-tolerant strip
    char_headers = headers[2:]                           # skip Reference, Description
    out = []
    for row in _product_rows(html):
        model = _link_text(row)                          # a.product-link
        if not model:
            continue
        cells = _char_cells(row)                         # td.characteristic-cell, in order
        by = {h: v for h, v in zip(char_headers, cells)}

        raw = {}
        lo, hi = _num(by.get(FREQ_MIN_HDR)), _num(by.get(FREQ_MAX_HDR))
        if lo is not None and hi is not None:
            raw["freq_range"] = RawValue((lo, hi), "GHz")
        for hdr, (canon, unit) in SPEC_MAP.items():
            v = _num(by.get(hdr))                        # None for "", "-", non-numeric
            if v is not None:
                raw[canon] = RawValue(v, unit)

        out.append(Candidate(
            model=model,
            manufacturer="UMS",
            url=_link_href(row) or f"{BASE}/products/{model.lower()}/",
            raw_params=raw,
            source="table",
        ))
    return out

def search(spec) -> list[Candidate]:
    results = []
    for slug in AMPLIFIER_SLUGS:                          # 5 GETs, cached
        _rate_limit_guard()
        html = _get(_category_url(slug))
        results += _parse_table(html, slug)
    return results
```

`_num(text)` returns `float(text)` or `None` for `""` / `"-"` / non-numeric;
`_norm(s)` lowercases, strips, collapses whitespace.

### Worked example (CHA5659-98F, HPA)

```python
Candidate(
    model="CHA5659-98F",
    manufacturer="UMS",
    url="https://www.ums-rf.com/products/cha5659-98f/",
    raw_params={
        "freq_range": RawValue((36.0, 43.5), "GHz"),
        "Gain":       RawValue(22.0, "dB"),
        "IP3":        RawValue(38.5, "dBm"),
        "P1dB":       RawValue(30.0, "dBm"),
        "Psat":       RawValue(31.0, "dBm"),
        "VDD":        RawValue(6.0,  "V"),
        # NF absent (HPA table has no NF column) -> Verifier marks UNKNOWN -> partial
    },
    source="table",
)
```

---

## 7. Test Plan (NFR-7, offline)

### Fixtures

Trimmed slices of real `?function=` table HTML (a handful of rows each, **not**
the full pages), covering the per-category column differences and edge cases:

- `ums_amplifier_lna.html` — has `Noise Figure`, **no** IP3/Psat columns; include
  a row with a `-`/empty cell (→ that param must be absent from `raw_params`).
- `ums_amplifier_hpa.html` — has `IP3` + `Sat. Output Power`, **no** NF column;
  include a `Case`-only oddity and a non-numeric/blank spec cell.

### Assertions (no network)

```python
def test_parses_all_rows():               # len == number of product-row in fixture
def test_model_manufacturer_source():     # manufacturer == "UMS", source == "table"
def test_freq_range_combined_ghz():        # RawValue((min,max), "GHz")
def test_header_label_mapping():           # maps by <thead> label, not position
def test_per_category_columns():           # LNA has NF not IP3; HPA has IP3/Psat not NF
def test_missing_or_dash_cell_absent():    # "" / "-" -> key not in raw_params
def test_url_and_datasheet_captured():
def test_raises_adaptererror_when_no_table():   # bad HTML -> AdapterError
```

### Integration (marked `network`, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    results = UmsAdapter().search(QuerySpec("amplifier", [...]))
    assert len(results) > 140            # ~156 amplifiers across 5 sub-types
    assert all(c.manufacturer == "UMS" for c in results)
```

---

## 8. Rate-Limiting Strategy (NFR-6)

- **5 requests per `search()`** — one GET per amplifier sub-type; no pagination,
  no per-product fetches.
- **Inter-request delay:** robots specifies **no `Crawl-delay`**, so self-impose a
  modest polite default between the 5 category GETs. Read from `config.yaml`
  (`rate_limits.ums.delay_seconds`, **recommend default 3–5 s**; see §9 OQ-U3),
  enforced as a `time.sleep()` guard before each live fetch. Only incurred on
  cache miss.
- **Cache:** same SQLite/TTL mechanism as the other adapters, keyed by category
  URL. After first fetch, searches serve from cache and the delay never applies.
- **User-Agent:** browser-style UA (clean 200s; honest search-retriever identity).

---

## 9. Risks & Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | **Wrong template:** scraping unfiltered `/products/` yields rows with no specs (catalog view). | **High if not careful** | Always use the `?function=<slug>` URL (archive-product template). Fail loudly if no `characteristic-cell`/`<thead>` spec columns are found. |
| R2 | UA / identity. | Low | Browser-style UA; honest search retriever. No Cloudflare, no AI-bot blocks in robots. (OQ-U1) |
| R3 | **Broken freq/power server filter** (narrowed range → 0 rows). | **High (observed)** | Always send the full default range; never pass user constraints into the URL. Verifier does all numeric filtering. |
| R4 | UMS renames column headers or restructures the table. | Medium | Label-based `SPEC_MAP` (not positional); log unmapped headers; warn on large row-count drift. Back-pocket: per-product `ums-characteristics-grid` (`spec-label`/`spec-value`) if the table view changes. |
| R5 | New amplifier sub-type slug added (or a slug renamed). | Medium | Slugs come from `umsFilterData.product_types` embedded in `/products/`; optionally derive `AMPLIFIER_SLUGS` from it (filter `value` starting `amplifier-`) instead of hard-coding. |
| R6 | Some specs (IP3/Psat/NF) absent for a given sub-type; Size/MSL/Temperature absent entirely. | Expected | Omit absent params → Verifier marks UNKNOWN → `partial`, never FAIL (matches the required matching behavior). Datasheet params deferred (OQ-U4). |
| R7 | `Case` mistaken for `Size`. | Low | `Case` is package form (Die/QFN), **not** the `Size` (mm) ontology param — skip it. |
| R8 | Transient TLS resets observed during investigation. | Low | Retry with small backoff (the adapter's HTTP layer); 5 small GETs are cheap to retry. |

### Open questions for implementation (project register: [open-questions.md](../open-questions.md))

- **OQ-U1 — UA / crawler identity.** *Recommend:* browser-style UA (no robots
  restriction; honest search retriever). Confirm.
- **OQ-U2 — `manufacturer` string & file name.** `"UMS"` vs `"UMS-RF"` vs full
  legal name; file `ums.py` vs `umsrf.py`. *Recommend:* `"UMS"`, `ums.py`.
- **OQ-U3 — Self-imposed delay.** No robots `Crawl-delay`; pick a polite default
  between the 5 GETs. *Recommend:* 3–5 s. Confirm.
- **OQ-U4 — Datasheet path for Size / MSL / Temperature.** These live only in the
  per-part datasheet PDF (`a.doc-link`, captured now). *Recommend:* defer PDF
  parsing to the `datasheet`-confidence iteration; resolve to UNKNOWN for now.
- **OQ-U5 — Derive slugs vs hard-code.** Hard-code the 5 amplifier slugs, or parse
  them from the embedded `umsFilterData.product_types`? *Recommend:* hard-code for
  now (simple, explicit); note the dynamic option for when more component types
  are added (§10 expansion).

---

## 10. Summary

- **Method (REQ-3.3):** REST API exists but is spec-less → use the **parametric
  URL search** (`?function=<slug>`) and **scrape the server-rendered table**.
  Plain `httpx`, no Playwright.
- **Fetch:** **5 GETs** (one per amplifier sub-type) → **156 amplifiers** with
  specs. No per-product crawl. Always send the full freq/power range (server-side
  numeric filter is broken); Verifier filters.
- **Mapping:** `header label → canonical` via a label-keyed `SPEC_MAP`; combine
  RF Bandwidth Min/Max into `freq_range` (already GHz). Per-category column sets
  differ — IP3/Psat on power types, NF on low-noise/VGA types.
- **Coverage:** 7/10 ontology params from the GETs (freq, Gain, P1dB, VDD always;
  NF/IP3/Psat by sub-type). Size/MSL/Temperature → datasheet (deferred → UNKNOWN).
- **Architecture:** identical to MACOM / Mini-Circuits — return all candidates;
  the Verifier filters and marks missing-but-requested params UNKNOWN (`partial`),
  never FAIL. Self-registers; no core change (NFR-3).
- **Compliance:** robots allows `/products/`; no `Crawl-delay` → self-imposed
  polite delay + cache.
- **Files to create:** `rf_finder/adapters/ums.py`, `tests/adapters/test_ums.py`,
  `tests/fixtures/ums_amplifier_lna.html`, `tests/fixtures/ums_amplifier_hpa.html`.
- **Open items for sign-off:** OQ-U1…OQ-U5 (above).

> **Phase A ends here. No code written.** Awaiting plan approval (gate #1) before
> implementation.

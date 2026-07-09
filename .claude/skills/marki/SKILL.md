---
name: marki
description: >-
  Complete retrieval guide for markimicrowave.com (Marki Microwave). Use whenever
  you work on the Marki adapter (rf_finder/adapters/marki.py) — to understand how
  the site serves product data, to debug or maintain the amplifier adapter, or
  (the main forward-looking use) to ADD A NEW COMPONENT TYPE (mixer, amplifier
  variant, …) beyond amplifiers. Covers the paginated server-rendered SvelteKit
  search table, the gated two-pass per-product enrichment (Size from the product
  table; VDD/Temperature from the SvelteKit JS payload), Cloudflare/robots
  compliance, the off-by-one part-number column, the column→ontology mapping, what
  was already built, and a step-by-step expansion recipe.
---

# Marki Microwave (markimicrowave.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
markimicrowave.com**. It records how the site behaves, how the existing
**amplifier** adapter was built, and how to extend it. If you are touching
`rf_finder/adapters/marki.py`, read this first.

> Reference implementation: [marki.py](../../../rf_finder/adapters/marki.py)
> Original investigation: [marki/plan.md](../../../specs/rf-component-finder/iteration2/marki/plan.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Server-rendered-table shape: [minicircuits skill](../minicircuits/SKILL.md) · JS-payload regex trick (like Pass 2): [macom skill](../macom/SKILL.md)

---

## 1. TL;DR — the one thing to remember

Marki is a **two-pass** adapter. **Pass 1** is a Mini-Circuits-style server-rendered
table: a paginated `httpx` GET to
`/search/?item_per_page=N&page=P&keyword=&family=amplifiers` returns the product
rows directly in SvelteKit-rendered HTML (no AJAX/POST) — parse the `<table>`, map
by header name, get model/freq/Gain/NF/Psat/IP3/P1dB. **Pass 2** runs **only when
the query constrains Size / VDD / Temperature**: one extra GET per product page,
where Size comes from the page's product table and **VDD + Temperature are
regex'd out of the SvelteKit JS payload** (`power_supply_voltage:[{value:"5"}]`,
`temperature:"25"`). The Verifier applies all constraints.

**The one gotcha:** the part number is a leading `<th>`, so the data `<td>` cells
align to `headers[1:]`, not `headers` — an off-by-one if mapped naively.

---

## 2. How markimicrowave.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | No. | Scrape. |
| **Server-side parametric URL filter?** | **No** — the F-Low/F-High/Gain/NF inputs are client-side JS only; the server returns all products for a page. | Fetch all pages; filter locally in the Verifier. |
| **Is the data in the raw HTML?** | **Yes — the search `<table>` is SvelteKit server-rendered** in the initial response. | Parse the table directly; no JS render needed. |
| **JS required?** | **No** for the search rows (Pass 1). For Pass-2 fields (VDD/Temperature) the values sit in a **SvelteKit JS payload string** in the product-page HTML — still plain text, regex-extractable, no execution. | `httpx` + `selectolax` + regex; no Playwright. |
| **Entry URL** | `https://markimicrowave.com/search/?item_per_page=N&page=P&keyword=&family=amplifiers` | Paginated GET. |
| **Rows** | ~123 amplifiers (June 2026), embedded as the `"X - Y of N"` count string. | Page until the running total ≥ N. |
| **Front-end** | SvelteKit; product page carries a JS payload with `power_supply_voltage`, `temperature`. | Pass-2 fields come from that payload, not a table. |

---

## 3. Compliance & access

- **robots.txt:** `/search/` and the product pages are **allowed**; datasheet PDFs
  are **not** fetched programmatically.
- **Cloudflare:** a **browser-style User-Agent** avoids the challenge for these
  URLs (plain bot UAs trigger it). If a large `item_per_page` is challenged (Pass 1
  returns no table), the adapter **falls back to 50-per-page paging**.
- **Inter-request delay:** `_MIN_DELAY_SECONDS = 1.5`, enforced before each fetch.
- **Retry:** `_MAX_ATTEMPTS = 3`, `_RETRY_BACKOFF_SECONDS = 1.0` for transient
  transport errors.

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL = "https://markimicrowave.com"
_SEARCH_PATH = "/search/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_MIN_DELAY_SECONDS = 1.5
_ITEM_PER_PAGE = 200            # one big page; fall back to 50 on a challenge
_FALLBACK_ITEM_PER_PAGE = 50
_MAX_PAGES = 50                 # paging safety bound
_PRODUCT_PAGE_PARAMS = {"Size", "VDD", "Temperature"}   # Pass-2 trigger set
```

1. **Pass 1 — search table.** `_page_through(200)`: loop pages
   `?item_per_page=200&page=P&keyword=&family=amplifiers`, parse each; stop when a
   page has no rows, or the running total ≥ N (parsed from `"X - Y of N"`), or
   `_MAX_PAGES`. If the big page yields nothing (challenge), retry
   `_page_through(50)`.
2. **Pass 2 — gated.** Only if `spec` constrains a param in `_PRODUCT_PAGE_PARAMS`,
   fetch each candidate's product page and merge Size/VDD/Temperature (§5). This
   avoids ~123 needless product-page fetches for the common freq/gain search.
3. **Per request** (`_request`): rate-limit guard → `httpx.get` (browser UA,
   `follow_redirects=True`, `timeout=30.0`) → `raise_for_status()`; retry transient
   `httpx.HTTPError` up to `_MAX_ATTEMPTS`, else raise
   `AdapterError(manufacturer, context, cause)`.

---

## 5. The parsing recipe

### Pass 1 — `_parse_search_html()`

1. `tree.css_first("table")`; if absent → **return `[]`** (challenge page or
   out-of-range page — the paging loop treats an empty page as the stop signal, so
   Pass 1 does not hard-fail on a single empty page).
2. **Header row:** last `<tr>` in `<thead>`, normalized via `_normalize_header`
   (lowercase, replace `()[]{}.,:/\` with spaces, collapse). `FLow[GHz]` /
   `FHigh[GHz]` become `flow ghz` / `fhigh ghz`.
3. **Off-by-one:** the part number is a leading **`<th><a>`** (model + product
   href); the data `<td>` cells therefore align to **`col_names[1:]`**
   (`data_headers`), NOT `col_names`. Drop the "Part Number" header before
   positional mapping.
4. Per row: `_row_model_and_url` reads the `<th><a>`; skip rows with no model.
   `_row_params` maps each `<td>` (against `data_headers`) via `SCALAR_COLUMN_MAP`
   (§6); frequency cells feed `freq_range`.
5. Emit `Candidate(model, manufacturer="Marki Microwave", url, raw_params,
   source="table")`.

### Pass 2 — `_enrich_candidate()` (resilient, NFR-4)

- Fetch the product page (`/products/{pkg}/amplifiers/{slug}/`). A fetch/parse
  failure **returns the original candidate unchanged** (those params stay UNKNOWN).
- **Size** (`_extract_size`): the product table has a `Size` column; take the
  **larger dimension in mm** (`_parse_size_mm` = `max` of the numbers in `"{W} x
  {H} mm"`). Match the row whose part number **equals the model** — the EVB variant
  row lists Size `"-"` and is ignored.
- **VDD:** `power_supply_voltage:[{value:"([^"]*)"` → first parseable float, unit
  `V`. Bare-die parts have no such field → VDD UNKNOWN.
- **Temperature:** `temperature:"([^"]*)"` → stored as a **degenerate `(t, t)`
  °C** range (a single characterisation point honestly does not *contain* a wider
  band under the ontology's `contains` rule → never a false PASS).
- **MSL:** **always UNKNOWN** — not present anywhere in the site HTML (only in
  datasheet PDFs / compliance docs, which are not fetched).

---

## 6. Column → canonical ontology mapping (REQ-3.4)

Name-based, keyed by normalized header text (Pass 1):

```python
SCALAR_COLUMN_MAP = {                 # normalized header -> (canonical, unit)
    "gain db":  ("Gain", "dB"),
    "nf db":    ("NF",   "dB"),
    "psat dbm": ("Psat", "dBm"),
    "oip3 dbm": ("IP3",  "dBm"),      # Marki publishes OIP3 -> ontology param IP3
    "p1db dbm": ("P1dB", "dBm"),
}
# flow ghz / fhigh ghz handled specially -> freq_range (GHz).
```

Rules:

- **Frequency:** combine `flow ghz` + `fhigh ghz` into `RawValue((lo, hi),
  "GHz")`, only when both bounds are present. A DC-coupled low edge is `"0"` →
  parses as `0.0` (row kept).
- Headers not in the map (BUY NOW, Subfamily, Datasheet, SnP, Package Type,
  Status…) are **skipped**.
- **Size / VDD / Temperature** come from Pass 2 (§5); **MSL** is always UNKNOWN.

### Architecture fit

- **No query-side filtering** — return every row; the **Verifier** applies all
  constraints (REQ-4.1). (Pass 2 is enrichment, not filtering.)
- **Self-registers** via `@register`. `manufacturer = "Marki Microwave"`,
  `supported_components = {"amplifier"}`.

---

## 7. Gotchas & risks

| # | Risk | Mitigation (already applied) |
|---|---|---|
| R1 | **Off-by-one** — part number is a leading `<th>`, so `<td>`s align to `headers[1:]`. | Map data cells against `col_names[1:]` (`data_headers`). |
| R2 | **Bracketed / junk headers** (`FLow[GHz]`, filter-dropdown text). | `_normalize_header` strips brackets/punct; match by name. |
| R3 | **Cloudflare challenge** on a big `item_per_page`. | Browser UA; fall back to 50/page when a page has no table. |
| R4 | **~123 product-page fetches** if Pass 2 ran for every query. | Gate Pass 2 on `_PRODUCT_PAGE_PARAMS`; skip otherwise. |
| R5 | **EVB variant row** lists Size `"-"`. | Select the row whose PN equals the model. |
| R6 | **Single-point Temperature** could look like a wide band. | Store as degenerate `(t, t)` — never a false PASS under `contains`. |
| R7 | **VDD/Temperature live in a JS payload string**, not a table. | Regex the payload (`power_supply_voltage`, `temperature`); no JS execution. |
| R8 | **MSL not on the site.** | Always UNKNOWN; flag for manual datasheet review if required. |

---

## 8. Open questions (status at time of writing)

Tracked in [open-questions.md](../../../openspec/open-questions.md):

- **OQ-1 — full manufacturer list.** Marki is an implemented amplifier adapter;
  the full target list is undetermined.
- **OQ-3 — warn on row-count drift.** The `"X - Y of N"` total gives a natural
  drift signal; a run-to-run warning is not yet implemented.

---

## 9. EXPANSION GUIDE — adding a new component type to Marki

Pass-1 machinery (§4–§6) is **category-agnostic**; the per-category work is the
`family=` value, the column map, and (if needed) Pass-2 fields.

1. **Register the component type** in
   [components.py](../../../rf_finder/ontology/components.py) with its canonical
   params/units.
2. **Find the family slug.** The search URL takes `&family=<slug>` (amplifiers →
   `family=amplifiers`). Confirm the new category's slug from the site's search UI.
3. **Confirm the pattern.** GET the search URL with the browser UA and check the
   SvelteKit `<table>` is present with real rows and a leading `<th>` part number.
   If so, **§4–§6 apply** — build a category-specific `SCALAR_COLUMN_MAP` from the
   live headers. If it renders differently, re-investigate per REQ-3.3.
4. **Decide Pass-2 needs.** If the new type needs page-only params (Size/VDD/…),
   confirm the product-page table column and the JS-payload keys, and extend
   `_PRODUCT_PAGE_PARAMS` + the extractors. Keep Pass 2 gated.
5. **Parameterize, don't fork.** Key the family slug + column map by
   `spec.component_type`; add the type to `supported_components`. Keep the paging,
   Cloudflare fallback, rate/retry guard, and off-by-one handling.
6. **Test offline** against `_parse_search_html()` / `_extract_product_details()`
   with trimmed fixtures ([marki_amplifiers.html](../../../tests/fixtures/marki_amplifiers.html),
   [marki_product_adm11425psm.html](../../../tests/fixtures/marki_product_adm11425psm.html)).
   Cover: the off-by-one mapping, a DC low edge, Size from the matching (non-EVB)
   row, VDD/Temperature from the payload, and Pass-2-not-run when unconstrained.
7. **Update this skill** with the new family slug, column map, and Pass-2 findings.

---

## 10. File map

| File | Role |
|---|---|
| [rf_finder/adapters/marki.py](../../../rf_finder/adapters/marki.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [tests/adapters/test_marki.py](../../../tests/adapters/test_marki.py) | Offline unit tests. |
| [tests/fixtures/marki_amplifiers.html](../../../tests/fixtures/marki_amplifiers.html) | Trimmed search-table fixture. |
| [tests/fixtures/marki_product_adm11425psm.html](../../../tests/fixtures/marki_product_adm11425psm.html) | Trimmed product-page fixture (Pass 2). |
| [specs/.../iteration2/marki/plan.md](../../../specs/rf-component-finder/iteration2/marki/plan.md) | Original investigation & plan. |

---
name: marki
description: >-
  Complete retrieval guide for markimicrowave.com (Marki Microwave). Use whenever
  you work on the Marki adapter (rf_finder/adapters/marki.py) — to understand how
  the site serves product data, to debug or maintain the amplifier adapter, or
  (the main forward-looking use) to ADD A NEW COMPONENT TYPE (mixer, amplifier
  variant, …) beyond amplifiers. Covers the paginated server-rendered SvelteKit
  search table (single-pass, table-only — Size/VDD/Temperature/MSL are left
  UNKNOWN for the datasheet pipeline), Cloudflare/robots compliance, the
  off-by-one part-number column, the column→ontology mapping, what was already
  built, and a step-by-step expansion recipe.
---

# Marki Microwave (markimicrowave.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
markimicrowave.com**. It records how the site behaves, how the existing
**amplifier** adapter was built, and how to extend it. If you are touching
`rf_finder/adapters/marki.py`, read this first.

> Reference implementation: [marki.py](../../../rf_finder/adapters/marki.py)
> Original investigation: [marki/plan.md](../../../specs/rf-component-finder/iteration2/marki/plan.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Server-rendered-table shape: [minicircuits skill](../minicircuits/SKILL.md)

---

## 1. TL;DR — the one thing to remember

Marki is a **single-pass, table-only** adapter. It is a Mini-Circuits-style
server-rendered table: a paginated `httpx` GET to
`/search/?item_per_page=N&page=P&keyword=&family=amplifiers` returns the product
rows directly in SvelteKit-rendered HTML (no AJAX/POST) — parse the `<table>`, map
by header name, get model/freq/Gain/NF/Psat/IP3/P1dB and the product URL. The
Verifier applies all constraints.

**It extracts only what is on the all-products search table.** Params that are NOT
on that table — **Size, VDD, Temperature, MSL** — are deliberately left UNKNOWN by
this adapter; they are the datasheet-extraction pipeline's job, not this scrape.
Product pages are **never** fetched. (A previous version ran a gated second pass
that fetched each product page for Size/VDD/Temperature; that pass was removed.)

**The one gotcha:** the part number is a leading `<th>`, so the data `<td>` cells
align to `headers[1:]`, not `headers` — an off-by-one if mapped naively.

---

## 1b. Datasheet link — where it lives (verified live 2026-07-20)

**Case 2 — the `Datasheet` column links to an HTML page, not a PDF.**

All **123/123** amplifier rows carry an `<a href>` in the `Datasheet` column, but it is a
RELATIVE link to a landing page: `/products/{package}/amplifiers/{model}/datasheet/` →
`200 text/html`. Feeding it to `datasheet_text_from_url` fails the `%PDF` guard.

The real PDF sits on that page as `https://markimicrowave.com/assets/{uuid}/{MODEL}-….pdf`
— the `{uuid}` makes it **NOT constructable**, so the hop is mandatory.

- **Selector: the `<a>` whose text is `Download PDF`.** Never "the first `.pdf` href" —
  every page also carries two `Online Catalog` links (`MM_Catalog_*.pdf`). Those are valid
  PDFs, so grabbing one would count as "datasheet read" and **drop** the part instead of
  leaving it `not-verified`.
- Read the first-hop URL from the `Datasheet` column; do NOT build it from `Candidate.url`
  (they match on 123/123 rows today, but a constructed URL is the Mini-Circuits failure mode).
- Verified end-to-end: ADM-11425PSM `%PDF-1.4`, 1.4 MB, 9916 chars; AMM-11561CH 13516;
  AMM-11059CH 12819; AMM-10861PSM 10537.
- **Compliance:** robots ALLOWS both hops (`/…/datasheet/` and `/assets/*.pdf`; the file is
  a deny-list of named bad bots, `*` unrestricted). §3's "datasheet PDFs are not fetched at
  all" describes the table-only adapter's SCOPE — the orchestration pipeline does fetch them.

---

## 2. How markimicrowave.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | No. | Scrape. |
| **Server-side parametric URL filter?** | **No** — the F-Low/F-High/Gain/NF inputs are client-side JS only; the server returns all products for a page. | Fetch all pages; filter locally in the Verifier. |
| **Is the data in the raw HTML?** | **Yes — the search `<table>` is SvelteKit server-rendered** in the initial response. | Parse the table directly; no JS render needed. |
| **JS required?** | **No** for the search rows. | `httpx` + `selectolax`; no Playwright. |
| **Entry URL** | `https://markimicrowave.com/search/?item_per_page=N&page=P&keyword=&family=amplifiers` | Paginated GET. |
| **Rows** | ~123 amplifiers (June 2026), embedded as the `"X - Y of N"` count string. | Page until the running total ≥ N. |
| **Params NOT on the table** | Size, VDD, Temperature, MSL — on the product page / JS payload / datasheet only. | **Left UNKNOWN** here; owned by the datasheet pipeline. Product pages are not fetched. |

---

## 3. Compliance & access

- **robots.txt:** `/search/` is **allowed**; product pages and datasheet PDFs are
  **not fetched at all** by this table-only adapter.
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
```

1. **Search table (the whole adapter).** `_page_through(200)`: loop pages
   `?item_per_page=200&page=P&keyword=&family=amplifiers`, parse each; stop when a
   page has no rows, or the running total ≥ N (parsed from `"X - Y of N"`), or
   `_MAX_PAGES`. If the big page yields nothing (challenge), retry
   `_page_through(50)`. `search()` returns these rows directly — no product-page
   fetches, no enrichment.
2. **Per request** (`_request`): rate-limit guard → `httpx.get` (browser UA,
   `follow_redirects=True`, `timeout=30.0`) → `raise_for_status()`; retry transient
   `httpx.HTTPError` up to `_MAX_ATTEMPTS`, else raise
   `AdapterError(manufacturer, context, cause)`.

---

## 5. The parsing recipe

### `_parse_search_html()`

1. `tree.css_first("table")`; if absent → **return `[]`** (challenge page or
   out-of-range page — the paging loop treats an empty page as the stop signal, so
   parsing does not hard-fail on a single empty page).
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

### Off-table params — always UNKNOWN

**Size, VDD, Temperature, MSL** are not on the search table and are **not fetched**
by this adapter. Size/VDD/Temperature live on the product page (Size in the
product table; VDD/Temperature in the SvelteKit JS payload
`power_supply_voltage:[{value:"5"}]` / `temperature:"25"`) and MSL only in datasheet
PDFs — all of which are the **datasheet-extraction pipeline's** responsibility.
They simply verify as UNKNOWN for Marki candidates.

---

## 6. Column → canonical ontology mapping (REQ-3.4)

Name-based, keyed by normalized header text (the search table):

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
- **Size / VDD / Temperature / MSL** are off-table (§5) → always UNKNOWN here.

### Architecture fit

- **No query-side filtering** — return every row; the **Verifier** applies all
  constraints (REQ-4.1).
- **Self-registers** via `@register`. `manufacturer = "Marki Microwave"`,
  `supported_components = {"amplifier"}`.

---

## 7. Gotchas & risks

| # | Risk | Mitigation (already applied) |
|---|---|---|
| R1 | **Off-by-one** — part number is a leading `<th>`, so `<td>`s align to `headers[1:]`. | Map data cells against `col_names[1:]` (`data_headers`). |
| R2 | **Bracketed / junk headers** (`FLow[GHz]`, filter-dropdown text). | `_normalize_header` strips brackets/punct; match by name. |
| R3 | **Cloudflare challenge** on a big `item_per_page`. | Browser UA; fall back to 50/page when a page has no table. |
| R4 | **Size / VDD / Temperature / MSL are off-table.** | Deliberately not fetched; left UNKNOWN for the datasheet pipeline. Flag for datasheet review if the Verifier requires them. |

---

## 8. Open questions (status at time of writing)

Tracked in [open-questions.md](../../../openspec/open-questions.md):

- **OQ-1 — full manufacturer list.** Marki is an implemented amplifier adapter;
  the full target list is undetermined.
- **OQ-3 — warn on row-count drift.** The `"X - Y of N"` total gives a natural
  drift signal; a run-to-run warning is not yet implemented.

---

## 9. EXPANSION GUIDE — adding a new component type to Marki

The table-scrape machinery (§4–§6) is **category-agnostic**; the per-category work
is the `family=` value and the column map.

1. **Register the component type** in
   [components.py](../../../rf_finder/ontology/components.py) with its canonical
   params/units.
2. **Find the family slug.** The search URL takes `&family=<slug>` (amplifiers →
   `family=amplifiers`). Confirm the new category's slug from the site's search UI.
3. **Confirm the pattern.** GET the search URL with the browser UA and check the
   SvelteKit `<table>` is present with real rows and a leading `<th>` part number.
   If so, **§4–§6 apply** — build a category-specific `SCALAR_COLUMN_MAP` from the
   live headers. If it renders differently, re-investigate per REQ-3.3.
4. **Off-table params stay off-table.** Any param not in the search table
   (Size/VDD/Temperature/MSL, or a new equivalent) is left UNKNOWN and handed to
   the datasheet-extraction pipeline — do **not** reintroduce per-product-page
   fetches here.
5. **Parameterize, don't fork.** Key the family slug + column map by
   `spec.component_type`; add the type to `supported_components`. Keep the paging,
   Cloudflare fallback, rate/retry guard, and off-by-one handling.
6. **Test offline** against `_parse_search_html()` with a trimmed fixture
   ([marki_amplifiers.html](../../../tests/fixtures/marki_amplifiers.html)).
   Cover: the off-by-one mapping, a DC low edge, and that off-table params are not
   emitted.
7. **Update this skill** with the new family slug and column map.

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
| [specs/.../iteration2/marki/plan.md](../../../specs/rf-component-finder/iteration2/marki/plan.md) | Original investigation & plan. |

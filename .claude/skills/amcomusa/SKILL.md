---
name: amcomusa
description: >-
  Complete retrieval guide for amcomusa.com (AMCOM USA). Use whenever you work on
  the AmcomUSA adapter (rf_finder/adapters/amcomusa.py) — to understand how the
  site serves product data, to debug or maintain the amplifier adapter, or (the
  main forward-looking use) to ADD A NEW COMPONENT TYPE or a new amplifier
  category beyond the eight already mapped. Covers the multi-category
  server-rendered-table retrieval method, per-category resilience, robots
  compliance, parsing gotchas (values in cell text not ddtf-value, dual-supply
  VDD, card-only Rackmount page), the column→ontology mapping, what was already
  built, and a step-by-step expansion recipe.
---

# AMCOM USA (amcomusa.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
amcomusa.com**. It records how the site behaves, how the existing **amplifier**
adapter was built, and how to extend it to new categories/component types. If you
are touching `rf_finder/adapters/amcomusa.py`, read this first.

> Reference implementation: [amcomusa.py](../../../rf_finder/adapters/amcomusa.py)
> Original investigation: [amcomusa/plan.md](../../../specs/rf-component-finder/iteration2/amcomusa/plan.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Same server-rendered-table shape: [minicircuits skill](../minicircuits/SKILL.md) (single table) · contrast the embedded-JSON site: [macom skill](../macom/SKILL.md)

---

## 1. TL;DR — the one thing to remember

Unlike Mini-Circuits (one table, one GET), **AmcomUSA splits its catalogue across
many category pages**, and the numeric value lives in the **cell text**, not in
the `ddtf-value` attribute (that attribute is JS/tablesorter-added and empty in
the raw HTML). The adapter makes **one `httpx` GET per category page** (8
table-backed amplifier categories + 1 card-only page), parses each
`table#allPnTable` with `selectolax`, maps columns by their live header text, and
returns every row as a `Candidate`. **Each category fetch is isolated** — one
failing page is skipped, not fatal. The Verifier applies all constraints.

---

## 1b. Datasheet link — where it lives (verified live 2026-07-20)

**Case 1 — the link is in the row `search()` already parses.**

The `allPnTable` row's LAST cell (empty header) holds an `<a>` pointing straight to an
ABSOLUTE CloudFront PDF, e.g.
`http://d2f6h2rm95zg9t.cloudfront.net/…/AM001019SF_1H_….pdf` — same HTML response as the
row's other params, no extra request. It is currently discarded (the empty-header column is
skipped).

- Identify it as "the last cell holding an `<a>` to a `.pdf`", **not** by a hardcoded index —
  the column set differs per category.
- robots.txt is `Allow: /` (only `/admin`, `/privacy` disallowed); the PDF is on a separate
  CloudFront CDN.

---

## 2. How amcomusa.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | No. | Scrape. |
| **Server-side parametric URL filter?** | **No** — the site's filter is exact-match only (ASP.NET WebForms POST with ViewState), not a usable range filter. | Fetch whole categories; filter locally in the Verifier. |
| **Is the data in the raw HTML?** | **Yes — as `<table id="allPnTable">` cells.** But the numeric value is the **cell text**; the `ddtf-value` attribute is empty in the raw HTML (added later by client-side tablesorter JS). | Read cell **text** (prefer `ddtf-value` only when non-empty, for forward-compat). |
| **JS required?** | **No** to get the data (it's server-rendered text). | `httpx` + `selectolax` suffice; no Playwright. |
| **One page or many?** | **Many.** The catalogue is split by product category; each category is its own listing page. | One GET per category (~9 total). |
| **Entry URL** | `https://www.amcomusa.com/categories/<slug>` | Per-category slug (see §4). |
| **Rows** | ~220 amplifier candidates across all categories. | Aggregate of the per-category tables. |
| **Front-end** | Static ASP.NET WebForms HTML + tablesorter JS for sort/filter. | Rely on server-rendered cell text, not the JS-populated `ddtf-value`. |

**Two page shapes:** 8 categories render `table#allPnTable`; the ninth
(**Rackmount HPAs**) has **no table**, only product cards — so those candidates
carry only a model + link (empty `raw_params`) and verify as `partial`.

---

## 3. Compliance & access

- Product category pages are fetched with a **browser-style User-Agent** (plain
  bot UAs may be rejected by the CDN).
- **Inter-request delay:** `_MIN_DELAY_SECONDS = 1.5` (the site asks for ~1.5 s),
  enforced by a `time.sleep()` guard before each live fetch.
- **Transient-failure retry:** `_MAX_ATTEMPTS = 3` with `_RETRY_BACKOFF_SECONDS =
  1.0` — AmcomUSA occasionally drops the TLS connection mid-handshake (SSL
  `UNEXPECTED_EOF`); the retry loop absorbs those.
- The datasheet PDF link (when present) is display-only; the current adapter is
  **table-only** and does not fetch PDFs.

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL = "https://www.amcomusa.com"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_MIN_DELAY_SECONDS = 1.5
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0
_TABLE_SELECTOR = "table#allPnTable"

TABLE_CATEGORIES = [   # 8 table-backed amplifier categories (all -> "amplifier")
    ("Low Noise Amplifiers", "low-noise-amplifier-modules"),
    ("Driver Amplifiers",    "driver-amplifiers"),
    ("GaAs MMIC PAs",        "gaas-mmic-pas"),
    ("GaN MMIC PAs",         "gan-mmic-pas"),
    ("Medium Power SSPA",    "medium-power-sspa-modules"),
    ("Compact SSPA",         "compact-sspa-modules"),
    ("Standard SSPA",        "standard-sspa-modules"),
    ("MMIC in a Box",        "mmic-in-a-box-modules"),
]
RACKMOUNT_CATEGORY = ("Rackmount HPAs", "rackmount-hpas")   # card-only, no table
```

1. **For each of the 8 table categories:** GET `/categories/<slug>`, parse with
   `_parse_table_html`. Wrap each in `try/except AdapterError` — a failed category
   is **appended to an errors list and skipped**, not raised.
2. **Then** GET the Rackmount HPAs page, parse with `_parse_rackmount_html`
   (also isolated).
3. **Per request** (`_request`): rate-limit guard → `httpx.get` (browser UA,
   `follow_redirects=True`, `timeout=30.0`) → `raise_for_status()`; retry transient
   `httpx.HTTPError` up to `_MAX_ATTEMPTS`, raising `AdapterError(manufacturer,
   context, cause)` only after all attempts fail.
4. **Aggregate tripwire:** if **no candidates at all** were collected **and** there
   were errors, raise `AdapterError` ("all N category fetches failed; first: …").
   Otherwise return what was gathered. → **one bad page never sinks the run**
   (NFR-4).

---

## 5. The parsing recipe (what `_parse_table_html()` does)

Uses `selectolax.parser.HTMLParser`.

1. **Locate the table:** `tree.css_first("table#allPnTable")`. **If absent →
   return `[]`** (NOT an error) — some category slugs are parent pages without a
   direct product table; the aggregate tripwire in §4 handles a true site failure.
   *(This differs from Mini-Circuits/MACOM, which fail loudly on a missing table,
   because AmcomUSA is multi-category.)*
2. **Header row:** use the **LAST `<tr>` in `<thead>`** (earlier rows are
   filter/search rows). `col_names[0]` is `"product"`; the technical columns
   follow, normalized via `_normalize_header` (lowercase, strip `().,:/\`, collapse
   whitespace). Column lookup is **name-based**, never positional-by-hardcode.
3. **Iterate `<tbody> <tr>`:** the part number is in `td[name="product"] > a`
   (fallback: first cell's `<a>`); skip rows with no model. Build the product URL
   from that `<a href>` (host-prefixed), else `/product-details/<model.lower()>`.
4. **Per data cell (aligned 1:1 with `col_names` by index):** take the value as
   the **cell text**, or the `ddtf-value` attribute **only when it is non-empty**.
   `_parse_float` returns `None` for sentinels `{"", "-", "n/a", "N/A", "TBD",
   "tbd"}` and for anything not a single float (so a dual-supply string like
   `"+8 / -0.75"` → `None` → param absent). Frequency columns feed `freq_range`;
   scalar columns go through `SCALAR_COLUMN_MAP` (§6).
5. Append `Candidate(model, manufacturer="AmcomUSA", url, raw_params,
   source="table")`. If `<tbody>` is missing, return `[]`.

**Rackmount HPAs (`_parse_rackmount_html`):** no table — collect unique
`a[href*="/product-details/"]` links, upper-case the slug as the model, emit
`Candidate(..., raw_params={}, source="table")`.

---

## 6. Column → canonical ontology mapping (REQ-3.4)

Name-based, keyed by normalized header text:

```python
SCALAR_COLUMN_MAP = {                 # normalized header -> (canonical, source unit)
    "nf db":    ("NF",   "dB"),
    "gain db":  ("Gain", "dB"),
    "p1db dbm": ("P1dB", "dBm"),
    "pout dbm": ("Psat", "dBm"),      # "Pout" and "Psat" both -> canonical Psat
    "psat dbm": ("Psat", "dBm"),
    "oip3 dbm": ("IP3",  "dBm"),      # OIP3 on the site -> ontology param IP3
    "vd v":     ("VDD",  "V"),        # LNA / GaN supply column
    "bias v":   ("VDD",  "V"),        # Driver / GaAs / SSPA supply column
}
# Fmin/Fmax handled specially -> freq_range; unit MHz or GHz read from the header.
```

Rules that matter:

- **Frequency unit is per-category.** `_freq_role_and_unit` classifies `fmin*`/
  `fmax*` and reads **MHz vs GHz from the header** (MHz for LNA / Medium-Power
  SSPA; GHz elsewhere). Combine into `raw_params["freq_range"] = RawValue((lo, hi),
  unit)`; the Verifier converts to canonical GHz. Only built when **both** bounds
  are present.
- **Both supply headers** (`Vd (V)`, `Bias (V)`) map to canonical **VDD** (V→V
  identity). Dual-supply cells (`"+8 / -0.75"`) are not a single float → VDD stays
  **UNKNOWN** for those rows (correct — never a false value).
- Headers not in the map (Package, ECCN, Connector, Size…) are **skipped**.
- **Size / MSL / Temperature / IP3 are NOT in these tables** — they verify as
  UNKNOWN. (IP3 exists only in the PDF datasheet; the adapter is table-only.)

### Architecture fit

- **No query-side filtering** — return every row; the **Verifier** applies all
  constraints (REQ-4.1).
- **Self-registers** via `@register` ([base.py](../../../rf_finder/adapters/base.py)).
  `manufacturer = "AmcomUSA"`, `supported_components = {"amplifier"}`.

---

## 7. Gotchas & risks (carry these into any new category)

| # | Risk | Mitigation (already applied) |
|---|---|---|
| R1 | **Value is in cell text, not `ddtf-value`** — the attribute is empty in raw HTML (JS/tablesorter fills it later). | Read cell **text**; use `ddtf-value` only when non-empty. |
| R2 | **Per-category header differences** — `Pout` vs `Psat`, MHz vs GHz, `Vd` vs `Bias`. | Read the header **live** and map by normalized name; detect freq unit from the header. |
| R3 | **First `<thead>` rows are filter/search rows**, not the real headers. | Use the **last** `<tr>` in `<thead>`. |
| R4 | **Dual-supply strings** (`"+8 / -0.75"`) are not a single VDD. | `_parse_float` → `None` → VDD absent (never a false value). |
| R5 | **Some category slugs are parent pages** with no `allPnTable`. | Missing table → return `[]` (skip), not an error. |
| R6 | **Transient TLS drop** (SSL `UNEXPECTED_EOF`) mid-fetch. | Retry up to `_MAX_ATTEMPTS` with backoff. |
| R7 | **One category page down** shouldn't lose the others. | Per-category isolation; raise only if **all** fail (NFR-4). |
| R8 | **Rackmount HPAs has no table.** | Card-only parser → model+link, empty `raw_params` → verifies `partial`. |

---

## 8. Open questions (status at time of writing)

Tracked in [open-questions.md](../../../openspec/open-questions.md):

- **OQ-1 — full manufacturer list.** AmcomUSA is one of the implemented amplifier
  adapters; the full target list is still undetermined.
- **OQ-3 — warn on row-count drift.** A big change in the ~220 candidate count
  could signal a site redesign; not implemented (no run-to-run comparison).

---

## 9. EXPANSION GUIDE — adding a new category / component type

The fetch/parse machinery (§4–§6) is **category-agnostic and reused as-is** — the
per-category work is the slug, the header map, and the ontology.

1. **Register the component type** (if new) in
   [components.py](../../../rf_finder/ontology/components.py) and its canonical
   params/units. For a new *amplifier* category, no ontology change is needed.

2. **Find the category's listing slug.** AmcomUSA uses
   `https://www.amcomusa.com/categories/<slug>`. Confirm the exact slug from the
   site's product menu (don't guess the plural/hyphenation).

3. **Confirm it's the same pattern.** GET the page with the browser UA and check
   for `table#allPnTable` with real **cell-text** values. If so, **§4–§6 apply
   unchanged** — just add the `(name, slug)` pair to `TABLE_CATEGORIES` (or, for a
   non-amplifier type, to a per-type category table). If the page renders
   differently (card-only, or JS-only data), re-investigate per REQ-3.3 and record
   it here.

4. **Read the live header row** of that category and extend `SCALAR_COLUMN_MAP`
   with any new normalized headers → `(canonical, unit)`. Watch for a new
   frequency unit (MHz vs GHz) and new supply-column labels.

5. **Parameterize, don't fork.** For a *new component type*, promote
   `TABLE_CATEGORIES` + `SCALAR_COLUMN_MAP` to a per-type table keyed by
   `spec.component_type`, select by it in `search`, and add the type to
   `supported_components`. Keep the per-category isolation and the rate/retry guard.

6. **Carry the gotchas (§7) forward** — cell-text over `ddtf-value`, last-thead
   header row, dual-supply → UNKNOWN, missing-table → skip, per-category isolation.

7. **Test offline.** Assert against `_parse_table_html()` directly with an inline
   trimmed `<table id="allPnTable">` fixture (see
   [test_amcomusa.py](../../../tests/test_amcomusa.py)). Cover: a full-spec row, a
   `Vd`/`Bias` → VDD row, a dual-supply → UNKNOWN row, a `-` sentinel row, and a
   no-`allPnTable` page → `[]`.

8. **Update this skill** with the new slug(s), header map additions, and any new
   quirks.

---

## 10. File map

| File | Role |
|---|---|
| [rf_finder/adapters/amcomusa.py](../../../rf_finder/adapters/amcomusa.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [tests/test_amcomusa.py](../../../tests/test_amcomusa.py) | Offline unit tests (inline HTML fixtures). |
| [specs/.../iteration2/amcomusa/plan.md](../../../specs/rf-component-finder/iteration2/amcomusa/plan.md) | Original investigation & plan. |

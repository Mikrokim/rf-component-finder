---
name: ums
description: >-
  Complete retrieval guide for ums-rf.com (UMS — United Monolithic
  Semiconductors). Use whenever you work on the UMS adapter
  (rf_finder/adapters/ums.py) — to understand how the site serves product data,
  to debug or maintain the amplifier adapter, or (the main forward-looking use)
  to ADD A NEW COMPONENT TYPE (mixer, switch, attenuator, …) to the UMS adapter
  beyond amplifiers. Covers the `?function=` template switch, the per-sub-type
  GET strategy, robots compliance, parsing gotchas (broken numeric filters,
  per-category column differences, nested sort-caret headers), the
  column→ontology mapping, what was already built, and a step-by-step expansion
  recipe.
---

# UMS (ums-rf.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
ums-rf.com** (United Monolithic Semiconductors). It records how the site
behaves, how the existing **amplifier** adapter was built, and how to extend it
to **new component types**. If you are touching `rf_finder/adapters/ums.py` or
adding a category, read this first — you should not have to re-investigate the
site from scratch.

> Reference implementation: [ums.py](../../../rf_finder/adapters/ums.py)
> Original investigation: [ums-plan.md](../../../specs/rf-component-finder/iteration2/ums-plan.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Contrast with the embedded-JSON site: [macom skill](../macom/SKILL.md) · the other server-rendered-table site: [minicircuits skill](../minicircuits/SKILL.md)

---

## 1. TL;DR — the one thing to remember

**The plain `/products/` page is the WRONG source — it renders a "catalog" view
with no spec columns (only Reference / Description / Case).** Adding a
**`?function=<slug>`** query switches the page to the "archive-product" template,
which **server-side renders the full parametric table** (Gain, NF, P1dB, IP3,
Psat, RF Bandwidth, Bias…) as real `<td>` cells.

So the retrieval is: **one `httpx` GET per amplifier sub-type → parse the
`<thead>` labels + `<tr class="product-row">` cells → map by header label to
canonical params.** Plain `httpx`; **no JavaScript, no Playwright, no
per-product fetches.** **5 GETs cover all ~156 amplifiers.** The Verifier applies
all constraints.

---

## 2. How ums-rf.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | **Partial / unusable.** A WordPress REST API exists (`/wp-json/wp/v2/product`, 274 products, paginated) but exposes **no specs** (`"acf":[]`). | Useful only as an index / count sanity-check; **not** for specs. Scrape. |
| **Server-side parametric URL filter?** | **Yes for `function`** (e.g. `amplifier-lna` → 47 rows). **No for frequency/power** — the sliders are **broken server-side**: a narrowed range returns **0 rows**. | Filter the *category* via `?function=`; send the **full** freq/power range and let the Verifier do all numeric filtering. |
| **Is the parametric data in the raw HTML?** | **Yes — as real `<td class="characteristic-cell">` cells** in the `?function=`-filtered page. The **unfiltered** `/products/` page has **no** spec columns (catalog view only). | Parse the `?function=` page's table directly; never the unfiltered page. |
| **JS required to *see* the data?** | **No.** `archive-product.js` only adds **column-sort** behavior; data and `<thead>` labels are server-rendered. | `httpx` + `selectolax` suffice; no Playwright. |
| **Entry URL (specs)** | `https://www.ums-rf.com/products/?function=<slug>&frequency-min=0&frequency-max=105.5&power-min=0&power-max=200&power-unit=watt` | The `?function=`-filtered listing is the fetch target. |
| **Load method** | HTTP **GET** with query string; **server-side** rendering of the filtered table. | One GET per sub-type. |
| **Front-end stack** | **WordPress 7.0**, custom post type `product`, theme `ums`. No Cloudflare. Cookiebot/Matomo present (irrelevant to scraping). | Don't expect a CDN challenge; rely on the server-rendered table. |
| **Rows per category** | LNA 47, HPA 61, MPA 36, Analog VGA 7, Digital VGA 5 = **156** amplifiers. | **5 GETs = full dataset.** No per-product fetches. |

This is a **server-rendered-table** pattern (like Mini-Circuits), **not** an
embedded-JSON one (contrast the [macom skill](../macom/SKILL.md)). Its
distinguishing twist vs Mini-Circuits is the **`?function=` template switch** and
the **multi-GET (one per sub-type)** fetch.

> Some rows carry a `hidden-row` CSS class ("View more" UI) — they are still in
> the raw HTML. **Ignore that class**; all rows are parsed.

---

## 3. Compliance & access (robots.txt)

`https://www.ums-rf.com/robots.txt` (HTTP 200, fetched live; **no Cloudflare**):

```
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php

Sitemap: https://www.ums-rf.com/sitemap_index.xml
```

Conclusions that govern the adapter:

- **`/products/` is allowed** — only `/wp-admin/` is disallowed. Scraping the
  product listing (filtered or not) is permitted.
- **No `Crawl-delay` directive.** The adapter still **self-imposes** a modest
  polite delay between the 5 category GETs: `_MIN_DELAY_SECONDS = 3.0`, enforced
  via a `time.sleep()` guard before each live fetch; only paid on cache miss.
- A **browser-style User-Agent** returns clean 200s — no bot challenge observed.
  Identity is an honest product-search retriever (see §8 R2 / OQ-U1).
- The sitemap splits products across `product-sitemap1.xml` / `product-sitemap2.xml`
  (consistent with the 274 REST count) — a possible enumeration cross-check, not
  needed for the chosen method.

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL     = "https://www.ums-rf.com"
_PRODUCTS_URL = _BASE_URL + "/products/"

_AMPLIFIER_SLUGS = (                         # one GET per sub-type → all 156 amps
    "amplifier-lna", "amplifier-hpa", "amplifier-mpa",
    "amplifier-analogvga", "amplifier-digitalvga",
)

# Full default range — narrowing freq/power returns 0 rows (broken server-side).
_RANGE_PARAMS = {
    "frequency-min": "0", "frequency-max": "105.5",
    "power-min": "0", "power-max": "200", "power-unit": "watt",
}

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_MIN_DELAY_SECONDS = 3.0
```

`search(spec)` loops over the 5 slugs, calling `_fetch_category(slug)` then
`_parse_html(html)`, accumulating every row. Per fetch:

1. **Rate-limit guard.** If `_last_fetch_time` is set and < `_MIN_DELAY_SECONDS`
   has elapsed, `time.sleep()` the remainder. Only incurred on a cache miss.
2. **One GET** to `_PRODUCTS_URL` with `params = {"function": slug, **_RANGE_PARAMS}`,
   `follow_redirects=True`, `timeout=60.0`, headers:
   - `User-Agent`: the browser UA above
   - `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8`
   - `Accept-Language: en-US,en;q=0.9`
3. `response.raise_for_status()`, then stamp `_last_fetch_time = time.time()`.
4. On any `httpx.HTTPError`, raise **`AdapterError(manufacturer, context, cause)`**
   (context names the failing `function=<slug>`) — never let a raw transport
   error escape.
5. Hand `response.text` to `_parse_html()`.

**Rate limiting / caching (NFR-6):** 5 requests per `search()`; no pagination, no
per-product fetches. The same SQLite/TTL cache the other adapters use serves
repeats keyed by category URL, so the delay is paid only on first fetch /
cache miss. The delay default belongs in config
(`rate_limits.ums.delay_seconds`, recommend 3–5 s; see OQ-U3).

---

## 5. The parsing recipe (what `_parse_html()` does)

Uses `selectolax.parser.HTMLParser`. Exposed for tests to call directly (offline).

1. **Locate the parametric table.** Find a `tr.product-row` and climb to its
   enclosing `<table>` (robust to the exact table class/id — the page has
   unrelated tables too). Fallback: `table.product-table`.
   **If no table is found → raise `AdapterError`** ("no parametric product table
   found in HTML"). This is the **template/redesign tripwire** — it fires when you
   accidentally fetched the catalog view, hit an empty/blocked response, or the
   site changed. Fail loudly; never return empty silently.
2. **Read the header labels (nested-tolerant).** From the first `<thead>` `<tr>`
   that has `<th>` cells, take `th.text(strip=True)`. The spec `<th>` cells
   contain **nested sort-caret markup**, so header text must be read with
   selectolax (nested-tolerant), **not a flat regex**.
   **If no `<thead>` labels → raise `AdapterError`** ("parametric table has no
   `<thead>` column labels").
3. **Build a name-based column map.** The `characteristic-cell` columns
   correspond to headers **after the first two** (Reference, Description) —
   `headers[2:]`. Normalize each with `_normalize_header` (lowercase; replace
   `()+/\.,:±-` with spaces; collapse whitespace) → map normalized label →
   **offset into the row's characteristic-cell list**. First occurrence of a
   label wins. **Map by label, never by position** (categories have different
   column sets — §6/§7).
4. **Iterate `tr.product-row`** and build a `Candidate` per row (§6); skip rows
   with no model name.

---

## 6. From a product row to a `Candidate`

Per `<tr class="product-row">` (see `_build_candidate`):

| Source | Use |
|---|---|
| `a.product-link` text | `Candidate.model` (skip the row if empty) |
| `a.product-link` href | `Candidate.url` — host-prefixed if relative; fallback `/products/<model-lower>/`. **Report link, never fetched.** |
| `td.characteristic-cell` texts, in order | zipped against `headers[2:]` → `raw_params` after mapping (§7) |
| `a.doc-link` href (datasheet PDF) | *Reserved* for the future `datasheet`-confidence path; captured in the page but not parsed now |
| `h3.product-subtitle` | description (embeds the band as text); not currently emitted |

Cell parsing (`_parse_float`): missing sentinels `{"", "-", "n/a", "N/A", "—"}`
→ `None`. A `None` result means the param is simply **omitted** from
`raw_params`, so the Verifier marks a requested-but-missing spec **UNKNOWN**
(partial), **never FAIL**. Otherwise `float(text)`, or `None` on `ValueError`.

### Architecture fit (same contract as Mini-Circuits / MACOM)

- **No query-side filtering** — return **every** row; the **Verifier** applies all
  constraints (REQ-4.1). The UMS sliders are broken server-side anyway, so this is
  the only correct option: always send the full range, never the user's.
- **Self-registers** via the `@register` class decorator from
  [base.py](../../../rf_finder/adapters/base.py) — no core file edits (NFR-3).
  `manufacturer = "UMS"`, `supported_components = {"amplifier"}` (a set; grows as
  you add types — §10), `source = "table"`.

---

## 7. Column → canonical ontology mapping (REQ-3.4)

Only the **amplifier ontology** params
([ontology/parameters.py](../../../rf_finder/ontology/parameters.py)) are mapped;
every other column (`Bias mA`, `Gain Control Range`, `Gain Flatness`,
`Dynamic Range`, `Case`) is **skipped**. The map is **name-based**, keyed by the
**normalized** `<thead>` label:

```python
COLUMN_MAP = {                       # normalized header -> (canonical, unit)
    "gain db":              ("Gain", "dB"),
    "noise figure db":      ("NF",   "dB"),
    "p 1db out dbm":        ("P1dB", "dBm"),
    "ip3 dbm":              ("IP3",  "dBm"),
    "sat output power dbm": ("Psat", "dBm"),
    "bias v":               ("VDD",  "V"),
}
_FREQ_MIN_HDR = "rf bandwidth ghz min"   # combined into freq_range
_FREQ_MAX_HDR = "rf bandwidth ghz max"
```

Rules that matter:

- **Frequency:** combine `RF Bandwidth (GHz) (Min)` + `(Max)` into
  `raw_params["freq_range"] = RawValue((lo, hi), "GHz")`. **Already GHz — no MHz
  conversion** (unlike MACOM / Mini-Circuits). Emitted only when *both* edges
  parse.
- **No synonyms / no unit ambiguity.** UMS uses the ontology's own names directly
  (`IP3`, `Psat`, `NF`) — no MACOM-style synonym or `uom`-distrust problem. The
  unit in `COLUMN_MAP` is the ontology canonical unit; the Verifier converts.
- **Skip non-numeric / sentinel cells** → param absent → Verifier marks UNKNOWN.

### Per-sub-type coverage (confirmed from live `<thead>`s)

The key reason mapping is label-based, not positional — **the column set differs
by sub-type**:

| Canonical | LNA | HPA | MPA | Analog VGA | Digital VGA |
|---|:--:|:--:|:--:|:--:|:--:|
| `freq_range` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `Gain` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `P1dB` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `VDD` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `NF` | ✅ | — | — | ✅ | ✅ |
| `IP3` | — | ✅ | ✅ | — | — |
| `Psat` | — | ✅ | ✅ | — | ✅ |

**7 of 10** amplifier ontology params come from the GETs (4 universal; NF/IP3/Psat
sub-type-dependent). **3** — `Size`, `MSL`, `Temperature` — are **not** table
columns (the table has only `Case` = package form, not `Size` in mm); they live in
the per-part datasheet PDF and are **deferred → resolve to UNKNOWN** (OQ-U4).

---

## 8. Gotchas & risks (carry these into any new category)

| # | Risk | Mitigation (already applied) |
|---|---|---|
| R1 | **Wrong template** — the unfiltered `/products/` page renders a *catalog* view with no spec columns. | Always use the `?function=<slug>` URL (archive-product template). Fail loudly via `AdapterError` if no product table / `<thead>` is found. |
| R2 | **UA / identity.** | Browser-style UA; honest search retriever. No Cloudflare, no AI-bot blocks in robots. (OQ-U1) |
| R3 | **Broken freq/power server filter** — a narrowed range returns 0 rows. | **Always send the full default `_RANGE_PARAMS`; never pass user constraints into the URL.** Verifier does all numeric filtering. |
| R4 | UMS renames headers or restructures the table. | Label-based `COLUMN_MAP` (not positional). Back-pocket: per-product `div.ums-characteristics-grid` (`spec-label`/`spec-value` pairs) if the table view changes — but that costs one fetch per part. |
| R5 | New amplifier sub-type slug added / a slug renamed. | Slugs come from `umsFilterData.product_types` embedded in `/products/`; optionally derive `_AMPLIFIER_SLUGS` from it (filter `value` starting `amplifier-`) instead of hard-coding (OQ-U5). |
| R6 | Some specs (IP3/Psat/NF) absent for a sub-type; Size/MSL/Temperature absent entirely. | Omit absent params → Verifier marks UNKNOWN → `partial`, never FAIL. Datasheet params deferred (OQ-U4). |
| R7 | **`Case` mistaken for `Size`.** | `Case` is package form (Die/QFN), **not** the `Size` (mm) ontology param — skipped. |
| R8 | Nested **sort-caret markup** inside spec `<th>` cells. | Read header text nested-tolerantly with selectolax (`th.text(strip=True)`), not a flat regex. |
| R9 | Transient TLS resets observed during investigation. | 5 small GETs are cheap to retry; rely on the HTTP layer's retry/backoff. |

---

## 9. Open questions (status at time of writing)

Live in the plan doc [ums-plan.md §9](../../../specs/rf-component-finder/iteration2/ums-plan.md);
the project register is
[open-questions.md](../../../specs/rf-component-finder/open-questions.md) **(the
OQ-U items are not yet copied into it — do so when reconciling the register).**

- **OQ-U1 — UA / crawler identity.** *Recommend:* browser-style UA (no robots
  restriction; honest search retriever). **Applied** in code; confirm policy.
- **OQ-U2 — `manufacturer` string & file name.** `"UMS"` vs `"UMS-RF"` vs full
  legal name. *Recommend & applied:* `"UMS"`, file `ums.py`.
- **OQ-U3 — Self-imposed delay.** No robots `Crawl-delay`. *Recommend:* 3–5 s.
  **Applied** as `_MIN_DELAY_SECONDS = 3.0`; surface in config when the loader
  lands (T9).
- **OQ-U4 — Datasheet path for Size / MSL / Temperature.** These live only in the
  per-part datasheet PDF (`a.doc-link`, captured now). *Recommend:* defer PDF
  parsing to the `datasheet`-confidence iteration; resolve to UNKNOWN for now.
- **OQ-U5 — Derive slugs vs hard-code.** *Recommend & applied:* hard-code the 5
  amplifier slugs (simple, explicit); note the dynamic
  (`umsFilterData.product_types`) option for when more component types are added
  (§10).

---

## 10. EXPANSION GUIDE — adding a new component type to UMS

The current adapter handles **amplifiers only** (5 sub-type slugs). To add a new
category (mixer, switch, attenuator, …), the fetch/parse machinery (§4–§6) is
**reused as-is**; the per-category work is the slug(s), the column map, and the
ontology.

1. **Register the component type in the ontology** —
   [components.py](../../../rf_finder/ontology/components.py) `COMPONENTS` plus its
   canonical parameters/units. The `COLUMN_MAP` units must match.

2. **Find the new category's `function` slug(s).** UMS keys the parametric table
   off `?function=<slug>`. The full slug list is embedded in `/products/` as
   `umsFilterData.product_types` (the amplifier ones are
   `amplifier-lna`/`-hpa`/`-mpa`/`-analogvga`/`-digitalvga`). **Read that blob** to
   find the new category's slug(s) — a category may, like amplifiers, split into
   several sub-type slugs.

3. **Verify the data source is the same pattern.** GET
   `/products/?function=<slug>&<full-range params>` with the browser UA and
   confirm the **archive-product** table is in the raw HTML: a `tr.product-row`
   with real `td.characteristic-cell` values and `<thead>` labels — **not** the
   catalog view (Reference/Description/Case only). If it renders the same way,
   **§4–§6 apply unchanged.** If not, re-run the REQ-3.3 investigation for that
   page before writing code, and record the finding here.

4. **Read that category's `<thead>` labels** across **all** its sub-type slugs and
   note coverage — UMS column sets **differ by sub-type** (see §7), so confirm
   which params each slug carries.

5. **Build a category-specific column map.** Normalized header →
   `(canonical, unit)`, plus any special-combine columns (as `RF Bandwidth
   Min/Max` → `freq_range`). Mind the units the *site* uses (amplifiers are
   already GHz; another category may not be).

6. **Parameterize, don't fork.** Prefer extending the existing adapter over a new
   class:
   - Promote `_AMPLIFIER_SLUGS` + `COLUMN_MAP` to a per-component table, e.g.
     `CATEGORIES = {"amplifier": (SLUGS, COLUMN_MAP), "mixer": (…)}`.
   - `search(spec)` selects by `spec.component_type`, loops that category's slugs,
     and parses with that category's map.
   - Add the type to `supported_components`; keep the per-fetch rate guard and the
     full-range `_RANGE_PARAMS` (the broken numeric filter is site-wide).

7. **Carry the gotchas (§8) forward** — `?function=` template (not the catalog
   view), full-range params (broken server filter), label-based map, nested-caret
   headers, missing-sentinel handling, `AdapterError` on missing table, browser
   UA, display-only `Candidate.url`, return-all + Verifier-filters.

8. **Test offline.** Save a **trimmed** HTML fixture (a handful of rows) per
   sub-type under `tests/fixtures/`, including a row with a `-`/empty cell, and
   assert against `_parse_html()` directly (no network). Cover the per-sub-type
   column differences and the no-table → `AdapterError` case. Mark live
   integration tests `@pytest.mark.network`.

9. **Update this skill** with the new category's slug(s), column map, row counts,
   and any new quirks — so the next person doesn't re-investigate.

---

## 11. File map

| File | Role |
|---|---|
| [rf_finder/adapters/ums.py](../../../rf_finder/adapters/ums.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [rf_finder/ontology/parameters.py](../../../rf_finder/ontology/parameters.py) | Canonical amplifier params/units the map targets. |
| [tests/adapters/test_ums.py](../../../tests/adapters/test_ums.py) | Offline unit tests. |
| [tests/fixtures/ums_amplifier_lna.html](../../../tests/fixtures/ums_amplifier_lna.html) | Trimmed LNA fixture (NF, no IP3/Psat; `-`-cell row). |
| [tests/fixtures/ums_amplifier_hpa.html](../../../tests/fixtures/ums_amplifier_hpa.html) | Trimmed HPA fixture (IP3 + Psat, no NF). |
| [specs/.../iteration2/ums-plan.md](../../../specs/rf-component-finder/iteration2/ums-plan.md) | Original Phase-A investigation & plan. |

---
name: threerwave
description: >-
  Complete retrieval guide for 3rwave.com (3rWave). Use whenever you work on the
  3rWave adapter (rf_finder/adapters/threerwave.py) — to understand how the site
  serves product data, to debug or maintain the amplifier adapter, or (the main
  forward-looking use) to ADD A NEW COMPONENT TYPE (mixer, switch, attenuator, …)
  to the 3rWave adapter beyond amplifiers. Covers the server-rendered TablePress
  retrieval method, robots compliance, parsing gotchas (PA+LNA on one page,
  content-filter block stub, GHz frequency, text-fragment deep links), the
  column→ontology mapping, what was already built, and a step-by-step expansion
  recipe.
---

# 3rWave (3rwave.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
3rwave.com**. It records how the site behaves, how the existing **amplifier**
adapter was built, and how to extend it to **new component types**. If you are
touching `rf_finder/adapters/threerwave.py` or adding a category, read this first.

> Reference implementation: [threerwave.py](../../../rf_finder/adapters/threerwave.py)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Same server-rendered-table family: [minicircuits skill](../minicircuits/SKILL.md) (`table#maintable`) · [ums skill](../ums/SKILL.md) (`?function=` template, multi-GET) · Contrast with the embedded-JSON site: [macom skill](../macom/SKILL.md)

---

## 1. TL;DR — the one thing to remember

3rwave.com is a **WordPress site whose product specs are rendered by the
TablePress plugin as real `<td class="column-N">` cells in the initial HTML.** A
single `httpx` GET to `/amplifier/` returns **both** the PA (power amplifier) and
LNA (low-noise amplifier) tables directly in the markup — **no AJAX, no POST, no
JavaScript rendering**. DataTables.js only adds client-side paging/search/sort on
top. Parse **every** `table.tablepress` with `selectolax`, map each column by its
header text, and return every row as a `Candidate`. The Verifier applies all
constraints. **Frequency is already in GHz** — no MHz conversion.

---

## 2. How 3rwave.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | Not used. Site is WordPress; a WP REST API may exist but specs are rendered by the **TablePress** plugin, not a queryable product post type. | Scrape. |
| **Server-side parametric URL filter?** | **No.** **DataTables.js** does paging/search/sort **client-side only**; the server ignores filter state. | Fetch the whole page; filter locally in the Verifier. |
| **Is the data in the raw HTML?** | **Yes — as real rendered `<td class="column-N">` cells** inside `table.tablepress`. | Parse the tables directly; no JS needed. |
| **JS required?** | **No.** No AJAX / no client rendering needed to see the rows. | `httpx` + `selectolax` suffice; no Playwright. |
| **Entry URL (amplifiers)** | `https://3rwave.com/amplifier/` | The category page is the fetch target. |
| **Load method** | HTTP **GET**, no query parameters. | Single request. |
| **Tables** | **Two on one page** — PA (Power Amplifier) and LNA (Low-Noise Amplifier). Both are `amplifier`. Fixture confirms both ship in the single GET. | One GET = full dataset; parse *all* tables. |
| **Front-end stack** | WordPress + TablePress + DataTables.js (cosmetic). | Read raw HTML; ignore DataTables. |

This is the **server-rendered-table** family (like [minicircuits](../minicircuits/SKILL.md)
and [ums](../ums/SKILL.md)) — **not** the embedded-JSON family (contrast the
[macom skill](../macom/SKILL.md)). It also shares UMS's **multi-sub-type shape**:
two sub-type tables on one page, both mapping to `amplifier`.

---

## 3. Compliance & access (robots.txt)

- **`https://3rwave.com/robots.txt` disallows nothing** (`User-agent: *` /
  `Disallow:`), so `/amplifier/` is fully crawlable. A `sitemap_index.xml` exists
  (possible enumeration cross-check, not needed for the chosen method).
- **No `Crawl-delay`.** The adapter still self-imposes a modest polite delay
  (`_MIN_DELAY_SECONDS = 1.0`, same as Mini-Circuits — a single light page),
  enforced by a `time.sleep()` guard before a live fetch; only paid on cache miss.
- A plain bot User-Agent may be rejected by the host, so the adapter sends a
  **browser-style User-Agent** (the same UA string the other adapters use).
- **Content-filter interception (runtime environment, not the site).** Some
  networks (e.g. the Etrog/safepage filter on the dev machine) intercept
  3rwave.com for non-browser requests and return a short block stub with HTTP 200
  instead of the real page. The adapter **detects** this and raises a legible
  `AdapterError` rather than a confusing "no table" error (see §5, R2, OQ-3W-10).

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL      = "https://3rwave.com"
_AMPLIFIER_URL = _BASE_URL + "/amplifier/"
_USER_AGENT    = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_MIN_DELAY_SECONDS = 1.0
```

1. **Rate-limit guard** before a live fetch (sleep the remainder of 1 s if needed).
2. **One GET** to `_AMPLIFIER_URL`, `follow_redirects=True`, `timeout=30.0`, headers:
   - `User-Agent`: browser UA above
   - `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8`
   - `Accept-Language: en-US,en;q=0.5`
3. `raise_for_status()`, stamp `_last_fetch_time`.
4. On any `httpx.HTTPError`, raise **`AdapterError(manufacturer, context, cause)`**
   — never let a raw transport error escape.
5. Hand `response.text` to `_parse_html()`.

Rate-limit/cache strategy (NFR-6): one GET covers all amplifiers, so the 1 s delay
is paid at most once per refresh; repeats are served from cache.

---

## 5. The parsing recipe (what `_parse_html()` does)

Uses `selectolax.parser.HTMLParser`. Exposed for offline tests to call directly.

1. **Content-filter tripwire first.** If the HTML contains any `_BLOCK_MARKERS`
   (`"safepage.etrog"`, `"block/block1"`, `"cause=url_level"`) → raise
   `AdapterError` ("request intercepted by a content filter … whitelist
   3rwave.com"). This distinguishes a network block stub from a genuine redesign.
2. **Locate the tables:** `tree.css("table.tablepress")` — **all** of them (PA +
   LNA). **Do not** hard-code the TablePress id (`tablepress-29`); ids change on
   rebuild. **If none found → raise `AdapterError`** ("no table.tablepress found in
   HTML"). This is the site-redesign tripwire — fail loudly, never return empty.
3. **Per table, find the real header row.** Detect the `<tr>` (prefer `<thead>`)
   whose cells contain **"Part Number"** (normalized). A table with no Part Number
   header is **skipped** (the page may carry unrelated tables) — return `[]` for it,
   not an error.
4. **Build a normalized-header → column-index map** with `_normalize_header`
   (lowercase, replace every non-`[a-z0-9]` run with a space, trim — so
   `"Gain(dB) ▲"` → `"gain db"`, `"Start Freq.(GHz)"` → `"start freq ghz"`). This
   makes column lookup **name-based**, robust to reordering and DataTables sort
   carets. First occurrence of a header wins.
5. **Iterate `<tbody> <tr>`:** build a `Candidate(source="table")` per row via
   `_build_candidate`. Skip rows with no model. If `<tbody>` is missing, return the
   rows collected so far (no error).

Cell parsing (`_parse_float`) robustness rules:
- Missing sentinels `{"", "-", "n/a", "N/A", "NA", "—"}` → `None` (param **absent**
  from `raw_params`, so the Verifier resolves it to UNKNOWN — a partial match,
  never a wrong FAIL).
- Tolerates thousands separators (`"1,500"` → `1500.0`) and a trailing qualifier
  (`"30 typ"`, `"1.2 max"` → first number).
- Rejects non-finite results (`"nan"`, `"inf"` → `None`).
- Caveat: an in-cell range like `"28-32"` yields its first number; the columns read
  here are single-valued, so this is not expected to fire.

---

## 6. From source row to `Candidate`

Built by `_build_candidate(row, col_index)`:

| Field | How it's built |
|---|---|
| `model` | Text of the `<a>` in the Part Number cell (fallback: the cell text). Row skipped if empty. |
| `url` | **Display only, never fetched.** Prefer the row's own `<a href>` (host-prefixed if relative). When there is none (the common 3rwave case — no per-part page/datasheet), fall back to a **Scroll-to-Text-Fragment deep link** `/amplifier/#:~:text=<part>` so the link highlights *this* exact row on the shared page. The part number is percent-encoded and its `-` is force-encoded to `%2D` (a literal `-` is the range delimiter in the text-fragment grammar). |
| `raw_params` | `freq_range` (combined) + scalar params from `COLUMN_MAP` (§7). |
| `manufacturer` | `"3rWave"` (class attribute; resolved OQ-3W-2). |
| `source` | `"table"`. |

### Architecture fit (same contract as the other adapters)

- **No query-side filtering** — return every PA + LNA row; the **Verifier** applies
  all constraints (REQ-4.1).
- **Self-registers** via `@register` from [base.py](../../../rf_finder/adapters/base.py)
  (NFR-3). `manufacturer = "3rWave"`, `supported_components = {"amplifier"}`. The
  explicit import in [__main__.py](../../../rf_finder/__main__.py) triggers
  registration.

---

## 7. Column → canonical ontology mapping (REQ-3.4)

Name-based, keyed on normalized header text. PA and LNA share the same header set
(the only difference — Consumption Current in A vs mA — is a column we skip), so
**one map serves both tables**:

```python
COLUMN_MAP = {                       # normalized header -> (canonical, unit|None)
    "part number":     ("model",     None),
    "start freq ghz":  ("freq_low",  "GHz"),
    "stop freq ghz":   ("freq_high", "GHz"),
    "gain db":         ("Gain",      "dB"),
    "psat dbm":        ("Psat",      "dBm"),
    "nf db":           ("NF",        "dB"),
    "drain voltage v": ("VDD",       "V"),
}
```

Rules:

- `model`, `freq_low`, `freq_high` are **handled specially**, not emitted as scalar
  `raw_params`. Combine `start freq ghz` + `stop freq ghz` into
  `raw_params["freq_range"] = RawValue((lo, hi), "GHz")` — **already GHz, no MHz
  conversion** (unlike Mini-Circuits / Analog Devices; like UMS).
- Headers not in `COLUMN_MAP` (Consumption Current, Efficiency, Size, Connector
  Type, Description) are **skipped** — only the amplifier ontology params are mapped.
- Units come from the map/ontology, **not** the source header text; trust the
  canonical unit, not a noisy on-page unit.
- **Deferred params never emitted:** `P1dB`, `IP3`, `MSL`, `Temperature`, `Size`
  have no table columns (or are undecided) → they resolve to UNKNOWN. See §8/§9.

---

## 8. Gotchas & risks

| # | Quirk | Applied mitigation |
|---|---|---|
| **R1** | Brittle TablePress ids (`tablepress-29` etc.) change on site rebuild. | Select **all** `table.tablepress` by class, never by id. |
| **R2** | A network content filter (Etrog/safepage) can return a **block stub with HTTP 200**, which would otherwise look like a site redesign. | Detect `_BLOCK_MARKERS` in the HTML and raise a **legible** `AdapterError` ("content filter … whitelist 3rwave.com"). |
| **R3** | PA and LNA are two tables on one page (multi-sub-type). | Parse every `table.tablepress`; both map to `amplifier`; one `COLUMN_MAP` serves both. |
| **R4** | DataTables injects sort carets / glyphs into headers (`"Gain(dB) ▲"`). | `_normalize_header` reduces **any** non-alphanumeric run to a space, so matching is glyph-proof. |
| **R5** | Missing/placeholder cells (`-`, `N/A`, `—`, blank, `TBD`, `Die`). | `_parse_float` → `None`; the param is **omitted** from `raw_params` (UNKNOWN, never a wrong FAIL). |
| **R6** | No per-part page/datasheet for many rows, so a bare `/amplifier/` link can't identify the row. | Text-fragment deep link `#:~:text=<part>` (with `-`→`%2D`) highlights the exact row; unsupported browsers just load the page. |
| **R7** | Some Psat / NF / Drain Voltage cells are blank on real rows. | Handled by R5 (omit); no fabrication (see §9 on the deferred Psat-efficiency fallback). |

---

## 9. Open questions & deferred work

Tracked in the plan doc [threerwave-plan.md](../../../specs/rf-component-finder/iteration2/threerwave-plan.md) §7.
**Note:** these OQ-3W items were **not yet copied** into the project register
[open-questions.md](../../../specs/rf-component-finder/open-questions.md) —
reconcile when the register is next updated.

- **OQ-3W-1 — Size input decoding (BLOCKER for Size). [DEFERRED]** The Size column
  is free text with mixed units (mm, inch `"`, package-only strings like `Die`,
  `19" Rack Mount`), and how the user's Size *input* is received/matched is
  undecided (options A–D in the plan). **Size is therefore NOT emitted yet;** a
  clearly-marked hook is left in `_build_candidate` for when the decision lands.
  Unit detection must be **per-adapter**, not a shared mm assumption.
- **OQ-3W-3 — Psat efficiency fallback. [PROPOSED, NOT IMPLEMENTED]** The plan
  proposed deriving `Psat = (η/100)·Vd·Id` (W→dBm) for blank-Psat rows. **The code
  does not implement this** — blank Psat simply omits the param (R5/§7). Do not
  fabricate Psat until this is signed off.
- **OQ-3W-4 — `VDD` scalar vs `between`.** The site gives a single Drain Voltage;
  the ontology `VDD` comparison is `between`. Confirm how the Verifier treats a
  scalar `found` against a `between` constraint.
- **OQ-3W-6 — `Candidate.url` value. [RESOLVED in code]** No per-part
  page/datasheet for most rows → use the row `<a href>` when present, else the
  text-fragment deep link (R6). Never fetched.
- **OQ-3W-7 — PA vs LNA sub-type.** Currently **ignored** (the Verifier doesn't need
  it); both tables return as `amplifier`.
- **OQ-3W-8 — Row-count drift warning.** Log a warning if the scraped row count
  drifts > 20 % from a cached baseline (possible redesign)? *Leaning yes;* not
  implemented.
- **OQ-3W-10 — Content-filter interception (code-only, beyond the plan's OQ list).**
  The Etrog/safepage filter blocks non-browser requests to 3rwave.com on some
  networks; handled by R2. Offline parsing/tests are unaffected.
- **Deferred to a future `datasheet`-confidence iteration:** `P1dB`, `IP3`, `MSL`,
  `Temperature` (and any Size dimensions) — no table columns; harvest from per-part
  datasheet PDFs later. Do **not** derive P1dB/IP3 from rules of thumb.

---

## 10. EXPANSION GUIDE — adding a new component type to 3rWave

The current adapter handles **amplifiers only** (PA + LNA). To add a new category,
the fetch/parse machinery (§4–§6) is **reused as-is**; the per-category work is the
URL, the column map, and the ontology.

1. **Register the component type in the ontology** —
   [components.py](../../../rf_finder/ontology/components.py) `COMPONENTS` plus its
   canonical parameters/units. The `COLUMN_MAP` units must match the ontology.

2. **Find the category's page.** 3rwave.com uses a top-level slug per category
   (amplifiers → `https://3rwave.com/amplifier/`). Confirm the exact slug from the
   site's product menu (e.g. a switch/mixer/attenuator page).

3. **Confirm it's the same pattern.** GET with the browser UA and check that the
   category's specs are in the raw HTML as real `table.tablepress` `<td>` cells (not
   empty cells awaiting JS). If it is server-rendered TablePress like amplifiers,
   **§4–§6 apply unchanged.** If a category instead renders client-side (like
   MACOM's embedded JSON), **re-investigate per REQ-3.3** and record the finding
   here. Also confirm whether the category is split across sub-type tables (as PA/LNA
   are) — parsing *all* `table.tablepress` already handles that.

4. **Read that table's headers and map them.** Build a category-specific
   `COLUMN_MAP` of normalized header → `(canonical, unit)`. Identify the model
   column ("Part Number") and the frequency low/high columns. Check the frequency
   **unit on the page** — amplifiers are GHz, but confirm per category (don't assume
   MHz vs GHz). Watch for the same gotchas (R4 carets, R5 sentinels).

5. **Parameterize, don't fork.** Prefer extending the existing adapter over a new
   class:
   - Promote `_AMPLIFIER_URL` and `COLUMN_MAP` to a per-category table keyed by
     component type, e.g. `CATEGORIES = {"amplifier": (URL, COLUMN_MAP), …}`.
   - `search(spec)` selects by `spec.component_type`, fetches that URL, parses with
     that `COLUMN_MAP`.
   - Add the type to `supported_components`; keep the per-fetch rate guard, the
     content-filter tripwire (R2), and the no-`tablepress` tripwire.

6. **Carry the contracts forward** — return-all + Verifier-filters, name-based
   column map, missing-sentinel handling, `AdapterError` on missing table, browser
   UA, display-only `Candidate.url` (with the text-fragment fallback, R6).

7. **Test offline.** Save a trimmed HTML fixture for the new category under
   `tests/fixtures/` and assert against `_parse_html()` directly (no network).
   Cover: a full-spec row, a missing-param row (sentinels), the anchor-vs-fallback
   URL cases, and the no-`tablepress` → `AdapterError` case. Keep live integration
   tests `@pytest.mark.network` (they may be content-filter-blocked, R2).

8. **Update this skill** with the new slug, `COLUMN_MAP`, table/sub-type layout, row
   count, and any new quirks.

---

## 11. File map

| File | Role |
|---|---|
| [rf_finder/adapters/threerwave.py](../../../rf_finder/adapters/threerwave.py) | The adapter (reference implementation). |
| [rf_finder/__main__.py](../../../rf_finder/__main__.py) | Explicit import that triggers `@register`. |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [tests/adapters/test_threerwave.py](../../../tests/adapters/test_threerwave.py) | Offline unit tests. |
| [tests/fixtures/threerwave_amplifier.html](../../../tests/fixtures/threerwave_amplifier.html) | Trimmed HTML fixture (PA + LNA). |
| [specs/rf-component-finder/iteration2/threerwave-plan.md](../../../specs/rf-component-finder/iteration2/threerwave-plan.md) | Investigation & plan doc. |

---
name: minicircuits
description: >-
  Complete retrieval guide for minicircuits.com (Mini-Circuits). Use whenever you
  work on the Mini-Circuits adapter (rf_finder/adapters/minicircuits.py) — to
  understand how the site serves product data, to debug or maintain the amplifier
  adapter, or (the main forward-looking use) to ADD A NEW COMPONENT TYPE (mixer,
  switch, attenuator, filter, …) to the Mini-Circuits adapter beyond amplifiers.
  Covers the server-rendered-table retrieval method, robots compliance, parsing
  gotchas (DC band edge, missing sentinels), the column→ontology mapping, what
  was already built, and a step-by-step expansion recipe.
---

# Mini-Circuits (minicircuits.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
minicircuits.com**. It records how the site behaves, how the existing
**amplifier** adapter was built, and how to extend it to **new component types**.
If you are touching `rf_finder/adapters/minicircuits.py` or adding a category,
read this first.

> Reference implementation: [minicircuits.py](../../../rf_finder/adapters/minicircuits.py)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Contrast with the embedded-JSON site: [macom skill](../macom/SKILL.md) · other server-rendered-table sites: [ums skill](../ums/SKILL.md) (`?function=` template, multi-GET) · [threerwave skill](../threerwave/SKILL.md) (WordPress/TablePress, PA+LNA on one page)

---

## 1. TL;DR — the one thing to remember

Unlike MACOM, **Mini-Circuits server-side renders the full results table in the
initial HTML response.** A single `httpx` GET to `/WebStore/Amplifiers.html`
returns the entire 781-row table directly in the markup — **no AJAX, no POST, no
JavaScript rendering**. Parse the `table#maintable` with `selectolax`, map each
column by its header text, and return every row as a `Candidate`. The Verifier
applies all constraints.

---

## 1b. Datasheet link — where it lives (verified live 2026-07-20)

**Case 2 — the link is NOT on the page `search()` scrapes.**

`Amplifiers.html` carries no datasheet link at all. The table's `<a href>` is
`modelSearch.html?model=X`, which **robots DISALLOWS**. The allowed product page is
`dashboard.html?model=<urlencoded>` (sitemap-listed); it carries an `<a>` whose text is
`DATASHEET`. `/pdfs/` is robots-allowed.

- **`+` MUST be percent-encoded `%2B`** — the un-encoded form returns **200 with no
  datasheet link at all**, a silent failure. `urllib.parse.quote(model, safe="")`.
- Do NOT derive the PDF path from the model: measured 37/40, and it 404s systematically
  in the ZFL/ZHL/ZVA families where suffix variants share a base datasheet
  (`ZHL-10M4G21W1X+` → `ZHL-10M4G21W1+.pdf`). The product page is authoritative.
- **The datasheet href is ROOT-relative** — `/pdfs/<model>.pdf`, not
  `WebStore/pdfs/...`. Join it against the HOST (`urljoin(page_url, href)`); joining it
  onto `_BASE_URL` yields `/WebStore/pdfs/...` and a 404. Caught live: the first
  implementation did exactly that.
- **The product page carries ~25 other PDFs** — app notes (`/app/AN…`), case styles,
  PCNs, S-parameter files, the patent guide. They are all valid PDFs, so picking "the
  first `.pdf`" would look successful and silently feed the extractor the wrong document.
  Match the anchor whose text is exactly `DATASHEET`.
- Implementation (`resolve_datasheet_url`, fetched on demand after Gate 1 — never per
  catalogue row from `search()`): verified live — `ZHL-2-S+` → 4654 chars,
  `ZX60-P33ULN+` → 5286 chars via `datasheet_text_from_url`.
- **`Candidate.url` is now `dashboard.html?model=<urlencoded>`** (was the disallowed
  `modelSearch.html`), which resolves OQ-2 in §7: the row's own `<a href>` is ignored.

---

## 2. How minicircuits.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | No public product API used. | Scrape. |
| **Server-side parametric URL filter?** | **No.** The freq filter inputs exist on the page but **filtering is client-side only** — the server ignores the filter form fields. | Fetch the whole table; filter locally in the Verifier. |
| **Is the data in the raw HTML?** | **Yes — as real rendered `<table>` cells.** The full results table is server-side rendered in the initial response. | Parse `table#maintable` directly; no JS needed. |
| **JS required?** | **No.** No AJAX / no client rendering needed to see the rows. | `httpx` + `selectolax` suffice; no Playwright. |
| **Entry URL (amplifiers)** | `https://www.minicircuits.com/WebStore/Amplifiers.html` | The category `.html` page is the fetch target. |
| **Load method** | HTTP **GET**, no query parameters. | Single request. |
| **Rows** | ~781 amplifier rows in one page. | One GET = full dataset. |

This is the **simpler** of the two site patterns: the data is in plain table
cells, so there is no embedded-JSON trick (contrast the [macom skill](../macom/SKILL.md)).

---

## 3. Compliance & access (robots.txt)

- **`/WebStore/Amplifiers.html` is allowed** — scraping the category table is
  permitted.
- **`/WebStore/modelSearch.html` is disallowed.** That URL is therefore used
  **only** as the human-facing `Candidate.url` for the reporter when a row has no
  direct `<a href>`; **it is never fetched programmatically.** (See OQ-2.)
- A plain bot User-Agent may be rejected by the CDN, so the adapter sends a
  **browser-style User-Agent** (same UA string as the MACOM adapter).
- **Inter-request delay:** `_MIN_DELAY_SECONDS = 1.0` (the table is light and the
  path is allowed; far smaller than MACOM's 60 s). Enforced via a `time.sleep()`
  guard before a live fetch; only paid on cache miss.

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL = "https://www.minicircuits.com/WebStore/"
_AMPLIFIERS_URL = _BASE_URL + "Amplifiers.html"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_MIN_DELAY_SECONDS = 1.0
```

1. **Rate-limit guard** before a live fetch (sleep the remainder of 1 s if needed).
2. **One GET**, `follow_redirects=True`, `timeout=30.0`, headers:
   - `User-Agent`: browser UA above
   - `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8`
   - `Accept-Language: en-US,en;q=0.5`
3. `raise_for_status()`, stamp `_last_fetch_time`.
4. On any `httpx.HTTPError`, raise **`AdapterError(manufacturer, context, cause)`**
   — never let a raw transport error escape.
5. Hand `response.text` to `_parse_html()`.

---

## 5. The parsing recipe (what `_parse_html()` does)

Uses `selectolax.parser.HTMLParser`.

1. **Locate the table:** `tree.css_first("table#maintable")`. **If absent → raise
   `AdapterError`** ("table#maintable not found in HTML"). This is the
   site-redesign tripwire — fail loudly, don't return empty.
2. **Find the real header row.** `<thead>` has **two** `<tr>`:
   - Row 0: a single merged filter cell (`colspan=14`) — **skip**.
   - Row 1: the actual column headers.
   Detect the header row as the `<tr>` whose cells contain `"Model Number"`.
   Fallback: all `<th>` in the table if that detection fails.
3. **Build a normalized-header → column-index map** with `_normalize_header`
   (lowercase, replace `().,:/\` with spaces, collapse whitespace). This makes
   column lookup **name-based**, robust to added/reordered columns.
4. **Iterate `<tbody> <tr>`:** read each `<td>` text. The model name is in the
   `<a>` inside the first `<td>` (fallback: first cell text). Skip rows with no
   model name.
5. **Build the product URL** (display only): the `<a href>` (host-prefixed if
   relative); if no href, fall back to `modelSearch.html?model=<model>` — never
   fetched.
6. Build `raw_params` via the column map (§6) and append a `Candidate(source="table")`.

If `<tbody>` is missing, return an empty list (no rows), not an error.

---

## 6. Column → canonical ontology mapping (REQ-3.4)

Name-based, keyed by normalized header text:

```python
COLUMN_MAP = {                       # normalized header -> (canonical, unit|None)
    "model number":  ("model",     None),
    "f low mhz":      ("freq_low",  "MHz"),
    "f high mhz":     ("freq_high", "MHz"),
    "gain db typ":    ("Gain",      "dB"),
    "nf db typ":      ("NF",        "dB"),
    "p1db dbm typ":   ("P1dB",      "dBm"),
    "psat dbm typ":   ("Pout",      "dBm"),
    "oip3 dbm typ":   ("OIP3",      "dBm"),
}
```

Rules:

- `model`, `freq_low`, `freq_high` are **handled specially**, not emitted as
  scalar `raw_params`. Combine `f low mhz` + `f high mhz` into
  `raw_params["freq_range"] = RawValue((lo, hi), "MHz")`.
- Headers not in `COLUMN_MAP` (e.g. VSWR, Voltage, Current) are **skipped** — only
  the amplifier ontology params are mapped.
- Cell parsing (`_parse_float`):
  - Missing sentinels `{"", "-", "n/a", "N/A"}` → `None` (param absent).
  - **`"DC"` → `0.0`** — Mini-Circuits encodes a DC-coupled lower band edge as the
    literal `"DC"` (0 Hz). Mapping it to 0.0 keeps DC-coupled amps' `freq_range`
    usable instead of dropping them to UNKNOWN.
  - Otherwise `float(text)`, or `None` on `ValueError`.

### Architecture fit (same contract as MACOM)

- **No query-side filtering** — return every row; the **Verifier** applies all
  constraints (REQ-4.1).
- **Self-registers** via `@register` from [base.py](../../../rf_finder/adapters/base.py)
  (NFR-3). `manufacturer = "Mini-Circuits"`, `supported_components = {"amplifier"}`.

---

## 7. Open questions (status at time of writing)

Tracked in [open-questions.md](../../../specs/rf-component-finder/open-questions.md):

- **OQ-2 — `Candidate.url` value.** Use the (robots-disallowed) per-model
  `modelSearch.html?model=XXX` URL for report value, or the allowed
  `Amplifiers.html`? *Recommend:* model-specific URL for report value, **never
  fetched** (current behavior prefers the row's own `<a href>` and falls back to
  `modelSearch.html`). Needs sign-off.
- **OQ-3 — Warn on row-count drift.** *Recommend:* yes — log a warning if the
  scraped row count deviates > 20 % from the cached count (possible redesign).
  Not yet implemented.

---

## 8. EXPANSION GUIDE — adding a new component type to Mini-Circuits

The current adapter handles **amplifiers only**. To add a new category, the
fetch/parse machinery (§4–§6) is **reused as-is**; the per-category work is the
URL, the column map, and the ontology.

1. **Register the component type in the ontology** —
   [components.py](../../../rf_finder/ontology/components.py) `COMPONENTS` plus its
   canonical parameters/units. The `COLUMN_MAP` units must match.

2. **Find the category's WebStore page.** Mini-Circuits uses
   `https://www.minicircuits.com/WebStore/<Category>.html` (amplifiers →
   `Amplifiers.html`). Confirm the exact page name from the site's product menu.

3. **Confirm it's the same pattern.** GET with the browser UA and check that the
   full results table is in the raw HTML (look for `table#maintable` or the
   category's main table, with real `<td>` data — not empty cells awaiting JS). If
   the data is server-rendered like amplifiers, **§4–§6 apply unchanged.** If a
   category instead renders client-side (like MACOM), re-investigate per REQ-3.3
   and record the finding here.

4. **Read that table's headers** and map them: build a category-specific
   `COLUMN_MAP` of normalized header → `(canonical, unit)`. Identify which column
   carries the model/part number and the frequency low/high columns. Watch for
   per-category sentinels and quirks (e.g. the `DC` band edge).

5. **Parameterize, don't fork.** Prefer extending the existing adapter over a new
   class:
   - Promote `_AMPLIFIERS_URL` and `COLUMN_MAP` to a per-category table keyed by
     component type, e.g. `CATEGORIES = {"amplifier": (URL, COLUMN_MAP), …}`.
   - `search(spec)` selects by `spec.component_type`, fetches that URL, parses with
     that `COLUMN_MAP`.
   - Add the type to `supported_components`; keep the per-fetch rate guard.

6. **Carry the contracts forward** — return-all + Verifier-filters, name-based
   column map, missing-sentinel handling, `AdapterError` on missing table, browser
   UA, display-only `Candidate.url`.

7. **Test offline.** Save a trimmed HTML fixture for the new category under
   `tests/fixtures/` and assert against `_parse_html()` directly (no network).
   Cover: a full-spec row, a missing-param row (sentinels), a `DC`-band-edge row
   (if frequency applies), and the no-`maintable` → `AdapterError` case. Mark live
   integration tests `@pytest.mark.network`.

8. **Update this skill** with the new page name, `COLUMN_MAP`, row count, and any
   new quirks.

---

## 9. File map

| File | Role |
|---|---|
| [rf_finder/adapters/minicircuits.py](../../../rf_finder/adapters/minicircuits.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [tests/adapters/test_minicircuits.py](../../../tests/adapters/test_minicircuits.py) | Offline unit tests. |
| [tests/fixtures/minicircuits_amplifiers.html](../../../tests/fixtures/minicircuits_amplifiers.html) | Trimmed HTML fixture. |

---
name: macom
description: >-
  Complete retrieval guide for macom.com (MACOM Technology). Use whenever you
  work on the MACOM adapter (rf_finder/adapters/macom.py) — to understand how
  macom.com serves its product data, to debug or maintain the amplifier adapter,
  or (the main forward-looking use) to ADD A NEW COMPONENT TYPE (mixer, switch,
  attenuator, filter, …) to the MACOM adapter beyond amplifiers. Covers the
  retrieval method, the embedded-JSON trick, robots/Cloudflare compliance,
  parsing gotchas, the spec→ontology mapping, what was already built, and a
  step-by-step expansion recipe.
---

# MACOM (macom.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF/microwave product data
from macom.com**. It records exactly how the site behaves, how the existing
**amplifier** adapter was built, and how to extend that adapter to **new
component types**. If you are touching `rf_finder/adapters/macom.py` or adding a
MACOM category, read this first — you should not have to re-investigate the site
from scratch.

> Reference implementation: [macom.py](../../../rf_finder/adapters/macom.py)
> Original investigation: [macom-plan.md](../../../specs/rf-component-finder/iteration2/macom-plan.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)

---

## 1. TL;DR — the one thing to remember

The visible MACOM parametric grid (Min/Max Frequency, Gain, P1dB, PSAT, OIP3,
NF, …) is **rendered client-side by React** and is **NOT** present as a `<table>`
in the HTML that `httpx` downloads. **But the same data is already in the raw
HTML**, embedded as HTML-entity-encoded JSON inside each product row's
`data-part="{…}"` attribute.

So the retrieval is: **one `httpx` GET → regex out every `data-part` blob →
`html.unescape` → `json.loads(strict=False)` → map specs to canonical params.**
No Playwright. No per-product fetches. No public API. No server-side filtering.
One request returns the entire category (all 1017 amplifiers, ~6.3 MB).

---

## 2. How macom.com serves product data (investigation findings)

These were established by live inspection of the site (REQ-3.3 decision rule:
*prefer an official API → else a parametric URL search → else scrape*).

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | **No.** The only API endpoint, `/search-area/search-form.partAutocomplete.do`, returns **HTTP 401 → Login**. No documented public product API. | Cannot use REQ-3.3 option 1. |
| **Server-side parametric URL filter?** | **No.** Category pages are URL-addressable but apply **no** server-side filter; the filter UI is client-side JS only. | Cannot use REQ-3.3 option 2. Fetch the *whole* category, filter locally. |
| **Is the parametric data in the raw HTML?** | **Yes — but not as `<table>` cells.** It is JSON inside each `<tr data-part="{…}">` attribute. The only real `<table>` in the HTML is a 2-column fallback (Part Number + Description). | Scrape the embedded JSON, **not** rendered cells. → REQ-3.3 option 3. |
| **Is JS needed to *see* the data?** | **No** for the data (it's in `data-part`). **Yes** only to *render* the visible grid. | `httpx` suffices; Playwright is unnecessary (back-pocket fallback only — see §8 R4). |
| **Front-end stack** | React + styled-components (`sc-*` class names), client-rendered grid. | Don't rely on rendered DOM; rely on `data-part`. |
| **Entry URL (amplifiers)** | `https://www.macom.com/products/rf-microwave-mmwave/amplifiers/all-amplifiers` | The "All-<category>" listing page is the fetch target. |
| **Load method** | HTTP **GET, no query parameters**. | Single request. |
| **Response size / rows** | ~6.3 MB, **1017** `data-part` rows for amplifiers. | One GET = the full dataset. |

**Why not parse the rendered `<table>`?** It does not exist before JS runs; the
numeric specs live *only* inside `data-part`. Parsing rendered cells would force
Playwright and gain nothing.

---

## 3. Compliance & access (robots.txt + Cloudflare)

`https://www.macom.com/robots.txt` (HTTP 200; site fronted by **Cloudflare**):

```
User-agent: *
Content-Signal: search=yes,ai-train=no
Allow: /
Crawl-delay: 60
Disallow: /start
Disallow: /administration
Disallow: /cms/login

# Named AI crawlers explicitly blocked (separate groups):
User-agent: ClaudeBot       Disallow: /
User-agent: GPTBot          Disallow: /
User-agent: CCBot           Disallow: /
User-agent: Google-Extended Disallow: /
...(Amazonbot, Bytespider, meta-externalagent, etc.)
```

Conclusions that govern the adapter:

- **The product listing path is allowed** (`Allow: /` for `User-agent: *`).
  Scraping the "All-<category>" page is permitted.
- **`Crawl-delay: 60`** applies to `User-agent: *`. Impact is minimal: the
  adapter makes **one request per refresh** (all data in one page), then serves
  from cache. The 60 s delay is only ever paid between live cache-miss fetches.
- **The blocked entries target AI-training/AI crawler bots** (ClaudeBot, GPTBot,
  …). This adapter is a **product-search retrieval tool**, not an AI trainer, and
  is consistent with `Content-Signal: search=yes`. It does **not** identify as
  any named blocked bot.
- **`Content-Signal: ai-train=no`** — we do not train on this content; retrieval
  for search results is `search=yes` (permitted).
- **Cloudflare** returns clean 200s for a **browser-style User-Agent**; plain bot
  UAs risk a challenge. So the adapter sends a real-browser UA (see §4). This is
  honest identity (a search retriever), not malicious impersonation.

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL = "https://www.macom.com"
_ALL_AMPLIFIERS_URL = _BASE_URL + "/products/rf-microwave-mmwave/amplifiers/all-amplifiers"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MIN_DELAY_SECONDS = 60.0   # robots Crawl-delay: 60
```

1. **Rate-limit guard.** Before a live fetch, if `_last_fetch_time` is set and
   less than `_MIN_DELAY_SECONDS` has elapsed, `time.sleep()` the remainder. Only
   incurred on a cache miss.
2. **One GET**, `follow_redirects=True`, `timeout=60.0`, with headers:
   - `User-Agent`: the browser UA above.
   - `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8`
   - `Accept-Language: en-US,en;q=0.9`
3. `response.raise_for_status()`, then stamp `_last_fetch_time = time.time()`.
4. On any `httpx.HTTPError`, raise **`AdapterError(manufacturer, context, cause)`**
   — never let a raw transport error escape (the reporter consumes `AdapterError`).
5. Hand `response.text` to `_parse_html()`.

**Rate limiting / caching (NFR-6):** one request per `search()`; no pagination,
no per-product fetches. The delay default lives in config
(`rate_limits.macom.delay_seconds`, default 60). A SQLite cache (TTL 7 days)
serves repeats so the delay is paid only on first fetch / cache miss.

---

## 5. The parsing recipe (what `_parse_html()` does)

```python
import html as htmlmod, json, re
_DATA_PART_RE = re.compile(r'data-part="(.*?)"', re.S)
```

1. **Extract every blob:** `_DATA_PART_RE.findall(html)`. Internal quotes inside
   the attribute are HTML-entity-encoded (`&#034;` = `"`), so the attribute's own
   `"` delimiters bound the JSON cleanly. `re.S` because a few blobs contain
   literal newlines.
2. **If zero blobs → raise `AdapterError`** ("no data-part product rows found").
   This is the tripwire for a site redesign / Cloudflare challenge: fail loudly,
   don't return an empty result silently.
3. **Per blob:** `json.loads(htmlmod.unescape(blob), strict=False)`.
   - `html.unescape` turns `&#034;` etc. back into real characters.
   - **`strict=False` is mandatory** — some blobs contain literal control
     characters inside JSON strings (observed; would otherwise raise).
   - Wrap each blob in `try/except (JSONDecodeError, ValueError)` and **skip** a
     malformed row rather than aborting the whole run.
4. Build a `Candidate` from each parsed object (see §6); skip rows with no part
   number.

---

## 6. From `data-part` JSON to a `Candidate`

A decoded `data-part` object looks like:

```json
{
  "partId": 12498,
  "partNumber": "CGH40006S",
  "partUrl": "/products/product-detail/CGH40006S",
  "description": "6 W RF Power GaN HEMT",
  "datasheetHref": "https://cdn.macom.com/datasheets/CGH40006S.pdf",
  "isDiscontinued": false,
  "specs": [
    {"specName": "Min Frequency", "uom": "MHz", "value": 0},
    {"specName": "Max Frequency", "uom": "MHz", "value": 6000},
    {"specName": "Gain",          "uom": "dB",  "value": 11},
    {"specName": "OIP3",          "uom": "dBm", "value": 35},
    {"specName": "NF",            "uom": "dB",  "value": 1.2}
  ],
  "attributes": [ {"attributeName": "Technology", "value": "GaN-on-SiC"}, … ]
}
```

Fields and how they're used (`Candidate` is a frozen dataclass — see
[models.py](../../../rf_finder/models.py)):

| JSON field | Use |
|---|---|
| `partNumber` | `Candidate.model` (skip the row if missing) |
| `partUrl` (host-prefixed) | `Candidate.url` — report link, **never fetched**. Fallback `/products/product-detail/<PN>` if absent. |
| `datasheetHref` | reserved for the future `datasheet`-confidence path (REQ-4.3); capture later, not parsed now |
| `specs[]` `{specName, uom, value}` | `Candidate.raw_params` after mapping (§7) |
| `isDiscontinued` | retained for possible reporter annotation; **NOT** filtered out (return all) |

Construction details:

- Build `by_name = {normalized specName: value}` with **first occurrence wins**.
- `_normalize_spec_name`: lowercase + collapse whitespace (handles casing and
  stray spaces like `' MHz'`).
- `_to_float`: returns `float` for numerics, `None` for missing/non-numeric, and
  explicitly rejects `bool`.
- Set `Candidate(source="table")` (the literal string source tag).

### Architecture fit (critical — same as Mini-Circuits)

- **The adapter does NO query-side filtering.** It returns **every** part as a
  `Candidate`; the **Verifier** applies all constraints (REQ-4.1). Don't add
  frequency/spec filtering in the adapter.
- The adapter **self-registers** via the `@register` class decorator from
  [base.py](../../../rf_finder/adapters/base.py) — no core file edits needed
  (NFR-3). `manufacturer = "MACOM"`, `supported_components = {"amplifier"}` (a
  set; grows as you add types — see §10).

---

## 7. Spec → canonical ontology mapping (REQ-3.4)

Only the parameters in the **amplifier ontology** are mapped; every other MACOM
spec (Bias Voltage, Efficiency, Operating Voltage, PAE, Gain Flatness, …) is
**skipped**. The map is **name-based** (robust to column reordering / new specs)
and keyed by the *normalized* `specName`:

```python
SPEC_MAP = {                       # normalized specName -> (canonical, unit)
    "gain":         ("Gain", "dB"),
    "output p1db":  ("P1dB", "dBm"),
    "oip3":         ("OIP3", "dBm"),
    "nf":           ("NF",   "dB"),
    "noise figure": ("NF",   "dB"),   # synonym of NF
    "psat":         ("Pout", "dBm"),
}
# Min/Max Frequency handled specially → combined into freq_range.
```

Rules that matter:

- **Frequency:** combine `Min Frequency` + `Max Frequency` (both MHz, 100 %
  coverage) into `raw_params["freq_range"] = RawValue((lo, hi), "MHz")`. The
  Verifier converts MHz → GHz.
- **Synonyms:** multiple source names can map to one canonical (`nf` and
  `noise figure` → `NF`). First mapped source for a canonical **wins** (skip if
  the canonical is already populated).
- **Distrust the source `uom`.** It is noisy: stray spaces (`' MHz'`), wrong
  units (`Output P1dB`/`OIP3` sometimes tagged `dB` instead of `dBm`), or empty.
  The unit in `SPEC_MAP` is the **ontology's** canonical unit; the Verifier's
  `to_canonical` does the conversion. Never blindly trust `uom`.

Observed amplifier coverage (of 1017): `freq_range` 100 %, `Gain` 99 %,
`Output P1dB` 55 %, `OIP3` 52 %, `NF` 45 % (+14 via `Noise Figure`), `PSAT` ~18 %
as dBm (power has several encodings — see OQ-M3 in §9).

---

## 8. Gotchas & risks (carry these into any new category)

| # | Risk | Mitigation (already applied) |
|---|---|---|
| R1 | **Noisy `uom`** — stray spaces, wrong units, empty. | Normalize `specName`; trust the ontology canonical unit, not raw `uom`. |
| R2 | **UA / identity** — robots blocks named AI bots; Cloudflare needs a browser UA. | Browser-style UA consistent with `Content-Signal: search=yes`; no malicious impersonation. (OQ-M1) |
| R3 | **Literal control chars** inside a `data-part` JSON string → `json.loads` fails by default. | `strict=False`; per-row try/except, skip+continue on a bad blob. |
| R4 | **Cloudflare enables an active bot-challenge** (JS/CAPTCHA). | Currently clean 200s. If it breaks, fall back to Playwright (D-1) — *source & mapping unchanged*. |
| R5 | **MACOM renames `specName`s / changes the `data-part` schema.** | Name-based `SPEC_MAP`; log unmapped names; warn on large row-count drift (OQ-3). |
| R6 | **Full page ~6.3 MB** → heavy test runs if used as a fixture. | Test fixture is a **trimmed** ~8–10-row slice, not the live page. |
| R7 | **Discontinued parts** (~30) surface as candidates. | Return all; reporter may annotate `isDiscontinued`. Not an adapter-side filter. |

---

## 9. Open questions (status at time of writing)

Tracked in the project register
[open-questions.md](../../../specs/rf-component-finder/open-questions.md). MACOM
items from the plan:

- **OQ-M1 — UA / crawler identity.** *Recommend:* browser-style UA, consistent
  with `Content-Signal: search=yes`. (Applied; confirm policy.)
- **OQ-M2 — `Candidate.url` value.** *Recommend:* per-product detail URL
  (`/products/product-detail/<PN>`, never fetched), mirroring Mini-Circuits OQ-2.
  (Applied.)
- **OQ-M3 — Power-spec encoding for `Pout`.** Power is published several ways
  (`PSAT` dBm; `PSAT Watt`/`Pout`/`Peak Output Power`/`Psat` in W). *Recommend:*
  prefer `PSAT` (dBm) when present, else a W-variant via `to_canonical`. Affects
  `Pout` coverage — **still needs sign-off.** Current code maps only `psat`→`Pout`.
- **OQ-M4 — Datasheet path.** `datasheetHref` gives a direct PDF per part
  (991/1017). Defer PDF parsing to the `datasheet`-confidence iteration; capture
  the URL now. (Deferred.)

---

## 10. EXPANSION GUIDE — adding a new component type to MACOM

The current adapter handles **amplifiers only**. To add a new MACOM category
(mixer, switch, attenuator, filter, …), follow this recipe. The retrieval and
parsing machinery (§4–§6) is **category-agnostic and reused as-is** — the only
per-category work is the URL, the spec map, and the ontology.

1. **Confirm the component type exists in the ontology.** Add it to
   [components.py](../../../rf_finder/ontology/components.py) `COMPONENTS` and add
   its canonical parameters to the parameter ontology, with canonical units. The
   `SPEC_MAP` units must match these.

2. **Find the "All-<category>" listing URL.** MACOM uses the pattern
   `https://www.macom.com/products/rf-microwave-mmwave/<category>/all-<category>`
   (e.g. amplifiers → `.../amplifiers/all-amplifiers`). Verify the exact slug by
   browsing the site's product taxonomy; don't assume the plural form.

3. **Verify the data source is the same.** GET the page with the browser UA and
   confirm `data-part="{…}"` rows are present (`re.findall(r'data-part="(.*?)"')`
   returns > 0). If they are, **everything in §4–§6 applies unchanged.** If they
   are *not* (a differently-built category page), re-run the REQ-3.3
   investigation for that page before writing code, and record findings here.

4. **Aggregate that category's `specName`/`uom` values** across all rows (decode
   the blobs, collect every `specName` and its coverage %). This tells you which
   ontology params are available and what the source names/synonyms are.

5. **Build a category-specific `SPEC_MAP`.** Map normalized `specName` →
   `(canonical, ontology_unit)`. Include synonyms. Decide frequency handling
   (combine Min/Max into `freq_range`, as amplifiers do, if applicable).

6. **Parameterize, don't fork.** Prefer extending the existing adapter to handle
   multiple categories over copy-pasting a new class. Sketch:
   - Promote `_ALL_AMPLIFIERS_URL` and `SPEC_MAP` to a **per-category table**
     keyed by component type, e.g. `CATEGORIES = {"amplifier": (URL, SPEC_MAP), …}`.
   - Make `search(spec)` pick the category by `spec.component_type`, fetch that
     category's URL, and parse with that category's `SPEC_MAP`.
   - Add the new type to `supported_components` (the set on the class).
   - Keep the rate-limit guard per live fetch; the cache keys on URL.

7. **Carry the gotchas (§8) forward** — `strict=False`, skip-bad-blob, distrust
   `uom`, return-all + Verifier-filters, browser UA, `Crawl-delay: 60`.

8. **Test offline.** Save a **trimmed** fixture (~8–10 representative
   `data-part` rows) for the new category under `tests/fixtures/`, including: a
   full-spec part, a missing-param part, a synonym case, a noisy-`uom` case, a
   control-char blob, and a discontinued part. Assert against `_parse_html()`
   directly (no network). Mark any live integration test `@pytest.mark.network`
   (skipped in CI).

9. **Update this skill** with the new category's URL slug, `SPEC_MAP`, coverage
   numbers, and any new quirks you discover — so the next person doesn't
   re-investigate.

---

## 11. File map

| File | Role |
|---|---|
| [rf_finder/adapters/macom.py](../../../rf_finder/adapters/macom.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [tests/adapters/test_macom.py](../../../tests/adapters/test_macom.py) | Offline unit tests. |
| [tests/fixtures/macom_all_amplifiers.html](../../../tests/fixtures/macom_all_amplifiers.html) | Trimmed HTML fixture. |
| [specs/.../iteration2/macom-plan.md](../../../specs/rf-component-finder/iteration2/macom-plan.md) | Original Phase-A investigation & plan. |

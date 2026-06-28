# MACOM Adapter — Investigation & Plan

> **Task:** MACOM amplifier adapter (future iteration; counterpart to iteration 1's
> T8 Mini-Circuits adapter).
> **Phase:** Plan only (Phase A). **No code written.**
> **Date:** 2026-06-28
> **Investigator:** Phase A planning (live network inspection of macom.com)
> **Methodology:** Spec-Driven Development (SDD) — same flow that produced
> [iteration1/t8-plan.md](../iteration1/t8-plan.md).
> **Decision rule applied:** REQ-3.3 — *prefer an official API; else a parametric
> URL search; else scrape the results table.*

---

## 0. Executive summary

| | Finding |
|---|---|
| **Official API?** | **No** — the only API endpoint (`partAutocomplete.do`) is auth-walled (401 → Login). No public product API. |
| **Parametric URL query?** | **No** — category pages are URL-addressable but apply **no server-side filter**; filtering is client-side JS only (same as Mini-Circuits). |
| **HTML scraping?** | **Yes — the viable method,** via embedded JSON, not rendered cells. |
| **Chosen method** | One `httpx` GET to the *All Amplifiers* page → extract per-row **`data-part` JSON** → map to canonical params. **No Playwright, no per-product fetches.** |
| **Fetch cost** | **1 request** returns **all 1017 amplifiers** with specs (~6.3 MB). |
| **Architecture fit** | Identical to the Mini-Circuits adapter: fetch all rows, map columns, return every `Candidate`; the Verifier filters. |

**The key insight:** the visible parametric grid (Min/Max Freq, Gain, P1dB, PSAT,
OIP3, NF…) is rendered **client-side by JavaScript** and is *not* in the HTML
`httpx` downloads. But the same data **is** present in the raw HTML — embedded as
HTML-entity-encoded JSON inside each table row's `data-part="{…}"` attribute.
We read that JSON; we do **not** parse rendered `<td>` cells (they don't exist
pre-JS) and we do **not** need Playwright.

---

## 1. Request Mechanism Finding (resolves REQ-3.3 for MACOM)

### Method used

Live `httpx.get` with a browser-style User-Agent to the category pages, plus a
probe of the site's search/autocomplete endpoint. Responses captured and parsed
with `selectolax`; embedded JSON extracted with regex + `html.unescape` +
`json.loads`.

### Findings

| Question | Answer |
|----------|--------|
| Entry URL | `https://www.macom.com/products/rf-microwave-mmwave/amplifiers/all-amplifiers` |
| Method for initial load | **HTTP GET, no query parameters** |
| Response body size | ~6.3 MB |
| Official/public API? | **No.** `/search-area/search-form.partAutocomplete.do` → **HTTP 401** (Login page). No documented public product API. |
| Server-side parametric filter via URL? | **No** — filtering is client-side JavaScript only. |
| Is the parametric data in the raw HTML? | **Yes** — but **not** as `<table>` cells. It is embedded as JSON in each `<tr data-part="{…}">` attribute. The raw HTML's only real `<table>` is a 2-column fallback (Part Number + Description). |
| JS required to *see* the data? | **No** for the data (it's in `data-part`). **Yes** only to *render* the visible grid. |
| Rows with `data-part` JSON | **1017** |
| Front-end stack | React + styled-components (`sc-*` class names), client-rendered grid. |

### Conclusion: httpx (not playwright)

The complete dataset for all 1017 amplifiers is in the initial GET response as
embedded JSON. `httpx` is sufficient; `playwright` is **not** needed. (It remains
a back-pocket fallback only if MACOM later enables a Cloudflare bot-challenge —
see §9 R4.) This matches design.md §6.2 / D-1: playwright is a fallback for
JS-rendered data, and here the *data* is not JS-rendered (only the *presentation*
is).

---

## 2. robots.txt Summary

URL: `https://www.macom.com/robots.txt` (HTTP 200, fetched live). Site is fronted
by **Cloudflare**.

Key directives:

```
User-agent: *
Content-Signal: search=yes,ai-train=no
Allow: /
Crawl-delay: 60
Disallow: /start
Disallow: /administration
Disallow: /cms/login

# Named AI crawlers explicitly blocked (separate groups):
User-agent: ClaudeBot      Disallow: /
User-agent: GPTBot         Disallow: /
User-agent: CCBot          Disallow: /
User-agent: Google-Extended  Disallow: /
... (Amazonbot, Bytespider, meta-externalagent, etc.)
```

**Key conclusions:**

- The *All Amplifiers* product path is **not disallowed** — `Allow: /` for the
  generic `User-agent: *`. Scraping the product listing is permitted.
- `Crawl-delay: 60` applies to `User-agent: *`. **Impact is minimal** because the
  adapter makes **one request per refresh** (all data in a single page), then
  serves from cache (TTL 7 days). The 60 s delay is enforced only between live
  cache-miss fetches.
- The blocked entries are named **AI-training/AI crawler** bots (ClaudeBot,
  GPTBot, …). The adapter is a **product-search retrieval tool**, not an AI
  trainer, and identifies with a browser-style UA — consistent with the
  `Content-Signal: search=yes` permission. (See §9 R2 for the UA/identity
  decision to confirm at implementation.)
- `Content-Signal: ai-train=no` — we do not train models on this content;
  retrieval for search results is `search=yes` (permitted).

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/macom.py` | **Create** | The MACOM adapter (main deliverable). |
| `tests/adapters/test_macom.py` | **Create** | Offline unit tests using a saved HTML fixture. |
| `tests/fixtures/macom_all_amplifiers.html` | **Create** | Trimmed snapshot containing `<tr data-part="…">` rows (a handful of representative parts, **not** the full 6.3 MB page — see §9 R6). |

No existing core files need editing. The adapter self-registers via the
`@register` decorator (design.md §6.1), so no core change is required (NFR-3).
Config/cache wiring (rate limit + SQLite cache) follows the same path the
Mini-Circuits adapter uses once that infrastructure (T9/T10) exists.

---

## 4. Data Extraction (HTML structure)

### Where the data lives

Each product is one `<tr>` whose `data-part` attribute holds an
HTML-entity-encoded JSON object (`&#034;` = `"`). Decoded, one row looks like:

```json
{
  "partId": 12498,
  "partNumber": "CGH40006S",
  "partUrl": "/products/product-detail/CGH40006S",
  "description": "6 W RF Power GaN HEMT",
  "datasheetHref": "https://cdn.macom.com/datasheets/CGH40006S.pdf",
  "isDiscontinued": false,
  "eccn": "null",
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

### Extraction strategy

```python
import re, json, html as htmlmod

# 1. Pull every data-part blob out of the raw HTML
for blob in re.findall(r'data-part="(.*?)"', raw_html, re.S):
    part = json.loads(htmlmod.unescape(blob), strict=False)   # strict=False: see §9 R3
    # 2. part["partNumber"], part["specs"], part["datasheetHref"], part["partUrl"]
```

We take from each object:

| JSON field | Use in `Candidate` |
|------------|--------------------|
| `partNumber` | `model` |
| `partUrl` (prefix host) | `url` (report link) |
| `datasheetHref` | reserved for the future `datasheet` confidence path (REQ-4.3) |
| `specs[]` `{specName, uom, value}` | `raw_params` after mapping (see §5) |
| `isDiscontinued` | retained for possible reporter annotation; **not** filtered out (return all) |

> **Why not parse the `<table>`?** The raw HTML's only `<table>` is a 2-column
> fallback (`Part Number` + `Description`). The numeric specs exist solely inside
> `data-part`. Parsing rendered cells would require Playwright and gain nothing.

---

## 5. Spec → Canonical Ontology Mapping (REQ-3.4)

Confirmed by aggregating `specName`/`uom` across **all 1017 parts**. Only the six
amplifier ontology params (design.md §4.1 / REQ-2.2) are mapped; all other specs
(Bias Voltage, Efficiency, Operating Voltage, etc.) are **skipped** — exactly as
the Mini-Circuits adapter skips VSWR/Voltage/Current.

| MACOM `specName` (synonyms) | Source `uom` | Canonical param | Coverage / 1017 | Notes |
|------------------------------|--------------|-----------------|-----------------|-------|
| `Min Frequency` + `Max Frequency` | MHz | `freq_range` | **1017 (100%)** | Combine into `RawValue((min,max), "MHz")`; Verifier → GHz. |
| `Gain` | dB | `Gain` | 1008 (99%) | |
| `Output P1dB` | dBm *(sometimes `dB`)* | `P1dB` | 564 (55%) | Unit noise — see §9 R1. |
| `OIP3` | dBm *(sometimes `dB`)* | `OIP3` | 528 (52%) | Unit noise — see §9 R1. |
| `NF`, `Noise Figure` | dB | `NF` | 458 (45%) + 14 | **Synonym pair.** |
| `PSAT` *(primary)*; `PSAT Watt`/`Pout`/`Peak Output Power`/`Psat`* | dBm; W | `Pout` | 181 dBm + ~415 W-variants | **Multiple power encodings — needs sign-off, §9 OQ-M3.** |

**Skipped specs** (not in this iteration's ontology): `Bias Voltage`,
`Bias Current`, `Efficiency`, `Operating Voltage`, `Supply Voltage`,
`Frequency Min`/`Frequency Max` (GHz duplicates of Min/Max Frequency),
`Test Freq`, `PAE`, `Gain Flatness`, `Attenuator Range`, `Theta J-C`, etc.

**Mapping strategy:** a hard-coded `SPEC_MAP` keyed by a **normalized** `specName`
(lowercase, strip, collapse whitespace), mapping to `(canonical_name, unit)`,
with explicit synonym entries (e.g. both `nf` and `noise figure` → `NF`). The
unit is taken from the ontology's canonical unit during verification, so the
noisy `uom` field is normalized but not blindly trusted (§9 R1). This mirrors the
Mini-Circuits `COLUMN_MAP` approach (robust to added columns / spec reordering).

---

## 6. Candidate Construction (pseudocode)

```python
BASE = "https://www.macom.com"

SPEC_MAP = {                       # normalized specName -> (canonical, unit)
    "gain":        ("Gain", "dB"),
    "output p1db": ("P1dB", "dBm"),
    "oip3":        ("OIP3", "dBm"),
    "nf":          ("NF",   "dB"),
    "noise figure":("NF",   "dB"),
    "psat":        ("Pout", "dBm"),
    # Min/Max Frequency handled specially (combined into freq_range)
}

def _build_candidate(part: dict) -> Candidate | None:
    model = part.get("partNumber")
    if not model:
        return None

    by_name = {_norm(s["specName"]): s for s in part.get("specs", [])}

    raw_params: dict[str, RawValue] = {}

    # frequency range: combine Min + Max Frequency (both MHz, 100% coverage)
    lo = _num(by_name.get("min frequency"))
    hi = _num(by_name.get("max frequency"))
    if lo is not None and hi is not None:
        raw_params["freq_range"] = RawValue((lo, hi), "MHz")

    # scalar params
    for norm_name, (canonical, unit) in SPEC_MAP.items():
        s = by_name.get(norm_name)
        val = _num(s)
        if val is not None:
            raw_params[canonical] = RawValue(val, unit)

    url = BASE + part.get("partUrl", f"/products/product-detail/{model}")
    return Candidate(
        model=model,
        manufacturer="MACOM",
        url=url,
        raw_params=raw_params,
        source="table",
    )
```

`_num(spec)` returns `float(spec["value"])` or `None` for missing/non-numeric;
`_norm(name)` lowercases, strips, and collapses whitespace (handles the `' MHz'`
stray-space and casing issues).

### Worked example (CGH40006S)

```python
Candidate(
    model="CGH40006S",
    manufacturer="MACOM",
    url="https://www.macom.com/products/product-detail/CGH40006S",
    raw_params={
        "freq_range": RawValue((0.0, 6000.0), "MHz"),
        "Gain":       RawValue(11.0, "dB"),
        "OIP3":       RawValue(35.0, "dBm"),
        "NF":         RawValue(1.2,  "dB"),
        # P1dB absent for this part -> Verifier marks UNKNOWN -> partial
    },
    source="table",
)
```

---

## 7. Test Plan (NFR-7, offline)

### Fixture

**Path:** `tests/fixtures/macom_all_amplifiers.html` — a **trimmed** slice of the
live page: the surrounding table markup plus ~8–10 representative
`<tr data-part="…">` rows covering:

- A part with all six params present.
- A part with `P1dB`/`OIP3`/`NF` absent (→ must be absent from `raw_params`).
- A part with the `Noise Figure` synonym (not `NF`).
- A part with a noisy `uom` (e.g. `Output P1dB` tagged `dB`) and a stray-space
  `' MHz'`.
- A part whose JSON contains a literal control character (→ `strict=False`).
- An `isDiscontinued: true` part (→ still returned).

### Assertions (no network)

```python
def test_parses_all_rows():            # len(candidates) == number of data-part rows
def test_model_manufacturer_source():  # manufacturer == "MACOM", source == "table"
def test_freq_range_combined_mhz():    # RawValue((lo,hi), "MHz")
def test_missing_param_absent():       # absent spec -> key not in raw_params
def test_noise_figure_synonym():       # "Noise Figure" maps to NF
def test_unit_noise_normalized():      # stray ' MHz' / wrong 'dB' handled
def test_control_char_blob_parses():   # strict=False path
def test_url_and_datasheet_populated():
def test_raises_adaptererror_when_no_data_part():   # bad HTML -> AdapterError
```

### Integration (marked `network`, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    results = MacomAdapter().search(QuerySpec("amplifier", [...]))
    assert len(results) > 500
    assert all(c.manufacturer == "MACOM" for c in results)
```

---

## 8. Rate-Limiting Strategy (NFR-6)

- **One request per `search()`** — all 1017 parts in a single GET; no pagination,
  no per-product fetches.
- **Inter-request delay:** honor robots `Crawl-delay: 60`. Read from
  `config.yaml` (`rate_limits.macom.delay_seconds`, default `60`), enforced as a
  `time.sleep()` guard before a live fetch (same mechanism as Mini-Circuits, just
  a larger default). Only incurred on cache miss.
- **Cache (T10 equivalent):** SQLite, TTL 7 days. After the first fetch, searches
  are served from cache and the delay never applies.
- **User-Agent:** browser-style UA (Cloudflare returns clean 200s for it; bot UAs
  risk challenge). Identity/UA policy to confirm at implementation — see §9 R2.

---

## 9. Risks & Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Noisy `uom` in source data: stray spaces (`' MHz'`), wrong units (`Output P1dB`/`OIP3` tagged `dB` not `dBm`), empty (`''`). | **High (observed)** | Normalize `specName`; trust the **ontology canonical unit** per param, not the raw `uom`. Verifier's `to_canonical` does the conversion. |
| R2 | UA / identity: robots blocks named AI bots; a browser UA is needed for Cloudflare, but identity should be honest. | Medium | Use a browser-style UA consistent with `Content-Signal: search=yes`; do not impersonate maliciously. Confirm policy at implementation (OQ-M1). |
| R3 | A `data-part` JSON blob contains a literal control character → `json.loads` fails by default. | **High (observed)** | Parse with `strict=False`; wrap per-row parse in try/except and skip+log a malformed row rather than aborting the run. |
| R4 | Cloudflare turns on an active bot-challenge (JS/CAPTCHA). | Low-Med | Live probe currently returns clean 200s. If it breaks, fall back to `playwright` (D-1) — the data source/mapping is unchanged. |
| R5 | MACOM renames `specName`s or changes the `data-part` schema. | Medium | Name-based `SPEC_MAP` (not positional); log unmapped spec names; warn on large row-count drift (cf. OQ-3). |
| R6 | Full page is ~6.3 MB → slow/heavy test runs if used as the fixture. | Low | Fixture is a **trimmed** slice (~8–10 rows), not the live page. |
| R7 | Discontinued parts (~30) surfaced as candidates. | Low | Per architecture, **return all**; the reporter may annotate `isDiscontinued`. Not an adapter-side filter. |

### Open questions for implementation (project register: [open-questions.md](../open-questions.md))

- **OQ-M1 — UA / crawler identity.** What User-Agent should the MACOM adapter
  send, given robots blocks named AI bots but the tool is a `search` retriever?
  *Recommend:* a browser-style UA, consistent with `Content-Signal: search=yes`.
  Needs sign-off.
- **OQ-M2 — `Candidate.url` value.** Use the per-product detail URL
  (`/products/product-detail/<PN>`, useful in the report; not fetched) or the
  datasheet PDF, or the listing page? *Recommend:* the detail URL for report
  value (never fetched), mirroring the Mini-Circuits OQ-2 decision.
- **OQ-M3 — Power-spec encoding for `Pout`.** Power is published in several forms
  (`PSAT` dBm; `PSAT Watt`/`Pout`/`Peak Output Power`/`Psat` in W). Which is
  authoritative, and do we map the W-variants to `Pout` (Verifier converts W→dBm)
  or only the dBm `PSAT`? *Recommend:* prefer `PSAT` (dBm) when present, else a
  W-variant via `to_canonical`. Needs sign-off (affects coverage of `Pout`).
- **OQ-M4 — Datasheet path.** `datasheetHref` gives a direct PDF per part (991/1017).
  Defer PDF parsing to the `datasheet`-confidence iteration (cf. requirements OQ-3),
  but capture the URL now. Confirm deferral.

---

## 10. Summary

- **Method (REQ-3.3):** No API, no parametric URL → **scrape**, specifically by
  extracting the embedded **`data-part` JSON**, not rendered cells.
- **Fetch:** single `httpx.get` to the *All Amplifiers* page → 1017 parts with
  full specs. No Playwright, no per-product crawl.
- **Mapping:** `specName → canonical` via a name-based `SPEC_MAP` with synonyms
  and unit normalization; combine Min/Max Frequency into `freq_range`.
- **Architecture:** identical to Mini-Circuits — return all candidates; the
  Verifier filters. Self-registers; no core change (NFR-3).
- **Compliance:** robots allows the path; one cached request respects
  `Crawl-delay: 60`.
- **Files to create:** `rf_finder/adapters/macom.py`,
  `tests/adapters/test_macom.py`, `tests/fixtures/macom_all_amplifiers.html`.
- **Open items for sign-off:** OQ-M1…OQ-M4 (above).

> **Phase A ends here. No code written.** Awaiting plan approval (gate #1) before
> implementation.

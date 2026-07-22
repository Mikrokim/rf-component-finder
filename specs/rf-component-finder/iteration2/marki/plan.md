# Marki Microwave Adapter — Plan

> **Task:** Marki adapter — `adapters/marki.py` (Iteration 2, extends design.md §6.1–6.2)
> **Phase:** Plan (Phase A). Documents the confirmed request/parse strategy.
> **Date:** 2026-07-02
> **Investigator:** Phase A planning agent
> **SDD trace:** REQ-3.1, REQ-3.4, REQ-3.5, REQ-3.6, REQ-4.1, NFR-4, NFR-6 · design.md §6.1–6.2
> **Pattern:** Server-side-rendered HTML table scrape (SvelteKit), table-only.

> **Revision (2026-07-16):** The adapter is now **single-pass, table-only**. The
> gated per-product-page enrichment (Pass 2 — Size / VDD / Temperature) was
> **removed**: those params, plus MSL, are left UNKNOWN and are owned by the
> datasheet-extraction pipeline. Sections below that describe "Pass 2" are retained
> for history but no longer reflect the code.

---

## 1. Request Mechanism Finding

### Method used

Live `httpx.get` (browser User-Agent) to the search endpoint
`https://markimicrowave.com/search/?item_per_page=200&page=1&keyword=&family=amplifiers`,
and to a product page `…/products/{package}/amplifiers/{slug}/`. Bodies captured,
tables parsed, and the SvelteKit data payload inspected.

### Findings

| Question | Answer |
|----------|--------|
| Base URL | `https://markimicrowave.com` |
| Search endpoint | `/search/?item_per_page={N}&page={P}&keyword=&family=amplifiers` |
| Method | **HTTP GET**; results table is **server-side rendered by SvelteKit** in the initial HTML |
| Catalogue size | ~123 amplifiers (embedded as the string `"1 - 123 of 123"`) |
| AJAX / POST for the table? | **No** — rows are in the raw HTML of each page |
| Server-side spec filter? | **No** — the F-Low/F-High/Gain/NF inputs are client-side JS only; server returns all rows for a page |
| Cloudflare? | Present, but a **browser-style UA returns the table** (no challenge observed); large `item_per_page` works |
| JS rendering required? | **No** for the search table |
| Params NOT in the search table | **Size**, **VDD**, **Temperature** (and **MSL**) — left UNKNOWN; owned by the datasheet pipeline, not fetched here |

### Conclusion: httpx (not playwright), single-pass table-only

`httpx` + `selectolax` suffice for the search table, which is the whole adapter.

The adapter will:
1. GET the search table (paginated); map model, freq_range, Gain, NF, Psat, IP3
   (Marki's OIP3), P1dB, product URL.
2. Return **all** rows; the Verifier applies constraints (REQ-4.1).

Params absent from the search table — Size, VDD, Temperature, MSL — verify as
UNKNOWN and are handled by the datasheet-extraction pipeline. Individual product
pages are **not** fetched.

> **Historical design note:** an earlier version added a gated second pass (one GET
> per product page for Size/VDD/Temperature) to avoid ~123 fetches on the common
> freq/gain search. That pass was removed in the 2026-07-16 revision.

---

## 2. robots.txt Summary

URL: `https://markimicrowave.com/robots.txt` (HTTP 200, fetched live). It is a long
bad-bot blocklist; the generic rule is permissive:

```
User-agent: *
Allow: /
# (dozens of named "bad bots" above are each Disallow: /)
```

**Key conclusions:**
- `/search/` and `/products/{pkg}/amplifiers/{slug}/` are **allowed** (`/search`
  is not mentioned; `*` → `Allow: /`).
- Datasheet PDFs are allowed but **not fetched** — all structured data comes from
  the HTML pages / embedded JS.
- `Candidate.url` = the product page (allowed; safe to fetch for Pass 2).

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/marki.py` | **Create** | The Marki adapter (main deliverable) |
| `tests/adapters/test_marki.py` | **Create** | Offline tests over captured fixtures + a live test |
| `tests/fixtures/marki_amplifiers.html` | **Create** | Search-table slice (header + sample rows) |
| `tests/fixtures/marki_product_adm11425psm.html` | **Create** | Product page (table + JS payload) |

Plus the `__main__.py` registration import.

---

## 4. HTML Structure and Parsing Strategy (verified live)

**Critical, non-obvious fact:** each `<tbody>` `<tr>` **begins with a `<th>`**
carrying the part number and its product href
(`<th><a href="/products/{pkg}/amplifiers/{slug}/">PN</a>`), followed by 13
`<td>` data cells. The data cells therefore align to `col_names[1:]` — **NOT**
`col_names` — so the part-number header is dropped before positional mapping
(an off-by-one vs a naive `header[i] → cell[i]`). `css("td,th")` reorders, so the
`<th>` (model) and the `<td>`s are queried separately.

**Header quirks:** `<th>` text is concatenated with filter-dropdown junk for
"Subfamily" and "Package Type" (match by `startswith`), and frequency headers
render as `FLow[GHz]`/`FHigh[GHz]` — **square brackets must be stripped** in header
normalization (`[()\[\]{}.,:/\\]` → space).

```python
tree = HTMLParser(html)
table = tree.css_first("table")
col_names = [_normalize(th.text(strip=True)) for th in thead_last_tr.css("th")]
data_headers = col_names[1:]                     # drop "Part Number" (<th>)
for row in table.css_first("tbody").css("tr"):
    a = row.css_first("th a")                    # model + product href
    for i, td in enumerate(row.css("td")):       # align to data_headers[i]
        ...
```

---

## 5. Column / Field Mapping

### Pass 1 — search table (by normalized header name)

| Normalized header | Canonical param | Source unit |
|-------------------|-----------------|-------------|
| `flow ghz` | `freq_range` (low) | GHz |
| `fhigh ghz` | `freq_range` (high) | GHz |
| `gain db` | `Gain` | dB |
| `nf db` | `NF` | dB |
| `psat dbm` | `Psat` | dBm |
| `oip3 dbm` | `IP3` | dBm (Marki lists OIP3) |
| `p1db dbm` | `P1dB` | dBm |
| Part Number, BUY NOW, Subfamily, Datasheet, SnP, Package Type, Status | — | skipped |

- Missing/NaN sentinel `"-"` → param absent (UNKNOWN), row kept.
- DC-coupled bare-die parts list F Low `0` → 0.0 GHz (valid, kept).

### Pass 2 — per-product page

| Param | Source | Representation |
|-------|--------|----------------|
| **Size** | product-table "Size" column (`"{W} x {H} mm"`), matched to the row whose `<th> a` = model (ignore EVB variant "-") | larger dimension → `RawValue(mm)` (ontology models Size as scalar "max"/mm) |
| **VDD** | SvelteKit JS payload `power_supply_voltage:[{value:"5"}]` | first parseable → `RawValue(V)`; bare-die w/o SnP → UNKNOWN |
| **Temperature** | JS payload `temperature:"25"` | characterisation point → degenerate `RawValue((25,25), degC)` (ontology "contains"; a point never falsely contains a band) |
| **MSL** | not present anywhere in HTML/JS | always UNKNOWN (only in datasheet PDF; not fetched) |

---

## 6. Candidate Construction (Pseudocode)

```python
SCALAR = {"gain db":("Gain","dB"), "nf db":("NF","dB"), "psat dbm":("Psat","dBm"),
          "oip3 dbm":("IP3","dBm"), "p1db dbm":("P1dB","dBm")}

# Pass 1
for row in tbody.css("tr"):
    a = row.css_first("th a");  model = a.text(strip=True)
    url = absolutise(a.attributes["href"])
    raw = {}; flo=fhi=None
    for i, td in enumerate(row.css("td")):
        norm = data_headers[i]; val = _parse_float(td.text(strip=True))
        if val is None: continue
        if norm.startswith("flow"): flo = val
        elif norm.startswith("fhigh"): fhi = val
        elif norm in SCALAR: c,u = SCALAR[norm]; raw[c] = RawValue(val,u)
    if flo is not None and fhi is not None: raw["freq_range"] = RawValue((flo,fhi),"GHz")
    cand = Candidate(model, "Marki Microwave", url, raw, "table")

# Pass 2 (only if spec constrains Size/VDD/Temperature) — resilient per page
if needs_product_pages(spec):
    cand = enrich(cand)     # Size (table row match), VDD & Temperature (regex on JS payload)
```

`_parse_float` maps `"-"`/empty → None; header normalization strips `[]()` etc.

---

## 7. Test Plan

**Fixtures** captured live: a search-table slice (`marki_amplifiers.html`) and a
product page (`marki_product_adm11425psm.html`, incl. the JS payload line).

**Offline tests** (`tests/adapters/test_marki.py`) call `_parse_search_html` /
`_extract_product_details` directly:
- `test_part_number_th_offset_mapping` — the leading `<th>` does not shift the
  `<td>`→header alignment (Gain 23.0, NF 3.3, IP3 19.5, P1dB 10.5).
- `test_freq_range_is_rawvalue_tuple_in_ghz`; `test_dc_coupled_low_edge_is_zero`.
- `test_missing_cell_is_absent_not_none` (Psat `"-"`).
- `test_size_from_matching_variant_row` / `test_size_absent_for_evb_variant`.
- `test_vdd_from_js_payload`; `test_temperature_is_degenerate_range_in_degc`.
- enrichment-gating tests (freq-only query → no Pass 2).
- `@pytest.mark.network test_search_live` — >100 amplifiers, all Marki.

---

## 8. Rate Limiting Strategy

- Pass 1: 1 GET (item_per_page=200 covers all 123); fallback to 50/page paging.
- Pass 2: 1 GET per candidate, **only when gated on** — else zero.
- **Minimum inter-request delay:** 1.5 s (`_MIN_DELAY_SECONDS`); 3× retry w/ backoff.
- **User-Agent:** browser-style (avoids the Cloudflare challenge for these URLs).
- **Cache (T10):** responses cached per URL.

---

## 9. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Off-by-one if the part-number `<th>` moves | Medium | Drop `col_names[0]`; query `<th> a` and `<td>`s separately (tested) |
| R2 | Cloudflare starts challenging the search URL | Low-Med | Browser UA works now; fallback item_per_page=50; Playwright cf_clearance if needed |
| R3 | Bracketed headers (`FLow[GHz]`) not normalized | Resolved | Normalization strips `[]` |
| R4 | Size as string vs ontology scalar mm | Resolved | Store larger dimension (mm) to fit "max" comparison |
| R5 | Temperature is a char point, ontology is "contains" | Resolved | Degenerate `(t,t)` range — never a false PASS |
| R6 | 123 product-page fetches too slow | Resolved | Pass 2 gated on the query |

### Open questions
- **OQ-1:** If Cloudflare tightens, adopt Playwright to obtain `cf_clearance`.
- **OQ-2:** MSL is unavailable in HTML — flag parts for manual datasheet review if
  the Verifier requires MSL.

---

## Summary

- **Fetch:** single-pass paginated GET of the SvelteKit search table (no JS/AJAX).
  Size/VDD/Temperature/MSL are off-table → UNKNOWN (datasheet pipeline); product
  pages are not fetched.
- **Parse:** part number is a row `<th>` (href); `<td>`s align to `headers[1:]`;
  headers normalized (brackets stripped); map by name.
- **robots.txt:** `/search/` allowed; product pages and datasheet PDFs not fetched.
- **Files:** `rf_finder/adapters/marki.py`, `tests/adapters/test_marki.py`, the
  `marki_amplifiers.html` fixture, plus the `__main__.py` registration import.

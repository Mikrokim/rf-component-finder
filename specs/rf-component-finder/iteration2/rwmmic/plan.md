# RWM (rwmmic) Adapter — Plan

> **Task:** RWM adapter — `adapters/rwmmic.py` (Iteration 2, extends design.md §6.1–6.2)
> **Phase:** Plan (Phase A). Documents the confirmed request/parse strategy.
> **Date:** 2026-07-02
> **Investigator:** Phase A planning agent
> **SDD trace:** REQ-3.1, REQ-3.3, REQ-3.4, REQ-3.5, REQ-3.6, REQ-4.1, NFR-4, NFR-6 · design.md §6.1–6.2
> **Pattern:** JSON API (like the Analog Devices adapter), NOT HTML scraping.

---

## 1. Request Mechanism Finding

### Method used

Live `httpx.get` to `https://www.rwmmic.com/product.html`; its inline JavaScript
inspected for the data source; the discovered API endpoints then called directly.

### Findings

| Question | Answer |
|----------|--------|
| Base URL | `https://www.rwmmic.com/` |
| `/product.html` | An almost-empty **JS shell**; product rows are NOT in the HTML |
| Data source | The page's JS (axios) calls a **JSON API** |
| Products endpoint | `https://www.rwmmic.com/index.php?r=api/all-products` — returns the **whole catalogue in one GET** |
| Category endpoint | `…?r=api/category-menu` — the category tree (not needed for the chosen filter) |
| Response shape | `{success, data:[ {category:{id,name}, field_definitions, products:[{name, field_values:[{field_name,value}]}], product_count} ]}` — grouped by category, **no flat product list** |
| Server-side spec filter? | **No** — API returns the whole catalogue |
| JS rendering required? | **No** — the API is called directly with `httpx` |
| Per-product detail page/endpoint? | **None** — `?id=` is ignored; `api/product*` → 404. Only a per-part **Datasheet** URL exists |

### Conclusion: httpx JSON API (not scraping, not playwright)

Per the REQ-3.3 preference order (documented API > parametric page > scrape), this
adapter uses the **JSON API directly** — one GET returns everything. `selectolax`
is not needed.

The adapter will:
1. GET `api/all-products` once.
2. Select amplifier category groups; map each product's `field_values` → canonical.
3. Return **all** amplifier rows; the Verifier applies constraints (REQ-4.1).

> **Design note (TLS):** rwmmic.com serves a **self-signed certificate in its
> chain** — strict verification fails (confirmed live: a control fetch of another
> vendor succeeds with verification on, rwmmic fails). The adapter sets
> `_VERIFY_TLS = False` for this host; flip to True on a network that trusts the
> site's cert.

---

## 2. robots.txt Summary

URL: `https://www.rwmmic.com/robots.txt` (HTTP 200, fetched live)

```
User-agent: *
Disallow:
```

**Key conclusions:**
- **Everything is allowed** (empty `Disallow:`). The `api/all-products` endpoint
  is fair game.
- Datasheet PDFs are allowed but **not fetched** — all structured data is in the
  JSON. `Candidate.url` = the per-part datasheet link (display only; never fetched).

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/rwmmic.py` | **Create** | The RWM adapter (main deliverable) |
| `tests/adapters/test_rwmmic.py` | **Create** | Offline tests over a trimmed JSON fixture + a live test |
| `tests/fixtures/rwmmic_products.json` | **Create** | Trimmed `all-products` slice (2 amp groups + 1 switch group) |

Plus the `__main__.py` registration import.

> **Note:** the repo's `rf_finder/cache.py` is still a T10 stub (`get_cache()` not
> implemented), so the adapter fetches directly for now, like the other live
> adapters; caching wires in once T10 lands.

---

## 4. Data Structure and Selection Strategy

### Amplifier selection (one request, in-memory filter)

The `all-products` response is grouped into ~53 category groups. Every amplifier
category's name contains the word **"Amplifier"** (Low Noise, Low Noise with
Limiter, Distributed, Driver, Power, GaN Power — bare-die & packaged), and no
non-amplifier category does, so groups are selected by that substring (~375
products). This is robust to the taxonomy quirk where "Low Noise Amplifier with
Limiter" (id 99) sits outside the Amplifiers subtree yet is a genuine amplifier.

> Filtering by the product **Type** field instead yields only 355 (it misses the
> 16 `Type="LNA+Limiter"` and ~14 empty-Type parts), so **category-name filtering
> is preferred** for recall.

### Field access (by name)

Each product carries `field_values:[{field_name, value}]`; columns differ per
category, so mapping is by **field name** (REQ-3.4), never by position.

---

## 5. Field Mapping

| Field name (as published) | Canonical param | Source unit | Notes |
|---------------------------|-----------------|-------------|-------|
| `Freq Low (GHz)` + `Freq High (GHz)` | `freq_range` | GHz | combined; `"DC"` → 0.0 |
| **`Gain (dB)` (exact label only)** | `Gain` | dB | **`Small Signal Gain` / `Power Gain` are NOT treated as Gain** → GaN PAs get Gain UNKNOWN |
| `NF (dB)` | `NF` | dB | |
| `P1dB (dBm)` | `P1dB` | dBm | |
| `Psat (dBm)` | `Psat` | dBm | |
| `Voltage (V)` / `Vd (V)` | `VDD` | V | both map to VDD |
| IP3 / OIP3 | — | — | **not published by rwmmic → UNKNOWN** |
| Type, Package, Current, PAE, Id, Power Gain, Datasheet | — | — | skipped |

- **Gain is matched by its exact on-site label `"Gain (dB)"`** (project decision):
  "Small Signal Gain (dB)" and "Power Gain (dB)" are distinct measurements and are
  deliberately excluded.
- Frequencies are GHz; the Verifier normalises.

---

## 6. Coupled Operating Points (key design point)

Some parts (~42: 30 with 2 points, 12 with 3) are characterised at several
**coupled bias points**, published as `/`-separated per-point values that align
by position across fields — e.g. RW3010 `Gain "24/23.5"`, `P1dB "27/29"`,
`Voltage "5/6"` (24 dB gain is the Vd=5 V point; 23.5 dB is the Vd=6 V point).

**The adapter emits one `Candidate` per operating point** (model labelled
`"PN (op i/N)"`) so each point stays self-consistent — the Verifier never mixes a
Gain from one bias with a Psat from another (Gain 24 with P1dB 29 is not a real
operating point). **Single-valued fields** (e.g. the frequency band, a lone NF)
are **shared** across every point.

- **N** = the common count of the multi-valued fields. Live data has **zero**
  count-mismatches; if fields ever disagree, fall back to a single row with the
  multi-valued fields dropped to UNKNOWN (safe, never a mixed point).
- Labelling is by index `op i/N` (not voltage), since Voltage may repeat
  (e.g. `5/5/8`).

---

## 7. Candidate Construction (Pseudocode)

```python
_GAIN_FIELD = "Gain (dB)"                    # exact label; not Small/Power Gain
FIELD_MAP = {"freq low ghz":("freq_low","GHz"), "freq high ghz":("freq_high","GHz"),
             "nf db":("NF","dB"), "p1db dbm":("P1dB","dBm"), "psat dbm":("Psat","dBm"),
             "voltage v":("VDD","V"), "vd v":("VDD","V")}

def _parse_float(t):
    t = t.strip()
    if not t or t in {"-","n/a","N/A"}: return None
    if t.upper() == "DC": return 0.0        # DC-coupled low edge
    return _try_float(t)

def _split(v): return [p.strip() for p in v.split("/") if p.strip()]

for group in data:
    if "amplifier" not in group.category.name.lower(): continue
    for p in group.products:
        values      = {normalize(fv.field_name): fv.value for fv in p.field_values}
        values_exact= {fv.field_name: fv.value for fv in p.field_values}   # for Gain
        lists = collect_split_lists(values, values_exact[_GAIN_FIELD])      # per field
        N = common_count(lists)   # 1, or the agreed multi-count; mismatch -> 1 + drop multis
        for i in range(N):
            raw = build_point(lists, i, N)          # single values shared; i-th of N otherwise
            model = pn if N == 1 else f"{pn} (op {i+1}/{N})"
            yield Candidate(model, "RWM", datasheet_url, raw, "table")
```

---

## 8. Test Plan

**Fixture** (`tests/fixtures/rwmmic_products.json`): a trimmed live slice — an LNA
group (`Gain (dB)`, `Voltage (V)`), a GaN-PA group (`Small Signal Gain`, `Vd`,
`Psat`), and a **PIN-Switch group** (to prove non-amplifier filtering).

**Offline tests** (`tests/adapters/test_rwmmic.py`) call `_parse_json` directly:
- `test_only_amplifier_categories_returned` — switch group excluded.
- `test_lna_scalar_and_freq_mapping`; `test_ip3_absent…`.
- `test_gain_matched_by_exact_label_only` — `Gain (dB)` sets Gain; Small/Power Gain do not.
- `test_pa_gain_unknown…` — GaN PA has no exact Gain → UNKNOWN.
- `test_two_operating_points_are_coupled` (RW3010, 2 pts, no cross-mixing).
- `test_three_operating_points_with_shared_singles` (RWDA1013: DC→0.0 & NF shared).
- `test_lone_multi_value_field_expands_to_points`; `test_mismatched_value_counts_fall_back_safely`.
- `test_bad_json…` / `test_missing_data_array…` → `AdapterError`.
- `@pytest.mark.network test_search_live` — >300 candidates, all RWM.

---

## 9. Rate Limiting Strategy

- **One GET per search** (`api/all-products` returns everything). No pagination,
  no per-product fetches.
- **Minimum inter-request delay:** 1.0 s (`_MIN_DELAY_SECONDS`).
- **User-Agent:** browser-style, with `Accept: application/json` and a `Referer`
  of `product.html`.
- **TLS:** `verify=False` for this host (self-signed cert in chain) — documented.
- **Cache (T10):** wires in once implemented.

---

## 10. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | API shape/field names change (undocumented API) | Medium | Map by field name; verify live; tests over fixture |
| R2 | `verify=False` weakens TLS trust | Medium | Isolated to this host + documented; flip to True where cert is trusted; consider pinning later |
| R3 | New multi-value count patterns / mismatched counts | Low | Fall back to single row, drop multi fields to UNKNOWN (tested) |
| R4 | A non-amplifier category name gains "Amplifier" | Low | Verify live; current catalogue is clean |
| R5 | Datasheet URL is a PDF, not an HTML page | Resolved | It is the only per-part link; display-only, never fetched |
| R6 | IP3/OIP3 never available → parts can't fully match an IP3 query | Resolved | Honest UNKNOWN → `partial`; source limitation |

### Open questions
- **OQ-1:** Include id 99 "Low Noise Amplifier with Limiter" (outside the
  Amplifiers subtree)? **Decision: yes** — genuine amplifiers, better recall (375).
- **OQ-2:** Manufacturer label — used **"RWM"** (domain rwmmic, PN prefix RW; no
  full brand name on the About page). Rename if an official name is confirmed.

---

## Summary

- **Fetch:** one `httpx.get` to the JSON API `index.php?r=api/all-products`
  (`verify=False`); no scraping, no JS, no per-product fetches.
- **Select:** amplifier category groups by name (~375 products).
- **Map:** by field name; Gain only from exact `"Gain (dB)"`; IP3 not published.
- **Operating points:** coupled `/`-values expanded into one Candidate per point
  (`PN (op i/N)`); single values shared — never mixes conditions.
- **robots.txt:** everything allowed.
- **Files:** `rf_finder/adapters/rwmmic.py`, `tests/adapters/test_rwmmic.py`,
  `tests/fixtures/rwmmic_products.json`, plus the `__main__.py` registration import.

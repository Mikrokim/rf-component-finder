---
name: rwmmic
description: >-
  Complete retrieval guide for rwmmic.com (RWM). Use whenever you work on the RWM
  adapter (rf_finder/adapters/rwmmic.py) — to understand how the site serves
  product data, to debug or maintain the amplifier adapter, or (the main
  forward-looking use) to ADD A NEW COMPONENT TYPE beyond amplifiers. Covers the
  single JSON-API retrieval method (api/all-products, self-signed-cert
  verify=False), the amplifier-category selection, field-name mapping, the exact
  "Gain (dB)" rule, the coupled-operating-point expansion (one product → one
  Candidate per bias point), the spec→ontology mapping, what was already built,
  and a step-by-step expansion recipe.
---

# RWM (rwmmic.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF product data from
rwmmic.com**. It records how the site behaves, how the existing **amplifier**
adapter was built, and how to extend it. If you are touching
`rf_finder/adapters/rwmmic.py`, read this first.

> Reference implementation: [rwmmic.py](../../../rf_finder/adapters/rwmmic.py)
> Original investigation: [rwmmic/plan.md](../../../specs/rf-component-finder/iteration2/rwmmic/plan.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Other JSON-source sites: [macom skill](../macom/SKILL.md) (JSON in a `data-part` attribute) · [analog-devices]/microchip-style parametric JSON

---

## 1. TL;DR — the one thing to remember

RWM has a **real JSON product API**. The visible `/product.html` is an almost-empty
shell that loads its data client-side via axios from
`index.php?r=api/all-products` — so the adapter **skips the HTML entirely and GETs
that JSON endpoint once**, receiving the ENTIRE catalogue (every category, its
field definitions, all products with spec values) in one response. Select the
amplifier category groups, map each product's `field_values` **by field name**,
and emit `Candidate`s. **Two RWM-specific rules:** (a) TLS verification must be
**off** (`verify=False`) because the host serves a self-signed cert in its chain;
(b) a product measured at several bias points expands into **one `Candidate` per
operating point**. The Verifier applies all constraints.

---

## 2. How rwmmic.com serves product data (investigation findings)

REQ-3.3 decision rule (*official API → parametric URL → scrape*):

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | **Yes (effectively)** — the site's own JS calls `index.php?r=api/all-products` (and `api/category-menu`). It returns the whole catalogue as JSON. | Use the JSON API (REQ-3.3 option 1) — **do not scrape HTML**. |
| **Server-side spec filter?** | **No** — the API always returns the full catalogue. | Select amplifier groups; filter locally in the Verifier. |
| **Is the data in the raw HTML?** | **No** — `/product.html` is a shell; the table renders client-side from the API. | Call the API directly; no HTML parse, no JS render. |
| **JS required?** | **No** — the JSON endpoint is directly fetchable. | `httpx` (JSON) suffices; no Playwright. |
| **Entry URL** | `https://www.rwmmic.com/index.php?r=api/all-products` | Single GET. |
| **TLS** | Host serves a **self-signed certificate in its chain** — strict verification fails (verified live). | `verify=False` for this host **only** (a control fetch of another vendor verifies fine). |
| **Shape** | `{"data": [ {category:{name}, products:[ {name, field_values:[{field_name, value}]} ]} ]}`. | Iterate groups → products → `field_values`. |

---

## 3. Compliance & access

- **robots.txt:** `Disallow:` is empty — everything allowed.
- **TLS:** `_VERIFY_TLS = False` (self-signed cert in chain). Flip to `True` on a
  network that trusts the site's certificate.
- **User-Agent:** browser-style UA (plain bot UAs may be rejected), plus a
  `Referer: …/product.html` and a JSON `Accept`.
- **Inter-request delay:** `_MIN_DELAY_SECONDS = 1.0` (one request per search).
- RWM has **no per-part product page** — only a datasheet PDF per part and the
  single shared `/product.html` catalogue table. So `Candidate.url` is a
  **Scroll-to-Text-Fragment deep link** into that catalogue page
  (`…/product.html#:~:text=<PN>`) that highlights the exact part on the shared
  page — **not** the datasheet PDF. Display only, and **never fetched**.

---

## 4. The retrieval recipe (what `search()` does)

```python
_BASE_URL = "https://www.rwmmic.com/"
_ALL_PRODUCTS_URL = _BASE_URL + "index.php?r=api/all-products"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_MIN_DELAY_SECONDS = 1.0
_VERIFY_TLS = False                 # self-signed cert in chain
_AMPLIFIER_KEYWORD = "amplifier"    # category-name substring
_GAIN_FIELD = "Gain (dB)"           # exact label for canonical Gain
```

1. **Rate-limit guard**, then **one GET** to `_ALL_PRODUCTS_URL` with the browser
   UA, `Accept: application/json,…`, `Referer: …/product.html`,
   `follow_redirects=True`, `timeout=30.0`, **`verify=_VERIFY_TLS`**.
2. `raise_for_status()`; on `httpx.HTTPError` raise
   `AdapterError(manufacturer, context, cause)`.
3. Hand `response.text` to `_parse_json()`.

---

## 5. The parsing recipe (what `_parse_json()` / `_product_to_candidates()` do)

1. `json.loads(text)`; **if the body is not valid JSON, or has no `data` list →
   raise `AdapterError`.** This is the fail-loudly tripwire (redesign / blocked
   response).
2. **Select amplifier groups:** keep only groups whose `category.name` contains
   `"amplifier"` (case-insensitive) — this is robust to the category-tree quirk
   where "Low Noise Amplifiers with Limiter" sits directly under "Amplifiers".
3. **Per product** (`_product_to_candidates`): collect `field_values` into two
   dicts — by **normalized** field name (`_normalize_field`) and by **exact**
   label (for the Gain rule). Model = product `name`, else the `pn` field; skip if
   empty. URL = a Scroll-to-Text-Fragment deep link into the shared
   `/product.html` catalogue page (`#:~:text=<PN>`, `-`→`%2D`) that highlights this
   exact part (`_highlight_url`) — RWM has no per-part page, so this is **not** the
   `datasheet` field.
4. **Operating-point expansion** (see §7 R1) — split `/`-separated values, compute
   N, and emit one `Candidate(source="table")` per point.

---

## 6. Field → canonical ontology mapping (REQ-3.4)

Name-based, keyed by normalized `field_name`:

```python
FIELD_MAP = {                        # normalized field name -> (canonical, unit|None)
    "pn":            ("model",     None),
    "freq low ghz":  ("freq_low",  "GHz"),
    "freq high ghz": ("freq_high", "GHz"),
    "nf db":         ("NF",        "dB"),
    "p1db dbm":      ("P1dB",      "dBm"),
    "psat dbm":      ("Psat",      "dBm"),
    "voltage v":     ("VDD",       "V"),   # LNAs
    "vd v":          ("VDD",       "V"),   # GaN PAs
}
```

Rules that matter:

- **Gain is special — exact label only.** Canonical `Gain` is taken **only** from
  the field whose exact on-site label is `"Gain (dB)"`. `"Small Signal Gain (dB)"`
  and `"Power Gain (dB)"` are **distinct measurements** and are deliberately NOT
  treated as Gain — so GaN PAs (no plain "Gain (dB)" column) get Gain UNKNOWN.
- **Frequency:** combine `freq low ghz` + `freq high ghz` into
  `RawValue((lo, hi), "GHz")`; a DC-coupled low edge (`"DC"`) → `0.0`.
- **Both supply labels** (`Voltage (V)`, `Vd (V)`) map to canonical **VDD**.
- **IP3/OIP3 is not published by rwmmic** → always UNKNOWN.
- Dual per-band values that are not a single float (e.g. `"27/25"`, `"+5/-5"` when
  not an operating-point split) → `_parse_float` returns `None` → param absent.

### Architecture fit

- **No query-side filtering** — return every amplifier row; the **Verifier**
  applies all constraints (REQ-4.1).
- **Self-registers** via `@register`. `manufacturer = "RWM"`,
  `supported_components = {"amplifier"}`.

---

## 7. Gotchas & risks

| # | Risk | Mitigation (already applied) |
|---|---|---|
| R1 | **Coupled operating points** — a product measured at several bias points publishes `/`-separated per-point values aligned by position (e.g. Gain `"24/23.5"`, Voltage `"5/6"`). Mapping them as single values would mix a Gain from one bias with a Psat from another. | Emit **one `Candidate` per operating point** (`model` → `"PN (op i/N)"`), each point self-consistent; single-valued fields (e.g. freq band) shared across points. See `_pick`. |
| R2 | **Mismatched multi-value counts** across fields. | Fall back to a **single** candidate with the multi-valued fields **absent** (never a mixed point). |
| R3 | **Self-signed TLS cert** in the chain → verification fails. | `verify=False` for this host only. |
| R4 | **Gain synonyms** — "Small Signal Gain", "Power Gain". | Canonical Gain **only** from the exact `"Gain (dB)"` label. |
| R5 | **IP3 not published.** | Always UNKNOWN (never a false value). |
| R6 | **Category-tree quirk** — limiter LNAs sit directly under "Amplifiers". | Select by the `"amplifier"` substring in the category name (catches all). |
| R7 | **"DC" low band edge.** | Parse `"DC"` → `0.0` so DC-coupled parts keep a usable `freq_range`. |

---

## 8. Open questions (status at time of writing)

Tracked in [open-questions.md](../../../openspec/open-questions.md):

- **OQ-1 — full manufacturer list.** RWM is an implemented amplifier adapter; the
  full target list is undetermined.
- **OQ-3 — warn on row-count drift.** Not implemented (no run-to-run comparison of
  the catalogue size / candidate count).

---

## 9. EXPANSION GUIDE — adding a new component type to RWM

The fetch is **already the whole catalogue** — one API call returns every category.
The per-category work is the group-selection keyword, the field map, and the
ontology.

1. **Register the component type** in
   [components.py](../../../rf_finder/ontology/components.py) with its canonical
   params/units.
2. **Identify the category names** for the new type in the API response (decode
   `data[].category.name`). Choose a robust selection substring (as `"amplifier"`
   is for amps) rather than an exact match.
3. **Confirm the same source.** The API returns all categories in one call, so
   **no new fetch pattern is needed** — just a different group filter. Verify the
   new type's products carry `field_values` with the specs you need.
4. **Aggregate the new category's `field_name`s** and coverage; build a
   category-specific field map (normalized name → `(canonical, unit)`), and decide
   the Gain-label rule if the new type also has multiple gain measurements.
5. **Parameterize, don't fork.** Key the selection keyword + field map by
   `spec.component_type`; select by it in `_parse_json`; add the type to
   `supported_components`. Keep the operating-point expansion, `verify=False`, and
   the "DC"→0.0 rule.
6. **Test offline** against `_parse_json()` with a trimmed
   [rwmmic_products.json](../../../tests/fixtures/rwmmic_products.json) fixture.
   Cover: amplifier-only selection, the exact-`Gain (dB)` rule, a coupled
   operating-point product (→ N candidates), a mismatched-count product (→ 1
   candidate), a `"DC"` low edge, and a bad-payload → `AdapterError`.
7. **Update this skill** with the new category keyword, field map, and quirks.

---

## 10. File map

| File | Role |
|---|---|
| [rf_finder/adapters/rwmmic.py](../../../rf_finder/adapters/rwmmic.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`, verdict models. |
| [rf_finder/ontology/components.py](../../../rf_finder/ontology/components.py) | Component-type registry (add new types here). |
| [tests/adapters/test_rwmmic.py](../../../tests/adapters/test_rwmmic.py) | Offline unit tests. |
| [tests/fixtures/rwmmic_products.json](../../../tests/fixtures/rwmmic_products.json) | Trimmed JSON-API fixture. |
| [specs/.../iteration2/rwmmic/plan.md](../../../specs/rf-component-finder/iteration2/rwmmic/plan.md) | Original investigation & plan. |

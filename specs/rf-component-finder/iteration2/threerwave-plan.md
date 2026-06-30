# 3rWave Adapter — Investigation & Plan

> **Task:** 3rWave (3rwave.com) amplifier adapter — counterpart to the MACOM,
> Mini-Circuits, Analog Devices and UMS adapters.
> **Phase:** Plan only. **No code written yet.**
> **Date:** 2026-06-29
> **Investigator:** Phase A planning (live inspection of 3rwave.com + DevTools
> capture of the `/amplifier/` TablePress markup).
> **Methodology:** Spec-Driven Development (SDD) — same flow that produced
> [macom-plan.md](macom-plan.md) and [ums-plan.md](ums-plan.md).
> **Decision rule applied:** REQ-3.3 — *prefer an official API; else a parametric
> URL search; else scrape the results table.*

---

## 0. Executive summary

| | Finding |
|---|---|
| **Official API?** | **Not used.** Site is WordPress; a WP REST API may exist but the spec data is rendered by the **TablePress** plugin (not a queryable product post type). To verify, but **not** the chosen method. |
| **Parametric URL query?** | **No.** The page uses **DataTables.js** for client-side paging/search/sort only; there is no server-side parametric URL filter. |
| **HTML scraping?** | **Yes — chosen method.** The full PA and LNA tables are **server-side rendered as real `<td>` cells** in the initial HTML. Plain `httpx` + `selectolax`; **no JavaScript, no Playwright.** |
| **Chosen method** | **One `httpx` GET** to `https://3rwave.com/amplifier/` → parse **every `table.tablepress`** on the page (PA + LNA tabs) → map columns by normalized header text → return every row as a `Candidate`. |
| **Fetch cost** | **1 GET** covers all amplifiers (PA ≈ 44 rows, LNA ≈ 10 rows; counts to confirm live). No pagination GETs, no per-product fetches. |
| **Architecture fit** | Identical to Mini-Circuits / UMS: fetch all rows, map columns, return every `Candidate`; the **Verifier** applies all constraints (REQ-4.1). Self-registers via `@register`; no core change (NFR-3). |

**The key insights:**

1. **This is the server-rendered-table family** (like
   [minicircuits](../../../.claude/skills/minicircuits/SKILL.md) and
   [ums](../../../.claude/skills/ums/SKILL.md)) — **not** the embedded-JSON family
   (macom / analogdevices). The data is in plain `<td class="column-N">` cells.
2. **PA and LNA are two amplifier sub-types on one page** (tabbed UI = CSS
   show/hide of two TablePress tables — *to confirm both ship in one GET*). Both
   map to component type `amplifier`. This is the UMS multi-sub-type shape: return
   all rows from both tables, let the Verifier filter.
3. **DataTables.js is cosmetic.** It adds paging ("rows per page"), search, and
   sort *on top of* the already-complete server-rendered rows. No data is fetched
   by JS. Read the raw HTML.
4. **Frequency is already in GHz** (Start Freq. / Stop Freq.) — like UMS, **no MHz
   conversion** (unlike Mini-Circuits / Analog Devices).

---

## 1. Request Mechanism Finding (resolves REQ-3.3 for 3rWave)

### Method used
Live `WebFetch` of `https://3rwave.com/amplifier/` and `/robots.txt`, plus
DevTools capture of the rendered table DOM.

### Findings

| Question | Answer |
|----------|--------|
| Platform | **WordPress** + **TablePress** plugin, enhanced by **DataTables.js**. |
| Entry URL (specs) | `https://3rwave.com/amplifier/` |
| Method for load | **HTTP GET**, no query parameters. Server-side rendered tables. |
| Official/public API? | Not used for specs (TablePress data is HTML, not a REST product type). To verify; not the chosen path. |
| Server-side filter? | **No.** DataTables filters/pages/sorts **client-side** only. |
| Is data in raw HTML? | **Yes** — real `<td class="column-1..12">` cells inside `table.tablepress`. Confirmed via DevTools: `table#tablepress-29.tablepress.tablepress-id-29.dataTable`. |
| JS required to see data? | **No.** `httpx` + `selectolax` suffice. |
| Tabs | **PA** (Power Amplifier) and **LNA** (Low Noise Amplifier) — both amplifiers. |

---

## 2. Compliance & access (robots.txt)

`https://3rwave.com/robots.txt` (fetched live):

```
User-agent: *
Disallow:

Sitemap: https://3rwave.com/sitemap_index.xml
```

Conclusions that govern the adapter:

- **Nothing is disallowed** — `/amplifier/` is fully crawlable.
- **No `Crawl-delay`.** Adapter still self-imposes a modest polite delay
  (`_MIN_DELAY_SECONDS = 1.0`, as Mini-Circuits — it's a single light page),
  enforced by a `time.sleep()` guard before a live fetch; paid only on cache miss.
- Send a **browser-style User-Agent** (reuse the shared UA the other adapters use)
  in case the host rejects plain bot UAs.
- A sitemap exists (`sitemap_index.xml`) — a possible enumeration cross-check, not
  needed for the chosen method.

---

## 3. The retrieval recipe (what `search()` will do)

```python
_BASE_URL      = "https://3rwave.com"
_AMPLIFIER_URL = _BASE_URL + "/amplifier/"
_USER_AGENT    = "<shared browser UA>"
_MIN_DELAY_SECONDS = 1.0
```

1. **Rate-limit guard** before a live fetch (sleep the remainder of 1 s if needed).
2. **One GET** to `_AMPLIFIER_URL`, `follow_redirects=True`, `timeout=30.0`,
   headers: browser `User-Agent`, `Accept: text/html,…`, `Accept-Language`.
3. `raise_for_status()`, stamp `_last_fetch_time`.
4. On any `httpx.HTTPError`, raise **`AdapterError(manufacturer, context, cause)`**
   — never let a raw transport error escape.
5. Hand `response.text` to `_parse_html()`.

---

## 4. The parsing recipe (what `_parse_html()` will do)

Uses `selectolax.parser.HTMLParser`. Exposed for offline tests.

1. **Locate the tables.** Select **all `table.tablepress`** on the page (PA + LNA).
   Do **not** hard-code `tablepress-29` — TablePress ids are brittle and change on
   rebuild. **If none found → raise `AdapterError`** ("no tablepress table found")
   — the site-redesign tripwire; fail loudly, never return empty.
2. **Per table, find the header row** by detecting the `<tr>` whose cells contain
   `"Part Number"` (same trick as Mini-Circuits' "Model Number"). Fallback: all
   `<th>` in the table.
3. **Build a normalized-header → column-index map** (`_normalize_header`:
   lowercase, strip punctuation, collapse whitespace). Name-based, robust to
   reorder. TablePress's `<td class="column-N">` gives a positional fallback if a
   header is unreadable.
4. **Iterate `<tbody> <tr>`**, read each cell, build a `Candidate(source="table")`
   per row; skip rows with no Part Number. PA and LNA share the same header set
   (the only difference is current in A vs mA — a column we skip), so one column
   map serves both tables.

---

## 5. Column → canonical ontology mapping (REQ-3.4)

Name-based, keyed on normalized header text. PA and LNA columns are identical
except the current unit.

| 3rWave column | Canonical param | Unit | Notes |
|---|---|---|---|
| Part Number | `model` | — | model name; row skipped if empty |
| Start Freq.(GHz) + Stop Freq.(GHz) | `freq_range` | GHz | combine into `(lo, hi)`; **already GHz** |
| Gain(dB) | `Gain` | dB | |
| Psat(dBm) | `Psat` | dBm | + **efficiency fallback**, see §6 (OQ-3W-3) |
| NF(dB) | `NF` | dB | |
| Drain Voltage(V) | `VDD` | V | site gives a **scalar**; `VDD` comparison is `between` — confirm Verifier handles scalar-vs-range (OQ-3W-4) |
| Size | `Size` | mm | **free text** — parse rule UNDECIDED, see §6 / OQ-3W-1 |
| Consumption Current (A/mA) @ Psat | — | — | no ontology param → skipped (used only for §6 Psat fallback) |
| Efficiency (%) @ Psat | — | — | no ontology param → skipped (used only for §6 Psat fallback) |
| Input/Output Connector Type | — | — | skipped |
| Description | — | — | skipped |

### Architecture fit
- **No query-side filtering** — return every row; the Verifier applies all
  constraints (REQ-4.1).
- **Self-registers** via `@register`. `manufacturer = "3rWave"` (OQ-3W-2),
  `supported_components = {"amplifier"}`, `source = "table"`.

---

## 6. Missing / derived parameters

### Not present as table columns → resolve to UNKNOWN (partial, never FAIL)
These must be sourced from the **per-part datasheet later** (deferred):

| Param | Why not available | Calculable? |
|---|---|---|
| **P1dB** | no column | Only via rule-of-thumb `P1dB ≈ Psat − 2…4 dB` → **no, don't fabricate** |
| **IP3** | no column | Only via chained rule-of-thumb `OIP3 ≈ OP1dB + ~10 dB` → **no** |
| **MSL** | no column | not derivable → datasheet-only |
| **Temperature** | no column | not derivable → datasheet-only |

> **TODO (future iteration):** harvest P1dB / IP3 / MSL / Temperature (and any
> Size dimensions missing from the table) from the per-part **datasheet PDFs**.
> This is the `datasheet`-confidence path, deferred for now.

### Psat efficiency fallback (proposed — OQ-3W-3)
The PA/LNA tables carry **Drain Voltage (V)**, **Consumption Current (A/mA)** and
**Efficiency (%) @ Psat**, which are physically related to output power by drain
efficiency: `Pout = η × Vdrain × Idrain`. Therefore:

- If a row is **missing Psat** but has efficiency + Vd + Id → **compute**
  `Psat = (η/100) × Vd × Id`, convert W→dBm, and tag it as **derived**.
- Where Psat **is** listed → the same formula is a free **sanity cross-check**.

Caveat: "Efficiency @ Psat" is usually **drain efficiency** (Pout/Pdc); if it is
actually **PAE** ((Pout−Pin)/Pdc) the derived Psat runs slightly low. So the
fallback should fire **only when Psat is genuinely absent**. *Decision pending.*

### Size (IN scope, decoding UNDECIDED — OQ-3W-1)
Size **must be included** (user requirement). The candidate-side column is free
text in mixed forms that conflate two concepts:
- **True dimensions:** `25.4 x 25.4 x 5mm`
- **Form factor / package:** `19" Rack Mount`, `SMT`, `Die`

**Open decision — how the user's Size *input* is received and matched** (the user
cannot yet decide; this MUST be resolved before implementing Size):

| Option | User input | Match semantics | Cost |
|---|---|---|---|
| A. Max dimension (mm) | one number X | candidate's largest L/W/H ≤ X; descriptive-only → UNKNOWN | fits current model unchanged |
| B. Bounding box L×W×H | three dims | sorted candidate dims each ≤ sorted user dims (rotation-aware) | needs `ParamConstraint`/form/Verifier changes |
| C. Footprint area (mm²) | one number | candidate L×W ≤ X | single scalar; ignores height |
| D. Dimension + form-factor filter | number + category | max-dim (as A) **plus** categorical SMT/Die/Connectorized/Rack | adds a categorical param outside the ontology |

Until this is decided, **Size parsing is not implemented**; the candidate-side
reduction (which scalar we extract: max dimension vs area vs volume) is coupled to
this choice and is therefore also pending.

---

## 7. Open questions (all currently UNANSWERED)

- **OQ-3W-1 — Size input decoding (BLOCKER for Size).** How is the user's Size
  constraint received and matched against the free-text Size column (§6, options
  A–D)? The user cannot decide yet. Candidate-side reduction depends on this.
  **No recommendation locked; must be decided before Size is built.**
- **OQ-3W-2 — `manufacturer` string & file/class name.** Module names can't start
  with a digit, so `3rwave.py` is impossible. *Proposed:* `manufacturer = "3rWave"`,
  file `threerwave.py`, class `ThreeRWaveAdapter`. Needs sign-off.
- **OQ-3W-3 — Psat efficiency fallback.** Include the `Pout = η·Vd·Id` derivation
  for blank-Psat rows (and as a cross-check)? Resolve the drain-efficiency-vs-PAE
  ambiguity and the W→dBm conversion. *Proposed:* include, fire only when Psat
  absent, tag as derived. Needs sign-off.
- **OQ-3W-4 — `VDD` scalar vs `between`.** The site gives a single Drain Voltage;
  ontology `VDD` comparison is `between` (expects a range). Confirm how the
  Verifier treats a scalar `found` against a `between` constraint (and whether the
  PA/LNA "Drain Voltage" is even the right source for the supply-range concept).
- **OQ-3W-5 — Both tables in one GET?** Confirm the PA **and** LNA TablePress
  tables both ship in the single `/amplifier/` HTML (vs. lazy-loaded per tab).
  Capture the LNA table's structure/id and row counts live.
- **OQ-3W-6 — `Candidate.url` value.** Is there a per-part link or datasheet
  anchor in the Part Number cell? If not, fall back to the `/amplifier/` page URL
  (display only, never fetched).
- **OQ-3W-7 — PA vs LNA sub-type.** Ignore the sub-type (Verifier doesn't need it)
  or capture it for reporting? *Leaning:* ignore for now.
- **OQ-3W-8 — Row-count drift warning.** Log a warning if scraped row count
  deviates > 20 % from a cached baseline (possible redesign)? *Leaning:* yes.
- **OQ-3W-9 — Official API / sitemap cross-check.** Confirm whether a usable WP
  REST endpoint or the sitemap offers a cleaner index (not expected to carry
  specs; TablePress data is HTML).

> These OQ-3W items are **not yet copied** into the project register
> [open-questions.md](../open-questions.md) — reconcile when the register is next
> updated (see [[remind-delete-source-open-questions]]).

---

## 8. Implementation steps (once OQs are answered)

1. **Register naming** (resolve OQ-3W-2): create `rf_finder/adapters/threerwave.py`,
   class `ThreeRWaveAdapter`, `@register`, `manufacturer = "3rWave"`,
   `supported_components = {"amplifier"}`.
2. **Add the explicit import** to [__main__.py](../../../rf_finder/__main__.py)
   alongside the other adapters (triggers `@register`).
3. **Implement `search()`** per §3 (single GET, rate guard, browser UA,
   `AdapterError` on HTTP failure).
4. **Implement `_parse_html()`** per §4–§5 (all `table.tablepress`, name-based
   header map, GHz freq combine, missing-sentinel handling).
5. **Psat efficiency fallback** per §6 — *only if OQ-3W-3 approved.*
6. **Size** per §6 — *only after OQ-3W-1 is decided* (candidate-side reduction +
   the form/Verifier side of the chosen option).
7. **Tests (offline).** Trimmed HTML fixtures under `tests/fixtures/`:
   `threerwave_pa.html`, `threerwave_lna.html`, a missing-cell row, and the
   no-`tablepress`-table → `AdapterError` case. Assert against `_parse_html()`
   directly. Mark live integration tests `@pytest.mark.network`.
8. **Skill.** Run `adapter-skill-writer` to produce
   `.claude/skills/threerwave/SKILL.md` matching the minicircuits/ums template.

---

## 9. File map (to be created)

| File | Role |
|---|---|
| `rf_finder/adapters/threerwave.py` | The adapter (to write). |
| `rf_finder/__main__.py` | Add the explicit import line. |
| `rf_finder/adapters/base.py` | `Adapter` ABC, `AdapterError`, `@register`. |
| `rf_finder/models.py` | `Candidate`, `RawValue`, `QuerySpec`. |
| `rf_finder/ontology/parameters.py` | Canonical params/units the map targets. |
| `tests/adapters/test_threerwave.py` | Offline unit tests (to write). |
| `tests/fixtures/threerwave_pa.html` / `_lna.html` | Trimmed fixtures (to write). |
| `.claude/skills/threerwave/SKILL.md` | Retrieval skill (to write, via adapter-skill-writer). |
</content>
</invoke>

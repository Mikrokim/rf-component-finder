# T8 Plan — VectraWave Adapter

> **Task:** T8 from tasks.md — `adapters/vectrawave.py` (fourth site adapter,
> after Mini-Circuits, Analog Devices, Guerrilla RF).
> **Phase:** Plan only (Phase A). No code written in this document.
> **Date:** 2026-06-30
> **Investigator:** Phase A planning agent
> **Resolves open items:** I-1 (request mechanism), I-2 (data fixture) for VectraWave.
> Manufacturer-specific requirements: [requirements.md](requirements.md).

---

## 1. Request Mechanism Finding (resolves I-1)

### Why VectraWave (and not Microchip)

Microchip was investigated first and **rejected**: every content URL on
`microchip.com` (parametric search, product pages, sitemap) returns **403
AkamaiGHost** even with full browser headers — an Akamai bot wall that `httpx`
cannot pass. VectraWave is fully accessible and was chosen instead.

### Findings (`/search-engine-mmic`)

| Question | Answer |
|----------|--------|
| URL | `https://vectrawave.com/search-engine-mmic` |
| Method | **HTTP GET** (browser-style UA) |
| Access | **Open** — no bot-wall (WordPress site) |
| Rendering | **Server-rendered.** Built with the Divi "Table Maker" plugin: tables are `<div>` structures (`dvmd_tm_trow`/`dvmd_tm_tcell`/`dvmd_tm_cdata`), present in the **raw HTML**. A JS lib only styles them — no JS needed for the data. `httpx` + `selectolax` suffice. |
| Layout | **Transposed** — products are **columns**, parameters are **rows** (first cell = parameter label). Product-header rows (part numbers) repeat between parameter rows. |
| Size | ~64 products across 7 section tables |

### Conclusion

`httpx.get` the page once, parse each amplifier-section table (transposed), and
return `Candidate` objects. The Verifier applies constraints.

> **Network note:** vectrawave.com was intermittently flaky during investigation
> (transient TLS/connect errors). The `AdapterError`-on-failure path (REQ-3.6) and
> the T10 cache cover this; a single retry on connect/TLS error is recommended.

---

## 2. robots.txt Summary

URL: `https://vectrawave.com/robots.txt`

```
User-agent: *
Disallow: /wp-content/uploads/wc-logs/
Disallow: /wp-content/uploads/woocommerce_*
Disallow: /*?add-to-cart=
Disallow: /wp-admin/
Allow:    /wp-admin/admin-ajax.php
# (Yoast block + sitemaps)
```

**Key conclusion:** `/search-engine-mmic` is **not** disallowed — scraping it is
compliant (NFR-6). The disallows target WooCommerce cart/admin paths only.

---

## 3. File Plan

| File | Action | Purpose |
|------|--------|---------|
| `rf_finder/adapters/vectrawave.py` | **Create** | The VectraWave adapter (main deliverable) |
| `tests/adapters/test_vectrawave.py` | **Create** | Offline unit tests using the HTML fixture |
| `tests/fixtures/vectrawave_mmic.html` | **Create** | Trimmed snapshot: one amplifier section + one non-amplifier section (I-2) |

Reuses the shared `drop_paramless` helper in `base.py`. No bandwidth case here.

---

## 4. HTML Structure (transposed Divi tables)

The page has 7 section tables, each preceded by a heading (`<h2>`/`<h3>`):
`HIGH POWER AMPLIFIERS > 3W`, `MEDIUM POWER AMPLIFIERS < 3W`,
`LOW NOISE AMPLIFIERS`, `WIDEBAND AMPLIFIERS`, `CORE CHIPS`, `ATTENUATOR`,
`PHASE SHIFTER`.

Each table (Divi Table Maker) is transposed:

```html
<div class="... dvmd_tm_trow ...">           <!-- product-header row -->
  <div class="dvmd_tm_tcell"><div class="dvmd_tm_cdata"></div></div>          <!-- empty label -->
  <div class="dvmd_tm_tcell"><div class="dvmd_tm_cdata">VM042D</div></div>    <!-- product 1 -->
  <div class="dvmd_tm_tcell"><div class="dvmd_tm_cdata">VM042F</div></div> ...
</div>
<div class="... dvmd_tm_trow ...">           <!-- a parameter row -->
  <div class="dvmd_tm_tcell"><div class="dvmd_tm_cdata">FrequencyMin GHZ</div></div>  <!-- label -->
  <div class="dvmd_tm_tcell"><div class="dvmd_tm_cdata">8.0</div></div>               <!-- product 1 value -->
  <div class="dvmd_tm_tcell"><div class="dvmd_tm_cdata">8.5</div></div> ...
</div>
<!-- 'Datasheet' row cells: <td>'s cdata holds <a href="/wp-content/uploads/...pdf">Download</a> -->
```

- **Products** = the non-empty cells of a product-header row (label cell empty),
  e.g. `VM042D`. The same header repeats between parameter rows — read once.
- **Parameter rows** = rows whose first cell is a non-empty label. Value for
  product *i* = cell *i* (aligned by column position).
- **Model + URL:** the product is the header cell text; the `Datasheet` row's
  cell *i* holds the `<a href>` (relative `/wp-content/uploads/…pdf`) → `Candidate.url`
  and the datasheet fallback's source.
- **Section grouping is the key parsing task:** rows belong to per-section tables
  (each a separate Divi module; cell class carries a table index, e.g.
  `dvmd_table_maker_item_6`). Group by that module, read the section name from the
  preceding heading.

---

## 5. Section + Parameter Mapping

### Section filter

**Keep (amplifiers):** `HIGH POWER AMPLIFIERS`, `MEDIUM POWER AMPLIFIERS`,
`LOW NOISE AMPLIFIERS`, `WIDEBAND AMPLIFIERS` (prefix match, normalised).
**Drop (not amplifiers):** `ATTENUATOR`, `PHASE SHIFTER`.
**Deferred:** `CORE CHIPS` (T/R modules with split Tx/Rx specs — VW-OQ-2).

### Per-section parameter availability (verified live)

Different sections expose different columns — the adapter maps by **row label**,
so each part gets exactly what its section publishes:

| Section | freq | Gain | P1dB | Psat | NF | VDD |
|---------|:----:|:----:|:----:|:----:|:--:|:---:|
| HIGH POWER   | ✓ | ✓ | — | ✓ (`Pout`)  | — | ✓ |
| MEDIUM POWER | ✓ | ✓ | ✓ (`OP1dB`) | ✓ (`Psat`) | — | ✓ |
| LOW NOISE    | ✓ | ✓ | ✓ (`OP1dB`) | ✓ (`Psat`) | ✓ | ✓ |
| WIDEBAND     | ✓ | ✓ | ✓ (`OP1dB`) | ✓ (`Psat`) | ✓ | ✓ |

`—` = not published, because the spec is irrelevant to that product class:
**NF** (noise) and **IP3** (linearity) are not characterised for **power
amplifiers**; the **High Power** section tables only `Pout` (= saturated output
power → `Psat`) and no separate P1dB column.

### Row-label → ontology (normalised label match)

| Row label(s) | Canonical param | Unit | Stored as |
|--------------|-----------------|------|-----------|
| `FrequencyMin GHZ` + `FrequencyMax GHz` | `freq_range` | GHz | `RawValue((min,max),"GHz")` |
| `Gain dB` | `Gain` | dB | scalar |
| `OP1dB dBm` | `P1dB` | dBm | scalar |
| `Psat dBm` **and** `Pout dBm` | `Psat` | dBm | scalar |
| `NF dB` | `NF` | dB | scalar (LNA/Wideband only) |
| `Voltage V` **and** `DrainVoltage V` | `VDD` | V | single value → `RawValue((v,v),"V")` |
| everything else | — | — | skipped |

**`Pout` = Psat (verified across two parts).** For a power amplifier "Pout" is the
rated/saturated output power — the same quantity as `Psat`, under a different
section label (like `DrainVoltage`=VDD). Verified: VM088D `Pout = 46 dBm @Pin=23 dBm`
with linear gain 31 dB → 8 dB compression (deep saturation) → this is Psat, **not**
P1dB. (VM042D's `Pout`=40 happens to equal its datasheet P1dB=40, but its Psat=40.8
is nearly identical, so the small under-report is harmless and conservative.)
Mapping `Pout`→P1dB would grossly over-report P1dB for parts like VM088D
(false positives), so **`Pout`→`Psat`** is the safe, correct choice. The High Power
section therefore yields Psat (from `Pout`) but no P1dB from the table.

**VDD has two source labels.** Sections name the supply either `Voltage V` or
`DrainVoltage V` — both are the FET supply (VDD), so both map to `VDD`. The
**`ControlVoltage V`** label (Phase Shifter section) is a *control* voltage, **not**
supply — deliberately **not** mapped (and phase shifters are filtered out anyway).
VDD is a single value → stored as a degenerate `(v,v)` range (like Mini-Circuits;
the table `Voltage` is the clean nominal VDD — verified VM042D = +8.5 V).

### Parameters NOT taken from the table

| Param | Why | Where it comes from |
|-------|-----|---------------------|
| **Temperature** | No Temperature column anywhere on the page | datasheet (operating/storage) — fallback |
| **Size** | `Package mm x mm` is a package label (`Die 4.5 x…`, `SOIC-8`), not a clean dimension | datasheet (exact die dimensions) — fallback. **Not mapped from the table.** |
| **IP3** | **Not published anywhere** (table or datasheet; verified on a PA and an LNA) — linearity not characterised | N/A — always UNKNOWN |
| **MSL** | **Not published anywhere** — parts are bare die (no JEDEC MSL) | N/A — always UNKNOWN |

So the adapter yields **up to 6 table params** (freq, Gain, P1dB, Psat, NF, VDD),
section-dependent. The datasheet fallback (separately owned, run on surviving
candidates only) fills **only the gaps** that exist in the datasheet —
Temperature and Size always; Psat/NF for sections that lacked them. IP3 and MSL
are never available and stay UNKNOWN.

---

## 6. Candidate Construction (Pseudocode)

```python
PAGE_URL = "https://vectrawave.com/search-engine-mmic"
AMP_SECTIONS = ("high power amplifiers", "medium power amplifiers",
                "low noise amplifiers", "wideband amplifiers")   # normalised prefix

ROW_MAP = {            # normalised label -> (canonical, unit); freq/vdd handled specially
    "frequencymin ghz": ("freq_low",  "GHz"),
    "frequencymax ghz": ("freq_high", "GHz"),
    "gain db":          ("Gain",      "dB"),
    "op1db dbm":        ("P1dB",      "dBm"),
    "psat dbm":         ("Psat",      "dBm"),
    "pout dbm":         ("Psat",      "dBm"),   # Pout = rated/saturated output power == Psat
    "nf db":            ("NF",        "dB"),
    "voltage v":        ("VDD",       "V"),     # supply voltage
    "drainvoltage v":   ("VDD",       "V"),     # same supply, different section label
    # NOTE: "controlvoltage v" intentionally absent (phase-shifter control, not VDD)
}

def _num(s): ...        # "" / non-numeric -> None

# for each section table whose heading prefix is in AMP_SECTIONS:
#   products = cells[1:] of the product-header row (non-empty part numbers)
#   per column i: accumulate raw_params{} and url
#   for each parameter row (non-empty label):
#     key = normalise(label)
#       - frequencymin/max -> stash; combine into freq_range (GHz) when both present
#       - voltage v / drainvoltage v -> VDD = RawValue((v,v),"V")
#       - else ROW_MAP scalar -> RawValue(num, unit)
#     if key == "datasheet": url[i] = absolute(href in cell i)
#   emit Candidate(model=product, manufacturer="VectraWave", url=url[i], raw_params, source="table")
# search(): fetch -> parse amplifier sections -> drop_paramless(...)
```

### Example (HIGH POWER section — VM042D)

```python
Candidate(model="VM042D", manufacturer="VectraWave",
    url="https://vectrawave.com/wp-content/uploads/2025/02/VM042D-DS-Rev3.0-Ed1.1.pdf",
    raw_params={
        "freq_range": RawValue((8.0, 12.0), "GHz"),
        "Gain": RawValue(25.0, "dB"),
        "Psat": RawValue(40.0, "dBm"),       # from "Pout dBm" (== saturated output power)
        "VDD":  RawValue((8.5, 8.5), "V"),   # from "Voltage V"
    }, source="table")
    # P1dB NOT in this section's table -> datasheet fallback (where labelled);
    # NF / IP3 / MSL not characterised; Temperature / Size -> datasheet
```

---

## 7. Test Plan

### Fixture file

**Path:** `tests/fixtures/vectrawave_mmic.html` — a trimmed page with:
- A HIGH POWER section table (columns: freq min/max, Gain, `Pout`, `DrainVoltage`,
  Datasheet) — proves `Pout`→P1dB and `DrainVoltage`→VDD, and no Psat/NF.
- A LOW NOISE section table (columns incl. `OP1dB`, `Psat`, `NF`, `Voltage`) —
  proves `Voltage`→VDD, Psat + NF present.
- One **non-amplifier** section (`ATTENUATOR`) that must be filtered out.

### Assertions (offline, no network) — call an internal `_parse_html(html)`:

```python
def test_only_amplifier_sections_returned()    # attenuator/phase-shifter dropped
def test_transposed_products_parsed()
def test_freq_range_from_min_max_ghz()
def test_pout_maps_to_psat_not_p1db()           # "Pout 40" -> Psat, no P1dB key (High Power)
def test_psat_and_nf_in_lna_section()
def test_vdd_from_both_voltage_labels()         # Voltage V and DrainVoltage V -> VDD (v,v)
def test_control_voltage_not_mapped_to_vdd()
def test_no_ip3_no_msl_no_size_no_temp_from_table()
def test_url_is_datasheet_pdf()
def test_missing_tables_raises_adaptererror()
```

Plus helper tests for label normalisation and `_num`.

### Integration test (marked network, skipped in CI)

```python
@pytest.mark.network
def test_search_live():
    res = VectraWaveAdapter().search(QuerySpec("amplifier", []))
    assert res and all(c.manufacturer == "VectraWave" for c in res)
    assert all("IP3" not in c.raw_params and "MSL" not in c.raw_params for c in res)
```

---

## 8. Rate Limiting Strategy

- **One request per `search()` call** — the whole catalogue is on one page.
- **Minimum inter-request delay:** **2 seconds**
  (`config.yaml` → `rate_limits.vectrawave.delay_seconds`, default `2.0`).
- **Cache (T10):** serves the page after the first fetch.
- **User-Agent:** browser-style (consistent with the other adapters).
- **Single retry** on transient TLS/connect errors (see §1 note).

---

## 9. Risks and Open Questions

| # | Risk | Likelihood | Mitigation |
|---|------|-----------|------------|
| R1 | Transposed parsing / section grouping wrong | Medium | Group rows per Divi table module; read products from the header row; map params by label. Fixture tests cover both a power and an LNA section. |
| R2 | Divi class names change (`dvmd_tm_*`) | Low-Medium | Selectors centralised; no tables found → `AdapterError` (REQ-3.6). |
| R3 | Section heading text changes | Low | Normalised prefix match against `AMP_SECTIONS`. |
| R4 | `Pout`/`Psat`/`P1dB` semantics | Resolved | Verified on 2 parts: `Pout` = saturated output power = `Psat` (VM088D shows 8 dB compression). `OP1dB`=P1dB; `Psat`=Psat. High Power yields Psat (from `Pout`), no table P1dB. |
| R5 | Core Chips (T/R modules) don't fit single-amplifier model | Known | Deferred (VW-OQ-2). |
| R6 | Site intermittently unreachable (TLS/connect) | Medium | `AdapterError` + cache + single retry. |
| R7 | Paramless / spacer rows | Resolved | `search()` applies the shared `drop_paramless` filter. |
| R8 | IP3 / MSL expected but missing | By design | Verified genuinely absent (saturated/radar parts on bare die); always UNKNOWN, documented (VW-OQ-1). |

### Open questions for implementation
- **VW-OQ-2:** Include Core Chips by mapping `Rx NF`→NF, `Tx Pout`→Psat, a Gain
  row→Gain? Or defer? Recommend defer initially.
- **VW-OQ-4:** `Voltage`/`Status` cells may be `TBD`/`New version` — treat as
  missing (`_num` → None).

---

## Summary

- **Source:** single `httpx.get` to `/search-engine-mmic` — server-rendered Divi
  Table Maker tables (no JS, robots-allowed). Microchip rejected (Akamai 403).
- **Parsing:** **transposed** tables (products = columns); group rows per section
  module; map params by normalised row label; model + datasheet URL from the
  header and `Datasheet` rows.
- **Scope (table, section-dependent, up to 6 params):** Frequency, Gain, P1dB
  (`OP1dB`), Psat (`Psat`/`Pout`), NF, VDD (`Voltage`/`DrainVoltage`).
- **Datasheet fallback (survivors only, gaps only):** Temperature + Size always;
  P1dB/NF where the section's table lacked them.
- **Never available (always UNKNOWN):** IP3 and MSL (verified — saturated/radar
  parts on bare die).
- **Reuses** shared `drop_paramless`.
- **Files to create:** `rf_finder/adapters/vectrawave.py`,
  `tests/adapters/test_vectrawave.py`, `tests/fixtures/vectrawave_mmic.html`.

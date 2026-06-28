# Design — RF Component Finder

> **Methodology:** Spec-Driven Development (SDD)
> **Sequence:** Requirements → **Design** → Tasks (currently in the Design stage)
> **Traces:** [requirements.md](requirements.md)
> **Scope for this iteration:** Phase 1 (amplifier ontology + structured Form Input) + Phase 2 (Mini-Circuits adapter + Verifier)
> **Status:** Draft pending approval

---

## 1. Design Overview

The system is a layered pipeline. A structured **form input** is collected into a
`QuerySpec`, dispatched to one or more manufacturer adapters, which return raw
`Candidate` objects; a `Verifier` normalizes and compares each candidate against
the spec and assigns a verdict; a `Reporter` ranks and renders the output.

```
Form input ──► QuerySpec ──► Adapter(s) ──► [Candidate] ──► Verifier ──► [VerifiedCandidate] ──► Reporter ──► CLI output
     │                            │                            │
     └────────── Ontology ────────┴──────── Units ────────────┘
                       (cross-cutting reference data)
```

Cross-cutting concerns: the **Ontology** and **Units** modules are shared
reference data consulted by the Form (field generation), the Adapter (header
mapping), and the Verifier (comparison). **Cache** and **Config** are
infrastructure used by the Adapter.

### Key design principles

1. **The Ontology is the single source of truth** for parameter names, canonical
   units, comparison rules, and which parameters apply to which component. Every
   other module reads from it; none hard-codes parameter knowledge. The form
   fields themselves are generated from it. (Satisfies NFR-3, REQ-2.)
2. **Adapters are pluggable behind one interface.** The core never imports a
   concrete adapter; adapters self-register. Adding a manufacturer = one new file.
   (Satisfies REQ-3.1, NFR-3.)
3. **Structured input, no parsing, no LLM.** The user fills a form whose fields
   are derived from the ontology, so the `QuerySpec` is built directly from typed
   fields — no free-text parsing, no LLM cost, fully deterministic and offline-
   testable. (Satisfies NFR-1, NFR-7.)
4. **Verification is separated from retrieval.** Adapters only fetch and map;
   they never judge a match. The Verifier owns all comparison logic. (Satisfies
   REQ-4, testability.)

---

## 2. Module Architecture

```
rf_finder/
├── __main__.py            # CLI entry point: run form → search → report (REQ-1.1, REQ-5)
├── models.py              # dataclasses: QuerySpec, ParamConstraint, Candidate,
│                          #   ParamVerdict, VerifiedCandidate
├── ontology/
│   ├── parameters.py      # central parameter dictionary (REQ-2.1–2.4)
│   ├── components.py      # component types + applicable params (REQ-1.2, REQ-1.3)
│   └── units.py           # unit conversions (REQ-2.5)
├── form/
│   ├── schema.py          # build form fields for a component from the ontology (REQ-1.2)
│   └── input.py           # collect + validate fields → QuerySpec (REQ-1.1, 1.4–1.7)
├── adapters/
│   ├── base.py            # Adapter ABC + registry (REQ-3.1)
│   └── minicircuits.py    # Mini-Circuits adapter (REQ-3.2–3.6)
├── verifier.py            # normalization + comparison + verdicts (REQ-4)
├── reporter.py            # ranking + CLI rendering (REQ-5)
├── cache.py               # SQLite response cache (NFR-1, NFR-2)
└── config.py              # loads config.yaml: site list, rate limits (NFR-5)
```

---

## 3. Data Models (`models.py`)

The data models are defined in a dedicated document:
**[data-models.md](data-models.md)**.

In brief, the pipeline passes these immutable `@dataclass(frozen=True)` objects:

```
QuerySpec ──(Adapter)──► Candidate ──(Verifier)──► VerifiedCandidate
   │ contains                │ contains               │ contains
ParamConstraint           RawValue              ParamVerdict
```

See [data-models.md](data-models.md) for full field definitions, invariants,
enumerations, and per-model requirements traceability.

---

## 4. Ontology Design (`ontology/`)

### 4.1 `parameters.py` (REQ-2.1–2.4)

A single dictionary keyed by canonical parameter name. Each entry is the
authoritative definition consulted by the Form (field + label + unit options),
the Adapter (column mapping), and the Verifier (comparison). The `label` and
`units` fields drive the form; `comparison` drives the verifier.

```python
PARAMETERS: dict[str, ParamDef] = {
    "freq_range": ParamDef(
        label="Frequency range",
        canonical_unit="GHz", units=["GHz", "MHz"],
        comparison="contains",            # range param → min/max fields in form
        applies_to=["amplifier", "mixer", "filter", "attenuator", "..."],
    ),
    "P1dB": ParamDef(
        label="P1dB (output 1 dB compression)",
        canonical_unit="dBm", units=["dBm", "W", "mW"],
        comparison="between",             # bounded-scalar param → min/max fields in form
        applies_to=["amplifier"],
    ),
    "Gain":  ParamDef("Gain",          "dB",  ["dB"],        "between", ["amplifier"]),
    "NF":    ParamDef("Noise figure",  "dB",  ["dB"],        "between", ["amplifier"]),
    "OIP3":  ParamDef("OIP3",          "dBm", ["dBm"],       "between", ["amplifier"]),
    "Pout":  ParamDef("Saturated power (Psat)",
                                       "dBm", ["dBm","W","mW"], "min", ["amplifier"]),
}
```

> **Note:** `label` is the human-readable field name shown in the form; `units`
> is the list offered in the field's unit selector (canonical first, REQ-1.4).
> A `contains` **or** `between` comparison signals a **range** parameter → the
> form renders separate min/max inputs (REQ-1.5). `contains` compares a candidate
> *range* against the required band (frequency); `between` checks that a candidate
> *scalar* falls within the required band, with one-sided defaults (omitted min→-∞,
> omitted max→+∞). No aliases are needed: the form presents labels directly, so
> there is no free text to disambiguate.

### 4.2 `components.py` (REQ-1.2, REQ-1.3)

```python
COMPONENTS: dict[str, ComponentDef] = {
    "amplifier": ComponentDef(label="Amplifier"),
    # mixer, filter, attenuator ... added in later phases
}
```

The component type is chosen from this list in the form (REQ-1.3). The set of
parameters offered for a chosen component is computed from the ontology by
filtering `PARAMETERS` on `applies_to` (REQ-1.2).

### 4.3 `units.py` (REQ-2.5)

Pure functions, no I/O, fully unit-testable (NFR-7). Conversions are expressed
relative to each canonical unit:

```python
def to_canonical(value: float, from_unit: str, canonical: str) -> float: ...
# frequency: Hz, kHz, MHz, GHz  → GHz
# power:     W, mW, dBm         → dBm   (dBm = 10*log10(mW))
```

---

## 5. Form Input Design (`form/`)

### 5.1 Strategy: ontology-driven structured form (NFR-1, NFR-7)

The form is built from the ontology and produces a `QuerySpec` directly — no
free-text parsing and no LLM. Two modules:

**`schema.py` — `build_form(component_type) -> FormSchema`.**
Given a component type, returns the ordered list of fields to present, computed
from the ontology (REQ-1.2):
- For each `param` in `PARAMETERS` where `component_type in param.applies_to`,
  emit a `Field(name, label, units, kind)`.
- `kind = "range"` if `param.comparison in ("contains", "between")` (renders
  min + max), else `kind = "scalar"` (renders a single value). Each field carries
  its `units` list (canonical first) for the unit selector (REQ-1.4, REQ-1.5).

**`input.py` — `collect(schema) -> QuerySpec`.**
Drives the interactive form (component selection first, then the parameter
fields) and converts the filled fields into constraints:
- Component type is chosen from `COMPONENTS` (REQ-1.3).
- Empty fields are skipped — only filled fields become `ParamConstraint`s
  (REQ-1.6).
- Each field is validated: numeric value, `min ≤ max` for ranges, sane bounds;
  invalid input is rejected with a clear message (REQ-1.7).
- The chosen unit is stored on the constraint (values are NOT converted here;
  the Verifier normalizes — keeps the form dumb and the Verifier authoritative).

Both modules are pure/offline and unit-testable (NFR-7). The interactive prompt
library (e.g. `questionary`) is isolated in `input.py` behind a thin seam so the
field-to-constraint logic can be tested without a TTY.

> **Implementation note (CLI form):** the primary UX is an interactive prompt
> (select component → fill fields). Equivalent non-interactive CLI flags
> (e.g. `--type amplifier --freq-min 2 --freq-max 6 --freq-unit GHz --p1db 26`)
> map to the same `collect` logic and are convenient for scripting/tests.

### 5.2 Worked example

Form input — component **Amplifier**; `Frequency range` min `2` max `6` unit `GHz`;
`P1dB` min `26` (max left blank) unit `dBm`; all other fields left empty → produces:

```python
QuerySpec(
  component_type="amplifier",
  constraints=[
    ParamConstraint("freq_range", "contains", None, (2.0, 6.0),           "GHz"),
    # P1dB is a "between" param; only-min given → max defaults to +inf.
    ParamConstraint("P1dB",       "between",  None, (26.0, float("inf")), "dBm"),
  ],
)
```

---

## 6. Adapter Design (`adapters/`)

### 6.1 Interface (`base.py`, REQ-3.1)

```python
class Adapter(ABC):
    manufacturer: str
    supported_components: set[str]
    datasheet_params: frozenset[str] = frozenset()   # params only a datasheet has

    @abstractmethod
    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Build a manufacturer-specific search, return raw candidates.
        Must NOT judge matches. Raises AdapterError with context on failure
        (REQ-3.6)."""

    # --- generic datasheet enrichment (REQ-3.8); see §6.4 ---
    def needs_datasheet(self, spec) -> bool: ...     # spec params ∩ datasheet_params
    def enrich(self, candidate, needed) -> Candidate: ...  # generic template
    def _datasheet_text(self, candidate) -> str | None:    # hook, default None
        return None

ADAPTERS: dict[str, Adapter] = {}     # self-registration registry, keyed by manufacturer
```

### 6.2 Mini-Circuits Adapter (`minicircuits.py`)

**Investigation findings (resolves A-2 / OQ-2).** The amplifier parametric page
is `https://www.minicircuits.com/WebStore/Amplifiers.html`. There is **no public
documented REST API** (the "Yoni" engine is interactive only). Therefore, per the
REQ-3.3 fallback order, this adapter uses the **parametric web page + results
table scraping** path. The exact request mechanism (GET query string vs.
AJAX/POST) will be confirmed by network inspection during implementation (a
task), but the **results table schema is already confirmed**:

**Confirmed Mini-Circuits column → canonical ontology mapping (REQ-3.4):**

| Mini-Circuits column header | Canonical param | Canonical unit | Notes |
|------------------------------|-----------------|----------------|-------|
| `Model Number`               | `model`         | —              | identity |
| `F Low (MHz)`                | `freq_range.min`| GHz            | MHz→GHz; combine with F High |
| `F High (MHz)`               | `freq_range.max`| GHz            | MHz→GHz; combine with F Low |
| `Gain (dB) Typ.`             | `Gain`          | dB             | |
| `NF (dB) Typ.`               | `NF`            | dB             | |
| `P1dB (dBm) Typ.`            | `P1dB`          | dBm            | target param |
| `PSAT (dBm) Typ.`            | `Pout`          | dBm            | |
| `OIP3 (dBm) Typ.`            | `OIP3`          | dBm            | |
| `Voltage (V)`                | `voltage`       | V              | not used this iter |
| `Current (mA)`               | `current`       | mA             | not used this iter |
| `Case Style`, `Connector Type` | —             | —              | metadata |

> **Critical design note:** Mini-Circuits reports frequency as two MHz columns
> (`F Low`, `F High`), while our canonical `freq_range` is a GHz tuple. The
> adapter combines the two columns into one `RawValue((f_low, f_high), "MHz")`;
> the Verifier (not the adapter) converts to GHz and applies the `contains` rule.
> This is exactly the scenario that justified the `contains` rule and the units
> layer in requirements.

**Search strategy.** The adapter passes the query's frequency band to the page's
F Low / F High filters to narrow server-side where possible, then scrapes the
full results table and maps every column. Non-frequency constraints
(P1dB, Gain, etc.) are intentionally **not** pushed to the site filter — they are left
to the Verifier so that `partial`/near-miss candidates are still surfaced rather
than silently dropped by the site. Respects robots.txt + rate limiting (NFR-6).

**Fetching.** `httpx` for plain HTML; if the table proves to be JS-rendered,
fall back to `playwright` (dependency already planned, D-1). Decision deferred to
the implementation task that inspects the live request.

### 6.3 AmcomUSA Adapter (`amcomusa.py`, REQ-3.7)

Static ASP.NET HTML, no API. Eight amplifier categories each render a
`table#allPnTable`; values are the **cell text**, aligned 1:1 with the live
header row (read per category — column order/units differ). Frequency is MHz for
LNA / Medium-Power SSPA and GHz elsewhere, stored in its source unit and
normalised by the Verifier; `Psat` and `Pout` both map to canonical `Pout`. The
card-only **Rackmount HPAs** page (no table) yields model+link candidates. The
datasheet PDF link is captured per row from `td.pn-pdf` for enrichment (§6.4).

### 6.4 Generic datasheet enrichment (`datasheet.py` + `base.py`, REQ-3.8)

Some parameters appear on **no** HTML table (verified live: OIP3 is absent from
every AmcomUSA table) and live only in the PDF datasheet. Enrichment is generic,
not manufacturer- or parameter-specific:

- **`datasheet.py`** — shared engine: `extract_pdf_text` (pdfplumber), a
  `PATTERNS` library (`canonical → (regex, unit)`), and `parse_params(text, wanted)`.
- **`base.Adapter`** — `datasheet_params` declaration, `needs_datasheet(spec)`,
  the generic `enrich` template (hook → `parse_params` → merge **without
  overwriting table values** → `source="datasheet"`), and the `_datasheet_text`
  hook (default `None`).
- An adapter opts in by declaring `datasheet_params` and overriding
  `_datasheet_text` (locate + download + `extract_pdf_text`). AmcomUSA declares
  `{"OIP3"}`.
- **Orchestration (`__main__`)** loads a datasheet only when `needs_datasheet(spec)`
  is true, and only for `partial` candidates whose every `UNKNOWN` is
  datasheet-recoverable (i.e. the rest already `PASS`), then re-verifies.

Adding a datasheet parameter = one `PATTERNS` entry + the adapter's
`datasheet_params`. No new per-adapter parsing code.

---

## 7. Verifier Design (`verifier.py`, REQ-4)

Pure logic, no network, fully unit-testable (NFR-7).

```python
def verify(spec: QuerySpec, cand: Candidate) -> VerifiedCandidate:
    verdicts = []
    for c in spec.constraints:
        raw = cand.raw_params.get(c.canonical_name)
        if raw is None:
            verdicts.append(ParamVerdict(c.canonical_name, "UNKNOWN", c, None))
            continue
        got = normalize(raw, c.unit)            # units.to_canonical
        verdicts.append(ParamVerdict(c.canonical_name, compare(c, got), c, raw))
    overall = decide(verdicts)                  # see rules below
    return VerifiedCandidate(cand, verdicts, overall, cand.source)
```

**`compare` rules (REQ-2.4, REQ-4.1):**

| comparison | PASS condition |
|------------|----------------|
| `min`      | `found >= required.value` |
| `max`      | `found <= required.value` |
| `contains` | `found.min <= required.range.min AND found.max >= required.range.max` |
| `between`  | `required.range.min <= found <= required.range.max` (scalar `found`; an omitted bound is `-∞` / `+∞`) |
| `eq`       | `found == required.value` (within tolerance) |

**`decide` rules (REQ-4.2, REQ-4.4, REQ-4.5):**
- any `FAIL` → `overall = "fail"`
- else any `UNKNOWN` → `overall = "partial"`
- else (all `PASS`) → `overall = "match"`

Confidence is taken from `candidate.source` (REQ-4.3): `"table"` or
`"datasheet"`, falling back to `"unknown"` if a candidate carries no source
information. This iteration always yields `"table"`.

---

## 8. Reporter Design (`reporter.py`, REQ-5)

- Prints a summary of the entered `QuerySpec` first (REQ-5.1), so the user confirms the search.
- Sorts: `match` > `partial` > `fail`; within a tier, by margin of strongest
  constraint (REQ-5.3).
- Renders a per-candidate table: model, manufacturer, per-param PASS/FAIL/UNKNOWN
  (with the found value), confidence badge, link (REQ-5.2).
- If no `match` and no `partial`: explicit "no matching components found"
  message (REQ-5.4).

---

## 9. Cross-Cutting Infrastructure

### 9.1 Cache (`cache.py`, NFR-1, NFR-2)
SQLite keyed by `(adapter, normalized_query_url)` for adapter HTTP responses.
TTL configurable; default 7 days. (No LLM-parse cache — the form path makes no
LLM calls this iteration.)

### 9.2 Config (`config.py`, NFR-5)
`config.yaml` holds the manufacturer site list, rate limits, and cache TTL. No
secrets in code. A `config.example.yaml` is committed. (An Anthropic API key
entry is reserved for the future free-form search path.)

### 9.3 Error handling (REQ-3.6, NFR-4)
Adapters raise `AdapterError(manufacturer, context, cause)`. The dispatcher
catches per-adapter, reports it, and continues with remaining adapters — one
site failure never aborts the run.

---

## 10. Testing Strategy (NFR-7)

| Module | Test type | Network? |
|--------|-----------|----------|
| `ontology/units` | unit (conversion table) | no |
| `form/schema` + `form/input` | unit (fields from ontology; fields→QuerySpec incl. the target example) | no |
| `verifier` | unit (PASS/FAIL/UNKNOWN/contains matrix) | no |
| `adapters/minicircuits` | unit against a **saved HTML fixture** of the results table | no |
| end-to-end | integration (live, optional/marked) | yes |

The Mini-Circuits adapter is tested against a captured HTML fixture so the
column-mapping logic is verifiable offline and stable against site changes.

---

## 11. Requirements Traceability

| Requirement | Design element |
|-------------|----------------|
| REQ-1.1–1.7 | §5 Form Input (schema + input), §3 QuerySpec |
| REQ-2.1–2.5 | §4 Ontology, §4.3 Units |
| REQ-3.1–3.6 | §6 Adapter interface + Mini-Circuits, §9.3 errors |
| REQ-3.7–3.8 | §6.3 AmcomUSA adapter, §6.4 generic datasheet enrichment |
| REQ-4.1–4.5 | §7 Verifier |
| REQ-5.1–5.4 | §8 Reporter |
| NFR-1 | §5.1 structured form (no LLM), §9.1 cache |
| NFR-2 | §9.1 cache |
| NFR-3 | §6.1 adapter registry, §4 ontology-driven |
| NFR-4 | §9.3 per-adapter error isolation |
| NFR-5 | §9.2 config |
| NFR-6 | §6.2 robots/rate limiting |
| NFR-7 | §10 offline unit tests |

---

## 12. Open Items Carried to Implementation

- **I-1** — Confirm Mini-Circuits request mechanism (GET query string vs AJAX/POST)
  by live network inspection; decide `httpx` vs `playwright`. (§6.2)
- **I-2** — Capture an HTML fixture of the amplifier results table for offline
  adapter tests. (§10)

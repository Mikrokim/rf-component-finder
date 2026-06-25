# Data Models — RF Component Finder

> **Methodology:** Spec-Driven Development (SDD)
> **Traces:** [requirements.md](requirements.md) · [design.md](design.md)
> **Purpose:** Single authoritative definition of the data structures (`models.py`)
> shared across Form Input, Adapter, Verifier, and Reporter. Referenced from
> [design.md §3](design.md).
> **Status:** Draft pending approval

---

## 1. Overview

All models are immutable `@dataclass(frozen=True)` objects living in
`rf_finder/models.py`. They carry no behavior — comparison and normalization
logic lives in the Verifier and Units modules, not on the models. This keeps the
models trivially serializable (for caching) and unit-testable.

Data flows through the models in this order:

```
QuerySpec ──(Adapter)──► Candidate ──(Verifier)──► VerifiedCandidate
   │  contains                │ contains               │ contains
ParamConstraint           RawValue              ParamVerdict (+ Candidate)
```

> **Scope note:** This document covers only the cross-cutting models shared
> between modules (`rf_finder/models.py`). The form-internal structures
> `FormSchema` and `Field` (see [design.md §5.1](design.md)) live in
> `rf_finder/form/schema.py`, are consumed only within the form layer, and are
> intentionally not part of the shared models.

---

## 2. Input Models

### 2.1 `ParamConstraint`

A single requirement on one parameter. Produced by the Form Input, consumed
by the Verifier. (REQ-1.4, REQ-1.5, REQ-2.4)

```python
@dataclass(frozen=True)
class ParamConstraint:
    canonical_name: str          # e.g. "P1dB", "freq_range"
    comparison: str              # "min" | "max" | "contains" | "eq" | "between"
    value: float | None          # for min/max/eq, in the chosen `unit`
    range: tuple[float, float] | None   # for "contains"/"between" (e.g. (2.0, 6.0))
    unit: str                    # the unit chosen in the form, e.g. "dBm", "GHz"
```

**Invariants:**
- Exactly one of `value` / `range` is non-`None`.
- `comparison in ("contains", "between")` ⇒ `range` is set; all others ⇒ `value`
  is set. For `between`, a one-sided range uses `-∞` (min) or `+∞` (max) for the
  omitted bound (so it imposes no restriction).
- `unit` is one of the parameter's accepted units (canonical or an equivalent);
  values are NOT pre-converted — the Verifier normalizes both sides to canonical.

### 2.2 `QuerySpec`

The structured search built from the form. Output of the Form Input, input to
every Adapter. (REQ-1.1, REQ-1.6, REQ-1.7)

```python
@dataclass(frozen=True)
class QuerySpec:
    component_type: str          # canonical, e.g. "amplifier"
    constraints: list[ParamConstraint]   # only the filled fields (REQ-1.6)
```

**Invariants:**
- `component_type` is a canonical key in `COMPONENTS` (chosen from the form, REQ-1.3).
- `constraints` contains one entry per filled field; empty fields are omitted
  (REQ-1.6). An all-empty form yields an empty `constraints` list (valid, but the
  Reporter will note there are no criteria to match on).

---

## 3. Retrieval Models

### 3.1 `RawValue`

A value exactly as found on a manufacturer source, **before** unit
normalization. Produced by an Adapter, normalized by the Verifier.

```python
@dataclass(frozen=True)
class RawValue:
    value: float | tuple[float, float]   # scalar, or (low, high) for a range
    unit: str                            # source unit, pre-normalization (e.g. "MHz")
```

> **Why pre-normalization:** Mini-Circuits reports frequency in MHz as
> `(F Low, F High)`. The Adapter records the raw `(low, high)` + `"MHz"`; the
> Verifier converts to the canonical unit. Adapters never convert units — see
> [design.md §6.2](design.md).

### 3.2 `Candidate`

One component returned by an Adapter, with its raw parameters mapped to canonical
names but **not** yet verified. (REQ-3.5)

```python
@dataclass(frozen=True)
class Candidate:
    model: str
    manufacturer: str
    url: str
    raw_params: dict[str, RawValue]      # canonical_name -> RawValue
    source: str                          # "table" | "datasheet"
                                         #   (this iteration: always "table")
```

**Invariants:**
- Keys of `raw_params` are canonical parameter names (from the ontology mapping).
- `source` drives the Verifier's confidence level (REQ-4.3).

---

## 4. Verification Models

### 4.1 `ParamVerdict`

The result of checking one constraint against one candidate. (REQ-4.1, REQ-4.2)

```python
@dataclass(frozen=True)
class ParamVerdict:
    canonical_name: str
    status: str                  # "PASS" | "FAIL" | "UNKNOWN"
    required: ParamConstraint    # what was asked
    found: RawValue | None       # what the candidate had (None ⇒ UNKNOWN)
```

### 4.2 `VerifiedCandidate`

A candidate plus its full verdict set and overall outcome. Output of the
Verifier, input to the Reporter. (REQ-4.4, REQ-4.5, REQ-4.3)

```python
@dataclass(frozen=True)
class VerifiedCandidate:
    candidate: Candidate
    verdicts: list[ParamVerdict]
    overall: str                 # "match" | "partial" | "fail"
    confidence: str              # "table" | "datasheet" | "unknown"  (from candidate.source)
```

**`overall` derivation (REQ-4.4, REQ-4.5):**
- any verdict `FAIL` → `"fail"`
- else any verdict `UNKNOWN` → `"partial"`
- else (all `PASS`) → `"match"`

---

## 5. Enumerations (string constants)

To avoid magic strings, these are defined once (e.g. as `Literal` types or module
constants) and reused:

| Group | Values |
|-------|--------|
| `comparison` | `"min"`, `"max"`, `"contains"`, `"eq"`, `"between"` |
| verdict `status` | `"PASS"`, `"FAIL"`, `"UNKNOWN"` |
| `overall` | `"match"`, `"partial"`, `"fail"` |
| `source` (Candidate) | `"table"`, `"datasheet"` |
| `confidence` (VerifiedCandidate) | `"table"`, `"datasheet"`, `"unknown"` (REQ-4.3) |

---

## 6. Requirements Traceability

| Model | Requirements |
|-------|--------------|
| `ParamConstraint` | REQ-1.4, REQ-1.5, REQ-2.4 |
| `QuerySpec` | REQ-1.1, REQ-1.3, REQ-1.6, REQ-1.7 |
| `RawValue` | REQ-2.5, REQ-3.5 |
| `Candidate` | REQ-3.4, REQ-3.5 |
| `ParamVerdict` | REQ-4.1, REQ-4.2 |
| `VerifiedCandidate` | REQ-4.3, REQ-4.4, REQ-4.5 |

# Requirements — RF Component Finder

> **Methodology:** Spec-Driven Development (SDD)
> **Sequence:** Requirements → Design → Tasks (currently in the Requirements stage)
> **Scope for this iteration:** Phase 1 (amplifier ontology + structured Form Input) + Phase 2 (Mini-Circuits adapter + Verifier)
> **Status:** Draft pending approval

---

## 1. Background and Goal (Vision)

A local Python tool that accepts a **structured form input** for locating an RF
component (the user selects a component type and fills parameter fields — e.g.
amplifier, frequency `2–6 GHz`, P1dB `26 dBm`), performs a tailored search across
official manufacturer sites according to how each manufacturer presents its data,
and **verifies** that the parameters actually match — rather than relying on a
result title alone.

The full system is designed around two search paths: (a) adapters for the
manufacturers on the list, (b) smart free-form search across additional
manufacturers. **In this iteration we build path (a) only, for amplifiers only,
starting with two manufacturers (Mini-Circuits and AmcomUSA).**

### Scope

**In scope for this iteration:**
- Single component type: **amplifier**
- Manufacturers: **Mini-Circuits** and **AmcomUSA**
- Structured form input → structured data (`QuerySpec`)
- Ontology of parameters relevant to amplifiers (drives the form fields)
- Real search against Mini-Circuits and AmcomUSA and verification of parameters against the request
- Verification source is primarily the manufacturer parametric **table**; for a parameter a table omits (e.g. OIP3 on AmcomUSA), an adapter MAY recover it from the product **PDF datasheet** (optional, targeted enrichment — see REQ-3.7/3.8)
- Clean CLI output

**Out of scope (future phases, documented to prevent ambiguity):**
- Qorvo, Macom, and the rest of the list (the list of 10 manufacturers is pending)
- Path (b) — free-form search via SerpAPI
- Additional RF components (mixers, filters, attenuators, etc.)
- Graphical / Web UI
- Search history / user accounts

---

## 2. Stakeholders and Users (Personas)

| Persona | Description | Primary need |
|---------|-------------|--------------|
| RF engineer | The primary user | Find a component that meets exact parameters, quickly and with confidence |
| Tool maintainer | Whoever adds adapters/parameters | Add a manufacturer or parameter without breaking existing behavior |

---

## 3. Glossary

| Term | Definition |
|------|------------|
| **QuerySpec** | Structured data object describing the user's request, built from the form fields |
| **Form schema** | The set of fields presented to the user for a given component type, derived from the ontology |
| **Ontology** | Central dictionary mapping parameter names, units, comparison rules, and applicable component types |
| **Adapter** | Manufacturer-specific module that knows how to build a search and interpret results in that manufacturer's terms |
| **Canonical unit** | The standard unit every value is converted to (GHz for frequency, dBm for power, etc.) |
| **Comparison rule** | The comparison rule for a parameter: `min` / `max` / `contains` / `eq` / `between` |
| **Verifier** | Component that compares actually-extracted values against the QuerySpec and marks a confidence level |

---

## 4. Functional Requirements (EARS Notation)

> EARS syntax: *WHEN \<trigger\>, the system SHALL \<response\>* / *IF \<condition\>, the system SHALL \<response\>* / *The system SHALL \<requirement\>*

### REQ-1 — Structured Form Input

- **REQ-1.1** — The system SHALL present a structured form in which the user selects a component type and fills in discrete parameter fields (no free-form text query).
- **REQ-1.2** — WHEN a component type is selected, the system SHALL derive the available parameter fields from the ontology, showing only the parameters that apply to that component type.
- **REQ-1.3** — The system SHALL present the component type as a selection from the ontology's known component types (the user does not type the type as free text).
- **REQ-1.4** — For each parameter field, the system SHALL default to the parameter's canonical unit and allow selecting an equivalent unit; the chosen unit SHALL be recorded together with the value.
- **REQ-1.5** — For range parameters — both `contains` (e.g. `freq_range`, `Temperature`) and bounded-scalar `between` (e.g. `VDD`) — the system SHALL provide separate `min` and `max` input fields. For a `between` parameter either side may be omitted: an omitted `min` defaults to `-∞` and an omitted `max` defaults to `+∞` (a one-sided range — an omitted bound imposes no restriction).
- **REQ-1.6** — The system SHALL treat empty fields as "no constraint" and include only the filled fields as constraints in the `QuerySpec`.
- **REQ-1.7** — The system SHALL validate each field (numeric value, `min ≤ max`, value within sane bounds) and reject invalid input with a clear message, producing a valid `QuerySpec` or an explicit validation error.

### REQ-2 — Parameter Ontology

- **REQ-2.1** — The system SHALL maintain a central dictionary defining, per parameter: canonical name, display label, canonical unit, accepted equivalent units, comparison rule, and the component types it applies to.
- **REQ-2.2** — The system SHALL support at least the following parameters for amplifiers: frequency range (`freq_range`), P1dB, Gain, Noise Figure (NF), IP3, Psat, VDD (supply voltage), Size, MSL (moisture sensitivity level, 1–5), and operating Temperature.
- **REQ-2.3** — The system SHALL use the ontology's display labels and applicable-parameter lists to build the form fields for the selected component type.
- **REQ-2.4** — The system SHALL define a comparison rule per parameter: `freq_range`=`contains`, `P1dB`/`Gain`/`IP3`/`Psat`=`min` (candidate must be at least the required value), `NF`/`Size`/`MSL`=`max` (candidate must be at most the required value), `VDD`=`between` (candidate must fall within a min/max band), `Temperature`=`contains` (the part's operating temperature range must contain the required range).
- **REQ-2.5** — The system SHALL convert between equivalent units (MHz↔GHz, dBm↔W, mW↔dBm), and SHALL treat dimensionless ratio units (dB, for Gain/NF) as an identity conversion (dB→dB), through a dedicated conversion module.

### REQ-3 — Site Adapters (generic; Mini-Circuits, AmcomUSA, Analog Devices)

> Manufacturer-specific refinements live in that adapter's own spec — e.g.
> [adapters/minicircuits/requirements.md](../adapters/minicircuits/requirements.md).

- **REQ-3.1** — The system SHALL expose a uniform adapter interface (`base adapter`) so that additional manufacturers can be added without changing the system core.
- **REQ-3.2** — WHEN a `QuerySpec` for a supported component is received, a site adapter SHALL build a search appropriate to the structure of that manufacturer's site/API.
- **REQ-3.3** — A site adapter SHALL prefer an official API if one exists; otherwise a parametric search via URL; otherwise scraping the results table.
- **REQ-3.4** — WHEN a results table is received, a site adapter SHALL map the manufacturer's column headers to the canonical parameter names in the ontology.
- **REQ-3.5** — A site adapter SHALL return a list of candidate components, each with a model number, manufacturer, link, and raw parameter values + units.
- **REQ-3.6** — IF the search fails (network/site structure change), a site adapter SHALL return a clear error with context, and not crash silently.
- **REQ-3.7** — The AmcomUSA adapter SHALL scrape every amplifier category table (`table#allPnTable`, plus the card-only Rackmount HPAs page), normalising MHz/GHz frequency and mapping per-category headers (e.g. `Pout`→`Psat`, `Vd`/`Bias`→`VDD`) to canonical names. A single category-page failure SHALL be skipped so the remaining categories still return (NFR-4).
- **REQ-3.8** — Every parameter a manufacturer's table omits but its product datasheet carries SHALL be recoverable from the PDF (on AmcomUSA: IP3, Size, MSL and operating Temperature). An adapter declares these in `datasheet_params`; the shared engine recovers them, supporting both scalar parameters (e.g. IP3, MSL, Size) and range parameters parsed as `(low, high)` for the `contains` rule (e.g. Temperature), and MAY read a value's unit inline (e.g. Size in mm vs inches) for the Verifier to normalise. The SearchManager SHALL load a datasheet only when the search constrains such a parameter (`needs_datasheet`) and only for candidates whose other required parameters already `PASS`; recovered values SHALL NOT overwrite table values and SHALL raise the candidate's confidence source to `datasheet`.

### REQ-4 — Result Verification (Verifier)

- **REQ-4.1** — WHEN a candidate component is received, the verifier SHALL convert its values to canonical units and compare them against the QuerySpec per each parameter's comparison rule.
- **REQ-4.2** — The verifier SHALL mark, per parameter, one of: `PASS` / `FAIL` / `UNKNOWN` (parameter not found on the component).
- **REQ-4.3** — The verifier SHALL mark a confidence level for the data source: `datasheet` (verified from PDF), `table` (from the manufacturer table only), `unknown`.
- **REQ-4.4** — A candidate SHALL be considered a match (`match`) only if all required parameters are `PASS`.
- **REQ-4.5** — IF a required parameter is `UNKNOWN`, the verifier SHALL mark the candidate as `partial` and not as a full `match`.

### REQ-5 — User Output (CLI Output)

- **REQ-5.1** — The system SHALL display a summary of the entered search criteria (`QuerySpec`) before the results (so the user can confirm the search).
- **REQ-5.2** — The system SHALL display results in an organized way: model, manufacturer, match status per parameter, confidence level, and link.
- **REQ-5.3** — The system SHALL rank full `match` results above `partial`.
- **REQ-5.4** — WHEN there are no matching results, the system SHALL state so explicitly and not return confusing empty output.

---

## 5. Non-Functional Requirements

- **NFR-1 (Cost)** — Form input SHALL require no LLM calls (input is fully local and deterministic); identical repeated searches SHALL be served from cache. LLM use is deferred to the future free-form search path.
- **NFR-2 (Performance)** — A single search SHALL return results within a reasonable time (target: < 30 seconds without cache).
- **NFR-3 (Extensibility)** — Adding a new manufacturer SHALL require writing a single adapter only, with no changes to the core.
- **NFR-4 (Robustness)** — A single site/network failure SHALL NOT bring down the whole run; the error is reported and the run continues with the remaining sources.
- **NFR-5 (Configuration)** — API keys and the site list SHALL be stored in external config, not in code.
- **NFR-6 (Compliance)** — Scraping SHALL respect robots.txt and the sites' rate limits.
- **NFR-7 (Testability)** — Every core module (form input, ontology, verifier) SHALL be unit-testable without network dependencies.

---

## 6. Assumptions and Dependencies

- **A-1** — No LLM/API key is required for this iteration; the structured form is fully local. (An Anthropic API key will be needed later for the free-form search path.)
- **A-2** — Each target manufacturer site has an accessible search path (API / parametric / table), verified per adapter in that adapter's spec (e.g. [adapters/minicircuits/requirements.md](../adapters/minicircuits/requirements.md)).
- **A-3** — Python 3.11+ is available in the runtime environment (Windows).
- **D-1** — External dependencies: `httpx`, `selectolax`/`playwright`, `pdfplumber`, `pyyaml`, and an interactive-prompt library for the form (e.g. `questionary`). (`anthropic` deferred to the free-form path.)

---

## 7. General Acceptance Criteria (Definition of Done for the iteration)

The iteration is complete when:
1. Completing the form (component = amplifier, frequency `2–6 GHz`, P1dB `26 dBm`) produces a valid QuerySpec and displays its summary.
2. The system returns real candidates from the configured manufacturer adapter(s). (Mini-Circuits acceptance: see [adapters/minicircuits/requirements.md](../adapters/minicircuits/requirements.md).)
3. Each candidate is marked `match` / `partial` / `fail` with a confidence level.
4. Unit tests exist for the form input, ontology, and verifier, and they pass.
5. All code is documented and consistent with the Design and Tasks documents.

---

## 8. Open Questions

- **OQ-1** — The full list of 10 manufacturers — pending (does not block this iteration).
- **OQ-2** — Manufacturer-specific open questions (e.g. whether a given site has a usable official API) are tracked in that adapter's spec — e.g. [adapters/minicircuits/requirements.md](../adapters/minicircuits/requirements.md).

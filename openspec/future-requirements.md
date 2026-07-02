# Future Requirements — RF Component Finder

> Legacy requirements from `specs/rf-component-finder/iteration1/requirements.md` that
> are **not (fully) implemented** in the current code. By the migration rule, these are
> NOT documentation gaps and are NOT added to `openspec/specs/` (which is limited to
> behavior that exists in code today). They are recorded here so the intended behavior
> is not lost, and most are already routed to a future OpenSpec change or an open question.

## Not implemented (or only partially implemented)

### REQ-1.3 — Component type as a selection (not free text)
**Legacy:** requirements.md §4 REQ-1.3 — "present the component type as a selection from the ontology's known component types (the user does not type the type as free text)."
**Current code:** `__main__.py` reads the component type via free-text `input("Component type [amplifier]")`. The value is still validated against `COMPONENTS` by `build_form`, but no selection UI exists.
**Status:** Not implemented (selection mechanism). Tracked as OQ-9. Currently moot — only `amplifier` is registered.

### REQ-1.7 (partial) — "value within sane bounds" validation
**Legacy:** requirements.md §4 REQ-1.7 — validate "value within sane bounds" and reject implausible input.
**Current code:** `form/input.py` validates numeric values, `min ≤ max`, and unit-in-list only. There is no sane-bounds / plausibility check. (The implemented part of REQ-1.7 is documented in `structured-form-input` → "Numeric validation".)
**Status:** Sane-bounds portion not implemented. Tracked as OQ-4.

### REQ-3.3 (partial) — adapter source preference (API → parametric → scrape)
**Legacy:** requirements.md §4 REQ-3.3 — "prefer an official API if one exists; otherwise a parametric search via URL; otherwise scraping the results table."
**Current code:** Each adapter hardcodes the single best source for its own site rather than performing a general API→parametric→scrape fallback: Mini-Circuits, AmcomUSA, and Marki scrape server-rendered HTML tables, while Analog Devices and RWM read the site's JSON endpoint/API directly. The practical outcome (use the API where one exists, otherwise scrape) is therefore realized per-adapter, but no general preference-ordering mechanism exists.
**Status:** Not implemented as a general mechanism (each adapter chooses its own source). Now exercised across both API and scrape sources; a dynamic preference layer remains unbuilt (see OQ-1).

### REQ-5.2 (partial) — display confidence level and manufacturer per result
**Legacy:** requirements.md §4 REQ-5.2 — display "model, manufacturer, match status per parameter, confidence level, and link."
**Current code:** `__main__.py` output prints model, per-parameter ✓/✗/? status, and the URL. The **confidence level is computed but not displayed**, and the **manufacturer is not shown** in the result line. (The implemented parts are documented in `cli-result-output`.)
**Status:** Confidence/manufacturer display not implemented. Tracked via future change `implement-reporter` (tasks.md §5.3).

### NFR-1 (partial) — repeated searches served from cache
**Legacy:** requirements.md §5 NFR-1 — "identical repeated searches SHALL be served from cache." (The no-LLM portion of NFR-1 IS implemented and documented.)
**Current code:** `cache.py` is a stub; the adapter is not wired to any cache and re-fetches on every run.
**Status:** Cache not implemented. Future change `implement-response-cache` (tasks.md §5.5).

### NFR-2 — performance target via caching
**Legacy:** requirements.md §5 NFR-2 — a single search returns within a reasonable time (target < 30s without cache).
**Current code:** No caching; the ~3.75 MB amplifiers page is fetched on every search. No performance instrumentation.
**Status:** Depends on the unimplemented cache. Future change `implement-response-cache` (tasks.md §5.5).

### NFR-5 — external configuration for keys and site list
**Legacy:** requirements.md §5 NFR-5 — "API keys and the site list SHALL be stored in external config, not in code."
**Current code:** `config.py` is a stub; the rate-limit delay is hard-coded and there is no config loader. (`config.example.yaml` exists but is not loaded.)
**Status:** Not implemented. Future change `implement-config-loader` (tasks.md §5.4).

## Additional intended behavior from design.md / t8-plan.md

### Non-interactive CLI flags
**Legacy:** design.md §5.1 implementation note and tasks.md T12 — equivalent CLI flags (e.g. `--type amplifier --freq-min 2 --freq-max 6 --freq-unit GHz --p1db 26`) mapping to the same `collect` logic for scripting.
**Current code:** Only interactive prompts and the in-process `answers` dict seam exist; no argument parsing in `__main__.py`.
**Status:** Not implemented. Future change `add-cli-flag-input` (tasks.md §5.2).

### Dedicated Reporter with within-tier margin ranking and confidence badge
**Legacy:** design.md §8 and tasks.md T11 — a `reporter.py` that ranks within a tier "by margin of the strongest constraint" and renders a confidence badge and a per-candidate table.
**Current code:** `reporter.py` is an empty stub; rendering is inline in `__main__.py` with tier-only ordering and no confidence display.
**Status:** Not implemented. Future change `implement-reporter` (tasks.md §5.3).

### Warn on significant scraped row-count drift
**Legacy:** t8-plan.md §9 (OQ-2) — log a warning when the scraped row count deviates significantly (e.g. >20%) between runs, as a possible site-redesign signal.
**Current code:** The adapter performs no run-to-run row-count comparison.
**Status:** Not implemented. Tracked as OQ-3 in `open-questions.md`.

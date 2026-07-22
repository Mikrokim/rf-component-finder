# Open Questions — RF Component Finder (OpenSpec)

> Active open-questions register for the OpenSpec source of truth. A question lives
> here while it is **Open** or **Investigating**; once **Resolved** or **Deferred**,
> record the outcome in the owning spec/change and remove it from this file.
>
> Carried forward from the legacy register `specs/rf-component-finder/open-questions.md`
> as part of the OpenSpec migration. The legacy file is retained read-only for history.

## Register

| ID | Question | Status | Origin |
|----|----------|--------|--------|
| OQ-1 | What is the full list of 10 manufacturers the system must support? | 🟡 Open | legacy OQ-1 |
| OQ-2 | Should `Candidate.url` be the robots-disallowed `modelSearch.html?model=XXX` URL, or the allowed `Amplifiers.html` page? | 🟡 Open | legacy OQ-2 |
| OQ-3 | Should the adapter warn when the scraped row count changes significantly between runs (possible site redesign)? | 🟡 Open | legacy OQ-3 |
| OQ-4 | Even when a field value is valid, should the form sanity-check it and warn that it may be a mistake (e.g. unit confusion)? | 🟡 Open | legacy OQ-4 |
| OQ-5 | How should VectraWave "Core Chips" (T/R modules with split Tx/Rx specs) map onto the single-amplifier ontology? | 🟡 Open | legacy VW-OQ-2 |

## Details

### OQ-1 — Full manufacturer list
**Question:** What are the 10 manufacturers the full system must eventually support?
**Why it matters:** Drives the adapter roadmap. Does not block current behavior — several `amplifier` adapters are implemented today (Mini-Circuits, Analog Devices, AmcomUSA, Marki, RWM, Qorvo, VectraWave, Guerrilla RF,macom, 3rwaves, microchip, ums; see `manufacturer-adapters` for the full list); the full manufacturer target list is still undetermined.
**Status:** 🟡 Open.

### OQ-2 — `Candidate.url` value choice
**Question:** Should `Candidate.url` be the disallowed `modelSearch.html?model=XXX` URL (more useful in the report) or the allowed `Amplifiers.html` page?
**Why it matters:** robots.txt disallows `modelSearch.html`. The adapter currently populates that URL string for display only and never fetches it (see `manufacturer-adapters` → "Candidate URL is populated for display only").
**Recommendation (legacy):** Use the model-specific URL for report value with a note that it is never fetched; fall back to `Amplifiers.html` if strict policy is required. Needs implementer sign-off.
**Status:** 🟡 Open.

### OQ-3 — Warn on row-count drift
**Question:** Should the adapter log a warning when the scraped row count deviates significantly (e.g. >20%) between runs?
**Why it matters:** A large change can signal a site redesign that breaks scraping. Not implemented today (the adapter does no run-to-run comparison).
**Status:** 🟡 Open.

### OQ-4 — Sanity-check valid-but-suspicious form input
**Question:** When a field value passes validation but looks implausible (e.g. P1dB entered in W instead of dBm, or a frequency off by 10×), should the form warn the user?
**Why it matters:** The form currently validates only hard validity — numeric, `min ≤ max`, and unit-in-list (see `structured-form-input` → "Numeric validation"). Legacy REQ-1.7 mentioned "value within sane bounds," which is **not** implemented; this question owns whether that behavior is desired.
**Options (legacy):** (a) none; (b) range-based "unusual value" warning; (c) unit-aware confirmation.
**Status:** 🟡 Open.

### OQ-5 — VectraWave "Core Chips" dual-path mapping
**Question:** How should a VectraWave "Core Chip" (a T/R front-end module with split `Tx Gain`, `Tx Pout`, `Rx Gain`, `Rx NF`) map onto the single-amplifier ontology, which assumes one gain / one NF per part?
**Why it matters:** A Core Chip carries two signal paths (transmit and receive), so it has two gains, an NF only on the receive path, and a Pout only on the transmit path — forcing it into the ontology's single `Gain`/`NF`/`Psat` slots would misrepresent the part. Candidate mappings (all undecided): pick one path, emit two candidates (one per path), extend the ontology for dual-path parts, or keep skipping Core Chips.
**Current behavior:** the adapter **skips Core Chips entirely** — it parses only the four amplifier sections (High Power, Medium Power, Low Noise, Wideband) and does not emit Core Chip candidates (see `manufacturer-adapters` → "VectraWave adapter retrieval and parsing").
**Status:** 🟡 Open (may be deferred).

### OQ-6 — Datasheet TEXT straight from an API, instead of a PDF URL
**Question:** Should the adapter contract gain a second seam — "give me this candidate's datasheet **text**" — alongside `resolve_datasheet_url` ("give me its PDF **URL**")?
**Why it matters:** Two live findings from the `add-datasheet-orchestration-pipeline` §6 verification pass push in this direction, and the current contract cannot express either:
- **Compliance.** Microchip's `datasheetUrl` points at `ww1.microchip.com`, whose robots.txt is `User-agent: * / Disallow: /`. Carrying the link is fine; the pipeline **fetching** it is a separate, unresolved question. The MCP tool `search_microchip_product_documents` (argument `query`, not `partNumber`) returns the document **content** as markdown straight from `api.microchip.com` — the allowed host — sidestepping `ww1` entirely.
- **Coverage.** That same tool returns a real datasheet for parts that carry no `datasheetUrl` at all (verified live for `MMA047CP4` and `SST12LP17E-XX8E`).
**Blocker:** `pipeline._enrich` assumes the chain URL → PDF bytes → text (`datasheet_text_from_url`). Supporting "the adapter already has the text" means changing design decisions D3/D5 and touching every adapter's contract — out of scope for `add-datasheet-orchestration-pipeline`, which is why it is recorded here rather than as a task.
**Options:** (a) leave as-is — Microchip parts whose datasheet cannot be fetched fall to `not-verified`, which is valid behaviour; (b) add an optional `datasheet_text(cand) -> str | None` seam the pipeline tries before the URL path; (c) keep it inside the Microchip adapter by having `resolve_datasheet_url` return an `api.microchip.com` URL that serves the content — needs verification that such a URL exists.
**Status:** 🟡 Open.

## Resolved during migration

### `openspec/` was git-ignored — RESOLVED
**Issue:** `git status` reported `!! openspec/`; the `.gitignore` (CRLF endings) had an unanchored `config.yaml` rule and a stray CR-only line matching arbitrary directories, which would have prevented the new OpenSpec files from being tracked.
**Resolution:** `.gitignore` was normalized to LF and the rule anchored to `/config.yaml` (repo root only). `git check-ignore` now reports `openspec/`, `openspec/specs`, and `openspec/open-questions.md` as not ignored. No application code changed. Recorded in the migration change's `proposal.md`/`design.md`.

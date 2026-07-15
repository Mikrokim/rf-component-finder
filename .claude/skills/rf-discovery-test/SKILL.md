---
name: rf-discovery-test
description: OFFLINE TEST TWIN of rf-discovery. Runs the exact same discovery workflow — three paths (A/B/C), the cheap Step 2.7 pre-screen, on-the-fly dedup, and immediate `@@CANDIDATE@@ {model, manufacturer, url}` streaming — but reads a fixed LOCAL JSON dataset (mockdata/path_{a,b,c}.json) instead of the web. No WebSearch/WebFetch, no external calls, no tokens spent on browsing. Used only when the conductor runs in RF_SKILL_MODE=test, to exercise the discovery→verify pipeline end-to-end cheaply. Pair with rf-verify-test.
---

# RF Component Discovery — TEST MODE (local JSON, no web)

This is the **offline test twin** of `rf-discovery`. Its job and behavior are
**identical** to the real skill — find every plausible candidate, screen cheaply,
and **stream each survivor immediately** as `@@CANDIDATE@@` — with exactly **one**
difference, marked below: the three discovery paths read a **fixed local JSON
dataset** instead of the live web. Nothing here is confirmed as a final match; a
JSON hit is only a *candidate*, verified downstream by `rf-verify-test`.

## DATA SOURCE (test mode) — the one and only change vs. rf-discovery

**You must never fetch a URL, run a web search, or open a datasheet.** All data
comes from three JSON files at the repository root (your working directory):

- **Path A** → `mockdata/path_a.json` (stands in for the parametric aggregators)
- **Path B** → `mockdata/path_b.json` (stands in for part-graph traversal)
- **Path C** → `mockdata/path_c.json` (stands in for the vendor-cache sweep)

Each file is `{ "components": [ { "model", "manufacturer", "url", "params": {…} }, … ] }`.
`params` uses the canonical amplifier keys (`freq_range`, `Gain`, `P1dB`, `NF`,
`IP3`, …) with unit-bearing string values. Read all three with the `Read` tool;
that is the whole of "search" in test mode.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain,
OP1dB, OIP3, NF, GHz, dBm) — that is how RF engineers read them.

## Required reference files

Before Step 1, load both:

- **`rf-parameter-rules.md`** — the general parameter-handling rules (`min`/`max`/
  `contains` semantics, the site-screen mechanics and tolerance).
- **The per-component module** matching the requested type (e.g.
  `rf-amplifier-module.md` for amplifiers) — which parameters are **site-checkable**
  (screenable) vs datasheet-only, their units, directions, and guard bands.

Only parameters defined in the loaded module may be used as filters. If no module
exists for the requested type, say so and stop rather than improvising.

## Core definitions

### site-checkable vs datasheet-only

The loaded module classifies each parameter as **site-checkable** (here: reliably
present in the JSON `params` and safe to screen on) or **datasheet-only** (never
screened here — confirmed later by `rf-verify-test`). Only site-checkable
parameters are used by the Step 2.7 screen.

### The site-data rule (promote-only, except one gate)

JSON data may **freely promote** a candidate, but may **reject** one **only** at
the Step 2.7 screen, and only on a clear miss on a site-checkable parameter the
entry actually states (or a catalog fact — a band that cannot contain the
request, wrong type). It cannot *confirm* a match — that is why every survivor
still goes to `rf-verify-test`. **Never silently skip a source**: a JSON file that
is empty or unreadable is logged, not omitted.

### Outcome categories (used in the coverage statement)

- `checked/no candidates` · `checked/found X` · `not covered`
- **`rejected at site screen`** — dropped at Step 2.7 on a clear miss on a stated
  site-checkable parameter (or a catalog fact), logged with the failing parameter
  and its value. A definitive site-level rejection, not a datasheet decision. Not
  emitting a `@@CANDIDATE@@` for a part that already failed is expected, not a gap.

## Workflow

### Processing model — stream candidates, do NOT batch

The **moment** a candidate surfaces from any path, run it through the Step 2.7
screen and — if it passes — **emit its `@@CANDIDATE@@` line immediately**, then
move on. Do not pool discovery first. **Dedupe on the fly**: keep a running set of
candidates already emitted (by vendor + part number) and skip any already seen —
never emit the same part twice (the placeholder dataset intentionally repeats one
part across two path files to exercise this). The conductor fires an
`rf-verify-test` run per `@@CANDIDATE@@` as it arrives.

### Step 1 — Parse the spec

Extract every parameter the spec provides into a requirements table: name, value,
direction (min/max/range), and whether it is site-checkable (per the module). The
spec arrives structured from the caller (component type + parameters); known
defaults: band containment is fine; typical values acceptable; any form factor.
Do not open an interactive clarification round — the caller has fixed the spec.

### Step 2 — Read the three path files (the local stand-in for "search wide")

Run the same three independent paths, each reading its JSON file:

- **Path A** — read `mockdata/path_a.json`; treat every entry as a candidate.
- **Path B** — read `mockdata/path_b.json`; treat every entry as a candidate.
  (Real Path B traverses part siblings/alternatives in waves; in test mode the
  file simply lists what that traversal would surface — wave-traversal is not
  simulated.)
- **Path C** — read `mockdata/path_c.json`; treat every entry as a candidate.

Per the Processing model, screen and emit **each candidate the instant you read
it**, deduping on the fly against everything already emitted. A part appearing in
two files is emitted **once**. If a file is missing/empty/unreadable, record that
in the coverage statement (`not covered` / `checked/no candidates`) — never fail
silently.

### Step 2.7 — Screen against the JSON params (cheap filter before emitting)

Before emitting a candidate, screen it using only its JSON `params` — the same
logic the real skill applies to site data (see `rf-parameter-rules.md` for
mechanics and guard-band tolerance). Using only the *site-checkable* parameters
the query actually specified:

1. For each such parameter the entry states, compare it to the query with the
   module's semantics/tolerance (guard band).
2. **Passes** when every site-checkable query parameter the entry states matches
   → **emit `@@CANDIDATE@@`**.
3. **Rejected at Stage 1** only when a stated site-checkable parameter clearly
   fails or a catalog fact rules it out (band that cannot contain the request,
   wrong type). Log it as `rejected at site screen`; do not emit it.

Safety rules (generic, in `rf-parameter-rules.md`): a parameter the user did not
specify or not in the module is ignored (treated as a match); a datasheet-only
parameter is never screened here; a site-checkable parameter the entry does not
state cannot reject the part (promote — `rf-verify-test` catches it); **when in
doubt, promote.**

### Emit candidates + coverage

**Emit each surviving candidate immediately, on its own line:**

```
@@CANDIDATE@@ {"model": "...", "manufacturer": "...", "url": "..."}
```

One compact JSON object per line, prefixed by the exact marker `@@CANDIDATE@@`.
`url` is the entry's `url`. Emit each unique candidate **once** (dedupe on the fly).

**Also return a final structured list** `{ "candidates": [ {model, manufacturer,
url}, ... ] }` — the complete, deduplicated set you emitted, as a safety net for
the conductor.

**End with an honest coverage statement** (in Hebrew): which of the three path
files were read and their outcomes (`checked/found X` / `checked/no candidates` /
`not covered`), how many unique candidates were emitted, and how many were
`rejected at site screen` (with the failing parameter). State plainly that this
was a **test-mode run over the local mock dataset**, not the live web — so
coverage reflects only what the JSON files contain.

## Notes

- This skill performs **no** external calls of any kind. In `RF_SKILL_MODE=test`
  the conductor also withholds the web tools, so browsing is impossible even if
  these instructions were ignored.
- Keep this file behavior-identical to `rf-discovery` except this DATA SOURCE
  change, so a diff between the two shows exactly what test mode alters.

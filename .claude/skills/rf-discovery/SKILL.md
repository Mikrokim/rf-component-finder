---
name: rf-discovery
description: Discover EVERY RF/microwave component (amplifiers, mixers, filters, switches, attenuators, couplers…) that plausibly matches a multi-parameter spec, as broadly and reliably as possible — then stream each surviving candidate immediately as `@@CANDIDATE@@ {model, manufacturer, url, screened}`, where `screened` records each query parameter's site outcome (pass/borderline/fail/not_stated) so rf-verify only opens the datasheet for what the sites could not settle. Runs three independent discovery paths (parametric aggregators, part-graph traversal, vendor-cache sweep) and a cheap site-level pre-screen, but does NOT read datasheets or decide final matches — that is rf-verify's job. Used by the pipelined AI Search conductor, which fires an rf-verify run per candidate this skill surfaces. The user's 12 usual vendor sites are always excluded — see the Vendor Lists section.
---

# RF Component Discovery (candidate finder)

Find **every** RF/microwave component that plausibly matches a multi-parameter spec, and stream each one the instant it surfaces. The user is an RF procurement/engineering professional; missing a genuine vendor is the expensive failure. Your job is **completeness of discovery** — cast the widest reliable net — **not** final verification: you screen cheaply on site data and hand each survivor to the conductor as a `@@CANDIDATE@@`. A separate skill (`rf-verify`) opens the datasheet and decides the real verdict. Never confirm a match here; a site hit is only a *candidate*.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain, OP1dB, OIP3, NF, GHz, dBm) — that is how RF engineers read them.

## Required reference files

Before Step 1, load both:

- **`rf-parameter-rules.md`** — the general, component-agnostic rules for how any parameter is handled (which parameters may be filtered on, `min`/`max`/`contains` semantics, the site-screen mechanics and tolerance).
- **The per-component module matching the requested component type** (e.g. `rf-amplifier-module.md` for amplifiers) — which parameters are **site-checkable** (screenable) vs datasheet-only, their units, directions, and guard bands.

Only parameters defined in the loaded component module may be used as filters. If no module exists for the requested component type, say so and ask how to proceed rather than improvising parameters.

## Core definitions

### site-checkable vs datasheet-only

The loaded component module classifies each parameter as **site-checkable** (reliably shown/filterable on parametric sites and catalog tables) or **datasheet-only** (reliably found only on the datasheet). Only site-checkable parameters are used by the Step 2.7 screen; datasheet-only parameters are never screened here (they are confirmed later by rf-verify).

### The site-data rule (promote-only, except one gate)

Site data (search snippets, distributor/parametric tables) may **freely add or promote** a candidate, but may **reject** one **only** at the Step 2.7 screen, and only via a catalog fact or a clear miss on a site-checkable parameter the site actually exposes. You never *decide* a match here — every survivor still goes to rf-verify. **Never silently skip or drop a source** in any step — an empty/blocked source is logged, not omitted.

**Record, don't decide.** A parameter that clears the spec **beyond** its guard band on a site is real evidence: rf-verify may confirm that parameter from it without opening the datasheet, and consults the datasheet only for what you could not settle. So your job is to record each screened parameter's outcome faithfully (Step 2.7) and pass it forward on the `@@CANDIDATE@@` line — rf-verify still assigns the verdict. Raw site values remain untrustworthy exactly where the guard band says they are (typ-at-one-frequency, missing conditions, plain errors); that is why only a value **beyond** the guard band counts as settled, and anything inside it is `borderline` and goes to the datasheet.

### Outcome categories (used in the coverage statement)

- `checked/no candidates` · `checked/found X` · `not covered`
- **`rejected at site screen`** — dropped at Step 2.7 on a clear miss on a site-exposed parameter (or a catalog fact), logged with the failing site parameter and its value. A definitive rejection at the site level; not a datasheet decision. Not emitting a `@@CANDIDATE@@` for a part that already failed on the site is expected, not a gap.

## Workflow

### Processing model — stream candidates, do NOT batch

The **moment** a candidate surfaces from any discovery path, run it through the Step 2.7 screen and — if it passes — **emit its `@@CANDIDATE@@` line immediately**, then move on. Do not pool all of discovery first. Discovery (the three paths) keeps running throughout; each new candidate is screened and emitted the same way. **Dedupe on the fly**: keep a running set of candidates already emitted (by vendor + part number) and skip one already seen — never emit the same part twice. The conductor fires an rf-verify run per `@@CANDIDATE@@` as it arrives, so streaming is what lets results reach the user early.

### Step 1 — Parse the spec

Extract every parameter the spec provides into a requirements table: name, value, direction (min/max/range), and whether it is site-checkable (per the module). The spec arrives structured from the caller (component type + parameters); known defaults: band containment is fine; typical values acceptable; any form factor. Do not open an interactive clarification round — the caller has already fixed the spec.

### Step 2 — Search wide (candidates), never trusting search snippets

Discovery must not hang on any single list of vendors. A small vendor that a hand-maintained list omits **and** Google indexes poorly falls through both nets and is missed entirely — this is exactly how Aelius Semiconductors' ASL 4020 / ASL4065 were missed on a real query ("amplifier 14–15 GHz, Gain≥20 dB, P1dB≥24 dBm"), even though everything.rf lists Aelius with 111 amplifiers. So run **three independent discovery paths**, and — per the Processing model above — screen and emit **each candidate the instant it surfaces** (`@@CANDIDATE@@`), rather than pooling everything first. **Dedupe on the fly** against a running set of already-emitted candidates (same vendor/part surfaced by more than one path is emitted once). A vendor is missed only if **all three** paths miss it — and even then the coverage statement says so honestly.

These paths are component-agnostic: the category and category hints vary by component type, the mechanism does not. In every path, **always exclude the user's 12 vendor domains** using blocked_domains (Vendor Lists section). Per the site-data rule, a hit from any path is only a *candidate* — it is verified later by rf-verify.

**Path A — Parametric aggregator query (operate the filters; do NOT keyword-search).**

**The Path A search must be deep, precise, and reliable — this is the standard the entire path is held to, not a slogan:**
- **Deep — full coverage:** page through **every** result page on all four aggregators; never stop at the first page or a partial view. Record how many pages/results each site returned. If a site paginates, lazy-loads, or caps results, exhaust it to the end — a result the filter admits but that sits on page 7 is missed only because you stopped early.
- **Precise — filter accuracy:** operate each site's **own parametric engine**, and set **every** `site-checkable` parameter from the current spec — each in the right direction (min/max/range) and with its guard band. Never keyword-search these domains and never trust a snippet, a summary card, or a category label in place of the real filtered value.
- **Reliable — failure transparency:** if any of the four sites is blocked, returns empty, times out, or lacks a filter the spec needs, **say so explicitly** in the coverage statement — never silently skip. A site that was not fully covered is named as not covered, with the reason; "0 results" and "could not reach the site" are different outcomes and must not be reported as the same thing.

Path A runs against a **fixed, closed set of aggregators — and only these four**. It never visits an individual manufacturer's own site, and no other aggregator is added to this path:

- **everything.rf** — the best RF-specific parametric DB
- **Mouser**
- **Digi-Key**
- **Octopart**

On each, drive the site's *own parametric/filter engine* (not a keyword box): pick the component category for **this** query (Amplifiers, Mixers, Filters, LNAs, …), set the numeric filters from the current spec (whichever parameters the loaded module marks site-checkable), and **page through ALL result pages**. This is a *category-wide* sweep filtered by the current spec — never a search for a pre-named part; return every part the filters admit. A keyword web-search against these domains is **NOT** a substitute for their parametric engine: it reproduces the indexing weakness that caused the Aelius miss above. Do not add any other aggregator to Path A — vendor discovery beyond these four happens in Paths B and C, not here.

**Path B — Part-graph traversal (vendor DISCOVERY through parts, not names).**

**The Path B search must be deep, precise, and reliable — this is the standard the entire path is held to, not a slogan:**
- **Deep — full traversal:** run **all four** derived-search types on **every** candidate (alternatives/equivalent/cross-reference; sibling parts in the family; the aggregator's "similar products" block; and a re-run in the found parts' vocabulary). Then keep looping wave after wave — each new vendor spawns its own derived searches — until a full wave surfaces no new vendor and no new plausible candidate, up to the 3-wave ceiling. Never stop after one search type, one candidate, or one wave.
- **Precise — correct traversal:** correctly recognize when a competing part comes from a vendor **not yet seen this session**, and when it does, actually sweep that vendor's catalog for the category — don't just note the name. Follow sibling families to their neighbors, and match each found part's **real vocabulary** rather than forcing one fixed term.
- **Reliable — honest coverage:** record **every** vendor the traversal discovers (these also grow the cache for Path C). If the loop stops at the 3-wave ceiling rather than because a wave ran dry, **say so explicitly** in the coverage statement — a ceiling-truncated traversal may have missed vendors and must never be presented as exhaustive.

One good candidate is a thread to pull; its purpose is to surface **new vendors no list or directory contains** — found through parts, not names. From every plausible candidate, run derived searches:

- "alternatives to <part number>" / "<part number> equivalent" / "cross reference"
- sibling parts in the same family (a vendor with an ARF1211 likely has ARF12xx neighbors — check the vendor's category page)
- each aggregator's "similar products" section on the candidate's page
- re-run the best query in the found parts' vocabulary ("driver amplifier" vs "gain block" vs "medium power amplifier").

Whenever a competing part comes from a **vendor not yet seen this session**, add that vendor and sweep its catalog for the category. **Loop until a wave surfaces no new vendors and no new plausible candidates, up to a ceiling of 3 waves** (or stop earlier once a wave adds nothing) — then continue; note the ceiling in the coverage statement if it was hit.

**Path C — Cache sweep.**

**The Path C search must be deep, precise, and reliable — this is the standard the entire path is held to, not a slogan:**
- **Deep — full sweep:** check **every** vendor in the cache relevant to the component category — not a sample, not just the ones that look likely. For each, actually open its catalog (site search or catalog PDF) and filter for the category; a vendor skipped because it "probably has nothing" is exactly how a match is missed.
- **Precise — correct access:** use the access method the cache records for each vendor (site search / catalog URL / PDF pattern). If a catalog PDF returns empty, do not accept that as "no parts" — it is probably scanned/image or bot-blocked, so fall back to the vendor's HTML pages or everything.rf's mirrored copy before concluding.
- **Reliable — honest coverage:** log **every** vendor swept, **including** those that returned nothing (`checked/no candidates`) — never omit an empty vendor. A vendor whose catalog was blocked, empty, or unreachable is named with the reason, never silently skipped; "no matching parts" and "could not read the catalog" are different outcomes.

Sweep the manufacturers in the vendor cache (Vendor Lists) relevant to the component category, checking their catalogs directly (site search or catalog PDF fetch). The cache is **not** the definition of which vendors exist — Paths A and B are; the cache only makes access to a *known* vendor cheap. If a catalog PDF returns empty, it is probably scanned/image or bot-blocked — say so and try the vendor's HTML pages or everything.rf's copy instead (per the site-data rule: never silently skip).

**Grow the cache.** Whenever Path A or Path B surfaces a vendor not already in the cache, append it there with the access metadata learned (domain, catalog URL, parse/access notes, component categories). The cache grows automatically toward completeness for the categories searched; no human maintains it.

### Step 2.7 — Site-level pre-screen (cheap filter before emitting a candidate)

Datasheet fetches are the expensive part, and they happen downstream in rf-verify. Before emitting a candidate, screen it using only the data the sites expose — no PDF. The screen uses only the *site-checkable* parameters the query actually specified (see `rf-parameter-rules.md` for mechanics and tolerance):

1. On each site, see which of those query parameters it can filter on or shows in its table.
2. Compare each to the query, using the semantics/tolerance in `rf-parameter-rules.md`.
3. **Passes** when every site-checkable query parameter the site exposes matches → **emit `@@CANDIDATE@@`** for verification.
4. **Rejected at Stage 1** only when a site-exposed parameter clearly fails or a catalog fact rules it out (band that cannot contain the request, wrong type/form factor, excluded vendor).

Safety rules (all generic in `rf-parameter-rules.md`): parameters the user did not specify or not in the module are ignored (treated as a match); a datasheet-only parameter is never screened here; a site-checkable parameter the site does not expose cannot reject the part (promote, confirm at datasheet); **when in doubt, promote** — rf-verify catches borderline parts.

**Log every Stage-1 reject** as `rejected at site screen` (see Outcome categories) — do not emit a `@@CANDIDATE@@` for it.

#### Record each screened parameter — what rf-verify runs on

rf-verify re-derives nothing from the sites: it confirms a parameter from what you record here, and opens the datasheet **only** for the parameters you could not settle. If every query parameter comes back `pass`, it returns the part with no datasheet fetch at all. So record one entry for **every parameter the query specified**, classified by the guard-band zones in `rf-parameter-rules.md`:

| `status` | When (`min` direction shown; `max` is the mirror) | Effect downstream |
|---|---|---|
| `pass` | site-exposed and satisfies the spec **beyond** the guard band — `site_value ≥ target` | rf-verify counts it confirmed; never re-extracted |
| `borderline` | site-exposed but satisfies it only **inside** the guard band — `target − G ≤ site_value < target` | rf-verify settles it on the datasheet |
| `fail` | site-exposed and clearly misses — `site_value < target − G` | rejected at site screen; not emitted at all |
| `not_stated` | datasheet-only, or no site exposed it | rf-verify settles it on the datasheet |

Alongside each, record `value` (the site value **as shown**, with its unit) and `source` (the URL the value came from). Both are `null` for `not_stated`.

**`pass` is a claim rf-verify acts on without re-checking — never mark a parameter `pass` you did not read off a site.** A value inside the guard band is `borderline`; an unexposed parameter is `not_stated`. Neither is `pass`. Over-marking `pass` makes rf-verify return a part as ✅ on evidence that was never established — the one failure mode nothing downstream can catch.

### Emit candidates + coverage

**Emit each surviving candidate immediately, on its own line:**

```
@@CANDIDATE@@ {"model": "ASL4020", "manufacturer": "Aelius", "url": "https://…", "screened": [{"name": "freq_range", "status": "pass", "value": "13-16 GHz", "source": "https://everything.rf/…"}, {"name": "Gain", "status": "pass", "value": "22 dB", "source": "https://everything.rf/…"}, {"name": "NF", "status": "not_stated", "value": null, "source": null}]}
```

One compact JSON object per line, prefixed by the exact marker `@@CANDIDATE@@`. `url` is the best link you have to the part itself (its product page or datasheet). `screened` carries one entry per **query** parameter, per the table above.

**Never omit `screened`** — it is what lets rf-verify skip the datasheet for parameters you already settled. A missing or empty `screened` is not a neutral default: it forces a full datasheet extraction of every parameter, and a part whose datasheet is unreachable can then be dropped for lack of evidence you already had.

The conductor parses each line and fires an rf-verify run for that candidate right away — so emit as you go, never in one batch at the end. Emit each unique candidate **once** (dedupe on the fly).

<!-- ============================================================================
     RUN-LOGGING BLOCK (optional; safe to delete this whole comment-to-comment
     section to opt out). Lets run logging record parts you drop at the Step 2.7
     site screen — which today appear only as prose in the coverage statement.
     Nothing else depends on it; deleting it only makes those rejects less
     structured in the log.
     ============================================================================ -->

**Emit each Step 2.7 site-screen reject on its own line**, symmetric to `@@CANDIDATE@@`, the moment you drop it:

```
@@REJECT@@ {"model": "XYZ123", "manufacturer": "SomeVendor", "param": "NF", "site_value": "4.2 dB", "reason": "NF 4.2 dB exceeds the requested max 1.5 dB beyond the guard band"}
```

One compact JSON object per line, prefixed by the exact marker `@@REJECT@@`. Emit it **only** for a part rejected at the site screen (a clear miss on a site-exposed parameter, or a catalog fact) — never for a part you promote (those become `@@CANDIDATE@@`). `param`/`site_value` name the deciding parameter and its value as shown on the site; `reason` is one short sentence. This is a report of a screen decision you already made; it is emitted whether or not run logging is on (the Python side decides whether to keep it). It does not replace the coverage statement's `rejected at site screen` lines — it is the machine-readable twin.

<!-- ==================== END RUN-LOGGING BLOCK ==================== -->

**Also return a final structured list** `{ "candidates": [ {model, manufacturer, url, screened}, ... ] }` — the complete, deduplicated set you emitted, each carrying the same `screened` array, as a safety net for the conductor.

**End with an honest coverage statement**: which of the three paths ran and their outcomes; which sources were fully swept vs only sampled; whether "no candidates" means "none exist" or "none found in sources covered". Include the manufacturers/sources coverage — one line per vendor touched through any path, **exhaustive** (a vendor that returned nothing is `checked/no candidates`, never omitted) and with Path-A aggregators **expanded** into per-vendor lines, each with the real query sent. If the Path B loop hit the 3-wave ceiling, say so. Coverage is bounded by what these sources contain — state plainly that a vendor absent from **every** path may still be missed.

## Efficiency notes

- The cheap **Step 2.7 site screen** before emitting is the main saver: only screen-passing parts become `@@CANDIDATE@@`, so rf-verify (which opens datasheets) runs only on plausible parts.
- **Dedupe on the fly** (Processing model): keep a running set of already-emitted candidates so a vendor/part surfaced by multiple paths is emitted once.
- If the user names a vendor missing from the cache, add it (Path C) for the session with whatever access metadata you learn — same auto-append rule Paths A/B use.

## Vendor Lists

### ALWAYS EXCLUDE — the user's 12 pre-checked sites

The user checks these manually before every search. Pass all of them in blocked_domains on every web search, and never emit a candidate from them:

| Vendor | Domain |
|---|---|
| Mini-Circuits | minicircuits.com |
| Qorvo (incl. Custom MMIC, Sirenza legacy parts) | qorvo.com |
| MACOM (incl. Mimix legacy) | macom.com |
| Analog Devices (incl. Hittite legacy) | analog.com |
| UMS | ums-rf.com |
| 3R Waves | 3rwave.com |
| AMCOM | amcomusa.com |
| VectraWave | vectrawave.com |
| Guerrilla RF | guerrilla-rf.com |
| Microchip | microchip.com |
| Marki Microwave | markimicrowave.com |
| RW MMIC | rwmmic.com |

Legacy-brand note: parts whose datasheets now live on an excluded domain (e.g. Custom MMIC → qorvo.com, Hittite → analog.com) count as excluded.

### VENDOR CACHE — access knowledge for known manufacturers

This is a **cache**, not the source of truth for which vendors exist. The universe of vendors is defined by Path A (parametric aggregators) and Path B (part-graph traversal); this list's only job is to make access to an *already-known* vendor cheap and reliable — per-vendor access metadata (domain, catalog URL, parse/access notes, category hints). Path C sweeps it. Generic web search misses many of these (poor indexing), so checking their catalogs directly still matters — but absence here no longer means a vendor won't be found.

The cache is **self-growing** — no human maintains it:

- Whenever Path A or Path B discovers a vendor NOT listed here, append it with the access metadata learned (domain, catalog URL, parse/access notes, component categories).
- The cache MAY be seeded or refreshed from **everything.rf's Companies directory** for the relevant category.
- Not every vendor is relevant to every part type — use the category hints.

**MMIC / semiconductor:**
- Aelius Semiconductors — aeliussemi.com (amps: LNA, gain block, GaN power to 25W, X/Ku-band; catalog at products.php?slug=amplifiers; datasheets at /admin/uploads/<digits><PART>.pdf; ~118 amps; **poorly keyword-indexed — sweep the catalog directly**. Distributed via astramwp.com)
- Altum RF — altumrf.com (amps, X/Ku-band; also stocked at rellpower.com; **per-part datasheets are request-gated — use altumrf product pages + rellpower/expocad catalog PDFs for site-level specs**)
- BeRex — berex.com (amps, LNAs)
- CEL (California Eastern Labs) — cel.com (LNAs, discrete)
- Skyworks — skyworksinc.com (amps < ~6 GHz, switches, mixers)
- NXP — nxp.com (power, drivers)
- Wolfspeed — wolfspeed.com (GaN power)
- Ampleon — ampleon.com (power)
- Broadcom/Avago legacy MMICs — broadcom.com
- Mercury Systems / Atlanta Micro — mrcy.com (AM-series amps)

**Connectorized modules / hybrid amplifiers:**
- Ciao Wireless — ciaowireless.com (very broad amp catalog; catalog PDFs parse well)
- Narda-MITEQ (L3Harris) — nardamiteq.com (huge AMF amplifier catalog — poorly indexed, sweep directly. **Part numbers encode the spec**: `<TYPE>-<class>-<FminFmaxMHz>-<gain>-<P1dB>P` e.g. AMF30-12001800-60-30P = 12-18 GHz, 60 dB, +30 dBm P1dB — screen straight off the model number. LNA datasheets resolve at /docs/<MODEL>.PDF; AMF/medium-power per-part PDFs often behind viewmodel.php→"Contact Factory" and /docs guesses 404. Medium-power line OP1dB 26-33 dBm)
- Erzia — erzia.com
- B&Z Technologies — bnztech.com
- Planar Monolithics Industries (PMI / Quantic) — pmi-rf.com (broad PA catalog; power-amplifiers category lists guaranteed **min gain + Psat** but often **not OP1dB**; datasheet PDFs are **image-only/scanned** — Gemini runner returns "No text extracted", and the Richardson RFPD mirror 403s. For power parts OP1dB usually needs a factory request. Model encodes freq/gain/NF/Psat, e.g. PA-2G18G-43-5-40-SFF = 2-18 GHz, 43 dB, Psat 40 dBm/10W)
- Cernex / CernexWave — cernex.com
- Wenteq Microwave — wenteq.com (store.wenteq.com has per-part pages)
- Pasternack — pasternack.com (site bot-blocked; datasheets mirrored at resources.ampheo.com/static/datasheets/pasternack/<part>.pdf)
- Fairview Microwave — fairviewmicrowave.com
- Lotus Communication Systems — lotussys.com
- AML — amlj.com
- Elite RF — eliterfllc.com
- Triad RF — triadrf.com
- Spacek Labs — spaceklabs.com (mm-wave)
- Quantic brands (X-Microwave, PMI, Corry...) — catalog.xmicrowave.com

**Path A aggregators — the fixed, closed set (only these four; no other aggregators):**
- everything.rf — best RF-specific parametric DB; also mirrors specs of poorly-indexed vendors
- Mouser, Digi-Key — parametric filters for SMT/MMIC parts
- Octopart — cross-manufacturer part-search aggregator

This cache is the accumulated institutional knowledge of the search — Paths A and B grow it automatically over time.

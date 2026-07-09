---
name: rf-component-search
description: Parametric search for RF/microwave components (amplifiers, mixers, filters, switches, attenuators, couplers, etc.) against a multi-parameter spec, with 100%-reliable datasheet verification. Use whenever the user gives a component spec with electrical parameters (frequency range, gain, P1dB, OIP3, NF, insertion loss, isolation...) and wants matching parts — e.g. "מצא לי מגבר", "תחפש רכיב", "צריכה mixer", "find an amplifier 8-12 GHz gain 20dB", or pastes a spec line. Also use when the user asks to check "if there's anything on the market" matching parameters. The user searches AFTER already checking their 12 usual vendor sites, so those are always excluded — see the Vendor Lists section. Trigger even for short spec-only messages with no verb.
---

# RF Component Parametric Search

Find RF/microwave components that **fully match** a multi-parameter spec, and prove it. The user is an RF procurement/engineering professional. This task normally takes her days of manually opening result after result; the value you add is speed **without sacrificing reliability**. A false "match" that fails on one parameter wastes her time and erodes trust — a verified "no match found" is a perfectly good answer.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain, OP1dB, OIP3, NF, GHz, dBm) — that is how RF engineers read them.

## Workflow

### Step 1 — Parse the spec, then clarify ONCE before searching

Extract every parameter into a requirements table: name, value, direction (min/max/range), and whether it's hard or soft. Specs arrive as terse free text ("pidb 20 min, OIP3 30dbm, NF 6db max").

Ambiguities are the #1 source of wrong results. Before searching, ask the user (in one round, using the question tool if available) only about what is genuinely ambiguous:

- **Frequency**: must the part's band merely contain the requested range (usual), or match it exactly?
- **Two-sided ranges** (e.g. "gain 20-30dB"): is the upper bound hard (a part with 33dB is rejected) or advisory?
- **P1dB**: input or output? Default assumption for amplifiers is **output** (OP1dB) — state the assumption if the user is unsure.
- **min/typ/max**: do required values need to be guaranteed (min/max columns) or is typical acceptable?
- **Form factor**: MMIC/SMT, connectorized module, bare die — or anything?

Do NOT re-ask things already answered in the conversation, and don't ask about parameters that are already unambiguous. Known user defaults: band containment is fine; typical values acceptable; any form factor.

### Step 2 — Search wide (candidates), never trusting search snippets

Run multiple searches in parallel with varied phrasings: technology terms (MMIC, GaAs, GaN), form-factor terms (connectorized, coaxial module, SMT), band names (L/S/C/X/Ku/Ka-band), and distributor/parametric sites (everything.rf, Mouser, Digi-Key, RFMW, X-Microwave).

**Always exclude the user's 12 vendor domains** using blocked_domains — full list in the Vendor Lists section below. She already checked them; results from them are pure noise.

**Then sweep the vendor list.** Google indexing misses small RF vendors (proven in practice: Altum RF never appeared in generic searches, yet had a near-match part). The Vendor Lists section has a sweep list of known RF component manufacturers — for the relevant component category, check their catalogs directly (site search or catalog PDF fetch). This is what makes the search exhaustive rather than lucky.

If a catalog PDF fetch returns empty, it is probably a scanned/image PDF or bot-blocked — say so and try the vendor's HTML product pages or everything.rf's copy instead. Never silently skip a source.

### Step 2.5 — Second wave: derived searches

One good candidate is a thread to pull. After the first wave produces candidates, run derived searches before verifying:

- "alternatives to <part number>" / "<part number> equivalent" / "cross reference"
- Sibling parts in the same family (a vendor with an ARF1211 likely has ARF12xx neighbors — check the vendor's category page).
- everything.rf's "similar products" section on each candidate's page.
- Re-run the best query with the found parts' vocabulary (vendors describe the same thing differently: "driver amplifier" vs "gain block" vs "medium power amplifier").

Stop when a wave adds no new plausible candidates.

### Step 3 — Verify every candidate against primary sources

A candidate becomes a "match" only after every required parameter is confirmed from the **manufacturer's datasheet or catalog table** (fetch the actual PDF/product page). Distributor summaries and search snippets routinely show typ values at one frequency point, omit conditions, or are simply wrong.

**Snippets may promote, never reject.** A search snippet or distributor summary can only add a candidate to the datasheet-check queue — it can never remove one. Never reject a part on snippet evidence alone. If a snippet *suggests* a parameter fails but the value is borderline, the conditions are unstated, or the parameter is simply absent from the snippet, that part is a **plausible candidate** and its datasheet must be opened. The same reasons a snippet can't confirm a match (typ-at-one-frequency, missing conditions, plain errors) mean it can't be trusted to fail one either. A part is rejected only against an actual datasheet value. When the candidate pool (after the wide + derived waves) is small enough, open the datasheet for **every** candidate rather than pre-filtering on snippets — pre-filtering is a performance concession for large pools, not a license to drop a part cheaply.

For each parameter record: the actual value, whether it is min/typ/max, and any conditions (temperature, frequency point vs full band). Watch for:

- Specs guaranteed only at +25°C vs over temperature — note which.
- NF/gain specified at a single frequency vs across the band. The requested band must be inside the datasheet's specified range, not just the "operating" range.
- Column-header typos in catalogs (a "Min/Typ" header on a Noise Figure column almost certainly means Max/Typ — flag it rather than assume).
- Parameters listed as TBD or absent → the part is **unverifiable**, not a match. Say "requires manufacturer contact", never guess.

Record the **margin** per parameter (e.g. OIP3 required ≥30, actual +37 → margin +7dB). Margins let the user rank matches and see instantly which are comfortable vs marginal.

Verdicts: ✅ full match · ⚠️ borderline (meets spec but only as typ, or exactly at the limit, or one spec unverifiable) · ❌ rejected (state exactly which parameter fails and by how much).

### Step 3.5 — Independent re-verification (the trust layer)

Reading errors and confirmation bias are real: once a part "looks like a match", it is easy to misread a column. So before reporting, re-verify every ✅/⚠️ candidate **from scratch**. First determine which re-verification mode is available — subagent capability depends on the *runtime environment*, not the model: the same model may have it in an agentic/orchestration context and lack it in a plain chat interface. Do not assume it is present. State in the coverage statement which mode was used.

**Preferred — subagent mode (use whenever subagents are available):** spawn a verification agent that receives ONLY the requirements table and the list of candidate part numbers + datasheet URLs — **not** your conclusions, values, or verdicts — and independently extracts each parameter value into its own table. Compare its table to yours; any discrepancy → fetch the datasheet again and resolve explicitly. The separation is what makes this trustworthy: an agent that never saw your answer cannot rubber-stamp it.

**Fallback — hardened single-agent mode (when subagents are unavailable — likely the common case, including a strong model in a plain chat run):** a plain "read it again" is weak, because you remember what you concluded. So make the re-read mechanical and hard to fake:

1. Do NOT look at your first table while re-verifying. Re-fetch each datasheet in a fresh read and extract the values into a **blank** second table, quoting for every value the exact datasheet string plus its location (page / table / row heading, e.g. *"Gain 22 dB typ, p.3 'Electrical Specifications' table, 8–12 GHz row"*). A value with no locatable quote is **unverifiable**, not confirmed — downgrade it.
2. Only after the second table is complete, diff it against the first. Any mismatch → open the datasheet a third time and resolve explicitly; the quoted source wins over memory.
3. Because this mode is self-checking rather than independent, treat its confidence as lower: any ✅ that rests on a single ambiguous reading becomes ⚠️, and the coverage statement notes that re-verification was single-agent.

Sanity checks during re-verification, in **either** mode (violations = red flag, re-check the source):

- OIP3 is normally ~8–13dB above OP1dB for the same part. A datasheet where OIP3 < OP1dB was probably misread.
- NF below ~1dB for a non-cryogenic part above 6 GHz, or gain-per-stage above ~15dB/stage, deserve a second look.
- Distributor page disagrees with datasheet → the datasheet wins; note the discrepancy.

Only candidates that survive re-verification are reported as matches.

### Step 4 — Report: chat table + Excel

**Chat**: one table of matches/borderlines (part number, vendor, band, each required parameter with min/typ noted, verdict), followed by a short "checked and rejected" list — part, failing parameter, actual value. The rejected list is what convinces the user the search was real, and saves her re-checking those parts.

**Excel** (use the xlsx skill; RTL Hebrew — follow the hebrew-office-documents skill) — **three sheets, all mandatory, even when there is only one match or zero matches**:

1. **התאמות** — matches with all parameters and datasheet links.
2. **נבדקו ונפסלו** — every candidate that reached datasheet-check and failed, with the failing parameter and actual value.
3. **יומן כיסוי** — every search run and every sweep-list vendor checked, with its outcome. Use these outcome categories: checked/no candidates · checked/found X · not covered · **snippet-filtered (not datasheet-verified)** — a candidate dropped before its datasheet on snippet grounds, logged so a thorough search is distinguishable from one that pruned cheaply. Also record the re-verification mode used (subagent / single-agent).

Sheets 2–3 are not decoration — they ARE the product. A report with one match and no rejection/coverage record is unverifiable: the user cannot tell a thorough search from a lucky first hit, and she will re-check everything manually, losing the entire value of the skill. An empty sheet with a header row ("אף מועמד לא נפסל בשלב datasheet") is itself meaningful information.

**One-match warning**: finding only 0–1 matches after a real sweep is possible but suspicious. Before accepting it, go back to Step 2.5 and run at least one derived-search wave, and confirm the category-relevant sweep-list vendors were each actually checked. Only then report, and say explicitly in the coverage statement that this was done.

**End with an honest coverage statement**: which sources were fully swept, which were only sampled, whether "no match" means "none exists" or "none found in the sources covered", and which re-verification mode (subagent / single-agent) was used. Never imply exhaustiveness you don't have. If nothing matches, say so plainly and show the nearest misses with their exact gaps — a near-miss with a 2dB gap is actionable information (the user may relax the spec).

### Step 5 — Final audit before sending

Run this checklist; fix anything that fails before reporting:

- [ ] Every ✅/⚠️ part: every required parameter has an actual value, min/typ/max label, margin, and a working datasheet/catalog link.
- [ ] Every ✅/⚠️ part survived Step 3.5 re-verification, and the mode used (subagent / single-agent) is stated in the coverage statement.
- [ ] No part was rejected on snippet evidence alone — every ❌ rests on an actual datasheet value.
- [ ] Any candidate dropped before its datasheet on snippet grounds is logged in the coverage sheet as *snippet-filtered (not datasheet-verified)*.
- [ ] Every ❌ part has the specific failing parameter and its actual value.
- [ ] No part is from an excluded vendor (including legacy brands now hosted on excluded domains).
- [ ] Sweep-list vendors relevant to the component category were each either checked or listed as not-covered in the coverage statement.
- [ ] The clarifications from Step 1 are reflected (e.g. if the gain upper bound is hard, no match exceeds it).
- [ ] Numbers in the chat table match the Excel exactly.
- [ ] The Excel has all three sheets (התאמות / נבדקו ונפסלו / יומן כיסוי) — even if a sheet is empty apart from its header.
- [ ] If 0–1 matches: a derived-search wave (Step 2.5) was run and the coverage statement says so.

## Efficiency notes

- Phase searches: cheap wide search first, then datasheet fetches for candidates. "Plausible candidate" is deliberately inclusive — a snippet may only *promote* a part into the datasheet queue, never *drop* it (see Step 3). Pre-filtering on snippets is allowed only to prioritize fetch order and to cap an unmanageably large pool; when the pool is small, fetch every candidate's datasheet. When you do drop a candidate before its datasheet on pure snippet grounds, log it in the coverage sheet as *snippet-filtered (not datasheet-verified)*.
- If the user names a vendor missing from the lists below, add it to the sweep for the rest of the session and suggest permanently updating this skill.

## Vendor Lists

### ALWAYS EXCLUDE — the user's 12 pre-checked sites

The user checks these manually before every search. Pass all of them in blocked_domains on every web search, and never present parts from them:

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

### SWEEP LIST — manufacturers to check directly

Generic web search misses many of these (poor indexing). For the relevant component category, check catalogs/site search directly. Not every vendor is relevant to every part type — use the category hints.

**MMIC / semiconductor:**
- Altum RF — altumrf.com (amps, X/Ku-band; also stocked at rellpower.com)
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
- Narda-MITEQ (L3Harris) — nardamiteq.com (huge AMF amplifier catalog — poorly indexed, sweep directly)
- Erzia — erzia.com
- B&Z Technologies — bnztech.com
- Planar Monolithics Industries (PMI) — pmi-rf.com
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

**Parametric search engines / distributors (search these too, not just Google):**
- everything.rf — best RF-specific parametric DB; also mirrors specs of poorly-indexed vendors
- Mouser, Digi-Key — parametric filters for SMT/MMIC parts
- RFMW — rfmw.com — RF-specialist distributor
- Richardson Electronics — rellpower.com (Altum RF and others)

These lists are the accumulated institutional knowledge of the search — they should grow over time.

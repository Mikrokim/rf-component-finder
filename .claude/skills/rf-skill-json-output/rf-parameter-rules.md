# Parameter Handling Rules (general, component-agnostic)

Reference file for the RF Component Parametric Search skill. `SKILL.md` owns the workflow, report format, and vendor lists; this file supplies **only** the rules for how any parameter is handled, independent of component type. The concrete list of searchable parameters for a given component type — their units, directions, formulas, and sanity checks — lives in that component's own module (e.g. the amplifier module), not here.

## How parameters work

**Only parameters defined in the loaded component module may be used as search filters.** If the user's spec contains an electrical term that is not in that module's dictionary, ask about it in the Step 1 clarification round — never improvise a filter from an undefined parameter. Parameters the user did NOT specify are ignored entirely: a datasheet may or may not mention them, and it makes no difference either way.

**Every parameter the user gives a value for must appear, with a value, on the result's datasheet.** This is the core suitability rule: *whenever the user enters a value for a parameter, a suitable part must state that parameter somewhere on its manufacturer datasheet.* If the parameter is nowhere on the datasheet, and cannot be derived by calculation from values the datasheet does state, the part is **unsuitable** — send it to the rejected sheet with the reason "parameter not stated in datasheet". This applies only to parameters the user actually entered a value for. A distributor page that omits the parameter is irrelevant; only the datasheet counts as source of truth.

This rule is about a datasheet that was *read* and does not state the parameter — distinct from a datasheet that could not be *fetched* at all (bot-block / not indexed). A datasheet that is inaccessible after all alternative sources are exhausted is handled by the engine's Step 3 "datasheet cannot be fetched" rule, not here: such a part may still be reported as a ⚠️ not-datasheet-verified match when every specified parameter is site-checkable and clears the spec, and is otherwise an access-blocked *unverifiable* reject ("consider contacting the manufacturer") — never labelled "parameter not stated in datasheet".

**Comparison semantics** — each parameter in a component module declares a direction (`min`, `max`, or `contains`). Apply it *after* converting the datasheet value to the module's canonical unit:

- `min` — the user's value is a **floor**. The datasheet value must be **≥** the user's value.
- `max` — the user's value is a **ceiling**. The datasheet value must be **≤** the user's value (it must not exceed it; equal is allowed).
- `contains` — the part's stated range must **fully contain** the user's requested range or value. Use the datasheet's *specified* range, not merely the "operating" range.

**Which column to compare against (min/max, not typ):** compare against the *guaranteed* column that matches the direction — the datasheet **min** column for `min` parameters, the **max** column for `max` parameters. Use the **typ** column **only** when no guaranteed min/max column exists for that parameter, and when you do, mark the verdict ⚠️ with a "typ only" note.

**Conversions and derived values:**

- Unit conversions are mandatory and must be **shown explicitly** in the output, e.g. `2 W → +33.0 dBm; required ≥ +30 dBm; margin +3.0 dB`. A silent conversion is exactly where a reading error hides, so every conversion is visible.
- If a specified parameter is not stated directly but *is* computable from values the datasheet does state (using a formula defined in the component module), do the calculation, show it, and treat the result as typ-grade (⚠️) unless every input to the calculation is itself a guaranteed min/max value.

**Sanity checks** are component-specific physics and live in the loaded component module, not here. Apply that module's sanity checks during verification and re-verification; a violation is a red flag to re-read the source.

## Where each parameter is checked (site screen vs datasheet)

The engine runs a two-stage filter: a cheap **Step 2.7 site screen** on data the sites expose, then **Step 3 datasheet verification** on the survivors. Each parameter in a component module is classified by *where it can be reliably checked*:

- **site-checkable** — shown or filterable on parametric sites and catalog tables reliably enough to screen on.
- **datasheet-only** — reliably found only on the manufacturer datasheet; never screened at Stage 1, always confirmed at Step 3.

Each component module declares this classification per parameter, and — for site-checkable parameters — a **guard band `G`** (a screening tolerance).

**How the Stage-1 site screen decides:**

- Consider only the parameters the user actually specified that the module marks **site-checkable**. On each site, use only those the site itself exposes or filters on.
- A site-checkable parameter **matches** when the site value satisfies the parameter's direction (`min`/`max`/`contains`) within its guard band `G` — the tolerance absorbs the typ-vs-guaranteed spread and unstated conditions that make raw site values untrustworthy:
  - `min` (need ≥ target): matches unless `site_value < target − G`.
  - `max` (need ≤ target): matches unless `site_value > target + G`.
  - `contains`: the site's listed range must contain the request; reject only if it clearly cannot.
- A candidate **passes** the screen when every site-exposed, site-checkable, user-specified parameter matches — a complete match on what the site can show. It then advances to Step 3.
- **Never reject at Stage 1** on: a parameter the user did not specify (treated as a match), a datasheet-only parameter, a site-checkable parameter the current site does not expose (that site can't screen it → promote), or a value within its guard band (borderline → promote).

The guard band is a screening tolerance only — it never relaxes the Step 3 datasheet comparison, which still applies the exact `min`/`max`/`contains` semantics against the guaranteed column.

**Two Stage-1 outcomes — never conflated:**

- **rejected at site screen** — the part *failed* a site-exposed parameter (or a catalog fact ruled it out). A clean, definitive rejection on a real discrepancy: log it with the failing parameter and its site value. Do **not** tag it "not datasheet-verified" — there was no reason to open the datasheet of a part that already failed on the site, so its unopened datasheet is not a gap and nothing the report owes the user.
- **not datasheet-verified** — reserved for the opposite case: a part that *passed* every specified site-checkable parameter at 100% (satisfying the spec clear of the guard band, not merely inside it) but whose datasheet was **not** checked — in practice the access-blocked ⚠️ match of Step 3. The only outcome that carries this flag, because it is the only one where a genuinely-promising part was left unverified.

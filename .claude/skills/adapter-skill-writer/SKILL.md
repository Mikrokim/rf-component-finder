---
name: adapter-skill-writer
description: >-
  Use this when a new manufacturer adapter has been written (or substantially
  changed), or when the user asks to "document this adapter", "create the skill
  for <vendor>", or "capture how <site> works". It generates the per-site
  retrieval skill (.claude/skills/<vendor>/SKILL.md) for an rf_finder adapter,
  following the project's established template. The canonical examples to match
  are the macom and minicircuits skills. Goal: capture each site's retrieval
  know-how (method, gotchas, spec mapping, compliance) plus a forward-looking
  expansion guide, so nobody has to re-investigate the site later.
---

# Adapter Skill Writer

This skill produces a **per-site retrieval skill** for a `rf_finder` manufacturer
adapter. Each generated skill is the durable "operating manual" for one
manufacturer's website: how to retrieve from it correctly, everything that was
learned building the adapter, and how to extend it to new component types.

**Canonical examples to match exactly** (read them before generating — they are
the template, the bar, and the house style):
- [macom skill](../macom/SKILL.md) — a *client-rendered* site (embedded `data-part` JSON).
- [minicircuits skill](../minicircuits/SKILL.md) — a *server-rendered* site (`table#maintable`).

These two cover the two retrieval shapes you'll usually meet. Pick whichever is
closer to the new site and adapt.

---

## When to invoke

- A new adapter file was just created under `rf_finder/adapters/`.
- An existing adapter gained a new component type or a materially new behavior.
- The user explicitly asks to document/capture an adapter or site.

Do **not** invoke for unrelated docs, or to edit core code.

---

## Step 1 — Gather the source material (read, don't guess)

Read these before writing a single line. Every claim in the skill must be
traceable to one of them — **never invent site behavior.**

1. **The adapter itself** — `rf_finder/adapters/<vendor>.py`. This is ground
   truth for what the code *actually does*: URL(s), headers, User-Agent, rate
   limit, the parse method, the spec/column map, error handling, `source` tag.
2. **The investigation / plan doc**, if one exists — e.g.
   `specs/.../iteration*/<vendor>-plan.md`. This is ground truth for *why*: the
   REQ-3.3 decision trail (API? parametric URL? scrape?), robots.txt, page size,
   row counts, coverage %, risks, open questions.
3. **The architecture contracts** —
   [base.py](../../../rf_finder/adapters/base.py) (`Adapter` ABC, `AdapterError`,
   `@register`/`ADAPTERS`) and [models.py](../../../rf_finder/models.py)
   (`Candidate`, `RawValue`, `QuerySpec`).
4. **The ontology** — [components.py](../../../rf_finder/ontology/components.py)
   and the parameter ontology, to state which canonical params/units the map
   targets.
5. **The tests & fixture** — `tests/adapters/test_<vendor>.py` and the fixture in
   `tests/fixtures/`, to describe the offline test approach accurately.
6. **The project open-questions register** —
   [open-questions.md](../../../specs/rf-component-finder/open-questions.md) — for
   any OQ-* items that belong to this adapter, with current status.

If the adapter has no plan doc, reconstruct the investigation findings *from the
code and docstrings only*, and explicitly note what is unverified rather than
asserting it.

---

## Step 2 — Write the skill (required structure)

Create `.claude/skills/<vendor>/SKILL.md`. Use a short, lowercase `<vendor>`
slug (e.g. `macom`, `minicircuits`, `analog-devices`). Frontmatter:

```yaml
---
name: <vendor-slug>
description: >-
  Complete retrieval guide for <domain> (<Manufacturer>). Use whenever you work
  on the <vendor> adapter (rf_finder/adapters/<vendor>.py) — to understand how
  the site serves product data, to debug/maintain the adapter, or (the main
  forward-looking use) to ADD A NEW COMPONENT TYPE beyond <current types>.
  Covers the retrieval method, compliance, parsing gotchas, the spec→ontology
  mapping, what was already built, and a step-by-step expansion recipe.
---
```

Body sections (mirror the macom/minicircuits skills — same order, same spirit):

1. **TL;DR — the one defining fact.** The single sentence that captures how this
   site differs (e.g. "data is server-rendered table cells" vs "data hides in a
   `data-part` JSON attribute, not the rendered DOM"). State the full
   fetch→parse path in 2–3 lines.
2. **How the site serves product data (investigation findings).** A table with
   the REQ-3.3 trail: official API? server-side parametric filter? is the data in
   the raw HTML and *where*? is JS required to see it? entry URL, load method,
   response size, row count, front-end stack. Each row: finding + consequence.
3. **Compliance & access.** robots.txt directives that matter (Allow/Disallow,
   Crawl-delay, any Content-Signal), CDN/Cloudflare behavior, the User-Agent
   decision and *why*, and any disallowed URL that is used display-only and never
   fetched.
4. **The retrieval recipe (`search()`).** Exact constants (URL(s), UA, delay),
   the rate-limit guard, request headers/timeout/redirects, `raise_for_status`,
   and the `AdapterError(manufacturer, context, cause)` wrapping rule. Note the
   rate-limit/cache strategy (NFR-6).
5. **The parsing recipe (`_parse_html()`).** The exact extraction (regex /
   selector), the **fail-loudly tripwire** when the anchor element/blob is absent
   (→ `AdapterError`), and every robustness rule (e.g. `strict=False`,
   skip-bad-row-don't-abort, missing sentinels, special-value handling).
6. **From source row to `Candidate`.** The field→`Candidate` mapping table, how
   `model`/`url`/`raw_params`/`source` are built, plus the **architecture fit**:
   no query-side filtering (return all; the Verifier filters), `@register`
   self-registration, `supported_components`.
7. **Spec → canonical ontology mapping.** The actual `SPEC_MAP`/`COLUMN_MAP`,
   synonym handling, frequency combining into `freq_range`, the "distrust the
   noisy source unit; trust the ontology canonical unit" rule, and observed
   coverage % per param if known.
8. **Gotchas & risks.** A numbered table (R1, R2, …) of every quirk and its
   applied mitigation — carry these forward to new categories.
9. **Open questions.** This adapter's OQ-* items with current status and the
   recommendation, linked to the register.
10. **EXPANSION GUIDE — adding a new component type.** The forward-looking
    payload. A numbered recipe: register the type in the ontology; find the new
    category's listing URL (state the site's URL pattern); **verify the data
    source is the same pattern** (and what to do if it isn't — re-investigate per
    REQ-3.3); aggregate the category's spec/column names + coverage; build a
    category-specific map; **parameterize the adapter rather than fork it**
    (per-category `{component_type: (URL, MAP)}` table selected by
    `spec.component_type`); carry the gotchas forward; test offline with a trimmed
    fixture; and **update the skill** with the new findings.
11. **File map.** A table linking the adapter, base.py, models.py, ontology,
    tests, fixture, and the plan doc — all relative markdown links.

---

## Step 3 — Quality bar (check before finishing)

- [ ] **Faithful to the code.** Every constant, rule, and gotcha matches the
      actual adapter. If code and plan doc disagree, the **code wins** and note
      the discrepancy.
- [ ] **No invented site behavior.** Anything not verifiable from the sources is
      flagged as unverified, not asserted.
- [ ] **The expansion guide is concrete**, not generic — it names this site's URL
      pattern and reuses *this* adapter's machinery.
- [ ] **Maps are name-based**, and the skill says so (robustness to reordering).
- [ ] **Architecture invariants are stated**: return-all + Verifier-filters,
      `@register`, `AdapterError` on failure, display-only `url`.
- [ ] **All links are relative** and resolve from
      `.claude/skills/<vendor>/SKILL.md` (core files are `../../../...`; sibling
      skills are `../<other>/SKILL.md`).
- [ ] **Frontmatter description** makes the skill auto-surface for both
      maintenance *and* the "add a new component type" use.

---

## Notes

- This skill writes *documentation*, not code. It does not modify the adapter,
  core files, or the ontology.
- "Every time" automation: a skill fires on intent/relevance, not as a guaranteed
  post-write trigger. If you want an automatic nudge whenever an
  `adapters/*.py` file is created, that belongs in a `settings.json` hook (use the
  update-config skill); this skill then does the actual authoring when invoked.
- After generating a new skill, consider cross-linking it from the closest
  existing example (the "contrast with …" line) so the two retrieval shapes stay
  discoverable.

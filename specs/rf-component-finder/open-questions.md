# Open Questions — RF Component Finder

> **Project-wide register.** Single source of truth for **active** open questions
> across all iterations. When a question is raised in a spec/plan, add it here and
> reference it by ID from that document.
>
> **Status legend:**
>
> | Status | Meaning | Stays in this file? |
> |--------|---------|---------------------|
> | 🟡 Open | Raised, not yet being worked on. | Yes |
> | 🔵 Investigating | Actively being researched / decided. | Yes |
> | 🟢 Resolved | A decision was made. | No — remove from this file; capture the decision in the relevant spec. |
> | ⚪ Deferred | Valid, but intentionally postponed to a future iteration. | No — remove from this file; note the deferral in the relevant spec. |
>
> **Lifecycle:** A question lives here while 🟡 Open or 🔵 Investigating. When it
> becomes 🟢 Resolved or ⚪ Deferred, record the outcome in the owning spec/plan,
> then remove it from this register so this file only ever shows active questions.

> **Note (2026-06-24):** Entries below were consolidated from
> `iteration1/requirements.md §8` and `iteration1/t8-plan.md §9`, whose original
> per-document IDs collided (two different "OQ-1"/"OQ-2"). They are renumbered into
> this single namespace — see the "Origin" column. The source documents have **not**
> been edited yet.

---

## Register

| ID | Question | Status | Raised in | Origin | Notes |
|----|----------|--------|-----------|--------|-------|
| OQ-1 | What is the full list of 10 manufacturers? | 🟡 Open | requirements §1, §8 | requirements OQ-1 | Pending; does not block iteration 1. |
| OQ-2 | Should `Candidate.url` be the (robots-disallowed) `modelSearch.html?model=XXX` URL, or the allowed `Amplifiers.html` page? | 🟡 Open | t8-plan §9 | t8-plan OQ-1 | Recommended: model-specific URL for report value, with a note that the adapter never fetches it. Needs implementer sign-off. |
| OQ-3 | Should the adapter log a warning when the page row count changes significantly between runs (possible site redesign)? | 🟡 Open | t8-plan §9 | t8-plan OQ-2 | Recommended: yes — warn if row count deviates > 20% from the cached count. |
| OQ-4 | Even when a field value is *valid*, should we sanity-check it and warn the user it may be a mistake? | 🟡 Open | (new) | — | — |

---

## Details

### OQ-1 — Full manufacturer list
**Question:** What are the 10 manufacturers the full system must support?
**Why it matters:** Drives the adapter roadmap, but iteration 1 only targets
Mini-Circuits, so this does not block current work.

### OQ-2 — `Candidate.url` value choice
**Question:** Should `Candidate.url` be the disallowed `modelSearch.html?model=XXX`
URL (more useful in the report) or the allowed `Amplifiers.html` page?
**Why it matters:** robots.txt technically disallows `modelSearch.html`. The
adapter populates the URL for **display only** and never fetches it.
**Recommendation:** Use the model-specific URL for user value in the report, with a
docstring note that it is never fetched. If strict policy is required, fall back to
`Amplifiers.html`. Needs implementer sign-off.

### OQ-3 — Warn on row-count drift
**Question:** Should the adapter log a warning when the scraped row count changes
significantly between runs?
**Why it matters:** A large change can signal a site redesign that breaks scraping.
**Recommendation:** Yes — log a warning if the row count deviates > 20% from the
cached count.

### OQ-4 — Sanity-check valid-but-suspicious user input
**Question:** Even when a field value passes validation (it is a *valid* value),
should the tool warn the user that it may be a mistake — e.g. P1dB entered in W
instead of dBm, or a frequency off by a factor of 10?
**Why it matters:** Affects the Form Input UX and the `QuerySpec` validation layer.
A purely valid/invalid check won't catch plausible-but-wrong entries, which are an
easy way for a user to get confidently wrong results.
**Options:**
- (a) None — only validate hard validity.
- (b) Range-based "unusual value" warning — flag values outside a typical range for
  the parameter (non-blocking, user can confirm).
- (c) Unit-aware confirmation — detect likely unit confusion and prompt to confirm.
**Decision needed by:** before the Form Input design is frozen.

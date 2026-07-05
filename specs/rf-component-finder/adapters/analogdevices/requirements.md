# Requirements — Analog Devices Adapter

> Manufacturer-specific spec. The generic **Site Adapter** requirements (REQ-3)
> and all general behavior live in
> [../../iteration1/requirements.md](../../iteration1/requirements.md).
> This file holds **only** what is unique to Analog Devices.

---

## Assumptions

- **ADI-A-1** — The Analog Devices parametric data is served as a single JSON
  document at `/cdp/pst2/data/standard/{catId}.js` (RF Amplifiers = catId 3003),
  returning the full dataset with no server-side filtering.
- **ADI-A-2** — The field-id → ontology mapping is stable across responses
  (`0`→model, `279`/`278`→freq_range, `2930`→P1dB, `2922`→IP3, `2913`→Gain,
  `2921`→NF, `4709`→Psat).

## Open Questions

- **ADI-OQ-1** — Is the `catId` (3003) stable, or can ADI reassign it and break
  the endpoint URL?
- **ADI-OQ-2** — Are the numeric field-ids guaranteed stable, or should the
  adapter resolve them from view metadata at runtime instead of hard-coding?

## Definition of Done

- The system returns real candidates from Analog Devices.

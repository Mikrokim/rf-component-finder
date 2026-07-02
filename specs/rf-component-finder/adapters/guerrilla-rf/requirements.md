# Requirements — Guerrilla RF Adapter

> Manufacturer-specific spec. The generic **Site Adapter** requirements (REQ-3)
> and all general behavior live in
> [../../iteration1/requirements.md](../../iteration1/requirements.md).
> This file holds **only** what is unique to Guerrilla RF.

---

## Assumptions

- **GRF-A-1** — The full amplifier list is served as a single server-rendered HTML
  page at `/products/amplifiers.html` (under robots.txt `Allow: /`) holding two
  tables: `table#genericAmpFunctionTbl` (LNAs/gain blocks) and `table#satPATbl`
  (saturated power amps). Columns include Min/Max Freq (GHz), Gain, NF, OP1dB,
  OIP3, Psat, and **Vdd Range (V)**.
- **GRF-A-2** — Min/Max Freq are GHz; `Vdd Range` is a `"low-high"` string;
  scalar cells are typical values; empty string `""` means "not specified". The
  data is in the raw HTML (a DataTables JS lib only wraps the tables at runtime).

## Open Questions

- **GRF-OQ-1** — Are Min/Max Freq always GHz (headers say `(GHz)`)?
- **GRF-OQ-2** — **MSL, Temperature, and exact Size are not on the page** — only
  in the datasheet PDF (`Package (mm)` is an approximate package label, not a
  clean dimension). Their enrichment is owned by the datasheet fallback, not this
  adapter — see [t8-plan.md](t8-plan.md) §5. (VDD **is** on the page and is mapped
  by this adapter.)

## Definition of Done

- The system returns real amplifier candidates from Guerrilla RF (category-filtered
  to amplifier types).

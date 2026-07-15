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
- **GRF-A-3** — The datasheet link Guerrilla RF exposes is a **viewer wrapper**,
  not the PDF: `/products/DataSheet?sku={SKU}&file_name={FILE}` (equivalently
  `?prodPath={SKU}&…`) returns `Content-Type: text/html` — an HTML page that
  *embeds* the real PDF via `<embed src="…/includes/prodFiles/{SKU}/{FILE}">`.
  The actual PDF is served directly at
  `https://www.guerrilla-rf.com/includes/prodFiles/{SKU}/{FILE}`
  (`Content-Type: application/pdf`, `%PDF` signature). Verified live 2026-07-15
  for `sku=5604`, `file_name=GRF5604DS.pdf` →
  `/includes/prodFiles/5604/GRF5604DS.pdf`.

## Open Questions

- **GRF-OQ-1** — Are Min/Max Freq always GHz (headers say `(GHz)`)?
- **GRF-OQ-2** — **MSL, Temperature, and exact Size are not on the page** — only
  in the datasheet PDF (`Package (mm)` is an approximate package label, not a
  clean dimension). Their enrichment is owned by the datasheet fallback, not this
  adapter — see [t8-plan.md](t8-plan.md) §5. (VDD **is** on the page and is mapped
  by this adapter.)

## Datasheet Retrieval

> Owns the Guerrilla-specific step of turning a datasheet link into fetchable PDF
> bytes for the datasheet fallback (Size, MSL, Temperature — see GRF-OQ-2). The
> generic "download a datasheet PDF by URL" behavior lives in
> `rf_finder/datasheet/pdf.py`.

- **GRF-DS-1** — Because Guerrilla RF's datasheet link is a viewer-wrapper HTML
  page (GRF-A-3), the datasheet URL MUST be resolved to the **direct PDF URL**
  before it is handed to the datasheet-text fetch. Resolution derives
  `https://www.guerrilla-rf.com/includes/prodFiles/{SKU}/{FILE}` from the wrapper's
  `sku`/`prodPath` and `file_name` query parameters (equivalently: read the
  `<embed>`/`<iframe>` `src` out of the wrapper HTML). Passing the raw
  `/products/DataSheet?…` URL straight to `datasheet_text_from_url` fails with
  `DatasheetFetchError` ("response is not a PDF (Content-Type: 'text/html…')"),
  because the wrapper is HTML, not a PDF.

## Definition of Done

- The system returns real amplifier candidates from Guerrilla RF (category-filtered
  to amplifier types).
- A Guerrilla RF datasheet link resolves to its direct
  `/includes/prodFiles/{SKU}/{FILE}` PDF URL (GRF-DS-1) so datasheet enrichment
  (Size/MSL/Temperature) can read the PDF instead of failing on the HTML wrapper.

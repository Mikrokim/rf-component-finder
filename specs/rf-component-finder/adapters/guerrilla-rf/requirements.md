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
- **GRF-A-3** — Guerrilla RF publishes each datasheet under **two** URLs. The
  **viewer wrapper** `/products/DataSheet?sku={SKU}&file_name={FILE}` (equivalently
  `?prodPath={SKU}&…`) returns `Content-Type: text/html` — an HTML page that merely
  *embeds* the PDF via `<embed src="…/includes/prodFiles/{SKU}/{FILE}">`. The
  **direct PDF** is served at
  `https://www.guerrilla-rf.com/includes/prodFiles/{SKU}/{FILE}`
  (`Content-Type: application/pdf`, `%PDF` signature). Verified live 2026-07-15 for
  `sku=5604`; re-verified 2026-07-16 by fetching both:
  `/includes/prodFiles/2003/GRF2003DS.pdf` → 200, `application/pdf`, 1.34 MB, `%PDF-`;
  its wrapper → 200, `text/html`, 54 KB, `<!DO…`.

- **GRF-A-4** — **The datasheet link is not in the results tables.** The amplifier
  page carries every parameter the adapter maps as table cells, but **zero**
  datasheet references: no `DataSheet?`, no `.pdf` and no `prodFiles` occurrence
  anywhere in the page, and no datasheet column among its headers (Product, Min/Max
  Freq, Gain, NF, OP1dB, OIP3, Reference Conditions, Vdd Range, Idd Range, Features,
  Package (mm), Description, Parametric Charts). Unlike every other parameter, the
  link cannot be read from the page already fetched.

- **GRF-A-5** — **The per-part product page carries the link.** Each table row links
  to `https://www.guerrilla-rf.com/products/detail/sku/{MODEL}` (e.g.
  `/products/detail/sku/GRF2003`) — already the adapter's `_DETAIL_URL` and the value
  it puts in `Candidate.url`.

- **GRF-A-6** — **The direct PDF link is present on every product page**, alongside
  the wrapper. Verified 2026-07-16 over a 12-model sample spanning both tables
  (GRF2003, GRF2051, GRF2082, GRF2110, GRF2201, GRF3016, GRF4015, GRF5226, GRF5526,
  GRF5613, GRF9297, GRF0030): **12/12 carried a direct
  `/includes/prodFiles/{SKU}/{MODEL}DS.pdf` anchor, 0 were wrapper-only.** Three
  fetched at random returned 200 / `application/pdf` / ~1.2–1.3 MB / `%PDF-`.

- **GRF-A-7** — **The page serves both links and switches on viewport.** They sit
  side by side in the markup, separated only by Bootstrap responsive classes:

  ```html
  <a href=".../includes/prodFiles/5604/GRF5604DS.pdf" class="d-md-none">        <!-- mobile  -->
  <a href=".../products/DataSheet?sku=5604&file_name=GRF5604DS.pdf"
     class="d-none d-md-block">                                                  <!-- desktop -->
  ```

  `d-md-none` hides at ≥md, so the **direct PDF is the mobile variant**;
  `d-none d-md-block` hides at <md, so the **wrapper is the desktop variant**. A human
  on a desktop therefore sees only the wrapper — which is why the site *appears* to
  offer a single, HTML, datasheet link.

  **This does not affect the adapter.** The switch is pure CSS: the server returns the
  same HTML to everyone, containing both anchors, and `httpx` has no viewport. A
  parser sees both, always.

  The pair occurs twice — in the header button (`div.fbox-icon`, both anchors with
  empty text) and in the **Documents** tab's `div.list-group` (inside `div#tabs-2`,
  `style="display:none"` until the tab is clicked, both anchors texted "Data Sheet")
  — plus a third, bare occurrence of the direct URL inside a `<details>` block in the
  FAQ section.

- **GRF-A-8** — **Neither anchor text, class, nor file extension distinguishes the
  two.** In the Documents tab both are `<a class="list-group-item" target="_blank">`
  whose text is exactly `"Data Sheet"`, with the same `icon-file-pdf` span. And both
  URLs **end in `.pdf`** — the wrapper's trailing `file_name=GRF5604DS.pdf` sees to
  that — while one is HTML and one is a PDF (GRF-A-3). Only the **href path**
  discriminates.

- **GRF-A-9** — **The detail URL uses the model name; the file paths use a numeric
  SKU** (`/products/detail/sku/GRF2003` → `/includes/prodFiles/2003/…`).

- **GRF-A-10** — **The detail page holds many other PDFs** — application notes
  (`/includes/prodFiles/AppNotes/…`), material declarations, MTTF reports, Gerber
  zips, and per-tune datasheets (`GRF2003 1000-5000 MHz.pdf`). "The first `.pdf`", or
  any `/includes/prodFiles/` link, would grab the wrong document.

- **GRF-A-11** — robots.txt permits the whole flow: no rule matches
  `/products/detail/`, and `/includes/` is **explicitly not blocked** — its comment
  states that datasheets there "should be discoverable". `ClaudeBot` and peers are
  granted `Allow: /`; the `*` policy blocks only CFML internals and `/api/`.

## Open Questions

- **GRF-OQ-1** — Are Min/Max Freq always GHz (headers say `(GHz)`)?
- **GRF-OQ-2** — **MSL, Temperature, and exact Size are not on the page** — only
  in the datasheet PDF (`Package (mm)` is an approximate package label, not a
  clean dimension). Their enrichment is owned by the datasheet fallback, not this
  adapter — see [t8-plan.md](t8-plan.md) §5. (VDD **is** on the page and is mapped
  by this adapter.)
- **GRF-OQ-3** — GRF-A-6 is 12/12 on a sample, not a proof over all 159 parts. A part
  whose page omits the mobile (direct) variant is covered by GRF-DS-3's fallback; a
  part whose wrapper parameters do not reconstruct its direct URL is surfaced by
  GRF-DS-3's cross-check.

## Datasheet Retrieval

> Owns the Guerrilla-specific step of finding a part's datasheet and turning it into
> fetchable PDF bytes for the datasheet fallback (Size, MSL, Temperature — see
> GRF-OQ-2). The generic "download a datasheet PDF by URL" behavior lives in
> `rf_finder/datasheet/pdf.py`.

- **GRF-DS-1** — Because the datasheet link is published in neither the same place
  nor the same form as the parameters the adapter scrapes (GRF-A-4), the adapter
  SHALL obtain it from **the part's own product page** (GRF-A-5) and return it as an
  absolute URL.

- **GRF-DS-2** — The URL returned SHALL be the **direct PDF**
  (`/includes/prodFiles/{SKU}/{FILE}`), never the `/products/DataSheet?…` wrapper:
  the wrapper is HTML, not a PDF (GRF-A-3), so `datasheet_text_from_url` rejects it
  with `DatasheetFetchError` ("response is not a PDF (Content-Type: 'text/html…')").
  It SHALL be identified by **anchor text `"Data Sheet"` plus an href path containing
  `/includes/prodFiles/`** — text alone does not separate it from the wrapper, and
  path alone does not separate it from the page's other documents (GRF-A-8, GRF-A-10).
  Verified to select correctly on 12/12 sampled parts (GRF-A-6).

- **GRF-DS-3** — Resolution SHALL read that direct link off the detail page, and
  SHALL fall back to **deriving** it from the wrapper's `sku`/`prodPath` and
  `file_name` query parameters (→ `/includes/prodFiles/{SKU}/{FILE}`) if no direct
  anchor is present. Both cost **no extra request** — the detail page is already
  fetched — and they fail independently: reading breaks if the mobile variant is
  dropped, deriving breaks if the path template changes. When both are available they
  SHALL agree; a mismatch means the site changed and is a free tripwire (GRF-OQ-3).

  Deriving is a substitution, not a guess: `sku` and `file_name` are both supplied by
  the site in the wrapper's own href, and only the path template is assumed — unlike
  a filename inferred from a model name.

  Resolution SHALL NOT fetch the wrapper page to read its `<embed>`/`<iframe>` `src`.
  That spends one extra request (54 KB) per candidate to recover `sku` and `file_name`
  that are already present in the wrapper's href.

- **GRF-DS-4** — Resolution SHALL NOT happen during `search()`. The tables list all
  159 amplifiers Guerrilla RF sells, so a detail-page fetch per row would cost one
  request per catalogue row at the adapter's 2 s guard, to obtain links only the few
  surviving candidates ever need. `search()` therefore leaves `datasheet_url` as
  `None`, and the adapter resolves the link **on demand, one candidate at a time**,
  when the pipeline asks.

- **GRF-DS-5** — Resolution SHALL be resilient: a detail page that fails to fetch, or
  that yields neither a direct link nor a derivable wrapper, gives `None` rather than
  raising. The part stays a valid candidate whose datasheet simply could not be read.

- **GRF-DS-6** — The existing rate guard (`_MIN_DELAY_SECONDS = 2.0`) and browser
  User-Agent SHALL apply to detail-page fetches as they do to the table fetch.

## Definition of Done

- The system returns real amplifier candidates from Guerrilla RF (category-filtered
  to amplifier types).
- A candidate's datasheet link is resolved from its product page when the pipeline
  needs it (GRF-DS-1), as the direct `/includes/prodFiles/{SKU}/{FILE}` PDF URL
  (GRF-DS-2/DS-3) so datasheet enrichment (Size/MSL/Temperature) reads the PDF
  instead of failing on the HTML wrapper — with `search()` making no per-part
  request (GRF-DS-4).

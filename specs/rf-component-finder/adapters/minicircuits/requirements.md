# Requirements — Mini-Circuits Adapter

> Manufacturer-specific spec. The generic **Site Adapter** requirements (REQ-3)
> and all general behavior live in
> [../../iteration1/requirements.md](../../iteration1/requirements.md).
> This file holds **only** what is unique to Mini-Circuits.

---

## Assumptions

- **MC-A-1** — The Mini-Circuits site has an accessible search path
  (API / parametric / table). *(was A-2)*

- **MC-A-2** — **The datasheet link is not in the results table.** Every parameter
  the adapter maps (freq low/high, Gain, NF, P1dB, Psat, OIP3, VDD) is a `<td>` of
  the part's `table#maintable` row, but nothing in that row links to a datasheet:
  the whole 3.8 MB page holds only 3 `.pdf` references, all site-wide boilerplate
  (the patent guide), none per-part. `Amplifiers_tab2.html` and
  `products/Amplifiers_tab3.html` likewise carry zero per-part `/pdfs/` links, and
  "Export to Excel" is a server-side action mirroring the visible columns. So unlike
  every other parameter, the link cannot be read from the page already fetched, and
  no bulk source supplies it.

- **MC-A-3** — **The per-part product page carries the link.**
  `https://www.minicircuits.com/WebStore/dashboard.html?model=<MODEL>` is
  server-rendered and holds an `<a>` whose text is `DATASHEET`, pointing at
  `/pdfs/<FILE>.pdf`. The path is robots-allowed and published in the site's
  `sitemap.xml` (15,404 WebStore URLs).

- **MC-A-4** — **The table's own product link is robots-disallowed.** Each row's
  `<a href>` is `modelSearch.html?model=<MODEL>`, a path `robots.txt` forbids, so it
  is never fetched. The allowed `dashboard.html` addresses the same product.

- **MC-A-5** — **The model name must be percent-encoded** into the query string
  (`urllib.parse.quote(model, safe="")`), because most Mini-Circuits part numbers end
  in `+`. An unencoded `+` decodes to a space and the page answers **HTTP 200 with
  valid HTML and no datasheet link** — a silent failure, not an error.

- **MC-A-6** — **The datasheet filename is not derivable from the model name.**
  `/pdfs/<MODEL>.pdf` resolves for ~90% of parts (37/40 sampled) but 404s wherever a
  suffix variant shares a base datasheet — systematic in the ZFL/ZHL/ZVA coaxial
  families (`ZHL-10M4G21W1X+` → `ZHL-10M4G21W1+.pdf`, `ZHL-2X-S+` → `ZHL-2-S+.pdf`,
  `ZFL-2500VHX+` → `ZFL-2500VH+.pdf`). The product page is the only authoritative
  source, so the URL is read there and never guessed.

- **MC-A-7** — **Not every part has a datasheet link** (~1 in 15 sampled had none);
  its absence is a normal outcome, not a failure.

## Datasheet Retrieval

> Owns the Mini-Circuits-specific step of finding a part's datasheet link for the
> datasheet fallback. The generic "download a datasheet PDF by URL" behavior lives
> in `rf_finder/datasheet/pdf.py`.

- **MC-DS-1** — Because the datasheet link is published in neither the same place
  nor the same form as the parameters the adapter scrapes (MC-A-2), the adapter
  SHALL obtain it from **the part's own product page** (MC-A-3), reading the
  `DATASHEET` anchor's href and returning it as an absolute URL. It SHALL NOT be
  derived from the model name (MC-A-6).

- **MC-DS-2** — This retrieval SHALL NOT happen during `search()`. The table lists
  every amplifier Mini-Circuits sells (789 rows), so a product-page fetch per row
  would cost one request per catalogue row (~13 min at the adapter's 1 s guard) to
  obtain links that only the few surviving candidates ever need. `search()`
  therefore leaves `datasheet_url` as `None`, and the adapter resolves the link **on
  demand, one candidate at a time**, when the pipeline asks for it.

- **MC-DS-3** — Resolution SHALL be resilient: a product page that fails to fetch,
  or that carries no `DATASHEET` anchor (MC-A-7), yields `None` rather than raising.
  The part stays a valid candidate whose datasheet simply could not be read.

- **MC-DS-4** — The existing rate guard (`_MIN_DELAY_SECONDS`) and browser
  User-Agent SHALL apply to product-page fetches as they do to the table fetch.

## Open Questions

- **MC-OQ-1** — Does Mini-Circuits have a usable official API without
  registration? *(was OQ-2)*

## Definition of Done

- The system returns real candidates from Mini-Circuits. *(was §7, criterion 2)*
- A candidate's datasheet link is resolved from its product page when the pipeline
  needs it (MC-DS-1), with `search()` making no per-part request (MC-DS-2).

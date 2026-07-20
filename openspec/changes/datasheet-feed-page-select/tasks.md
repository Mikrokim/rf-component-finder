## 1. Page access (PDF layer)

- [ ] 1.1 Add a per-page text accessor to `rf_finder/datasheet/pdf.py` that returns the list of page texts (so the selector can score pages independently), reusing the existing pdfplumber path.
- [ ] 1.2 Confirm the existing `pages=[...]` extraction path still works and is used to build the VDD feed from selected page indices.

## 2. VDD feed — page selection

- [ ] 2.1 Implement the page-select signals as named constants/regexes in `rf_finder/datasheet/`: `MTM` (Min/Typ/Max triple), `ABS` (absolute / max-rating), `VSUPPLY` (supply/drain/bias voltage stated with a value).
- [ ] 2.2 Implement the `" vs"` graph-marker density filter with a named threshold constant (`VS_MAX`), so chart pages that repeat a spec header are excluded.
- [ ] 2.3 Implement `select_vdd_pages(pages) -> [idx...]`: keep a page when `VS` density is low AND (`MTM` ∨ `ABS` ∨ `VSUPPLY`). Each signal must select its own page (no co-location reliance).
- [ ] 2.4 Fallback: if no page is selected, feed the whole datasheet text rather than an empty feed.

## 3. SIZE / MSL / TEMPERATURE feed — regex locators

- [ ] 3.1 Implement `regex_feed(text)` with a named `WINDOW` constant: merge ±window spans around the SIZE / MSL / TEMPERATURE locator matches into one grouped feed.
- [ ] 3.2 SIZE locator: dimension pattern (metric + inch/`"` + mils + diameter). **Add a distractor filter** so mechanical-drawing callouts (thru-hole, tolerance, "Dimensions in mils") do not win over the product/package/die dimension (AM001019SF failure).
- [ ] 3.3 TEMPERATURE locator: **prefer the `operating` window and exclude the `storage` window** from the feed, so the operating max is returned, not the storage max (grf2111, AM001019SF failures).
- [ ] 3.4 MSL locator: moisture-sensitivity keyword; keep the absent-case returning null (guard against prose false-positives like "Moisture protection").

## 4. Call grouping in the extractor

- [ ] 4.1 In `rf_finder/datasheet/extractor.py`, split `extract_rf_parameters` so VDD is requested in its own isolated call and SIZE/MSL/TEMPERATURE are requested in one grouped call.
- [ ] 4.2 Merge the two call results into a single mapping with exactly the requested keys and the six-field shape (contract unchanged).
- [ ] 4.3 Route each requested parameter to its feed: VDD → selected pages; SIZE/MSL/TEMP → regex feed.

## 5. VDD six-field shape normalisation (deterministic, post-extraction)

- [ ] 5.1 Enforce the shape rules in code after the VDD call: list → `value[]`; range → `min`/`max`; single → `typ`; max-only → `max`; min-only → `min` (fixes grf2111 list, cmpa1e1f060d single).
- [ ] 5.2 Drop spurious extras (values duplicated from graph conditions / axis labels) so `value[]` holds a real list only.
- [ ] 5.3 Add an abs-max decode: when an absolute-maximum voltage is present in the feed, place it in `max` (fixes am06/hmc/AM missing max, and RWLA operating→typ + abs-max→max).

## 6. Validation harness

- [ ] 6.1 Add the hand-verified, source-checked gold for the labelled datasheets to `evals/eval_gold.py` `GOLD_CASES` (VDD/MSL/SIZE/TEMPERATURE), applying the shape rules.
- [ ] 6.2 Make the gold eval run through the new feed path (page-select + regex + 2 calls), not the whole-text path, so it scores the architecture under test.
- [ ] 6.3 Run `evals/eval_gold.py` and record the per-parameter score; confirm MSL 7/7 holds and VDD/TEMP/SIZE improve over the pre-fix baseline (MSL 7/7, SIZE 6/7, TEMP 5/7, VDD weak).

## 7. Open questions (tracked, not implemented here)

- [ ] 7.1 Label gold for the three eyeball-only datasheets (CMD192, VM042D, MMA035AA) and fold them into the eval.
- [ ] 7.2 Decide VDD-from-prose placement strategy (LLM vs code decode vs instruction hint) beyond the abs-max decode.
- [ ] 7.3 Decide TEMPERATURE column-format decode ("-40 105 °C" with no "to").
- [ ] 7.4 Validate the `" vs"` threshold and supply-voltage signal breadth on a larger labelled corpus before trusting beyond the current 10.

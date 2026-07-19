## Context

`extract_rf_parameters` sends the datasheet text plus a list of requested parameter names to a small local model (`llama3.1:8b`) and asks for one JSON object per name. Measured at `temperature=0`, three of the four parameters this project targets fail — for reasons that are **not** in the text rendering (that is `improve-datasheet-pdf-text`) but in the extraction logic:

- **VDD** — a request for `VDD` on a datasheet stating `Drain Voltage 28 V` returns `{}`: the model does not connect the requested name to the vendor's term.
- **MSL** — extracts correctly where stated (`3`, `1`) but is **fabricated** where absent: the model emits the instruction's own `"3"` example. Abstracting the example and adding an explicit "absent → null" rule both failed (it parroted the replacement placeholder `"1..5"`).
- **Physical size** — stated as prose (`Die size: 4530 µm x 6090 µm`); the model reads the `(+0/-50 µm)` tolerance as a range and fabricates a `max`, varies run-to-run, and parrots the `9.00 x 8.00 mm` example.

The governing finding, established across the companion investigation: **on this weak model, deterministic code is a strong lever and instruction wording is a weak one.** Two separate instruction-only attempts at the MSL and size problems failed. This design therefore puts the load on code and uses the prompt only where the model genuinely must do the reading.

## Goals / Non-Goals

**Goals:**

- Recognise a requested supply-voltage name (`VDD`/`VCC`) under the vendor's wording (`Drain Voltage`, `Vds`, …).
- Never emit a fabricated value for a categorical parameter whose topic is absent from the fed text.
- Decompose physical-size prose (`A x B unit`) into `length`/`width` deterministically.
- Keep the `{unit, min, typ, max, value, condition}` / `null` result shape unchanged.
- Keep the new grounding and dimension logic unit-testable without a model.

**Non-Goals:**

- The pdf.py rendering/segmentation pipeline (companion change).
- A general synonym system for every parameter — only the supply-voltage aliases the target set needs, structured so more can be added.
- Changing the provider/model or `num_ctx` (measured as not the cause).
- Operating/storage temperature, which already extracts correctly.

## Decisions

### VDD recognition: an alias map injected into the prompt, not hardcoded instruction prose

Keep a small alias map — `VDD → {Drain Voltage, Vds, Drain to Source Voltage}`, `VCC → {Vcc, Collector Voltage}` — and, per request, inject the requested parameter's aliases into the prompt (e.g. `VDD (also written: Drain Voltage, Vds, Drain to Source Voltage)`). The mapping is **data in code**, not prose baked into the instruction, so it is extensible to other parameters and keeps the instruction generic.

*Measured basis.* A single synonym line already moved `VDD` from `{}` to `{"typ": 28}`; the alias map generalises that result without hardcoding one parameter into the instruction text.

*Alternative rejected.* One hardcoded synonym sentence in `EXTRACT_RF_PARAMETERS_INSTRUCTION` — simplest, but it mixes parameter data into prose and does not extend.

### Absent categorical parameters: deterministic grounding in code, not the model

After extraction, for each requested **categorical** parameter (per the ontology — MSL, package, size), check whether any of its keywords appears (case-insensitively) in the fed datasheet text. If none does, force the value to `null`. The model's categorical answer is trusted only when the topic is demonstrably present.

*Measured basis.* MSL fabricates `"3"`/`"MSL1"`/`"1..5"` on a datasheet without MSL; two instruction-only fixes failed. A code check cannot be parroted.

*Keyword source (data-based).* Derived from the wording of the five surveyed vendors, not guessed: `MSL → {msl, moisture}` — verified to catch all three real instances (ADCA3270, GRF2111, HMC952), while `jedec` was **rejected as too broad** (it matches ESD `HBM per JEDEC` and package `JEDEC MO-220` standards, not MSL). `package → {package, pkg, case, outline, body}` — `package` alone covers all five, the rest add margin for vendors that word it `Case`/`Outline`/`Body`. `size` needs **no** keyword list: its dimension parser (below) is self-grounding.

### Physical size: a deterministic dimension parser, bypassing the model

Parse the fed text for a dimension pattern (`A x B unit`, tolerant of `x`/`×` and an optional repeated unit) and assign the **first** number to `length`, the **second** to `width` — the product-resolved convention. This runs deterministically for `length`/`width`; when no pattern matches they are `null`, never guessed.

The regex match is itself the grounding for `length`/`width`/`size`: a match yields the values, no match yields `null` — so no separate keyword list is needed. The `A x B` pattern was confirmed present in every surveyed vendor (`9.00 mm × 8.00 mm`, `5x5 mm`, `4530 µm x 6090 µm`, `1.5 x 1.5 mm`).

*Measured basis.* Requesting these from the model yields fabricated maxes (from the `+0/-50` tolerance), run-to-run variation, and the parroted `9.00 x 8.00 mm` example. A regex over the prose avoids all three.

## Risks / Trade-offs

- **Alias / keyword lists need maintenance.** New vendor wording not in the lists is missed (VDD) or nulled (categorical). Mitigated by seeding from the five surveyed vendors and biasing the keyword lists toward inclusion.
- **Grounding can null a real value** if a datasheet states a categorical parameter under wording outside its keyword list. Measured across the five vendors: **zero false-nulls** with the lists above — every real MSL instance carried `msl`/`moisture`, every package carried `package`/`case`/`outline`/`body`. The residual risk is genuinely novel wording (e.g. MSL stated only as `J-STD-020 Level 3`, with no `msl`/`moisture`), which did not occur in the surveyed set; adding the missing term is the fix if it ever appears.
- **Multiple size lines.** A datasheet may state die size, package size, and pad size; the parser must choose which is the product dimension. Left to an Open Question below.
- **The length/width convention is a labelling choice, not a datasheet fact** — `A x B` is unlabelled. Documented as resolved (first = length) so it is at least consistent.

## Open Questions

- **Where does the alias map live** — a field on `ParamDef` in `ontology/parameters.py`, or a separate `synonyms` module? The ontology couples it to the parameter definitions; a module keeps the ontology lean.
- **Which size wins** when a datasheet states several (die vs package vs pad)? None of the target flow needs more than the die/package dimension today, but the parser needs a deterministic pick.

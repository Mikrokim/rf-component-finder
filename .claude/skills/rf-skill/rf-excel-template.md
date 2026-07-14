# RF Search — Excel Output Template

The canonical, fixed column schema for the report workbook. **Load this at Step 4 (reporting).** Every run must produce a workbook with exactly these three sheets and exactly these columns, in this order, so the file's structure is identical run to run. Only the *dynamic parameter columns* in the התאמות sheet vary — and only because they follow the user's query.

Build the file with the **xlsx skill**; apply RTL Hebrew layout via the **hebrew-office-documents skill**. Headers are Hebrew (the reader is an RTL Hebrew user); part numbers, parameter names and units stay English (Gain, OP1dB, OIP3, NF, GHz, dBm).

Content rules — *which* part belongs in *which* sheet, the outcome vocabulary, the exhaustiveness and aggregator-expansion requirements — are **not** repeated here; they live in `SKILL.md` (Core definitions → Outcome categories, and Step 4). This file fixes only the **column layout**.

All three sheets are **mandatory even when empty** — a sheet with only its header row is itself meaningful (e.g. "אף מועמד לא נפסל בשלב datasheet").

---

## Sheet 1 — התאמות (matches)

Holds ✅ full matches and ⚠️ borderline / `not datasheet-verified` rows.

Columns, in order (right-to-left in the RTL sheet):

| # | כותרת עמודה | תוכן |
|---|---|---|
| 1 | יצרן | Manufacturer name. |
| 2 | מספר רכיב | Part number (English). |
| 3 | סוג | Component type / sub-type (e.g. "MMIC amplifier", "connectorized module"). |
| 4…N | **[דינאמי] עמודה לכל פרמטר שנתבקש** | One column per parameter the user actually specified this search — header is the parameter name + unit (e.g. `Gain (dB)`, `OP1dB (dBm)`, `Freq (GHz)`). Cell = the part's actual value. These columns appear **only** for parameters in the query; nothing else. |
| N+1 | בסיס ההתאמה (min/max או typ) | Whether the match rests on **guaranteed min/max** columns or on **typ** values. If mixed, state the weakest basis and name the typ parameter (e.g. "min/max; OIP3 לפי typ"). |
| N+2 | הערה / מקור | Free note. Carries the ⚠️ flag when relevant — for a `not datasheet-verified` row put exactly **"לא אומת — גישה ל-datasheet חסומה"** here. Also any condition caveat (e.g. "מובטח ב-+25°C בלבד"). |
| N+3 | קישור לרכיב | The closest link to **the part itself** — prefer the part's **own datasheet PDF**, not the company's general catalog. For a `not datasheet-verified` row (datasheet unreachable) put the aggregator/product page link instead. |
| N+4 | שאילתה שנשלחה | The query used to find the part on the site it came from (keyword string, or the Path-A parametric filter set, e.g. "Amplifiers; 14–15 GHz; Gain≥20 dB"). |

---

## Sheet 2 — נבדקו ונפסלו (checked & rejected)

Holds every candidate that reached datasheet-check and failed, plus access-blocked *unverifiable* parts (labelled per SKILL.md, not as a parameter failure).

| # | כותרת עמודה | תוכן |
|---|---|---|
| 1 | יצרן | Manufacturer name. |
| 2 | מספר רכיב | Part number (English). |
| 3 | פרמטר כושל | The parameter that failed. For an access-blocked *unverifiable* part, name the datasheet-only parameter that could not be checked. |
| 4 | ערך בפועל | The actual value of the failing parameter (the datasheet value that lost against the spec). |
| 5 | הערה | Reason detail. For an unverifiable part use exactly **"לא נפסל על פרמטר — נדרש אימות ב-datasheet שלא היה נגיש; כדאי לשקול פנייה ליצרן"**. |
| 6 | קישור לרכיב | Link to the part if one exists (datasheet or product page); leave empty if none. |

---

## Sheet 3 — יומן כיסוי (coverage journal)

The proof-of-work sheet. Its main table is the **manufacturers / sources table** — one row per vendor or source touched at least once through any path. Must be **exhaustive** (a vendor that returned nothing is listed `checked/no candidates`, never omitted) and aggregators must be **expanded** into one row per vendor they surfaced — full rules in SKILL.md Step 4.

Manufacturers / sources table columns, in order:

| # | כותרת עמודה | תוכן |
|---|---|---|
| 1 | יצרן / מקור | Vendor or source name. |
| 2 | נבדק דרך | Which discovery path reached it — A (parametric aggregator) / B (part-graph) / C (cache sweep). |
| 3 | שאילתה שנשלחה | The exact query sent to that source: keyword string, Path-A filter set, or catalog search term / URL fetched. Multiple queries → newline-separated in the cell or one row per query. A `not covered` source leaves this empty. |
| 4 | תוצאה | Outcome, using the Outcome categories in SKILL.md: `checked/no candidates` · `checked/found X` · `not covered` · `rejected at site screen` · `not datasheet-verified` · `datasheet inaccessible`. |
| 5 | קישור | Link to the vendor/source page, catalog, or aggregator result used. |

Above this table, include the short **paths summary** (three rows — one per discovery path A/B/C — with its run outcome, e.g. "everything.rf parametric ✓ — N pages"; "part-graph traversal ✓ — M waves, K new vendors"; "cache sweep ✓"). Also note that datasheet reading was delegated to Gemini (provider/model), with no independent re-verification run.

"""Extract requested RF parameters from raw datasheet text via GenAIFabric.

The extraction contract lives in ``EXTRACT_RF_PARAMETERS_INSTRUCTION``: the
model receives the datasheet text plus the list of requested parameter names,
and must answer with one JSON key per requested name — either a
``{unit, min, typ, max, value, condition}`` object or ``null`` when the datasheet
does not state the parameter (guessing is forbidden).  Numeric specs use
``min``/``typ``/``max``; categorical or non-numeric ones (MSL, package, size)
and discrete supply option lists use ``value``.

``genaifabric`` (and a provider API key) is only needed when
``extract_rf_parameters`` is actually called — importing this module is free,
so the scraping/verification path keeps working without the ``llm`` extra.
"""

from __future__ import annotations

import json
from functools import lru_cache

from rf_finder.config import DATASHEET_MODEL, DATASHEET_PROVIDER

EXTRACT_RF_PARAMETERS_INSTRUCTION = """\
You are an RF component datasheet parameter extraction engine.

The Context contains two keys:
  - "datasheet": the raw text of an RF component datasheet.
  - "requested_parameters": a list of parameter names the caller wants extracted.

Your task: for EACH name in "requested_parameters", find its value in the datasheet.

Rules:
- Return ONLY a valid JSON object. No prose, no markdown, no ``` fences.
- The JSON MUST contain exactly one key per requested parameter, using the
  requested name verbatim as the key.
- If a parameter IS found, its value is an object:
    {
      "unit":      <string or null>,   // e.g. "dBm", "dB", "GHz", "Ohm", "V", "mm"
      "min":       <number or null>,
      "typ":       <number or null>,
      "max":       <number or null>,
      "value":     <string, number, array of numbers, or null>,
      "condition": <string or null>    // the operating point the value is stated
                                       // at (frequency / supply / temperature);
                                       // build it ONLY from the datasheet, null if
                                       // none — never echo this hint text verbatim.
    }
  ALWAYS output all six keys for a found parameter, in the order above; use the JSON
  literal null for any that do not apply — do NOT omit keys. "condition" is NEVER the
  value or its range restated — leave it null unless the datasheet gives a SEPARATE
  qualifying operating point (bias, frequency, temperature). Emit strictly valid
  JSON: keep every string value plain and avoid characters that need escaping (for
  units, spell the word — see PHYSICAL DIMENSIONS).

- FIELD DISCIPLINE — choose the numeric fields OR "value", NEVER both:
    - A numeric quantity — a range OR a single figure, INCLUDING temperatures and
      physical dimensions — goes in "min"/"typ"/"max" ONLY, and its "value" stays
      null. Do NOT also copy the number, the unit, or the raw range text into
      "value".
    - "value" is used ONLY for a categorical string (package, MSL, ...) or an
      explicit list of discrete selectable options; then the numeric fields stay
      null.

- NUMERIC parameters (gain, noise figure, P1dB, frequency, impedance,
  temperature ranges, ...):
    - If the datasheet gives a min/typ/max range, fill "min"/"typ"/"max" and
      leave "value" null.
    - A two-ended range written as "A to B" (e.g. an operating or storage
      temperature "-A°C to +B°C", or "A MHz to B MHz") is NUMERIC: put A in
      "min" and B in "max" (keep the sign), and leave "typ"/"value" null. Do NOT
      return it as a string.
    - RANGE INTEGRITY: both endpoints of a range MUST come from the SAME row / the
      SAME parameter. NEVER pair a "min" taken from one parameter with a "max"
      taken from a different, adjacent parameter, even when the two sit on
      neighbouring lines (a common trap with stacked "operating" vs "storage"
      temperature rows, or one row's label/subscript spilling onto the next line).
      If the requested parameter states only one endpoint, fill that one and leave
      the other null.
    - COPY EXACTLY: transcribe every number, unit, and condition exactly as printed —
      same digits, decimal point, and sign. Do NOT shift the decimal, round, rescale,
      or convert units.
    - If it gives only a SINGLE figure (no range), put it in "typ"; leave
      "min"/"max"/"value" null.
    - Each requested parameter is stated at a SINGLE operating point — return one
      object, not a list.

- SUPPLY parameters (VDD, VCC, ...):
    - Three values presented as Min/Typ/Max columns (e.g. "A B C V") are a
      RANGE, not a list — fill "min"/"typ"/"max" and leave "value" null. This is
      the default; when in doubt, treat supply numbers as a min/typ/max range.
    - Use the "value" array ONLY when the datasheet EXPLICITLY enumerates several
      separate, selectable supply voltages as distinct options — e.g. a
      comma-separated list "A, B, C V" or wording like "supports A V, B V and
      C V". Then put them in "value" as [A, B, C] with the "unit" and leave
      "min"/"typ"/"max" null.

- NON-NUMERIC / categorical parameters (moisture sensitivity level, package type):
  put the value in "value" as a string, exactly as written — e.g. the level number
  for MSL, "LGA_CAV" for package; leave the numeric fields null.

- PHYSICAL DIMENSIONS ("length" and "width") are each a SINGLE numeric measurement —
  put the number in "typ" (NOT in "value", and never a combined string) and put the
  unit STATED in the source in "unit", written as a short ASCII word — "mm", "inch",
  or "mil". Do NOT emit the symbols " (double-prime) or ' for inches — spell the word
  "inch" instead, so the JSON stays valid — and do NOT convert between units. Read
  the two package-body footprint numbers, written "A x B <unit>" (or "A x B x C
  <unit>", where C is height/thickness — ignore C). They may appear in a dedicated
  Outline / Package Dimensions table, in the package name/descriptor (e.g. "A x B mm
  DFN-N"), a Features bullet, the DESCRIPTION prose (e.g. "... at A (L) x B (W) x
  C (H)"), or the document title — read whichever states them. Use the PACKAGE BODY
  size, NOT the PCB / suggested footprint, carrier-tape, or reel dimensions.
    - If the source LABELS the numbers — "(L)"/"(W)"/"(H)" or "Length"/"Width"/
      "Height" — assign by the LABEL: "length" <- the L number, "width" <- the W
      number (ignore the H/height number). The label WINS over position.
    - Only when there are NO such labels, use SOURCE ORDER: the first number goes to
      "length", the second to "width".
  Leave the other numeric fields null.

- DISAMBIGUATION: when a requested name specifies a variant, extract THAT variant
  only — e.g. "operating_temperature" -> the operating temperature range,
  "storage_temperature" -> the storage temperature range. Never substitute a
  different one. When such variants sit on ADJACENT rows, read ONLY the row whose
  label matches, and take BOTH endpoints from that one row (see RANGE INTEGRITY) —
  do not let the neighbouring row's numbers leak in.

- GENERIC NAMES: an UNQUALIFIED requested name maps to the device's PRIMARY
  parameter of that kind. "Voltage" / "Supply" / "Supply Voltage" -> the main device
  supply (VDD / VCC), never an enable, leakage, or ESD voltage. An unqualified
  "Temperature" -> the OPERATING temperature, never storage or channel/junction.

- WHERE TO LOOK: parameters such as length, width, MSL, and temperature ranges
  usually live OUTSIDE the main specifications table — check the Recommended
  Operating Conditions and Absolute Maximum Ratings tables, the Outline / Package
  Dimensions, and the package descriptor. When the SAME parameter appears in more
  than one table, prefer the "Recommended Operating Conditions" / "Nominal Operating"
  value; an "Absolute Maximum Ratings" value is a damage limit, NOT the operating
  spec — use it only when the parameter appears nowhere else.

- If a parameter is NOT present in the datasheet, set its value to null (the JSON
  literal null), NOT an object. NEVER guess or infer a value that is not stated.
- The parameter names used in these rules are ILLUSTRATIVE examples of each
  category (numeric / range / discrete-supply / categorical), NOT an exhaustive
  list. Apply the same rules to ANY requested parameter, named or not.
"""


@lru_cache(maxsize=1)
def _get_runtime():
    """Build the default runtime with every provider that can be constructed.

    ``mock`` and ``local`` (Ollama) are built in and need nothing.  ``openai``
    is registered only when it can be constructed (the ``openai`` package is
    installed and an API key is available), so the local/mock paths keep
    working with no API key.
    """
    from genaifabric import GenAIFabric
    from genaifabric.providers.local import LocalProvider
    from genaifabric.providers.mock import MockProvider

    providers = {
        "mock": MockProvider(),
        # Local thinking models on CPU are slow, and the first call also loads
        # the model into memory — give them plenty of head-room.
        "local": LocalProvider(timeout_seconds=600.0),
    }
    try:
        from genaifabric.providers.openai import OpenAIProvider

        providers["openai"] = OpenAIProvider(model="gpt-4o")
    except Exception:
        # openai package missing or OPENAI_API_KEY unset — skip it; the other
        # providers are still usable.
        pass

    try:
        from genaifabric.providers.gemini import GeminiProvider

        providers["gemini"] = GeminiProvider(model=DATASHEET_MODEL)
    except Exception:
        # GeminiProvider raises at CONSTRUCTION when GEMINI_API_KEY is unset, so
        # this guard is what keeps the mock/local paths working without a key.
        pass

    return GenAIFabric(provider_map=providers)


def _extract_json_object(text: str) -> str:
    """Pull the JSON object out of a model reply that may wrap it in noise.

    Handles thinking models (``<think>...</think>`` preambles), markdown code
    fences, and stray prose around the object — so a compliant ``{...}`` reply
    is recovered even from a chatty local model.
    """
    raw = text.strip()
    if "</think>" in raw:
        raw = raw.rsplit("</think>", 1)[1].strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    # Last resort: slice from the first "{" to the last "}".
    if not raw.startswith("{") and "{" in raw and "}" in raw:
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
    return raw


def extract_rf_parameters(
    datasheet_text: str,
    requested_parameters: list[str],
    runtime=None,
) -> dict:
    """Extract the requested parameters from an RF component datasheet's text.

    Returns a dict with exactly one key per requested parameter name: either a
    full ``{unit, min, typ, max, value, condition}`` dict, or ``None`` when the
    datasheet does not state that parameter.  A found parameter always carries
    all six fields (missing ones as ``None``), normalised so the shape is
    uniform regardless of how much of the schema the model spelled out.

    The model and provider are taken from the ``DATASHEET_MODEL`` and
    ``DATASHEET_PROVIDER`` variables in ``rf_finder.config``, not passed in.
    ``runtime`` lets callers/tests supply their own GenAIFabric instance (e.g.
    one whose provider_map holds a MockProvider); default is the shared runtime.

    Raises ``RuntimeError`` when the LLM run itself fails and ``ValueError``
    when the model's output is not valid JSON.
    """
    if runtime is None:
        runtime = _get_runtime()
    result = runtime.run(
        instruction=EXTRACT_RF_PARAMETERS_INSTRUCTION,
        provider=DATASHEET_PROVIDER,
        model=DATASHEET_MODEL,
        input={
            "datasheet": datasheet_text,
            "requested_parameters": requested_parameters,
        },
    )

    if not result.success:
        raise RuntimeError(f"Extraction failed: {result.error}")

    raw = _extract_json_object(result.output)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw output:\n{raw}")

    # Enforce the contract regardless of what the model returned: exactly the
    # requested keys, missing ones as None, extras dropped.  For each FOUND
    # parameter, also normalise its inner shape to the full six-field schema so
    # the output is uniform no matter how compliant the model was — a terse
    # model that omits null fields and a chatty one that spells them out yield
    # the same dict.  Not-found parameters stay ``None``, not ``{}``.
    return {name: _normalize_spec(data.get(name)) for name in requested_parameters}


# The full per-parameter field set the extraction contract promises.
_SPEC_FIELDS = ("unit", "min", "typ", "max", "value", "condition")


def _normalize_spec(spec):
    """Fill any missing field with ``None`` so every found spec has all six keys.

    ``None`` (parameter not found in the datasheet) passes through unchanged; a
    non-dict value is left as-is rather than being coerced.
    """
    if not isinstance(spec, dict):
        return spec
    return {field: spec.get(field) for field in _SPEC_FIELDS}

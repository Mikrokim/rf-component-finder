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
      "condition": <string or null>    // e.g. "@ 2.4 GHz, Vcc=5V, 25°C"
    }

- NUMERIC parameters (gain, noise figure, P1dB, frequency, impedance,
  temperature ranges, ...):
    - If the datasheet gives a min/typ/max range, fill "min"/"typ"/"max" and
      leave "value" null.
    - A two-ended range written as "A to B" (e.g. an operating or storage
      temperature "-30C to +110C", or "45 MHz to 1218 MHz") is NUMERIC: put A in
      "min" and B in "max" (keep the sign), and leave "typ"/"value" null. Do NOT
      return it as a string.
    - If it gives only a SINGLE figure (no range), put it in "typ"; leave
      "min"/"max"/"value" null.
    - Each requested parameter is stated at a SINGLE operating point — return one
      object, not a list.

- SUPPLY parameters (VDD, VCC, ...):
    - Three values presented as Min/Typ/Max columns (e.g. "18 24 26 V") are a
      RANGE, not a list — fill "min"/"typ"/"max" and leave "value" null. This is
      the default; when in doubt, treat supply numbers as a min/typ/max range.
    - Use the "value" array ONLY when the datasheet EXPLICITLY enumerates several
      separate, selectable supply voltages as distinct options — e.g. a
      comma-separated list "3, 5, 8 V" or wording like "supports 3 V, 5 V and
      8 V". Then put them in "value" as [3, 5, 8] with the "unit" and leave
      "min"/"typ"/"max" null.

- NON-NUMERIC / categorical parameters (moisture sensitivity level, package type):
  put the value in "value" as a string, exactly as written — e.g. "3" for MSL,
  "LGA_CAV" for package; leave the numeric fields null.

- PHYSICAL DIMENSIONS ("length" and "width") are each a SINGLE numeric measurement
  in mm — put the number in "typ" (NOT in "value", and never a combined string).
  Read the two footprint numbers from the Outline Dimensions in SOURCE ORDER: the
  first goes to "length", the second to "width". E.g. a "9.00 x 8.00 mm" outline
  means length -> typ 9.0 and width -> typ 8.0. Leave the other numeric fields null.

- DISAMBIGUATION: when a requested name specifies a variant, extract THAT variant
  only — e.g. "operating_temperature" -> the operating temperature range,
  "storage_temperature" -> the storage temperature range. Never substitute a
  different one.

- WHERE TO LOOK: parameters such as length, width, MSL, and temperature ranges
  usually live OUTSIDE the main specifications table — check Absolute Maximum
  Ratings and Outline Dimensions.

- If a parameter is NOT present in the datasheet, set its value to null (the JSON
  literal null), NOT an object. NEVER guess or infer a value that is not stated.
- Preserve units and conditions exactly as written in the datasheet.
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

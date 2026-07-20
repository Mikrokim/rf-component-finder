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
import re
from functools import lru_cache

from rf_finder.config import DATASHEET_MODEL, DATASHEET_PROVIDER

EXTRACT_RF_PARAMETERS_INSTRUCTION = """\
Return only a valid JSON object.
Do not return Markdown or explanations.
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
    - A SINGLE supply figure — one number, e.g. "Drain voltage 10 V" — is NOT a
      list and NOT a range: put it in "typ" and leave "min"/"max"/"value" null.
      Only a comma-separated enumeration (above) uses the "value" array.

- NON-NUMERIC / categorical parameters (moisture sensitivity level, package type,
  physical size / dimensions): put the value in "value" as a string, exactly as
  written in THIS datasheet; leave the numeric fields null. Copy the characters
  from the datasheet — never a value from these rules.
- For "size": report the PACKAGE outline / body dimensions (the outer size the
  part ships as) when the datasheet states them; only if there is no package —
  the part is a bare die — report the die size. Return it verbatim as an
  "A x B unit" string, e.g. the exact dimensions printed in the Outline / Package
  Drawing of THIS datasheet.

- DISAMBIGUATION: when a requested name specifies a variant, extract THAT variant
  only — e.g. "operating_temperature" -> the operating temperature range,
  "storage_temperature" -> the storage temperature range. Never substitute a
  different one.

- WHERE TO LOOK: parameters such as size, MSL, and temperature ranges usually live
  OUTSIDE the main specifications table — check Absolute Maximum Ratings and
  Outline Dimensions.

- If a parameter is NOT present in the datasheet, set its value to null (the JSON
  literal null), NOT an object. NEVER guess or infer a value that is not stated.
- Preserve units and conditions exactly as written in the datasheet.
- The parameter names used in these rules are ILLUSTRATIVE examples of each
  category (numeric / range / discrete-supply / categorical), NOT an exhaustive
  list. Apply the same rules to ANY requested parameter, named or not.
  If a requested parameter is not explicitly stated, return null.
- INDEPENDENCE: each requested parameter is extracted on its own merits. Some
  requested parameters may be absent — return those as null, but this MUST NOT
  affect the others: a parameter that IS stated must still be returned in full.
  NEVER null a value that is present just because other requested values are
  missing.
Return only JSON. No text before or after it.
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
        "local": LocalProvider(
            timeout_seconds=600.0,
            allowed_models=["qwen3:8b", "llama3.1:8b", "phi4-mini:latest"],
        ),
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
        # gemini package missing or GEMINI_API_KEY unset — skip it; the other
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

    # length/width are not extracted directly (the model pollutes them: it reads
    # a "+/-" tolerance as a range and fabricates a max).  Instead the model is
    # asked for the whole "size", which it selects reliably (the die, not the
    # pad), and its answer is split into length/width below.  "size" is requested
    # even when only length/width were asked for.
    wants_dimensions = (
        "length" in requested_parameters or "width" in requested_parameters
    )
    # When dimensions are wanted, ask the model for the whole "size" ONLY, not
    # length/width: requesting all three made the model juggle them and degrade
    # the answer (measured: GRF2111 returns the correct "1.5 x 1.5 mm" for a lone
    # "size" request, but nulled when length/width/size were requested together).
    # length/width are derived from "size" in _parse_size_spec below.
    model_params = [p for p in requested_parameters if p not in ("length", "width")]
    if wants_dimensions and "size" not in model_params:
        model_params.append("size")

    # Make vendor aliases for the requested supply names available to the model,
    # so a "Drain Voltage" row satisfies a request for VDD.  Built per call from
    # ``_PARAM_ALIASES`` and appended to the instruction; the module-level
    # instruction is left unchanged.
    instruction = EXTRACT_RF_PARAMETERS_INSTRUCTION
    alias_hints = [
        f'"{name}" may be written as: {", ".join(_PARAM_ALIASES[name])}.'
        for name in requested_parameters
        if name in _PARAM_ALIASES
    ]
    if alias_hints:
        instruction = EXTRACT_RF_PARAMETERS_INSTRUCTION.replace(
            "Return only JSON. No text before or after it.",
            "SYNONYMS: " + " ".join(alias_hints)
            + "\nReturn only JSON. No text before or after it.",
        )
    result = runtime.run(
        instruction=instruction,
        provider=DATASHEET_PROVIDER,
        model=DATASHEET_MODEL,
        input={
            "datasheet": datasheet_text,
            "requested_parameters": model_params,
        },
        # Extraction is a lookup, not a creative task: the same datasheet must
        # always yield the same values.  Providers default to sampling
        # (Ollama 0.8, Gemini ~1.0), which made repeated runs disagree on both
        # the value and which field it landed in — greedy decoding pins it.
        temperature=0,
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
    specs = {name: _normalize_spec(data.get(name)) for name in model_params}

    # The model selects the product's size; split its answer into clean
    # length/width (see ``_parse_size_spec``).  The internally-added "size" is
    # not returned — only the caller's requested keys are.
    if wants_dimensions:
        length, width = _parse_size_spec(data.get("size"), datasheet_text)
        if "length" in requested_parameters:
            specs["length"] = _normalize_spec(length)
        if "width" in requested_parameters:
            specs["width"] = _normalize_spec(width)

    # Ground categorical values whose topic is absent from the text, and return
    # exactly the caller's requested keys.
    return {
        name: _ground_categorical(name, specs.get(name), datasheet_text)
        for name in requested_parameters
    }


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


# Vendor wordings that satisfy a request for a canonical supply-voltage name.
# These are injected into the prompt so the model finds the value under the
# datasheet's own term (measured: a request for VDD on a "Drain Voltage 28 V"
# datasheet returned {} until the wording was made available, then {"typ": 28}).
_PARAM_ALIASES = {
    "VDD": ["Drain Voltage", "Vds", "Drain to Source Voltage"],
    "VCC": ["Vcc", "Collector Voltage"],
}

# Keyword lists that ground a categorical parameter: if none of a parameter's
# keywords appears in the fed text, the model's categorical answer is nulled
# rather than trusted (the small model fabricates absent categoricals). Derived
# from the surveyed vendors; "jedec" is excluded from MSL because it also marks
# ESD ("HBM per JEDEC") and package ("JEDEC MO-220") standards, not moisture.
_CATEGORICAL_KEYWORDS = {
    "MSL": ["msl", "moisture"],
    "package": ["package", "pkg", "case", "outline", "body"],
}

# The MSL level as written in the datasheet: "MSL 1", "(MSL) 3", "msl3".
# Anchored on the "MSL" abbreviation ONLY (not "Moisture Sensitivity Level",
# whose adca line carries a stray "260°C"). The trailing \b rejects multi-digit
# numbers ("MSL 260" -> no word-boundary between 2 and 6), so 260/-- /[2] traps
# are all sidestepped. Validated 5/5 with zero false-positives on the survey.
_MSL_LEVEL_RE = re.compile(r"MSL[\s:\)]*([1-6][a-z]?)\b", re.I)

# An "A x B unit" physical-dimension pattern: two numbers separated by x or ×,
# with the unit on the second (an optional matching unit may follow the first).
_DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:µm|μm|um|mm|nm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(µm|μm|um|mm|nm)",
    re.I,
)

# Looser variant for parsing the MODEL's own size string, where the model often
# drops the unit into the separate "unit" field and returns a bare "A x B" (e.g.
# "4530 x 6090", "1.5 x 1.5"): here the trailing unit is OPTIONAL. Grounding still
# uses the strict _DIM_RE against the datasheet text (which does carry units), so
# loosening the value parse cannot admit an ungrounded pair.
_DIM_VALUE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:µm|μm|um|mm|nm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(µm|μm|um|mm|nm)?",
    re.I,
)


def _dim_num(text: str):
    """Parse a dimension number, returning an int when it is whole (9.00 -> 9)."""
    value = float(text)
    return int(value) if value.is_integer() else value


def _parse_size_spec(size_spec, datasheet_text: str):
    """Split the model's ``size`` answer into (length, width) specs.

    The model selects which dimension is the product's size (the die, not the
    pad); this parses ITS output into the clean length/width shape — the FIRST
    number is length, the SECOND width.  It reads an "A x B" string in ``value``
    first, then falls back to the model's ``min``/``max`` pair.  The pair is
    grounded against the datasheet text: it is kept only if those same two
    numbers occur as a real dimension pair in the text, so a fabricated size
    (e.g. the instruction's "9.00 x 8.00 mm" example) is nulled.  Returns
    ``(None, None)`` when nothing usable and grounded is found.
    """
    if not isinstance(size_spec, dict):
        return None, None
    unit = size_spec.get("unit")
    a = b = None
    value = size_spec.get("value")
    if isinstance(value, str):
        m = _DIM_VALUE_RE.search(value)
        if m:
            a, b = _dim_num(m.group(1)), _dim_num(m.group(2))
            unit = unit or m.group(3)
    if a is None:
        low, high = size_spec.get("min"), size_spec.get("max")
        if low is not None and high is not None:
            a, b = _dim_num(str(low)), _dim_num(str(high))
    if a is None:
        return None, None
    # Ground against the source: keep only a pair that is a real "A x B" in text.
    text_pairs = [
        (_dim_num(m.group(1)), _dim_num(m.group(2)))
        for m in _DIM_RE.finditer(datasheet_text)
    ]
    if (a, b) not in text_pairs:
        return None, None
    return {"unit": unit, "typ": a}, {"unit": unit, "typ": b}


def _ground_categorical(name: str, spec, datasheet_text: str):
    """Null a keyword-grounded categorical value whose topic is absent.

    For a categorical parameter with a keyword list (``MSL``, ``package``), the
    model's answer is kept only when one of its keywords appears in
    ``datasheet_text`` (case-insensitively); otherwise the result is ``None``,
    never a fabricated value. Parameters with no keyword list pass through
    unchanged.
    """
    keywords = _CATEGORICAL_KEYWORDS.get(name)
    if keywords and not any(k in datasheet_text.lower() for k in keywords):
        return None
    if name == "MSL":
        return _extract_msl_level(datasheet_text, spec)
    return spec


def _extract_msl_level(datasheet_text: str, spec):
    """Override the model's MSL answer with the level parsed from the text.

    The small model returns MSL unreliably ("--", "MSL3"); when the datasheet
    states an "MSL <n>" level, trust the TEXT, not the model. Returns a spec
    whose ``value`` is the parsed level ("1", "3", "2a"). If no clean level is
    found, fall back to the model's own answer (which is null when the model
    likewise found nothing) rather than fabricating one.
    """
    m = _MSL_LEVEL_RE.search(datasheet_text)
    if not m:
        return spec
    return {
        "unit": None, "min": None, "typ": None, "max": None,
        "value": m.group(1), "condition": None,
    }

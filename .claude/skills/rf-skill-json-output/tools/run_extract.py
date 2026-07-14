#!/usr/bin/env python
"""Runner: a candidate's datasheet (URL or local file) -> text -> Gemini -> JSON.

This is the single datasheet-reading entry point for the rf-component-search
skill. It ties the three pieces together --

    config.py     picks the provider/model (from rf-llm.env)
    pdf.py        turns PDF pages into text (its _join_page_text helper)
    extractor.py  sends text + parameter names to the model, gets values-only JSON

-- so the skill can hand a datasheet off to the configured model in one call. The
skill NEVER reads the PDF itself; this runner is the only path, and it always
routes to the external model.

A datasheet URL points at a **PDF file**, not readable text, so its bytes must be
fetched to be decoded. Those bytes are decoded **in memory** (BytesIO) and never
written to disk. The model extracts values only (no verdict, no quote/location);
the skill still judges the match and owns provenance for a ✅ (SKILL.md Step 3).

Usage:
    python tools/run_extract.py --url "https://vendor.com/AMP1234.pdf" --params "Gain,P1dB,NF,OIP3"
    python tools/run_extract.py --file ./AMP1234.pdf --requirements-file reqs.json

Output: one JSON object on stdout -- {success, provider, model, parameters, error,
sources}. Exit code 0 on a successful extraction, 1 otherwise. A fetch/read
failure is `success:false` -- treat it exactly like the skill's *datasheet
inaccessible* case (Access-blocked datasheet logic).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request

import config  # noqa: F401 - importing loads rf-llm.env into the environment
import extractor
import pdf as pdf_module

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DEFAULT_MAX_CHARS = 120_000


def _strip_html(text: str) -> str:
    """Very light HTML-to-text: drop tags and collapse whitespace."""
    import re

    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _pdf_text_from_bytes(data: bytes) -> str:
    """Decode PDF bytes into text fully in memory (no temp file, no disk).

    pdfplumber opens a file-like object directly, so the fetched bytes are wrapped
    in a BytesIO and read straight from RAM. Page-joining reuses pdf.py's
    ``_join_page_text`` helper, so the friend's logic stays the single source of
    that behaviour and pdf.py itself is untouched.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf_obj:
        return pdf_module._join_page_text(pdf_obj.pages)


def _bytes_to_text(data: bytes, ref: str, content_type: str = "") -> str:
    """Turn fetched/read bytes into plain text, handling PDF and HTML."""
    is_pdf = data[:5] == b"%PDF-" or "pdf" in content_type.lower() or ref.lower().endswith(".pdf")
    if is_pdf:
        return _pdf_text_from_bytes(data)

    decoded = data.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or ref.lower().endswith((".htm", ".html")) or "<html" in decoded[:2000].lower():
        return _strip_html(decoded)
    return decoded.strip()


def _fetch_url(url: str, timeout: float) -> str:
    """Fetch a URL (PDF or HTML) and return extracted text — bytes stay in memory."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-provided URL
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read()
    return _bytes_to_text(data, url, content_type)


def _read_file(path: str) -> str:
    """Read a local datasheet file (PDF or text) and return extracted text."""
    with open(path, "rb") as fh:
        data = fh.read()
    return _bytes_to_text(data, path)


def _requested_parameter_names(requirements: object, explicit: list[str]) -> list[str]:
    """Resolve the flat list of parameter NAMES to extract.

    Only names go to the model (never thresholds). ``--params`` (comma-separated,
    repeatable) wins; otherwise names are pulled from the requirements JSON,
    tolerating a bare list of names, a list of ``{"name": ...}`` objects, a dict
    keyed by name, or a ``{"parameters": [...]}`` wrapper.
    """
    names: list[str] = []
    for item in explicit or []:
        names.extend(p.strip() for p in item.split(",") if p.strip())
    if names:
        return names

    if requirements is None:
        return []
    if isinstance(requirements, dict):
        inner = requirements.get("parameters")
        if isinstance(inner, (list, dict)):
            return _requested_parameter_names(inner, [])
        return [str(k) for k in requirements.keys()]
    if isinstance(requirements, list):
        out: list[str] = []
        for it in requirements:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                nm = it.get("name") or it.get("parameter") or it.get("param")
                if nm:
                    out.append(str(nm))
        return out
    return []


def _emit(obj: dict, raw: bool) -> int:
    if raw:
        if obj.get("success"):
            sys.stdout.write(json.dumps(obj.get("parameters"), ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stderr.write((obj.get("error") or "unknown error") + "\n")
    else:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return 0 if obj.get("success") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract RF datasheet parameters via the configured external model (config.py / rf-llm.env).",
    )
    parser.add_argument("--url", action="append", default=[], metavar="URL",
                        help="Datasheet URL to fetch (PDF or HTML); repeatable")
    parser.add_argument("--file", action="append", default=[], metavar="PATH",
                        help="Local datasheet file (PDF or text); repeatable")
    parser.add_argument("--params", action="append", default=[], metavar="NAMES",
                        help="Comma-separated parameter names to extract; repeatable")
    parser.add_argument("--requirements-file", default=None,
                        help="JSON file to read parameter names from (if --params not given)")
    parser.add_argument("--max-chars", type=int, default=_DEFAULT_MAX_CHARS,
                        help=f"Cap on datasheet text per source (default {_DEFAULT_MAX_CHARS})")
    parser.add_argument("--fetch-timeout", type=float, default=60.0,
                        help="Timeout in seconds for URL fetches")
    parser.add_argument("--raw", action="store_true",
                        help="Print only the parameters JSON (stdout) / error (stderr)")
    args = parser.parse_args(argv)

    provider = extractor.DATASHEET_PROVIDER
    model = extractor.DATASHEET_MODEL

    def fail(error: str, sources: list | None = None) -> int:
        return _emit({
            "success": False, "error": error,
            "provider": provider, "model": model,
            "parameters": None, "sources": sources or [],
        }, args.raw)

    # --- requested parameter names --------------------------------------------
    requirements: object | None = None
    if args.requirements_file:
        try:
            with open(args.requirements_file, "r", encoding="utf-8") as fh:
                requirements = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            return fail(f"Could not read --requirements-file: {exc}")

    requested = _requested_parameter_names(requirements, args.params)
    if not requested:
        return fail("No parameters to extract. Pass --params or a --requirements-file listing names.")

    # --- gather datasheet text (bytes fetched to memory, decoded, discarded) ---
    sources: list[dict] = []
    chunks: list[str] = []

    def add_source(ref: str, kind: str, text: str) -> None:
        if not text:
            return
        clipped = text[: args.max_chars]
        chunks.append(clipped if not chunks else f"\n\n===== source: {ref} =====\n{clipped}")
        sources.append({"ref": ref, "kind": kind, "chars": len(clipped),
                        "clipped": len(text) > args.max_chars})

    try:
        for url in args.url:
            add_source(url, "url", _fetch_url(url, args.fetch_timeout))
        for path in args.file:
            add_source(path, "file", _read_file(path))
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return fail(f"Datasheet fetch failed (treat as datasheet inaccessible): {exc}", sources)
    except (OSError, RuntimeError) as exc:
        return fail(f"Datasheet read failed (treat as datasheet inaccessible): {exc}", sources)

    datasheet_text = "".join(chunks).strip()
    if not datasheet_text:
        return fail("No datasheet text extracted (treat as datasheet inaccessible).", sources)

    # --- extract (the model reads; the skill judges) ---------------------------
    try:
        parameters = extractor.extract_rf_parameters(datasheet_text, requested)
    except RuntimeError as exc:
        return fail(f"Extraction failed (treat as datasheet inaccessible): {exc}", sources)
    except ValueError as exc:
        return fail(f"Extraction produced no usable JSON: {exc}", sources)

    return _emit({
        "success": True,
        "provider": provider,
        "model": model,
        "parameters": parameters,
        "error": None,
        "sources": sources,
    }, args.raw)


if __name__ == "__main__":
    raise SystemExit(main())

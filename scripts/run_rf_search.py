"""Standalone smoke-test for the rf-skill-json-output skill.

Proves the Claude Agent SDK plumbing works in this project WITHOUT the GUI: it
calls the same ``run_rf_search()`` the "AI Search" button uses, with a sample
spec, and prints the components it returns. If this prints components and
``[done: success]``, the connection and structured output are working, and the
GUI button will use that exact same plumbing.

No ANTHROPIC_API_KEY is required when you are logged into Claude Code — the SDK
uses that existing login. The skill reads datasheets via its own bundled tools
(``tools/run_extract.py`` -> Gemini), so ``tools/rf-llm.env`` must be present in
the skill folder for a full run.

Run:  py scripts/run_rf_search.py
"""

import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")  # keep Windows terminals happy

# Make 'rf_finder' importable when run as a loose script from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rf_finder.agent.skill_runner import run_rf_search

SAMPLE_SPEC = (
    "Component type: amplifier | Gain: >= 20 dB | "
    "freq_range: 14 to 15 GHz | P1dB: >= 24 dBm"
)


async def main() -> None:
    result = await run_rf_search(SAMPLE_SPEC)
    print("\n--- returned structured result ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

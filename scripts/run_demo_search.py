"""Standalone smoke-test for the demo-component-search skill.

Proves the Claude Agent SDK plumbing works in this project WITHOUT the GUI: it
calls the same ``run_demo_search()`` the "AI Search" button uses, with a sample
spec, and prints the components it returns. If this prints the sample
components and ``[done: success]``, the connection and structured output are
working, and the GUI button will use that exact same plumbing.

No ANTHROPIC_API_KEY is required when you are logged into Claude Code — the SDK
uses that existing login.

Run:  py scripts/run_demo_search.py
"""

import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")  # keep Windows terminals happy

# Make 'rf_finder' importable when run as a loose script from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rf_finder.agent.skill_runner import run_demo_search

SAMPLE_SPEC = (
    "Component type: amplifier | Gain: >= 20 dB | "
    "freq_range: 14 to 15 GHz | P1dB: >= 24 dBm"
)


async def main() -> None:
    result = await run_demo_search(SAMPLE_SPEC)
    print("\n--- returned structured result ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

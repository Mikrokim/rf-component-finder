"""The 'work' behind the demo-component-search skill.

Claude runs this script (via the Bash tool) when the skill is invoked. It
prints a small fixed list of sample RF components as JSON. This is the piece a
Skill *does*; SKILL.md only describes it. A real skill would search the web /
manufacturer sites here instead of returning canned data.
"""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")  # keep Windows terminals happy


SAMPLE_COMPONENTS = [
    {
        "model": "HMC451LP3",
        "manufacturer": "Analog Devices",
        "url": "https://www.analog.com/en/products/hmc451lp3.html",
        "verdict": "match",
    },
    {
        "model": "QPA1003",
        "manufacturer": "Qorvo",
        "url": "https://www.qorvo.com/products/p/QPA1003",
        "verdict": "match",
    },
    {
        "model": "PMA3-83LN+",
        "manufacturer": "Mini-Circuits",
        "url": "https://www.minicircuits.com/pdfs/PMA3-83LN+.pdf",
        "verdict": "partial",
    },
]


def main() -> None:
    print(json.dumps({"components": SAMPLE_COMPONENTS}))


if __name__ == "__main__":
    main()

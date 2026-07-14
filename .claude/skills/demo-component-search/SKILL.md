---
name: demo-component-search
description: Returns a small list of sample RF components (a placeholder for a real component search). Use this whenever the user asks to search for or list RF components for a given set of parameters.
---

# Demo Component Search Skill

This skill returns a small, fixed list of sample RF components. It is a
placeholder that proves the search path end to end; it does not really search
the web or the manufacturer sites.

To get the components, run the bundled script:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sample_components.py"
```

The script prints a JSON object with a `components` array — each item has
`model`, `manufacturer`, `url`, and `verdict`. Return exactly those components
as the result.

Always respond in English only. Do not use emoji.

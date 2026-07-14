"""Claude Agent SDK integration for the RF finder.

``skill_runner`` holds the SDK plumbing (``run_agent_skill``) ported from the
proven learning-project wrapper, plus ``run_rf_search`` — which the GUI's "AI
Search" button calls to run the real ``rf-skill-json-output`` skill.
"""

from rf_finder.agent.skill_runner import run_agent_skill, run_rf_search

__all__ = ["run_agent_skill", "run_rf_search"]

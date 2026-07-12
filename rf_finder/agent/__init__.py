"""Claude Agent SDK integration for the RF finder.

``skill_runner`` holds the SDK plumbing (``run_agent_skill``) ported from the
proven learning-project wrapper, plus ``run_demo_search`` — the placeholder the
GUI's "AI Search" button calls until the real ``rf-component-search`` skill is
wired in.
"""

from rf_finder.agent.skill_runner import run_agent_skill, run_demo_search

__all__ = ["run_agent_skill", "run_demo_search"]

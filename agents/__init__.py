"""Agents stage: events + match info in, timed overlays out.

Pipeline (see agents/README.md):
    stats (code) -> director (selects moments) -> explainer (LLM words)
    -> verifier (checks every number and name) -> overlays.json
"""

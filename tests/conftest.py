"""Shared fixtures: a few seeded matches, played once per test session.

Most tests use short matches (2 x 5 min, "short" profile, which boosts rare
events) so the suite stays fast.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator import Match, build_tracking, generate, load_team  # noqa: E402

SHORT = 300  # seconds per half


@pytest.fixture(scope="session")
def validate():
    """scripts/validate.py loaded as a module (reuses its schema checks)."""
    spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def short_match():
    """A short Bosphorus v Thames match containing every event type
    (including a red card and substitutions), with full tracking."""
    m, _ = generate(42, SHORT, "short", "test_short", require_all=True, min_events=100)
    return m, build_tracking(m, 0, m.t)


@pytest.fixture(scope="session")
def styled_match():
    """A short match between the two newer teams, with full tracking."""
    m = Match(11, SHORT, "short", "test_styled", home=load_team("caldera"), away=load_team("saltmarsh"))
    m.play()
    return m, build_tracking(m, 0, m.t)


@pytest.fixture(scope="session")
def full_matches():
    """Full 90-minute matches (events only) over several seeds and pairings."""
    pairs = [("bosphorus", "thames"), ("caldera", "saltmarsh"), ("thames", "caldera"),
             ("saltmarsh", "bosphorus")]
    out = []
    for i, (h, a) in enumerate(pairs * 3):
        m = Match(300 + i, 2700, "full", f"test_full_{i}", home=load_team(h), away=load_team(a))
        m.play()
        out.append(m)
    return out

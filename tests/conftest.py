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


# Seam-2 simulator clips: the first minutes of each half of a full match, cut
# together as the broadcast cuts the break, so kickoff direction and the
# second-half switch are covered. Not the tuning seeds (201-204), though their
# grades were looked at while tuning (vision/README.md). Between them the clips
# hold 7 goals, each followed by a kickoff.
CLIP_SEEDS = [(401, "bosphorus", "thames"), (402, "caldera", "saltmarsh"),
              (403, "saltmarsh", "bosphorus"), (404, "thames", "caldera")]
CLIP_MINUTES = 15                       # from the start of each half


@pytest.fixture(scope="session")
def sim_clips():
    """[(tracking, team sheet, true events in the clip)] for a few seeds and
    pairings, each clip the first CLIP_MINUTES of both halves."""
    out = []
    for seed, home, away in CLIP_SEEDS:
        m = Match(seed, 2700, "full", f"seam2_{seed}", home=load_team(home), away=load_team(away))
        m.play()
        windows = [(p["start"], min(p["end"], p["start"] + CLIP_MINUTES * 60)) for p in m.periods]
        tracking = [fr for start, end in windows for fr in build_tracking(m, start, end)]
        out.append((tracking, m.match_info(),
                    [e for e in m.events if any(start <= e["t"] < end for start, end in windows)]))
    return out

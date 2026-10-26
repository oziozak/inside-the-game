"""Run the agents stage on one match folder.

    python -m agents.run data/fake/sample_a                    # offline, template text
    python -m agents.run data/fake/sample_a --backend noisy    # shows the verifier catching bad numbers
    python -m agents.run data/fake/sample_b --backend foundry  # real LLM on Microsoft Foundry (.env)

Writes data/generated/<match folder>/overlays.json and agents_report.json (both git-ignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from .data_io import load_match, write_overlays
from .director import direct
from .explainer import explain_all
from .llm import make_backend


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", help="folder with match_info.json and events.json")
    ap.add_argument("--backend", default="mock", choices=["mock", "noisy", "foundry"])
    ap.add_argument("--langs", default="en,tr,es", help="comma-separated, e.g. en,tr")
    ap.add_argument("--out", help="output folder (default: data/generated/<data folder name>)")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    t0 = time.perf_counter()
    match = load_match(args.data)
    candidates, decisions = direct(match)
    backend = make_backend(args.backend)
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    overlays, vreport = asyncio.run(explain_all(candidates, match, backend, langs))

    out_dir = Path(args.out or Path("data/generated") / Path(args.data).name)
    write_overlays(overlays, out_dir / "overlays.json")
    report = {
        "match_id": match.info["match_id"],
        "backend": backend.name,
        "events_in": len(match.events),
        "moments_selected": len(candidates),
        "overlays_out": len(overlays),
        "overlays_per_mode": dict(Counter(o["mode"] for o in overlays)),
        "low_confidence_overlays": vreport["low_confidence_overlays"],  # team-named: player uncertain
        "verifier": {"rejected_attempts": len(vreport["rejected"]),
                     "fixed_on_retry": vreport["fixed_on_retry"],
                     "template_fallbacks": vreport["template_fallbacks"],
                     "dropped": len(vreport["dropped"]),
                     "rejections": vreport["rejected"][:20]},
        "seconds": round(time.perf_counter() - t0, 2),
        "director_decisions": decisions,
    }
    (out_dir / "agents_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")

    v = report["verifier"]
    print(f"{report['events_in']} events -> {report['moments_selected']} moments -> "
          f"{report['overlays_out']} overlays {report['overlays_per_mode']}, "
          f"{report['low_confidence_overlays']} naming the team (player uncertain)")
    print(f"verifier: {v['rejected_attempts']} rejected, {v['fixed_on_retry']} fixed on retry, "
          f"{v['template_fallbacks']} template fallbacks, {v['dropped']} dropped")
    print(f"wrote {out_dir / 'overlays.json'} in {report['seconds']} s")


if __name__ == "__main__":
    main()

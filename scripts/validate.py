"""Validate data files against the shared schemas.

Usage:
    python scripts/validate.py              # checks schemas/examples and data/fake
    python scripts/validate.py path/to/dir  # checks one folder

File names decide the schema:
    *match_info*.json   -> match_info
    *events*.json       -> list of events
    *tracking*.jsonl    -> one tracking frame per line
    *overlays*.json     -> list of overlays
    tactics.*json       -> tactical facts (tactics.json, tactics.example.json)
    report.*json        -> match analysis report (report.json; not agents_report.json)
"""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"


def load_validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


VALIDATORS = {
    "match_info": load_validator("match_info"),
    "event": load_validator("event"),
    "tracking": load_validator("tracking"),
    "overlay": load_validator("overlay"),
    "tactics": load_validator("tactics"),
    "report": load_validator("report"),
}


def check_items(kind: str, items: list, path: Path) -> list[str]:
    errors = []
    validator = VALIDATORS[kind]
    for i, item in enumerate(items):
        for err in validator.iter_errors(item):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{path.name} item {i} at {loc}: {err.message}")

    # Extra checks the schema cannot express.
    if kind in ("event", "overlay"):
        ids = [x.get("id") for x in items]
        dupes = {x for x in ids if ids.count(x) > 1}
        if dupes:
            errors.append(f"{path.name}: duplicate ids {sorted(dupes)}")
        key = "t" if kind == "event" else "start"
        times = [x.get(key, 0) for x in items]
        if times != sorted(times):
            errors.append(f"{path.name}: items are not sorted by '{key}'")
    if kind == "report":
        for report in items:
            ids = [i.get("id") for i in report.get("insights", [])]
            if len(ids) != len(set(ids)):
                errors.append(f"{path.name}: duplicate insight ids")
            for i in report.get("insights", []):
                if i.get("hedged") != (i.get("coverage", 0) < report.get("coverage_min", 0)):
                    errors.append(f"{path.name}: {i.get('id')} hedged must be coverage < coverage_min")
    return errors


def kind_of_name(name: str) -> str | None:
    """The schema a file name selects (see the module docstring), or None."""
    if not name.endswith((".json", ".jsonl")):
        return None
    if name.startswith("tactics.") and name.endswith(".json"):
        return "tactics"
    if name.startswith("report.") and name.endswith(".json"):
        return "report"
    for key, kind in (("match_info", "match_info"), ("events", "event"), ("overlays", "overlay")):
        if key in name and name.endswith(".json"):
            return kind
    return "tracking" if "tracking" in name and name.endswith(".jsonl") else None


def check_file(path: Path) -> list[str]:
    kind = kind_of_name(path.name)
    if kind is None:
        return []
    if kind == "tracking":
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return check_items("tracking", [json.loads(l) for l in lines], path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return check_items(kind, data if kind in ("event", "overlay") else [data], path)


def main() -> int:
    targets = [Path(a) for a in sys.argv[1:]] or [SCHEMAS / "examples", ROOT / "data" / "fake"]
    files = [f for t in targets if t.exists() for f in sorted(t.rglob("*")) if f.is_file()]
    all_errors, checked = [], 0
    for f in files:
        errs = check_file(f)
        if errs or kind_of_name(f.name):
            checked += 1
        all_errors.extend(errs)

    for e in all_errors:
        print("ERROR", e)
    print(f"Checked {checked} file(s): {'OK' if not all_errors else f'{len(all_errors)} error(s)'}")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())

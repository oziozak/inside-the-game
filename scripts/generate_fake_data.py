#!/usr/bin/env python3
"""Rebuild the committed sample data in data/fake/ with the simulator package.

Thin wrapper around simulator.samples; see that module for details.

Usage:
    python scripts/generate_fake_data.py                 # writes data/fake/
    python scripts/generate_fake_data.py --full-tracking # + data/generated/
    python scripts/generate_fake_data.py --seed 7 --report
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.samples import main  # noqa: E402

if __name__ == "__main__":
    main()

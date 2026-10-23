"""`python -m vision VIDEO --out EVENTS.json`: the tracer (see vision/pipeline.py)."""

import sys

from vision.pipeline import main

sys.exit(main())

The full project brief is in `AGENTS.md` at the repository root. Read it before making changes.

Most important rules:

1. `schemas/` is the contract between all parts. Match it exactly; run `python scripts/validate.py` on any data you produce.
2. The vision AI only sees video frames. It never reads simulator data at runtime.
3. Every number shown on screen is computed by code, never written by an LLM. Overlays cite the `event_ids` they are based on.
4. Fictional clubs and players only. No real Premier League names, logos or footage.
5. No secrets (`.env`) and no large generated files (videos, frames, weights) in git.

Conventions: `t` is seconds since kick-off; positions are meters on a 105 x 68 pitch with origin at the bottom-left; home attacks toward x = 105 in the first half.

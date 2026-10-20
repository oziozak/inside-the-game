# Shared data formats

These four formats are the contract between all parts of the project. **Do not change them without telling the whole team**, because every part reads or writes them.

| Format | File | Written by | Read by |
| --- | --- | --- | --- |
| Match info | `match_info.schema.json` | Simulator | Everyone |
| Event | `event.schema.json` | Vision AI (`source: cv`), simulator (`source: sim`) | Stats, agents |
| Tracking | `tracking.schema.json` | Vision AI, simulator | Stats, web player |
| Overlay | `overlay.schema.json` | Director agent | Web player |

Examples of each are in [`examples/`](examples/).

## Conventions

- **Time:** `t` is seconds since kick-off, as a decimal. 2052.4 = 34:12.4. Convert to `mm:ss` only when displaying.
- **Positions:** meters on a 105 x 68 m pitch. `(0, 0)` is the bottom-left corner. `x` runs goal to goal (0-105), `y` sideline to sideline (0-68).
- **Ball height:** tracking `ball` is `[x, y, z]`; `z` is meters above the grass.
- **Player ids:** unique across both teams. Home 1-99, away 101-199.
- **Event ids:** `e` + 4 digits (`e0412`). Overlay ids: `o` + 4 digits.
- **Files:** events and overlays are JSON arrays sorted by time. Tracking is JSON Lines (one frame per line) because it is large.
- **Numbers on screen come from code, never from the LLM.** Overlays put them in `values`.

## Event types

`kickoff`, `pass`, `possession_change`, `clearance`, `throw_in`, `shot`, `free_kick`, `foul`, `goal_kick`, `corner`, `substitution`, `offside`, `yellow_card`, `red_card`, `goal`, `half_time`, `full_time`.

Optional `subtype` adds detail: pass `short|long|cross|through`, possession_change `tackle|interception`, shot `on_target|off_target|blocked`, goal `open_play|penalty|own_goal`.

## Validate

```bash
pip install jsonschema
python scripts/validate.py
```

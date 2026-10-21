# Simulator

**Owner:** Ozan

Python match engine. Generates a fictional match and writes, following the
shared schemas in [`schemas/`](../schemas/):

- `match_info.json`: teams, kits, lineups, formations, styles, when each half starts and ends
- `events.json`: true events (`source: sim`), sorted by `t`
- `tracking.jsonl`: positions of all players and the ball, 25 fps, one frame per line

These files feed the renderer (video) and are the **ground truth** the vision
AI is graded against. Everything is seeded: the same arguments always give
byte-identical files.

## Command line

```bash
python -m simulator --home bosphorus --away thames --seed 7 --half-length 45 \
    --out data/generated/m007 [--no-tracking] [--start 0 --end 600]
```

| Option | Meaning |
| --- | --- |
| `--home`, `--away` | team keys = file names in `simulator/teams/` (`bosphorus`, `thames`, `caldera`, `saltmarsh`) |
| `--seed` | random seed (default 1) |
| `--half-length` | minutes per half (default 45) |
| `--profile` | `full` (realistic, default) or `short` (rare events boosted so a few minutes contain every event type) |
| `--out` | output folder (use `data/generated/...`; it is ignored by git) |
| `--match-id` | match id written into every event and frame (default: the output folder name) |
| `--no-tracking` | skip `tracking.jsonl` |
| `--start`, `--end` | tracking window in seconds (default: the whole match). Players start the window at their formation spots. |

A full 90-minute match with tracking (~135,000 frames, ~140 MB) takes about
8.5 s on an Apple M2 Pro.

Other entry points:

```bash
python scripts/generate_fake_data.py [--full-tracking] [--report]   # rebuild data/fake/
python -m simulator.realism --matches 40                            # realism report (below)
pytest                                                              # tests in tests/
```

From Python:

```python
from simulator import Match, load_team, iter_tracking
m = Match(7, 2700, "full", "m007", home=load_team("bosphorus"), away=load_team("thames"))
m.play()                       # m.events, m.match_info()
for frame in iter_tracking(m, 0, m.t):
    ...
```

## How it works

Two layers. The event layer decides **what** happens; the movement layer
decides **where everyone is** in every frame. The movement layer never
changes an event.

### Event layer (`engine.py`, class `Match`)

The player on the ball repeatedly picks an action with weighted dice:
hold, dribble, short / long / through pass, cross, shot or clearance. The
weights depend on where he is (own box, build-up, midfield, final third,
the box), on his team's **style**, and for shots on the profile. Success is
random too, shaped by the players' **attributes** and the opponent's style:

- a pass reaches a teammate, is intercepted by the defender closest to its
  path, or goes out of play;
- a dribble can be challenged: a tackle (`possession_change`), a `foul`,
  or the carrier rides it;
- a shot is a goal (chance falls off with distance, a simple xG curve),
  saved, off target or blocked.

Basic football rules then follow: throw-ins, corners and goal kicks when
the ball goes out, free kicks and penalties after fouls, yellow and red
cards (never below 7 players: then the card is downgraded, or not shown if
it would be a second yellow), offside on balls in behind, kickoffs after
goals, substitutions at dead balls between 58' and 82', and half-time,
where the teams swap ends (home attacks toward x = 105 in the first half).
A failed pass cut out in the first 30% of its path by a defender who was
within 10 m counts as an interception (`possession_change`).

Besides events, the Match records what the movement layer needs: the ball
path (with flight height), who carries the ball when, planned runs
(receivers, interceptors, tacklers, set-piece takers) and who is on the
pitch when (spans end and start exactly at red-card and substitution
event times).

### Movement layer (`movement.py`, `iter_tracking`)

Every player has a formation slot (team JSON, in the team's own frame).
Each frame (25 fps):

- the team shape shifts with the ball (with a 0.8 s delay) and pushes up
  when the team has the ball; a defending team also moves its block up or
  down by its style's line height;
- the ball carrier stays 0.6 m behind the ball; pass receivers,
  interceptors, tacklers and set-piece takers run to where the ball goes;
- pressing players close down the carrier but stop 3.5 m short;
- before a kickoff everyone except the taker waits in his own half;
- speed is capped: 7 m/s with the shape, the player's sprint speed on a
  run (from pace: 9.5 m/s at 70, 8.6-10.4 m/s), his speed with the ball
  (10.5 m/s at 70, at most 10.65 m/s).

At half-time the broadcast cuts: everyone is re-placed for the second half
(the only place where a player "jumps").

## Teams

Teams live in `simulator/teams/<key>.json`. All teams and players are fictional.

| Key | Team | Formation | Style | Kit |
| --- | --- | --- | --- | --- |
| `bosphorus` | Bosphorus FC | 4-3-3 | possession | red / white |
| `thames` | Thames United | 4-4-2 | counter | blue |
| `caldera` | Caldera SC | 4-2-3-1 | pressing | orange / black |
| `saltmarsh` | Saltmarsh FC | 5-3-2 | direct | green / white |

### Styles (`config.STYLES`)

All knobs are relative to `balanced`, which is exactly the base model.

| Style | Action weights | Tempo (hold time) | Defensive line | Press |
| --- | --- | --- | --- | --- |
| balanced | - | x1.0 | 0 m | 0 |
| possession | short x1.3, long x0.6, through x0.8 | x0.9 | +3 m | 0.3 |
| counter | long x1.15; for 8 s after winning the ball through x2.0, long x1.3, dribble x1.3 | x1.0 | -5 m | 0.1 |
| pressing | through x1.1 (x1.3 after winning it) | x0.85 | +5 m | 0.6 |
| direct | long x2.0, cross x1.3, short x0.9 | x0.85 | 0 m | 0.4 |

- **Defensive line** moves the outfield block up or down while the other
  team has the ball. A high line is easier to beat in behind: the
  opponent's offside chance is multiplied by 1 + 0.08 per meter and their
  through-ball success by 1 + 0.015 per meter.
- **Press** (0-1): opponent dribbles are challenged x(1 + 0.6 x press) as
  often, opponent short passes lose 3 x press percentage points, and
  round(3 x press) players close down the carrier in tracking.

Measured against the same team playing `balanced` (tests in
`tests/test_styles.py`): possession +20% passes, counter +30% through
balls and fewer opponent offsides, pressing +25% tackles and fouls and
more opponent offsides, direct a larger share of long balls and crosses.

### Player attributes (`config.py`)

Each player has `passing`, `shooting`, `pace`, `tackling` (0-100). 70 is
the league average and changes nothing; a missing attribute is 70.

| Attribute | Effect per point above 70 |
| --- | --- |
| passing | +0.4 percentage points pass success (all pass-like deliveries) |
| shooting | goal chance x(1 + 1.5%) (penalties 0.5%) |
| tackling | +0.4 percentage points share of challenges won |
| pace | sprint +0.03 m/s (9.5 at 70, max 10.4), with the ball +0.005 m/s (max 10.65) |

Ratings follow the position (forwards shoot better, defenders tackle
better). Each attribute's outfield average must stay within 60-80, and the
realism report checks that the match totals stay inside the norms.

### Adding a team

1. Copy `simulator/teams/thames.json` to `simulator/teams/<key>.json`.
2. Set `name`, `short` (max 4 letters), `formation` (outfield lines adding
   up to 10), `style` (a key of `config.STYLES`), `kit` and `away_kit` (hex
   colors for `shirt`, `shorts`, `goalkeeper`).
3. List 11 starters (exactly one `GK`) with a `slot` `[x, y]` each, and the
   substitutes (no slot). Slots are in the team's own frame: own goal at
   x = 0, attacking toward x = 105, ball on the center spot; facing +x, the
   team's right side is low y. Positions: `GK RB CB LB RWB LWB DM CM AM RM LM
   RW LW ST CF`. Shirt numbers 1-99, unique. Invented names only.
4. Give every player the four attributes.
5. Check: `pytest tests/test_teams.py` (loads, validates and checks that
   no pairing has a kit clash) and `python -m simulator.realism --matches 40`
   (the new shape and style keep every norm). If interceptions or goal kicks
   drift, spread the shape (compact shapes near the opponent's build-up
   create more interceptions).

**Kit clashes:** the home team always wears its `kit`. The away team
switches to its `away_kit` if the shirts are too close in RGB (< 140), or a
keeper is too close to the other team's shirts or keeper (< 100): the
vision AI tells teams apart by color.

## What the realism checks guarantee

`python -m simulator.realism --matches 40` plays 40 full matches (seed
1000 + i, cycling all 12 ordered pairings of the 4 teams, in parallel and
deterministic) and exits with code 1 if any check fails:

| Check | Guarantee |
| --- | --- |
| Event means | Every event type with a norm averages inside its real-football range per 90 min (`config.NORMS`: ~850-1050 passes, 20-30 shots, 1-5 goals, 8-13 corners, 18-26 fouls...). Prints mean and sd for all 17 types. |
| Pass accuracy | Mean share of successful passes is 75-87% (about 81%). |
| Max speed | No player moves faster than 11 m/s between two frames, except across the half-time cut: nobody teleports. |
| Nearest player | At >= 95% of passes and shots (about 97%), the player nearest the ball at the event's frame is the event's player, so the vision AI can use "nearest player has the ball". |
| Set pieces | Every kickoff, throw-in, corner, goal kick and free kick taker is within 1 m of the ball when he takes it. |
| Players on pitch | 7-11 players per team in every frame. |
| Ball on pitch | The ball is always within 1 m of the pitch. |

The tests (`pytest`) add: byte-identical output for the same seed (also
across processes), schema validity, unique sorted event ids, scores that
match the goals, teams swapping ends at half-time, red-carded players
leaving tracking at the card, substitutes appearing only after their
substitution, and every event type occurring with the `short` profile.

Known limits: the base model is calibrated, not fitted to real data. Goal
kicks (~16 per match) sit near the bottom of their norm, and goals (~3.6)
near the top.

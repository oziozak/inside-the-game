"""Lineup assignment: anonymous tracks -> roster player ids, from the team sheet.

Part of the event stage: it sees only frame observations and the team sheet.

- **At each kickoff**, each team's tracks are matched to its starters by
  formation geometry, on the frame just before the ball is played (on a
  period's first frame players may not be lined up yet). The goalkeeper is
  the track in the keeper's kit; the outfield is matched to where each
  position typically stands (SLOT, held in the team's own half): the back
  line ordered by side, and so on through midfield and attack. Both shapes
  are centered first, so a team standing higher or deeper still matches. The
  kickoff taker stands on the center spot, not in their slot, and gets the
  starter left over.
- **In play**, each track's place in its team's shape (its position relative
  to the team's outfield centroid) is averaged over the last SHAPE_S. Every
  REFINE_S, and at each kickoff, the named tracks with SHAPE_MIN_S of shape
  swap names among themselves to fit SLOT best. One frame cannot tell apart
  players who stand together at a kickoff (a striker and an attacking
  midfielder both held on the halfway line); their shapes in play can.
- **Between kickoffs**, a track nobody is named for (a track lost, swapped or
  merged comes back under a new id) takes the roster id of a player of its
  team whose track is missing from the frame, the one last seen nearest, if
  that player could have run there since (REMATCH_M plus RUN_V per second
  missing). A named track whose kit stops fitting its name (the tracker
  swapped it onto a player of the other team, or a keeper) gives the name up
  and is matched again, so the two tracks of a swap trade names. An unnamed
  track standing on a named one of the same kit is a second box on that
  player (its twin) and answers to that name.

Substitutes are never named: who comes on is invisible to video in v1, so a
substitute's track takes the name of the player who went off.
"""

from __future__ import annotations

import math

from vision.observation import PlayerObservation

# Where each position stands in play, in its team's frame: attacking toward
# x = 105, so the right side is y < 34. At a kickoff x is held to KICKOFF_X.
SLOT = {"GK": (4, 34), "CB": (24, 34), "RB": (30, 12), "LB": (30, 56),
        "RWB": (40, 8), "LWB": (40, 60), "DM": (38, 34), "CM": (44, 34),
        "RM": (46, 12), "LM": (46, 56), "AM": (50, 34),
        "RW": (60, 10), "LW": (60, 58), "ST": (62, 34), "CF": (62, 34)}
KICKOFF_X = 51.0            # at a kickoff everyone waits in their own half
SPREAD_M = 12.0             # players sharing a slot stand this far apart, right to left in roster order
KIT_COST = 1e6              # matching a keeper's track to an outfield player, or the reverse
SHAPE_S = 60.0              # a track's place in the shape is averaged over about this long
SHAPE_MIN_S = 4.0           # ... and used once it has been seen this long
REFINE_S = 2.0              # named tracks swap names to fit the shape this often
REMATCH_M = 3.0             # a new track takes a missing player's name only this near where they were last seen ...
RUN_V = 8.0                 # ... plus this many meters per second they have been missing
TWIN_M = 1.0                # an unnamed track this near a named one of the same kit is a second box on that player
FPS = 25


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of rows to distinct columns (rows <= columns).
    Returns the column of each row."""
    n, m = len(cost), len(cost[0]) if cost else 0
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    owner = [0] * (m + 1)                       # owner[j]: the row (1-based) holding column j
    for i in range(1, n + 1):
        owner[0], j0 = i, 0
        low, way, used = [math.inf] * (m + 1), [0] * (m + 1), [False] * (m + 1)
        while owner[j0]:
            used[j0] = True
            i0, delta, j1 = owner[j0], math.inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    c = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if c < low[j]:
                        low[j], way[j] = c, j0
                    if low[j] < delta:
                        delta, j1 = low[j], j
            for j in range(m + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    low[j] -= delta
            j0 = j1
        while j0:
            j1 = way[j0]
            owner[j0], j0 = owner[j1], j1
    col = [0] * n
    for j in range(1, m + 1):
        if owner[j]:
            col[owner[j] - 1] = j - 1
    return col


def _pairs(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Minimum-cost one-to-one (row, column) pairs; the longer side keeps some unpaired."""
    if not cost or not cost[0]:
        return []
    if len(cost) <= len(cost[0]):
        return list(enumerate(_hungarian(cost)))
    return [(r, c) for c, r in enumerate(_hungarian([list(col) for col in zip(*cost)]))]


def formation_slots(players: list[dict]) -> dict[int, tuple[float, float]]:
    """Each starter's slot in play (team frame) from its position. Starters
    sharing a slot (two center backs, a striker pair) spread across it, right
    to left in the order the team sheet lists them."""
    groups: dict[tuple[float, float], list[int]] = {}
    for p in players:
        if p["starter"]:
            groups.setdefault(SLOT[p["pos"]], []).append(p["id"])
    slots = {}
    for (x, y), ids in groups.items():
        for k, pid in enumerate(ids):
            slots[pid] = (x, y + (k - (len(ids) - 1) / 2) * SPREAD_M)
    return slots


def _centroid(points) -> tuple[float, float]:
    """The mean of some points ((0, 0) for none)."""
    points = list(points)
    if not points:
        return 0.0, 0.0
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


class Lineup:
    """Names tracks with roster ids. Call `observe` every frame and `assign`
    at each kickoff; `player(track_id)` is the roster id, or None."""

    def __init__(self, team_sheet: dict):
        self.length, self.width = team_sheet.get("pitch", [105, 68])
        sides = ("home", "away")
        self.keepers = {p["id"] for side in sides for p in team_sheet[side]["players"] if p["pos"] == "GK"}
        self.team_of = {p["id"]: side for side in sides for p in team_sheet[side]["players"]}
        slots = {side: formation_slots(team_sheet[side]["players"]) for side in sides}
        # Slots relative to the outfield centroid, in play and at a kickoff.
        self.play_slots, self.kickoff_slots = {}, {}
        for side in sides:
            outfield = {pid: s for pid, s in slots[side].items() if pid not in self.keepers}
            held = {pid: (min(x, KICKOFF_X), y) for pid, (x, y) in slots[side].items()}
            self.play_slots[side] = self._relative(slots[side], outfield)
            self.kickoff_slots[side] = self._relative(held, {pid: held[pid] for pid in outfield})
        self.player_of: dict[int, int] = {}                  # track -> roster id
        self.track_of: dict[int, int] = {}                   # roster id -> track
        self.last_pos: dict[int, tuple[float, float]] = {}   # roster id -> last seen position
        self.last_seen: dict[int, float] = {}                # roster id -> when (none: a slot guess)
        self.t = 0.0                                         # the latest frame's time
        self.shape: dict[int, list[float]] = {}              # track -> [frames, x, y] relative to its team
        self.twin: dict[int, int] = {}                       # unnamed track -> the named track it doubles, when last seen
        self.last_refine = -math.inf

    def player(self, track_id: int | None) -> int | None:
        """The roster id a track is named for (or, for an unnamed track, the
        one its twin is named for), or None."""
        return self.player_of.get(track_id, self.player_of.get(self.twin.get(track_id)))

    def names(self, players: list[PlayerObservation]) -> dict[int, int]:
        """Track id -> roster id for the tracks among `players` named now (twins included)."""
        return {p.track_id: pid for p in players if (pid := self.player(p.track_id)) is not None}

    # ---- at a kickoff ----------------------------------------------------
    def assign(self, players: list[PlayerObservation], home_attacks_right: bool,
               taker: int | None = None) -> None:
        """Name every track by formation geometry, then let tracks with a
        shape in play swap names to fit it (see the module docstring).
        `taker` is the track on the center spot, if any. A starter with no
        track in the frame is last known at their slot, for re-matching."""
        self.player_of, self.track_of = {}, {}
        for side, (rel, center) in self._team_shapes(players, home_attacks_right).items():
            tracks = [p for p in players if p.team == side]
            shaped = [p for p in tracks if p.track_id != taker]
            for p, pid in self._match(shaped, {p.track_id: rel[p.track_id] for p in shaped},
                                      self.kickoff_slots[side]):
                self._name(p, pid)
            left = [pid for pid in self.kickoff_slots[side]
                    if pid not in self.track_of and pid not in self.keepers]
            t = next((p for p in tracks if p.track_id == taker and not p.goalkeeper), None)
            if t is not None and left:                  # the most advanced starter left over
                self._name(t, max(left, key=lambda pid: self.play_slots[side][pid][0]))
            right = home_attacks_right == (side == "home")
            for pid, (x, y) in self.kickoff_slots[side].items():
                if pid not in self.track_of:
                    self.last_pos[pid] = self._team_frame((center[0] + x, center[1] + y), right)
                    self.last_seen.pop(pid, None)
        self._refine(players)

    # ---- every frame -----------------------------------------------------
    def observe(self, t: float, players: list[PlayerObservation], home_attacks_right: bool) -> None:
        """One frame: name new tracks after missing players, follow each track's
        place in its team's shape, and every REFINE_S let named tracks swap
        names to fit the formation."""
        self.t = t
        self._rematch(players)
        for side, (rel, _) in self._team_shapes(players, home_attacks_right).items():
            for tid, (x, y) in rel.items():
                s = self.shape.setdefault(tid, [0, x, y])
                s[0] += 1
                a = max(1 / s[0], 1 / (SHAPE_S * FPS))
                s[1] += a * (x - s[1])
                s[2] += a * (y - s[2])
        if self.player_of and t - self.last_refine >= REFINE_S:
            self.last_refine = t
            self._refine(players)

    def _rematch(self, players: list[PlayerObservation]) -> None:
        """Name tracks nobody is named for after players of their team whose
        track is missing from the frame, nearest last-known position first. A
        track still unnamed standing on a named one of the same kit is its twin
        (the detector boxed one player twice), as last seen."""
        live = {p.track_id for p in players}
        new = []
        for p in players:
            pid = self.player_of.get(p.track_id)
            if pid is not None and not self._fits(p, pid):
                self._unname(p.track_id)            # swapped with a player of another kit
                pid = None
            if pid is None:
                new.append(p)
            else:
                self.last_pos[pid], self.last_seen[pid] = p.pos, self.t
        # Missing: players seen before whose track is not in the frame (or who
        # were missing from the last kickoff's frame, so have no track).
        missing = [pid for pid in self.last_pos if self.track_of.get(pid) not in live]
        pairs = sorted((math.dist(p.pos, self.last_pos[pid]), i, pid)
                       for i, p in enumerate(new) for pid in missing
                       if self._fits(p, pid) and self._reachable(p, pid))
        done = set()
        for _, i, pid in pairs:
            if i not in done and self.track_of.get(pid) not in live:
                done.add(i)
                self._name(new[i], pid)
                live.add(new[i].track_id)
        named = [p for p in players if p.track_id in self.player_of]
        for p in new:
            self.twin.pop(p.track_id, None)
            if p.track_id not in self.player_of:
                q = min((q for q in named if (q.team, q.goalkeeper) == (p.team, p.goalkeeper)),
                        key=lambda q: math.dist(p.pos, q.pos), default=None)
                if q is not None and math.dist(p.pos, q.pos) <= TWIN_M:
                    self.twin[p.track_id] = q.track_id

    def _refine(self, players: list[PlayerObservation]) -> None:
        """Named tracks in the frame with a shape of at least SHAPE_MIN_S swap
        names among themselves to fit their team's slots in play."""
        for side in ("home", "away"):
            ready = [p for p in players if p.team == side and p.track_id in self.player_of
                     and self.shape.get(p.track_id, [0])[0] >= SHAPE_MIN_S * FPS]
            names = {self.player_of[p.track_id] for p in ready}
            slots = {pid: s for pid, s in self.play_slots[side].items() if pid in names}
            shapes = {p.track_id: tuple(self.shape[p.track_id][1:]) for p in ready}
            for p, pid in self._match(ready, shapes, slots):
                self.player_of[p.track_id] = pid
                self.track_of[pid] = p.track_id

    # ---- helpers ---------------------------------------------------------
    def _match(self, tracks: list[PlayerObservation], where: dict, slots: dict) -> list[tuple]:
        """(track, roster id) pairs fitting each track's relative position to
        a relative slot at least squared distance; keepers' kit must agree."""
        ids = list(slots)
        cost = [[(where[p.track_id][0] - slots[pid][0]) ** 2 + (where[p.track_id][1] - slots[pid][1]) ** 2
                 + (KIT_COST if p.goalkeeper != (pid in self.keepers) else 0.0)
                 for pid in ids] for p in tracks]
        return [(tracks[r], ids[c]) for r, c in _pairs(cost)]

    def _team_shapes(self, players: list[PlayerObservation], home_attacks_right: bool) -> dict:
        """Per team: (track -> position in its team's frame relative to the
        team's outfield centroid, that centroid)."""
        out = {}
        for side in ("home", "away"):
            right = home_attacks_right == (side == "home")
            mine = {p.track_id: self._team_frame(p.pos, right) for p in players if p.team == side}
            if mine:
                center = _centroid(mine[p.track_id] for p in players
                                   if p.team == side and not p.goalkeeper)
                out[side] = ({k: (x - center[0], y - center[1]) for k, (x, y) in mine.items()}, center)
        return out

    @staticmethod
    def _relative(points: dict, outfield: dict) -> dict:
        """Points relative to the centroid of the outfield ones."""
        cx, cy = _centroid(outfield.values())
        return {k: (x - cx, y - cy) for k, (x, y) in points.items()}

    def _fits(self, p: PlayerObservation, pid: int) -> bool:
        """Whether track `p`'s kit (team, keeper or not) is roster player `pid`'s."""
        return self.team_of[pid] == p.team and (pid in self.keepers) == p.goalkeeper

    def _reachable(self, p: PlayerObservation, pid: int) -> bool:
        """Whether roster player `pid` could have run to track `p` since last
        seen (always, for a slot guess). A track far from every missing player
        (a duplicate of a tracked one, or a false detection) stays unnamed."""
        if pid not in self.last_seen:
            return True
        reach = REMATCH_M + RUN_V * (self.t - self.last_seen[pid])
        return math.dist(p.pos, self.last_pos[pid]) <= reach

    def _unname(self, track_id: int) -> None:
        """Track `track_id` is nobody from now on: its player is missing, last
        seen where the track last was under their name, and its shape restarts."""
        pid = self.player_of.pop(track_id)
        if self.track_of.get(pid) == track_id:
            del self.track_of[pid]
        self.shape.pop(track_id, None)

    def _name(self, p: PlayerObservation, pid: int) -> None:
        """Track `p` is roster player `pid` from now on."""
        old = self.track_of.get(pid)
        if old is not None:
            self.player_of.pop(old, None)
        self.player_of[p.track_id] = pid
        self.track_of[pid] = p.track_id
        self.last_pos[pid], self.last_seen[pid] = p.pos, self.t

    def _team_frame(self, pos, attacks_right: bool) -> tuple[float, float]:
        """A position in its team's frame (attacking toward x = length)."""
        return (pos[0], pos[1]) if attacks_right else (self.length - pos[0], self.width - pos[1])

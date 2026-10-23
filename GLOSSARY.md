# Inside the Game

Explainable match intelligence for a fictional football match: an AI watches a synthetic match video, detects what happens, and decides which graphic to show, when, and for whom.

## Language

### Events

**True event**:
An event as the simulator generated it (`source: sim`): the ground truth of what happened in the match.
_Avoid_: Real event, ground-truth event, sim event

**Detected event**:
An event the vision AI found in the video on its own (`source: cv`), with a confidence below 1.
_Avoid_: CV event, predicted event, inferred event

### Vision

**Frame observation**:
Everything the vision AI saw in one video frame, in pitch meters: the ball's ground position and visibility, and each detected player as a track with its team and goalkeeper flag.
_Avoid_: Detection frame, observation row

**Track**:
An anonymous identity the vision AI keeps for one detected person across frames; it says nothing about who that person is.
_Avoid_: Player id, ID (a track id is never a roster player id)

**Player**:
A person on a team's roster, identified by a player id from the team sheet.
_Avoid_: Track, athlete

**Team sheet**:
The pre-match information a broadcaster would have: both teams' rosters, kits and formations, the pitch size and the periods (`match_info.json`).
_Avoid_: Lineup file, metadata, roster file

**Lineup assignment**:
The mapping from tracks to players, made from the team sheet's formation at each kickoff and kept up when tracks are lost or swapped.
_Avoid_: Identity matching, re-identification, player mapping

**Possession**:
The player nearest the ball while the ball is at ground level and within reach, for a moment (not a ball flying past). From frame observations, which have no ball height, "at ground level" means the ball moves with the track.
_Avoid_: Control, ball ownership

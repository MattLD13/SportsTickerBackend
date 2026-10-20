# Ticker-owned live game counts

## Diagnosis

The real Six data response contained one live NBA game and sixteen pregame records.
Its schedule metadata reported three live games.
The server counted identifiers across every ticker snapshot.
Other devices could therefore raise this ticker's live-game threshold count.
The read-only diagnostic did not change device settings or schedules.

## Behavior owners

`ScheduleService.live_game_count` now counts one ticker's latest snapshot.
It excludes hidden records, other content families, pregame records, stale snapshots, future snapshots, and duplicate game identifiers.
The threshold comparison remains explicit: More than uses `gt`, and At least uses `gte`.
The schedule document uses the same count as its effective status.
The old fleet-wide count path is removed.

`ScheduleService.resolve` owns `has_enabled_rules` in the V2 schedule status.
It checks enabled time blocks and live-sports conditions for this ticker's supported modes.
An enabled block outside its current time range still counts as configured.
Disabled rules and another ticker's rules do not count.
The contract schema, JSON fixtures, Swift model, and production preview include the field.
Home and calendar controls hide schedule override actions when the field is false.
The rule editor shows the selected ticker's current live-game count.
The single-rule button opens its editor directly. Multiple saved rules retain a selection menu.

## Evidence

The regression creates one ticker with one live game and another with ten live games.
A More than one rule stays inactive for the first ticker.
A second local live game activates the rule.
Finishing that second game restores the original All games filter.
Separate cases cover duplicate identifiers, hidden games, stale observations, and future timestamps.
Presence checks cover empty schedules, disabled rules, enabled blocks, and enabled conditions.
The existing paired device and pinned-game precedence checks remain in the test suite.

Focused API and offline contract checks passed 68 tests.
The full repository suite passed 1,090 tests, with ten skips.
The critical suite passed 740 tests, with ten skips and 350 deselected tests.
The Six sports renderer produced an inspected 384 by 32 frame.
Swift package checks passed in Debug and Release.
The five focused simulator checks passed, including empty schedules, disabled schedules, live-rule editing, and override recovery.
The Release simulator build passed.

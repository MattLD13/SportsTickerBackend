# Sports lifecycle and football scoring data

## Owners

`sports_ticker/providers/sports_display.py` owns shared lifecycle and live-play facts.
The V2 projection calls `project_sports_display` after provider enrichment.
`game_phase` identifies scheduled, playing, break, halftime, shootout, paused, final, and unavailable states.

`sports_ticker/providers/espn.py` owns football play identity, player names, yardage, clock, score totals, and drive context.
`sports_ticker/providers/score_alerts.py` binds that play data to each observed score increase.
`ticker_core/rendering/fonts.py` owns the bundled alert headline font.

## Former paths removed

- The football cache previously copied whole situations across possession, period, and score changes.
- The V2 projection previously cleaned only baseball inning transitions.
- Football alerts previously selected the latest team scoring play without matching its score.
- Alert details previously read the next drive's down and red-zone fields.
- College scoring text lost receiver names and yardage when it used `pass to` and `yds`.
- Scoring alerts skipped scores that first appeared with a final result.
- The alert renderer selected system fonts through a separate fallback list.

## Shared sports behavior

| Family | Behavior |
|---|---|
| Baseball | Preserve three-out inning breaks, cleared runners, and provider-confirmed next halves. |
| NFL, FBS, FCS | Clear stale down, possession, and red-zone facts during breaks. Keep untimed college overtime active. |
| NBA and college basketball | Respect period-end and halftime states. Require provider confirmation for final results and further overtime. |
| NHL | Clear live PP and EN badges during intermissions and shootouts. Preserve shootout results and further playoff overtime. |
| Soccer | Preserve stoppage time, extra time, cards, and goal history. Show penalties before a stale extra-time clock. |
| Golf | Preserve the provider's round and progress. Do not infer tournament completion from one player's finished round. |
| F1, IndyCar, IMSA, WEC | Preserve provider session state. Do not infer a final result from the last lap or a red flag. |

The backend sends cleaned facts to both ticker families. Existing Mini firmware can render these facts without an update.
The projection leaves source snapshots, settings, scores, and historical events intact.

## Football alert behavior

- Match scoring detail to the scoring team's observed total.
- Use matching drive IDs to obtain the scoring down and field position.
- Resolve abbreviated names only when the same team's boxscore gives one match.
- Separate touchdown scorers from extra-point and two-point conversion players.
- Keep the scoring clock separate from the next drive's clock.
- Fill delayed detail without changing alert identity or creation time.
- Reject missed, failed, reversed, and no-play records as scoring detail.
- Keep a touchdown when only its conversion fails.
- Preserve a generic two-point score when the provider supplies no scoring type.
- Accept a new winning score at final. Do not replay the same alert after a score correction.
- Render goal-to-go downs as `1&G` through `4&G` beside the scoring clock.

## Real input and output

The capture fixture contains public ESPN summaries for NFL game `401872995` and college game `401858263`.
It retains scoring records, matching drive fields, and boxscore identities.

| Captured input | Normalized alert output |
|---|---|
| Jason Myers 55-yard field goal | FIELD GOAL, Jason Myers, 55YD, Q1 6:31, 4&5 |
| Mark Fletcher Jr. 7-yard touchdown | RUSH TD, Mark Fletcher Jr., 7YD, Q1 7:32, 1&G |
| Desirrio Riles 23-yard reception | PASS TD, Desirrio Riles, 23YD PASS Ashton Daniels, Q2 13:52 |
| Malachi Toney 14-yard reception | PASS TD, Malachi Toney, 14YD PASS Darian Mensah, Q2 8:19 |
| Wil Lutz 53-yard winning field goal | FIELD GOAL, Wil Lutz, 53YD, OT 4:53, 4&2 |

## Validation

- The full Python suite passes 741 tests. The critical suite passes 408 tests.
- Captured scoring ledgers pass through the tracker, snapshot projection, and Pi response decoder.
- Lifecycle cases cover all configured sport families and both device projections.
- The physical Pi runs the native Mini renderer for 11 controlled sports cases.
- Ten 384x32 football alert frames match exactly between the PC and physical Pi.
- Four frozen production frames retain their approved hashes.
- Python compilation, Ruff, public demo assets, and generated Mini contracts pass.

Evidence is in `previews/sports-intelligence/`.
These checks use captured provider data and controlled replays. They do not inject fake games into either running ticker.

# NFL alert repair and agent comparison

Date: 2026-10-19

## Result

The blind reviewer selected the context-planned candidate as the stronger repair basis.
Neither original candidate passed every independent check.
The final change uses that basis and repairs the defects found during review.
The reviewer accepted the final snapshot with no material findings.

The new context method did not save tokens in this task.
It reduced peak coding context by 12.0%, but successful planning and coding used 22.1% more tokens.
This single task does not establish a general advantage for either method.

## Controlled setup

- Both coding agents used GPT-6.1 Sol with high reasoning and fresh context.
- Both started from `9c8e7035e6431ca570639e6a8d8a90ab8622ee8a` source contents.
- Both received identical current `AGENTS.md` files and engineering rules.
- Both received the same bug description and acceptance clarifications.
- Both worked in separate full source checkouts without production access.
- The source snapshot contained 706 safe tracked files.
- Its Git SHA was `337386f513832b4e4b252e676028603048d779f1`.

The snapshot excluded `.env.example`, the diagnostics recipient PEM, the Mini certificate PEM, and the credential-bearing Mini `config.h`.
No production state or credentials entered either workspace.

The new arm received a Luna task packet with 30 context files and 344 build files.
It searched those entry points first and recorded dependency expansions.
The control arm used ordinary repository searches with an explicit startup exception.
Both had the same complete safe build workspace.
This experiment isolates context discovery, rather than sparse checkout size.
Existing workspace tests used fake planner responses in both arms.

The reviewer received anonymous A/B patches, source checkouts, and common test results.
It received no method mapping or token measurements before its quality verdict.
Candidate A used ordinary search. Candidate B used the Luna packet.

## Token measurements

The runtime supplied these counts. Input includes cached input. Output includes reasoning tokens.
Cached input and reasoning are subsets, so the totals do not add them twice.

| Run | Input | Cached input | Output | Input plus output |
|---|---:|---:|---:|---:|
| New coding agent | 3,634,925 | 3,522,560 | 15,592 | 3,650,517 |
| Successful Luna planning | 76,177 | 21,120 | 1,553 | 77,730 |
| New coding and planning | 3,711,102 | 3,543,680 | 17,145 | 3,728,247 |
| Ordinary-search coding agent | 3,035,569 | 2,902,912 | 16,655 | 3,052,224 |

Peak coding input was 130,566 tokens with the packet and 148,419 tokens with ordinary search.
Input excluding cache, plus output, was 184,567 tokens for the new path and 149,312 for ordinary search.
These counts measure processing work across turns. They do not represent unique source text loaded once.
They do not apply monetary pricing to cached tokens.

The accepted blind reviewer used 4,181,217 tokens, including its follow-up reviews.
An interrupted review attempt used another 590,133 tokens.
These shared review costs do not belong to either coding arm.
Parent coordination and follow-up implementation are outside the arm measurements.

## Failed setup attempts and limits

The first Luna startup exceeded its inspection budget and stopped.
Its temporary runner did not retain usage, so that failed planning cost remains unknown.
A logged retry supplied the successful packet measured above.

Both initial command-line coding attempts were rejected by execution policy before source access.
The experiment used supported app subagents afterward, without bypassing that policy.
The rejected attempts used 72,444 tokens for the new arm and 45,782 for ordinary search.
Including those measured attempts gives 3,800,691 and 3,098,006 tokens respectively.
The new total remains a lower bound because the first failed planner usage is unavailable.

Initial review logs contained original folder names. That review was interrupted and discarded.
The names were removed, and a fresh reviewer received the anonymous packet.
The final verdict came from that fresh reviewer.

Both safe checkouts had five baseline test failures caused by excluded configuration or PEM files.
The same failures appeared before either fix. They did not affect candidate ranking.
The main checkout passed the complete suite after the repair.

## Quality comparison

| Independent checks before repairs | Ordinary search | Luna context |
|---|---:|---:|
| Passed | 13 | 15 |
| Failed | 4 | 2 |

The ordinary-search candidate covered flat alert assets and stale score totals.
It omitted provider logo selection, delayed logo hydration, and active client enrichment.
The context-planned candidate covered those logo and client paths.
It omitted display delta assets, stale score replay, and conversion matching after turnover alerts.

The reviewer selected the second candidate for its more complete behavior path.
The smaller token count did not outweigh the control candidate's correctness gaps.
Review also caught a correction defect in the initial repair based only on remembered score totals.
The final owner uses explicit scoring play identities and keeps score-only protection when event evidence is absent.

## Final behavior and owners

| Owner | Change |
|---|---|
| `sports_ticker/providers/espn.py` | Reuse the usable-logo selector instead of trusting an empty primary or first list entry. |
| `sports_ticker/providers/score_alerts.py` | Combine observed touchdowns and conversions, preserve event identity, and hydrate matching facts and logos. |
| `ticker_core/assets/planner.py` | Read raw V2 overlays and flat delta records without treating detail text as nested content. |
| `ticker_core/runtime/state.py` | Refresh queued and active alert data without restarting their display duration. |

Football memory seeds known baseline plays and excludes future scoreboard states.
A repeated known play cannot create another alert after stale scores or opponent score changes.
A distinct provider play can create a fresh alert after a real score correction.
Pending transitions retain the previous score when that new identity arrives later.
Hydration cannot assign a later scoring play to an unrelated earlier alert.

The former conversion path created another takeover after an observed touchdown.
The new path keeps the touchdown ID, timestamp, and details while updating its score.
Standalone conversions remain valid when the tracker did not announce the touchdown.
Turnovers retain their own alerts and do not block conversion matching.

## Validation

- Full Python suite: **986 passed, 10 skipped**.
- Critical suite: **638 passed, 10 skipped, 348 deselected**.
- Final blind review: **182 focused checks passed**, including **35 boundary cases**.
- Ruff, configured mypy, Python compilation, and Git diff checks passed.
- The full suite includes the critical invariants.
- A production alert render measured **384x32** pixels.

The render starts with an empty content list and introduces the alert through `display_delta` and `_delta_asset_source`.
The asset coordinator prepares the repository's NYG logo fixture before the production renderer reads it.
The alert keeps `WILLIAMS`, `RUSH 4YD`, its original ID, and its timestamp as the score changes from six to seven.
Only one takeover remains.

Inputs are deterministic fixtures. The render proves the production data and image path, rather than a live scoring event or physical panel.
No server publication or device update occurred during this experiment.

## Local evidence

Ignored evidence remains under `previews/nfl-alert-comparison/`:

- `setup.json`, `planner.json`, and `planner-calls.json`
- `subagent-usage.json` and the two frozen candidate patches
- `blind/review.md` and `blind/final-review.md`
- `test_independent_boundary.py` and candidate test logs
- `final-full-suite.log` and `final-critical.log`
- `final-render-evidence.json` and `final-alert-384x32.png`

The committed regression module is `tests/python/protocol/test_score_alert_boundaries.py`.
The measured original candidates remain frozen. Later repairs are separate from their reported scores and token counts.

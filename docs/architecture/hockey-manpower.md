# NHL manpower

`ticker/server/providers/nhl_live.py` reads current NHL game state every eight seconds.
It refreshes completed games every 60 seconds to retain goal and shootout records.
It reads the top-level `situation`, `periodDescriptor`, and `clock` from the NHL play-by-play response.
The NHL omits `situation` during standard strength.
Regulation and playoff overtime use five skaters. Regular-season overtime uses three skaters.
Intermission, shootout, and finished games have no active player-count display.

`ticker/shared/sports_display.py` owns the V2 `situation.manpower` contract and PP and empty-net ownership.
Each manpower object contains `phase`, `state`, `awaySkaters`, `homeSkaters`, `label`, `scrollLabel`, `powerPlayTimeRemaining`, and `penaltyNumbers`.
Counts use away-team order followed by home-team order.
An empty `label` hides the count. Unknown counts use JSON null.

Normal 5v5 and equal-strength overtime have an empty label.
Power plays, pulled goalies, unequal strength, and reduced-strength regulation carry labels such as `5v4` and `4v4`.
NHL `situationDescriptions` owns PP status. Goalie presence owns empty-net status.
Penalty-box occupants do not establish a power play.
Current penalty-box timers identify penalized jersey numbers. Recorded penalty kinds exclude misconduct timers.
The projection limits displayed penalties to the current skater advantage, with goalie presence included.
Each selected penalty keeps its own clock. Different clocks display separate pairs, such as `0:10 #72 | 2:00 #17`.
Matching clocks share one label, such as `1:30 #17/#72`. Expired players disappear from the label.
The `penalties` field retains each selected jersey number and remaining time.

The ESPN provider joins NHL facts with normalized team identities and checks the game start date.
Each new observation replaces all manpower and badge fields.
Fresh normal play clears prior indicators. Failed game reads remove that game's facts.
Failed scoreboard reads expire the previous cache after 24 seconds.
Snapshot storage, V2 projection, and Pi protocol preserve these facts without adding display policy.
Faceoffs do not hide current PP or empty-net facts when the NHL stops its game clock.
A fresh standard situation still clears those indicators.
The scrolling card places `scrollLabel` below the score.
A PP label contains time and the penalized player's jersey number, such as `1:47 #55`.
The scrolling card places the PP badge above the owning team's logo.
The badge uses `powerPlayTeam`, not possession or the penalized player's team.
The full display retains its PP and empty-net badges without the timer.

The provider reads all regular and overtime goals from the NHL play ledger.
The domain projection formats scorer labels with three surname letters and the jersey number, such as `TAV#91`.
Full-screen goal lanes display three entries per team. Pages change every five seconds and include every goal.
The NHL goal ledger excludes shootout goals. The shootout contract preserves each attempt in order.
Both layouts display three vertical shootout squares beside each team score.
The score keeps its normal position. The full display removes horizontal attempt rows and separate shootout totals.
The domain projection owns the aligned `displayRounds`, lifecycle `state`, `nextSide`, and `roundLabel`.
The contract retains all `away` and `home` outcomes for existing API consumers.
During sudden death, both layouts show the same latest three-round window.
A blue outline marks the next attempt. Completed shootouts mark unused attempts with a dim dash.
The league source supplies shootout results. ESPN period-five plays do not establish an NHL shootout.

## Removed path

The provider no longer selects the latest historical play's situation code.
It no longer combines that historical code with current penalty-box occupants.
It no longer renews failed game observations when other games refresh.
The ESPN provider no longer duplicates count parsing or preserves unverified PP flags.

## Real input and output

`tests/fixtures/display/nhl_live_manpower.json` contains a live Colorado at Dallas observation from October 13, 2026.
At P3 14:57, the current situation reports `1541` and Colorado PP.
The preceding penalty event reports `1551` at P3 15:10.
The V2 output reports away five, home four, label `5v4`, and PP owner `COL`.
A later observation without `situation` clears the label and PP owner.

Live validation also produced Vegas at Nashville `5v4` and Calgary at Anaheim `5v3`.
Edmonton at Los Angeles produced an empty label for normal 5v5.
Real 384x32 previews are saved under `previews/nhl/`.

Run `python -m pytest tests/server/providers/test_nhl_live.py tests/shared/display/test_sports_display.py tests/server/providers/test_espn_provider.py -q`.

## Rangers PP replay

`tests/fixtures/display/nhl_rangers_pp_replay.json` records Tampa Bay at New York on October 13, 2026.
John Carlson, Tampa Bay number 74, received a two-minute penalty at P1 03:03 elapsed.
The recorded Rangers shot at P1 03:33 elapsed used situation code `1451`.
The historical preview reconstructs P1 16:27, score 0-1, and penalty label `1:30 #74`.
The PP badge appears above the Rangers logo on the right.
This replay does not represent a captured live situation response.

## Shootout verification

The Seattle at Philadelphia ledger proves the completed `R3-5` window and the live `R2-4` window.
The Buffalo at Montreal ledger proves that the final unused Buffalo attempt does not remain pending.
The frame test compares both score regions before and after adding the shootout columns.
The score pixels remain identical. Real 384x32 previews are saved under `previews/nhl/shootout/`.

## Staggered penalties and number glyph

`tests/fixtures/display/nhl_staggered_penalties_replay.json` records Calgary at Anaheim on October 13, 2026.
At P1 06:37 remaining, Calgary number 72 has ten seconds left and number 17 has two minutes left.
The scrolling output displays `0:10 #72 | 2:00 #17` below the score.
The stadium pixel font uses a five-column number sign with two vertical strokes and two horizontal bars.
Glyph drawing and width measurement use the same variable advance.

# Baseball inning transitions

## Owner

`sports_ticker/providers/sports_display.py` owns the shared baseball display state.
The V2 projection calls `project_baseball_display` after provider detail enrichment.
The controller, Mini, HTTP response, and device stream receive the same facts.

## Former path

The projection previously copied inning text without checking the out count.
It retained runners, batting ownership, and player details during inning breaks.
The pinned renderer used `possession` for player placement and invented `P:0` when the pitch count was absent.

The projection now removes baseball `possession` and sets `activeTeam` from the active inning half.
The pinned renderer uses `activeTeam`, respects the projected phase, and preserves explicit zero pitch counts.

## Input and output

| Input | Output |
|---|---|
| Top 5th with three outs | Mid 5th, inning break, cleared runners and counts, no batting marker |
| Bottom 5th with three outs | End 5th, inning break, cleared runners and counts, no batting marker |
| Bot 12th with three outs | End 12th, inning break |
| Bottom 5th with zero outs | Active bottom half, home batting marker |
| Rain Delay with stale play facts | Paused state, no live batting details |
| FINAL with stale play facts | Final state, no live batting details |

Three outs end the current half. The display waits for provider confirmation before it starts the next half or declares a final result.
This rule preserves ninth-inning endings, extra innings, and provider corrections.
The projection leaves source snapshots, scores, and saved user settings intact.

## Validation

- All 674 Python tests pass. All 341 critical tests pass.
- Python compilation, Ruff, public demo assets, and generated Mini contracts pass.
- Sixteen transition cases pass through both device projections.
- Six pinned render cases check batting ownership, breaks, delays, and final state.
- A captured ESPN game supplies team, logo, and player inputs for seven controlled transition previews.
- The production renderers produce both 384x32 Ticker Six frames and 64x32 Mini frames.
- The physical Pi runs the native Mini preview renderer without changing its display service.
- The frozen baseline changes only the MLB pinned frame because player details now follow batting ownership.
- The NFL frames and MLB pane retain their prior pixel hashes.
- The PC and physical Pi produce identical hashes for all four frozen frames.

Preview evidence is in `previews/baseball-transitions/`.
These controlled previews do not represent an observed live third-out event.

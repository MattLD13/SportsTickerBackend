# College football controls and blind agent comparison

Date: 2026-10-19

## Result

The blind reviewer selected candidate B by a small margin.
B used ordinary search with the current agent instructions.
Both candidates passed every locked acceptance test. Neither required a repair.
B provided clearer group backgrounds and a separate feature view.
The original registered rule gave quality priority over token use and initially selected B.
After the verdict and cost reveal, the user changed the selection rule.
The user directed lower token use to decide when quality is very similar.
The final selection follows that revised rule and uses A unchanged.

Candidate A used the new context method and consumed 36.28% fewer total tokens.
It also reduced maximum coding input by 15.19%.
This single task cannot establish a general advantage for either method.

## Feature and behavior owner

`EnabledLeagueControls` owns the local dropdown state and groups records through explicit `conference_parent` metadata.
`ModesView` renders the conference controls.
`TickerViewModel.saveSettings` retains persistence ownership.
`LeagueOption` now decodes the optional parent metadata.

The change replaces the flat Enabled Leagues loop in `ModesView`.
FBS and FCS each have separate overall controls and initially collapsed conference lists.
Each enable action changes one existing settings key.
Opening or closing a list changes no settings and performs no save.
Disabling a parent preserves its conference choices for later use.

The simulator disabled `ncf_fbs:4`, disabled FBS, and enabled FBS again.
The conference stayed disabled, the other division stayed enabled, and the fixture counted three save calls.
Opening and closing the conference list produced zero save calls.
The fixture counts persistence calls without live HTTP writes. Contract tests check settings serialization.

## Controlled setup

- Both agents used GPT-6.1 Sol with high reasoning and fresh context.
- Both started from `c8ce4fa57e343ab710ca4e981879b1ab34e2353c` source contents.
- Both received identical current engineering instructions and the same feature specification.
- Both received full, identical safe workspaces with 717 tracked files.
- The safe Git snapshot was `00cd73cec1528ec74796c2426fedce9f1972b4a5`.
- Both had one coding attempt. The coordinator froze each completed patch before independent validation.
- The coordinator locked acceptance tests before coding began.
- Random allocation assigned A to selective context and B to ordinary search.
- The reviewer received anonymous source, test results, and actual screenshots.
- The reviewer recorded its quality verdict before learning methods, token counts, or coding times.

The safe snapshot excluded environment examples, two PEM files, and the credential-bearing Mini configuration.
No production credentials or customer state entered either workspace.

A received the explicit `ios` packet with 13 context files and 168 build files.
Packet preparation took 0.56 seconds and made zero model calls.
No Luna planning call was needed for this known component.
B used ordinary repository search with the same current instructions and an explicit discovery-method exception.
Both had the same complete safe source available.
This trial compares discovery methods, rather than sparse checkout sizes.

The blind verdict was locked at `2026-10-19T23:35:08.688275+00:00`.
The [original quality review](conference-trial/blind-review.md) gives the full reasoning.

## Independent validation

| Check | A: selective context | B: ordinary search |
|---|---:|---:|
| Production Debug build | Pass | Pass |
| Production Release build | Pass | Pass |
| Swift package tests, Debug | 26 passed | 26 passed |
| Swift package tests, Release | 26 passed | 26 passed |
| Locked simulator UI tests | 5 passed | 5 passed |
| Confirmed required repairs | None | None |

Each package suite includes seven candidate regression tests and two independently locked contract tests.
The UI suite covers collapsed defaults, save-free disclosure actions, parent cycles, division isolation, dynamic conferences, and empty catalogs.
Both simulator result bundles report five passes, zero failures, and zero skips.
Both Xcode logs contain `** TEST SUCCEEDED **`.

The simulator used iPhone Air with iOS 26.5.
Both screenshots show readable controls without clipping or overlap.
The screenshots use an injected test catalog with deliberately overlapping and unfamiliar names.

- [A screenshot and selected layout](conference-trial/A-fbs-expanded.png)
- [B comparison screenshot](conference-trial/B-fbs-expanded.png)
- [A macOS validation](https://github.com/MattLD13/SportsTickerBackend/actions/runs/39340575838)
- [B macOS validation](https://github.com/MattLD13/SportsTickerBackend/actions/runs/39340581624)

These checks cover one simulator size and text setting.
They do not establish manual VoiceOver, large-text, physical-phone, or live-server persistence behavior.

## Runtime token measurements

Input includes cached input. Output includes reasoning tokens.
Cached input and reasoning are subsets and are not added twice.

| Measurement | A: selective context | B: ordinary search |
|---|---:|---:|
| Input | 644,866 | 1,016,018 |
| Cached input | 568,704 | 933,248 |
| Output | 10,691 | 12,756 |
| Input plus output | 655,557 | 1,028,774 |
| Input excluding cache, plus output | 86,853 | 95,526 |
| Maximum single input | 69,778 | 82,272 |
| Coding and packet preparation | 192.64 seconds | 230.09 seconds |
| Planner model calls | 0 | 0 |

A used 36.28% fewer total tokens and 9.08% fewer input-excluding-cache plus output tokens.
Its measured coding and preparation time was 16.28% shorter.
These measurements include all discovery retries within each coding run.
They exclude shared experiment setup, CI waits, review, and coordinator work.
Token totals measure processing across turns, including repeated context. They do not measure unique source lines.
Billing weights differ, so these counts do not measure monetary cost.

The blind reviewer used 1,528,673 tokens across its initial and final reviews.
The shared harness agent used 1,659,079 tokens across setup and diagnosis.
These common costs do not belong to either coding arm.
Coordinator and integration usage remain outside these arm measurements.

## Harness failures and cancellation

The first shared fixture omitted `import Combine`.
The coordinator added the import equally and kept both candidate patches unchanged.

The generated UI project then omitted the production Swift concurrency settings.
Both generated targets failed in the same existing pairing method before running UI tests.
The original production projects passed their builds.
The coordinator copied the production concurrency settings into both generated targets.
The coordinator changed no candidate or acceptance-test code.

The next runs completed every test successfully.
The coordinator requested cancellation while the simulator jobs still appeared active.
A had already completed its workflow.
B had already completed all tests before cancellation reached its workflow wrapper.
B retained a cancelled aggregate status with a complete passing result bundle and screenshot.
The coordinator requested an identical job rerun for a clean aggregate status.
The inherited-polling stall hypothesis was not confirmed. No polling code changed.

The selective agent also encountered a Windows character-encoding error during a source excerpt.
It retried with UTF-8 output. The measured coding usage includes that recovery.

## Audit files

[Machine evidence](agent-conference-trial-evidence.json) records source hashes, patch hashes, locked acceptance hashes, allocation, measurements, and validation history.
The report directory retains both frozen patches as gzip archives, both screenshots, the acceptance sources, and the blind review.
The final app change uses the frozen A patch without a later repair.
Temporary validation refs contain harness plumbing and are separate from the app change.

The integrated checkout passed all 1,086 Python tests, with ten skips.
The focused server catalog checks passed both tests.
The critical suite passed 738 tests, with ten skips and 348 deselected tests.

The published app commit is `726febb10eb57cf9face7918370ec2293af2d292`.
Its [Debug and Release workflow](https://github.com/MattLD13/SportsTickerBackend/actions/runs/39343056754) passed both builds.
The coordinator removed all six temporary validation tags after retaining their evidence.
The audit directory fixes source line endings to preserve acceptance and review hashes across checkouts.
The unchanged B wrapper rerun finished successfully and again passed all five UI tests.

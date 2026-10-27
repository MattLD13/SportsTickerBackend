# Progressive agent context

## Decision

Keep ordinary targeted search and explicit manifest slices as the default.
Use `find.py` for bounded file, symbol, and excerpt discovery without a model.
Keep Luna opt-in for broad, unfamiliar, or cross-component tasks.
The new planner reduces input size and protocol failures. It does not establish lower total token use or faster coding.

## Implementation

`tools/workspaces/discovery.py` owns safe discovery.
`tools/workspaces/find.py` exposes that discovery without a model.
`planner.py` owns optional model selection. `start.py` owns task packets and enforced context.
The manifest continues to own dependencies, checks, and component boundaries.

The former planner sent every source path and verbose component rules on each call.
Version 5 starts with a compact component map, explicit entry paths, and ranked filename hints.
Hints use literal filename and path words. They do not read source or choose a final slice.
Luna can request a component inventory, scoped symbol search, definition list, or named excerpt.
The host accepts only disclosed safe paths and validates every model response locally.

The planner allows three rounds. The first two rounds permit two discovery requests each.
The final response schema requires a ready plan with no further discovery requests.
Per-request and total input limits remain 48,000 and 144,000 bytes.
These limits exclude transport schema and client overhead.
The component catalog has a 16,000-byte limit. Filename hints have a 6,000-byte and 16-file limit.
Source excerpts contain at most 100 lines and 6,000 output bytes.
Selected-file scans stop at one MiB or 20,000 lines.
Truncated and absent sparse files remain explicit results.

Shared changes retain declared owner and consumer context even when Luna omits it.
The report distinguishes model selections from context added by that enforcement.
Sparse startup includes the discovery helper, so an isolated workspace can import the startup command before expansion.

Startup and prompt hooks remain model-free.
A normal continuation reuses its existing packet. Another model call requires `--plan` or `--replan`.
Failures retain available usage without replacing a valid task packet.
Benchmark checkpoints record an unknown-cost attempt before execution and replace it with available results afterward.
Timeout accounting remains a lower bound.

## Commands

```powershell
python tools/workspaces/find.py --search "station_retry"
python tools/workspaces/find.py --search "sports_ticker/providers ScoreAlertTracker"
python tools/workspaces/find.py --symbols sports_ticker/providers/score_alerts.py
python tools/workspaces/find.py --excerpt sports_ticker/providers/espn.py --symbol _event_passer_full
python tools/workspaces/start.py --slice mini-runtime --task "Inspect station recovery"
python tools/workspaces/start.py --plan --task "Trace a shared sports contract through both devices"
```

The filename-only station query returns its helper and native regression without reading source or starting a model.
The late ESPN definition lookup finds the real symbol at line 3,776 while returning a bounded source window.

## Measurement method

The baseline is planner version 2 from source revision `558782aafc92f0c31f6cd11b4c2a08971295cb6f`.
Both arms use `gpt-6-luna` with low reasoning through the same signed-in CLI.
Each arm receives the same task and safe repository state.
Arm order alternates across cases and repeats.

The three task classes cover football conversion alerts, unfamiliar Mini station recovery, and a shared hockey shootout fact.
Each case runs twice per arm. Expected paths and consumers remain outside both model inputs.
Those expectations assess selected context. They do not prove an implementation correct.
The cases informed versions 4 and 5 after failures in version 3.
They are development cases, rather than untouched validation cases.

The benchmark records exact CLI input bytes, schema bytes, time, tokens, selected paths, required consumers, and failed attempts.
Implementation digests identify the measured code, including the separate discovery helper.
No expected-answer file or benchmark implementation enters the planner's file inventory.
Normal CI validates cases and accounting without making model calls.

## Final version 5 results

All-run totals include every model attempt, including the failed baseline plan.
Input includes cached tokens. Output includes reasoning tokens. Those subsets are not added twice.

| Measure | Full-index baseline | Progressive version 5 |
|---|---:|---:|
| Valid completed plans | 5 of 6 | 6 of 6 |
| Failed plans | 1 | 0 |
| Total input and output tokens | 379,157 | 389,748 |
| Input excluding cache, plus output | 133,653 | 142,068 |
| Total CLI input bytes | 396,942 | 286,893 |
| Mean first request bytes | 40,466 | 12,676 |
| Sum of planning time | 64.34 seconds | 96.18 seconds |

The first request is 68.7% smaller. Total CLI input is 27.7% smaller.
All-run token use is 2.8% higher. Input excluding cache, plus output, is 6.3% higher.
The extra model rounds and process overhead consume the input-size savings.
These results support keeping Luna optional.

Five pairs have two valid plans and complete usage.
Those paired plans use 336,669 baseline tokens and 330,524 progressive tokens, a 1.8% reduction.
Their time increases from 56.47 to 80.04 seconds.
That paired token result excludes the failed baseline case. It does not replace the all-run result above.

Mean raw required-path coverage is 83.3% for both arms in those five pairs.
Across all valid plans, raw coverage is 83.3% for the baseline and 77.8% for the new planner.
The new planner's additional shared-contract plan accounts for the different denominators.
Effective coverage is 86.7% for valid baseline plans and 94.4% for valid progressive plans.
The effective increase comes from mandatory owner and consumer context. It is not a model-only selection improvement.

The strict expected paths expose useful omissions.
Some plans omit the football boundary regression or Mini station runtime caller.
The manager repairs shared owner and consumer omissions, but it cannot prove every relevant test was selected.
The coding agent must still investigate real dependencies.

## Earlier iterations

| Iteration | Baseline valid plans | New valid plans | Interpretation |
|---|---:|---:|---|
| Version 3 | 5 of 6 | 1 of 6 | Compact input alone causes extra discovery rounds, byte-limit failures, and incomplete selections. |
| Version 4 | 5 of 6 | 5 of 6 | Filename hints improve completion. Comparable plans use fewer tokens but have lower required-path coverage. |
| Version 5 | 5 of 6 | 6 of 6 | Final-round rules and shared context enforcement improve reliability. Total token use remains higher. |

Version 3 consumes 471,920 baseline tokens and 456,900 progressive tokens, including failures.
Version 4 consumes 500,046 baseline tokens and 382,108 progressive tokens, including failures.
Those lower progressive totals do not establish a quality-equivalent improvement.
All three experiments consume 2,579,879 tokens in total.
That figure excludes implementation, coordination, and independent review agents.
A separate fresh stock-session packet check uses 30,200 tokens and selects the existing market-session and stock owners.
Its continuation reuses the same packet and recorded usage without another model call.
This probe checks packet creation and reuse. It does not prove complete regression selection.

## Validation and review

- Full Python suite: **1,086 passed, 10 skipped**.
- Critical suite: **738 passed, 10 skipped, 348 deselected**.
- Ruff, configured mypy, Python compilation, and workflow lint pass.
- Tests cover credential exclusions, links, Windows paths, sparse imports, Unicode, large files, budgets, and malformed model events.
- Tests verify that hooks and ordinary discovery never invoke a model.
- Independent review found and verified fixes for scoped instructions, local limits, sparse imports, and partial usage accounting.

Owner: Discovery owns bounded evidence. The planner owns model decisions. The manager owns mandatory shared context and task records.
Former path: Repeated full-index planning and discarded failure usage are replaced by progressive evidence and durable accounting.
Input and output: A real station query returns two file paths with zero source reads and zero model calls.

## Evidence

[Machine-readable summaries](agent-context-v5-evidence.json) retain every experiment's run outcomes, coverage, usage, errors, and implementation digests.
Full reports and checkpoints remain under ignored `previews/context-evaluation/`.
Future comparisons exclude this report and its evidence summary from model discovery to prevent answer leakage.
That exclusion was added after measurement. The measured versions' recorded implementation digests remain unchanged.
The prior [NFL coding comparison](2026-10-19-nfl-alert-agent-comparison.md) measures a separate implementation experiment.
These planning-only measurements cannot replace that coding comparison or predict savings across other repositories.

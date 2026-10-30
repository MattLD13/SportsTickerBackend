# First cleanup batch

Base revision: `c3cebe6cfc3b2897b83adc27a97e0f997224909d`.

## Completed changes

| Behavior owner | Replaced path | Result |
|---|---|---|
| `providers/score_alerts.py` | Unused `services/score_alerts.py` | One active score-alert tracker implementation remains. |
| Mode-specific provider sources | `providers/live_sources.py` | Golf, stocks, flights, news, and clock have separate modules. |
| `ticker/ops/components.py` | Source-symbol dependency analysis | Explicit files select provider workers. Shared numeric helpers select their consumers. |
| `domain/settings.py` | Repeated API, repository, and provider conversion | One codec uses domain defaults and validation. |
| `providers/racing_session.py` | Duplicate source and Six classifiers | Both callers use the same unchanged classification rule. |
| `providers/sports_display.py` | Duplicate ESPN player-name parser | ESPN uses the existing canonical player-name reader. |

`source_values.py` holds numeric validation shared by the new source modules.
Deployment ownership includes both ESPN and FotMob for score-alert changes.
Racing session changes select the racing worker, backend core, and Six update path.

## Evidence

- All 1,579 Python tests passed after implementation.
- The full suite includes API, worker, deployment, settings, sports, render baseline, and showcase checks.
- New settings checks cover JSON round trips, database reopening, detached containers, defaults, and invalid input.
- Source ownership checks cover each new source module, shared helpers, and both score-alert consumers.
- The Six dependency check covers the shared racing session module.
- AST comparison found no implementation changes in the moved provider functions and classes.
- Python correctness checks, scoped type checks, compilation, and generated Mini field and drawing checks passed.
- Public demo verification passed without regenerating assets.

The domain rejects an explicit null mode. An empty mode selects sports.
The new codec preserves both behaviors.

## Protected boundary

The showcase files, demo assets, firmware files, and `sports_display.py` remain byte-for-byte unchanged.
The racing classifier uses a separate pure module because the showcase records the exact `sports_display.py` source hash.
The ESPN reader imports the existing player-name helper without renaming that canonical helper.

Implementation validation ran locally before publication. The existing GitHub workflow controls release activation.
The project map and inventories describe the original review revision. They remain historical review artifacts.

# Repository organization design

Base revision: `5ee30fa4a9a2f84b7cb6155ea5027f028bebd271`.

## Goal

Group files by responsibility. Keep runtime behavior and public entry points stable.

```text
sports_ticker/
  providers/
    sources/
      golf.py
      stocks.py
      flights.py
      news.py
      values.py
    clock.py
    factory.py
    ...provider adapters and shared sports facts
backend_ops/
  deployment/
    components.py
    manager.py
  manager.py                 # stable command entry point
  ...workers, diagnostics, reporting
tests/python/
  providers/                 # upstream sources and provider behavior
  protocol/                  # transport and V2 contracts
  ...existing boundary groups
docs/architecture/
  README.md
  repository-layout.md
  reviews/2026-10-27/
    project-map.md
    project-inventory.csv
    project-imports.csv
```

## Move plan

| Current path | New path | Reason |
|---|---|---|
| `providers/golf_source.py` | `providers/sources/golf.py` | Group upstream sources and remove redundant filename suffixes. |
| `providers/stock_source.py` | `providers/sources/stocks.py` | Match the stock adapter name. |
| `providers/flight_source.py` | `providers/sources/flights.py` | Match the flight adapter name. |
| `providers/news_source.py` | `providers/sources/news.py` | Keep news source logic beside other source adapters. |
| `providers/source_values.py` | `providers/sources/values.py` | Keep source-only numeric helpers in the source package. |
| `backend_ops/components.py` | `backend_ops/deployment/components.py` | Put release selection beside release activation. |
| Release implementation in `backend_ops/manager.py` | `backend_ops/deployment/manager.py` | Separate release mechanics from the stable command entry point. |
| Provider source tests under `tests/python/protocol/` | `tests/python/providers/` | Keep source behavior separate from transport contracts. |
| Project map and inventories in `docs/architecture/` | `docs/architecture/reviews/2026-10-27/` | Separate historical review evidence from current guides. |

Provider paths in the first five rows are relative to `sports_ticker/`.
Clock remains a provider because it does not wrap an upstream source.
The root manager module retains command parsing and delegates release operations to the deployment package.
It does not retain duplicate release implementations.

## Dependency updates

- Update imports and test patch targets to the new modules.
- Match source deployment owners by relative module path, including the `sources/` package.
- Keep shared source helpers assigned to their actual provider consumers.
- Update GitHub packaging commands to the new component selector.
- Update workspace manifests so sparse task checkouts include nested source and deployment modules.
- Update current documentation and test commands. Preserve historical review contents.
- Keep archive packaging recursive so worker releases contain the new packages.

## Preserved boundaries

Keep `sports_ticker`, `ticker_core`, `esp32_hub75`, and `TickerControlApp` as product roots.
Installed releases, build tools, and showcase provenance use those paths.
Keep `setup.sh`, `updater.py`, `test.py`, and service entry points stable.
Keep showcase sources, assets, contracts, and `sports_display.py` unchanged.
No API, database schema, firmware, or rendered output change belongs in this task.

## Validation

Run provider and deployment checks after the moves.
Run the complete Python suite, correctness checks, type checks, and public demo verification.
Check command entry points and packaged archive contents.
Compare protected files with the base revision byte-for-byte.

Publication remains a separate action from this local organization change.

## Implementation evidence

The move plan is implemented. It moves 32 files and extracts release mechanics into the deployment package.
The provider source implementations retain their existing functions and classes.
The stable recovery command retains command parsing and delegates to the extracted manager.

The initial provider and deployment run passed 347 tests.
Correctness checks, scoped type checks, compilation, and public demo verification passed.
Archive checks include the nested source and deployment packages for every process release.
The command test runs the installed recovery status command against a temporary home directory.
The protected-file comparison confirms that 185 showcase, firmware, contract, and rendering files remain unchanged.

The complete suite passed all 1,580 tests against the committed new layout.
Workspace checks resolve the new source, deployment, and provider-test paths.
AST comparison confirms that source definitions and release mechanics changed only their relocated imports.
The organization change remains committed locally without a push or deployment.

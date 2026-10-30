# Backend recovery and agent evidence

## Ownership

The engine owns loop readiness.
Each worker owns settings-scoped provider recovery for its provider.
Providers retain their last healthy data through their existing cache contracts.
The core supervisor owns worker restarts, worker deploys, and worker rollback.
`server/ticker/ops/manager.py` owns release files, the core service, and the deployment record.
The incident store owns redaction, bounded evidence, and failure deduplication.
The deployment generates `RELEASE_SHA` as the full backend identity.

## Worker behavior

Three failed calls pause that provider for the affected ticker settings.
The first pause lasts 30 seconds.
Repeated failures increase the pause to a maximum of 300 seconds.
A successful call resets the circuit.
A settings change creates a fresh recovery state.
Other tickers and providers continue to refresh.
The engine publishes only data from matching settings.
Each process runs the files of one release.

## Readiness

Readiness requires a running engine loop and recent completed passes.
Remote provider errors remain separate from process readiness.
A stopped or stalled engine loop becomes unready.
`GET /health` includes the release identity, loop progress, and the health and recovery state of each provider.
`GET /workers` includes the active release, the previous release, the bad releases, and the restarts of each worker.

## Agent evidence

The incident store retains release IDs, entrypoints, source locations, exception types, tracebacks, and recovery decisions.
It removes known environment secrets, credential fields, URL queries, and bearer values.
It bounds incident count and message size.

Run `python3 -m ticker.ops.diagnostics --home /home/ubuntu --output /tmp/backend-report.zip` in `/home/ubuntu/backend-control/current` on the server.
The ZIP contains `report.json` and `TRIAGE.md`.
It excludes environment files, raw user payloads, and database contents.
The server registers a diagnostic stack signal for the external recovery controller.
The signal produces thread locations without dumping local variable values.

## Validation

Injected-clock tests cover provider pause, last-good data, settings isolation, retry, and recovery.
Readiness tests distinguish stale loop progress from upstream failure.
Evidence tests check source tracebacks, redaction, storage limits, and ZIP contents.

## Processes and releases

The core and nine provider workers are separate processes.
The workers are `espn`, `fotmob`, `weather`, `golf`, `racing`, `stock`, `flights`, `music`, and `news`. The core makes the clock result.
`server/deploy/ticker.service` runs the core. The core supervisor starts each worker. No worker has a service unit.
The unit uses `KillMode=process`, so a core restart leaves the workers running. The new core adopts them.

| Path under the home folder | Content |
|---|---|
| `ticker3/releases/<revision>/` | One immutable release: all source files, a manifest, and a `.venv` link |
| `ticker3/environments/<hash>/` | One dependency environment for each set of requirements |
| `ticker3/current` | The release of the core |
| `ticker_data/backend-control/state.json` | The deployment record and the report queue |
| `ticker_data/ticker3-supervisor.json` | The active, previous, and bad release of each worker |

Each release holds every source file, so the core and each worker can run any release.
`server/ticker/ops/components.py` reads the module import graph to select the processes that a change reaches.
The core starts at `ticker.server.main`. Each worker starts at `ticker.server.worker.__main__` and its branch of `create_provider`.
For example, a change in `providers/stock_source.py` selects only `stock`.
A change in `providers/sports_display.py` selects the core and the four sports workers.
The worker contract, `server/ticker/ops/`, requirements, units, and workflows select all processes.
A deleted provider module or a provider data file has no import edge, so it selects all processes.
`tests/ops/deploy/test_component_graph.py` checks that each graph covers every module that the process really loads.

User state, credentials, stock caches, and firmware remain outside releases.
A core deployment creates a private SQLite backup before activation.
Rollback never replaces current user settings or pairing records with an older database.
Database migrations must retain compatibility with the previous release.

## Deployment sequence

1. Unpack the release and check the checksum of each file. Running processes do not change.
2. Give the release a dependency environment, compile it, and import the core and worker entry points.
3. Install the guard toolkit and the units.
4. If the core is selected, save a rollback record, move `ticker3/current`, and restart the core.
5. Require three ready checks with the exact release identity. If they fail, restore the previous core release and quarantine the candidate.
6. For each selected worker, call `POST /workers/<provider>/deploy`. The supervisor starts the new release next to the old one.
7. The supervisor promotes the new worker after it sends a result for every subscription. Otherwise it keeps the old worker and marks the release bad.

## Guard

The guard timer checks the core every 30 seconds.
After three failed checks, it records thread stacks and restarts the core once.
After three further failed checks, it restores the previous core release.
Three core process crashes within 30 minutes also restore the previous core release, even when a later health sample succeeds.
If a deployment stops before confirmation, the guard resolves the saved rollback record.
The guard copies the worker releases from the supervisor record, and reports each worker release that the supervisor marked bad.
The guard runs on the system Python. It imports only `ticker.ops` and `ticker.server.contract`.

## First Ticker 3 deployment

The first Ticker 3 deployment moves every process, whatever the change selection says.
It keeps the deployment record of the old layout in `ticker_data/backend-control/state-before-ticker3.json`.
It keeps the old units in `ticker_data/backend-control/units-before-ticker3/`.
If the new core becomes ready, the deployment stops and disables the old `ticker-fetcher@` units.
If the new core fails, the deployment restores the old units, the old guard toolkit, and the old deployment record. The old fetchers keep running.
The report queue keeps the failure reports in both cases.

The Six and the Mini cannot update themselves across this deployment. Their released code reads the old routes and the old repository layout.
Update each device by hand after the server changes:

- On each Six, run the install script of the new release. It installs the newest `main` release, its requirements, and its service unit:

  ```sh
  curl -fsSL https://raw.githubusercontent.com/MattLD13/SportsTickerBackend/main/six/deploy/setup.sh | sudo bash
  ```

- Flash each Mini over USB.

## Agent repair workflow

Run `gh workflow run backend-diagnostics.yml -f component=music` to collect music evidence.
Use `component=all` to collect all components.
Download the encrypted `backend-evidence-*` workflow artifact.
The artifact contains `backend-report.p7m`.
The repository contains only the public encryption certificate.
The private decryption key remains at `~/.ssh/ticker_backend_diagnostics.pem` on the operator PC.
Decrypt the artifact before reading the report.

```powershell
& 'C:\Program Files\Git\usr\bin\openssl.exe' cms -decrypt -binary -inform DER -in backend-report.p7m -inkey "$env:USERPROFILE\.ssh\ticker_backend_diagnostics.pem" -out backend-report.zip
```

Read `TRIAGE.md` and `report.json` before editing source.
The report includes process releases, worker state, changed files, service facts, tracebacks, and rollback decisions.
Use sanitized provider fixtures to reproduce the failure.
Publish reviewed changes through the deployment workflow.

## GitHub runtime reporting

The recovery manager owns a durable report queue in deployment state.
It queues failed startup, repeated readiness failures, crash loops, rollback decisions, and verified recovery.
It saves failure reports before attempting rollback.
Normal upstream provider errors do not mark a deployment as failed.

GitHub reads the queue through the existing SSH deployment access.
The server stores no GitHub token.
The reporting job uses a temporary workflow token with `checks: write` permission.
Each affected component and revision gets one runtime check.
Recovered code updates its check. A restored older revision never clears the failed candidate's check.
Report sequences prevent retries from replacing a newer result with an older result.
The server removes a queued report only after GitHub confirms its check.

Public checks contain fixed lifecycle text, component names, code identities, and report references.
Detailed logs, tracebacks, and credentials never enter public check output.
Diagnostic artifacts retain the existing encryption policy.
The health response exposes queue depth and the last acknowledgement time.

The collector uses the existing five-minute monitoring schedule and supports manual dispatch.
GitHub can delay scheduled runs. Reports remain queued during delivery outages.
Read [GitHub check runs](https://docs.github.com/en/rest/checks/runs) for the check update API.

## Limits

Process recovery requires a running server host and systemd.
This design does not provide host failover or an off-server database backup.
The supervisor cannot prove every upstream response before production receives it.
Focused tests cover that boundary.

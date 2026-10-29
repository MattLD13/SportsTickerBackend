# Backend recovery and agent evidence

## Ownership

The refresh runtime owns loop readiness.
The scheduler owns settings-scoped provider recovery.
Providers retain their last healthy data through their existing cache contracts.
The incident store owns redaction, bounded evidence, and failure deduplication.
The deployment generates `RELEASE_SHA` as the full backend identity.

## Fetcher behavior

Three failed calls pause that provider for the affected ticker settings.
The first pause lasts 30 seconds.
Repeated failures increase the pause to a maximum of 300 seconds.
A successful call resets the circuit.
A settings change creates a fresh recovery state.
Other tickers and providers continue to refresh.
The scheduler publishes only data from matching settings.
No recovery path combines source files from different releases.

## Readiness

Readiness requires a running refresh loop and recent completed work.
Remote provider errors remain separate from process readiness.
A stopped or stalled refresh loop becomes unready.
The public health response includes release identity, loop progress, and aggregate fetcher recovery state.

## Agent evidence

The incident store retains release IDs, entrypoints, source locations, exception types, tracebacks, and recovery decisions.
It removes known environment secrets, credential fields, URL queries, and bearer values.
It bounds incident count and message size.

Run `python -m backend_ops.diagnostics --home /home/ubuntu --output /tmp/backend-report.zip` on the server.
The ZIP contains `report.json` and `TRIAGE.md`.
It excludes environment files, raw user payloads, and database contents.
The server registers a diagnostic stack signal for the external recovery controller.
The signal produces thread locations without dumping local variable values.

## Validation

Injected-clock tests cover provider pause, last-good data, settings isolation, retry, and recovery.
Readiness tests distinguish stale loop progress from upstream failure.
Evidence tests check source tracebacks, redaction, storage limits, and ZIP contents.

## Independent components

The core and ten fetcher workers have separate immutable releases and service units.
The fetchers are `espn`, `fotmob`, `weather`, `golf`, `racing`, `stock`, `flights`, `music`, `news`, and `clock`.
The planner owns source-to-component selection.
A provider implementation change updates that worker and its declared consumers.
Shared domain, protocol, or dependency changes update all affected components together.
The planner in `backend_ops/components.py` reads the module import graph of the release.
A change to a Python module selects each process that can load that module.
The core starts at `sports_ticker.server`. Each worker starts at `backend_ops.worker` and its branch of `create_provider`.
For example, a change in `providers/stock_source.py` selects only `stock`.
A change in `providers/sports_display.py` selects core and the four sports workers.
Contract files, `backend_ops/`, requirements, and service units select all components.
A deleted provider module or a provider data file has no import edge, so it selects all components.
Worker bundles include provider dependencies. They exclude the core API, dashboard, and Pi renderer.
A test checks that each worker bundle carries every module in its import graph.
The core calls workers through a bounded local JSON socket contract.
Rendering and public V2 payloads retain their existing owners.

Each component stores its current and previous code identities in `ticker_data/backend-control/state.json`.
Dependency environments remain immutable and use requirement hashes.
Components can share the same unchanged dependency environment.
User state, credentials, stock caches, and firmware remain outside releases.
Core deployment creates a private SQLite backup before activation.
Rollback never replaces current user settings or pairing records with an older database.
Database migrations must retain compatibility with the previous release.

## Failure sequence

1. Prepare candidate files and dependencies without changing running services.
2. Check source hashes and the shared worker contract.
3. Save a rollback transaction before switching component links.
4. Restart only selected components.
5. Require three successful readiness checks with the exact release identity.
6. If startup fails, restore the transaction's previous versions and quarantine the candidate.

The independent system timer checks components every 30 seconds.
After three failed checks, it records thread stacks and restarts the failed component once.
After three further failed checks, it restores the previous release.
Three process crashes within 30 minutes also trigger rollback, even when a later health sample succeeds.
If deployment stops before confirmation, the timer resolves the saved rollback transaction.
The timer retains healthy data during upstream outages through the scheduler's existing cache and pause rules.

Three repeated programming errors can trigger a private request replay against the previous fetcher process.
The controller first confirms that the current worker still fails the same request.
If the previous process returns healthy data, the timer restores that fetcher.
If both versions fail, the timer records the result and keeps the current code.
Remote HTTP failures do not trigger code rollback by themselves.
A shared contract change requires a coordinated rollback of matching component versions.
The missed-deploy workflow reads the processed revision from deployment state.
It does not repeatedly deploy a quarantined revision.

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
The report includes component versions, changed files, service facts, tracebacks, replay IDs, and rollback decisions.
Raw replay requests remain private on the server.
Do not include raw requests in issue text or public artifacts.
Use sanitized provider fixtures to reproduce the failure.
Publish reviewed changes through the component deployment workflow.

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
Detailed logs, tracebacks, replay inputs, and credentials never enter public check output.
Diagnostic artifacts retain the existing encryption policy.
The health response exposes queue depth and the last acknowledgement time.

The collector uses the existing five-minute monitoring schedule and supports manual dispatch.
GitHub can delay scheduled runs. Reports remain queued during delivery outages.
Read [GitHub check runs](https://docs.github.com/en/rest/checks/runs) for the check update API.

## Migration and limits

The first release adds readiness and worker infrastructure without changing the active deployment layout.
The next release freezes that verified version as the rollback baseline.
The controller then activates immutable core and worker services.
The baseline environment preserves existing installed dependencies during this one-time migration.
Later dependency environments use isolated installations.
Process recovery requires a running server host and systemd.
This design does not provide host failover or an off-server database backup.
The controller cannot prove every upstream response before production receives it.
Focused tests and private replay evidence cover that boundary.

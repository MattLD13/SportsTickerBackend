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

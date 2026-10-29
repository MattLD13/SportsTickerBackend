# Backend operations

Keep deployment selection, release activation, evidence, and GitHub reporting separate.
The core supervisor in `ticker3/core/supervisor.py` owns worker restarts, worker deploys, and worker rollback.
This folder owns release files, the core service, and the deployment record.
The guard runs on the system Python. Import only the standard library, `backend_ops`, and `ticker3.contract`.
Use explicit component identity and release revision in recovery records.
Do not clear a failed candidate report when a previous release recovers.
Preserve the durable reporting queue until GitHub acknowledges its events.
Keep public status summaries free of credentials, customer data, and private logs.
Encrypt private diagnostic evidence before uploading it.
Keep deployment selection in its existing owner. Agent workspace selection does not change it.
Use temporary directories for recovery tests. Do not mutate production release state during tests.

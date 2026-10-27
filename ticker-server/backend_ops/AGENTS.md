# Backend operations

Keep worker lifecycle, deployment selection, evidence, and GitHub reporting separate.
Use explicit component identity and release revision in recovery records.
Do not clear a failed candidate report when a previous release recovers.
Preserve the durable reporting queue until GitHub acknowledges its events.
Keep public status summaries free of credentials, customer data, and private logs.
Encrypt private diagnostic evidence before uploading it.
Keep deployment selection in its existing owner. Agent workspace selection does not change it.
Use temporary directories for recovery tests. Do not mutate production release state during tests.

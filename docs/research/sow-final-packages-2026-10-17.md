# Final SOW packages

## Scope

The owner requests all five remaining packages. Preserve current modes, app pairing, manual pins, and real display output.
TV calibration and local game-clock interpolation remain excluded.

## Acceptance record

| Package | Required evidence | State |
| --- | --- | --- |
| Mini networking | Compare real request timing, heap, outage recovery, logos, and OTA with the current release. | Implemented. Physical outage and timeout checks pass. Fixed-response comparison remains. |
| Platform cleanup | Extract sprite/cache and payload ownership. Split iOS response and timer responsibilities. Preserve exact pixels and builds. | In progress. |
| Provider efficiency | Own demand and market-session policy. Prove schedule activation, retained close data, and lower request counts. | In progress. |
| Security | Issue durable device credentials. Authenticate device reads and mutations. Audit controller and deployment authorization. | In progress. |
| Final validation | Prove remaining OTA recovery cases, frame-based Pi release health, and deterministic performance baselines. | In progress. |

Each package records its owner, removed path, actual input, output, and measured limits before publication.

## First implementation batch

`BackendHttpSession` owns the reusable device connection. Exclusive network work closes that connection under `NetworkGate`.
The real Mini passes two forty-five-second outages, forced request expiry, BLE setup recovery, and 160 TLS destructor checks.
Live response sizes change between captures. Their latency medians do not isolate connection reuse.
The fixed authenticated response benchmark will compare fresh and reused connections with equal response bytes.

`SpriteAssets` owns LittleFS storage, RAM marks, transfers, and cache metrics.
Runtime planning retains generation checks and page ownership. `DevicePayload` owns filtered, atomic V2 document commits.
The real Pi passes one thousand retained-document commits and malformed-response rejection checks.
The physical `mini-1.3.23` capture records 88 samples and nine frames without capture errors or JSON failures.
All samples report current logos ready. Eighteen displayed logo checks match 2,412 backend sprite pixels.
The active user selection remains pinned throughout that capture. It does not measure rotating-page dwell.

`TickerPollingCoordinator` owns timer lifetime and save debounce. `TickerDisplayResponse` owns response decoding and game ordering.
The state owner retains credentials, selection, settings application, and request policy.

`ProviderDemand` reads fleet presence and schedule transitions. It pauses unused specialty feeds and prefetches a ten-minute activation horizon.
`market_sessions.py` owns XNYS regular hours. The calendar includes holidays, daylight-saving changes, and early closes.
The stock source records one final-close refresh after a one-minute settlement window and retains that close across restart.
A deterministic two-hour closed-market replay makes one HTTP request instead of 240 periodic requests for its single-symbol fixture.
This fixture measures request policy. It does not estimate fleet-wide production traffic.
Calendar semantics follow the [exchange_calendars project](https://github.com/gerrymanoim/exchange_calendars).

The enrollment release adds private device secrets and administrator-authorized hash enrollment.
It does not yet require those secrets on the existing data routes. Enforcement follows enrollment and verification of both physical devices.
The API stores hashes separately from fleet metadata. Device projections never include secrets or hashes.

`PresentedFrameHealth` writes one receipt after successful driver presentation.
The Pi updater checks process identity, release, restart time, geometry, and a valid frame hash before accepting a release.
It retains the real rollback release before removing other worktrees.
The Mini overrides the framework's early OTA approval. Its updater retains approval until display validation.
Physical invalid-boot rollback and Pi rollback trials remain before Gate 7 closes.

## March Madness correction

The public example lacked seeds and used NBA placeholders. It now shows an example Duke and Houston tournament matchup.
The backend already owns `away_seed` and `home_seed`. The Mini now retains and renders those fields.
The big ticker's pinned view also renders seeds. Both targets retain separate college-football ranking fields.
The preview includes real 384x32 frames and the production Mini C++ renderer.

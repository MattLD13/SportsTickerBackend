# Final SOW packages

## Scope

The owner requests all five remaining packages. Preserve current modes, app pairing, manual pins, and real display output.
TV calibration and local game-clock interpolation remain excluded.

## Acceptance record

| Package | Required evidence | State |
| --- | --- | --- |
| Mini networking | Compare real request timing, heap, outage recovery, logos, and OTA with the current release. | Implemented. Physical outage and timeout checks pass. Fixed-response comparison remains. |
| Platform cleanup | Extract sprite/cache and payload ownership. Split iOS response and timer responsibilities. Preserve exact pixels and builds. | Published. A new Mini memory correction awaits hardware recovery. |
| Provider efficiency | Own demand and market-session policy. Prove schedule activation, retained close data, and lower request counts. | Published. Demand and calendar tests pass. |
| Security | Issue durable device credentials. Authenticate device reads and mutations. Audit controller and deployment authorization. | Both real credentials verify. Enforcement and boundary tests await publication. |
| Final validation | Prove OTA recovery, frame health, and deterministic performance baselines. | Real Pi rollback passes. Offline pixel baselines pass. Mini recovery remains open. |

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


## Follow-up status

The Mini receives 152 games in one real payload. Its retained document consumes internal memory needed for TLS.
The device logs `X509 - Allocation of memory failed` and stops data and sprite requests.
Its free heap reaches 34,600 bytes. Its lowest recorded free heap reaches 1,768 bytes.
The candidate moves the retained document, filter, and replacement document into PSRAM.
Its constructor now defers filter creation until the runtime accepts a response.
The native payload check preserves 160 games and their logo references after one thousand atomic commits.
The candidate firmware builds. USB recovery now passes. The candidate boots and validates the physical display at 200 Hz.

The update ledger now owns assigned attempts, release quarantine, and durable update events.
A device reports its attempt identity, target version, running version, status, and bounded reason.
An authenticated rollback report quarantines that version for its product family.
The transaction cancels matching family update commands and preserves pairing, settings, heartbeat time, and unrelated commands.
A download failure closes its attempt without quarantining the release. A new attempt can retry that version.
Both clients retain results until the server accepts them.
Ticker Six uses an independent update service and a startup recovery unit.
The Mini uses one IDF activation call after image validation and a final server release check.
This removes the former duplicate boot selection and acknowledgement before successful startup.

The real Pi rejects a running candidate that produces no frame receipt.
It restores the prior release and confirms a new 384x32 frame in 38.66 seconds.
The trial uses an isolated worktree and preserves real device settings and data.
This trial does not simulate a physical power cut.

Four frozen production frames match between the PC and real Pi.
The inputs include verified logo bytes from the real Pi cache. Rendering performs no network requests.
The measurements record Pillow, FreeType, and font identities.
At 15 repeated game panes, real Pi composition measures 0.372 ms p50 and 0.517 ms p95.
The memory frame sink sustains 33.33 paced frames per second. This benchmark does not measure physical DMA or VSync.

The interface labels now use Ticker Six. The internal `full` family identifier remains stable.
The new Swift labels require the next device build check.

## Mini recovery and wire contract

The saved working image restores through ROM recovery. A watchdog reset exits the USB download state.
The revised firmware boots in the other slot and validates its physical display.
A second cache fault rejected completed immutable logos when the page generation changed.
The worker now accepts an identity that the current plan still needs.
It loads flash hits before network misses. One backend transport now owns data, diagnostic, and sprite requests.
The former separate sprite TLS client is removed.

`mini_fields.py` owns the Mini wire fields. The generator emits the matching C++ filter.
Device POST replies omit hidden records. Mini replies retain the fields that its decoder reads.
Controller GET replies retain the full selection data.
A real 152-game input falls from 149,545 bytes to 41,303 bytes, a 72.4 percent reduction.
The production Mini C++ decoder confirms identical selected display fields before and after this projection.
The native cache check passes 2,940 lookups at 15, 20, 50, and 160 games.
The full Python suite passes 652 tests. The critical suite passes 325 tests.

Owner: The Mini field contract owns wire selection. BackendHttpSession owns serialized backend transport.
Removed path: Manual C++ field lists and the separate sprite TLS connection are removed.
Input and output: The real 152-game response produces identical selected Mini facts with 72.4 percent fewer bytes.

## Remaining release evidence

1. Verify the smaller device reply after deployment.
2. Check logo availability and exact captured pixels across a complete physical rotation.
3. Complete the authenticated update result and recovery checks.
4. Run the fixed-response HTTPS comparison and authenticated live request checks.
5. Prove a new Mini boot failure reports after rollback and quarantines its release.
6. Run final critical, full, native, firmware, and iOS checks before publication.
7. Migrate Ticker Six through SSH because its former acknowledgement endpoint is removed.
8. Check live fleet cancellation and retained manual controls after deployment.

Owner: The update ledger owns release policy. Device platform code owns boot validation and durable receipts.
Removed path: Device clients no longer clear update commands before proving startup. Mini activation uses one IDF owner.
Input and output: Assigned rollback reports cancel matching family commands. Real Pi frame failure restores a validated prior release.

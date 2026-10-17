# Final SOW packages

## Scope

The owner requests all five remaining packages. Preserve current modes, app pairing, manual pins, and real display output.
TV calibration and local game-clock interpolation remain excluded.

## Acceptance record

| Package | Required evidence | State |
| --- | --- | --- |
| Mini networking | Compare real request timing, heap, outage recovery, logos, and OTA with the current release. | Implemented. Physical outage and timeout checks pass. The fixed-response comparison passes on the real Mini. |
| Platform cleanup | Extract sprite/cache and payload ownership. Split iOS response and timer responsibilities. Preserve exact pixels and builds. | Published. Memory, wire, and cache corrections pass physical checks. |
| Provider efficiency | Own demand and market-session policy. Prove schedule activation, retained close data, and lower request counts. | Published. Demand and calendar tests pass. |
| Security | Issue durable device credentials. Authenticate device reads and mutations. Audit controller and deployment authorization. | Both real credentials verify. Device enforcement and boundary tests are published. |
| Final validation | Prove OTA recovery, frame health, and deterministic performance baselines. | Real Pi and Mini rollback pass. Family quarantine, offline baselines, and physical logo checks pass. |

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

## Physical release validation

The Mini completes 56 timed visits between 3,010.864 and 3,019.554 milliseconds.
All 83 sports samples report ready current logos across 24 game identities. No reset occurs during this capture.
The pixel check validates 42 logos across 15 games and 4,538 opaque pixels without differences.
Two comparisons lack a current backend asset reference. The check excludes the rank shadow from raw-logo comparisons.

Five equal-size authenticated request pairs compare fresh and reused TLS connections.
Each response contains 58 bytes. Median latency falls from 2,346 milliseconds to 50 milliseconds, a 97.87 percent reduction.
This comparison measures connection setup. It does not measure all game payload transfers.
Ten diagnostic file round trips and 160 client teardown checks pass. The first diagnostic wait records one response timeout.

The controlled Mini trial downloads and verifies the published 25 image before its first boot.
The test then replaces only the pending image with an isolated startup-fault image.
It preserves the valid 26 slot, NVS, and OTA metadata. The fault source never enters Git.
The bootloader restores 26. The device resumes games and reports the failed assigned attempt.
The live server records `rolled_back`, reason `boot_reset`, and a quarantine for Mini version 25.
The Ticker Six release remains unquarantined. The failed version cannot receive another fleet assignment.
This trial tests boot failure and interrupted activation. It does not simulate a physical power cut.

The last corrected boot receipt remains pending until display validation succeeds.
This prevents a startup crash from leaving an installed receipt on the restored firmware.

## Runtime corrections from the hardware checks

A task watchdog trace locates flash-cache reads during TLS work.
NetworkGate now serializes flash access and TLS. Its recursive ownership protects nested updater receipt writes.
LittleSpriteStore builds its file index at mount. Cache count and eviction no longer scan the filesystem on each download.
The retained index uses PSRAM. File count and modification-time ordering remain unchanged.

The pinned Arduino Stream implementation reads secure bodies one byte at a time.
DeadlineClient now uses bulk reads with total-budget, idle-timeout, partial-read, and timer-wrap checks.
The native test confirms three buffer reads without single-byte reads for a twelve-byte input.

The server deployment previously spends ninety seconds waiting for shutdown.
The service now limits shutdown to fifteen seconds.
A combined deployment restarts the backend once after copying code and firmware metadata.
The deployment requires a successful HTTP health check before it reports success.

Owner: NetworkGate owns flash and TLS exclusion. FirmwareUpdater owns durable boot validation.
Removed path: Repeated directory scans, byte-at-a-time TLS bodies, and installed receipts before validation are removed.
Input and output: The real Mini restores 26 after a failed boot. Its authenticated report quarantines only the Mini release.

## Package completion

The five requested implementation packages are complete.
Provider demand and market policy remain published and tested.
Device authentication, shared wire fields, cache ownership, and iOS extraction retain their checked boundaries.
Physical Pi rollback, Mini rollback reporting, family quarantine, pixel checks, and fixed-response timing provide release evidence.
Release 26 receives the final CI and production health checks after publication.

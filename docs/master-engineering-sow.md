# Master Engineering Statement of Work

## Revised plan

**Repository:** SportsTickerBackend
**Baseline:** `a74596046a3672a912ade0dbc7b112d7c167a9d0`
**Status date:** 2026-10-15
**Status:** Replaces the original draft as the active engineering plan.

## Objective

Improve backend-to-device update latency, cross-platform contract quality, asset identity, and measured frame efficiency.
Preserve current API behavior and display output during each migration gate.
Keep provider reads, persistence, projection, scheduling, and rendering in their current owners.

## Scope decisions

- Replace Waitress with an ASGI server for backend HTTP and device WebSocket traffic.
- Keep Flask HTTP routes behind an ASGI adapter during the transport migration.
- Add device streaming through the existing ticker identity and effective projection.
- Define formal schemas before generating cross-language models.
- Measure current card and logo rendering before changing their cache design.
- Keep existing manual live-delay behavior and overlay timing.
- Drop TV clock calibration, the calibration sheet, and per-device TV delay changes.
- Keep operational `AGENTS.md` files and their scoped instructions.
- Preserve `sports_ticker/server.py`, both active dashboards, `test.py`, and public demo assets.
- Keep the Xcode user-state cleanup and duplicate-icon removal as Gate 0 evidence. Both already pass at this baseline.

## Current foundations

| Capability | Current owner | Current state |
|---|---|---|
| Backend service | `sports_ticker/server.py`, `sports_ticker/asgi.py` | Hypercorn serves one ASGI worker. Flask HTTP routes use `WsgiToAsgi`. Device Stream V1 runs through the outer ASGI layer. |
| V2 snapshot | `sports_ticker/projections/data_api.py` | Devices read `/api/v2/tickers/<ticker_id>/data`. |
| Pi delta application | `ticker_core/protocol/model.py`, `ticker_core/protocol/stream.py` | HTTP provides boot state. The WebSocket client validates and applies sequenced deltas. |
| Pi pane surfaces | `ticker_core/app/viewport.py` | Panes render asynchronously. The viewport caches pane surfaces and a tiled strip. |
| Frame reuse | `ticker_core/app/application.py` | Unchanged visual states skip presentation work. |
| Snapshot history | `sports_ticker/application/state_store.py` | Immutable snapshots use bounded per-ticker deques. |
| Fleet storage | `sports_ticker/fleet/repository.py` | SQLite stores device and schedule state. |
| Pi image cache | `ticker_core/platform/assets.py` | Original image bytes use SHA-256 storage. |
| Mini image cache | `esp32_hub75/src/mini/assets/sprite_pipeline.inc` | Backend sprites use validated LittleFS transactions and RAM rendering. |
| Pi deployment | `updater.py` | Immutable worktrees and rollback already exist. |
| ESP32 update flow | `esp32_hub75/src/mini/platform/firmware_update.inc` | Dual-slot update and boot validation already exist. |
| CI | `.github/workflows/` | Python static and device build workflows exist. |

Device Stream V1 provides projection deltas, bounded replay, and snapshot recovery. Gate 4 adds backend-generated Mini sports sprites.

## Workstream 1: Maintain an accurate plan

Record current implementation, owner, evidence, and remaining work in this SOW.
Keep implementation dates and performance claims tied to measured results.
Do not delete code because a disposition table calls it legacy.
Remove a path only after caller, test, route, service, and documentation audits.
Gate 0 verifies that Git tracks no `xcuserdata` files and no `Icon-AppStore-1024 1.png` duplicate.
The app icon manifest must reference the retained image. These cleanup checks already pass at this baseline.
If Git tracks Xcode user state again, run `git rm --cached` and retain local state files.
Remove the duplicate icon asset and update the manifest to reference the retained image.

## Workstream 2: Define cross-platform contracts

Add separate schemas for registration requests, registration responses, normalized hardware profiles, and capabilities.
Add schemas for schedule requests, schedule blocks, effective schedule responses, and firmware manifests.
Add a display response schema with typed content variants.
Design stream schemas after sequence, replay, reset, and field-removal semantics are stable.
Add deterministic positive and negative fixtures for offline schema validation.
Keep cross-field business rules in domain and application owners.
Generate narrow DTOs only after Python, Swift, and C++ contracts agree.

### Contract owners

| Contract | Owner and consumers |
|---|---|
| Registration | `sports_ticker/api/routes.py`, `sports_ticker/fleet/`, Pi and Mini registration clients. |
| Hardware profile | `sports_ticker/fleet/profiles.py`, `TickerHardwareProfile.swift`, Mini registration payload. |
| Schedule | `sports_ticker/domain/schedule.py`, `sports_ticker/application/schedule.py`, `TickerScheduleModels.swift`. |
| Firmware | `sports_ticker/firmware.py`, Pi updater, Mini update manifest reader. |
| Display | `sports_ticker/projections/data_api.py`, Pi protocol model, Mini payload parser, dashboard client. |

The existing `docs/contracts/device-registration.json` differs from route defaults and accepted fields.
Resolve that mismatch before using schemas as runtime request gates.

## Workstream 3: Serve the backend through ASGI

Gate 1 serves the existing Flask HTTP application through Hypercorn and an outer ASGI application.
`asgiref.wsgi.WsgiToAsgi` adapts Flask HTTP routes. The ASGI lifespan owns one `BackendRuntime` start and stop.
Keep existing HTTP paths, statuses, authorization, and bodies stable. Keep one worker until shared publication has evidence.
Preserve `TICKER_HTTP_THREADS` as a bounded concurrent WSGI request limit through per-request thread-sensitive contexts.
Keep WebSocket queues on the ASGI event loop. Projector reads run in worker threads and queue writes stay on the event loop.
Gate 1 passed HTTP parity, bounded concurrency, runtime lifecycle, and local Hypercorn smoke checks in this branch.
Gate 2 adds the device WebSocket route and protocol V1. Device credentials and deployed proxy checks remain open.
Keep `ticker-controller.service` separate from the backend service.

### Transport references

Flask documents `WsgiToAsgi` as its adapter for ASGI servers and shows Hypercorn as a serving option.
Flask HTTP handlers remain WSGI handlers. The outer ASGI layer owns WebSocket protocol handling.

## Workstream 4: Add device snapshot and delta streaming

Retain `GET /api/v2/tickers/<ticker_id>/data` as the boot snapshot route.
Serve `WS /api/v2/tickers/<ticker_id>/stream` in the ASGI application.
Publish deltas from the effective device projection after backend policy applies.
Include mode, schedule, pairing, content order, alerts, news, stale state, and device commands.
Do not stream raw provider changes around projection or schedule owners.

Every stream session needs a `stream_id`, monotonic `seq`, `base_seq`, server timestamp, and protocol version.
Clients apply sequence order. Timestamps measure age and delay.
Support replay with `stream_id` and `after_seq`.
Send a full snapshot when the stream ID changes or replay history expires.
Make snapshot acquisition and stream subscription atomic so updates cannot disappear between them.
Bound each client queue and define slow-client reset behavior.
Keep health heartbeats and OTA acknowledgements independent from stream traffic.
Preserve current manual live delay and durable overlay timing.

`SnapshotStore` and fleet state remain the fact owners. Snapshot writes and HTTP mutations wake active stream projections.
The ASGI projector reads blocking state with `asyncio.to_thread` and writes bounded queues on the event loop.
It checks active tickers once per second for schedule and expiry changes without a direct event.
Never call `asyncio.Queue` methods from provider or runtime threads.
Hypercorn sends WebSocket Ping frames every 20 seconds. The Pi WebSocket client returns Pong frames.
Hypercorn does not expose a Pong timeout setting. Validate proxy idle limits and reconnect through the deployed proxy before rollout.

Read [Device Stream V1](contracts/device-stream-v1.md) for envelope, replay, queue, and recovery rules.
The route validates registered ticker identity and uses the current data endpoint access policy. A device-specific credential remains future security work.

### Provider backoff

Pause stock refresh outside the configured market session and serve the last-good close snapshot.
Define the exchange calendar, time zone, holidays, and extended-hours policy before implementation.
Pause flights and golf refresh when no online ticker uses or schedules those modes within the configured activation horizon.
Read active modes and schedules from fleet state. Do not infer subscriptions from rendered text.
Resume specialty providers when a device becomes online or its schedule enters the activation horizon.
Measure upstream request counts and stale-data age before and after the change.

### Stream validation

Prove reconnect, duplicate, stale, missing, and reordered message behavior with deterministic fixtures.
Prove new content, ordering, schedule, pairing, and command updates reach clients.
Measure bytes per update, fan-out latency, active connections, queue resets, and recovery time.
Test one backend process before planning shared broker or multi-worker support.

## Workstream 5: Make logo assets content-addressed

Add a deterministic sprite identity from source bytes, rendering decision, pipeline version, dimensions, and format.
Expose sprite identity and metadata in the V2 projection.
Add an authenticated or public-cache-safe sprite endpoint with checksum and length metadata.
Start with one Mini sports logo variant and prove cache reuse after reboot.
Invalidate a sprite when source bytes or rendering decisions change at the same source URL.
Write validated sprites atomically and cap persistent storage with an eviction policy.
Keep Pi RGBA assets and Mini RGB565 assets target-specific.
Define a mask or transparency rule because RGB565 has no alpha channel.
Preserve Pi outlines that depend on local background contrast.
Keep album artwork memory-only if a Mini artwork renderer is added later.

The Mini will keep HTTP snapshot polling during the first sprite gate.
Serialize sprite HTTP fetches with other Mini network work.
If the Mini later adopts WSS, it must not open a second TLS session during a sprite miss.
It can pause and reconnect the stream or carry the sprite on the active connection after format and memory tests.
Measure contiguous internal heap before and after TLS handshakes on the target board.
Espressif reports a typical 40–50 KB free-heap requirement during an ESP32 TLS handshake. Actual use depends on SDK and configuration.

### Initial sprite format

Define width, height, row order, RGB565 byte order, mask format, payload length, checksum, and pipeline version.
Use separate outputs for Mini and Pi display sizes.
Do not use one universal outlined sprite when outline choice depends on background.

### Gate 4 implementation and evidence

The backend now owns source selection, shared contained image preparation, versioned identity, and immutable sprite responses.
Mini firmware `mini-1.3.0` advertises sprite protocol 1. Older firmware and Pi projections retain their current payloads.
Each 705-byte file contains a 16-byte header, 648 RGB565 bytes, and a 41-byte coverage mask.
The backend caps stored source and sprite bodies at 8 MiB and 256 entries. The Mini caps committed files at 128.
The Mini serializes HTTP work and renders only from its RAM working set.
The former PNG/JPEG decoders, generated logo overrides, URL selection, and URL cache implementation are removed.

Python tests cover source changes, policy changes, conditional requests, corruption, atomic writes, bounds, and the V2 route.
A native C++ check on the Pi passes three Python wire vectors, all pixels, masks, restart reuse, corruption, interrupted writes, and eviction.
The PlatformIO build uses 73,892 bytes of static RAM and 1,223,605 bytes of application flash.
USB upload to the connected ESP32-S3 completed with a verified flash hash. Serial output confirms `mini-1.3.0` boots.
The Mini now connects to `lehigh-guest` with an empty password. The user confirmed app pairing.
Live sprite downloads, reboot reuse, and TLS heap measurements pass on the physical Mini.
The `mini-1.3.4` image passes physical OTA download and reboot checks.
The published `mini-1.3.5` image passes physical OTA verification, reboot, server acknowledgement, and a second restart.
The backend clears the update command. App pairing and stored sprites survive both restarts.

Hardware provisioning exposed a cross-core NimBLE shutdown crash and an unsigned timer error.
The shutdown task now runs on the NimBLE host core. Credential application uses the scheduler timestamp for both retry timers.
The Mini waits for a credential result read or client disconnect before switching from BLE to Wi-Fi.
This SDK uses sequential BLE and Wi-Fi sessions during provisioning.
The physical check returns `OK`, stops the BLE host, and retries Wi-Fi without a reset.

## Workstream 6: Measure and improve rendering efficiency

Keep pane rendering asynchronous and cache each changed pane surface.
Cache one tiled strip after a pane layout commits. Crop each 384x32 frame from that strip.
The benchmark compares the prior pane loop, the tiled strip, and a bounded ribbon.
The Windows fixture records a 94.9 percent p50 composition reduction at 60 panes with identical pixels.
The 60 pane cache adds about 1.0 MiB. The ribbon uses less memory and renders slower.
Use the two source panes in the fixture for 1, 10, and 60 capacity scenarios.
The 60 pane case repeats those two records and does not represent 60 unique games.
Read `tools/benchmarks/README.md` for measurements and limits.
Measure startup readiness, pane update latency, p50 and p95 frame build time, CPU, and memory.
Record actual scroll cadence from runtime configuration instead of assuming 60 FPS.
Retain card ordering, separators, wraparound, stale-worker protection, and late asset updates.
Expand cache keys to cover every pixel-affecting setting, asset revision, font, and layout choice.
Refactor one renderer family at a time after capturing real `384x32` output baselines.
Use selected Pillow operations for measured hot loops only.
Preserve connected-border logo removal because global color masks erase enclosed white details.

Debug JSON files are render inputs, not pixel-golden images.
Create explicit PNG or pixel-hash baselines with fixed fonts, Pillow version, assets, and render time.

The Pi stream parser now freezes incoming replacements once and shares unchanged immutable sections.
Captured live-message replay on the real Pi reduces median delta processing from 457.757 ms to 64.337 ms.
The output and 12 rendered sports frames retain identical hashes.
Short live overlay runs reduce observed overruns from 1.057 percent to 0.806 percent at the same frame cadence.
The first candidate passes the physical 15-game test. The final pane change passes deterministic 15-pane checks.
Pane cache comparisons now retain immutable scenes. Identical captured nine-pane cache checks fall from 124.567 ms to 0.715 ms.
The physical application replay processes 120 identical messages per release at the same frame cadence.
Its overrun rate falls from 3.337 percent to 1.614 percent. Its longest frame falls from 180.087 ms to 80.385 ms.
Bounded frame logs now split update acceptance, preparation, and composition work.
Read [the Pi stream report](research/pi-stream-overruns-2026-10-14.md) for evidence and measurement limits.

### Mini display style

The `mini-1.3.2` build adapts the main scrolling pane to 64x32.
The main ticker owns shared glyphs and colors. Generated C++ data keeps the Mini definitions aligned.
The Mini uses 16x16 RAM marks, clear score bounds, and two rows for long center labels.
Twelve native Mini previews include a production V2 record and local layout examples beside real 384x32 main ticker frames.
The Mini runs the UI build through USB. Live backend, pairing, sprite transfer, and reboot cache checks pass. Read [Mini display style](research/mini-ui-unification-2026-10-15.md) for owners and limits.

## Workstream 7: Modernize ESP32 modules and resource use

Split `.inc` modules only with explicit interfaces and stable initialization order.
Keep matrix refresh, network work, buffers, and mutex ownership unchanged during the first split.
Use [the platform module map](research/platform-modularization-map.md) to select the first pure drawing split.
Measure memory and frame stability on the target board before changing task placement.
Retain existing dual-slot OTA and boot validation while adding focused recovery checks.
Add native parsing tests only when the PlatformIO target can run them reliably.

## Workstream 8: Modularize the iOS client

Split `ContentView.swift` by screen while retaining state ownership and current request timing.
Extract HTTP and WebSocket clients behind tested service interfaces.
Use [the platform module map](research/platform-modularization-map.md) to sequence BLE and model extraction.
Preserve token auth, BLE provisioning, schedules, and update flows.
Add simulator build and focused serialization tests before each screen migration.

## Workstream 9: Security, deployment, and runtime ownership

Keep the backend service and Pi controller service as separate deployment targets.
Audit mutating route authentication and firmware checksum verification by endpoint.
Keep runtime data outside immutable Pi releases.
Keep the existing Pi worktree updater unless measured failures require another deployment design.
Use one ASGI worker until provider and stream state have a shared ownership design.
Add rollback checks for healthy rendered frames before replacing service activity checks.

## Workstream 10: Observability and CI

Add push-to-main and contract-path triggers to static and device build workflows.
Report frame latency, bytes transferred, stream reconnects, queue resets, and sprite cache hits.
Keep tools in place until moves update imports, workflow paths, and documented commands.
Keep `test.py` because setup documentation uses it as a device diagnostic.

## Workstream 11: Evaluate quick wins individually

Measure local game clock interpolation before adding it to sports payloads.
Measure brightness and current on real panels before adding a brownout limiter.
Treat tmpfs as a write reduction, not a zero-write guarantee.
Validate mDNS discovery with current iOS permissions and network isolation.
Adopt `orjson` only after response equivalence and serialization benchmarks.
Do not add restart-state hydration until the cache and startup lifecycle define valid state.

## Dropped scope: TV delay calibration

Do not build TV clock calibration, a calibration sheet, or per-device calibration APIs.
Keep existing manual live-delay settings and delayed snapshot behavior.
Do not delay or recalibrate score alerts beyond current policy.

## Delivery gates

| Gate | Completion evidence |
|---|---|
| 0. SOW and contracts | Revised scope, schema inventory, request/response mismatch fixed, offline fixtures pass, Xcode state untracked, duplicate icon removed. |
| 1. ASGI transport | Existing HTTP checks pass, bounded concurrency remains, health passes, one runtime starts and stops once, no API contract changes. |
| 2. Device stream | V1 projection, sequence replay, queue reset, and route identity checks pass. Device credentials and deployed proxy checks remain open. |
| 3. Pi client | V1 HTTP boot, WebSocket reconnect, delta application, and real `384x32` frame checks pass. Bounded local logs record stream and frame timings for a deployed Pi run. |
| 4. Mini client | Cache miss fetches once, reboot reuses validated bytes, same-URL policy changes invalidate, RAM stays bounded. |
| 5. Rendering efficiency | Benchmark beats the recorded baseline without pixel or lifecycle regressions. |
| 6. ESP32 and iOS modularization | ESP32 module splits compile and preserve measured memory and frame stability. The iOS app builds in CI and focused schedule and profile serialization checks pass. |
| 7. Security, CI, and operations | Mutating route auth and OTA checksums have evidence. CI runs on direct `main` pushes and contract changes. Each quick win has a recorded go/no-go result. |

## Evidence and change notes

Every gate records owner, former path changed, real input, real output, and test evidence.
Use the Pi performance log to compare deployed frame and stream behavior after release.
Use hardware measurements for panel power, refresh stability, and Mini memory claims.
Use production-shaped API payloads for protocol and projection checks.

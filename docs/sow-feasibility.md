# SOW Feasibility and Reality Check

## Basis

This assessment uses repository baseline `a74596046a3672a912ade0dbc7b112d7c167a9d0`.
It replaces claims from the original attachment with current code evidence and revised gates.
The active plan lives in [master-engineering-sow.md](master-engineering-sow.md).
The first-wave platform findings live in [platform-modularization-map.md](research/platform-modularization-map.md).

## Summary

The program is feasible when it ships as separate, measured workstreams.
The original acceptance criteria mix implemented features, risky rewrites, unsupported performance claims, and a new calibration feature.
TV delay calibration is dropped by owner direction.
Existing manual live delay remains in scope as a behavior to preserve.

| Original area | Assessment | Updated treatment |
|---|---|---|
| Repository hygiene and packaging | Partly complete. | Keep existing docs, pytest, Ruff, Mypy, and CI work. Stage package metadata and dependency migration separately. |
| V1 purge | Incorrect as a blanket delete list. | Preserve active launchers, diagnostics, dashboards, and public demo assets. Remove only paths proven unused. |
| Renderer ports | Feasible as maintenance work. | Refactor one family at a time and preserve real `384x32` output. |
| Pre-rendered ribbon | Unproven and partly redundant. | Benchmark against existing asynchronous card surfaces before adoption. |
| Pillow vectorization | Feasible for measured hot loops. | Preserve alpha rules, edge behavior, and connected-border removal. |
| Provider demand polling | Feasible with policy tests. | Separate provider scheduling from device transport and record request volume first. |
| HTTP pooling and caching | Feasible by provider adapter. | Add timeouts and conditional requests only where upstreams support them. |
| Device WebSocket deltas | Feasible, high integration risk. | Add an ASGI boundary, effective-projection stream, sequence replay, and full-snapshot recovery. |
| Deep-copy-free snapshot history | Partly complete. | Bounded immutable snapshot references exist. Per-game delta history is a separate design. |
| TV delay calibration | Dropped. | Keep the existing manual delay and overlay behavior. |
| Cross-platform schemas | Feasible, high value. | Fix current registration mismatch and add request, response, schedule, profile, firmware, and display schemas. |
| Content-addressed sprites | Feasible in stages. | Begin with Mini sports logos and target-specific formats. Keep Pi RGBA and Mini RGB565 policies distinct. |
| ESP32 `.inc` conversion | Feasible, medium risk. | Split modules only with interface, initialization, and hardware checks. |
| ESP32 dual-core task changes | Partly implemented, hardware-sensitive. | Preserve current placement until measurements prove a need to change it. |
| OTA rollback | Existing foundation. | Retain current dual-slot flow. Add evidence for failure and recovery gates. |
| iOS modularization | Feasible, medium effort. | Split one screen and service boundary at a time. Keep BLE and token behavior stable. |
| Pi atomic deployment | Already implemented in substance. | Keep immutable worktrees and rollback. Improve health evidence before replacing deployment. |
| Backend service migration | Gate 1 implemented in this branch. | Hypercorn serves one ASGI worker. Flask HTTP routes pass through `WsgiToAsgi`. Gate 2 still owns device WebSockets. |
| Telemetry and CI | Partly complete. | Add stream and render metrics. Trigger checks on direct main pushes and contract changes. |
| Quick wins | Mixed. | Require a measured benefit and target hardware evidence for every item. |
| Thread-to-async publication | Feasible and required for stream safety. | Use `loop.call_soon_threadsafe` or a bounded thread-safe broker. Never write to event-loop queues from provider threads. |
| WebSocket keepalive | Feasible with proxy validation. | Send Ping frames every 20 seconds, check Pong timeouts, and test reconnect through the deployed proxy. |
| Mini TLS and sprite fetches | Feasible with device limits. | Keep Mini on HTTP polling first and serialize TLS work. Measure internal heap before enabling WSS. |
| Off-hours provider backoff | Feasible with explicit policy. | Respect market calendars and pause flights or golf only when no online or scheduled subscriber needs fresh data. |
| Xcode state and icon cleanup | Complete at this baseline. | `xcuserdata` is no longer tracked. The duplicate icon is removed and the manifest points to the retained asset. |
| Delivery gates | Incomplete in the prior SOW. | Add Gate 6 for ESP32 and iOS. Add Gate 7 for security, CI, and measured quick wins. |

## SOW claims to remove or rewrite

| Claim | Why it is inaccurate or risky | Replacement |
|---|---|---|
| Delete `sports_ticker/server.py`. | It starts the active V2 production runtime. | Keep it until the ASGI entry point owns the same lifecycle and HTTP contract. |
| Delete `test.py`. | Setup uses it as a Pi hardware diagnostic. | Keep it and classify it as operations tooling. |
| Remove one dashboard tree. | Both `/` and `/dashboard` are active. | Audit templates by route and keep both until product scope changes. |
| Delete the music demo cover. | The public demo loads that asset. | Keep the asset and existing demo contract. |
| Store logos forever by URL. | URLs do not track changed bytes or render policy. | Use versioned content identity, bounded storage, and eviction. |
| Use one RGB565 sprite everywhere. | RGB565 lacks alpha and target sizes differ. | Define separate target formats and masks. |
| Let provider patches update devices directly. | This bypasses schedule, pairing, delay, and projection owners. | Stream the effective device projection. |
| Use timestamp-only last-write-wins. | Timestamps can collide or move backward. | Apply sequence order. Use timestamps for age and delay. |
| Poll full schedules only every 15 minutes. | New content and mode transitions need prompt delivery. | Use versioned snapshots plus event-driven deltas and recovery. |
| Claim 60 FPS from `scroll_speed`. | Runtime cadence is configurable and differs by state. | Record actual frame intervals and latency distributions. |
| Require pixel-identical debug JSON snapshots. | JSON files define inputs, not rendered goldens. | Add real PNG or pixel-hash references with pinned inputs. |
| Promise zero SD writes. | Volatile logs and tmpfs reduce writes but cannot guarantee none. | State a measured write-reduction target. |
| Promise software-only brownout prevention. | Current draw depends on panel, power supply, and wiring. | Validate brightness limits with current measurements. |

## Transport decision

The current backend uses Hypercorn with one ASGI worker.
An outer ASGI application owns runtime lifecycle and adapts Flask HTTP routes with `asgiref.wsgi.WsgiToAsgi`.
Gate 2 adds the device WebSocket route. The ASGI application currently rejects WebSocket scopes.
The backend runtime starts once. Keep one worker until shared state has a proven design.
The Pi service remains separate from the backend service.

Provider work runs in standard background threads. WebSocket queues run on the ASGI event loop.
Use `loop.call_soon_threadsafe` or a bounded thread-safe bridge when providers publish updates.
Configure 20-second Ping frames and a Pong timeout. Validate actual proxy idle limits instead of promising that connections never drop.

The Mini will use the existing HTTP snapshot path in its first stream release.
It will serialize sprite downloads and other TLS work.
Enable Mini WSS only after free internal heap, reconnect, and simultaneous-network-work tests pass.
Espressif lists 40–50 KB as typical free heap for an ESP32 TLS handshake, not a fixed total connection cost.
See the [Espressif TLS FAQ](https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/protocols/esp-tls.html).
The deployed Arduino and PlatformIO configuration must supply the final memory measurements.

Flask documents its WSGI-to-ASGI adapter and shows Hypercorn as an ASGI serving option.
See [Flask ASGI deployment](https://flask.palletsprojects.com/en/stable/deploying/asgi/) and [Flask production deployment](https://flask.palletsprojects.com/en/stable/deploying/).

## Logo and render feasibility

Pi and Mini caches already retain assets. The missing work centers on identity, invalidation, and measured speed.
The Mini uses small RGB565 logos. The Pi keeps RGBA images and selects outlines from its current background.
The sprite identity must include source bytes, rendering policy, pipeline version, target size, and format.
The first sprite experiment can target one Mini sports logo family.

The Pi viewport already caches independent card surfaces. A continuous ribbon can reduce composition work but increases memory and rebuild costs.
Benchmark current surfaces, flattened surfaces, and a bounded ribbon with 1, 10, and 60 cards.
Record startup, update latency, frame latency percentiles, CPU, and memory.
Accept a new design only when it improves a recorded measure and preserves card order, wraparound, and failure recovery.

## Risks and dependencies

| Risk | Required control |
|---|---|
| ASGI migration changes request behavior. | Compare status, auth, body, and lifecycle behavior across all existing V2 routes. |
| Snapshot and stream race loses updates. | Define an atomic snapshot-to-stream boundary and replay cursor. |
| Multiple workers duplicate provider loops. | Keep one worker until runtime ownership or shared publication has proof. |
| Client buffers grow without bound. | Set queue limits and reset slow clients to a full snapshot. |
| Schema codegen changes defaults. | Validate existing default and normalization behavior before generating models. |
| Sprite updates corrupt flash or cache. | Verify size, checksum, format, atomic write, eviction, and reboot reuse. |
| Render refactor changes display output. | Capture real output baselines and compare fixed-input frames. |
| Provider cadence increases upstream load. | Measure requests by provider and test backoff under failure. |
| Provider thread writes to event-loop state. | Route every cross-thread publication through a thread-safe bridge. |
| Proxy idle timeout closes a healthy stream. | Send protocol Ping frames and prove reconnect behavior through the actual deployment path. |
| Mini TLS handshakes exhaust fragmented heap. | Keep HTTP polling first and measure free internal heap during one serialized secure request. |
| Specialty feed pauses during an upcoming schedule. | Include the schedule activation horizon in subscription checks and test schedule transitions. |

## Completed cleanup evidence

The baseline no longer tracks Xcode `xcuserdata` files.
The duplicate `Icon-AppStore-1024 1.png` file is gone, and the app icon manifest references the retained image.
Keep these checks in Gate 0. Do not repeat destructive cleanup when the evidence already passes.

## Recommended delivery order

1. Reconcile SOW facts and record a baseline for current API, display, assets, and runtime cadence.
2. Correct registration schema and add offline contract schemas and fixtures.
3. Design and ship the ASGI transport while preserving the current HTTP API.
4. Add effective-projection WebSocket deltas, sequence replay, and snapshot recovery.
5. Integrate the Pi stream client and prove reconnect plus real frame output.
6. Add one content-addressed Mini sports sprite with bounded persistent storage.
7. Benchmark rendering alternatives, then refactor only measured hot paths.

Do not add TV calibration to gates, APIs, UI, or acceptance checks.

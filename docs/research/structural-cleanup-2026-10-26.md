# Structural cleanup review

This review covered provider caches, stale results, payload parsing, worker transport, and server refresh boundaries. It did not cover every repository path.

## Completed

- ESPN scoreboard and event reads and FotMob match reads share concurrent request coalescing.
- ESPN catalog reads share successful-result caching with start-time expiry.
- ESPN, FotMob, weather, and feature providers share settings-scoped stale result projection.
- Provider payload shape checks share mapping and sequence helpers.
- Provider requests and recovery probes share local worker socket transport. Each caller keeps its own contract validation.
- Worker result decoding shares content and health construction across individual and batch responses.

## Remaining

- `weather.py` caches forecast points, UV data, and office names with distinct keys and lifetimes. Review those source contracts before sharing a cache.
- `catalog.py` allows concurrent loads and expires from request start. `singleflight.py` coalesces loads and expires from completion. Keep these policies separate.
- `application/refresh.py` owns snapshot refresh. `application/scheduler.py` owns scheduling, provider recovery, and batch dispatch. Similar error handling serves different boundaries.
- `backend_ops/manager.py` controls release recovery. `backend_ops/diagnostics.py` collects bounded evidence. Their file reads have different failure and size policies.

## Controller, Mini, and application review

- `TickerControlApp/TickerControl/Services/TickerHTTPClient.swift` owns request transport and common response errors.
- `TickerControlApp/TickerControl/ViewModels/TickerViewModel.swift` has repeated callbacks with different status codes, cancellation, and selection rules. Separate those contracts before further extraction.
- Mini checksum consolidation was tested separately. It is not included in this publication.
- `sports_ticker/application/events.py` creates alerts and news through similar methods. Their domain event types and public defaults remain separate.
- `sports_ticker/application/refresh.py` assembles snapshots. `scheduler.py` controls due work and recovery. A shared exception wrapper would blur their distinct failure boundaries.
- The review sampled these workflows. It did not inspect all controller views, Mini hardware drivers, native paths, or application services.

## HTTP client ownership review

- `production.py` owns the shared ESPN catalog and weather resolver. `bootstrap_v2.py` owns its resolver. Application shutdown closes these resources once.
- `api/routes.py` registers its stock catalog for application shutdown. An injected catalog remains caller-owned.
- Hybrid weather shares one client with its Open-Meteo fallback. Only the constructing provider closes that client.
- FotMob waits for its own detail executor before closing its client. An injected executor and client remain caller-owned.
- The golf factory transfers its source to the provider. A directly injected golf source stays caller-owned.
- ESPN owns its NHL source in factory composition. NHL, stock, and news defer pool cleanup until a background refresh ends.
- News retains a lease on a shared ESPN catalog until its refresh ends. An independent news worker owns its catalog and transaction source.
- Racing closes its owned JSON and text clients after scheduler work stops. Endurance timing sockets close after each snapshot.
- Provider shutdown assumes callers stop direct synchronous fetches first. The scheduler waits for its executor before closing providers.
- An injected FotMob executor remains caller-owned. Its owner must finish pending detail tasks before provider shutdown.
- The installed `FlightRadar24API` and `APIClient` expose no public close method. Their session is private. Do not close it through private attributes.

## Repository inventory

An exact AST comparison covered 189 tracked production Python files. It compared function bodies with at least two statements. It did not prove near-duplicate behavior or review every caller.

- Server snapshots, domain content, provider contracts, normalization, and scheduler values now share one freeze function.
- `domain/events.py` and `fleet/models.py` convert mapping keys to strings. Their policy differs from the shared freeze function.
- `providers/espn.py` and `providers/sports_display.py` repeat MLB player-name extraction. Review the shared sports fact owner before changing that boundary.
- `providers/features.py` and `providers/normalization.py` repeat first-present-key selection. This small helper retains explicit behavior at each boundary.
- Six polling and card workers share one CPU affinity helper. Frame and viewport code share frozen-value conversion.
- `ticker_core` retains duplicate sports color helpers. Review their renderer semantics before consolidation.
- Swift review sampled HTTP request handling and polling in `TickerViewModel.swift`, `TickerHTTPClient.swift`, and `TickerPollingCoordinator.swift`. Request paths have distinct status and cancellation rules.
- Mini review sampled asset validation, sprite residency, and scheduling. Format checks, cache windows, and frame timing have distinct owners.
- The AST comparison was complete for the selected Python file set. Swift, C++, generated code, shell scripts, and their cross-file behavior received only sampled review.

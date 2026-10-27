# Input-to-display latency

The timing trace follows provider input, core receipt, snapshot commit, stream preparation, publication, client reception, decoding, and successful presentation.
It preserves source identity through the worker JSON contract and the Pi polling-process bridge.

## Ownership and boundaries

| Owner | Measurement |
|---|---|
| `providers/espn_fastcast.py` | Fastcast receive time, nested wrapper `ts`, and the matching event version. |
| `backend_ops/worker_contract.py` | Core worker request and receipt times. Retain earlier input timing when available. |
| `application/state_store.py` | Snapshot commit time. Timing changes do not create delayed fact-history entries. |
| `projections/data_api.py` | Optional V2 snapshot timing. Strip private trace fields from renderer data. |
| `device_stream.py` | Stream preparation and publication times. Timing-only changes do not publish extra updates. |
| `ticker_core/app/poller.py` | Receive, decode, transfer preparation, and process-queue timestamps. |
| `ticker_core/app/viewport.py` | Current pane readiness and changed pixels inside the presented viewport. |
| `ticker_core/app/application.py` | Acceptance and successful frame-sink return. |
| `ticker_core/platform/performance.py` | Bounded `kind: latency` JSONL records written outside the frame loop. |

`input_boundary` defines the start point. It is not an inferred game-action time.
Fastcast uses complete socket receipt before wrapper decoding and patch application.
HTTP snapshot timing starts when the provider applies that snapshot.
Other workers start at core receipt when no earlier provider trace exists.
Their request timestamp also permits request-to-display measurement.
Missing upstream timestamps remain unavailable.

The Pi measures each input trace only at its first presentation for that item and device.
It records superseded input, removed items, unchanged pixels, and already-presented traces separately.
A scrolling update requires the current pane version and changed pixels inside the visible window.
An unrelated frame cannot end the timer.

## ESPN timestamp evidence

Live official Fastcast publications contain a JSON string in `pl`.
That wrapper contains `ts`, `~c`, and the compressed patch payload.
The observed `ts` values use UTC Unix milliseconds.
Message `mid` values are sequence identifiers and are not timestamps.

The trace labels this basis `publisher_envelope`.
It provides an age relative to ESPN's publication wrapper.
It does not prove the time of the real-world play, venue capture, or television presentation.
Scheduled game dates and period clocks do not substitute for a live-event timestamp.

## Validated physical trial

The final trial uses live NBA data, the production ticker-scoped provider entry, and the production web API snapshot schema.
An isolated backend runs the scheduler, snapshot store, and V2 stream.
The physical Six uses temporary credentials and device state.
Two encrypted SSH forwards connect the hosts through the workstation.
The trial excludes production worker IPC. Its network delay includes those forwards.

The final 90-second capture contains ten presented records.
One repeats an input trace that already reached the screen. The report excludes that repeat.
Nine unique first presentations remain, including one with a usable Fastcast publication timestamp.
One other record contains unchanged pixels and has no first-display latency.

For the unique Fastcast input:

| Interval | Observed time |
|---|---:|
| ESPN wrapper timestamp to server receipt | 140.6 ms |
| Receipt to snapshot ready | 1,659.5 ms |
| Snapshot ready to display boundary | 105.4 ms |
| Device receive to display boundary | 71.5 ms |
| Server receipt to display boundary | 1,764.9 ms |
| ESPN wrapper timestamp to display boundary | 1,905.5 ms |

This single trace proves the path. It does not establish a typical latency or a tail percentile.
The six HTTP-snapshot traces range from 5.154 to 9.817 seconds from snapshot application to the display boundary.
Their upstream publisher time is unavailable.

Most observed wait occurs before the snapshot becomes ready.
The shared ESPN source cache retains results for five seconds.
That cache and HTTP reconciliation are concrete targets for investigation before further renderer tuning.
This measurement does not assign all pre-snapshot wait to one cause.

The end boundary is successful frame-sink return.
For `RgbMatrixFrameSink`, this follows the vertical-sync swap.
The trial does not measure LED scan completion or photons with a camera.

## Clock checks

The server and Pi report NTP synchronization.
The Pi reports a two-millisecond offset in the recorded clock check.
Windows Time is stopped on the workstation. Three NTP probes show its clock about 1.76 seconds ahead.
The physical trial uses server and Pi timestamps. It does not use the workstation clock for cross-host differences.
Clock-order failures remain visible instead of becoming clamped zero delays.

## Validation and operation

The full Python suite passes 1,374 tests, with ten platform skips.
The public demo provenance check also passes.

The V2 timing schema is `docs/contracts/display-timing.json`.
Measurement metadata does not alter display fingerprints, renderer inputs, or delayed fact history.
The compact Mini response omits detailed timing metadata.
The worker contract keeps its strict value shape. The core adds receipt timing while decoding canonical worker results.

Use the bounded Pi performance log to collect normal runtime traces after publication.

```powershell
python tools/diagnostics/latency_report.py --log capture.jsonl --output previews/latency/report.json
```

The tool writes JSON and HTML. It deduplicates input traces per device and omits tail estimates below twenty samples.
The validated trial evidence remains under `previews/profiling/2026-10-25/latency/`.
Earlier setup attempts produced no valid complete trace and supply no latency estimate.

The diagnostic service uses an automatic runtime limit and restores the normal Pi controller through systemd.
The normal release is active again. Temporary diagnostic credentials have been removed.
The implementation remains local and has not replaced the deployed releases.

## Faster source publication

Fastcast now assigns a version to each league snapshot and wakes source-change readers.
Each worker lifetime has a different identity. A worker restart cannot reuse an old version.
The local worker contract carries bounded change waits separately from fetch requests.
Those waits do not acquire the provider fetch lock.

The ESPN provider compares versions before it reuses the five-second source cache.
Its live refresh projects retained snapshots without starting HTTP reconciliation.
The ordinary five-second reconciliation deadline remains separate.
Cached schedules, rankings, logos, and NHL situations remain available to that projection.

The production scheduler reads providers in a bounded executor.
The runtime wakes when a source changes or a provider finishes.
It publishes available results without waiting for another provider's unfinished request.
It coalesces source notifications and selects tickers that enable the changed league.
It rejects a completed result when ticker settings changed during the read.
Snapshot publication still uses complete immutable provider results and compatible retained data.

One read remains active per provider. A slow ESPN request can still delay a subsequent ESPN source refresh.
This limit prevents simultaneous fetches against the same worker and its mutable provider caches.
The live comparison must measure that case before any stronger latency guarantee.

The full suite passes 1,381 tests, with ten platform skips.
Focused tests cover immediate cache invalidation, notification wakeups, blocked unrelated providers, and changed settings during a read.

The Linux benchmark sends fifty controlled patches through an actual worker process and Unix socket.
It uses the production scheduler, normalization, refresh service, and snapshot store.
Input-to-snapshot time has a 2.555 ms median, a 3.318 ms 95th percentile, and a 4.377 ms maximum.
These values exclude the internet feed and display. They are not a replacement for the physical live trial.

```text
python tools/benchmarks/worker_notification_latency.py --samples 50 --output previews/latency/worker.json
```

## Collection through midnight

The isolated diagnostic runs an ESPN worker, V2 server, and production Six renderer with a memory frame sink.
Its local WebSocket connection uses no SSH forwarding.
The collector changes no deployed release, normal service, or physical display.
It selects a live game when one becomes available.
Before a live game starts, scheduled-game frames validate the path but do not establish live latency.

```text
python tools/diagnostics/latency_probe.py server --data /tmp/ticker-latency-study --seconds 120
```

The collector binds only to localhost and uses a temporary device token.
It removes that token when it stops.
An external service runtime limit also bounds the authorized daily collection.
The October 26 collection stops at midnight Eastern. A chat heartbeat checks results every thirty minutes.
The heartbeat reports meaningful changes, failures, and completion.
The memory-sink report remains separate from the original physical-screen report.

## League batches and shared worker results

The worker now accepts up to 256 ticker settings in one explicit `fetch_batch` request.
The ordinary eight-megabyte request and response limits still apply.
Larger ticker sets use bounded chunks.
The response contains one immutable game table and a separate result for each ticker.
Each result references game-table indices. It retains its own alerts, news, health, and observation time.
The core decodes each shared game once and rejects missing ticker results or invalid references.

The ESPN provider prepares each matching source view once per batch.
It captures matching Fastcast versions and retained snapshots under one source lock.
Later feed updates remain available for the next batch and cannot split an existing batch across input versions.
The provider retains up to 4,096 game projections keyed by event identity, input trace, and ranking or logo context.
An unchanged game can reuse its immutable projection.
Ticker alert histories, conference filters, settings, and delayed viewing remain separate.

The source notification reader combines a burst for at most 25 milliseconds after the first change.
Further messages do not extend that window.
It applies every incoming patch. Only display preparation is combined.
Individual device streams still use their existing V2 projections and deltas.
The shared worker table does not send another customer's settings or alerts to a device.

The 150-game test found a former patch-tagging defect.
An absent `from` field on an ordinary patch marked every league event as changed.
The corrected code reads `from` only for copy and move operations.
A one-game update now rebuilds one projection and retains the other 149.
The earlier single physical trial has unverified game-level source attribution because it used the former tagging code.
Its timings remain historical diagnostics. A new capture must establish a precise game-level comparison.

The paired Linux benchmark uses 150 college-football-shaped games and 150 tickers.
It alternates request order and includes both complete-league changes and one-game changes.
Both methods use the same candidate code and real Unix socket transport.
The comparison isolates per-ticker requests versus shared batch transfer. It does not compare complete deployed releases.
All paired display-data digests match.

| Median across eight paired trials | Individual requests | Shared batch |
|---|---:|---:|
| Worker-to-core assembly and transfer | 3,423.5 ms | 568.2 ms |
| Core process CPU | 1,587.5 ms | 38.8 ms |
| Worker responses | 150 | 1 |
| Response bytes | 21,120,450 | 240,006 |
| Decoded game objects | 22,500 | 150 |

These are controlled measurements. They exclude the internet source, subsequent snapshot publication, and physical display.
Per-ticker alerts and settings still require work inside the worker.
The fifty-sample notification test includes the deliberate batch window.
Its input-to-snapshot median is 27.746 ms. Its 95th percentile is 28.510 ms.
The former 2.555 ms controlled median used no batch window.
The additional bounded wait trades a small isolated-update delay for fewer repeated operations during bursts.

```text
python tools/benchmarks/league_batch.py --games 150 --tickers 150 --pairs 8 --output previews/latency/batch.json
```

The full suite passes 1,387 tests, with ten platform skips.
The daily collector now uses the batch path. It recorded no live Fastcast first presentations before that change.
Normal services and deployed releases remain unchanged.

## Complete scrolling rotation

The clarified workload contains 150 games on one scrolling Six ticker.
The former viewport sliced its input to sixty cards. That slice is removed.
Timing collection also retains every eligible game in the current response.
It removes pending timing records when games leave the active response instead of discarding records after sixty entries.
The completed-trace cache retains its separate bounded history.

The regression test renders 150 panes and confirms that the last game remains in the scrolling layout.
Updating that game renders one replacement card and keeps the other 149 card surfaces.
The timing test also records the final game and removes timing state for games outside the rotation.

A production-path check parses V2 data, classifies content, and renders the scrolling viewport with the standard renderer catalog.
It retains all 150 panes, from `game-1` to `game-150`, with no failed renders.
The strip width is 13,926 pixels for these controlled fixtures.
Inspected 384x32 frames cover the first game, the former cutoff, and the final game with the rotation seam.
Evidence remains under `previews/profiling/2026-10-25/latency/150-pane-rotation/`.

This change removes the cutoff. It does not change the generation commit barrier, render priority, or complete strip composition.
Physical Pi measurements with 150 scrolling games remain separate work.

The full suite passes 1,389 tests, with ten platform skips after the cutoff removal.

## Visible-first scrolling and physical validation

The viewport now installs completed card surfaces before unrelated pending cards finish.
It keeps the last good surface for other games while their latest data waits for rendering.
The pending queue starts at the currently visible pane and continues forward around the rotation.
One active render can finish before the worker changes priority. Pending requests retain only the latest desired scene.

Same-size card updates patch their existing strip rectangles and both affected dividers in every repeated strip copy.
Changes in pane order, width, or strip height use a complete composition.
A strip revision invalidates the frame cache when card pixels change without a payload or offset change.
Frame cropping and strip mutation use the same lock.
Cold start publishes the first complete screenful, then extends the strip in screenful increments.
An equal new payload retains already completed cold-start card work.

The tests block an off-screen renderer while a visible replacement reaches the strip.
They also verify forward queue order across the seam, transparent pixels, divider colors, and changed geometry.
The full suite passes 1,395 tests, with ten platform skips.

The physical comparison uses 150 controlled games on one Six and its actual RGB matrix driver.
Both variants use the same input document, normal polling process, queue bridge, application, and card process.
The baseline contains the former viewport with only its sixty-card cutoff removed.
Temporary service units stop the normal controller and restore it through an explicit stop handler.
The diagnostic never modifies a running release or controller configuration.

Each main trial injects nine updates during forty-five seconds of scrolling, followed by a six-second drain window.
Updates alternate between one fully visible game and all 150 games.
The number of fully visible targets can differ with scroll position.

| Physical comparison | Former viewport | New viewport |
|---|---:|---:|
| First scrolling screenful | 29.723 s | 5.524 s |
| Full 150-pane warmup | 29.723 s | 28.444 s |
| Targeted visible updates presented | 1 of 15 | 16 of 16 |
| Average presentation rate | 32.595 FPS | 32.616 FPS |
| Full strip rebuilds during warm updates | 1 | 0 |
| Main process peak resident memory | 77,232 KiB | 74,576 KiB |

Five visible single-game updates have a 353 ms median and a 394 ms maximum in the new main trial.
Eleven visible targets from complete-game bursts have a 720 ms median and an 882 ms maximum.
The former viewport presents no targeted burst result during its measurement window. Its one successful single-game result takes 419 ms.
Those small counts do not establish a general latency distribution or a 95th percentile.

Average scroll rate remains stable. Large payload acceptance still causes occasional presentation gaps of about 200 ms in both main trials.
The new design fixes the publication barrier. It does not eliminate all application acceptance work or every scroll pause.
Off-screen images can remain pending while their latest source data stays retained.

A separate physical trial starts at pane 148 and crosses the last-game seam.
It retains 150 panes, crosses the seam once, presents four of four targeted visible changes, and uses no warm-update strip rebuilds.
Its first scrolling screenful appears after 9.340 seconds. Startup timing varies between these short trials.
Inspected 384x32 captures show multiple panes before and after the seam.

These measurements start at controlled V2 input in the Pi polling process and end after the physical frame-sink returns.
They exclude provider latency, network delivery, and LED scan completion.
An earlier diagnostic pair parsed input on the drawing thread and remains separate from the normal-process comparison.

The evidence resides under `previews/profiling/2026-10-25/latency/scrolling/`.
The normal controller is active on its original immutable release. The diagnostic units are stopped.
The changes remain local and are not published.

## Incremental acceptance and restart cache

The polling process now sends events to a dedicated preparation thread.
That thread restores process messages, applies deltas, copies full input for the content cache, and starts asset planning.
It retains immutable runtime objects for unchanged games and identifies changed games before the display loop consumes the event.
The drawing loop processes ordered events within a small per-frame budget.
The viewport updates changed scenes and retains existing card requests for unchanged games.
It also compares locally generated cards that are not part of a server delta.

Sports cards can use a bounded persistent image cache during cold startup.
The cache verifies the exact scene, renderer code and fonts, Pillow and FreeType versions, prepared asset pixels, and stored image checksum.
It checks current input before presenting a cached card. A changed score or asset cannot use an old cached card.
The card worker reloads prepared assets after an asset revision so later asset changes reach the display.
Cache reads and writes run on a separate worker. The display thread performs no cache file I/O.

### Physical Pi measurements

The single-game comparison uses 150 controlled games and 22 visible updates for each version.
Both use the polling process, queue bridge, production application and renderer, and physical matrix driver.
The old side uses the earlier visible-first renderer and retains the 150-pane cutoff removal.
The new side adds producer-side update preparation and changed-game reuse.
Each side displays all 22 targeted updates.
Median main-thread acceptance decreases from 23.9 ms to 8.2 ms.
Median controlled input to physical frame-sink return changes from 274 ms to 265 ms.
The difference in the total interval is small and the trial has only 22 samples per side.
Maximum presentation gaps are 66.6 ms and 60.1 ms. Average frame rates are 33.16 and 33.26 FPS.

The mixed comparison runs 96 seconds plus a drain window per version.
Each run includes 32 updates, five alerts, and five controlled disconnect/reconnect events.
Both retain all latest game data. The old side displays 22 of 22 selected visible changes.
The new side displays 23 of 23, with a different visible-target count because scroll positions differ.
For sampled presented updates, median main-thread acceptance decreases from 37.7 ms to 15.9 ms.
Median input-to-presentation time changes from 601 ms to 763 ms with differing visible targets and overlay timing.
This mixed run does not prove an end-to-end speedup. Maximum presentation gaps are 200 ms and 170 ms.

The restart check uses two consecutive runs with the same controlled game data on the physical Pi.
The cold run displays its first screenful after 5.952 seconds.
The cached restart displays its first screenful after 0.871 seconds, with 15 cache hits and one mismatch.
Full rotation preparation takes about 29.1 seconds in each run. The remaining cards load while the first screen scrolls.
This is one paired restart, not a general startup guarantee.
The cache is limited to 32 stored cards and checks the first 16 eligible scrolling requests at startup.

These experiments start at controlled V2 input and end after the physical frame sink returns.
They do not include ESPN delivery, network delay, or LED scan completion.
The normal controller is active on its original immutable release, and all test units stopped.
The implementation remains local. The standalone live collector uses an isolated server memory display.

The final full Python suite passes 1,432 tests, with ten platform skips.
Cleanup includes shared source caches, stale-result construction, worker transport, immutable-value handling, and owned HTTP client shutdown.
The cleanup agent also shares Mini asset checksum logic without changing display pixels.
The sampled Swift and Mini review and remaining lifecycle boundaries are recorded in `docs/research/structural-cleanup-2026-10-26.md`.

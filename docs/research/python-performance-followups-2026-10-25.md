# Python performance follow-ups

The first change addresses four targets from the live Python profiles.
The measurements use fixed inputs and preserve protocol values and rendered pixels.
The continuation also replaces WebSocket payload copies and completes the native racing integration cleanup.

## Behavior owners and replacements

| Owner | Replacement |
|---|---|
| `ticker_core/protocol/model.py` | Encode frozen JSON directly for canonical hashes. Copy only snapshot metadata that the fingerprint excludes. |
| `application/provider_demand.py` and `application/scheduler.py` | Resolve each ticker's schedule horizon once per scheduler pass. Return demand for the complete provider set. |
| `providers/espn_fastcast.py` | Freeze incoming snapshots once. Share immutable reads and copy only changed ancestors during patches and event refreshes. |
| `providers/http.py` | Replace separate `urlopen` calls with retained, thread-safe connection pools. Keep verified TLS and explicit request timeouts. |
| `ticker_core/drivers/rgbmatrix.py` | Transfer four-row bands through the existing native API. Avoid an RGB copy when the matrix driver only reads the image. |

The memory sink still owns detached pixels.
The matrix driver still completes the frame before its vertical-sync swap.
Provider clients retain their JSON and text ports. Default consumers now use the pooled implementations.
The transport follows bounded redirects and makes no automatic retries after request failures.

## Fixed-input measurements

The backend comparison uses Python 3.13.1 on Windows.
The Pi comparison uses Python 3.13.5 and the physical 384x32 matrix.
The baseline source is commit `7ba43041966203324a27c2bfc5fc1ff961609fef`.
The candidate contains only this task's changes over that source.

| Measurement | Baseline | Candidate |
|---|---:|---:|
| Pi stream delta p50 | 65.571 ms | 39.432 ms |
| Pi stream delta p95 | 118.359 ms | 90.318 ms |
| Demand selection p50, ten tickers | 27.826 ms | 9.452 ms |
| Demand SELECT statements per pass | 309 | 103 |
| Fastcast snapshot read p50 | 4.441 ms | 0.0008 ms |
| Fastcast patch p50 | 4.570 ms | 0.0525 ms |
| Fastcast event refresh p50 | 4.705 ms | 0.1255 ms |
| Local verified HTTPS request p50 | 2.810 ms | 0.392 ms |
| TLS connections for fifty requests | 50 | 1 |
| Paced matrix presentation CPU p50, run A | 7.722 ms | 7.000 ms |
| Paced matrix presentation CPU p50, reversed run B | 7.777 ms | 7.057 ms |

The Pi stream replay contains one snapshot and twenty deltas, totaling 308,765 compact JSON bytes.
Each version replays the same input ten times on CPU 0 while the normal controller runs.
Both versions produce output digest `8fd376d27544ba2af632e1a6a8de0d8a15d549d3c15ffbd8c541cfb3600923db`.
The digest covers cursors, fingerprints, full payloads, content, alerts, and news.

The Fastcast benchmark uses one public NFL scoreboard with fourteen events and 235,283 stored bytes.
Its input digest is `0348b25f0b7a9494b84da3d3e6d9ceae9b730b9d25a75bf5624b7f473eb46f38`.
Each version performs 250 reads, 250 patches, and fifty individual event refreshes.
Both versions produce snapshot digest `891ee00371037357b405c0e87425e6fd39b3922e09c4e01c297b9592406f67de`.

The HTTPS benchmark uses a temporary local TLS server and a verified test certificate.
Both versions receive the same fifty JSON responses.
These timings measure transport overhead. They do not predict internet provider latency.

## Physical matrix evidence

The transfer inputs contain eight scrolling sports windows rendered from twelve captured panes.
They also include black, solid, and dense-pattern frames.
Baseline and candidate renderers produce identical hashes for all eleven RGB frames.
The production render command also produces identical 384x32 NFL PNG pixels.

The final presentation comparison uses CPU 1 and a 30 ms cadence.
It includes RGB preparation, image transfer, brightness, and vertical sync.
Two independent trials reverse the baseline and candidate order.
Both trials reduce main-thread presentation CPU time by about nine percent.
Presentation wall time remains about ten milliseconds because it includes vertical-sync waiting.

Initial transfer experiments also measured cropped bounds, sparse tiles, individual rows, and larger bands.
The sparse plans cost more on ordinary sports frames. The production driver uses four-row full-width bands.
Native-only transfer timings varied with canvas reuse. The final claim uses complete paced presentation CPU time.

The trial starts no second matrix controller while the service runs.
Each trial stops the service and restores it through an exit trap or a Python `finally` block.
The running release remains immutable.
After the last trial, the original release reports 33.333 FPS, zero overruns, and no throttling in its latest window.

## Validation

- All 149 focused checks pass in the working tree.
- The isolated full suite passes 1,459 tests, with ten existing platform skips.
- The isolated environment uses Certifi 2026.10.23, which satisfies the existing repository requirement.
- Tests cover mutation isolation, retained snapshot views, atomic failed patches, array operations, and UID paths.
- HTTP checks cover cross-thread reuse, concurrent reads, redirects, closed connections, failed bodies, status errors, and TLS configuration.
- Matrix checks cover complete pixels, RGB and RGBA inputs, inversion, brightness, and reused front and back canvases.

Initial combined validation failed because a racing change removed `racing_signal` while Six still imported it.
The first isolated validation excluded those unrelated edits and used independent Git metadata for workspace checks.
The continuation below resolves the integration failures in the actual combined working tree.

The application changes remain local. The hardware trials use temporary candidate files and restore the original running release.

## Reproduction and artifacts

Use `tools/benchmarks/device_stream_apply.py` with the same captured messages and repeat count.
Use `tools/benchmarks/profile_followups.py` with the same scoreboard JSON and repeat count.
Use `tools/benchmarks/matrix_transfer.py` with the same 384x32 PNG inputs.
Before a physical matrix trial, stop the controller and install a recovery trap.
Pass `--hardware --present --cpu 1 --interval 0.03` for the paced hardware comparison.

Generated evidence remains under `previews/profiling/2026-10-25/optimizations/`.
The directory contains raw benchmark results, rendered PNGs, input captures, and an isolated validation source.
Input captures and temporary diagnostic data remain outside Git.

## WebSocket publication continuation

`sports_ticker/device_stream.py` now owns immutable encoded projections and complete outbound messages.
`project_stream_payload` prepares JSON sections with the projector in one background task.
The hub compares encoded sections, creates each delta once, and shares that message across subscribers and replay history.
Snapshot recovery uses the retained encoded projection. The event loop performs no nested payload copies.
The ASGI route sends the prepared message text directly.

Sequence checks, reconnect replay, bounded queues, slow-client snapshots, and authorization retain their contracts.
New null-valued sections produce explicit deltas. Object key order does not cause duplicate publications.

The comparison reconstructs complete projections from the same twenty-one captured messages.
Each benchmark publishes 630 updates to three subscribers.
Both versions produce decoded wire digest `d551c0f765c29426e38b0b2afcfa2edf6b98b65dac8de0d2728bf1d57dbd8349`.

| Measurement | Baseline | Candidate |
|---|---:|---:|
| Windows publication event-loop p50 | 2.956 ms | 0.050 ms |
| Server publication event-loop p50 | 4.646 ms | 0.072 ms |
| Server preparation and publication p50 | 4.850 ms | 2.727 ms |

The independent server sampling runs each publish 700 updates at twenty updates per second.
Each run lasts about thirty-five seconds and uses py-spy at 99 Hz with nonblocking reads.
The baseline records 406 active samples. The candidate records 211.
The baseline includes 304 replay samples in `deepcopy`. The candidate includes none.
The candidate's main thread records 29 active samples. Its encoding worker records 182.
JSON encoding on the worker now dominates this controlled publication replay.
These profiles exclude live provider and database latency.

## Combined working tree validation

Six now renders native racing records without the deleted class-card projection or scoped signal helpers.
Shared basic flag colors remain in `sports_display.py`. Missing flag values remain unknown.
The native layouts retain pinned driver caches and use the existing series fields.
The scroll visual key remains stable when its data and assets remain unchanged.

The rendering proof passes native records through saved ticker settings, V2 projection, WebSocket encoding, and client decoding.
It renders four real 384x32 frames for F1 and IMSA in scroll and pinned presentations.
The frames pass visual inspection.

The workspace inventory now excludes explicit working tree deletions while retaining the committed revision tree.
The public gallery rebuild renders 4,072 Mini firmware frames and stores 135 layout examples locally.
Its source provenance and approved page assets pass verification.

The normal `python -m pytest -q` command passes 1,358 tests with ten existing platform skips in the actual working tree.
The local Certifi package is now 2026.10.23, matching the repository's existing requirement.
The smaller count reflects the combined tree's removed racing feature tests and its added current checks.
No assertions or platform conditions were weakened.

Continuation evidence remains under `previews/profiling/2026-10-25/stream-followup/`.
It includes Windows and server benchmark results, both sampled profiles, racing PNGs, and rebuilt gallery frames.
The continuation changes remain local. The replay profiling does not restart the deployed backend or the Pi controller.

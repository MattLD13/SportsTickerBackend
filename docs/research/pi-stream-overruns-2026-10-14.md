# Pi stream processing and frame overruns

## Ownership and cause

The Pi protocol boundary owns validation, immutable display data, and payload fingerprints.
`DeviceStreamState` owns stream identity and sequence acceptance.
The runtime owns overlays, commands, and display scheduling.

The former stream path copied the full retained JSON tree for each delta.
The parser then froze nested sections repeatedly and rebuilt full JSON values several times for hashing.
The replacement freezes incoming data once and shares unchanged immutable sections.
Private parsing methods inspect validated sections without copying them again.
Canonical JSON serialization and payload fingerprints stay identical.
The stream retains its validated response instead of a second mutable JSON tree.
Sequence checks, snapshot recovery, and removal semantics retain their existing rules.

## Captured input and offline Pi evidence

The capture contains 21 live backend messages: one snapshot and 20 contiguous deltas.
Compact JSON totals 308,765 bytes.
The benchmark replays the capture twice on the physical Pi while its normal controller runs.
Both runs use CPU 0. The display cadence remains 30 milliseconds.
The baseline uses release `d13bf4d6`.
The candidate changes only protocol parsing and stream state.

| Measurement | Baseline | Candidate |
|---|---:|---:|
| Snapshot p50 | 63.531 ms | 18.447 ms |
| Delta p50 | 457.757 ms | 64.337 ms |
| Delta p95 | 524.803 ms | 165.648 ms |
| Delta maximum | 715.659 ms | 169.082 ms |

Median delta processing falls 85.9 percent.
The output digest covers every accepted cursor, full wire payload, payload fingerprint, rendered item data, and overlay data.
Both runs produce `38bb9efaf594cc91436c0b889f611845192225394e69a3a9d2c62a6b7862adab`.
These measurements describe parsing work. They do not establish a frame overrun reduction.

## Validation

- All 566 tests pass.
- The 240 critical tests pass.
- New boundary checks cover shared immutable sections, caller mutation, rejected replacement recovery, optional field removal, and canonical fingerprints.
- Process transfer, reconnect, overlays, commands, and application lifecycle checks pass.
- The pane composition benchmark preserves identical pixels across all compared strategies.
- All 12 captured live sports panes preserve identical 384x32 RGB hashes across the old and new parsers.

Run an offline captured stream benchmark:

```powershell
python tools/benchmarks/device_stream_apply.py --messages capture.json --output stream-report.json
```

Capture files contain live display data. Keep them outside committed source.
Generated reports and frame PNGs remain in `.tmp/overrun-investigation/`.

## Live hardware validation

The baseline smoke check passes on the deployed Pi and physical 384x32 matrix.
Its selected window reports 327 frames, 32.677 FPS, 26.261 ms frame p95, and 10 overruns.
The server expires the test event. The Pi records the cleared payload.
The first candidate smoke run includes service startup and pane warmup. It fails the steady frame budget.
The repeat after warmup passes delivery, sequence advancement, frame budget, expiry, and clear checks.

Six complete telemetry windows include overlay arrival and the following 50 seconds.
Both versions use the live backend and the physical panel at a 30 ms cadence.

| Live measurement | Baseline | Candidate |
|---|---:|---:|
| Duration | 60.075 s | 60.099 s |
| Frames | 1,987 | 1,986 |
| FPS | 33.075 | 33.045 |
| Overruns | 21 | 16 |
| Overrun rate | 1.057% | 0.806% |
| Largest window frame p95 | 26.261 ms | 23.710 ms |
| Longest frame | 155.489 ms | 169.368 ms |
| Stream messages | 89 | 91 |
| Mean stream application | 160.654 ms | 26.272 ms |

The observed overrun rate falls about 24 percent. These short live runs receive different provider updates.
The candidate still has a long frame during overlay arrival. Parsing improvements do not remove every scheduling stall.
The logger records update acceptance, frame preparation, and composition timing for further diagnosis.
Each window retains at most eight worst overrun samples. The writer formats these samples outside the display loop.

The physical 15-game check passes with 15 ready panes and no failed panes.
It covers 1.2 full scroll cycles, one score change, and 15 simultaneous score changes.
The three phases report zero, zero, and one frame overruns. All phases retain at least 33.2 FPS.
One changed pane becomes ready in 142 ms. All 15 changed panes become ready in 1.434 seconds.
The controller resumes its normal live feed after the check.

## Pane cache comparisons

Stage samples identify another display-loop cost after the parser change.
One live window spends 152.589 ms accepting an update. Another frame spends 124.201 ms preparing panes.
These samples spend less than 14 ms composing pixels and about 12 to 23 ms presenting them.
Pane cache comparisons repeatedly convert immutable nested game data into mutable dictionaries.
Completion checks and generation commits repeat this conversion across the desired pane set.

`CardViewport` now retains one immutable scene mapping per request and surface.
Cache comparisons use that mapping directly. Worker dispatch converts a scene once for its process transfer.
The runtime remains the owner of immutable content. Rendering and pixel output retain their existing contracts.
The former comparison-time `_content_mapping` path is removed.
The cache regression check proves unchanged updates perform no additional scene serialization.
Worker recovery, stale completion, late assets, changed panes, and strip wrap checks continue to pass.

The same nine captured panes undergo 30 unchanged cache updates on the physical Pi.
Median cache update time falls from 124.567 ms to 0.715 ms. The p95 falls from 125.607 ms to 0.858 ms.
Both versions produce RGB digest `33acc6a9a93dcc38d7818e401c78a12d52f463ddfd0da687868aaa5439bf72f6`.

## Equal traffic through the physical display pipeline

`tools/benchmarks/pi_stream_replay.py` replays the captured messages at two messages per second.
Each release warms up for 20 seconds and then measures 60 seconds on the same Pi and matrix.
The production poller, decoder, application, runtime, pane worker, and matrix driver run normally.
The injected transport replaces network delivery. Platform actions remain disabled, and temporary content stays outside normal runtime storage.
The source digest matches across both runs: `f5bd23b0bd7d4b58f1871df4d1deb6ad06b78dbbbe7eb7d02c44eff8a758782e`.

| Controlled replay measurement | Baseline `d13bf4d6` | Final code `e34eccc6` |
|---|---:|---:|
| Duration | 59.979 s | 59.966 s |
| Stream messages | 120 | 120 |
| Frames | 1,858 | 1,983 |
| FPS | 30.978 | 33.069 |
| Overruns | 62 | 32 |
| Overrun rate | 3.337% | 1.614% |
| Largest window frame p95 | 28.542 ms | 21.285 ms |
| Longest frame | 180.087 ms | 80.385 ms |

The measured overrun rate falls 51.6 percent. The longest frame falls 55.4 percent.
The configured 30 ms frame interval remains unchanged.
This short replay establishes improvement under identical captured traffic. It excludes network, proxy, and live provider timing.
The separate final live smoke passes delivery, expiry, and clearing on the real controller.
The final live feed receives fewer provider changes than the baseline. Its overrun count is not an equal-load comparison.

The physical 15-game run above uses the first parser candidate, before the pane comparison change.
The final pane change passes the deterministic 15-pane test and the nine-pane physical replay.
Further display takeover tests stop when the owner resumes manual app control.
The normal controller resumes after each replay through the shell EXIT trap.

The smoke reader now handles null sequence values in windows that receive no stream message.
The null value denotes no observation during that window. The reader retains the latest sequence from other observed windows.

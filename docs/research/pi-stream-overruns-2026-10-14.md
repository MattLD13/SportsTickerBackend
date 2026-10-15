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

- All 564 tests pass.
- The 239 critical tests pass.
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

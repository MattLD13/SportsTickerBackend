# Pi viewport baseline

The benchmark measures existing code at commit `1d38e4f6879141098011fbe2aaf93c630dcc6045`.
`CardViewport` owns card readiness and surfaces.
`FrameBuilder` owns panel composition.
`MemoryFrameSink` presents the desktop frames.
This change replaces no production code.

Run from the repository root:

```powershell
python tools/benchmarks/pi_viewport_baseline.py
```

The default run uses 6,000 measured frames, 30 warmup frames, and 300 paced frames per case.
Each case starts a fresh interpreter and uses the existing spawned card process.
Readiness polling installs one completed card at each configured frame boundary.
The fixed render time is `2026-08-13T00:00:00+00:00`.
The script records resolved font names, sizes, and SHA-256 hashes.

The source is `tests/rewrite/debug/v2_render_snapshot.json`.
It contains two sports records and no asset URLs.
The 1, 10, and 60 card cases repeat those records with unique card identities.
These capacity cases do not represent 60 distinct live games.
The script uses an empty prepared asset cache and performs no prefetch.
A production workload with diverse cards and prepared external assets needs another captured V2 snapshot and its assets.

The score update increases the first source card's away score by one.
The benchmark requires changed presented RGB bytes after that update.
It also measures complete asset invalidation and checks all desired cards commit without failures.
This script calls the frame builder and sink directly.
It excludes application events, backend polling, network time, and matrix hardware.

The snapshot configures a 30 ms scroll interval, or 33.33 presentation decisions per second.
`RuntimeConfig` separately defaults general frames to 1/30 second.
The real scrolling runtime selects the snapshot interval.
The benchmark measures approximately 33.33 desktop presentations per second with this interval.
This measurement does not establish Pi matrix presentation rate or 60 FPS.

`pi_viewport_windows_baseline.json` records the completed Windows host run.
The table rounds measured values.

| Cards | Queue to ready ms | Startup to first presentation ms | Build p50/p95 ms | Score update to presentation ms | Full invalidation ms | Paced CPU percent | Parent and worker memory MiB |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 520.07 | 944.47 | 0.0799 / 0.0817 | 30.46 | 30.83 | 0.69 | 101.91 |
| 10 | 789.03 | 1217.67 | 0.0816 / 0.0869 | 30.69 | 300.23 | 1.22 | 102.31 |
| 60 | 2289.76 | 2719.22 | 0.0834 / 0.0892 | 30.60 | 1800.47 | 0.69 | 103.46 |

CPU values sum parent and card worker CPU time, relative to one logical CPU.
Windows CPU accounting is coarse, so brief samples can report zero or exceed 100 percent.
The memory measurements sum process working sets and can count shared pages twice.
Each process also reports its peak working set.
The resource tracker is excluded.
The measured host uses Windows 11, Python 3.13, Ubuntu Mono, Arial Bold, and Pillow's embedded Aileron font.
Pi measurements need the deployed Pi fonts and hardware.

Each case saves actual 384x32 initial and updated PNGs under `previews/benchmarks/pi-baseline/`.
Raw RGB and PNG hashes remain in the JSON report.
The report stores preview paths relative to the repository and font filenames without host directory paths.
Process metrics exclude transient process IDs.
A separate short run reproduced the 1-card initial and updated RGB hashes and font manifest.
The 60-card frame passed visual inspection.
PNG artifacts remain ignored.

Validation commands:

```powershell
python tools/benchmarks/pi_viewport_baseline.py
python tools/benchmarks/pi_viewport_baseline.py --case 1 --frames 10 --paced-frames 2 --output previews/benchmarks/pi-baseline/repeat-check
python -m py_compile tools/benchmarks/pi_viewport_baseline.py
git diff --check
```

## Pane composition comparison

Run the composition comparison:

```powershell
python tools/benchmarks/pi_pane_composition.py
```

The benchmark compares the prior independent-pane loop, the current cached tiled strip, and a bounded 384x32 ribbon.
Each method must produce identical 384x32 RGB bytes across wrap points before timing is accepted.
The report measures 3,000 frames per strategy after warmup for 1, 10, and 60 panes.

The current Windows run records these 60-pane results:

| Composition | Frame p50 | Frame p95 | Retained composition memory |
| --- | ---: | ---: | ---: |
| Prior pane loop | 68.0 microseconds | 72.5 microseconds | Pane surfaces only |
| Cached tiled strip | 3.5 microseconds | 4.5 microseconds | 1.04 MB |
| Bounded ribbon | 27.6 microseconds | 30.6 microseconds | 36.9 KB |

The tiled strip cuts composition p50 by 94.9 percent. Its 1.44 millisecond rebuild runs only after a pane generation commits.
The 60-pane case takes about 2.28 seconds to prepare all pane images and 32 milliseconds to prepare one changed pane.
The scroll fixture uses two unique sports panes repeated with unique IDs for capacity cases.
These numbers exclude pane rendering, provider work, backend time, and Pi matrix DMA.
The old composition used about 0.23 percent of a 30 millisecond frame interval. The new composition uses about 0.01 percent.
This gain reduces CPU work and leaves more headroom. It does not change the configured frame cadence.
Run the benchmark on a Pi before claiming production frame-speed gains.

## Stream application cost

`device_stream_apply.py` replays captured Device Stream V1 messages without network or matrix writes.
It measures JSON decoding, envelope validation, and stream state application.
Its digest covers accepted cursors, raw payloads, fingerprints, rendered item data, and overlays.
Use identical capture files and repeat counts when comparing implementations.
Keep live captures outside committed source.
Read [the Pi stream report](../../docs/research/pi-stream-overruns-2026-10-14.md) for physical Pi measurements.

## Captured stream replay on the physical matrix

`pi_stream_replay.py` uses the real Pi poller, protocol, application, runtime, pane workers, and RGB matrix driver.
Its transport supplies the same captured messages every 0.5 seconds and repeats the capture with a new stream identity.
It removes update and reboot commands from replayed metadata. It keeps temporary display state outside normal runtime storage.
It uses the normal durable asset cache.

Run this utility on the physical Pi only.
Before running the replay, stop `ticker-controller.service`.
Use an EXIT trap to restore the controller after success or failure.

```sh
sudo env PYTHONDONTWRITEBYTECODE=1 python3 tools/benchmarks/pi_stream_replay.py \
  --repository /opt/sports-ticker/current --messages capture.json --output report.json
```

The default run warms up for 20 seconds and measures 60 seconds.
Compare the same capture, message interval, warmup, and measurement duration across releases.
The report includes the source digest, message count, frame timings, and overrun rate.
This replay measures the physical display pipeline. It excludes Wi-Fi, proxy behavior, and live provider timing.

# Ticker motion experiment record

This record documents a rejected motion experiment. It preserves evidence, safety rules, and next-step gates.

See the [evidence index](EVIDENCE.md) for compact inputs, outputs, and reproduction paths.

## Objective

The experiment investigated smoother 384x32 ticker scrolling on a Pi-class controller. The target preserved the existing UI, card order, logos, modes, and controls while reducing CPU work and visible motion defects.

The original reports included blank or frozen no-games screens, Pi scroll stutter, low-speed jumps, high-speed blur, and low-speed flicker. Some cards also showed test blocks instead of logos. Logo loading and motion quality share the viewport path, but this experiment does not prove the logo cache cause.

## Root tradeoff

The renderer must choose between fractional movement and crisp source pixels.

- Full-frame RGB blending produces fractional motion, but it creates neighboring-image ghosts, blur, and high frame work.
- Whole-column frames preserve source pixels, but slow levels repeat frames or jump across columns.
- Spatial coverage selects pixels from adjacent source columns, but temporal dither can create brightness modulation, pattern texture, and CPU cost.
- A fixed 30 ms scheduler keeps cadence stable, but the renderer must represent the requested distance without changing the display contract.

The experiment found no candidate that passed both the logical contract and the hardware proof.

## Exact speed contract

The iOS scale owns these persisted intervals. The runtime owns a 30 ms scroll cadence. The expected distance per scroll frame is the cadence divided by the interval.

| Level | Interval seconds per pixel | Expected pixels per 30 ms frame |
| ---: | ---: | ---: |
| 1 | 0.100000 | 0.3 |
| 2 | 0.075000 | 0.4 |
| 3 | 0.060000 | 0.5 |
| 4 | 0.050000 | 0.6 |
| 5 | 0.042857 | 0.7 |
| 6 | 0.037500 | 0.8 |
| 7 | 0.033333 | 0.9 |
| 8 | 0.030000 | 1.0 |
| 9 | 0.027273 | 1.1 |
| 10 | 0.025000 | 1.2 |

Level 8 remains the reference setting because it advances exactly one source column per 30 ms frame.

## Candidate contracts

Candidates 1 through 4 are reconstructed runnable equivalents in the research tool. Their exact original uncommitted runner was overwritten. Candidate 1 is associated with release `42d700b`. Candidate 2 has an exact rejected diff in [`source/rejected-spatial-dither.patch`](source/rejected-spatial-dither.patch).

| Candidate | Reconstructed or recorded contract | Reported result |
| ---: | --- | --- |
| 1 | Continuous adjacent-column `Image.blend` at a stable cadence. | User feedback: nausea. This is the implementation associated with release `42d700b`. |
| 2 | Spatial binary rank dither that selects source pixels from adjacent columns without RGB mixing. | User feedback: pixel spray. The exact rejected diff is [`source/rejected-spatial-dither.patch`](source/rejected-spatial-dither.patch). |
| 3 | Fixed 30 ms fractional logical motion floored to crisp integer columns. | User feedback: jittery. Flooring creates irregular holds as the logical phase crosses columns. |
| 4 | Blend below 1 pixel per frame and floor at or above 1 pixel per frame. | User feedback: ghosting. Neighboring source columns remain mixed below the threshold. |
| 5 | Recorded as `uniform-native-pixel`. Advance one source column at each requested interval. Use no dwell, blend, or dither. | Hardware capture showed crisp source behavior, but timing proof failed under the unsynchronized capture. Level 10 contained a long apparent hold. |
| 6 | Recorded as `aligned-dwell`. Advance one source column every 30 ms, then dwell at each real card boundary to realize the requested card cycle. Use no blend or dither. | Hardware capture showed reduced spray, but low levels froze or moved far below contract speed. |

The candidate 1 through 4 labels preserve the reported feedback and runnable-equivalent contracts only. They do not claim that the overwritten runner remains reproducible.

## Trial order and schedule

The recorded runner used one static prelude, a visual sync marker, and eight motion segments.

1. Hold one static reference frame for 5 seconds.
2. Run candidate 5 at levels 1, 5, 8, and 10.
3. Run candidate 6 at levels 1, 5, 8, and 10.
4. Give every segment 2 seconds of warmup and 8 seconds of measurement.

The planned schedule lasted 85 seconds. The panel size was 384x32. The generated motion manifest recorded 2,357 motion frames, with 1 static baseline frame presented by the runner. The camera captured 6,294 frames over 104.9 seconds at 60 FPS, including setup and trailing footage. The manifest recorded real card spans of 83, 81, and 81 pixels for that run.

## Hardware results

The BRIO capture used a fixed 720p view, a four-corner panel calibration, and a 384x32 rectified analysis surface. The calibration reprojection error was 0 pixels. The static prelude used 300 camera frames at 60 FPS. Baseline exposure had median 31, p01 3, p99 228, zero clipped fraction, and p99 coefficient of variation 0.01453.

The old webcam setup supplied 30 FPS calibration and smoke clips. Those clips supported geometry checks only. They did not support reliable temporal claims against a 33.33 FPS display.

Recorded moving comparisons reported these approximate average speeds:

| Candidate | Level 1 | Level 5 | Level 8 | Level 10 |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 33.15 px/s | 33.68 px/s | 33.42 px/s | 33.01 px/s |
| 6 | 0.06 px/s | 12.29 px/s | 25.08 px/s | 33.73 px/s |

The requested speeds were 10, 23.33, 33.33, and 40 px/s for those levels. Candidate 6 level 1 showed a 1.57 second longest apparent freeze. Candidate 5 level 10 showed a 1.12 second longest apparent freeze and a ghost p95 of 6.81 in the evaluator report.

## Capture validity limits

The runner declared `SYNC_MOTION_TRIAL`, but the camera evaluator detected zero marker transitions. The moving baseline therefore cannot establish a valid capture-to-trial offset. Every moving segment was marked invalid for the missing marker.

The camera recorded at 60 FPS while the display cadence was 33.33 FPS. Spatial confidence was high, but temporal confidence was low. Flicker, jitter, judder, and nausea metrics remain low confidence below 120 FPS. The static baseline and motion windows also lack a verified synchronization point, so their comparison is not a publication proof.

The camera reports also contain exposure variation, panel drift, phase aliasing, and camera sampling artifacts. A future run must use a detected marker and a 120 FPS or faster capture before temporal conclusions can pass.

## No-winner conclusion

Candidate 5 did not prove the exact slow-speed contract. Candidate 6 preserved crisp source pixels but introduced unacceptable low-speed holds. Candidates 1 through 4 remain reconstructed research labels rather than repeatable results.

No motion candidate won. No candidate was deployed to the production release. The production state remains unchanged by this document.

## Ownership, former path, and proof

The ownership boundaries are:

- `TickerRuntime` owns cadence, logical distance, and strip-offset continuity.
- `CardViewport` owns card composition, source-column selection, and panel pixels.
- `FrameBuilder` owns visual-key identity and frame requests.
- `ScrollSpeedScale` owns the iOS persistence table.
- The trial runner and camera evaluator own research measurements only. They do not own production policy or service restoration.

The former path under test used a full-frame adjacent-image blend for fractional viewport positions. The experimental replacement attempted source-column spatial coverage and added `scroll_step` to the frame contract. The replacement remains unaccepted because low-speed brightness and temporal gates fail.

Proof artifacts include the focused motion test, the trial manifest, the camera evaluator output, real 384x32 diagnostics, and the [`rejected-spatial-dither-quality-test.py`](source/rejected-spatial-dither-quality-test.py) and [`rejected-spatial-dither.patch`](source/rejected-spatial-dither.patch) records. The focused motion test currently reports 80 passing checks and 8 failures. A real render and synchronized hardware run remain required for any accepted replacement.

## Next experimental steps

1. Preserve the exact iOS interval table and the 30 ms logical cadence.
2. Design a renderer that keeps slow frames progressive without full-frame RGB ghosts or periodic dither texture.
3. Require source-palette membership, monotonic distance, stable local luminance, bounded temporal second difference, and no repeated spatial period.
4. Exercise real text and logo surfaces, not only synthetic edges.
5. Benchmark viewport CPU work on a Pi-class environment without an active SSH measurement session.
6. Record a same-camera static baseline, begin capture before the trial, detect a sync marker, and use 120 FPS or faster video.
7. Keep the root hardware wrapper and delayed recovery unit outside production releases. Use them only for an approved experiment, then remove them after a read-only health check.
8. Publish only after focused tests, the full Python suite, a real 384x32 render, iOS contract tests, and synchronized hardware evidence pass.

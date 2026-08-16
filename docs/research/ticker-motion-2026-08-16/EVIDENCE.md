# Ticker Motion Evidence

This checkpoint records the offline motion trial captured on 2026-08-16.
The checkpoint contains compact inputs, outputs, proofs, and visual evidence.
It excludes every real camera video from the repository.

See the [experiment README](README.md) for candidate contracts, ownership, and the no-winner conclusion.

## Provenance

The evaluator source is `tools/ticker_camera_evaluator.py`.
The trial source is `tools/ticker_motion_trial.py`.
The focused runtime test is `source/rejected-spatial-dither-quality-test.py`.

The real trial used `evidence/ticker-motion-trial-manifest.json`.
The manifest declares candidates 5 and 6 at speed levels 1, 5, 8, and 10.
The evaluator used the fixed BRIO calibration in `evidence/brio-framing-calibration.json`.
The calibration maps a 1280x720 BRIO view to the 384x32 ticker panel.

The capture used 1280x720 video at 60 frames per second.
The evaluator used OpenCV presentation timestamps when available.
The evaluator kept a three-frame streaming buffer.
The evaluator masked the manifest badge rectangle `[0, 0, 39, 10]`.
The evaluator discarded every two-second warmup window.

## Reproduction

If the raw trial video is available outside Git, run:

```text
python tools/ticker_camera_evaluator.py \
  <external-raw-video>/brio-motion-720p60.mkv \
  --manifest docs/research/ticker-motion-2026-08-16/evidence/ticker-motion-trial-manifest.json \
  --calibration docs/research/ticker-motion-2026-08-16/evidence/brio-framing-calibration.json \
  --output docs/research/ticker-motion-2026-08-16/evidence/real-motion-evaluation.json \
  --diagnostics docs/research/ticker-motion-2026-08-16/evidence/real-motion-diagnostics
```

If synthetic validation is required, run the evaluator with
`docs/research/ticker-motion-2026-08-16/evidence/synthetic-base.avi` and
`docs/research/ticker-motion-2026-08-16/evidence/synthetic-manifest.json`.
The synthetic calibration is
`docs/research/ticker-motion-2026-08-16/evidence/synthetic-calibration.json`.

## Authoritative evidence

The JSON result is authoritative for the evaluator output and confidence labels.
The text result is an expanded human-readable copy of that JSON result.
The trial manifest is authoritative for candidate names, levels, windows, warmups, badge masking, and sync declaration.
The BRIO calibration is authoritative for the rectification geometry.
The independent metrics file is authoritative only for its separately computed frame-difference measurements.
The badge proof is authoritative for the synthetic badge-mask invariance check.
The synthetic fixture outputs are authoritative for parser and mask regression evidence.

Included authoritative files:

- `evidence/real-motion-evaluation.json`
- `evidence/real-motion-evaluation.txt`
- `evidence/ticker-motion-trial-manifest.json`
- `evidence/brio-framing-calibration.json`
- `evidence/independent-review-metrics.json`
- `evidence/badge-mask-proof.json`
- `evidence/synthetic-calibration.json`
- `evidence/synthetic-manifest.json`
- `evidence/synthetic-base.avi`
- `evidence/synthetic-badge.avi`
- `evidence/synthetic-base-evaluation.json`
- `evidence/synthetic-evaluation.json`
- `evidence/synthetic-base-output.txt`
- `evidence/synthetic-output.txt`
- `evidence/validation-output.txt`
- `evidence/brio-framing-representative.png`

## Diagnostic evidence

The eight candidate contact sheets provide visual review for candidates 5 and 6.
The eight sparse real-motion frames provide decode and framing checks.
These images support review and do not replace the JSON metrics or confidence labels.

Contact sheets:

- `evidence/candidate5-S1-contact.png`
- `evidence/candidate5-S5-contact.png`
- `evidence/candidate5-S8-contact.png`
- `evidence/candidate5-S10-contact.png`
- `evidence/candidate6-S1-contact.png`
- `evidence/candidate6-S5-contact.png`
- `evidence/candidate6-S8-contact.png`
- `evidence/candidate6-S10-contact.png`

Sparse diagnostics:

- `evidence/real-motion-frame-000060.png`
- `evidence/real-motion-frame-000120.png`
- `evidence/real-motion-frame-000180.png`
- `evidence/real-motion-frame-000240.png`
- `evidence/real-motion-frame-000300.png`
- `evidence/real-motion-frame-000360.png`
- `evidence/real-motion-frame-000420.png`
- `evidence/real-motion-frame-000480.png`

## Limits

The declared `SYNC_MOTION_TRIAL` marker was not observed confidently in the 60 fps capture.
The report records `invalid_marker_not_observed` and a fallback offset near zero.
The eight measurement segments therefore carry sync invalidity.

The 60 fps capture aliases the ticker's approximately 33.33 fps update cadence.
Judder, jitter, PWM flicker, and nausea metrics remain low confidence below 120 fps.
The report does not select a motion winner from those metrics.

The same-video static baseline changed during capture.
Edge and ghost values relative to that baseline remain diagnostic.
They do not provide blur or ghost pass/fail decisions.

The capture exposes spatial clipping, exposure stability, panel drift, freeze-like holds,
relative spray, edge energy, and bounded frame-difference diagnostics.
It does not expose reliable display-time behavior for the low-confidence temporal claims.

## Excluded real videos

The repository excludes these files because GitHub blocks normal Git files above 100 MiB,
and the complete capture set would add approximately 1.12 GB to the repository.
The SHA-256 values preserve identity for external archival copies.

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `temp/camera-calibration/brio/brio-720p60.mkv` | 28,741,449 | `e0312d29e8c57793bb2b001b54ea5beea95532e4b953e40516fdb5c4ea4210fc` |
| `temp/camera-calibration/brio/framing/brio-framing-720p60.mkv` | 14,512,940 | `d3137f51882004393c02ee34fb8ecbcd8f3634297d19d62cff8201f633ed4aaa` |
| `temp/camera-calibration/brio/manual/brio-manual-720p60.mkv` | 16,238,309 | `11a0aced7ce002b59e1e1067ef415b9661e88bfd96a0d2d36a00bfcda0555d6c` |
| `temp/camera-calibration/ticker-30fps-mjpeg.avi` | 12,024,752 | `6e4bc78662bf0a0e85fa42764bad3311ecddaa73363d58f421b12b0404578da8` |
| `temp/camera-calibration/ticker-30fps-raw.avi` | 153,473,998 | `9115d26939e6c62d96695940918047529ee64796d0b784fa8fc6628e06c9831b` |
| `temp/camera-calibration/ticker-30fps.mp4` | 12,201,208 | `1634ff75b4e22f4c342472033c5f220a369d5c707d21335b4599898bccc6df02` |
| `temp/camera-calibration/ticker-exposure-minus7.avi` | 4,913,840 | `a94a3484d887133056686c720cd9282e7eca1ea64742b8d2fb0e8a93a39581fa` |
| `temp/camera-trials/brio-20260816-105s-720p60.mkv` | 517,382,930 | `13bbdbfefafad240596bf0897079126ad97564a22b270df77c1e965200d5ea9f` |
| `temp/camera-trials/brio-unsynced-partial.mkv` | 432,201,222 | `4c5c1e1e5bc2ba6873f674a1e67aa54ee63ec91d7dcf4a1f91ce435307753aeb` |

The compact synthetic videos remain in this checkpoint because each file stays below 250 KB.
They do not contain real camera footage.

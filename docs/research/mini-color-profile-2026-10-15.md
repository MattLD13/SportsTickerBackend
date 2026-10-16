# Mini dark-logo color profile

Date: 2026-10-15

## Input and observations

The user reports green areas inside the Lightning logo on the physical Mini.
The production sprite and captured 16x16 logo region contain no green-dominant pixels.
The source includes a small green component within its navy blue colors.
The physical panel uses USB power. The user reports that reducing brightness does not remove the tint.
The user confirms correct red, green, and blue test patches.
The user also confirms that flat navy and dark-blue patches look blue.

The original Lightning logo shows the tint in a controlled comparison.
A second copy with its green channel removed does not show the tint.
This diagnostic identifies sensitivity to the low-intensity color mix. It does not justify changing team artwork.
The diagnostic restores normal live rendering after the comparison.

## Working profile

The former Mini profile requests at least 240 Hz at an 8 MHz matrix clock.
The driver changes low-bit scheduling to satisfy that refresh target.
The test profile reports 200 Hz and uses the original logo pixels.
The user confirms that the unwanted green disappears with this profile.

The production minimum is now 200 Hz at the existing 8 MHz clock.
`metadata.display_metrics.panel_refresh_hz` exposes the driver-calculated refresh rate.
This rate describes panel scanning. It is separate from application frame submissions and pane duration.
The main Pi configuration caps panel refresh at 100 Hz.

The firmware dependencies now match the working physical build:

| Dependency | Version |
|---|---|
| Espressif32 platform | 6.5.0 |
| ArduinoJson | 7.4.3 |
| Adafruit GFX | 1.12.6 |
| Matrix DMA driver | `a8b172aee5710c7ab5e8c049cd001703b73f1eb9` |
| NimBLE-Arduino | 2.5.1 |

The release target is `mini-1.3.7`.
The temporary `mini-1.3.7-colorcheck` image runs successfully on the physical Mini.
A real 384x32 main ticker reference also renders successfully.

## Published result

Deployment [38835861645](https://github.com/MattLD13/SportsTickerBackend/actions/runs/38835861645) passes runtime checks and the firmware build.
The physical Mini downloads and verifies 1,272,320 bytes, restarts into `mini-1.3.7`, and acknowledges the release.
The backend clears the update command and retains app pairing.
The final live capture reports 200 Hz on the published firmware.
It saves three complete frames without protocol errors and observes the normal 19-page sports rotation.
The full suite passes 597 tests. The critical suite passes 267 tests.
The local firmware build, Ruff, scoped Mypy, and the real 384x32 reference render pass.
All temporary display patterns and serial collectors have finished.

## Change notes

Owner: The Mini matrix adapter owns scan timing. PlatformIO owns the tested build dependencies.
Former path: Replace the 240 Hz minimum and floating firmware dependencies with the verified profile and exact versions.
Real input: Original Lightning sprite pixels, primary-color checks, and physical user observations.
Real output: Correct colors at a driver-reported 200 Hz without a team-specific image rule.

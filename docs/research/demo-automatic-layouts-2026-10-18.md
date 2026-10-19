# Automatic public ticker layouts

## Owners

`docs/contracts/demo-layouts.json` owns reviewed public example inputs.
`docs/contracts/demo-assets/` contains their approved public logo source images.
The production Mini presenters and renderers own every displayed pixel.
`tools/rendering/build_demo_layouts.py` prepares assets, compiles the native renderer, and packages its output.
The browser reads the generated frame atlases and draws their pixels without a second layout implementation.
Ticker Six continues through its production frame and pane renderers.

## Former path

The old Mini gallery retained firmware 1.3.10 screenshots after later renderer deployments.
The new build removes manual capture input and the frozen gallery checksum.
Release verification compares the generated gallery with the current renderer source hashes and reviewed inputs.
Flight, airport, and message drawing now share portable functions between firmware and the native preview.
Their 15 reference frames, including clock and pairing, remain pixel-identical to the former captures.
The native RGB conversion matches the panel driver's RGB565 expansion.

## Automatic deployment

Every deployment builds the gallery before public route checks and the complete test suite.
The job compiles C++ against the ArduinoJson version pinned in `esp32_hub75/platformio.ini`.
It uses the bundled public image sources and the production image preparation functions.
The verification job uploads one generated gallery artifact for its exact commit.
The backend deployment installs that verified artifact before copying files to the server.
Mini renderer changes also trigger website deployment, keeping the public examples current.
Source or provenance mismatches stop release verification.

If you change a Mini renderer, update its firmware version and push the change to `main`.
The deployment rebuilds its examples automatically.
If you add an example with another team, include its approved public source image.

For a local build, run:

```text
python tools/rendering/build_demo_layouts.py
python tools/rendering/verify_public_demo.py
```

If the PC lacks a C++ compiler, use the physical Pi:

```text
python tools/rendering/build_demo_layouts.py --host <pi-host> --ssh-key <key-path>
```

## Public views

The catalog contains 117 cases and 1,839 native Mini frames.
Weather examples animate at ten frames per second and include both statistic pages.
Music examples display the shared album cover, album colors, scrolling names, and remaining time.
The browser supports animation pause, brightness, pixel display, search, and zoom.
Ticker Six stock examples use real scrolling panes instead of stretching one card across the display.
The main website keeps its existing style and routes. The explorer remains at `/demo/layouts`.
The build and public explorer never read ticker records, Spotify accounts, or private device data.

## Validation

The native build runs on the physical Pi during local development and Linux during deployment.
Public route checks verify every board size, atlas dimensions, artwork stability, weather fields, and owner isolation.
The provenance check rejects a simulated renderer change without rebuilt frames.
Deployment scope checks verify that Mini drawing changes trigger website updates.
The firmware build succeeds with the shared drawing functions.
The full Python suite passes 760 tests. The critical suite passes 414 tests.

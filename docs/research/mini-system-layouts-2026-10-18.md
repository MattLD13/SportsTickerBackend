# Mini utility screens and corner overlays

## Ownership

The runtime selects an explicit utility kind from device, network, and updater state.
The shared Mini presenter formats that state.
The shared renderer draws full panels or corner overlays.
The matrix driver owns the retained content pixels in PSRAM.

## Replaced paths

- Remove the ten-character message renderer and its separate classic font.
- Replace hardware-only download drawing with shared, previewable renderers.
- Remove registration label parsing from the connection layer.
- Select error and connection kinds at each runtime source.
- Retain clean content before drawing an overlay.
- Restore clean content before drawing update status during firmware transfer.
- Use the same composition for sports, music, weather, stocks, flights, airports, and clock content.

## Presentation

Startup, pairing, asset loading, and time synchronization use full panels.
Connection loss and data errors use an upper right icon over available content.
Firmware updates use a lower right box over available content.
The connection icon occupies 12 by 10 pixels in the upper right corner.
The icon uses a gray server box and a red slash.
Update status occupies 34 by 13 pixels in the lower right corner.
The selected mode remains active while a connection warning appears.
The runtime retains the last content frame during firmware transfer.
If no content exists, the runtime displays a full utility panel.
The retained frame uses 6,144 additional PSRAM bytes.
Ticker Six retains its existing rendering code.

## Evidence

The public catalog supplies 18 system examples, including two pairing examples.
Each example uses the production C++ presenter and renderer.
Native checks validate frame bounds, animation, zero-length transfers, completed transfers, and large counters.
Overlay checks verify that every pixel outside the corner box remains unchanged.
The full Python suite passes 760 tests.
The critical suite passes 414 tests.
The firmware build passes for `mini-1.3.33`.
Production Ticker Six renderers supply four 384x32 reference frames.

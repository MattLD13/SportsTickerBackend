# Mini and main ticker display style

Date: 2026-10-15

## Direction

Use the main ticker scrolling game pane as the Mini reference.
Adapt fonts, spacing, and logo size to keep the 64x32 panel readable.
The local firmware version is `mini-1.3.2`.

## Owners

- `ticker_core/rendering/pixels.py` owns compact, tiny, and hybrid glyph data.
- `ticker_core/rendering/style.py` owns shared colors and the Mini logo size.
- `tools/generate_mini_ui.py` exports this drawing data and backend sport families into C++.
- `esp32_hub75/src/mini/protocol/panels.h` maps V2 fields into typed drawing inputs.
- `sports_pane.h` and `utility_panels.h` own Mini geometry and draw through a supplied canvas.
- The asset worker prepares 16x16 RAM marks from validated 18x18 sprites before rendering.
- The runtime refreshes clock mode when its displayed second changes.

## Replaced paths

The Mini no longer owns separate compact glyph definitions or a separate medium score font.
The Mini sports renderer no longer parses inning numbers, inning halves, or interruption words from status text.
It displays the backend status and uses explicit `activeTeam`, `powerPlayTeam`, `emptyNetSide`, and shootout fields.
The old shaded fallback badge and sports drawing functions are removed.
The new fallback badge uses the main ticker colors, rounded fill, and readable acronym contrast.

## Layout

The Mini uses black backgrounds, a blue-gray header rule, warm status text, and white scores.
Team marks use 16x16 pixels and share one vertical center in the game body.
Scores use three sizes. Each size keeps clear bounds between the marks.
Long center labels use two rows with normal letter spacing.
Football uses the main pane possession symbol, green down text, and red-zone border.
Baseball shows the shared inning glyph, batting-side count, occupied bases, and rectangular out indicators.
Hockey shows explicit power-play or empty-net ownership, manpower text, and the backend shootout window.
Soccer shows red-card counts above the team mark.
Stock mode uses the main ticker white symbol and gain or loss colors.
Clock mode shows date, seconds, white time, and the bottom progress rail.
Weather, music, flights, and airports now use the shared compact font and black background.
Their full content layouts and animation remain later work.
Sports clocks continue to use backend status values.

## Rendering evidence

`tools/render_mini_ui.cpp` compiles the same drawing headers that the ESP32 firmware uses.
It loads prepared assets before drawing and writes exact 64x32 RGB frames with RGB565 color conversion.
`tools/render_mini_ui.py` places these frames beside 384x32 main ticker frames.
The preview includes one production V2 sports record and local layout examples.
The examples cover football, baseball, triple-digit basketball, power plays, shootouts, overtime, period ends, soccer, stock, and clock.
Stock prices in the example describe layout input.
The preview process uses a temporary native executable on the Pi. It does not change its display service or device settings.

Generated PNG files stay outside Git:

- `previews/mini-ui/sports-comparison.png`
- `previews/mini-ui/comparison.png`
- `previews/mini-ui/production-main.png`
- `previews/mini-ui/production-mini.png`

## Release state

The firmware build, Python compilation, Ruff, shared drawing export check, and native frame generation pass.
The build uses 73,912 bytes of static RAM and 1,230,089 bytes of application flash.
The full suite passes 586 tests. The critical suite passes 256 tests.
The physical Mini now runs `mini-1.3.2` through USB. Serial output confirms its boot.
Its live network validation still needs a reachable 2.4 GHz network.

## Change notes

Owner: Shared main ticker glyphs and colors define the style. Mini drawing code owns target geometry.
Former path: Remove separate Mini glyph tables, medium scores, old sports drawing, and status inference.
Real input: A production V2 sports record and prepared team art feed both rendering paths.
Real output: Matching main ticker and Mini PNG previews use their real drawing implementations.

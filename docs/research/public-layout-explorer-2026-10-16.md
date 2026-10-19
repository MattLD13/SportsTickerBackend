# Public layout explorer

## Owner

The dashboard owns the public sample catalog and browser controls.
The production Pi and Mini renderers own pixels and layout rules.
The catalog contains synthetic data. It contains no device identifiers or real pairing codes.

## Former path

The complete Mini review gallery existed only in local preview files.
The public demo displayed only the big ticker.
The new `/demo/layouts` page serves both board sizes from one reviewed static catalog.
The landing page links to this subpage through its navigation and footer.
The existing live demo and portfolio embed keep their current render paths.

## Website style correction

The dashboard owns page routing and the public website style.
The explorer remains a subpage at `/demo/layouts`.
The main page retains its original sections and live demo.
The `/demo` template matches the version before the explorer release.
The main page includes only navigation and footer links to the explorer.

Remove the explorer's separate global theme and green branding.
Load the existing `style.css` and `led.js` on the subpage.
Scope additional layout rules under `.layout-page`.
Use the original header, logo, typography, page rails, and amber accents.

Route tests verify the main pages exclude explorer markup and assets.
The subpage test verifies shared website assets and its separate page frame.

## Input and output

The catalog contains 114 sports, utility, and system examples.
Sports include football, baseball, basketball, hockey, soccer, racing, and golf.
Hockey includes shootouts, 5v4, 5v3, 4v3, empty nets, and multiple overtime periods.
Football includes compact down labels, goal situations, and active untimed college overtime.

Each main frame uses the production Python renderer and measures 384x32 pixels.
Scrolling panes retain their production widths and appear together in a 384x32 viewport.
Each Mini frame measures 64x32 pixels.
The native firmware renderer produced 87 Mini sports frames on the Pi.
Physical Mini captures supply 27 utility and system frames.
The catalog records Mini firmware and renderer source hashes.

The main renderer requires numeric pregame scores.
The public sample producer supplies zero scores instead of invalid dash strings.
The Mini renderer then draws those same sample values.

The Mini currently uses its generic scoreboard for racing and golf.
The page identifies that limitation.
The main ticker has no matching JSON-error or Mini time-sync screen.
The page explains those differences without inventing frames.

## Interaction

- Select a category, search a situation, or browse with arrow keys.
- Compare both devices or view one device.
- Switch between pinned and scrolling main layouts.
- Start scrolling or play examples with a selected dwell time.
- Change preview brightness or select LED dots.
- Enlarge either display and inspect source pixel coordinates and RGB values.
- Copy a link with the selected example and preview settings.

Playback starts only after a user action.
The browser pauses timers and scrolling while the page is hidden.
The browser downloads the sample catalog and requests current big ticker frames from the server.
The page sends no controller commands and reads no fleet records.
Brightness and dwell controls affect the preview only.
Weather and music images show one captured animation moment.

## Rebuild

Run `python tools/rendering/build_demo_layouts.py` to package sample inputs and Mini captures.
The tool preserves Mini capture provenance. The server renders main frames when the browser requests them.
Use `--manifest` and `--mini-frames` to import reviewed native renders and physical captures.
The import requires one 64x32 PNG for each case ID.
The tool records source hashes when it imports those frames.
The source manifest uses the same game objects for both renderers.
Do not change a Mini sample input without rendering its new frame.

The published JSON is a website asset.
Generated review PNGs stay in `previews/demo-layouts` and remain outside Git.
Update `tools/rendering/verify_public_demo.py` after an authorized public design change.

## Validation

- All 114 Mini images decode at 64x32 pixels.
- All 112 matching main images decode at 384x32 pixels.
- All 87 Mini sports images match the native production output pixel for pixel.
- Public route tests reject fleet access and verify all modes and image dimensions.
- The current rendering release adds pixel equality and renderer update checks.
- Python compilation, Ruff, scoped Mypy, and JavaScript syntax checks pass.
- Browser checks cover search, layout switching, LED dots, zoom, and timed playback.
- Actual 384x32 frames appear in `previews/demo-layouts` for visual review.

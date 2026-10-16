# Current renderer for the public big ticker demo

## Owner

The production content catalog owns pane pixels.
The production frame builder owns complete 384x32 frames.
The shared pane composer owns strip widths and leading dividers.
The bundled DejaVu fonts own text metrics on every host.
The dashboard selects public inputs and requests those rendering services.

## Former paths removed

The browser drew its own clock and music layouts with browser fonts.
The layout catalog stored encoded main images that required manual rebuilds.
The browser assembled gallery panes with its own divider rules.
The live demo padded short strips with black pixels.
The backend deployment omitted `ticker_core` and ignored renderer-only changes.
Font discovery selected different system fonts on different hosts.

Remove those duplicate rendering and font paths.
The new public endpoint is `/api/v2/demo/frame.png`.
Remove the former `/api/preview/strip.png` endpoint and its active callers.

## Current path

The layout catalog stores sample inputs and Mini captures.
The browser requests current main pixels for a selected case and presentation.
Static views use `FrameBuilder`. Scrolling views use the production catalog and shared pane composer.
The browser displays those images and moves scroll strips by whole source pixels.
It repeats short strips seamlessly and refreshes public scores every 15 seconds.
Music and weather refresh up to four times per second. Clock frames refresh once per second.
Hidden previews stop requests and animation.

The renderer keeps at most 16 rendering sessions and 64 encoded frames.
Encoded frames also have an eight MiB memory limit.
Prepared asset revisions invalidate image cache entries.
Public frame requests include conditional image tags and a renderer release header.

Backend releases copy `ticker_core`, including its fonts.
Changes under `ticker_core` now trigger a backend release and the existing Pi update process.
The next page load uses the new release assets and renderer.
No manual screenshot rebuild is necessary for big ticker layout changes.

The deployment workflow owns the backend renderer source folder.
The first copy attempt found renderer directories owned by another account.
Tar rejected their timestamp and permission updates.
The workflow now verifies the source folder path and assigns it to the deployment account before copying files.

## Input and output proof

Pixel tests compare public football, hockey, weather, music, and clock responses with the real frame builder.
Another test compares scrolling responses with the real asynchronous `CardViewport` at three offsets.
A renderer change test modifies one production pixel and verifies the next renderer instance returns that pixel.
The test does not rebuild the catalog.
All 112 supported main examples render through the HTTP boundary at 384x32 pixels.
The Mini retains its 114 reviewed 64x32 captures.

The font files come from the personal Pi's installed DejaVu fonts.
The repository includes their copyright and permission notice.
The hardware and backend load these same files without system font discovery.

## Scope

The main website, live demo, portfolio embed, and separate explorer keep their existing page routes and style.
Public sports use available V2 sports snapshots.
Utility demonstrations use public samples and do not expose personal Spotify or flight records.
The demo does not mirror every physical device setting or overlay.
Mini captures remain fixed until a new Mini capture import.

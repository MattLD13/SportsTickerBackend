# Six card templates

The Six keeps bounded in-memory templates for fixed renderer layers.
Each renderer owns its own template key and draws live content after it copies the fixed layer.
The shared cache returns independent images. It limits entry count and pixel memory.
It never reads files or starts network requests from rendering functions.

## Template ownership

| Renderer | Reused layer | Dynamic inputs |
|---|---|---|
| Scrolling sports | Background, team logos or missing badges, rank marks, and rule. | Clock, scores, possession, down and distance, game situations, and overlays. |
| Full sports | Football field, soccer pitch, or baseball diamond. | Scores, time, possession, positions, logos, red-zone state, and game-specific details. |
| Stock | Company symbol and prepared logo. | Price, change, direction, and position. |
| Golf | Event header and column labels for stroke and match play. | Players, scores, positions, and results. |
| Racing | Session header, flag, and separator. | Driver order, lap, gap, and other race facts. |
| Airport board | Airport heading, weather label, inbound and outbound labels, and dividers. | Arrival and departure rows. |
| Clock | Date heading. | Current time and progress rail. |

The sports key includes pane width, competition rule, team colors, abbreviations, rankings, logo pixels, and logo outline settings.
A changed key builds a new template. Dynamic values cannot reuse an incompatible fixed layer.
Full baseball fields also include the three base-occupancy states in their key.
The scrolling sports cache allows up to 256 entries and four MiB of pixel data.
The regression suite retains 150 distinct maximum-width templates and confirms hits after score and clock changes.

The news banner already caches its active image. Racing already retains separate driver artwork caches.
Weather animation, music cover preparation, visitor-flight backgrounds, and full-screen hockey and basketball fields were tested.
They did not show a clear gain in these short trials. Their attempted template changes were removed.
Their existing rendering and animation paths remain active.
Other overlays and status panels keep their existing renderers.

## Pixel evidence

The original renderers were saved before this change under the local preview directory.
The comparison renders changing scores, time, possession, base states, and logo pixels through both implementations.
It checks image mode, dimensions, and every pixel before recording timings.
It covers seven scrolling sports, stock, stroke and match-play golf, racing, visitor flight, airport boards, weather, music, and clock.
Separate full-screen cases exercise football, hockey, baseball, basketball, and soccer.
The test suite also checks changed logo outlines, bounded eviction, private image copies, and 150 wide unique cards.

## Pi renderer measurements

The Pi test uses 150 controlled input cases, prepared logo images, alternating measurement order, and two paired timed runs.
The test changes scores, clock, possession, or equivalent live data between pairs.
Each test primes the templates before timing its warm path. It excludes provider reads, networking, scheduling, and display refresh.

| Renderer | Original CPU for 150 renders | Template CPU for 150 renders | Reduction |
|---|---:|---:|---:|
| Scrolling sports | 2,418 ms | 420 ms | 82.6% |
| Stock | 352 ms | 271 ms | 23.2% |
| Stroke-play golf | 693 ms | 233 ms | 66.5% |
| Match-play golf | 1,043 ms | 387 ms | 62.9% |
| Airport board | 839 ms | 325 ms | 61.3% |
| Clock | 477 ms | 220 ms | 54.0% |

The separate four-pair initial run showed music cover caching used about 3.9% more CPU.
It showed no clear savings for the weather background or visitor-flight layer.
The final code does not keep those three attempted caches.

The separate full-screen test uses forty controlled renders per pair and two pairs for each sport.
Football field reuse reduced median renderer CPU from 1,387 ms to 1,289 ms, or 7.1%.
Baseball diamond reuse reduced it from 1,540 ms to 1,194 ms, or 22.4%.
Soccer pitch reuse reduced it from 1,397 ms to 1,241 ms, or 11.2%.
Hockey and basketball showed gains below 2.2% in this small test. Their field caches were removed.

The cold sports check creates a fresh renderer before each pair.
The original path uses 2,427 ms of CPU for 150 first renders. The template path uses 2,500 ms.
The first creation is about three percent more expensive in this short test. Later updates can reuse those templates.
The test uses two prepared fixture logos with unique per-game pixel markers. It does not measure remote image loading.

## Physical scrolling application

The physical Pi comparison starts one Six with 150 controlled game panes and its normal polling and card processes.
Both versions use identical application code and data. Only the sports stadium renderer differs.
Each trial runs for 45 seconds plus a drain window. It alternates visible-game and all-game updates.

| Measurement | Original renderer | Template renderer |
|---|---:|---:|
| Full 150-card warmup | 31.77 s | 22.71 s |
| First screenful | 8.56 s | 8.53 s |
| Targeted visible updates displayed | 15 of 15 | 16 of 16 |
| Median visible input to frame-sink return | 640 ms | 466 ms |
| Average presentation rate | 33.02 FPS | 33.10 FPS |
| Pending card jobs after drain | 68 | 0 |

The number of visible targets differs because scrolling positions differ.
This is one paired physical trial, not a typical or tail-latency estimate.
The input is controlled V2 data. It excludes ESPN, network delivery, and LED scan completion.
The first-screen time remained similar because cold templates must be built.

The benchmark and image evidence reside under `previews/profiling/2026-10-25/latency/scrolling/templates/`.
The normal controller was restored on its original immutable release. The test units were stopped.

The racing template was adapted to retain the existing racing contract.
The earlier racing timing used a different renderer and does not measure the published implementation.
The renderer owns the header template. It replaces repeated header drawing.
A racing card with changing driver metrics produces the same pixels with and without template reuse.

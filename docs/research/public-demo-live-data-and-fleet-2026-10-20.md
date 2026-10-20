# Public demo data and fleet status

## Behavior owners

`PublicDemoData` owns shared public stock and EWR flight refreshes through the existing provider ports.
It uses fixed public settings and does not read personal flight selections or Spotify accounts.
It refreshes each source at most once every 30 seconds while visitors request that mode.
All visitors share the cached result. Failed refreshes retain available results for at most ten minutes.
An unavailable source produces an empty view instead of a saved quote or flight.

Stocks use the production Tech / AI group, including prepared company logos.
Flights select a real EWR arrival and request its tracked flight details.
Airports use the live EWR arrivals and departures board.
The former default demo used one saved Apple quote and reviewed flight examples.
The layout explorer retains its reviewed examples.

`_preview_items` carries V2 envelope identity, kind, and family into the renderer input.
Provider normalization moves these facts out of the nested data mapping.
The former demo discarded the envelope, which sent normalized airport data to the sports renderer.
Regression tests now pass real provider adapters through the public frame route.

`PreviewRenderer.animation` prepares three seconds of consecutive production frames at 30 frames per second.
The browser displays these frames through its animation callback and prepares the next chunk in advance.
Music initializes its phase from playback progress and warms the production renderer's smoothing state.
Adjacent chunks match continuous playback, including future fetch anchors.
The former browser fetched one frame every 250 milliseconds, plus request latency.
Weather and music retain their public example content.

## Fleet presentation

The Fleet heading says: Every board, and what it is doing.
Offline labels describe missing heartbeats. They do not claim that the physical panel is dark.
Each connected, paired ticker contributes its effective scheduled mode to the On air badges.
Offline and unpaired devices do not activate a mode badge.
Markets list all five actual stock groups, with enabled and disabled states across the fleet.
Ticker Six and Ticker Mini have separate hardware cards.
Each card uses its product geometry and its device's build and uptime.
The Mini card shows page duration. The Six card shows scroll speed.
The former card showed server build and server uptime beside Six geometry.

## Evidence

- Real EWR reads returned an airport board and flight UA967 from NAP to EWR.
- The production renderer produced inspected 384 by 32 frames for both live flight views.
- Company logo downloads for AAPL, MSFT, and NVDA returned PNG images.
- A browser check displayed all three company marks through the production stock renderer.
- Music and weather each displayed 204 frame changes during a 6.8-second browser sample.
- The mean interval was approximately 33.33 milliseconds for both modes.
- Each sample crossed two chunk boundaries and fetched two additional chunks.
- The browser reported no script errors.
- Desktop checks showed simultaneous Sports and Weather badges, all five market options, and both hardware cards.
- The 390-pixel mobile check found no horizontal page overflow.
- The full Python suite passed 1104 tests, with ten skips.
- The critical suite passed 754 tests, with ten skips and 350 deselected tests.

Browser captures, real provider frames, and timing reports remain under the ignored `previews/demo-live-fix/` directory.

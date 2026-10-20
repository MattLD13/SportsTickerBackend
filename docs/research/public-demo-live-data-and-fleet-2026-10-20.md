# Public demo data and fleet status

## Behavior owners

`PublicDemoData` owns public stock, NYC weather, and EWR flight refreshes through the existing provider ports.
It uses fixed public settings and does not read personal flight selections or Spotify accounts.
It refreshes stocks and flights at most once every 30 seconds while visitors request that mode.
It refreshes NYC weather at most once every five minutes.
NYC uses coordinates 40.7128, -74.0060. EWR uses its own fixed airport settings.
All visitors share the cached result. Failed refreshes retain available results for at most ten minutes.
An unavailable source produces an empty view instead of a saved quote or flight.

Stocks use the production Tech / AI group, including prepared company logos.
Flights prefer validated tracking details for an EWR flight.
If tracking is unavailable, Flights displays that flight's real airport schedule facts.
It checks up to three candidates from the airport board.
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
Music retains its public example content. Weather uses live NYC data.

## Fleet presentation

The Fleet heading says: Every board, and what it is doing.
Offline labels describe missing heartbeats. They do not claim that the physical panel is dark.
Each connected, paired ticker contributes its effective scheduled mode to the On air badges.
Offline and unpaired devices do not activate a mode badge.
Markets list all five stock groups in orange by default.
A connected ticker in Stocks mode turns each selected group green.
Different tickers can activate different green groups. Offline tickers do not activate groups.
The Active modes summary shows the number of distinct active modes.
Ticker Six and Ticker Mini have separate hardware cards.
Each card uses its product geometry and its device's build and uptime.
The Mini card shows page duration. The Six card shows scroll speed.
The former card showed server build and server uptime beside Six geometry.
Each card has a padded header in a horizontal scrolling catalog.
The catalog includes Ticker Six, Ticker Mini, and Ticker Server.
Tabs, keyboard arrows, and swipe scrolling select the visible card.
The server card shows API version, memory, threads, open files, build, and process uptime.
The home stylesheet URL includes the current release version to replace cached styling after deployment.
The former URL allowed the browser to retain old card styles for four hours.
Build labels show existing versions as Build 1757 and Build 1.3.36.
Hover text retains the complete device identifier. Firmware version values remain unchanged.

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

## Follow-up validation

- A live NYC read returned a 62-degree temperature and rendered an inspected 384 by 32 frame.
- Browser measurements found a 24-pixel card gap and 23-pixel title inset at desktop and mobile widths.
- Both card headers measured 99 pixels high. Neither viewport had horizontal overflow.
- Browser text checks confirmed the numeric active-mode count and both shorter version labels.
- The full suite passed 1113 tests, with ten skips.
- The critical suite passed 763 tests, with ten skips and 350 deselected tests.

Follow-up screenshots and measurements remain under the ignored `previews/demo-card-polish/` directory.

## Live-image cache correction

Production PNG responses had a four-hour browser cache lifetime, including an unavailable Flights frame.
The weather animation's initial URL had no unique request token.
The live response now sends private and no-store directives to browsers and CDNs.
The browser also disables its fetch cache and includes release and request identifiers in every preview URL.
The server retains its bounded rendered-frame cache, which remains separate from browser and CDN caching.
See [Cloudflare cache directives](https://developers.cloudflare.com/cache/concepts/cache-control/) for the no-store behavior.

The previous flight selector checked only one candidate and discarded the schedule if tracking details were missing.
Regression checks now cover a missing first candidate, a usable second candidate, and real schedule output without tracking.
Schedule cards omit unreported telemetry instead of inventing altitude, speed, or distance.
When a public source is still loading, the browser shows a NYC or EWR loading message.

Browser checks confirmed three catalog cards, tab clicks, keyboard arrows, swipe synchronization, and no horizontal page overflow.
These checks used desktop and mobile widths and collected no browser script errors.

Browser captures, real provider frames, and timing reports remain under the ignored `previews/demo-live-fix/` directory.

# Spotify adaptive polling and quota recovery

## Evidence and history

Live backend health reported `HTTP 429 QUOTA_EXCEEDED` while the user played a song.
The fixed 0.6-second music schedule requested up to 100 source refreshes per minute for each ticker.

Commit `fdec4e7e` removed `sports_ticker/fetchers/spotify.py` during the V2 rewrite.
That source used 0.6 seconds while playing, 1.5 seconds while paused, and three seconds while idle.
It used five seconds after API errors and ten seconds after loop errors.
It fetched the queue when the track changed.
V2 initially used a ten-second music schedule.
Commit `49251b1b` replaced that schedule with a fixed 0.6-second interval.

## Owners and replaced path

`SpotifyIntegrationService` owns account playback cadence, shared reads, access tokens, queue windows, and rate-limit cooldowns.
The production scheduler wakes the music provider every 0.6 seconds.
The service replaces the fixed upstream polling and repeated access-token refresh path.

- Playing accounts poll every 0.6 seconds.
- Paused accounts poll every 1.5 seconds.
- Idle accounts poll every three seconds.
- Polling follows Spotify's observed state, including idle responses that retain the last song's display metadata.
- Transient errors use a 15-second retry interval.
- Each group and Spotify account shares one poll across its tickers.
- A single-flight lock prevents concurrent duplicate requests.
- Access tokens remain cached until one minute before expiry.
- Reauthorization and disconnect clear account caches. HTTP 401 evicts the rejected access token.
- Track changes trigger queue reads. Failed reads remain pending for retry. Successful empty queues remain cached.

The HTTP adapter exposes status and `Retry-After` as structured error values.
HTTP 429 starts a shared application cooldown and preserves the existing stale-result path.
Without `Retry-After`, the service increases delays from 30 seconds to a maximum of 15 minutes.
The service checks the cooldown again after acquiring the account lock.
Transient failures retain their error state until their retry deadline, including failures before the first successful playback read.
Music stale results use ticker identity and exact settings, preventing reuse across different owners.

## Validation

Injected-clock tests verify playback states, token expiry, reauthorization, rejected tokens, retry deadlines, queue recovery, and shared account reads.
A concurrent test proves two tickers make one playback request and one queue request.
A provider test verifies that a failing ticker never receives another ticker's cached music.
The focused integration and provider checks pass 21 tests.

Upstream quota recovery remains controlled by Spotify. A backend restart does not clear that limit.

Spotify documents its rolling application limit and `Retry-After` handling in its rate-limit guide.
See https://developer.spotify.com/documentation/web-api/concepts/rate-limits.
Token expiry follows https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens.

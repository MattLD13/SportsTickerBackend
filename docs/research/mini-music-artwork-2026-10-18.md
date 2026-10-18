# Mini album artwork and playback layout

## Owners

`sports_ticker/assets/mini_artwork.py` owns 32x32 cover preparation and the bounded server RAM cache.
`ArtworkAssets` owns five Mini covers and one background download buffer in PSRAM.
`artwork_window.h` owns current cover priority, queue residency, retries, and eviction.
`sports_ticker/assets/music_palette.py` owns album accent colors for both products.
The existing asset worker and `NetworkWorker` own transfers through the existing HTTPS connection.
`music_pane.h` owns drawing. The protocol presenter reads playback values in seconds.

## Former path

The Mini previously drew a synthetic record, truncated song names, and treated progress seconds as a percentage.
The new path removes that renderer and displays the album's actual square cover.
The Mini uses envelope track identity to reset text scrolling when the song changes.

## Layout

- The full cover occupies pixels 0 through 31 across all 32 rows.
- The right column shows the song, artist, remaining time, and a thin progress bar.
- Long song and artist names scroll separately after an initial hold.
- Paused playback freezes the countdown and preserves the album accent color.
- The countdown, progress bar, and divider use the album palette.
- Missing artwork displays a music note. It never displays another song's cover.

## Transfer and resource contract

`GET /api/v2/assets/mini-artwork/<asset_id>.mta` serves public, immutable RGB565 cover bytes.
The `MTA1` format contains a 16-byte header and 2048 pixel bytes.
The metadata supplies dimensions, length, format, version, and SHA256.
The Mini rejects invalid lengths, headers, and checksums before installing a cover.

The backend retains at most 12 encoded covers, approximately 24 KiB of pixel bodies.
The Mini allocates 12,384 bytes in PSRAM for five images and one transfer buffer.
The window retains the current cover, three queued covers, and one previous cover when Spotify supplies them.
Duplicate covers share one slot. Missing queue entries do not create artificial artwork.
Current artwork downloads first. Upcoming artwork downloads next. Previous artwork downloads last.
The payload adds `next_cover_assets` and `last_cover_asset` beside `cover_asset`.
Each ready reference supplies `accent_rgb` from the shared Ticker Six palette function.
Artwork never enters the logo flash cache. No image decoding or network work runs in the drawing function.
Repeated metadata polls reuse the same cover. Failed requests use a retry delay.
The Mini redraws music at ten frames per second. Panel refresh remains 200 Hz.

## Validation

- The full Python suite passes 744 tests. The critical suite passes 411 tests.
- Real V2 routes verify asynchronous preparation, family isolation, SHA256, byte length, ETag, and invalid identities.
- Cache checks verify source restrictions and bounded memory eviction.
- The native Mini presenter and renderer check clipping, scrolling, pause, completion, and unknown duration.
- The physical Pi renders 242 frames with the production Mini drawing code.
- Example album art uses actual catalog images, followed by the production RGB565 preparation path.
- The preview tool renders real 384x32 Ticker Six reference frames.
- Firmware `mini-1.3.27` builds successfully with the new artwork path.

## Cache and stock update

Firmware `mini-1.3.28` replaces the single cover cache and fixed green music accents.
The native cache check verifies five covers, priority, forward and back reuse, retries, stale transfers, and bounded eviction.
The V2 route check prepares five distinct covers and excludes the fourth queued cover.
Serial metrics report `artwork_resident`, `artwork_planned`, `artwork_cache_hits`, and `artwork_downloads`.

The stock presenter owns quote strings and currency formatting.
The stock renderer places the symbol and percentage above the price and dollar change.
Small text and separate rows prevent the former bottom row collision.
The shared pixel font supplies the missing percentage glyph.
Native stock checks cover gains, losses, long symbols, large prices, and missing quotes.
The physical Pi renders 204 Mini frames through the production drawing code.
The preview tool also renders real 384x32 Ticker Six stock frames.
Example quote values demonstrate layout. They do not represent live market prices.

Cache and stock previews are in `previews/mini-cache-stocks/`.

Preview images and animations are in `previews/mini-music-layout/`.

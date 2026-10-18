# Mini album artwork and playback layout

## Owners

`sports_ticker/assets/mini_artwork.py` owns 32x32 cover preparation and the bounded server RAM cache.
`ArtworkAssets` owns the Mini's current cover and background download buffer in PSRAM.
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
- Paused playback freezes the countdown and uses a neutral timer color.
- Missing artwork displays a music note. It never displays another song's cover.

## Transfer and resource contract

`GET /api/v2/assets/mini-artwork/<asset_id>.mta` serves public, immutable RGB565 cover bytes.
The `MTA1` format contains a 16-byte header and 2048 pixel bytes.
The metadata supplies dimensions, length, format, version, and SHA256.
The Mini rejects invalid lengths, headers, and checksums before installing a cover.

The backend retains at most 12 encoded covers, approximately 24 KiB of pixel bodies.
The Mini allocates 4128 bytes in PSRAM for the current image and transfer buffer.
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

Preview images and animations are in `previews/mini-music-layout/`.

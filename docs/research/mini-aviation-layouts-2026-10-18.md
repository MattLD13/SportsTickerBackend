# Mini flight, airport, and music layouts

## Ownership

The Mini presenters own text formatting and board pagination.
The Mini renderers own pixel placement.
The backend retains ownership of flight status, delay, route, and playback facts.
Ticker Six retains its existing renderers.

## Replaced paths

- Flight routes use separate airport labels instead of one clipped route string.
- Flight status, ETA, altitude, and speed use separate rows.
- Airport boards show aligned flight numbers and airport codes.
- Airport boards advance through four pairs at four-second intervals.
- The footer alternates arrival and departure status every two seconds.
- Music progress uses all 64 bottom pixels instead of 30 pixels beside the artwork.
- Missing artwork and idle playback display a centered music note.
- Idle playback displays `NO MUSIC` and `PLAY A SONG`.

## Validation inputs and outputs

The public catalog supplies the same input to the production Mini presenter, native renderer, firmware, and website.
`MD13` renders the complete `EWR` to `LAX` route and `2H20M` ETA.
`MD28` renders four arrivals and departures, including `UAL12345`, a 25-minute arrival delay, and a 120-minute departure delay.
`MD29` renders tracker setup from the backend default flight record.
`MD26` renders idle playback without artwork.
`MD27` renders playback while artwork is unavailable.

Native checks assert frame bounds, board selection, delay labels, and progress coverage across all 64 pixels.
The generated website gallery includes airport pagination and the revised music frames.

The full Python suite passes 760 tests.
The critical suite passes 414 tests.
The firmware build and both native panel checks pass.
Seven existing Ticker Six flight and airport frames remain pixel-identical.

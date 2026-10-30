# Ticker Mini

The production display uses `64x32` pixels.
`src/mini/protocol/panes.h` reads explicit display facts into pane views. `src/mini/ui/` draws the views without I/O.
`src/mini/runtime/` owns scheduling and network results. `src/mini/platform/` owns hardware boundaries.
Edit shared field and glyph owners before regenerating `fields_generated.h` or `ui/generated.h`.
Use the generators in `tools/mini/`. Do not hand-edit generated headers.
If pane pixels change, run `python tools/rendering/mini_golden.py check`. Accept a change on purpose with `accept` only after you inspect real `64x32` frames.
If sports pixels change, also compile the native production path with `tools/workspaces/native_hockey.py`.
The PlatformIO environment is `esp32s3` in `platformio.ini`.
Native pane checks do not prove complete firmware or hardware behavior.
Keep provisioned credentials in device storage. Do not print credential header values.
If the user authorizes hardware checks, restore ordinary device state after the checks.

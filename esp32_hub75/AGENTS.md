# Ticker Mini

The production display uses `64x32` pixels.
`src/mini/protocol/` reads explicit V2 facts. `src/mini/rendering/` draws them without I/O.
`src/mini/runtime/` owns scheduling and network results. `src/mini/platform/` owns hardware boundaries.
Edit shared field and glyph owners before regenerating `fields_generated.h` or `ui_generated.h`.
Use the generators in `tools/mini/`. Do not hand-edit generated headers.
If sports pixels change, compile the native production path with `tools/workspaces/native_hockey.py`.
Use the real render preview for other pane changes.
The PlatformIO environment is `esp32s3` in `platformio.ini`.
Native pane checks do not prove complete firmware or hardware behavior.
Keep provisioned credentials in device storage. Do not print credential header values.
If the user authorizes hardware checks, restore ordinary device state after the checks.

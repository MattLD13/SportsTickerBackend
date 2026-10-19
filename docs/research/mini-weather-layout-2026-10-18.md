# Mini weather layout and shared artwork

## Owners

The weather provider owns temperature, wind, humidity, AQI, condition, and day or night state.
`mini/protocol/panels.h` converts those canonical values into one `WeatherPane`.
`mini/rendering/weather_pane.h` owns the 64x32 layout and reads prepared animation frames.
The runtime supplies elapsed time and redraws animated modes at ten frames per second.

Ticker Six's `PreparedWeatherRenderer.draw_weather_pixel_art` owns weather icon artwork.
`tools/mini/generate_mini_weather.py` samples that renderer and fits each animation into a stable 22x17 rectangle.
The generator removes duplicate frames and writes immutable RGB565 arrays for Mini flash storage.
CI checks the generated arrays against the drawing owner.

## Former path

The former Mini renderer drew separate weather icons and packed four statistics around the temperature.
It truncated readings and used the sun for clear weather at night.
The new path removes those drawing functions and reads the provider's explicit `is_day` flag.
It preserves unknown readings as `--`.

## Layout

- The city uses the same small white header as stocks. Long names scroll after an initial hold.
- A thin divider uses the current condition's accent color.
- The left area uses Ticker Six artwork, including its moon texture and animated sun, rain, snow, fog, and lightning.
- The right area shows the temperature, Fahrenheit unit, and condition.
- The footer alternates every five seconds between feels-like and wind, then humidity and AQI.
- Wind includes `MPH`. Humidity includes `%`.
- Negative and three-digit temperatures retain their complete text.

Moon and cloud artwork remain static, matching their Ticker Six source.
The other artwork follows a sampled 12.6-second loop at ten frames per second.
The Mini reads these frames from flash without network transfers or image cache allocations.

## Validation

Live weather input comes from `HybridWeatherProvider` and the V2 content projection.
The preview tool renders 337 Mini frames through the production C++ renderer on the physical Pi.
It also renders a real 384x32 Ticker Six weather reference.
The native check verifies artwork pixels, animation changes, day and night, header spacing, statistics, missing values, and frame bounds.
The complete Python suite passes 758 tests. The critical suite passes 412 tests.

Firmware `mini-1.3.29` uses 77,268 static RAM bytes and 1,455,777 application flash bytes.
The firmware occupies 69.4 percent of its 2 MiB application partition.

Preview files are in `previews/mini-weather/`.
`sunny-motion.gif` and `rain-motion.gif` show the shared artwork in the Mini layout.

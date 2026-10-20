# Mini sensors and public coverage

## Behavior owners

`MiniDeviceSensors` owns chip temperature reads and LIS3DH acceleration reads.
It samples temperature every ten seconds and acceleration every 100 milliseconds.
The heartbeat sends finite chip readings through the existing `metadata.temperature_c` field.
Invalid readings become null. The website displays a dash for unavailable readings.
The value measures the ESP32 chip, not room temperature.
The former Mini heartbeat omitted this field.

`mini_display::Orientation` owns landscape orientation decisions.
It requires 800 milliseconds of stable gravity before changing between zero and 180 degrees.
It ignores portrait positions, flat positions, missing samples, and strong motion.
Ticker Mini keeps its existing 64 by 32 layouts.
`MiniMatrix` rotates physical output, retained overlay backgrounds, and the captured frame mirror together.
The former driver always used zero rotation.

The public dashboard uses the shared league catalog for conference names.
Markets use `selected_market_groups`, which also owns provider group selection.
The former coverage function mixed all enabled settings into both sections and formatted raw keys as labels.
The Modes section now includes Stocks and uses each mode's display name.

## Input and output evidence

The production catalog returned `ncf_fbs:1` as ACC and `ncf_fcs:177` as UAC.
Regression inputs contain both sports settings and stock settings.
Their market output contains only the selected Financial Stocks group.
Conference output uses catalog labels and respects its parent league's enabled state.
The public page remains available when the conference provider fails.

The connected Mini ran `mini-1.3.36` after an application-only USB update.
The update preserved its bootloader, partition table, credentials, and asset storage.
A private local backup retains the previous application image outside Git.
The first chip reading was 36.3 degrees Celsius.
After startup, serial telemetry reported 44.3 degrees Celsius.
The public fleet page showed 44C for the same Mini.
The user confirmed that the physical display turns correctly when held upside down.

A 35-second hardware capture collected four complete 64 by 32 RGB frames and ten timed page visits.
The mean page duration was 3015.715 milliseconds.
The run reported no capture errors, JSON failures, heartbeat failures, or reconnects.
The final heartbeat returned HTTP 200, and data age was 2632 milliseconds.
The display refresh rate stayed at 200 Hz. Firmware boot validation passed.

## Validation

- PlatformIO compiled and linked the complete ESP32-S3 firmware.
- Native checks covered orientation settling, rejected positions, invalid samples, timer wrap, frame rotation, and retained background rotation.
- The production renderer rebuilt 135 public examples from 4072 Mini frames.
- The full Python suite passed 1093 tests, with ten skips.
- The critical suite passed 743 tests, with ten skips and 350 deselected tests.

Hardware captures and the firmware backup remain in the ignored `previews/mini-sensors/` directory.

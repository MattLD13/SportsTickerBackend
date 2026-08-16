# Hardware profiles

The backend stores hardware identity separately from display mode.

| Profile | Hardware | Logical display | Modes |
| --- | --- | --- | --- |
| `normal` | Raspberry Pi Zero 2 W | six panels, `384x32` | all V2 modes |
| `mini` | ESP32-S3 | one panel, `64x32` | sports |
| `custom` | administrator-defined | validated dimensions | validated capabilities |

Every device registration can include a `profile` object. Legacy registrations infer `normal` unless their metadata identifies an ESP32 device. Custom profiles must include display width, height, and panel count.

The backend persists the normalized profile in device metadata, returns it in ticker responses, and filters projected modes using its declared capabilities.

Set these Pi variables for a custom display:

```powershell
$env:TICKER_PRODUCT_FAMILY = "custom"
$env:TICKER_HARDWARE = "custom-controller"
$env:TICKER_DISPLAY_WIDTH = "128"
$env:TICKER_DISPLAY_HEIGHT = "32"
$env:TICKER_DISPLAY_FIT_MODE = "letterbox"
$env:TICKER_PANEL_COUNT = "2"
```

The fit mode can be `scale`, `crop`, or `letterbox`. The renderer applies that policy before overlays and frame presentation.

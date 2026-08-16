# TickerControl

Open `TickerControl.xcodeproj` in Xcode.

The app uses the V2 ticker API. It stores its controller token on this device after code pairing.

Use Settings > Set Up Ticker Wi-Fi when a ticker enters recovery. Choose the iPhone's current Wi-Fi to prefill its SSID, or choose a different network and enter its name. Enter the six-digit code and Wi-Fi password. iOS will ask permission to join the temporary ticker network before the app submits the settings over the ticker's local HTTPS portal.

When no ticker is paired, the app gates the dashboard behind this setup screen. A second household user can choose Connect an existing ticker with a pair code, using a fresh code from the owner's device row.

Set `SPOTIFY_APP_RETURN_URI` to `tickercontrol://spotify` on the backend. Spotify returns to the app after authorization.

`TickerControl/` contains app source and assets. `design/` contains source icon art. `tools/` contains icon generators.

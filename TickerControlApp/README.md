# TickerControl

Open `TickerControl.xcodeproj` in Xcode.

The app uses the ticker API in `docs/api.md`. It keeps one controller token for each paired ticker in the Keychain.

When no ticker is paired, the app shows the setup screen first.

- Set Up Wi-Fi sends the home Wi-Fi settings to a new ticker over Bluetooth. Enter the six-digit WIFI PIN that the ticker shows. Choose the current Wi-Fi of the iPhone, or enter the name of a different network. The app then pairs with the code that the ticker returns.
- Connect an existing ticker pairs with a code. A second household user gets a fresh code from Show Pair Code on the device card of the owner.

The connection line on Home opens the ticker switcher. The selector on each Settings device card also changes the active ticker.
My Teams and Spotify belong to the controller group of the app. Display mode, brightness, scroll speed, and the other hardware settings belong to each ticker.

Set `SPOTIFY_APP_RETURN_URI` to `tickercontrol://spotify` on the backend. Spotify returns to the app after authorization.

`TickerControl/` contains the app source and assets. `design/` contains the source icon art.

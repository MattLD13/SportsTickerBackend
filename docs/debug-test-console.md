# V2 test console

Set `TICKER_DEBUG_PASSWORD` before starting the backend.

Open `/debug/test` after the server starts. The former `/debug/alerts` and `/debug/news` URLs redirect to this console.

The console uses the V2 API and tests health, catalogs, tickers, pairing, settings, overlays, previews, heartbeat, updates, reboot, acknowledgements, and Spotify status.

Enter controller and deployment tokens when an action requires them. The page keeps tokens in browser memory only.

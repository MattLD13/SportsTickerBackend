# Ticker API

The server has one API. Paths have no version prefix.
Each request and response body is JSON, unless the table names another type.

## Authorization

| Caller | Header | Scope |
|---|---|---|
| Device | `X-Device-Token: <token>` | The token identifies one ticker, so device paths have no ticker ID. |
| App | `Authorization: Bearer <controller token>` | The token comes from `POST /pair`. It controls the tickers of one controller group. |
| Operator | `X-Deployment-Token: <secret>` | The secret is the `TICKER_DEPLOY_TOKEN` setting of the server. |
| Public | none | |

## Device

| Method | Path | Job |
|---|---|---|
| `POST` | `/register` | Register a device. The body has `device_id`, and can have `name`, `metadata`, `profile`, and `pairing_code`. |
| `POST` | `/verify` | Check the device token. |
| `GET` | `/data` | The full display data of the ticker. The Six reads this. |
| `POST` | `/poll` | Send telemetry in `metadata` and get the compact display data. The Mini reads this. |
| `WS` | `/stream` | Live display data: a snapshot, then deltas. Subprotocol `ticker`. |
| `POST` | `/heartbeat` | Send telemetry. The answer is the ticker record. |
| `GET` | `/firmware` | The Mini firmware manifest. `?version=` names one release. |
| `POST` | `/update-result` | Report the result of a firmware update. |
| `POST` | `/reboot-ack` | Acknowledge a reboot command. The body has `id`. |

## Public files

| Method | Path | Job |
|---|---|---|
| `GET` | `/firmware/<file>.bin` | The current Mini firmware binary. |
| `GET` | `/assets/sprites/<id>.mts` | One Mini team sprite. The ID is its content hash. |
| `GET` | `/assets/artwork/<id>.mta` | One Mini album cover. The ID is its content hash. |

## App

| Method | Path | Job |
|---|---|---|
| `POST` | `/pair` | Exchange a pairing code for a controller token. |
| `GET` | `/tickers` | The tickers of the controller group. |
| `GET` | `/tickers/<id>` | One ticker record. |
| `PATCH` | `/tickers/<id>` | Change the name, display settings, or schedule override. |
| `DELETE` | `/tickers/<id>` | Delete the ticker. |
| `GET` | `/tickers/<id>/data` | The full display data, as the device sees it. |
| `POST` | `/tickers/<id>/pairing-code` | Make a new pairing code. |
| `DELETE` | `/tickers/<id>/pairing` | Unpair the ticker. |
| `POST` | `/tickers/<id>/reboot` | Ask the device to reboot. |
| `POST` | `/tickers/<id>/events/<event_id>/ack` | Dismiss one alert or news overlay. |
| `GET` | `/tickers/<id>/schedule` | The weekly blocks, the live-game conditions, and the effective mode. |
| `POST` | `/tickers/<id>/schedule/blocks` | Add a weekly block. |
| `PATCH` | `/tickers/<id>/schedule/blocks/<block_id>` | Change a weekly block. |
| `DELETE` | `/tickers/<id>/schedule/blocks/<block_id>` | Delete a weekly block. |
| `POST` | `/tickers/<id>/schedule/conditions` | Add a live-game condition. |
| `PATCH` | `/tickers/<id>/schedule/conditions/<condition_id>` | Change a live-game condition. |
| `DELETE` | `/tickers/<id>/schedule/conditions/<condition_id>` | Delete a live-game condition. |
| `GET` | `/tickers/<id>/spotify` | The linked Spotify accounts. |
| `DELETE` | `/tickers/<id>/spotify` | Unlink every Spotify account. |
| `POST` | `/tickers/<id>/spotify/login` | Start a Spotify login. The answer has the URL to open. |
| `PATCH` | `/tickers/<id>/spotify/priority` | Choose the account that the ticker shows first. |
| `DELETE` | `/tickers/<id>/spotify/<account_id>` | Unlink one Spotify account. |
| `GET` | `/spotify/callback` | Public. Spotify sends the browser here after a login. |

## Catalog

| Method | Path | Job |
|---|---|---|
| `GET` | `/modes` | The display modes. |
| `GET` | `/leagues` | The leagues. |
| `GET` | `/leagues/<league_id>/teams` | The teams of one league. |
| `GET` | `/stocks?q=<text>` | Stock symbols that match the text. |

## Operator

| Method | Path | Job |
|---|---|---|
| `GET` | `/health` | Public. Server, engine, and provider health. |
| `GET` | `/fleet` | Heartbeat age and telemetry of every ticker. |
| `GET` | `/fleet/updates` | The firmware update history. |
| `POST` | `/tickers/<id>/update` | Ask a ticker to install a release. The body has `version`. |
| `POST` | `/tickers/<id>/credential` | Enroll a device token. The body has `token_sha256`. A token can belong to one ticker only. |
| `GET` | `/workers` | The release, connection, health, and restarts of each provider worker. |
| `POST` | `/workers/<provider>/deploy` | Start a release of one worker next to the active release. The body has `release`. The answer is `200` when the release becomes active, and `409` when the supervisor keeps the old release. |
| `POST` | `/alerts` | Publish a score alert overlay. |
| `POST` | `/news` | Publish a news overlay. |

## Web pages

| Method | Path | Job |
|---|---|---|
| `GET` | `/` | The public landing page. |
| `GET` | `/dashboard` | The controller dashboard. |
| `GET` | `/demo` | The full-screen panel demo. |
| `GET` | `/demo/portfolio` | The embeddable panel demo. |
| `GET` | `/demo/layouts` | The layout gallery. |
| `GET` | `/demo/frame.png` | One demo frame from the Six renderer. |
| `GET` | `/demo/animation.png` | Consecutive demo frames for music and weather. |
| `GET` | `/display-alerts` | The alert overlay gallery. |

## Errors

An error answer is `{"error": {"code": "<code>", "message": "<text>"}}` with an HTTP status.

| Status | Code | Meaning |
|---|---|---|
| 400 | `invalid_request` | A field is missing, unknown, or has the wrong type. |
| 400 | `spotify_authorization_denied`, `spotify_authorization_failed` | Spotify did not complete the login. |
| 401 | `unauthorized` | The request has no credential. |
| 403 | `forbidden` | The credential is not valid for this resource. |
| 404 | `not_found` | The resource or the route does not exist. |
| 405 | `method_not_allowed` | The route exists, but not for this method. |
| 409 | `firmware_unavailable`, `firmware_incompatible`, `firmware_quarantined` | The firmware request cannot be done. |
| 409 | `deploy_refused` | The worker release has no folder, is marked bad, or another deploy of that worker runs. |
| 415 | `unsupported_media_type` | The body is not JSON. |
| 503 | `spotify_unavailable`, `catalog_unavailable`, `workers_unavailable` | The server has no such service configured. |
| 503 | `stock_search_unavailable` | The stock symbol source did not answer. |

## Device stream

`WS /stream` sends JSON text messages. The device sends no messages. A device message ends the stream.

| Type | Content |
|---|---|
| `snapshot` | The full data in `payload`. `seq` and `base_seq` are equal. |
| `delta` | The changed top-level sections in `changes`, and the removed sections in `removed`. `seq` is `base_seq + 1`. |
| `ready` | The device already has the current data. |

Each message has `stream_id`, `seq`, `base_seq`, and `server_time`.
To resume, connect with `?stream_id=<id>&after_seq=<n>`. The server sends the missed deltas, or a snapshot when it no longer holds them.
If a device cannot keep up, the server sends one snapshot in place of its queued deltas.

| Close code | Meaning |
|---|---|
| `1002` | The request did not offer the subprotocol `ticker`. |
| `1008` | The path, the resume query, or a device message is not valid. |
| `4401` | The request has no device token. |
| `4403` | The device token is not valid, or it stopped being valid during the stream. |

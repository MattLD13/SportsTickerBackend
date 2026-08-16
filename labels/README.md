# Ticker identity label template

The SVG template stays independent of label stock, adhesive, finish, and printer settings. Replace each `{{FIELD}}` token before printing.

Fields:

- `{{MODEL}}` identifies the hardware model.
- `{{REVISION}}` identifies the shipped software or hardware revision.
- `{{TICKER_ID}}` identifies the backend device record.
- `{{SERIAL}}` identifies the physical unit.
- `{{PAIR_CODE}}` holds a short-lived code and must not become a permanent secret.
- `{{QR_PAYLOAD}}` identifies the encoded payload reserved for a future QR generator.
- `{{SETUP_URL}}` identifies the local setup address.

Do not print the Wi-Fi password on a permanent label. Select the stock dimensions later, then preserve the 2:1 aspect ratio or update the SVG view box.

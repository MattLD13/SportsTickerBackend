# Mini HTTPS trust

`backend.pem` contains Mozilla roots for the backend edge certificate authorities.
The adjacent JSON records the source version, selected organizations, and checksums.
The generator selects Google Trust Services, Let's Encrypt, SSL.com, and Sectigo roots.
Every Mini HTTPS client verifies the server name and certificate chain with the same store.
Standard PEM validation accepts trusted roots within cross-signed server chains.
The SDK compressed bundle fails this check for the current backend chain.

To refresh the store, install a reviewed Certifi version and run:

```powershell
python tools/mini/generate_mini_trust.py
```

Review the metadata, build the firmware, and check HTTPS on the physical Mini before release.
The firmware build embeds the committed store without downloading trust data.

Sources: [Certifi](https://github.com/certifi/python-certifi) and
[backend edge certificate authorities](https://developers.cloudflare.com/ssl/reference/certificate-authorities/).
Mozilla certificate data uses the [MPL 2.0 license](https://www.mozilla.org/en-US/MPL/2.0/).

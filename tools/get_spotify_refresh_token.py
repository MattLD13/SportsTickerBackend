"""One-shot helper: authorize Spotify and print a refresh token for the VPS.

Usage (on your PC, with a browser):
  set SPOTIFY_CLIENT_ID=...
  set SPOTIFY_CLIENT_SECRET=...
  python tools/get_spotify_refresh_token.py

Or put those in a local .env first. Then paste the printed refresh token into
the GitHub Actions secret SPOTIFY_REFRESH_TOKEN and redeploy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    print("Install spotipy first: pip install spotipy")
    sys.exit(1)

SCOPES = "user-read-playback-state user-read-currently-playing"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
CACHE_PATH = ROOT / ".spotify_token"


def main() -> int:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")

    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("SPOTIFY_REDIRECT_URI") or REDIRECT_URI).strip()

    if not client_id or not client_secret:
        print("Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET.")
        print("Set them in the environment or a local .env, then rerun.")
        return 1

    print("Opening browser for Spotify login…")
    print(f"Redirect URI must match the dashboard entry: {redirect_uri}")

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPES,
        open_browser=True,
        cache_path=str(CACHE_PATH),
    )
    token = auth.get_access_token(as_dict=True, check_cache=False)
    refresh = (token or {}).get("refresh_token") or ""
    if not refresh:
        print("No refresh_token returned. Revoke the app under Spotify account")
        print("privacy settings and try again, or confirm the redirect URI.")
        return 1

    print()
    print("SPOTIFY_REFRESH_TOKEN=")
    print(refresh)
    print()
    print("Next:")
    print("  1. GitHub → repo Settings → Secrets → Actions")
    print("  2. Update secret SPOTIFY_REFRESH_TOKEN with the value above")
    print("  3. Redeploy / restart the ticker backend")
    print(f"Local cache also written to {CACHE_PATH} (do not commit it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

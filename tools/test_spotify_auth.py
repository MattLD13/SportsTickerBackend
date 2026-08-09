"""Paste your Spotify credentials below, start a song, then run:

    python tools/test_spotify_auth.py
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

# === PASTE HERE ===
CLIENT_ID = "PASTE_CLIENT_ID_HERE"
CLIENT_SECRET = "PASTE_CLIENT_SECRET_HERE"
REFRESH_TOKEN = "PASTE_REFRESH_TOKEN_HERE"
# ==================

BACKEND_URL = "https://ticker.mattdicks.org"


def refresh_access_token() -> dict:
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
        }
    ).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def currently_playing(access_token: str) -> dict | None:
    req = urllib.request.Request(
        "https://api.spotify.com/v1/me/player/currently-playing",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        if resp.status == 204 or not raw:
            return None
        return json.loads(raw.decode())


def backend_now() -> dict:
    req = urllib.request.Request(
        BACKEND_URL.rstrip("/") + "/api/spotify/now",
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    if "PASTE_" in CLIENT_ID or "PASTE_" in CLIENT_SECRET or "PASTE_" in REFRESH_TOKEN:
        print("Paste your real CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN into this file first.")
        return 1

    print("1) Refreshing access token…")
    try:
        token = refresh_access_token()
    except urllib.error.HTTPError as e:
        print(f"   FAIL HTTP {e.code}: {e.read().decode(errors='replace')}")
        print("   → Bad refresh token, or client id/secret don't match the app that issued it.")
        return 1

    access = token.get("access_token") or ""
    if not access:
        print("   FAIL no access_token:", token)
        return 1
    print("   OK access token received")
    if token.get("refresh_token"):
        print("   NOTE Spotify returned a NEW refresh_token — update the GitHub secret to that value.")

    print("2) Currently playing…")
    try:
        now = currently_playing(access)
    except urllib.error.HTTPError as e:
        print(f"   FAIL HTTP {e.code}: {e.read().decode(errors='replace')}")
        return 1

    if not now:
        print("   Auth OK, but nothing playing.")
        print("   Play a track on the same Spotify account you authorized, then rerun.")
    else:
        item = now.get("item") or {}
        artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
        print(
            f"   OK playing={now.get('is_playing')}  "
            f"track={item.get('name')!r}  artist={artists!r}"
        )

    print(f"3) Backend {BACKEND_URL}/api/spotify/now …")
    try:
        data = backend_now()
    except Exception as e:
        print(f"   FAIL backend: {e}")
        return 1

    print(json.dumps(data, indent=2))
    if data.get("name") == "Waiting for Music...":
        print("   → Backend still idle. Redeploy/restart so the VPS picks up the new secret.")
        return 2
    if data.get("is_playing"):
        print("   OK backend sees live playback")
    else:
        print("   Backend has data but is_playing=false (paused/idle)")

    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

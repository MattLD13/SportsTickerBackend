import os
import threading
import time

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    spotipy = None
    SpotifyOAuth = None

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from .test_mode import TestMode

SPOTIFY_SCOPES = "user-read-playback-state user-read-currently-playing"
SPOTIFY_CACHE_PATH = ".spotify_token"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"


class SpotifyFetcher(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self._lock = threading.Lock()

        self.client_id = os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        self.refresh_token = (os.getenv('SPOTIFY_REFRESH_TOKEN') or '').strip()

        # --- INTERNAL CACHE ---
        self.cached_current_id = None
        self.cached_current_cover = ""
        self.cached_queue_covers = []

        # --- STATE ---
        self.state = {
            "is_playing": False,
            "name": "Waiting for Music...",
            "artist": "",
            "cover": "",
            "last_cover": "",
            "next_covers": [],
            "duration": 0,
            "progress": 0,
            "last_fetch_ts": time.time()
        }

    def get_cached_state(self):
        with self._lock:
            return self.state.copy()

    def _build_auth_manager(self):
        return SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI', SPOTIFY_REDIRECT_URI),
            scope=SPOTIFY_SCOPES,
            open_browser=False,
            cache_path=os.getenv('SPOTIFY_CACHE_PATH', SPOTIFY_CACHE_PATH),
        )

    def _seed_token_cache(self, auth_manager):
        """Authorize headlessly from SPOTIFY_REFRESH_TOKEN (deploy secret).

        SpotifyOAuth alone expects an interactive browser login or a pre-built
        cache file. The VPS only has the refresh token in .env, so seed/refresh
        the cache from that on every startup.
        """
        if not self.refresh_token:
            cached = auth_manager.cache_handler.get_cached_token()
            if cached and cached.get('refresh_token'):
                return cached
            raise RuntimeError(
                "No SPOTIFY_REFRESH_TOKEN and no usable .spotify_token cache"
            )

        token_info = auth_manager.refresh_access_token(self.refresh_token)
        if not token_info.get('refresh_token'):
            # Spotify often omits refresh_token on refresh; keep the env one.
            token_info['refresh_token'] = self.refresh_token
            auth_manager.cache_handler.save_token_to_cache(token_info)
        return token_info

    def _make_client(self):
        auth_manager = self._build_auth_manager()
        self._seed_token_cache(auth_manager)
        return spotipy.Spotify(auth_manager=auth_manager)

    def run_simulation(self):
        """Runs a fake loop when no API keys are present or test_spotify is enabled."""
        print("⚠️ Spotify: no API keys or test mode active — starting MUSIC SIMULATION.")
        idx = 0
        while True:
            playlist = TestMode.get_fake_playlist()
            song = playlist[idx]

            next_1 = playlist[(idx + 1) % len(playlist)]
            next_2 = playlist[(idx + 2) % len(playlist)]

            start_time = time.time()

            with self._lock:
                self.state.update({
                    "is_playing": True,
                    "name": song['name'],
                    "artist": song['artist'],
                    "cover": song['cover'],
                    "last_cover": playlist[(idx - 1) % len(playlist)]['cover'],
                    "next_covers": [next_1['cover'], next_2['cover']],
                    "duration": song['duration'],
                    "progress": 0,
                    "last_fetch_ts": start_time
                })

            # Simulate playback: update progress every second for 20s, then advance
            for _ in range(20):
                time.sleep(1)
                with self._lock:
                    self.state['progress'] = time.time() - start_time
                    self.state['last_fetch_ts'] = time.time()

            idx = (idx + 1) % len(playlist)

    def run(self):
        # Run simulation if keys are missing OR test_spotify is explicitly enabled
        if (
            not self.client_id
            or not self.client_secret
            or spotipy is None
            or SpotifyOAuth is None
            or TestMode.is_enabled('spotify')
        ):
            self.run_simulation()
            return

        print("✅ Spotify Adaptive Polling Started")

        sp = None
        while not sp:
            try:
                sp = self._make_client()
                print("✅ Spotify authorized via refresh token/cache")
            except Exception as e:
                print(f"Spotify Init Failed (Retrying in 5s): {e}")
                time.sleep(5)

        current_delay = 1.0

        while True:
            try:
                current = None
                fetch_success = False

                try:
                    current = sp.current_user_playing_track()
                    fetch_success = True
                except Exception as e:
                    # STAGE 3: Error/Long Polling (>5s)
                    print(f"Spotify API Error: {e}")
                    current_delay = 5.0
                    # Re-seed auth if the access/refresh token went bad
                    try:
                        sp = self._make_client()
                    except Exception as auth_err:
                        print(f"Spotify re-auth failed: {auth_err}")

                if fetch_success:
                    if current and current.get('item'):
                        item = current['item']
                        is_playing = current.get('is_playing', False)
                        progress_ms = current.get('progress_ms', 0)

                        current_id = item.get('id')
                        current_cover = item['album']['images'][0]['url'] if item.get('album', {}).get('images') else ""

                        # Only fetch heavy queue data if the song changed
                        if self.cached_current_id != current_id:
                            self.state['last_cover'] = self.cached_current_cover
                            try:
                                queue_data = sp.queue()
                                new_queue = []
                                if queue_data and 'queue' in queue_data:
                                    for q_track in queue_data['queue'][:3]:
                                        if q_track.get('album') and q_track['album'].get('images'):
                                            new_queue.append(q_track['album']['images'][0]['url'])
                                        else:
                                            new_queue.append("")
                                self.cached_queue_covers = new_queue
                            except Exception:
                                pass  # Queue fetch failures shouldn't crash the loop

                        self.cached_current_id = current_id
                        self.cached_current_cover = current_cover

                        with self._lock:
                            self.state.update({
                                "is_playing": is_playing,
                                "name": item.get('name', 'Unknown'),
                                "artist": ", ".join(a['name'] for a in item.get('artists', [])),
                                "cover": current_cover,
                                "next_covers": self.cached_queue_covers,
                                "duration": item.get('duration_ms', 0) / 1000.0,
                                "progress": progress_ms / 1000.0,
                                "last_fetch_ts": time.time()
                            })

                        # STAGE 1 vs STAGE 2
                        # Quick Polling (0.6s) if playing, Medium (1.5s) if paused
                        current_delay = 0.6 if is_playing else 1.5

                    else:
                        # No active playback (204 / empty item)
                        with self._lock:
                            self.state['is_playing'] = False
                        current_delay = 3.0

            except Exception as e:
                print(f"Spotify Critical Loop Error: {e}")
                current_delay = 10.0  # Long backoff for critical failures

            time.sleep(current_delay)

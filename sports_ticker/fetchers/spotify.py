try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    spotipy = None
    SpotifyOAuth = None

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from .test_mode import TestMode

class SpotifyFetcher(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self._lock = threading.Lock()
        
        self.client_id = os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

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
        if not self.client_id or not self.client_secret or spotipy is None or SpotifyOAuth is None or TestMode.is_enabled('spotify'):
            self.run_simulation()
            return

        print("✅ Spotify Adaptive Polling Started")

        sp = None
        while not sp:
            try:
                auth_manager = SpotifyOAuth(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    redirect_uri="http://127.0.0.1:8888/callback",
                    scope="user-read-playback-state user-read-currently-playing",
                    open_browser=False,
                    cache_path=".spotify_token"
                )
                sp = spotipy.Spotify(auth_manager=auth_manager)
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

                if fetch_success:
                    if current and current.get('item'):
                        item = current['item']
                        is_playing = current.get('is_playing', False)
                        progress_ms = current.get('progress_ms', 0)

                        current_id = item.get('id')
                        current_cover = item['album']['images'][0]['url'] if item.get('album',{}).get('images') else ""

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
                            except: pass # Queue fetch failures shouldn't crash the loop

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

                    elif current is None:
                        # STAGE 2: No Content / Idle (3s)
                        with self._lock:
                            self.state['is_playing'] = False
                        current_delay = 3.0

            except Exception as e:
                print(f"Spotify Critical Loop Error: {e}")
                current_delay = 10.0 # Long backoff for critical failures

            time.sleep(current_delay)

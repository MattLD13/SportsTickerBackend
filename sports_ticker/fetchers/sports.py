"""Composed sports fetcher."""

import concurrent.futures

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .weather import WeatherFetcher
from .stocks import StockFetcher
from .sports_general import SportsGeneralMixin
from .sports_nhl import SportsNhlMixin
from .sports_soccer import SportsSoccerMixin
from .sports_espn import SportsEspnMixin
from .sports_golf import SportsGolfMixin
from .sports_mlb import SportsMlbMixin
from .sports_modes import SportsModesMixin
from .sports_indycar import SportsIndycarMixin
from .sports_f1 import SportsF1Mixin
from .sports_nascar import SportsNascarMixin


class SportsFetcher(
    SportsModesMixin,
    SportsMlbMixin,
    SportsGolfMixin,
    SportsEspnMixin,
    SportsSoccerMixin,
    SportsNhlMixin,
    SportsGeneralMixin,
    SportsIndycarMixin,
    SportsF1Mixin,
    SportsNascarMixin,
):
    def __init__(self, initial_city, initial_lat, initial_lon):
        self.weather = WeatherFetcher(initial_lat=initial_lat, initial_lon=initial_lon, city=initial_city)
        self.stocks = StockFetcher()
        self.possession_cache = {}
        self.football_situation_cache = {}  # game id -> last real down & distance
        self.base_url = 'http://site.api.espn.com/apis/site/v2/sports/'
        
        # CHANGE 1: Reduce Pool Size to 15 (Save RAM)
        self.session = build_pooled_session(pool_size=15)
        
        # CHANGE 2: Use Configured Thread Count (10)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_THREAD_COUNT)
        
        # CHANGE 3: Add New Caches for Smart Sleep
        self.history_buffer = [] 
        self.final_game_cache = {}      # Stores finished games so we don't re-fetch
        self.league_next_update = {}    # Stores "Wake Up" time for sleeping leagues
        self.league_last_data = {}      # Stores last data for sleeping leagues
        
        self.consecutive_empty_fetches = 0
        self._mlb_player_cache = {}   # playerId (int/str) → last name string
        self._mlb_summary_cache = {}  # gameId -> {'ts': float, 'data': dict}
        self._mlb_gamepk_cache = {}   # espn_gid -> mlb gamePk (or None on miss)
        self._mlb_challenge_cache = {}  # gamePk -> {'ts': float, 'home': int|None, 'away': int|None}
        # abbr-keyed index rebuilt in fetch_all_teams — O(1) team lookups
        self._teams_abbr_index: dict = {}  # league -> {abbr -> team_entry}
        # Per-mode content buffers: mode_name → list[game_obj]
        # Sports/live/my_teams share the same raw buffer; filtering happens in /data.
        self._mode_buffers: dict = {}
        self._mode_buffer_lock = threading.Lock()
        # Prevent overlapping expensive refresh passes from workers/routes.
        self._update_lock = threading.Lock()
        self._update_pending = threading.Event()
        # Golf API cache to avoid re-fetching every trigger burst.
        self._golf_cache = {'ts': 0.0, 'game': None}
        self._golf_cache_ttl = 60.0
        # When the sports slate was last fetched. A refresh rebuilds every mode
        # in use, so any worker asking for one re-ran the sports fetch — and the
        # music worker asks once a second. That drove a dozen upstream endpoints
        # at five times the intended rate until the host was blocked outright.
        self._last_sports_build = 0.0
        
        self.leagues = { 
            item['id']: item['fetch'] 
            for item in LEAGUE_OPTIONS 
            if item['type'] == 'sport' and 'fetch' in item 
        }

    def sports_refresh_interval(self) -> float:
        """Use the short poll interval only while a game is live."""
        with self._mode_buffer_lock:
            games = self._mode_buffers.get('sports', ())
        for game in games:
            if str(game.get('state', '')).lower() in {'in', 'half', 'crit'}:
                return LIVE_SPORTS_UPDATE_INTERVAL
        return SPORTS_UPDATE_INTERVAL


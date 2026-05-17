import math

from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

_SENTINEL = object()

class TestMode:
    """
    Centralized simulation / debug mode manager.

    In production this class is completely inert (all flags False by default).

    Usage examples:
        TestMode.configure(enabled=True)              # turn on all subsystems
        TestMode.configure(stocks=True)               # stocks-only test
        TestMode.configure(enabled=False)             # turn everything off
        TestMode.is_enabled('spotify')                # → bool
        TestMode.get_custom_date()                    # → 'YYYYMMDD' or None
        TestMode.get_fake_playlist()                  # → list of song dicts
        TestMode.get_fake_stock_price('AAPL')         # → {base, change, pct}
        TestMode.status()                             # → dict snapshot for /api/debug
    """

    _enabled: bool = False
    _subsystems: dict = {
        'spotify':     False,   # simulate Spotify playback
        'stocks':      False,   # simulate stock prices
        'sports_date': False,   # override sports date with custom_date
        'flights':     False,   # verbose flight debug logging
    }
    _custom_date: str | None = None

    # Simulation data lives here — not scattered in individual class constructors
    _FAKE_PLAYLIST = [
        {
            "name": "Simulated Song", "artist": "The Test Band",
            "cover": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/768px-Google_%22G%22_logo.svg.png",
            "duration": 180.0
        },
        {
            "name": "Coding All Night", "artist": "Dev Team",
            "cover": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/Unofficial_JavaScript_logo_2.svg/1024px-Unofficial_JavaScript_logo_2.svg.png",
            "duration": 240.0
        },
        {
            "name": "Offline Mode", "artist": "No Wifi",
            "cover": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/Visual_Editor_-_Icon_-_No-connection.svg/1024px-Visual_Editor_-_Icon_-_No-connection.svg.png",
            "duration": 120.0
        },
    ]

    @classmethod
    def configure(cls, *, enabled=None, custom_date=_SENTINEL, **subsystems):
        """
        Update test mode settings.
        - enabled=True  → flip all subsystems on at once
        - enabled=False → turn all off
        - Individual kwargs (spotify=True, stocks=False) control per-subsystem
        - custom_date='YYYY-MM-DD' sets the sports date override string
        """
        if custom_date is not _SENTINEL:
            cls._custom_date = custom_date

        if enabled is True:
            cls._enabled = True
            for k in cls._subsystems:
                cls._subsystems[k] = True
        elif enabled is False:
            cls._enabled = False
            for k in cls._subsystems:
                cls._subsystems[k] = False

        for k, v in subsystems.items():
            if k in cls._subsystems:
                cls._subsystems[k] = bool(v)
                if v:
                    cls._enabled = True  # any subsystem on → globally enabled

    @classmethod
    def is_enabled(cls, subsystem: str) -> bool:
        """Return True if the named subsystem simulation is active."""
        return cls._subsystems.get(subsystem, False)

    @classmethod
    def get_custom_date(cls) -> str | None:
        """Return the date override as a YYYYMMDD string, or None if not active."""
        if cls._custom_date and cls.is_enabled('sports_date'):
            return cls._custom_date.replace('-', '')
        return None

    @classmethod
    def get_fake_playlist(cls):
        """Return the simulated Spotify playlist."""
        return cls._FAKE_PLAYLIST

    @classmethod
    def get_fake_stock_price(cls, symbol: str) -> dict:
        """
        Return deterministic, slowly-fluctuating fake price data for a symbol.
        Logic originally lived in StockFetcher._fetch_single_stock.
        """
        base_price = sum(ord(c) for c in symbol) % 200 + 50
        variation = (time.time() % 600) / 100.0
        current_price = base_price + math.sin(variation + len(symbol)) * 5
        change = math.sin(variation * 2) * 2.5
        pct = (change / base_price) * 100
        return {'base': current_price, 'change': change, 'pct': pct}

    @classmethod
    def status(cls) -> dict:
        """Snapshot of current test mode state, exposed by /api/debug GET."""
        return {
            'enabled': cls._enabled,
            'subsystems': dict(cls._subsystems),
            'custom_date': cls._custom_date}

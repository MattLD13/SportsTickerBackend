"""Build the standard rewrite rendering services."""

from PIL import Image

from .assets import LogoAssetView
from .app.frame_builder import FrameBuilder
from .app.viewport import CardViewport
from .ui.cards.clock import ClockCard
from .ui.news_banner import NewsBanner
from .ui.score_alert import ScoreAlert
from .ui.cards.flight import FlightCard
from .ui.cards.golf import GolfCard
from .ui.cards.music import MusicCard
from .ui.cards.racing import RacingCard
from .ui.sports import SportsCard
from .ui.cards.stock import StockCard
from .ui.screens import Screens
from .ui.cards.weather import WeatherCard
from .ui import CardCatalog, FrameGeometry, load_default_font_set


class CachedLogoView:
    """Adapt the shared asset view for renderers that need logos."""

    def __init__(self, assets: object) -> None:
        self._assets = assets

    def get(self, value: object, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared logo without any I/O."""
        url = str(value or "").strip()
        image = getattr(self._assets, "image", None)
        return image(url, "logo", size) if url and callable(image) else None


def create_default_content_catalog(assets: object) -> CardCatalog:
    """Create the renderer catalog for every enabled ticker content family."""
    fonts = load_default_font_set()
    logos = CachedLogoView(assets)
    sports_logos = LogoAssetView(assets)
    catalog = CardCatalog()
    sports = SportsCard(fonts, sports_logos)
    catalog.register("clock", ClockCard(fonts))
    catalog.register("scoreboard", sports)
    catalog.register("sports", sports)
    catalog.register("racing", RacingCard(fonts, assets))
    catalog.register("golf", GolfCard(fonts))
    catalog.register("weather", WeatherCard(fonts))
    catalog.register("music", MusicCard(fonts, logos))
    catalog.register("flight", FlightCard(fonts, logos))
    catalog.register("stock", StockCard(fonts, logos))
    catalog.register("empty", Screens(fonts))
    return catalog


def create_default_frame_builder(
    assets: object,
    *,
    card_cpu: int | None = None,
    geometry: FrameGeometry | None = None,
) -> tuple[FrameBuilder, CardViewport]:
    """Create the complete frame builder and its card viewport."""
    fonts = load_default_font_set()
    logos = CachedLogoView(assets)
    catalog = create_default_content_catalog(assets)
    asset_directory = getattr(assets, "directory", None)
    from .platform.panes import PreparedPaneCache
    viewport = CardViewport(
        catalog,
        use_process=asset_directory is not None,
        asset_directory=asset_directory,
        worker_cpu=card_cpu,
        pane_cache=PreparedPaneCache(assets) if asset_directory is not None else None,
    )
    return FrameBuilder(
        catalog,
        Screens(fonts),
        ScoreAlert(fonts, logos),
        NewsBanner(),
        viewport,
        geometry=geometry,
    ), viewport

"""Build the standard rewrite rendering services."""

from PIL import Image

from .assets import LogoAssetView
from .app.frame_builder import FrameBuilder
from .app.viewport import CardViewport
from .ui.cards.clock import ClockCard
from .features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from .ui.cards.flight import FlightCard
from .features.golf import GolfRenderer
from .ui.cards.music import MusicCard
from .features.racing import RacingRenderer
from .features.sports import SportsRenderer
from .features.utility import UtilityRenderer
from .features.weather import WeatherRenderer
from .ui import ContentRendererCatalog, ContentScene, FrameGeometry, RenderedContent, load_default_font_set
from .ui.text import load_display_font, load_monospace_font


class CachedLogoView:
    """Adapt the shared asset view for renderers that need logos."""

    def __init__(self, assets: object) -> None:
        self._assets = assets

    def get(self, value: object, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared logo without any I/O."""
        url = str(value or "").strip()
        image = getattr(self._assets, "image", None)
        return image(url, "logo", size) if url and callable(image) else None


def create_default_content_catalog(assets: object) -> ContentRendererCatalog:
    """Create the renderer catalog for every enabled ticker content family."""
    fonts = load_default_font_set()
    logos = CachedLogoView(assets)
    sports_logos = LogoAssetView(assets)
    catalog = ContentRendererCatalog()
    sports = SportsRenderer(fonts, sports_logos)
    utility = UtilityRenderer(fonts, logos)
    catalog.register("clock", ClockCard(fonts))
    catalog.register("scoreboard", sports)
    catalog.register("sports", sports)
    catalog.register("racing", RacingRenderer(fonts, assets))
    catalog.register("golf", GolfRenderer(fonts))
    catalog.register("weather", WeatherRenderer(fonts))
    catalog.register("music", MusicCard(fonts, logos))
    catalog.register("flight", FlightCard(fonts, logos))
    catalog.register("stock", utility)
    catalog.register("leaderboard", utility)
    catalog.register("empty", utility)
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
        UtilityRenderer(fonts, logos),
        ScoreAlertRenderer(fonts, logos),
        NewsBannerRenderer(fonts),
        viewport,
        geometry=geometry,
    ), viewport

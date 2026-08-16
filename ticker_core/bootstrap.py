"""Build the standard rewrite rendering services."""

from collections.abc import Mapping
from PIL import Image

from .app.frame_builder import FrameBuilder
from .app.viewport import CardViewport
from .features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from .features.clock import ClockRenderer
from .features.flight import FlightRenderer
from .features.golf import GolfRenderer
from .features.music import MusicRenderer
from .features.racing import RacingRenderer
from .features.sports import SportsRenderer
from .features.utility import UtilityRenderer
from .features.weather import WeatherRenderer
from .rendering import ContentRendererCatalog, ContentScene, RenderedContent, load_default_font_set
from .rendering.fonts import load_display_font, load_monospace_font
from .registry import SceneRegistry


class CachedLogoView:
    """Adapt the shared asset view for renderers that need logos."""

    def __init__(self, assets: object) -> None:
        self._assets = assets

    def get(self, value: object, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared logo without any I/O."""
        url = str(value or "").strip()
        image = getattr(self._assets, "image", None)
        return image(url, "logo", size) if url and callable(image) else None


class _ClockContentRenderer:
    """Adapt the standalone clock renderer to the content catalog."""

    def __init__(self, renderer: ClockRenderer) -> None:
        self._renderer = renderer

    def render(self, context, scene: ContentScene) -> RenderedContent:
        """Render the current time as a static full-panel scene."""
        del scene
        from .features.clock import ClockScene

        return RenderedContent(self._renderer.render(context, ClockScene()))


def create_default_content_catalog(assets: object) -> ContentRendererCatalog:
    """Create the renderer catalog for every enabled ticker content family."""
    fonts = load_default_font_set()
    logos = CachedLogoView(assets)
    catalog = ContentRendererCatalog()
    sports = SportsRenderer(fonts, logos)
    utility = UtilityRenderer(fonts, logos)
    catalog.register("clock", _ClockContentRenderer(ClockRenderer(fonts.tiny, fonts.clock)))
    catalog.register("scoreboard", sports)
    catalog.register("sports", sports)
    catalog.register("racing", RacingRenderer(fonts, assets))
    catalog.register("golf", GolfRenderer(fonts))
    catalog.register("weather", WeatherRenderer(fonts))
    catalog.register("music", MusicRenderer(fonts, logos))
    catalog.register("flight", FlightRenderer(fonts, logos))
    catalog.register("stock", utility)
    catalog.register("leaderboard", utility)
    catalog.register("empty", utility)
    return catalog


def create_default_frame_builder(assets: object, *, card_cpu: int | None = None) -> tuple[FrameBuilder, CardViewport]:
    """Create the complete frame builder and its card viewport."""
    fonts = load_default_font_set()
    logos = CachedLogoView(assets)
    catalog = create_default_content_catalog(assets)
    asset_directory = getattr(assets, "directory", None)
    viewport = CardViewport(
        catalog,
        use_process=asset_directory is not None,
        asset_directory=asset_directory,
        worker_cpu=card_cpu,
    )
    return FrameBuilder(
        catalog,
        UtilityRenderer(fonts, logos),
        ScoreAlertRenderer(fonts, logos),
        NewsBannerRenderer(fonts),
        viewport,
    ), viewport


def create_default_scene_registry() -> SceneRegistry[Image.Image]:
    """Create the registry for all enabled rewrite scenes."""
    registry = SceneRegistry()
    registry.register(
        "clock",
        ClockRenderer(
            tiny_font=load_monospace_font(9),
            clock_font=load_display_font(28, bold=True),
        ),
    )
    return registry

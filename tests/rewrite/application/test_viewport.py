"""Exercise scrolling cards without precomposing a long strip image."""

from datetime import datetime, timezone
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from threading import Event
from time import monotonic, sleep

from PIL import Image
import pytest

from ticker_core.app.viewport import CardViewport
from ticker_core.context import RenderContext
from ticker_core.rendering import RenderedContent
from ticker_core.runtime import Content

pytestmark = pytest.mark.critical


class Catalog:
    """Render one colored card and record renderer work."""

    def __init__(self) -> None:
        self.calls = 0
        self.scenes = []

    def render(self, context, scene):
        del context
        self.calls += 1
        self.scenes.append(dict(scene.item))
        color = (255, 0, 0) if scene.item.get("down") == "1st" else (0, 255, 0)
        return RenderedContent(Image.new("RGB", (96, 32), color))


def test_viewport_renders_only_changed_card() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    old = (
        Content("game", "scoreboard", "nfl", {"down": "1st"}),
        Content("other", "scoreboard", "nfl", {"down": "1st"}),
    )
    new = (
        Content("game", "scoreboard", "nfl", {"down": "2nd"}),
        old[1],
    )
    try:
        viewport.update(old, context, "sports")
        _drain(viewport, catalog, 2)
        viewport.update(new, context, "sports")
        _drain(viewport, catalog, 3)

        assert catalog.calls == 3
        assert viewport.frame(0).getpixel((1, 1)) == (0, 255, 0)
    finally:
        viewport.close()


def test_viewport_reuses_inflight_render_for_equal_content_in_a_new_generation() -> None:
    class BlockingCatalog(Catalog):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def render(self, context, scene):
            self.calls += 1
            self.started.set()
            assert self.release.wait(1)
            color = (255, 0, 0) if scene.item.get("down") == "1st" else (0, 255, 0)
            return RenderedContent(Image.new("RGB", (96, 32), color))

    catalog = BlockingCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("game", "scoreboard", "nfl", {"down": "1st"}),), context, "sports")
        assert catalog.started.wait(1)
        viewport.update((Content("game", "scoreboard", "nfl", {"down": "1st"}),), context, "sports")
        catalog.release.set()
        _drain(viewport, catalog, 1)

        assert catalog.calls == 1
        assert viewport.status["committed_generation"] == 2
        assert viewport.frame(0).getpixel((1, 1)) == (255, 0, 0)
    finally:
        catalog.release.set()
        viewport.close()


def test_viewport_reuses_surfaces_for_equal_content_from_a_new_payload() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    items = (
        Content("game", "scoreboard", "nfl", {"down": "1st"}),
        Content("other", "scoreboard", "nfl", {"down": "2nd"}),
    )
    replacement = tuple(
        Content(item.id, item.type, item.sport, dict(item.data)) for item in items
    )
    try:
        viewport.update(items, context, "sports")
        _drain(viewport, catalog, 2)
        viewport.update(replacement, context, "sports")
        viewport.install_completed()

        assert catalog.calls == 2
        assert viewport.status["committed_generation"] == 2
        assert viewport.status["ready"] == 2
    finally:
        viewport.close()


def test_fifteen_live_games_rerender_only_the_changed_pane() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    games = tuple(
        Content(
            f"live-{index:02d}",
            "scoreboard",
            "nfl",
            {
                "state": "in",
                "away_score": str(index),
                "home_score": str(index + 3),
                "down": "1st",
            },
        )
        for index in range(15)
    )
    update = tuple(
        Content(
            game.id,
            game.type,
            game.sport,
            {**game.data, "away_score": "21", "down": "2nd"} if index == 7 else dict(game.data),
        )
        for index, game in enumerate(games)
    )
    try:
        viewport.update(games, context, "sports")
        _drain(viewport, catalog, 15)
        viewport.update(update, context, "sports")
        _drain(viewport, catalog, 16)

        assert catalog.calls == 16
        assert viewport.status["desired"] == 15
        assert viewport.status["ready"] == 15
        assert viewport.status["committed_generation"] == 2
        layout = viewport.layout
        assert layout is not None
        game_start = sum(segment.width for segment in layout.segments[:7])
        assert viewport.frame(game_start).getpixel((1, 1)) == (0, 255, 0)
    finally:
        viewport.close()


def test_clock_ticks_update_cached_pane_header_without_rerendering_card() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    first = Content("game", "scoreboard", "nfl", {
        "state": "in",
        "status": "Q1 1:00",
        "clock": {"direction": "down", "period_label": "Q1", "remaining_seconds": 60},
    })
    next_tick = Content("game", "scoreboard", "nfl", {
        "state": "in",
        "status": "Q1 0:59",
        "clock": {"direction": "down", "period_label": "Q1", "remaining_seconds": 59},
    })
    try:
        viewport.update((first,), context, "sports")
        _drain(viewport, catalog, 1)
        viewport.update((next_tick,), context, "sports")
        _drain(viewport, catalog, 1)
        first_frame = viewport.frame(0, clock_labels={"game": "Q1 1:00"})
        second_frame = viewport.frame(0, clock_labels={"game": "Q1 0:59"})

        assert catalog.calls == 1
        assert catalog.scenes[0]["status"] == "Q1"
        assert catalog.scenes[0]["clock_header_reserve"] == "Q1 88:88"
        assert "clock" not in catalog.scenes[0]
        assert first_frame.size == (384, 32)
        assert first_frame.tobytes() != second_frame.tobytes()
    finally:
        viewport.close()


def test_clock_header_stays_attached_to_pane_as_it_crosses_left_panel_edge() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    item = Content("game", "scoreboard", "nfl", {
        "state": "in",
        "status": "Q1 0:59",
        "clock": {"direction": "down", "period_label": "Q1", "remaining_seconds": 59},
    })
    try:
        viewport.update((item,), context, "sports")
        _drain(viewport, catalog, 1)
        base = viewport.frame(10)
        overlay = viewport.frame(10, clock_labels={"game": "Q1 0:58"})

        assert base.getpixel((30, 2)) != overlay.getpixel((30, 2))
        assert catalog.calls == 1
    finally:
        viewport.close()


def test_cached_pane_strip_matches_previous_composition_across_wraps() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    panes = tuple(
        Content(f"pane-{index}", "scoreboard", "nfl", {"down": "1st" if index % 2 == 0 else "2nd"})
        for index in range(3)
    )
    try:
        viewport.update(panes, context, "sports")
        _drain(viewport, catalog, len(panes))
        layout = viewport.layout
        assert layout is not None
        for offset in (0, 1, layout.width // 2, layout.width - 1, layout.width, layout.width + 17):
            assert viewport.frame(offset).tobytes() == _previous_pane_composition(viewport, offset).tobytes()
    finally:
        viewport.close()


def test_viewport_keeps_cold_start_unpublished_until_a_surface_is_ready() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        assert viewport.update((Content("game", "scoreboard", "nfl", {}),), context, "sports") is None
        assert viewport.layout is None
        _drain(viewport, catalog, 1)
        assert viewport.layout is not None
        assert viewport.status["committed_generation"] == 1
    finally:
        viewport.close()


def test_viewport_keeps_committed_surface_when_a_replacement_fails() -> None:
    class FailingCatalog(Catalog):
        def render(self, context, scene):
            if scene.item.get("fail"):
                self.calls += 1
                raise RuntimeError("broken card")
            return super().render(context, scene)

    catalog = FailingCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    old = Content("game", "scoreboard", "nfl", {"down": "1st"})
    failed = Content("game", "scoreboard", "nfl", {"down": "2nd", "fail": True})
    try:
        viewport.update((old,), context, "sports")
        _drain(viewport, catalog, 1)
        committed = viewport.layout
        viewport.update((failed,), context, "sports")
        _drain(viewport, catalog, 2)
        assert viewport.layout == committed
        assert viewport.status["failed"] == 1
    finally:
        viewport.close()


def test_viewport_omits_a_failed_new_card_and_keeps_old_layout_during_refresh() -> None:
    class FailingCatalog(Catalog):
        def render(self, context, scene):
            if scene.item.get("fail"):
                self.calls += 1
                raise RuntimeError("new card failed")
            return super().render(context, scene)

    catalog = FailingCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    old = Content("game", "scoreboard", "nfl", {"down": "1st"})
    failed_new = Content("new", "scoreboard", "nfl", {"fail": True})
    try:
        viewport.update((old,), context, "sports")
        _drain(viewport, catalog, 1)
        committed = viewport.layout
        assert viewport.update((old, failed_new), context, "sports") == committed
        assert viewport.layout == committed
        _drain(viewport, catalog, 2)
        assert viewport.layout == committed
        assert tuple(segment.item_id for segment in viewport.layout.segments) == ("game",)
        assert viewport.status["committed_generation"] == 2
    finally:
        viewport.close()


def test_stale_generation_failure_does_not_change_current_readiness() -> None:
    class ReverseCatalog(Catalog):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def render(self, context, scene):
            del context
            self.calls += 1
            if scene.item.get("phase") == "old":
                self.started.set()
                self.release.wait(1)
                raise RuntimeError("stale card failed")
            return RenderedContent(Image.new("RGB", (96, 32), (0, 255, 0)))

    catalog = ReverseCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("game", "scoreboard", "nfl", {"phase": "old"}),), context, "sports")
        assert catalog.started.wait(1)
        viewport.update((Content("game", "scoreboard", "nfl", {"phase": "new"}),), context, "sports")
        catalog.release.set()
        _drain(viewport, catalog, 2)
        assert viewport.status["failed"] == 0
        assert viewport.status["committed_generation"] == 2
        assert viewport.frame(0).getpixel((1, 1)) == (0, 255, 0)
    finally:
        catalog.release.set()
        viewport.close()


def test_asset_refresh_commits_successful_card_and_retains_failed_prior_card() -> None:
    class MixedCatalog(Catalog):
        def __init__(self) -> None:
            super().__init__()
            self.refresh = False
            self.fail_bad = False

        def render(self, context, scene):
            del context
            self.calls += 1
            if self.fail_bad and scene.item.get("name") == "bad":
                raise RuntimeError("logo still unavailable")
            if scene.item.get("name") == "good":
                color = (0, 255, 0) if self.refresh else (255, 0, 0)
            else:
                color = (0, 0, 255)
            return RenderedContent(Image.new("RGB", (96, 32), color))

    catalog = MixedCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    items = (
        Content("good", "scoreboard", "nfl", {"name": "good"}),
        Content("bad", "scoreboard", "nfl", {"name": "bad"}),
    )
    try:
        viewport.update(items, context, "sports")
        _drain(viewport, catalog, 2)
        catalog.refresh = True
        catalog.fail_bad = True
        previous_generation = viewport.status["committed_generation"]
        viewport.invalidate()
        assert viewport.status["staging_generation"] == previous_generation + 1
        _drain(viewport, catalog, 4)
        assert viewport.status["committed_generation"] == previous_generation + 1
        assert viewport.status["failed"] == 1
        assert viewport.frame(0).getpixel((1, 1)) == (0, 255, 0)
        assert viewport.frame(0).getpixel((98, 1)) == (0, 0, 255)
    finally:
        viewport.close()


def test_broken_worker_submission_is_recovered_without_stuck_queue() -> None:
    class BrokenSubmitter:
        def submit(self, function, argument):
            del function, argument
            raise BrokenProcessPool("worker unavailable")

        def shutdown(self, **kwargs):
            del kwargs

    catalog = Catalog()
    issues = []
    viewport = CardViewport(catalog, issue_handler=issues.append)
    recovered = ThreadPoolExecutor(max_workers=1)
    viewport._worker.shutdown(wait=True, cancel_futures=True)
    viewport._worker = BrokenSubmitter()
    viewport._restart_worker_locked = lambda: setattr(viewport, "_worker", recovered)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("game", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport, catalog, 1)
        assert viewport.layout is not None
        assert any(issue["error_type"] == "BrokenProcessPool" for issue in issues)
    finally:
        viewport.close()


def test_broken_worker_future_requeues_the_current_card_once() -> None:
    class BrokenFutureWorker:
        def __init__(self) -> None:
            self.used = False

        def submit(self, function, argument):
            del function, argument
            if self.used:
                raise AssertionError("the broken worker received a second request")
            self.used = True
            future = Future()
            future.set_exception(BrokenProcessPool("worker exited during render"))
            return future

        def shutdown(self, **kwargs):
            del kwargs

    catalog = Catalog()
    issues = []
    viewport = CardViewport(catalog, issue_handler=issues.append)
    recovered = ThreadPoolExecutor(max_workers=1)
    viewport._worker.shutdown(wait=True, cancel_futures=True)
    viewport._worker = BrokenFutureWorker()
    viewport._restart_worker_locked = lambda: setattr(viewport, "_worker", recovered)
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("game", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport, catalog, 1)
        assert viewport.layout is not None
        assert viewport.status["failed"] == 1
        assert any(issue["error_type"] == "BrokenProcessPool" for issue in issues)
    finally:
        viewport.close()


def _drain(viewport: CardViewport, catalog: Catalog, expected_calls: int) -> None:
    deadline = monotonic() + 1
    while (catalog.calls < expected_calls or viewport.layout is None) and monotonic() < deadline:
        viewport.install_completed()
        sleep(0.005)
    viewport.install_completed()
    assert catalog.calls == expected_calls


def _previous_pane_composition(viewport: CardViewport, offset: int) -> Image.Image:
    """Render with the previous per-pane loop as a pixel-equivalence oracle."""
    with viewport._lock:
        layout = viewport._layout
        surfaces = dict(viewport._surfaces)
        order = viewport._order
    image = Image.new("RGB", (384, 32), "black")
    if layout is None or not order:
        return image
    position = offset % layout.width
    start = 0
    index = 0
    for index, segment in enumerate(layout.segments):
        if start + segment.width > position:
            break
        start += segment.width
    x = start - position
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    while x < image.width:
        segment = layout.segments[index % len(layout.segments)]
        surface = surfaces.get(segment.item_id)
        draw.line((x, 0, x, image.height - 1), fill=(45, 45, 45))
        if surface is not None:
            image.paste(surface.image, (x + 1, 0), surface.image)
        x += segment.width
        index += 1
    return image

"""Exercise scrolling cards without precomposing a long strip image."""

from datetime import datetime, timezone
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from threading import Event
from time import monotonic, sleep

from PIL import Image
import pytest

from ticker_core.app.viewport import CardViewport
from ticker_core.app import viewport as viewport_module
from ticker_core.context import RenderContext
from ticker_core.ui import RenderedContent
from ticker_core.runtime import Content

pytestmark = pytest.mark.critical


def test_visible_update_requires_current_surface_and_changed_pixels_inside_the_window():
    class PixelCatalog:
        calls = 0

        def render(self, context, scene):
            self.calls += 1
            image = Image.new("RGB", (96, 32))
            image.putpixel((90, 16), (255, 0, 0) if scene.item["score"] == 1 else (0, 255, 0))
            return RenderedContent(image)

    catalog = PixelCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 25, tzinfo=timezone.utc))
    try:
        viewport.update((Content("game", "scoreboard", "nfl", {"score": 1}),), context, "sports")
        _drain(viewport, catalog, 1)
        assert viewport.visible_updates(0, ("game",), width=50) == {}
        assert viewport.visible_updates(60, ("game",), width=50)["game"]["changed_visible"]
        viewport.update((Content("game", "scoreboard", "nfl", {"score": 2}),), context, "sports")
        assert viewport.visible_updates(60, ("game",), width=50) == {}
        prior_pixels = viewport.status["patched_pixels"]
        _drain(viewport, catalog, 2)
        assert viewport.visible_updates(0, ("game",), width=50) == {}
        assert viewport.visible_updates(60, ("game",), width=50)["game"]["changed_visible"]
        assert viewport.frame(0).tobytes() == _previous_pane_composition(viewport, 0).tobytes()
        repeats = viewport._tiled_strip.width // viewport.layout.width
        assert viewport.status["patched_pixels"] - prior_pixels == repeats * (1 + 2 * 32)
    finally:
        viewport.close()


class Catalog:
    """Render one colored card and record renderer work."""

    def __init__(self) -> None:
        self.calls = 0

    def render(self, context, scene):
        del context
        self.calls += 1
        color = (255, 0, 0) if scene.item.get("down") == "1st" else (0, 255, 0)
        return RenderedContent(Image.new("RGB", (96, 32), color))


def test_visibility_uses_presented_geometry_and_wraps_at_the_rotation_seam():
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(f"game-{index}", "scoreboard", "nfl", {"down": "1st"}) for index in range(6))
    try:
        assert viewport.visible_ids(0) is None
        viewport.update(games, context, "sports")
        _settle(viewport)
        width = viewport.layout.width
        assert viewport.visible_ids(0, width=96) == frozenset({"game-0"})
        assert viewport.visible_ids(width - 20, width=50) == frozenset({"game-5", "game-0"})
        assert set(viewport.installed_times(("game-0", "missing"))) == {"game-0"}
    finally:
        viewport.close()


def test_scroll_rotation_keeps_150_panes_and_updates_the_last_game() -> None:
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    items = tuple(Content(f"game-{index}", "scoreboard", "nfl", {"down": "1st"}) for index in range(150))

    def finish():
        deadline = monotonic() + 5
        while viewport.status["pending"] and monotonic() < deadline:
            viewport.install_completed()
            sleep(0.001)
        assert viewport.status["pending"] == 0

    try:
        viewport.update(items, context, "sports")
        finish()
        layout = viewport.layout
        assert layout is not None
        assert tuple(segment.item_id for segment in layout.segments) == tuple(item.id for item in items)
        assert catalog.calls == 150
        tail = sum(segment.width for segment in layout.segments[:-1])
        assert viewport.frame(tail).getpixel((1, 1)) == (255, 0, 0)
        changed = items[:-1] + (Content("game-149", "scoreboard", "nfl", {"down": "2nd"}),)
        viewport.update(changed, context, "sports")
        finish()
        assert catalog.calls == 151
        assert len(viewport.layout.segments) == 150
        assert viewport.frame(tail).getpixel((1, 1)) == (0, 255, 0)
        assert viewport.frame(0).getpixel((1, 1)) == (255, 0, 0)
        assert viewport.frame(tail).tobytes() == _previous_pane_composition(viewport, tail).tobytes()
    finally:
        viewport.close()


def _settle(viewport):
    deadline = monotonic() + 5
    while viewport.status["pending"] and monotonic() < deadline:
        viewport.install_completed()
        sleep(0.001)
    assert viewport.status["pending"] == 0


def test_visible_update_publishes_before_blocked_offscreen_work_and_patches_in_place():
    class BlockingCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.blocked, self.release = Event(), Event()
            self.order = []

        def render(self, context, scene):
            if scene.item.get("down") == "2nd":
                self.order.append(scene.item["id"])
                if scene.item["id"] == "game-0":
                    self.blocked.set()
                    assert self.release.wait(5)
            return super().render(context, scene)

    catalog = BlockingCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(f"game-{index}", "scoreboard", "nfl", {"down": "1st"}) for index in range(150))
    try:
        viewport.update(games, context, "sports")
        _settle(viewport)
        offset = sum(segment.width for segment in viewport.layout.segments[:100])
        viewport.frame(offset)
        original_strip = viewport._tiled_strip
        original_revision = viewport.revision
        original_compositions = viewport.status["full_compositions"]
        updated = tuple(Content(game.id, game.type, game.sport, {"down": "2nd"}) if index in (0, 100) else game
                        for index, game in enumerate(games))
        viewport.update(updated, context, "sports")
        deadline = monotonic() + 2
        while not catalog.blocked.is_set() and monotonic() < deadline:
            viewport.install_completed()
            sleep(0.001)
        assert catalog.blocked.is_set()
        assert catalog.order == ["game-100", "game-0"]
        assert viewport.status["pending"] == 1
        assert viewport.frame(offset).getpixel((1, 1)) == (0, 255, 0)
        assert viewport.frame(0).getpixel((1, 1)) == (255, 0, 0)
        assert viewport._tiled_strip is original_strip
        assert viewport.revision > original_revision
        assert viewport.status["full_compositions"] == original_compositions
        assert viewport.status["region_patches"] == 1
        catalog.release.set()
        _settle(viewport)
        assert viewport.frame(0).getpixel((1, 1)) == (0, 255, 0)
        assert viewport.status["full_compositions"] == original_compositions
    finally:
        catalog.release.set()
        viewport.close()


def test_visible_burst_follows_inflight_offscreen_and_discards_its_stale_result():
    class BlockingCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.blocked, self.release = Event(), Event()
            self.order = []

        def render(self, context, scene):
            marker = scene.item.get("revision")
            if marker is not None:
                self.order.append((scene.item["id"], marker))
                if scene.item["id"] == "game-0" and marker == 1:
                    self.blocked.set()
                    assert self.release.wait(5)
            return super().render(context, scene)

    catalog = BlockingCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(f"game-{index}", "scoreboard", "nfl", {"down": "1st"}) for index in range(150))
    try:
        viewport.update(games, context, "sports")
        _settle(viewport)
        offset = sum(segment.width for segment in viewport.layout.segments[:100])
        viewport.frame(offset)
        old = (Content("game-0", "scoreboard", "nfl", {"down": "2nd", "revision": 1}),) + games[1:]
        viewport.update(old, context, "sports")
        assert catalog.blocked.wait(2)
        burst = tuple(Content(game.id, game.type, game.sport, {"down": "2nd", "revision": 2}) for game in games)
        viewport.update(burst, context, "sports")
        assert viewport.frame(offset).getpixel((1, 1)) == (255, 0, 0)
        catalog.release.set()
        deadline = monotonic() + 5
        while len(catalog.order) < 2 and monotonic() < deadline:
            viewport.install_completed()
            sleep(0.001)
        assert catalog.order[:2] == [("game-0", 1), ("game-100", 2)]
        assert viewport.frame(0).getpixel((1, 1)) == (255, 0, 0)
        _settle(viewport)
        assert viewport.frame(offset).getpixel((1, 1)) == (0, 255, 0)
        assert viewport.frame(0).getpixel((1, 1)) == (0, 255, 0)
        assert ("game-0", 1) in catalog.order and ("game-0", 2) in catalog.order
    finally:
        catalog.release.set()
        viewport.close()


def test_background_worker_starts_next_offscreen_card_before_the_next_frame():
    class RecordingCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.updated = []
            self.finished = Event()

        def render(self, context, scene):
            result = super().render(context, scene)
            if scene.item.get("down") == "2nd":
                self.updated.append(scene.item["id"])
                if len(self.updated) == 2:
                    self.finished.set()
            return result

    catalog = RecordingCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(str(index), "scoreboard", "nfl", {"down": "1st"}) for index in range(8))
    try:
        viewport.update(games, context, "sports")
        _settle(viewport)
        viewport.frame(0)
        changed = tuple(Content(item.id, item.type, item.sport, {"down": "2nd"}) if item.id in {"5", "6"} else item
                        for item in games)
        viewport.update(changed, context, "sports")
        assert catalog.finished.wait(2)
        assert catalog.updated == ["5", "6"]
        _settle(viewport)
        assert viewport.frame(5 * 97).getpixel((1, 1)) == (0, 255, 0)
    finally:
        viewport.close()


def test_pending_cards_follow_scroll_order_across_the_rotation_seam():
    class OrderedCatalog(Catalog):
        order = []

        def render(self, context, scene):
            if scene.item.get("down") == "2nd":
                self.order.append(scene.item["id"])
            return super().render(context, scene)

    catalog = OrderedCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(str(index), "scoreboard", "nfl", {"down": "1st"}) for index in range(6))
    try:
        viewport.update(games, context, "sports")
        _settle(viewport)
        viewport.frame(5 * 97 + 80)
        viewport.update(tuple(Content(item.id, item.type, item.sport, {"down": "2nd"}) for item in games), context, "sports")
        _settle(viewport)
        assert catalog.order == ["5", "0", "1", "2", "3", "4"]
    finally:
        viewport.close()


def test_cold_rotation_starts_after_one_screenful_without_waiting_for_the_last_card():
    class ColdCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.blocked, self.release = Event(), Event()

        def render(self, context, scene):
            if scene.item['id'] == '4':
                self.blocked.set()
                assert self.release.wait(5)
            return super().render(context, scene)

    catalog = ColdCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    try:
        viewport.update(tuple(Content(str(index), 'scoreboard', 'nfl', {}) for index in range(6)), context, 'sports')
        deadline = monotonic()+2
        while not catalog.blocked.is_set() and monotonic()<deadline:
            viewport.install_completed()
            sleep(0.001)
        assert catalog.blocked.is_set()
        assert viewport.status['pending'] == 2
        assert tuple(segment.item_id for segment in viewport.layout.segments) == ('0','1','2','3')
        assert viewport.frame(0).getbbox() is not None
        catalog.release.set()
        _settle(viewport)
        assert len(viewport.layout.segments) == 6
    finally:
        catalog.release.set()
        viewport.close()


def test_cold_progress_survives_an_equal_payload_before_the_first_screen_is_ready():
    class ColdCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.blocked, self.release = Event(), Event()

        def render(self, context, scene):
            if scene.item['id'] == '3':
                self.blocked.set()
                assert self.release.wait(5)
            return super().render(context, scene)

    catalog = ColdCatalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(str(index), 'scoreboard', 'nfl', {}) for index in range(8))
    try:
        viewport.update(games, context, 'sports')
        deadline = monotonic()+2
        while not catalog.blocked.is_set() and monotonic()<deadline:
            viewport.install_completed()
            sleep(0.001)
        assert catalog.blocked.is_set()
        assert viewport.layout is None
        assert viewport.status['ready'] == 3
        viewport.update(tuple(Content(item.id,item.type,item.sport,dict(item.data)) for item in games), context, 'sports')
        assert viewport.status['ready'] == 3
        catalog.release.set()
        _settle(viewport)
        assert catalog.calls == 8
        assert len(viewport.layout.segments) == 8
    finally:
        catalog.release.set()
        viewport.close()


def test_incremental_strip_matches_full_composition_for_alpha_and_changed_geometry():
    class AlphaCatalog:
        def render(self, context, scene):
            return RenderedContent(Image.new("RGBA", (scene.item["width"], 32), tuple(scene.item["color"])))

    viewport = CardViewport(AlphaCatalog())
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))

    def game(width, color, stage):
        return Content("one", "scoreboard", "nba", {"width": width, "color": color, "competition_stage": stage})

    try:
        viewport.update((game(60, (255, 0, 0, 128), 0),), context, "sports")
        _settle(viewport)
        strip = viewport._tiled_strip
        viewport.update((game(60, (0, 255, 0, 128), 2),), context, "sports")
        _settle(viewport)
        assert viewport._tiled_strip is strip
        expected = viewport_module._compose_tiled_strip(viewport.layout, viewport._surfaces)
        assert viewport._tiled_strip.tobytes() == expected.tobytes()
        assert viewport.frame(59).tobytes() == expected.crop((59, 0, 59 + 384, 32)).tobytes()
        viewport.update((game(90, (0, 0, 255, 128), 1),), context, "sports")
        _settle(viewport)
        assert viewport._tiled_strip is not strip
        assert viewport.status["full_compositions"] == 2
        expected = viewport_module._compose_tiled_strip(viewport.layout, viewport._surfaces)
        assert viewport._tiled_strip.tobytes() == expected.tobytes()
    finally:
        viewport.close()


def test_tournament_update_recolors_both_boundaries_and_the_repeat_seam():
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc))
    regular = Content("regular", "scoreboard", "nba", {"competition_stage": 0})
    playoff = Content("playoff", "scoreboard", "nhl", {"competition_stage": 1})
    finals = Content("finals", "scoreboard", "mlb", {"competition_stage": 2})
    try:
        viewport.update((regular, playoff, finals), context, "sports")
        _drain(viewport, catalog, 3)
        layout = viewport.layout
        assert layout is not None
        frame = viewport.frame(0, width=layout.width)
        expected = ((255, 215, 0), (192, 192, 192), (255, 215, 0))
        start = 0
        for segment, color in zip(layout.segments, expected):
            assert frame.getpixel((start, 16)) == color
            start += segment.width
        updated = Content("playoff", "scoreboard", "nhl", {"competition_stage": 2})
        viewport.update((regular, updated, finals), context, "sports")
        _drain(viewport, catalog, 4)
        frame = viewport.frame(0, width=layout.width)
        assert frame.getpixel((layout.segments[0].width, 16)) == (255, 215, 0)
    finally:
        viewport.close()


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


def test_changed_game_delta_reuses_every_unchanged_scene(monkeypatch):
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 26, tzinfo=timezone.utc))
    games = tuple(Content(f'game-{index}', 'scoreboard', 'nfl', {'down': '1st'}) for index in range(150))
    try:
        viewport.update(games, context, 'sports')
        _settle(viewport)
        scenes = []
        original = viewport_module._scene_mapping

        def capture(item):
            scenes.append(item.id)
            return original(item)

        monkeypatch.setattr(viewport_module, '_scene_mapping', capture)
        changed = games[:-1] + (Content('game-149', 'scoreboard', 'nfl', {'down': '2nd'}),)
        viewport.update(changed, context, 'sports', changed_ids=frozenset({'game-149'}))
        _settle(viewport)
        assert scenes == ['game-149']
        assert catalog.calls == 151
        assert len(viewport.layout.segments) == 150
    finally:
        viewport.close()


def test_incremental_update_detects_changed_locally_generated_panes():
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026,4,1,tzinfo=timezone.utc))
    game = Content('game','scoreboard','nfl',{'down':'1st'})
    old_local = Content('local','scoreboard','nfl',{'down':'1st'})
    try:
        viewport.update((game,old_local),context,'sports')
        _settle(viewport)
        new_local = Content('local','scoreboard','nfl',{'down':'2nd'})
        viewport.update((game,new_local),context,'sports',changed_ids=frozenset())
        _settle(viewport)
        assert catalog.calls == 3
        assert viewport.frame(97).getpixel((1,1)) == (0,255,0)
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


def test_unchanged_cached_panes_do_not_serialize_scenes_again(monkeypatch) -> None:
    calls = []
    serialize = viewport_module._plain_mapping

    def capture(value):
        calls.append(value)
        return serialize(value)

    monkeypatch.setattr(viewport_module, "_plain_mapping", capture)
    catalog = Catalog()
    viewport = CardViewport(catalog)
    context = RenderContext(datetime(2026, 10, 14, tzinfo=timezone.utc))
    data = {"down": "1st", "situation": {"count": (1, 2), "nested": {"live": True}}}
    try:
        viewport.update((Content("game", "scoreboard", "nfl", data),), context, "sports")
        _drain(viewport, catalog, 1)
        initial_calls = len(calls)
        for _ in range(20):
            viewport.update((Content("game", "scoreboard", "nfl", dict(data)),), context, "sports")
            viewport.install_completed()
        assert initial_calls > 0
        assert len(calls) == initial_calls
        assert catalog.calls == 1
        assert viewport.status["committed_generation"] == 21
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

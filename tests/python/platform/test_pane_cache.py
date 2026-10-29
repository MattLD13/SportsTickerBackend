"""Verify durable card images cannot outlive their renderer, scene, or asset inputs."""

from datetime import datetime, timezone
from threading import Event
from time import monotonic, sleep

from PIL import Image

from ticker_core.app.viewport import CardViewport
from ticker_core.ui.frame import RenderContext
from ticker_core.platform.assets import AssetCoordinator
from ticker_core.platform.panes import PreparedPaneCache, asset_signatures
from ticker_core.ui import RenderedContent
from ticker_core.runtime import Content


def test_cached_pane_requires_matching_scene_renderer_asset_and_pixels(tmp_path, monkeypatch):
    import ticker_core.platform.panes as module
    from ticker_core.assets import AssetRequest

    monkeypatch.setattr(module, '_renderer_fingerprint', lambda: 'renderer-a')
    assets = AssetCoordinator(tmp_path)
    scene = {'id': 'game', 'type': 'scoreboard', 'sport': 'nfl', 'home_logo': 'https://example.test/logo.png', 'home_score': '7'}
    for size in ((16,16),(22,22),(24,24)):
        assets.long_term.prepared.put(AssetRequest(scene['home_logo'], 'logo', size), Image.new('RGBA', size, 'red'))
    signature = asset_signatures(assets, scene)
    rgba = Image.new('RGBA', (96,32), 'green').tobytes()
    cache = PreparedPaneCache(assets)
    cache.save('game', scene, 'sports', 96, 32, rgba, signature)
    cache.close()
    cache = PreparedPaneCache(assets)
    try:
        assert cache.load('game', scene, 'sports').result(timeout=5) == (96,32,rgba)
        assert cache.load('game', {**scene, 'home_score': '8'}, 'sports').result(timeout=5) is None
        assert cache.load('game', scene, 'weather').result(timeout=5) is None
        previous_revision = assets.revision
        assets.long_term.prepared.put(AssetRequest(scene['home_logo'], 'logo', (22,22)), Image.new('RGBA',(22,22),'blue'))
        assert assets.revision > previous_revision
        assert cache.load('game', scene, 'sports').result(timeout=5) is None
    finally:
        cache.close()
    monkeypatch.setattr(module, '_renderer_fingerprint', lambda: 'renderer-b')
    cache = PreparedPaneCache(assets)
    try:
        assert cache.load('game', scene, 'sports').result(timeout=5) is None
    finally:
        cache.close()
        assets.close()


def test_corrupt_pane_file_is_not_used(tmp_path):
    assets = AssetCoordinator(tmp_path)
    cache = PreparedPaneCache(assets)
    scene = {'id': 'game', 'type': 'scoreboard', 'sport': 'nfl'}
    rgba = Image.new('RGBA', (96,32), 'red').tobytes()
    cache.save('game', scene, 'sports', 96, 32, rgba, ())
    cache.close()
    path = next((tmp_path/'rendered-panes').glob('*.json'))
    text = path.read_text(encoding='utf-8')
    path.write_text(text.replace('"pixels":"', '"pixels":"bad'), encoding='utf-8')
    cache = PreparedPaneCache(assets)
    try:
        assert cache.load('game', scene, 'sports').result(timeout=5) is None
    finally:
        cache.close()
        assets.close()


def test_persistent_pane_cache_is_bounded(tmp_path):
    assets = AssetCoordinator(tmp_path)
    cache = PreparedPaneCache(assets, capacity=2)
    rgba = Image.new('RGBA', (96,32), 'red').tobytes()
    for index in range(10):
        scene = {'id': str(index), 'type': 'scoreboard', 'sport': 'nfl'}
        cache.save(str(index), scene, 'sports', 96, 32, rgba, ())
    cache.close()
    files = tuple((tmp_path/'rendered-panes').glob('*.json'))
    assert 1 <= len(files) <= 2
    assets.close()


def test_restart_shows_verified_cached_cards_while_renderer_is_blocked(tmp_path):
    class Catalog:
        def __init__(self, blocked=False):
            self.blocked, self.started, self.release = blocked, Event(), Event()

        def render(self, context, scene):
            if self.blocked:
                self.started.set()
                assert self.release.wait(8)
            color = 'red' if scene.item.get('score') == '1' else 'green'
            return RenderedContent(Image.new('RGBA', (96,32), color))

    def settle(viewport):
        deadline = monotonic()+8
        while viewport.status['pending'] and monotonic()<deadline:
            viewport.install_completed()
            sleep(0.001)
        assert viewport.status['pending'] == 0

    assets = AssetCoordinator(tmp_path)
    games = tuple(Content(str(index), 'scoreboard', 'nfl', {'score':'1'}) for index in range(4))
    context = RenderContext(datetime(2026,10,26,tzinfo=timezone.utc))
    first = CardViewport(Catalog(), pane_cache=PreparedPaneCache(assets))
    try:
        first.update(games, context, 'sports')
        settle(first)
    finally:
        first.close()
    catalog = Catalog(blocked=True)
    restored = CardViewport(catalog, pane_cache=PreparedPaneCache(assets))
    try:
        restored.update(games, context, 'sports')
        assert catalog.started.wait(2)
        deadline = monotonic()+6
        while restored.layout is None and monotonic()<deadline:
            restored.install_completed()
            sleep(0.002)
        assert restored.layout is not None
        assert len(restored.layout.segments) == 4
        assert restored.frame(0).getpixel((1,1)) == (255,0,0)
        assert restored.status['pending'] == 1
    finally:
        catalog.release.set()
        restored.close()
        assets.close()


def test_restart_does_not_show_a_cached_score_after_the_game_changes(tmp_path):
    class Catalog:
        def __init__(self):
            self.started, self.release = Event(), Event()

        def render(self, context, scene):
            self.started.set()
            assert self.release.wait(8)
            return RenderedContent(Image.new('RGBA', (96,32), (0,255,0,255)))

    assets = AssetCoordinator(tmp_path)
    cache = PreparedPaneCache(assets)
    for index in range(4):
        scene = {'id': str(index), 'type': 'scoreboard', 'sport': 'nfl', 'score': '1'}
        cache.save(str(index), scene, 'sports', 96, 32, Image.new('RGBA',(96,32),'red').tobytes(), ())
    cache.close()
    catalog = Catalog()
    viewport = CardViewport(catalog, pane_cache=PreparedPaneCache(assets))
    context = RenderContext(datetime(2026,10,26,tzinfo=timezone.utc))
    try:
        viewport.update(tuple(Content(str(index),'scoreboard','nfl',{'score':'2'}) for index in range(4)), context, 'sports')
        assert catalog.started.wait(2)
        deadline = monotonic()+6
        while viewport._cache_futures and monotonic()<deadline:
            viewport.install_completed()
            sleep(0.002)
        assert not viewport._cache_futures
        assert viewport.status['cache_misses'] == 4
        assert viewport.layout is None
        catalog.release.set()
        deadline = monotonic()+6
        while viewport.status['pending'] and monotonic()<deadline:
            viewport.install_completed()
            sleep(0.002)
        assert viewport.frame(0).getpixel((1,1)) == (0,255,0)
    finally:
        catalog.release.set()
        viewport.close()
        assets.close()


def test_process_renderer_uses_new_prepared_logo_after_asset_revision(tmp_path):
    from PIL import ImageChops
    from ticker_core.assets import AssetRequest
    from ticker_core.bootstrap import create_default_content_catalog

    assets = AssetCoordinator(tmp_path)
    url = 'https://example.test/team.png'
    request = AssetRequest(url, 'logo', (22,22))
    assets.long_term.prepared.put(request, Image.new('RGBA',(22,22),(255,0,0,255)))
    viewport = CardViewport(create_default_content_catalog(assets), use_process=True, asset_directory=tmp_path)
    context = RenderContext(datetime(2026,10,26,tzinfo=timezone.utc))
    game = Content('game','scoreboard','nfl',{'state':'in','status':'Q3 08:12',
        'home_abbr':'NYG','away_abbr':'DAL','home_score':'7','away_score':'3','home_logo':url})

    def settle():
        deadline = monotonic()+20
        while viewport.status['pending'] and monotonic()<deadline:
            viewport.install_completed()
            sleep(0.005)
        assert viewport.status['pending'] == 0
        assert viewport.status['failed'] == 0

    try:
        viewport.update((game,),context,'sports')
        settle()
        before = viewport.frame(0)
        assets.long_term.prepared.put(request, Image.new('RGBA',(22,22),(0,0,255,255)))
        viewport.invalidate()
        settle()
        assert ImageChops.difference(before,viewport.frame(0)).getbbox() is not None
    finally:
        viewport.close()
        assets.close()

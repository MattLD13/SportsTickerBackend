"""Verify template reuse preserves dynamic content and stays bounded."""

from datetime import datetime, timezone

import pytest
from PIL import Image

from ticker.six.ui.frame import RenderContext
from ticker.six.ui.cards.flight import FlightCard
from ticker.six.ui.cards.golf import GolfCard
from ticker.six.ui.cards.music import MusicCard
from ticker.six.ui.cards.racing import RacingCard
from ticker.six.ui.sports.pane import PaneCard
from ticker.six.ui.sports.pinned import PinnedCard
from ticker.six.ui.cards.stock import StockCard
from ticker.six.ui.cards.weather import WeatherCard
from ticker.six.ui import load_default_font_set
from ticker.six.ui.cards.clock import ClockCard
from ticker.six.ui.layers import ImageTemplates

pytestmark = pytest.mark.critical


class NoTemplates:
    def render(self, key, build):
        return build().copy()


class Logos:
    def __init__(self):
        self.color = (255,0,0,255)

    def get(self, url, size):
        return Image.new('RGBA', size, self.color) if url else None


def test_templates_are_bounded_and_return_independent_copies():
    cache = ImageTemplates(capacity=2, max_bytes=512)
    original = cache.render('a', lambda: Image.new('RGBA',(8,8),'red'))
    original.putpixel((0,0),(0,0,0,0))
    assert cache.render('a', lambda: None).getpixel((0,0)) == (255,0,0,255)
    cache.render('b', lambda: Image.new('RGBA',(8,8),'blue'))
    cache.render('c', lambda: Image.new('RGBA',(8,8),'green'))
    assert len(cache._items) == 2 and cache._bytes == 512
    assert cache.hits == 1 and cache.misses == 3


@pytest.mark.parametrize('sport', ['nfl','ncf_fbs','mlb','nhl','nba','march_madness','soccer_mls'])
def test_sports_template_matches_uncached_dynamic_and_logo_changes(sport):
    logos = Logos()
    cached = PaneCard(logos)
    reference = PaneCard(logos)
    reference._bases = NoTemplates()
    game = {'sport':sport,'state':'in','status':'Q2 08:12','away_score':7,'home_score':14,
            'away_abbr':'AWY','home_abbr':'HOM','away_logo':'away','home_logo':'home',
            'away_color':'#005599','home_color':'#cc2200','away_rank':'2','home_rank':'5',
            'competition_stage':1,'situation':{'activeTeam':'AWY','downDist':'3RD & 4'}}
    if sport == 'mlb':
        game['baseball_inning'] = {'number':5,'half':'top','phase':'playing'}
    for index in range(8):
        game['home_score'] = index * 11
        game['status'] = f'Q2 08:{index:02}'
        game['situation']['activeTeam'] = ('AWY','HOM','')[index%3]
        game['situation']['isRedZone'] = bool(index%2)
        if index == 4:
            logos.color = (0,0,255,255)
        first = cached.card(game)
        second = reference.card(game)
        assert first.size == second.size and first.tobytes() == second.tobytes()
    assert cached._bases.hits > 0


def test_150_wide_distinct_sports_cards_fit_in_the_bounded_template_cache():
    renderer = PaneCard(Logos())
    games = [{'sport':'nfl','state':'in','status':'Q4 08:59','away_score':14,'home_score':21,
              'away_abbr':f'A{index}','home_abbr':f'H{index}','away_logo':f'away-{index}',
              'home_logo':f'home-{index}', 'situation':{'downDist':'FIRST AND GOAL AT THE LONG 10 YARD LINE'}} for index in range(150)]
    for game in games:
        image = renderer.card(game)
        assert image.width == 160
    assert len(renderer._bases._items) == 150
    misses = renderer._bases.misses
    for game in games:
        renderer.card({**game,'away_score':15,'status':'Q4 08:58'})
    assert renderer._bases.hits == 150
    assert renderer._bases.misses == misses
    assert renderer._bases._bytes <= 4 * 1024 * 1024


def test_sports_logo_outline_changes_invalidate_the_template():
    from ticker.six.assets import LogoAssetView, MemoryAssetView

    assets = MemoryAssetView()
    url = 'https://example.test/mark.png'
    assets.put_image(url, 'logo_native_grid', (22,22), Image.new('RGBA',(22,22),(15,15,15,255)))
    renderer = PaneCard(LogoAssetView(assets))
    reference = PaneCard(LogoAssetView(assets))
    reference._bases = NoTemplates()
    game = {'sport':'nfl','state':'in','status':'Q2 08:00','away_score':7,'home_score':3,
            'home_abbr':'HOM','away_abbr':'AWY','home_logo':url,'situation':{}}
    for outline in ('off','inner','auto'):
        game['home_logo_rendering'] = {'method':'new','outline':outline,'cutoff':35}
        actual = renderer.card(game)
        expected = reference.card(game)
        assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize('sport',['nfl','ncf_fbs','nhl','nba','mlb','soccer_mls'])
def test_pinned_sports_surfaces_preserve_dynamic_fields(sport):
    logos, fonts = Logos(), load_default_font_set()
    renderer = PinnedCard(fonts,logos)
    reference = PinnedCard(fonts,logos)
    reference._surfaces = NoTemplates()
    game = {'sport':sport,'state':'in','status':'Q2 08:00','away_score':7,'home_score':3,
            'home_abbr':'HOM','away_abbr':'AWY','home_logo':'home','away_logo':'away',
            'home_color':'#005599','away_color':'#bb2200','situation':{'activeTeam':'AWY','yardLine':50,'yardsToGo':10}}
    if sport == 'mlb':
        game['baseball_inning'] = {'number':5,'half':'top','phase':'playing'}
    for index in range(8):
        game['home_score'] = index
        game['status'] = f'Q2 08:{index:02}'
        game['situation'].update(activeTeam=('AWY','HOM','')[index%3], yardLine=index*10,
                                 isRedZone=bool(index%2), downDist=f'{index%4+1}ST & 10',
                                 onFirst=bool(index&1), onSecond=bool(index&2), onThird=bool(index&4))
        if index == 4:
            logos.color = (0,0,255,255)
        actual = renderer.frame(game)
        expected = reference.frame(game)
        assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
    if sport in {'nfl','ncf_fbs','soccer_mls'}:
        assert renderer._surfaces.hits > 0


def test_mode_templates_match_fresh_layers_when_values_change():
    fonts, logos = load_default_font_set(), Logos()
    utility, utility_ref = StockCard(fonts,logos), StockCard(fonts,logos)
    utility_ref._layers = NoTemplates()
    golf, golf_ref = GolfCard(fonts), GolfCard(fonts)
    golf_ref._panes = NoTemplates()
    racing, racing_ref = RacingCard(fonts,logos), RacingCard(fonts,logos)
    racing_ref._headers = NoTemplates()
    flight, flight_ref = FlightCard(fonts,logos), FlightCard(fonts,logos)
    flight_ref._boards = NoTemplates()
    weather, weather_ref = WeatherCard(fonts), WeatherCard(fonts)
    clock, clock_ref = ClockCard(fonts), ClockCard(fonts)
    clock_ref._dates = NoTemplates()
    music, music_ref = MusicCard(fonts,logos), MusicCard(fonts,logos)
    for index in range(8):
        if index == 4:
            logos.color = (0,0,255,255)
        now = datetime(2026,10,26,12,1,index,tzinfo=timezone.utc)
        context = RenderContext(now)
        stock = {'home_abbr':'AAPL','home_logo':'logo','home_score':f'{100+index}.23','away_score':f'{index-4}%',
                 'situation':{'change':str(index-4)}}
        golf_game = {'golf':{'event_name':'OPEN','round':'R2','players':[{'name':'A Player','total':index-4,'thru':5}]}}
        race = {'sport':'indycar','state':'in','indycar':{'session_name':'RACE','flag':'YELLOW' if index%2 else 'GREEN',
                'lap':index,'total_laps':100,'drivers':[{'pos':1,'abbr':'ABC','car':'12'}]}}
        from ticker.shared.sports_display import racing_signal
        race['racing_display'] = {'cards': [{'race_name':'500', 'signals':[racing_signal('GREEN', 'indycar')],
            'rows':[{'position':1, 'position_rgb':(255,255,255), 'car':'12', 'name':'ABC',
                     'metric':str(index), 'metric_rgb':(255,255,255)}]}]}
        visitor = {'id':'UA12','type':'flight_visitor','airline_logo':'logo','guest_name':'Guest','is_live':True,
                   'progress':index*10,'alt':30000+index,'is_delayed':bool(index%2)}
        weather_item = {'home_abbr':str(70+index),'away_abbr':'Boston','situation':{'icon':'rain' if index%2 else 'sun','is_day':1}}
        airport = {'iata':'EWR','city':'Newark','away_abbr':f'{70+index}F','status':'CLEAR'}
        artwork = logos.get('logo',(42,42))
        pairs = [(utility.pane(stock),utility_ref.pane(stock)), (golf.pane(golf_game),golf_ref.pane(golf_game)),
                 (racing.strip(race, 0),racing_ref.strip(race, 0)),
                 (flight.visitor(visitor),flight_ref.visitor(visitor)),
                 (flight.board(airport,[{'flight_number':str(index)}],[]),flight_ref.board(airport,[{'flight_number':str(index)}],[])),
                 (weather.frame(context.now,weather_item),weather_ref.frame(context.now,weather_item)),
                 (clock.frame(now),clock_ref.frame(now)),
                 (music._label(artwork),music_ref._label(artwork))]
        for actual, expected in pairs:
            assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
    assert racing._headers.hits > 0

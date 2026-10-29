"""Verify template reuse preserves dynamic content and stays bounded."""

from datetime import datetime, timezone

import pytest
from PIL import Image

from ticker_core.ui.frame import RenderContext
from ticker_core.ui.cards.flight import FlightCard
from ticker_core.features.golf.renderer import GolfRenderer
from ticker_core.ui.cards.music import MusicCard
from ticker_core.features.racing.renderer import RacingRenderer
from ticker_core.features.sports.stadium_port import PreparedStadiumRenderer
from ticker_core.features.sports.pinned import PreparedSportsFullRenderer
from ticker_core.features.utility.renderer import UtilityRenderer
from ticker_core.features.weather.renderer import WeatherRenderer
from ticker_core.ui import load_default_font_set
from ticker_core.ui.cards.clock import ClockCard
from ticker_core.ui.layers import ImageTemplates

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
    cached = PreparedStadiumRenderer(logos)
    reference = PreparedStadiumRenderer(logos)
    reference._card_templates = NoTemplates()
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
        first, width = cached.render(game)
        second, ref_width = reference.render(game)
        assert width == ref_width and first.tobytes() == second.tobytes()
    assert cached._card_templates.hits > 0


def test_150_wide_distinct_sports_cards_fit_in_the_bounded_template_cache():
    renderer = PreparedStadiumRenderer(Logos())
    games = [{'sport':'nfl','state':'in','status':'Q4 08:59','away_score':14,'home_score':21,
              'away_abbr':f'A{index}','home_abbr':f'H{index}','away_logo':f'away-{index}',
              'home_logo':f'home-{index}', 'situation':{'downDist':'FIRST AND GOAL AT THE LONG 10 YARD LINE'}} for index in range(150)]
    for game in games:
        image, _ = renderer.render(game)
        assert image.width == 160
    assert len(renderer._card_templates._items) == 150
    misses = renderer._card_templates.misses
    for game in games:
        renderer.render({**game,'away_score':15,'status':'Q4 08:58'})
    assert renderer._card_templates.hits == 150
    assert renderer._card_templates.misses == misses
    assert renderer._card_templates._bytes <= 4 * 1024 * 1024


def test_sports_logo_outline_changes_invalidate_the_template():
    from ticker_core.assets import LogoAssetView, MemoryAssetView

    assets = MemoryAssetView()
    url = 'https://example.test/mark.png'
    assets.put_image(url, 'logo_native_grid', (22,22), Image.new('RGBA',(22,22),(15,15,15,255)))
    renderer = PreparedStadiumRenderer(LogoAssetView(assets))
    reference = PreparedStadiumRenderer(LogoAssetView(assets))
    reference._card_templates = NoTemplates()
    game = {'sport':'nfl','state':'in','status':'Q2 08:00','away_score':7,'home_score':3,
            'home_abbr':'HOM','away_abbr':'AWY','home_logo':url,'situation':{}}
    for outline in ('off','inner','auto'):
        game['home_logo_rendering'] = {'method':'new','outline':outline,'cutoff':35}
        actual,_ = renderer.render(game)
        expected,_ = reference.render(game)
        assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize('sport',['nfl','ncf_fbs','nhl','nba','mlb','soccer_mls'])
def test_pinned_sports_field_templates_preserve_dynamic_fields(sport):
    logos, fonts = Logos(), load_default_font_set()
    renderer = PreparedSportsFullRenderer(fonts,logos)
    reference = PreparedSportsFullRenderer(fonts,logos)
    reference._field_templates = NoTemplates()
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
        actual = renderer.draw_sport_full_bleed(game)
        expected = reference.draw_sport_full_bleed(game)
        assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
    if sport in {'nfl','ncf_fbs','soccer_mls'}:
        assert renderer._field_templates.hits > 0


def test_mode_templates_match_fresh_layers_when_values_change():
    fonts, logos = load_default_font_set(), Logos()
    utility, utility_ref = UtilityRenderer(fonts,logos), UtilityRenderer(fonts,logos)
    utility_ref._stock_templates = NoTemplates()
    golf, golf_ref = GolfRenderer(fonts), GolfRenderer(fonts)
    golf_ref._scroll_templates = NoTemplates()
    racing, racing_ref = RacingRenderer(fonts,logos), RacingRenderer(fonts,logos)
    racing_ref._scroll_templates = NoTemplates()
    flight, flight_ref = FlightCard(fonts,logos), FlightCard(fonts,logos)
    flight_ref._boards = NoTemplates()
    weather, weather_ref = WeatherRenderer(fonts), WeatherRenderer(fonts)
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
        from sports_ticker.providers.sports_display import racing_signal
        race['racing_display'] = {'cards': [{'race_name':'500', 'signals':[racing_signal('GREEN', 'indycar')],
            'rows':[{'position':1, 'position_rgb':(255,255,255), 'car':'12', 'name':'ABC',
                     'metric':str(index), 'metric_rgb':(255,255,255)}]}]}
        visitor = {'id':'UA12','type':'flight_visitor','airline_logo':'logo','guest_name':'Guest','is_live':True,
                   'progress':index*10,'alt':30000+index,'is_delayed':bool(index%2)}
        weather_item = {'home_abbr':str(70+index),'away_abbr':'Boston','situation':{'icon':'rain' if index%2 else 'sun','is_day':1}}
        airport = {'iata':'EWR','city':'Newark','away_abbr':f'{70+index}F','status':'CLEAR'}
        artwork = logos.get('logo',(42,42))
        pairs = [(utility.stock(stock),utility_ref.stock(stock)), (golf.scroll(golf_game),golf_ref.scroll(golf_game)),
                 (racing._render_scroll(race),racing_ref._render_scroll(race)),
                 (flight.visitor(visitor),flight_ref.visitor(visitor)),
                 (flight.board(airport,[{'flight_number':str(index)}],[]),flight_ref.board(airport,[{'flight_number':str(index)}],[])),
                 (weather.detailed(context,weather_item),weather_ref.detailed(context,weather_item)),
                 (clock.frame(now),clock_ref.frame(now)),
                 (music._label(artwork),music_ref._label(artwork))]
        for actual, expected in pairs:
            assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
    assert racing._scroll_templates.hits > 0

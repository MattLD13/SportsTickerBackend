"""Compare original and cached renderer layers with exact pixels and paired timings."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ticker_core.context import RenderContext
from ticker_core.rendering import load_default_font_set
from ticker_core.features.sports.stadium_port import PreparedStadiumRenderer
from ticker_core.features.sports.pinned import PreparedSportsFullRenderer
from ticker_core.features.utility.renderer import UtilityRenderer
from ticker_core.features.golf.renderer import GolfRenderer
from ticker_core.features.racing.renderer import RacingRenderer
from sports_ticker.projections.racing_display import racing_cards
from ticker_core.features.flight.renderer import FlightRenderer
from ticker_core.features.weather.renderer import WeatherRenderer
from ticker_core.features.music.renderer import MusicAnimationState, MusicRenderer
from ticker_core.features.clock.renderer import ClockRenderer


def load_reference(package, path):
    name = f'ticker_core.features.{package}._reference_{path.stem.replace("-", "_")}'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f'Cannot load reference: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Logos:
    """Supply the same prepared logo pixels to both renderer paths."""

    def __init__(self, root):
        self.images = [Image.open(root / name).convert('RGBA') for name in ('nfl-dal.png', 'nfl-nyg.png')]
        self.prepared = {}

    def get(self, url, size):
        if not url:
            return None
        key = str(url), size
        if key not in self.prepared:
            source = self.images[1 if str(url).endswith('home') else 0]
            image = source.resize(size, Image.Resampling.LANCZOS)
            if str(url).startswith('game-'):
                marker = sha256(str(url).encode()).digest()
                image.putpixel((0, 0), (marker[0], marker[1], marker[2], 255))
            self.prepared[key] = image
        return self.prepared[key]


def inputs(index):
    sports = ('nfl','ncf_fbs','mlb','nhl','nba','march_madness','soccer_mls')
    sport = sports[index % len(sports)]
    score = index % 100
    game = {'id':f'game-{index%150}','sport':sport,'state':'in','status':f'Q2 08:{index%60:02}',
            'away_abbr':'DAL','home_abbr':'NYG','away_score':score,'home_score':score+1,
            'away_logo':f'game-{index%150}-away','home_logo':f'game-{index%150}-home','away_color':'#00338D','home_color':'#D50A0A',
            'away_rank':'2','home_rank':'5','competition_stage':index%3,
            'situation':{'activeTeam':('DAL','NYG','')[index%3], 'downDist':('1ST & 10','3RD & 4')[index%2],
                         'isRedZone':bool(index%2),'balls':index%4,'strikes':index%3,'outs':index%3,
                         'powerPlay':bool(index%2),'powerPlayTeam':'DAL','manpower':{'scrollLabel':'PP 1:12'}}}
    if sport == 'mlb':
        game['baseball_inning'] = {'number':5,'half':'top','phase':'playing'}
    stock = {'home_abbr':'AAPL','home_logo':'fixture-home','home_score':f'{100+index%20}.23',
             'away_score':f'{index%9-4}%', 'situation':{'change':str(index%9-4)}}
    golf = {'golf':{'event_name':'PGA TOUR','round':'ROUND 2','players':[{'name':'A Player','pos':'1','total':index%8-4,'thru':5},
                                                                          {'name':'B Player','pos':'2','total':index%6-3,'thru':7}]}}
    racing = {'sport':'indycar','state':'in','indycar':{'session_name':'RACE','flag':'YELLOW' if index%5==0 else 'GREEN',
              'lap':index%100+1,'total_laps':100,'drivers':[{'pos':1,'abbr':'ABC','car':'12'},{'pos':2,'abbr':'DEF','car':'44','gap':'+1.2'}]}}
    visitor = {'id':'UA12','type':'flight_visitor','airline_logo':'fixture-home','guest_name':'Guest','origin_city':'Boston',
               'dest_city':'Chicago','is_live':True,'progress':index%100,'alt':30000+index,'is_delayed':bool(index%2)}
    airport = {'iata':'EWR','city':'Newark','away_abbr':f'{70+index%5}F','status':'CLEAR'}
    weather = {'home_abbr':str(70+index%5),'away_abbr':'Boston','situation':{'icon':('sun','rain','snow','storm')[index%4],
                'is_day':1,'cloud_cover':index%100,'obs_time':'2026-10-26T12:00','stats':{'wind':str(index%10)}}}
    music = {'home_abbr':'Artist','away_abbr':'Song','home_logo':'fixture-home',
             'situation':{'is_playing':True,'duration':240,'fetch_ts':1793016000}}
    return game,stock,golf,racing,visitor,airport,weather,music


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-directory',type=Path,required=True)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--iterations',type=int,default=150)
    parser.add_argument('--pairs',type=int,default=4)
    parser.add_argument('--categories', nargs='+', choices=('sports','pinned','pinned_football','pinned_hockey',
        'pinned_baseball','pinned_basketball','pinned_soccer','stock','golf','golf_match','racing','flight','airport','weather','music','clock'))
    parser.add_argument('--cpu',type=int)
    parser.add_argument('--hardware',action='store_true',help='Present a final frame after stopping the controller and installing a recovery handler.')
    args = parser.parse_args()
    if not 1 <= args.iterations <= 1000 or not 2 <= args.pairs <= 20:
        parser.error('Use 1 to 1000 iterations and 2 to 20 pairs.')
    if args.cpu is not None:
        os.sched_setaffinity(0,{args.cpu})
    root=args.baseline_directory
    old_sports=load_reference('sports',root/'stadium-before-template.py')
    old_pinned=load_reference('sports',root/'pinned-before-template.py')
    old_stock=load_reference('utility',root/'utility-before-template.py')
    old_golf=load_reference('golf',root/'golf-before-template.py')
    old_racing=load_reference('racing',root/'racing-before-template.py')
    old_flight=load_reference('flight',root/'flight-before-template.py')
    old_weather=load_reference('weather',root/'weather-drawing-before-template.py')
    old_music=load_reference('music',root/'music-renderer-before-template.py')
    old_clock=load_reference('clock',root/'clock-renderer-before-template.py')
    fonts,logos=load_default_font_set(),Logos(args.fixtures)
    prior={'sports':old_sports.PreparedStadiumRenderer(logos),'pinned':old_pinned.PreparedSportsFullRenderer(fonts,logos),
           'stock':old_stock.UtilityRenderer(fonts,logos),
           'golf':old_golf.GolfRenderer(fonts),'racing':old_racing.RacingRenderer(fonts,logos),
           'flight':old_flight.FlightRenderer(fonts,logos),'weather':old_weather.PreparedWeatherRenderer,
           'music':old_music.MusicRenderer(fonts,logos),'clock':old_clock.ClockRenderer(fonts.tiny,fonts.clock)}
    current={'sports':PreparedStadiumRenderer(logos),'pinned':PreparedSportsFullRenderer(fonts,logos),
             'stock':UtilityRenderer(fonts,logos),'golf':GolfRenderer(fonts),
             'racing':RacingRenderer(fonts,logos),'flight':FlightRenderer(fonts,logos),'weather':WeatherRenderer(fonts),
             'music':MusicRenderer(fonts,logos),'clock':ClockRenderer(fonts.tiny,fonts.clock)}
    contexts=[RenderContext(datetime(2026,10,26,12,0,tzinfo=timezone.utc)+timedelta(seconds=index)) for index in range(args.iterations)]
    samples=[inputs(index) for index in range(args.iterations)]
    phase = 0

    def render(which,category,index):
        owner='pinned' if category.startswith('pinned_') else {'airport':'flight','golf_match':'golf'}.get(category,category)
        renderer=which[owner]
        game,stock,golf,racing,flight,airport,weather,music=samples[index]
        context=contexts[index]
        if category == 'sports' or category.startswith('pinned'):
            changed={**game,'away_score':(index+phase)%100,'status':f'Q2 {8-(phase%2):02}:{(index+phase)%60:02}',
                     'situation':{**game['situation'],'activeTeam':('DAL','NYG','')[(index+phase)%3],
                                  'yardLine':(index+phase)%100,'yardsToGo':10,'onFirst':bool(index&1),
                                  'onSecond':bool(index&2),'onThird':bool(index&4)}}
            selected={'pinned_football':'nfl','pinned_hockey':'nhl','pinned_baseball':'mlb',
                      'pinned_basketball':'nba','pinned_soccer':'soccer_mls'}.get(category)
            if selected is not None:
                changed['sport']=selected
                if selected == 'mlb':changed['baseball_inning']={'number':5,'half':'top','phase':'playing'}
            return renderer.render(changed)[0] if category=='sports' else renderer.draw_sport_full_bleed(changed)
        if category=='stock':return renderer.stock({**stock,'home_score':f'{100+(index+phase)%20}.23'})
        if category=='golf':
            changed={**golf,'golf':{**golf['golf'],'players':[{'name':'A Player','pos':'1','total':(index+phase)%8-4,'thru':5}]}}
            return renderer.scroll(changed)
        if category=='golf_match':
            return renderer.scroll({'golf':{'format':'match_play','event_name':'PRES CUP',
                'teams':[{'abbr':'USA','score':index%4},{'abbr':'INTL','score':phase%4}],
                'matches':[{'sides':[{'team':'USA','player':'A Player','score':f'{(index+phase)%3+1}UP'},
                                     {'team':'INTL','player':'B Player'}]}]}})
        if category=='racing':
            changed = {**racing, 'indycar': {**racing['indycar'], 'lap': (index+phase)%100+1}}
            changed['racing_display'] = {'cards': racing_cards(changed)}
            return renderer._render_scroll(changed)
        if category=='flight':return renderer.visitor({**flight,'progress':(index+phase)%100})
        if category=='airport':return renderer.airport(airport,[{'flight_number':str(index),'airport_city':'Boston'}],[])
        if category=='weather':
            return renderer(fonts,context.now).draw_weather_detailed(weather) if which is prior else renderer.detailed(context,weather)
        if category=='music':
            state=old_music.MusicAnimationState() if which is prior else MusicAnimationState()
            return renderer.render_with_state(context,music,state)[0]
        return renderer.render_at(context.now)

    categories=tuple(args.categories or ('sports','pinned','stock','golf','golf_match','racing','flight','airport','weather','music','clock'))
    digest=sha256()
    references={}
    for category in categories:
        for index in range(args.iterations):
            before=render(prior,category,index)
            after=render(current,category,index)
            if before.mode!=after.mode or before.size!=after.size or before.tobytes()!=after.tobytes():
                raise AssertionError(f'Pixel mismatch for {category} case {index}')
            digest.update(category.encode());digest.update(before.tobytes())
        references[category]=before
    result={}
    cold_sports = None
    if 'sports' in categories:
        cold_sports = {'previous': [], 'template': []}
        for pair in range(args.pairs):
            phase = pair + 1
            order = ('previous','template') if pair % 2 == 0 else ('template','previous')
            for name in order:
                fresh = dict(prior if name == 'previous' else current)
                fresh['sports'] = old_sports.PreparedStadiumRenderer(logos) if name == 'previous' else PreparedStadiumRenderer(logos)
                started,cpu=time.perf_counter(),time.thread_time()
                for index in range(args.iterations):
                    render(fresh,'sports',index)
                cold_sports[name].append({'wall_ms':(time.perf_counter()-started)*1000,
                                          'cpu_ms':(time.thread_time()-cpu)*1000})
    for category in categories:
        measurements={'previous':[],'template':[]}
        for pair in range(args.pairs):
            phase = pair + 1
            for index in range(args.iterations):
                a,b=render(prior,category,index),render(current,category,index)
                if a.mode!=b.mode or a.size!=b.size or a.tobytes()!=b.tobytes():
                    raise AssertionError(f'Pixel mismatch for {category} case {index} phase {phase}')
            order=('previous','template') if pair%2==0 else ('template','previous')
            for name in order:
                source=prior if name=='previous' else current
                started,cpu=time.perf_counter(),time.thread_time()
                for index in range(args.iterations):render(source,category,index)
                measurements[name].append({'wall_ms':(time.perf_counter()-started)*1000,
                                           'cpu_ms':(time.thread_time()-cpu)*1000})
        summary={name:{metric:statistics.median(row[metric] for row in values) for metric in ('wall_ms','cpu_ms')}
                 for name,values in measurements.items()}
        summary['cpu_change_percent']=(100*(1-summary['template']['cpu_ms']/summary['previous']['cpu_ms'])
                                       if summary['previous']['cpu_ms'] else None)
        summary['pairs']=measurements
        result[category]=summary
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for category,image in references.items():
        image.convert('RGB').save(args.output.parent/f'{category}-reference.png')
    if args.hardware:
        from ticker_core.drivers import RgbMatrixFrameSink
        from ticker_core.rendering.strip import compose_pane_strip
        sink=RgbMatrixFrameSink.create()
        try:
            cards=[render(current,'sports',index).convert('RGBA') for index in range(4)]
            strip=compose_pane_strip([(card,card.width+1) for card in cards])
            frame=Image.new('RGB',(384,32));frame.paste(strip.crop((0,0,min(384,strip.width),32)),(0,0))
            sink.present(frame)
            frame.save(args.output.parent/'physical-frame.png')
        finally:
            sink.clear()
            close=getattr(sink,'close',None)
            if callable(close):close()
    payload={'context':'Controlled original-versus-template renderer comparison. Equal pixels checked for every input. Warm templates, paired alternating order. CPU timing excludes network, scheduling, and physical refresh.',
             'iterations_per_pair':args.iterations,'pairs':args.pairs,'pixel_sha256':digest.hexdigest(),
             'hardware_frame_presented':args.hardware,'cold_sports':cold_sports,'results':result}
    args.output.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps({'iterations_per_pair':args.iterations,'pairs':args.pairs,'pixel_sha256':digest.hexdigest(),
        'results':{key:{name:value for name,value in row.items() if name!='pairs'} for key,row in result.items()}},indent=2))


if __name__=='__main__':
    main()

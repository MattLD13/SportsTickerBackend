"""Misc metadata API routes (leagues, Spotify, blank logo)."""

import time
from flask import request, jsonify, make_response
from ..routes_runtime import app
from ..core import (
    state,
    LEAGUE_OPTIONS, _league_sort_key, _auto_category_for_option, resolve_ticker_id,
)
from ..workers import spotify_fetcher


@app.route('/leagues', methods=['GET'])
def get_league_options():
    ticker_id = request.args.get('id')
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        ticker_id = resolve_ticker_id(client_id=cid)

    league_meta = []
    for item in sorted(LEAGUE_OPTIONS, key=_league_sort_key):
        league_meta.append({
            'id':       item['id'],
            'label':    item['label'],
            'type':     item['type'],
            'category': _auto_category_for_option(item),
            'enabled':  state['active_sports'].get(item['id'], False),
        })
    if not any(x['id'] == 'music' for x in league_meta):
        league_meta.append({
            'id': 'music', 'label': 'Music', 'type': 'util',
            'enabled': state['active_sports'].get('music', False),
        })
    return jsonify(league_meta)


@app.route('/api/spotify/now', methods=['GET'])
def api_spotify():
    data = spotify_fetcher.get_cached_state()
    if data.get('is_playing') and data.get('last_fetch_ts'):
        elapsed = time.time() - data['last_fetch_ts']
        data['progress'] = min(data['progress'] + elapsed, data.get('duration', 0))
    return jsonify(data)


@app.route('/api/blank-logo.png', methods=['GET'])
def api_blank_logo():
    png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01'
        b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    resp = make_response(png)
    resp.headers['Content-Type'] = 'image/png'
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp

"""Racing API routes (JSON only — no HTML pages)."""

from flask import Blueprint, jsonify
from ..fetchers.racing_indycar import indycar_fetcher as _indycar_fetcher

racing = Blueprint('racing', __name__)


@racing.route('/api/racing/indycar')
def indycar_data():
    data = _indycar_fetcher.fetch()
    if not data:
        return jsonify({
            'status':            'no_data',
            'event_name':        'INDIANAPOLIS 500',
            'session_type':      'race',
            'session_label':     'RACE',
            'leader_laps':       0,
            'entries':           [],
            'race_control':      [],
            'track_state':       '0',
            'track_state_name':  'GREEN',
            'track_state_color': '#00C040',
            'track_state_key':   'green',
            'fetched_at':        0,
        })
    return jsonify(_indycar_fetcher.enrich(data))


@racing.route('/api/racing/indycar/racecontrol')
def indycar_racecontrol():
    data = _indycar_fetcher.fetch()
    if not data:
        return jsonify({'messages': [], 'track_state': '0', 'track_state_name': 'GREEN'})
    return jsonify({
        'messages':          data.get('race_control', []),
        'track_state':       data.get('track_state', '0'),
        'track_state_name':  data.get('track_state_name', 'GREEN'),
        'track_state_color': data.get('track_state_color', '#00C040'),
        'track_state_key':   data.get('track_state_key', 'green'),
        'session_type':      data.get('session_type', 'race'),
        'session_label':     data.get('session_label', 'RACE'),
    })


# Legacy alias
@racing.route('/api/racing/nurburgring')
def nurburgring_data_alias():
    return indycar_data()

"""Racing UI and API routes."""

import os
from flask import Blueprint, jsonify, render_template
from ..fetchers.racing_nurburgring import (
    n24_fetcher as _n24_fetcher,
    MANUFACTURER_COLORS,
    CLASS_COLORS,
)

_TMPL_DIR = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'templates')

racing = Blueprint('racing', __name__, template_folder=_TMPL_DIR)


@racing.route('/racing/nurburgring')
def nurburgring_ui():
    return render_template('racing/nurburgring.html')


@racing.route('/api/racing/nurburgring')
def nurburgring_data():
    data = _n24_fetcher.fetch()
    if not data:
        return jsonify({
            'status':            'no_data',
            'event_name':        '54. ADAC RAVENOL 24h Nürburgring',
            'leader_laps':       0,
            'entries':           [],
            'race_control':      [],
            'track_state':       '0',
            'track_state_name':  'GREEN FLAG',
            'track_state_color': '#00C040',
            'track_state_key':   'green',
            'fetched_at':        0,
        })
    return jsonify(_n24_fetcher.enrich(data))


@racing.route('/api/racing/nurburgring/racecontrol')
def nurburgring_racecontrol():
    data = _n24_fetcher.fetch()
    if not data:
        return jsonify({'messages': [], 'track_state': '0', 'track_state_name': 'GREEN FLAG'})
    return jsonify({
        'messages':          data.get('race_control', []),
        'track_state':       data.get('track_state', '0'),
        'track_state_name':  data.get('track_state_name', 'GREEN FLAG'),
        'track_state_color': data.get('track_state_color', '#00C040'),
        'track_state_key':   data.get('track_state_key', 'green'),
    })


@racing.route('/api/racing/nurburgring/colors')
def nurburgring_colors():
    """Return full manufacturer and class color maps for client use."""
    return jsonify({
        'manufacturers': MANUFACTURER_COLORS,
        'classes':       CLASS_COLORS,
    })

import os
import threading
import time
from flask import request, jsonify
from ..routes_runtime import app
from ..core import (
    state, tickers, data_lock,
    resolve_ticker_id,
    _maybe_update_ticker_timezone_from_request, _extract_timezone_from_request_headers,
    _extract_client_ip, _lookup_timezone_for_ip,
    _lookup_timezone_for_current_connection, _lookup_timezone_for_latlon,
    _get_ticker_timezone_context,
)
from ..workers import sync_test_mode_from_state
from ..fetchers_runtime import TestMode

@app.route('/api/timezone', methods=['GET'])
@app.route('/timezone', methods=['GET'])
def api_timezone_debug():
    """
    Debug endpoint for ticker timezone resolution.
    Query params:
      - id: ticker id (optional; inferred from X-Client-ID or single-ticker fallback)
      - refresh: 1/true to force running timezone update pipeline for this request
    """
    ticker_id = request.args.get('id')
    if not ticker_id:
        cid = request.headers.get('X-Client-ID')
        ticker_id = resolve_ticker_id(client_id=cid)

    if not ticker_id or ticker_id not in tickers:
        return jsonify({
            "status": "error",
            "message": "Ticker not found. Provide ?id=<ticker_id>",
            "known_tickers": list(tickers.keys())[:20]
        }), 404

    refresh_raw = str(request.args.get('refresh', '')).strip().lower()
    do_refresh = refresh_raw in ('1', 'true', 'yes', 'y', 'on')

    if do_refresh:
        _maybe_update_ticker_timezone_from_request(ticker_id, request)

    rec = tickers[ticker_id]
    settings = rec.get('settings', {}) if isinstance(rec, dict) else {}

    hdr_tz, hdr_offset = _extract_timezone_from_request_headers(request)
    client_ip = _extract_client_ip(request)

    ip_lookup = None
    if client_ip:
        ip_tz, ip_off = _lookup_timezone_for_ip(client_ip)
        ip_lookup = {
            "ip": client_ip,
            "timezone": ip_tz,
            "utc_offset": ip_off}

    self_tz, self_off, self_ip = _lookup_timezone_for_current_connection()

    lat = settings.get('weather_lat', state.get('weather_lat'))
    lon = settings.get('weather_lon', state.get('weather_lon'))
    ll_tz, ll_off = _lookup_timezone_for_latlon(lat, lon)

    effective_tz, effective_off = _get_ticker_timezone_context(rec)

    return jsonify({
        "status": "ok",
        "ticker_id": ticker_id,
        "refresh_applied": do_refresh,
        "request_inputs": {
            "query": {
                "timezone_name": request.args.get('timezone_name'),
                "utc_offset": request.args.get('utc_offset'),
                "tz": request.args.get('tz'),
                "offset": request.args.get('offset'),
            },
            "headers": {
                "X-Client-ID": request.headers.get('X-Client-ID'),
                "X-Ticker-Timezone": request.headers.get('X-Ticker-Timezone'),
                "X-Ticker-Utc-Offset": request.headers.get('X-Ticker-Utc-Offset'),
                "X-Timezone": request.headers.get('X-Timezone'),
                "X-UTC-Offset": request.headers.get('X-UTC-Offset'),
                "X-Forwarded-For": request.headers.get('X-Forwarded-For'),
                "X-Real-IP": request.headers.get('X-Real-IP'),
                "CF-Connecting-IP": request.headers.get('CF-Connecting-IP'),
            },
            "resolved_from_request": {
                "header_timezone": hdr_tz,
                "header_utc_offset": hdr_offset,
                "client_ip": client_ip,
                "remote_addr": request.remote_addr}
        },
        "stored": {
            "settings.timezone_name": settings.get('timezone_name'),
            "settings.utc_offset": settings.get('utc_offset'),
            "rec.timezone_name": rec.get('timezone_name'),
            "rec.last_ip": rec.get('last_ip'),
            "weather_lat": lat,
            "weather_lon": lon,
        },
        "lookups": {
            "ip_lookup": ip_lookup,
            "current_connection_lookup": {
                "ip": self_ip,
                "timezone": self_tz,
                "utc_offset": self_off,
            },
            "latlon_lookup": {
                "timezone": ll_tz,
                "utc_offset": ll_off}
        },
        "effective": {
            "timezone_name": effective_tz,
            "utc_offset": effective_off}
    })


@app.route('/api/hardware', methods=['POST'])
def api_hardware():
    try:
        data = request.json or {}
        action = data.get('action')
        ticker_id = data.get('ticker_id')
        
        # NEW: Handle Update Action
        if action == 'update':
            with data_lock:
                for t in tickers.values(): t['update_requested'] = True
            threading.Timer(60, lambda: [t.update({'update_requested':False}) for t in tickers.values()]).start()
            return jsonify({"status": "ok", "message": "Updating Fleet"})

        if action == 'reboot':
            if ticker_id and ticker_id in tickers:
                with data_lock:
                    tickers[ticker_id]['reboot_requested'] = True
                def clear_flag(tid):
                    with data_lock:
                        if tid in tickers: tickers[tid]['reboot_requested'] = False
                threading.Timer(15, clear_flag, args=[ticker_id]).start()
                return jsonify({"status": "ok", "message": f"Rebooting {ticker_id}"})
            elif len(tickers) > 0:
                target = list(tickers.keys())[0]
                with data_lock:
                    tickers[target]['reboot_requested'] = True
                threading.Timer(15, lambda: tickers[target].update({'reboot_requested': False})).start()
                return jsonify({"status": "ok"})
                
        return jsonify({"status": "ignored"})
    except Exception as e:
        print(f"Hardware API Error: {e}")
        return jsonify({"status": "error"}), 500


@app.route('/api/debug', methods=['GET', 'POST'])
def api_debug():
    if request.method == 'POST':
        payload = request.json or {}
        with data_lock:
            state.update(payload)
        # Sync TestMode whenever any relevant key was sent
        if any(k.startswith('test_') or k in ('debug_mode', 'custom_date') for k in payload):
            sync_test_mode_from_state()
        return jsonify({"status": "ok"})
    else:
        # GET: return current debug / test mode snapshot
        with data_lock:
            debug_snap = {
                'debug_mode': state.get('debug_mode'),
                'custom_date': state.get('custom_date'),
                'show_debug_options': state.get('show_debug_options')}
        return jsonify({
            "state_debug": debug_snap,
            "test_mode": TestMode.status(),
        })


@app.route('/errors', methods=['GET'])
def get_logs():
    log_file = "ticker.log"
    if not os.path.exists(log_file):
        return "Log file not found", 404
    try:
        file_size = os.path.getsize(log_file)
        read_size = min(file_size, 102400) 
        log_content = ""
        with open(log_file, 'rb') as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
            data = f.read()
            log_content = data.decode('utf-8', errors='replace')

        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Logs</title><meta http-equiv="refresh" content="10"></head>
        <body style="background:#111;color:#0f0;font-family:monospace;padding:20px;">
            <pre>{log_content}</pre>
            <script>window.scrollTo(0,document.body.scrollHeight);</script>
        </body></html>
        """
        return app.response_class(response=html_response, status=200, mimetype='text/html')
    except Exception as e:
        return f"Error: {str(e)}", 500



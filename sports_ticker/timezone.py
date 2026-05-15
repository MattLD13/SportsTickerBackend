"""Timezone detection, resolution, and application for ticker requests."""

import ipaddress
import time
from datetime import datetime as dt, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import requests

# Imported from core — loaded before any route triggers this module.
from .core import state, tickers, data_lock, save_specific_ticker, TIMEOUTS, parse_iso

_IP_TZ_CACHE: dict = {}
_IP_TZ_CACHE_TTL = 12 * 3600  # 12 hours


def _extract_client_ip(req) -> str | None:
    def _normalize_public_ip(raw: str) -> str | None:
        raw_ip = (raw or '').strip()
        if not raw_ip:
            return None
        if raw_ip.lower().startswith('::ffff:'):
            raw_ip = raw_ip[7:]
        if '%' in raw_ip:
            raw_ip = raw_ip.split('%', 1)[0]
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
            if any([
                ip_obj.is_private, ip_obj.is_loopback, ip_obj.is_link_local,
                ip_obj.is_reserved, ip_obj.is_multicast, ip_obj.is_unspecified,
            ]):
                return None
            return str(ip_obj)
        except Exception:
            return None

    for h in ('CF-Connecting-IP', 'X-Forwarded-For', 'X-Real-IP'):
        v = (req.headers.get(h) or '').strip()
        if v:
            for part in v.split(','):
                pub = _normalize_public_ip(part)
                if pub:
                    return pub
    return _normalize_public_ip(req.remote_addr or '')


def _utc_offset_hours_for_timezone(tz_name: str | None) -> float | None:
    if not tz_name or not ZoneInfo:
        return None
    try:
        now_local = dt.now(ZoneInfo(tz_name))
        off = now_local.utcoffset()
        if off is None:
            return None
        return round(off.total_seconds() / 3600.0, 2)
    except Exception:
        return None


def _extract_timezone_from_request_headers(req) -> tuple[str | None, float | None]:
    tz_raw = str(
        req.headers.get('X-Ticker-Timezone')
        or req.headers.get('X-Timezone')
        or req.args.get('timezone_name')
        or req.args.get('tz')
        or ''
    ).strip()
    off_raw = (
        req.headers.get('X-Ticker-Utc-Offset')
        or req.headers.get('X-UTC-Offset')
        or req.args.get('utc_offset')
        or req.args.get('offset')
    )

    tz_name = None
    if tz_raw:
        if ZoneInfo:
            try:
                ZoneInfo(tz_raw)
                tz_name = tz_raw
            except Exception:
                tz_name = None
        if tz_name is None and len(tz_raw) <= 64:
            tz_name = tz_raw

    offset = None
    if off_raw is not None:
        try:
            offset = round(float(off_raw), 2)
            if offset < -14 or offset > 14:
                offset = None
        except Exception:
            offset = None

    if offset is None and tz_name:
        offset = _utc_offset_hours_for_timezone(tz_name)

    return tz_name, offset


def _lookup_timezone_for_ip(ip_addr: str) -> tuple[str | None, float | None]:
    now_ts = time.time()
    cached = _IP_TZ_CACHE.get(ip_addr)
    if cached and (now_ts - cached.get('ts', 0) < _IP_TZ_CACHE_TTL):
        return cached.get('timezone'), cached.get('offset')

    try:
        resp = requests.get(
            f"https://ip-api.com/json/{ip_addr}",
            params={"fields": "status,timezone,offset,message,query"},
            timeout=TIMEOUTS.get('quick', 3),
        )
        data = resp.json() if resp.ok else {}
        if data.get('status') == 'success' and data.get('timezone'):
            tz_name = str(data['timezone']).strip()
            offset_raw = data.get('offset')
            offset_hours = round(float(offset_raw) / 3600.0, 2) if isinstance(offset_raw, (int, float)) else None
            if offset_hours is None:
                offset_hours = _utc_offset_hours_for_timezone(tz_name)
            _IP_TZ_CACHE[ip_addr] = {'timezone': tz_name, 'offset': offset_hours, 'ts': now_ts}
            return tz_name, offset_hours
    except Exception as e:
        print(f"[TZ] ip-api lookup failed for {ip_addr}: {e}")

    return None, None


def _lookup_timezone_for_current_connection() -> tuple[str | None, float | None, str | None]:
    """Fallback when client IP is private/local — resolves from current egress IP."""
    cache_key = '__self__'
    now_ts = time.time()
    cached = _IP_TZ_CACHE.get(cache_key)
    if cached and (now_ts - cached.get('ts', 0) < _IP_TZ_CACHE_TTL):
        return cached.get('timezone'), cached.get('offset'), cached.get('query')

    try:
        resp = requests.get(
            "https://ip-api.com/json/",
            params={"fields": "status,query,timezone,offset,message"},
            timeout=TIMEOUTS.get('quick', 3),
        )
        data = resp.json() if resp.ok else {}
        if data.get('status') == 'success' and data.get('timezone'):
            tz_name = str(data['timezone']).strip()
            query_ip = str(data.get('query') or '').strip() or None
            offset_raw = data.get('offset')
            offset_hours = round(float(offset_raw) / 3600.0, 2) if isinstance(offset_raw, (int, float)) else None
            if offset_hours is None:
                offset_hours = _utc_offset_hours_for_timezone(tz_name)
            _IP_TZ_CACHE[cache_key] = {'timezone': tz_name, 'offset': offset_hours, 'query': query_ip, 'ts': now_ts}
            return tz_name, offset_hours, query_ip
    except Exception as e:
        print(f"[TZ] ip-api self lookup failed: {e}")

    return None, None, None


def _lookup_timezone_for_latlon(lat: float, lon: float) -> tuple[str | None, float | None]:
    """Resolve timezone from lat/lon via open-meteo (last-resort fallback)."""
    try:
        lat_f, lon_f = float(lat), float(lon)
    except Exception:
        return None, None

    cache_key = f"__latlon__:{round(lat_f, 3)},{round(lon_f, 3)}"
    now_ts = time.time()
    cached = _IP_TZ_CACHE.get(cache_key)
    if cached and (now_ts - cached.get('ts', 0) < _IP_TZ_CACHE_TTL):
        return cached.get('timezone'), cached.get('offset')

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat_f, "longitude": lon_f, "current": "temperature_2m", "timezone": "auto"},
            timeout=TIMEOUTS.get('quick', 3),
        )
        data = resp.json() if resp.ok else {}
        tz_name = str(data.get('timezone') or '').strip()
        if not tz_name:
            return None, None
        off = _utc_offset_hours_for_timezone(tz_name)
        _IP_TZ_CACHE[cache_key] = {'timezone': tz_name, 'offset': off, 'ts': now_ts}
        return tz_name, off
    except Exception as e:
        print(f"[TZ] lat/lon timezone lookup failed ({lat_f},{lon_f}): {e}")
        return None, None


def _get_ticker_timezone_context(rec: dict) -> tuple[str, float]:
    settings = rec.get('settings', {}) if isinstance(rec, dict) else {}
    tz_name = str(settings.get('timezone_name') or rec.get('timezone_name') or '').strip()

    offset = settings.get('utc_offset', None)
    try:
        offset = float(offset)
    except Exception:
        offset = None

    if tz_name:
        live_offset = _utc_offset_hours_for_timezone(tz_name)
        if live_offset is not None:
            offset = live_offset
    if offset is None:
        offset = float(state.get('utc_offset', -5))

    return tz_name, offset


def _apply_ticker_timezone(rec: dict, tz_name: str | None, offset: float | None) -> bool:
    """Apply timezone/offset to a ticker record. Returns True if anything changed."""
    settings = rec.setdefault('settings', {})
    changed = False
    if tz_name and settings.get('timezone_name') != tz_name:
        settings['timezone_name'] = tz_name
        changed = True
    if offset is not None and settings.get('utc_offset') != offset:
        settings['utc_offset'] = offset
        changed = True
    if tz_name and rec.get('timezone_name') != tz_name:
        rec['timezone_name'] = tz_name
        changed = True
    return changed


def _maybe_update_ticker_timezone_from_request(ticker_id: str, req) -> None:
    if not ticker_id or ticker_id not in tickers:
        return

    rec = tickers[ticker_id]

    hdr_tz, hdr_offset = _extract_timezone_from_request_headers(req)
    if hdr_tz or hdr_offset is not None:
        changed = _apply_ticker_timezone(rec, hdr_tz, hdr_offset)
        if changed:
            off_txt = f"UTC{hdr_offset:+}" if isinstance(hdr_offset, (int, float)) else "UTC?"
            print(f"[TZ] Ticker {ticker_id} timezone set from ticker headers: {hdr_tz or 'unknown'} ({off_txt})")
            save_specific_ticker(ticker_id)
        if hdr_tz:
            return

    ip_addr = _extract_client_ip(req)

    if not ip_addr:
        tz_name, offset, query_ip = _lookup_timezone_for_current_connection()
        if tz_name:
            if offset is None:
                offset = _utc_offset_hours_for_timezone(tz_name)
            changed = _apply_ticker_timezone(rec, tz_name, offset)
            if query_ip and rec.get('last_ip') != query_ip:
                rec['last_ip'] = query_ip
                changed = True
            if changed:
                off_txt = f"UTC{offset:+}" if isinstance(offset, (int, float)) else "UTC?"
                print(f"[TZ] Ticker {ticker_id} timezone set to {tz_name} ({off_txt}) from fallback IP {query_ip or 'unknown'}")
                save_specific_ticker(ticker_id)

    prev_ip = str(rec.get('last_ip', '')).strip()
    prev_tz = str(rec.get('settings', {}).get('timezone_name', '')).strip()

    if ip_addr == prev_ip and prev_tz:
        off = _utc_offset_hours_for_timezone(prev_tz)
        if off is not None and rec.get('settings', {}).get('utc_offset') != off:
            rec['settings']['utc_offset'] = off
            print(f"[TZ] Ticker {ticker_id} offset refreshed from timezone {prev_tz}: UTC{off:+}")
            save_specific_ticker(ticker_id)
        return

    if ip_addr:
        tz_name, offset = _lookup_timezone_for_ip(ip_addr)
        if tz_name:
            if offset is None:
                offset = _utc_offset_hours_for_timezone(tz_name)
            changed = _apply_ticker_timezone(rec, tz_name, offset)
            if rec.get('last_ip') != ip_addr:
                rec['last_ip'] = ip_addr
                changed = True
            if changed:
                off_txt = f"UTC{offset:+}" if isinstance(offset, (int, float)) else "UTC?"
                print(f"[TZ] Ticker {ticker_id} timezone set to {tz_name} ({off_txt}) from IP {ip_addr}")
                save_specific_ticker(ticker_id)

    settings = rec.setdefault('settings', {})
    lat = settings.get('weather_lat', state.get('weather_lat'))
    lon = settings.get('weather_lon', state.get('weather_lon'))
    ll_tz, ll_off = _lookup_timezone_for_latlon(lat, lon)
    if not ll_tz:
        return

    ll_changed = _apply_ticker_timezone(rec, ll_tz, ll_off)
    if ll_changed:
        off_txt = f"UTC{ll_off:+}" if isinstance(ll_off, (int, float)) else "UTC?"
        print(f"[TZ] Ticker {ticker_id} timezone set from weather coords ({lat},{lon}): {ll_tz} ({off_txt})")
        save_specific_ticker(ticker_id)


def _apply_timezone_to_game_times(games: list, tz_name: str = '', utc_offset: float = -5.0) -> None:
    if not isinstance(games, list):
        return

    tz_obj = None
    if tz_name and ZoneInfo:
        try:
            tz_obj = ZoneInfo(tz_name)
        except Exception:
            tz_obj = None

    try:
        offset_hours = float(utc_offset)
    except Exception:
        offset_hours = -5.0

    fallback_tz = timezone(timedelta(hours=offset_hours))

    for g in games:
        if not isinstance(g, dict):
            continue
        if g.get('state') != 'pre':
            continue
        start_utc = g.get('startTimeUTC')
        if not start_utc:
            continue
        try:
            game_dt = parse_iso(start_utc)
            local_dt = game_dt.astimezone(tz_obj) if tz_obj else game_dt.astimezone(fallback_tz)
            g['status'] = local_dt.strftime("%I:%M %p").lstrip('0')
        except Exception:
            continue

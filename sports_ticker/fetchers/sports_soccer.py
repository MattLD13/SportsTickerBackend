from .. import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})
from .test_mode import TestMode

class SportsSoccerMixin:
    def parse_fotmob_goal_and_card_events(self, payload):
        """Extract goal scorers and red/second-yellow cards from a FotMob matchDetails payload."""
        try:
            events_dict = (payload.get("content") or {}).get("matchFacts", {}).get("events", {})
            if not isinstance(events_dict, dict):
                return [], []
            events = events_dict.get("events") or []
            if not isinstance(events, list):
                return [], []

            goal_events, red_cards = [], []

            for ev in events:
                if not isinstance(ev, dict):
                    continue
                ev_type = str(ev.get("type") or "").strip()
                is_home = ev.get("isHome")
                if is_home is None:
                    continue
                is_home = bool(is_home)

                # Time — FotMob may send int minutes or a nested dict
                time_raw = ev.get("time") or ev.get("minute") or 0
                if isinstance(time_raw, dict):
                    time_int = int(time_raw.get("minute") or time_raw.get("s", 0) // 60)
                else:
                    try:
                        time_int = int(time_raw)
                    except (ValueError, TypeError):
                        time_int = 0

                added_raw = ev.get("addedTime") or ev.get("extra_time") or 0
                try:
                    added_int = int(added_raw)
                except (ValueError, TypeError):
                    added_int = 0

                time_str = f"{time_int}+{added_int}'" if added_int else (f"{time_int}'" if time_int else "")

                # Player name — may be a string or a nested object
                player_raw = ev.get("player") or ev.get("playerName") or ""
                if isinstance(player_raw, dict):
                    player_name = str(player_raw.get("name") or player_raw.get("short") or "").strip()
                else:
                    player_name = str(player_raw).strip()

                # Keep only the last name, upper-cased, max 8 chars
                parts = [p for p in player_name.split() if p]
                player_last = parts[-1].upper()[:8] if parts else ""

                if ev_type == "Goal":
                    sub = str(ev.get("subType") or "").lower()
                    is_og = "own" in sub or ev.get("ownGoal") is True
                    goal_events.append({
                        "player": player_last,
                        "time": time_str,
                        "is_home": is_home,
                        "own_goal": is_og,
                    })

                elif ev_type == "Card":
                    card = str(ev.get("card") or "").lower()
                    is_red = ("red" in card and "yellow" not in card) or ("yellow" in card and "red" in card)
                    if is_red:
                        red_cards.append({
                            "player": player_last,
                            "time": time_str,
                            "is_home": is_home,
                        })

            return goal_events, red_cards
        except Exception:
            return [], []
    def _fetch_fotmob_details(self, match_id, home_id=None, away_id=None):
        """Fetch matchDetails and return shootout data plus goal/card events.

        Returns dict with keys:
          'shootout'    — {'home': [...], 'away': [...]} or None
          'goal_events' — list of goal dicts
          'red_cards'   — list of red card dicts
        Returns None on network failure.
        """
        try:
            payload = None
            detail_urls = [
                f"https://www.fotmob.com/api/data/matchDetails?matchId={match_id}",
                f"https://www.fotmob.com/api/matchDetails?matchId={match_id}",
            ]
            for url in detail_urls:
                try:
                    resp = self.session.get(url, headers=HEADERS, timeout=TIMEOUTS['slow'])
                    resp.raise_for_status()
                    payload = resp.json()
                    break
                except Exception:
                    continue
            if not isinstance(payload, dict):
                return None

            info = payload.get("general", {})
            general_home = (info.get("homeTeam") or {}).get("id")
            general_away = (info.get("awayTeam") or {}).get("id")

            # ── Shootout ──────────────────────────────────────────────────────
            containers = [
                payload.get("shootout"),
                payload.get("content", {}).get("shootout"),
                payload.get("content", {}).get("penaltyShootout"),
            ]
            home_shootout, away_shootout = [], []
            for raw in containers:
                h, a, _, _ = self.parse_shootout(raw, home_id, away_id, general_home, general_away)
                if h or a:
                    home_shootout, away_shootout = h, a
                    break
            if not home_shootout and not away_shootout and payload.get("content", {}).get("matchFacts"):
                events_container = payload["content"].get("matchFacts", {}).get("events")
                h, a, _, _ = self.parse_shootout_events(events_container, home_id, away_id, general_home, general_away)
                if h or a:
                    home_shootout, away_shootout = h, a

            # ── Goal / card events ────────────────────────────────────────────
            goal_events, red_cards = self.parse_fotmob_goal_and_card_events(payload)

            return {
                'shootout': {'home': home_shootout, 'away': away_shootout} if (home_shootout or away_shootout) else None,
                'goal_events': goal_events,
                'red_cards': red_cards,
            }
        except Exception:
            return None

    def _parse_score_str(self, score_str):
        if not score_str or "-" not in str(score_str):
            return None, None
        try:
            home_raw, away_raw = [part.strip() for part in str(score_str).split("-", 1)]
            home_val = int(home_raw) if home_raw.isdigit() else None
            away_val = int(away_raw) if away_raw.isdigit() else None
            return home_val, away_val
        except Exception:
            return None, None

    def _format_live_clock(self, status: dict, fallback_text: str = "") -> str | None:
        def _render_clock(minutes: int, seconds: int, max_time: int | None) -> str:
            if max_time is not None and minutes > max_time:
                extra_total = minutes * 60 + seconds - max_time * 60
                extra_min, extra_sec = divmod(extra_total, 60)
                return f"{max_time}+{extra_min:02d}:{extra_sec:02d}'"
            return f"{minutes:02d}:{seconds:02d}'"

        if not isinstance(status, dict):
            return None

        live_time = status.get("liveTime") or status.get("live_time") or {}
        max_time = None
        if isinstance(live_time, dict):
            max_time_raw = live_time.get("maxTime") or live_time.get("max_time")
            if isinstance(max_time_raw, (int, float)) or (isinstance(max_time_raw, str) and max_time_raw.isdigit()):
                max_time = int(float(max_time_raw))

            long_val = live_time.get("long") or live_time.get("clock") or live_time.get("elapsed")
            if long_val:
                text = str(long_val)
                plus_match = re.match(r"\s*(\d+)\+(\d+)(?::(\d{1,2}))?", text)
                if plus_match:
                    base = int(plus_match.group(1))
                    extra_min = int(plus_match.group(2))
                    extra_sec = int(plus_match.group(3) or 0)
                    return f"{base}+{extra_min:02d}:{extra_sec:02d}'"

                clock_match = re.match(r"\s*(\d+):(\d{1,2})", text)
                if clock_match:
                    minutes = int(clock_match.group(1))
                    seconds = int(clock_match.group(2))
                    return _render_clock(minutes, seconds, max_time)

            minute_val = live_time.get("minute")
            second_val = live_time.get("second")
            if minute_val is not None and second_val is not None:
                try:
                    minutes = int(minute_val)
                    seconds = int(second_val)
                    return _render_clock(minutes, seconds, max_time)
                except Exception:
                    pass

            short_val = live_time.get("short")
            if short_val:
                short_match = re.match(r"\s*(\d+)(?:\+(\d+))?'", str(short_val))
                if short_match:
                    base = int(short_match.group(1))
                    extra = int(short_match.group(2) or 0)
                    if extra:
                        return f"{base}+{extra:02d}:00'"
                    return f"{base:02d}:00'"

        if fallback_text:
            text = str(fallback_text)
            text_match = re.search(r"(\d+)(?:\+(\d+))?'", text)
            if text_match:
                base = int(text_match.group(1))
                extra = int(text_match.group(2) or 0)
                if extra:
                    return f"{base}+{extra:02d}:00'"
                return f"{base:02d}:00'"

        return None

    def _extract_matches(self, sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc):
        matches = []
        seen_match_ids = set()
        _local_tz = timezone(timedelta(hours=conf.get('utc_offset', -5)))
        for section in sections:
            candidate_matches = section.get("matches") if isinstance(section, dict) else None
            if candidate_matches is None: candidate_matches = [section]
            
            for match in candidate_matches:
                if not isinstance(match, dict): continue
                
                status = match.get("status") or {}
                kickoff = status.get("utcTime") or match.get("time")
                if not kickoff: continue
                
                try:
                    match_dt = parse_iso(kickoff)
                    if not (start_window <= match_dt <= end_window): continue
                except: continue

                mid = match.get("id")
                if mid in seen_match_ids: continue
                seen_match_ids.add(mid)
                
                h_name = match.get("home", {}).get("name") or "Home"
                a_name = match.get("away", {}).get("name") or "Away"
                
                h_ab = SOCCER_ABBR_OVERRIDES.get(h_name, h_name[:3].upper())
                a_ab = SOCCER_ABBR_OVERRIDES.get(a_name, a_name[:3].upper())
                
                finished = bool(status.get("finished"))
                started = bool(status.get("started"))
                reason = (status.get("reason") or {}).get("short") or ""
                
                home_score = (match.get("home") or {}).get("score")
                away_score = (match.get("away") or {}).get("score")

                status_score = status.get("score") or status.get("current") or {}
                if isinstance(status_score, dict):
                    if home_score is None: home_score = status_score.get("home")
                    if away_score is None: away_score = status_score.get("away")
                    
                    for key in ("ft", "fulltime"):
                        ft_score = status_score.get(key)
                        if isinstance(ft_score, (list, tuple)) and len(ft_score) >= 2:
                            if home_score is None: home_score = ft_score[0]
                            if away_score is None: away_score = ft_score[1]
                elif isinstance(status_score, (list, tuple)) and len(status_score) >= 2:
                    if home_score is None: home_score = status_score[0]
                    if away_score is None: away_score = status_score[1]

                score_str_sources = [
                    status.get("scoreStr"),
                    (match.get("home") or {}).get("scoreStr"),
                    (match.get("away") or {}).get("scoreStr"),
                    status.get("statusText") if "-" in str(status.get("statusText", "")) else None 
                ]

                for s_str in score_str_sources:
                    if home_score is not None and away_score is not None: break
                    h_val, a_val = self._parse_score_str(s_str)
                    if home_score is None: home_score = h_val
                    if away_score is None: away_score = a_val

                final_home_score = str(home_score) if home_score is not None else "0"
                final_away_score = str(away_score) if away_score is not None else "0"

                gst = 'pre'
                
                try:
                    k_dt = parse_iso(kickoff)
                    local_k = k_dt.astimezone(_local_tz)
                    disp = local_k.strftime("%I:%M %p").lstrip('0')
                except:
                    disp = kickoff.split("T")[1][:5]

                if started and not finished:
                    gst = 'in'
                    clock_str = self._format_live_clock(status, match.get("status_text"))
                    if clock_str:
                        disp = clock_str
                    else:
                        disp = "In Progress"
                    
                    current_minute = 0
                    try:
                        current_minute = int((status.get("liveTime") or {}).get("minute", 0))
                    except: pass

                    raw_status_text = str(status.get("statusText", ""))
                    is_ht = (
                        reason == "HT" 
                        or raw_status_text == "HT" 
                        or "Halftime" in raw_status_text
                        or status.get("liveTime", {}).get("short") == "HT"
                        or reason == "PET" 
                    )
                    
                    if is_ht:
                        if current_minute >= 105:
                            disp = "HT ET"
                        else:
                            disp = "HALF"

                elif finished:
                    gst = 'post'
                    disp = "Final" 
                    if "AET" in reason: disp = "Final AET"
                    if "Pen" in reason or (status.get("reason") and "Pen" in str(status.get("reason"))):
                        disp = "FIN"

                elif status.get("cancelled"):
                    gst = 'post'
                    disp = "Postponed"
                
                if "Postponed" in reason or "PPD" in reason:
                    gst = 'post'
                    disp = "Postponed"

                if match_dt < visible_start_utc or match_dt >= visible_end_utc:
                      if gst != 'in': continue

                is_shootout = False
                if "Pen" in reason or (gst == 'in' and "Pen" in str(status)) or disp == "FIN":
                    is_shootout = True
                    if gst == 'in': disp = "Pens"
                
                # Fetch matchDetails for live and finished games to get goals, cards, and shootout data.
                details = None
                if gst in ('in', 'post'):
                    details = self._fetch_fotmob_details(mid, match.get("home", {}).get("id"), match.get("away", {}).get("id"))

                shootout_data  = (details or {}).get('shootout')
                goal_events    = (details or {}).get('goal_events') or []
                red_cards      = (details or {}).get('red_cards') or []

                is_shown = True
                if "Postponed" in disp or "PPD" in reason or status.get("cancelled"):
                    is_shown = False

                h_id = match.get("home", {}).get("id")
                a_id = match.get("away", {}).get("id")
                h_fotmob_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{h_id}.png" if h_id else None
                a_fotmob_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{a_id}.png" if a_id else None

                h_info = self.lookup_team_info_from_cache(internal_id, h_ab, h_name, logo=h_fotmob_logo)
                a_info = self.lookup_team_info_from_cache(internal_id, a_ab, a_name, logo=a_fotmob_logo)

                matches.append({
                    'type': 'scoreboard',
                    'sport': internal_id,
                    'id': str(mid),
                    'status': disp,
                    'state': gst,
                    'is_shown': is_shown,
                    'home_abbr': h_ab, 'home_score': final_home_score,
                    'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{h_id}.png",
                    'away_abbr': a_ab, 'away_score': final_away_score,
                    'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{a_id}.png",
                    'home_color': f"#{h_info['color']}", 'home_alt_color': f"#{h_info['alt_color']}",
                    'away_color': f"#{a_info['color']}", 'away_alt_color': f"#{a_info['alt_color']}",
                    'startTimeUTC': kickoff,
                    'estimated_duration': 115,
                    'situation': {
                        'possession': '',
                        'shootout': shootout_data,
                        'goal_events': goal_events,
                        'red_cards': red_cards,
                    }
                })
        return matches

    def _fetch_fotmob_league(self, league_id, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc):
        try:
            url = "https://www.fotmob.com/api/data/matches"
            # Fetch day-by-day within the requested window because FotMob's new endpoint is date-scoped.
            start_date = start_window.date()
            end_date = end_window.date()
            day = start_date
            aggregate_sections = []

            while day <= end_date:
                params = {
                    "date": day.strftime("%Y%m%d"),
                    "timezone": "UTC",
                    "ccode3": "USA"}
                try:
                    resp = self.session.get(url, params=params, headers=HEADERS, timeout=TIMEOUTS['slow'])
                    resp.raise_for_status()
                    payload = resp.json()
                    leagues = payload.get("leagues", []) if isinstance(payload, dict) else []

                    filtered_sections = []
                    for league in leagues:
                        if not isinstance(league, dict):
                            continue
                        ids = {
                            league.get("id"),
                            league.get("primaryId"),
                            league.get("parentLeagueId")}
                        if league_id in ids:
                            filtered_sections.append(league)

                    if filtered_sections:
                        aggregate_sections.extend(filtered_sections)
                except Exception:
                    pass

                day += timedelta(days=1)

            if aggregate_sections:
                return self._extract_matches(aggregate_sections, internal_id, conf, start_window, end_window, visible_start_utc, visible_end_utc)
            return []
        except Exception as e:
            print(f"FotMob League {league_id} error: {e}")
            return []


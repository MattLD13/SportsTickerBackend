"""Mode buffers, pinned-game refresh, and snapshot orchestration."""

import concurrent.futures
import time

from .. import core as _core

globals().update({k: v for k, v in vars(_core).items() if not k.startswith('__')})

from .sports_modes_buffers import SportsModesBuffersMixin
from .sports_modes_common import (
    SPORTS_LIKE_MODES,
    _mode_builder_registry,
    flight_tracker,
    spotify_fetcher,
)
from .sports_modes_pins import SportsModesPinsMixin

__all__ = [
    'SportsModesMixin',
    'SPORTS_LIKE_MODES',
    'flight_tracker',
    'spotify_fetcher',
]


class SportsModesMixin(SportsModesBuffersMixin, SportsModesPinsMixin):
    def update_current_games(self):
        """Build and cache content buffers for every mode currently needed by any ticker."""
        if not self._update_lock.acquire(blocking=False):
            self._update_pending.set()
            return

        try:
            while True:
                self._update_pending.clear()

                with data_lock:
                    global_mode = state.get('mode', 'sports')
                    active_modes = dict(state.get('active_modes', {}))
                    needed: set = {global_mode} if is_mode_enabled(global_mode, active_modes) else set()
                    for t in tickers.values():
                        m = t.get('settings', {}).get('mode')
                        if m and m in VALID_MODES and is_mode_enabled(m, active_modes):
                            needed.add(m)

                        t_settings = t.get('settings', {})
                        t_single_pin, t_pin_list = _normalize_single_pin(
                            pinned_game=t_settings.get('pinned_game'),
                            pinned_games=t_settings.get('pinned_games', []),
                        )
                        for _pin in t_pin_list:
                            pin_norm = str(_pin).strip().lower()
                            if not pin_norm:
                                continue
                            if ':' in pin_norm:
                                pin_league = pin_norm.split(':', 1)[0]
                            else:
                                pin_league = 'golf' if pin_norm.startswith(('golf', 'masters')) else ''
                            if pin_league in ('golf', 'masters'):
                                if is_mode_enabled('golf', active_modes):
                                    needed.add('golf')
                                break
                            if pin_league == 'f1':
                                if is_mode_enabled('f1', active_modes):
                                    needed.add('f1')
                                break

                dispatch = _mode_builder_registry(self)

                sports_built = False
                for mode in needed:
                    is_sports = mode in SPORTS_LIKE_MODES

                    if is_sports and sports_built:
                        continue

                    builder = dispatch.get(mode, self._build_sports_buffer)
                    result = builder()

                    if is_sports:
                        sports_built = True
                        for sm in SPORTS_LIKE_MODES:
                            self._set_mode_buffer(sm, result)

                        snap = (time.time(), result[:])
                        self.history_buffer.append(snap)
                        if len(self.history_buffer) > 120:
                            self.history_buffer = self.history_buffer[-120:]

                        if result:
                            try:
                                save_json_atomically(GAME_CACHE_FILE, result)
                            except Exception:
                                pass
                    else:
                        self._set_mode_buffer(mode, result)

                with self._mode_buffer_lock:
                    global_result = self._mode_buffers.get(global_mode, [])
                is_global_sports = global_mode in SPORTS_LIKE_MODES
                with data_lock:
                    if global_result or not is_global_sports or not state.get('current_games'):
                        state['current_games'] = global_result

                if not self._update_pending.is_set():
                    break
        finally:
            self._update_lock.release()

    def get_snapshot_for_delay(self, delay_seconds):
        """Return current games, optionally from history buffer for live-delay."""
        with self._mode_buffer_lock:
            latest_sports = list(self._mode_buffers.get('sports', []))

        if delay_seconds <= 0:
            if latest_sports:
                return latest_sports
            with data_lock:
                return list(state.get('current_games', []))

        if not self.history_buffer:
            if latest_sports:
                return latest_sports
            with data_lock:
                return list(state.get('current_games', []))

        target_time = time.time() - delay_seconds
        chosen = None
        for ts, snapshot in reversed(self.history_buffer):
            if ts <= target_time:
                chosen = snapshot
                break

        if chosen is None and self.history_buffer:
            chosen = self.history_buffer[0][1]

        if chosen is None:
            return latest_sports

        return chosen

    def _set_mode_buffer(self, mode: str, result: list):
        with self._mode_buffer_lock:
            self._mode_buffers[mode] = result
        with data_lock:
            if state.get('mode') == mode:
                if result or not state.get('current_games'):
                    state['current_games'] = result

    def get_mode_snapshot(self, mode: str, delay_seconds: float = 0) -> list:
        with data_lock:
            if not is_mode_enabled(mode):
                return []

        if mode in SPORTS_LIKE_MODES:
            return self.get_snapshot_for_delay(delay_seconds)
        with self._mode_buffer_lock:
            snapshot = list(self._mode_buffers.get(mode, []))

        if snapshot:
            return snapshot

        builder = _mode_builder_registry(self).get(mode)
        if not builder:
            return []

        try:
            result = builder()
            self._set_mode_buffer(mode, result)
            return list(result)
        except Exception as e:
            print(f"[preview] on-demand buffer build failed for {mode}: {e}")
            return []

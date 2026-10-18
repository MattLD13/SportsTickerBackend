#pragma once
#include "sports_pane.h"
#include <cstdio>

namespace ticker_ui {
struct MusicPane {
  std::string title, artist, remaining;
  bool playing = false, idle = false;
  float fraction = 0;
  uint32_t scrollMs = 0;
  Rgb accent = {160, 175, 195};
};

template<class Canvas>
void musicMarquee(Canvas& canvas, const std::string& value, int y, Rgb ink, uint32_t ms, int speed) {
  const int left = 34, right = 64;
  if (textWidth(value) <= right - left) { text(canvas, value, left, y, ink, 3, 5, 1, false, left, right); return; }
  const std::string cycle = value + "    ";
  const int offset = ms < 1400 ? 0 : static_cast<int>((static_cast<uint64_t>(ms - 1400) * speed / 1000) % (textWidth(cycle) + 1));
  text(canvas, cycle + value, left - offset, y, ink, 3, 5, 1, false, left, right);
}

template<class Canvas>
void renderMusic(Canvas& canvas, const MusicPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  if (view.idle || !canvas.artwork()) {
    canvas.rect(0, 0, 32, 31, {12, 19, 27});
    const Rgb note{170, 190, 215};
    canvas.rect(12, 8, 2, 15, note);
    canvas.rect(22, 6, 2, 15, note);
    canvas.rect(12, 6, 12, 3, note);
    canvas.rect(7, 21, 7, 4, note);
    canvas.rect(17, 19, 7, 4, note);
  }
  const Rgb dim = {static_cast<uint8_t>(view.accent.r / 5), static_cast<uint8_t>(view.accent.g / 5), static_cast<uint8_t>(view.accent.b / 5)};
  canvas.rect(32, 0, 1, 32, dim);
  musicMarquee(canvas, view.title, 2, {245, 245, 255}, view.scrollMs, 10);
  musicMarquee(canvas, view.artist, 12, {155, 180, 205}, view.scrollMs, 7);
  const Rgb progress = view.accent;
  text(canvas, view.idle ? "SPOTIFY" : view.remaining, 34, 23, progress, 3, 5, 1, false, 34, 64);
  canvas.rect(0, 31, 64, 1, dim);
  const int filled = std::max(0, std::min(64, static_cast<int>(view.fraction * 64)));
  if (filled) canvas.rect(0, 31, filled, 1, progress);
}
}  // namespace ticker_ui

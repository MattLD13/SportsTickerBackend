#pragma once
#include "sports_pane.h"
#include <cstdio>

namespace ticker_ui {
struct MusicPane {
  std::string title, artist, remaining;
  bool playing = false;
  float fraction = 0;
  uint32_t scrollMs = 0;
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
  if (!canvas.artwork()) {
    canvas.rect(0, 0, 32, 32, {15, 22, 30});
    canvas.rect(18, 9, 2, 13, {105, 130, 150});
    canvas.rect(11, 9, 9, 2, {105, 130, 150});
    canvas.rect(10, 20, 10, 4, {105, 130, 150});
  }
  canvas.rect(32, 0, 1, 32, {30, 36, 45});
  musicMarquee(canvas, view.title, 2, {245, 245, 255}, view.scrollMs, 10);
  musicMarquee(canvas, view.artist, 12, {155, 180, 205}, view.scrollMs, 7);
  const Rgb progress = view.playing ? Rgb{60, 220, 125} : Rgb{150, 165, 185};
  text(canvas, view.remaining, 34, 23, progress, 3, 5, 1, false, 34, 64);
  canvas.rect(34, 31, 30, 1, {30, 40, 50});
  canvas.rect(34, 31, std::max(0, std::min(30, static_cast<int>(view.fraction * 30))), 1, progress);
}
}  // namespace ticker_ui

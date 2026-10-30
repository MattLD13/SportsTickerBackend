// Draw the cover or a note, the title and the artist, the time that remains, and the progress rail.
#pragma once

#include "text.h"

namespace mini_ui {

struct MusicPane {
  std::string title, artist, remaining;
  bool playing = false, idle = false;
  float fraction = 0;
  uint32_t scrollMs = 0;
  Rgb accent = {160, 175, 195};
};

namespace music {

static constexpr Motion titleMotion{1400, 10, 1000, 9}, artistMotion{1400, 7, 1000, 9};

template<class Canvas>
void note(Canvas& canvas) {
  const Rgb ink{170, 190, 215};
  canvas.rect(0, 0, 32, 31, {12, 19, 27});
  canvas.rect(12, 8, 2, 15, ink);
  canvas.rect(22, 6, 2, 15, ink);
  canvas.rect(12, 6, 12, 3, ink);
  canvas.rect(7, 21, 7, 4, ink);
  canvas.rect(17, 19, 7, 4, ink);
}

}  // namespace music

template<class Canvas>
void draw(Canvas& canvas, const MusicPane& view) {
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  if (view.idle || !canvas.artwork()) music::note(canvas);
  const Rgb dim = {static_cast<uint8_t>(view.accent.r / 5), static_cast<uint8_t>(view.accent.g / 5), static_cast<uint8_t>(view.accent.b / 5)};
  canvas.rect(32, 0, 1, PANE_HEIGHT, dim);
  marquee(canvas, view.title, 34, 64, 2, {245, 245, 255}, view.scrollMs, music::titleMotion, false);
  marquee(canvas, view.artist, 34, 64, 12, {155, 180, 205}, view.scrollMs, music::artistMotion, false);
  drawText(canvas, view.idle ? "SPOTIFY" : view.remaining, 34, 23, view.accent, {}, {34, 64});
  canvas.rect(0, 31, PANE_WIDTH, 1, dim);
  const int filled = std::max(0, std::min(PANE_WIDTH, static_cast<int>(view.fraction * PANE_WIDTH)));
  if (filled) canvas.rect(0, 31, filled, 1, view.accent);
}

}  // namespace mini_ui

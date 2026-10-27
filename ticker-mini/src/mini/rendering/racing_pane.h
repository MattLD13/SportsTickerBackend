// Render the compact V2 racing card without I/O.
#pragma once
#include <array>
#include <string>
#include "sports_pane.h"

namespace ticker_ui {
using ticker_ui::Rgb;
struct RacingRow {
  std::string car, name, gap;
  int position = 0;
  Rgb positionColor{235, 235, 235}, metricColor{180, 210, 255};
  Rgb numberColor{115, 180, 255}, numberOutline{0, 0, 0};
  bool outlined = false;
};
struct RacingPane {
  struct Signal {
    std::array<uint16_t, 25> pixels{};
    std::string label;
    bool showLabel = false;
    bool flashing = false;
  };
  std::string race, group, status;
  Signal signal;
  bool signalPresent = false;
  bool upcoming = false;
  std::array<RacingRow, 3> rows;
  int count = 0;
  unsigned elapsedMs = 0;
  unsigned signalPhaseMs = 0;
};

template<class Canvas> struct NumberClip {
  Canvas& canvas;
  void pixel(int x, int y, Rgb ink) {
    if (x >= 5 && x < 18 && y >= 12 && y < 32) canvas.pixel(x, y, ink);
  }
};

template<class Canvas>
void renderRacing(Canvas& canvas, const RacingPane& view) {
  using namespace ticker_ui;
  const Rgb blue{115, 180, 255};
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 0, 64, 6, {5, 12, 24});
  const int width = textWidth(view.race);
  int offset = 0;
  if (width > 62 && view.elapsedMs > 1500)
    offset = static_cast<int>((view.elapsedMs - 1500) / 90) % (width + 14);
  text(canvas, view.race, 1 - offset, 0, STATUS_TEXT, 3, 5, 1, false, 1, 63);
  if (width > 62)
    text(canvas, view.race, 1 - offset + width + 14, 0, STATUS_TEXT, 3, 5, 1, false, 1, 63);
  text(canvas, view.group, 1, 6, blue, 3, 5, 1, false, 1, 31);
  const auto& signal = view.signal;
  const std::string status = signal.showLabel ? signal.label : view.status;
  const int statusLeft = 56 - textWidth(status);
  text(canvas, status, statusLeft, 6, MUTED_TEXT, 3, 5, 1, false, 31, 56);
  for (int index = 0; index < 25; ++index) {
    const uint16_t rgb = signal.pixels[index];
    const int light = signal.flashing && (view.signalPhaseMs / 350) % 2 ? 1 : 3;
    canvas.pixel(59 + index % 5, 6 + index / 5, {
      static_cast<uint8_t>(((rgb >> 11) & 31) * 255 / 31 * light / 3),
      static_cast<uint8_t>(((rgb >> 5) & 63) * 255 / 63 * light / 3),
      static_cast<uint8_t>((rgb & 31) * 255 / 31 * light / 3)});
  }
  canvas.rect(0, 11, 64, 1, HEADER_RULE);
  if (!view.count) {
    centered(canvas, view.upcoming ? "STARTS" : "NO TIMES", 0, 64, 16, MUTED_TEXT);
    centered(canvas, view.status, 0, 64, 25, blue);
    return;
  }
  for (int index = 0; index < view.count && index < 3; ++index) {
    const auto& row = view.rows[index];
    const int y = 13 + index * 7;
    text(canvas, std::to_string(row.position), 0, y, row.positionColor, 3, 5, 1, false, 0, 4);
    if (row.outlined) {
      NumberClip<Canvas> clipped{canvas};
      for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
        if (dx == 0 && dy == 0) continue;
        text(clipped, row.car, 6 + dx, y + dy, row.numberOutline, 3, 5, 1, false, 5, 18);
      }
    }
    text(canvas, row.car, 6, y, row.numberColor, 3, 5, 1, false, 6, 18);
    text(canvas, row.name, 19, y, SCORE_TEXT, 3, 5, 1, false, 19, 32);
    const int metricLeft = 64 - textWidth(row.gap);
    text(canvas, row.gap, metricLeft, y, row.metricColor, 3, 5, 1, false, 33, 64);
  }
}
}  // namespace ticker_ui

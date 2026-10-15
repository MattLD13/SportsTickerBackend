#pragma once
#include "sports_pane.h"

namespace ticker_ui {
struct ClockPane {
  std::string date, time;
  int seconds = 0;
  bool ready = false;
};
struct StockPane {
  std::string symbol, price, percent, change;
};

template<class Canvas>
void renderClock(Canvas& canvas, const ClockPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  if (!view.ready) {
    centered(canvas, "SYNC", 0, 64, 12, STATUS_TEXT, 6, 10, 1);
    return;
  }
  centered(canvas, view.date, 0, 64, 0, CLOCK_DATE);
  centered(canvas, view.time, 0, 64, 9, SCORE_TEXT, 5, 18, 1);
  canvas.rect(0, 31, 64, 1, CLOCK_RAIL);
  canvas.rect(0, 31, std::max(0, std::min(59, view.seconds)) * 64 / 60, 1, CLOCK_PROGRESS);
}

template<class Canvas>
void renderStock(Canvas& canvas, const StockPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  const Rgb ink = view.percent.empty() || view.percent[0] != '-' ? STOCK_GAIN : STOCK_LOSS;
  text(canvas, view.symbol, 1, 1, SCORE_TEXT, 4, 6, 1, true);
  centered(canvas, view.price, 1, 62, 10, ink, 4, 12, 1, true);
  text(canvas, view.percent, 1, 25, ink, 4, 6, 1, true, 1, 32);
  text(canvas, view.change, 63 - textWidth(view.change, 4), 25, ink, 4, 6, 1, true, 33, 63);
}
}  // namespace ticker_ui

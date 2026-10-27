#pragma once
#include "sports_pane.h"
#include "system_pane.h"

namespace ticker_ui {
enum class PairingStage { WiFiSetup, AppPairing };
struct PairingPane {
  PairingStage stage = PairingStage::WiFiSetup;
  std::string code;
  uint32_t elapsedMs = 0;
};

inline PairingPane pairingPane(bool wifiSetup, const std::string& wifiPin, const std::string& appCode, uint32_t elapsedMs = 0) {
  PairingPane view;
  view.elapsedMs = elapsedMs;
  view.stage = wifiSetup ? PairingStage::WiFiSetup : PairingStage::AppPairing;
  view.code = wifiSetup ? wifiPin : appCode;
  return view;
}

template<class Canvas>
void renderPairing(Canvas& canvas, const PairingPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  const bool wifi = view.stage == PairingStage::WiFiSetup;
  canvas.rect(0, 31, 64, 1, {35, 45, 55});
  centered(canvas, wifi ? "WIFI PIN" : "PAIR CODE", 0, 64, 1, {255, 200, 0});
  if ((view.elapsedMs / 500) % 2 == 0) canvas.rect(60, 1, 2, 2, {0, 200, 255});
  centered(canvas, view.code.empty() ? "WAIT" : view.code, 0, 64, 11, SCORE_TEXT, 5, 9, 1);
  centered(canvas, wifi ? "OPEN APP" : "ADD TICKER", 0, 64, 26, {125, 165, 190});
}

struct ClockPane {
  std::string date, time;
  uint32_t elapsedMs = 0;
  int seconds = 0;
  bool ready = false;
};
struct StockPane {
  std::string symbol, price, percent;
};

template<class Canvas>
void renderClock(Canvas& canvas, const ClockPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  if (!view.ready) {
    renderSystem(canvas, systemPane(SystemKind::TimeSync, "SETTING TIME", 0, 0, view.elapsedMs));
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
  const bool known = !view.percent.empty() && view.percent != "--";
  const Rgb ink = !known ? MUTED_TEXT : view.percent[0] == '-' ? STOCK_LOSS : STOCK_GAIN;
  if (!canvas.logo(Side::Home, 1, 1)) badge(canvas, 1, 1, {28, 43, 58}, view.symbol.substr(0, 3));
  const int symbolWidth = textWidth(view.symbol, 4, 1) <= 42 ? 4 : 3;
  const int symbolGap = textWidth(view.symbol, symbolWidth, 1) <= 42 ? 1 : 0;
  text(canvas, view.symbol, 22, 1, SCORE_TEXT, symbolWidth, 7, symbolGap, false, 22, 64);
  const int percentGap = textWidth(view.percent, 3, 1) <= 36 ? 1 : 0;
  text(canvas, view.percent, 28, 12, ink, 3, 5, percentGap, false, 28, 64);
  const bool loss = !view.percent.empty() && view.percent[0] == '-';
  for (int row = 0; known && row < 3; ++row) {
    const int half = loss ? 2 - row : row;
    canvas.rect(23 - half / 2, 13 + row, half + 1, 1, ink);
  }
  canvas.rect(1, 20, 62, 1, {24, 35, 48});
  const int priceWidth = textWidth(view.price, 4, 1, true) <= 62 ? 4 : 3;
  text(canvas, view.price, 1, 23, SCORE_TEXT, priceWidth, 9, 1, true, 1, 63);
}
}  // namespace ticker_ui

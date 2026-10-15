#pragma once
#include "sports_pane.h"

namespace ticker_ui {
enum class PairingStage { WiFiSetup, AppPairing };
struct PairingPane {
  PairingStage stage = PairingStage::WiFiSetup;
  std::string code;
};

inline PairingPane pairingPane(bool wifiSetup, const std::string& wifiPin, const std::string& appCode) {
  PairingPane view;
  view.stage = wifiSetup ? PairingStage::WiFiSetup : PairingStage::AppPairing;
  view.code = wifiSetup ? wifiPin : appCode;
  return view;
}

template<class Canvas>
void renderPairing(Canvas& canvas, const PairingPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  const bool wifi = view.stage == PairingStage::WiFiSetup;
  centered(canvas, wifi ? "WIFI PIN" : "APP PAIR", 0, 64, 1, CLOCK_PROGRESS);
  centered(canvas, view.code.empty() ? "WAIT" : view.code, 0, 64, 11, STATUS_TEXT, 5, 9, 1);
  centered(canvas, wifi ? "WIFI SETUP" : "ADD TICKER", 0, 64, 26, MUTED_TEXT);
}

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

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
  const int percentGap = textWidth(view.percent) <= 32 ? 1 : 0;
  const int percentLeft = 63 - textWidth(view.percent, 3, percentGap);
  const int symbolRight = percentLeft - 6;
  const int symbolGap = textWidth(view.symbol) <= symbolRight - 1 ? 1 : 0;
  const int symbolWidth = textWidth(view.symbol, 3, symbolGap) <= symbolRight - 1 ? 3 : 2;
  text(canvas, view.symbol, 1, 1, SCORE_TEXT, symbolWidth, 5, symbolGap, false, 1, symbolRight);
  text(canvas, view.percent, percentLeft, 1, ink, 3, 5, percentGap, false, symbolRight + 6, 63);
  const bool loss = !view.percent.empty() && view.percent[0] == '-';
  for (int row = 0; row < 3; ++row) {
    const int half = loss ? 2 - row : row;
    canvas.rect(percentLeft - 4 - half / 2, 2 + row, half + 1, 1, ink);
  }
  canvas.rect(1, 8, 62, 1, {24, 35, 48});
  const int priceWidth = textWidth(view.price, 4, 1, true) <= 62 ? 4 : 3;
  text(canvas, view.price, 1, 11, ink, priceWidth, 9, 1, true, 1, 63);
  const int changeWidth = textWidth(view.change, 4, 1, true) <= 62 ? 4 : 3;
  const int changeLeft = 63 - textWidth(view.change, changeWidth, 1, true);
  if (changeLeft >= 29) text(canvas, "CHANGE", 1, 25, MUTED_TEXT);
  text(canvas, view.change, changeLeft, 25, ink, changeWidth, 6, 1, true, 1, 63);
}
}  // namespace ticker_ui

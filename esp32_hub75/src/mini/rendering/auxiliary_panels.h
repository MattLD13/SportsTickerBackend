#pragma once
#include "sports_pane.h"
#include "classic_font.h"

namespace ticker_ui {
struct FlightPane {
  std::string id, origin, destination, eta, metrics, status, badge, aircraft;
  bool live = false, delayed = false, disrupted = false, complete = false, setup = false;
  int progress = 0;
};
struct AirportPane {
  std::string code, temperature, arrival, arrivalAirport, departure, departureAirport, detail;
  bool arrivalPresent = false, departurePresent = false, detailWarning = false;
  int page = 0, pages = 1;
};

template<class Canvas>
void aviationLabel(Canvas& canvas, const std::string& value, int left, int right, int y, Rgb ink) {
  text(canvas, value, left, y, ink, 3, 5, 1, false, left, right);
}

template<class Canvas>
void renderFlight(Canvas& canvas, const FlightPane& view) {
  const Rgb blue{80, 180, 255}, green{50, 225, 125}, amber{255, 185, 65}, red{255, 80, 75};
  const Rgb accent = view.disrupted ? red : view.delayed ? amber : view.live || view.complete ? green : amber;
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 0, 64, 8, {5, 16, 28});
  const int badgeLeft = 63 - textWidth(view.badge);
  aviationLabel(canvas, view.setup ? "FLIGHTS" : view.id, 1, badgeLeft - 3, 1, SCORE_TEXT);
  aviationLabel(canvas, view.badge, badgeLeft, 63, 1, accent);
  canvas.rect(1, 8, 62, 1, {24, 43, 62});
  if (view.setup) {
    centered(canvas, "TRACK A FLIGHT", 0, 64, 12, SCORE_TEXT);
    centered(canvas, "ADD IN APP", 0, 64, 23, blue);
    return;
  }
  centered(canvas, view.origin, 0, 25, 10, SCORE_TEXT, 5, 9);
  centered(canvas, view.destination, 39, 25, 10, SCORE_TEXT, 5, 9);
  canvas.rect(28, 14, 8, 1, blue);
  for (int row = 0; row < 3; ++row) {
    canvas.pixel(33 + row, 12 + row, blue);
    canvas.pixel(33 + row, 16 - row, blue);
  }
  centered(canvas, view.live ? "ETA " + view.eta : view.status, 0, 64, 20, view.live ? blue : accent);
  centered(canvas, view.live ? view.metrics : view.aircraft, 0, 64, 26, MUTED_TEXT);
  canvas.rect(0, 31, 64, 1, {24, 43, 62});
  const int progress = std::min(100, std::max(0, view.progress));
  if (progress) canvas.rect(0, 31, (progress * 64 + 50) / 100, 1, accent);
}

template<class Canvas>
void renderAirport(Canvas& canvas, const AirportPane& view) {
  const Rgb green{50, 225, 125}, blue{80, 180, 255}, amber{255, 185, 65};
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 0, 64, 9, {5, 16, 28});
  text(canvas, view.code, 2, 1, blue, 4, 6, 1, false, 2, 33);
  const int tempLeft = 63 - textWidth(view.temperature);
  aviationLabel(canvas, view.temperature, tempLeft, 63, 2, amber);
  for (int page = 0; page < view.pages; ++page)
    canvas.pixel(27 + page * 3, 4, page == view.page ? blue : Rgb{24, 43, 62});
  canvas.rect(0, 9, 64, 8, {5, 13, 22});
  canvas.rect(0, 18, 64, 8, {5, 13, 22});
  for (int side = 0; side < 2; ++side) {
    const int y = 11 + side * 8;
    const bool present = side ? view.departurePresent : view.arrivalPresent;
    const Rgb ink = side ? blue : green;
    aviationLabel(canvas, side ? "OUT" : "IN", 1, 13, y, ink);
    aviationLabel(canvas, present ? (side ? view.departure : view.arrival) : "NONE", 15, 47, y, present ? SCORE_TEXT : MUTED_TEXT);
    const auto& code = side ? view.departureAirport : view.arrivalAirport;
    aviationLabel(canvas, present ? code : "---", 63 - textWidth(code), 63, y, ink);
  }
  centered(canvas, view.detail, 0, 64, 27, view.detailWarning ? amber : MUTED_TEXT);
}

template<class Canvas>
void renderMessage(Canvas& canvas, const std::string& value) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 0, 64, 1, {30, 150, 220});
  const std::string visible = value.substr(0, 10);
  for (size_t index = 0; index < visible.size(); ++index) {
    const unsigned char ch = visible[index];
    const auto* glyph = classicFont[ch >= 32 && ch <= 126 ? ch - 32 : 0];
    for (int x = 0; x < 5; ++x) for (int y = 0; y < 8; ++y)
      if (glyph[x] & (1 << y)) canvas.pixel(2 + index * 6 + x, 13 + y, {255, 220, 80});
  }
}
}  // namespace ticker_ui

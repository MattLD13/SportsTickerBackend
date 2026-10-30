// Draw a tracked flight, or the arrivals and departures of one airport.
#pragma once

#include "text.h"

namespace mini_ui {

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

namespace aviation {

static constexpr Rgb blue{80, 180, 255}, green{50, 225, 125}, amber{255, 185, 65}, red{255, 80, 75};
static constexpr Rgb headerFill{5, 16, 28}, ruleInk{24, 43, 62}, rowFill{5, 13, 22};

template<class Canvas>
void label(Canvas& canvas, const std::string& value, int left, int right, int y, Rgb ink) {
  drawText(canvas, value, left, y, ink, {}, {left, right});
}

}  // namespace aviation

// The header holds the flight and its state badge. The route sits between them and the live or lifecycle lines.
template<class Canvas>
void draw(Canvas& canvas, const FlightPane& view) {
  using namespace aviation;
  const Rgb accent = view.disrupted ? red : view.delayed ? amber : view.live || view.complete ? green : amber;
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  canvas.rect(0, 0, PANE_WIDTH, 8, headerFill);
  const int badgeLeft = 63 - measure(view.badge);
  label(canvas, view.setup ? "FLIGHTS" : view.id, 1, badgeLeft - 3, 1, SCORE_TEXT);
  label(canvas, view.badge, badgeLeft, 63, 1, accent);
  canvas.rect(1, 8, 62, 1, ruleInk);
  if (view.setup) {
    center(canvas, "TRACK A FLIGHT", 0, PANE_WIDTH, 12, SCORE_TEXT);
    center(canvas, "ADD IN APP", 0, PANE_WIDTH, 23, blue);
    return;
  }
  center(canvas, view.origin, 0, 25, 10, SCORE_TEXT, {5, 9});
  center(canvas, view.destination, 39, 25, 10, SCORE_TEXT, {5, 9});
  canvas.rect(28, 14, 8, 1, blue);
  for (int row = 0; row < 3; ++row) {
    canvas.pixel(33 + row, 12 + row, blue);
    canvas.pixel(33 + row, 16 - row, blue);
  }
  center(canvas, view.live ? "ETA " + view.eta : view.status, 0, PANE_WIDTH, 20, view.live ? blue : accent);
  center(canvas, view.live ? view.metrics : view.aircraft, 0, PANE_WIDTH, 26, MUTED_TEXT);
  canvas.rect(0, 31, PANE_WIDTH, 1, ruleInk);
  const int progress = std::min(100, std::max(0, view.progress));
  if (progress) canvas.rect(0, 31, (progress * PANE_WIDTH + 50) / 100, 1, accent);
}

// The header holds the airport, the page dots, and the temperature. One row each for an arrival and a departure.
template<class Canvas>
void draw(Canvas& canvas, const AirportPane& view) {
  using namespace aviation;
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  canvas.rect(0, 0, PANE_WIDTH, 9, headerFill);
  drawText(canvas, view.code, 2, 1, blue, {4, 6}, {2, 33});
  label(canvas, view.temperature, 63 - measure(view.temperature), 63, 2, amber);
  for (int page = 0; page < view.pages; ++page) canvas.pixel(27 + page * 3, 4, page == view.page ? blue : ruleInk);
  canvas.rect(0, 9, PANE_WIDTH, 8, rowFill);
  canvas.rect(0, 18, PANE_WIDTH, 8, rowFill);
  for (int side = 0; side < 2; ++side) {
    const int y = 11 + side * 8;
    const bool present = side ? view.departurePresent : view.arrivalPresent;
    const Rgb ink = side ? blue : green;
    label(canvas, side ? "OUT" : "IN", 1, 13, y, ink);
    label(canvas, present ? (side ? view.departure : view.arrival) : "NONE", 15, 47, y, present ? SCORE_TEXT : MUTED_TEXT);
    const auto& code = side ? view.departureAirport : view.arrivalAirport;
    label(canvas, present ? code : "---", 63 - measure(code), 63, y, ink);
  }
  center(canvas, view.detail, 0, PANE_WIDTH, 27, view.detailWarning ? amber : MUTED_TEXT);
}

}  // namespace mini_ui

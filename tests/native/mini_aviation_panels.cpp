#include <array>
#include <cassert>
#include <fstream>
#include <iostream>
#include <panels.h>

struct Canvas {
  std::array<uint8_t, 64 * 32 * 3> pixels{};
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    assert(x >= 0 && x < 64 && y >= 0 && y < 32);
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = ink.r; pixels[offset + 1] = ink.g; pixels[offset + 2] = ink.b;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
};

int main(int argc, char** argv) {
  assert(argc == 2);
  std::ifstream input(argv[1]);
  JsonDocument document;
  assert(!deserializeJson(document, input));
  int flights = 0, airports = 0;
  for (JsonObjectConst row : document["cases"].as<JsonArrayConst>()) {
    const std::string mode = row["mode"] | "";
    const std::string name = row["name"] | "";
    const auto game = row["game"].as<JsonObjectConst>();
    if (mode == "flights") {
      const auto view = ticker_ui::flightPane(game);
      Canvas frame;
      ticker_ui::renderFlight(frame, view);
      if (name == "MD13") assert(view.origin == "EWR" && view.destination == "LAX" && view.eta == "2H20M");
      if (name == "MD14") assert(view.delayed && view.badge == "+20M");
      if (name == "MD17") assert(view.disrupted && view.status == "CANCELED");
      if (name == "MD29") assert(view.setup);
      ++flights;
    } else if (mode == "airports") {
      for (uint32_t ms = 0; ms < 16000; ms += 2000) {
        const auto view = ticker_ui::airportPane(game, ms);
        Canvas frame;
        ticker_ui::renderAirport(frame, view);
        if (name == "MD19") assert(!view.arrivalPresent && !view.departurePresent && view.pages == 1);
        if (name == "MD28" && ms == 4000) {
          assert(view.pages == 4 && view.page == 1);
          assert(view.arrival == "UAL12345" && view.arrivalAirport == "LAX");
          assert(view.detailWarning && view.detail == "ARR +25 MIN");
        }
        if (name == "MD28" && ms == 6000) assert(view.detail == "DEP +120 MIN");
      }
      ++airports;
    }
  }
  assert(flights == 6 && airports == 3);
  std::cout << "Flight routes, lifecycle labels, airport pages, delays, empty boards, and frame bounds pass\n";
}

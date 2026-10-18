#pragma once
#include "sports_pane.h"
#include "text_layout.h"
#include "classic_font.h"

namespace ticker_ui {
struct FlightPane {
  std::string id, route, eta, speed, detail, status, footer;
  bool live = false, delayed = false;
  int progress = 0;
};
struct AirportPane {
  std::string code, temperature, arrival, arrivalAirport, departure, departureAirport;
};

template<class Canvas>
struct PaneSurface {
  Canvas& canvas;
  void fillRect(int x, int y, int width, int height, uint16_t value) {
    canvas.rect(x, y, width, height, {static_cast<uint8_t>(((value >> 11) & 31) * 255 / 31),
        static_cast<uint8_t>(((value >> 5) & 63) * 255 / 63), static_cast<uint8_t>((value & 31) * 255 / 31)});
  }
};

template<class Canvas>
void auxiliaryText(Canvas& canvas, const std::string& value, int x, int y, Rgb ink, int span = -1) {
  PaneSurface<Canvas> surface{canvas};
  const auto visible = span < 0 ? value : value.substr(0, std::max(0, span / 4));
  const uint16_t packed = ((ink.r & 248) << 8) | ((ink.g & 252) << 3) | (ink.b >> 3);
  mini_text::drawPaneText(surface, visible.c_str(), visible.size(), x, y, packed, 1);
}

template<class Canvas>
void auxiliaryHeader(Canvas& canvas, const std::string& label, Rgb ink) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 7, 64, 1, {55, 76, 130});
  auxiliaryText(canvas, label, 2, 1, ink, 60);
}

template<class Canvas>
void renderFlight(Canvas& canvas, const FlightPane& view) {
  const Rgb orange{255, 145, 45}, blue{50, 150, 255}, red{255, 80, 75}, green{50, 225, 125};
  auxiliaryHeader(canvas, view.id, view.delayed ? red : orange);
  auxiliaryText(canvas, "^", 54, 1, view.delayed ? red : green);
  auxiliaryText(canvas, view.route, 2, 10, {242, 246, 255}, 27);
  if (view.live) {
    auxiliaryText(canvas, "E" + view.eta, 2, 18, blue, 31);
    auxiliaryText(canvas, "S" + view.speed, 40, 18, {120, 210, 230}, 21);
  } else auxiliaryText(canvas, view.status, 2, 18, orange, 34);
  auxiliaryText(canvas, view.detail, 2, 24, view.delayed ? red : Rgb{220, 225, 240}, 25);
  auxiliaryText(canvas, view.footer, 31, 24, view.delayed ? red : green, 31);
  canvas.rect(2, 29, 60, 3, view.delayed ? Rgb{60, 10, 10} : Rgb{15, 35, 15});
  canvas.rect(2, 29, std::max(1, std::min(100, std::max(0, view.progress)) * 60 / 100), 3, view.delayed ? red : green);
}

template<class Canvas>
void renderAirport(Canvas& canvas, const AirportPane& view) {
  const Rgb green{45, 220, 125}, red{255, 75, 75}, white{242, 246, 255}, muted{155, 175, 205};
  auxiliaryHeader(canvas, view.code, green);
  auxiliaryText(canvas, view.temperature, 39, 1, {255, 220, 70}, 24);
  auxiliaryText(canvas, "IN", 2, 10, green);
  auxiliaryText(canvas, view.arrival, 13, 10, white, 27);
  auxiliaryText(canvas, view.arrivalAirport, 43, 10, muted, 19);
  auxiliaryText(canvas, "OUT", 0, 19, red);
  auxiliaryText(canvas, view.departure, 18, 19, white, 22);
  auxiliaryText(canvas, view.departureAirport, 46, 19, muted, 17);
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

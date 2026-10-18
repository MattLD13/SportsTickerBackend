#pragma once
#include "sports_pane.h"

class MiniCanvas {
 public:
  void pixel(int x, int y, ticker_ui::Rgb ink) { matrix->drawPixel(x, y, color(ink.r, ink.g, ink.b)); }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) { matrix->fillRect(x, y, width, height, color(ink.r, ink.g, ink.b)); }
};

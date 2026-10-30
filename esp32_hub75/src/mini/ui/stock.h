// Draw one stock: the logo or a badge, the symbol, the move with its arrow, and the price.
#pragma once

#include "sports.h"

namespace mini_ui {

struct StockPane {
  std::string symbol, price, percent;
};

template<class Canvas>
void draw(Canvas& canvas, const StockPane& view) {
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  const bool known = !view.percent.empty() && view.percent != "--";
  const bool loss = !view.percent.empty() && view.percent[0] == '-';
  const Rgb ink = !known ? MUTED_TEXT : loss ? STOCK_LOSS : STOCK_GAIN;
  if (!canvas.logo(Side::Home, 1, 1)) badge(canvas, 1, 1, {28, 43, 58}, view.symbol.substr(0, 3));
  // A long symbol uses the smaller figures, then drops its letter gaps.
  const int symbolWidth = measure(view.symbol, {4, 5, 1}) <= 42 ? 4 : 3;
  drawText(canvas, view.symbol, 22, 1, SCORE_TEXT, {symbolWidth, 7, measure(view.symbol, {symbolWidth, 5, 1}) <= 42 ? 1 : 0}, {22, 64});
  drawText(canvas, view.percent, 28, 12, ink, {3, 5, measure(view.percent) <= 36 ? 1 : 0}, {28, 64});
  for (int row = 0; known && row < 3; ++row) {
    const int half = loss ? 2 - row : row;
    canvas.rect(23 - half / 2, 13 + row, half + 1, 1, ink);
  }
  canvas.rect(1, 20, 62, 1, {24, 35, 48});
  drawText(canvas, view.price, 1, 23, SCORE_TEXT, {measure(view.price, {4, 5, 1, true}) <= 62 ? 4 : 3, 9, 1, true}, {1, 63});
}

}  // namespace mini_ui

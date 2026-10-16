#pragma once

#include <algorithm>
#include <cctype>
#include <cmath>
#include <string>
#include "ui_generated.h"

namespace ticker_ui {

static constexpr int LOGO_Y = 9 + (22 - MINI_LOGO_SIZE) / 2;
static constexpr int HOME_LOGO_X = 63 - MINI_LOGO_SIZE;
static constexpr int CONTENT_LEFT = MINI_LOGO_SIZE + 2;
static constexpr int CONTENT_WIDTH = 64 - 2 * CONTENT_LEFT;

enum class Side { None, Away, Home };
enum class InningHalf { None, Top, Bottom, Break };

enum class Sport { Other, Football, Baseball, Basketball, Hockey, Soccer };
enum class Shot { Pending, Goal, Miss, Next, NotTaken };

struct SportsPane {
  std::string status, awayScore, homeScore, footer, awayRank, homeRank, awayLabel, homeLabel;
  Rgb awayColor = {86, 104, 132}, homeColor = {86, 104, 132};
  Sport sport = Sport::Other;
  Side active = Side::None, powerPlay = Side::None, emptyNet = Side::None;
  bool live = false, redZone = false, baseballLive = false, shootout = false;
  int balls = 0, strikes = 0, outs = 0, inning = 0;
  InningHalf inningHalf = InningHalf::None;
  bool first = false, second = false, third = false;
  int awayCards = 0, homeCards = 0;
  Shot awayShots[5] = {}, homeShots[5] = {};
  int shotCount = 0;
};

inline int glyphIndex(char ch) {
  const unsigned char value = static_cast<unsigned char>(ch);
  const int upper = std::toupper(value);
  return upper >= 32 && upper <= 126 ? upper - 32 : 0;
}

inline int glyphWidth(char ch, int width, bool hybridFont) {
  if (!hybridFont && ch == ' ') return std::max(1, width / 3);
  return hybridFont ? width : (paneWidths[glyphIndex(ch)] * width + 1) / 3;
}

inline int textWidth(const std::string& value, int width = 3, int gap = 1, bool hybridFont = false) {
  int size = 0;
  for (char ch : value) size += glyphWidth(ch, width, hybridFont) + gap;
  return value.empty() ? 0 : size - gap;
}

template<class Canvas>
void text(Canvas& canvas, const std::string& value, int x, int y, Rgb ink,
          int width = 3, int height = 5, int gap = 1, bool hybridFont = false, int clipLeft = 0, int clipRight = 64) {
  const int rows = hybridFont ? 6 : 5;
  for (char ch : value) {
    const int index = glyphIndex(ch);
    const int columns = hybridFont ? 4 : paneWidths[index];
    const int drawnWidth = glyphWidth(ch, width, hybridFont);
    for (int dy = 0; dy < height; ++dy) {
      const int row = ((2 * dy + 1) * rows) / (2 * height);
      const uint8_t bits = hybridFont ? hybrid[index][row] : pane[index][row];
      for (int dx = 0; dx < drawnWidth; ++dx) {
        const int column = ((2 * dx + 1) * columns) / (2 * drawnWidth);
        if (x + dx >= clipLeft && x + dx < clipRight && (bits & (1 << (columns - 1 - column)))) canvas.pixel(x + dx, y + dy, ink);
      }
    }
    x += drawnWidth + gap;
  }
}

template<class Canvas>
void centered(Canvas& canvas, const std::string& value, int left, int span, int y,
              Rgb ink, int width = 3, int height = 5, int gap = 1, bool hybridFont = false) {
  const int size = textWidth(value, width, gap, hybridFont);
  text(canvas, value, left + (span - size + 1) / 2, y, ink, width, height, gap, hybridFont, left, left + span);
}

template<class Canvas>
void footer(Canvas& canvas, const std::string& value, Rgb ink) {
  if (value.empty()) return;
  if (textWidth(value) <= CONTENT_WIDTH) {
    centered(canvas, value, CONTENT_LEFT, CONTENT_WIDTH, 23, ink);
    return;
  }
  // Keep long labels on two clear rows between the team marks.
  size_t split = value.rfind(' ', value.size() / 2);
  if (split == std::string::npos) split = value.find(' ', value.size() / 2);
  if (split == std::string::npos) split = value.size() / 2;
  const std::string first = value.substr(0, split);
  const size_t start = split < value.size() && value[split] == ' ' ? split + 1 : split;
  const std::string second = value.substr(start);
  centered(canvas, first, CONTENT_LEFT, CONTENT_WIDTH, 20, ink);
  centered(canvas, second, CONTENT_LEFT, CONTENT_WIDTH, 26, ink);
}


template<class Canvas>
void football(Canvas& canvas, int center) {
  const Rgb leather = {150, 75, 20}, tip = {110, 54, 14};
  for (int row = 0; row < 5; ++row) {
    const int radius = 4 - std::abs(2 - row);
    canvas.rect(center - radius, row + 1, radius * 2 + 1, 1, leather);
  }
  canvas.pixel(center - 4, 3, tip);
  canvas.pixel(center + 4, 3, tip);
  canvas.rect(center - 2, 3, 5, 1, SCORE_TEXT);
}

template<class Canvas>
void base(Canvas& canvas, int cx, int cy, bool occupied) {
  const Rgb ink = occupied ? Rgb{255, 200, 0} : Rgb{55, 55, 55};
  for (int row = 0; row < 3; ++row) canvas.rect(cx - 2 + row, cy + row, 5 - row * 2, 1, ink);
}

template<class Canvas>
void rank(Canvas& canvas, const std::string& value, int x) {
  if (value.empty()) return;
  text(canvas, value, x - 1, LOGO_Y + MINI_LOGO_SIZE - 6, BACKGROUND);
  text(canvas, value, x + 1, LOGO_Y + MINI_LOGO_SIZE - 6, BACKGROUND);
  text(canvas, value, x, LOGO_Y + MINI_LOGO_SIZE - 7, BACKGROUND);
  text(canvas, value, x, LOGO_Y + MINI_LOGO_SIZE - 5, BACKGROUND);
  text(canvas, value, x, LOGO_Y + MINI_LOGO_SIZE - 6, RANK);
}

template<class Canvas>
void badge(Canvas& canvas, int x, int y, Rgb fill, const std::string& label) {
  for (int row = 0; row < MINI_LOGO_SIZE - 2; ++row) {
    const int inset = row == 0 || row == MINI_LOGO_SIZE - 3 ? 3 : row == 1 || row == MINI_LOGO_SIZE - 4 ? 1 : 0;
    canvas.rect(x + 1 + inset, y + 1 + row, MINI_LOGO_SIZE - 2 - 2 * inset, 1, fill);
  }
  auto linear = [](uint8_t value) {
    const float v = value / 255.0f;
    return v <= 0.04045f ? v / 12.92f : std::pow((v + 0.055f) / 1.055f, 2.4f);
  };
  const float luminance = .2126f * linear(fill.r) + .7152f * linear(fill.g) + .0722f * linear(fill.b);
  const Rgb ink = luminance < .18f ? Rgb{250, 252, 255} : Rgb{8, 12, 18};
  centered(canvas, label, x, MINI_LOGO_SIZE, y + (MINI_LOGO_SIZE - 6) / 2, ink, 4, 6, label.size() == 4 ? 0 : 1, true);
}

template<class Canvas>
void renderSports(Canvas& canvas, const SportsPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  canvas.rect(0, 7, 64, 1, HEADER_RULE);
  if (!canvas.logo(Side::Away, 1, LOGO_Y)) badge(canvas, 1, LOGO_Y, view.awayColor, view.awayLabel);
  if (!canvas.logo(Side::Home, HOME_LOGO_X, LOGO_Y)) badge(canvas, HOME_LOGO_X, LOGO_Y, view.homeColor, view.homeLabel);
  rank(canvas, view.awayRank, 2);
  rank(canvas, view.homeRank, 62 - textWidth(view.homeRank));

  const bool headerSides = view.active != Side::None || view.powerPlay != Side::None ||
                           view.emptyNet != Side::None || view.awayCards || view.homeCards;
  const int headerSpan = view.baseballLive ? 32 : headerSides ? 36 : 62;
  const int headerLeft = (64 - headerSpan) / 2;
  if (view.baseballLive && view.inning > 0) {
    const std::string number = std::to_string(view.inning);
    const int width = 4 + textWidth(number);
    const int x = (64 - width + 1) / 2;
    if (view.inningHalf == InningHalf::Top || view.inningHalf == InningHalf::Bottom) {
      const uint8_t* rows = view.inningHalf == InningHalf::Top ? inningTop : inningBottom;
      for (int row = 0; row < 5; ++row) for (int column = 0; column < 3; ++column) {
        if (rows[row] & (1 << (2 - column))) canvas.pixel(x + column, row + 1, {255, 220, 105});
      }
    } else text(canvas, "-", x, 1, STATUS_TEXT);
    text(canvas, number, x + 4, 1, STATUS_TEXT);
  } else {
    const bool fullFont = textWidth(view.status, 4, 1, true) <= headerSpan;
    centered(canvas, view.status, headerLeft, headerSpan, 1, STATUS_TEXT,
             fullFont ? 4 : 3, fullFont ? 6 : 5, fullFont || textWidth(view.status) <= headerSpan ? 1 : 0, fullFont);
  }


  const int scoreSpan = view.shootout ? 20 : CONTENT_WIDTH;
  const size_t digits = std::max(view.awayScore.size(), view.homeScore.size());
  int digitWidth = digits == 1 ? 6 : digits <= 2 && !view.shootout ? 4 : 3;
  int digitGap = 1;
  const int dashWidth = digits == 1 ? 6 : 3;
  int group = textWidth(view.awayScore, digitWidth, digitGap) + textWidth(view.homeScore, digitWidth, digitGap) + dashWidth + 2;
  if (group > scoreSpan) {
    digitGap = 0;
    group = textWidth(view.awayScore, digitWidth, digitGap) + textWidth(view.homeScore, digitWidth, digitGap) + dashWidth + 2;
  }
  const int x = (64 - group + 1) / 2;
  const bool twoFooterRows = !view.shootout && !view.baseballLive && textWidth(view.footer) > CONTENT_WIDTH;
  const int height = digitWidth == 6 ? (twoFooterRows ? 9 : 11) : digitWidth == 4 ? 9 : 7;
  const int y = view.baseballLive ? 8 : digitWidth == 6 ? 9 : 10;
  const int awayWidth = textWidth(view.awayScore, digitWidth, digitGap);
  text(canvas, view.awayScore, x, y, SCORE_TEXT, digitWidth, height, digitGap);
  canvas.rect(x + awayWidth + 1, y + height / 2, dashWidth, digitWidth == 6 ? 2 : 1, SCORE_TEXT);
  text(canvas, view.homeScore, x + awayWidth + dashWidth + 2, y, SCORE_TEXT, digitWidth, height, digitGap);

  if (view.live && view.sport == Sport::Football) {
    if (view.active != Side::None) football(canvas, view.active == Side::Home ? 55 : 7);
    footer(canvas, view.footer, view.redZone ? RED_ZONE_TEXT : PLAY_TEXT);
    if (view.redZone) {
      canvas.rect(0, 0, 64, 1, RED_ZONE_BORDER);
      canvas.rect(0, 31, 64, 1, RED_ZONE_BORDER);
      canvas.rect(0, 0, 1, 32, RED_ZONE_BORDER);
      canvas.rect(63, 0, 1, 32, RED_ZONE_BORDER);
    }
  }
  if (view.baseballLive) {
    if (view.active != Side::None) {
      const int x = view.active == Side::Home ? 49 : 4;
      text(canvas, std::to_string(view.balls), x, 2, BALL);
      text(canvas, "-", x + 4, 2, {160, 160, 160});
      text(canvas, std::to_string(view.strikes), x + 8, 2, STRIKE);
    }
    base(canvas, 32, 19, view.second);
    base(canvas, 28, 23, view.third);
    base(canvas, 36, 23, view.first);
    for (int index = 0; index < 3; ++index) canvas.rect(25 + index * 5, 28, 4, 3, index < view.outs ? OUT : INACTIVE);
  }
  if (view.live && view.sport == Sport::Hockey && !view.shootout) {
    const Side side = view.emptyNet != Side::None ? view.emptyNet : view.powerPlay;
    const bool empty = view.emptyNet != Side::None;
    if (side != Side::None) centered(canvas, empty ? "EN" : "PP", side == Side::Home ? HOME_LOGO_X : 1, MINI_LOGO_SIZE, 2, empty ? EMPTY_NET : POWER_PLAY);
    footer(canvas, view.footer, empty ? EMPTY_NET : side != Side::None ? POWER_PLAY : MUTED_TEXT);
  }
  if (view.shootout) {
    for (int index = 0; index < view.shotCount; ++index) {
      const int size = view.shotCount > 3 ? 2 : 3;
      const int step = view.shotCount > 3 ? 4 : 6;
      auto ink = [](Shot state) -> Rgb {
        return state == Shot::Goal ? Rgb{50, 200, 70} : state == Shot::Miss ? Rgb{220, 55, 55} :
               state == Shot::Next ? Rgb{255, 210, 40} : Rgb{80, 80, 80};
      };
      if (view.awayShots[index] != Shot::NotTaken)
        canvas.rect(CONTENT_LEFT, 9 + index * step, size, size, ink(view.awayShots[index]));
      if (view.homeShots[index] != Shot::NotTaken)
        canvas.rect(64 - CONTENT_LEFT - size, 9 + index * step, size, size, ink(view.homeShots[index]));
    }
    centered(canvas, view.footer, CONTENT_LEFT, CONTENT_WIDTH, 27, MUTED_TEXT, 3, 5, 0);
  }
  if (view.sport == Sport::Soccer) {
    for (int side = 0; side < 2; ++side) {
      const int cards = side ? view.homeCards : view.awayCards;
      if (!cards) continue;
      const int x = side ? 56 : 3;
      canvas.rect(x, 0, 5, 7, {210, 30, 30});
      if (cards > 1) text(canvas, std::to_string(std::min(cards, 9)), x + 1, 1, SCORE_TEXT);
    }
  }
}
}  // namespace ticker_ui

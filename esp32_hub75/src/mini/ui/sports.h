// Draw one game: a logo at each side, the status above a rule, the score, and the marks of its sport.
#pragma once

#include <cmath>
#include "text.h"

namespace mini_ui {

static constexpr int LOGO_Y = 9 + (22 - MINI_LOGO_SIZE) / 2;
static constexpr int HOME_LOGO_X = 63 - MINI_LOGO_SIZE;
static constexpr int CONTENT_LEFT = MINI_LOGO_SIZE + 2;
static constexpr int CONTENT_WIDTH = PANE_WIDTH - 2 * CONTENT_LEFT;

enum class Side { None, Away, Home };
enum class Sport { Other, Football, Baseball, Basketball, Hockey, Soccer };
enum class InningHalf { None, Top, Bottom, Break };
enum class Shot { Pending, Goal, Miss, Next, NotTaken };

struct Penalty { std::string clock, number; };

struct SportsPane {
  std::string status, awayScore, homeScore, footer, awayRank, homeRank, awayLabel, homeLabel;
  std::string powerPlayLabel, awaySeed, homeSeed;
  Rgb awayColor = {86, 104, 132}, homeColor = {86, 104, 132}, ruleColor = HEADER_RULE;
  Sport sport = Sport::Other;
  Side active = Side::None, powerPlay = Side::None, emptyNet = Side::None;
  bool live = false, redZone = false, baseballLive = false, shootout = false;
  int balls = 0, strikes = 0, outs = 0, inning = 0;
  InningHalf inningHalf = InningHalf::None;
  bool first = false, second = false, third = false;
  int awayCards = 0, homeCards = 0;
  Shot awayShots[5] = {}, homeShots[5] = {};
  int shotCount = 0;
  Penalty penalties[2];
  int penaltyCount = 0;
};

// A rounded team-color badge with the team code, where a logo is missing.
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
  center(canvas, label, x, MINI_LOGO_SIZE, y + (MINI_LOGO_SIZE - 6) / 2, ink, {4, 6, label.size() == 4 ? 0 : 1, true});
}

namespace sports {

// A footer that does not fit on one row breaks at " | ", or else at the space nearest the middle.
template<class Canvas>
void footer(Canvas& canvas, const std::string& value, Rgb ink) {
  if (value.empty()) return;
  const int gap = measure(value) <= CONTENT_WIDTH ? 1 : 0;
  const int width = measure(value, {3, 5, gap});
  if (width <= CONTENT_WIDTH) {
    const int spaces = static_cast<int>(std::count(value.begin(), value.end(), ' '));
    const int wordSpace = gap == 0 && spaces > 0 ? 1 + std::min(1, (CONTENT_WIDTH - width) / spaces) : 1;
    center(canvas, value, CONTENT_LEFT, CONTENT_WIDTH, 23, ink, {3, 5, gap, false, wordSpace});
    return;
  }
  const size_t separator = value.find(" | ");
  size_t split = separator;
  if (split == std::string::npos) split = value.rfind(' ', value.size() / 2);
  if (split == std::string::npos) split = value.find(' ', value.size() / 2);
  if (split == std::string::npos) split = value.size() / 2;
  const size_t start = separator != std::string::npos ? split + 3 : split < value.size() && value[split] == ' ' ? split + 1 : split;
  const std::string top = value.substr(0, split), bottom = value.substr(start);
  center(canvas, top, CONTENT_LEFT, CONTENT_WIDTH, 20, ink, {3, 5, measure(top) <= CONTENT_WIDTH ? 1 : 0});
  center(canvas, bottom, CONTENT_LEFT, CONTENT_WIDTH, 26, ink, {3, 5, measure(bottom) <= CONTENT_WIDTH ? 1 : 0});
}

// The penalty clock uses glyphs without side columns when the clock and the number need the room.
template<class Canvas>
void penalty(Canvas& canvas, const Penalty& value, int y, Rgb ink) {
  const std::string number = "#" + value.number;
  const int numberWidth = measure(number);
  const int gap = measureInk(value.clock, 1) + 2 + numberWidth <= CONTENT_WIDTH ? 1 : 0;
  const int clockWidth = measureInk(value.clock, gap);
  const int left = CONTENT_LEFT + (CONTENT_WIDTH - clockWidth - 2 - numberWidth) / 2;
  drawInk(canvas, value.clock, left, y, ink, gap);
  drawText(canvas, number, left + clockWidth + 2, y, ink);
}

template<class Canvas>
void ball(Canvas& canvas, int center) {
  for (int row = 0; row < 5; ++row) {
    const int radius = 4 - std::abs(2 - row);
    canvas.rect(center - radius, row + 1, radius * 2 + 1, 1, {150, 75, 20});
  }
  canvas.pixel(center - 4, 3, {110, 54, 14});
  canvas.pixel(center + 4, 3, {110, 54, 14});
  canvas.rect(center - 2, 3, 5, 1, SCORE_TEXT);
}

template<class Canvas>
void base(Canvas& canvas, int cx, int cy, bool occupied) {
  for (int row = 0; row < 3; ++row) canvas.rect(cx - 2 + row, cy + row, 5 - row * 2, 1, occupied ? Rgb{255, 200, 0} : Rgb{55, 55, 55});
}

// A college rank sits in the low corner of the logo, with a dark outline.
template<class Canvas>
void rank(Canvas& canvas, const std::string& value, int x) {
  if (value.empty()) return;
  const int y = LOGO_Y + MINI_LOGO_SIZE - 6;
  for (const auto& [dx, dy] : {std::pair{-1, 0}, {1, 0}, {0, -1}, {0, 1}}) drawText(canvas, value, x + dx, y + dy, BACKGROUND);
  drawText(canvas, value, x, y, RANK);
}

template<class Canvas>
void header(Canvas& canvas, const SportsPane& view) {
  if (view.baseballLive && view.inning > 0) {
    const std::string number = std::to_string(view.inning);
    const int x = (PANE_WIDTH - (4 + measure(number)) + 1) / 2;
    if (view.inningHalf == InningHalf::Top || view.inningHalf == InningHalf::Bottom) {
      const uint8_t* rows = view.inningHalf == InningHalf::Top ? inningTop : inningBottom;
      for (int row = 0; row < 5; ++row) for (int column = 0; column < 3; ++column) {
        if (rows[row] & (1 << (2 - column))) canvas.pixel(x + column, row + 1, {255, 220, 105});
      }
    } else drawText(canvas, "-", x, 1, STATUS_TEXT);
    drawText(canvas, number, x + 4, 1, STATUS_TEXT);
    return;
  }
  // Marks at the sides of the header narrow the status span.
  const bool sides = view.active != Side::None || view.powerPlay != Side::None || view.emptyNet != Side::None ||
                     view.awayCards || view.homeCards || !view.awaySeed.empty() || !view.homeSeed.empty();
  const bool manpower = view.sport == Sport::Hockey && view.emptyNet == Side::None && !view.powerPlayLabel.empty();
  const int span = view.baseballLive ? 32 : manpower ? 30 : sides ? 36 : 62;
  const bool large = measure(view.status, {4, 6, 1, true}) <= span;
  const Type type = large ? Type{4, 6, 1, true} : Type{3, 5, measure(view.status) <= span ? 1 : 0};
  center(canvas, view.status, (PANE_WIDTH - span) / 2, span, 1, STATUS_TEXT, type);
}

// One or two digits use large figures. A wide score drops its digit gaps before it overflows.
template<class Canvas>
void score(Canvas& canvas, const SportsPane& view) {
  const size_t digits = std::max(view.awayScore.size(), view.homeScore.size());
  const int digitWidth = digits == 1 ? 6 : digits <= 2 && !view.shootout ? 4 : 3;
  const int dash = digits == 1 ? 6 : 3;
  const int span = view.shootout ? 20 : CONTENT_WIDTH;
  Type type{digitWidth, 5, 1};
  auto group = [&] { return measure(view.awayScore, type) + measure(view.homeScore, type) + dash + 2; };
  if (group() > span) type.gap = 0;
  const bool twoFooterRows = view.penaltyCount > 1 || (!view.shootout && !view.baseballLive && measure(view.footer, {3, 5, 0}) > CONTENT_WIDTH);
  type.height = digitWidth == 6 ? (twoFooterRows ? 9 : 11) : digitWidth == 4 ? 9 : 7;
  const int x = (PANE_WIDTH - group() + 1) / 2, y = view.baseballLive ? 8 : digitWidth == 6 ? 9 : 10;
  const int awayWidth = measure(view.awayScore, type);
  drawText(canvas, view.awayScore, x, y, SCORE_TEXT, type);
  canvas.rect(x + awayWidth + 1, y + type.height / 2, dash, digitWidth == 6 ? 2 : 1, SCORE_TEXT);
  drawText(canvas, view.homeScore, x + awayWidth + dash + 2, y, SCORE_TEXT, type);
}

template<class Canvas>
void football(Canvas& canvas, const SportsPane& view) {
  if (view.active != Side::None) ball(canvas, view.active == Side::Home ? 55 : 7);
  footer(canvas, view.footer, view.redZone ? RED_ZONE_TEXT : PLAY_TEXT);
  if (view.redZone) {
    canvas.rect(0, 0, PANE_WIDTH, 1, RED_ZONE_BORDER);
    canvas.rect(0, 31, PANE_WIDTH, 1, RED_ZONE_BORDER);
    canvas.rect(0, 0, 1, PANE_HEIGHT, RED_ZONE_BORDER);
    canvas.rect(63, 0, 1, PANE_HEIGHT, RED_ZONE_BORDER);
  }
}

// The count sits over the batting team. The bases and the outs sit below the score.
template<class Canvas>
void baseball(Canvas& canvas, const SportsPane& view) {
  if (view.active != Side::None) {
    const int x = view.active == Side::Home ? 49 : 4;
    drawText(canvas, std::to_string(view.balls), x, 2, BALL);
    drawText(canvas, "-", x + 4, 2, {160, 160, 160});
    drawText(canvas, std::to_string(view.strikes), x + 8, 2, STRIKE);
  }
  base(canvas, 32, 19, view.second);
  base(canvas, 28, 23, view.third);
  base(canvas, 36, 23, view.first);
  for (int index = 0; index < 3; ++index) canvas.rect(25 + index * 5, 28, 4, 3, index < view.outs ? OUT : INACTIVE);
}

// An empty net or a power play shows over its team. The penalties or the manpower label show below the score.
template<class Canvas>
void hockey(Canvas& canvas, const SportsPane& view) {
  const bool empty = view.emptyNet != Side::None;
  const Side side = empty ? view.emptyNet : view.powerPlay;
  if (side != Side::None)
    center(canvas, empty ? "EN" : view.powerPlayLabel, side == Side::Home ? HOME_LOGO_X : 1, MINI_LOGO_SIZE, 2, empty ? EMPTY_NET : POWER_PLAY);
  const Rgb ink = empty ? EMPTY_NET : side != Side::None ? POWER_PLAY : MUTED_TEXT;
  if (view.penaltyCount == 0) {
    footer(canvas, view.footer, ink);
    return;
  }
  for (int index = 0; index < view.penaltyCount; ++index)
    penalty(canvas, view.penalties[index], view.penaltyCount == 1 ? 23 : 20 + index * 6, ink);
}

// Each team has a column of shots beside the score: three rounds of hockey, or five soccer kicks.
template<class Canvas>
void shootout(Canvas& canvas, const SportsPane& view) {
  auto ink = [](Shot shot) -> Rgb {
    return shot == Shot::Goal ? Rgb{50, 200, 70} : shot == Shot::Miss ? Rgb{220, 55, 55} : shot == Shot::Next ? Rgb{255, 210, 40} : Rgb{80, 80, 80};
  };
  const int size = view.shotCount > 3 ? 2 : 3, step = view.shotCount > 3 ? 4 : 6;
  for (int index = 0; index < view.shotCount; ++index) {
    if (view.awayShots[index] != Shot::NotTaken) canvas.rect(CONTENT_LEFT, 9 + index * step, size, size, ink(view.awayShots[index]));
    if (view.homeShots[index] != Shot::NotTaken) canvas.rect(PANE_WIDTH - CONTENT_LEFT - size, 9 + index * step, size, size, ink(view.homeShots[index]));
  }
  center(canvas, view.footer, CONTENT_LEFT, CONTENT_WIDTH, 27, MUTED_TEXT, {3, 5, 0});
}

// A red card sits above each team. More than one card shows the count.
template<class Canvas>
void cards(Canvas& canvas, const SportsPane& view) {
  for (const auto& [count, x] : {std::pair{view.awayCards, 3}, {view.homeCards, 56}}) {
    if (!count) continue;
    canvas.rect(x, 0, 5, 7, {210, 30, 30});
    if (count > 1) drawText(canvas, std::to_string(std::min(count, 9)), x + 1, 1, SCORE_TEXT);
  }
}

}  // namespace sports

template<class Canvas>
void draw(Canvas& canvas, const SportsPane& view) {
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  canvas.rect(0, 7, PANE_WIDTH, 1, view.ruleColor);
  if (!canvas.logo(Side::Away, 1, LOGO_Y)) badge(canvas, 1, LOGO_Y, view.awayColor, view.awayLabel);
  if (!canvas.logo(Side::Home, HOME_LOGO_X, LOGO_Y)) badge(canvas, HOME_LOGO_X, LOGO_Y, view.homeColor, view.homeLabel);
  sports::rank(canvas, view.awayRank, 2);
  sports::rank(canvas, view.homeRank, 62 - measure(view.homeRank));
  drawText(canvas, view.awaySeed, 2, 2, TOURNAMENT_SEED);
  drawText(canvas, view.homeSeed, 62 - measure(view.homeSeed), 2, TOURNAMENT_SEED);
  sports::header(canvas, view);
  sports::score(canvas, view);
  if (view.live && view.sport == Sport::Football) sports::football(canvas, view);
  if (view.baseballLive) sports::baseball(canvas, view);
  if (view.live && view.sport == Sport::Hockey && !view.shootout) sports::hockey(canvas, view);
  if (view.shootout) sports::shootout(canvas, view);
  if (view.sport == Sport::Soccer) sports::cards(canvas, view);
}

}  // namespace mini_ui

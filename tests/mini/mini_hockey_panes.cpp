#include "panes.h"
#include "payload_reader.h"
#include "response_body.h"
#include <array>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>

struct Canvas {
  std::array<mini_ui::Rgb, 64 * 32> pixels{};
  void pixel(int x, int y, mini_ui::Rgb ink) {
    if (x >= 0 && y >= 0 && x < 64 && y < 32) pixels[y * 64 + x] = ink;
  }
  void rect(int x, int y, int width, int height, mini_ui::Rgb ink) {
    for (int row = y; row < y + height; ++row)
      for (int column = x; column < x + width; ++column) pixel(column, row, ink);
  }
  bool logo(mini_ui::Side, int, int) { return false; }
};

mini_ui::Shot expected(const std::string& value) {
  using mini_ui::Shot;
  if (value == "goal") return Shot::Goal;
  if (value == "miss") return Shot::Miss;
  if (value == "next") return Shot::Next;
  if (value == "not_taken") return Shot::NotTaken;
  assert(value == "pending");
  return Shot::Pending;
}

int main(int argc, char** argv) {
  assert(argc >= 2);
  // Cross the library's former 64 KB boundary during repeated buffer growth.
  const std::string large = "{\"ignored\":\"" + std::string(210000, 'x') + "\",\"settings\":{\"mode\":\"sports\"}}";
  ResponseBody response;
  for (size_t offset = 0; offset < large.size(); offset += 1024) {
    const size_t count = std::min(size_t(1024), large.size() - offset);
    assert(response.append(reinterpret_cast<const unsigned char*>(large.data() + offset), count) == count);
  }
  assert(response.size() == large.size());
  assert(std::string(response.data(), response.size()) == large);
  JsonDocument filter, projected;
  filter["settings"]["mode"] = true;
  PayloadReader largeReader(response.data(), response.size());
  assert(!deserializeJson(projected, largeReader, DeserializationOption::Filter(filter)));
  assert(projected["settings"]["mode"] == "sports");
  ResponseBody limited(10);
  const unsigned char bytes[12] = {};
  assert(limited.append(bytes, 10) == 10);
  assert(limited.append(bytes, 2) == 0 && limited.failed() && limited.size() == 10);
  assert(limited.append(bytes, 0) == 0 && limited.failed());
  ResponseBody exhausted(1024, [](void*, size_t) -> void* { return nullptr; });
  assert(exhausted.append(bytes, 1) == 0 && exhausted.failed() && exhausted.size() == 0);
  std::ifstream input(argv[1]);
  const std::string source((std::istreambuf_iterator<char>(input)), {});
  PayloadReader reader(source.data(), source.size());
  JsonDocument document;
  assert(!deserializeJson(document, reader));
  for (JsonObjectConst row : document.as<JsonArrayConst>()) {
    const auto view = mini_ui::sportsPane(row["game"]);
    const auto rounds = row["game"]["situation"]["shootout"]["displayRounds"].as<JsonArrayConst>();
    assert(view.shootout == (rounds.size() > 0));
    assert(view.shotCount == static_cast<int>(rounds.size()));
    if (view.shootout) assert(view.footer == row["game"]["situation"]["shootout"]["roundLabel"].as<std::string>());
    for (int index = 0; index < view.shotCount; ++index) {
      assert(view.awayShots[index] == expected(row["away_shots"][index].as<std::string>()));
      assert(view.homeShots[index] == expected(row["home_shots"][index].as<std::string>()));
    }
    Canvas canvas;
    mini_ui::draw(canvas, view);
    if (!row["expected_power_label"].isNull()) {
      assert(view.powerPlayLabel == row["expected_power_label"].as<std::string>());
      if (!view.powerPlayLabel.empty()) {
        for (int y = 1; y < 7; ++y) for (int x : {15, 16, 17, 47, 48, 49}) {
          const auto pixel = canvas.pixels[y * 64 + x];
          assert(pixel.r == 0 && pixel.g == 0 && pixel.b == 0);
        }
      }
      const std::string badge = row["expected_badge"].as<std::string>();
      if (!badge.empty()) {
        Canvas expectedBadge;
        const int left = (row["badge_home"] | false) ? mini_ui::HOME_LOGO_X : 1;
        mini_ui::center(expectedBadge, badge, left, mini_ui::MINI_LOGO_SIZE, 2, mini_ui::POWER_PLAY);
        for (int y = 2; y < 7; ++y) for (int x = left; x < left + mini_ui::MINI_LOGO_SIZE; ++x) {
          const auto expected = expectedBadge.pixels[y * 64 + x];
          if (expected.r || expected.g || expected.b) {
            const auto actual = canvas.pixels[y * 64 + x];
            assert(actual.r == expected.r && actual.g == expected.g && actual.b == expected.b);
          }
        }
      }
    }
    for (int index = 0; index < view.shotCount; ++index) {
      for (int side = 0; side < 2; ++side) {
        const auto state = side ? view.homeShots[index] : view.awayShots[index];
        const int x = side ? 64 - mini_ui::CONTENT_LEFT - 3 : mini_ui::CONTENT_LEFT;
        const auto color = canvas.pixels[(9 + index * 6) * 64 + x];
        if (state == mini_ui::Shot::Next) assert(color.r == 255 && color.g == 210 && color.b == 40);
        if (state == mini_ui::Shot::NotTaken) assert(color.r == 0 && color.g == 0 && color.b == 0);
      }
    }
    if (argc > 2) {
      std::filesystem::create_directories(argv[2]);
      const std::filesystem::path path = std::filesystem::path(argv[2]) / (row["name"].as<std::string>() + ".ppm");
      std::ofstream image(path, std::ios::binary);
      image << "P6\n64 32\n255\n";
      for (auto ink : canvas.pixels) { image.put(ink.r); image.put(ink.g); image.put(ink.b); }
    }
  }
  assert(mini_ui::measure("3RD & 6") == 23);
  JsonDocument college;
  college["sport"] = "march_madness";
  college["status"] = "2H 04:32";
  college["away_seed"] = "1";
  college["home_seed"] = "16";
  const auto seeded = mini_ui::sportsPane(college.as<JsonObjectConst>());
  assert(seeded.awaySeed == "1" && seeded.homeSeed == "16");
  assert(seeded.awayRank.empty() && seeded.homeRank.empty());
  Canvas seededCanvas;
  mini_ui::draw(seededCanvas, seeded);
  Canvas seedReference;
  mini_ui::drawText(seedReference, "1", 2, 2, {66, 117, 199});
  mini_ui::drawText(seedReference, "16", 62 - mini_ui::measure("16"), 2, {66, 117, 199});
  for (int y = 2; y < 7; ++y) for (int x = 0; x < 64; ++x) {
    const auto expected = seedReference.pixels[y * 64 + x];
    if (expected.r || expected.g || expected.b) {
      const auto actual = seededCanvas.pixels[y * 64 + x];
      assert(actual.r == expected.r && actual.g == expected.g && actual.b == expected.b);
    }
  }
  assert(mini_ui::measure("4TH & 15") == 27);
  assert(mini_ui::measure("2ND & GOAL", {3, 5, 0, false, 2}) == 28);
  assert(mini_ui::measure("4TH & 15") <= mini_ui::CONTENT_WIDTH);
  mini_ui::SportsPane football;
  football.sport = mini_ui::Sport::Football;
  football.live = true;
  football.awayScore = "23";
  football.homeScore = "7";
  football.footer = "4TH & 15";
  Canvas down;
  mini_ui::draw(down, football);
  for (int y = 20; y < 23; ++y) {
    for (int x = mini_ui::CONTENT_LEFT; x < mini_ui::CONTENT_LEFT + mini_ui::CONTENT_WIDTH; ++x) {
      const auto pixel = down.pixels[y * 64 + x];
      assert(pixel.r == 0 && pixel.g == 0 && pixel.b == 0);
    }
  }
  bool footerDrawn = false;
  for (int y = 23; y < 28; ++y) {
    for (int x = mini_ui::CONTENT_LEFT; x < mini_ui::CONTENT_LEFT + mini_ui::CONTENT_WIDTH; ++x) {
      const auto pixel = down.pixels[y * 64 + x];
      footerDrawn |= pixel.r || pixel.g || pixel.b;
    }
  }
  assert(footerDrawn);
  for (auto side : {mini_ui::Side::Away, mini_ui::Side::Home}) {
    football.active = side;
    Canvas possession;
    mini_ui::draw(possession, football);
    const int center = side == mini_ui::Side::Away ? 7 : 55;
    assert(possession.pixels[3 * 64 + center - 4].r == 110);
    assert(possession.pixels[3 * 64 + center + 4].r == 110);
  }
  for (const std::string label : {"0:45 #88", "10:00 #20"}) {
    assert(mini_ui::measure(label, {3, 5, 0}) <= mini_ui::CONTENT_WIDTH);
    Canvas penalty;
    mini_ui::sports::footer(penalty, label, {255, 255, 255});
    bool drawn = false;
    for (int y = 0; y < 32; ++y) for (int x = 0; x < 64; ++x) {
      const bool lit = penalty.pixels[y * 64 + x].r;
      if (y < 23 || y > 27) assert(!lit);
      drawn |= lit;
    }
    assert(drawn);
  }
  JsonDocument longPenalty;
  longPenalty["sport"] = "nhl";
  longPenalty["state"] = "in";
  longPenalty["situation"]["manpower"]["scrollLabel"] = "0:45 #88 | 1:30 #99";
  const auto longView = mini_ui::sportsPane(longPenalty.as<JsonObjectConst>());
  assert(longView.footer == "0:45 #88 | 1:30 #99");
  Canvas paired;
  mini_ui::sports::footer(paired, longView.footer, {255, 255, 255});
  Canvas pairedExpected;
  mini_ui::center(pairedExpected, "0:45 #88", mini_ui::CONTENT_LEFT, mini_ui::CONTENT_WIDTH, 20, {255, 255, 255}, {3, 5, 0});
  mini_ui::center(pairedExpected, "1:30 #99", mini_ui::CONTENT_LEFT, mini_ui::CONTENT_WIDTH, 26, {255, 255, 255}, {3, 5, 0});
  for (size_t index = 0; index < paired.pixels.size(); ++index) assert(paired.pixels[index].r == pairedExpected.pixels[index].r);
  JsonArray penaltyRows = longPenalty["situation"]["manpower"]["penalties"].to<JsonArray>();
  for (int number : {88, 99}) {
    JsonObject entry = penaltyRows.add<JsonObject>();
    entry["timeRemaining"] = "0:45";
    entry["jerseyNumber"] = number;
  }
  const auto stacked = mini_ui::sportsPane(longPenalty.as<JsonObjectConst>());
  assert(stacked.penaltyCount == 2 && stacked.footer.empty());
  assert(stacked.penalties[0].number == "88" && stacked.penalties[1].number == "99");
  Canvas actualRows, expectedRows;
  mini_ui::draw(actualRows, stacked);
  mini_ui::sports::penalty(expectedRows, stacked.penalties[0], 20, mini_ui::MUTED_TEXT);
  mini_ui::sports::penalty(expectedRows, stacked.penalties[1], 26, mini_ui::MUTED_TEXT);
  for (int y = 20; y < 31; ++y) for (int x = mini_ui::CONTENT_LEFT; x < mini_ui::CONTENT_LEFT + mini_ui::CONTENT_WIDTH; ++x) {
    const auto actual = actualRows.pixels[y * 64 + x], expected = expectedRows.pixels[y * 64 + x];
    assert(actual.r == expected.r && actual.g == expected.g && actual.b == expected.b);
  }
  for (const mini_ui::Penalty penalty : {mini_ui::Penalty{"0:45", "88"}, mini_ui::Penalty{"10:00", "20"}}) {
    const int numberWidth = mini_ui::measure("#" + penalty.number);
    const int gap = mini_ui::measureInk(penalty.clock, 1) + 2 + numberWidth <= mini_ui::CONTENT_WIDTH ? 1 : 0;
    assert(mini_ui::measureInk(penalty.clock, gap) + 2 + numberWidth == mini_ui::CONTENT_WIDTH);
  }
  Canvas glyph;
  mini_ui::drawText(glyph, "#", 0, 0, {255, 255, 255});
  assert(mini_ui::measure("#88") == 13);
  for (int y = 0; y < 5; ++y) {
    for (int x = 0; x < 5; ++x) {
      const bool lit = x == 1 || x == 3 || y == 1 || y == 3;
      assert(glyph.pixels[y * 64 + x].r == (lit ? 255 : 0));
    }
  }
  for (const char* league : {"nfl", "ncf_fbs", "ncf_fcs", "mlb", "wbc", "nba", "march_madness", "nhl", "soccer_mls"}) {
    for (int stage : {0, 1, 2}) {
      JsonDocument game;
      game["sport"] = league;
      game["status"] = "FINAL";
      game["state"] = "post";
      game["competition_stage"] = stage;
      Canvas canvas;
      mini_ui::draw(canvas, mini_ui::sportsPane(game.as<JsonObjectConst>()));
      const auto expectedRule = stage == 2 ? mini_ui::FINALS_RULE :
                                stage == 1 ? mini_ui::PLAYOFF_RULE : mini_ui::HEADER_RULE;
      for (int x = 0; x < 64; ++x) {
        const auto actual = canvas.pixels[7 * 64 + x];
        assert(actual.r == expectedRule.r && actual.g == expectedRule.g && actual.b == expectedRule.b);
      }
    }
  }
  std::cout << "Mini hockey, football spacing, glyphs, and tournament rules passed\n";
}

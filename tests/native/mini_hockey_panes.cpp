#include "panels.h"
#include "payload_reader.h"
#include "response_body.h"
#include <array>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>

struct Canvas {
  std::array<ticker_ui::Rgb, 64 * 32> pixels{};
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    if (x >= 0 && y >= 0 && x < 64 && y < 32) pixels[y * 64 + x] = ink;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int row = y; row < y + height; ++row)
      for (int column = x; column < x + width; ++column) pixel(column, row, ink);
  }
  bool logo(ticker_ui::Side, int, int) { return false; }
};

ticker_ui::Shot expected(const std::string& value) {
  using ticker_ui::Shot;
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
    const auto view = ticker_ui::sportsPane(row["game"]);
    const auto rounds = row["game"]["situation"]["shootout"]["displayRounds"].as<JsonArrayConst>();
    assert(view.shootout == (rounds.size() > 0));
    assert(view.shotCount == static_cast<int>(rounds.size()));
    if (view.shootout) assert(view.footer == row["game"]["situation"]["shootout"]["roundLabel"].as<std::string>());
    for (int index = 0; index < view.shotCount; ++index) {
      assert(view.awayShots[index] == expected(row["away_shots"][index].as<std::string>()));
      assert(view.homeShots[index] == expected(row["home_shots"][index].as<std::string>()));
    }
    Canvas canvas;
    ticker_ui::renderSports(canvas, view);
    for (int index = 0; index < view.shotCount; ++index) {
      for (int side = 0; side < 2; ++side) {
        const auto state = side ? view.homeShots[index] : view.awayShots[index];
        const int x = side ? 64 - ticker_ui::CONTENT_LEFT - 3 : ticker_ui::CONTENT_LEFT;
        const auto color = canvas.pixels[(9 + index * 6) * 64 + x];
        if (state == ticker_ui::Shot::Next) assert(color.r == 255 && color.g == 210 && color.b == 40);
        if (state == ticker_ui::Shot::NotTaken) assert(color.r == 0 && color.g == 0 && color.b == 0);
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
  assert(ticker_ui::textWidth("3RD & 6") == 23);
  assert(ticker_ui::textWidth("4TH & 15") == 27);
  assert(ticker_ui::textWidth("4TH & 15") <= ticker_ui::CONTENT_WIDTH);
  ticker_ui::SportsPane football;
  football.sport = ticker_ui::Sport::Football;
  football.live = true;
  football.awayScore = "23";
  football.homeScore = "7";
  football.footer = "4TH & 15";
  Canvas down;
  ticker_ui::renderSports(down, football);
  for (int y = 20; y < 23; ++y) {
    for (int x = ticker_ui::CONTENT_LEFT; x < ticker_ui::CONTENT_LEFT + ticker_ui::CONTENT_WIDTH; ++x) {
      const auto pixel = down.pixels[y * 64 + x];
      assert(pixel.r == 0 && pixel.g == 0 && pixel.b == 0);
    }
  }
  bool footerDrawn = false;
  for (int y = 23; y < 28; ++y) {
    for (int x = ticker_ui::CONTENT_LEFT; x < ticker_ui::CONTENT_LEFT + ticker_ui::CONTENT_WIDTH; ++x) {
      const auto pixel = down.pixels[y * 64 + x];
      footerDrawn |= pixel.r || pixel.g || pixel.b;
    }
  }
  assert(footerDrawn);
  for (auto side : {ticker_ui::Side::Away, ticker_ui::Side::Home}) {
    football.active = side;
    Canvas possession;
    ticker_ui::renderSports(possession, football);
    const int center = side == ticker_ui::Side::Away ? 7 : 55;
    assert(possession.pixels[3 * 64 + center - 4].r == 110);
    assert(possession.pixels[3 * 64 + center + 4].r == 110);
  }
  Canvas glyph;
  ticker_ui::text(glyph, "#", 0, 0, {255, 255, 255});
  assert(ticker_ui::textWidth("#88") == 13);
  for (int y = 0; y < 5; ++y) {
    for (int x = 0; x < 5; ++x) {
      const bool lit = x == 1 || x == 3 || y == 1 || y == 3;
      assert(glyph.pixels[y * 64 + x].r == (lit ? 255 : 0));
    }
  }
  std::cout << "Mini response growth, NHL rounds, next shooter, completed attempts, playoff overtime, football spacing, and hash glyph passed\n";
}

#include "panels.h"
#include "device_payload.h"
#include <array>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

struct Canvas {
  std::array<ticker_ui::Rgb, 64 * 32> pixels{};
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    assert(x >= 0 && x < 64 && y >= 0 && y < 32);
    pixels[y * 64 + x] = ink;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int row = 0; row < height; ++row) for (int column = 0; column < width; ++column) pixel(x + column, y + row, ink);
  }
};

bool same(ticker_ui::Rgb a, ticker_ui::Rgb b) { return a.r == b.r && a.g == b.g && a.b == b.b; }

int main(int argc, char** argv) {
  assert(argc >= 2);
  // A long class, session and lap counter cannot all fit beside the flag.
  // Keep the class in place while alternating complete session and lap text.
  {
    ticker_ui::RacingPane view;
    view.group = "LMGT3"; view.session = "RACE"; view.status = "65/200";
    Canvas first, second, sessionOnly, lapOnly;
    ticker_ui::renderRacing(first, view);
    view.elapsedMs = 3000;
    ticker_ui::renderRacing(second, view);
    auto expected = view; expected.elapsedMs = 0; expected.status.clear();
    ticker_ui::renderRacing(sessionOnly, expected);
    expected.session.clear(); expected.status = "65/200";
    ticker_ui::renderRacing(lapOnly, expected);
    for (int y = 6; y < 11; ++y) for (int x = 0; x < 50; ++x) {
      assert(same(first.pixels[y * 64 + x], sessionOnly.pixels[y * 64 + x]));
      assert(same(second.pixels[y * 64 + x], lapOnly.pixels[y * 64 + x]));
    }
  }
  {
    ticker_ui::RacingPane view;
    view.group = "Q G2"; view.count = 1;
    view.rows[0].position = 1; view.rows[0].car = "10"; view.rows[0].name = "PAL";
    view.rows[0].gap = "1:09.1398";
    Canvas longTime, shortTime;
    ticker_ui::renderRacing(longTime, view);
    view.rows[0].gap = "1:09.139";
    assert(ticker_ui::textWidth(view.rows[0].gap) <= 31);
    ticker_ui::renderRacing(shortTime, view);
    for (int y = 13; y < 18; ++y) for (int x = 33; x < 64; ++x)
      assert(same(longTime.pixels[y * 64 + x], shortTime.pixels[y * 64 + x]));
  }
  std::ifstream input(argv[1]);
  JsonDocument fixture;
  assert(!deserializeJson(fixture, input, DeserializationOption::NestingLimit(24)));
  int frames = 0;
  for (JsonObjectConst example : fixture["cases"].as<JsonArrayConst>()) {
    std::string wire;
    serializeJson(example["payload"], wire);
    ResponseBody body;
    assert(body.append(reinterpret_cast<const unsigned char*>(wire.data()), wire.size()) == wire.size());
    DevicePayload retained;
    assert(retained.accept(body));
    JsonArrayConst items = retained.document()["content"]["racing"].as<JsonArrayConst>();
    assert(items.size() > 0);
    for (JsonObjectConst item : items) {
      const auto view = ticker_ui::racingPane(item["data"], example["elapsed_ms"] | 0U, example["elapsed_ms"] | 0U);
      assert(view.signalPresent);
      assert(!view.race.empty() && !view.group.empty());
      Canvas canvas;
      ticker_ui::renderRacing(canvas, view);
      assert(view.signal.width == 11);
      if (example["name"] == "flag-green") {
        assert(view.metricType == "MPH");
        Canvas liveHeader, expectedMphHeader;
        auto liveView = view;
        liveView.status = "LIVE";
        ticker_ui::renderRacing(liveHeader, liveView);
        auto expectedView = liveView;
        expectedView.status = "MPH";
        expectedView.metricType = "";
        ticker_ui::renderRacing(expectedMphHeader, expectedView);
        for (int y = 6; y < 11; ++y) for (int x = 31; x < 50; ++x)
          assert(same(liveHeader.pixels[y * 64 + x], expectedMphHeader.pixels[y * 64 + x]));
        Canvas timeHeader, expectedTimeHeader;
        liveView.metricType = "LAP_TIME";
        ticker_ui::renderRacing(timeHeader, liveView);
        expectedView.status = "TIME";
        ticker_ui::renderRacing(expectedTimeHeader, expectedView);
        for (int y = 6; y < 11; ++y) for (int x = 31; x < 50; ++x)
          assert(same(timeHeader.pixels[y * 64 + x], expectedTimeHeader.pixels[y * 64 + x]));
        Canvas metricHeader;
        auto metricView = view;
        metricView.elapsedMs = 3000;
        ticker_ui::renderRacing(metricHeader, metricView);
        bool headerChanged = false;
        for (int y = 6; y < 11; ++y) for (int x = 31; x < 50; ++x)
          headerChanged = headerChanged || !same(canvas.pixels[y * 64 + x], metricHeader.pixels[y * 64 + x]);
        assert(headerChanged);
        const auto top = canvas.pixels[6 * 64 + 53];
        const auto bottom = canvas.pixels[11 * 64 + 53];
        assert(top.g > 0 && same(top, bottom));
      }
      if (view.signal.alternateMs) {
        Canvas alternate;
        auto next = view;
        next.signalPhaseMs += view.signal.alternateMs;
        ticker_ui::renderRacing(alternate, next);
        bool changed = false;
        for (int y = 6; y < 12; ++y) for (int x = 64 - view.signal.width; x < 64; ++x)
          changed = changed || !same(canvas.pixels[y * 64 + x], alternate.pixels[y * 64 + x]);
        assert(changed);
        if (view.signal.alternateBoardFlashes) {
          Canvas boardOff;
          next.signalPhaseMs += 500;
          ticker_ui::renderRacing(boardOff, next);
          bool boardChanged = false;
          for (int y = 6; y < 12; ++y) for (int x = 64 - view.signal.width; x < 64; ++x)
            boardChanged = boardChanged || !same(alternate.pixels[y * 64 + x], boardOff.pixels[y * 64 + x]);
          assert(boardChanged);
        }
        for (int y = 13; y < 32; ++y) for (int x = 33; x < 64; ++x)
          assert(same(canvas.pixels[y * 64 + x], alternate.pixels[y * 64 + x]));
      }
      const ticker_ui::Rgb expected[] = {{255, 215, 0}, {192, 192, 192}, {205, 127, 50}};
      for (int row = 0; row < view.count; ++row) {
        bool medal = false;
        for (int y = 13 + row * 7; y < 18 + row * 7; ++y)
          for (int x = 0; x < 4; ++x) medal = medal || same(canvas.pixels[y * 64 + x], expected[row]);
        assert(medal);
      }
      if (argc > 2) {
        std::filesystem::create_directories(argv[2]);
        const std::string name = example["name"] | "frame";
        const std::string id = item["id"] | "";
        std::ofstream output(std::filesystem::path(argv[2]) / (name + "-" + std::to_string(frames) + ".ppm"), std::ios::binary);
        output << "P6\n64 32\n255\n";
        for (auto pixel : canvas.pixels) { output.put(pixel.r); output.put(pixel.g); output.put(pixel.b); }
      }
      ++frames;
    }
  }
  std::vector<std::string> ids;
  ticker_ui::forEachRotationItem(fixture["rotation"]["content"].as<JsonObjectConst>(), true,
                               [&](JsonObjectConst item) { ids.push_back(item["id"] | ""); });
  assert(ids.size() == 5 && ids[0] == "hockey");
  assert(ids[1] == "vector:GTP" && ids[2] == "vector:LMP2" && ids[3] == "vector:GTDPRO" && ids[4] == "vector:GTD");
  JsonDocument mixed;
  auto games = mixed["sports"].to<JsonArray>();
  games.add<JsonObject>()["id"] = "early"; games[0]["rotation_order"] = 0;
  games.add<JsonObject>()["id"] = "late"; games[1]["rotation_order"] = 2;
  auto races = mixed["racing"].to<JsonArray>();
  races.add<JsonObject>()["id"] = "race:A"; races[0]["rotation_order"] = 1;
  races.add<JsonObject>()["id"] = "race:B"; races[1]["rotation_order"] = 1;
  ids.clear();
  ticker_ui::forEachRotationItem(mixed.as<JsonObjectConst>(), true,
                               [&](JsonObjectConst item) { ids.push_back(item["id"] | ""); });
  assert((ids == std::vector<std::string>{"early", "race:A", "race:B", "late"}));
  JsonDocument wirePayload;
  wirePayload["api_version"] = "v2"; wirePayload["settings"]["mode"] = "sports";
  wirePayload["meta"]["pairing"]["paired"] = true; wirePayload["content"] = mixed;
  std::string mixedWire; serializeJson(wirePayload, mixedWire);
  ResponseBody mixedBody;
  assert(mixedBody.append(reinterpret_cast<const unsigned char*>(mixedWire.data()), mixedWire.size()) == mixedWire.size());
  DevicePayload mixedRetained; assert(mixedRetained.accept(mixedBody));
  ids.clear();
  ticker_ui::forEachRotationItem(mixedRetained.document()["content"].as<JsonObjectConst>(), true,
                               [&](JsonObjectConst item) { ids.push_back(item["id"] | ""); });
  assert((ids == std::vector<std::string>{"early", "race:A", "race:B", "late"}));
  ids.clear();
  ticker_ui::forEachRotationItem(fixture["rotation"]["content"].as<JsonObjectConst>(), false,
                               [&](JsonObjectConst item) { ids.push_back(item["id"] | ""); });
  assert(ids.size() == 1 && ids[0] == "stock");
  std::cout << "Validated " << frames << " Mini racing frames, retained filters, class rotation, and podium colors\n";
}

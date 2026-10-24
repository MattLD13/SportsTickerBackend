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
      if (example["name"] == "car-signal") assert(view.signal.label == "PI45");
      if (example["name"] == "sector-signal") assert(view.signal.label == "2 S2");
      Canvas canvas;
      ticker_ui::renderRacing(canvas, view);
      if (view.signal.flashing) {
        Canvas alternate;
        auto next = view;
        next.signalPhaseMs += 350;
        ticker_ui::renderRacing(alternate, next);
        bool changed = false;
        for (int y = 6; y < 11; ++y) for (int x = 59; x < 64; ++x)
          changed = changed || !same(canvas.pixels[y * 64 + x], alternate.pixels[y * 64 + x]);
        assert(changed);
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
  ids.clear();
  ticker_ui::forEachRotationItem(fixture["rotation"]["content"].as<JsonObjectConst>(), false,
                               [&](JsonObjectConst item) { ids.push_back(item["id"] | ""); });
  assert(ids.size() == 1 && ids[0] == "stock");
  std::cout << "Validated " << frames << " Mini racing frames, retained filters, class rotation, and podium colors\n";
}

// Render the production Mini sports code into portable RGB images.
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <panels.h>
#include <mini_sprite.h>

struct Sprite {
  bool ready = false;
  std::array<uint16_t, ticker_ui::MINI_LOGO_SIZE * ticker_ui::MINI_LOGO_SIZE> pixels{};
  std::array<uint8_t, ticker_ui::MINI_LOGO_SIZE * ticker_ui::MINI_LOGO_SIZE> mask{};
  explicit Sprite(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    std::array<uint8_t, mini_sprite::kBytes> bytes{};
    if (stream.read(reinterpret_cast<char*>(bytes.data()), bytes.size())) {
      mini_sprite::decodeScaled(bytes.data(), pixels.data(), mask.data(), ticker_ui::MINI_LOGO_SIZE);
      ready = true;
    }
  }
};

struct Canvas {
  std::array<uint8_t, 64 * 32 * 3> pixels{};
  Sprite away, home;
  Canvas(const std::string& a, const std::string& h) : away(a), home(h) {}
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    if (x < 0 || x >= 64 || y < 0 || y >= 32) return;
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = (ink.r >> 3) * 255 / 31;
    pixels[offset + 1] = (ink.g >> 2) * 255 / 63;
    pixels[offset + 2] = (ink.b >> 3) * 255 / 31;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
  bool logo(ticker_ui::Side side, int x, int y) {
    const Sprite& source = side == ticker_ui::Side::Away ? away : home;
    if (!source.ready) return false;
    for (int index = 0; index < ticker_ui::MINI_LOGO_SIZE * ticker_ui::MINI_LOGO_SIZE; ++index) {
      if (!source.mask[index]) continue;
      const uint16_t value = source.pixels[index];
      pixel(x + index % ticker_ui::MINI_LOGO_SIZE, y + index / ticker_ui::MINI_LOGO_SIZE, {static_cast<uint8_t>(((value >> 11) & 31) * 255 / 31),
          static_cast<uint8_t>(((value >> 5) & 63) * 255 / 63), static_cast<uint8_t>((value & 31) * 255 / 31)});
    }
    return true;
  }
  void save(const std::filesystem::path& path) {
    std::ofstream stream(path, std::ios::binary);
    stream << "P6\n64 32\n255\n";
    stream.write(reinterpret_cast<const char*>(pixels.data()), pixels.size());
  }
};

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  JsonDocument document;
  if (deserializeJson(document, input)) return 3;
  std::filesystem::create_directories(argv[2]);
  int count = 0;
  for (JsonObjectConst row : document.as<JsonArrayConst>()) {
    Canvas canvas(row["away_sprite"] | "", row["home_sprite"] | "");
    const std::string mode = row["mode"] | "sports";
    if (mode == "stock") ticker_ui::renderStock(canvas, ticker_ui::stockPane(row["game"].as<JsonObjectConst>()));
    else if (mode == "clock") {
      ticker_ui::ClockPane view;
      view.ready = true; view.date = row["game"]["date"] | ""; view.time = row["game"]["time"] | ""; view.seconds = row["game"]["seconds"] | 0;
      ticker_ui::renderClock(canvas, view);
    } else ticker_ui::renderSports(canvas, ticker_ui::sportsPane(row["game"].as<JsonObjectConst>()));
    const std::string name = row["name"] | "frame";
    canvas.save(std::filesystem::path(argv[2]) / (name + ".ppm"));
    ++count;
  }
  std::cout << "Rendered " << count << " Mini frames from the firmware drawing code\n";
}

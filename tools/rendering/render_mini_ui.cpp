// Render the production Mini panels into portable RGB frame atlases.
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <panels.h>
#include <mini_sprite.h>
#include <mini_artwork.h>

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
  std::array<uint8_t, mini_artwork::Bytes> cover{};
  bool coverReady = false;
  Canvas(const std::string& a, const std::string& h, const std::string& artwork = "") : away(a), home(h) {
    std::ifstream input(artwork, std::ios::binary);
    coverReady = static_cast<bool>(input.read(reinterpret_cast<char*>(cover.data()), cover.size())) && memcmp(cover.data(), "MTA1", 4) == 0;
  }
  bool artwork() {
    if (!coverReady) return false;
    for (size_t y = 0; y < 32; ++y) for (size_t x = 0; x < 32; ++x) {
      const uint16_t value = mini_sprite::little16(cover.data() + 16 + (y * 32 + x) * 2);
      pixel(x, y, {static_cast<uint8_t>(((value >> 11) & 31) * 255 / 31),
                   static_cast<uint8_t>(((value >> 5) & 63) * 255 / 63), static_cast<uint8_t>((value & 31) * 255 / 31)});
    }
    return true;
  }
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    if (x < 0 || x >= 64 || y < 0 || y >= 32) return;
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = (ink.r & 248) | (ink.r >> 5);
    pixels[offset + 1] = (ink.g & 252) | (ink.g >> 6);
    pixels[offset + 2] = (ink.b & 248) | (ink.b >> 5);
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

};

bool renderPanel(Canvas& canvas, const std::string& mode, JsonObjectConst game, JsonObjectConst row, uint32_t elapsed) {
      if (mode == "pairing") ticker_ui::renderPairing(canvas, ticker_ui::pairingPane(game["wifi_setup"] | false, game["wifi_pin"] | "", game["app_code"] | "", elapsed));
      else if (mode == "stock") ticker_ui::renderStock(canvas, ticker_ui::stockPane(game));
      else if (mode == "weather") ticker_ui::renderWeather(canvas, ticker_ui::weatherPane(game, (row["elapsed_ms"] | 0) + elapsed));
      else if (mode == "music") ticker_ui::renderMusic(canvas, ticker_ui::musicPane(game, (row["now_epoch"] | 1800000000.0) + elapsed / 1000.0, (row["scroll_ms"] | 0) + elapsed));
      else if (mode == "flights") ticker_ui::renderFlight(canvas, ticker_ui::flightPane(game));
      else if (mode == "airports") ticker_ui::renderAirport(canvas, ticker_ui::airportPane(game, (row["elapsed_ms"] | 0) + elapsed));
      else if (mode == "message") {
        ticker_ui::SystemPane view;
        if (!ticker_ui::systemPane(game, (row["elapsed_ms"] | 0) + elapsed, view)) return false;
        JsonObjectConst background = game["background"].as<JsonObjectConst>();
        const std::string backgroundMode = background["mode"] | "";
        if (!background.isNull() && ticker_ui::systemOverlay(view.kind) && backgroundMode != "message") {
          if (!renderPanel(canvas, backgroundMode, background["game"].as<JsonObjectConst>(), row, elapsed)) return false;
          ticker_ui::renderSystemOverlay(canvas, view);
        } else ticker_ui::renderSystem(canvas, view);
      }
      else if (mode == "clock") {
        ticker_ui::ClockPane view;
        view.elapsedMs = elapsed;
        view.ready = game["ready"] | true; view.date = game["date"] | ""; view.time = game["time"] | ""; view.seconds = game["seconds"] | 0;
        ticker_ui::renderClock(canvas, view);
      } else if (mode == "sports") ticker_ui::renderSports(canvas, ticker_ui::sportsPane(game));
      else return false;
  return true;
}

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  JsonDocument document;
  if (deserializeJson(document, input)) return 3;
  std::filesystem::create_directories(argv[2]);
  int count = 0;
  for (JsonObjectConst row : document.as<JsonArrayConst>()) {
    const std::string name = row["name"] | "frame";
    const int frames = row["frame_count"] | 1;
    if (frames < 1 || frames > 2000) return 4;
    std::ofstream output(std::filesystem::path(argv[2]) / (name + ".ppm"), std::ios::binary);
    output << "P6\n64 " << frames * 32 << "\n255\n";
    for (int index = 0; index < frames; ++index) {
      const uint32_t elapsed = index * (row["frame_ms"] | 100);
      Canvas canvas(row["away_sprite"] | "", row["home_sprite"] | "", row["cover_artwork"] | "");
      const std::string mode = row["mode"] | "sports";
      if (!renderPanel(canvas, mode, row["game"].as<JsonObjectConst>(), row, elapsed)) return 5;
      output.write(reinterpret_cast<const char*>(canvas.pixels.data()), canvas.pixels.size());
      ++count;
    }
  }
  std::cout << "Rendered " << count << " Mini frames from the firmware drawing code\n";
}

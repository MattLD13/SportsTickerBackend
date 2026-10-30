// Render the production Mini panels into portable RGB frame atlases, or print one digest for each row.
// A sprite or artwork path "standin:<seed>" gives deterministic stand-in pixels, so a golden case reads no file.
#include <array>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <panes.h>
#include <mini_sprite.h>
#include <mini_artwork.h>

struct Sprite {
  bool ready = false;
  std::array<uint16_t, mini_ui::MINI_LOGO_SIZE * mini_ui::MINI_LOGO_SIZE> pixels{};
  std::array<uint8_t, mini_ui::MINI_LOGO_SIZE * mini_ui::MINI_LOGO_SIZE> mask{};
  explicit Sprite(const std::string& path) {
    if (path.rfind("standin:", 0) == 0) {
      const uint32_t seed = static_cast<uint32_t>(std::stoul(path.substr(8)));
      const int size = mini_ui::MINI_LOGO_SIZE, middle = size / 2;
      for (int index = 0; index < size * size; ++index) {
        const int x = index % size - middle, y = index / size - middle;
        mask[index] = x * x + y * y <= (middle - 1) * (middle - 1);
        pixels[index] = static_cast<uint16_t>((seed * 2654435761u >> (y == 0 ? 3 : 16)) & 0xffff);
      }
      ready = true;
      return;
    }
    std::ifstream stream(path, std::ios::binary);
    std::array<uint8_t, mini_sprite::kBytes> bytes{};
    if (stream.read(reinterpret_cast<char*>(bytes.data()), bytes.size())) {
      mini_sprite::decodeScaled(bytes.data(), pixels.data(), mask.data(), mini_ui::MINI_LOGO_SIZE);
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
    if (artwork.rfind("standin:", 0) == 0) {
      const uint32_t seed = static_cast<uint32_t>(std::stoul(artwork.substr(8)));
      memcpy(cover.data(), "MTA1", 4);
      for (size_t index = 0; index < 32 * 32; ++index) {
        const uint16_t value = static_cast<uint16_t>((seed * 40503u + index * (index % 7 + 1)) & 0xffff);
        cover[16 + index * 2] = value & 0xff;
        cover[17 + index * 2] = value >> 8;
      }
      coverReady = true;
      return;
    }
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
  void pixel(int x, int y, mini_ui::Rgb ink) {
    if (x < 0 || x >= 64 || y < 0 || y >= 32) return;
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = (ink.r & 248) | (ink.r >> 5);
    pixels[offset + 1] = (ink.g & 252) | (ink.g >> 6);
    pixels[offset + 2] = (ink.b & 248) | (ink.b >> 5);
  }
  void rect(int x, int y, int width, int height, mini_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
  bool logo(mini_ui::Side side, int x, int y) {
    const Sprite& source = side == mini_ui::Side::Away ? away : home;
    if (!source.ready) return false;
    for (int index = 0; index < mini_ui::MINI_LOGO_SIZE * mini_ui::MINI_LOGO_SIZE; ++index) {
      if (!source.mask[index]) continue;
      const uint16_t value = source.pixels[index];
      pixel(x + index % mini_ui::MINI_LOGO_SIZE, y + index / mini_ui::MINI_LOGO_SIZE, {static_cast<uint8_t>(((value >> 11) & 31) * 255 / 31),
          static_cast<uint8_t>(((value >> 5) & 63) * 255 / 63), static_cast<uint8_t>((value & 31) * 255 / 31)});
    }
    return true;
  }

};

bool renderPanel(Canvas& canvas, const std::string& mode, JsonObjectConst game, JsonObjectConst row, uint32_t elapsed) {
      if (mode == "pairing") mini_ui::draw(canvas, mini_ui::pairingPane(game["wifi_setup"] | false, game["wifi_pin"] | "", game["app_code"] | "", elapsed));
      else if (mode == "stock") mini_ui::draw(canvas, mini_ui::stockPane(game));
      else if (mode == "weather") mini_ui::draw(canvas, mini_ui::weatherPane(game, (row["elapsed_ms"] | 0) + elapsed));
      else if (mode == "music") mini_ui::draw(canvas, mini_ui::musicPane(game, (row["now_epoch"] | 1800000000.0) + elapsed / 1000.0, (row["scroll_ms"] | 0) + elapsed));
      else if (mode == "flights") mini_ui::draw(canvas, mini_ui::flightPane(game));
      else if (mode == "airports") mini_ui::draw(canvas, mini_ui::airportPane(game, (row["elapsed_ms"] | 0) + elapsed));
      else if (mode == "message") {
        mini_ui::SystemPane view;
        if (!mini_ui::systemPane(game, (row["elapsed_ms"] | 0) + elapsed, view)) return false;
        JsonObjectConst background = game["background"].as<JsonObjectConst>();
        const std::string backgroundMode = background["mode"] | "";
        if (!background.isNull() && mini_ui::systemOverlay(view.kind) && backgroundMode != "message") {
          if (!renderPanel(canvas, backgroundMode, background["game"].as<JsonObjectConst>(), row, elapsed)) return false;
          mini_ui::drawOverlay(canvas, view);
        } else mini_ui::draw(canvas, view);
      }
      else if (mode == "clock") {
        mini_ui::ClockPane view;
        view.elapsedMs = elapsed;
        view.ready = game["ready"] | true; view.date = game["date"] | ""; view.time = game["time"] | ""; view.seconds = game["seconds"] | 0;
        mini_ui::draw(canvas, view);
      } else if (mode == "sports") {
        if (game["racing_display"].is<JsonObjectConst>())
          mini_ui::draw(canvas, mini_ui::racingPane(game, (row["elapsed_ms"] | 0) + elapsed, (row["signal_ms"] | 0) + elapsed));
        else mini_ui::draw(canvas, mini_ui::sportsPane(game));
      }
      else return false;
  return true;
}

// Usage: render_mini_ui input.json frames-directory   (write one PPM atlas for each row)
//        render_mini_ui input.json --digest              (print one FNV-1a digest for each row)
int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  JsonDocument document;
  if (deserializeJson(document, input)) return 3;
  const bool digest = std::string(argv[2]) == "--digest";
  if (!digest) std::filesystem::create_directories(argv[2]);
  int count = 0;
  for (JsonObjectConst row : document.as<JsonArrayConst>()) {
    const std::string name = row["name"] | "frame";
    const int frames = row["frame_count"] | 1;
    if (frames < 1 || frames > 2000) return 4;
    std::ofstream output;
    if (!digest) {
      output.open(std::filesystem::path(argv[2]) / (name + ".ppm"), std::ios::binary);
      output << "P6\n64 " << frames * 32 << "\n255\n";
    }
    uint64_t hash = 1469598103934665603ull;
    for (int index = 0; index < frames; ++index) {
      const uint32_t elapsed = index * (row["frame_ms"] | 100);
      Canvas canvas(row["away_sprite"] | "", row["home_sprite"] | "", row["cover_artwork"] | "");
      const std::string mode = row["mode"] | "sports";
      if (!renderPanel(canvas, mode, row["game"].as<JsonObjectConst>(), row, elapsed)) {
        if (!digest) return 5;
        hash = 0;
        break;
      }
      if (digest) for (uint8_t value : canvas.pixels) hash = (hash ^ value) * 1099511628211ull;
      else output.write(reinterpret_cast<const char*>(canvas.pixels.data()), canvas.pixels.size());
      ++count;
    }
    if (digest) std::printf("%016llx\n", static_cast<unsigned long long>(hash));
  }
  if (!digest) std::cout << "Rendered " << count << " Mini frames from the firmware drawing code\n";
}

#include <array>
#include <cassert>
#include <iostream>
#include <panels.h>

struct Canvas {
  std::array<uint8_t, 64 * 32 * 3> pixels{};
  void pixel(int x, int y, ticker_ui::Rgb ink) {
    assert(x >= 0 && x < 64 && y >= 0 && y < 32);
    const int offset = (y * 64 + x) * 3;
    pixels[offset] = ink.r; pixels[offset + 1] = ink.g; pixels[offset + 2] = ink.b;
  }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) {
    for (int dy = 0; dy < height; ++dy) for (int dx = 0; dx < width; ++dx) pixel(x + dx, y + dy, ink);
  }
};

int main() {
  JsonDocument data;
  data["city"] = "BETHLEHEM";
  data["icon"] = "sun"; data["is_day"] = 1;
  data["temperature"] = 72; data["feels"] = 70;
  data["wind"] = 8; data["humidity"] = 53; data["aqi"] = 31;
  const auto day = ticker_ui::weatherPane(data.as<JsonObjectConst>(), 0);
  assert(day.temperature == "72" && day.feels == "70" && day.temperatureReady && !day.night);
  assert(day.sky == ticker_ui::WeatherSky::Clear && day.condition == "SUNNY");
  Canvas first;
  ticker_ui::renderWeather(first, day);
  data["is_day"] = false;
  const auto night = ticker_ui::weatherPane(data.as<JsonObjectConst>(), 0);
  assert(night.night && night.condition == "CLEAR");
  Canvas moon;
  ticker_ui::renderWeather(moon, night);
  assert(first.pixels != moon.pixels);
  Canvas humidity;
  ticker_ui::renderWeather(humidity, ticker_ui::weatherPane(data.as<JsonObjectConst>(), 5000));
  assert(moon.pixels != humidity.pixels);
  data["icon"] = "rain";
  Canvas rain, laterRain;
  ticker_ui::renderWeather(rain, ticker_ui::weatherPane(data.as<JsonObjectConst>(), 0));
  ticker_ui::renderWeather(laterRain, ticker_ui::weatherPane(data.as<JsonObjectConst>(), 300));
  assert(rain.pixels != laterRain.pixels);
  const auto* original = mini_weather_art::Pixels[mini_weather_art::Tracks[3][0]];
  for (int y = 0; y < mini_weather_art::Height; ++y) for (int x = 0; x < mini_weather_art::Width; ++x) {
    const uint16_t expected = original[y * mini_weather_art::Width + x];
    const int offset = ((9 + y) * 64 + 1 + x) * 3;
    assert(rain.pixels[offset] == ((expected >> 11) & 31) * 255 / 31);
    assert(rain.pixels[offset + 1] == ((expected >> 5) & 63) * 255 / 63);
    assert(rain.pixels[offset + 2] == (expected & 31) * 255 / 31);
  }
  for (const char* icon : {"sun", "cloud", "rain", "snow", "fog", "storm", "unknown"}) {
    data["icon"] = icon;
    for (int value : {-9999, -105, -8, 0, 72, 105, 9999}) {
      data["temperature"] = value; data["feels"] = value;
      data["wind"] = 123; data["humidity"] = 100; data["aqi"] = 500;
      for (int ms = 0; ms <= 11000; ms += 100) {
        Canvas frame;
        ticker_ui::renderWeather(frame, ticker_ui::weatherPane(data.as<JsonObjectConst>(), ms));
        const auto accent = ticker_ui::weatherAccent(ticker_ui::weatherPane(data.as<JsonObjectConst>(), ms));
        for (int x = 1; x < 63; ++x) {
          const int offset = (8 * 64 + x) * 3;
          assert(frame.pixels[offset] == accent.r / 6);
          assert(frame.pixels[offset + 1] == accent.g / 6);
          assert(frame.pixels[offset + 2] == accent.b / 6);
        }
      }
    }
  }
  data["city"] = "A VERY LONG CITY NAME";
  Canvas held, scrolled;
  ticker_ui::renderWeather(held, ticker_ui::weatherPane(data.as<JsonObjectConst>(), 0));
  ticker_ui::renderWeather(scrolled, ticker_ui::weatherPane(data.as<JsonObjectConst>(), 5000));
  bool changed = false;
  for (int x = 0; x < 64 * 6 * 3; ++x) changed |= held.pixels[x] != scrolled.pixels[x];
  assert(changed);
  data["temperature"] = nullptr; data["feels"] = nullptr; data["wind"] = "invalid";
  const auto missing = ticker_ui::weatherPane(data.as<JsonObjectConst>(), 0);
  assert(!missing.temperatureReady && missing.temperature == "--" && missing.feels == "--" && missing.wind == "--");
  Canvas blank;
  ticker_ui::renderWeather(blank, missing);
  std::cout << "Weather day/night, seven icons, two statistic pages, extremes, missing values, city scrolling, and bounds pass\n";
}

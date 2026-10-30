// Draw the city, the animated condition icon, the temperature, the condition, and two alternating stats.
#pragma once

#include "text.h"
#include "weather_art_generated.h"

namespace mini_ui {

enum class WeatherSky { Unknown, Clear, Cloud, Rain, Snow, Fog, Storm };

struct WeatherPane {
  std::string city, temperature, feels, wind, humidity, aqi, condition;
  WeatherSky sky = WeatherSky::Unknown;
  bool night = false, temperatureReady = false;
  int temperatureF = 0;
  uint32_t elapsedMs = 0;
};

namespace weather {

static constexpr Motion cityMotion{1400, 10, 1000, 9};

inline Rgb accent(const WeatherPane& view) {
  switch (view.sky) {
    case WeatherSky::Clear: return view.night ? Rgb{150, 175, 245} : Rgb{255, 205, 50};
    case WeatherSky::Rain: return {70, 155, 255};
    case WeatherSky::Snow: return {190, 230, 255};
    case WeatherSky::Storm: return {180, 130, 255};
    default: return {150, 175, 205};
  }
}

// The temperature color moves from ice blue at freezing to red-orange at 90 F and above.
inline Rgb temperature(const WeatherPane& view) {
  if (!view.temperatureReady) return SCORE_TEXT;
  const int value = view.temperatureF;
  if (value >= 90) return {255, 90, 35};
  if (value >= 75) return {255, 185, 40};
  if (value >= 55) return {95, 225, 105};
  if (value >= 35) return {95, 190, 255};
  return {190, 230, 255};
}

inline int track(const WeatherPane& view) {
  switch (view.sky) {
    case WeatherSky::Clear: return view.night ? 1 : 0;
    case WeatherSky::Rain: return 3;
    case WeatherSky::Snow: return 4;
    case WeatherSky::Fog: return 5;
    case WeatherSky::Storm: return 6;
    default: return 2;
  }
}

template<class Canvas>
void icon(Canvas& canvas, const WeatherPane& view) {
  if (view.sky == WeatherSky::Unknown) {
    center(canvas, "?", 1, 22, 12, MUTED_TEXT, {5, 9, 1, true});
    return;
  }
  const int frame = (view.elapsedMs / mini_weather_art::StepMs) % mini_weather_art::Frames;
  const auto* pixels = mini_weather_art::Pixels[mini_weather_art::Tracks[track(view)][frame]];
  for (int y = 0; y < mini_weather_art::Height; ++y) for (int x = 0; x < mini_weather_art::Width; ++x) {
    const uint16_t rgb = pixels[y * mini_weather_art::Width + x];
    canvas.pixel(1 + x, 9 + y, {static_cast<uint8_t>(((rgb >> 11) & 31) * 255 / 31),
        static_cast<uint8_t>(((rgb >> 5) & 63) * 255 / 63), static_cast<uint8_t>((rgb & 31) * 255 / 31)});
  }
}

// A stat shows its name at the left of its span and its value at the right. A tight stat drops its letter gaps.
template<class Canvas>
void stat(Canvas& canvas, const std::string& name, const std::string& value, int left, int span, Rgb ink) {
  const int gap = measure(name) + 2 + measure(value) <= span ? 1 : 0;
  const Type type{3, 5, gap};
  drawText(canvas, name, left, 27, MUTED_TEXT, type, {left, left + span});
  drawText(canvas, value, left + span - measure(value, type), 27, ink, type, {left, left + span});
}

}  // namespace weather

template<class Canvas>
void draw(Canvas& canvas, const WeatherPane& view) {
  canvas.rect(0, 0, PANE_WIDTH, PANE_HEIGHT, BACKGROUND);
  const Rgb accent = weather::accent(view);
  marquee(canvas, view.city, 1, 63, 1, SCORE_TEXT, view.elapsedMs, weather::cityMotion, false);
  canvas.rect(1, 8, 62, 1, {static_cast<uint8_t>(accent.r / 6), static_cast<uint8_t>(accent.g / 6), static_cast<uint8_t>(accent.b / 6)});
  weather::icon(canvas, view);
  const Rgb ink = weather::temperature(view);
  const Type large{5, 9, 1, true};
  const int valueWidth = measure(view.temperature, large);
  const int left = 24 + (39 - valueWidth - 9) / 2;
  drawText(canvas, view.temperature, left, 10, ink, large, {24, 63});
  canvas.rect(left + valueWidth + 2, 10, 2, 2, ink);
  drawText(canvas, "F", left + valueWidth + 6, 14, ink, {}, {24, 63});
  center(canvas, view.condition, 24, 39, 20, accent);
  canvas.rect(32, 27, 1, 5, {28, 36, 48});
  // The stats alternate every five seconds.
  if ((view.elapsedMs / 5000) % 2 == 0) {
    weather::stat(canvas, "FEEL", view.feels, 1, 30, accent);
    weather::stat(canvas, "", view.wind == "--" ? "--" : view.wind + "MPH", 35, 28, accent);
  } else {
    weather::stat(canvas, "HUM", view.humidity == "--" ? "--" : view.humidity + "%", 1, 30, accent);
    weather::stat(canvas, "AQI", view.aqi, 35, 28, accent);
  }
}

}  // namespace mini_ui

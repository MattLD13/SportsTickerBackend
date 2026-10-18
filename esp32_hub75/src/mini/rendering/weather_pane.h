#pragma once
#include "sports_pane.h"
#include "weather_art_generated.h"

namespace ticker_ui {
enum class WeatherSky { Unknown, Clear, Cloud, Rain, Snow, Fog, Storm };
struct WeatherPane {
  std::string city, temperature, feels, wind, humidity, aqi, condition;
  WeatherSky sky = WeatherSky::Unknown;
  bool night = false, temperatureReady = false;
  int temperatureF = 0;
  uint32_t elapsedMs = 0;
};

inline Rgb weatherAccent(const WeatherPane& view) {
  switch (view.sky) {
    case WeatherSky::Clear: return view.night ? Rgb{150, 175, 245} : Rgb{255, 205, 50};
    case WeatherSky::Rain: return {70, 155, 255};
    case WeatherSky::Snow: return {190, 230, 255};
    case WeatherSky::Storm: return {180, 130, 255};
    default: return {150, 175, 205};
  }
}

inline Rgb weatherTemperatureInk(const WeatherPane& view) {
  if (!view.temperatureReady) return SCORE_TEXT;
  const int value = view.temperatureF;
  if (value >= 90) return {255, 90, 35};
  if (value >= 75) return {255, 185, 40};
  if (value >= 55) return {95, 225, 105};
  if (value >= 35) return {95, 190, 255};
  return {190, 230, 255};
}

template<class Canvas>
void weatherIcon(Canvas& canvas, const WeatherPane& view) {
  if (view.sky == WeatherSky::Unknown) {
    centered(canvas, "?", 1, 22, 12, MUTED_TEXT, 5, 9, 1, true);
    return;
  }
  int track = 2;
  switch (view.sky) {
    case WeatherSky::Clear: track = view.night ? 1 : 0; break;
    case WeatherSky::Rain: track = 3; break;
    case WeatherSky::Snow: track = 4; break;
    case WeatherSky::Fog: track = 5; break;
    case WeatherSky::Storm: track = 6; break;
    default: break;
  }
  const int frame = (view.elapsedMs / mini_weather_art::StepMs) % mini_weather_art::Frames;
  const auto* pixels = mini_weather_art::Pixels[mini_weather_art::Tracks[track][frame]];
  for (int y = 0; y < mini_weather_art::Height; ++y) for (int x = 0; x < mini_weather_art::Width; ++x) {
    const uint16_t rgb = pixels[y * mini_weather_art::Width + x];
    canvas.pixel(1 + x, 9 + y, {static_cast<uint8_t>(((rgb >> 11) & 31) * 255 / 31),
        static_cast<uint8_t>(((rgb >> 5) & 63) * 255 / 63), static_cast<uint8_t>((rgb & 31) * 255 / 31)});
  }
}

template<class Canvas>
void weatherStat(Canvas& canvas, const std::string& name, const std::string& value, int left, int span, Rgb accent) {
  const int gap = textWidth(name) + 2 + textWidth(value) <= span ? 1 : 0;
  text(canvas, name, left, 27, MUTED_TEXT, 3, 5, gap, false, left, left + span);
  text(canvas, value, left + span - textWidth(value, 3, gap), 27, accent, 3, 5, gap, false, left, left + span);
}

template<class Canvas>
void renderWeather(Canvas& canvas, const WeatherPane& view) {
  canvas.rect(0, 0, 64, 32, BACKGROUND);
  const Rgb accent = weatherAccent(view);
  const std::string city = view.city + "    ";
  const int cityWidth = textWidth(view.city);
  const int offset = cityWidth > 62 && view.elapsedMs >= 1400 ?
      static_cast<int>((static_cast<uint64_t>(view.elapsedMs - 1400) * 10 / 1000) % (textWidth(city) + 1)) : 0;
  text(canvas, cityWidth > 62 ? city + view.city : view.city, 1 - offset, 1, SCORE_TEXT, 3, 5, 1, false, 1, 63);
  canvas.rect(1, 8, 62, 1, {static_cast<uint8_t>(accent.r / 6), static_cast<uint8_t>(accent.g / 6), static_cast<uint8_t>(accent.b / 6)});
  weatherIcon(canvas, view);
  const Rgb temperature = weatherTemperatureInk(view);
  const int valueWidth = textWidth(view.temperature, 5, 1, true);
  const int left = 24 + (39 - valueWidth - 9) / 2;
  text(canvas, view.temperature, left, 10, temperature, 5, 9, 1, true, 24, 63);
  canvas.rect(left + valueWidth + 2, 10, 2, 2, temperature);
  text(canvas, "F", left + valueWidth + 6, 14, temperature, 3, 5, 1, false, 24, 63);
  centered(canvas, view.condition, 24, 39, 20, accent);
  canvas.rect(32, 27, 1, 5, {28, 36, 48});
  if ((view.elapsedMs / 5000) % 2 == 0) {
    weatherStat(canvas, "FEEL", view.feels, 1, 30, accent);
    weatherStat(canvas, "", view.wind == "--" ? "--" : view.wind + "MPH", 35, 28, accent);
  } else {
    weatherStat(canvas, "HUM", view.humidity == "--" ? "--" : view.humidity + "%", 1, 30, accent);
    weatherStat(canvas, "AQI", view.aqi, 35, 28, accent);
  }
}
}  // namespace ticker_ui

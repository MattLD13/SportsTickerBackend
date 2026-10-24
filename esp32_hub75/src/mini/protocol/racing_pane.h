#pragma once
#include <ArduinoJson.h>
#include "../rendering/racing_pane.h"

namespace ticker_ui {
inline std::string racingText(JsonVariantConst value, size_t limit = 64) {
  std::string text = value.isNull() ? "" : value.as<std::string>();
  for (char& ch : text) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  return text.substr(0, limit);
}
inline Rgb racingRgb(JsonVariantConst value, Rgb empty) {
  JsonArrayConst rgb = value.as<JsonArrayConst>();
  if (rgb.size() != 3) return empty;
  return {static_cast<uint8_t>(std::max(0, std::min(255, rgb[0] | 0))),
          static_cast<uint8_t>(std::max(0, std::min(255, rgb[1] | 0))),
          static_cast<uint8_t>(std::max(0, std::min(255, rgb[2] | 0)))};
}
inline RacingPane racingPane(JsonObjectConst data, uint32_t elapsedMs, uint32_t signalPhaseMs) {
  RacingPane view;
  JsonObjectConst source = data["racing_display"].as<JsonObjectConst>();
  view.race = racingText(source["race_name"], 120);
  view.group = racingText(source["class_label"], 16);
  view.status = racingText(source["status"], 16);
  view.upcoming = source["state"] == "pre";
  view.elapsedMs = elapsedMs;
  view.signalPhaseMs = signalPhaseMs;
  JsonArrayConst signals = source["signals"].as<JsonArrayConst>();
  if (signals.size()) {
    JsonObjectConst signal = signals[(signalPhaseMs / 2000) % signals.size()].as<JsonObjectConst>();
    auto& output = view.signal;
    view.signalPresent = true;
    output.label = racingText(signal["label"], 12);
    output.showLabel = signal["show_label"] | false;
    output.flashing = signal["flashing"] | false;
    JsonArrayConst pixels = signal["pixels"].as<JsonArrayConst>();
    for (int index = 0; index < 25; ++index) output.pixels[index] = pixels[index] | uint16_t(0);
  } else {
    view.signal.label = "?";
    view.signal.showLabel = true;
    view.signal.pixels.fill(uint16_t(0x73B0));
  }
  for (JsonObjectConst row : source["rows"].as<JsonArrayConst>()) {
    if (view.count == 3) break;
    auto& output = view.rows[view.count++];
    output.car = racingText(row["car"], 4);
    output.name = racingText(row["name"], 3);
    output.gap = racingText(row["compact_metric"], 12);
    output.position = row["position"] | 0;
    output.positionColor = racingRgb(row["position_rgb"], {235, 235, 235});
    output.metricColor = racingRgb(row["metric_rgb"], {180, 210, 255});
    output.numberColor = racingRgb(row["number_style"]["color_rgb"], {235, 235, 235});
    JsonArrayConst outline = row["number_style"]["outline_rgb"].as<JsonArrayConst>();
    output.outlined = outline.size() == 3;
    output.numberOutline = racingRgb(row["number_style"]["outline_rgb"], {0, 0, 0});
  }
  return view;
}
}  // namespace ticker_ui

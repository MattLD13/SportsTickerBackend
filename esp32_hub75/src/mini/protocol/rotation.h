#pragma once
#include <ArduinoJson.h>

namespace ticker_ui {
template<class Callback>
void forEachRotationItem(JsonObjectConst content, bool sports, Callback callback) {
  if (!sports) {
    for (JsonObjectConst item : content["stock"].as<JsonArrayConst>())
      if (item["is_shown"].isNull() || item["is_shown"].as<bool>()) callback(item);
    return;
  }
  JsonArrayConst games = content["sports"].as<JsonArrayConst>();
  JsonArrayConst races = content["racing"].as<JsonArrayConst>();
  size_t game = 0, race = 0;
  while (game < games.size() || race < races.size()) {
    JsonObjectConst a = game < games.size() ? games[game].as<JsonObjectConst>() : JsonObjectConst();
    JsonObjectConst b = race < races.size() ? races[race].as<JsonObjectConst>() : JsonObjectConst();
    const unsigned long gameOrder = a.isNull() ? 0xffffffffUL : a["rotation_order"] | 0xffffffffUL;
    const unsigned long raceOrder = b.isNull() ? 0xffffffffUL : b["rotation_order"] | 0xffffffffUL;
    const bool takeGame = !a.isNull() && (b.isNull() || gameOrder <= raceOrder);
    JsonObjectConst item = takeGame ? a : b;
    if (takeGame) ++game; else ++race;
    if (item["is_shown"].isNull() || item["is_shown"].as<bool>()) callback(item);
  }
}
}  // namespace ticker_ui

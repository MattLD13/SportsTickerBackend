#pragma once
#include <ArduinoJson.h>

namespace mini_ui {
template<class Callback>
void forEachRotationItem(JsonObjectConst content, bool sports, Callback callback) {
  const char* families[] = {sports ? "sports" : "stock", "racing"};
  const int count = sports ? 2 : 1;
  for (int family = 0; family < count; ++family)
    for (JsonObjectConst item : content[families[family]].as<JsonArrayConst>())
      if (item["is_shown"].isNull() || item["is_shown"].as<bool>()) callback(item);
}
}  // namespace mini_ui

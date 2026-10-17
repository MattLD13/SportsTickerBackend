#include "device_payload.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <sstream>

bool accept(DevicePayload& payload, const char* text) {
  ResponseBody body;
  body.append(reinterpret_cast<const unsigned char*>(text), std::strlen(text));
  return payload.accept(body);
}
int main() {
  DevicePayload payload;
  const char* valid = R"({"api_version":"v2","settings":{"mode":"sports"},"meta":{"pairing":{"paired":true}},"content":{"sports":[{"id":"game","data":{"sport":"march_madness","away_seed":"1","home_seed":"16"}}]}})";
  assert(accept(payload, valid));
  assert(payload.document()["content"]["sports"][0]["data"]["home_seed"] == "16");
  for (const char* invalid : {"{", "{}", "[]", "{\"api_version\":\"v1\"}"}) {
    assert(!accept(payload, invalid));
    assert(payload.document()["content"]["sports"][0]["id"] == "game");
  }
  for (int index = 0; index < 1000; ++index) assert(accept(payload, valid));
  std::ostringstream large;
  large << R"({"api_version":"v2","settings":{"mode":"sports"},"meta":{"pairing":{"paired":true}},"content":{"sports":[)";
  for (int index = 0; index < 160; ++index) {
    if (index) large << ',';
    large << R"({"is_shown":true,"id":")" << index
          << R"(","data":{"sport":"nhl","away_logo_asset":{"state":"ready","asset_id":"frozen"},"home_score":"2","away_score":"1"}})";
  }
  large << "]}}";
  const std::string crowded = large.str();
  assert(accept(payload, crowded.c_str()));
  assert(payload.document()["content"]["sports"].size() == 160);
  assert(payload.document()["content"]["sports"][159]["data"]["away_logo_asset"]["asset_id"] == "frozen");
  std::cout << "Retained V2 payload preserves 160 games and logo references after 1000 atomic commits\n";
}

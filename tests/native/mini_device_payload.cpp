#include "device_payload.h"
#include <cassert>
#include <cstring>
#include <iostream>

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
  std::cout << "Retained V2 payload rejects incomplete contracts and preserves seeds across 1000 commits\n";
}

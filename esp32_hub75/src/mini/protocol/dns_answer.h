#pragma once
#include <ArduinoJson.h>
#include <array>
#include <string>
#include <algorithm>

struct DnsAnswer {
  std::array<uint8_t, 4> address{};
  uint32_t ttlSeconds = 0;
  bool valid = false;
};

inline bool dnsCacheFresh(uint32_t savedMs, uint32_t ttlMs, uint32_t now) {
  return static_cast<uint32_t>(now - savedMs) < ttlMs;
}

inline DnsAnswer readDnsAnswer(JsonObjectConst response, const std::string& host) {
  DnsAnswer answer;
  if (!response["Status"].is<int>() || response["Status"].as<int>() != 0 || (response["TC"] | false)) return answer;
  std::string question = response["Question"][0]["name"] | "";
  if (!question.empty() && question.back() == '.') question.pop_back();
  if (question != host || response["Question"][0]["type"] != 1) return answer;
  uint32_t ttl = 3600;
  for (JsonObjectConst entry : response["Answer"].as<JsonArrayConst>()) {
    if (!entry["TTL"].is<uint32_t>()) return DnsAnswer{};
    ttl = std::min(ttl, entry["TTL"].as<uint32_t>());
    if (entry["type"] != 1 || answer.valid) continue;
    const std::string value = entry["data"] | "";
    size_t position = 0;
    bool valid = true;
    for (size_t part = 0; part < 4; ++part) {
      unsigned number = 0, digits = 0;
      while (position < value.size() && value[position] >= '0' && value[position] <= '9') {
        number = number * 10 + value[position++] - '0';
        if (++digits > 3 || number > 255) { valid = false; break; }
      }
      if (!digits || !valid) { valid = false; break; }
      answer.address[part] = number;
      if (part < 3 && (position == value.size() || value[position++] != '.')) { valid = false; break; }
    }
    answer.valid = valid && position == value.size() &&
                   std::any_of(answer.address.begin(), answer.address.end(), [](uint8_t byte) { return byte != 0; });
  }
  answer.ttlSeconds = ttl;
  return answer;
}

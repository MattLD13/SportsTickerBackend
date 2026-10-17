#include "device_payload.h"
#include "payload_reader.h"
#include <utility>

DevicePayload::DevicePayload() {
  filter_["api_version"] = true;
  filter_["meta"]["pairing"]["paired"] = true;
  filter_["meta"]["pairing"]["code"] = true;
  filter_["meta"]["update"]["version"] = true;
  filter_["meta"]["update"]["id"] = true;
  filter_["meta"]["update"]["expires_at"] = true;
  filter_["settings"]["mode"] = true;
  filter_["settings"]["timezone"] = true;
  filter_["settings"]["scroll_speed"] = true;
  filter_["settings"]["brightness"] = true;
  filter_["content"]["sports"][0]["is_shown"] = true;
  filter_["content"]["sports"][0]["id"] = true;
  filter_["content"]["sports"][0]["identifier"] = true;
  filter_["content"]["sports"][0]["key"] = true;
  for (const char* family : {"weather", "music", "flights", "airports", "stock", "clock"}) {
    filter_["content"][family][0]["is_shown"] = true;
    filter_["content"][family][0]["id"] = true;
    filter_["content"][family][0]["data"] = true;
  }
  JsonObject filterGame = filter_["content"]["sports"][0]["data"].to<JsonObject>();
  filterGame["sport"] = true;
  filterGame["league"] = true;
  filterGame["away_logo_asset"] = true;
  filterGame["home_logo_asset"] = true;
  filterGame["away_abbr"] = true;
  filterGame["home_abbr"] = true;
  filterGame["away_score"] = true;
  filterGame["home_score"] = true;
  filterGame["away_color"] = true;
  filterGame["home_color"] = true;
  filterGame["status"] = true;
  filterGame["state"] = true;
  filterGame["baseball_inning"] = true;
  filterGame["away_rank"] = true;
  filterGame["home_rank"] = true;
  filterGame["away_seed"] = true;
  filterGame["home_seed"] = true;
  JsonObject filterSituation = filterGame["situation"].to<JsonObject>();
  filterSituation["downDist"] = true;
  filterSituation["activeTeam"] = true;
  filterSituation["possession"] = true;
  filterSituation["balls"] = true;
  filterSituation["strikes"] = true;
  filterSituation["outs"] = true;
  filterSituation["onFirst"] = true;
  filterSituation["onSecond"] = true;
  filterSituation["onThird"] = true;
  filterSituation["powerPlay"] = true;
  filterSituation["powerPlayTeam"] = true;
  filterSituation["manpower"]["scrollLabel"] = true;
  filterSituation["manpower"]["powerPlayLabel"] = true;
  filterSituation["manpower"]["penalties"][0]["timeRemaining"] = true;
  filterSituation["manpower"]["penalties"][0]["jerseyNumber"] = true;
  filterSituation["shootout"] = true;
  filterSituation["isRedZone"] = true;
  filterSituation["emptyNet"] = true;
  filterSituation["emptyNetSide"] = true;
  filterSituation["red_cards"][0]["is_home"] = true;

}

bool DevicePayload::accept(const ResponseBody& body) {
  JsonDocument candidate;
  PayloadReader reader(body.data(), body.size());
  const auto error = deserializeJson(candidate, reader, DeserializationOption::Filter(filter_));
  offset_ = reader.position();
  error_ = error ? error.c_str() : "";
  if (error) return false;
  if (candidate["api_version"] != "v2" || !candidate["settings"].is<JsonObject>() ||
      !candidate["content"].is<JsonObject>() || !candidate["meta"]["pairing"]["paired"].is<bool>()) {
    error_ = "Invalid V2 display contract";
    return false;
  }
  document_ = std::move(candidate);
  return true;
}

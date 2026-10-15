#pragma once

#include <ArduinoJson.h>
#include <cstdlib>
#include "../rendering/sports_pane.h"
#include "../rendering/utility_panels.h"

namespace ticker_ui {
inline std::string label(JsonVariantConst value, const char* empty = "", size_t limit = 64) {
  std::string result = value.isNull() ? empty : value.as<std::string>();
  for (char& ch : result) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  return result.substr(0, limit);
}

inline Side side(const std::string& value, const std::string& away, const std::string& home) {
  if (value.empty()) return Side::None;
  if (value == away || value == "AWAY" || value == "A") return Side::Away;
  if (value == home || value == "HOME" || value == "H") return Side::Home;
  return Side::None;
}

inline uint8_t shot(const std::string& value) {
  return value == "GOAL" ? 1 : value == "MISS" ? 2 : 0;
}

inline Rgb teamInk(JsonVariantConst value) {
  std::string raw = value | "";
  if (!raw.empty() && raw[0] == '#') raw.erase(0, 1);
  if (raw.size() != 6) return {86, 104, 132};
  const unsigned long rgb = std::strtoul(raw.c_str(), nullptr, 16);
  return {static_cast<uint8_t>(rgb >> 16), static_cast<uint8_t>(rgb >> 8), static_cast<uint8_t>(rgb)};
}

inline SportsPane sportsPane(JsonObjectConst game) {
  SportsPane view;
  std::string league = game["sport"] | "";
  for (char& ch : league) ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
  const std::string family = sportFamily(league.c_str());
  if (family == "football") view.sport = Sport::Football;
  else if (family == "baseball") view.sport = Sport::Baseball;
  else if (family == "basketball") view.sport = Sport::Basketball;
  else if (family == "hockey") view.sport = Sport::Hockey;
  else if (family == "soccer") view.sport = Sport::Soccer;
  view.status = label(game["status"], "UPCOMING", 12);
  view.awayScore = label(game["away_score"], "-", 3);
  view.homeScore = label(game["home_score"], "-", 3);
  const std::string state = label(game["state"]);
  view.live = state == "IN" || state == "CRIT";
  const std::string away = label(game["away_abbr"]), home = label(game["home_abbr"]);
  view.awayLabel = away.substr(0, 4); view.homeLabel = home.substr(0, 4);
  view.awayColor = teamInk(game["away_color"]); view.homeColor = teamInk(game["home_color"]);
  JsonObjectConst situation = game["situation"].as<JsonObjectConst>();
  view.active = side(label(situation["activeTeam"]), away, home);
  view.redZone = situation["isRedZone"] | false;
  if (view.sport == Sport::Football) view.footer = label(situation["downDist"], "", 12);
  if (league == "ncf_fbs" || league == "ncf_fcs") {
    view.awayRank = label(game["away_rank"], "", 2);
    view.homeRank = label(game["home_rank"], "", 2);
  }
  if (view.sport == Sport::Baseball && view.live) {
    view.baseballLive = view.active != Side::None;
    view.balls = std::max(0, std::min(3, situation["balls"] | 0));
    view.strikes = std::max(0, std::min(2, situation["strikes"] | 0));
    view.outs = std::max(0, std::min(3, situation["outs"] | 0));
    view.first = situation["onFirst"] | false;
    view.second = situation["onSecond"] | false;
    view.third = situation["onThird"] | false;
  }
  if (view.sport == Sport::Hockey && view.live) {
    if (situation["powerPlay"] | false) view.powerPlay = side(label(situation["powerPlayTeam"]), away, home);
    if (situation["emptyNet"] | false) view.emptyNet = side(label(situation["emptyNetSide"]), away, home);
    view.footer = label(situation["manpower"]["scrollLabel"], "", 12);
  }
  if (view.sport == Sport::Soccer) {
    for (JsonObjectConst card : situation["red_cards"].as<JsonArrayConst>()) {
      if (card["is_home"] | false) ++view.homeCards;
      else ++view.awayCards;
    }
  }
  JsonObjectConst shootout = situation["shootout"].as<JsonObjectConst>();
  if (shootout.size() > 0 && (view.sport == Sport::Hockey || view.sport == Sport::Soccer)) {
    view.shootout = true;
    view.footer = label(shootout["roundLabel"], "", 5);
    if (view.sport == Sport::Hockey) {
      for (JsonObjectConst round : shootout["displayRounds"].as<JsonArrayConst>()) {
        if (view.shotCount == 3) break;
        view.awayShots[view.shotCount] = shot(label(round["away"]));
        view.homeShots[view.shotCount] = shot(label(round["home"]));
        ++view.shotCount;
      }
    } else {
      view.shotCount = 5;
      for (int index = 0; index < 5; ++index) {
        view.awayShots[index] = shot(label(shootout["away"][index]));
        view.homeShots[index] = shot(label(shootout["home"][index]));
      }
    }
  }
  return view;
}
inline StockPane stockPane(JsonObjectConst stock) {
  StockPane view;
  view.symbol = label(stock["symbol"].isNull() ? stock["home_abbr"] : stock["symbol"], "STOCK", 10);
  if (!view.symbol.empty() && view.symbol[0] != '$') view.symbol = "$" + view.symbol;
  view.price = label(stock["home_score"], "--", 10);
  if (!view.price.empty() && view.price[0] != '$') view.price = "$" + view.price;
  view.percent = label(stock["away_score"], "--", 8);
  view.change = label(stock["situation"]["change"], "--", 6);
  return view;
}

}  // namespace ticker_ui

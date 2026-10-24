#pragma once

#include <ArduinoJson.h>
#include <cstdlib>
#include "../rendering/sports_pane.h"
#include "../rendering/utility_panels.h"
#include "../rendering/music_pane.h"
#include "../rendering/weather_pane.h"
#include "../rendering/auxiliary_panels.h"

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

inline Shot shot(const std::string& value) {
  return value == "GOAL" ? Shot::Goal : value == "MISS" ? Shot::Miss :
         value == "NOT_TAKEN" ? Shot::NotTaken : Shot::Pending;
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
  const int stage = game["competition_stage"] | 0;
  view.ruleColor = stage == 2 ? FINALS_RULE : stage == 1 ? PLAYOFF_RULE : HEADER_RULE;
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
  if (league == "march_madness") {
    view.awaySeed = label(game["away_seed"], "", 2);
    view.homeSeed = label(game["home_seed"], "", 2);
  }
  if (view.sport == Sport::Baseball && view.live) {
    JsonObjectConst inning = game["baseball_inning"].as<JsonObjectConst>();
    const std::string phase = label(inning["phase"]);
    view.baseballLive = phase == "PLAYING" || phase == "BREAK";
    view.inning = inning["number"] | 0;
    const std::string half = label(inning["half"]);
    view.inningHalf = half == "TOP" ? InningHalf::Top : half == "BOTTOM" ? InningHalf::Bottom : half == "BREAK" ? InningHalf::Break : InningHalf::None;
    view.balls = std::max(0, std::min(3, situation["balls"] | 0));
    view.strikes = std::max(0, std::min(2, situation["strikes"] | 0));
    view.outs = std::max(0, std::min(3, situation["outs"] | 0));
    view.first = situation["onFirst"] | false;
    view.second = situation["onSecond"] | false;
    view.third = situation["onThird"] | false;
  }
  if (view.sport == Sport::Hockey && view.live) {
    if (situation["powerPlay"] | false) view.powerPlay = side(label(situation["powerPlayTeam"]), away, home);
    view.powerPlayLabel = label(situation["manpower"]["powerPlayLabel"], "", 5);
    if (situation["emptyNet"] | false) view.emptyNet = side(label(situation["emptyNetSide"]), away, home);
    view.footer = label(situation["manpower"]["scrollLabel"], "", 64);
    for (JsonObjectConst penalty : situation["manpower"]["penalties"].as<JsonArrayConst>()) {
      if (view.penaltyCount == 2) break;
      view.penalties[view.penaltyCount++] = {label(penalty["timeRemaining"], "", 5), label(penalty["jerseyNumber"], "", 2)};
    }
    if (view.penaltyCount > 0) view.footer.clear();
  }
  if (view.sport == Sport::Soccer) {
    for (JsonObjectConst card : situation["red_cards"].as<JsonArrayConst>()) {
      if (card["is_home"] | false) ++view.homeCards;
      else ++view.awayCards;
    }
  }
  JsonObjectConst shootout = situation["shootout"].as<JsonObjectConst>();
  const std::string shootoutState = label(shootout["state"]);
  const bool hockeyShootout = view.sport == Sport::Hockey &&
                             (shootoutState == "ACTIVE" || shootoutState == "COMPLETE");
  if (hockeyShootout || (shootout.size() > 0 && view.sport == Sport::Soccer)) {
    view.shootout = true;
    view.footer = label(shootout["roundLabel"], "", 16);
    if (view.sport == Sport::Hockey) {
      for (JsonObjectConst round : shootout["displayRounds"].as<JsonArrayConst>()) {
        if (view.shotCount == 3) break;
        view.awayShots[view.shotCount] = shot(label(round["away"]));
        view.homeShots[view.shotCount] = shot(label(round["home"]));
        const std::string next = label(round["nextSide"]);
        if (shootoutState == "ACTIVE" && next == "AWAY" && view.awayShots[view.shotCount] == Shot::Pending)
          view.awayShots[view.shotCount] = Shot::Next;
        if (shootoutState == "ACTIVE" && next == "HOME" && view.homeShots[view.shotCount] == Shot::Pending)
          view.homeShots[view.shotCount] = Shot::Next;
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
inline bool systemPane(JsonObjectConst data, uint32_t elapsedMs, SystemPane& view) {
  SystemKind kind;
  if (!systemKind(data["utility_kind"] | "", kind)) return false;
  view = systemPane(kind, label(data["detail"]), data["complete"] | 0U, data["total"] | 0U, elapsedMs);
  view.clock = label(data["clock"], "--:--");
  view.date = label(data["date"]);
  view.ageSeconds = (data["age_seconds"] | 0U) + elapsedMs / 1000;
  return true;
}

inline MusicPane musicPane(JsonObjectConst music, double now, uint32_t scrollMs) {
  MusicPane view;
  view.title = label(music["name"], "SPOTIFY", 160);
  view.artist = label(music["artist"], "", 120);
  view.playing = music["is_playing"] | false;
  view.idle = label(music["status"]) == "IDLE";
  if (view.idle) { view.title = "NO MUSIC"; view.artist = "PLAY A SONG"; }
  view.scrollMs = scrollMs;
  JsonArrayConst accent = music["cover_asset"]["accent_rgb"].as<JsonArrayConst>();
  if (accent.size() == 3) {
    view.accent = {static_cast<uint8_t>(std::max(0, std::min(255, accent[0] | 160))),
                   static_cast<uint8_t>(std::max(0, std::min(255, accent[1] | 175))),
                   static_cast<uint8_t>(std::max(0, std::min(255, accent[2] | 195)))};
  }
  const double duration = music["duration"] | 0.0;
  double progress = music["progress"] | 0.0;
  const double fetched = music["fetch_ts"] | 0.0;
  if (view.playing && now > 1700000000 && fetched > 1700000000) progress += std::max(0.0, now - fetched);
  if (std::isfinite(duration) && std::isfinite(progress) && duration > 0) {
    progress = std::max(0.0, std::min(duration, progress));
    const unsigned remaining = static_cast<unsigned>(std::ceil(std::min(359999.0, duration - progress)));
    char clock[16];
    std::snprintf(clock, sizeof(clock), "-%u:%02u", remaining / 60, remaining % 60);
    view.remaining = clock;
    view.fraction = static_cast<float>(progress / duration);
  } else view.remaining = "--:--";
  return view;
}

inline std::string weatherNumber(JsonVariantConst value) {
  if (value.isNull() || (!value.is<int>() && !value.is<double>())) return "--";
  const double number = value.as<double>();
  if (!std::isfinite(number) || std::abs(number) > 9999) return "--";
  return std::to_string(static_cast<int>(std::round(number)));
}

inline WeatherPane weatherPane(JsonObjectConst weather, uint32_t elapsedMs) {
  WeatherPane view;
  view.city = label(weather["city"], "WEATHER", 120);
  view.temperature = weatherNumber(weather["temperature"]);
  view.temperatureReady = view.temperature != "--";
  view.temperatureF = view.temperatureReady ? static_cast<int>(std::round(weather["temperature"].as<double>())) : 0;
  view.feels = weatherNumber(weather["feels"]);
  view.wind = weatherNumber(weather["wind"]);
  view.humidity = weatherNumber(weather["humidity"]);
  view.aqi = weatherNumber(weather["aqi"]);
  view.elapsedMs = elapsedMs;
  view.night = !weather["is_day"].isNull() && weather["is_day"].as<int>() == 0;
  const std::string icon = weather["icon"] | "";
  if (icon == "sun") { view.sky = WeatherSky::Clear; view.condition = view.night ? "CLEAR" : "SUNNY"; }
  else if (icon == "cloud") { view.sky = WeatherSky::Cloud; view.condition = "CLOUDY"; }
  else if (icon == "rain") { view.sky = WeatherSky::Rain; view.condition = "RAIN"; }
  else if (icon == "snow") { view.sky = WeatherSky::Snow; view.condition = "SNOW"; }
  else if (icon == "fog") { view.sky = WeatherSky::Fog; view.condition = "FOG"; }
  else if (icon == "storm") { view.sky = WeatherSky::Storm; view.condition = "STORM"; }
  else view.condition = "--";
  return view;
}

inline FlightPane flightPane(JsonObjectConst flight) {
  FlightPane view;
  view.id = label(flight["id"], "FLIGHT", 10);
  view.setup = label(flight["id"]) == "FLIGHT_BLANK";
  view.live = flight["is_live"] | false;
  view.delayed = flight["is_delayed"] | false;
  auto origin = label(flight["origin_iata"], "", 3);
  auto destination = label(flight["dest_iata"], "", 3);
  view.origin = origin.empty() ? label(flight["origin_city"], "---", 3) : origin;
  view.destination = destination.empty() ? label(flight["dest_city"], "---", 3) : destination;
  view.eta = label(flight["eta_str"], "--", 12);
  view.eta.erase(std::remove(view.eta.begin(), view.eta.end(), ' '), view.eta.end());
  view.metrics = std::to_string((flight["alt"] | 0) / 1000) + "K FT " + label(flight["speed"], "--", 4) + "MPH";
  view.status = label(flight["status"], "SCHEDULED", 14);
  std::replace(view.status.begin(), view.status.end(), '-', ' ');
  view.disrupted = view.status == "CANCELED" || view.status == "CANCELLED" || view.status == "DIVERTED";
  view.complete = view.status == "LANDED" || view.status == "ARRIVED";
  if (view.setup) view.badge = "";
  else if (view.disrupted) view.badge = view.status == "DIVERTED" ? "DIV" : "CXL";
  else if (view.delayed) view.badge = "+" + std::to_string(flight["delay_min"] | 0) + "M";
  else if (view.live) view.badge = "LIVE";
  else if (view.complete) view.badge = "DONE";
  else view.badge = "";
  view.aircraft = label(flight["aircraft_code"], "", 12);
  view.progress = flight["progress"] | 0;
  return view;
}

inline AirportPane airportPane(JsonObjectConst airport, uint32_t elapsedMs = 0) {
  AirportPane view;
  JsonObjectConst weather = airport["weather"].as<JsonObjectConst>();
  view.code = label(weather["iata"], "---", 3);
  view.temperature = label(weather["away_abbr"], "--", 5);
  const auto arrivals = airport["arrivals"].as<JsonArrayConst>();
  const auto departures = airport["departures"].as<JsonArrayConst>();
  view.pages = std::max(1, std::min(4, static_cast<int>(std::max(arrivals.size(), departures.size()))));
  view.page = (elapsedMs / 4000) % view.pages;
  JsonObjectConst arrival = arrivals.size() ? arrivals[view.page % arrivals.size()].as<JsonObjectConst>() : JsonObjectConst();
  JsonObjectConst departure = departures.size() ? departures[view.page % departures.size()].as<JsonObjectConst>() : JsonObjectConst();
  view.arrivalPresent = !arrival.isNull();
  view.departurePresent = !departure.isNull();
  view.arrival = label(arrival["flight_number"], "---", 8);
  view.arrivalAirport = label(arrival["airport_code"], "---", 3);
  view.departure = label(departure["flight_number"], "---", 8);
  view.departureAirport = label(departure["airport_code"], "---", 3);
  const bool outbound = (elapsedMs / 2000) % 2;
  const auto row = outbound ? departure : arrival;
  view.detailWarning = row["is_delayed"] | false;
  view.detail = (outbound ? "DEP " : "ARR ") + (row.isNull() ? std::string("NONE") :
      view.detailWarning ? "+" + std::to_string(row["delay_min"] | 0) + " MIN" : label(row["status"], "--", 10));
  return view;
}

inline StockPane stockPane(JsonObjectConst stock) {
  StockPane view;
  view.symbol = label(stock["symbol"].isNull() ? stock["home_abbr"] : stock["symbol"], "STOCK", 10);
  view.price = label(stock["home_score"], "--", 15);
  if (view.price != "--" && !view.price.empty() && view.price[0] != '$') view.price = "$" + view.price;
  view.percent = label(stock["away_score"], "--", 12);
  return view;
}

}  // namespace ticker_ui

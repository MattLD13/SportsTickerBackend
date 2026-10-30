// Read the explicit display facts of one item into the view that its pane draws.
// A reader does no I/O. A missing fact gets the placeholder that the pane shows for it.
#pragma once

#include <ArduinoJson.h>
#include <cstdio>
#include <cstdlib>
#include "../ui/aviation.h"
#include "../ui/clock.h"
#include "../ui/music.h"
#include "../ui/racing.h"
#include "../ui/sports.h"
#include "../ui/stock.h"
#include "../ui/system.h"
#include "../ui/weather.h"
#include "rotation.h"

namespace mini_ui {

// Return the value as upper-case text of at most `limit` characters.
inline std::string label(JsonVariantConst value, const char* empty = "", size_t limit = 64) {
  std::string result = value.isNull() ? empty : value.as<std::string>();
  for (char& ch : result) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  return result.substr(0, limit);
}

inline Rgb rgbArray(JsonVariantConst value, Rgb empty) {
  JsonArrayConst rgb = value.as<JsonArrayConst>();
  if (rgb.size() != 3) return empty;
  return {static_cast<uint8_t>(std::max(0, std::min(255, rgb[0] | 0))),
          static_cast<uint8_t>(std::max(0, std::min(255, rgb[1] | 0))),
          static_cast<uint8_t>(std::max(0, std::min(255, rgb[2] | 0)))};
}

inline Rgb rgbHex(JsonVariantConst value) {
  std::string raw = value | "";
  if (!raw.empty() && raw[0] == '#') raw.erase(0, 1);
  if (raw.size() != 6) return {86, 104, 132};
  const unsigned long rgb = std::strtoul(raw.c_str(), nullptr, 16);
  return {static_cast<uint8_t>(rgb >> 16), static_cast<uint8_t>(rgb >> 8), static_cast<uint8_t>(rgb)};
}

namespace parse {

inline Side side(const std::string& value, const std::string& away, const std::string& home) {
  if (value.empty()) return Side::None;
  if (value == away || value == "AWAY" || value == "A") return Side::Away;
  if (value == home || value == "HOME" || value == "H") return Side::Home;
  return Side::None;
}

inline Shot shot(const std::string& value) {
  return value == "GOAL" ? Shot::Goal : value == "MISS" ? Shot::Miss : value == "NOT_TAKEN" ? Shot::NotTaken : Shot::Pending;
}

inline Sport sport(const std::string& league) {
  const std::string family = sportFamily(league.c_str());
  return family == "football" ? Sport::Football : family == "baseball" ? Sport::Baseball : family == "basketball" ? Sport::Basketball :
         family == "hockey" ? Sport::Hockey : family == "soccer" ? Sport::Soccer : Sport::Other;
}

inline void baseball(SportsPane& view, JsonObjectConst game, JsonObjectConst situation) {
  JsonObjectConst inning = game["baseball_inning"].as<JsonObjectConst>();
  const std::string phase = label(inning["phase"]), half = label(inning["half"]);
  view.baseballLive = phase == "PLAYING" || phase == "BREAK";
  view.inning = inning["number"] | 0;
  view.inningHalf = half == "TOP" ? InningHalf::Top : half == "BOTTOM" ? InningHalf::Bottom : half == "BREAK" ? InningHalf::Break : InningHalf::None;
  view.balls = std::max(0, std::min(3, situation["balls"] | 0));
  view.strikes = std::max(0, std::min(2, situation["strikes"] | 0));
  view.outs = std::max(0, std::min(3, situation["outs"] | 0));
  view.first = situation["onFirst"] | false;
  view.second = situation["onSecond"] | false;
  view.third = situation["onThird"] | false;
}

// The penalties replace the manpower label. Two penalties at most show.
inline void hockey(SportsPane& view, JsonObjectConst situation, const std::string& away, const std::string& home) {
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

// A hockey shootout shows three rounds and marks the next shooter. A soccer shootout shows five kicks.
inline void shootout(SportsPane& view, JsonObjectConst shootout) {
  const std::string state = label(shootout["state"]);
  const bool hockey = view.sport == Sport::Hockey && (state == "ACTIVE" || state == "COMPLETE");
  if (!hockey && !(shootout.size() > 0 && view.sport == Sport::Soccer)) return;
  view.shootout = true;
  view.footer = label(shootout["roundLabel"], "", 16);
  if (view.sport != Sport::Hockey) {
    view.shotCount = 5;
    for (int index = 0; index < 5; ++index) {
      view.awayShots[index] = shot(label(shootout["away"][index]));
      view.homeShots[index] = shot(label(shootout["home"][index]));
    }
    return;
  }
  for (JsonObjectConst round : shootout["displayRounds"].as<JsonArrayConst>()) {
    if (view.shotCount == 3) break;
    Shot& away = view.awayShots[view.shotCount];
    Shot& home = view.homeShots[view.shotCount];
    away = shot(label(round["away"]));
    home = shot(label(round["home"]));
    const std::string next = label(round["nextSide"]);
    if (state == "ACTIVE" && next == "AWAY" && away == Shot::Pending) away = Shot::Next;
    if (state == "ACTIVE" && next == "HOME" && home == Shot::Pending) home = Shot::Next;
    ++view.shotCount;
  }
}

}  // namespace parse

inline SportsPane sportsPane(JsonObjectConst game) {
  SportsPane view;
  std::string league = game["sport"] | "";
  for (char& ch : league) ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
  view.sport = parse::sport(league);
  view.status = label(game["status"], "UPCOMING", 12);
  const int stage = game["competition_stage"] | 0;
  view.ruleColor = stage == 2 ? FINALS_RULE : stage == 1 ? PLAYOFF_RULE : HEADER_RULE;
  view.awayScore = label(game["away_score"], "-", 3);
  view.homeScore = label(game["home_score"], "-", 3);
  const std::string state = label(game["state"]);
  view.live = state == "IN" || state == "CRIT";
  const std::string away = label(game["away_abbr"]), home = label(game["home_abbr"]);
  view.awayLabel = away.substr(0, 4);
  view.homeLabel = home.substr(0, 4);
  view.awayColor = rgbHex(game["away_color"]);
  view.homeColor = rgbHex(game["home_color"]);
  JsonObjectConst situation = game["situation"].as<JsonObjectConst>();
  view.active = parse::side(label(situation["activeTeam"]), away, home);
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
  if (view.sport == Sport::Baseball && view.live) parse::baseball(view, game, situation);
  if (view.sport == Sport::Hockey && view.live) parse::hockey(view, situation, away, home);
  if (view.sport == Sport::Soccer) {
    for (JsonObjectConst card : situation["red_cards"].as<JsonArrayConst>()) ++((card["is_home"] | false) ? view.homeCards : view.awayCards);
  }
  parse::shootout(view, situation["shootout"].as<JsonObjectConst>());
  return view;
}

inline RacingPane racingPane(JsonObjectConst data, uint32_t elapsedMs, uint32_t signalPhaseMs) {
  RacingPane view;
  JsonObjectConst source = data["racing_display"].as<JsonObjectConst>();
  view.race = label(source["race_name"], "", 120);
  view.group = label(source["class_label"], "", 16);
  view.status = label(source["status"], "", 16);
  view.upcoming = source["state"] == "pre";
  view.elapsedMs = elapsedMs;
  view.signalPhaseMs = signalPhaseMs;
  // The signals take turns every two seconds. A race without a signal shows a gray "?".
  JsonArrayConst signals = source["signals"].as<JsonArrayConst>();
  if (signals.size()) {
    JsonObjectConst signal = signals[(signalPhaseMs / 2000) % signals.size()].as<JsonObjectConst>();
    view.signalPresent = true;
    view.signal.label = label(signal["label"], "", 12);
    view.signal.showLabel = signal["show_label"] | false;
    view.signal.flashing = signal["flashing"] | false;
    JsonArrayConst pixels = signal["pixels"].as<JsonArrayConst>();
    for (int index = 0; index < 25; ++index) view.signal.pixels[index] = pixels[index] | uint16_t(0);
  } else {
    view.signal.label = "?";
    view.signal.showLabel = true;
    view.signal.pixels.fill(uint16_t(0x73B0));
  }
  for (JsonObjectConst row : source["rows"].as<JsonArrayConst>()) {
    if (view.count == 3) break;
    RacingRow& output = view.rows[view.count++];
    output.car = label(row["car"], "", 4);
    output.name = label(row["name"], "", 3);
    output.gap = label(row["compact_metric"], "", 12);
    output.position = row["position"] | 0;
    output.positionColor = rgbArray(row["position_rgb"], {235, 235, 235});
    output.metricColor = rgbArray(row["metric_rgb"], {180, 210, 255});
    output.numberColor = rgbArray(row["number_style"]["color_rgb"], {235, 235, 235});
    output.outlined = row["number_style"]["outline_rgb"].as<JsonArrayConst>().size() == 3;
    output.numberOutline = rgbArray(row["number_style"]["outline_rgb"], {0, 0, 0});
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

// A playing track advances from the time the server read it. The remaining time counts down.
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
  if (!std::isfinite(duration) || !std::isfinite(progress) || duration <= 0) {
    view.remaining = "--:--";
    return view;
  }
  progress = std::max(0.0, std::min(duration, progress));
  const unsigned remaining = static_cast<unsigned>(std::ceil(std::min(359999.0, duration - progress)));
  char clock[16];
  std::snprintf(clock, sizeof(clock), "-%u:%02u", remaining / 60, remaining % 60);
  view.remaining = clock;
  view.fraction = static_cast<float>(progress / duration);
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
  static const struct { const char* icon; WeatherSky sky; const char* day; const char* night; } skies[] = {
      {"sun", WeatherSky::Clear, "SUNNY", "CLEAR"}, {"cloud", WeatherSky::Cloud, "CLOUDY", "CLOUDY"},
      {"rain", WeatherSky::Rain, "RAIN", "RAIN"}, {"snow", WeatherSky::Snow, "SNOW", "SNOW"},
      {"fog", WeatherSky::Fog, "FOG", "FOG"}, {"storm", WeatherSky::Storm, "STORM", "STORM"}};
  const std::string icon = weather["icon"] | "";
  view.condition = "--";
  for (const auto& sky : skies) {
    if (icon == sky.icon) { view.sky = sky.sky; view.condition = view.night ? sky.night : sky.day; }
  }
  return view;
}

inline FlightPane flightPane(JsonObjectConst flight) {
  FlightPane view;
  view.id = label(flight["id"], "FLIGHT", 10);
  view.setup = label(flight["id"]) == "FLIGHT_BLANK";
  view.live = flight["is_live"] | false;
  view.delayed = flight["is_delayed"] | false;
  const std::string origin = label(flight["origin_iata"], "", 3), destination = label(flight["dest_iata"], "", 3);
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
  view.aircraft = label(flight["aircraft_code"], "", 12);
  view.progress = flight["progress"] | 0;
  return view;
}

// The board turns a page every four seconds. The detail line alternates between the arrival and the departure every two seconds.
inline AirportPane airportPane(JsonObjectConst airport, uint32_t elapsedMs = 0) {
  AirportPane view;
  JsonObjectConst weather = airport["weather"].as<JsonObjectConst>();
  view.code = label(weather["iata"], "---", 3);
  view.temperature = label(weather["away_abbr"], "--", 5);
  const auto arrivals = airport["arrivals"].as<JsonArrayConst>(), departures = airport["departures"].as<JsonArrayConst>();
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

}  // namespace mini_ui

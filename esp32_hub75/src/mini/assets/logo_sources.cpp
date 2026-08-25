#include <Arduino.h>
#include <ArduinoJson.h>

#include "logo_overrides_generated.h"
#include "logo_sources.h"

String fallbackSportsLogoUrl(JsonObjectConst game, const String& abbreviation) {
  String league = game["league"] | game["sport"] | "";
  league.toLowerCase();
  if (league == "football") league = "nfl";
  else if (league == "hockey") league = "nhl";
  else if (league == "baseball") league = "mlb";
  else if (league == "basketball") league = "nba";
  if (league.length() == 0 || abbreviation.length() == 0) {
    return "";
  }
  String code = abbreviation;
  code.toLowerCase();
  if (league == "nhl") {
    if (code == "sjs") code = "sj";
    else if (code == "njd") code = "nj";
    else if (code == "tbl") code = "tb";
    else if (code == "lak") code = "la";
    else if (code == "vgk" || code == "veg") code = "vgs";
    else if (code == "wsh" || code == "was") code = "wsh";
    else if (code == "uta") code = "utah";
  } else if (league == "nfl" && code == "was") {
    code = "wsh";
  }
  if (league == "ncf_fbs" || league == "ncf_fcs" || league == "ncaa" ||
      league == "college football" || league == "college basketball") {
    league = "ncaa";
  }
  return "https://a.espncdn.com/i/teamlogos/" + league + "/500/" + code + ".png";
}

String derivedSportsLogoUrl(JsonObjectConst game, const char* field, const String& abbreviation) {
  String url = game[field] | "";
  url.trim();
  if (url.length() > 0 && !url.startsWith("demo:")) {
    return url;
  }
  return fallbackSportsLogoUrl(game, abbreviation);
}

String miniLogoOverrideUrl(JsonObjectConst game, const String& abbreviation) {
  String league = game["league"] | game["sport"] | "";
  league.trim();
  league.toUpperCase();
  if (league == "BASEBALL") league = "MLB";
  else if (league == "BASKETBALL") league = "NBA";
  else if (league == "FOOTBALL") league = "NFL";
  else if (league == "HOCKEY") league = "NHL";
  String code = abbreviation;
  code.trim();
  code.toUpperCase();
  const String key = league + ":" + code;
  for (size_t index = 0; index < MINI_GENERATED_LOGO_OVERRIDE_COUNT; ++index) {
    const MiniGeneratedLogoOverride& override = MINI_GENERATED_LOGO_OVERRIDES[index];
    if (key == override.key) {
      return override.url;
    }
  }
  return "";
}

String sportsLogoUrl(JsonObjectConst game, const char* field, const String& abbreviation) {
  const String overrideUrl = miniLogoOverrideUrl(game, abbreviation);
  if (overrideUrl.length() > 0) {
    return overrideUrl;
  }
  return derivedSportsLogoUrl(game, field, abbreviation);
}

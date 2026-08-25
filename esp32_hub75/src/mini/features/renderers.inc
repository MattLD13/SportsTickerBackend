void drawFootballPossessionIndicator(int16_t x, int16_t y, uint16_t teamColor) {
  x += CONTENT_X_OFFSET;
  const uint16_t leather = color(165, 78, 25);
  const uint16_t laces = color(255, 240, 190);
  matrix->fillRoundRect(x, y, 9, 6, 2, color(12, 16, 28));
  matrix->drawRoundRect(x, y, 9, 6, 2, teamColor);
  matrix->fillRoundRect(x + 2, y + 1, 5, 4, 2, leather);
  matrix->drawFastVLine(x + 4, y + 1, 4, laces);
  matrix->drawPixel(x + 3, y + 2, laces);
  matrix->drawPixel(x + 5, y + 2, laces);
  matrix->drawPixel(x + 3, y + 3, laces);
  matrix->drawPixel(x + 5, y + 3, laces);
}

void drawScoreCenter(const String& awayScore, const String& homeScore) {
  String score = awayScore + "-" + homeScore;
  uint8_t scale = score.length() <= 4 ? 2 : 1;
  int16_t width = compactPixelTextWidth(score, scale);
  int16_t x = centeredPixelX(width);
  drawCompactPixelText(score, x, scale == 2 ? 9 : 11, color(255, 255, 255), scale);
}

bool sportIs(const String& sport, const char* value) {
  return sport == value;
}

void drawBaseballInningHeader(const String& status) {
  String upper = status;
  upper.toUpperCase();
  bool top = upper.startsWith("TOP") || upper.indexOf(" TOP") >= 0;
  bool bottom = upper.startsWith("BOT") || upper.startsWith("BOTTOM") || upper.indexOf(" BOT") >= 0;
  const bool middleOrEnd = upper.startsWith("MID") || upper.startsWith("END") || upper.indexOf(" MID") >= 0 || upper.indexOf(" END") >= 0;
  String inning = "";
  for (size_t index = 0; index < upper.length(); ++index) {
    if (isDigit(upper[index])) {
      inning += upper[index];
    } else if (inning.length() > 0) {
      break;
    }
  }
  if (!top && !bottom && !middleOrEnd) {
    return;
  }
  const uint16_t header = color(255, 235, 145);
  const int16_t symbolWidth = 5;
  const int16_t numberWidth = static_cast<int16_t>(inning.length() * 4);
  const int16_t totalWidth = symbolWidth + (numberWidth > 0 ? 1 + numberWidth : 0);
  const int16_t x = centeredPixelX(totalWidth);
  const int16_t symbolX = x + CONTENT_X_OFFSET;
  const int16_t symbolY = 1;
  if (top) {
    matrix->drawFastHLine(symbolX, symbolY + 4, symbolWidth, header);
    matrix->drawFastHLine(symbolX + 1, symbolY + 3, 3, header);
    matrix->drawFastHLine(symbolX + 2, symbolY + 2, 1, header);
  } else if (bottom) {
    matrix->drawFastHLine(symbolX, symbolY + 1, symbolWidth, header);
    matrix->drawFastHLine(symbolX + 1, symbolY + 2, 3, header);
    matrix->drawFastHLine(symbolX + 2, symbolY + 3, 1, header);
  } else {
    matrix->drawFastHLine(symbolX, symbolY + 2, symbolWidth, header);
  }
  if (numberWidth > 0) {
    drawPixelText(inning, x + symbolWidth + 1, symbolY, header, 1);
  }
}

void drawBaseballCountAndBases(JsonObjectConst situation, const String& away, const String& home) {
  const uint16_t ballColor = color(70, 210, 80);
  const uint16_t strikeColor = color(255, 150, 35);
  const uint16_t outColor = color(220, 65, 65);
  const uint16_t offColor = color(45, 45, 55);
  const int balls = min(3, static_cast<int>(situation["balls"] | 0));
  const int strikes = min(2, static_cast<int>(situation["strikes"] | 0));
  const int outs = min(3, static_cast<int>(situation["outs"] | 0));
  String activeTeam = situation["activeTeam"] | "";
  if (activeTeam.length() == 0) activeTeam = situation["possession"] | "";
  activeTeam.toUpperCase();
  const bool homeBatting = activeTeam == home || activeTeam == "HOME" || activeTeam == "H";
  const int16_t battingCenter = homeBatting ? 55 : 9;
  const int16_t countWidth = 12;
  const int16_t countX = battingCenter - countWidth / 2;
  drawPixelText(String(balls), countX, 1, ballColor, 1);
  drawPixelText("-", countX + 4, 1, color(160, 160, 160), 1);
  drawPixelText(String(strikes), countX + 8, 1, strikeColor, 1);

  const int16_t centerX = 32 + CONTENT_X_OFFSET;
  const int16_t baseY = 20;
  const uint16_t baseColor = color(255, 200, 55);
  const bool onFirst = situation["onFirst"] | false;
  const bool onSecond = situation["onSecond"] | false;
  const bool onThird = situation["onThird"] | false;
  matrix->fillRect(centerX - 1, baseY, 3, 3, onSecond ? baseColor : offColor);
  matrix->fillRect(centerX - 5, baseY + 3, 3, 3, onThird ? baseColor : offColor);
  matrix->fillRect(centerX + 3, baseY + 3, 3, 3, onFirst ? baseColor : offColor);
  const int16_t outX = centerX - 7;
  for (int index = 0; index < 3; ++index) {
    matrix->fillCircle(outX + index * 5, 29, 1, index < outs ? outColor : offColor);
  }
}

void drawHockeyIndicators(JsonObjectConst situation, const String& away, const String& home) {
  const bool powerPlay = situation["powerPlay"] | false;
  const bool emptyNet = situation["emptyNet"] | false;
  if (!powerPlay && !emptyNet) {
    return;
  }
  String label = emptyNet ? "EN" : "PP";
  String side = situation["emptyNetSide"] | "";
  if (side.length() == 0) {
    side = situation["activeTeam"] | "";
  }
  side.toUpperCase();
  const bool homeSide = side == home || side == "HOME" || side == "H";
  const int16_t x = homeSide ? 50 : 2;
  drawPixelText(label, x, 1, emptyNet ? color(255, 90, 90) : color(255, 220, 70), 1);
}

void drawSoccerIndicators(JsonObjectConst situation) {
  JsonArrayConst redCards = situation["red_cards"].as<JsonArrayConst>();
  uint8_t awayCards = 0;
  uint8_t homeCards = 0;
  for (JsonObjectConst card : redCards) {
    if (card["is_home"] | false) {
      ++homeCards;
    } else {
      ++awayCards;
    }
  }
  if (awayCards > 0) {
    matrix->fillRect(16 + CONTENT_X_OFFSET, 1, 3, 5, color(220, 35, 45));
  }
  if (homeCards > 0) {
    matrix->fillRect(45 + CONTENT_X_OFFSET, 1, 3, 5, color(220, 35, 45));
  }
}

void drawGame(JsonObjectConst game, const PreparedGameLogos& logos) {
  const uint16_t cyan = color(35, 190, 235);
  const uint16_t navy = color(0, 0, 0);
  const uint16_t muted = color(55, 76, 130);
  const uint16_t red = color(220, 45, 60);
  const uint16_t awayColor = teamColor(game["away_color"], color(255, 130, 40));
  const uint16_t homeColor = teamColor(game["home_color"], color(70, 155, 255));

  String sport = sportName(game);
  String away = shortValue(game["away_abbr"], "AWY", 4);
  String home = shortValue(game["home_abbr"], "HOM", 4);
  String awayScore = shortValue(game["away_score"], "-", 3);
  String homeScore = shortValue(game["home_score"], "-", 3);
  String status = shortValue(game["status"], "UPCOMING", 12);
  String state = shortValue(game["state"], "", 5);
  JsonObjectConst situation = game["situation"].as<JsonObjectConst>();
  const bool football = sportIs(sport, "FOOTBALL");
  const bool baseball = sportIs(sport, "BASEBALL");
  const bool hockey = sportIs(sport, "HOCKEY");
  const bool soccer = sport.startsWith("SOCCER");
  String detail = football ? shortValue(situation["downDist"], "", 12) : "";
  String possession = situation["activeTeam"] | "";
  if (possession.length() == 0) possession = situation["possession"] | "";
  possession.toUpperCase();
  const bool active = state == "IN";
  String statusLower = status;
  statusLower.toLowerCase();
  const bool delayed = statusLower.indexOf("delay") >= 0 || statusLower.indexOf("suspended") >= 0 ||
                       statusLower.indexOf("postponed") >= 0 || statusLower.indexOf("canceled") >= 0 ||
                       statusLower.indexOf("ppd") >= 0;
  const bool homePossession = possession == home || possession == "HOME" || possession == "H";
  const bool awayPossession = possession == away || possession == "AWAY" || possession == "A";

  matrix->fillScreen(navy);
  matrix->drawFastHLine(0, 7, 64, muted);
  if (!(baseball && active && !delayed)) {
    const int16_t statusWidth = static_cast<int16_t>(status.length() * 4);
    drawPixelTextFit(status, centeredPixelX(statusWidth), 1, color(255, 240, 150), 1, 60);
  }

  // Match the big ticker's one-pixel edge margins. The bounds also keep a bad
  // asset from wrapping into the opposite edge of the physical panel.
  drawLogoWithFallback(logos.awayPrimary, logos.awayFallback, away, 1, 9, awayColor);
  drawLogoWithFallback(logos.homePrimary, logos.homeFallback, home, 45, 9, homeColor);
  drawScoreCenter(awayScore, homeScore);

  if (football && active && awayPossession) drawFootballPossessionIndicator(2, 1, awayColor);
  if (football && active && homePossession) drawFootballPossessionIndicator(53, 1, homeColor);
  if (football && detail.length() > 0) {
    const int16_t detailWidth = static_cast<int16_t>(detail.length() * 4);
    drawPixelTextFit(detail, centeredPixelX(detailWidth), 24, active ? red : color(255, 220, 90), 1, 60);
  } else if (baseball && active) {
    if (!delayed) {
      drawBaseballInningHeader(status);
      drawBaseballCountAndBases(situation, away, home);
    }
  } else if (hockey && active) {
    drawHockeyIndicators(situation, away, home);
  } else if (soccer) {
    drawSoccerIndicators(situation);
  }
  presentFrame();
}

bool firstShownModeItem(const char* family, JsonObjectConst& data) {
  JsonArrayConst items = payload["content"][family].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) {
      continue;
    }
    data = item["data"].as<JsonObjectConst>();
    return !data.isNull();
  }
  return false;
}

void drawModeHeader(const String& label, uint16_t accent) {
  matrix->fillScreen(color(1, 4, 12));
  matrix->drawFastHLine(0, 7, 64, color(35, 58, 105));
  drawPixelTextFit(label, 2, 1, accent, 1, 60);
}

void drawWeather(JsonObjectConst weather) {
  const uint16_t blue = color(50, 150, 255);
  const uint16_t yellow = color(255, 218, 70);
  const uint16_t white = color(240, 245, 255);
  drawModeHeader(shortValue(weather["away_abbr"], "WEATHER", 12), blue);
  String temperature = shortValue(weather["home_abbr"], "--", 4);
  drawPixelTextFit(temperature, 2, 10, yellow, 2, 30);
  drawPixelText("F", 30, 13, yellow, 1);
  drawPixelTextFit(shortValue(weather["status"], "NO DATA", 12), 2, 25, white, 1, 32);
  JsonObjectConst situation = weather["situation"].as<JsonObjectConst>();
  JsonObjectConst stats = situation["stats"].as<JsonObjectConst>();
  drawPixelTextFit("H" + shortValue(stats["humidity"], "--", 2), 39, 11, blue, 1, 24);
  drawPixelTextFit("W" + shortValue(stats["wind"], "--", 2), 39, 18, blue, 1, 24);
  presentFrame();
}

void drawMusic(JsonObjectConst music) {
  const uint16_t magenta = color(230, 65, 195);
  const uint16_t green = color(40, 220, 120);
  drawModeHeader("MUSIC", magenta);
  matrix->fillCircle(10, 17, 8, color(24, 28, 42));
  matrix->drawCircle(10, 17, 8, magenta);
  matrix->drawCircle(10, 17, 5, color(55, 64, 88));
  matrix->fillCircle(10, 17, 2, green);
  drawPixelTextFit(shortValue(music["name"], music["away_abbr"].isNull() ? "UNKNOWN" : music["away_abbr"].as<String>().c_str(), 10), 22, 10, color(245, 245, 255), 1, 40);
  drawPixelTextFit(shortValue(music["artist"], music["home_abbr"].isNull() ? "ARTIST" : music["home_abbr"].as<String>().c_str(), 10), 22, 18, color(165, 180, 205), 1, 40);
  const bool playing = music["is_playing"] | false;
  drawPixelText(playing ? "P" : "S", 2, 27, green, 1);
  const int progress = min(64, max(0, static_cast<int>(music["progress"] | 0)));
  matrix->fillRect(10, 30, 54, 2, color(28, 42, 60));
  matrix->fillRect(10, 30, progress * 54 / 100, 2, green);
  presentFrame();
}

void drawFlight(JsonObjectConst flight) {
  const uint16_t orange = color(255, 145, 45);
  const uint16_t blue = color(50, 150, 255);
  const bool delayed = flight["is_delayed"] | false;
  drawModeHeader(shortValue(flight["id"], "FLIGHT", 12), orange);
  String origin = shortValue(flight["origin_city"], "DEP", 3);
  String destination = shortValue(flight["dest_city"], "ARR", 3);
  drawPixelTextFit(origin + "/" + destination, 2, 10, color(242, 246, 255), 1, 34);
  drawPixelTextFit(shortValue(flight["eta_str"], "--", 8), 2, 18, blue, 1, 32);
  drawPixelTextFit(delayed ? "DELAY" : shortValue(flight["status"], "EN ROUTE", 8), 37, 18, delayed ? color(255, 80, 75) : color(50, 225, 125), 1, 26);
  const int progress = min(100, max(0, static_cast<int>(flight["progress"] | 0)));
  matrix->fillRect(2, 29, 60, 3, color(25, 38, 58));
  matrix->fillRect(2, 29, progress * 60 / 100, 3, blue);
  presentFrame();
}

void drawAirport(JsonObjectConst airport) {
  const uint16_t green = color(45, 220, 125);
  const uint16_t red = color(255, 75, 75);
  JsonObjectConst weather = airport["weather"].as<JsonObjectConst>();
  String code = shortValue(weather["iata"], "AIRPORT", 8);
  drawModeHeader(code, green);
  drawPixelTextFit(shortValue(weather["away_abbr"], "--", 4), 39, 1, color(255, 220, 70), 1, 24);
  JsonArrayConst arrivals = airport["arrivals"].as<JsonArrayConst>();
  JsonArrayConst departures = airport["departures"].as<JsonArrayConst>();
  JsonObjectConst arrival = arrivals.size() > 0 ? arrivals[0].as<JsonObjectConst>() : JsonObjectConst();
  JsonObjectConst departure = departures.size() > 0 ? departures[0].as<JsonObjectConst>() : JsonObjectConst();
  drawPixelText("IN", 2, 10, green, 1);
  drawPixelTextFit(shortValue(arrival["flight_number"], "---", 7), 13, 10, color(242, 246, 255), 1, 27);
  drawPixelTextFit(shortValue(arrival["airport_code"], "---", 3), 43, 10, color(155, 175, 205), 1, 19);
  drawPixelText("OUT", 0, 19, red, 1);
  drawPixelTextFit(shortValue(departure["flight_number"], "---", 7), 18, 19, color(242, 246, 255), 1, 22);
  drawPixelTextFit(shortValue(departure["airport_code"], "---", 3), 46, 19, color(155, 175, 205), 1, 17);
  presentFrame();
}

void drawStock(JsonObjectConst stock) {
  const uint16_t green = color(45, 220, 125);
  const uint16_t red = color(255, 75, 75);
  String symbol = shortValue(stock["symbol"], stock["home_abbr"].isNull() ? "STOCK" : stock["home_abbr"].as<String>().c_str(), 8);
  const float percent = stock["away_score"] | 0.0f;
  const bool positive = percent >= 0.0f;
  drawModeHeader(symbol, positive ? green : red);
  String price = shortValue(stock["home_score"], "--", 7);
  drawPixelTextFit(price, 2, 10, color(245, 245, 255), 2, 38);
  String change = String(percent, 1) + "P";
  if (positive) change = "+" + change;
  drawPixelTextFit(change, 43, 14, positive ? green : red, 1, 20);
  JsonObjectConst situation = stock["situation"].as<JsonObjectConst>();
  drawPixelTextFit("D" + shortValue(situation["change"], "--", 6), 2, 25, positive ? green : red, 1, 40);
  presentFrame();
}

void drawClock(const struct tm& localTime, bool clockReady) {
  const uint16_t cyan = color(45, 205, 235);
  drawModeHeader("CLOCK", cyan);
  if (!clockReady) {
    drawPixelTextFit("SYNC", 2, 12, color(255, 220, 70), 2, 32);
    presentFrame();
    return;
  }
  char dateBuffer[16] = {};
  char timeBuffer[8] = {};
  char amPmBuffer[4] = {};
  strftime(dateBuffer, sizeof(dateBuffer), "%a %b %d", &localTime);
  strftime(timeBuffer, sizeof(timeBuffer), "%I:%M", &localTime);
  strftime(amPmBuffer, sizeof(amPmBuffer), "%p", &localTime);
  String timeValue = timeBuffer;
  if (timeValue.startsWith("0")) timeValue.remove(0, 1);
  drawPixelTextFit(dateBuffer, 2, 1, color(155, 180, 210), 1, 60);
  drawPixelTextFit(timeValue, 2, 10, color(245, 245, 255), 2, 42);
  drawPixelTextFit(amPmBuffer, 48, 15, cyan, 1, 14);
  matrix->fillRect(2, 29, 60, 3, color(22, 35, 54));
  matrix->fillRect(2, 29, (localTime.tm_sec * 60) / 60, 3, cyan);
  presentFrame();
}

void renderCurrent() {
  bool loading = false;
  uint16_t complete = 0;
  uint16_t total = 0;
  logoProgressSnapshot(loading, complete, total);
  if (loading) {
    drawDownloadingProgress(complete, total);
    return;
  }
  if (pairingMode) {
    drawPairingCode();
    return;
  }
  if (sportsMode) {
    if (pageCount == 0) {
      drawMessage("NO SPORTS");
      return;
    }
    if (pageIndex >= pageCount) {
      pageIndex = 0;
    }
    JsonObjectConst game;
    if (!selectedGame(game)) {
      drawMessage("BAD DATA");
      return;
    }
    prepareSelectedGameLogoSources(game);
    drawGame(game, preparedGameLogos);
    return;
  }
  JsonObjectConst item;
  if (displayMode == "weather" && firstShownModeItem("weather", item)) drawWeather(item);
  else if (displayMode == "music" && firstShownModeItem("music", item)) drawMusic(item);
  else if (displayMode == "flights" && firstShownModeItem("flights", item)) drawFlight(item);
  else if (displayMode == "airports" && firstShownModeItem("airports", item)) drawAirport(item);
  else if (displayMode == "stock" && firstShownModeItem("stock", item)) drawStock(item);
  else if (displayMode == "clock") drawClock(preparedClock, preparedClockValid);
  else drawMessage("NO " + displayMode);
}
// Owns sports indicators and renderers for all selectable display modes.

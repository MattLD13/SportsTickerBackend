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
  const size_t longestScore = awayScore.length() > homeScore.length() ? awayScore.length() : homeScore.length();
  const bool largeScores = longestScore <= 1;
  const bool mediumScores = longestScore == 2;
  const uint8_t compactScale = largeScores ? 2 : 1;
  const int16_t awayWidth = mediumScores ? mediumScoreTextWidth(awayScore) : compactPixelTextWidth(awayScore, compactScale);
  const int16_t dashWidth = compactPixelTextWidth("-", 1);
  const int16_t homeWidth = mediumScores ? mediumScoreTextWidth(homeScore) : compactPixelTextWidth(homeScore, compactScale);
  const int16_t groupWidth = awayWidth + 1 + dashWidth + 1 + homeWidth;
  const int16_t groupX = centeredPixelX(groupWidth);
  const uint16_t scoreColor = color(255, 255, 255);
  if (mediumScores) {
    drawMediumScoreText(awayScore, groupX, 9, scoreColor);
  } else {
    drawCompactPixelText(awayScore, groupX, largeScores ? 8 : 10, scoreColor, compactScale);
  }
  drawCompactPixelText("-", groupX + awayWidth + 1, 10, color(185, 190, 205), 1);
  const int16_t homeX = groupX + awayWidth + dashWidth + 2;
  if (mediumScores) {
    drawMediumScoreText(homeScore, homeX, 9, scoreColor);
  } else {
    drawCompactPixelText(homeScore, homeX, largeScores ? 8 : 10, scoreColor, compactScale);
  }
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
  const int16_t countWidth = 11;
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
  auto drawBase = [&](int16_t x, int16_t y, bool occupied) {
    const uint16_t value = occupied ? baseColor : offColor;
    matrix->drawFastHLine(x - 2, y, 5, value);
    matrix->drawFastHLine(x - 1, y + 1, 3, value);
    matrix->drawPixel(x, y + 2, value);
  };
  drawBase(centerX, baseY, onSecond);
  drawBase(centerX - 5, baseY + 3, onThird);
  drawBase(centerX + 5, baseY + 3, onFirst);
  const int16_t outX = centerX - 5;
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

void drawWeatherGlyph(const String& name, int16_t x, int16_t y, uint16_t accent) {
  String icon = name;
  icon.toLowerCase();
  const uint16_t cloud = color(150, 175, 205);
  const uint8_t frame = static_cast<uint8_t>((millis() / 350) % 4);
  if (icon.indexOf("sun") >= 0 || icon.indexOf("clear") >= 0) {
    const uint16_t sun = color(255, 205, 50);
    matrix->fillCircle(x + 6, y + 6, 3, sun);
    matrix->drawFastHLine(x + 6, y, 1, accent);
    matrix->drawFastHLine(x + 6, y + 12, 1, accent);
    matrix->drawFastVLine(x, y + 6, 1, accent);
    matrix->drawFastVLine(x + 12, y + 6, 1, accent);
    const uint8_t diagonalPhase = frame == 1 || frame == 3 ? 1 : 0;
    matrix->drawPixel(x + 1 + diagonalPhase, y + 1, accent);
    matrix->drawPixel(x + 10 - diagonalPhase, y + 1, accent);
    matrix->drawPixel(x + 1 + diagonalPhase, y + 10, accent);
    matrix->drawPixel(x + 10 - diagonalPhase, y + 10, accent);
    return;
  }
  if (icon.indexOf("snow") >= 0) {
    matrix->fillCircle(x + 4, y + 5, 3, cloud);
    matrix->fillCircle(x + 8, y + 5, 4, cloud);
    matrix->drawFastHLine(x + 1, y + 8, 10, cloud);
    matrix->drawPixel(x + 3, y + 10 + (frame & 1), accent);
    matrix->drawPixel(x + 6, y + 11 - (frame & 1), accent);
    matrix->drawPixel(x + 9, y + 10 + ((frame + 1) & 1), accent);
    return;
  }
  if (icon.indexOf("fog") >= 0 || icon.indexOf("mist") >= 0 || icon.indexOf("haze") >= 0) {
    const int8_t drift = static_cast<int8_t>(frame) - 1;
    matrix->drawFastHLine(x + 1 + drift, y + 3, 9, cloud);
    matrix->drawFastHLine(x + 2 - drift, y + 6, 8, accent);
    matrix->drawFastHLine(x + 1 + drift, y + 9, 10, cloud);
    return;
  }
  matrix->fillCircle(x + 4, y + 6, 3, cloud);
  matrix->fillCircle(x + 8, y + 5, 4, cloud);
  matrix->drawFastHLine(x + 1, y + 8, 11, cloud);
  if (icon.indexOf("rain") >= 0 || icon.indexOf("storm") >= 0) {
    const uint8_t dropOffset = frame == 0 ? 0 : frame == 1 ? 1 : frame == 2 ? 2 : 1;
    matrix->drawPixel(x + 3, y + 9 + dropOffset, accent);
    matrix->drawPixel(x + 6, y + 10 + ((dropOffset + 1) % 3), accent);
    matrix->drawPixel(x + 9, y + 9 + ((dropOffset + 2) % 3), accent);
  }
  if (icon.indexOf("storm") >= 0) {
    const uint16_t lightning = color(255, 220, 55);
    if (frame == 0 || frame == 3) {
      matrix->drawPixel(x + 7, y + 8, lightning);
      matrix->drawPixel(x + 6, y + 9, lightning);
      matrix->drawPixel(x + 5, y + 10, lightning);
    }
  }
}

uint16_t weatherTemperatureColor(const String& value) {
  const int16_t temperature = value.toInt();
  if (temperature >= 90) return color(255, 90, 35);
  if (temperature >= 75) return color(255, 185, 40);
  if (temperature >= 55) return color(95, 225, 105);
  if (temperature >= 35) return color(95, 190, 255);
  return color(190, 230, 255);
}

void drawWeather(JsonObjectConst weather) {
  const uint16_t blue = color(50, 150, 255);
  const uint16_t yellow = color(255, 218, 70);
  const uint16_t white = color(240, 245, 255);
  String city = shortValue(weather["city"], weather["away_abbr"].isNull() ? "WEATHER" : weather["away_abbr"].as<String>().c_str(), 10);
  String temperature = shortValue(weather["temperature"], weather["home_abbr"].isNull() ? "--" : weather["home_abbr"].as<String>().c_str(), 4);
  JsonObjectConst situation = weather["situation"].as<JsonObjectConst>();
  JsonObjectConst stats = situation["stats"].as<JsonObjectConst>();
  String icon = situation["icon"] | weather["icon"] | weather["status"] | "cloud";
  matrix->fillScreen(color(1, 4, 12));
  drawPixelTextFit(city, 2, 1, blue, 1, 40);
  drawWeatherGlyph(icon, 1, 9, blue);
  const uint16_t temperatureColor = weatherTemperatureColor(temperature);
  drawPixelTextFit(temperature, 16, 10, temperatureColor, 2, 21);
  drawPixelText("F", 33, 13, temperatureColor, 1);
  drawPixelTextFit("FEELS", 1, 24, yellow, 1, 20);
  drawPixelTextFit(shortValue(stats["feels"], "--", 2), 22, 24, yellow, 1, 13);
  drawPixelTextFit("W" + shortValue(stats["wind"], "--", 2), 43, 9, blue, 1, 21);
  drawPixelTextFit("H" + shortValue(stats["humidity"], "--", 2), 43, 16, color(120, 210, 230), 1, 21);
  drawPixelTextFit("A" + shortValue(stats["aqi"], "--", 2), 43, 23, color(100, 230, 125), 1, 21);
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
  const uint16_t red = color(255, 80, 75);
  const uint16_t green = color(50, 225, 125);
  const bool live = flight["is_live"] | false;
  const bool delayed = flight["is_delayed"] | false || (flight["delay_min"] | 0) > 0;
  String flightId = shortValue(flight["id"], "FLIGHT", 8);
  drawModeHeader(flightId, delayed ? red : orange);
  drawPixelText("^", 54, 1, delayed ? red : green, 1);
  String origin = shortValue(flight["origin_iata"], flight["origin_city"].isNull() ? "DEP" : flight["origin_city"].as<String>().c_str(), 3);
  String destination = shortValue(flight["dest_iata"], flight["dest_city"].isNull() ? "ARR" : flight["dest_city"].as<String>().c_str(), 3);
  drawPixelTextFit(origin + ">" + destination, 2, 10, color(242, 246, 255), 1, 27);
  if (live) {
    drawPixelTextFit("E" + shortValue(flight["eta_str"], "--", 6), 2, 18, blue, 1, 31);
    drawPixelTextFit("S" + shortValue(flight["speed"], "--", 4), 40, 18, color(120, 210, 230), 1, 21);
  } else {
    drawPixelTextFit(shortValue(flight["status"], "SCHEDULED", 8), 2, 18, orange, 1, 34);
  }
  String detail = delayed ? "D" + shortValue(flight["delay_min"], "--", 3) : "A" + String((flight["alt"] | 0) / 1000) + "K";
  drawPixelTextFit(detail, 2, 24, delayed ? red : color(220, 225, 240), 1, 25);
  drawPixelTextFit(shortValue(flight["status"], "EN ROUTE", 7), 31, 24, delayed ? red : green, 1, 31);
  const int progress = min(100, max(0, static_cast<int>(flight["progress"] | 0)));
  matrix->fillRect(2, 29, 60, 3, delayed ? color(60, 10, 10) : color(15, 35, 15));
  matrix->fillRect(2, 29, max(1, progress * 60 / 100), 3, delayed ? red : green);
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
    const int16_t syncWidth = compactPixelTextWidth("SYNC", 2);
    drawCompactPixelText("SYNC", centeredPixelX(syncWidth) - CONTENT_X_OFFSET, 8, color(255, 220, 70), 2);
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
  const int16_t timeWidth = compactPixelTextWidth(timeValue, 2);
  const int16_t amPmWidth = compactPixelTextWidth(amPmBuffer, 1);
  const int16_t groupWidth = timeWidth + 2 + amPmWidth;
  const int16_t groupX = centeredPixelX(groupWidth) - CONTENT_X_OFFSET;
  drawCompactPixelText(timeValue, groupX, 8, color(245, 245, 255), 2);
  drawCompactPixelText(amPmBuffer, groupX + timeWidth + 2, 11, cyan, 1);
  matrix->fillRect(CONTENT_X_OFFSET, 20, 60, 3, color(22, 35, 54));
  matrix->fillRect(CONTENT_X_OFFSET, 20, (localTime.tm_sec * 60) / 60, 3, cyan);
  presentFrame();
}

void renderCurrent() {
  if (firmwareUpdateDisplayActive()) {
    uint8_t state = 0;
    uint32_t complete = 0;
    uint32_t total = 0;
    char detail[24] = {};
    firmwareUpdateDisplaySnapshot(state, complete, total, detail, sizeof(detail));
    drawFirmwareUpdate(state, complete, total, detail);
    return;
  }
  if (pairingMode) {
    drawPairingCode();
    return;
  }
  bool loading = false;
  uint16_t complete = 0;
  uint16_t total = 0;
  logoProgressSnapshot(loading, complete, total);
  if (loading && sportsMode && !sportsFrameReady) {
    drawDownloadingProgress(complete, total);
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

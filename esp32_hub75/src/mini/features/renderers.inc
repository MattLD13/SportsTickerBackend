#include "../protocol/panels.h"

class MiniCanvas {
 public:
  void pixel(int x, int y, ticker_ui::Rgb ink) { matrix->drawPixel(x, y, color(ink.r, ink.g, ink.b)); }
  void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) { matrix->fillRect(x, y, width, height, color(ink.r, ink.g, ink.b)); }
};

class MiniSportsCanvas : public MiniCanvas {
 public:
  explicit MiniSportsCanvas(const PreparedGameLogos& value) : logos(value) {}
  bool logo(ticker_ui::Side side, int x, int y) { return drawLogoAsset(side == ticker_ui::Side::Away ? logos.awayPrimary : logos.homePrimary, x, y); }
 private:
  const PreparedGameLogos& logos;
};

void drawGame(JsonObjectConst game, const PreparedGameLogos& logos) {
  MiniSportsCanvas canvas(logos);
  ticker_ui::renderSports(canvas, ticker_ui::sportsPane(game));
  presentFrame();
}

bool firstShownModeItem(const char* family, JsonObjectConst& data) {
  JsonArrayConst items = payload["content"][family].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) {
      continue;
    }
    beginFrame(family, item["id"] | "", 0, 1);
    data = item["data"].as<JsonObjectConst>();
    return !data.isNull();
  }
  return false;
}

void drawModeHeader(const String& label, uint16_t accent) {
  matrix->fillScreen(color(0, 0, 0));
  matrix->drawFastHLine(0, 7, 64, color(55, 76, 130));
  mini_text::drawPixelTextFit(*matrix, label, 2, 1, accent, 1, 60);
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
  matrix->fillScreen(color(0, 0, 0));
  mini_text::drawPixelTextFit(*matrix, city, 2, 1, blue, 1, 40);
  drawWeatherGlyph(icon, 1, 9, blue);
  const uint16_t temperatureColor = weatherTemperatureColor(temperature);
  mini_text::drawPixelTextFit(*matrix, temperature, 16, 10, temperatureColor, 2, 21);
  mini_text::drawPixelText(*matrix, "F", 33, 13, temperatureColor, 1);
  mini_text::drawPixelTextFit(*matrix, "FEELS", 1, 24, yellow, 1, 20);
  mini_text::drawPixelTextFit(*matrix, shortValue(stats["feels"], "--", 2), 22, 24, yellow, 1, 13);
  mini_text::drawPixelTextFit(*matrix, "W" + shortValue(stats["wind"], "--", 2), 43, 9, blue, 1, 21);
  mini_text::drawPixelTextFit(*matrix, "H" + shortValue(stats["humidity"], "--", 2), 43, 16, color(120, 210, 230), 1, 21);
  mini_text::drawPixelTextFit(*matrix, "A" + shortValue(stats["aqi"], "--", 2), 43, 23, color(100, 230, 125), 1, 21);
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
  mini_text::drawPixelTextFit(*matrix, shortValue(music["name"], music["away_abbr"].isNull() ? "UNKNOWN" : music["away_abbr"].as<String>().c_str(), 10), 22, 10, color(245, 245, 255), 1, 40);
  mini_text::drawPixelTextFit(*matrix, shortValue(music["artist"], music["home_abbr"].isNull() ? "ARTIST" : music["home_abbr"].as<String>().c_str(), 10), 22, 18, color(165, 180, 205), 1, 40);
  const bool playing = music["is_playing"] | false;
  mini_text::drawPixelText(*matrix, playing ? "P" : "S", 2, 27, green, 1);
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
  mini_text::drawPixelText(*matrix, "^", 54, 1, delayed ? red : green, 1);
  String origin = shortValue(flight["origin_iata"], flight["origin_city"].isNull() ? "DEP" : flight["origin_city"].as<String>().c_str(), 3);
  String destination = shortValue(flight["dest_iata"], flight["dest_city"].isNull() ? "ARR" : flight["dest_city"].as<String>().c_str(), 3);
  mini_text::drawPixelTextFit(*matrix, origin + ">" + destination, 2, 10, color(242, 246, 255), 1, 27);
  if (live) {
    mini_text::drawPixelTextFit(*matrix, "E" + shortValue(flight["eta_str"], "--", 6), 2, 18, blue, 1, 31);
    mini_text::drawPixelTextFit(*matrix, "S" + shortValue(flight["speed"], "--", 4), 40, 18, color(120, 210, 230), 1, 21);
  } else {
    mini_text::drawPixelTextFit(*matrix, shortValue(flight["status"], "SCHEDULED", 8), 2, 18, orange, 1, 34);
  }
  String detail = delayed ? "D" + shortValue(flight["delay_min"], "--", 3) : "A" + String((flight["alt"] | 0) / 1000) + "K";
  mini_text::drawPixelTextFit(*matrix, detail, 2, 24, delayed ? red : color(220, 225, 240), 1, 25);
  mini_text::drawPixelTextFit(*matrix, shortValue(flight["status"], "EN ROUTE", 7), 31, 24, delayed ? red : green, 1, 31);
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
  mini_text::drawPixelTextFit(*matrix, shortValue(weather["away_abbr"], "--", 4), 39, 1, color(255, 220, 70), 1, 24);
  JsonArrayConst arrivals = airport["arrivals"].as<JsonArrayConst>();
  JsonArrayConst departures = airport["departures"].as<JsonArrayConst>();
  JsonObjectConst arrival = arrivals.size() > 0 ? arrivals[0].as<JsonObjectConst>() : JsonObjectConst();
  JsonObjectConst departure = departures.size() > 0 ? departures[0].as<JsonObjectConst>() : JsonObjectConst();
  mini_text::drawPixelText(*matrix, "IN", 2, 10, green, 1);
  mini_text::drawPixelTextFit(*matrix, shortValue(arrival["flight_number"], "---", 7), 13, 10, color(242, 246, 255), 1, 27);
  mini_text::drawPixelTextFit(*matrix, shortValue(arrival["airport_code"], "---", 3), 43, 10, color(155, 175, 205), 1, 19);
  mini_text::drawPixelText(*matrix, "OUT", 0, 19, red, 1);
  mini_text::drawPixelTextFit(*matrix, shortValue(departure["flight_number"], "---", 7), 18, 19, color(242, 246, 255), 1, 22);
  mini_text::drawPixelTextFit(*matrix, shortValue(departure["airport_code"], "---", 3), 46, 19, color(155, 175, 205), 1, 17);
  presentFrame();
}

void drawStock(JsonObjectConst stock) {
  MiniCanvas canvas;
  ticker_ui::renderStock(canvas, ticker_ui::stockPane(stock));
  presentFrame();
}

void drawClock(const struct tm& localTime, bool clockReady) {
  beginFrame("clock", "", 0, 1);
  MiniCanvas canvas;
  ticker_ui::ClockPane view;
  view.ready = clockReady;
  if (clockReady) {
    char dateBuffer[16] = {}, timeBuffer[12] = {};
    strftime(dateBuffer, sizeof(dateBuffer), "%a %b %d", &localTime);
    strftime(timeBuffer, sizeof(timeBuffer), "%I:%M:%S", &localTime);
    view.date = dateBuffer;
    view.time = timeBuffer[0] == '0' ? timeBuffer + 1 : timeBuffer;
    view.seconds = localTime.tm_sec;
  }
  ticker_ui::renderClock(canvas, view);
  presentFrame();
  lastPresentedClockReady = view.ready;
  lastPresentedClockSecond = view.ready ? view.seconds : -1;
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
    JsonObjectConst selected;
    selectedSportsItem(selected);
    beginFrame("sports", selected["id"] | "", pageIndex, pageCount,
               pageCount > 1 ? pageHoldMillis(pageHoldSeconds) : 0);
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

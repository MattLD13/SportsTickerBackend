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
  JsonArrayConst items = payload.document()["content"][family].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) {
      continue;
    }
    selectedModeItemId = item["id"] | "";
    beginFrame(family, selectedModeItemId.c_str(), 0, 1);
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

void drawWeather(JsonObjectConst weather) {
  static String visibleCity;
  static uint32_t visibleSince = 0;
  const String city = weather["city"] | "";
  if (city != visibleCity) { visibleCity = city; visibleSince = millis(); }
  MiniCanvas canvas;
  ticker_ui::renderWeather(canvas, ticker_ui::weatherPane(weather, millis() - visibleSince));
  presentFrame();
}

void drawMusic(JsonObjectConst music) {
  class MusicCanvas : public MiniCanvas {
   public:
    explicit MusicCanvas(JsonObjectConst value) : asset(value) {}
    bool artwork() { return musicArtwork.draw(asset, *matrix); }
   private:
    JsonObjectConst asset;
  } canvas(music["cover_asset"].as<JsonObjectConst>());
  static String visibleTrack;
  static uint32_t visibleSince = 0;
  const String identity = selectedModeItemId;
  if (identity != visibleTrack) { visibleTrack = identity; visibleSince = millis(); }
  ticker_ui::renderMusic(canvas, ticker_ui::musicPane(music, static_cast<double>(time(nullptr)), millis() - visibleSince));
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
  if (firmwareUpdater.displayActive()) {
    uint8_t state = 0;
    uint32_t complete = 0;
    uint32_t total = 0;
    char detail[24] = {};
    firmwareUpdater.displaySnapshot(state, complete, total, detail, sizeof(detail));
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

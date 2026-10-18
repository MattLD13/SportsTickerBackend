#include "../protocol/panels.h"

#include "../rendering/matrix_canvas.h"

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
  MiniCanvas canvas;
  ticker_ui::renderFlight(canvas, ticker_ui::flightPane(flight));
  presentFrame();
}

void drawAirport(JsonObjectConst airport) {
  MiniCanvas canvas;
  ticker_ui::renderAirport(canvas, ticker_ui::airportPane(airport));
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

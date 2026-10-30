// Present frames, rotate pages, and draw device notices over or instead of content.
// This file binds the pure panes in ui/ to the matrix, the clock, and the runtime state.
#include "../protocol/panes.h"

class MiniCanvas {
 public:
  void pixel(int x, int y, mini_ui::Rgb ink) { matrix->drawPixel(x, y, color(ink.r, ink.g, ink.b)); }
  void rect(int x, int y, int width, int height, mini_ui::Rgb ink) { matrix->fillRect(x, y, width, height, color(ink.r, ink.g, ink.b)); }
};

bool shownItem(JsonObjectConst item) {
  return item["is_shown"].isNull() || item["is_shown"].as<bool>();
}


template<class Callback>
void forEachRotationItem(Callback callback) {
  JsonObjectConst content = payload.document()["content"].as<JsonObjectConst>();
  mini_ui::forEachRotationItem(content, sportsMode, callback);
}

bool rotatingMode() { return sportsMode || displayMode == "stock"; }

uint16_t countShownPages() {
  uint16_t count = 0;
  forEachRotationItem([&](JsonObjectConst) { ++count; });
  return count;
}

uint32_t pageRotationSignature() {
  String sequence = displayMode + "|";
  forEachRotationItem([&](JsonObjectConst item) {
    String identity = item["id"] | "";
    if (identity.length() == 0) identity = item["identifier"] | "";
    if (identity.length() == 0) identity = item["key"] | "";
    JsonObjectConst data = item["data"].as<JsonObjectConst>();
    if (identity.length() == 0) identity = data["id"] | "";
    if (identity.length() == 0) identity = data["identifier"] | "";
    if (identity.length() == 0) {
      String sport = data["sport"] | "";
      if (sport.length() == 0) sport = data["league"] | "sports";
      String away = data["away_abbr"] | "AWY";
      String home = data["home_abbr"] | "HOM";
      identity = sport + ":" + away + ":" + home;
    }
    sequence += identity + "|";
    sequence += miniSpriteToken(data, "away_logo_asset") + "|";
    sequence += miniSpriteToken(data, "home_logo_asset") + ";";
  });
  return hashBody(sequence);
}

bool pageItemAt(uint16_t wanted, JsonObjectConst& selected) {
  uint16_t index = 0;
  bool found = false;
  forEachRotationItem([&](JsonObjectConst item) {
    if (index++ == wanted) { selected = item; found = true; }
  });
  return found;
}

bool selectedPageItem(JsonObjectConst& selected) {
  return pageItemAt(pageIndex, selected);
}

bool racingPageSelected() {
  JsonObjectConst selected;
  return sportsMode && selectedPageItem(selected) && selected["data"]["racing_display"].is<JsonObjectConst>();
}

bool selectedGame(JsonObjectConst& selected) {
  JsonObjectConst item;
  if (!selectedPageItem(item)) return false;
  selected = item["data"].as<JsonObjectConst>();
  return !selected.isNull();
}

uint32_t pageHoldMillis(float scrollSpeed) {
  // The backend stores seconds per scroll pixel. On this panel, that value
  // controls page dwell. The default 0.03 value gives three seconds per page.
  if (!(scrollSpeed > 0.0f)) {
    scrollSpeed = 0.03f;
  }
  uint32_t dwell = static_cast<uint32_t>(scrollSpeed * 100000.0f);
  if (dwell < 1000) dwell = 1000;
  if (dwell > 10000) dwell = 10000;
  return dwell;
}

void prepareSystemClock(mini_ui::SystemPane& view) {
  const time_t epoch = time(nullptr);
  if (epoch < 1700000000) return;
  struct tm local = {};
  localtime_r(&epoch, &local);
  char clock[12] = {}, date[16] = {};
  strftime(clock, sizeof(clock), "%I:%M", &local);
  strftime(date, sizeof(date), "%a %b %d", &local);
  view.clock = clock[0] == '0' ? clock + 1 : clock;
  view.date = date;
  for (char& ch : view.date) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
}

mini_ui::SystemPane preparedSystemNotice(mini_ui::SystemKind kind, const String& detail) {
  static String previousDetail;
  static mini_ui::SystemKind previousKind = mini_ui::SystemKind::Startup;
  static uint32_t startedAt = 0;
  if (previousDetail != detail || previousKind != kind) {
    previousDetail = detail;
    previousKind = kind;
    startedAt = millis();
  }
  auto view = mini_ui::systemPane(kind, detail.c_str(), 0, 0, millis() - startedAt);
  prepareSystemClock(view);
  view.ageSeconds = wifiWaitStartedAt ? (millis() - wifiWaitStartedAt) / 1000 :
      lastDataSuccessAt ? (millis() - lastDataSuccessAt) / 1000 : 0;
  return view;
}

void presentContentFrame() {
  matrix->retainBaseFrame();
  if (message.length() && mini_ui::systemOverlay(messageKind)) {
    MiniCanvas canvas;
    mini_ui::drawOverlay(canvas, preparedSystemNotice(messageKind, message));
  }
  presentFrame();
}

void drawSystemNotice(mini_ui::SystemKind kind, const String& detail) {
  beginFrame("system", detail.c_str());
  MiniCanvas canvas;
  const auto view = preparedSystemNotice(kind, detail);
  if (kind == mini_ui::SystemKind::Empty) {
    mini_ui::draw(canvas, view);
    presentContentFrame();
    return;
  }
  if (mini_ui::systemOverlay(kind) && matrix->restoreBaseFrame()) mini_ui::drawOverlay(canvas, view);
  else mini_ui::draw(canvas, view);
  presentFrame();
}

void drawDownloadingProgress(uint16_t complete, uint16_t total) {
  beginFrame("loading", "sprites");
  if (!matrix) return;
  MiniCanvas canvas;
  mini_ui::draw(canvas, mini_ui::systemPane(mini_ui::SystemKind::Assets, "", complete, total, assetLoadingStartedAt ? millis() - assetLoadingStartedAt : 0));
  presentFrame();
}

void drawFirmwareUpdate(uint8_t state, uint32_t complete, uint32_t total, const char* detail) {
  beginFrame("firmware_update");
  if (!matrix) return;
  mini_ui::SystemKind kind = mini_ui::SystemKind::UpdateFailed;
  switch (state) {
    case FIRMWARE_UPDATE_CHECKING: kind = mini_ui::SystemKind::Checking; break;
    case FIRMWARE_UPDATE_DOWNLOADING: kind = mini_ui::SystemKind::Downloading; break;
    case FIRMWARE_UPDATE_INSTALLING: kind = mini_ui::SystemKind::Installing; break;
    case FIRMWARE_UPDATE_FAILED: kind = mini_ui::SystemKind::UpdateFailed; break;
  }
  static uint8_t previousState = 255;
  static uint32_t phaseStartedAt = 0;
  if (previousState != state) { previousState = state; phaseStartedAt = millis(); }
  MiniCanvas canvas;
  const auto view = mini_ui::systemPane(kind, detail ? detail : "", complete, total, millis() - phaseStartedAt);
  if (matrix->restoreBaseFrame()) mini_ui::drawOverlay(canvas, view);
  else mini_ui::draw(canvas, view);
  presentFrame();
}

void drawSolidColorTest() {
  beginFrame("test", "solid_color");
  const uint16_t colors[] = {
    color(255, 0, 0),
    color(0, 255, 0),
    color(0, 0, 255),
    color(255, 255, 255),
    color(0, 0, 0),
  };
  matrix->fillScreen(colors[solidColorIndex]);
  presentFrame();
  Serial.print("Solid color test index: ");
  Serial.println(solidColorIndex);
  solidColorIndex = (solidColorIndex + 1) % (sizeof(colors) / sizeof(colors[0]));
}

void drawPairingCode() {
  beginFrame("pairing", wifiPairingMode ? "wifi" : "app");
  MiniCanvas canvas;
  const auto view = mini_ui::pairingPane(wifiPairingMode, setupCode.c_str(), pairingCode.c_str(), millis());
  mini_ui::draw(canvas, view);
  presentFrame();
}



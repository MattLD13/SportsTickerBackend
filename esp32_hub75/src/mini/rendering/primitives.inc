void drawText(const String& value, int16_t x, int16_t y, uint16_t foreground) {
  matrix->setTextColor(foreground);
  matrix->setCursor(x, y);
  matrix->print(value);
}

void drawTextFit(const String& value, int16_t x, int16_t y, uint16_t foreground, int16_t width) {
  String clipped = value;
  const size_t maxCharacters = width > 0 ? static_cast<size_t>(width / 6) : 0;
  if (clipped.length() > maxCharacters) {
    clipped.remove(maxCharacters);
  }
  drawText(clipped, x, y, foreground);
}

void drawTextRight(const String& value, int16_t right, int16_t y, uint16_t foreground, int16_t left) {
  String clipped = value;
  const int16_t width = right - left;
  const size_t maxCharacters = width > 0 ? static_cast<size_t>(width / 6) : 0;
  if (clipped.length() > maxCharacters) {
    clipped.remove(maxCharacters);
  }
  const int16_t x = right - static_cast<int16_t>(clipped.length() * 6);
  drawText(clipped, x, y, foreground);
}

String shortValue(JsonVariantConst value, const char* fallback, size_t limit) {
  String result = value.isNull() ? String(fallback) : value.as<String>();
  result.trim();
  result.toUpperCase();
  if (result.length() > limit) {
    result.remove(limit);
  }
  return result;
}

bool shownItem(JsonObjectConst item) {
  return item["is_shown"].isNull() || item["is_shown"].as<bool>();
}


uint16_t countShownGames() {
  uint16_t count = 0;
  JsonObjectConst content = payload["content"].as<JsonObjectConst>();
  JsonArrayConst items = content["sports"].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (shownItem(item)) {
      ++count;
    }
  }
  return count;
}

uint32_t sportsRotationSignature() {
  String sequence = displayMode + "|";
  JsonObjectConst content = payload["content"].as<JsonObjectConst>();
  JsonArrayConst items = content["sports"].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) continue;
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
  }
  return hashBody(sequence);
}

bool selectedSportsItem(JsonObjectConst& selected) {
  uint16_t index = 0;
  JsonObjectConst content = payload["content"].as<JsonObjectConst>();
  JsonArrayConst items = content["sports"].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) {
      continue;
    }
    if (index == pageIndex) {
      selected = item;
      return true;
    }
    ++index;
  }
  return false;
}

bool selectedGame(JsonObjectConst& selected) {
  JsonObjectConst item;
  if (!selectedSportsItem(item)) return false;
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

void drawMessage(const String& value) {
  beginFrame("message", value.c_str());
  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, color(30, 150, 220));
  drawTextFit(value, 2, 13, color(255, 220, 80), 60);
  presentFrame();
}

void drawDownloadingProgress(uint16_t complete, uint16_t total) {
  beginFrame("loading", "sprites");
  if (matrix == nullptr) {
    return;
  }
  if (total == 0) {
    total = 1;
  }
  if (complete > total) {
    complete = total;
  }
  const uint16_t cyan = color(30, 150, 220);
  const uint16_t yellow = color(255, 220, 80);
  const uint8_t percent = static_cast<uint8_t>((complete * 100U) / total);
  const uint16_t filledWidth = static_cast<uint16_t>((58U * complete) / total);

  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, cyan);
  drawText("DOWNLOAD", 2, 3, yellow);
  drawTextRight(String(percent) + "%", 61, 3, cyan, 2);
  drawText("ASSETS", 2, 13, color(180, 200, 220));
  drawTextRight(String(complete) + "/" + String(total), 61, 13, color(180, 200, 220), 2);
  matrix->drawRect(2, 22, 60, 7, cyan);
  if (filledWidth > 0) {
    matrix->fillRect(3, 24, filledWidth, 3, yellow);
  }
  presentFrame();
}

void drawFirmwareUpdate(uint8_t state, uint32_t complete, uint32_t total, const char* detail) {
  beginFrame("firmware_update");
  if (matrix == nullptr) {
    return;
  }
  const uint16_t cyan = color(30, 150, 220);
  const uint16_t yellow = color(255, 220, 80);
  const uint16_t red = color(255, 75, 75);
  const char* title = state == 1 ? "CHECK UPDATE" :
                      state == 2 ? "DOWNLOAD FW" :
                      state == 3 ? "INSTALL FW" : "UPDATE FAIL";
  const uint16_t titleColor = state == 4 ? red : yellow;
  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, state == 4 ? red : cyan);
  drawTextFit(title, 2, 3, titleColor, 60);
  if (state == 2 && total > 0) {
    const uint8_t percent = static_cast<uint8_t>(min<uint32_t>(100, (complete * 100U) / total));
    drawTextRight(String(percent) + "%", 61, 3, cyan, 2);
    matrix->drawRect(2, 13, 60, 7, cyan);
    const uint16_t filledWidth = static_cast<uint16_t>((58U * min(complete, total)) / total);
    if (filledWidth > 0) {
      matrix->fillRect(3, 15, filledWidth, 3, yellow);
    }
    drawTextRight(String(complete / 1024) + "/" + String(total / 1024) + "K", 61, 24, color(180, 200, 220), 2);
  } else {
    drawTextFit(detail == nullptr ? "WAIT" : detail, 2, 16, state == 4 ? red : color(180, 200, 220), 60);
  }
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
  struct Canvas {
    void pixel(int x, int y, ticker_ui::Rgb ink) { matrix->drawPixel(x, y, color(ink.r, ink.g, ink.b)); }
    void rect(int x, int y, int width, int height, ticker_ui::Rgb ink) { matrix->fillRect(x, y, width, height, color(ink.r, ink.g, ink.b)); }
  } canvas;
  const auto view = ticker_ui::pairingPane(wifiPairingMode, setupCode.c_str(), pairingCode.c_str());
  ticker_ui::renderPairing(canvas, view);
  presentFrame();
}

const char* pixelGlyph(char value) {
  static char bits[16];
  const uint8_t* rows = ticker_ui::pane[ticker_ui::glyphIndex(value)];
  for (uint8_t row = 0; row < 5; ++row) {
    for (uint8_t column = 0; column < 3; ++column) bits[row * 3 + column] = rows[row] & (1 << (2 - column)) ? '1' : '0';
  }
  bits[15] = '\0';
  return bits;
}

void drawPixelText(const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale = 1) {
  int16_t cursor = x + CONTENT_X_OFFSET;
  for (size_t characterIndex = 0; characterIndex < value.length(); ++characterIndex) {
    const char* glyph = pixelGlyph(value[characterIndex]);
    for (uint8_t row = 0; row < 5; ++row) {
      for (uint8_t column = 0; column < 3; ++column) {
        if (glyph[row * 3 + column] == '1') {
          matrix->fillRect(cursor + column * scale, y + row * scale, scale, scale, foreground);
        }
      }
    }
    cursor += 4 * scale;
  }
}

void drawPixelTextFit(const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale, int16_t width) {
  String clipped = value;
  const size_t maximumCharacters = width > 0 ? static_cast<size_t>(width / (4 * scale)) : 0;
  if (clipped.length() > maximumCharacters) {
    clipped.remove(maximumCharacters);
  }
  drawPixelText(clipped, x, y, foreground, scale);
}

// Owns pixel primitives, status panels, geometry helpers, and page timing helpers.

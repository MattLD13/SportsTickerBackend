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

String sportName(JsonObjectConst game) {
  String sport = game["sport"] | game["league"] | "SPORTS";
  sport.trim();
  sport.toUpperCase();
  if (sport == "NFL") return "FOOTBALL";
  if (sport == "NHL") return "HOCKEY";
  if (sport == "MLB") return "BASEBALL";
  if (sport == "NBA") return "BASKETBALL";
  if (sport.length() == 0) return "SPORTS";
  if (sport.length() > 10) sport.remove(10);
  return sport;
}

bool shownItem(JsonObjectConst item) {
  return item["is_shown"].isNull() || item["is_shown"].as<bool>();
}

String sportsLogoUrl(JsonObjectConst game, const char* field, const String& abbreviation);
String fallbackSportsLogoUrl(JsonObjectConst game, const String& abbreviation);

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
    const String away = shortValue(data["away_abbr"], "AWY", 4);
    const String home = shortValue(data["home_abbr"], "HOM", 4);
    sequence += sportsLogoUrl(data, "away_logo", away) + "|";
    sequence += fallbackSportsLogoUrl(data, away) + "|";
    sequence += sportsLogoUrl(data, "home_logo", home) + "|";
    sequence += fallbackSportsLogoUrl(data, home) + ";";
  }
  return hashBody(sequence);
}

bool selectedGame(JsonObjectConst& selected) {
  uint16_t index = 0;
  JsonObjectConst content = payload["content"].as<JsonObjectConst>();
  JsonArrayConst items = content["sports"].as<JsonArrayConst>();
  for (JsonObjectConst item : items) {
    if (!shownItem(item)) {
      continue;
    }
    if (index == pageIndex) {
      selected = item["data"].as<JsonObjectConst>();
      return !selected.isNull();
    }
    ++index;
  }
  return false;
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
  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, color(30, 150, 220));
  drawTextFit(value, 2, 13, color(255, 220, 80), 60);
  presentFrame();
}

void drawDownloadingProgress(uint16_t complete, uint16_t total) {
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

void drawSolidColorTest() {
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
  matrix->fillScreen(0);
  matrix->drawFastHLine(0, 0, 64, color(30, 150, 220));
  drawTextFit("PAIR", 2, 3, color(40, 190, 230), 24);
  const String code = setupCode.length() > 0 ? setupCode : pairingCode;
  drawTextFit(code.length() > 0 ? code : "------", 8, 16, color(255, 220, 80), 54);
  presentFrame();
}

const char* pixelGlyph(char value) {
  switch (toupper(value)) {
    case '0': return "111101101101111";
    case '1': return "010110010010111";
    case '2': return "111001111100111";
    case '3': return "111001111001111";
    case '4': return "101101111001001";
    case '5': return "111100111001111";
    case '6': return "111100111101111";
    case '7': return "111001010010010";
    case '8': return "111101111101111";
    case '9': return "111101111001111";
    case 'A': return "010101111101101";
    case 'B': return "110101110101110";
    case 'C': return "011100100100011";
    case 'D': return "110101101101110";
    case 'E': return "111100110100111";
    case 'F': return "111100110100100";
    case 'G': return "011100101101011";
    case 'H': return "101101111101101";
    case 'I': return "111010010010111";
    case 'J': return "001001001101010";
    case 'K': return "101110100110101";
    case 'L': return "100100100100111";
    case 'M': return "101111101101101";
    case 'N': return "101111111111101";
    case 'O': return "010101101101010";
    case 'P': return "110101110100100";
    case 'Q': return "010101101111011";
    case 'R': return "110101110101101";
    case 'S': return "011100010001110";
    case 'T': return "111010010010010";
    case 'U': return "101101101101011";
    case 'V': return "101101101101010";
    case 'W': return "101101101111101";
    case 'X': return "101101010101101";
    case 'Y': return "101101010010010";
    case 'Z': return "111001010100111";
    case '&': return "010101010101011";
    case '-': return "000000111000000";
    case ':': return "000010000010000";
    case '/': return "001001010100100";
    case '.': return "000000000000010";
    default: return "000000000000000";
  }
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

int16_t compactPixelTextWidth(const String& value, uint8_t scale) {
  if (value.length() == 0) return 0;
  return static_cast<int16_t>((value.length() - 1) * (3 * scale + 1) + 3 * scale);
}

int16_t centeredPixelX(int16_t width) {
  // Match the large ticker's rounded half-pixel placement on odd-width text.
  return (64 - width + 1) / 2;
}

void drawCompactPixelText(const String& value, int16_t x, int16_t y, uint16_t foreground, uint8_t scale = 1) {
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
    cursor += 3 * scale + 1;
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

void drawPixelTextRight(const String& value, int16_t right, int16_t y, uint16_t foreground, uint8_t scale, int16_t left) {
  String clipped = value;
  const int16_t width = right - left;
  const size_t maximumCharacters = width > 0 ? static_cast<size_t>(width / (4 * scale)) : 0;
  if (clipped.length() > maximumCharacters) {
    clipped.remove(maximumCharacters);
  }
  const int16_t x = right - static_cast<int16_t>(clipped.length() * 4 * scale);
  drawPixelText(clipped, x, y, foreground, scale);
}

uint16_t teamColor(JsonVariantConst value, uint16_t fallback) {
  String raw = value | "";
  raw.trim();
  if (raw.startsWith("#")) raw.remove(0, 1);
  if (raw.length() != 6) return fallback;
  const uint32_t rgb = strtoul(raw.c_str(), nullptr, 16);
  return color((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF);
}
// Owns pixel primitives, status panels, geometry helpers, and page timing helpers.

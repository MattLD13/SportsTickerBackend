#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

String fallbackSportsLogoUrl(JsonObjectConst game, const String& abbreviation);
String derivedSportsLogoUrl(JsonObjectConst game, const char* field, const String& abbreviation);
String miniLogoOverrideUrl(JsonObjectConst game, const String& abbreviation);
String sportsLogoUrl(JsonObjectConst game, const char* field, const String& abbreviation);

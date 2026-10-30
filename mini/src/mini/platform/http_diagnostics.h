#pragma once

#include <WiFiClientSecure.h>

void logSecureHttpError(const char* operation, int status, WiFiClientSecure& client);

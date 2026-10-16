#include "http_diagnostics.h"
#include <HTTPClient.h>

void logSecureHttpError(const char* operation, int status, WiFiClientSecure& client) {
  if (status >= 0) return;
  char tlsError[96] = {};
  const int tlsStatus = client.lastError(tlsError, sizeof(tlsError));
  Serial.printf("%s failed: %s", operation, HTTPClient::errorToString(status).c_str());
  if (tlsStatus != 0) Serial.printf(" TLS %d %s", tlsStatus, tlsError);
  Serial.println();
}

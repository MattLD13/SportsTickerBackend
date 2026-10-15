#pragma once

#include <WiFiClientSecure.h>

extern const char miniTrustStore[] asm("_binary_certs_backend_pem_start");

inline void configureTls(WiFiClientSecure& client) {
  client.setCACert(miniTrustStore);
}

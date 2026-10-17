#pragma once

#include <WiFiClientSecure.h>
#include "deadline_client.h"

// Own socket teardown before the Arduino base destructor runs.
class TlsTransport : public WiFiClientSecure {
 public:
  TlsTransport() = default;
  TlsTransport(const TlsTransport&) = delete;
  TlsTransport& operator=(const TlsTransport&) = delete;
  ~TlsTransport() override { stop(); }
  void stop() override {
    stop_ssl_socket(sslclient, _CA_cert, _cert, _private_key);
    sslclient->socket = -1;
    _connected = false;
    _peek = -1;
  }
};

inline uint32_t tlsClockMs() { return millis(); }
using TlsClient = DeadlineClient<TlsTransport, tlsClockMs>;

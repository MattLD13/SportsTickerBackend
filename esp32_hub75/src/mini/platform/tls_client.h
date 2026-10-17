#pragma once

#include <WiFiClientSecure.h>

// Own socket teardown before the Arduino base destructor runs.
class TlsClient : public WiFiClientSecure {
 public:
  TlsClient() = default;
  TlsClient(const TlsClient&) = delete;
  TlsClient& operator=(const TlsClient&) = delete;
  ~TlsClient() override { stop(); }
  void stop() override {
    stop_ssl_socket(sslclient, _CA_cert, _cert, _private_key);
    sslclient->socket = -1;
    _connected = false;
    _peek = -1;
  }
};

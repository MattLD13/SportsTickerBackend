#pragma once

#include <WiFiClientSecure.h>
#include "tls_client.h"
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "response_stream.h"
#include "../protocol/payload_reader.h"
#include "../protocol/dns_answer.h"

extern const char miniTrustStore[] asm("_binary_certs_backend_pem_start");

inline void configureTls(WiFiClientSecure& client) {
  client.setCACert(miniTrustStore);
}

// Bootstrap the resolver with its published address and verified TLS hostname.
class ResolverTlsClient : public TlsClient {
 public:
  using WiFiClientSecure::connect;
  int connect(const char* host, uint16_t port) override {
    if (strcmp(host, "cloudflare-dns.com") != 0 || port != 443) return 0;
    return WiFiClientSecure::connect(IPAddress(1, 1, 1, 1), port, host, miniTrustStore, nullptr, nullptr);
  }
  int connect(const char* host, uint16_t port, int32_t timeout) override {
    _timeout = timeout;
    return connect(host, port);
  }
};

inline bool resolveBackendAddress(const String& requestedHost, IPAddress& address) {
  struct Cache { String host; IPAddress address; uint32_t savedMs = 0, ttlMs = 0; };
  static Cache cache;
  String host = requestedHost;
  host.toLowerCase();
  if (host.length() == 0 || host.length() > 253) return false;
  for (size_t index = 0; index < host.length(); ++index) {
    const char ch = host[index];
    if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '.' || ch == '-')) return false;
  }
  if (cache.host == host && dnsCacheFresh(cache.savedMs, cache.ttlMs, millis())) { address = cache.address; return true; }
  ResolverTlsClient client;
  configureTls(client);
  client.setHandshakeTimeout(8);
  HTTPClient http;
  http.setReuse(false);
  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  if (!http.begin(client, "https://cloudflare-dns.com/dns-query?name=" + host + "&type=A")) return false;
  http.addHeader("accept", "application/dns-json");
  const int status = http.GET();
  ResponseStream response;
  const int transferred = status == HTTP_CODE_OK ? http.writeToStream(&response) : -1;
  http.end();
  if (transferred < 0 || response.body.failed() || static_cast<size_t>(transferred) != response.body.size()) {
    char detail[128] = {};
    const int tlsStatus = client.lastError(detail, sizeof(detail));
    Serial.printf("HTTPS DNS failed status=%d transfer=%d tls=%d %s\n", status, transferred, tlsStatus, detail);
    return false;
  }
  JsonDocument document;
  PayloadReader reader(response.body.data(), response.body.size());
  if (deserializeJson(document, reader)) return false;
  const DnsAnswer answer = readDnsAnswer(document.as<JsonObjectConst>(), host.c_str());
  if (!answer.valid) return false;
  address = IPAddress(answer.address[0], answer.address[1], answer.address[2], answer.address[3]);
  cache.host = host; cache.address = address; cache.savedMs = millis(); cache.ttlMs = answer.ttlSeconds * 1000;
  Serial.printf("HTTPS DNS ready host=%s address=%s ttl_seconds=%lu\n", host.c_str(), address.toString().c_str(), static_cast<unsigned long>(answer.ttlSeconds));
  return true;
}

// Keep SNI and certificate hostname checks when using the resolved address.
class BackendTlsClient : public TlsClient {
  bool resolved_ = false;
  String address_;
  uint32_t connections_ = 0;
 public:
  uint32_t connectionAttempts() const { return connections_; }
  bool nameResolved() const { return resolved_; }
  const String& resolvedAddress() const { return address_; }
  using WiFiClientSecure::connect;
  int connect(const char* host, uint16_t port) override {
    stop();
    ++connections_;
    IPAddress address;
    resolved_ = resolveBackendAddress(host, address);
    address_ = resolved_ ? address.toString() : String();
    if (!resolved_) return 0;
    return WiFiClientSecure::connect(address, port, host, _CA_cert, _cert, _private_key);
  }
  int connect(const char* host, uint16_t port, int32_t timeout) override {
    _timeout = timeout;
    return connect(host, port);
  }
};

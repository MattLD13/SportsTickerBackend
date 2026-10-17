#pragma once

#include "network.h"
#include "../platform/tls.h"

// The network worker owns one reusable backend connection under the shared gate.
class BackendHttpSession {
 public:
  explicit BackendHttpSession(NetworkGate& gate);
  void execute(NetworkJob& job);
  void close();

 private:
  static void releaseIdle(void* owner);
  BackendTlsClient client_;
  HTTPClient http_;
};

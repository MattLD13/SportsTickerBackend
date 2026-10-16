#pragma once

#include "../platform/response_stream.h"

enum class NetworkKind { Registration, Data, Heartbeat, FirmwareAck };

// The display task transfers ownership through two bounded queues.
struct NetworkJob {
  NetworkKind kind;
  String url, request, identity, command;
  ResponseStream response;
  int status = 0, expectedBytes = -1, transferredBytes = 0;
  String contentType, contentEncoding;
  String errorStage, resolvedAddress;
  uint32_t durationMs = 0;
  explicit NetworkJob(NetworkKind value) : kind(value) {}
  bool complete() const {
    return transferredBytes >= 0 && !response.body.failed() &&
           static_cast<size_t>(transferredBytes) == response.body.size() &&
           (expectedBytes < 0 || static_cast<size_t>(expectedBytes) == response.body.size());
  }
};

bool networkAvailable();
bool queueNetworkJob(NetworkJob* job);
void setupNetworkWorker();
void pollNetworkResults();

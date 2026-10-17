#pragma once

#include "../platform/response_stream.h"
#include "../platform/network_gate.h"
#include "../platform/transfer_deadline.h"
#include <freertos/queue.h>

enum class NetworkKind { Registration, DevicePoll, FirmwareAck };

// The display task transfers ownership through two bounded queues.
struct NetworkJob {
  NetworkKind kind;
  String url, request, identity, command;
  ResponseStream response;
  int status = 0, expectedBytes = -1, transferredBytes = 0;
  String contentType, contentEncoding;
  String errorStage, resolvedAddress;
  uint32_t durationMs = 0;
  uint32_t gateWaitMs = 0, headersMs = 0, bodyMs = 0;
  bool expired = false;
  uint32_t budgetMs = TransferDeadline::DefaultBudgetMs;
  explicit NetworkJob(NetworkKind value) : kind(value) {}
  bool complete() const {
    return !expired && transferredBytes >= 0 && !response.body.failed() &&
           static_cast<size_t>(transferredBytes) == response.body.size() &&
           (expectedBytes < 0 || static_cast<size_t>(expectedBytes) == response.body.size());
  }
};

// The caller owns jobs before enqueue and after takeResult.
// enqueue consumes each non-null job, including rejected jobs.
// Instances must outlive their background tasks. Queue methods run on the display task.
class NetworkWorker {
 public:
  explicit NetworkWorker(NetworkGate& gate) : gate_(gate) {}
  NetworkWorker(const NetworkWorker&) = delete;
  NetworkWorker& operator=(const NetworkWorker&) = delete;
  bool begin();
  bool available() const;
  bool enqueue(NetworkJob* job);
  NetworkJob* takeResult();

 private:
  static void taskEntry(void* context);
  void run();
  void execute(NetworkJob& job);
  NetworkGate& gate_;
  QueueHandle_t requests_ = nullptr;
  QueueHandle_t results_ = nullptr;
  bool pending_ = false;
};

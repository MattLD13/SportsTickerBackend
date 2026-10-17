#pragma once

#include "../platform/response_stream.h"
#include "../platform/network_gate.h"
#include "../platform/transfer_deadline.h"
#include <freertos/queue.h>

class BackendHttpSession;

struct AssetTransfer {
  int status = 0;
  uint32_t durationMs = 0, heapBefore = 0, heapDuring = 0, largestDuring = 0;
  bool reused = false;
};

enum class NetworkKind { Registration, DevicePoll, FirmwareResult, AuthCheck, AssetGet };

// Main jobs return through the result queue. Asset jobs signal their waiting owner.
struct NetworkJob {
  NetworkKind kind;
  String url, request, identity, command, deviceToken;
  ResponseStream response;
  int status = 0, expectedBytes = -1, transferredBytes = 0;
  String contentType, contentEncoding;
  String errorStage, resolvedAddress;
  uint32_t durationMs = 0;
  uint32_t gateWaitMs = 0, headersMs = 0, bodyMs = 0;
  SemaphoreHandle_t completion = nullptr;
  uint32_t heapBefore = 0, heapDuring = 0, largestDuring = 0;
  bool expired = false;
  bool reusedConnection = false;
  bool requireFreshConnection = false;
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
// Instances must outlive their tasks. The display task owns enqueue and takeResult.
// One asset task uses fetchAsset and retains its job until completion.
class NetworkWorker {
 public:
  explicit NetworkWorker(NetworkGate& gate, const String& deviceToken) : gate_(gate), deviceToken_(deviceToken) {}
  NetworkWorker(const NetworkWorker&) = delete;
  NetworkWorker& operator=(const NetworkWorker&) = delete;
  bool begin();
  bool available() const;
  bool enqueue(NetworkJob* job);
  NetworkJob* takeResult();
  bool fetchAsset(const String& url, uint8_t* bytes, size_t expectedBytes, AssetTransfer& transfer);

 private:
  static void taskEntry(void* context);
  void run();
  void execute(NetworkJob& job, BackendHttpSession& session);
  NetworkGate& gate_;
  const String& deviceToken_;
  QueueHandle_t requests_ = nullptr;
  QueueHandle_t results_ = nullptr;
  bool pending_ = false;
};

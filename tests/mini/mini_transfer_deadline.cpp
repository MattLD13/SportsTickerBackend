#include "transfer_deadline.h"
#include "deadline_client.h"
#include <cassert>
#include <iostream>
#include <cstring>
#include <algorithm>

uint32_t clockMs = 0;
uint32_t testClock() { return clockMs; }
void waitForInput() { ++clockMs; }
struct StalledTransport {
  bool open = true;
  unsigned stops = 0, singleReads = 0;
  uint32_t readTimeout = 8000;
  uint32_t getTimeout() const { return readTimeout; }
  virtual ~StalledTransport() = default;
  virtual uint8_t connected() { return open; }
  virtual int available() { return 0; }
  virtual int read() { ++singleReads; return -1; }
  virtual int read(uint8_t*, size_t) { return -1; }
  virtual size_t readBytes(char*, size_t) = 0;
  virtual size_t readBytes(uint8_t*, size_t) = 0;
  virtual size_t write(uint8_t) { return 1; }
  virtual size_t write(const uint8_t*, size_t count) { return count; }
  virtual void stop() { open = false; ++stops; }
};

struct BufferedTransport : StalledTransport {
  using StalledTransport::read;
  const char* content = "ABCDEFGHIJKL";
  size_t position = 0, bulkReads = 0;
  int available() override { return std::min<size_t>(4, 12 - position); }
  int read(uint8_t* bytes, size_t count) override {
    ++bulkReads;
    const size_t received = std::min<size_t>(count, 12 - position);
    std::memcpy(bytes, content + position, received);
    position += received;
    if (position == 12) open = false;
    return received;
  }
};

int main() {
  TransferDeadline deadline;
  deadline.start(1000, 20000);
  for (uint32_t now = 1000; now < 21000; ++now) assert(!deadline.expired(now));
  assert(deadline.expired(21000));
  assert(deadline.expired(300000));
  deadline.start(0xfffffff0u, 20000);
  assert(!deadline.expired(0xfffffff0u + 19999u));
  assert(deadline.expired(0xfffffff0u + 20000u));
  deadline.start(50, 300000);
  assert(!deadline.expired(300049));
  assert(deadline.expired(300050));
  clockMs = 0;
  DeadlineClient<StalledTransport, testClock, waitForInput> client;
  StalledTransport& stream = client;
  while (stream.connected()) {
    assert(stream.available() == 0);
    clockMs += 1;
    assert(clockMs <= 20000);
  }
  assert(client.deadlineExpired() && client.stops == 1);
  uint8_t byte = 0;
  assert(stream.read() == -1 && stream.read(&byte, 1) == -1);
  assert(stream.write(&byte, 1) == 0 && stream.write(byte) == 0);
  assert(client.stops == 1);
  clockMs = 0;
  DeadlineClient<BufferedTransport, testClock, waitForInput> buffered;
  BufferedTransport& bufferedStream = buffered;
  char bytes[20] = {};
  assert(bufferedStream.readBytes(bytes, sizeof(bytes)) == 12);
  assert(std::memcmp(bytes, "ABCDEFGHIJKL", 12) == 0);
  assert(buffered.bulkReads == 3 && buffered.singleReads == 0);
  DeadlineClient<StalledTransport, testClock, waitForInput> bounded;
  bounded.setTransferBudget(10);
  bounded.readTimeout = 100;
  assert(bounded.readBytes(reinterpret_cast<uint8_t*>(bytes), 1) == 0);
  assert(bounded.deadlineExpired() && bounded.stops == 1 && clockMs == 10);
  clockMs = 0;
  DeadlineClient<StalledTransport, testClock, waitForInput> idle;
  idle.readTimeout = 3;
  assert(idle.readBytes(bytes, 1) == 0 && clockMs == 3 && !idle.deadlineExpired());
  clockMs = 0xfffffff0u;
  DeadlineClient<StalledTransport, testClock, waitForInput> wrapped;
  wrapped.setTransferBudget(20);
  assert(wrapped.readBytes(bytes, 1) == 0 && wrapped.deadlineExpired());
  std::cout << "TLS transfer deadlines bound stalled reads and retain the OTA budget across timer rollover\n";
}

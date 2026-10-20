// Software-only prepared DevKit programmer bridge. NOT physically verified.
// No camera power, IO0, EN or reset GPIO is configured by this project.
#include <Arduino.h>
#include <atomic>
namespace {
constexpr uint32_t BAUD = 115200, HOST_IDLE_MS = 30000, SESSION_MS = 900000;
enum Mode { IDLE, RAW, LOCKED };
Mode mode = IDLE;
std::atomic<bool> rxFault{false};
uint32_t startedAt = 0, hostSeenAt = 0;
String commandLine;
bool overflow = false;
const char* stopReason = "none";
struct Pending {
  uint8_t bytes[256];
  size_t offset = 0, length = 0;
  void clear() { offset = length = 0; }
};
Pending toCamera, toHost;

void stopBridge(const char* reason) {
  if (mode == RAW) Serial2.end();
  pinMode(16, INPUT); pinMode(17, INPUT);
  mode = LOCKED; stopReason = reason;
  toCamera.clear(); toHost.clear(); commandLine = ""; overflow = false;
  // No unsolicited marker: it would contaminate the binary stream.
  while (Serial.available()) Serial.read();
}
void status() {
  Serial.print("{\"bridge\":1,\"firmware\":\"sentinel_uart_programmer\",\"state\":\"");
  Serial.print(mode == IDLE ? "idle" : mode == LOCKED ? "locked" : "raw");
  Serial.print("\",\"baud\":115200,\"rx_pin\":16,\"tx_pin\":17,\"host_idle_ms\":30000,\"session_ms\":900000,\"reason\":\"");
  Serial.print(stopReason);
  Serial.println("\"}");
  Serial.flush(); // Only small control replies, never in binary forwarding.
}
void control(const String& line) {
  if (line == "BRIDGE.STATUS") { status(); return; }
  if (mode == IDLE && line == "BRIDGE.ARM POWER_VERIFIED BOOT_VERIFIED") {
    rxFault.store(false);
    Serial2.setRxBufferSize(4096);
    Serial2.begin(BAUD, SERIAL_8N1, 16, 17);
    Serial2.onReceiveError([](hardwareSerial_error_t) { rxFault.store(true); });
    mode = RAW; startedAt = hostSeenAt = millis();
    status(); // Raw bytes start only after this complete reply.
    return;
  }
  Serial.println("{\"bridge\":1,\"error\":\"not_allowed\"}");
}
void pump(HardwareSerial& from, HardwareSerial& to, Pending& pending, bool hostSide) {
  if (pending.offset == pending.length) {
    pending.clear();
    while (from.available() && pending.length < sizeof(pending.bytes)) {
      int value = from.read();
      if (value < 0) break;
      pending.bytes[pending.length++] = static_cast<uint8_t>(value);
      if (hostSide) hostSeenAt = millis();
    }
  }
  if (pending.offset < pending.length) {
    int available = to.availableForWrite();
    if (available > 0) {
      size_t remaining = pending.length - pending.offset;
      size_t count = remaining < static_cast<size_t>(available) ? remaining : static_cast<size_t>(available);
      pending.offset += to.write(pending.bytes + pending.offset, count);
    }
  }
}
}
void setup() {
  pinMode(16, INPUT); pinMode(17, INPUT);
  Serial.setRxBufferSize(4096);
  Serial.begin(BAUD, SERIAL_8N1);
  Serial.onReceiveError([](hardwareSerial_error_t) { rxFault.store(true); });
  commandLine.reserve(96);
}
void loop() {
  if (mode == RAW) {
    const uint32_t now = millis();
    if (rxFault.load()) stopBridge("uart_rx_error");
    else if (uint32_t(now - startedAt) >= SESSION_MS) stopBridge("session_expired");
    else if (uint32_t(now - hostSeenAt) >= HOST_IDLE_MS) stopBridge("host_silent");
    else {
      // Every byte is opaque, including NUL, SLIP escaping and control-looking text.
      pump(Serial, Serial2, toCamera, true);
      pump(Serial2, Serial, toHost, false);
    }
  } else {
    // Locked can report status but cannot re-arm until a DevKit reset.
    for (size_t budget = 0; budget < 128 && Serial.available(); ++budget) {
      char c = Serial.read();
      if (c == '\n') {
        if (!overflow) control(commandLine);
        commandLine = ""; overflow = false;
        // Never parse remaining packet bytes after entering raw mode.
        if (mode == RAW) break;
      } else if (c != '\r') {
        if (!overflow && commandLine.length() < 95) commandLine += c;
        else overflow = true;
      }
    }
  }
  delay(1);
}

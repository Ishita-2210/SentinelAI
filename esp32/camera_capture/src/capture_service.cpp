// Driver calls are compiled, but reference main never initializes a sensor.
#include "capture_service.h"
#include <esp_timer.h>
#include <esp_system.h>
#include <esp_log.h>
#include <algorithm>
#include <cstring>
namespace {
constexpr size_t MAX_JPEG = 128 * 1024;
struct __attribute__((packed)) Header {
  char magic[4]; uint8_t version, kind; uint16_t flags;
  uint32_t session, sequence; uint64_t capture; uint32_t length, crc;
};
static_assert(sizeof(Header) == 32, "SNC1 header size");
uint32_t updateCRC(uint32_t crc, const uint8_t* bytes, size_t count) {
  while (count--) {
    crc ^= *bytes++;
    for (unsigned i=0;i<8;++i) crc = (crc >> 1) ^ (0xEDB88320u & (0u-(crc & 1u)));
  }
  return crc;
}
bool writeBounded(HardwareSerial& uart, const uint8_t* data, size_t length, uint32_t started) {
  while (length) {
    if (uint32_t(millis()-started) >= 13000) return false;
    int available = uart.availableForWrite();
    if (available <= 0) { delay(1); continue; }
    size_t chunk = std::min(length, std::min(size_t(available), size_t(256)));
    size_t written = uart.write(data, chunk);
    if (!written || written > chunk) return false;
    data += written; length -= written;
    delay(0);
  }
  return true;
}
}

bool CaptureService::packet(uint8_t kind, const uint8_t* data, size_t length, uint64_t captured) {
  if (!uart || !data || !length || length > (kind == 1 ? 2048u : MAX_JPEG)) return false;
  Header header{{'S','N','C','1'}, 1, kind, 0, session, sequence, captured, uint32_t(length), 0};
  uint32_t crc = updateCRC(0xFFFFFFFFu, reinterpret_cast<const uint8_t*>(&header), 28);
  header.crc = ~updateCRC(crc, data, length);
  uint32_t started = millis();
  return writeBounded(*uart, reinterpret_cast<const uint8_t*>(&header), sizeof(header), started)
      && writeBounded(*uart, data, length, started);
}

bool CaptureService::status(const char* capture, bool pong, uint32_t nonce) {
  char payload[400], suffix[48] = {0};
  if (pong) snprintf(suffix, sizeof(suffix), ",\"pong_nonce\":%lu", (unsigned long)nonce);
  int length = snprintf(payload, sizeof(payload),
    "{\"role\":\"camera_capture\",\"device_id\":\"%s\",\"init_status\":\"%s\","
    "\"sensor_pid\":%u,\"capture_status\":\"%s\",\"error\":\"%s\"%s}",
    device, ready ? "ready" : "error", pid, capture, error, suffix);
  lastStatus = millis();
  return length > 0 && size_t(length) < sizeof(payload) && packet(1, reinterpret_cast<uint8_t*>(payload), length, esp_timer_get_time());
}

bool CaptureService::begin(const camera_config_t& config, HardwareSerial& serial) {
  uart = &serial;
  // Camera-driver/background logs must not interleave binary UART0 packets.
  esp_log_level_set("*", ESP_LOG_NONE);
  uart->setDebugOutput(false);
  snprintf(device, sizeof(device), "sentinel-cam-%016llX", (unsigned long long)ESP.getEfuseMac());
  session = esp_random();
  if (config.pixel_format != PIXFORMAT_JPEG || config.fb_count != 1) {
    snprintf(error, sizeof(error), "JPEG and one framebuffer required");status("not_started");return false;
  }
  const int pins[] = {config.pin_pwdn,config.pin_reset,config.pin_xclk,config.pin_sccb_sda,config.pin_sccb_scl,
    config.pin_d0,config.pin_d1,config.pin_d2,config.pin_d3,config.pin_d4,config.pin_d5,config.pin_d6,config.pin_d7,
    config.pin_vsync,config.pin_href,config.pin_pclk};
  for (int pin : pins) if (pin == 1 || pin == 3) {
    snprintf(error,sizeof(error),"Camera map conflicts with UART0");status("not_started");return false;
  }
  esp_err_t code = esp_camera_init(&config);
  if (code != ESP_OK) {
    snprintf(error,sizeof(error),"esp_camera_init:%ld", (long)code);status("not_started");return false;
  }
  sensor_t* sensor = esp_camera_sensor_get();
  if (!sensor || !sensor->id.PID) {
    snprintf(error,sizeof(error),"Sensor PID unavailable");esp_camera_deinit();status("not_started");return false;
  }
  pid = sensor->id.PID;ready = true;
  return status("not_started");
}

void CaptureService::controls() {
  unsigned budget = 128;
  while (uart->available() && budget--) {
    char c = uart->read();
    if (c == '\n') {
      if (!overflow && inputLength > 5 && !strncmp(input,"PING ",5)) {
        uint64_t value = 0;bool valid = true;
        for (size_t i=5;i<inputLength;++i) {
          if (input[i]<'0' || input[i]>'9') { valid = false;break; }
          value = value*10+(input[i]-'0');
          if (value>0xFFFFFFFFu) { valid = false;break; }
        }
        if (valid) status("not_started",true,uint32_t(value));
      }
      inputLength = 0;overflow = false;
    } else if (c != '\r') {
      if (inputLength < sizeof(input)-1 && !overflow) input[inputLength++] = c;
      else overflow = true;
    }
  }
}

void CaptureService::tick() {
  if (!uart) return;
  controls();
  if (!ready) { if (uint32_t(millis()-lastStatus)>=2000) status("not_started");delay(1);return; }
  // Cadence is bounded; actual JPEG wire time is additional. No FPS promise.
  if (uint32_t(millis()-lastCapture)<1000) { delay(1);return; }
  lastCapture = millis();
  camera_fb_t* frame = esp_camera_fb_get();
  if (!frame) { snprintf(error,sizeof(error),"Frame acquisition failed");status("error");return; }
  ++sequence;
  uint64_t captured = uint64_t(frame->timestamp.tv_sec)*1000000u + frame->timestamp.tv_usec;
  error[0] = 0;
  bool valid = frame->format == PIXFORMAT_JPEG && frame->len > 0 && frame->len <= MAX_JPEG
      && frame->width > 0 && frame->height > 0 && frame->width*frame->height <= 1024*1024;
  if (!valid) snprintf(error,sizeof(error),"Frame format or size exceeds budget");
  bool sent = false;
  if (valid && status("ready")) sent = packet(2, frame->buf, frame->len, captured);
  esp_camera_fb_return(frame); // Always release the sole frame buffer.
  if (!valid || !sent) {
    if (valid) snprintf(error,sizeof(error),"Bounded UART transfer failed");
    status("error");
  }
}

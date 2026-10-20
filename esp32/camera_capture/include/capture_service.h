#pragma once
#include <Arduino.h>
#include <esp_camera.h>

class CaptureService {
 public:
  bool begin(const camera_config_t& config, HardwareSerial& uart);
  void tick();
 private:
  HardwareSerial* uart = nullptr;
  bool ready = false;
  uint16_t pid = 0;
  uint32_t session = 0, sequence = 0, lastCapture = 0, lastStatus = 0;
  char device[40] = {0}, error[80] = {0}, input[64] = {0};
  size_t inputLength = 0;
  bool overflow = false;
  bool packet(uint8_t kind, const uint8_t* data, size_t length, uint64_t captured);
  bool status(const char* capture, bool pong = false, uint32_t nonce = 0);
  void controls();
};

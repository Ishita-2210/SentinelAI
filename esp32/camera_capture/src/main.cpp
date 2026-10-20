#include <Arduino.h>
#include "capture_service.h"
#if defined(SENTINEL_REFERENCE_ONLY)
// Deliberately inert reference image: never initialize Serial, camera or GPIO.
void setup() {}
void loop() { delay(100); }
#else
#include "verified_camera_config.h"
#if SENTINEL_POWER_VERIFIED != 1 || SENTINEL_PINMAP_VERIFIED != 1 || SENTINEL_PROGRAMMING_VERIFIED != 1 || SENTINEL_UART0_VERIFIED != 1
#error "Physical board/power/programming/UART verification is required"
#endif
CaptureService camera;
void setup() { Serial.begin(115200); camera.begin(verifiedCameraConfig(), Serial); }
void loop() { camera.tick(); }
#endif

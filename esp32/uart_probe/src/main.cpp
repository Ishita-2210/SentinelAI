// DevKit-only probe. No JPEG or transparent programming bridge.
// GPIO16/17 stay inputs until a deliberate power-verified host command.
#include <Arduino.h>
String deviceId, hostLine, cameraLine, lastAlert = "";
bool enabled = false, pending = false, hostOverflow = false, cameraOverflow = false;
uint32_t sequence = 0, sentAt = 0, lastTelemetry = 0, lastCameraCommand = 0;
const char* events[] = {"PERSON_ENTERED","PERSON_EXITED","ZONE_CHANGED","LOITERING","RUNNING","UNATTENDED_OBJECT"};
void message(const char* type, const String& fields) {
  Serial.print("{\"protocol\":1,\"type\":\""); Serial.print(type);
  Serial.print("\",\"device_id\":\""); Serial.print(deviceId);
  Serial.print("\""); Serial.print(fields); Serial.println("}");
}
void disableCamera() {
  if (enabled) Serial2.end();
  pinMode(16, INPUT); pinMode(17, INPUT);
  enabled = false; pending = false; cameraLine = ""; cameraOverflow = false;
}
void setup() {
  pinMode(16, INPUT); pinMode(17, INPUT);
  Serial.begin(115200);
  char id[17]; snprintf(id, sizeof(id), "%016llX", (unsigned long long)ESP.getEfuseMac());
  deviceId = String("sentinel-") + id;
  hostLine.reserve(512); cameraLine.reserve(64);
}
void command(const String& line) {
  if (line == "{\"command\":\"ping\"}") {
    message("ack", ",\"command\":\"ping\""); return;
  }
  if (line == "{\"command\":\"camera_uart_disable\"}") {
    disableCamera(); message("ack", ",\"command\":\"camera_uart_disable\""); return;
  }
  if (line == "{\"command\":\"camera_uart_enable\",\"power_verified\":true}") {
    if (!enabled) {
      Serial2.begin(115200, SERIAL_8N1, 16, 17); // RX=16, TX=17 explicitly
      enabled = true; cameraLine = ""; cameraOverflow = false;
    }
    lastCameraCommand = millis();
    message("ack", ",\"command\":\"camera_uart_enable\""); return;
  }
  if (line == "{\"command\":\"camera_ping\"}") {
    if (!enabled) { message("error", ",\"error\":\"camera_uart_disabled\""); return; }
    if (pending) { message("error", ",\"error\":\"camera_ping_busy\""); return; }
    // Discard prior input; only a fresh matching reply can acknowledge this probe.
    while (Serial2.available()) Serial2.read();
    cameraLine = ""; cameraOverflow = false;
    sequence = esp_random(); pending = true; sentAt = millis(); lastCameraCommand = sentAt;
    message("camera_ping_sent", String(",\"sequence\":") + sequence);
    Serial2.print("PING "); Serial2.println(sequence); return;
  }
  for (const char* event : events) {
    if (line == String("{\"command\":\"alert\",\"event_type\":\"") + event + "\"}") {
      lastAlert = event;
      message("ack", String(",\"command\":\"alert\",\"event_type\":\"") + event + "\""); return;
    }
  }
  message("error", ",\"error\":\"unsupported_command\"");
}
void loop() {
  if (enabled && uint32_t(millis() - lastCameraCommand) >= 15000) {
    disableCamera();
    message("error", ",\"error\":\"camera_uart_idle_disabled\"");
  }
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (hostOverflow) message("error", ",\"error\":\"message_too_long\"");
      else command(hostLine);
      hostLine = ""; hostOverflow = false;
    } else if (c != '\r') {
      if (hostLine.length() < 511 && !hostOverflow) hostLine += c;
      else hostOverflow = true;
    }
  }
  if (pending && uint32_t(millis() - sentAt) >= 2000) {
    pending = false;
    message("error", String(",\"error\":\"camera_ping_timeout\",\"sequence\":") + sequence);
  }
  while (enabled && Serial2.available()) {
    char c = Serial2.read();
    if (c == '\n') {
      if (!cameraOverflow && pending && cameraLine == String("PONG ") + sequence) {
        pending = false;
        message("ack", String(",\"command\":\"camera_ping\",\"sequence\":") + sequence +
          ",\"transport\":\"uart2\",\"camera_reply\":\"PONG\"");
      }
      cameraLine = ""; cameraOverflow = false;
    } else if (c != '\r') {
      if (cameraLine.length() < 63 && !cameraOverflow) cameraLine += c;
      else cameraOverflow = true;
    }
  }
  if (uint32_t(millis() - lastTelemetry) >= 1000) {
    lastTelemetry = millis();
    message("telemetry", String(",\"firmware\":\"uart_probe\",\"uptime_ms\":") + millis() +
      ",\"free_heap\":" + ESP.getFreeHeap() + ",\"last_alert\":\"" + lastAlert +
      "\",\"camera_uart_enabled\":" + (enabled ? "true" : "false"));
  }
  delay(2);
}

// ESP32-WROOM-32 development board, USB-UART 115200. No GPIO peripherals.
// Alerts update memory and receive acknowledgements; no physical actuation.
#include <Arduino.h>
String deviceId, inputLine, lastAlert = "";
unsigned long lastTelemetry = 0;
const char* events[] = {"PERSON_ENTERED","PERSON_EXITED","ZONE_CHANGED","LOITERING","RUNNING","UNATTENDED_OBJECT"};
bool overflow = false;
void message(const char* type, const String& fields) {
  Serial.print("{\"protocol\":1,\"type\":\""); Serial.print(type);
  Serial.print("\",\"device_id\":\""); Serial.print(deviceId);
  Serial.print("\""); Serial.print(fields); Serial.println("}");
}
void setup() {
  Serial.begin(115200);
  char id[17]; snprintf(id, sizeof(id), "%016llX", (unsigned long long)ESP.getEfuseMac());
  deviceId = String("sentinel-") + id;
  inputLine.reserve(512);
}
void processCommand(String line) {
  if (line == "{\"command\":\"ping\"}") {
    message("ack", ",\"command\":\"ping\"");
    return;
  }
  for (const char* event : events) {
    String allowed = String("{\"command\":\"alert\",\"event_type\":\"") + event + "\"}";
    if (line == allowed) {
      lastAlert = event;
      message("ack", String(",\"command\":\"alert\",\"event_type\":\"") + event + "\"");
      return;
    }
  }
  message("error", ",\"error\":\"unsupported_command\"");
}
void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (overflow) message("error", ",\"error\":\"message_too_long\"");
      else processCommand(inputLine);
      inputLine = ""; overflow = false;
    } else if (c != '\r') {
      if (inputLine.length() < 511 && !overflow) inputLine += c;
      else overflow = true;
    }
  }
  unsigned long now = millis();
  if (now - lastTelemetry >= 1000) {
    lastTelemetry = now;
    message("telemetry", String(",\"uptime_ms\":") + now +
      ",\"free_heap\":" + ESP.getFreeHeap() +
      ",\"last_alert\":\"" + lastAlert + "\"");
  }
  delay(2);
}

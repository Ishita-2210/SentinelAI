// UART0 responder only. Board target, supply, programmer and boot controls
// MUST be verified before compiling/flashing. No camera pins or JPEG configured.
// UART0 is reserved for this protocol after boot; do not add console logging.
#include <Arduino.h>
String inputLine;
bool overflow = false;
void setup() { Serial.begin(115200); inputLine.reserve(64); }
void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (!overflow && inputLine.startsWith("PING ")) {
        String nonce = inputLine.substring(5);
        bool valid = nonce.length() > 0 && nonce.length() <= 10;
        for (unsigned int i = 0; i < nonce.length(); ++i)
          if (nonce[i] < '0' || nonce[i] > '9') valid = false;
        if (valid) { Serial.print("PONG "); Serial.println(nonce); }
      }
      inputLine = ""; overflow = false;
    } else if (c != '\r') {
      if (inputLine.length() < 63 && !overflow) inputLine += c;
      else overflow = true;
    }
  }
  delay(2);
}

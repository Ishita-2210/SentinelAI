/*
 * SentinelAI - ESP32-CAM firmware (AI-Thinker module)
 *
 *   MJPEG stream : http://<esp32-ip>:81/stream   -> SENTINEL_CAMERA
 *   Alert action : http://<esp32-ip>/alert?type=UNATTENDED_OBJECT&duration=3
 *                                                -> ESP32_URL=http://<esp32-ip>
 *
 * Alert outputs:
 *   LED    : onboard flash LED (GPIO 4)
 *   Buzzer : active buzzer on GPIO 13
 *
 * Board: "AI Thinker ESP32-CAM" in the Arduino IDE (esp32 board package).
 * Set WIFI_SSID / WIFI_PASSWORD below before flashing.
 *
 * NOTE: this sketch has not been compiled or flashed as part of the repo
 * review. Treat it as a starting point and test on your hardware.
 */

#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>

const char *WIFI_SSID = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// AI-Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

#define LED_PIN 4
#define BUZZER_PIN 13

static const char *STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=sentinelframe";
static const char *STREAM_BOUNDARY = "\r\n--sentinelframe\r\n";
static const char *STREAM_PART =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

httpd_handle_t control_httpd = NULL;
httpd_handle_t stream_httpd = NULL;

// Non-blocking alert timer: loop() switches the outputs off again.
volatile unsigned long alertUntilMs = 0;

// ---------------------------------------------------------------
// /stream  (port 81)
// ---------------------------------------------------------------
static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  char part[64];

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else {
      size_t headerLen = snprintf(part, sizeof(part), STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
      if (res == ESP_OK) res = httpd_resp_send_chunk(req, part, headerLen);
      if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
      esp_camera_fb_return(fb);
    }
    if (res != ESP_OK) break;  // client disconnected
  }
  return res;
}

// ---------------------------------------------------------------
// /alert?type=...&duration=...  (port 80)
// ---------------------------------------------------------------
static esp_err_t alert_handler(httpd_req_t *req) {
  char query[96] = {0};
  char value[16] = {0};
  int duration = 3;

  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
    if (httpd_query_key_value(query, "duration", value, sizeof(value)) == ESP_OK) {
      duration = atoi(value);
    }
  }
  if (duration < 1) duration = 1;
  if (duration > 30) duration = 30;

  digitalWrite(LED_PIN, HIGH);
  digitalWrite(BUZZER_PIN, HIGH);
  alertUntilMs = millis() + (unsigned long)duration * 1000UL;

  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, "OK", HTTPD_RESP_USE_STRLEN);
}

static esp_err_t ping_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, "SentinelAI ESP32", HTTPD_RESP_USE_STRLEN);
}

void startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  httpd_uri_t alertUri = {"/alert", HTTP_GET, alert_handler, NULL};
  httpd_uri_t pingUri = {"/", HTTP_GET, ping_handler, NULL};

  if (httpd_start(&control_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(control_httpd, &alertUri);
    httpd_register_uri_handler(control_httpd, &pingUri);
  }

  config.server_port = 81;
  config.ctrl_port += 1;

  httpd_uri_t streamUri = {"/stream", HTTP_GET, stream_handler, NULL};

  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &streamUri);
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;  // 640x480 is plenty for YOLO11n
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.grab_mode = CAMERA_GRAB_LATEST;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera init failed");
    return;
  }

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  startServers();

  Serial.print("Stream : http://");
  Serial.print(WiFi.localIP());
  Serial.println(":81/stream");
  Serial.print("Alerts : http://");
  Serial.print(WiFi.localIP());
  Serial.println("/alert?type=TEST&duration=2");
}

void loop() {
  if (alertUntilMs != 0 && (long)(millis() - alertUntilMs) >= 0) {
    digitalWrite(LED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    alertUntilMs = 0;
  }
  delay(20);
}

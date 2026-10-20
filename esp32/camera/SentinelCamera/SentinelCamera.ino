// NOT physically verified. Board/sensor/pin mapping is currently unknown.
// This sketch must not be flashed until the exact hardware is identified.
#include <Arduino.h>
#include <WiFi.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#if !__has_include("camera_pins.h")
#error "Missing verified camera_pins.h: identify board, sensor and FPC orientation first."
#else
#include "camera_pins.h"
#endif
#if !__has_include("camera_secrets.h")
#error "Missing local camera_secrets.h; copy the example and configure Wi-Fi privately."
#else
#include "camera_secrets.h"
#endif

httpd_handle_t statusServer = nullptr, streamServer = nullptr;
bool cameraReady = false;
esp_err_t cameraError = ESP_FAIL;

esp_err_t healthHandler(httpd_req_t* request) {
  char body[256];
  sensor_t* sensor = cameraReady ? esp_camera_sensor_get() : nullptr;
  snprintf(body,sizeof(body),
    "{\"device_id\":\"%s\",\"camera_ready\":%s,\"sensor_pid\":%u,\"uptime_ms\":%lu,\"rssi_dbm\":%d,\"camera_error\":%d}",
    WiFi.macAddress().c_str(), cameraReady ? "true" : "false",
    sensor ? sensor->id.PID : 0, millis(), WiFi.RSSI(), (int)cameraError);
  httpd_resp_set_type(request,"application/json");
  return httpd_resp_send(request,body,HTTPD_RESP_USE_STRLEN);
}
esp_err_t unavailable(httpd_req_t* request,const char* message) {
  httpd_resp_set_status(request,"503 Service Unavailable");
  return httpd_resp_send(request,message,HTTPD_RESP_USE_STRLEN);
}
esp_err_t captureHandler(httpd_req_t* request) {
  camera_fb_t* frame = cameraReady ? esp_camera_fb_get() : nullptr;
  if (!frame) return unavailable(request,"Camera frame unavailable");
  if (frame->format != PIXFORMAT_JPEG) {
    esp_camera_fb_return(frame);
    return unavailable(request,"Verified JPEG-capable sensor configuration required");
  }
  httpd_resp_set_type(request,"image/jpeg");
  httpd_resp_set_hdr(request,"Cache-Control","no-store");
  esp_err_t result = httpd_resp_send(request,(const char*)frame->buf,frame->len);
  esp_camera_fb_return(frame);
  return result;
}
esp_err_t streamHandler(httpd_req_t* request) {
  if (!cameraReady) return unavailable(request,"Camera not ready");
  httpd_resp_set_type(request,"multipart/x-mixed-replace;boundary=sentinel");
  httpd_resp_set_hdr(request,"Cache-Control","no-store");
  while (true) {
    camera_fb_t* frame = esp_camera_fb_get();
    if (!frame) return ESP_FAIL;
    if (frame->format != PIXFORMAT_JPEG) {esp_camera_fb_return(frame);return ESP_FAIL;}
    char headers[144];
    int count = snprintf(headers,sizeof(headers),
      "\r\n--sentinel\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\nX-Uptime-Ms: %lu\r\n\r\n",
      (unsigned)frame->len,millis());
    esp_err_t result=httpd_resp_send_chunk(request,headers,count);
    if (result==ESP_OK) result=httpd_resp_send_chunk(request,(const char*)frame->buf,frame->len);
    esp_camera_fb_return(frame);
    if (result!=ESP_OK) return result;
    delay(50);
  }
}
void setup() {
  Serial.begin(115200);
  camera_config_t config = {};
  config.ledc_channel=LEDC_CHANNEL_0;config.ledc_timer=LEDC_TIMER_0;
  config.pin_d0=CAM_D0;config.pin_d1=CAM_D1;config.pin_d2=CAM_D2;config.pin_d3=CAM_D3;
  config.pin_d4=CAM_D4;config.pin_d5=CAM_D5;config.pin_d6=CAM_D6;config.pin_d7=CAM_D7;
  config.pin_xclk=CAM_XCLK;config.pin_pclk=CAM_PCLK;config.pin_vsync=CAM_VSYNC;
  config.pin_href=CAM_HREF;config.pin_sccb_sda=CAM_SIOD;config.pin_sccb_scl=CAM_SIOC;
  config.pin_pwdn=CAM_PWDN;config.pin_reset=CAM_RESET;config.xclk_freq_hz=CAM_XCLK_HZ;
  config.pixel_format=PIXFORMAT_JPEG;config.frame_size=FRAMESIZE_QVGA;
  config.jpeg_quality=12;config.fb_count=1;config.fb_location=CAMERA_FB_IN_DRAM;
  config.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  cameraError=esp_camera_init(&config);cameraReady=cameraError==ESP_OK;
  Serial.printf("Camera init: %s (%d)\n",cameraReady ? "ready" : "error",(int)cameraError);
  WiFi.mode(WIFI_STA);WiFi.setAutoReconnect(true);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  unsigned long start=millis();
  while (WiFi.status()!=WL_CONNECTED && millis()-start<20000) delay(200);
  if (WiFi.status()!=WL_CONNECTED) {Serial.println("Wi-Fi connection failed; restarting");delay(2000);ESP.restart();}
  httpd_config_t serverConfig=HTTPD_DEFAULT_CONFIG();
  serverConfig.server_port=80;
  if (httpd_start(&statusServer,&serverConfig)==ESP_OK) {
    httpd_uri_t health={};health.uri="/health";health.method=HTTP_GET;health.handler=healthHandler;
    httpd_uri_t capture={};capture.uri="/capture";capture.method=HTTP_GET;capture.handler=captureHandler;
    httpd_register_uri_handler(statusServer,&health);httpd_register_uri_handler(statusServer,&capture);
  }
  serverConfig.server_port=81;serverConfig.ctrl_port+=1;
  if (httpd_start(&streamServer,&serverConfig)==ESP_OK) {
    httpd_uri_t stream={};stream.uri="/stream";stream.method=HTTP_GET;stream.handler=streamHandler;
    httpd_register_uri_handler(streamServer,&stream);
  }
  Serial.printf("Health http://%s/health ; stream http://%s:81/stream\n",
                WiFi.localIP().toString().c_str(),WiFi.localIP().toString().c_str());
}
void loop() {delay(1000);}

// Hypothesis test, NOT an established map for the user's carrier.
// Source: Espressif Arduino CameraWebServer CAMERA_MODEL_AI_THINKER.
// Remove CAM IO0-GND before normal boot: this hypothesis uses IO0 as XCLK.
#include <Arduino.h>
#include <esp_camera.h>
#include <esp_timer.h>
#include <esp_system.h>
#include <esp_log.h>

struct __attribute__((packed)) Header {
  char magic[4]; uint8_t version, kind; uint16_t flags;
  uint32_t session, sequence; uint64_t capture; uint32_t length, crc;
};
static_assert(sizeof(Header)==32,"SNC1 header");
uint32_t boot;
uint16_t sensorPID=0;
bool initialized=false;
char device[40];
uint32_t crc32(uint32_t crc,const uint8_t* p,size_t n) {
  while(n--) { crc^=*p++; for(unsigned i=0;i<8;++i)crc=(crc>>1)^(0xEDB88320u&(0u-(crc&1))); }
  return crc;
}
bool writeBytes(const uint8_t* p,size_t n,uint32_t start) {
  while(n) {
    if(uint32_t(millis()-start)>15000)return false;
    int room=Serial.availableForWrite();
    if(room<=0){delay(1);continue;}
    size_t chunk=n<size_t(room)?n:size_t(room);
    if(chunk>256)chunk=256;
    size_t sent=Serial.write(p,chunk);
    if(!sent)return false;
    p+=sent;n-=sent;delay(0);
  }
  return true;
}
bool packet(uint8_t kind,const uint8_t* bytes,size_t n,uint32_t sequence=0) {
  Header h{{'S','N','C','1'},1,kind,0,boot,sequence,uint64_t(esp_timer_get_time()),uint32_t(n),0};
  h.crc=~crc32(crc32(0xFFFFFFFFu,reinterpret_cast<uint8_t*>(&h),28),bytes,n);
  uint32_t start=millis();
  return writeBytes(reinterpret_cast<uint8_t*>(&h),sizeof(h),start)&&writeBytes(bytes,n,start);
}
void status(const char* capture,const char* error="",bool pong=false,uint32_t nonce=0) {
  char text[400],tail[48]={0};
  if(pong)snprintf(tail,sizeof(tail),",\"pong_nonce\":%lu",(unsigned long)nonce);
  int n=snprintf(text,sizeof(text),"{\"role\":\"camera_capture\",\"device_id\":\"%s\",\"init_status\":\"%s\",\"sensor_pid\":%u,\"capture_status\":\"%s\",\"error\":\"%s\"%s}",device,initialized?"ready":"error",sensorPID,capture,error,tail);
  if(n>0&&size_t(n)<sizeof(text))packet(1,reinterpret_cast<uint8_t*>(text),n);
}
void setup() {
  Serial.begin(115200);Serial.setDebugOutput(false);esp_log_level_set("*",ESP_LOG_NONE);
  boot=esp_random();
  snprintf(device,sizeof(device),"sentinel-cam-%016llX",(unsigned long long)ESP.getEfuseMac());
  Serial.println("HYPOTHESIS AI_THINKER; one QVGA JPEG; no WiFi; no flash LED");
  camera_config_t c={};
  c.ledc_channel=LEDC_CHANNEL_0;c.ledc_timer=LEDC_TIMER_0;
  c.pin_pwdn=32;c.pin_reset=-1;c.pin_xclk=0;
  c.pin_sccb_sda=26;c.pin_sccb_scl=27;
  c.pin_d0=5;c.pin_d1=18;c.pin_d2=19;c.pin_d3=21;
  c.pin_d4=36;c.pin_d5=39;c.pin_d6=34;c.pin_d7=35;
  c.pin_vsync=25;c.pin_href=23;c.pin_pclk=22;
  c.xclk_freq_hz=20000000;c.pixel_format=PIXFORMAT_JPEG;
  c.frame_size=FRAMESIZE_QVGA;c.jpeg_quality=12;c.fb_count=1;
  c.fb_location=CAMERA_FB_IN_DRAM;c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  esp_err_t result=esp_camera_init(&c);
  Serial.printf("INIT code=0x%X\n",unsigned(result));
  if(result!=ESP_OK){Serial.flush();status("not_started","esp_camera_init failed");return;}
  sensor_t* sensor=esp_camera_sensor_get();
  sensorPID=sensor?sensor->id.PID:0;
  initialized=sensorPID!=0;
  Serial.printf("SENSOR PID=0x%04X device_id=%s\n",sensorPID,device);Serial.flush();
  if(!initialized){status("not_started","PID missing");return;}
  // Give a manually started receiver time to join, then send ONE image.
  delay(8000);
  camera_fb_t* fb=esp_camera_fb_get();
  if(!fb){status("error","frame acquisition failed");return;}
  bool valid=fb->format==PIXFORMAT_JPEG&&fb->len>=4&&fb->len<=131072&&
      fb->buf[0]==0xFF&&fb->buf[1]==0xD8&&fb->buf[fb->len-2]==0xFF&&fb->buf[fb->len-1]==0xD9;
  if(valid){status("ready");if(!packet(2,fb->buf,fb->len,1))status("error","UART deadline");}
  else status("error","JPEG format or length invalid");
  esp_camera_fb_return(fb);
}
void loop() {
  // A bounded PING responder remains available; never captures a second image.
  static char line[32];static size_t used=0;static bool overflow=false;
  unsigned budget=64;
  while(Serial.available()&&budget--) {
    char ch=Serial.read();
    if(ch=='\n') {
      if(!overflow&&used>5&&!strncmp(line,"PING ",5)) {
        uint64_t n=0;bool valid=true;
        for(size_t i=5;i<used;++i){if(line[i]<'0'||line[i]>'9'){valid=false;break;}n=n*10+line[i]-'0';if(n>0xFFFFFFFFu){valid=false;break;}}
        if(valid)status("diagnostic_complete","",true,uint32_t(n));
      }
      used=0;overflow=false;
    } else if(ch!='\r'){if(used<sizeof(line)&&!overflow)line[used++]=ch;else overflow=true;}
  }
  delay(2);
}

#include <WiFi.h>
#include <WiFiClient.h>
#include "esp_camera.h"
#include <TinyGPSPlus.h>

// -----------------------------
// User configuration
// -----------------------------
const char* WIFI_SSID = "Vuln";
const char* WIFI_PASSWORD = "11111118";

// Backend host reachable from ESP32 on the same Wi-Fi.
// Example: "192.168.1.50" (do not include http://)
const char* BACKEND_HOST = "10.230.143.202";
const uint16_t BACKEND_PORT = 8000;
const char* BACKEND_PATH = "/api/v1/gateway/esp32/telemetry";
const char* HEALTH_PATH = "/docs";

// Must match the vehicle.device_id registered in your backend.
const char* DEVICE_ID = "ESP32_BUS_001";
const char* BUS_PLATE_NUMBER = "AA-ESP-001";
const char* BUS_TYPE = "Anbessa";

// Used by backend to estimate occupancy from people_count.
const int BUS_CAPACITY = 40;

// Send interval in milliseconds.
const unsigned long SEND_INTERVAL_MS = 60000;
const unsigned long HEARTBEAT_INTERVAL_MS = 10000;

// If true, camera telemetry is still posted when GPS is not fresh.
// This prevents image uploads from stalling while waiting for GPS lock.
const bool ALLOW_SEND_WITHOUT_GPS = true;
const float FALLBACK_LAT = 9.032000f;
const float FALLBACK_LON = 38.752000f;

// GPS UART mapping (ESP32-CAM + NEO-6M)
// NEO-6M TX -> ESP32 GPIO14 (GPS_RX_PIN)
// NEO-6M RX -> ESP32 GPIO15 (GPS_TX_PIN)
static const int GPS_RX_PIN = 14;
static const int GPS_TX_PIN = 15;
static const uint32_t GPS_BAUD = 9600;

// AI Thinker ESP32-CAM pin map
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

TinyGPSPlus gps;
HardwareSerial gpsSerial(1);
unsigned long lastSendMs = 0;
unsigned long lastHeartbeatMs = 0;
unsigned long telemetryAttemptCount = 0;
unsigned long telemetrySuccessCount = 0;
bool cameraHealthy = false;
bool lastTelemetryOk = false;
bool hasLastKnownGps = false;
float lastKnownLat = 0.0f;
float lastKnownLon = 0.0f;

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Wi-Fi connected, IP: ");
  Serial.println(WiFi.localIP());
}

bool initCamera() {
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

  if (psramFound()) {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QQVGA;
    config.jpeg_quality = 14;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.print("Camera init failed, error 0x");
    Serial.println((uint32_t)err, HEX);
    return false;
  }

  sensor_t* s = esp_camera_sensor_get();
  if (s != nullptr) {
    s->set_brightness(s, 0);
    s->set_saturation(s, 0);
  }

  return true;
}

bool cameraSelfCheck() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (fb == nullptr) {
    Serial.println("Camera self-check failed: no frame buffer");
    return false;
  }

  bool ok = fb->len > 0;
  if (!ok) {
    Serial.println("Camera self-check failed: empty frame");
  }
  esp_camera_fb_return(fb);
  return ok;
}

void feedGpsParser() {
  while (gpsSerial.available()) {
    gps.encode(gpsSerial.read());
  }
}

bool hasFreshFix() {
  if (!gps.location.isValid()) {
    return false;
  }
  float lat = gps.location.lat();
  float lon = gps.location.lng();
  if (lat == 0.0f && lon == 0.0f) {
    return false;
  }
  return true;
}

bool selectGpsFix(float& lat, float& lon, float& speedKmph, bool& usingFallbackCoords) {
  usingFallbackCoords = false;

  if (hasFreshFix()) {
    lat = gps.location.lat();
    lon = gps.location.lng();
    speedKmph = gps.speed.isValid() ? gps.speed.kmph() : 0.0f;
    hasLastKnownGps = true;
    lastKnownLat = lat;
    lastKnownLon = lon;
    return true;
  }

  if (hasLastKnownGps) {
    lat = lastKnownLat;
    lon = lastKnownLon;
    speedKmph = 0.0f;
    Serial.println("No fresh GPS fix. Sending last known GPS coordinates.");
    return true;
  }

  if (ALLOW_SEND_WITHOUT_GPS) {
    lat = FALLBACK_LAT;
    lon = FALLBACK_LON;
    speedKmph = 0.0f;
    usingFallbackCoords = true;
    Serial.println("No GPS fix yet. Sending fallback coordinates.");
    return true;
  }

  return false;
}

bool pingServerStatus(
  const char* eventName,
  bool gpsValid,
  bool camOk,
  bool telemetryOk,
  float lat,
  float lon,
  float speedKmph
) {
  WiFiClient client;
  if (!client.connect(BACKEND_HOST, BACKEND_PORT)) {
    Serial.println("Server ping failed: cannot connect to backend host");
    return false;
  }

  String path = String(HEALTH_PATH)
    + "?event=" + String(eventName)
    + "&device_id=" + String(DEVICE_ID)
    + "&gps_valid=" + String(gpsValid ? 1 : 0)
    + "&cam_ok=" + String(camOk ? 1 : 0)
    + "&telemetry_ok=" + String(telemetryOk ? 1 : 0)
    + "&attempt=" + String(telemetryAttemptCount)
    + "&success=" + String(telemetrySuccessCount)
    + "&lat=" + String(lat, 6)
    + "&lon=" + String(lon, 6)
    + "&speed=" + String(speedKmph, 2);

  client.print(String("GET ") + path + " HTTP/1.1\r\n");
  client.print(String("Host: ") + BACKEND_HOST + ":" + String(BACKEND_PORT) + "\r\n");
  client.print("Connection: close\r\n\r\n");

  unsigned long timeout = millis();
  while (!client.available() && millis() - timeout < 3000) {
    delay(10);
  }

  if (!client.available()) {
    Serial.println("Server ping timeout");
    client.stop();
    return false;
  }

  String statusLine = client.readStringUntil('\n');
  statusLine.trim();
  Serial.print("Ping status: ");
  Serial.println(statusLine);

  bool ok = statusLine.indexOf("200") > 0;
  client.stop();
  return ok;
}

bool postTelemetryMultipart(float lat, float lon, float speedKmph, const uint8_t* imageData, size_t imageLen) {
  WiFiClient client;
  if (!client.connect(BACKEND_HOST, BACKEND_PORT)) {
    Serial.println("Failed to connect to backend host");
    return false;
  }

  String boundary = "----esp32camBoundary7MA4YWxkTrZu0gW";

  String partDevice = "--" + boundary + "\r\n"
                      "Content-Disposition: form-data; name=\"device_id\"\r\n\r\n" + String(DEVICE_ID) + "\r\n";

  String partPlate = "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"plate_number\"\r\n\r\n" + String(BUS_PLATE_NUMBER) + "\r\n";

  String partBusType = "--" + boundary + "\r\n"
                       "Content-Disposition: form-data; name=\"bus_type\"\r\n\r\n" + String(BUS_TYPE) + "\r\n";

  String partLat = "--" + boundary + "\r\n"
                   "Content-Disposition: form-data; name=\"lat\"\r\n\r\n" + String(lat, 6) + "\r\n";

  String partLon = "--" + boundary + "\r\n"
                   "Content-Disposition: form-data; name=\"lon\"\r\n\r\n" + String(lon, 6) + "\r\n";

  String partSpeed = "--" + boundary + "\r\n"
                     "Content-Disposition: form-data; name=\"speed\"\r\n\r\n" + String(speedKmph, 2) + "\r\n";

  String partCapacity = "--" + boundary + "\r\n"
                        "Content-Disposition: form-data; name=\"bus_capacity\"\r\n\r\n" + String(BUS_CAPACITY) + "\r\n";

  String partImageHeader = "--" + boundary + "\r\n"
                           "Content-Disposition: form-data; name=\"image\"; filename=\"frame.jpg\"\r\n"
                           "Content-Type: image/jpeg\r\n\r\n";

  String partImageFooter = "\r\n--" + boundary + "--\r\n";

  size_t contentLength = partDevice.length() + partPlate.length() + partBusType.length() +
                         partLat.length() + partLon.length() +
                         partSpeed.length() + partCapacity.length() +
                         partImageHeader.length() + imageLen + partImageFooter.length();

  client.print(String("POST ") + BACKEND_PATH + " HTTP/1.1\r\n");
  client.print(String("Host: ") + BACKEND_HOST + ":" + String(BACKEND_PORT) + "\r\n");
  client.print("Connection: close\r\n");
  client.print(String("Content-Type: multipart/form-data; boundary=") + boundary + "\r\n");
  client.print(String("Content-Length: ") + String(contentLength) + "\r\n\r\n");

  client.print(partDevice);
  client.print(partPlate);
  client.print(partBusType);
  client.print(partLat);
  client.print(partLon);
  client.print(partSpeed);
  client.print(partCapacity);
  client.print(partImageHeader);
  client.write(imageData, imageLen);
  client.print(partImageFooter);

  unsigned long timeout = millis();
  while (!client.available() && millis() - timeout < 7000) {
    delay(10);
  }

  if (!client.available()) {
    Serial.println("Backend response timeout");
    client.stop();
    return false;
  }

  String statusLine = client.readStringUntil('\n');
  statusLine.trim();
  Serial.print("HTTP status: ");
  Serial.println(statusLine);

  bool ok = statusLine.indexOf("200") > 0;

  while (client.available()) {
    String line = client.readStringUntil('\n');
    if (line == "\r") {
      break;
    }
  }

  String body;
  while (client.available()) {
    body += client.readStringUntil('\n');
  }
  body.trim();
  if (body.length() > 0) {
    Serial.print("Response body: ");
    Serial.println(body);
  }

  client.stop();
  return ok;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("ESP32-CAM + NEO-6M telemetry firmware starting...");

  if (!initCamera()) {
    Serial.println("Camera init failed. Rebooting in 5 seconds...");
    delay(5000);
    ESP.restart();
  }

  cameraHealthy = cameraSelfCheck();
  Serial.print("Camera health: ");
  Serial.println(cameraHealthy ? "OK" : "FAILED");

  gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  Serial.println("GPS UART initialized");

  connectWiFi();

  // Startup ping to backend before waiting for GPS fix.
  float startupLat = 0.0f;
  float startupLon = 0.0f;
  float startupSpeed = 0.0f;
  bool startupFallback = false;
  bool startupHasLocation = selectGpsFix(startupLat, startupLon, startupSpeed, startupFallback);
  bool startupPing = pingServerStatus("boot", startupHasLocation, cameraHealthy, false, startupLat, startupLon, startupSpeed);
  Serial.print("Startup ping: ");
  Serial.println(startupPing ? "OK" : "FAILED");
}

void loop() {
  feedGpsParser();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi disconnected, reconnecting...");
    connectWiFi();
  }

  unsigned long now = millis();

  bool gpsValidNow = hasFreshFix();
  if (gpsValidNow) {
    hasLastKnownGps = true;
    lastKnownLat = gps.location.lat();
    lastKnownLon = gps.location.lng();
  }
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;

    float hbLat = 0.0f;
    float hbLon = 0.0f;
    float hbSpeed = 0.0f;
    bool heartbeatFallback = false;
    bool heartbeatHasLocation = selectGpsFix(hbLat, hbLon, hbSpeed, heartbeatFallback);

    bool heartbeatOk = pingServerStatus(
      "heartbeat",
      heartbeatHasLocation,
      cameraHealthy,
      lastTelemetryOk,
      hbLat,
      hbLon,
      hbSpeed
    );

    Serial.print("Heartbeat ping: ");
    Serial.println(heartbeatOk ? "OK" : "FAILED");
  }

  if (now - lastSendMs < SEND_INTERVAL_MS) {
    delay(20);
    return;
  }

  lastSendMs = now;

  float lat = 0.0f;
  float lon = 0.0f;
  float speedKmph = 0.0f;
  bool usingFallbackCoords = false;

  if (!selectGpsFix(lat, lon, speedKmph, usingFallbackCoords)) {
    lastTelemetryOk = false;
    Serial.println("No fresh GPS fix yet, waiting...");
    Serial.print("Telemetry state | sent=NO_GPS | attempts=");
    Serial.print(telemetryAttemptCount);
    Serial.print(" success=");
    Serial.println(telemetrySuccessCount);
    return;
  }

  camera_fb_t* fb = esp_camera_fb_get();
  if (fb == nullptr) {
    cameraHealthy = false;
    lastTelemetryOk = false;
    Serial.println("Camera capture failed");
    Serial.print("Telemetry state | sent=CAMERA_FAIL | attempts=");
    Serial.print(telemetryAttemptCount);
    Serial.print(" success=");
    Serial.println(telemetrySuccessCount);
    return;
  }

  cameraHealthy = true;
  telemetryAttemptCount++;
  bool ok = postTelemetryMultipart(lat, lon, speedKmph, fb->buf, fb->len);
  esp_camera_fb_return(fb);
  lastTelemetryOk = ok;
  if (ok) {
    telemetrySuccessCount++;
  }

  Serial.print("Send telemetry: ");
  Serial.print(ok ? "OK" : "FAILED");
  if (usingFallbackCoords) {
    Serial.print(" | gps=fallback");
  }
  if (!gpsValidNow && !hasLastKnownGps) {
    Serial.print(" | waiting_for_fix");
  }
  Serial.print(" | lat=");
  Serial.print(lat, 6);
  Serial.print(" lon=");
  Serial.print(lon, 6);
  Serial.print(" speed=");
  Serial.print(speedKmph, 2);
  Serial.print(" | attempts=");
  Serial.print(telemetryAttemptCount);
  Serial.print(" success=");
  Serial.println(telemetrySuccessCount);
}

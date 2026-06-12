/**
 * ESP32-CAM + NEO-6M MQTT Telemetry Firmware
 * ──────────────────────────────────────────────────────────────────────────────
 * Sends GPS + camera telemetry via MQTT instead of HTTP.
 *
 * MQTT Topics:
 *   bus/{device_id}/gps       → {"lat": 9.02, "lon": 38.76, "speed": 25.5}
 *   bus/{device_id}/image     → binary JPEG payload
 *   bus/{device_id}/heartbeat → {"uptime": 1234, "rssi": -65}
 *   bus/{device_id}/cmd       ← server commands (reboot, config)
 *
 * Dependencies (Arduino IDE Library Manager):
 *   - PubSubClient by Nick O'Leary (MQTT)
 *   - TinyGPSPlus by Mikal Hart
 *   - ESP32 Camera
 *
 * Configuration: edit the constants below for your network and broker.
 * ──────────────────────────────────────────────────────────────────────────────
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include "esp_camera.h"
#include <TinyGPSPlus.h>

// ── WiFi ─────────────────────────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ── MQTT Broker ──────────────────────────────────────────────────────────────
const char* MQTT_HOST     = "10.230.143.202";  // Your server IP
const int   MQTT_PORT     = 1883;
const char* MQTT_USER     = "bustrack";
const char* MQTT_PASS     = "";
const char* DEVICE_ID     = "ESP32_BUS_001";

// ── Intervals (ms) ───────────────────────────────────────────────────────────
const unsigned long GPS_INTERVAL    = 3000;   // GPS ping every 3s (was 60s over HTTP)
const unsigned long IMAGE_INTERVAL  = 15000;  // Image every 15s (was 60s)
const unsigned long HB_INTERVAL     = 30000;  // Heartbeat every 30s

// ── Camera Pins (AI-Thinker ESP32-CAM) ──────────────────────────────────────
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ── GPS (UART1) ──────────────────────────────────────────────────────────────
HardwareSerial gpsSerial(1);
TinyGPSPlus gps;

// ── MQTT ─────────────────────────────────────────────────────────────────────
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

String topicGps;
String topicImage;
String topicHeartbeat;
String topicCmd;

unsigned long lastGpsPub    = 0;
unsigned long lastImagePub  = 0;
unsigned long lastHeartbeat = 0;

// ── Fallback GPS (Addis Ababa center, used when no fix) ─────────────────────
float FALLBACK_LAT = 9.032;
float FALLBACK_LON = 38.752;

// ── Function Declarations ────────────────────────────────────────────────────
void connectWiFi();
void connectMQTT();
void publishGps();
void publishImage();
void publishHeartbeat();
void onMqttMessage(char* topic, byte* payload, unsigned int length);

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("\n[BusTrack] ESP32-CAM MQTT Starting...");

    // Build topics
    String base = "bus/" + String(DEVICE_ID);
    topicGps       = base + "/gps";
    topicImage     = base + "/image";
    topicHeartbeat = base + "/heartbeat";
    topicCmd       = base + "/cmd";

    // GPS
    gpsSerial.begin(9600, SERIAL_8N1, 14, 15);  // RX=14, TX=15

    // Camera
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;  config.pin_d1  = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;  config.pin_d3  = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;  config.pin_d5  = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;  config.pin_d7  = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sscb_sda = SIOD_GPIO_NUM;
    config.pin_sscb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;

    if (psramFound()) {
        config.frame_size = FRAMESIZE_QVGA;  // 320x240
        config.jpeg_quality = 12;
        config.fb_count = 2;
    } else {
        config.frame_size = FRAMESIZE_QQVGA;  // 160x120
        config.jpeg_quality = 15;
        config.fb_count = 1;
    }

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("[Camera] Init failed: 0x%x — auto-rebooting\n", err);
        delay(3000);
        ESP.restart();
    }
    Serial.println("[Camera] Initialized");

    // WiFi + MQTT
    connectWiFi();
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setCallback(onMqttMessage);
    mqtt.setBufferSize(65536);  // Large buffer for JPEG images
    connectMQTT();
}

// ── Main Loop ────────────────────────────────────────────────────────────────
void loop() {
    if (!mqtt.connected()) connectMQTT();
    mqtt.loop();

    // Feed GPS parser
    while (gpsSerial.available() > 0) {
        gps.encode(gpsSerial.read());
    }

    unsigned long now = millis();

    // GPS publish
    if (now - lastGpsPub >= GPS_INTERVAL) {
        lastGpsPub = now;
        publishGps();
    }

    // Image publish
    if (now - lastImagePub >= IMAGE_INTERVAL) {
        lastImagePub = now;
        publishImage();
    }

    // Heartbeat
    if (now - lastHeartbeat >= HB_INTERVAL) {
        lastHeartbeat = now;
        publishHeartbeat();
    }
}

// ── GPS Publish ──────────────────────────────────────────────────────────────
void publishGps() {
    if (!mqtt.connected()) return;

    float lat, lon, spd;

    if (gps.location.isValid() && gps.location.isUpdated()) {
        lat = gps.location.lat();
        lon = gps.location.lng();
        spd = gps.speed.kmph();
    } else {
        // Use fallback coords so the bus stays visible on the map
        lat = FALLBACK_LAT;
        lon = FALLBACK_LON;
        spd = 0.0;
    }

    char payload[128];
    snprintf(payload, sizeof(payload),
        "{\"lat\":%.6f,\"lon\":%.6f,\"speed\":%.1f,\"hdop\":%.1f}",
        lat, lon, spd, gps.hdop.hdop());

    bool ok = mqtt.publish(topicGps.c_str(), payload, false);
    if (!ok) Serial.println("[MQTT] GPS publish failed");
}

// ── Image Publish ────────────────────────────────────────────────────────────
void publishImage() {
    if (!mqtt.connected()) return;

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("[Camera] Capture failed");
        return;
    }

    bool ok = mqtt.publish(topicImage.c_str(),
                           (const uint8_t*)fb->buf, fb->len, false);
    esp_camera_fb_return(fb);

    if (!ok) Serial.println("[MQTT] Image publish failed");
}

// ── Heartbeat ────────────────────────────────────────────────────────────────
void publishHeartbeat() {
    if (!mqtt.connected()) return;
    char hb[64];
    snprintf(hb, sizeof(hb), "{\"uptime\":%lu,\"rssi\":%d}",
             millis() / 1000, WiFi.RSSI());
    mqtt.publish(topicHeartbeat.c_str(), hb, false);
}

// ── MQTT Command Handler ────────────────────────────────────────────────────
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
    String msg;
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

    if (msg == "reboot") ESP.restart();
    // Add more commands as needed: config changes, interval updates, etc.
}

// ── WiFi ─────────────────────────────────────────────────────────────────────
void connectWiFi() {
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf(" OK (%s)\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println(" FAILED — restarting");
        ESP.restart();
    }
}

// ── MQTT ─────────────────────────────────────────────────────────────────────
void connectMQTT() {
    String clientId = "ESP32-" + String(DEVICE_ID);
    // Last Will: broker publishes this if ESP32 disconnects unexpectedly
    String willTopic = topicHeartbeat.c_str();
    String willMsg   = "{\"status\":\"offline\"}";

    if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS,
                     willTopic.c_str(), 1, true, willMsg.c_str())) {
        Serial.println("[MQTT] Connected");
        mqtt.subscribe(topicCmd.c_str(), 1);
    } else {
        Serial.printf("[MQTT] Connect failed, rc=%d — retrying in 5s\n",
                      mqtt.state());
    }
}

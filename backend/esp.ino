#include <WiFi.h>
#include <WebServer.h>

const char* ssid     = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";

WebServer server(80);

void handleRoot() {
  String html = "<html><body>"
    "<h2>ESP32 Name Echo</h2>"
    "<form action='/greet' method='GET'>"
    "  <input name='name' placeholder='Enter your name'>"
    "  <input type='submit' value='Send'>"
    "</form></body></html>";
  server.send(200, "text/html", html);
}

void handleGreet() {
  String name = server.arg("name");
  String response = "<html><body><h2>Hello, " + name + "!</h2>"
    "<a href='/'>Go back</a></body></html>";
  server.send(200, "text/html", response);
}

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nConnected! Open this in your browser:");
  Serial.println(WiFi.localIP());

  server.on("/", handleRoot);
  server.on("/greet", handleGreet);
  server.begin();
}

void loop() {
  server.handleClient();
}
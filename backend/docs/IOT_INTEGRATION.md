# IoT Device Integration Guide

This project connects buses or gateway devices to the backend through HTTP telemetry endpoints and a live WebSocket stream for the admin dashboard.

## 1. Register the device in the system

Before a device can send telemetry, it must be linked to a vehicle record.

Use the vehicle registration endpoint:

```bash
curl -X POST http://localhost:8000/api/v1/vehicles \
  -H "Content-Type: application/json" \
  -d '{
    "plate_number": "AA-123-BB",
    "device_id": "351234068795432",
    "bus_type": "Anbessa",
    "capacity": 60,
    "is_active": true
  }'
```

`device_id` should be the unique hardware identifier on the bus, such as a SIM7600 IMEI or another serial ID you keep stable on the device.

## 2. Send GPS telemetry from the device

For GPS-only devices, POST JSON to:

`POST /api/v1/telemetry`

Payload:

```json
{
  "device_id": "351234068795432",
  "lat": 9.032,
  "lon": 38.752,
  "speed": 12.5,
  "pixel_count": 8200,
  "raw_payload": {
    "battery": 85,
    "signal": -72
  }
}
```

Behavior:

The backend looks up the vehicle by `device_id`, checks route compliance when a route is assigned, rejects obvious GPS outliers, stores raw telemetry in `raw_telemetry`, updates the live vehicle position, and pushes the latest position to Redis and the admin dashboard stream.

If `pixel_count` is included, the backend also derives an occupancy level from that value.

## 3. Send camera telemetry from an ESP32-CAM gateway

For devices that upload an image frame, use multipart form data:

`POST /api/v1/gateway/esp32/telemetry`

Fields:

- `device_id`
- `lat`
- `lon`
- `speed`
- `bus_capacity`
- `image`

Example:

```bash
curl -X POST http://localhost:8000/api/v1/gateway/esp32/telemetry \
  -F "device_id=351234068795432" \
  -F "lat=9.032" \
  -F "lon=38.752" \
  -F "speed=12.5" \
  -F "bus_capacity=60" \
  -F "image=@frame.jpg"
```

What the endpoint does:

The image is analyzed locally, a simple crowd count is derived from the frame, occupancy is estimated from that count and the bus capacity, the vehicle location is updated, and the raw reading is stored asynchronously.

## 4. Live dashboard stream

The admin dashboard listens on:

`GET /api/v1/ws/live?token=<admin_jwt>`

The token must belong to an admin account. The stream sends `vehicle_position` messages whenever telemetry is processed.

## 5. Environment setup

Required services:

- PostgreSQL
- Redis

Typical local startup:

```bash
docker-compose up -d
alembic upgrade head
uvicorn app.main:app --reload
```

## 6. Configuration notes

Important settings live in `.env`:

- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `RAW_TELEMETRY_RETENTION_DAYS`
- `AWS_IOT_ENDPOINT` if you later want to add AWS IoT Core as a transport layer

## 7. Common device errors

- `Vehicle not registered` means the `device_id` does not exist in the vehicles table.
- `off_route` means the vehicle has a route assigned and the GPS point is outside the allowed corridor.
- `gps_outlier` means the point jumped too far from recent history.
- If camera uploads always return `occupancy_level: 0`, confirm that the image is actually multipart form data and that OpenCV is installed in the runtime.

## 8. Recommended device flow

1. Register the vehicle once.
2. Store the same `device_id` in the IoT firmware.
3. POST telemetry every few seconds.
4. For buses with cameras, send the image frame to the ESP32 gateway endpoint.
5. Use the admin dashboard WebSocket for live tracking.

## 9. ESP32-CAM + NEO-6M hardware wiring

The project now includes a ready firmware example at:

`firmware/esp32_cam_neo6m/esp32_cam_neo6m.ino`

Recommended wiring (AI Thinker ESP32-CAM):

| NEO-6M Pin | ESP32-CAM Pin | Note |
|---|---|---|
| VCC | 3.3V | Use stable 3.3V power |
| GND | GND | Common ground required |
| TX | GPIO14 | GPS sends NMEA to ESP32 RX |
| RX | GPIO15 | Optional, only needed if configuring GPS |

Power note:

ESP32-CAM + camera + Wi-Fi can draw high current peaks. Use a stable 5V supply (for board input) and avoid weak USB power.

## 10. Backend preparation before flashing ESP32

1. Start backend services:

```bash
docker-compose up -d
alembic upgrade head
uvicorn app.main:app --reload
```

2. Register the bus with the same `device_id` used in firmware:

```bash
curl -X POST http://localhost:8000/api/v1/vehicles \
  -H "Content-Type: application/json" \
  -d '{
    "plate_number": "AA-ESP-001",
    "device_id": "ESP32_BUS_001",
    "bus_type": "Anbessa",
    "capacity": 40,
    "is_active": true
  }'
```

3. Make sure the backend is reachable from Wi-Fi clients using your machine LAN IP (for example `192.168.1.50`) and not only `localhost`.

## 11. Firmware configuration (ESP32 side)

Open `firmware/esp32_cam_neo6m/esp32_cam_neo6m.ino` and set these values:

- `WIFI_SSID`
- `WIFI_PASSWORD`
- `BACKEND_HOST` (your backend PC LAN IP)
- `BACKEND_PORT` (default `8000`)
- `BACKEND_PATH` (keep `/api/v1/gateway/esp32/telemetry`)
- `DEVICE_ID` (must match the registered vehicle)
- `BUS_CAPACITY`

What this firmware does automatically:

- Connects to Wi-Fi on boot.
- Reads GPS from NEO-6M on UART.
- Captures a JPEG frame from ESP32-CAM.
- Sends multipart telemetry every few seconds to `/api/v1/gateway/esp32/telemetry`.
- Reconnects Wi-Fi if disconnected.

## 12. Arduino IDE / PlatformIO dependencies

Install these libraries:

- TinyGPSPlus (by Mikal Hart)

Use board:

- AI Thinker ESP32-CAM

Upload hints:

- Hold GPIO0 to GND for flashing mode if your board requires it.
- After upload, release GPIO0 and reset the board to run.
- Use Serial Monitor at `115200` baud to confirm Wi-Fi and telemetry status.

## 13. Confirm data is visible on your system

After ESP32 boots and gets GPS lock, verify in this order:

1. Serial Monitor shows lines like `Send telemetry: OK`.
2. API returns live coordinates:

```bash
curl http://localhost:8000/api/v1/vehicles/positions
```

You should see your vehicle id with `lat`, `lon`, and `timestamp`.

3. Open admin dashboard map (or your live page that uses vehicle positions / ws stream). The vehicle marker should update as GPS changes.

## 14. Why you might not see the bus on dashboard

- `Vehicle not registered`: firmware `DEVICE_ID` does not match backend vehicle record.
- No GPS lock: NEO-6M needs open sky, and first fix can take time.
- Backend unreachable: wrong `BACKEND_HOST` or different network segment.
- Weak power: camera + Wi-Fi brownout causes random resets.
- Route/off-route rejection (if strict route checks are enabled on the telemetry path you use).

## 15. Optional performance tuning for prototype

- Increase `SEND_INTERVAL_MS` to reduce Wi-Fi traffic.
- Use QVGA/QQVGA JPEG to keep upload latency low.
- Add an external antenna for better GPS and Wi-Fi reliability.
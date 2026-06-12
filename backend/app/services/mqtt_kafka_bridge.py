"""MQTT-to-Kafka bridge service.

Subscribes to MQTT bus telemetry topics and forwards messages to Kafka topics,
providing durable buffering between the MQTT broker and the backend pipeline.

Architecture:
    ESP32 → MQTT Broker → Bridge → Kafka Topic → Consumer → Pipeline

This decouples the ESP32 devices from the backend — if the backend restarts,
Kafka retains messages so no telemetry is lost.
"""

from __future__ import annotations

import json
import logging
import time as _time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Singleton reference
_bridge_instance: MqttKafkaBridge | None = None


class MqttKafkaBridge:
    """Subscribes to MQTT bus topics and forwards to Kafka topics.

    Uses paho-mqtt for MQTT and kafka-python for Kafka. Runs the MQTT
    client loop in a background thread to avoid blocking the async event loop.
    """

    def __init__(self, settings: Any, kafka_producer: Any) -> None:
        self._settings = settings
        self._kafka = kafka_producer
        self._mqtt: Any = None
        self._running = False

        # Metrics
        self.messages_forwarded = 0
        self.messages_failed = 0

    async def start(self) -> None:
        """Start the MQTT client and connect to the broker."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.error(
                "paho-mqtt not installed — MQTT bridge disabled. "
                "Install with: pip install paho-mqtt"
            )
            return

        self._running = True

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info("MQTT bridge connected to %s:%d",
                            self._settings.MQTT_BROKER_HOST,
                            self._settings.MQTT_BROKER_PORT)
                # Subscribe to all bus topics
                client.subscribe(f"{self._settings.MQTT_BASE_TOPIC}/+/gps", qos=1)
                client.subscribe(f"{self._settings.MQTT_BASE_TOPIC}/+/image", qos=1)
                client.subscribe(f"{self._settings.MQTT_BASE_TOPIC}/+/heartbeat", qos=0)
            else:
                logger.error("MQTT bridge connection failed, rc=%d", rc)

        def on_message(client, userdata, msg):
            self._handle_mqtt_message(msg)

        self._mqtt = mqtt.Client(client_id="bustrack-bridge", clean_session=True)
        self._mqtt.username_pw_set(
            self._settings.MQTT_USERNAME,
            self._settings.MQTT_PASSWORD,
        )
        self._mqtt.on_connect = on_connect
        self._mqtt.on_message = on_message

        try:
            self._mqtt.connect_async(
                self._settings.MQTT_BROKER_HOST,
                self._settings.MQTT_BROKER_PORT,
                keepalive=self._settings.MQTT_KEEPALIVE,
            )
            self._mqtt.loop_start()
            logger.info("MQTT-Kafka bridge started")
        except Exception:
            logger.exception("MQTT bridge failed to connect")
            self._running = False

    async def stop(self) -> None:
        """Disconnect MQTT and stop the background loop."""
        self._running = False
        if self._mqtt:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
        logger.info("MQTT-Kafka bridge stopped")

    def _handle_mqtt_message(self, msg) -> None:
        """Forward an MQTT message to the appropriate Kafka topic."""
        try:
            topic: str = msg.topic
            parts = topic.split("/")
            # Expected: bus/{device_id}/gps|image|heartbeat
            if len(parts) != 3:
                return
            device_id = parts[1]
            subtopic = parts[2]
            timestamp = _time.time()

            if subtopic == "gps":
                payload = json.loads(msg.payload)
                kafka_msg = {
                    "device_id": device_id,
                    "lat": payload.get("lat"),
                    "lon": payload.get("lon"),
                    "speed": payload.get("speed", 0),
                    "hdop": payload.get("hdop"),
                    "timestamp": timestamp,
                    "source": "mqtt",
                }
                self._kafka.send(
                    self._settings.KAFKA_TELEMETRY_TOPIC,
                    key=device_id.encode(),
                    value=json.dumps(kafka_msg).encode(),
                )

            elif subtopic == "image":
                # Save image to disk, send metadata to Kafka
                image_path = self._save_image(device_id, msg.payload)
                kafka_msg = {
                    "device_id": device_id,
                    "image_path": image_path,
                    "image_size_bytes": len(msg.payload),
                    "timestamp": timestamp,
                    "source": "mqtt",
                }
                self._kafka.send(
                    self._settings.KAFKA_IMAGE_TOPIC,
                    key=device_id.encode(),
                    value=json.dumps(kafka_msg).encode(),
                )

            elif subtopic == "heartbeat":
                logger.debug("Heartbeat from %s", device_id)

            self.messages_forwarded += 1

        except json.JSONDecodeError:
            logger.warning("Invalid JSON on MQTT topic %s", msg.topic)
            self.messages_failed += 1
        except Exception:
            logger.exception("Bridge: error forwarding MQTT message")
            self.messages_failed += 1

    def _save_image(self, device_id: str, data: bytes) -> str:
        """Save raw image bytes to disk for later CV processing."""
        directory = Path("storage") / "esp32_images"
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"mqtt_{device_id}_{int(_time.time() * 1000)}.jpg"
        filepath = directory / filename
        filepath.write_bytes(data)
        return str(filepath)


async def get_mqtt_kafka_bridge(settings: Any = None) -> MqttKafkaBridge | None:
    """Get or create the singleton bridge instance."""
    global _bridge_instance
    if _bridge_instance is not None:
        return _bridge_instance
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()
    if not settings.KAFKA_ENABLED or not settings.MQTT_ENABLED:
        return None
    try:
        from app.services.telemetry_consumer import get_kafka_producer
        producer = get_kafka_producer(settings)
        _bridge_instance = MqttKafkaBridge(settings, producer)
    except Exception:
        logger.exception("Failed to create MQTT-Kafka bridge")
    return _bridge_instance

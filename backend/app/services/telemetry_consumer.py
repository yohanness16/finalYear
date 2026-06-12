"""Kafka consumer for telemetry data.

Consumes telemetry from Kafka topics and processes through the same
`process_telemetry()` pipeline used by the HTTP and MQTT gateways.

Architecture:
    Kafka Topic → Consumer → process_telemetry() → Redis + DB + WebSocket

This provides durable, replayable telemetry ingestion independent of
the MQTT broker or HTTP gateway.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Singleton references
_consumer_instance: TelemetryConsumer | None = None
_producer_instance: Any = None


class TelemetryConsumer:
    """Consumes telemetry from Kafka and processes through the unified pipeline."""

    def __init__(self, settings: Any, process_telemetry_fn) -> None:
        self._settings = settings
        self._process = process_telemetry_fn
        self._consumer: Any = None
        self._running = False

        # Metrics
        self.messages_consumed = 0
        self.messages_processed = 0
        self.messages_failed = 0

    async def start(self) -> None:
        """Start the Kafka consumer in a background task."""
        try:
            from kafka import KafkaConsumer
        except ImportError:
            logger.error(
                "kafka-python not installed — Kafka consumer disabled. "
                "Install with: pip install kafka-python"
            )
            return

        try:
            self._consumer = KafkaConsumer(
                self._settings.KAFKA_TELEMETRY_TOPIC,
                self._settings.KAFKA_IMAGE_TOPIC,
                bootstrap_servers=self._settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=self._settings.KAFKA_GROUP_ID,
                auto_offset_reset=self._settings.KAFKA_AUTO_OFFSET_RESET,
                max_poll_interval_ms=self._settings.KAFKA_MAX_POLL_INTERVAL_MS,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                enable_auto_commit=False,
            )
            self._running = True
            logger.info(
                "Kafka consumer started: topics=%s,%s",
                self._settings.KAFKA_TELEMETRY_TOPIC,
                self._settings.KAFKA_IMAGE_TOPIC,
            )
        except Exception:
            logger.exception("Failed to start Kafka consumer")
            self._running = False

    async def stop(self) -> None:
        """Stop the Kafka consumer."""
        self._running = False
        if self._consumer:
            self._consumer.close()
        logger.info("Kafka consumer stopped")


def get_kafka_producer(settings: Any = None) -> Any:
    """Get or create a singleton Kafka producer."""
    global _producer_instance
    if _producer_instance is not None:
        return _producer_instance
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()
    try:
        from kafka import KafkaProducer
        _producer_instance = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
        )
    except ImportError:
        logger.error("kafka-python not installed")
    except Exception:
        logger.exception("Failed to create Kafka producer")
    return _producer_instance


async def get_telemetry_consumer(settings: Any = None) -> TelemetryConsumer | None:
    """Get or create the singleton consumer instance."""
    global _consumer_instance
    if _consumer_instance is not None:
        return _consumer_instance
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()
    if not settings.KAFKA_ENABLED:
        return None
    from app.services.telemetry_ingest import process_telemetry
    _consumer_instance = TelemetryConsumer(settings, process_telemetry)
    return _consumer_instance

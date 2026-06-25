# vira/sensors/network_sensor.py
import time
import psutil

from vira.sensors.event_sensor import EventSensor


class NetworkSensor(EventSensor):

    EVENT_TYPE = "sensor.network.state"

    def __init__(self, interval=5.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="network_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )
        self._previous_io = None
        self._previous_time = None

    async def read(self):
        current_io = psutil.net_io_counters()
        current_time = time.monotonic()

        if self._previous_io is None:
            self._previous_io = current_io
            self._previous_time = current_time
            return {
                "bytes_sent": 0,
                "bytes_received": 0,
                "packets_sent": 0,
                "packets_received": 0,
                "bytes_sent_per_sec": 0.0,
                "bytes_received_per_sec": 0.0,
                "packets_sent_per_sec": 0.0,
                "packets_received_per_sec": 0.0,
            }

        elapsed = current_time - self._previous_time
        bytes_sent = max(0, current_io.bytes_sent - self._previous_io.bytes_sent)
        bytes_received = max(0, current_io.bytes_recv - self._previous_io.bytes_recv)
        packets_sent = max(0, current_io.packets_sent - self._previous_io.packets_sent)
        packets_received = max(0, current_io.packets_recv - self._previous_io.packets_recv)

        self._previous_io = current_io
        self._previous_time = current_time

        if elapsed <= 0:
            elapsed = 1e-6

        return {
            "bytes_sent": bytes_sent,
            "bytes_received": bytes_received,
            "packets_sent": packets_sent,
            "packets_received": packets_received,
            "bytes_sent_per_sec": round(bytes_sent / elapsed, 2),
            "bytes_received_per_sec": round(bytes_received / elapsed, 2),
            "packets_sent_per_sec": round(packets_sent / elapsed, 2),
            "packets_received_per_sec": round(packets_received / elapsed, 2),
        }
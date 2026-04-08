"""BLE connection manager with auto-reconnect."""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Callable, Optional

from bleak import BleakClient

from opple_bridge.config import settings

logger = logging.getLogger(__name__)


class BLEConnection:
    """Manages the BleakClient lifecycle with automatic reconnection."""

    def __init__(self, address: str, on_disconnect: Optional[Callable] = None):
        self._address = address
        self._client: Optional[BleakClient] = None
        self._on_disconnect_cb = on_disconnect
        self._connected = False
        self._reconnecting = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None and self._client.is_connected

    @property
    def client(self) -> Optional[BleakClient]:
        return self._client

    @property
    def mtu_size(self) -> int:
        return self._client.mtu_size if self._client else 0

    async def connect(self) -> bool:
        """Connect to the BLE device with exponential backoff retry."""
        delay = settings.ble_reconnect_delay

        for attempt in range(settings.ble_reconnect_max_retries):
            try:
                logger.info("Connecting to %s (attempt %d/%d)...",
                            self._address, attempt + 1, settings.ble_reconnect_max_retries)

                self._client = BleakClient(
                    self._address,
                    disconnected_callback=self._handle_disconnect,
                )
                await self._client.connect()

                if self._client.is_connected:
                    self._connected = True
                    self._reconnecting = False
                    logger.info("Connected to %s (MTU: %d)", self._address, self._client.mtu_size)
                    return True

            except Exception as e:
                logger.warning("Connection attempt %d failed: %s", attempt + 1, e)

            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 30.0)

        logger.error("Failed to connect after %d attempts", settings.ble_reconnect_max_retries)
        return False

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._connected = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning("Error during disconnect: %s", e)
        self._client = None

    def _handle_disconnect(self, client: BleakClient) -> None:
        """Called by BleakClient when the device disconnects unexpectedly."""
        logger.warning("Device disconnected!")
        self._connected = False
        if self._on_disconnect_cb:
            self._on_disconnect_cb()

    async def write(self, char_uuid: str, data: bytes, response: bool = False) -> None:
        """Write data to a GATT characteristic."""
        if not self.is_connected:
            raise ConnectionError("Not connected")
        await self._client.write_gatt_char(char_uuid, data, response=response)

    async def start_notify(self, char_uuid: str, callback: Callable) -> None:
        """Subscribe to notifications on a characteristic."""
        if not self.is_connected:
            raise ConnectionError("Not connected")
        await self._client.start_notify(char_uuid, callback)

    async def stop_notify(self, char_uuid: str) -> None:
        """Unsubscribe from notifications."""
        if self.is_connected:
            try:
                await self._client.stop_notify(char_uuid)
            except Exception:
                pass

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# PiSugar server exposes a line-based TCP protocol on port 8423.
# Each query: send "get <field>\n", receive "<field>: <value>\n".
_TIMEOUT = 3.0


@dataclass
class PiSugarStatus:
    available: bool
    battery_pct: float | None = None
    charging: bool = False
    voltage_v: float | None = None


def _parse_host_port(addr: str) -> tuple[str, int]:
    """Parse 'host:port' or 'scheme://host:port' into (host, port)."""
    # Strip optional scheme (http://, tcp://, etc.)
    if "://" in addr:
        addr = addr.split("://", 1)[1]
    addr = addr.rstrip("/")
    host, _, port_str = addr.rpartition(":")
    if not host:
        host = "127.0.0.1"
    return host, int(port_str) if port_str.isdigit() else 8423


class PiSugarClient:
    """Polls the pisugar-server TCP API (port 8423, line-based text protocol)."""

    def __init__(self, url: str) -> None:
        self._host, self._port = _parse_host_port(url)
        self._last_pct: float | None = None
        self._was_available: bool | None = None

    async def _query(self, field: str) -> str | None:
        """Send 'get <field>' and return the value string, or None on any error."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError):
            return None

        try:
            writer.write(f"get {field}\n".encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=_TIMEOUT)
            text = line.decode().strip()
            # Expected format: "battery: 69.04"
            if ": " in text and not text.startswith("Invalid"):
                return text.split(": ", 1)[1]
            return None
        except (OSError, asyncio.TimeoutError):
            return None
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (OSError, asyncio.TimeoutError):
                pass

    async def poll(self) -> PiSugarStatus:
        pct_raw = await self._query("battery")
        if pct_raw is None:
            if self._was_available is not False:
                logger.warning("PiSugar unreachable -- no battery data")
                self._was_available = False
            return PiSugarStatus(available=False)

        try:
            pct = float(pct_raw)
        except ValueError:
            return PiSugarStatus(available=False)

        charging_raw = await self._query("battery_charging")
        charging = charging_raw == "true" if charging_raw else False

        status = PiSugarStatus(
            available=True,
            battery_pct=round(pct, 1),
            charging=charging,
            voltage_v=None,
        )

        if self._was_available is not True:
            logger.info("PiSugar connected -- %.0f%% %s", pct, "charging" if charging else "discharging")
            self._was_available = True
        elif self._last_pct is not None and abs(pct - self._last_pct) >= 5:
            logger.info("Battery %.0f%% %s", pct, "charging" if charging else "discharging")

        if pct <= 5:
            logger.error("Battery critical: %.0f%% -- shutdown imminent", pct)
        elif pct <= 15:
            logger.warning("Battery low: %.0f%%", pct)

        self._last_pct = pct
        return status

    async def close(self) -> None:
        pass


class MockPiSugarClient:
    def __init__(self) -> None:
        self._started = time.monotonic()

    async def poll(self) -> PiSugarStatus:
        # Drains slowly from 85% at 1%/minute
        elapsed_min = (time.monotonic() - self._started) / 60.0
        pct = max(0.0, 85.0 - elapsed_min)
        logger.debug("Mock PiSugar: %.1f%% discharging", pct)
        return PiSugarStatus(
            available=True,
            battery_pct=round(pct, 1),
            charging=False,
            voltage_v=3.7,
        )

    async def close(self) -> None:
        pass

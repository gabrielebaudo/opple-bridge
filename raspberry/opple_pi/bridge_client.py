from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BridgeHealth:
    reachable: bool
    status: str = "unknown"
    uptime_s: float = 0.0
    last_measurement_age_s: float | None = None
    ble_state: str = "unknown"
    version: str = ""
    ws_clients: int = 0
    last_error: str | None = None


class BridgeClient:
    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._session = None
        self._was_reachable: bool | None = None

    async def _session_get(self) -> "aiohttp.ClientSession":  # type: ignore[name-defined]
        import aiohttp

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=3)
            )
        return self._session

    async def poll_health(self) -> BridgeHealth:
        import aiohttp

        session = await self._session_get()
        try:
            async with session.get(f"{self._url}/api/health") as resp:
                data = await resp.json()
                health = BridgeHealth(
                    reachable=True,
                    status=data.get("status", "ok"),
                    uptime_s=data.get("uptime_s", 0.0),
                    last_measurement_age_s=data.get("last_measurement_age_s"),
                    ble_state=data.get("ble_state", "unknown"),
                    version=data.get("version", ""),
                    ws_clients=data.get("ws_clients", 0),
                    last_error=data.get("last_error"),
                )
                if self._was_reachable is not True:
                    logger.info(
                        "Bridge OK -- uptime %.0fs, BLE %s, %d client(s)",
                        health.uptime_s,
                        health.ble_state,
                        health.ws_clients,
                    )
                    self._was_reachable = True
                else:
                    logger.debug("Bridge health: %s", health)
                return health
        except (aiohttp.ClientError, OSError) as exc:
            if self._was_reachable is not False:
                logger.warning("Bridge unreachable (%s)", exc)
                self._was_reachable = False
            return BridgeHealth(reachable=False, status="unreachable")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class MockBridgeClient:
    def __init__(self) -> None:
        self._started = time.monotonic()

    async def poll_health(self) -> BridgeHealth:
        uptime = round(time.monotonic() - self._started, 1)
        logger.debug("Mock bridge health: uptime=%.1fs", uptime)
        return BridgeHealth(
            reachable=True,
            status="ok",
            uptime_s=uptime,
            last_measurement_age_s=0.5,
            ble_state="connected",
            version="0.1.0-mock",
            ws_clients=0,
        )

    async def close(self) -> None:
        pass

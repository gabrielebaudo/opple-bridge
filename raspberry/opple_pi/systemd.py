from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_UNIT = "opple-bridge.service"
_WARN_THRESHOLD = 2
_CRIT_THRESHOLD = 3


@dataclass
class ServiceHealth:
    active: bool
    state: str = "unknown"
    n_restarts: int = 0
    result: str = "unknown"


async def _systemctl_show(*props: str, unit: str = _UNIT) -> dict[str, str]:
    cmd = ["systemctl", "show", unit, "--property=" + ",".join(props)]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    result: dict[str, str] = {}
    for line in stdout.decode().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k] = v
    return result


class SystemdClient:
    def __init__(self, unit: str = _UNIT) -> None:
        self._unit = unit
        self._last_restarts: int | None = None

    async def get_service_health(self) -> ServiceHealth:
        try:
            props = await _systemctl_show("ActiveState", "NRestarts", "Result", unit=self._unit)
        except (OSError, FileNotFoundError):
            logger.debug("systemctl not available")
            return ServiceHealth(active=False, state="unavailable")

        active_state = props.get("ActiveState", "unknown")
        n_restarts = int(props.get("NRestarts", "0"))
        result = props.get("Result", "unknown")

        if n_restarts >= _CRIT_THRESHOLD and n_restarts != self._last_restarts:
            logger.error("Bridge unstable: %d restarts", n_restarts)
        elif n_restarts >= _WARN_THRESHOLD and n_restarts != self._last_restarts:
            logger.warning("Bridge restarted %d times", n_restarts)

        self._last_restarts = n_restarts
        return ServiceHealth(
            active=active_state == "active",
            state=active_state,
            n_restarts=n_restarts,
            result=result,
        )


class MockSystemdClient:
    async def get_service_health(self) -> ServiceHealth:
        logger.debug("Mock systemd: active, 0 restarts")
        return ServiceHealth(active=True, state="active", n_restarts=0, result="success")

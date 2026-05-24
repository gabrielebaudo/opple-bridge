from __future__ import annotations

import asyncio
import logging
import subprocess
import time

from opple_bridge.models import SystemInfo

_started_at = time.monotonic()
logger = logging.getLogger(__name__)


async def _systemctl(action: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "sudo", "-n", "systemctl", action,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        if proc.returncode not in (0, None):
            logger.error("systemctl %s failed (rc=%s): %s", action, proc.returncode, stderr.decode().strip())
    except asyncio.TimeoutError:
        pass  # system is going down


async def reboot() -> None:
    await _systemctl("reboot")


async def shutdown() -> None:
    await _systemctl("poweroff")


def get_info(version: str) -> SystemInfo:
    try:
        sha = subprocess.check_output(
            ["git", "describe", "--always", "--dirty"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode().strip()
    except Exception:
        sha = "unknown"
    return SystemInfo(
        version=version,
        git_sha=sha,
        uptime_s=round(time.monotonic() - _started_at, 1),
    )

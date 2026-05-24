from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class NetworkStatus:
    connected: bool
    ssid: str | None = None
    ip_address: str | None = None
    signal_strength: int | None = None
    is_hotspot: bool = False


async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


class NetworkManager:
    def __init__(self) -> None:
        self._last_ssid: str | None = None
        self._last_hotspot: bool | None = None

    async def get_status(self) -> NetworkStatus:
        # Check if hotspot is active
        hotspot_out = await _run(
            ["nmcli", "-t", "-f", "GENERAL.TYPE,GENERAL.STATE", "device", "show", "wlan0"]
        )
        is_hotspot = "ap" in hotspot_out.lower()

        if is_hotspot:
            ip_out = await _run(
                ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"]
            )
            ip = ip_out.split(":")[1].split("/")[0] if ":" in ip_out else None
            status = NetworkStatus(connected=True, ssid="OPPLE BRIDGE (hotspot)", ip_address=ip, is_hotspot=True)
        else:
            # Get SSID and IP
            out = await _run(
                ["nmcli", "-t", "-f", "GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", "wlan0"]
            )
            ssid = None
            ip = None
            for line in out.splitlines():
                if line.startswith("GENERAL.CONNECTION:"):
                    val = line.split(":", 1)[1]
                    ssid = val if val and val != "--" else None
                elif line.startswith("IP4.ADDRESS"):
                    raw = line.split(":", 1)[1]
                    ip = raw.split("/")[0] if raw else None

            connected = ssid is not None and ip is not None
            status = NetworkStatus(connected=connected, ssid=ssid, ip_address=ip, is_hotspot=False)

        # Log changes
        if status.ssid != self._last_ssid or status.is_hotspot != self._last_hotspot:
            if status.connected:
                logger.info(
                    "WiFi: %s (%s)%s",
                    status.ssid,
                    status.ip_address or "no IP",
                    " [hotspot]" if status.is_hotspot else "",
                )
            else:
                logger.warning("WiFi: not connected")
            self._last_ssid = status.ssid
            self._last_hotspot = status.is_hotspot

        return status

    async def start_hotspot(self, ssid: str, psk: str | None = None) -> bool:
        cmd = ["nmcli", "device", "wifi", "hotspot", "ssid", ssid, "band", "bg", "ifname", "wlan0"]
        if psk:
            cmd += ["password", psk]
        try:
            await _run(cmd)
            logger.info("Hotspot started: %s", ssid)
            return True
        except Exception as exc:
            logger.error("Failed to start hotspot: %s", exc)
            return False

    async def stop_hotspot(self) -> bool:
        try:
            await _run(["nmcli", "device", "disconnect", "wlan0"])
            logger.info("Hotspot stopped")
            return True
        except Exception as exc:
            logger.error("Failed to stop hotspot: %s", exc)
            return False


class MockNetworkManager:
    async def get_status(self) -> NetworkStatus:
        logger.debug("Mock network: connected to MockWiFi")
        return NetworkStatus(
            connected=True,
            ssid="MockWiFi",
            ip_address="192.168.1.42",
            signal_strength=75,
            is_hotspot=False,
        )

    async def start_hotspot(self, ssid: str, psk: str | None = None) -> bool:
        logger.info("Mock: hotspot started (%s)", ssid)
        return True

    async def stop_hotspot(self) -> bool:
        return True

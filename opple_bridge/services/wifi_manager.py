from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

import yaml

from opple_bridge.models import HotspotConfig, WifiNetworkOut, WifiStatus

logger = logging.getLogger(__name__)


def _validate_ssid(ssid: str) -> None:
    if not ssid or len(ssid) > 32 or "\x00" in ssid:
        raise ValueError("SSID deve essere 1-32 caratteri, senza NUL")


def _validate_psk(psk: str) -> None:
    if len(psk) < 8 or len(psk) > 63:
        raise ValueError("Password WiFi deve essere 8-63 caratteri")


def _write_yaml(path: str, data: dict) -> None:
    dir_ = os.path.dirname(path)
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        tmp = f.name
    os.replace(tmp, path)


def _con_name(ssid: str) -> str:
    return f"opple-{ssid}"


def _normalize_password(password: Optional[str]) -> Optional[str]:
    if password is None:
        return None
    return password.strip() or None


async def _run_nmcli(*args: str, timeout: float = 10.0) -> str:
    proc = await asyncio.create_subprocess_exec(
        "nmcli",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"nmcli timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(
            f"nmcli error (rc={proc.returncode}): {stderr.decode().strip()}"
        )
    return stdout.decode().strip()


class WifiManager:
    def __init__(self, config_path: str, mock_mode: bool = False) -> None:
        self._config_path = config_path
        self._mock_mode = mock_mode

    # ------------------------------------------------------------------
    # Internal YAML helpers
    # ------------------------------------------------------------------

    def _load_yaml(self) -> dict:
        if not os.path.exists(self._config_path):
            return {"networks": []}
        with open(self._config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "networks" not in data:
            data["networks"] = []
        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_networks(self) -> list[WifiNetworkOut]:
        if self._mock_mode:
            return [
                WifiNetworkOut(ssid="MockWiFi", priority=100, has_password=True),
                WifiNetworkOut(ssid="OpenNet", priority=50, has_password=False),
            ]
        data = self._load_yaml()
        networks = sorted(
            data.get("networks", []),
            key=lambda n: n.get("priority", 0),
            reverse=True,
        )
        return [
            WifiNetworkOut(
                ssid=n["ssid"],
                priority=n.get("priority", 50),
                has_password=bool(n.get("psk")),
                password=n.get("psk"),
                autoconnect=n.get("autoconnect", True),
            )
            for n in networks
            if "ssid" in n
        ]

    async def add_network(
        self,
        ssid: str,
        password: Optional[str],
        priority: int,
    ) -> None:
        _validate_ssid(ssid)
        if password is not None:
            _validate_psk(password)

        if self._mock_mode:
            return

        cmd = [
            "connection", "add",
            "type", "wifi",
            "ifname", "wlan0",
            "con-name", _con_name(ssid),
            "ssid", ssid,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(priority),
        ]
        if password:
            cmd += [
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", password,
            ]
        await _run_nmcli(*cmd)

        data = self._load_yaml()
        # Avoid duplicates
        data["networks"] = [n for n in data["networks"] if n.get("ssid") != ssid]
        entry: dict = {"ssid": ssid, "priority": priority}
        if password:
            entry["psk"] = password
        data["networks"].append(entry)
        _write_yaml(self._config_path, data)

    async def update_network(
        self,
        ssid: str,
        new_ssid: Optional[str],
        password: Optional[str],
        priority: Optional[int],
    ) -> None:
        _validate_ssid(ssid)
        target_ssid = (new_ssid or ssid).strip()
        _validate_ssid(target_ssid)
        clean_password = _normalize_password(password)
        if clean_password is not None:
            _validate_psk(clean_password)

        data = self._load_yaml()
        networks = data.get("networks", [])
        current = next((n for n in networks if n.get("ssid") == ssid), None)
        if current is None:
            raise KeyError(ssid)
        if target_ssid != ssid and any(n.get("ssid") == target_ssid for n in networks):
            raise ValueError(f"Network '{target_ssid}' already exists")

        if self._mock_mode:
            return

        modify_args: list[str] = ["connection", "modify", _con_name(ssid)]
        if target_ssid != ssid:
            modify_args += ["connection.id", _con_name(target_ssid), "802-11-wireless.ssid", target_ssid]
        if priority is not None:
            modify_args += ["connection.autoconnect-priority", str(priority)]
        if clean_password is not None:
            modify_args += [
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", clean_password,
            ]
        if len(modify_args) > 3:
            await _run_nmcli(*modify_args)

        current["ssid"] = target_ssid
        if priority is not None:
            current["priority"] = priority
        if clean_password is not None:
            current["psk"] = clean_password
        _write_yaml(self._config_path, data)

    async def delete_network(self, ssid: str) -> None:
        _validate_ssid(ssid)

        data = self._load_yaml()
        if not any(n.get("ssid") == ssid for n in data.get("networks", [])):
            raise KeyError(ssid)

        if self._mock_mode:
            return

        await _run_nmcli("connection", "delete", _con_name(ssid))

        data["networks"] = [n for n in data["networks"] if n.get("ssid") != ssid]
        _write_yaml(self._config_path, data)

    async def reorder(self, order: list[str]) -> None:
        for ssid in order:
            _validate_ssid(ssid)

        if self._mock_mode:
            return

        # priority = 100 - index (highest first)
        priority_map = {ssid: 100 - i for i, ssid in enumerate(order)}

        for ssid, prio in priority_map.items():
            await _run_nmcli(
                "connection", "modify", _con_name(ssid),
                "connection.autoconnect-priority", str(prio),
            )

        data = self._load_yaml()
        # Update priorities and reorder list to match requested order
        net_by_ssid = {n["ssid"]: n for n in data["networks"] if "ssid" in n}
        reordered = []
        for ssid in order:
            if ssid in net_by_ssid:
                net_by_ssid[ssid]["priority"] = priority_map[ssid]
                reordered.append(net_by_ssid[ssid])
        # Append any networks not in the order list (preserving them)
        for n in data["networks"]:
            if n.get("ssid") not in priority_map:
                reordered.append(n)
        data["networks"] = reordered
        _write_yaml(self._config_path, data)

    async def get_status(self) -> WifiStatus:
        if self._mock_mode:
            return WifiStatus(
                connected=True,
                ssid="MockWiFi",
                ip_address="192.168.1.42",
                is_hotspot=False,
            )

        try:
            hotspot_out = await _run_nmcli(
                "-t", "-f", "GENERAL.TYPE,GENERAL.STATE",
                "device", "show", "wlan0",
            )
            is_hotspot = "ap" in hotspot_out.lower()

            if is_hotspot:
                ip_out = await _run_nmcli(
                    "-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"
                )
                ip = ip_out.split(":")[1].split("/")[0] if ":" in ip_out else None
                return WifiStatus(
                    connected=True,
                    ssid="OPPLE BRIDGE (hotspot)",
                    ip_address=ip,
                    is_hotspot=True,
                )

            out = await _run_nmcli(
                "-t", "-f", "GENERAL.CONNECTION,IP4.ADDRESS",
                "device", "show", "wlan0",
            )
            ssid = None
            ip = None
            for line in out.splitlines():
                if line.startswith("GENERAL.CONNECTION:"):
                    val = line.split(":", 1)[1]
                    if val and val != "--":
                        ssid = val[len("opple-"):] if val.startswith("opple-") else val
                elif line.startswith("IP4.ADDRESS"):
                    raw = line.split(":", 1)[1]
                    ip = raw.split("/")[0] if raw else None

            connected = ssid is not None and ip is not None
            return WifiStatus(connected=connected, ssid=ssid, ip_address=ip, is_hotspot=False)

        except Exception as exc:
            logger.warning("Could not get WiFi status via nmcli: %s", exc)
            return WifiStatus(connected=False)

    async def get_hotspot_config(self) -> HotspotConfig:
        data = self._load_yaml()
        hotspot = data.get("hotspot", {})
        return HotspotConfig(
            ssid=hotspot.get("ssid", "OPPLE BRIDGE"),
            has_password=bool(hotspot.get("psk")),
        )

    async def update_hotspot_config(
        self,
        ssid: str,
        password: Optional[str],
    ) -> None:
        _validate_ssid(ssid)
        if password:
            _validate_psk(password)

        data = self._load_yaml()
        hotspot = data.get("hotspot", {})
        hotspot["ssid"] = ssid
        if password == "":
            hotspot["psk"] = None
        elif password is not None:
            hotspot["psk"] = password
        hotspot.setdefault("ip", "192.168.1.1")
        hotspot.setdefault("fallback_after_s", 45)
        data["hotspot"] = hotspot
        _write_yaml(self._config_path, data)

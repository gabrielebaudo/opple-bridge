from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SidecarConfig:
    bridge_url: str = "http://127.0.0.1"
    pisugar_url: str = "127.0.0.1:8423"
    poll_interval_s: float = 5.0
    hotspot_fallback_after_s: float = 45.0
    log_level: str = "info"
    display_enabled: bool = True
    display_interval_s: float = 60.0
    logo_path: str | None = None
    mock_mode: bool = False
    output_dir: str = "/tmp/opple-pi"


@dataclass
class WifiNetwork:
    ssid: str
    psk: str | None = None
    priority: int = 50


@dataclass
class WifiConfig:
    networks: list[WifiNetwork] = field(default_factory=list)
    hotspot_ssid: str = "OPPLE BRIDGE"
    hotspot_psk: str | None = None
    hotspot_ip: str = "192.168.1.1"
    fallback_after_s: float = 45.0


def _default_logo_path() -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(here, "assets", "logo.png")
    return candidate if os.path.exists(candidate) else None


def load_config() -> SidecarConfig:
    def _bool(val: str) -> bool:
        return val.lower() in ("1", "true", "yes")

    return SidecarConfig(
        bridge_url=os.environ.get("OPPLE_PI_BRIDGE_URL", "http://127.0.0.1"),
        pisugar_url=os.environ.get("OPPLE_PI_PISUGAR_URL", "127.0.0.1:8423"),
        poll_interval_s=float(os.environ.get("OPPLE_PI_POLL_INTERVAL", "5.0")),
        hotspot_fallback_after_s=float(os.environ.get("OPPLE_PI_HOTSPOT_FALLBACK", "45.0")),
        log_level=os.environ.get("OPPLE_PI_LOG_LEVEL", "info"),
        display_enabled=_bool(os.environ.get("OPPLE_PI_DISPLAY_ENABLED", "true")),
        display_interval_s=float(os.environ.get("OPPLE_PI_DISPLAY_INTERVAL", "60.0")),
        logo_path=os.environ.get("OPPLE_PI_LOGO_PATH", _default_logo_path()),
        mock_mode=_bool(os.environ.get("OPPLE_PI_MOCK_MODE", "false")),
        output_dir=os.environ.get("OPPLE_PI_OUTPUT_DIR", "/tmp/opple-pi"),
    )


def load_wifi_config(path: str) -> WifiConfig:
    import yaml

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return WifiConfig()

    networks = [
        WifiNetwork(
            ssid=n["ssid"],
            psk=n.get("psk"),
            priority=n.get("priority", 50),
        )
        for n in data.get("networks", [])
    ]
    hotspot = data.get("hotspot", {})
    return WifiConfig(
        networks=networks,
        hotspot_ssid=hotspot.get("ssid", "OPPLE BRIDGE"),
        hotspot_psk=hotspot.get("psk"),
        hotspot_ip=hotspot.get("ip", "192.168.1.1"),
        fallback_after_s=hotspot.get("fallback_after_s", 45.0),
    )

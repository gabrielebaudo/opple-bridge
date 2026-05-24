from __future__ import annotations

import time
from dataclasses import dataclass, fields


@dataclass
class AppState:
    # Bridge
    bridge_reachable: bool = False
    bridge_status: str = "unknown"
    bridge_uptime_s: float = 0.0
    bridge_ble_state: str = "disconnected"
    bridge_version: str = ""
    bridge_last_error: str | None = None

    # PiSugar
    pisugar_available: bool = False
    battery_pct: float | None = None
    charging: bool = False

    # Network
    wifi_connected: bool = False
    wifi_ssid: str | None = None
    ip_address: str | None = None
    is_hotspot: bool = False

    # Systemd
    bridge_service_active: bool = False
    bridge_n_restarts: int = 0

    # Sidecar meta
    sidecar_uptime_s: float = 0.0
    timestamp: float = 0.0

    # Fields that never trigger a display refresh
    _DISPLAY_SKIP = frozenset({
        "sidecar_uptime_s", "timestamp",
        "bridge_uptime_s", "bridge_ble_state",
        "bridge_status", "bridge_version", "bridge_last_error",
        "bridge_service_active",
        "battery_pct", "charging", "pisugar_available",
    })
    # Subset that bypasses the throttle (force=True) when they change
    _CRITICAL_FIELDS = frozenset({
        "bridge_reachable", "wifi_connected", "is_hotspot", "bridge_n_restarts",
    })

    def has_critical_change(self, other: "AppState") -> bool:
        for f in fields(self):
            if f.name in self._CRITICAL_FIELDS:
                if getattr(self, f.name) != getattr(other, f.name):
                    return True
        return False

    def has_changed(self, other: "AppState") -> bool:
        for f in fields(self):
            if f.name in self._DISPLAY_SKIP:
                continue
            if getattr(self, f.name) != getattr(other, f.name):
                return True
        return False

    def warning_level(self) -> str:
        if self.bridge_n_restarts >= 3:
            return "critical"
        if not self.bridge_reachable:
            return "warning"
        return "normal"

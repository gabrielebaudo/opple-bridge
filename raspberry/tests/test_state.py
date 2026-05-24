from __future__ import annotations

from opple_pi.state import AppState


class TestAppStateChangeDetection:
    def test_identical_states_not_changed(self):
        s1 = AppState(bridge_reachable=True, wifi_ssid="MyNet")
        s2 = AppState(bridge_reachable=True, wifi_ssid="MyNet")
        assert s1.has_changed(s2) is False

    def test_different_bridge_status_is_change(self):
        s1 = AppState(bridge_reachable=True)
        s2 = AppState(bridge_reachable=False)
        assert s1.has_changed(s2) is True

    def test_uptime_delta_is_not_change(self):
        s1 = AppState(bridge_uptime_s=100.0, sidecar_uptime_s=10.0, timestamp=1000.0)
        s2 = AppState(bridge_uptime_s=105.0, sidecar_uptime_s=15.0, timestamp=1005.0)
        assert s1.has_changed(s2) is False

    def test_wifi_change_is_change(self):
        s1 = AppState(wifi_ssid="A")
        s2 = AppState(wifi_ssid="B")
        assert s1.has_changed(s2) is True


class TestWarningLevel:
    def test_normal(self):
        s = AppState(bridge_reachable=True, bridge_n_restarts=0, battery_pct=50.0)
        assert s.warning_level() == "normal"

    def test_warning_on_unreachable_bridge(self):
        s = AppState(bridge_reachable=False)
        assert s.warning_level() == "warning"

    def test_battery_does_not_affect_warning_level(self):
        s = AppState(bridge_reachable=True, battery_pct=3.0)
        assert s.warning_level() == "normal"

    def test_critical_on_many_restarts(self):
        s = AppState(bridge_reachable=True, bridge_n_restarts=3)
        assert s.warning_level() == "critical"

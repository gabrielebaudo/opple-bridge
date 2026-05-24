from __future__ import annotations

import os

from opple_pi.state import AppState
from opple_pi.display.layout import DisplayLayout, WIDTH, HEIGHT


class TestDisplayLayout:
    def _layout(self):
        return DisplayLayout()

    def test_render_returns_correct_size(self):
        img = self._layout().render(AppState())
        assert img.size == (WIDTH, HEIGHT)

    def test_render_mode_is_1bit(self):
        img = self._layout().render(AppState())
        assert img.mode == "1"

    def test_render_healthy_state(self):
        state = AppState(
            bridge_reachable=True,
            bridge_ble_state="connected",
            wifi_ssid="TestNet",
            ip_address="192.168.1.10",
            battery_pct=75.0,
        )
        img = self._layout().render(state)
        assert img.size == (WIDTH, HEIGHT)

    def test_render_critical_state(self):
        state = AppState(bridge_n_restarts=5, bridge_reachable=False)
        img = self._layout().render(state)
        assert img.size == (WIDTH, HEIGHT)

    def test_render_to_file(self, tmp_path):
        path = str(tmp_path / "display.png")
        self._layout().render_to_file(AppState(), path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

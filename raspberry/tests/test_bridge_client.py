from __future__ import annotations

import asyncio
import pytest

from opple_pi.bridge_client import BridgeClient, MockBridgeClient


class TestMockBridgeClient:
    def test_returns_reachable(self):
        client = MockBridgeClient()
        health = asyncio.get_event_loop().run_until_complete(client.poll_health())
        assert health.reachable is True
        assert health.status == "ok"
        assert health.ble_state == "connected"

    def test_uptime_increases(self):
        import time
        client = MockBridgeClient()
        h1 = asyncio.get_event_loop().run_until_complete(client.poll_health())
        time.sleep(0.05)
        h2 = asyncio.get_event_loop().run_until_complete(client.poll_health())
        assert h2.uptime_s >= h1.uptime_s


class TestRealBridgeClientUnreachable:
    def test_returns_unreachable_without_raising(self):
        client = BridgeClient("http://127.0.0.1:19999")
        health = asyncio.get_event_loop().run_until_complete(client.poll_health())
        assert health.reachable is False
        assert health.status == "unreachable"

    def test_close_is_safe(self):
        client = BridgeClient("http://127.0.0.1:19999")
        asyncio.get_event_loop().run_until_complete(client.close())

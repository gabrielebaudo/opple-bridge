from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


os.environ.setdefault("MOCK_MODE", "true")


class TestHealthEndpoint:
    def test_returns_200(self):
        from opple_bridge.main import app

        with TestClient(app) as client:
            resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_response_fields(self):
        from opple_bridge.main import app

        with TestClient(app) as client:
            resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert data["uptime_s"] >= 0
        assert data["ws_clients"] == 0
        assert "ble_state" in data
        assert "last_measurement_age_s" in data
        assert "last_error" in data

    def test_ble_state_connected_in_mock_mode(self):
        from opple_bridge.main import app

        with TestClient(app) as client:
            resp = client.get("/api/health")
        assert resp.json()["ble_state"] == "connected"

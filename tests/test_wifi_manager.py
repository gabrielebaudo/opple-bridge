from __future__ import annotations

import asyncio

import pytest
import yaml

from opple_bridge.services import wifi_manager as wm
from opple_bridge.services.wifi_manager import WifiManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _write_config(path, networks):
    path.write_text(yaml.safe_dump({"networks": networks}), encoding="utf-8")


def _read_networks(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))["networks"]


def test_list_networks_exposes_saved_password(tmp_path):
    config = tmp_path / "wifi.yaml"
    _write_config(config, [{"ssid": "Stage", "psk": "oldpassword", "priority": 80}])

    networks = _run(WifiManager(str(config)).list_networks())

    assert networks[0].ssid == "Stage"
    assert networks[0].has_password is True
    assert networks[0].password == "oldpassword"


def test_update_network_renames_ssid_and_preserves_password(tmp_path, monkeypatch):
    calls = []

    async def fake_run_nmcli(*args, timeout=10.0):
        calls.append(args)
        return ""

    monkeypatch.setattr(wm, "_run_nmcli", fake_run_nmcli)

    config = tmp_path / "wifi.yaml"
    _write_config(config, [{"ssid": "OldNet", "psk": "oldpassword", "priority": 70}])

    _run(WifiManager(str(config)).update_network("OldNet", "NewNet", None, 90))

    networks = _read_networks(config)
    assert networks == [{"ssid": "NewNet", "psk": "oldpassword", "priority": 90}]
    assert calls == [(
        "connection", "modify", "opple-OldNet",
        "connection.id", "opple-NewNet",
        "802-11-wireless.ssid", "NewNet",
        "connection.autoconnect-priority", "90",
    )]


def test_update_network_replaces_password(tmp_path, monkeypatch):
    async def fake_run_nmcli(*args, timeout=10.0):
        return ""

    monkeypatch.setattr(wm, "_run_nmcli", fake_run_nmcli)

    config = tmp_path / "wifi.yaml"
    _write_config(config, [{"ssid": "Stage", "psk": "oldpassword", "priority": 80}])

    _run(WifiManager(str(config)).update_network("Stage", "Stage", "newpassword", None))

    assert _read_networks(config)[0]["psk"] == "newpassword"


def test_update_network_rejects_duplicate_rename(tmp_path):
    config = tmp_path / "wifi.yaml"
    _write_config(config, [
        {"ssid": "StageA", "psk": "passworda", "priority": 80},
        {"ssid": "StageB", "psk": "passwordb", "priority": 70},
    ])

    with pytest.raises(ValueError):
        _run(WifiManager(str(config)).update_network("StageA", "StageB", None, None))

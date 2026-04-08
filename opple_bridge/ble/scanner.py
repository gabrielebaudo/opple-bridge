"""BLE device scanner for Opple Light Master."""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from opple_bridge.config import settings

logger = logging.getLogger(__name__)

KNOWN_NAMES = ("sigmesh", "light master", "opple", "lm iv", "lm4")


def _device_name(device: BLEDevice, adv) -> str:
    return device.name or (adv.local_name if adv else "") or ""


def _name_matches(name: str, preferred: str) -> bool:
    lower = name.lower()
    if preferred and preferred.lower() in lower:
        return True
    return any(known in lower for known in KNOWN_NAMES)


async def _discover(timeout: Optional[float] = None) -> dict:
    scan_timeout = timeout or settings.ble_scan_timeout
    logger.info("Scanning for BLE devices (timeout: %.1fs)...", scan_timeout)
    return await BleakScanner.discover(timeout=scan_timeout, return_adv=True)


async def scan_opple_devices(timeout: Optional[float] = None) -> list[dict]:
    """Return every Opple-matching device currently advertising."""
    discovered = await _discover(timeout)
    preferred = settings.ble_device_name
    results: list[dict] = []
    seen: set[str] = set()

    for address, (device, adv) in discovered.items():
        name = _device_name(device, adv)
        if not name or not _name_matches(name, preferred):
            continue
        if device.address in seen:
            continue
        seen.add(device.address)
        results.append({
            "name": name,
            "address": device.address,
            "rssi": adv.rssi if adv else None,
        })

    logger.info("Found %d Opple device(s)", len(results))
    return results


async def find_opple(timeout: Optional[float] = None) -> Optional[BLEDevice]:
    """Return the first device matching the preferred name, else any known Opple."""
    discovered = await _discover(timeout)
    preferred = settings.ble_device_name.lower()

    preferred_match: Optional[BLEDevice] = None
    fallback_match: Optional[BLEDevice] = None

    for address, (device, adv) in discovered.items():
        name = _device_name(device, adv).lower()
        if not name:
            continue
        if preferred and preferred in name and preferred_match is None:
            preferred_match = device
        elif fallback_match is None and any(k in name for k in KNOWN_NAMES):
            fallback_match = device

    match = preferred_match or fallback_match
    if match:
        logger.info("Found: %s [%s]", match.name, match.address)
    else:
        logger.warning("No Opple device found (scanned %d devices)", len(discovered))
    return match

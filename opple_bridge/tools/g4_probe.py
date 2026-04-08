"""Live diagnostic probe for the Opple Light Master.

Scans, connects, and prints each parsed measurement using the same BLE
stack as the bridge server. Useful for checking that a device talks the
expected protocol on a new machine or after a firmware update.

Usage:
    python -m opple_bridge.tools.g4_probe
    python -m opple_bridge.tools.g4_probe --address XX:XX
    python -m opple_bridge.tools.g4_probe --count 5
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from opple_bridge.ble.manager import BLEManager
from opple_bridge.models import ConnectionState, MeasurementData

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _print_measurement(m: MeasurementData, raw_power: float | None, pct: int | None) -> None:
    batt = f"{pct}% (raw={raw_power})" if pct is not None else f"-- (raw={raw_power})"
    print(
        f"  lux={m.lux:<8.1f} cct={m.cct_k:<6d}K duv={m.duv:+.4f}  "
        f"x={m.cie_x:.4f} y={m.cie_y:.4f}  "
        f"Ra={m.cri_ra}  R9={m.r9}  batt={batt}"
    )


async def probe(address: str | None, count: int) -> None:
    manager = BLEManager()
    received = 0
    done = asyncio.Event()

    def on_measurement(m: MeasurementData) -> None:
        nonlocal received
        received += 1
        _print_measurement(m, manager.last_raw_power, m.connection.battery_pct)
        if received >= count:
            done.set()

    manager.on_measurement(on_measurement)
    await manager.connect_to(address)

    try:
        await asyncio.wait_for(done.wait(), timeout=60.0)
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for %d measurements (got %d)", count, received)
    finally:
        await manager.user_disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Opple Light Master live probe")
    parser.add_argument("--address", help="BLE device address (auto-scans if omitted)")
    parser.add_argument("--count", type=int, default=3, help="Measurements to print before exit")
    args = parser.parse_args()
    asyncio.run(probe(args.address, args.count))


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

from .config import load_config
from .state import AppState


class _SidecarFormatter(logging.Formatter):
    _LEVELS = {
        "DEBUG": "DEBUG",
        "INFO": "INFO ",
        "WARNING": "WARN ",
        "ERROR": "ERR  ",
        "CRITICAL": "CRIT ",
    }

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        level = self._LEVELS.get(record.levelname, record.levelname[:5])
        module = record.name.split(".")[-1][:8].ljust(8)
        return f"{ts} {level} {module} {record.getMessage()}"


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_SidecarFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    logger.info("Opple Pi sidecar starting (mock=%s, log=%s)", config.mock_mode, config.log_level)

    if config.mock_mode:
        from .bridge_client import MockBridgeClient
        from .pisugar_client import MockPiSugarClient
        from .network import MockNetworkManager
        from .systemd import MockSystemdClient

        bridge = MockBridgeClient()
        pisugar = MockPiSugarClient()
        network = MockNetworkManager()
        systemd_client = MockSystemdClient()
        logger.info("Using mock backends")
    else:
        from .bridge_client import BridgeClient
        from .pisugar_client import PiSugarClient
        from .network import NetworkManager
        from .systemd import SystemdClient

        bridge = BridgeClient(config.bridge_url)
        pisugar = PiSugarClient(config.pisugar_url)
        network = NetworkManager()
        systemd_client = SystemdClient()

    if config.display_enabled:
        from .display.layout import DisplayLayout
        from .display.driver import EPaperDriver
        from .display.strategy import RefreshStrategy
        os.makedirs(config.output_dir, exist_ok=True)
        layout = DisplayLayout(logo_path=config.logo_path)
        epd_driver = EPaperDriver()
        epd = RefreshStrategy(epd_driver, min_interval_s=config.display_interval_s)
    else:
        layout = None
        epd = None

    # Cancel the main loop on SIGTERM so the finally block renders the shutdown screen
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)

    sidecar_started = time.monotonic()
    previous_state: AppState | None = None

    try:
        while True:
            health = await bridge.poll_health()
            sugar = await pisugar.poll()
            net = await network.get_status()
            svc = await systemd_client.get_service_health()

            new_state = AppState(
                bridge_reachable=health.reachable,
                bridge_status=health.status,
                bridge_uptime_s=health.uptime_s,
                bridge_ble_state=health.ble_state,
                bridge_version=health.version,
                bridge_last_error=health.last_error,
                pisugar_available=sugar.available,
                battery_pct=sugar.battery_pct,
                charging=sugar.charging,
                wifi_connected=net.connected,
                wifi_ssid=net.ssid,
                ip_address=net.ip_address,
                is_hotspot=net.is_hotspot,
                bridge_service_active=svc.active,
                bridge_n_restarts=svc.n_restarts,
                sidecar_uptime_s=round(time.monotonic() - sidecar_started, 1),
                timestamp=time.time(),
            )

            if previous_state is None or new_state.has_changed(previous_state):
                logger.debug("State changed, rendering display")
                if layout is not None:
                    img = layout.render(new_state)
                    img.save(os.path.join(config.output_dir, "display.png"))
                    if epd is not None:
                        force = (previous_state is not None
                                 and new_state.has_critical_change(previous_state))
                        epd.update(img, force=force)

            previous_state = new_state
            await asyncio.sleep(config.poll_interval_s)

    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Sidecar shutting down")
        if layout is not None:
            path = os.path.join(config.output_dir, "display.png")
            layout.render_shutdown_to_file(path)
            logger.info("Shutdown screen written to %s", path)
            if epd is not None:
                epd.shutdown(layout.render_shutdown())
        await bridge.close()
        await pisugar.close()


if __name__ == "__main__":
    asyncio.run(main())

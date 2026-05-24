from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from opple_bridge.api.system import router as system_router
from opple_bridge.api.wifi import router as wifi_router
from opple_bridge.config import settings, APP_VERSION
from opple_bridge.models import ConnectionStatus, HealthStatus
from opple_bridge.ws.manager import WSManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ws_manager = WSManager()
_data_source: Any = None
_background_tasks: set[asyncio.Task] = set()
_started_at: float = 0.0
_last_measurement_at: float = 0.0
_last_error: Optional[str] = None


def _track(task: asyncio.Task) -> asyncio.Task:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _measurement_loop() -> None:
    global _last_measurement_at, _last_error
    while True:
        try:
            if _data_source is not None and _data_source.latest_measurement is not None:
                await ws_manager.broadcast(_data_source.latest_measurement.model_dump())
                _last_measurement_at = time.monotonic()
                _last_error = None
        except Exception as exc:
            _last_error = str(exc)
            logger.exception("Error in measurement loop")
        await asyncio.sleep(settings.measurement_interval)


def _on_state_change(status: ConnectionStatus) -> None:
    _track(asyncio.create_task(
        ws_manager.broadcast({"type": "connection", **status.model_dump()})
    ))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_source

    global _started_at
    _started_at = time.monotonic()

    if settings.mock_mode:
        logger.warning("Starting in MOCK mode")
        from opple_bridge.mock.generator import MockGenerator
        _data_source = MockGenerator()
        await _data_source.start()
    else:
        logger.warning("Starting in BLE mode (manual connect)")
        from opple_bridge.ble.manager import BLEManager
        _data_source = BLEManager()
        _data_source.on_state_change(_on_state_change)

    loop_task = _track(asyncio.create_task(_measurement_loop()))
    logger.warning("Opple Bridge started on %s:%d", settings.host, settings.port)

    try:
        yield
    finally:
        loop_task.cancel()
        for task in list(_background_tasks):
            task.cancel()
        if _data_source:
            await _data_source.stop()
        logger.warning("Opple Bridge shut down")


app = FastAPI(title="Opple Bridge", version=APP_VERSION, lifespan=lifespan)

_NO_CACHE_EXTS = {".js", ".css", ".html"}


class _NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if any(path.endswith(ext) for ext in _NO_CACHE_EXTS):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(_NoCacheMiddleware)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    try:
        if _data_source and hasattr(_data_source, "connection_status"):
            await ws.send_json({
                "type": "connection",
                **_data_source.connection_status.model_dump(),
            })
        while True:
            data = await ws.receive_json()
            if data.get("type") == "command" and data.get("action") == "request_flicker":
                if _data_source and hasattr(_data_source, "request_flicker"):
                    flicker = await _data_source.request_flicker()
                    if flicker:
                        await ws.send_json(flicker.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(ws)


@app.get("/api/status")
async def get_status() -> JSONResponse:
    if _data_source and hasattr(_data_source, "connection_status"):
        return JSONResponse(content=_data_source.connection_status.model_dump())
    return JSONResponse(content={"status": "unknown"})


@app.get("/api/scan")
async def scan_devices() -> JSONResponse:
    if _data_source and hasattr(_data_source, "scan"):
        return JSONResponse(content={"devices": await _data_source.scan()})
    return JSONResponse(content={"devices": []})


@app.post("/api/connect")
async def connect_device(request: Request) -> JSONResponse:
    if not _data_source or not hasattr(_data_source, "connect_to"):
        return JSONResponse(content={"error": "BLE not available"}, status_code=400)

    address: str | None = None
    try:
        body = await request.json()
        address = body.get("address")
    except Exception:
        pass

    await _data_source.connect_to(address)
    return JSONResponse(content={"status": "connecting", "address": address})


@app.post("/api/disconnect")
async def disconnect_device() -> JSONResponse:
    if _data_source and hasattr(_data_source, "user_disconnect"):
        await _data_source.user_disconnect()
        return JSONResponse(content={"status": "disconnected"})
    return JSONResponse(content={"error": "Not connected"}, status_code=400)


@app.get("/api/pi_battery")
async def get_pi_battery() -> JSONResponse:
    """
    Query the PiSugar 3 server (localhost:8423) for battery state.
    Returns {"available": false} gracefully when the server is unreachable
    (e.g. in dev/MOCK_MODE on macOS).
    """
    async def _query_pisugar(field: str) -> str | None:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", 8423), timeout=3.0
            )
            writer.write(f"get {field}\n".encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=3.0)
            text = line.decode().strip()
            if ": " in text and not text.startswith("Invalid"):
                return text.split(": ", 1)[1]
            return None
        except (OSError, asyncio.TimeoutError):
            return None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except (OSError, asyncio.TimeoutError):
                    pass

    try:
        pct_raw = await _query_pisugar("battery")
        charging_raw = await _query_pisugar("battery_charging")

        if pct_raw is None:
            return JSONResponse(content={"available": False, "battery_pct": None, "charging": False})

        battery_pct = float(pct_raw)
        charging = (charging_raw or "").strip().lower() == "true"
        return JSONResponse(content={"available": True, "battery_pct": round(battery_pct, 1), "charging": charging})
    except Exception:
        return JSONResponse(content={"available": False, "battery_pct": None, "charging": False})


@app.get("/api/health")
async def get_health() -> JSONResponse:
    now = time.monotonic()
    uptime = round(now - _started_at, 1) if _started_at else 0.0
    meas_age = round(now - _last_measurement_at, 1) if _last_measurement_at else None

    ble_state = "unknown"
    if _data_source and hasattr(_data_source, "connection_status"):
        ble_state = _data_source.connection_status.status.value

    return JSONResponse(content=HealthStatus(
        status="ok",
        uptime_s=uptime,
        last_measurement_age_s=meas_age,
        last_error=_last_error,
        version=app.version,
        ble_state=ble_state,
        ws_clients=ws_manager.client_count,
    ).model_dump())


app.include_router(wifi_router)
app.include_router(system_router)

app.mount("/", StaticFiles(directory="web", html=True), name="static")

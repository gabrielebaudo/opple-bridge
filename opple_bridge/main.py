from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from opple_bridge.config import settings
from opple_bridge.models import ConnectionStatus
from opple_bridge.ws.manager import WSManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ws_manager = WSManager()
_data_source: Any = None
_background_tasks: set[asyncio.Task] = set()


def _track(task: asyncio.Task) -> asyncio.Task:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _measurement_loop() -> None:
    while True:
        try:
            if _data_source is not None and _data_source.latest_measurement is not None:
                await ws_manager.broadcast(_data_source.latest_measurement.model_dump())
        except Exception:
            logger.exception("Error in measurement loop")
        await asyncio.sleep(settings.measurement_interval)


def _on_state_change(status: ConnectionStatus) -> None:
    _track(asyncio.create_task(
        ws_manager.broadcast({"type": "connection", **status.model_dump()})
    ))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_source

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


app = FastAPI(title="Opple Bridge", version="0.1.0", lifespan=lifespan)


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


app.mount("/", StaticFiles(directory="web", html=True), name="static")

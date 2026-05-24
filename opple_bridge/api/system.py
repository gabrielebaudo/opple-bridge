from __future__ import annotations

from fastapi import APIRouter

from opple_bridge.config import APP_VERSION
from opple_bridge.models import SystemInfo
from opple_bridge.services import system_manager as sm

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/reboot", status_code=202)
async def reboot() -> dict:
    await sm.reboot()
    return {"status": "rebooting"}


@router.post("/shutdown", status_code=202)
async def shutdown() -> dict:
    await sm.shutdown()
    return {"status": "shutting down"}


@router.get("/info", response_model=SystemInfo)
async def system_info() -> SystemInfo:
    return sm.get_info(version=APP_VERSION)

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from opple_bridge.config import settings
from opple_bridge.models import (
    HotspotConfig,
    HotspotConfigUpdate,
    WifiNetworkIn,
    WifiNetworkOut,
    WifiNetworkUpdate,
    WifiReorder,
    WifiStatus,
)
from opple_bridge.services.wifi_manager import WifiManager

router = APIRouter(prefix="/api/wifi", tags=["wifi"])
_manager = WifiManager(settings.wifi_config_path, settings.mock_mode)


@router.get("/networks", response_model=list[WifiNetworkOut])
async def list_networks() -> list[WifiNetworkOut]:
    return await _manager.list_networks()


@router.post("/networks", status_code=201)
async def add_network(body: WifiNetworkIn) -> dict:
    try:
        await _manager.add_network(body.ssid, body.password, body.priority)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "created", "ssid": body.ssid}


# NOTE: /networks/reorder must be declared BEFORE /networks/{ssid}
# to prevent FastAPI from matching "reorder" as the {ssid} path parameter.
@router.post("/networks/reorder")
async def reorder_networks(body: WifiReorder) -> dict:
    try:
        await _manager.reorder(body.order)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok"}


@router.put("/networks")
async def update_network(
    ssid: str = Query(..., description="SSID of the network to update"),
    body: WifiNetworkUpdate = ...,
) -> dict:
    try:
        await _manager.update_network(ssid, body.new_ssid, body.password, body.priority)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Network '{ssid}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "updated", "ssid": ssid}


@router.delete("/networks", status_code=204)
async def delete_network(
    ssid: str = Query(..., description="SSID of the network to delete"),
) -> None:
    try:
        await _manager.delete_network(ssid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Network '{ssid}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status", response_model=WifiStatus)
async def wifi_status() -> WifiStatus:
    return await _manager.get_status()


@router.get("/hotspot", response_model=HotspotConfig)
async def get_hotspot() -> HotspotConfig:
    return await _manager.get_hotspot_config()


@router.put("/hotspot")
async def update_hotspot(body: HotspotConfigUpdate) -> dict:
    try:
        await _manager.update_hotspot_config(body.ssid, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "updated"}

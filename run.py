#!/usr/bin/env python3
import uvicorn
from opple_bridge.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "opple_bridge.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level,
        access_log=False,
    )

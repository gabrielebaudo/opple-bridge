from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

from .driver import EPaperDriver

logger = logging.getLogger(__name__)

_FORCE_FULL_INTERVAL_S = 30 * 60


class RefreshStrategy:
    def __init__(self, driver: EPaperDriver, min_interval_s: float = 60.0) -> None:
        self._driver = driver
        self._min_interval_s = min_interval_s
        self._last_update_at: float = 0.0
        self._last_full_at: float = 0.0

    def update(self, image: "PILImage.Image", force: bool = False) -> None:
        if not self._driver.available:
            return

        now = time.monotonic()
        if not force and self._last_update_at != 0.0 and (now - self._last_update_at) < self._min_interval_s:
            return

        logger.debug("Full e-paper refresh")
        self._driver.init_full()
        self._driver.display_full(image)
        self._driver.sleep()
        self._last_update_at = now
        self._last_full_at = now

    def shutdown(self, image: "PILImage.Image") -> None:
        if not self._driver.available:
            return
        self._driver.init_full()
        self._driver.display_full(image)
        self._driver.sleep()

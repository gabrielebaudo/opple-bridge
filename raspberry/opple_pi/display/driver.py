from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)


def _load_epd_module():
    try:
        from waveshare_epd import epd2in13_V4
        return epd2in13_V4
    except Exception:
        return None


_mod = _load_epd_module()


class EPaperDriver:
    def __init__(self) -> None:
        self._epd = None
        if _mod is not None:
            try:
                self._epd = _mod.EPD()
                logger.info("Waveshare 2.13\" V4 driver loaded")
            except Exception as exc:
                logger.warning("EPD init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._epd is not None

    def init_full(self) -> None:
        if self._epd:
            self._epd.init()

    def display_full(self, image: "PILImage.Image") -> None:
        if self._epd:
            self._epd.display(self._epd.getbuffer(image))

    def init_partial(self) -> None:
        if self._epd and hasattr(self._epd, "init_Part"):
            self._epd.init_Part()

    def set_base(self, image: "PILImage.Image") -> None:
        """Sync OLD_DATA register to current on-screen image before partial updates."""
        if self._epd and hasattr(self._epd, "displayPartbaseImage"):
            self._epd.displayPartbaseImage(self._epd.getbuffer(image))

    def display_partial(self, image: "PILImage.Image") -> None:
        """Partial update — XORs against OLD_DATA set by set_base or auto-updated by hardware."""
        if not self._epd:
            return
        if hasattr(self._epd, "displayPartial"):
            self._epd.displayPartial(self._epd.getbuffer(image))
        else:
            self.init_full()
            self.display_full(image)

    def sleep(self) -> None:
        if self._epd:
            self._epd.sleep()

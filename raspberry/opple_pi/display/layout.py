from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

from ..state import AppState

logger = logging.getLogger(__name__)

WIDTH = 250
HEIGHT = 122
LOGO_W = 64
BLACK = 0
WHITE = 255

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
]
_FONT_SIZE = 11


def _pil():
    from PIL import Image, ImageDraw, ImageFont
    return Image, ImageDraw, ImageFont


def _load_font(size: int):
    _, _, ImageFont = _pil()
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


def _load_logo(path: str, max_w: int, max_h: int) -> "PILImage.Image | None":
    """Load logo, flatten transparency, resize with aspect ratio preserved (fit)."""
    Image, _, _ = _pil()
    try:
        raw = Image.open(path)
        bg = Image.new("L", raw.size, 255)
        if raw.mode in ("RGBA", "LA"):
            alpha = raw.convert("RGBA").split()[3]
            bg.paste(raw.convert("L"), mask=alpha)
        elif raw.mode == "P" and "transparency" in raw.info:
            alpha = raw.convert("RGBA").split()[3]
            bg.paste(raw.convert("L"), mask=alpha)
        else:
            bg.paste(raw.convert("L"))
        orig_w, orig_h = bg.size
        scale = min(max_w / orig_w, max_h / orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        bg = bg.resize((new_w, new_h), Image.LANCZOS)
        return bg.point(lambda x: WHITE if x > 128 else BLACK, "1")
    except Exception as exc:
        logger.warning("Logo not loaded: %s", exc)
        return None


def _strip_ssid_prefix(ssid: str) -> str:
    for prefix in ("opple-wifi-", "opple-wifi", "opple-"):
        if ssid.lower().startswith(prefix):
            return ssid[len(prefix):]
    return ssid


class DisplayLayout:
    def __init__(self, logo_path: str | None = None) -> None:
        self._logo: "PILImage.Image | None" = None
        if logo_path:
            self._logo = _load_logo(logo_path, LOGO_W, HEIGHT)
        self._font = _load_font(_FONT_SIZE)

    def render(self, state: AppState) -> "PILImage.Image":
        Image, ImageDraw, _ = _pil()

        img = Image.new("1", (WIDTH, HEIGHT), WHITE)
        draw = ImageDraw.Draw(img)

        # Left panel: logo centered (aspect ratio preserved) or placeholder
        if self._logo:
            lw, lh = self._logo.size
            x_off = (LOGO_W - lw) // 2
            y_off = (HEIGHT - lh) // 2
            img.paste(self._logo, (x_off, y_off))
        else:
            draw.rectangle([0, 0, LOGO_W - 2, HEIGHT - 1], outline=BLACK)
            draw.text((6, HEIGHT // 2 - 10), "OPPLE", font=self._font, fill=BLACK)
            draw.text((6, HEIGHT // 2 + 2), "BRIDGE", font=self._font, fill=BLACK)

        draw.line([(LOGO_W, 0), (LOGO_W, HEIGHT - 1)], fill=BLACK)

        x = LOGO_W + 6
        if state.warning_level() == "critical":
            self._draw_critical(draw, state, x)
        else:
            self._draw_normal(draw, state, x)

        return img

    def _draw_normal(self, draw, state: AppState, x: int) -> None:
        f = self._font

        # WiFi
        y = 10
        if state.is_hotspot:
            ssid_str = "HOTSPOT"
        elif state.wifi_ssid:
            ssid_str = _strip_ssid_prefix(state.wifi_ssid)
        else:
            ssid_str = "--"
        draw.text((x, y), f"WiFi: {ssid_str}", font=f, fill=BLACK)

        # IP
        y = 28
        draw.text((x, y), f"IP:   {state.ip_address or '--'}", font=f, fill=BLACK)

        y = 46
        draw.line([(x, y), (WIDTH - 2, y)], fill=BLACK)

        # Bridge
        y = 54
        if state.bridge_reachable:
            draw.text((x, y), "Bridge: OK", font=f, fill=BLACK)
        else:
            draw.text((x, y), "Bridge: DOWN", font=f, fill=BLACK)

        y = 72
        draw.line([(x, y), (WIDTH - 2, y)], fill=BLACK)

        # URL
        y = 80
        draw.text((x, y), "opple-bridge.local", font=f, fill=BLACK)

    def _draw_critical(self, draw, state: AppState, x: int) -> None:
        f = self._font
        y = 8
        draw.text((x, y), "! BRIDGE UNSTABLE", font=f, fill=BLACK)
        y += 16
        draw.text((x, y), f"{state.bridge_n_restarts} restarts", font=f, fill=BLACK)
        y += 16
        draw.text((x, y), "check via SSH", font=f, fill=BLACK)
        y += 16
        draw.text((x, y), f"IP: {state.ip_address or '--'}", font=f, fill=BLACK)

    def render_shutdown(self) -> "PILImage.Image":
        Image, ImageDraw, _ = _pil()
        img = Image.new("1", (WIDTH, HEIGHT), WHITE)
        draw = ImageDraw.Draw(img)

        if self._logo:
            lw, lh = self._logo.size
            img.paste(self._logo, ((WIDTH - lw) // 2, (HEIGHT - lh) // 2))
        else:
            cx, cy = WIDTH // 2, HEIGHT // 2
            draw.text((cx - 20, cy - 12), "OPPLE", font=self._font, fill=BLACK)
            draw.text((cx - 20, cy + 2), "BRIDGE", font=self._font, fill=BLACK)

        return img

    def render_to_file(self, state: AppState, path: str) -> None:
        img = self.render(state)
        img.save(path)
        logger.debug("Display rendered to %s", path)

    def render_shutdown_to_file(self, path: str) -> None:
        img = self.render_shutdown()
        img.save(path)


def _fmt_uptime(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    hours = minutes // 60
    mins = minutes % 60
    if hours:
        return f"{hours}h{mins:02d}m"
    return f"{mins}m"

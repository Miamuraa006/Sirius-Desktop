"""DPI-independent paired panel geometry, independent of Qt for exact tests."""

from dataclasses import dataclass
import math

MINI_WIDTH = 180
CHAT_WIDTH = 360
PANEL_HEIGHT = 284
DOCK_GAP = 8


@dataclass(frozen=True)
class PairLayout:
    mini: tuple[int, int, int, int]
    chat: tuple[int, int, int, int]
    scale: float
    gap: int


def fit_pair(
    available: tuple[int, int, int, int],
    anchor: tuple[int, int] | None = None,
    zoom: float = 1.0,
    *, chat_visible: bool = True,
) -> PairLayout:
    """Clamp only visible panels; a hidden chat must not reserve screen space.

    Qt screen.availableGeometry is already logical; do not multiply by device
    pixel ratio a second time. Quantize the Mini width first to retain exact 1:2
    window width even at fractional scale / Windows DPI.
    """
    sx, sy, width, height = available
    if width < 4 or height < 4:
        raise ValueError("Screen working area is empty")
    margin = min(16, max(0, min(width, height) // 40))
    design_width = MINI_WIDTH + CHAT_WIDTH + DOCK_GAP if chat_visible else MINI_WIDTH
    scale = min(max(0.75, min(float(zoom), 1.5)), (width - 2 * margin) / design_width,
                (height - 2 * margin) / PANEL_HEIGHT)
    mini_width = max(1, math.floor(MINI_WIDTH * scale))
    scale = mini_width / MINI_WIDTH
    panel_height = round(PANEL_HEIGHT * scale)
    gap = max(1, round(DOCK_GAP * scale))
    pair_width = mini_width * 3 + gap if chat_visible else mini_width
    if anchor is None:
        x = sx + width - pair_width - 32
        y = sy + height - panel_height - 32
    else:
        x, y = anchor
    x = max(sx + margin, min(int(x), sx + width - margin - pair_width))
    y = max(sy + margin, min(int(y), sy + height - margin - panel_height))
    return PairLayout(
        (x, y, mini_width, panel_height),
        (x + mini_width + gap, y, mini_width * 2, panel_height),
        scale, gap,
    )

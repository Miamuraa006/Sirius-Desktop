"""Logical window geometry; Qt already converts physical DPI to logical units."""

import importlib.util

import pytest


def geometry():
    assert importlib.util.find_spec("ui") is not None, "The production UI package must exist"
    from ui.geometry import fit_pair
    return fit_pair


@pytest.mark.parametrize("dpi", [1.0, 1.25, 1.5])
def test_exact_shared_scale_at_windows_dpi(dpi):
    fit_pair = geometry()
    available = (0, 0, int(1920 / dpi), int(1040 / dpi))
    layout = fit_pair(available)
    mx, my, mw, mh = layout.mini
    cx, cy, cw, ch = layout.chat
    assert cw == 2 * mw
    assert mh == ch
    assert my == cy
    assert cx == mx + mw + layout.gap
    assert layout.scale == pytest.approx(mw / 180)
    assert mh == round(284 * layout.scale)
    assert mx >= 0 and my >= 0
    assert cx + cw <= available[2]
    assert cy + ch <= available[3]
    if dpi == 1:
        assert (mw, mh, cw, ch) == (180, 284, 360, 284)


@pytest.mark.parametrize("area", [(0, 0, 1024, 720), (-1280, 0, 1280, 680), (20, 30, 800, 480)])
def test_compact_and_negative_origin_monitors_fit(area):
    fit_pair = geometry()
    layout = fit_pair(area, anchor=(5000, -100))
    x, y, width, height = area
    mx, my, mw, mh = layout.mini
    cx, cy, cw, ch = layout.chat
    assert x <= mx < cx
    assert y <= my == cy
    assert cx + cw <= x + width
    assert my + mh <= y + height
    assert cw == 2 * mw and mh == ch
    assert layout.scale <= 1


def test_anchor_is_stable_on_chat_toggle():
    fit_pair = geometry()
    before = fit_pair((0, 0, 1920, 1040), anchor=(51, 80))
    after = fit_pair((0, 0, 1920, 1040), anchor=before.mini[:2])
    assert before == after


@pytest.mark.parametrize('area', [(0, 0, 1536, 816), (-1920, 0, 1920, 1040)])
@pytest.mark.parametrize('zoom', [1, 1.25, 1.5])
def test_hidden_chat_releases_right_edge_and_reopening_fits(area, zoom):
    fit_pair = geometry()
    hidden = fit_pair(area, anchor=(10000, 100), zoom=zoom, chat_visible=False)
    x, y, w, h = hidden.mini
    assert x + w == area[0] + area[2] - 16
    opened = fit_pair(area, anchor=(x, y), zoom=zoom, chat_visible=True)
    assert opened.chat[0] + opened.chat[2] <= area[0] + area[2] - 16
    assert opened.mini[1] == y and opened.mini[2:] == hidden.mini[2:]

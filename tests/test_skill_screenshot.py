"""Screen capture tests use generated pixels, never the user's desktop."""
import importlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from core.models import Intent
from core.context import Context
from skills.windows.native import WindowRef


def module():
    assert (Path(__file__).parents[1] / 'skills/screenshot/handler.py').exists(), 'screenshot handler missing'
    return importlib.import_module('skills.screenshot.handler')


class Capture:
    def __init__(self):
        self.calls = []
        self.window = WindowRef(12, 34, 'notepad.exe', 'Fixture', 1.0)
        self.valid = True

    def target(self, context):
        return self.window if self.valid else None

    def capture(self, window=None):
        self.calls.append(window)
        return Image.new('RGB', (11, 7), (45, 88, 99))


@pytest.mark.parametrize('action', ['full', 'window'])
def test_capture_unique_png_verified_by_real_readback(tmp_path, action):
    adapter = Capture()
    handler = module().Handler(adapter, {'screenshot': {'directory': str(tmp_path)}})
    first = handler.execute(Intent('screenshot', action), Context())
    second = handler.execute(Intent('screenshot', action), Context())
    assert first.verified and second.verified
    assert first.details['path'] != second.details['path']
    for result in (first, second):
        path = Path(result.details['path'])
        assert path.parent == tmp_path and path.suffix == '.png'
        with Image.open(path) as image:
            image.load()
            assert image.size == (11, 7) and image.getpixel((0, 0)) == (45, 88, 99)
    assert adapter.calls == ([adapter.window] * 2 if action == 'window' else [None, None])


def test_active_capture_requires_identified_window(tmp_path):
    adapter = Capture()
    adapter.valid = False
    result = module().Handler(adapter, {'screenshot': {'directory': str(tmp_path)}}).execute(Intent('screenshot', 'window'), Context())
    assert result.status == 'failed' and not adapter.calls
    assert list(tmp_path.iterdir()) == []


def test_capture_failure_does_not_claim_saved_file(tmp_path):
    class Broken(Capture):
        def capture(self, window=None):
            raise OSError('sensitive driver text')
    result = module().Handler(Broken(), {'screenshot': {'directory': str(tmp_path)}}).execute(Intent('screenshot', 'full'), Context())
    assert result.status == 'failed' and 'sensitive' not in str(result)
    assert list(tmp_path.iterdir()) == []


def test_corrupt_png_write_is_not_success(tmp_path):
    class Corrupt:
        size = (11, 7)
        def save(self, stream, format):
            stream.write(b'not PNG')
        def close(self):
            pass
    adapter = Capture()
    adapter.capture = lambda window=None: Corrupt()
    result = module().Handler(adapter, {'screenshot': {'directory': str(tmp_path)}}).execute(Intent('screenshot', 'full'), Context())
    assert not result.verified and result.status == 'failed'
    assert list(tmp_path.iterdir()) == []


def test_invalid_action_does_not_capture(tmp_path):
    adapter = Capture()
    result = module().Handler(adapter).execute(Intent('screenshot', 'upload'), Context())
    assert result.status == 'failed' and not adapter.calls

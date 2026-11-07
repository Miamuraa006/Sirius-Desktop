"""Only temporary files and injected shell/recycle adapters are touched."""
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest


def paths():
    try:
        return import_module('skills.files.paths')
    except ModuleNotFoundError as exc:
        pytest.fail(f'Local path validation is missing: {exc}')


def module():
    try:
        return import_module('skills.files.handler')
    except ModuleNotFoundError as exc:
        pytest.fail(f'Files implementation is missing: {exc}')


@pytest.mark.parametrize('raw', [
    '../escape.txt', 'sub/../escape.txt', r'\\server\share\a.txt',
    r'\\?\C:\Users\a.txt', r'\\.\C:\a.txt', r'C:relative.txt',
    'a.txt:stream', 'CON.txt', 'LPT1', 'COM¹.txt', 'file.', 'file ',
    'bad?.txt', 'bad\x00.txt', r'\Windows\x.txt', '', '.',
    'C:/Windows/file.txt', 'C:/Program Files/file.txt', 'C:/$Recycle.Bin/a',
])
def test_local_path_validator_rejects_dangerous_syntax(raw, tmp_path):
    with pytest.raises(ValueError):
        paths().local_path(raw, base=tmp_path)


def test_local_path_validator_preserves_case_and_unicode(tmp_path):
    assert paths().local_path('Документы/My File.txt', base=tmp_path) == tmp_path / 'Документы' / 'My File.txt'


def intent(action, **params):
    return SimpleNamespace(skill='files', action=action, parameters=params)


def handler(tmp_path, adapter=None):
    return module().Handler(adapter, {'files': {'root': str(tmp_path), 'allowed_roots': [str(tmp_path)]}})


@pytest.mark.parametrize('action,name', [('mkdir', 'Папка'), ('touch', 'Text.TXT')])
def test_create_then_readback_without_overwriting(tmp_path, action, name):
    h = handler(tmp_path)
    result = h.execute(intent(action, path=name), SimpleNamespace(data={}))
    assert result.status == 'success' and result.verified
    assert (tmp_path / name).exists()
    assert h.execute(intent(action, path=name), SimpleNamespace(data={})).status == 'failed'


def test_touch_rejects_executable_extension(tmp_path):
    assert handler(tmp_path).execute(intent('touch', path='evil.bat'), None).status == 'failed'
    assert not (tmp_path / 'evil.bat').exists()


def test_handler_validates_before_calling_adapter(tmp_path):
    result = handler(tmp_path, object()).execute(intent('mkdir', path='../escape'), None)
    assert result.status == 'failed'


def test_no_success_without_filesystem_readback(tmp_path):
    adapter = SimpleNamespace(mkdir=lambda path: None)
    result = handler(tmp_path, adapter).execute(intent('mkdir', path='missing'), None)
    assert result.status == 'failed'
    assert not result.verified


@pytest.mark.parametrize('action', ['rename', 'move'])
def test_rename_move_readback_and_no_overwrite(tmp_path, action):
    source = tmp_path / 'source.txt'
    source.write_text('original', encoding='utf-8')
    h = handler(tmp_path)
    result = h.execute(intent(action, path='source.txt', destination='new.txt'), SimpleNamespace(data={}))
    assert result.status == 'success' and result.verified
    assert not source.exists()
    assert (tmp_path / 'new.txt').read_text(encoding='utf-8') == 'original'
    source.write_text('keep', encoding='utf-8')
    result = h.execute(intent(action, path='source.txt', destination='new.txt'), SimpleNamespace(data={}))
    assert result.status == 'failed'
    assert source.read_text(encoding='utf-8') == 'keep'
    assert (tmp_path / 'new.txt').read_text(encoding='utf-8') == 'original'


def test_trash_requires_core_grant_not_parameter_flag(tmp_path):
    (tmp_path / 'test.txt').write_text('test')
    result = handler(tmp_path, object()).execute(intent('trash', path='test.txt', confirmed=True), SimpleNamespace(data={}))
    assert result.status == 'needs_confirmation'
    assert (tmp_path / 'test.txt').exists()


def test_trash_grant_is_single_use_and_observes_absence(tmp_path):
    source = tmp_path / 'test.txt'
    source.write_text('test')
    recycled = tmp_path / 'fake-recycle.txt'
    context = SimpleNamespace(data={'file_grant': (str(source),)})
    adapter = SimpleNamespace(trash=lambda p: p.rename(recycled))
    result = handler(tmp_path, adapter).execute(intent('trash', path='test.txt'), context)
    assert result.status == 'success' and result.verified
    assert not source.exists() and recycled.exists()
    assert 'file_grant' not in context.data


def test_cross_root_needs_confirmation_before_adapter(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    source = first / 'a.txt'
    source.write_text('a')
    h = module().Handler(object(), {'files': {'root': str(first), 'allowed_roots': [str(second)]}})
    result = h.execute(intent('move', path=str(source), destination=str(second / 'a.txt')), SimpleNamespace(data={}))
    assert result.status == 'needs_confirmation'


def test_open_cannot_claim_success_from_dispatch_only(tmp_path):
    (tmp_path / 'a.txt').write_text('a')
    adapter = SimpleNamespace(open=lambda path: False)
    result = handler(tmp_path, adapter).execute(intent('open', path='a.txt'), None)
    assert result.status == 'unsupported' and not result.verified


def test_open_is_success_only_after_adapter_observes_document(tmp_path):
    (tmp_path / 'a.txt').write_text('a')
    adapter = SimpleNamespace(open=lambda path: True)
    result = handler(tmp_path, adapter).execute(intent('open', path='a.txt'), None)
    assert result.status == 'success' and result.verified


def test_open_rejects_executable_even_in_trusted_root(tmp_path):
    (tmp_path / 'a.cmd').write_text('exit')
    assert handler(tmp_path, object()).execute(intent('open', path='a.cmd'), None).status == 'failed'


def test_validator_rejects_reparse_component(monkeypatch, tmp_path):
    original = Path.lstat

    def stat(path):
        result = original(path)
        if path == tmp_path:
            return SimpleNamespace(st_file_attributes=0x400, st_mode=result.st_mode)
        return result

    monkeypatch.setattr(Path, 'lstat', stat)
    with pytest.raises(ValueError, match='ссыл'):
        paths().local_path('child.txt', base=tmp_path)

from pathlib import Path
import json

def test_license_manifest_records_hashes(tmp_path):
    import importlib.util
    assert importlib.util.find_spec('scripts.assemble_notices') is not None, 'License assembly utility missing'
    from scripts.assemble_notices import assemble
    report=assemble(tmp_path)
    assert report['components'] and report['files']
    assert any(x['name'].lower()=='pyside6' for x in report['components'])
    assert all((tmp_path/x['path']).is_file() and len(x['sha256'])==64 for x in report['files'])
    assert json.loads((tmp_path/'inventory.json').read_text(encoding='utf8'))['files']==report['files']

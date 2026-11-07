import importlib.util
import pytest


def test_portable_release_rejects_stale_or_partial_acceptance():
    assert importlib.util.find_spec('scripts.release_bundle') is not None
    from scripts.release_bundle import validate_acceptance
    report={'passed':True,'exe_sha256':'a'*64,'checks':{'diagnostics':True,'voice':True,'ui100':True,'ui125':True,'ui150':True,'bundled_python':True}}
    validate_acceptance(report,'a'*64)
    with pytest.raises(ValueError):validate_acceptance(report,'b'*64)
    with pytest.raises(ValueError):validate_acceptance(dict(report,passed=False),'a'*64)
    with pytest.raises(ValueError):validate_acceptance(dict(report,checks={}), 'a'*64)


def test_manifest_detects_file_change(tmp_path):
    from scripts.release_bundle import manifest,verify_manifest
    (tmp_path/'file.txt').write_text('original')
    data=manifest(tmp_path)
    assert verify_manifest(tmp_path,data)==[]
    (tmp_path/'file.txt').write_text('changed')
    assert verify_manifest(tmp_path,data)==['file.txt']

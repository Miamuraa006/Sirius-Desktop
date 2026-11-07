"""Produce the shareable archive, containing only the installer and public docs."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

release = Path(sys.argv[1]).resolve()
files = ['Sirius-Setup-0.5.1.exe', 'ПРОЧИТАЙ МЕНЯ.txt', 'SHA256SUMS.txt']
archive_path = release / 'Sirius-0.5.1-Windows.zip'
digests = {}
with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_STORED) as archive:
    for name in files:
        with (release / name).open('rb') as stream:
            digests[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        archive.write(release / name, name)
with zipfile.ZipFile(archive_path) as archive:
    assert archive.namelist() == files
    assert archive.testzip() is None
    for name in files:
        with archive.open(name) as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == digests[name]
assert (release / 'SHA256SUMS.txt').read_text('ascii').split()[0] == digests[files[0]]
with archive_path.open('rb') as stream:
    archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
print(json.dumps({'archive': str(archive_path), 'bytes': archive_path.stat().st_size,
                  'sha256': archive_hash, 'files': digests, 'verified': True}, ensure_ascii=False, indent=2))

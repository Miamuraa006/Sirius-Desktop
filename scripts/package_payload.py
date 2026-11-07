"""Build a verified installer payload from the frozen application only."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile


def main():
    app, uninstaller, output = map(lambda p: Path(p).resolve(), sys.argv[1:])
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    forbidden = {'config.json', 'history.db', 'history.sqlite', 'diagnostics.log', 'portable.marker'}
    for file in sorted(app.rglob('*')):
        if file.is_symlink() or file.is_junction():
            raise ValueError(f'Linked payload entry: {file}')
        if file.is_file():
            relative = file.relative_to(app).as_posix()
            if relative == 'portable.marker':
                continue
            if file.name.casefold() in forbidden or file.suffix.casefold() in {'.wav', '.sqlite', '.sqlite3'}:
                raise ValueError(f'User data in application bundle: {relative}')
            rows.append((file, relative))
    rows.append((uninstaller, 'Uninstall.exe'))
    names = [name.casefold() for _, name in rows]
    assert len(names) == len(set(names))
    manifest, total = [], 0
    with zipfile.ZipFile(output / 'payload.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file, name in rows:
            digest = hashlib.file_digest(file.open('rb'), 'sha256').hexdigest()
            manifest.append(f'{digest}\t{name}')
            archive.write(file, name)
            total += file.stat().st_size
    (output / 'files.sha256').write_text('\n'.join(manifest) + '\n', encoding='utf8')
    with zipfile.ZipFile(output / 'payload.zip') as archive:
        assert archive.testzip() is None
        for line in manifest:
            digest, name = line.split('\t')
            with archive.open(name) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest, name
    report = {'files': len(rows), 'bytes': total, 'zip_bytes': (output / 'payload.zip').stat().st_size,
              'hashes_verified': True, 'personal_data_excluded': True, 'portable_marker_excluded': True}
    (output / 'payload-report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

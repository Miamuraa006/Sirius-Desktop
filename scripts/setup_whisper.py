"""Explicit one-time installation of the local CTranslate2 Small multilingual model."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen

REVISION = '536b0662742c02347bc0e980a01041f333bce120'
FILES = {
    'model.bin': '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671',
    'config.json': 'b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828',
    'tokenizer.json': 'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab',
    'vocabulary.txt': '34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913',
}


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Sirius/Speech/faster-whisper-small'
    root.mkdir(parents=True, exist_ok=True)
    for name, digest in FILES.items():
        path = root / name
        if path.is_file() and checksum(path) == digest:
            continue
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as temp:
            transfer = Path(temp.name)
        try:
            url = f'https://huggingface.co/Systran/faster-whisper-small/resolve/{REVISION}/{name}?download=true'
            with urlopen(url, timeout=90) as source, transfer.open('wb') as target:
                shutil.copyfileobj(source, target)
            if checksum(transfer) != digest:
                raise ValueError(f'Ошибка проверки SHA-256: {name}')
            transfer.replace(path)
        finally:
            transfer.unlink(missing_ok=True)
    print(f'Faster-Whisper Small готов: {root}')


if __name__ == '__main__':
    main()

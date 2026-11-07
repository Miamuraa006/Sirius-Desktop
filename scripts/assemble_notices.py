"""Copy installed distribution notices verbatim; generate a checked inventory."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import sys


def assemble(destination: Path):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    components=[]
    for dist in sorted(metadata.distributions(),key=lambda d:d.metadata.get('Name','').casefold()):
        name=dist.metadata.get('Name','unknown')
        safe=re.sub(r'[^A-Za-z0-9_.-]','_',name)
        folder=destination/safe
        folder.mkdir(exist_ok=True)
        license_files=[]
        for source in dist.files or []:
            # Use named text notice files; never bundle similarly named executables.
            basename=Path(str(source)).name.lower()
            if not (basename.startswith(('license','licence','copying','notice')) or '/licenses/' in str(source).lower()):
                continue
            actual=Path(dist.locate_file(source))
            if not actual.is_file() or actual.stat().st_size>2*1024*1024 or actual.suffix.lower() in ('.exe','.dll','.pyc'):
                continue
            target=folder/re.sub(r'[^A-Za-z0-9_.-]','_',str(source))
            shutil.copyfile(actual,target)
            license_files.append(target.name)
        text=dist.read_text('METADATA') or ''
        (folder/'METADATA.txt').write_text(text,encoding='utf8')
        components.append({'name':name,'version':dist.version,
                           'declared_license':dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'See metadata/upstream',
                           'license_files':license_files})
    python_dir=destination/'CPython'
    python_dir.mkdir(exist_ok=True)
    for name in ('LICENSE.txt','LICENSE'):
        source=Path(sys.base_prefix)/name
        if source.is_file():shutil.copyfile(source,python_dir/name)
    files=[]
    for path in sorted(destination.rglob('*')):
        if path.is_file() and path.name!='inventory.json':
            files.append({'path':path.relative_to(destination).as_posix(),'bytes':path.stat().st_size,
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    report={'python':sys.version,'components':components,'files':files}
    (destination/'inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    for record in files:
        actual=hashlib.sha256((destination/record['path']).read_bytes()).hexdigest()
        if actual!=record['sha256']:raise RuntimeError('License-copy verification failed')
    return report


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    report=assemble(root/'THIRD_PARTY_LICENSES')
    lines=['# Third-party notices / лицензии компонентов','',
           'Тексты из установленного окружения скопированы без изменения. inventory.json содержит их SHA-256.',
           'Список включает инструменты сборки и тестирования; наличие в этом списке не означает включение модуля в EXE.',
           'Qt/PySide6 поставляются как отдельные динамические библиотеки onedir. Их можно заменить совместимыми библиотеками; компоненты Qt используются по применимым LGPL/GPL/commercial условиям, указанным в их лицензиях.',
           'Содержимое исходного проекта и пользовательского визуального референса не объявляется автоматически лицензированным под лицензией сторонней библиотеки.','',
           '| Компонент | Версия | Заявленная лицензия |', '|---|---|---|']
    for c in report['components']:
        license_text=str(c['declared_license']).replace('\n',' ').replace('|','/')[:120]
        lines.append(f"| {c['name']} | {c['version']} | {license_text} |")
    lines += ['', '## Русская модель Vosk',
              'Встроенная модель скопирована из предоставленного проекта; её файлы и исходный путь зафиксированы в docs/legacy-manifest.json.',
              'Официальный каталог https://alphacephei.com/vosk/models указывает для vosk-model-small-ru-0.22 лицензию Apache 2.0. Метрики в bundled README совпадают с описанием этой модели; локальный hash сам по себе не удостоверяет upstream происхождение.',
              'Vosk API: https://github.com/alphacep/vosk-api — Apache-2.0; дополнительный текст лицензии находится в THIRD_PARTY_LICENSES/_external.',
              'PySide6/Qt: https://doc.qt.io/qtforpython-6/licenses.html ; https://www.qt.io/licensing/open-source-lgpl-obligations',
              'WMI: автор Tim Golden, MIT; исходный модуль и его metadata включены в notices, если пакет не содержит отдельного LICENSE.',
              'pypiwin32 — пакет перенаправления зависимости на pywin32; фактическая лицензия — в каталоге pywin32.', '']
    (root/'THIRD_PARTY_NOTICES.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({'components':len(report['components']),'license_and_metadata_files':len(report['files']),'verified':True}))

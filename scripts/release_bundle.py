"""Assemble portable/source archives only from hash-bound acceptance evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile

REQUIRED={'diagnostics','voice','ui100','ui125','ui150','bundled_python'}


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def validate_acceptance(report,exe_hash):
    if report.get('passed') is not True or report.get('exe_sha256')!=exe_hash:
        raise ValueError('Frozen acceptance is failed or belongs to another executable')
    checks=report.get('checks',{})
    if not REQUIRED.issubset(checks) or not all(checks[k] is True for k in REQUIRED):
        raise ValueError('Missing frozen acceptance checks')


def manifest(directory):
    root=Path(directory)
    rows=[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p)}
          for p in sorted(root.rglob('*')) if p.is_file() and p.name!='BUNDLE_MANIFEST.json']
    return {'files':rows,'file_count':len(rows),'bytes':sum(x['bytes'] for x in rows)}


def verify_manifest(directory,data):
    root=Path(directory)
    return [row['path'] for row in data['files'] if not (root/row['path']).is_file()
            or sha256(root/row['path'])!=row['sha256']]


def zip_paths(target,files):
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path,name in files:archive.write(path,name)
    with zipfile.ZipFile(target) as archive:
        bad=archive.testzip()
        if bad is not None:raise ValueError('Archive CRC mismatch: '+bad)
        return len(archive.infolist())


def assemble(root):
    root=Path(root).resolve(); bundle=root/'dist/Sirius'
    report=json.loads((root/'docs/FROZEN_ACCEPTANCE.json').read_text(encoding='utf8'))
    exe_hash=sha256(bundle/'Sirius.exe')
    validate_acceptance(report,exe_hash)
    for name in ('README.md','COMMANDS.md','THIRD_PARTY_NOTICES.md','requirements.txt'):
        shutil.copyfile(root/name,bundle/name)
    evidence=bundle/'verification';evidence.mkdir(exist_ok=True)
    for path in (root/'docs').iterdir():
        if path.is_file() and path.suffix in ('.md','.json','.xml'):
            shutil.copyfile(path,evidence/path.name)
    frozen_ui=Path(report['output_directory'])/'ui125'
    for name in ('mini.png','chat.png','pair.png','report.json'):
        shutil.copyfile(frozen_ui/name,evidence/('ui-'+name))
    data=manifest(bundle)
    (bundle/'BUNDLE_MANIFEST.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    mismatches=verify_manifest(bundle,data)
    if mismatches:raise ValueError('Bundle manifest mismatch')
    portable=root/'Sirius-Windows-Portable.zip'
    portable_entries=zip_paths(portable,[(p,'Sirius/'+p.relative_to(bundle).as_posix()) for p in sorted(bundle.rglob('*')) if p.is_file()])
    excluded={'.venv','.git','.qa','build','dist','__pycache__','.pytest_cache','.ruff_cache','releases'}
    source_files=[]
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if not p.is_file() or any(x in excluded for x in rel.parts) or p.suffix in ('.zip','.pyc'):
            continue
        source_files.append((p,'SIRIUS/'+rel.as_posix()))
    source=root/'Sirius-Foundation-Source.zip'
    source_entries=zip_paths(source,source_files)
    delivery={'exe_sha256':exe_hash,'bundle':data|{'files':'See BUNDLE_MANIFEST.json'},'bundle_mismatches':mismatches,
              'archives':[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha256(p),'entries':n,'crc_verified':True}
                          for p,n in ((portable,portable_entries),(source,source_entries))],
              'release_gates_all_passed':False,
              'note':'Verified portable build; human speech, clean offline Windows without installed Python and other untested hardware gates remain in TEST_REPORT.md.'}
    (root/'DELIVERY.json').write_text(json.dumps(delivery,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return delivery


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    print(json.dumps(assemble(args.root),ensure_ascii=False,indent=2))

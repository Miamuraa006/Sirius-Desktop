# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata, collect_dynamic_libs, collect_data_files
import comtypes.client
# Generate stable typelib modules during BUILD, never depend on runtime codegen.
comtypes.client.GetModule('UIAutomationCore.dll')
root=Path(SPECPATH).parent
vosk_data,vosk_bins,vosk_hidden=collect_all('vosk')
hidden=vosk_hidden + collect_submodules('skills') + collect_submodules('voice') + collect_submodules('comtypes.gen')
hidden += ['pycaw.pycaw','screen_brightness_control','wmi','pythoncom','pywintypes',
           'win32com.client','win32com.client.dynamic','win32com.shell.shell','win32com.shell.shellcon','win32timezone',
           'win32clipboard','win32api','win32con','win32gui','win32process',
           'winrt.windows.media.control','winrt.windows.foundation',
           'winrt.windows.foundation.collections','winrt.windows.storage.streams',
           'PySide6.QtSvg','PySide6.QtQuick','PIL.ImageGrab','comtypes.stream']
datas=vosk_data+[(str(root/'ui/qml'),'ui/qml'),(str(root/'ui/assets'),'ui/assets'),(str(root/'ui/shaders'),'ui/shaders'),
                (str(root/'config/defaults.json'),'config'),(str(root/'models/ru_vosk'),'models/ru_vosk')]
for package in ('vosk','sounddevice','PySide6','pywin32','psutil'):
    datas += copy_metadata(package)
for p in (root/'skills').glob('*/phrases.json'):
    datas.append((str(p),str(p.parent.relative_to(root))))
vosk_bins.extend(collect_dynamic_libs('soxr'))
if (root/'THIRD_PARTY_LICENSES').exists():
    datas.append((str(root/'THIRD_PARTY_LICENSES'),'THIRD_PARTY_LICENSES'))
for name in ('README.md','UI_FACE.md','COMMANDS.md','THIRD_PARTY_NOTICES.md','requirements.txt'):
    if (root/name).exists():datas.append((str(root/name),'.'))
a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=vosk_bins,datas=datas,
           hiddenimports=hidden,hookspath=[],runtime_hooks=[],
           excludes=['faster_whisper','ctranslate2','onnxruntime','tokenizers','av','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick',
                     'PySide6.QtPdf','PySide6.QtPdfWidgets','PySide6.QtCharts','PySide6.QtGraphs',
                     'PySide6.Qt3DCore','PySide6.Qt3DRender','PySide6.Qt3DInput','PySide6.Qt3DExtras',
                     'tkinter','pytest','ruff'],noarchive=False)
if any('CodexPrimaryRuntime' in str(entry[1]) for entry in a.binaries):
    raise RuntimeError('Build PATH contains unrelated Codex tool DLLs; use scripts/build_desktop.ps1')
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Sirius',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        disable_windowed_traceback=False,icon=str(root/'ui/assets/sirius.ico') if (root/'ui/assets/sirius.ico').exists() else None,
        version=str(root/'packaging/version_info.txt'),
        manifest=str(root/'packaging/windows.manifest'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='app')

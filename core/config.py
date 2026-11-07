"""Validated per-user settings; no network, secrets, or writes in bundle resources."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
from urllib.parse import urlsplit

_LOCK = threading.RLock()

def resource_root() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))

def default_data_dir() -> Path:
    # This desktop edition owns its data, separate from every older Sirius build.
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).resolve().parent
        if (app_dir / 'portable.marker').is_file():
            return app_dir.parent / 'data'
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Sirius' / 'UserData'
    return Path(__file__).resolve().parents[2] / 'data'

def _text(value):
    return isinstance(value,str) and 0 < len(value) <= 4096 and not any(ord(c)<32 for c in value)

def _merge(defaults, provided, prefix=''):
    if not isinstance(provided,dict):
        raise ValueError(f'Настройка {prefix or "config"} должна быть объектом JSON.')
    result=deepcopy(defaults)
    for key,value in provided.items():
        if key not in defaults:
            raise ValueError(f'Неизвестная настройка: {prefix}{key}. Файл не изменён.')
        if key=='applications' and not prefix:
            if not isinstance(value,dict) or len(value)>100:
                raise ValueError('Неверный список приложений.')
            for name,entry in value.items():
                if not _text(name) or not isinstance(entry,dict) or set(entry)-{'command','process_names','aliases'}:
                    raise ValueError('Неверная регистрация приложения.')
                for field in ('command','process_names'):
                    if not isinstance(entry.get(field),list) or not entry[field] or not all(_text(s) for s in entry[field]):
                        raise ValueError('command/process_names должны быть непустыми списками строк.')
                if not isinstance(entry.get('aliases',[]),list) or not all(_text(s) for s in entry.get('aliases',[])):
                    raise ValueError('aliases должен быть списком строк.')
            result[key]=deepcopy(value)
        elif isinstance(defaults[key],dict):
            result[key]=_merge(defaults[key],value,prefix+key+'.')
        else:
            expected=defaults[key]
            if expected is None:
                valid=value is None or (type(value) is int and value>=0) or _text(value)
            elif type(expected) is float:
                valid=type(value) in (int,float)
            elif isinstance(expected,list):
                valid=isinstance(value,list) and len(value)<=100 and all(_text(v) for v in value)
            else:
                valid=type(value) is type(expected)
                if isinstance(value,str):valid &= _text(value)
            if not valid:
                raise ValueError(f'Неверный тип настройки {prefix}{key}.')
            result[key]=value
    return result

def validate(config: dict, root: Path | None = None):
    root=root or resource_root()
    defaults=json.loads((root/'config'/'defaults.json').read_text(encoding='utf8'))
    data=_merge(defaults,config)
    voice=data['voice']; hotkey=data['hotkey']
    # Retired material: old settings must still open without losing other choices.
    if data['ui']['theme'] in {'clear', 'blue'}:
        data['ui']['theme'] = 'dark'
    if data['ui']['theme'] != 'dark':
        raise ValueError('Тема должна быть dark.')
    if voice['command_decoder'] in {'auto', 'faster-whisper'}:
        voice['command_decoder'] = 'vosk'
    if voice['command_decoder'] not in {'auto', 'vosk', 'faster-whisper'}:
        raise ValueError('voice.command_decoder должен быть auto, faster-whisper или vosk.')
    if voice['active_seconds'] != 60:
        raise ValueError('В Foundation активное окно речи равно 60 секундам.')
    if voice['sample_rate'] not in (16000,32000,44100,48000) or not 0.5 <= voice['min_confidence'] <= 1:
        raise ValueError('Недопустимые параметры распознавания.')
    model=Path(voice['model_path'])
    if str(model).startswith(('\\','//')) or '..' in model.parts:
        raise ValueError('Модель должна находиться в локальном каталоге.')
    if not 1 <= data['history']['retention_days'] <= 3650:
        raise ValueError('Срок истории должен быть от 1 до 3650 дней.')
    if (type(hotkey['key']) is not int or not 1 <= hotkey['key'] <= 254
            or type(hotkey['modifiers']) is not int or not 1 <= hotkey['modifiers'] <= 15):
        raise ValueError('Некорректная глобальная комбинация.')
    if data['brightness']['display'] < 0:
        raise ValueError('Неверный индекс дисплея.')
    url=data['browser']['search_url']
    parts=urlsplit(url.replace('{query}','probe'))
    if url.count('{query}') != 1 or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Поиск требует HTTPS URL с единственным {query}, без встроенных credentials.')
    # Registration validators are imported lazily, without initializing native APIs.
    if data['applications']:
        from skills.applications.registry import app_registry
        app_registry(data)
    for field in ('root',):
        data['files'][field]=os.path.expandvars(data['files'][field])
    data['files']['allowed_roots']=[os.path.expandvars(p) for p in data['files']['allowed_roots']]
    data['screenshot']['directory']=os.path.expandvars(data['screenshot']['directory'])
    return data

def _read(path):
    try:
        if path.stat().st_size>1024*1024:
            raise ValueError('Файл config.json слишком большой; файл не изменён.')
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('config.json повреждён. Он сохранён без изменений; исправьте JSON или переименуйте файл.') from exc

def load_config(data_dir: Path | None = None, *, root: Path | None = None):
    root=(root or resource_root()).resolve()
    data_dir=Path(data_dir or default_data_dir()).resolve()
    with _LOCK:
        data_dir.mkdir(parents=True,exist_ok=True)
        path=data_dir/'config.json'
        saved = _read(path) if path.exists() else {}
        config=validate(saved,root)
        if not path.exists() or saved.get('ui', {}).get('theme') in {'clear', 'blue'}:
            save_config(data_dir,config,root=root)
        config['_resource_root']=str(root)
        config['_data_dir']=str(data_dir)
        return config

def save_config(data_dir: Path, config: dict, *, root: Path | None = None):
    root=root or resource_root()
    with _LOCK:
        path=Path(data_dir)/'config.json'
        if path.exists():
            validate(_read(path),root)  # Never silently overwrite a corrupt file.
        config=validate({k:v for k,v in config.items() if not k.startswith('_')},root)
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=None
        try:
            with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=path.parent,prefix='.config-',suffix='.tmp',delete=False) as f:
                temp=Path(f.name)
                json.dump(config,f,ensure_ascii=False,indent=2)
                f.write('\n');f.flush();os.fsync(f.fileno())
            os.replace(temp,path)
        finally:
            if temp and temp.exists():temp.unlink()

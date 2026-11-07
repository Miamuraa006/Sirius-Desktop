"""Fail-closed path policy and expiring, session-bound, single-use approvals."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat
import time
from core.models import Intent, Result

EXECUTABLE_SUFFIXES = {'.exe','.com','.bat','.cmd','.ps1','.psm1','.vbs','.vbe','.js','.jse',
                       '.wsf','.wsh','.hta','.lnk','.url','.scr','.msi','.reg','.cpl','.msc','.dll'}
RESERVED = re.compile(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def trusted_root(path: Path, roots) -> Path | None:
    """One longest-prefix resolver shared by preparation and execution."""
    return max((r for r in roots if path.is_relative_to(r)), key=lambda r:len(r.parts), default=None)


def fingerprint(path: Path):
    if not path.exists():
        return None
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)


@dataclass(frozen=True)
class Pending:
    intent: Intent
    expires_at: float
    fingerprints: dict


class PermissionPolicy:
    def __init__(self, config: dict, clock=time.monotonic):
        self.config = config
        files = config.get('files', {})
        self.root = expand_path(files.get('root', str(Path.home()/'Documents'/'Sirius'))).resolve()
        self.allowed = [expand_path(s).resolve() for s in files.get('allowed_roots', [str(self.root)])]
        if self.root not in self.allowed:
            self.allowed.append(self.root)
        self.clock = clock
        self.pending: dict[str, Pending] = {}

    def checked_path(self, raw: str, *, base: Path | None = None) -> Path:
        if not isinstance(raw, str) or not raw or len(raw) > 240 or any(ord(c)<32 for c in raw):
            raise ValueError('Некорректный путь.')
        if raw.startswith(('\\\\', '//', '\\?', '\\.')) or '%' in raw or '~' in raw:
            raise ValueError('Сетевые, специальные пути и переменные в командах запрещены.')
        p = Path(raw)
        if '..' in p.parts or ':' in raw[2:] or (':' in raw and not re.match(r'^[a-zA-Z]:[\\/]',raw)):
            raise ValueError('Выход через .., потоки NTFS и пути устройств запрещены.')
        for part in p.parts:
            if part in (p.anchor, p.drive, '\\', '/'):
                continue
            if part.endswith((' ', '.')) or RESERVED.match(part) or any(c in part for c in '*?<>|"'):
                raise ValueError('Недопустимое имя файла Windows.')
        if not p.is_absolute():
            p = (base or self.root) / p
        # Resolve only after checking every ancestor for links/reparse points.
        for ancestor in (p, *p.parents):
            try:
                s = ancestor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Ссылки и junction/reparse points не разрешены.')
        p = p.resolve()
        protected = [expand_path(os.environ.get('WINDIR','C:/Windows')),
                     expand_path(os.environ.get('ProgramFiles','C:/Program Files')),
                     expand_path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))]
        if p == Path(p.anchor) or any(p.is_relative_to(d.resolve()) for d in protected):
            raise ValueError('Системные каталоги защищены.')
        return p

    def _prepare_paths(self, intent: Intent):
        params = deepcopy(intent.parameters)
        paths = {}
        if intent.skill == 'files':
            if intent.action not in ('mkdir','touch','open','trash','rename','move'):
                raise ValueError('Недопустимое файловое действие.')
            source = self.checked_path(params.get('path',''))
            params['path'] = str(source)
            paths['path'] = source
            if intent.action == 'open' and source.suffix.lower() in EXECUTABLE_SUFFIXES:
                raise ValueError('Запуск исполняемых файлов через файловые команды запрещён. Зарегистрируйте приложение.')
            if intent.action == 'touch' and source.suffix.lower() != '.txt':
                raise ValueError('Создать можно только пустой файл .txt.')
            if intent.action in ('rename','move'):
                base = source.parent if intent.action == 'rename' else self.root
                destination = self.checked_path(params.get('destination',''),base=base)
                if destination.exists():
                    raise ValueError('Цель уже существует: перезапись в v0.3 запрещена. Выберите другое имя.')
                params['destination'] = str(destination)
                paths['destination'] = destination
            if intent.action in ('mkdir','touch') and source.exists():
                raise ValueError('Путь уже существует; существующие данные не перезаписываются.')
            if intent.action in ('trash','rename','move') and source in self.allowed:
                raise ValueError('Корневые доверенные папки защищены от изменения.')
        return Intent(intent.skill,intent.action,params,intent.context_reference), paths

    def prepare(self, intent: Intent, session_id: str) -> Result | None:
        self.pending.pop(session_id, None)
        try:
            prepared, paths = self._prepare_paths(intent)
        except (ValueError, OSError) as exc:
            return Result.fail(str(exc) if isinstance(exc,ValueError) else 'Путь недоступен для проверки.')
        needs = intent.skill == 'applications' and intent.action in ('close','close_app','restart')
        if needs:
            from skills.applications.catalog import resolve_app, protected
            name = intent.parameters.get('app')
            if isinstance(name, str) and protected(name):
                return Result.fail('Эта программа защищена от закрытия.')
            if not isinstance(name, str) or not name.strip() or resolve_app(name, self.config) is None:
                return Result.fail('Приложение не зарегистрировано в разрешенном списке.')
        needs |= intent.skill == 'power'
        needs |= intent.skill == 'files' and intent.action == 'trash'
        roots = []
        for path in paths.values():
            root = trusted_root(path,self.allowed)
            roots.append(root)
            needs |= root is None
        if len(roots) > 1 and roots[0] != roots[1]:
            needs = True
        if not needs:
            return None
        self.pending[session_id] = Pending(prepared, self.clock()+60,
                                           {str(p):fingerprint(p) for p in paths.values()})
        if intent.skill == 'applications':
            verb = 'Закрыть' if intent.action in ('close', 'close_app') else 'Перезапустить'
            summary = f'{verb} приложение «{prepared.parameters.get("app", "")}»? После закрытия окон может быть завершён его фоновый процесс.'
        elif intent.skill == 'power':
            summary = {'shutdown': 'Выключить ноутбук сейчас?', 'restart': 'Перезагрузить ноутбук сейчас?'}[intent.action]
        else:
            verbs = {'trash':'Переместить в корзину','rename':'Переименовать','move':'Переместить','open':'Открыть','touch':'Создать .txt','mkdir':'Создать папку'}
            summary = f'{verbs[intent.action]} «{prepared.parameters["path"]}»'
            if 'destination' in prepared.parameters:
                summary += f' → «{prepared.parameters["destination"]}»'
            summary += '?'
        details = {'presentation': 'question', 'spoken_question': summary} if intent.skill == 'power' else {}
        return Result('needs_confirmation',summary+' Ответьте «да» или «нет». Подтверждение действует 60 секунд.', details=details)

    def prepared_intent(self, intent: Intent) -> Intent:
        return self._prepare_paths(intent)[0]

    def awaiting_reply(self, session_id: str) -> bool:
        item = self.pending.get(session_id)
        return item is not None and self.clock() < item.expires_at

    def resolve(self, session_id: str, approve: bool) -> tuple[Intent | None, Result | None]:
        item = self.pending.pop(session_id, None)
        if item is None:
            return None, Result.fail('Нет ожидающего подтверждения в этой сессии.')
        if not approve:
            return None, Result.ok('Действие отменено; выполнение не запускалось.', cancelled=True)
        if self.clock() >= item.expires_at:
            return None, Result.fail('Срок подтверждения истёк. Повторите команду.')
        try:
            intent, paths = self._prepare_paths(item.intent)
            if any(fingerprint(p) != item.fingerprints[str(p)] for p in paths.values()):
                return None, Result.fail('Файл изменился после запроса. Подтверждение отменено.')
        except (ValueError,OSError):
            return None, Result.fail('Условия операции изменились. Повторите команду.')
        return intent, None

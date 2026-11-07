"""One serialized, auditable pipeline for both speech and text."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import logging
import threading
import time
from core.context import Context
from core.replies import parse_reply
from core.help import is_help, capability_guide
from core.intent_router import IntentRouter
from core.models import Command, Intent, Result
from security.permissions import PermissionPolicy
from security.privacy import display_command
from storage.history import History

LOG=logging.getLogger('sirius.core')

class Engine:
    def __init__(self, config: dict, data_dir: Path, event_callback=None, registry=None):
        self.config=config
        root=Path(config.get('_resource_root',Path(__file__).resolve().parents[1]))
        self.router=IntentRouter(root/'skills',config)
        if registry is None:
            from core.skill_registry import SkillRegistry
            registry=SkillRegistry(config)
        self.registry=registry
        self.policy=PermissionPolicy(config)
        options=config.get('history',{})
        self.history=History(Path(data_dir)/'history.sqlite3',options.get('enabled',True),options.get('retention_days',30))
        self.event_callback=event_callback
        self.contexts=OrderedDict()
        self.lock=threading.RLock()
        self.targets_lock=threading.Lock()
        self.targets={}
        self.closed=False

    def set_window_context(self, hwnd: int, pid: int | None = None, session_id='desktop'):
        # UI publishes a previously observed external foreground window, never a random window.
        with self.targets_lock:
            self.targets[session_id]=(int(hwnd),pid)

    def _context(self, session_id):
        if session_id not in self.contexts:
            if len(self.contexts)>=64:
                removed,_=self.contexts.popitem(last=False)
                self.policy.pending.pop(removed,None)
            self.contexts[session_id]=Context(session_id=session_id)
        ctx=self.contexts[session_id]
        with self.targets_lock:
            target=self.targets.get(session_id)
        if target:
            ctx.last_window=target[0]
            ctx.data['window_pid']=target[1]
            ctx.data['last_window_pid']=target[1]
            ctx.data.pop('last_window_created',None)
        return ctx

    def recognizes(self,text: str, session_id='desktop') -> bool:
        if parse_reply(text) is not None:
            with self.lock:
                ctx = self.contexts.get(session_id)
                if ctx and ctx.question and ctx.question.is_active():
                    return True
                return self.policy.awaiting_reply(session_id)
        if is_help(text):
            return True
        intent = self.router.parse(text)
        if intent and intent.skill == 'applications' and intent.action != 'list':
            from skills.applications.catalog import resolve_app
            name = intent.parameters.get('app', '').strip().casefold()
            if name not in ('его', 'ее', 'её', 'последнее приложение', 'последнюю программу'):
                return resolve_app(name, self.config) is not None
        return intent is not None

    def _emit(self,event):
        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception:
                LOG.error('Event subscriber failed (payload not logged)')

    def _base_event(self,command,intent):
        text=display_command(command.text,intent)
        return dict(text=text,source=command.source,session_id=command.session_id,
                    time=datetime.now(timezone.utc).isoformat(),skill=intent.skill if intent else '')

    def _finish(self,command,event,result,started):
        details=dict(result.details)
        details['total_ms']=round((time.perf_counter()-started)*1000,3)
        result=replace(result,details=details)
        safe_command=replace(command,text=event['text'])
        try:
            self.history.append(safe_command,event['skill'],result,event['time'])
        except Exception:
            LOG.error('History write failed (payload not logged)')
            # Executed operation remains truthful; failure to persist is visible.
            result=replace(result,message=result.message+' Историю сохранить не удалось.')
        event_type='completed' if result.status in ('success','needs_confirmation') else 'error'
        self._emit(dict(event,type=event_type,result=result.to_dict()))
        return result

    def execute(self, command: Command) -> Result:
        with self.lock:
            started=time.perf_counter()
            if self.closed:
                return Result.fail('Ядро завершено.')
            context=self._context(command.session_id)
            question, context.question = context.question, None
            if is_help(command.text):
                pending = self.policy.pending.get(command.session_id)
                if pending and pending.intent.skill == "power":
                    self.policy.pending.pop(command.session_id, None)
                command = replace(command, text='help')
                event = self._base_event(command, Intent('help', 'show'))
                self._emit(dict(event, type='recognized'))
                message, skills = capability_guide(self.config, self.registry)
                result = Result.ok(message, presentation='help', available_skills=skills)
                return self._finish(command, event, result, started)
            answer=parse_reply(command.text)
            confirmed=False
            if answer is not None and question and question.is_active():
                self.policy.pending.pop(command.session_id,None)
                intent=question.yes
                result=None if answer else Result.ok('Хорошо, оставляю плеер как есть.', declined=True)
            elif answer is not None and command.session_id in self.policy.pending:
                pending = self.policy.pending[command.session_id]
                if (answer and pending.intent.skill == 'power' and
                        command.text.strip().casefold().rstrip('.!') not in {'да', 'да да', 'да-да', 'да, да', 'подтверждаю'}):
                    intent, result = None, Result('needs_confirmation', 'Для управления питанием ответьте «да» или «нет».')
                else:
                    intent,result=self.policy.resolve(command.session_id,answer)
                confirmed=intent is not None
            else:
                self.policy.pending.pop(command.session_id,None)
                intent=self.router.parse(command.text,context)
                result=None
            route_ms=(time.perf_counter()-started)*1000
            if intent is None and result is None:
                result=Result('not_understood','Команда не распознана. Напишите help, чтобы посмотреть возможности и примеры команд.')
                if command.source=='voice':
                    return result
            if intent and intent.skill=='applications' and str(intent.parameters.get('app','')).casefold() in ('его','ее','её','последнее приложение','последнюю программу'):
                if context.last_app:
                    intent=replace(intent,parameters=dict(intent.parameters,app=context.last_app),context_reference=context.last_app)
                else:
                    result=Result.fail('Нет однозначно известного последнего приложения. Укажите программу.')
            event=self._base_event(command,intent)
            self._emit(dict(event,type='recognized'))
            if result is not None:
                return self._finish(command,event,result,started)
            if not confirmed:
                decision=self.policy.prepare(intent,command.session_id)
                if decision is not None:
                    return self._finish(command,event,decision,started)
                try:
                    intent=self.policy.prepared_intent(intent)
                except (ValueError,OSError):
                    return self._finish(command,event,Result.fail('Путь изменился или недоступен.'),started)
            self._emit(dict(event,type='started'))
            execution_start=time.perf_counter()
            if confirmed:
                context.data['confirmed']=True
                if intent.skill=='files':
                    context.data['file_grant']=tuple(str(v) for k,v in intent.parameters.items() if k in ('path','destination'))
            try:
                handler=self.registry.get(intent.skill)
                if handler is None:
                    result=Result.unsupported('Навык не установлен.')
                else:
                    result=handler.execute(intent,context)
                    if not isinstance(result,Result):
                        result=Result.fail('Обработчик вернул неверный формат ответа.')
            except Exception as exc:
                LOG.error('Skill %s failed: %s (details suppressed)',intent.skill,type(exc).__name__)
                result=Result.fail('Ошибка Windows или устройства. Повторите команду; подробности без личных данных в журнале диагностики.')
            finally:
                context.data.pop('confirmed',None)
                context.data.pop('file_grant',None)
            if result.verified:
                context.last_skill=intent.skill
                context.last_action=intent.action
            if intent.skill=='applications' and intent.action in ('open','open_app','focus_app','restart'):
                # After a failed switch, a pronoun must not close a different, earlier app.
                context.last_app=result.details.get('app',intent.parameters.get('app')) if result.verified else None
            if intent.skill=='clipboard':
                allowed=('has_text','length','characters','format','hwnd','target')
                result=replace(result,details={k:v for k,v in result.details.items() if k in allowed})
            result=replace(result,details=dict(result.details,route_ms=round(route_ms,3),execution_ms=round((time.perf_counter()-execution_start)*1000,3)))
            return self._finish(command,event,result,started)

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed=True
                self.policy.pending.clear()
                self.history.close()

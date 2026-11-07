"""Confirmed Windows power requests. No forced closure of applications."""
import os
from pathlib import Path
import subprocess

from core.models import Result


def request_power(action):
    executable = Path(os.environ['SystemRoot']) / 'System32' / 'shutdown.exe'
    option = {'shutdown': '/s', 'restart': '/r'}[action]
    subprocess.run([str(executable), option, '/t', '0'], check=True, timeout=6,
                   creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)


class Handler:
    def __init__(self, adapter=None, config=None):
        self.adapter = adapter or request_power

    def execute(self, intent, context):
        if intent.action not in ('shutdown', 'restart'):
            return Result.fail('Неизвестная команда питания.')
        if context.data.get('confirmed') is not True:
            return Result('needs_confirmation', 'Сначала подтвердите действие в текущем диалоге.')
        try:
            self.adapter(intent.action)
        except (OSError, subprocess.SubprocessError):
            return Result.fail('Windows отклонила запрос управления питанием.')
        message = 'выключение' if intent.action == 'shutdown' else 'перезагрузку'
        return Result.ok(f'Windows приняла запрос на {message} ноутбука.')

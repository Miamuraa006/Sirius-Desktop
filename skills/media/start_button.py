"""Cold-start a player through a labelled button in the window Sirius just opened."""
import time
from pathlib import Path

from skills.windows.automation import UIAutomation
from skills.windows.native import NativeUnavailable, WindowsAdapter


def invoke_play_button(target):
    windows = WindowsAdapter()
    window = windows.window(target['hwnd'])
    if (window is None or window.pid != target['pid'] or window.created != target['created']
            or Path(window.executable) != Path(target['executable'])):
        raise NativeUnavailable('Окно плеера изменилось. Откройте приложение снова.')
    with UIAutomation() as api:
        root = api.api.ElementFromHandle(window.hwnd)
        button_type = api.api.CreatePropertyCondition(30003, 50000)
        def playing():
            windows.require(window)
            for label in ('Пауза', 'Приостановить воспроизведение', 'Pause'):
                cond = api.api.CreateAndCondition(button_type, api.api.CreatePropertyCondition(30005, label))
                items = root.FindAll(4, cond)
                if items.Length == 1 and not items.GetElement(0).CurrentIsOffscreen:
                    return True
            return False
        if playing():
            return True
        deadline = time.monotonic() + 6
        while True:
            for label in target['play_buttons']:
                condition = api.api.CreateAndCondition(button_type, api.api.CreatePropertyCondition(30005, label))
                matches = root.FindAll(4, condition)
                buttons = [matches.GetElement(i) for i in range(matches.Length)]
                available = [b for b in buttons if b.CurrentIsEnabled and not b.CurrentIsOffscreen]
                if len(available) != 1:
                    continue
                button = available[0]
                invoke = api.pattern(button, 10000, 'IUIAutomationInvokePattern')
                if invoke and button.CurrentName == label:
                    windows.require(window)
                    invoke.Invoke()
                    # Some Electron players update the button before publishing a Windows session.
                    until = time.monotonic() + 1.2
                    while time.monotonic() < until:
                        windows.require(window)
                        try:
                            if playing() or (button.CurrentName or '').casefold() in {'пауза', 'приостановить', 'pause'}:
                                return True
                        except OSError:
                            break  # The UI replaced the element; GSMTC can still verify playback.
                        time.sleep(.08)
                    return False
            if time.monotonic() >= deadline:
                break
            time.sleep(.15)
    raise NativeUnavailable('Плеер не показывает доступную кнопку воспроизведения. Выберите трек в приложении.')

# Third-party notices / лицензии компонентов

Тексты из установленного окружения скопированы без изменения. inventory.json содержит их SHA-256.
Список включает инструменты сборки и тестирования; наличие в этом списке не означает включение модуля в EXE.
Qt/PySide6 поставляются как отдельные динамические библиотеки onedir. Их можно заменить совместимыми библиотеками; компоненты Qt используются по применимым LGPL/GPL/commercial условиям, указанным в их лицензиях.
Содержимое исходного проекта и пользовательского визуального референса не объявляется автоматически лицензированным под лицензией сторонней библиотеки.

| Компонент | Версия | Заявленная лицензия |
|---|---|---|
| altgraph | 0.17.5 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.2 | MIT |
| colorama | 0.4.6 | See metadata/upstream |
| comtypes | 1.4.17 | MIT |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pefile | 2024.8.26 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| pluggy | 1.7.0 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| pycaw | 20260927 | MIT |
| pycparser | 3.12 | BSD-3-Clause |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyinstaller | 6.22.3 | GPLv2-or-later with a special exception which allows to use PyInstaller to build and distribute non-free programs (inclu |
| pyinstaller-hooks-contrib | 2026.9 | See metadata/upstream |
| pypiwin32 | 223 | UNKNOWN |
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Addons | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Pdf | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_WebEngine | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pytest | 9.1.1 | MIT |
| pytest-timeout | 2.4.0 | MIT |
| pywin32 | 312 | PSF |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| requests | 2.34.2 | Apache-2.0 |
| ruff | 0.17.2 | MIT |
| screen_brightness_control | 0.27.2 | MIT |
| Send2Trash | 2.1.0 | BSD-3-Clause |
| setuptools | 84.2.1 | MIT |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| sounddevice | 0.5.6 | MIT |
| srt | 3.5.3 | MIT |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| vosk | 0.3.45 | UNKNOWN |
| websockets | 17.3 | BSD-3-Clause |
| winrt-runtime | 4.0.3 | MIT |
| winrt-Windows.Foundation | 4!10.0.28000.2705 | MIT |
| winrt-Windows.Foundation.Collections | 4!10.0.28000.2705 | MIT |
| winrt-Windows.Media.Control | 4!10.0.28000.2705 | MIT |
| winrt-Windows.Storage.Streams | 4!10.0.28000.2705 | MIT |
| WMI | 1.5.1 | http://www.opensource.org/licenses/mit-license.php |

## Русская модель Vosk
Встроенная модель скопирована из предоставленного проекта; её файлы и исходный путь зафиксированы в docs/legacy-manifest.json.
Официальный каталог https://alphacephei.com/vosk/models указывает для vosk-model-small-ru-0.22 лицензию Apache 2.0. Метрики в bundled README совпадают с описанием этой модели; локальный hash сам по себе не удостоверяет upstream происхождение.
Vosk API: https://github.com/alphacep/vosk-api — Apache-2.0; дополнительный текст лицензии находится в THIRD_PARTY_LICENSES/_external.
PySide6/Qt: https://doc.qt.io/qtforpython-6/licenses.html ; https://www.qt.io/licensing/open-source-lgpl-obligations
WMI: автор Tim Golden, MIT; исходный модуль и его metadata включены в notices, если пакет не содержит отдельного LICENSE.
pypiwin32 — пакет перенаправления зависимости на pywin32; фактическая лицензия — в каталоге pywin32.

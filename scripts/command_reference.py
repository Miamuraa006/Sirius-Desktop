"""Generate exact reference from shipped grammars; no second vocabulary."""
from pathlib import Path
import json


def render(root):
    root=Path(root)
    counts={'skills':0,'rules':0,'examples':0}
    lines=['# Команды Sirius Desktop','',
           'Создано из `skills/*/phrases.json`. Каждый пример проходит full-match роутер в автотестах.',
           'Числа для процентов могут быть цифрами или русскими словами. Контекст и политика разрешений проверяются после разбора.',
           'Для подтверждения скажите «да», «давай» или «го». Для отмены — «нет», «не надо» или «отмена».','']
    for path in sorted((root/'skills').glob('*/phrases.json')):
        data=json.loads(path.read_text(encoding='utf8'))
        counts['skills']+=1
        lines += [f"## {data['skill']}",'','| Действие | Параметры по умолчанию | Примеры формулировок |','|---|---|---|']
        for rule in data['rules']:
            counts['rules']+=1
            counts['examples']+=len(rule.get('examples',[]))
            examples='<br>'.join('`'+x.replace('|','&#124;')+'`' for x in rule.get('examples',[]))
            params=json.dumps(rule.get('parameters',{}),ensure_ascii=False).replace('|','&#124;')
            lines.append(f"| `{rule['action']}` | `{params}` | {examples} |")
        lines += ['', '<details><summary>Точные регулярные грамматики</summary>','', '```json',
                  json.dumps(data['rules'],ensure_ascii=False,indent=2),'```','</details>','']
    lines += ['## Итог',f"{counts['skills']} навыков; {counts['rules']} правил; {counts['examples']} примеров.",
              'Наличие примера не отменяет необходимость подходящего устройства, окна и подтверждения. Неподдерживаемое действие не выдаётся за выполненное.','']
    return '\n'.join(lines),counts


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    text,counts=render(root)
    (root/'COMMANDS.md').write_text(text,encoding='utf8')
    print(json.dumps(counts))

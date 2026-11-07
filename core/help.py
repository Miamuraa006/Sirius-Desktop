"""Local capability guide; displaying it never executes a device action."""
import re
from core.capabilities import ENTRIES

_REQUEST = re.compile(r"\s*(?:/?help|хелп|хэлп|помощь|справка|что (?:ты )?умеешь)[.!?\s]*", re.IGNORECASE)



def is_help(text):
    return isinstance(text, str) and len(text) <= 100 and _REQUEST.fullmatch(text) is not None


def capability_guide(config, available):
    rows = ["Что умеет Sirius", ""]
    skills = []
    for skill, title, example in ENTRIES:
        if skill not in available:
            continue
        skills.append(skill)
        rows.append(f"✓ {title} — «{example}»")
        if skill == "applications":
            from skills.applications.registry import app_registry
            apps = app_registry(config)
            names = {spec.name: (spec.aliases[0] if spec.aliases else spec.name) for spec in apps.values()}
            rows.append("Можно открыть: " + ", ".join(names.values()) + ".")
    rows.extend([
        "\nГолос: Alt + M или «Сириус», затем команда.\nСкажите «хелп» — откроется этот список.",
        "\nЧтобы согласиться, скажите «да», «давай» или «го». Чтобы отказаться — «нет», «не надо» или «отмена».",
    ])
    return "\n".join(rows), skills

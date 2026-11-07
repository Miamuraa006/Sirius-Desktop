from importlib import import_module
from core.intent_router import SKILL_IDS

class SkillRegistry(dict):
    """Explicit allowlist, not dynamic discovery/execution of arbitrary plugins."""
    def __init__(self, config=None):
        super().__init__()
        for skill in SKILL_IDS:
            module=import_module(f'skills.{skill}.handler')
            self[skill]=module.Handler(config=config or {})
        if tuple(self) != SKILL_IDS:
            raise RuntimeError('Registry differs from the approved skills')

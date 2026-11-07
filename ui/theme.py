"""The single black-glass material, independent of activation state."""
from PySide6.QtCore import QObject, Property, Signal, Slot

LABELS = {"dark": "Чёрное стекло"}
PALETTES = {
    "dark": dict(top="#ed202229", middle="#f0080b12", bottom="#e51b202b",
                 edge="#719ba9bc", shine="#bedee9fc", accent="#a2b9ff",
                 text="#eff2ff", muted="#9aa5bd", row="#b0131722", reply="#c0101420",
                 rowEdge="#494f5c72", input="#d00c1019", button="#e237405b"),
}


class Appearance(QObject):
    changed = Signal()
    saveFailed = Signal(str)

    def __init__(self, mode="dark", persist=None, parent=None):
        super().__init__(parent)
        self._mode = "dark"
        self._persist = persist

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Property(str, notify=changed)
    def label(self):
        return LABELS[self._mode]

    @Property("QVariantMap", notify=changed)
    def colors(self):
        return dict(PALETTES[self._mode])

    @Slot(str, result=bool)
    def select(self, mode):
        if mode not in PALETTES:
            return False
        if mode == self._mode:
            return True
        # Persist first: do not display a successful selection if the write failed.
        if self._persist:
            try:
                self._persist(mode)
            except (OSError, ValueError):
                self.saveFailed.emit("Не удалось сохранить тему. Проверь доступ к настройкам.")
                return False
        self._mode = mode
        self.changed.emit()
        return True

    @Slot()
    def cycle(self):
        modes = list(PALETTES)
        self.select(modes[(modes.index(self._mode) + 1) % len(modes)])

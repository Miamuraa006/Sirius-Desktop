"""Bounded, truthful, plain-text command/result model for Qt Quick."""

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class MessageModel(QAbstractListModel):
    FIELDS = ("entryId", "userText", "resultText", "timeText", "source", "skillName", "status", "verified")
    LIMIT = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._roles = {int(Qt.UserRole) + i + 1: name.encode() for i, name in enumerate(self.FIELDS)}

    def roleNames(self):
        return self._roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = self._roles.get(role)
        return self._rows[index.row()].get(key.decode()) if key else None

    @staticmethod
    def _time(value):
        try:
            return datetime.fromisoformat(str(value)).astimezone().strftime("%H:%M")
        except (TypeError, ValueError):
            return ""

    def append_event(self, entry_id, event):
        if any(row["entryId"] == entry_id for row in self._rows):
            return
        if len(self._rows) >= self.LIMIT:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._rows.pop(0)
            self.endRemoveRows()
        row = {"entryId": entry_id, "userText": str(event.get("text", "")),
               "resultText": "", "timeText": self._time(event.get("time")),
               "source": str(event.get("source", "text")),
               "skillName": str(event.get("skill") or ""), "status": "processing", "verified": False}
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(row)
        self.endInsertRows()

    def finish(self, entry_id, result):
        for index, row in enumerate(self._rows):
            if row["entryId"] != entry_id:
                continue
            status = str(result.get("status", "failed"))
            verified = result.get("verified") is True and status == "success"
            # Defensive boundary: an unverified success can never get a tick.
            if status == "success" and not verified:
                status = "failed"
            row.update(resultText=str(result.get("message", "")), status=status, verified=verified)
            self.dataChanged.emit(self.index(index), self.index(index), list(self._roles))
            return

    def load(self, records):
        self.clear()
        for i, event in enumerate(sorted(records, key=lambda row: str(row.get("time", "")))[-self.LIMIT:]):
            entry_id = -i - 1
            self.append_event(entry_id, event)
            self.finish(entry_id, event)

    def clear(self):
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def snapshot(self):
        return [dict(row) for row in self._rows]

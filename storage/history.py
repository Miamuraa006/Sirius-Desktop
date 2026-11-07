"""Local, optional SQLite history. This database is NOT encrypted."""
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
from core.models import Command, Result

class History:
    def __init__(self, path: Path, enabled=True, retention_days=30):
        self.enabled = bool(enabled)
        self.retention_days = max(1,min(3650,int(retention_days)))
        self.lock = threading.RLock()
        self.memory = deque(maxlen=500)
        self.connection = None
        if self.enabled:
            Path(path).parent.mkdir(parents=True,exist_ok=True)
            self.connection=sqlite3.connect(str(path), check_same_thread=False)
            self.connection.row_factory=sqlite3.Row
            self.connection.execute('PRAGMA journal_mode=WAL')
            self.connection.execute('PRAGMA secure_delete=ON')
            self.connection.execute('CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, session_id TEXT NOT NULL, time TEXT NOT NULL, skill TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL, verified INTEGER NOT NULL CHECK (verified IN (0,1)))')
            cutoff=(datetime.now(timezone.utc)-timedelta(days=max(1,min(3650,int(retention_days))))).isoformat()
            self.connection.execute('DELETE FROM history WHERE time < ?', (cutoff,))
            self.connection.commit()

    def append(self, command: Command, skill: str, result: Result, timestamp: str | None = None):
        row=dict(text=command.text,source=command.source,session_id=command.session_id,
                 time=timestamp or datetime.now(timezone.utc).isoformat(),skill=skill,
                 status=result.status,message=result.message,verified=result.verified)
        with self.lock:
            if self.connection:
                self.connection.execute('INSERT INTO history(text,source,session_id,time,skill,status,message,verified) VALUES (:text,:source,:session_id,:time,:skill,:status,:message,:verified)',row)
                cutoff=(datetime.now(timezone.utc)-timedelta(days=self.retention_days)).isoformat()
                self.connection.execute('DELETE FROM history WHERE time < ?', (cutoff,))
                # Bound storage as well as presentation; never retain infinite history.
                self.connection.execute('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 10000)')
                self.connection.commit()
            else:
                self.memory.append(row)

    def recent(self, limit=200):
        with self.lock:
            n=max(0,min(2000,int(limit)))
            if not n:
                return []
            if self.connection:
                rows=[dict(r) for r in self.connection.execute('SELECT text,source,session_id,time,skill,status,message,verified FROM history ORDER BY id DESC LIMIT ?', (n,)).fetchall()][::-1]
                for row in rows:
                    row['verified']=bool(row['verified'])
                return rows
            return list(self.memory)[-n:]

    def clear(self):
        with self.lock:
            self.memory.clear()
            if self.connection:
                self.connection.execute('DELETE FROM history')
                self.connection.commit()
                self.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                self.connection.execute('VACUUM')

    def close(self):
        with self.lock:
            if self.connection:
                self.connection.close()
                self.connection=None

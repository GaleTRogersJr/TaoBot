"""Atomic SQLite persistence for settings, watchlists, alerts and history."""
import json
import sqlite3
from pathlib import Path
from .core import Alert


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS watch (key TEXT PRIMARY KEY, name TEXT NOT NULL, netuid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, body TEXT NOT NULL, observed REAL NOT NULL);
        """)
        self.connection.commit()

    def setting(self, key, default=None):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        if "key" in key.lower() or "secret" in key.lower():
            raise ValueError("Credentials are session-only and cannot be stored here.")
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    def watched(self):
        return {key: {"name": name, "netuid": netuid} for key, name, netuid in
                self.connection.execute("SELECT key,name,netuid FROM watch ORDER BY rowid")}

    def add_watch(self, sample):
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO watch VALUES (?, ?, ?)", (sample.key, sample.name, sample.netuid))

    def remove_watch(self, key):
        with self.connection:
            self.connection.execute("DELETE FROM watch WHERE key=?", (key,))
            for alert in self.alerts():
                if alert.key == key:
                    self.connection.execute("DELETE FROM alerts WHERE id=?", (alert.id,))

    def alerts(self):
        return [Alert(**json.loads(row[0])) for row in self.connection.execute("SELECT body FROM alerts ORDER BY rowid")]

    def save_alert(self, alert):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO alerts VALUES (?, ?)", (alert.id, json.dumps(alert.to_dict())))

    def delete_alert(self, alert_id):
        with self.connection:
            self.connection.execute("DELETE FROM alerts WHERE id=?", (alert_id,))

    def persist_evaluation(self, alerts, events):
        # State and notification history commit together before any notification.
        with self.connection:
            self.connection.executemany("INSERT OR REPLACE INTO alerts VALUES (?, ?)",
                [(alert.id, json.dumps(alert.to_dict())) for alert in alerts])
            self.connection.executemany("INSERT OR IGNORE INTO history VALUES (?, ?, ?)",
                [(e["id"], json.dumps(e), e["observed_time"]) for e in events])

    def history(self):
        return [json.loads(row[0]) for row in self.connection.execute("SELECT body FROM history ORDER BY observed DESC")]

    def close(self):
        self.connection.close()

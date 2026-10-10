"""Atomic SQLite persistence for settings, watchlists, alerts and history."""
import json
import sqlite3
import zlib
from pathlib import Path
from .core import Alert, Sample

ARCHIVE_MAX_BATCHES = 2016  # One week at five-minute cadence; fewer if refreshing faster.
ARCHIVE_MAX_DAYS = 7
ARCHIVE_MAX_BYTES = 50 * 1024 * 1024


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
            CREATE TABLE IF NOT EXISTS catalog (key TEXT PRIMARY KEY, source TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata (source TEXT PRIMARY KEY, body TEXT NOT NULL, refreshed REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                fetched REAL NOT NULL, body TEXT NOT NULL);
        """)
        self.connection.commit()

    def setting(self, key, default=None):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        if "key" in key.lower() or "secret" in key.lower():
            raise ValueError("Credentials cannot be stored in settings. Use Windows protected credential storage.")
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

    def cache_catalog(self, source, samples, fetched):
        # A complete provider refresh replaces the catalog atomically. A failed
        # page never reaches here, so partial refreshes cannot remove subnets.
        body = [s.to_dict() for s in samples]
        with self.connection:
            self.connection.execute("DELETE FROM catalog WHERE source=?", (source,))
            self.connection.executemany("INSERT OR REPLACE INTO catalog VALUES (?, ?, ?)",
                [(s.key, source, json.dumps(s.to_dict())) for s in samples])
            if source == "taostats":
                compressed = zlib.compress(json.dumps(body, separators=(",", ":")).encode("utf-8"))
                self.connection.execute("INSERT INTO snapshots(source,fetched,body) VALUES (?, ?, ?)",
                                        (source, fetched, compressed))
                self.connection.execute("DELETE FROM snapshots WHERE fetched < ?", (fetched-ARCHIVE_MAX_DAYS*86400,))
                self.connection.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)",
                                        (ARCHIVE_MAX_BATCHES,))
                self.connection.execute("""DELETE FROM snapshots WHERE id IN (
                    SELECT id FROM (SELECT id, SUM(length(body)) OVER (ORDER BY id DESC) AS retained_bytes
                    FROM snapshots) WHERE retained_bytes > ?)""", (ARCHIVE_MAX_BYTES,))

    def cached_catalog(self, source):
        return [Sample.from_dict(json.loads(row[0]), cached=True) for row in
                self.connection.execute("SELECT body FROM catalog WHERE source=? ORDER BY rowid", (source,))]

    def metadata(self, source):
        row = self.connection.execute("SELECT body,refreshed FROM metadata WHERE source=?", (source,)).fetchone()
        return ({int(key): value for key, value in json.loads(row[0]).items()}, row[1]) if row else ({}, 0)

    def save_metadata(self, source, names, refreshed):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?, ?)",
                                    (source, json.dumps(names), refreshed))

    def close(self):
        self.connection.close()

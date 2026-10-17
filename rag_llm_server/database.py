import sqlite3
import time
from pathlib import Path
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL,
 rtc_room_id TEXT,
 rtc_user_id TEXT,
 rtc_task_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _as_dict(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _now() -> int:
        return int(time.time())

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.executescript(SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def create_user(self, username: str, password_hash: str) -> dict:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (username, password_hash, self._now()),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.commit()
            return dict(row)
        finally:
            connection.close()

    def get_user_by_username(self, username: str) -> dict | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            return self._as_dict(row)
        finally:
            connection.close()

    def get_user_by_id(self, user_id: int) -> dict | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return self._as_dict(row)
        finally:
            connection.close()

    @staticmethod
    def _select_session(
        connection: sqlite3.Connection, token_hash: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT sessions.*, users.username
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.id = ?
            """,
            (token_hash,),
        ).fetchone()

    def create_session(
        self, token_hash: str, user_id: int, expires_at: int
    ) -> dict:
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO sessions (id, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, user_id, expires_at, self._now()),
            )
            row = self._select_session(connection, token_hash)
            connection.commit()
            return dict(row)
        finally:
            connection.close()

    def get_session(self, token_hash: str, now: int | None = None) -> dict | None:
        current_time = self._now() if now is None else now
        connection = self._connect()
        try:
            row = self._select_session(connection, token_hash)
            if row is None:
                return None
            if row["expires_at"] <= current_time:
                cursor = connection.execute(
                    """
                    DELETE FROM sessions
                    WHERE id = ? AND expires_at <= ?
                    """,
                    (token_hash, current_time),
                )
                if cursor.rowcount == 0:
                    latest_row = self._select_session(connection, token_hash)
                    if (
                        latest_row is not None
                        and latest_row["expires_at"] > current_time
                    ):
                        connection.commit()
                        return dict(latest_row)
                    connection.execute(
                        """
                        DELETE FROM sessions
                        WHERE id = ? AND expires_at <= ?
                        """,
                        (token_hash, current_time),
                    )
                connection.commit()
                return None
            return dict(row)
        finally:
            connection.close()

    def delete_session(self, token_hash: str) -> int:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE id = ?", (token_hash,)
            )
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def delete_expired_sessions(self, now: int | None = None) -> int:
        current_time = self._now() if now is None else now
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (current_time,)
            )
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def get_or_create_rtc_ids(
        self, token_hash: str, now: int | None = None
    ) -> dict | None:
        current_time = self._now() if now is None else now
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_session(connection, token_hash)
            if row is None:
                connection.commit()
                return None
            if row["expires_at"] <= current_time:
                connection.execute("DELETE FROM sessions WHERE id = ?", (token_hash,))
                connection.commit()
                return None

            rtc_room_id = row["rtc_room_id"] or f"room_{uuid4().hex}"
            rtc_user_id = row["rtc_user_id"] or f"user_{row['user_id']}"
            rtc_task_id = row["rtc_task_id"] or f"task_{uuid4().hex}"
            if (
                rtc_room_id != row["rtc_room_id"]
                or rtc_user_id != row["rtc_user_id"]
                or rtc_task_id != row["rtc_task_id"]
            ):
                connection.execute(
                    """
                    UPDATE sessions
                    SET rtc_room_id = ?, rtc_user_id = ?, rtc_task_id = ?
                    WHERE id = ?
                    """,
                    (rtc_room_id, rtc_user_id, rtc_task_id, token_hash),
                )
            result = self._select_session(connection, token_hash)
            connection.commit()
            return dict(result)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

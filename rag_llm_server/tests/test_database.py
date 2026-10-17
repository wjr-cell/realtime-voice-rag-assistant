import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from database import Database


FUTURE = 4_102_444_800


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "nested" / "app.db")
    database.initialize()
    return database


def test_initialize_creates_parent_schema_and_indexes(tmp_path):
    database = Database(tmp_path / "nested" / "app.db")

    database.initialize()

    assert database.path.parent.is_dir()
    with sqlite3.connect(database.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert {"users", "sessions"} <= tables
    assert {"idx_sessions_user_id", "idx_sessions_expires_at"} <= indexes


def test_create_user_returns_dict_and_username_is_unique_case_insensitively(db):
    user = db.create_user("Alice", "password-hash")

    assert user["id"] > 0
    assert user["username"] == "Alice"
    assert user["password_hash"] == "password-hash"
    assert isinstance(user["created_at"], int)
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("alice", "another-hash")


def test_user_lookups_return_dicts_and_username_lookup_is_case_insensitive(db):
    created = db.create_user("Alice", "password-hash")

    assert db.get_user_by_username("aLiCe") == created
    assert db.get_user_by_id(created["id"]) == created
    assert db.get_user_by_username("missing") is None
    assert db.get_user_by_id(created["id"] + 1) is None


def test_create_get_and_delete_session(db):
    user = db.create_user("alice", "password-hash")

    created = db.create_session("session-hash", user["id"], expires_at=FUTURE)

    assert created["id"] == "session-hash"
    assert created["user_id"] == user["id"]
    assert created["username"] == "alice"
    assert created["expires_at"] == FUTURE
    assert db.get_session("session-hash", now=0) == created
    assert db.delete_session("session-hash") == 1
    assert db.get_session("session-hash", now=0) is None
    assert db.delete_session("session-hash") == 0


def test_get_session_deletes_an_expired_session(db):
    user = db.create_user("alice", "password-hash")
    db.create_session("expired", user["id"], expires_at=100)

    assert db.get_session("expired", now=100) is None
    assert db.get_session("expired", now=0) is None


def test_get_session_does_not_delete_a_concurrently_renewed_session(db, monkeypatch):
    user = db.create_user("alice", "password-hash")
    db.create_session("renewed", user["id"], expires_at=100)
    stale_row_selected = Event()
    renewal_committed = Event()
    original_select = Database._select_session
    first_select = True

    def pause_after_first_select(connection, token_hash):
        nonlocal first_select
        row = original_select(connection, token_hash)
        if first_select:
            first_select = False
            stale_row_selected.set()
            assert renewal_committed.wait(timeout=5)
        return row

    monkeypatch.setattr(
        Database, "_select_session", staticmethod(pause_after_first_select)
    )

    def renew_session():
        assert stale_row_selected.wait(timeout=5)
        with sqlite3.connect(db.path) as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = ? WHERE id = ?",
                (FUTURE, "renewed"),
            )
        renewal_committed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        renewal = pool.submit(renew_session)
        result = db.get_session("renewed", now=100)
        renewal.result(timeout=5)

    assert result is not None
    assert result["expires_at"] == FUTURE
    assert db.get_session("renewed", now=100)["expires_at"] == FUTURE


def test_delete_expired_sessions_only_deletes_expired_rows(db):
    user = db.create_user("alice", "password-hash")
    db.create_session("old-1", user["id"], expires_at=99)
    db.create_session("old-2", user["id"], expires_at=100)
    db.create_session("live", user["id"], expires_at=101)

    assert db.delete_expired_sessions(now=100) == 2
    assert db.get_session("old-1", now=0) is None
    assert db.get_session("old-2", now=0) is None
    assert db.get_session("live", now=100) is not None


def test_foreign_keys_reject_session_for_missing_user(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.create_session("session-hash", 999_999, expires_at=FUTURE)


def test_get_or_create_rtc_ids_is_atomic(tmp_path):
    db = Database(tmp_path / "nested" / "app.db")
    db.initialize()
    assert db.path.parent.is_dir()
    user = db.create_user("alice", "hash")
    db.create_session("session-hash", user["id"], expires_at=FUTURE)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: db.get_or_create_rtc_ids("session-hash"), range(4))
        )

    assert len({result["rtc_room_id"] for result in results}) == 1
    assert len({result["rtc_task_id"] for result in results}) == 1
    assert {result["rtc_user_id"] for result in results} == {
        f"user_{user['id']}"
    }
    assert re.fullmatch(r"room_[0-9a-f]{32}", results[0]["rtc_room_id"])
    assert re.fullmatch(r"task_[0-9a-f]{32}", results[0]["rtc_task_id"])


def test_get_or_create_rtc_ids_reuses_all_existing_ids(db):
    user = db.create_user("alice", "hash")
    db.create_session("session-hash", user["id"], expires_at=FUTURE)
    with sqlite3.connect(db.path) as connection:
        connection.execute(
            """
            UPDATE sessions
            SET rtc_room_id = ?, rtc_user_id = ?, rtc_task_id = ?
            WHERE id = ?
            """,
            ("room_existing", "user_existing", "task_existing", "session-hash"),
        )

    result = db.get_or_create_rtc_ids("session-hash")

    assert result["rtc_room_id"] == "room_existing"
    assert result["rtc_user_id"] == "user_existing"
    assert result["rtc_task_id"] == "task_existing"


def test_get_or_create_rtc_ids_uses_injected_time_for_expiry(db):
    user = db.create_user("alice", "hash")
    db.create_session("session-hash", user["id"], expires_at=2_000)

    result = db.get_or_create_rtc_ids("session-hash", now=1_000)

    assert result is not None
    assert result["rtc_room_id"] is not None
    assert db.get_session("session-hash", now=1_000) is not None


@pytest.mark.parametrize("expires_at", [None, 1])
def test_get_or_create_rtc_ids_returns_none_for_missing_or_expired_session(
    db, expires_at
):
    if expires_at is not None:
        user = db.create_user("alice", "hash")
        db.create_session("session-hash", user["id"], expires_at=expires_at)

    assert db.get_or_create_rtc_ids("session-hash") is None
    assert db.get_session("session-hash", now=0) is None

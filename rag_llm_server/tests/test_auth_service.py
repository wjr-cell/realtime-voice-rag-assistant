import hashlib
import re
import sqlite3
import time

import pytest

from database import Database
from services import auth_service as auth_module
from services.auth_service import (
    SESSION_TTL_SECONDS,
    AuthService,
    AuthValidationError,
    InvalidCredentials,
    UsernameTaken,
    password_hash,
)


NOW = int(time.time())


@pytest.fixture
def auth(tmp_path):
    service = AuthService(Database(tmp_path / "auth.db"), now=lambda: NOW)
    service.initialize()
    return service


def test_register_normalizes_username_and_returns_safe_user(auth):
    result = auth.register(" Alice_01 ", "password-123", "password-123")

    assert result.user["username"] == "alice_01"
    assert "password_hash" not in result.user
    assert result.token


@pytest.mark.parametrize(
    "username",
    [
        "ab",
        "a" * 33,
        "alice-01",
        "alice smith",
        "用户名",
        "ａｌｉｃｅ",
        "álîce",
    ],
)
def test_register_rejects_invalid_ascii_username_with_stable_message(auth, username):
    with pytest.raises(
        AuthValidationError,
        match="^用户名必须为 3–32 位，只能包含小写英文字母、数字和下划线$",
    ):
        auth.register(username, "password-123", "password-123")


def test_register_rejects_non_ascii_username_that_lowercases_to_ascii(auth):
    with pytest.raises(AuthValidationError):
        auth.register("Kelvin", "password-123", "password-123")


def test_login_hides_non_ascii_username_validation(auth):
    with pytest.raises(InvalidCredentials, match="^用户名或密码错误$"):
        auth.login("Kelvin", "password-123")


@pytest.mark.parametrize("password", ["x" * 7, "x" * 73])
def test_register_validates_password_by_python_character_count(auth, password):
    with pytest.raises(
        AuthValidationError, match="^密码长度必须为 8–72 个字符$"
    ):
        auth.register("alice", password, password)


def test_register_accepts_eight_multibyte_characters(auth):
    result = auth.register("alice", "密" * 8, "密" * 8)

    assert result.user["username"] == "alice"


def test_register_rejects_confirmation_mismatch(auth):
    with pytest.raises(AuthValidationError, match="^两次输入的密码不一致$"):
        auth.register("alice", "password-123", "password-124")


def test_register_stores_argon2_hash_not_plaintext(auth):
    password = "a-unique-password"
    result = auth.register("alice", password, password)
    stored = auth.database.get_user_by_id(result.user["id"])

    assert stored["password_hash"].startswith("$argon2")
    assert stored["password_hash"] != password
    assert password_hash.verify(password, stored["password_hash"])


def test_duplicate_username_is_case_insensitive(auth):
    auth.register("Alice", "password-123", "password-123")

    with pytest.raises(UsernameTaken, match="^用户名已被占用$"):
        auth.register("ALICE", "another-password", "another-password")


def test_login_uses_same_error_for_unknown_user_wrong_password_and_bad_username(auth):
    auth.register("alice", "password-123", "password-123")

    for username, password in [
        ("unknown", "password-123"),
        ("alice", "wrong-password"),
        ("not-valid!", "password-123"),
    ]:
        with pytest.raises(InvalidCredentials, match="^用户名或密码错误$"):
            auth.login(username, password)


def test_unknown_user_still_verifies_dummy_hash(auth, monkeypatch):
    calls = []

    class PasswordHashSpy:
        def verify(self, password, encoded_hash):
            calls.append((password, encoded_hash))
            return False

    monkeypatch.setattr(auth_module, "password_hash", PasswordHashSpy())

    with pytest.raises(InvalidCredentials):
        auth.login("unknown", "password-123")

    assert calls == [("password-123", auth_module.DUMMY_HASH)]


def test_login_hides_malformed_stored_password_hash(auth):
    auth.database.create_user("alice", "broken")

    with pytest.raises(InvalidCredentials, match="^用户名或密码错误$"):
        auth.login("alice", "password-123")


def test_login_succeeds_and_creates_a_new_session(auth):
    registered = auth.register("alice", "password-123", "password-123")

    logged_in = auth.login(" ALICE ", "password-123")

    assert logged_in.user == registered.user
    assert logged_in.token != registered.token
    assert auth.get_current_user(logged_in.token) == registered.user


def test_session_token_is_urlsafe_and_only_sha256_is_stored(auth):
    result = auth.register("alice", "password-123", "password-123")
    token_hash = hashlib.sha256(result.token.encode()).hexdigest()

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", result.token)
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash)
    stored = auth.database.get_session(token_hash, now=NOW)
    assert stored["id"] == token_hash
    assert stored["expires_at"] == NOW + SESSION_TTL_SECONDS
    assert result.token.encode() not in auth.database.path.read_bytes()


def test_initialize_creates_schema_and_deletes_expired_sessions(tmp_path):
    database = Database(tmp_path / "nested" / "auth.db")
    database.initialize()
    user = database.create_user("alice", "hash")
    database.create_session("expired", user["id"], expires_at=NOW)
    service = AuthService(database, now=lambda: NOW)

    service.initialize()

    assert database.path.exists()
    assert database.get_session("expired", now=0) is None


def test_get_current_session_returns_safe_data_and_repr_hides_tokens(auth):
    result = auth.register("alice", "password-123", "password-123")

    current = auth.get_current_session(result.token)

    assert current.user == result.user
    assert current.raw_token == result.token
    assert current.session["expires_at"] == NOW + SESSION_TTL_SECONDS
    representation = repr(current)
    assert result.token not in representation
    assert current.session["id"] not in representation
    assert result.token not in repr(result)


@pytest.mark.parametrize("token", [None, "", "invalid-token"])
def test_current_user_and_session_return_none_for_invalid_tokens(auth, token):
    assert auth.get_current_user(token) is None
    assert auth.get_current_session(token) is None


def test_expired_session_is_not_authenticated(auth):
    result = auth.register("alice", "password-123", "password-123")
    auth.now = lambda: NOW + SESSION_TTL_SECONDS

    assert auth.get_current_user(result.token) is None
    assert auth.get_current_session(result.token) is None


def test_logout_is_idempotent_for_valid_invalid_and_none_tokens(auth):
    result = auth.register("alice", "password-123", "password-123")

    assert auth.logout(result.token) is None
    assert auth.get_current_user(result.token) is None
    assert auth.logout(result.token) is None
    assert auth.logout("invalid-token") is None
    assert auth.logout(None) is None


def test_get_or_create_rtc_session_reuses_ids_for_valid_token(auth):
    result = auth.register("alice", "password-123", "password-123")

    first = auth.get_or_create_rtc_session(result.token)
    second = auth.get_or_create_rtc_session(result.token)

    assert first is not None
    assert second is not None
    assert first["rtc_room_id"] == second["rtc_room_id"]
    assert first["rtc_user_id"] == second["rtc_user_id"]
    assert first["rtc_task_id"] == second["rtc_task_id"]


def test_authentication_and_rtc_use_the_same_injected_time(tmp_path):
    service = AuthService(Database(tmp_path / "auth.db"), now=lambda: 1_000)
    service.initialize()
    result = service.register("alice", "password-123", "password-123")

    assert service.get_current_user(result.token) == result.user
    first = service.get_or_create_rtc_session(result.token)
    second = service.get_or_create_rtc_session(result.token)

    assert first is not None
    assert first["expires_at"] == 1_000 + SESSION_TTL_SECONDS
    assert first["rtc_room_id"] == second["rtc_room_id"]
    assert first["rtc_user_id"] == second["rtc_user_id"]
    assert first["rtc_task_id"] == second["rtc_task_id"]


def test_rtc_flow_reads_clock_once_and_passes_same_time_to_database(
    tmp_path, monkeypatch
):
    clock_calls = []

    def advancing_clock():
        current_time = 1_000 + len(clock_calls)
        clock_calls.append(current_time)
        return current_time

    database = Database(tmp_path / "auth.db")
    service = AuthService(database, now=advancing_clock)
    service.initialize()
    result = service.register("alice", "password-123", "password-123")
    clock_calls.clear()
    database_times = []
    original_get_session = database.get_session
    original_get_or_create_rtc_ids = database.get_or_create_rtc_ids

    def get_session_spy(token_hash, now=None):
        database_times.append(("get_session", now))
        return original_get_session(token_hash, now=now)

    def get_or_create_rtc_ids_spy(token_hash, now=None):
        database_times.append(("get_or_create_rtc_ids", now))
        return original_get_or_create_rtc_ids(token_hash, now=now)

    monkeypatch.setattr(database, "get_session", get_session_spy)
    monkeypatch.setattr(database, "get_or_create_rtc_ids", get_or_create_rtc_ids_spy)

    assert service.get_or_create_rtc_session(result.token) is not None
    assert len(clock_calls) == 1
    assert database_times == [
        ("get_session", clock_calls[0]),
        ("get_or_create_rtc_ids", clock_calls[0]),
    ]


def test_get_or_create_rtc_session_rejects_invalid_and_expired_tokens(auth):
    assert auth.get_or_create_rtc_session(None) is None
    assert auth.get_or_create_rtc_session("invalid-token") is None

    result = auth.register("alice", "password-123", "password-123")
    auth.now = lambda: NOW + SESSION_TTL_SECONDS
    assert auth.get_or_create_rtc_session(result.token) is None


def test_register_only_translates_username_unique_constraint(auth, monkeypatch):
    def unrelated_integrity_error(username, encoded_password):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(auth.database, "create_user", unrelated_integrity_error)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        auth.register("alice", "password-123", "password-123")

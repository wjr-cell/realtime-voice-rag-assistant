import hashlib
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from database import Database


SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$", re.ASCII)

USERNAME_VALIDATION_MESSAGE = (
    "用户名必须为 3–32 位，只能包含小写英文字母、数字和下划线"
)
PASSWORD_VALIDATION_MESSAGE = "密码长度必须为 8–72 个字符"
PASSWORD_CONFIRMATION_MESSAGE = "两次输入的密码不一致"
USERNAME_TAKEN_MESSAGE = "用户名已被占用"
INVALID_CREDENTIALS_MESSAGE = "用户名或密码错误"

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-password")


class AuthValidationError(ValueError):
    pass


class UsernameTaken(Exception):
    pass


class InvalidCredentials(Exception):
    pass


@dataclass(frozen=True)
class AuthResult:
    user: dict
    token: str = field(repr=False)


@dataclass(frozen=True)
class AuthenticatedSession:
    user: dict
    session: dict = field(repr=False)
    raw_token: str = field(repr=False)


class AuthService:
    def __init__(
        self,
        database: Database,
        now: Callable[[], int] = lambda: int(time.time()),
    ):
        self.database = database
        self.now = now

    def initialize(self) -> None:
        self.database.initialize()
        self.database.delete_expired_sessions(self.now())

    @staticmethod
    def _normalize_username(username: str) -> str:
        if not isinstance(username, str):
            return ""
        stripped_username = username.strip()
        if not stripped_username.isascii():
            return ""
        return stripped_username.lower()

    @staticmethod
    def _is_valid_username(username: str) -> bool:
        return USERNAME_RE.fullmatch(username) is not None

    @staticmethod
    def _safe_user(user: dict) -> dict:
        safe_user = dict(user)
        safe_user.pop("password_hash", None)
        return safe_user

    @staticmethod
    def _hash_token(raw_token: str | None) -> str | None:
        if not isinstance(raw_token, str) or not raw_token:
            return None
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @staticmethod
    def _is_username_unique_error(error: sqlite3.IntegrityError) -> bool:
        return (
            getattr(error, "sqlite_errorcode", None)
            == sqlite3.SQLITE_CONSTRAINT_UNIQUE
            and "users.username" in str(error)
        )

    def _create_session(self, user: dict) -> AuthResult:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        self.database.create_session(
            token_hash,
            user["id"],
            expires_at=self.now() + SESSION_TTL_SECONDS,
        )
        return AuthResult(user=self._safe_user(user), token=raw_token)

    def register(
        self, username: str, password: str, password_confirmation: str
    ) -> AuthResult:
        normalized_username = self._normalize_username(username)
        if not self._is_valid_username(normalized_username):
            raise AuthValidationError(USERNAME_VALIDATION_MESSAGE)
        if not isinstance(password, str) or not 8 <= len(password) <= 72:
            raise AuthValidationError(PASSWORD_VALIDATION_MESSAGE)
        if password != password_confirmation:
            raise AuthValidationError(PASSWORD_CONFIRMATION_MESSAGE)

        encoded_password = password_hash.hash(password)
        try:
            user = self.database.create_user(normalized_username, encoded_password)
        except sqlite3.IntegrityError as error:
            if self._is_username_unique_error(error):
                raise UsernameTaken(USERNAME_TAKEN_MESSAGE) from error
            raise
        return self._create_session(user)

    def login(self, username: str, password: str) -> AuthResult:
        normalized_username = self._normalize_username(username)
        valid_username = self._is_valid_username(normalized_username)
        user = (
            self.database.get_user_by_username(normalized_username)
            if valid_username
            else None
        )
        candidate_password = password if isinstance(password, str) else ""
        encoded_password = user["password_hash"] if user is not None else DUMMY_HASH

        try:
            password_matches = password_hash.verify(
                candidate_password, encoded_password
            )
        except PwdlibError:
            raise InvalidCredentials(INVALID_CREDENTIALS_MESSAGE) from None

        if not password_matches or user is None:
            raise InvalidCredentials(INVALID_CREDENTIALS_MESSAGE)
        return self._create_session(user)

    def get_current_session(
        self, raw_token: str | None
    ) -> AuthenticatedSession | None:
        return self._get_current_session(raw_token, self.now())

    def _get_current_session(
        self, raw_token: str | None, current_time: int
    ) -> AuthenticatedSession | None:
        token_hash = self._hash_token(raw_token)
        if token_hash is None:
            return None
        session = self.database.get_session(token_hash, now=current_time)
        if session is None:
            return None
        user = self.database.get_user_by_id(session["user_id"])
        if user is None:
            return None
        return AuthenticatedSession(
            user=self._safe_user(user),
            session=session,
            raw_token=raw_token,
        )

    def get_current_user(self, raw_token: str | None) -> dict | None:
        authenticated = self.get_current_session(raw_token)
        return authenticated.user if authenticated is not None else None

    def logout(self, raw_token: str | None) -> None:
        token_hash = self._hash_token(raw_token)
        if token_hash is not None:
            self.database.delete_session(token_hash)

    def get_or_create_rtc_session(self, raw_token: str | None) -> dict | None:
        current_time = self.now()
        authenticated = self._get_current_session(raw_token, current_time)
        if authenticated is None:
            return None
        return self.database.get_or_create_rtc_ids(
            authenticated.session["id"], now=current_time
        )

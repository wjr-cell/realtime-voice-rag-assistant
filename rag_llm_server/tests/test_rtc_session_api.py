import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from config import Config
from database import Database
from services.auth_service import AuthService, SESSION_TTL_SECONDS


NOW = 1_700_000_000
BASE_CONFIG = {
    "VOLC_ACCESS_KEY": "injected-ak",
    "VOLC_SECRET_KEY": "injected-sk",
    "RTC_APP_ID": "a" * 24,
    "RTC_APP_KEY": "test-app-key",
    "ASR_APP_ID": "asr-app",
    "TTS_APP_ID": "tts-app",
    "SERVER_URL": "http://testserver",
}
REGISTER = {
    "username": "alice",
    "password": "password-123",
    "confirm_password": "password-123",
}


def make_app(tmp_path: Path, *, now=None, config_values=None):
    from main import create_app

    clock = now or (lambda: NOW)
    service = AuthService(Database(tmp_path / "nested" / "rtc.db"), now=clock)
    config = Config({**BASE_CONFIG, **(config_values or {})})
    return create_app(config, service, validate_config=False), service


def register(client):
    response = client.post("/api/auth/register", json=REGISTER)
    assert response.status_code == 201
    return client.cookies["rtc_session"]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {"ok": True}
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeAsyncClient:
    def __init__(self, calls, response=None, error=None):
        self.calls = calls
        self.response = response or FakeResponse()
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


def install_upstream(monkeypatch, *, response=None, error=None):
    import main as main_module

    class SafeSigner:
        def __init__(self, request_data, service):
            self.request_data = request_data

        def add_authorization(self, account):
            self.request_data["headers"]["Authorization"] = "safe-test-signature"

    if main_module.Signer.__module__ == "services.utils":
        monkeypatch.setattr(main_module, "Signer", SafeSigner)
    calls = []
    monkeypatch.setattr(
        main_module.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(calls, response=response, error=error),
    )
    return calls


@pytest.mark.parametrize("path", ["/getScenes", "/proxy?Action=StartVoiceChat"])
def test_rtc_routes_require_login(tmp_path, path):
    app, _ = make_app(tmp_path)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "请先登录"}


@pytest.mark.parametrize("path", ["/getScenes", "/proxy?Action=StartVoiceChat"])
def test_expired_cookie_is_rejected_and_cleared(tmp_path, path):
    current_time = [NOW]
    app, _ = make_app(tmp_path, now=lambda: current_time[0])

    with TestClient(app, raise_server_exceptions=False) as client:
        register(client)
        current_time[0] += SESSION_TTL_SECONDS
        response = client.post(path, json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "请先登录"}
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_get_scenes_returns_original_shape_with_dynamic_rtc_values(tmp_path):
    app, service = make_app(tmp_path)

    with TestClient(app) as client:
        token = register(client)
        response = client.post("/getScenes", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ResponseMetadata"] == {"Action": "getScenes"}
    assert len(payload["Result"]["scenes"]) == 1
    scene = payload["Result"]["scenes"][0]
    assert set(scene) == {"scene", "rtc", "VoiceChat"}
    assert scene["rtc"]["AppId"] == BASE_CONFIG["RTC_APP_ID"]
    rtc = service.get_current_session(token).session
    assert scene["rtc"]["RoomId"] == rtc["rtc_room_id"]
    assert scene["rtc"]["UserId"] == rtc["rtc_user_id"]
    assert scene["rtc"]["Token"].startswith("001" + BASE_CONFIG["RTC_APP_ID"])


def test_same_session_reuses_ids_and_resigns_token(tmp_path):
    app, service = make_app(tmp_path)

    with TestClient(app) as client:
        raw_token = register(client)
        first = client.post("/getScenes", json={}).json()["Result"]["scenes"][0]["rtc"]
        first_rtc = dict(service.get_current_session(raw_token).session)
        second = client.post("/getScenes", json={}).json()["Result"]["scenes"][0]["rtc"]

    second_rtc = service.get_current_session(raw_token).session
    assert first["RoomId"] == second["RoomId"] == first_rtc["rtc_room_id"]
    assert first["UserId"] == second["UserId"] == first_rtc["rtc_user_id"]
    assert first_rtc["rtc_room_id"] == second_rtc["rtc_room_id"]
    assert first_rtc["rtc_user_id"] == second_rtc["rtc_user_id"]
    assert first_rtc["rtc_task_id"] == second_rtc["rtc_task_id"]
    assert first["Token"] != second["Token"]


def test_different_login_sessions_get_distinct_room_and_task_but_same_user(
    tmp_path, monkeypatch
):
    calls = install_upstream(monkeypatch)
    app, service = make_app(tmp_path)

    with TestClient(app) as first_client, TestClient(app) as second_client:
        first_token = register(first_client)
        login = second_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password-123"},
        )
        assert login.status_code == 200
        second_token = second_client.cookies["rtc_session"]
        first_client.post("/getScenes", json={})
        second_client.post("/getScenes", json={})
        first_client.post("/proxy?Action=StopVoiceChat", json={})
        second_client.post("/proxy?Action=StopVoiceChat", json={})

    first_rtc = service.get_current_session(first_token).session
    second_rtc = service.get_current_session(second_token).session
    assert first_rtc["rtc_room_id"] != second_rtc["rtc_room_id"]
    assert first_rtc["rtc_task_id"] != second_rtc["rtc_task_id"]
    assert first_rtc["rtc_user_id"] == second_rtc["rtc_user_id"]
    assert {calls[0]["json"]["TaskId"], calls[1]["json"]["TaskId"]} == {
        first_rtc["rtc_task_id"],
        second_rtc["rtc_task_id"],
    }


def test_proxy_requires_scenes_initialization(tmp_path):
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        response = client.post("/proxy?Action=StartVoiceChat", json={})

    assert response.status_code == 409
    assert response.json() == {"detail": "请先获取场景配置"}


@pytest.mark.parametrize("action", ["StartVoiceChat", "StopVoiceChat"])
def test_proxy_start_and_stop_use_session_rtc_ids(tmp_path, monkeypatch, action):
    calls = install_upstream(monkeypatch)
    app, service = make_app(tmp_path)

    with TestClient(app) as client:
        raw_token = register(client)
        client.post("/getScenes", json={})
        response = client.post(f"/proxy?Action={action}", json={})

    assert response.status_code == 200
    rtc = service.get_current_session(raw_token).session
    body = calls[0]["json"]
    assert body["AppId"] == BASE_CONFIG["RTC_APP_ID"]
    assert body["RoomId"] == rtc["rtc_room_id"]
    assert body["TaskId"] == rtc["rtc_task_id"]
    if action == "StartVoiceChat":
        assert body["AgentConfig"]["TargetUserId"] == [rtc["rtc_user_id"]]
        assert body["AgentConfig"]["UserId"] == "AiAgent"


@pytest.mark.parametrize("path", ["/proxy", "/proxy?Action=DeleteRoom"])
def test_proxy_rejects_missing_or_unknown_action_before_signing_and_network(
    tmp_path, monkeypatch, path
):
    import main as main_module

    signer_calls = []

    class SignerSpy:
        def __init__(self, request_data, service):
            self.request_data = request_data
            signer_calls.append((request_data, service))

        def add_authorization(self, account):
            raise AssertionError("invalid actions must not be signed")

    monkeypatch.setattr(main_module, "Signer", SignerSpy)
    calls = install_upstream(monkeypatch)
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post(path, json={"unsafe": True})

    assert response.status_code == 400
    assert response.json() == {"detail": "不支持的 Action"}
    assert signer_calls == []
    assert calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_proxy_rejects_cross_site_cookie_request_before_signing_and_network(
    tmp_path, monkeypatch, headers
):
    import main as main_module

    signer_calls = []

    class SignerSpy:
        def __init__(self, request_data, service):
            signer_calls.append((request_data, service))

        def add_authorization(self, account):
            raise AssertionError("cross-site request must not be signed")

    monkeypatch.setattr(main_module, "Signer", SignerSpy)
    calls = install_upstream(monkeypatch)
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post(
            "/proxy?Action=StopVoiceChat", json={}, headers=headers
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "跨站请求被拒绝"}
    assert signer_calls == []
    assert calls == []


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "http://10.20.30.40:3000"]
)
def test_proxy_allows_restricted_development_origin_with_https_server_url(
    tmp_path, monkeypatch, origin
):
    calls = install_upstream(monkeypatch)
    app, _ = make_app(
        tmp_path, config_values={"SERVER_URL": "https://tunnel.example"}
    )

    with TestClient(app, base_url="https://tunnel.example") as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post(
            "/proxy?Action=StopVoiceChat", json={}, headers={"Origin": origin}
        )

    assert response.status_code == 200
    assert len(calls) == 1


def test_proxy_rejects_unconfigured_public_host_before_signing_and_network(
    tmp_path, monkeypatch
):
    import main as main_module

    signer_calls = []

    class SignerSpy:
        def __init__(self, request_data, service):
            signer_calls.append((request_data, service))

        def add_authorization(self, account):
            raise AssertionError("unsafe host must not be signed")

    monkeypatch.setattr(main_module, "Signer", SignerSpy)
    calls = install_upstream(monkeypatch)
    app, _ = make_app(tmp_path, config_values={"SERVER_URL": ""})

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post(
            "/proxy?Action=StartVoiceChat",
            json={},
            headers={"Host": "attacker.example"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "服务地址配置不安全"}
    assert signer_calls == []
    assert calls == []


def test_proxy_rejects_backslash_userinfo_host_before_signing_and_network(
    tmp_path, monkeypatch
):
    import main as main_module

    signer_calls = []

    class SignerSpy:
        def __init__(self, request_data, service):
            self.request_data = request_data
            signer_calls.append((request_data, service))

        def add_authorization(self, account):
            self.request_data["headers"]["Authorization"] = "safe-signature"

    monkeypatch.setattr(main_module, "Signer", SignerSpy)
    calls = install_upstream(monkeypatch)
    app, _ = make_app(tmp_path, config_values={"SERVER_URL": ""})

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post(
            "/proxy?Action=StartVoiceChat",
            json={},
            headers={"Host": "attacker.example\\@localhost:3001"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "服务地址配置不安全"}
    assert signer_calls == []
    assert calls == []


def test_proxy_revalidates_session_after_reading_body_and_before_network(
    tmp_path, monkeypatch
):
    import main as main_module

    signer_calls = []

    class SignerSpy:
        def __init__(self, request_data, service):
            signer_calls.append((request_data, service))

        def add_authorization(self, account):
            raise AssertionError("expired session must not be signed")

    monkeypatch.setattr(main_module, "Signer", SignerSpy)
    calls = install_upstream(monkeypatch)
    app, service = make_app(tmp_path)

    with TestClient(app) as client:
        raw_token = register(client)
        client.post("/getScenes", json={})
        authenticated = service.get_current_session(raw_token)
        checks = 0

        def expire_after_dependency(token):
            nonlocal checks
            checks += 1
            return authenticated if checks == 1 else None

        monkeypatch.setattr(service, "get_current_session", expire_after_dependency)
        response = client.post("/proxy?Action=StopVoiceChat", json={})

    assert checks == 2
    assert response.status_code == 401
    assert response.json() == {"detail": "请先登录"}
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert signer_calls == []
    assert calls == []


def test_proxy_uses_fresh_session_ids_from_revalidation(tmp_path, monkeypatch):
    from services.auth_service import AuthenticatedSession

    calls = install_upstream(monkeypatch)
    app, service = make_app(tmp_path)

    with TestClient(app) as client:
        raw_token = register(client)
        client.post("/getScenes", json={})
        authenticated = service.get_current_session(raw_token)
        fresh_rtc = {
            **authenticated.session,
            "rtc_room_id": "room_fresh",
            "rtc_user_id": "user_fresh",
            "rtc_task_id": "task_fresh",
        }
        checks = 0

        def refresh_after_dependency(token):
            nonlocal checks
            checks += 1
            if checks == 1:
                return authenticated
            return AuthenticatedSession(
                user=authenticated.user,
                session=fresh_rtc,
                raw_token=authenticated.raw_token,
            )

        monkeypatch.setattr(service, "get_current_session", refresh_after_dependency)
        response = client.post("/proxy?Action=StopVoiceChat", json={})

    assert response.status_code == 200
    assert checks == 2
    assert calls[0]["json"] == {
        "AppId": BASE_CONFIG["RTC_APP_ID"],
        "RoomId": "room_fresh",
        "TaskId": "task_fresh",
    }


def test_proxy_signer_uses_injected_credentials(tmp_path, monkeypatch):
    import main as main_module

    accounts = []

    class SignerSpy:
        def __init__(self, request_data, service):
            self.request_data = request_data

        def add_authorization(self, account):
            accounts.append(account)
            self.request_data["headers"]["Authorization"] = "safe-test-signature"

    monkeypatch.setattr(main_module, "Signer", SignerSpy)
    install_upstream(monkeypatch)
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post("/proxy?Action=StopVoiceChat", json={})

    assert response.status_code == 200
    assert accounts == [
        {"accessKeyId": "injected-ak", "secretKey": "injected-sk"}
    ]


def test_sqlite_locked_maps_to_stable_503_without_database_path(
    tmp_path, monkeypatch
):
    app, service = make_app(tmp_path)

    def locked(_):
        raise sqlite3.OperationalError("database is locked: /secret/app.db")

    monkeypatch.setattr(service, "get_or_create_rtc_session", locked)
    with TestClient(app, raise_server_exceptions=False) as client:
        register(client)
        response = client.post("/getScenes", json={})

    assert response.status_code == 503
    assert response.json() == {"detail": "服务繁忙，请稍后重试"}
    assert "/secret/app.db" not in response.text


def test_upstream_timeout_maps_to_stable_504_without_secrets(
    tmp_path, monkeypatch, capsys
):
    install_upstream(
        monkeypatch,
        error=httpx.ReadTimeout("timeout with injected-sk"),
    )
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post("/proxy?Action=StopVoiceChat", json={})

    assert response.status_code == 504
    assert response.json() == {"detail": "RTC 服务响应超时"}
    output = capsys.readouterr()
    assert "injected-sk" not in response.text + output.out + output.err


@pytest.mark.parametrize(
    "upstream",
    [
        FakeResponse(status_code=500, payload={"secret": "upstream"}),
        FakeResponse(status_code=200, json_error=ValueError("not json")),
    ],
)
def test_bad_upstream_response_maps_to_stable_502(
    tmp_path, monkeypatch, upstream
):
    install_upstream(monkeypatch, response=upstream)
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post("/proxy?Action=StopVoiceChat", json={})

    assert response.status_code == 502
    assert response.json() == {"detail": "RTC 服务调用失败"}
    assert "upstream" not in response.text


def test_2xx_json_with_response_metadata_error_is_returned_unchanged(
    tmp_path, monkeypatch
):
    payload = {
        "ResponseMetadata": {
            "RequestId": "request-id",
            "Error": {"Code": "UpstreamError", "Message": "failed"},
        }
    }
    install_upstream(monkeypatch, response=FakeResponse(payload=payload))
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        register(client)
        client.post("/getScenes", json={})
        response = client.post("/proxy?Action=StopVoiceChat", json={})

    assert response.status_code == 200
    assert response.json() == payload

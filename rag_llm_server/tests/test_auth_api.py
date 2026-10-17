import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from config import Config
from database import Database
from services.auth_service import AuthService, SESSION_TTL_SECONDS


NOW = 1_700_000_000
CLOUD_ENV_NAMES = {
    "VOLC_ACCESS_KEY",
    "VOLC_SECRET_KEY",
    "ARK_API_KEY",
    "ARK_ENDPOINT_ID",
    "RTC_APP_ID",
    "RTC_APP_KEY",
    "VOLC_ACCOUNT_ID",
    "KB_COLLECTION_NAME",
    "SPEECH_APP_ID",
    "ASR_APP_ID",
    "TTS_APP_ID",
}


def make_app(tmp_path: Path, *, config_values=None, now=lambda: NOW):
    from main import create_app

    service = AuthService(Database(tmp_path / "nested" / "auth.db"), now=now)
    config = Config(config_values or {})
    return create_app(config=config, auth_service=service, validate_config=False), service


def assert_session_cookie(response, *, secure=False, deleted=False):
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("rtc_session=")
    assert "Path=/" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "expires=" in cookie.lower()
    assert f"Max-Age={0 if deleted else SESSION_TTL_SECONDS}" in cookie
    assert ("Secure" in cookie) is secure


def test_create_app_has_no_database_io_until_lifespan(tmp_path):
    app, service = make_app(tmp_path)

    assert not service.database.path.exists()
    assert not service.database.path.parent.exists()

    with TestClient(app):
        assert service.database.path.exists()


def test_import_main_without_cloud_environment_has_no_cwd_database_io(tmp_path):
    server_root = Path(__file__).resolve().parents[1]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in CLOUD_ENV_NAMES
    }
    environment["PYTHONPATH"] = str(server_root)

    result = subprocess.run(
        [sys.executable, "-c", "import main; print('ok')"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert not (tmp_path / "data").exists()


def test_factory_registers_existing_business_and_auth_routes(tmp_path):
    app, _ = make_app(tmp_path)
    route_pairs = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}

    assert {
        ("/getScenes", "POST"),
        ("/proxy", "POST"),
        ("/api/chat_callback", "POST"),
        ("/debug/chat", "POST"),
        ("/debug/rag", "GET"),
        ("/api/auth/register", "POST"),
        ("/api/auth/login", "POST"),
        ("/api/auth/me", "GET"),
        ("/api/auth/logout", "POST"),
    } <= route_pairs


def test_chat_callback_sets_explicit_wildcard_cors_header_without_origin(
    tmp_path, monkeypatch
):
    import main as main_module

    app, _ = make_app(tmp_path)

    async def retrieve_stub(query):
        return ""

    monkeypatch.setattr(main_module.rag_service, "retrieve", retrieve_stub)
    monkeypatch.setattr(
        main_module.llm_service, "chat_stream", lambda messages, context: iter(())
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat_callback",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_lifespan_initializes_and_cleans_expired_sessions(tmp_path):
    app, service = make_app(tmp_path)
    service.database.initialize()
    user = service.database.create_user("alice", "hash")
    service.database.create_session("expired", user["id"], expires_at=NOW)

    with TestClient(app):
        assert service.database.get_session("expired", now=0) is None


def test_register_returns_user_and_secure_session_cookie(tmp_path):
    app, _ = make_app(tmp_path)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )

    assert response.status_code == 201
    assert response.json()["user"]["username"] == "alice"
    assert isinstance(response.json()["user"]["id"], int)
    assert_session_cookie(response, secure=True)


def test_server_https_marks_cookie_secure_for_http_request(tmp_path):
    app, _ = make_app(tmp_path, config_values={"SERVER_URL": "https://api.test"})

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )

    assert_session_cookie(response, secure=True)


def test_local_http_cookie_is_not_secure(tmp_path):
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )

    assert_session_cookie(response)


def test_duplicate_register_returns_string_detail(tmp_path):
    app, _ = make_app(tmp_path)
    payload = {
        "username": "alice",
        "password": "password-123",
        "confirm_password": "password-123",
    }

    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=payload).status_code == 201
        response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "用户名已存在"}


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"username": "ab", "password": "password-123", "confirm_password": "password-123"}, "用户名必须为 3–32 位，只能包含小写英文字母、数字和下划线"),
        ({"username": "alice", "password": "short", "confirm_password": "short"}, "密码长度必须为 8–72 个字符"),
        ({"username": "alice", "password": "password-123", "confirm_password": "different"}, "两次输入的密码不一致"),
    ],
)
def test_register_domain_validation_returns_specific_string_detail(
    tmp_path, payload, detail
):
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"username": "alice", "password": 123, "confirm_password": "password-123"},
        {"username": "alice", "password": "password-123"},
    ],
)
def test_request_validation_has_stable_string_detail(tmp_path, payload):
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "请求参数不合法"}


def test_login_me_and_logout_flow(tmp_path):
    app, _ = make_app(tmp_path)
    registration = {
        "username": "alice",
        "password": "password-123",
        "confirm_password": "password-123",
    }

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration)
        first_token = client.cookies["rtc_session"]
        logged_in = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password-123"},
        )
        second_token = client.cookies["rtc_session"]
        current = client.get("/api/auth/me")
        logged_out = client.post("/api/auth/logout")
        missing = client.get("/api/auth/me")

    assert logged_in.status_code == 200
    assert logged_in.json() == registered.json()
    assert first_token != second_token
    assert_session_cookie(logged_in)
    assert current.status_code == 200
    assert current.json() == registered.json()
    assert logged_out.status_code == 204
    assert logged_out.content == b""
    assert_session_cookie(logged_out, deleted=True)
    assert missing.status_code == 401
    assert missing.json() == {"detail": "请先登录"}
    assert_session_cookie(missing, deleted=True)


def test_unknown_and_wrong_password_have_identical_unauthorized_response(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        unknown = client.post(
            "/api/auth/login",
            json={"username": "unknown", "password": "password-123"},
        )
        wrong = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong-password"},
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "用户名或密码错误"}
    assert_session_cookie(unknown, deleted=True)
    assert_session_cookie(wrong, deleted=True)


@pytest.mark.parametrize("cookie", [None, "invalid-token"])
def test_me_rejects_missing_or_invalid_cookie_and_clears_it(tmp_path, cookie):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        if cookie:
            client.cookies.set("rtc_session", cookie)
        response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "请先登录"}
    assert_session_cookie(response, deleted=True)


def test_me_rejects_expired_cookie_and_clears_it(tmp_path):
    current_time = [NOW]
    app, _ = make_app(tmp_path, now=lambda: current_time[0])
    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        current_time[0] += SESSION_TTL_SECONDS
        response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert_session_cookie(response, deleted=True)


@pytest.mark.parametrize("cookie", [None, "invalid-token"])
def test_logout_is_always_idempotent_and_clears_cookie(tmp_path, cookie):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        if cookie:
            client.cookies.set("rtc_session", cookie)
        response = client.post("/api/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    assert_session_cookie(response, deleted=True)


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example", "Content-Type": "application/x-www-form-urlencoded"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_logout_rejects_cross_site_cookie_request_without_deleting_session(
    tmp_path, headers
):
    app, service = make_app(tmp_path)

    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        raw_token = client.cookies["rtc_session"]
        response = client.post("/api/auth/logout", headers=headers, content="")

    assert response.status_code == 403
    assert response.json() == {"detail": "跨站请求被拒绝"}
    assert service.get_current_session(raw_token) is not None


def test_logout_allows_explicit_trusted_frontend_origin(tmp_path):
    origin = "https://frontend.example"
    app, _ = make_app(tmp_path, config_values={"CORS_ORIGINS": origin})

    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        response = client.post("/api/auth/logout", headers={"Origin": origin})

    assert response.status_code == 204


def test_logout_allows_same_private_request_origin_without_server_url(tmp_path):
    app, _ = make_app(tmp_path)

    with TestClient(app, base_url="http://localhost:3001") as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        response = client.post(
            "/api/auth/logout", headers={"Origin": "http://localhost:3001"}
        )

    assert response.status_code == 204


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "http://192.168.1.20:3000"]
)
def test_logout_allows_restricted_development_origin_with_https_server_url(
    tmp_path, origin
):
    app, service = make_app(
        tmp_path, config_values={"SERVER_URL": "https://tunnel.example"}
    )

    with TestClient(app, base_url="https://tunnel.example") as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        raw_token = client.cookies["rtc_session"]
        response = client.post("/api/auth/logout", headers={"Origin": origin})

    assert response.status_code == 204
    assert service.get_current_session(raw_token) is None


@pytest.mark.parametrize(
    ("path", "method"),
    [("/debug/chat", "post"), ("/debug/rag?query=hello", "get")],
)
def test_debug_routes_require_login(tmp_path, path, method):
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        response = (
            client.post(path, json={})
            if method == "post"
            else client.get(path)
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "请先登录"}


def test_logged_in_debug_routes_work_with_mocked_cloud_services(
    tmp_path, monkeypatch, capsys
):
    import main as main_module

    async def retrieve_stub(query):
        return "private-rag-context"

    monkeypatch.setattr(main_module.rag_service, "retrieve", retrieve_stub)
    monkeypatch.setattr(
        main_module.llm_service,
        "chat_stream",
        lambda messages, context: iter(()),
    )
    app, _ = make_app(tmp_path)

    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "password-123",
                "confirm_password": "password-123",
            },
        )
        chat = client.post(
            "/debug/chat", json={"history": [], "question": "private-question"}
        )
        rag = client.get("/debug/rag?query=private-question")

    assert chat.status_code == 200
    assert rag.status_code == 200
    assert rag.json()["retrieved_context"] == "private-rag-context"
    output = capsys.readouterr().out
    assert "private-question" not in output
    assert "private-rag-context" not in output


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://10.1.2.3:3000",
        "http://172.16.0.1:3000",
        "http://172.31.255.255:3000",
        "http://192.168.1.2:3000",
    ],
)
def test_dev_cors_allows_only_supported_private_origins(tmp_path, origin):
    app, _ = make_app(tmp_path)
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
    }
    with TestClient(app) as client:
        response = client.options("/api/auth/login", headers=headers)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize(
    "origin",
    [
        "http://8.8.8.8:3000",
        "http://10.1.2.3:3001",
        "http://172.32.0.1:3000",
        "https://10.1.2.3:3000",
        "https://app.example.com",
    ],
)
def test_cors_rejects_public_wrong_port_and_unconfigured_origins(tmp_path, origin):
    app, _ = make_app(tmp_path)
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
    }
    with TestClient(app) as client:
        response = client.options("/api/auth/login", headers=headers)

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_configured_full_cors_origin_is_allowed(tmp_path):
    origin = "https://app.example.com"
    app, _ = make_app(tmp_path, config_values={"CORS_ORIGINS": origin})
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
    }
    with TestClient(app) as client:
        response = client.options("/api/auth/login", headers=headers)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"

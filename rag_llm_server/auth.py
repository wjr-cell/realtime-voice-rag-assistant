import ipaddress
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from services.auth_service import (
    SESSION_TTL_SECONDS,
    AuthenticatedSession,
    AuthValidationError,
    InvalidCredentials,
    UsernameTaken,
)


COOKIE_NAME = "rtc_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


class CredentialsRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(CredentialsRequest):
    confirm_password: str


class UserResponse(BaseModel):
    id: int
    username: str


class AuthResponse(BaseModel):
    user: UserResponse


def _cookie_is_secure(request: Request) -> bool:
    return request.url.scheme == "https" or str(
        request.app.state.config.SERVER_URL
    ).startswith("https://")


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        expires=datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS),
        path="/",
        secure=_cookie_is_secure(request),
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value="",
        max_age=0,
        expires=0,
        path="/",
        secure=_cookie_is_secure(request),
        httponly=True,
        samesite="lax",
    )


def require_session(request: Request) -> AuthenticatedSession:
    authenticated = request.app.state.auth_service.get_current_session(
        request.cookies.get(COOKIE_NAME)
    )
    if authenticated is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return authenticated


def _canonical_origin(value: str) -> str:
    try:
        if "\\" in value:
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.hostname is None
        ):
            raise ValueError
        port = parsed.port
        hostname = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            normalized_host = hostname
        else:
            normalized_host = address.compressed
            if address.version == 6:
                normalized_host = f"[{normalized_host}]"
        normalized_port = f":{port}" if port is not None else ""
        return f"{parsed.scheme}://{normalized_host}{normalized_port}"
    except ValueError:
        raise ValueError("invalid origin") from None


def _is_local_or_private_origin(origin: str, port: int | None = None) -> bool:
    parsed = urlsplit(origin)
    if port is not None and parsed.port != port:
        return False
    hostname = parsed.hostname
    if hostname == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname or "")
    except ValueError:
        return False
    private_networks = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    return (
        address == ipaddress.ip_address("127.0.0.1")
        or address == ipaddress.ip_address("::1")
        or any(address in network for network in private_networks)
    )


def require_trusted_origin(request: Request) -> None:
    if not request.cookies.get(COOKIE_NAME):
        return
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="跨站请求被拒绝")

    origin_header = request.headers.get("origin")
    if not origin_header:
        return
    try:
        origin = _canonical_origin(origin_header)
    except ValueError:
        raise HTTPException(status_code=403, detail="跨站请求被拒绝") from None

    config = request.app.state.config
    trusted = set()
    for configured_origin in config.CORS_ORIGINS:
        try:
            trusted.add(_canonical_origin(configured_origin))
        except ValueError:
            continue
    if config.SERVER_URL:
        try:
            trusted.add(_canonical_origin(config.SERVER_URL))
        except ValueError:
            pass
    else:
        try:
            request_origin = _canonical_origin(str(request.base_url).rstrip("/"))
        except ValueError:
            request_origin = None
        if request_origin and _is_local_or_private_origin(request_origin):
            trusted.add(request_origin)
    if _is_local_or_private_origin(origin, port=3000):
        trusted.add(origin)

    if origin not in trusted:
        raise HTTPException(status_code=403, detail="跨站请求被拒绝")


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response):
    try:
        result = request.app.state.auth_service.register(
            payload.username, payload.password, payload.confirm_password
        )
    except UsernameTaken:
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    except AuthValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    set_session_cookie(response, request, result.token)
    return {"user": result.user}


@router.post("/login", response_model=AuthResponse)
def login(payload: CredentialsRequest, request: Request, response: Response):
    try:
        result = request.app.state.auth_service.login(payload.username, payload.password)
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="用户名或密码错误") from None
    set_session_cookie(response, request, result.token)
    return {"user": result.user}


@router.get("/me", response_model=AuthResponse)
def me(authenticated: AuthenticatedSession = Depends(require_session)):
    return {"user": authenticated.user}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    _: None = Depends(require_trusted_origin),
):
    request.app.state.auth_service.logout(request.cookies.get(COOKIE_NAME))
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_session_cookie(response, request)
    return response

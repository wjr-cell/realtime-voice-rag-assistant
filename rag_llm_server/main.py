import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import (
    clear_session_cookie,
    require_session,
    require_trusted_origin,
    router as auth_router,
)
from config import settings
from database import Database
from services.auth_service import AuthenticatedSession, AuthService
from services.llm_service import llm_service
from services.rag_service import rag_service
from services.utils import Signer
from services.voice_chat_service import (
    build_rtc_token,
    build_voice_chat_body,
    resolve_server_url,
)


IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
PRIVATE_DEV_ORIGIN_REGEX = (
    rf"^http://(?:10(?:\.{IPV4_OCTET}){{3}}|"
    rf"172\.(?:1[6-9]|2\d|3[01])(?:\.{IPV4_OCTET}){{2}}|"
    rf"192\.168(?:\.{IPV4_OCTET}){{2}}):3000$"
)


class ChatMessage(BaseModel):
    role: str
    content: str


class DebugRequest(BaseModel):
    history: Optional[List[ChatMessage]] = []
    question: str


def register_business_routes(app: FastAPI) -> None:
    @app.post("/getScenes")
    async def get_scenes(
        request: Request,
        session: AuthenticatedSession = Depends(require_session),
    ):
        config = request.app.state.config
        rtc = request.app.state.auth_service.get_or_create_rtc_session(
            session.raw_token
        )
        if rtc is None:
            raise HTTPException(status_code=401, detail="请先登录")
        token = build_rtc_token(config, rtc)

        return {
            "ResponseMetadata": {"Action": "getScenes"},
            "Result": {
                "scenes": [
                    {
                        "scene": {
                            "id": "Custom",
                            "name": "自定义助手",
                            "botName": "AiAgent",
                            "icon": "https://lf3-rtc-demo.volccdn.com/obj/rtc-aigc-assets/DoubaoAvatar.png",
                            "isInterruptMode": True,
                            "isVision": False,
                            "isScreenMode": False,
                            "isAvatarScene": None,
                            "avatarBgUrl": None,
                        },
                        "rtc": {
                            "AppId": config.RTC_APP_ID,
                            "RoomId": rtc["rtc_room_id"],
                            "UserId": rtc["rtc_user_id"],
                            "Token": token,
                        },
                        "VoiceChat": {},
                    }
                ]
            },
        }

    @app.post("/proxy")
    async def proxy(
        request: Request,
        session: AuthenticatedSession = Depends(require_session),
        _: None = Depends(require_trusted_origin),
    ):
        """代理接口，用于下发及转发 RTC 配置。"""
        config = request.app.state.config
        action = request.query_params.get("Action")
        version = request.query_params.get("Version", "2024-12-01")
        try:
            await request.json()
        except Exception:
            pass

        if action not in ("StartVoiceChat", "StopVoiceChat"):
            raise HTTPException(status_code=400, detail="不支持的 Action")

        fresh_session = request.app.state.auth_service.get_current_session(
            session.raw_token
        )
        if fresh_session is None:
            raise HTTPException(status_code=401, detail="请先登录")
        rtc = fresh_session.session
        if not all(
            rtc.get(field)
            for field in ("rtc_room_id", "rtc_user_id", "rtc_task_id")
        ):
            raise HTTPException(status_code=409, detail="请先获取场景配置")

        try:
            server_url = resolve_server_url(request, config)
        except ValueError:
            raise HTTPException(
                status_code=500, detail="服务地址配置不安全"
            ) from None

        request_body = build_voice_chat_body(
            action,
            config,
            rtc,
            server_url,
        )

        host = "rtc.volcengineapi.com"
        open_api_request_data = {
            "method": "POST",
            "path": "/",
            "params": {"Action": action, "Version": version},
            "headers": {"Host": host, "Content-Type": "application/json"},
            "body": request_body,
        }
        signer = Signer(open_api_request_data, "rtc")
        signer.add_authorization(
            {"accessKeyId": config.VOLC_AK, "secretKey": config.VOLC_SK}
        )
        url = f"https://{host}?Action={action}&Version={version}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=open_api_request_data["headers"],
                    json=request_body,
                    timeout=30.0,
                )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504, detail="RTC 服务响应超时"
            ) from None
        except httpx.RequestError:
            raise HTTPException(
                status_code=502, detail="RTC 服务调用失败"
            ) from None
        if not 200 <= response.status_code < 300:
            raise HTTPException(status_code=502, detail="RTC 服务调用失败")
        try:
            return response.json()
        except ValueError:
            raise HTTPException(
                status_code=502, detail="RTC 服务调用失败"
            ) from None

    @app.post("/api/chat_callback")
    async def chat_callback(request: Request):
        try:
            data = await request.json()
        except Exception:
            return {"text": ""}

        messages = data.get("messages", [])
        if not messages or messages[-1].get("role") != "user":
            return {"text": ""}

        async def generate_sse():
            rag_content = await rag_service.retrieve(
                messages[-1].get("content", "")
            )
            for chunk in llm_service.chat_stream(messages, rag_content):
                if chunk:
                    yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.post("/debug/chat")
    async def debug_chat(
        request: DebugRequest,
        session: AuthenticatedSession = Depends(require_session),
    ):
        current_messages = [
            {"role": message.role, "content": message.content}
            for message in request.history
        ]
        current_messages.append({"role": "user", "content": request.question})

        async def generate_text():
            total_usage = None
            rag_content = await rag_service.retrieve(request.question)
            print("DEBUG: 知识库查询完成")
            for chunk in llm_service.chat_stream(current_messages, rag_content):
                if chunk and chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
                if chunk and getattr(chunk, "usage", None):
                    total_usage = chunk.usage
            print("DEBUG: LLM 流式调用完成")
            if total_usage:
                print(
                    f"🎫 Token 统计: Total={total_usage.total_tokens} "
                    f"(P:{total_usage.prompt_tokens}, C:{total_usage.completion_tokens})"
                )

        return StreamingResponse(generate_text(), media_type="text/plain")

    @app.get("/debug/rag")
    async def debug_rag(
        query: str,
        session: AuthenticatedSession = Depends(require_session),
    ):
        if not query:
            return {"error": "请提供 query 参数"}
        context = await rag_service.retrieve(query)
        return {
            "query": query,
            "retrieved_context": context,
            "length": len(context) if context else 0,
            "status": "success" if context else "no_results_or_error",
        }


def create_app(config=settings, auth_service=None, validate_config=True) -> FastAPI:
    service = auth_service or AuthService(
        Database(Path(__file__).resolve().parent / "data" / "app.db")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if validate_config:
            missing = config.validate()
            if missing:
                raise RuntimeError(
                    "Missing required configuration: " + ", ".join(missing)
                )
        service.initialize()
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.auth_service = service
    app.state.config = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"]
        + config.CORS_ORIGINS,
        allow_origin_regex=PRIVATE_DEV_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, error: HTTPException):
        response = JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
        )
        if error.status_code == 401:
            clear_session_cookie(response, request)
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, error: RequestValidationError
    ):
        return JSONResponse(
            status_code=422, content={"detail": "请求参数不合法"}
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def sqlite_operational_error_handler(
        request: Request, error: sqlite3.OperationalError
    ):
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            return JSONResponse(
                status_code=503,
                content={"detail": "服务繁忙，请稍后重试"},
            )
        return JSONResponse(
            status_code=500, content={"detail": "服务内部错误"}
        )

    app.include_router(auth_router)
    register_business_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    print(f"🚀 Server running at {settings.SERVER_URL}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3001,
        reload=True,
        reload_dirs=[".", "services"],
        reload_excludes=["*/__pycache__/*", "*.pyc", ".venv/*", "*/.venv/*"],
    )

# 普通注册登录与动态 RTC 会话 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有 RTC Demo 增加开放的用户名密码注册/登录，在登录后按 Session 动态生成并复用 RoomId、UserId、TaskId 和 RTC Token，同时把 `rag_llm_server/.env` 缩减到必要的云端凭据与资源标识。

**Architecture:** FastAPI 使用 SQLite 保存用户和服务端 Session，Argon2 保存密码哈希，浏览器只持有 HttpOnly Cookie。`/getScenes` 原子创建 RTC 会话标识并签发现有官方格式 Token，`/proxy` 从同一 Session 读取标识；React 在挂载原 `MainPage` 前通过认证上下文完成登录门禁。

**Tech Stack:** Python 3.13、FastAPI、sqlite3、pwdlib/Argon2、pytest、React 18、TypeScript、Arco Design、Jest/Testing Library、火山引擎 RTC/Ark。

---

## 实施前约束

- 规格来源：[设计文档](../specs/2026-08-13-login-and-dynamic-rtc-session-design.md)。
- 当前工作区已有用户未提交改动：`rag_llm_server/config.py`、`rag_llm_server/main.py`、`rag_llm_server/services/rag_service.py`。开始每个任务前先看 `git diff -- <文件>`，在这些改动上做增量修改，禁止覆盖、还原或把它们混入无关提交。
- 所有提交使用精确路径 `git add`；不要使用 `git add .`。
- `.env` 被 Git 忽略。测试、日志、计划和提交中不得输出真实 AK/SK、AppKey、Ark API Key、RTC Token、密码或 Session Token。
- 使用 @superpowers:test-driven-development：每项功能先写失败测试，再写最小实现。
- 完成前使用 @superpowers:verification-before-completion，运行本文末尾完整验证矩阵。

## 文件职责图

| 文件 | 责任 |
| --- | --- |
| `rag_llm_server/config.py` | 显式加载本目录 `.env`、配置默认值、语音兼容规则、启动校验 |
| `rag_llm_server/database.py` | SQLite 建表、用户/Session 数据访问、原子 RTC ID get-or-create |
| `rag_llm_server/services/auth_service.py` | 用户名/密码规则、Argon2、Session Token 创建与验证 |
| `rag_llm_server/auth.py` | 认证 Pydantic 模型、Cookie、路由和 `require_session` 依赖 |
| `rag_llm_server/services/voice_chat_service.py` | 按 Session 构造 Start/Stop VoiceChat 请求体和回调 URL |
| `rag_llm_server/main.py` | 组装应用、CORS、保护 `/getScenes`、`/proxy` 和调试接口，保留 RTC 云回调 |
| `rag_llm_server/tests/*` | 后端单元与 HTTP 集成测试 |
| `src/app/http.ts` | 统一带 Cookie 的 fetch、HTTP 错误和 401 事件 |
| `src/auth/api.ts` | register/login/me/logout 类型化调用 |
| `src/auth/AuthContext.tsx` | 登录状态恢复、登录/注册/退出和 401 响应 |
| `src/pages/AuthPage/*` | 简单登录/注册表单 |
| `src/components/AuthUserActions/*` | 主页面用户名和退出按钮 |
| `src/App.tsx` | 认证加载/错误/登录页/原 MainPage 门禁 |
| `src/app/base.ts`、`src/app/type.ts` | 现有 RTC API 支持 Cookie 和可选 AbortSignal |
| `src/lib/RtcClient.ts`、`src/lib/useCommon.ts` | 退出时可中止 StopVoiceChat，保证 3 秒上限 |

---

### Task 1: 建立测试基线和依赖

**Files:**
- Modify: `rag_llm_server/pyproject.toml`
- Modify: `rag_llm_server/requirements.txt`
- Modify: `rag_llm_server/uv.lock`
- Modify: `package.json`
- Modify: `package-lock.json`
- Create: `rag_llm_server/tests/conftest.py`
- Create: `src/testSetup.ts`
- Create: `src/setupTests.ts`

- [ ] **Step 1: 记录当前基线，不改业务文件**

Run:

```bash
git status --short
git diff -- rag_llm_server/config.py rag_llm_server/main.py rag_llm_server/services/rag_service.py
npm run build
cd rag_llm_server && .venv/bin/python -m py_compile *.py services/*.py
```

Expected: 前端 build 和 Python 编译通过；若基线本来失败，先记录原始错误，不在此任务顺手修复无关问题。

- [ ] **Step 2: 添加后端运行与测试依赖**

在 `rag_llm_server/pyproject.toml` 的运行依赖加入：

```toml
"pwdlib[argon2]>=0.2.1,<1",
```

并增加：

```toml
[dependency-groups]
dev = [
    "pytest>=8,<9",
]
```

在 `rag_llm_server/requirements.txt` 同步加入运行依赖：

```text
pwdlib[argon2]>=0.2.1,<1
```

Run:

```bash
cd rag_llm_server && uv lock && uv sync --dev
```

Expected: `pwdlib`、Argon2 后端和 pytest 安装成功，`uv.lock` 更新。

- [ ] **Step 3: 添加前端测试依赖和统一 setup**

Run:

```bash
npm install --save-dev @testing-library/react@16.3.2 @testing-library/user-event@14.6.4 @testing-library/jest-dom@6.9.1
```

创建 `src/testSetup.ts`：

```ts
import '@testing-library/jest-dom';
```

在 `package.json` 的 Jest 配置或 `src/setupTests.ts` 约定中接入该文件；优先创建 CRA 默认识别的 `src/setupTests.ts` 并从中导入 `./testSetup`，不要 eject。

- [ ] **Step 4: 创建 pytest import 基线**

`rag_llm_server/tests/conftest.py`：

```python
from pathlib import Path
import sys

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
```

Run:

```bash
cd rag_llm_server && uv run pytest --collect-only -q
npm test -- --watchAll=false --passWithNoTests
```

Expected: 两端测试命令均退出 0。

- [ ] **Step 5: 提交依赖与测试基线**

```bash
git add rag_llm_server/pyproject.toml rag_llm_server/requirements.txt rag_llm_server/uv.lock rag_llm_server/tests/conftest.py package.json package-lock.json src/testSetup.ts src/setupTests.ts
git commit -m "test: add auth test foundations"
```

---

### Task 2: 精简并验证配置

**Files:**
- Modify: `rag_llm_server/config.py`
- Create: `rag_llm_server/.env.example`
- Create: `rag_llm_server/tests/test_config.py`

- [ ] **Step 1: 写失败的配置测试**

`rag_llm_server/tests/test_config.py` 至少覆盖：

```python
from config import Config


BASE = {
    "VOLC_ACCESS_KEY": "ak",
    "VOLC_SECRET_KEY": "sk",
    "ARK_API_KEY": "ark",
    "ARK_ENDPOINT_ID": "ep",
    "RTC_APP_ID": "rtc-app",
    "RTC_APP_KEY": "rtc-key",
    "VOLC_ACCOUNT_ID": "account",
    "KB_COLLECTION_NAME": "knowledge",
}


def test_speech_app_id_fills_asr_and_tts():
    config = Config({**BASE, "SPEECH_APP_ID": "speech"})
    assert config.ASR_APP_ID == "speech"
    assert config.TTS_APP_ID == "speech"
    assert config.KB_PROJECT_NAME == "default"
    assert config.validate() == []


def test_legacy_pair_remains_valid():
    config = Config({**BASE, "ASR_APP_ID": "asr", "TTS_APP_ID": "tts"})
    assert config.validate() == []


def test_partial_legacy_speech_config_is_rejected():
    config = Config({**BASE, "ASR_APP_ID": "asr"})
    assert "SPEECH_APP_ID or TTS_APP_ID" in config.validate()


def test_cors_origins_are_trimmed_and_empty_values_removed():
    config = Config({**BASE, "SPEECH_APP_ID": "speech", "CORS_ORIGINS": " https://app.example.com, ,https://admin.example.com "})
    assert config.CORS_ORIGINS == ["https://app.example.com", "https://admin.example.com"]
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd rag_llm_server && uv run pytest tests/test_config.py -q
```

Expected: FAIL，因为当前 `Config` 不接受映射、没有 `validate()` 和 `SPEECH_APP_ID` 继承逻辑。

- [ ] **Step 3: 实现可测试 Config**

将 `config.py` 改为显式从 `rag_llm_server/.env` 加载，核心接口保持下面形态：

```python
from collections.abc import Mapping
import os
from pathlib import Path
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().with_name(".env")
load_dotenv(ENV_FILE)


class Config:
    def __init__(self, environ: Mapping[str, str] | None = None):
        env = os.environ if environ is None else environ
        self.VOLC_AK = env.get("VOLC_ACCESS_KEY")
        self.VOLC_SK = env.get("VOLC_SECRET_KEY")
        self.ARK_ENDPOINT_ID = env.get("ARK_ENDPOINT_ID")
        self.ARK_API_KEY = env.get("ARK_API_KEY")
        self.RTC_APP_ID = env.get("RTC_APP_ID")
        self.RTC_APP_KEY = env.get("RTC_APP_KEY")
        self.SERVER_URL = (env.get("SERVER_URL") or "").rstrip("/")
        self.VOLC_ACCOUNT_ID = env.get("VOLC_ACCOUNT_ID")
        self.KB_COLLECTION_NAME = env.get("KB_COLLECTION_NAME")
        self.KB_PROJECT_NAME = env.get("KB_PROJECT_NAME") or "default"
        speech_app_id = env.get("SPEECH_APP_ID")
        self.ASR_APP_ID = env.get("ASR_APP_ID") or speech_app_id
        self.TTS_APP_ID = env.get("TTS_APP_ID") or speech_app_id
        self.CORS_ORIGINS = [v.strip() for v in (env.get("CORS_ORIGINS") or "").split(",") if v.strip()]

    def validate(self) -> list[str]:
        required = {
            "VOLC_ACCESS_KEY": self.VOLC_AK,
            "VOLC_SECRET_KEY": self.VOLC_SK,
            "ARK_ENDPOINT_ID": self.ARK_ENDPOINT_ID,
            "ARK_API_KEY": self.ARK_API_KEY,
            "RTC_APP_ID": self.RTC_APP_ID,
            "RTC_APP_KEY": self.RTC_APP_KEY,
            "VOLC_ACCOUNT_ID": self.VOLC_ACCOUNT_ID,
            "KB_COLLECTION_NAME": self.KB_COLLECTION_NAME,
        }
        missing = [name for name, value in required.items() if not value]
        if not self.ASR_APP_ID:
            missing.append("SPEECH_APP_ID or ASR_APP_ID")
        if not self.TTS_APP_ID:
            missing.append("SPEECH_APP_ID or TTS_APP_ID")
        return missing


settings = Config()
```

删除 `DEFAULT_ROOM_ID`、`DEFAULT_USER_ID`。不要把任何当前 `.env` 值复制进代码或测试。

- [ ] **Step 4: 添加无秘密的配置样例**

`rag_llm_server/.env.example` 仅列出：

```dotenv
VOLC_ACCESS_KEY=
VOLC_SECRET_KEY=
ARK_API_KEY=
ARK_ENDPOINT_ID=
RTC_APP_ID=
RTC_APP_KEY=
VOLC_ACCOUNT_ID=
KB_COLLECTION_NAME=
SPEECH_APP_ID=

# Optional
# KB_PROJECT_NAME=default
# SERVER_URL=https://your-public-api.example.com
# CORS_ORIGINS=https://your-frontend.example.com
# ASR_APP_ID=
# TTS_APP_ID=
```

- [ ] **Step 5: 验证并提交**

Run:

```bash
cd rag_llm_server && uv run pytest tests/test_config.py -q
```

Expected: PASS。

```bash
git add rag_llm_server/config.py rag_llm_server/.env.example rag_llm_server/tests/test_config.py
git commit -m "refactor: validate minimal server configuration"
```

---

### Task 3: 实现 SQLite 用户和 Session 存储

**Files:**
- Modify: `rag_llm_server/database.py`
- Create: `rag_llm_server/tests/test_database.py`
- Modify: `.gitignore`

- [ ] **Step 1: 写数据库失败测试**

`rag_llm_server/tests/test_database.py` 使用不存在的嵌套路径 `tmp_path / "nested" / "app.db"`，覆盖：自动创建父目录、建表、用户名唯一、Session 读取/删除/过期清理，以及并发首次 RTC ID 创建。关键断言：

```python
from concurrent.futures import ThreadPoolExecutor
from database import Database


def test_get_or_create_rtc_ids_is_atomic(tmp_path):
    db = Database(tmp_path / "nested" / "app.db")
    db.initialize()
    assert db.path.parent.is_dir()
    user = db.create_user("alice", "hash")
    db.create_session("session-hash", user["id"], expires_at=4_102_444_800)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: db.get_or_create_rtc_ids("session-hash"), range(4)))

    assert len({r["rtc_room_id"] for r in results}) == 1
    assert len({r["rtc_task_id"] for r in results}) == 1
    assert {r["rtc_user_id"] for r in results} == {f"user_{user['id']}"}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd rag_llm_server && uv run pytest tests/test_database.py -q
```

Expected: FAIL，`Database` 尚不存在。

- [ ] **Step 3: 实现数据库类和完整 schema**

`database.py` 使用每次操作独立连接、Row factory、外键和 5 秒锁等待：

```python
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
```

`Database.initialize()` 首先执行 `self.path.parent.mkdir(parents=True, exist_ok=True)`，再连接 SQLite。`Database` 必须提供明确方法：

```python
initialize()
create_user(username, password_hash) -> dict
get_user_by_username(username) -> dict | None
get_user_by_id(user_id) -> dict | None
create_session(token_hash, user_id, expires_at) -> dict
get_session(token_hash, now=None) -> dict | None
delete_session(token_hash) -> None
delete_expired_sessions(now=None) -> int
get_or_create_rtc_ids(token_hash) -> dict
```

`get_or_create_rtc_ids()` 使用 `BEGIN IMMEDIATE`，事务内重新读 Session；空值时生成 `room_<uuid4.hex>`、`user_<user_id>`、`task_<uuid4.hex>`，UPDATE 后重新 SELECT 并返回最终持久化值。连接参数包含 `timeout=5.0` 和 `PRAGMA busy_timeout=5000`。

- [ ] **Step 4: 忽略运行期数据库**

在 `.gitignore` 增加：

```gitignore
/rag_llm_server/data/
```

- [ ] **Step 5: 验证并提交**

```bash
cd rag_llm_server && uv run pytest tests/test_database.py -q
```

Expected: PASS，包括并发用例。

```bash
git add rag_llm_server/database.py rag_llm_server/tests/test_database.py .gitignore
git commit -m "feat: persist users and RTC sessions"
```

---

### Task 4: 实现认证领域服务

**Files:**
- Create: `rag_llm_server/services/auth_service.py`
- Create: `rag_llm_server/tests/test_auth_service.py`

- [ ] **Step 1: 写认证失败测试**

覆盖：用户名 trim/ASCII 小写、非法字符、3–32 长度、密码 8–72、确认密码、Argon2 哈希、重复注册、统一登录失败、Session 原始 Token 不落库、7 天过期、启动初始化清理历史过期 Session、logout。

关键断言：

```python
def test_register_hashes_password_and_returns_session(auth_service, database):
    result = auth_service.register(" Alice_01 ", "password1", "password1")
    stored = database.get_user_by_username("alice_01")
    assert result.user["username"] == "alice_01"
    assert stored["password_hash"] != "password1"
    assert result.token not in database.path.read_text(errors="ignore")


def test_unknown_user_and_wrong_password_raise_same_error(auth_service):
    with pytest.raises(InvalidCredentials, match="用户名或密码错误"):
        auth_service.login("missing", "password1")
    auth_service.register("alice", "password1", "password1")
    with pytest.raises(InvalidCredentials, match="用户名或密码错误"):
        auth_service.login("alice", "wrongpass")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd rag_llm_server && uv run pytest tests/test_auth_service.py -q
```

Expected: FAIL，认证服务和异常尚不存在。

- [ ] **Step 3: 实现最小认证服务**

`services/auth_service.py` 定义：

```python
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$", re.ASCII)
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
    token: str


@dataclass(frozen=True)
class AuthenticatedSession:
    user: dict
    session: dict
    raw_token: str = field(repr=False)
```

`AuthService` 公开：

```python
initialize() -> None
register(username, password, confirm_password) -> AuthResult
login(username, password) -> AuthResult
get_current_user(raw_token) -> dict | None
get_current_session(raw_token) -> AuthenticatedSession | None
logout(raw_token) -> None
get_or_create_rtc_session(raw_token) -> dict
```

`initialize()` 调用 `database.initialize()`，随后调用 `database.delete_expired_sessions()`。Session Token 使用 `secrets.token_urlsafe(32)`，落库前用 SHA-256 十六进制摘要。用户不存在时仍验证 `DUMMY_HASH`，避免明显的用户名枚举时序差异。

- [ ] **Step 4: 验证并提交**

```bash
cd rag_llm_server && uv run pytest tests/test_auth_service.py -q
```

Expected: PASS。

```bash
git add rag_llm_server/services/auth_service.py rag_llm_server/tests/test_auth_service.py
git commit -m "feat: add password and session authentication"
```

---

### Task 5: 增加认证 HTTP 接口、Cookie 和 CORS

**Files:**
- Create: `rag_llm_server/auth.py`
- Modify: `rag_llm_server/main.py`
- Modify: `rag_llm_server/services/llm_service.py`
- Create: `rag_llm_server/tests/test_auth_api.py`
- Create: `rag_llm_server/tests/test_llm_service.py`

- [ ] **Step 1: 写 HTTP 失败测试**

用 `fastapi.testclient.TestClient` 和临时 `Database` 构建测试 app，覆盖：

- register `201`、规范化用户 JSON 和 `rtc_session` Cookie。
- 重复注册 `409 {"detail": "用户名已存在"}`。
- login `200`；错误账号/密码统一 `401`。
- me `200`；缺 Cookie/过期 `401` 并清 Cookie。
- logout 始终 `204` 并清 Cookie。
- 注册请求校验失败的 `422` 响应始终包含可显示的字符串 `detail`。
- Cookie 包含 `HttpOnly`、`SameSite=lax`、7 天 `Max-Age`；HTTPS/HTTPS `SERVER_URL` 时包含 `Secure`。
- 默认 localhost Origin、RFC1918 `:3000` 预检成功，公网 IP、错误端口和未配置域名失败；显式同站 `CORS_ORIGINS` 成功。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd rag_llm_server && uv run pytest tests/test_auth_api.py -q
```

Expected: FAIL，路由和 app factory 尚不存在。

- [ ] **Step 3: 让 Ark 客户端延迟到首次 LLM 调用时创建**

先在 `tests/test_llm_service.py` 断言 `LLMService(Config({}))` 构造时不调用 Ark、不因缺少 `ARK_API_KEY` 抛异常；只有调用 `chat_stream()` 时才创建客户端或返回现有错误流。修改 `services/llm_service.py`：构造函数只保存 config 和 `self.client = None`，新增 `_get_client()` 在首次 `chat_stream()` 时用当前相同的 base URL、API Key 和 timeout 创建并缓存 Ark。生产行为、模型参数、系统提示词和流式输出保持不变。

Run:

```bash
cd rag_llm_server && uv run pytest tests/test_llm_service.py -q
```

Expected: PASS；无 `.env` 的干净环境可以安全 import `main`，但真实 LLM 调用仍会因缺配置被启动校验阻止。

- [ ] **Step 4: 实现 auth router 和 Cookie helper**

`auth.py` 使用 `APIRouter(prefix="/api/auth")`，请求/响应模型固定为：

```python
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
```

Cookie helper 必须统一 register/login 的写入属性和 me/logout 的清理行为。`require_session(request)` 从 `request.app.state.auth_service` 获取服务，从 `rtc_session` Cookie 解析当前 Session；失败抛 `HTTPException(401, "请先登录")`。在 app 上注册统一 `HTTPException` handler：保留状态码、`detail` 和原 headers；只要状态码是 `401`，就在 JSONResponse 上调用与 logout 相同参数的 `delete_cookie("rtc_session", path="/")`。这样当前 me 以及 Task 6 将保护的 `/getScenes`、`/proxy` 都会清 Cookie。对 FastAPI/Pydantic 自动产生的 `RequestValidationError` 增加 handler，把字段错误归纳成 `{"detail": "请求参数不合法"}` 字符串，避免前端收到数组后显示 `[object Object]`。

- [ ] **Step 5: 将 main.py 改为可测试 app factory**

保留用户当前业务改动，在其外围增加。工厂不得在函数执行或模块 import 时连接/初始化数据库；初始化和配置校验放入 lifespan，测试传入临时 AuthService：

```python
PRIVATE_ORIGIN_REGEX = (
    r"^http://(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):3000$"
)


def create_app(config=settings, auth_service=None, validate_config=True) -> FastAPI:
    service = auth_service or AuthService(
        Database(Path(__file__).resolve().parent / "data" / "app.db")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if validate_config:
            missing = config.validate()
            if missing:
                raise RuntimeError(f"缺少配置: {', '.join(missing)}")
        service.initialize()
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.auth_service = service
    app.state.config = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", *config.CORS_ORIGINS],
        allow_origin_regex=PRIVATE_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    # 在工厂内注册或包含现有业务路由
    return app


app = create_app()
```

`AuthService.initialize()` 按 Task 4 的唯一实现先委托 `self.database.initialize()`，再调用 `self.database.delete_expired_sessions()`；不得在 Task 5 覆盖或弱化该行为。模块级 `app = create_app()` 允许构造对象，但不得校验配置、建目录或打开数据库；这些动作只能在该 app 真正进入 lifespan 时发生。测试调用 `create_app(test_config, AuthService(Database(tmp_path / "app.db")), validate_config=False)`，因此导入 `main` 和启动测试 app 都不会触碰真实 `data/app.db`。如果直接移动所有现有装饰器会产生大范围 diff，可将现有 handler 注册提取成 `register_business_routes(app)`，但不要复制现有回调逻辑。

- [ ] **Step 6: 验证并提交**

```bash
cd rag_llm_server && uv run pytest tests/test_llm_service.py tests/test_auth_api.py -q
```

Expected: PASS。

```bash
git add rag_llm_server/auth.py rag_llm_server/main.py rag_llm_server/services/llm_service.py rag_llm_server/tests/test_auth_api.py rag_llm_server/tests/test_llm_service.py
git commit -m "feat: expose cookie based auth APIs"
```

---

### Task 6: 将 `/getScenes` 和 `/proxy` 绑定登录 Session

**Files:**
- Create: `rag_llm_server/services/voice_chat_service.py`
- Modify: `rag_llm_server/main.py`
- Create: `rag_llm_server/tests/test_rtc_session_api.py`
- Create: `rag_llm_server/tests/test_voice_chat_service.py`
- Create: `rag_llm_server/tests/test_token_build.py`

- [ ] **Step 1: 写 RTC Token 与 Session 失败测试**

覆盖：

- 未登录 `/getScenes`、`/proxy` 返回 `401`。
- 未登录 `/debug/chat`、`/debug/rag` 返回 `401`；登录后保留原业务响应和调试功能，避免开放注册环境下匿名消耗云资源或读取调试结果。
- 过期 Cookie 访问 `/getScenes`、`/proxy` 返回 `401` 且响应清除 Cookie。
- 登录后首次 `/getScenes` 返回原 `ResponseMetadata/Result.scenes` 结构。
- 同 Session 两次调用复用 RoomId/UserId/TaskId，Token 可重新签发。
- 不同登录 Session 的 RoomId、TaskId 不同；同一用户的 UserId 相同。
- 未调用 `/getScenes` 就调用 `/proxy` 返回 `409`。
- Token 解包得到正确 AppId、RoomId、UserId、24 小时有效期、发布/订阅权限。
- SQLite 锁超过 5 秒时映射为可重试的 `503`，不返回堆栈或数据库路径。
- RTC OpenAPI 超时、非 JSON 响应、非 2xx 响应都返回稳定 JSON 错误结构，不泄漏 Authorization Header。

在 `test_voice_chat_service.py` 精确断言：

```python
def test_start_and_stop_share_global_app_room_and_task():
    rtc = {"rtc_room_id": "room_a", "rtc_user_id": "user_1", "rtc_task_id": "task_a"}
    start = build_voice_chat_body("StartVoiceChat", SETTINGS, rtc, "https://api.example.com")
    stop = build_voice_chat_body("StopVoiceChat", SETTINGS, rtc, "https://api.example.com")
    assert start["AppId"] == stop["AppId"] == SETTINGS.RTC_APP_ID
    assert start["RoomId"] == stop["RoomId"] == "room_a"
    assert start["TaskId"] == stop["TaskId"] == "task_a"
    assert start["AgentConfig"]["TargetUserId"] == ["user_1"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd rag_llm_server && uv run pytest tests/test_token_build.py tests/test_voice_chat_service.py tests/test_rtc_session_api.py -q
```

Expected: FAIL，现有接口仍使用默认 ID，且没有可测试的 VoiceChat body builder/Token parser。

- [ ] **Step 3: 在测试中解析并验证现有 Token，不改官方生成代码**

在 `tests/test_token_build.py` 内写局部 decoder，按 `VERSION + 24 位 AppId + Base64(消息+签名)` 和小端字节格式解析测试 Token，验证消息字段和权限。不修改 `services/token_build.py` 的 `AccessToken.serialize()` 或字节格式，也不要记录 AppKey 或 Token。

- [ ] **Step 4: 提取 VoiceChat 请求体构造**

`services/voice_chat_service.py` 提供：

```python
def build_rtc_token(config: Config, rtc: dict) -> str:
    token = AccessToken(
        config.RTC_APP_ID,
        config.RTC_APP_KEY,
        rtc["rtc_room_id"],
        rtc["rtc_user_id"],
    )
    token.add_privilege(PRIVILEGES["PrivSubscribeStream"], 0)
    token.add_privilege(PRIVILEGES["PrivPublishStream"], 0)
    token.expire_time(int(time.time()) + 24 * 60 * 60)
    return token.serialize()


def resolve_server_url(request: Request, config: Config) -> str:
    return config.SERVER_URL or str(request.base_url).rstrip("/")


def build_voice_chat_body(action: str, config: Config, rtc: dict, server_url: str) -> dict:
    if action == "StartVoiceChat":
        return {
            "AppId": config.RTC_APP_ID,
            "RoomId": rtc["rtc_room_id"],
            "TaskId": rtc["rtc_task_id"],
            "AgentConfig": {
                "TargetUserId": [rtc["rtc_user_id"]],
                "WelcomeMessage": EXISTING_WELCOME_MESSAGE,
                "UserId": "AiAgent",
                "EnableConversationStateCallback": True,
            },
            "Config": build_existing_asr_tts_llm_config(config, server_url),
        }
    if action == "StopVoiceChat":
        return {"AppId": config.RTC_APP_ID, "RoomId": rtc["rtc_room_id"], "TaskId": rtc["rtc_task_id"]}
    raise ValueError(f"不支持的 Action: {action}")
```

`build_existing_asr_tts_llm_config()` 原样搬运当前 ASR/TTS/LLM 配置值，不改变 Provider、Cluster、音色、欢迎语、InterruptMode 或回调协议。

- [ ] **Step 5: 保护并改造 `/getScenes`**

为 handler 注入当前 Session：

```python
@app.post("/getScenes")
async def get_scenes(request: Request, session=Depends(require_session)):
    config = request.app.state.config
    rtc = request.app.state.auth_service.get_or_create_rtc_session(session.raw_token)
    token = build_rtc_token(config, rtc)
    # 返回现有完全相同的 scenes 外形
```

依赖对象不能把原始 Token写入日志或响应；若为调用服务需要携带 raw token，使用不可 repr 的 dataclass 字段或仅保存在 request state。

- [ ] **Step 6: 保护并改造 `/proxy`**

- 从 Session 读取已经存在的 RTC 字段；为空返回 `409 {"detail": "请先获取场景配置"}`。
- Start/Stop 调用 `build_voice_chat_body()`。
- `/proxy` 仅允许 `StartVoiceChat` 和 `StopVoiceChat`；缺失或其他 Action 在签名和网络请求前返回稳定 `400`。开放注册用户不得借助服务端 AK/SK 获得任意 RTC OpenAPI 签名代理能力。
- 删除打印完整 incoming body 的日志，改为只打印 Action 和远端 RequestId/错误码。
- SQLite busy timeout 转为 `503 {"detail": "服务繁忙，请稍后重试"}`。
- RTC OpenAPI 超时转为 `504 {"detail": "RTC 服务响应超时"}`。
- RTC OpenAPI 非 2xx 或无法解析 JSON 转为 `502 {"detail": "RTC 服务调用失败"}`。
- RTC 正常 HTTP 响应中的现有 `ResponseMetadata.Error` 结构原样返回，让前端继续使用当前 `resultHandler`；错误日志不得包含签名 Header。

- [ ] **Step 7: 验证并提交**

```bash
cd rag_llm_server && uv run pytest tests/test_token_build.py tests/test_voice_chat_service.py tests/test_rtc_session_api.py -q
```

Expected: PASS。

```bash
git add rag_llm_server/services/voice_chat_service.py rag_llm_server/main.py rag_llm_server/tests/test_rtc_session_api.py rag_llm_server/tests/test_voice_chat_service.py rag_llm_server/tests/test_token_build.py
git commit -m "feat: bind RTC configuration to login sessions"
```

---

### Task 7: 增加前端统一 HTTP 和认证状态

**Files:**
- Modify: `src/config/index.ts`
- Create: `src/app/http.ts`
- Modify: `src/app/base.ts`
- Modify: `src/app/type.ts`
- Create: `src/auth/api.ts`
- Create: `src/auth/AuthContext.tsx`
- Create: `src/auth/AuthContext.test.tsx`

- [ ] **Step 1: 写认证上下文失败测试**

Mock `global.fetch`，覆盖：

- 首次 `/api/auth/me` 请求带 `credentials: 'include'`。
- me 成功进入 authenticated。
- me `401` 进入 unauthenticated。
- 网络错误进入 error 并可 retry。
- login/register 成功保存 `user`；失败展示 `detail`。
- register 将前端 `confirmPassword` 明确映射为后端 `confirm_password`，测试断言实际 fetch JSON。
- 任意普通 API 发出全局 401 事件后清除当前用户。
- development 默认请求当前主机的 `:3001`，production 默认请求 `window.location.origin`，显式 `REACT_APP_API_BASE` 优先。

- [ ] **Step 2: 运行测试确认失败**

```bash
npm test -- --watchAll=false src/auth/AuthContext.test.tsx
```

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 修正开发与生产 API 基址**

修改 `src/config/index.ts`：

```ts
const configuredApiBase = process.env.REACT_APP_API_BASE?.replace(/\/$/, '');
export const AIGC_PROXY_HOST =
  configuredApiBase ||
  (process.env.NODE_ENV === 'development'
    ? `http://${window.location.hostname}:3001`
    : window.location.origin);
```

开发环境保持当前跨端口行为；生产构建默认走同源反向代理，避免 HTTPS 页面请求 HTTP `:3001` 产生混合内容。需要独立同站 Origin 时再显式设置 `REACT_APP_API_BASE`。

- [ ] **Step 4: 实现统一 HTTP helper**

`src/app/http.ts`：

```ts
export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const UNAUTHORIZED_EVENT = 'auth:unauthorized';

export async function apiFetch(path: string, init: RequestInit = {}, emit401 = true) {
  const response = await fetch(`${AIGC_PROXY_HOST}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'content-type': 'application/json', ...(init.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 && emit401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new HttpError(response.status, payload.detail || '请求失败');
  }
  return response;
}
```

认证 login 的 `401` 调用使用 `emit401=false`，避免重复全局事件。`204` logout 不调用 `.json()`。

- [ ] **Step 5: 让现有 RTC API 复用 helper并统一异步函数类型**

`requestGetMethod`、`requestPostMethod` 和 `generateAPIs` 的生成函数接受第二个可选 `RequestInit`，向 `apiFetch` 透传 `signal`；所有现有单参数调用保持兼容。删除未使用的同步 `RequestFn` 联合分支，统一更新 `src/app/type.ts`：

```ts
type PromiseRequestFn = (
  params?: RequestParams,
  init?: RequestInit
) => Promise<any>;

export type Apis<T extends readonly ApiConfig[]> = Record<
  ApiNames<T>,
  PromiseRequestFn
>;
```

成功后继续使用现有 `resultHandler`，保持 RTC 响应处理逻辑。

- [ ] **Step 6: 实现 auth API 和 Context**

`src/auth/api.ts` 固定类型并在边界处转换命名风格：

```ts
export interface AuthUser { id: number; username: string }
export interface AuthPayload { user: AuthUser }
export interface LoginInput { username: string; password: string }
export interface RegisterInput extends LoginInput { confirmPassword: string }
export const getMe = () => authJson('/api/auth/me', undefined, true);
export const login = (body: LoginInput) => authJson('/api/auth/login', body, false);
export const register = ({ confirmPassword, ...body }: RegisterInput) =>
  authJson('/api/auth/register', { ...body, confirm_password: confirmPassword }, false);
export const logout = () => apiFetch('/api/auth/logout', { method: 'POST' }, false);
```

`AuthContext` 状态使用明确联合类型 `loading | authenticated | unauthenticated | error`，对外提供 `user`、`login`、`register`、`logout`、`retry`。监听 `UNAUTHORIZED_EVENT` 并切换到 unauthenticated。

- [ ] **Step 7: 验证并提交**

```bash
npm test -- --watchAll=false src/auth/AuthContext.test.tsx
npm run build
```

Expected: PASS，TypeScript build 无错误。

```bash
git add src/config/index.ts src/app/http.ts src/app/base.ts src/app/type.ts src/auth/api.ts src/auth/AuthContext.tsx src/auth/AuthContext.test.tsx
git commit -m "feat: add frontend authentication state"
```

---

### Task 8: 实现登录页、应用门禁和有界退出

**Files:**
- Modify: `src/App.tsx`
- Create: `src/pages/AuthPage/index.tsx`
- Create: `src/pages/AuthPage/index.module.less`
- Create: `src/pages/AuthPage/index.test.tsx`
- Create: `src/components/AuthUserActions/index.tsx`
- Create: `src/components/AuthUserActions/index.module.less`
- Create: `src/components/AuthUserActions/index.test.tsx`
- Modify: `src/pages/MainPage/index.tsx`
- Modify: `src/lib/useCommon.ts`
- Modify: `src/lib/RtcClient.ts`
- Create: `src/App.test.tsx`

- [ ] **Step 1: 写 UI 门禁失败测试**

覆盖：

- 未登录显示用户名、密码、登录按钮和注册切换，不挂载 `MainPage`，因此没有 `/getScenes`。
- 登录成功挂载原 MainPage 并调用 `/getScenes`。
- 注册模式有确认密码；前端密码不一致时不发请求。
- loading 显示加载状态；网络 error 显示重试按钮。
- Header 显示规范化用户名和退出按钮。
- 退出按钮在清理成功、失败或 3 秒超时后都会调用 logout，且提交期间禁用。
- 即使任一 RTC 设备停止或 `leaveRoom()` Promise 永不 settle，logout 仍会在 3 秒后调用。
- `RtcClient.joinRoom()` 的控制台输出不包含 RTC Token。

- [ ] **Step 2: 运行测试确认失败**

```bash
npm test -- --watchAll=false src/App.test.tsx src/pages/AuthPage/index.test.tsx src/components/AuthUserActions/index.test.tsx
```

Expected: FAIL，页面和门禁尚不存在。

- [ ] **Step 3: 实现登录/注册页**

使用现有 Arco `Form`、`Input`、`Button`、`Alert` 或等价组件：

```tsx
type Mode = 'login' | 'register';

// 登录字段：username/password
// 注册字段：username/password/confirmPassword
// submit 时 await context.login/register；错误显示 error.message
// loading 时禁用 submit，切换模式时清理密码和错误
```

样式只负责居中卡片、响应式宽度和与现有主题一致的间距；不重做主页面品牌。

- [ ] **Step 4: 在 App 中增加认证门禁**

```tsx
function AppContent() {
  const auth = useAuth();
  if (auth.status === 'loading') return <AuthLoading />;
  if (auth.status === 'error') return <AuthLoadError onRetry={auth.retry} />;
  if (auth.status === 'unauthenticated') return <AuthPage />;
  return <MainPage />;
}

function App() {
  return <AuthProvider><BrowserRouter><AppContent /></BrowserRouter></AuthProvider>;
}
```

保留当前未知路由落回 MainPage 的行为；未登录时任何路由均显示 AuthPage。

- [ ] **Step 5: 让 StopVoiceChat 支持 AbortSignal**

沿调用链增加可选 signal，现有调用不变：

```ts
// RtcClient.ts
stopAgent = async (scene: string, signal?: AbortSignal) => {
  try {
    if (this.audioBotEnabled || sessionStorage.getItem('audioBotEnabled')) {
      await Apis.VoiceChat.StopVoiceChat({ SceneID: scene }, { signal });
    }
  } finally {
    this.audioBotStartTime = 0;
    sessionStorage.removeItem('audioBotEnabled');
    this.audioBotEnabled = false;
  }
};
```

在 `useCommon.ts` 的现有 `useLeave()` 中，把返回函数签名改为 `return async function (signal?: AbortSignal)`，并确保 Stop 失败/Abort 时仍然离房和清 Redux：

```ts
return async function (signal?: AbortSignal) {
  try {
    await RtcClient.stopAgent(idRef.current, signal);
  } finally {
    await Promise.allSettled([
      RtcClient.stopAudioCapture(),
      RtcClient.stopScreenCapture(),
      RtcClient.stopVideoCapture(),
    ]);
    try {
      await RtcClient.leaveRoom();
    } finally {
      dispatch(clearHistoryMsg());
      dispatch(clearCurrentMsg());
      dispatch(localLeaveRoom());
      dispatch(updateAIGCState({ isAIGCEnable: false }));
    }
  }
};
```

如 `RtcClient.leaveRoom()` 当前返回 `void`，允许 `await`；同时确保 engine 尚未创建时该方法安全返回，避免未进房直接退出抛错。日常离房按钮继续无参数调用同一函数，正常行为不变。

不要改变日常离房按钮的无 signal 调用。

同时删除 `RtcClient.joinRoom()` 中打印 ``token: ${this.basicInfo.token}`` 的完整 Token 日志；允许保留 RoomId/UserId 的非秘密调试信息。测试使用唯一假 Token 并 spy `console.log`，断言所有日志拼接后不包含该 Token。

- [ ] **Step 6: 实现 3 秒有界退出**

`MainPage` 通过 `Header` 的 children 插入 `AuthUserActions`。3 秒上限覆盖整个 `useLeave()`，而不只是 StopVoiceChat fetch：

```tsx
const handleLogout = async () => {
  const controller = new AbortController();
  let timeoutId: number | undefined;
  const cleanup = leaveRoom(controller.signal).catch(() => undefined);
  const timeout = new Promise<void>((resolve) => {
    timeoutId = window.setTimeout(() => {
      controller.abort();
      resolve();
    }, 3000);
  });
  try {
    await Promise.race([cleanup, timeout]);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    // 超时时 Abort 已终止带鉴权的 Stop fetch；未完成的仅是本地 SDK 清理。
    await logout();
  }
};
```

测试使用 Jest fake timers，让一个设备停止 Promise 永不 settle；推进 3000ms 后断言 `controller.signal.aborted === true` 且 logout 已调用。Abort 后不再主动发起新的 Stop 请求；浏览器中已取消的 fetch 或服务端已接收的 Stop 可以自行结束，剩余本地 SDK 清理不得阻塞注销。未加入房间时跳过 RTC 清理并直接 logout。

- [ ] **Step 7: 验证并提交**

```bash
npm test -- --watchAll=false src/App.test.tsx src/pages/AuthPage/index.test.tsx src/components/AuthUserActions/index.test.tsx
npm run build
```

Expected: PASS，原 MainPage 仍可构建。

```bash
git add src/App.tsx src/pages/AuthPage/index.tsx src/pages/AuthPage/index.module.less src/pages/AuthPage/index.test.tsx src/components/AuthUserActions/index.tsx src/components/AuthUserActions/index.module.less src/components/AuthUserActions/index.test.tsx src/pages/MainPage/index.tsx src/lib/useCommon.ts src/lib/RtcClient.ts src/App.test.tsx
git commit -m "feat: gate RTC page behind login"
```

---

### Task 9: 安全迁移本地 `.env` 并完成回归验证

**Files:**
- Modify locally, not tracked: `rag_llm_server/.env`
- Create: `rag_llm_server/README.md`
- Modify only if test failures require scoped fixes: files from Tasks 2–8

- [ ] **Step 1: 无回显检查本地语音 AppId 是否可合并**

运行只输出布尔结果的检查，不输出值：

```bash
cd rag_llm_server && uv run python - <<'PY'
from dotenv import dotenv_values
v = dotenv_values('.env')
print('speech_ids_equal=', bool(v.get('ASR_APP_ID')) and v.get('ASR_APP_ID') == v.get('TTS_APP_ID'))
PY
```

Expected: 只显示 `True` 或 `False`。

- [ ] **Step 2: 精简被忽略的真实 `.env`**

- 总是删除 `DEFAULT_ROOM_ID`、`DEFAULT_USER_ID`。
- 若 ASR/TTS 相等，保留该值为一个 `SPEECH_APP_ID`，删除两个旧项。
- 若不相等，保留两个旧项，不伪造公共 AppId。
- `KB_PROJECT_NAME=default` 可删除，使用代码默认值。
- `SERVER_URL` 若为 RTC 云端可访问的隧道/HTTPS 地址则保留；只有确认通过请求地址可公开回调时才能删除。
- 其余真实秘密原值保持不变，不在终端或 Git diff 中输出 `.env`。

- [ ] **Step 3: 写运行说明**

`rag_llm_server/README.md` 包含：

- 从 `.env.example` 配置的 9 项新部署必填变量。
- 旧 ASR/TTS 双变量兼容规则。
- `uv sync --dev`、`uv run python main.py`、前端 `npm start`。
- 注册后自动进入主页面；数据库位置和删除数据库会清空账号的说明。
- 同站 Cookie 部署要求、默认 localhost/RFC1918 CORS、生产 `CORS_ORIGINS` 和 HTTPS `SERVER_URL`。
- 不写入任何真实值。

- [ ] **Step 4: 运行完整后端测试**

```bash
cd rag_llm_server && uv run pytest -q
```

Expected: 全部 PASS，无密钥或 Token 出现在测试输出。

- [ ] **Step 5: 运行完整前端测试与构建**

```bash
npm test -- --watchAll=false
npm run build
```

Expected: 全部 PASS，生产构建成功。

- [ ] **Step 6: 运行静态与差异检查**

```bash
cd rag_llm_server && uv run python -m py_compile *.py services/*.py
cd .. && git diff --check
git status --short
git diff --name-only origin/main...HEAD
```

Expected:

- Python 编译和 `git diff --check` 通过。
- `.env`、`data/app.db`、密码、Token、真实 Key 不在 Git 文件列表中。
- 用户原有三处业务改动没有丢失；若已在功能提交中合并，diff 内容仍保留其 RAG/配置意图。

- [ ] **Step 7: 浏览器人工验收**

依次验证：

1. 未登录只显示登录/注册页，Network 中没有 `/getScenes`。
2. 注册新账号后直接进入原页面；刷新仍保持登录。
3. 加入房间、启动 VoiceChat、RAG 流式回答、字幕、打断、离房均保持正常。
4. 退出后回到登录页；再次访问 `/getScenes` 收到 `401`。
5. 两个浏览器/无痕窗口使用不同账号，返回不同 RoomId/TaskId/UserId。
6. 在实际生产同站 Origin 上验证 Cookie、CORS 和刷新恢复登录。

- [ ] **Step 8: 提交文档和必要的最终修正**

```bash
git add rag_llm_server/README.md
# 如有测试驱动的 scoped 修正，逐个列出文件，不使用 git add .
git commit -m "docs: document authenticated RTC server setup"
```

---

## 最终成功标准

- 新访问者可注册、登录、刷新恢复和退出；密码仅以 Argon2 哈希保存。
- 未登录不能调用 `/getScenes` 或 `/proxy`。
- `/proxy` 只允许 StartVoiceChat/StopVoiceChat，未知 Action 不签名、不访问上游。
- RTC Token 由现有官方格式代码动态签发，没有固定 Token。
- RoomId、UserId、TaskId 不在 `.env` 或代码中写死；同一 Session 全链路一致，不同登录 Session 隔离。
- Start/Stop、ASR、TTS、CustomLLM 回调、RAG 和流式回复原功能通过回归。
- 新部署仅需 9 项必填配置；旧 ASR/TTS 配置可兼容启动。
- `.env` 和 SQLite 数据库不进入 Git，日志不泄漏凭据。

# 普通注册登录与动态 RTC 会话设计

## 目标

在不改变现有 RTC、RAG、LLM、ASR、TTS 功能和 `/getScenes` 返回结构的前提下，增加面向所有访问者的普通用户名密码注册/登录，并在登录后为当前浏览器会话自动生成 RTC `RoomId`、`UserId`、`TaskId` 和 Token。同时精简 `rag_llm_server/.env`，删除房间和用户等运行期数据配置。

## 范围

本次包含：

- `rag_llm_server` 中的用户、登录会话、鉴权和 RTC 会话关联。
- 前端增加简单登录/注册页、登录状态检查、退出入口和携带 Cookie 的 API 请求。
- 保持现有主页面、RTC 操作、RAG 检索、流式 LLM 回调和调试接口的业务行为。

本次不包含：

- 管理员、角色、邀请码、邮箱或手机验证、验证码。
- 找回密码、修改密码、第三方登录、JWT/刷新令牌。
- 用户资料系统或复杂数据库迁移框架。

## 选定方案

使用 SQLite 持久化用户和服务端登录会话，浏览器通过 HttpOnly Session Cookie 鉴权。

选择该方案的原因：

- 不需要新增 JWT 签名密钥，符合减少配置项的目标。
- 服务端可以立即注销会话，浏览器无法通过 JavaScript 读取 Session Token。
- SQLite 无需独立数据库服务，适合当前单实例 Demo 的部署方式。
- RoomId、UserId 和 TaskId 可以直接绑定到登录会话，确保 `/getScenes`、`StartVoiceChat` 和 `StopVoiceChat` 使用同一组数据。

## 数据模型

SQLite 默认文件为 `rag_llm_server/data/app.db`，启动时自动建目录和表，不增加必填配置。

### users

| 字段 | 说明 |
| --- | --- |
| `id` | 自增整数主键 |
| `username` | 唯一用户名，保存规范化后的 ASCII 小写值 |
| `password_hash` | Argon2 密码哈希，不保存明文密码 |
| `created_at` | UTC 创建时间 |

用户名规则：去除首尾空格后转为 ASCII 小写，长度为 3–32，只允许英文字母、数字和下划线。登录、`/api/auth/me` 和页面展示均使用这个规范化名称。密码长度为 8–72，不额外设计复杂度规则。

### sessions

| 字段 | 说明 |
| --- | --- |
| `id` | Session Token 的 SHA-256 哈希，唯一主键 |
| `user_id` | 关联 `users.id` |
| `expires_at` | UTC 过期时间 |
| `created_at` | UTC 创建时间 |
| `rtc_room_id` | 当前会话的 RTC 房间号，可空 |
| `rtc_user_id` | 当前会话的 RTC 用户号，可空 |
| `rtc_task_id` | 当前会话的 VoiceChat 任务号，可空 |

浏览器 Cookie 保存高熵随机原始 Token，数据库只保存 Token 哈希。Session 默认有效期 7 天。每次成功登录或注册创建一个新 Session；不实现刷新令牌。过期会话在读取时删除，服务启动或创建新会话时顺便清理历史过期记录。

## 后端组件

### 配置

`config.py` 负责：

- 从 `rag_llm_server/.env` 显式加载配置，避免依赖启动目录。
- 区分必填、可选和默认配置。
- 启动时集中校验实际启用功能需要的配置，错误信息只包含变量名，不包含密钥内容。

### 数据库与认证服务

`database.py` 负责 SQLite 连接、建表和最小的数据访问操作。新增独立认证服务负责：

- 用户名规范化和校验。
- 使用 Argon2 生成、验证密码哈希。
- 注册、密码验证、创建/读取/删除 Session。
- 生成并保存当前 Session 对应的 RTC 标识。

不把认证、数据库 SQL 和 RTC Token 生成继续堆入 `main.py`。

### 登录接口

新增接口：

- `POST /api/auth/register`
  - JSON：`{"username": "...", "password": "...", "confirm_password": "..."}`。
  - 校验通过后创建用户，并直接建立登录 Session。
  - 成功返回 `201` 和 `{"user": {"id": 1, "username": "normalized_name"}}`，同时写入 Cookie。
  - 用户名重复返回 `409`；输入不合法返回 `422`。
- `POST /api/auth/login`
  - JSON：`{"username": "...", "password": "..."}`。
  - 用户不存在或密码错误统一返回 `401` 和相同错误文案。
  - 成功返回 `200` 和与注册接口相同的 `{"user": ...}` 结构，同时写入 Cookie。
- `GET /api/auth/me`
  - 成功返回 `200` 和 `{"user": {"id": ..., "username": "..."}}`。
  - 未登录或 Session 过期返回 `401`。
- `POST /api/auth/logout`
  - 删除服务端 Session 并清除 Cookie。
  - 即使 Cookie 已失效也返回 `204`，使前端可以稳定回到登录页。

所有可预期的认证错误统一返回 JSON `{"detail": "面向用户的错误信息"}`，前端只读取 `detail` 展示。Cookie 名为 `rtc_session`，属性为 `HttpOnly`、`SameSite=Lax`、`Path=/`，并设置与数据库 Session 一致的 7 天 `Max-Age` 和 `Expires`。当 `SERVER_URL` 以 `https://` 开头或请求 URL Scheme 为 HTTPS 时设置 `Secure`；反向代理部署必须正确传递并由 Uvicorn 信任 `X-Forwarded-Proto`，或者显式配置 HTTPS 的 `SERVER_URL`。本地 HTTP 开发不设置 `Secure`，以免浏览器拒绝 Cookie。

### 受保护接口

以下接口要求有效登录 Session：

- `/getScenes`
- `/proxy`

`/api/chat_callback` 是 RTC 云端回调，不能依赖浏览器 Cookie，保持原鉴权边界和响应协议。`/debug/chat`、`/debug/rag` 保留原业务响应和调试功能，但必须通过登录 Session 才能访问；开放注册后，这一收紧可避免匿名调用消耗 RAG/LLM 云资源或读取调试结果。

## RTC 会话生命周期

### 创建和读取场景

登录用户第一次调用 `/getScenes` 时，服务端在同一个 Session 中生成：

- `RoomId = room_<uuid>`
- `UserId = user_<users.id>`
- `TaskId = task_<uuid>`

UUID 使用不带连字符的十六进制形式，确保所有 ID 满足 RTC 字符约束。`UserId` 对同一注册用户保持稳定，RoomId 和 TaskId 随登录 Session 隔离。

首次创建采用数据库原子 get-or-create：开启 SQLite `BEGIN IMMEDIATE` 事务，在事务内重新读取 Session；仅当 RTC 字段仍为空时生成并写入，随后返回数据库最终保存的值。SQLite 连接设置 5 秒 busy timeout；超时后返回可重试的服务错误，不创建第二套 ID。这样同一 Session 并发首次调用 `/getScenes` 时，所有成功响应与后续 `/proxy` 都会使用同一组 ID。

随后使用现有 `services/token_build.py`，根据 `RTC_APP_ID`、`RTC_APP_KEY`、RoomId 和 UserId 实时签发 24 小时 RTC Token。Token 只返回给前端，不写入数据库。

同一个登录 Session 重复调用 `/getScenes` 时：

- 复用数据库中的 RoomId、UserId 和 TaskId。
- 重新签发 Token，使刷新页面不会因为旧 Token 过期而失败。

返回给前端的 `ResponseMetadata`、`Result.scenes`、`scene`、`rtc` 字段结构保持不变。

### 启动和停止 VoiceChat

`/proxy` 从全局配置读取 `RTC_APP_ID`，从登录 Session 读取 RoomId、UserId 和 TaskId；AppId 不写入 Session：

- `StartVoiceChat` 使用全局 `RTC_APP_ID` 以及当前 Session 的 RoomId、TaskId，并将 `AgentConfig.TargetUserId` 设置为当前 RTC UserId。
- `StopVoiceChat` 使用相同的全局 `RTC_APP_ID` 以及当前 Session 的 RoomId 和 TaskId。
- 若用户未先调用 `/getScenes`，`/proxy` 返回明确的 `409`，不隐式生成另一组标识。
- `/proxy` 仅允许 `StartVoiceChat` 和 `StopVoiceChat`；缺失或其他 Action 返回 `400`，且不会签名或访问上游。因为系统允许开放注册，普通登录用户不能获得使用服务端 AK/SK 对任意 RTC OpenAPI 请求签名的代理能力。

AI 智能体自身的 `AgentConfig.UserId = "AiAgent"` 保持不变；它不是登录用户 ID，也不迁入 `.env`。

正常退出顺序固定为：前端先调用现有离房/StopVoiceChat 流程，最多等待 3 秒；成功、失败或超时后都继续调用 `/api/auth/logout` 删除 Session，最后回到登录页。logout 请求不会与 StopVoiceChat 并发发出，避免 Stop 因 Session 提前删除而收到 `401`。异常关闭页面或 Stop 失败仍由现有 RTC 任务超时机制兜底，因此退出页面不会被 RTC OpenAPI 无限阻塞。

## 前端流程

### 应用入口

应用加载时先调用 `/api/auth/me`：

- 成功：渲染现有 `MainPage`，由现有流程调用 `/getScenes`。
- `401`：渲染登录/注册页，不挂载 `MainPage`，因此不会提前调用 `/getScenes`。
- 网络错误：显示可重试错误，不误判为用户名密码错误。

注册或登录成功后保存的只是 React 内存中的用户信息；身份凭证由 HttpOnly Cookie 管理，不写入 localStorage 或 sessionStorage。

### 登录/注册页

使用现有 React 和 Arco Design 组件实现单页表单：

- 登录模式：用户名、密码、登录按钮、切换到注册。
- 注册模式：用户名、密码、确认密码、注册按钮、切换到登录。
- 显示后端返回的校验或认证错误。
- 提交期间禁用按钮，避免重复请求。

不新增 UI 组件库，不改变现有主页面布局。Header 增加当前用户名和退出按钮；退出前调用现有离房逻辑，然后清理登录 Session 并回到登录页。

### API 请求

统一请求封装为同源或跨端口请求增加 `credentials: "include"`，覆盖认证接口、`/getScenes` 和 `/proxy`。收到 `401` 时由应用级认证状态返回登录页。

由于 Cookie 鉴权不能配合通配 CORS，后端使用明确规则：

- 默认精确允许 `http://localhost:3000` 和 `http://127.0.0.1:3000`。
- 使用正则额外允许前端开发端口 `3000` 上的 RFC1918 IPv4 地址：`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`，保持当前局域网调试能力；不匹配公网 IPv4、任意域名或任意端口。
- 可选 `CORS_ORIGINS` 中显式配置完整的生产前端 Origin（协议、主机和端口），多个值用逗号分隔；这些 Origin 必须与 API 属于浏览器定义的同一 Site。

`allow_credentials=True` 保持开启，不再使用 `allow_origins=["*"]`。本设计固定使用 `SameSite=Lax`，只支持同站同源或同站跨 Origin 部署；不承诺前端与 API 位于不同 Site 时仍能发送登录 Cookie。生产环境推荐通过同一站点的反向代理暴露前端和 `/api`。若未来确需跨站部署，应作为独立需求评估 `SameSite=None; Secure` 和 CSRF 防护，不在本次范围内。

## 配置精简

新部署的目标必填配置：

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
```

默认或可选配置：

```dotenv
# 默认 default
KB_PROJECT_NAME=default

# 默认继承 SPEECH_APP_ID，仅在两个服务账号不同时覆盖
ASR_APP_ID=
TTS_APP_ID=

# 默认根据进入 /proxy 请求的公开地址生成；反向代理或隧道场景可覆盖
SERVER_URL=

# 生产环境前后端跨域时配置，逗号分隔；本地开发无需配置
CORS_ORIGINS=
```

删除：

- `DEFAULT_ROOM_ID`
- `DEFAULT_USER_ID`

语音配置校验规则只有两种有效情况：提供 `SPEECH_APP_ID`，或在兼容模式下同时提供旧的 `ASR_APP_ID` 和 `TTS_APP_ID`。有效 ASR AppId 为 `ASR_APP_ID` 覆盖值，否则继承 `SPEECH_APP_ID`；有效 TTS AppId 为 `TTS_APP_ID` 覆盖值，否则继承 `SPEECH_APP_ID`。若 `SPEECH_APP_ID` 缺失且旧变量只存在一个，启动校验失败并明确列出缺失项。这样现有 `.env` 可以分阶段迁移，不因一次变量改名中断运行。

非敏感、与当前场景绑定的默认项继续放在代码中，例如 API 域名、Region、ASR Cluster、TTS Cluster、音色、欢迎语和 AI 用户名。这些不是密钥，不需要让使用者重复配置。

## 错误处理

- 服务缺少必填云端配置：启动失败并列出缺失变量名。
- 注册用户名重复：`409`。
- 注册字段不合法：`422`。
- 登录失败：统一 `401`，不暴露用户名是否存在。
- Session 缺失或过期：`401` 并清 Cookie。
- 已登录但没有 RTC 会话就调用 `/proxy`：`409`。
- RTC Token 生成或 OpenAPI 请求失败：保持现有响应结构，补充稳定的 HTTP/业务错误处理，不输出密钥或完整 Cookie。
- 日志不打印密码、Session Token、RTC Token、AK/SK、AppKey、Ark API Key；现有打印请求体的调试日志需要过滤认证路径和敏感字段。

## 测试与验收

### 后端

- 首次启动自动创建 SQLite 表。
- 注册成功、用户名重复、非法用户名、密码不匹配、密码长度错误。
- 登录成功、错误用户名/密码使用统一响应。
- `/api/auth/me` 和 logout 的成功、过期、无 Cookie 场景。
- 未登录访问 `/getScenes`、`/proxy` 返回 `401`。
- 同一 Session 多次 `/getScenes` 复用三个 RTC ID，但 Token 可重新签发。
- 并发首次请求 `/getScenes` 时，成功响应使用同一组 RTC ID，锁等待不会产生第二套 ID。
- 不同登录 Session 的 RoomId、TaskId 不同，同一用户的 RTC UserId 相同。
- Start/Stop 构造体使用 Session 中完全一致的 RoomId 和 TaskId。
- Token 解包后包含期望的 AppId、RoomId、UserId、有效期和发布/订阅权限。
- `.env` 旧 ASR/TTS 变量兼容，新 `SPEECH_APP_ID` 默认继承正确。

### 前端

- 未登录只显示登录页且不调用 `/getScenes`。
- 注册成功和登录成功后进入原主页面。
- 刷新页面通过 `/api/auth/me` 恢复登录状态。
- 所有后端请求携带 Cookie。
- 在实际采用的生产同站部署地址上验证 Cookie、CORS 与刷新恢复登录。
- Session 过期后返回登录页。
- 退出时执行离房/停止流程并回到登录页。

### 回归验收

- 登录后现有场景仍能进入 RTC 房间。
- StartVoiceChat、打断、StopVoiceChat、字幕、RAG 检索和流式回复行为不变。
- 两个不同账号同时使用时不会共用 RoomId、UserId 或 TaskId。
- `.env` 不再包含固定 RoomId、UserId 或 RTC Token。

## 实施边界

- 保留用户已有的 `rag_llm_server/config.py`、`main.py`、`services/rag_service.py` 未提交改动，并在其基础上做最小增量修改。
- 不更换现有 RTC Token 算法，只补充可测试性和调用边界。
- 不引入 ORM；SQLite 访问保持小而明确。
- 不顺带重构与认证、会话或配置精简无关的 RTC/RAG 代码。

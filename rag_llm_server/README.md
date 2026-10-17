# RAG LLM Server

该服务为实时对话页面提供开放注册/登录、RTC 会话配置、VoiceChat 代理、ASR/TTS/LLM 回调和 RAG 能力。用户登录后，服务端会按登录 Session 自动生成 RoomId、UserId、TaskId，并动态签发 RTC Token；这些值不需要写入环境变量。

## 配置

复制示例文件并填写配置：

```bash
cp .env.example .env
```

新部署需要以下 9 项配置：

1. `VOLC_ACCESS_KEY`
2. `VOLC_SECRET_KEY`
3. `ARK_API_KEY`
4. `ARK_ENDPOINT_ID`
5. `RTC_APP_ID`
6. `RTC_APP_KEY`
7. `VOLC_ACCOUNT_ID`
8. `KB_COLLECTION_NAME`
9. `SPEECH_APP_ID`

`SPEECH_APP_ID` 同时用于 ASR 和 TTS。旧部署仍可不设置它，改为同时提供 `ASR_APP_ID` 和 `TTS_APP_ID`；若设置了对应的旧变量，它会覆盖公共语音 AppId。不能只配置其中一个旧变量，ASR 和 TTS 都必须能获得 AppId。

可选配置：

- `KB_PROJECT_NAME`：知识库项目名，默认 `default`。
- `SERVER_URL`：RTC 云服务可访问的后端公开地址。公网部署必须配置有效的 HTTPS Origin，且不要包含路径。仅 localhost、loopback 或 RFC1918 私网开发地址可在未配置时安全回退到请求 Origin。
- `CORS_ORIGINS`：额外允许的前端 Origin，多个值使用逗号分隔。

不要提交 `.env`，也不要把 Access Key、App Key、API Key、密码或 RTC Token 写入源码和日志。

## RTC AppKey 与动态 Token

`RTC_APP_KEY` 不是 RTC Token。它是 RTC 应用的服务端签名密钥，必须与 `RTC_APP_ID` 属于火山引擎 RTC 控制台中的同一个应用，并且只能保存在后端 `.env` 中。

用户登录后，服务端会自动完成以下流程：

1. 为登录 Session 分配并复用动态 `RoomId`、`UserId` 和 `TaskId`。
2. 使用 `RTC_APP_ID`、`RTC_APP_KEY`、`RoomId`、`UserId` 和有效期动态签发正式 Token。
3. 通过 `/getScenes` 将当前会话需要的 `AppId`、`RoomId`、`UserId` 和 Token 返回给前端。

因此 `.env` 中不需要也不应配置固定 Token、固定房间号或固定用户号。Token 按火山引擎官方 Python AccessToken 格式生成，权限 Map 会按权限编号排序后参与 HMAC-SHA256 签名；默认有效期为 24 小时。

官方说明与校验流程参见[火山引擎 RTC：使用 Token 鉴权](https://www.volcengine.com/docs/6348/70121?lang=zh)。

修改 `RTC_APP_ID` 或 `RTC_APP_KEY` 后必须重启后端，并刷新整个前端页面，让 `/getScenes` 获取新 Token。不要继续使用页面内存中的旧 Token。

## 本地启动

后端使用 Python 3.13+ 和 `uv`：

```bash
cd rag_llm_server
uv sync --dev
uv run python main.py
```

服务默认监听 `0.0.0.0:3001`。另开终端启动前端：

```bash
cd ..
npm install
npm start
```

开发环境前端默认访问当前主机的 3001 端口。访问页面后可直接注册；注册成功会建立登录 Session 并进入原 RTC 页面，随后页面才请求 `/getScenes`。

如果启动时报 `Address already in use`，说明 3001 端口已有后端进程，不要重复启动。先检查占用：

```bash
lsof -nP -iTCP:3001 -sTCP:LISTEN
```

优先回到原终端停止旧服务，再重新运行 `uv run python main.py`。

## 数据库与账号

账号、Argon2 密码哈希、登录 Session 和对应的 RTC 会话标识保存在：

```text
rag_llm_server/data/app.db
```

目录和数据库会在服务启动时自动创建。删除 `data/app.db` 会永久清空本地账号、登录 Session 和 RTC 会话映射；生产环境操作前应先备份。数据库文件和 `.env` 均不应提交到 Git。

## Cookie、反向代理与 CORS

生产环境建议让前端与后端通过同一站点提供服务，例如由 HTTPS 反向代理提供静态前端，并将 `/api/auth`、`/getScenes`、`/proxy` 和回调路径转发到本服务。前端请求统一携带 Cookie；登录 Cookie 为 `HttpOnly`、`SameSite=Lax`，在 HTTPS 请求或 HTTPS `SERVER_URL` 下会设置 `Secure`。

如果配置了 HTTPS `SERVER_URL`，即使本地请求本身是 HTTP，Cookie 也会带 `Secure`。本地浏览器应通过同一个 HTTPS 隧道访问，或者开发时暂不设置 `SERVER_URL`，使用受限的 localhost、loopback 或 RFC1918 fallback；不要放宽 Cookie 的 Secure 策略。

默认 CORS 允许：

- `http://localhost:3000`
- `http://127.0.0.1:3000`
- RFC1918 私网开发地址

生产域名应通过 `CORS_ORIGINS` 明确加入完整 Origin，并保持凭据请求启用。不要使用通配 Origin 搭配 Cookie。跨站部署还会受到浏览器 SameSite Cookie 策略限制，因此优先采用同站部署。

携带登录 Cookie 的 logout 和 RTC 代理写请求会校验 `Origin` 与 Fetch Metadata；显式跨站请求返回 `403`。浏览器前端 Origin 必须来自 `SERVER_URL`、`CORS_ORIGINS` 或受限的本机/私网开发 Origin。没有 `Origin` 的服务端和自动化客户端请求保持兼容。

`SERVER_URL` 应与 RTC 回调实际可达地址一致。公网生产环境必须使用有效 HTTPS 域名，并确保 VoiceChat 服务能够访问该地址上的 ASR、TTS、Custom LLM 和对话状态回调路由。未配置时的自动回退只接受 localhost、loopback 和 RFC1918 私网地址，不接受公网 Host。

## 验证

```bash
cd rag_llm_server
uv run pytest -q
uv run python -m py_compile *.py services/*.py
```

前端验证：

```bash
cd ..
npm test -- --watchAll=false
npm run build
```

## 常见问题排查

### 点击通话提示 `INVALID_TOKEN` / `token_error`

该错误表示 RTC 服务端拒绝了 Token，与浏览器翻译插件报错无关。依次检查：

1. 确认浏览器中 `/getScenes` 返回的 `AppId`、`RoomId`、`UserId` 与实际调用 `joinRoom` 时完全一致，包括大小写。
2. 确认 `.env` 中的 `RTC_APP_ID` 长度为 24，并且 `RTC_APP_KEY` 是该应用当前有效的主 AppKey 或已启用的副 AppKey。
3. 修改 `.env` 后重启后端并完整刷新页面，重新获取 Token。
4. 在火山引擎 RTC 控制台进入对应应用，使用“Token 校验”，填写 `/getScenes` 返回的 Token、RoomId 和 UserId。

不要将 AppKey 或完整 Token 粘贴到日志、Issue 或聊天中。项目生成的 Token 也可以使用火山引擎官方 `AccessToken.py` 的 `parse()` 和 `verify()` 在本地交叉校验。

### 点击关闭出现 `Failed to convert value to 'AbortSignal'`

该问题来自关闭按钮将点击事件误作为 `fetch` 的 `signal` 参数。当前版本已经限制关闭流程只接受原生 `AbortSignal`，并让普通关闭按钮以无参数方式调用。更新代码后重新启动前端即可。

### 点击通话失败但没有明确提示

当前前端会显示失败阶段和错误码，并在控制台输出脱敏后的结构化信息：

```text
[RTC 通话失败] { stage, code, message }
```

常见阶段包括 `createEngine`、`addEventListeners`、`joinRoom`、`getDevices` 和 `StartVoiceChat`。`joinRoom` 超过 15 秒没有结果时会显示 `JOIN_TIMEOUT`。排查时提供阶段和错误码即可，不要提供完整 Token。

浏览器控制台中的 `Immersive Translate ERROR` 来自沉浸式翻译扩展，不属于本项目错误；必要时可临时禁用扩展以减少日志干扰。

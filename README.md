# 实时语音 RAG 助手

基于火山引擎实时对话式 AI Demo 二次开发的语音助手。用户登录后可以直接和 AI 语音对话；后端按会话签发 RTC Token，并把语音识别结果交给知识库检索和方舟大模型，再通过语音合成返回。

前端界面沿用火山引擎 RTC AIGC Demo，并增加了注册登录。后端已替换为 `rag_llm_server`。

## 功能

- 开放注册和登录，密码使用 Argon2 哈希，会话使用 HttpOnly Cookie
- 每个登录会话独立生成房间、用户和任务标识，并动态签发 RTC Token
- 语音通话：实时音视频、语音识别、语音合成
- 回答前检索火山引擎知识库，再调用方舟模型流式生成

## 目录

```text
src/              React 前端
public/           静态资源
rag_llm_server/   FastAPI 后端、鉴权、RTC 代理、RAG
```

## 环境

- Node.js 16+
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

需要自行开通火山引擎 RTC、语音识别、语音合成、方舟模型和知识库。密钥只放在 `rag_llm_server/.env`，不要写入源码。

## 启动

后端：

```bash
cd rag_llm_server
cp .env.example .env
uv sync --dev
uv run python main.py
```

服务监听 `0.0.0.0:3001`。

前端另开一个终端，在项目根目录执行：

```bash
npm install
npm start
```

开发环境前端默认请求当前主机的 3001 端口。打开页面后先注册，注册成功会进入通话页。

更完整的配置、Cookie、反向代理和 RTC Token 排查说明见 [rag_llm_server/README.md](rag_llm_server/README.md)。

## 验证

```bash
cd rag_llm_server
uv run pytest -q
```

```bash
npm test -- --watchAll=false
npm run build
```

## 不要提交的内容

- `rag_llm_server/.env`
- `rag_llm_server/data/app.db`（本地账号和会话）
- `node_modules/`、`.venv/`、`build/`


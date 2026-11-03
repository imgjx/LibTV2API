# Liblib2API

> 把 **liblib.tv（LibTV）** 的「手机号验证码 / 微信扫码」登录模块抓取并实现为可复用代码，
> 再以 **MCP / OpenAPI 客户端 + FastAPI 服务** 的形式，供你的自动化工作流稳定接入。

LibTV 自带的自动化（画布节点、剧本等）约束较多、不好用。本项目不依赖它的内置自动化，
而是**先把登录打通**，拿到你本人账户的令牌，再通过标准 MCP 协议直接调用它暴露的 86 个
创作工具（画布、图片/视频/音频生成、剧本、剪辑、导出等）——任何能打 HTTP 的调度系统
（n8n、自研编排、定时脚本）都能接进来。

---

## 1. 它解决什么问题

| 痛点 | 本项目的做法 |
|---|---|
| LibTV 内置自动化不好用、难编排 | 登录后直接调 MCP 工具，状态/进度自己掌控 |
| 每次要手动在网页操作 | 一次登录，令牌落地本机，脚本自动续期 |
| 多账号 / 多工作流难复用 | 统一 Python SDK + HTTP API，任意语言可调用 |

---

## 2. 鉴权体系（已逆向 + 官方规范核实）

| 登录方式 | 协议 / 端点 | 本项目实现 |
|---|---|---|
| **微信扫码** | OAuth 2.1 + PKCE，`mcp.liblib.tv` 标准发现端点 | ✅ 忠实实现，自动发现端点 |
| **手机号验证码** | `api.liblib.tv` passport 类端点（逆向基址） | ✅ 实现，端点可配置 + 浏览器核验 |
| **OpenAPI（Access Key）** | `im.liblib.tv/openapi`，Bearer 鉴权 | ✅ 可选，REST 透传 |
| **MCP（86 个工具）** | `mcp.liblib.tv/mcp`，JSON-RPC，Bearer 鉴权 | ✅ 接入层（自动化核心入口） |

> 登录拿到的 token 真正能驱动的是 **MCP 端点**（全部创作能力）。微信扫码走标准
> OAuth 2.1 + PKCE，令牌约 1 小时过期，由 refresh token 自动续期，凭据存
> `~/.libtv/credentials.json`（权限 `0600`，仅本人可读写，令牌不出本机）。

---

## 3. 安装

```bash
cd Liblib2API
pip install -r requirements.txt
# 或作为包安装（提供 liblib2api 命令）
pip install -e .
```

依赖：`httpx`、`fastapi`、`uvicorn`、`pydantic`（Python ≥ 3.8）。

---

## 4. 登录

### 4.1 微信扫码（推荐，最稳）

```bash
python -m liblib2api.cli login wechat
```

脚本会打印授权链接并自动打开浏览器；用**微信扫码**确认后，令牌自动落地。无图形界面
时加 `--no-browser`，手动复制链接到能联网的浏览器完成扫码。

### 4.2 手机号验证码

```bash
# 第一步：下发验证码
python -m liblib2api.cli login phone --phone 13800138000
# 第二步：带验证码完成登录
python -m liblib2api.cli login phone --phone 13800138000 --code 123456
```

#### 手机号登录端点（已实测）

liblib.tv 的手机号登录端点未在公开文档给出。本项目已实测确认以下端点可用
（默认已写入 `config.py`，无需手动设置）：

```text
发验证码  POST https://passport.liblib.art/api/www/login/sendLoginPhoneCode
登  录    POST https://passport.liblib.art/api/www/login/loginByPhoneCode
用户信息  POST https://passport.liblib.art/api/www/user/getUserInfo
```

Web API（会员/积分/模型）基址为 `https://api2.liblib.art`，调用需带请求头
`Token: <access_token>` 与 `Webid: <webid>`。若未来端点变动，用环境变量
`LIBLIB_PHONE_SMS_SEND_URL` / `LIBLIB_PHONE_LOGIN_URL` / `LIBLIB_WEB_API_BASE` 覆盖即可。

---

## 5. 自动化接入

### 方式 A：Python SDK（脚本/编排内直接调用）

```python
from liblib2api import LiblibClient

client = LiblibClient()          # 自动读取 ~/.libtv/credentials.json
tools = client.list_tools()      # 列出全部能力
res = client.call_tool("generate_video", {...})   # 调用任意工具
```

先 `print([t["name"] for t in tools])` 看清楚你账号实际可用的工具名与参数，再写调用逻辑。
视频/图片生成为长任务，结合 `list_tools` 返回的查询/状态工具做轮询。

### 方式 B：HTTP 服务（任意语言/系统可调用）

```bash
# 多账号团队面板（账号池 + 监控 + 模型可用性 + 图片/视频生成 API），默认入口
python -m liblib2api.cli serve --port 8000
# 浏览器打开 http://127.0.0.1:8000/panel 即可管理
```

> `serve` 默认启动 `liblib2api.panel_server:app`（多账号版）。若只需单账号 MCP 透传，
> 可改用 `uvicorn liblib2api.server:app --port 8000`。

### 一键启动脚本

项目根目录提供跨平台一键启动脚本，会自动建虚拟环境、安装依赖并拉起面板：

```bash
# Linux / macOS
./start.sh
# Windows（双击 start.bat，或以管理员 PowerShell 运行 start.ps1）
start.bat
```

启动后浏览器自动打开 `http://127.0.0.1:8000/panel`。可用环境变量 `LIBLIB_PORT` / `LIBLIB_HOST` 覆盖端口与监听地址。

接口一览（多账号面板 `panel_server`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/panel` | 团队账号池管理面板（单页应用） |
| GET | `/health` | 健康检查 + 账号数 + 监控状态 |
| GET | `/api/v1/accounts` | 账号池列表（含类型/积分/活性/可用模型数） |
| POST | `/api/v1/accounts/import` | 导入账号 JSON，**自动识别类型 + 模型可用性** |
| GET | `/api/v1/accounts/export` | 导出账号池 JSON |
| POST | `/api/v1/accounts/register-current` | 把本机凭据注册进账号池 |
| GET | `/api/v1/accounts/{account}/type` | 账号类型识别详情 |
| GET | `/api/v1/accounts/{account}/models` | 该账号可用模型（标注每个是否可用） |
| POST | `/api/v1/accounts/{account}/sync` | 同步积分/类型/模型可用性 |
| POST | `/api/v1/accounts/{account}/checkin` | 手动签到（领免费算力） |
| POST | `/api/v1/accounts/{account}/proxy` | 绑定独立代理 IP |
| GET | `/api/v1/monitor/status` | 监控状态（最近一次巡检结果） |
| POST | `/api/v1/monitor/check` | 立即巡检一次（活性 + 自动签到） |
| POST | `/api/v1/generate/video` | 视频生成（**支持 mp4/webm/mov/gif、多种分辨率/时长/帧率**） |
| POST | `/api/v1/generate/image` | 图片生成（交叉选号，支持 png/jpg/webp） |
| POST | `/api/v1/generate/audio` | 音频生成（交叉选号，支持 mp4/wav/mp3） |
| GET | `/api/v1/tools?kind=` | 按类型（video/image/audio）列出 MCP 工具并推荐默认工具 |
| POST | `/api/v1/generate/video/split` | 视频拆分生成（多账号接力，单账号积分不够时拆条，支持 OpenAI 兼容 API 创意拆条） |
| GET/POST | `/api/v1/settings` | 设置：OpenAI 兼容 API（拆条用）/ 每积分消耗 / 监控间隔 |

`generate/video` 请求示例：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/generate/video" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"一只猫在星空下奔跑","model":"star-video2.5",
       "duration":10,"resolution":"1080p","format":"mp4","fps":30,
       "aspect_ratio":"16:9","account":null,"strategy":"balanced",
       "dry_run":true}'
```

设 `dry_run:true` 只做选号 + 参数校验，不真正消耗额度，便于先确认将发送什么。

---

### 5.1 多账号团队面板（账号池核心能力）

面向团队：每位成员把各自的 liblib 会员/额度包账号加入账号池，自动化工作流无需关心
具体用哪个号，由系统**交叉自动选号**。

| 能力 | 说明 |
|---|---|
| **账号类型自动识别** | 导入/登录/同步时调 `member/account`：识别 `VIP / 免费`（`is_sub` 副卡作为独立标签）、`member_until` 到期时间；面板统一显示为「VIP / 免费」 |
| **模型可用性识别** | 对每个账号：会员专属模型（名称/标签含 VIP/会员专属 等）+ 当日免费权益豁免 → 标出「免费版用不了」的模型（如 Seedance 2.0 VIP） |
| **综合自动交叉选号** | 生成时按「模型可用 + 积分足够 + 均衡/最少使用/积分最多/会员优先」策略从账号池挑号，均摊团队额度 |
| **图片 / 视频 / 音频统一生成** | 三类媒体均走 MCP 工具 + 交叉选号；视频支持 mp4/webm/mov/gif 多格式与多分辨率；图片 png/jpg/webp；音频 mp4/wav/mp3 |
| **视频拆分生成（多账号接力）** | 长视频单账号积分不够时，拆成多段（如 5+5+5 / 9+4+1+1 秒），每段交给积分够的账号接力生成，本地 ffmpeg 拼接。可配置 **OpenAI 兼容 API** 做创意拆条 |
| **在线 Playground** | 面板内置统一试用台：图片/视频/音频一键切换、参数化、结果直接预览（图/视频/音频播放器） |
| **每 10 分钟活性检查** | 后台线程每 600s 巡检：验证 token 活性、刷新类型/积分、自动签到领免费算力 |
| **独立代理 IP** | 每个账号可绑定独立代理 |
| **导入/导出** | 账号池 JSON 导入导出（权限 0600） |

> 关键词识别覆盖绝大多数会员专属模型；若某模型实际被拒，会记入该账号的
> `model_usable` 缓存（运行时学习），越用越准。

旧版单账号接口（无账号池）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 + 登录态 |
| POST | `/auth/phone/send-code` | 下发验证码 `{phone}` |
| POST | `/auth/phone/login` | 登录 `{phone, code}` |
| GET | `/auth/wechat/login` | 返回 `{state, auth_url}`，扫码用 |
| GET | `/auth/wechat/callback` | OAuth 回调（微信扫码后浏览器跳转至此） |
| GET | `/auth/wechat/status?state=` | 轮询登录状态 |
| GET | `/me` | 当前登录信息 |
| GET | `/mcp/tools` | 列出 MCP 工具 |
| POST | `/mcp/tools/call` | 调用工具 `{name, arguments}` |
| POST | `/mcp` | 透传任意 MCP JSON-RPC `{method, params}` |
| POST | `/openapi` | 透传 OpenAPI REST（需 `LIBTV_ACCESS_KEY`） |
| POST | `/auth/logout` | 注销 |

典型自动化调用链：

```bash
# 1) 启动后先登录（微信）：拿到 auth_url，扫码，轮询状态
curl "http://127.0.0.1:8000/auth/wechat/login"
# 浏览器打开返回的 auth_url 用微信扫码 → 自动跳回 /auth/wechat/callback
curl "http://127.0.0.1:8000/auth/wechat/status?state=<state>"

# 2) 之后任意创作能力
curl -X POST "http://127.0.0.1:8000/mcp/tools"
curl -X POST "http://127.0.0.1:8000/mcp/tools/call" \
  -H 'Content-Type: application/json' \
  -d '{"name":"generate_video","arguments":{...}}'
```

> 服务本身**无独立账号体系**，依赖本机凭据文件。请仅在可信网络 / 本机暴露，
> 切勿把 `/auth/wechat/callback` 等接口公开到公网。

---

## 6. 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LIBTV_HOME` | `~/.libtv` | 凭据目录 |
| `LIBTV_ISSUER` | `https://mcp.liblib.tv` | OAuth issuer（用于发现端点） |
| `LIBTV_MCP_URL` | `https://mcp.liblib.tv/mcp` | MCP 网关 |
| `LIBTV_OAUTH_PORT` | `8765` | CLI 阻塞模式本地回调端口 |
| `LIBTV_OAUTH_CLIENT_ID` | 空（尝试动态注册） | OAuth client_id |
| `LIBLIB_PHONE_API_BASE` | `https://passport.liblib.art` | 手机号登录基址（已实测可用） |
| `LIBLIB_PHONE_SMS_SEND_URL` / `LIBLIB_PHONE_LOGIN_URL` | `passport.liblib.art/api/www/login/...` | 手机号端点（已实测） |
| `LIBLIB_WEB_API_BASE` | `https://api2.liblib.art` | 会员/积分/模型列表接口基址 |
| `LIBLIB_MONITOR_INTERVAL` | `600` | 账号活性巡检间隔（秒，默认 10 分钟） |
| `LIBTV_ACCESS_KEY` | 空 | OpenAPI Access Key（可选） |
| `LIBLIB_PROXY` | 空 | HTTP 代理 |
| `LIBLIB_SERVER_PORT` / `LIBLIB_SERVER_PUBLIC_URL` | `8000` / `http://127.0.0.1:8000` | 服务端口与 OAuth 回调对外地址 |
| `LIBLIB_OPENAI_BASE_URL` | `https://api.openai.com/v1` | 视频拆分「创意拆条」用的 OpenAI 兼容 API 地址（任意兼容 /v1/chat/completions 的服务） |
| `LIBLIB_OPENAI_API_KEY` | 空 | 上述 API Key（也可在面板「设置」页填写，持久化到 `settings.json`） |
| `LIBLIB_OPENAI_MODEL` | `gpt-4o-mini` | 拆条所用模型名 |
| `LIBLIB_POINTS_PER_SECOND` | `10` | 拆分预算估算：每生成 1 秒视频约消耗算力点（可在面板「设置」调整） |
| `LIBLIB_SETTINGS_FILE` | `~/.libtv/settings.json` | 运行设置持久化文件（权限 0600） |

---

## 7. 项目结构

```
Liblib2API/
├── liblib2api/
│   ├── config.py          # 全局配置与常量（端点、环境变量）
│   ├── exceptions.py      # 统一异常
│   ├── credentials.py     # 凭据加载/持久化/刷新（0600）
│   ├── auth/
│   │   ├── phone.py       # 手机号验证码登录（端点可配置）
│   │   └── wechat.py      # 微信扫码 OAuth 2.1 + PKCE
│   ├── mcp.py             # MCP JSON-RPC 客户端（SSE 兼容 + 自动续期，支持直接传凭据）
│   ├── openapi.py         # OpenAPI REST 客户端（Access Key）
│   ├── client.py          # 统一门面 LiblibClient
│   ├── accounts.py        # 多账号仓库（账号池 / 独立代理 / 导入导出 / 类型识别）
│   ├── webapi.py          # Web API 客户端（会员/积分/模型可用性/类型识别）
│   ├── models.py          # 模型注册表 + 会员专属识别 + 可用性标注
│   ├── selector.py        # 综合自动交叉账号选择引擎
│   ├── monitor.py         # 账号活性监控（10 分钟巡检 + 自动签到）
│   ├── video_output.py    # 多格式视频生成规范与结果归一化
│   ├── media.py           # 图片/音频生成规范与参数构建
│   ├── split_gen.py       # 视频拆分生成（OpenAI 兼容创意拆条 + 按积分贪心分配多账号）
│   ├── panel_server.py    # 多账号面板 + 对外开放 API（默认 serve 入口）
│   ├── panel.html         # 面板前端单页应用（账号池/模型/Playground/拆分/监控/设置）
│   ├── server.py          # 单账号 FastAPI 服务（MCP 透传）
│   └── cli.py             # 命令行入口
├── start.sh               # Linux/macOS 一键启动（建 venv + 装依赖 + 起面板）
├── start.ps1 / start.bat  # Windows 一键启动
├── examples/automation_example.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 8. 安全与合规

- 凭据文件权限为 `0600`，令牌仅存本机，不外传、不写日志。
- 微信扫码是 OAuth 标准流程，令牌只能由你本人账户签发，本项目不代你登录、不收集密码。
- 请仅用于**本人账户**的合法自动化；遵守 liblib.tv 服务条款与频控，勿用于商用滥用或绕过限制。
- 本仓库仅作学习/研究用途的接口封装示例。

---

## 9. 路线图

- [ ] 补充各 MCP 工具的高层封装（generate_video / export 等）与轮询助手
- [ ] 多账号凭据管理
- [ ] 抓包脚本 `liblib2api sniff` 一键提取真实手机号登录端点
- [ ] 适配 LiblibAI 生图 Web API（`bridge.liblib.art`，参考 liblib-web）

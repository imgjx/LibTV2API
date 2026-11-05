# LibTV-Team

> **面向团队的 liblib 账号统一管理工具**：把团队成员各自的 liblib 会员 / 额度包账号
> 统一纳入账号池，集中查看积分、会员到期与模型可用性，由系统**交叉自动选号**、
> 统一分配额度，再以 **MCP / OpenAPI 客户端 + FastAPI 服务**的形式供自动化工作流调用。

> liblib 平台原生**没有团队 / 组织功能**：每个账号彼此独立、额度互不相通、到期时间各自为政。
> 本项目在其官方账号体系之上补齐这一层——把分散在成员手上的账号**统一管理**起来，
> 让团队额度与会员资产在一个面板里可观测、可调度、可提醒。

---

## 合规声明与使用条例

> **首次使用需阅读并同意本条例**：面板首次打开会强制展示本条例，
> 需阅读至底部并勾选同意后方可进入（同意状态记录在本机 `settings.json`）。

1. **仅限本人与本团队合法使用**：本工具用于管理你本人或本团队成员**已合法拥有**的 liblib 账号。
2. **遵守平台服务条款**：遵守 liblib.tv 及相关平台的服务条款、计费与频控规则，不得滥用。
3. **不做逆向、破解与账号交易**：不用于绕过平台限制、破解付费能力、批量注册或买卖账号；
   凭据仅用于本团队自有账号的正常调用。
4. **凭据安全**：令牌仅存本机（权限 `0600`），不外传、不写日志、不上传第三方；
   面板默认开启鉴权，请勿在未加固的情况下直接暴露到公网。
5. **不代你登录**：微信扫码走 OAuth 标准流程，手机号验证码由本人接收，均不收集密码。
6. **风险自担**：所用接口随官方调整可能变动，作者与维护者对不当使用或账号受限造成的后果不承担责任。
7. **无隶属关系**：本项目与 liblib 官方无隶属关系。

**关于"团队"能力**：liblib 平台原生不提供团队 / 组织功能，成员账号彼此独立、额度互不相通。
本项目不修改平台任何机制，只在官方账号体系之上提供一层**统一管理**
（集中纳管账号、交叉选号、统一分配额度、会员到期提醒），
所有能力仍受平台规则与账号自身权限约束。

---

## 1. 它解决什么问题

> 前提：liblib 平台原生没有团队功能，成员账号各管各的。下面这些都是**团队实际会遇到的**问题。

| 痛点 | 本项目的做法 |
|---|---|
| 团队账号分散在成员手上，无人统筹 | 账号池统一纳管：一个面板看清全部账号的类型、积分、会员到期与模型可用性 |
| 有人会员快到期却没人知道 | **会员到期提醒**：临近到期 / 已到期自动标红提醒，避免额度突然断档 |
| 额度用不完、分布也不均 | 综合自动交叉选号（均衡 / 最少使用 / 积分最多 / 会员优先），均摊团队额度 |
| 团队资产到底还剩多少、谁用超了 | **团队统计**：总览 / 成员维度 / 账号维度，算力点、额度使用率、可用模型覆盖率一屏可见 |
| 出了问题没人知道，只能天天刷面板 | **告警通知**：会员到期、账号失效、额度超限、领取结果，邮件 / 企业微信机器人主动推送到人 |
| 长视频单账号算力点不够 | 算力均摊：多账号分段接力生成后本地拼接，产出不断档 |
| LibTV 内置自动化不好用、难编排 | 登录后直接调 MCP 工具，状态 / 进度自己掌控 |
| 每次要手动在网页操作 | 一次登录，令牌落地本机，脚本自动续期 |

---

## 2. 鉴权体系

| 登录方式 | 协议 / 端点 | 本项目实现 |
|---|---|---|
| **微信扫码** | OAuth 2.1 + PKCE，标准发现端点（自动发现） | ✅ 忠实实现 |
| **手机号验证码** | 官方 passport 登录流程（端点已内置，可配置） | ✅ 实现，端点可经环境变量覆盖 |
| **OpenAPI（Access Key）** | Access Key 鉴权，REST 透传 | ✅ 可选 |
| **MCP（86 个工具）** | JSON-RPC + Bearer 鉴权（创作能力入口） | ✅ 接入层（自动化核心入口） |

> 登录拿到的 token 真正能驱动的是 **MCP 端点**（全部创作能力）。微信扫码走标准
> OAuth 2.1 + PKCE，令牌约 1 小时过期，由 refresh token 自动续期，凭据存
> `~/.libtv/credentials.json`（权限 `0600`，仅本人可读写，令牌不出本机）。

---

## 3. 安装

```bash
cd LibTV-Team
pip install -r requirements.txt
# 或作为包安装（提供 libtv-team 命令）
pip install -e .
```

依赖：`httpx`、`fastapi`、`uvicorn`、`pydantic`、`qrcode`（Python ≥ 3.8）。

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

#### 手机号登录端点

手机号登录端点已内置在 `config.py` 中（基于官方 passport 登录流程），无需手动设置。
若未来端点变动，可用环境变量 `LIBLIB_PHONE_SMS_SEND_URL` / `LIBLIB_PHONE_LOGIN_URL`
覆盖；Web API 基址可用 `LIBLIB_WEB_API_BASE` 覆盖。

---

## 5. 团队账号统一管理与创作调用

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
# 浏览器打开 http://127.0.0.1:8000/ 即可管理（/panel 为同一页面的兼容路径）
```

> `serve` 默认启动 `liblib2api.panel_server:app`（多账号版）。面板为随程序自带的
> 零依赖单 HTML 页面（`liblib2api/panel.html`），无需单独构建前端。若只需单账号
> MCP 透传，可改用 `uvicorn liblib2api.server:app --port 8000`。

### 一键启动脚本

项目根目录提供跨平台一键启动脚本，会自动建虚拟环境、安装依赖并拉起面板：

```bash
# Linux / macOS
./start.sh
# Windows（双击 start.bat，或以管理员 PowerShell 运行 start.ps1）
start.bat
```

启动后浏览器自动打开 `http://127.0.0.1:8000/panel`。可用环境变量 `LIBLIB_PORT` / `LIBLIB_HOST` 覆盖端口与监听地址。

> **Windows 提示**：脚本已处理中文乱码（`chcp 65001` + UTF-8 BOM），会自动探测
> `py -3` / `python` / `python3` 并创建 `.venv`、安装依赖后启动。
> 若双击无反应，请在 PowerShell 中执行 `.\start.ps1` 查看具体报错。

接口一览（多账号面板 `panel_server`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/panel` | 团队账号池管理面板（单页应用） |
| GET | `/health` | 健康检查 + 账号数 + 监控状态 |
| GET | `/api/v1/accounts` | 账号池列表（含类型/算力点/额度/到期/活性/可用模型数） |
| POST | `/api/v1/accounts/import` | 导入账号 JSON，**自动识别类型 + 模型可用性** |
| GET | `/api/v1/accounts/export` | 导出账号池 JSON |
| POST | `/api/v1/accounts/register-current` | 把本机凭据注册进账号池 |
| GET | `/api/v1/accounts/{account}/type` | 账号类型识别详情 |
| GET | `/api/v1/accounts/{account}/models` | 该账号可用模型（标注每个是否可用） |
| POST | `/api/v1/accounts/{account}/sync` | 同步算力点/类型/到期时间/模型可用性 |
| POST | `/api/v1/accounts/{account}/claim` | 手动领取当日免费算力权益（旧路径 `/checkin` 仍兼容） |
| POST | `/api/v1/accounts/{account}/proxy` | 绑定独立代理 IP |
| GET | `/api/v1/monitor/status` | 监控状态（最近一次巡检结果） |
| POST | `/api/v1/monitor/check` | 立即巡检一次（活性 + 自动领取权益） |
| POST | `/api/v1/generate/video` | 视频生成（**支持 mp4/webm/mov/gif、多种分辨率/时长/帧率**） |
| POST | `/api/v1/generate/image` | 图片生成（交叉选号，支持 png/jpg/webp） |
| POST | `/api/v1/generate/audio` | 音频生成（交叉选号，支持 mp4/wav/mp3） |
| GET | `/api/v1/tools?kind=` | 按类型（video/image/audio）列出 MCP 工具并推荐默认工具 |
| POST | `/api/v1/generate/video/balance` | **算力均摊**：仅当无任一账号能独立生成完整时长时，分段接力生成（旧路径 `/split` 仍兼容） |
| GET | `/api/v1/accounts/expiring?days=` | **会员即将到期提醒**列表（默认提前 30 天，含剩余天数） |
| GET/POST | `/api/v1/teams` | 团队列表 / 新建团队 |
| GET/PATCH/DELETE | `/api/v1/teams/{team_id}` | 团队详情 / 改名与备注 / 删除 |
| GET/POST | `/api/v1/teams/{team_id}/members` | 团队下的成员列表 / 新增成员（可设额度） |
| GET | `/api/v1/members` | 全部成员与额度概览 |
| PATCH | `/api/v1/members/{member_id}` | 更新成员资料（姓名 / 备注 / 额度上限） |
| POST | `/api/v1/members/{member_id}/quota` | 设置成员每日额度上限（`quota_limit`，`null` = 不限） |
| DELETE | `/api/v1/members/{member_id}` | 移除成员（账号保留，仅解除归属） |
| POST | `/api/v1/accounts/{account}/assign` | 把账号分配给成员（自动备注「团队·成员 的账号」） |
| POST | `/api/v1/accounts/{account}/remark` | 设置账号备注 |
| GET | `/api/v1/terms` | 使用条例状态与全文（首次进入面板需阅读并同意） |
| POST | `/api/v1/terms/accept` | 记录使用条例同意（写入本机 `settings.json`） |
| GET | `/api/v1/stats` | 团队统计（总览 + 成员维度 + 账号维度） |
| GET | `/api/v1/stats/overview` | 团队总览指标（轻量版） |
| GET | `/api/v1/notify/status` | 通知通道状态、告警规则与最近发送记录 |
| POST | `/api/v1/notify/config` | 保存通知通道配置（邮件 SMTP / 企业微信 Webhook / 控制台） |
| POST | `/api/v1/notify/rule/{event}` | 更新某类告警的启停与阈值 |
| POST | `/api/v1/notify/test` | 发送测试通知（可指定 `channel`） |
| GET | `/api/v1/notify/history` | 最近的通知发送记录 |
| POST | `/api/v1/alerts/scan` | 立即扫描一次告警（`force=true` 可忽略静默期） |
| POST | `/api/v1/admin/login` | 面板管理员登录（单管理员，返回会话令牌） |
| POST | `/api/v1/admin/password` | 修改管理员密码 |
| GET | `/api/v1/admin/apikey` | 查看对外 API Key |
| GET/POST | `/api/v1/settings` | 设置：OpenAI 兼容 API（分段规划用）/ 每算力点消耗 / 监控间隔 |

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

### 5.1 团队账号统一管理面板（账号池核心能力）

> liblib 平台原生**没有团队功能**：成员账号各自独立、额度互不相通、会员到期无人知晓。
> 下面的能力都是在官方账号体系之上补齐的**统一管理层**，不修改平台任何机制。

面向团队：每位成员把各自的 liblib 会员/额度包账号加入账号池，自动化工作流无需关心
具体用哪个号，由系统**交叉自动选号**。

| 能力 | 说明 |
|---|---|
| **账号类型自动识别** | 导入/登录/同步时调 `member/account`：识别 `VIP / 免费`（`is_sub` 副卡作为独立标签）、`member_until` 到期时间；面板统一显示为「VIP / 免费」 |
| **多团队与成员纳管** | 平台原生无团队功能：这里自建「团队 → 成员 → 账号」层级，把成员账号统一纳管，账号可自动备注为「团队·成员 的账号」 |
| **成员额度限制** | 为每位成员设置每日算力点上限与用量统计；额度用尽的账号会被选号引擎自动跳过，并支持一键重置用量 |
| **会员即将到期提醒** | 按 `member_until` 计算剩余天数：临近到期（默认 30 天内）自动标黄、7 天内标红、已到期标红告警；面板顶部汇总提醒条，`/api/v1/accounts/expiring` 可接外部巡检/告警 |
| **模型可用性识别** | 对每个账号：会员专属模型（名称/标签含 VIP/会员专属 等）+ 当日免费权益豁免 → 标出「免费版用不了」的模型（如 Seedance 2.0 VIP） |
| **综合自动交叉选号** | 生成时按「模型可用 + 算力点足够 + 均衡/最少使用/算力点最多/会员优先」策略从账号池挑号，均摊团队额度 |
| **图片 / 视频 / 音频统一生成** | 三类媒体均走 MCP 工具 + 交叉选号；视频支持 mp4/webm/mov/gif 多格式与多分辨率；图片 png/jpg/webp；音频 mp4/wav/mp3 |
| **算力均摊（跨账号分段）** | 仅当**没有任何账号能独立生成完整时长**时才启用：拆成多段（如 5+5+5 / 9+4+1+1 秒），每段交给算力点够用的账号接力生成，本地 ffmpeg 拼接。若有账号能独立完成，则直接由它一次生成。可配置 **OpenAI 兼容 API** 做分段规划 |
| **在线 Playground** | 面板内置统一试用台：图片/视频/音频一键切换、参数化、结果直接预览（图/视频/音频播放器） |
| **管理员登录与使用条例** | 单管理员用户名/密码登录（可改密）；对外 API 支持 Bearer / X-Api-Key / `?api_key=`；首次进入需阅读并同意使用条例 |
| **每 10 分钟活性检查** | 后台线程每 600s 巡检：验证 token 活性、刷新类型/算力点与会员到期时间、自动领取当日免费算力权益 |
| **团队统计** | 总览（算力点合计 / 在线 / 临近到期 / 模型可用覆盖率）+ 成员维度（额度使用率）+ 账号维度（调用错误比、到期倒计时） |
| **告警通知** | 邮件（SMTP）+ 企业微信机器人 Webhook + 控制台三通道；8 类告警规则可逐项启停并调阈值 |
| **独立代理 IP** | 每个账号可绑定独立代理 |
| **导入/导出** | 账号池 JSON 导入导出（权限 0600） |

> 关键词识别覆盖绝大多数会员专属模型；若某模型实际被拒，会记入该账号的
> `model_usable` 缓存（运行时学习），越用越准。

### 5.2 团队与成员管理（平台原生没有的功能）

liblib 平台原生**没有团队 / 组织**：成员账号彼此独立、额度互不相通、会员到期无人知晓。
本项目在其上补齐一层**统一纳管**，不修改平台任何机制。

| 层级 | 说明 |
|---|---|
| **团队** | 一个协作单位（如「视频组」），可写备注；一个账号池可同时管理多个团队 |
| **成员** | 团队内的自然人（如「张三」），可绑定多个自己的账号 |
| **账号归属** | 把账号分配给成员后，账号自动备注为「视频组·张三 的账号」；备注也可手动改写 |
| **每日额度限制** | 为每位成员设「每日算力点上限」；生成时自动记账，跨天自动清零 |
| **额度拦截** | 额度用尽的成员，其账号会被选号引擎**自动跳过**，避免超额消耗 |
| **用量可视** | 面板显示每个成员的「已用 / 上限」进度条（≥80% 变黄、满额变红），可一键重置用量 |

调用示例：

```bash
# 1) 建团队
curl -X POST "http://127.0.0.1:8000/api/v1/teams" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"视频组","note":"负责视频产出"}'

# 2) 加成员并限制每日 1000 算力点
curl -X POST "http://127.0.0.1:8000/api/v1/teams/<team_id>/members" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"张三","quota_limit":1000}'

# 3) 把账号分配给张三（自动备注「视频组·张三 的账号」）
curl -X POST "http://127.0.0.1:8000/api/v1/accounts/191****1785/assign" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"member_id":"<member_id>"}'

# 4) 查谁快到期了
curl "http://127.0.0.1:8000/api/v1/accounts/expiring?days=30" \
  -H "Authorization: Bearer $API_KEY"
```

> **遗留单账号透传模式（无账号池）**：如需把本机单个 liblib 凭据以 MCP / OpenAPI 直接透传，
> 可改用 `uvicorn liblib2api.server:app --port 8000`（实现见 `server.py`）。新部署建议使用上面的多账号面板。

### 5.3 团队统计与告警通知

团队规模变大后，光有账号列表不够用：得知道**资产还剩多少**、**谁用超了**、
**哪个账号出问题了**，并且要**主动通知到人**，而不是等人去面板翻。

**统计（团队统计页 / `GET /api/v1/stats`）**

| 维度 | 内容 |
|---|---|
| 总览 | 账号总数、VIP / 免费账号数、算力点合计、每日免费算力、在线 / 失效 / 临近到期数、模型可用覆盖率 |
| 成员维度 | 名下账号数、算力点合计、今日额度已用 / 上限、使用率进度条、累计调用次数 |
| 账号维度 | 算力点与免费算力、可用模型数、调用 / 错误计数、最近使用时间、会员到期倒计时 |

**通知中心（通知告警页 / `/api/v1/notify/*`）**

| 通道 | 说明 |
|---|---|
| **邮件** | 标准 SMTP（SSL 465 / STARTTLS 587 均可），支持多个收件人；SMTP 密码仅存本机 `settings.json` |
| **企业微信机器人** | 群机器人 Webhook，Markdown 消息体，支持 `@成员`；适合即时提醒 |
| **控制台** | 兜底通道，输出到服务日志，便于本地排查 |

告警规则可逐项启停并调阈值，命中后按通道推送；同一事件在静默期内不重复推送。

| 告警项 | 默认阈值 |
|---|---|
| 会员即将到期 | 提前 30 天 |
| 会员已到期 | — |
| 账号失效 | — |
| 算力点余额偏低 | < 100 点 |
| 成员额度接近上限 | ≥ 90% |
| 成员额度已用尽 | — |
| 权益领取失败 | — |
| 每日领取摘要 | 默认关闭 |

```bash
# 配置企业微信机器人并开启
curl -X POST "http://127.0.0.1:8000/api/v1/notify/config" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"wecom":{"enabled":true,"webhook_url":"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"}}'

# 立即扫描一次告警并发送
curl -X POST "http://127.0.0.1:8000/api/v1/alerts/scan" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' -d '{"force":true}'

# 查看统计与发送记录
curl "http://127.0.0.1:8000/api/v1/stats" -H "Authorization: Bearer $API_KEY"
curl "http://127.0.0.1:8000/api/v1/notify/history?limit=20" -H "Authorization: Bearer $API_KEY"
```

命令行同样可查：

```bash
python -m liblib2api.cli stats       # 团队算力点与用量概览
python -m liblib2api.cli notify      # 通道与规则状态
python -m liblib2api.cli notify --test --channel wecom   # 发一条测试通知
```

---

## 6. 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LIBTV_HOME` | `~/.libtv` | 凭据目录 |
| `LIBTV_ISSUER` | （内置，可经环境变量覆盖） | OAuth issuer（用于发现端点） |
| `LIBTV_MCP_URL` | （内置） | MCP 网关 |
| `LIBTV_OAUTH_PORT` | `8765` | CLI 阻塞模式本地回调端口 |
| `LIBTV_OAUTH_CLIENT_ID` | 空（尝试动态注册） | OAuth client_id |
| `LIBLIB_PHONE_API_BASE` | （内置） | 手机号登录基址 |
| `LIBLIB_PHONE_SMS_SEND_URL` / `LIBLIB_PHONE_LOGIN_URL` | （内置） | 手机号登录端点，可覆盖 |
| `LIBLIB_WEB_API_BASE` | （内置） | 会员/算力点/模型列表接口基址 |
| `LIBLIB_MONITOR_INTERVAL` | `600` | 账号活性巡检间隔（秒，默认 10 分钟） |
| `LIBLIB_MEMBER_EXPIRY_WARN_DAYS` | `30` | 会员到期提醒提前天数（面板高亮 + `/accounts/expiring` 默认窗口） |
| `LIBLIB_TEAMS_FILE` | `~/.libtv/teams.json` | 团队与成员数据文件（权限 0600） |
| `LIBLIB_IMAGE_POINTS_ESTIMATE` | `10` | 图片生成的额度估算（算力点/张），用于成员额度记账 |
| `LIBLIB_ADMIN_USER` | `admin` | 面板管理员用户名（单管理员） |
| `LIBLIB_ADMIN_PASSWORD` | `admin` | 管理员初始密码（仅首次生效，建议首登后在「设置」中修改） |
| `LIBLIB_REQUIRE_AUTH` | `1` | 是否强制鉴权（`0` = 关闭，仅建议本机/内网使用） |
| `LIBLIB_AUTH_SECRET` | 空 | 会话令牌签名密钥（留空则每次启动随机，重启后旧令牌失效） |
| `LIBTV_ACCESS_KEY` | 空 | OpenAPI Access Key（可选） |
| `LIBLIB_PROXY` | 空 | HTTP 代理 |
| `LIBLIB_SERVER_PORT` / `LIBLIB_SERVER_PUBLIC_URL` | `8000` / `http://127.0.0.1:8000` | 服务端口与 OAuth 回调对外地址 |
| `LIBLIB_OPENAI_BASE_URL` | `https://api.openai.com/v1` | 算力均摊「分段规划」用的 OpenAI 兼容 API 地址（任意兼容 /v1/chat/completions 的服务） |
| `LIBLIB_OPENAI_API_KEY` | 空 | 上述 API Key（也可在面板「设置」页填写，持久化到 `settings.json`） |
| `LIBLIB_OPENAI_MODEL` | `gpt-4o-mini` | 分段规划所用模型名 |
| `LIBLIB_POINTS_PER_SECOND` | `10` | 拆分预算估算：每生成 1 秒视频约消耗算力点（可在面板「设置」调整） |
| `LIBLIB_SETTINGS_FILE` | `~/.libtv/settings.json` | 运行设置持久化文件（权限 0600） |

---

## 7. 项目结构

```
LibTV-Team/
├── liblib2api/
│   ├── config.py          # 全局配置与常量（端点、环境变量）
│   ├── exceptions.py      # 统一异常
│   ├── credentials.py     # 凭据加载/持久化/刷新（0600）
│   ├── auth/
│   │   ├── base.py         # 登录方式抽象
│   │   ├── phone.py       # 手机号验证码登录（端点可配置）
│   │   └── wechat.py      # 微信扫码 OAuth 2.1 + PKCE
│   ├── mcp.py             # MCP JSON-RPC 客户端（SSE 兼容 + 自动续期，支持直接传凭据）
│   ├── openapi.py         # OpenAPI REST 客户端（Access Key）
│   ├── client.py          # 统一门面 LiblibClient
│   ├── accounts.py        # 多账号仓库（账号池 / 独立代理 / 导入导出 / 类型识别 / 团队归属）
│   ├── teams.py           # 团队与成员（统一纳管 + 每日额度限制与用量记账）
│   ├── expiry.py          # 会员到期解析与提醒分级（临近到期 / 已到期）
│   ├── webapi.py          # Web API 客户端（会员/积分/模型可用性/类型与到期识别）
│   ├── models.py          # 模型注册表 + 会员专属识别 + 可用性标注
│   ├── selector.py        # 综合自动交叉账号选择引擎
│   ├── monitor.py         # 账号活性监控（10 分钟巡检 + 自动领取权益）
│   ├── video_output.py    # 多格式视频生成规范与结果归一化
│   ├── media.py           # 图片/音频生成规范与参数构建
│   ├── split_gen.py       # 算力均摊（分段规划 + 按算力点贪心分配多账号）
│   ├── panel_server.py    # 团队管理面板 + 对外开放 API（默认 serve 入口）
│   ├── notify.py          # 通知中心（邮件 SMTP / 企业微信机器人 Webhook / 控制台 + 告警规则）
│   ├── analytics.py       # 团队统计（总览 / 成员维度 / 账号维度聚合）
│   ├── panel.html         # 面板前端单页应用（账号池/到期提醒/模型/Playground/均摊/监控/统计/通知/设置）|
│   ├── server.py          # 遗留单账号 FastAPI 服务（MCP 透传）
│   └── cli.py             # 命令行入口
├── start.sh               # Linux/macOS 一键启动（建 venv + 装依赖 + 起面板）
├── start.ps1 / start.bat  # Windows 一键启动（UTF-8 防乱码 + 自动装依赖）
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 8. 安全与合规

完整条款见上文「**合规声明与使用条例**」，要点复述：

- 凭据文件权限为 `0600`，令牌仅存本机，不外传、不写日志。
- 微信扫码是 OAuth 标准流程，令牌只能由你本人账户签发，本项目不代你登录、不收集密码。
- 请仅用于**本人与本团队合法拥有的账号**；遵守 liblib.tv 服务条款与频控。
- 不做逆向、破解、绕过平台限制、批量注册与账号买卖。
- 面板默认开启鉴权并要求首次阅读同意使用条例；对外暴露请自行加固（改密 + 使用 API Key）。
- 本仓库仅作学习 / 研究与团队自用用途的接口封装示例。

---

## 9. 路线图

- [x] 团队用量与算力点统计（总览 / 成员维度 / 账号维度）
- [x] 到期提醒接入外部通道（邮件 SMTP / 企业微信机器人）
- [ ] 生成历史记录留存与导出
- [ ] 成员月度预算上限与成本分摊报表
- [ ] 生成任务的异步轮询 + webhook 回调
- [ ] 补充各 MCP 工具的高层封装（generate_video / export 等）与轮询助手
- [ ] 面板内登录体验优化与生成历史展示

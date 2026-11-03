"""LibTV-Team 全局配置与常量。

所有可调参数均支持环境变量覆盖，便于在不改代码的情况下接入不同环境。
登录端点遵循 liblib 官方 passport 登录流程与 MCP 规范，其中微信扫码走标准
OAuth 2.1 + PKCE（端点可自动发现），手机号验证码端点内置于下方常量，
并可通过环境变量覆盖（详见 README「手机号登录端点」一节）。
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 目录与凭据
# ---------------------------------------------------------------------------
# 凭据目录，等价于官方 libtv CLI / dsh-libtv 的 ~/.libtv
LIBTV_HOME = Path(os.environ.get("LIBTV_HOME", os.path.expanduser("~/.libtv")))
CREDENTIALS_FILE = LIBTV_HOME / "credentials.json"
# 多账号仓库
ACCOUNTS_FILE = Path(
    os.environ.get("LIBTV_ACCOUNTS_FILE", str(LIBTV_HOME / "accounts.json"))
)
# 运行设置（OpenAI 兼容 API、每积分消耗等，可由面板持久化）
SETTINGS_FILE = Path(
    os.environ.get("LIBLIB_SETTINGS_FILE", str(LIBTV_HOME / "settings.json"))
)
# 团队与成员数据（平台原生无团队功能，这里做统一纳管）
TEAMS_FILE = Path(
    os.environ.get("LIBLIB_TEAMS_FILE", str(LIBTV_HOME / "teams.json"))
)

# ---------------------------------------------------------------------------
# 真实 API 基址（实测）
# ---------------------------------------------------------------------------
# passport：登录 / 用户信息
PASSPORT_BASE = os.environ.get("LIBLIB_PASSPORT_BASE", "https://passport.liblib.art")
# Web API 主体：会员 / 积分 / 模型列表
WEB_API_BASE = os.environ.get("LIBLIB_WEB_API_BASE", "https://api2.liblib.art")
# 生图网关（有 WAF，非浏览器指纹请求会被 405 拦截）
BRIDGE_BASE = os.environ.get("LIBLIB_BRIDGE_BASE", "https://bridge.liblib.art")

# ---------------------------------------------------------------------------
# 微信扫码登录（OAuth 2.1 + PKCE）—— 标准、可自动发现
# ---------------------------------------------------------------------------
# MCP / OAuth issuer。微信扫码授权页与 token 端点由其 /.well-known 动态发现。
LIBTV_ISSUER = os.environ.get("LIBTV_ISSUER", "https://mcp.liblib.tv")
# 直接指定 MCP 网关（Bearer token 实际打这里）
LIBTV_MCP_URL = os.environ.get("LIBTV_MCP_URL", "https://mcp.liblib.tv/mcp")
# OAuth 发现文档路径
OAUTH_DISCOVERY_PATH = os.environ.get(
    "LIBTV_OAUTH_DISCOVERY_PATH", "/.well-known/oauth-authorization-server"
)
# 本地回调（CLI 阻塞模式用 127.0.0.1:8765，与官方一致）
OAUTH_REDIRECT_HOST = os.environ.get("LIBTV_OAUTH_HOST", "127.0.0.1")
OAUTH_PORT = int(os.environ.get("LIBTV_OAUTH_PORT", "8765"))
OAUTH_REDIRECT_PATH = os.environ.get("LIBTV_OAUTH_PATH", "/callback")
# client_id：优先用环境变量；否则尝试动态注册；再不行用兜底值
OAUTH_CLIENT_ID = os.environ.get("LIBTV_OAUTH_CLIENT_ID", "")
# 留空时由 OAuth 发现文档的 scopes_supported 自动填充（实测为
# libtv:account:read libtv:project:read libtv:project:write 等）。
OAUTH_SCOPE = os.environ.get("LIBTV_OAUTH_SCOPE", "")
OAUTH_TIMEOUT = int(os.environ.get("LIBTV_OAUTH_TIMEOUT", "300"))  # 等待扫码超时(秒)

# ---------------------------------------------------------------------------
# 手机号验证码登录（liblib 账号体系，实测端点）
# ---------------------------------------------------------------------------
PHONE_API_BASE = os.environ.get("LIBLIB_PHONE_API_BASE", "https://passport.liblib.art")
# 站点来源 / Referer
PHONE_ORIGIN = os.environ.get("LIBLIB_PHONE_ORIGIN", "https://www.liblib.art")
# 以下为实测可用端点，可通过环境变量覆盖：
#   LIBLIB_PHONE_SMS_SEND_URL / LIBLIB_PHONE_LOGIN_URL / LIBLIB_PHONE_USER_INFO_URL
PHONE_SMS_SEND_URL = os.environ.get(
    "LIBLIB_PHONE_SMS_SEND_URL",
    f"{PHONE_API_BASE}/api/www/login/sendLoginPhoneCode",
)
PHONE_LOGIN_URL = os.environ.get(
    "LIBLIB_PHONE_LOGIN_URL",
    f"{PHONE_API_BASE}/api/www/login/loginByPhoneCode",
)
PHONE_USER_INFO_URL = os.environ.get(
    "LIBLIB_PHONE_USER_INFO_URL",
    f"{PHONE_API_BASE}/api/www/user/getUserInfo",
)
# 手机号登录拿到的 token 默认打哪个服务（Web API 域）
PHONE_TOKEN_TARGET = os.environ.get("LIBLIB_PHONE_TOKEN_TARGET", WEB_API_BASE)

# ---------------------------------------------------------------------------
# LibTV OpenAPI（Access Key 鉴权，可选）
# ---------------------------------------------------------------------------
OPENAPI_BASE = os.environ.get("LIBTV_OPENAPI_BASE", "https://im.liblib.tv")
OPENAPI_ACCESS_KEY = os.environ.get("LIBTV_ACCESS_KEY", "")

# ---------------------------------------------------------------------------
# HTTP 客户端默认值
# ---------------------------------------------------------------------------
HTTP_TIMEOUT = int(os.environ.get("LIBLIB_HTTP_TIMEOUT", "30"))
HTTP_PROXY = os.environ.get("LIBLIB_PROXY", "")

# 对外暴露的服务端口（python -m liblib2api.cli serve）
SERVER_PORT = int(os.environ.get("LIBLIB_SERVER_PORT", "8000"))
# 服务端模式下 OAuth 回调指向的公网/本机地址（默认 http://127.0.0.1:SERVER_PORT）
SERVER_PUBLIC_URL = os.environ.get(
    "LIBLIB_SERVER_PUBLIC_URL", f"http://127.0.0.1:{SERVER_PORT}"
)

# MCP 协议版本（对端协商，向下兼容）
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_CLIENT_NAME = "liblib2api"
MCP_CLIENT_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# OpenAI 兼容 API（视频拆分生成的「智能拆条」规划用）
# ---------------------------------------------------------------------------
# 任意兼容 /v1/chat/completions 的服务：OpenAI、DeepSeek、通义、本地 Ollama 等
OPENAI_COMPATIBLE_BASE_URL = os.environ.get(
    "LIBLIB_OPENAI_BASE_URL", "https://api.openai.com/v1"
)
OPENAI_COMPATIBLE_API_KEY = os.environ.get("LIBLIB_OPENAI_API_KEY", "")
OPENAI_COMPATIBLE_MODEL = os.environ.get("LIBLIB_OPENAI_MODEL", "gpt-4o-mini")

# 拆分生成时，每生成 1 秒视频预计消耗的算力点（用于估算账号额度是否够接力）
# 不同分辨率/模型会有差异，这里给一个可配置的经验值，面板可在「设置」中调整
POINTS_PER_SECOND = float(os.environ.get("LIBLIB_POINTS_PER_SECOND", "10"))

# 图片生成的额度估算（算力点/张），用于成员额度记账；平台未按张公开计费口径，取经验值
IMAGE_POINTS_ESTIMATE = float(os.environ.get("LIBLIB_IMAGE_POINTS_ESTIMATE", "10"))

# 账号类型展示标签（VIP / 免费），避免展示「免费/副卡」这类内部组合
ACCOUNT_TYPE_LABEL = {"member": "VIP", "vip": "VIP", "free": "免费", "unknown": "未知"}

# ---------------------------------------------------------------------------
# 会员到期提醒（团队管理）
# ---------------------------------------------------------------------------
# liblib 平台原生没有团队功能，成员账号到期时间互不相通，这里统一提前提醒，
# 避免团队额度突然断档。单位：天。
MEMBER_EXPIRY_WARN_DAYS = int(os.environ.get("LIBLIB_MEMBER_EXPIRY_WARN_DAYS", "30"))

# ---------------------------------------------------------------------------
# 面板管理员 & 对外 API Key 鉴权（公网部署必备）
# ---------------------------------------------------------------------------
# 单管理员账号（可改）。首次运行未配置时用默认 admin/admin，并提示修改。
ADMIN_USER = os.environ.get("LIBLIB_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("LIBLIB_ADMIN_PASSWORD", "admin")
# 对外 API Key：未配置时由程序首次启动自动生成并持久化到 settings.json
API_KEY = os.environ.get("LIBLIB_API_KEY", "")
# 会话令牌/API Key 签名密钥（未配置则每次启动随机；用 env 可固定）
AUTH_SECRET = os.environ.get("LIBLIB_AUTH_SECRET", "")
# 是否强制鉴权（设为 0 可临时关闭，仅建议本地调试）
REQUIRE_AUTH = os.environ.get("LIBLIB_REQUIRE_AUTH", "1") != "0"

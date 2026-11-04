"""多账号管理面板 + 对外开放 API（FastAPI）。

设计原则
--------
1. 面板（/panel）是零依赖单页应用（panel.html），浏览器打开即可管理账号、看积分、
   看模型可用性、发起图片/视频/音频生成。
2. 对外 API（/api/v1/*）给自动化工作流用：图片/视频/音频生成走账号池交叉选择，
   积分、账号类型、模型可用性动态拉取。视频支持多格式输出与「多账号接力拆分生成」。
3. 每个账号可绑定独立代理 IP。
4. 后台每 10 分钟巡检账号活性 + 自动签到（monitor）。
5. 公网/团队共享部署时：面板需**单管理员用户名/密码**登录；对外 API 需携带 **API Key**
   （支持 Authorization: Bearer / X-Api-Key / ?api_key= 多种兼容形式）。

关于「多用户」
------------
这里的「多用户」指 liblib 平台账号池（团队成员各自的会员/额度包），面板本身只设一个管理员。
管理员账号用于守护 WebUI 与对外 API 的访问，凭据仅存本机 settings.json（权限 0600）。

账号池策略
----------
    POST /api/v1/generate/video   {prompt, format, duration, resolution, model?, account?}
    不指定 account 时，按模型可用 + 积分 + 均衡策略从账号池交叉选择最合适的账号。
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import qrcode
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import liblib2api.config as cfg
from liblib2api import auth as srv_auth
from liblib2api.accounts import Account, AccountStore
from liblib2api.credentials import CredentialStore
from liblib2api.analytics import team_stats
from liblib2api.exceptions import ApiError, AuthError, ModelUnavailableError
from liblib2api.expiry import expiry_info
from liblib2api.notify import (
    EVENT_ACCOUNT_INVALID,
    EVENT_CLAIM_FAILED,
    EVENT_DAILY_DIGEST,
    EVENT_MEMBER_EXPIRED,
    EVENT_MEMBER_EXPIRING,
    EVENT_POINTS_LOW,
    EVENT_QUOTA_EXHAUSTED,
    EVENT_QUOTA_NEAR_LIMIT,
    NotifyCenter,
    NotifyMessage,
)
from liblib2api.media import (
    ImageGenerateRequest,
    AudioGenerateRequest,
    build_image_arguments,
    build_audio_arguments,
    normalize_media,
)
from liblib2api.monitor import AccountMonitor
from liblib2api.selector import AccountSelector
from liblib2api.teams import TeamStore
from liblib2api.split_gen import (
    OpenAICompatibleClient,
    VideoSplitPlanner,
    assign_accounts,
    single_account_feasible,
)
from liblib2api.video_output import VideoGenerateRequest, build_arguments, normalize_result
from liblib2api.webapi import WebApiClient

import json as _json

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("liblib2api.panel")

app = FastAPI(
    title="LibTV-Team",
    description="团队账号统一管理面板 + 图片/视频/音频生成开放接口（团队自用）",
    version="0.5.0",
)

# 跨域支持：独立前端（如 Vite 开发服务器 :5173）需要能跨端口调用本 API。
# 可用 LIBLIB_CORS_ORIGINS 指定逗号分隔的白名单；留空则允许任意来源（自托管场景）。
_CORS_ORIGINS = [
    o.strip()
    for o in (os.environ.get("LIBLIB_CORS_ORIGINS") or "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS or ["*"],
    allow_credentials=bool(_CORS_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ---------------------------------------------------------------------------
# 构建版前端（Vue SPA）托管
# 后端在 8000 端口同时提供 API（/api/v1/*）与图形化界面。构建产物优先从
# 仓库内嵌的 liblib2api/webui/dist 读取；也可通过 LIBLIB_WEBUI_DIST 指向
# 同级的 front/dist（开发场景），或任意自定义目录。
# ---------------------------------------------------------------------------
def _find_webui_dist() -> Optional[Path]:
    env = os.environ.get("LIBLIB_WEBUI_DIST")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path(__file__).parent / "webui" / "dist")
    candidates.append(Path(__file__).parent.parent.parent / "front" / "dist")
    candidates.append(Path("/workspace/front/dist"))
    for c in candidates:
        try:
            if c.is_dir() and (c / "index.html").exists():
                return c
        except OSError:  # noqa: BLE001
            continue
    return None


_WEBUI_DIST = _find_webui_dist()

_store = AccountStore()
_teams = TeamStore()
_selector = AccountSelector(_store, _teams)
_monitor = AccountMonitor(_store, interval=int(os.environ.get("LIBLIB_MONITOR_INTERVAL", "600")))

_PENDING_WECHAT: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# 管理员 & API Key 运行时状态（由 lifespan 从 settings 载入）
# ---------------------------------------------------------------------------
_admin_user: str = cfg.ADMIN_USER
_admin_pass_hash: Optional[str] = None
_api_key: Optional[str] = None


# ---------------------------------------------------------------------------
# 设置（OpenAI 兼容 API / 每积分消耗 / 监控间隔），持久化到 settings.json
# ---------------------------------------------------------------------------
def _load_settings() -> dict:
    try:
        if cfg.SETTINGS_FILE.exists():
            return _json.loads(cfg.SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_settings(s: dict) -> None:
    try:
        cfg.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(cfg.SETTINGS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(s, f, ensure_ascii=False, indent=2)
        os.chmod(cfg.SETTINGS_FILE, 0o600)
    except Exception:  # noqa: BLE001
        pass


# 通知中心（邮件 / 企业微信机器人 / 控制台），配置存 settings.json
_notifier = NotifyCenter(_load_settings, _save_settings)


def _type_label(at: Optional[str]) -> str:
    return cfg.ACCOUNT_TYPE_LABEL.get(at or "unknown", "未知")


# ---------------------------------------------------------------------------
# 管理员 & API Key 鉴权
# ---------------------------------------------------------------------------
def _ensure_admin() -> None:
    """首次启动保证管理员与对外 API Key 存在：
    - 未设密码则写入默认 admin/admin 并标记 needs_change=True（面板提示修改）
    - 未设 api_key 则自动生成并持久化
    """
    global _admin_user, _admin_pass_hash, _api_key
    s = _load_settings()
    if not s.get("admin_pass_hash"):
        s["admin_user"] = s.get("admin_user") or _admin_user
        s["admin_pass_hash"] = srv_auth.hash_password(cfg.ADMIN_PASSWORD)
        s["admin_needs_change"] = True
    if not s.get("api_key"):
        s["api_key"] = srv_auth.new_api_key()
    _save_settings(s)
    _admin_user = s.get("admin_user") or _admin_user
    _admin_pass_hash = s["admin_pass_hash"]
    _api_key = s["api_key"]


def _check_request_auth(request: Request) -> bool:
    """支持多种传入方式：Bearer、X-Api-Key、?api_key=；管理员会话令牌亦可调用。"""
    if not cfg.REQUIRE_AUTH:
        return True
    candidates: list[str] = []
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        candidates.append(auth[7:].strip())
    xk = request.headers.get("X-Api-Key")
    if xk:
        candidates.append(xk)
    qk = request.query_params.get("api_key")
    if qk:
        candidates.append(qk)
    for t in candidates:
        if not t:
            continue
        if _api_key and t == _api_key:
            return True
        if srv_auth.verify_token(t) == _admin_user:
            return True
    return False


_PUBLIC_PATHS = {
    "/",
    "/panel",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):  # noqa: ANN001
    path = request.url.path
    # 预检请求（CORS）直接放行，避免被鉴权中间件拦截
    if request.method == "OPTIONS":
        return await call_next(request)
    if path in _PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi.json") or path == "/redoc":
        return await call_next(request)
    # 登录接口无需鉴权
    if path == "/api/v1/admin/login":
        return await call_next(request)
    # 使用条例：首次进入面板时需在登录前阅读，故不强制鉴权
    if path in ("/api/v1/terms", "/api/v1/terms/accept"):
        return await call_next(request)
    # 微信 OAuth 回调：由用户浏览器携带授权码访问，不携带管理员令牌，故免鉴权
    if path == "/api/v1/auth/wechat/callback":
        return await call_next(request)
    if path.startswith("/api/v1/"):
        if not _check_request_auth(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权：请先登录面板，或在请求中携带 API Key（Authorization: Bearer / X-Api-Key / ?api_key=）"},
            )
    return await call_next(request)


# ---------------------------------------------------------------------------
# MCP 工具发现（图片 / 视频 / 音频）
# ---------------------------------------------------------------------------
_KIND_KEYWORDS = {
    "video": ["视频", "video", "影", "animation", "动图", "短片"],
    "image": ["图片", "image", "绘画", "生图", "绘图", "img", "画", "海报"],
    "audio": ["音频", "音乐", "声音", "音效", "audio", "music", "tts", "语音", "配音", "歌曲"],
}


def _tool_matches(tool: dict, kind: str) -> bool:
    blob = ((tool.get("name") or "") + " " + (tool.get("description") or "")).lower()
    kws = _KIND_KEYWORDS.get(kind, [])
    if any(k in blob for k in kws):
        # 排除被其它类型关键词命中的（例如「视频配乐」仍按 video 优先）
        others = [k for kk, kws2 in _KIND_KEYWORDS.items() if kk != kind for k in kws2]
        if not any(o in blob for o in others):
            return True
    return False


def _find_tool(creds, kind: str) -> Optional[str]:
    """从 MCP 工具列表里挑一个指定类型的生成工具。"""
    from liblib2api.client import LiblibClient

    try:
        client = LiblibClient(store=None, credentials=creds)
        tools = client.list_tools()
    except Exception:  # noqa: BLE001
        return None
    for t in tools:
        if _tool_matches(t, kind):
            return t.get("name")
    # 退一步：只含关键词即可
    blob_all = " ".join(
        ((t.get("name") or "") + " " + (t.get("description") or "")).lower() for t in tools
    )
    for t in tools:
        name = (t.get("name") or "").lower()
        if any(k in name for k in _KIND_KEYWORDS.get(kind, [])):
            return t.get("name")
    return None


# ---------------------------------------------------------------------------
# 生命周期：启动监控 + 必要时把已登录凭据导入账号池
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用持久化设置（监控间隔等）
    _ensure_admin()
    _s = _load_settings()
    if _s.get("monitor_interval"):
        try:
            _monitor.interval = int(_s["monitor_interval"])
        except (TypeError, ValueError):
            pass
    # 若账号池为空但本机已有登录凭据，自动注册为首个账号并识别类型
    if len(_store) == 0:
        try:
            creds = CredentialStore().get()
            if creds and creds.access_token:
                _register_credential(creds)
                log.info("已从本机凭据自动注册账号到账号池：%s", creds.account)
        except Exception as e:  # noqa: BLE001
            log.warning("自动注册本机凭据失败（可忽略）：%s", e)
    _monitor.start(run_immediately=True)
    log.info("账号活性监控已启动（间隔 %ss）", _monitor.interval)
    yield
    _monitor.stop()


app.router.lifespan_context = lifespan


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _client_for(acc: Account) -> WebApiClient:
    return WebApiClient(access_token=acc.access_token, webid=acc.webid, proxy=acc.proxy)


def _record_quota_usage(account: str, points: float) -> None:
    """按账号所属成员记账额度消耗（团队额度限制）。"""
    try:
        _teams.consume(account, float(points or 0))
    except Exception as e:  # noqa: BLE001
        log.debug("额度记账失败（%s）：%s", account, e)


def _current_pps() -> float:
    """当前每算力点可生成的秒数（用于额度估算）。"""
    try:
        return float(_load_settings().get("points_per_second") or cfg.POINTS_PER_SECOND)
    except Exception:  # noqa: BLE001
        return float(cfg.POINTS_PER_SECOND)


def _account_view(acc: Account) -> dict:
    usable = acc.model_usable or {}
    usable_count = sum(1 for v in usable.values() if v)
    # 团队 / 成员 / 额度（平台原生无团队功能，这里做统一纳管）
    member = _teams.member_of_account(acc.account)
    team = _teams.get_team(acc.team_id) if acc.team_id else None
    if member is not None and member.team_id:
        team = _teams.get_team(member.team_id) or team
    quota: Optional[dict] = None
    if member is not None:
        member.rollover()
        quota = {
            "member_id": member.id,
            "member_name": member.name,
            "limit": member.quota_limit,
            "used": member.quota_used,
            "remaining": member.quota_remaining(),
            "unlimited": member.quota_unlimited,
            "exhausted": member.quota_exhausted(),
            "reset_date": member.quota_reset_date,
        }
    # 会员到期提醒
    expiry = expiry_info(acc.member_until, warn_days=cfg.MEMBER_EXPIRY_WARN_DAYS)
    return {
        "account": acc.account,
        "nickname": acc.nickname,
        "login_method": acc.login_method,
        "user_id": acc.user_id,
        "uuid": acc.uuid,
        "account_type": acc.account_type,
        "account_type_label": _type_label(acc.account_type),
        "is_member": acc.is_member(),
        "is_sub": acc.is_sub,
        "member_name": acc.member_name,
        "account_level": acc.account_level,
        "member_until": acc.member_until,
        "package_type": acc.package_type,
        "points": acc.points,
        "free_power": acc.free_power,
        "has_get_power": acc.has_get_power,
        "alive": acc.alive,
        "alive_error": acc.alive_error,
        "last_alive_check": acc.last_alive_check,
        "last_sync": acc.last_sync,
        "last_claim": acc.last_claim,
        "last_checkin": acc.last_claim,  # 兼容旧字段名
        "proxy": acc.proxy,
        "status": acc.status,
        "note": acc.note,
        "remark": acc.note,
        "team_id": team.id if team else acc.team_id,
        "team_name": team.name if team else None,
        "member_id": member.id if member else acc.member_id,
        "member_display_name": member.name if member else None,
        "quota": quota,
        "member_until_days": expiry.get("days_left"),
        "member_expiry_level": expiry.get("level"),
        "member_expiry_text": expiry.get("level_text"),
        "member_until_text": expiry.get("member_until_text"),
        "expiring_soon": expiry.get("expiring_soon", False),
        "expired": expiry.get("expired", False),
        "request_count": acc.request_count,
        "error_count": acc.error_count,
        "last_used_at": acc.last_used_at,
        "model_usable_count": usable_count,
        "model_total_count": len(usable),
        "created_at": acc.created_at,
        "updated_at": acc.updated_at,
        "has_token": bool(acc.access_token),
    }


def _pick_account(account: Optional[str]) -> Account:
    if account:
        acc = _store.get(account)
        if not acc:
            raise HTTPException(404, f"账号不存在：{account}")
        if not acc.access_token:
            raise HTTPException(400, f"账号未登录：{account}")
        return acc
    acc = _store.next_round_robin()
    if not acc:
        raise HTTPException(400, "账号池为空，请先在面板中添加账号并登录")
    return acc


def _register_credential(creds, note: str = "") -> Account:
    """把 Credentials 注册为账号池中的一个账号，并立即同步识别类型。"""
    acc = Account(
        account=creds.account or creds.extra.get("phone") or creds.extra.get("nickname") or "unknown",
        access_token=creds.access_token,
        login_method=creds.login_method or "phone",
        webid=creds.extra.get("webid"),
        nickname=creds.extra.get("nickname"),
        user_id=str(creds.extra.get("user_id")) if creds.extra.get("user_id") else None,
        uuid=creds.extra.get("uuid"),
        note=note,
    )
    _store.add(acc)
    try:
        _sync_account(acc)
    except (ApiError, AuthError) as e:
        log.warning("账号 %s 同步失败：%s", acc.account, e)
    return acc


def _sync_account(acc: Account) -> dict:
    """拉取单个账号的积分/会员/模型可用性快照并落库。

    这是「账号类型自动识别」+「模型可用性识别」的统一入口：
      - 调 member/account 识别 account_type（member/free）、是否副卡、到期时间
      - 调 每日权益 + 模型列表，计算每个模型对该账号是否可用，写入 model_usable
    """
    try:
        with _client_for(acc) as c:
            snap = c.compute_model_usability()
    except (ApiError, AuthError) as e:
        _store.update(acc.account, status="error", alive=False,
                      alive_error=str(e)[:200], last_alive_check=int(time.time()))
        raise HTTPException(502, f"同步失败：{e}")

    atype = snap.get("account_type") or {}
    usable = snap.get("usable") or {}
    member = atype.get("raw_member") or {}

    # 免费算力（每日额度），用于面板展示与拆分生成的预算估算
    free_power = None
    try:
        fp = c.free_power()
        free_power = fp.get("freePower")
    except Exception:  # noqa: BLE001
        free_power = acc.free_power

    _store.update(
        acc.account,
        account_type=atype.get("type"),
        is_sub=atype.get("is_sub", acc.is_sub),
        owner_uuid=atype.get("owner_uuid"),
        owner_type=atype.get("owner_type"),
        member_name=atype.get("name"),
        account_level=atype.get("level"),
        member_until=atype.get("member_until"),
        package_type=atype.get("package_type"),
        free_power=free_power if free_power is not None else acc.free_power,
        model_usable=usable,
        status="active",
        alive=True,
        alive_error=None,
        last_alive_check=int(time.time()),
        last_sync=int(time.time()),
    )
    return snap


def _find_video_tool(creds) -> Optional[str]:
    """从 MCP 工具列表里挑一个视频生成工具（兼容旧调用）。"""
    return _find_tool(creds, "video")


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "accounts": len(_store),
        "monitor": _monitor.status().get("running"),
    }


@app.get("/api/v1/accounts")
def list_accounts():
    return {"accounts": [_account_view(a) for a in _store.list()]}


# 注意：静态路径必须注册在 "/api/v1/accounts/{account}" 通配路由之前，
# 否则会被通配路由抢先匹配（表现为「账号不存在」）。
@app.get("/api/v1/accounts/expiring")
def expiring_accounts(days: int = Query(cfg.MEMBER_EXPIRY_WARN_DAYS, ge=1, le=365)):
    """会员即将到期提醒（团队管理核心提醒）。"""
    warn = cfg.MEMBER_EXPIRY_WARN_DAYS
    items = []
    for acc in _store.list():
        info = expiry_info(acc.member_until, warn_days=warn)
        left = info.get("days_left")
        if left is None or left > days:
            continue
        view = _account_view(acc)
        items.append({
            "account": acc.account,
            "nickname": acc.nickname,
            "remark": acc.note,
            "team_name": view.get("team_name"),
            "member_display_name": view.get("member_display_name"),
            "member_until": acc.member_until,
            "member_until_text": info.get("member_until_text"),
            "days_left": left,
            "level": info.get("level"),
            "level_text": info.get("level_text"),
            "expired": info.get("expired"),
            "points": acc.points,
        })
    items.sort(key=lambda x: (x["days_left"] if x["days_left"] is not None else 9999))
    return {"days": days, "warn_days": warn, "count": len(items), "items": items}


@app.get("/api/v1/accounts/export")
def export_accounts(path: Optional[str] = Query(None, description="可选：写入指定文件路径")):
    """导出账号池 JSON（可选写入文件）。"""
    return _export_accounts(path)


@app.get("/api/v1/accounts/{account}")
def get_account(account: str):
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    return _account_view(acc)


@app.post("/api/v1/accounts/{account}/proxy")
def set_proxy(account: str, payload: dict = Body(...)):
    """给账号绑定代理 IP，proxy 传 null 清除。"""
    proxy = (payload or {}).get("proxy")
    acc = _store.set_proxy(account, proxy)
    if not acc:
        raise HTTPException(404, "账号不存在")
    return _account_view(acc)


@app.delete("/api/v1/accounts/{account}")
def delete_account(account: str):
    if not _store.remove(account):
        raise HTTPException(404, "账号不存在")
    return {"deleted": account}


@app.post("/api/v1/accounts/{account}/sync")
def sync_account(account: str):
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    return _sync_account(acc)


@app.post("/api/v1/accounts/sync-all")
def sync_all():
    results = []
    for acc in _store.list():
        if not acc.access_token:
            continue
        try:
            _sync_account(acc)
            results.append({"account": acc.account, "ok": True})
        except HTTPException as e:
            results.append({"account": acc.account, "ok": False, "error": e.detail})
    return {"results": results}


# ---------------------------------------------------------------------------
# 账号类型 / 模型可用性
# ---------------------------------------------------------------------------
@app.get("/api/v1/accounts/{account}/type")
def account_type(account: str):
    """返回账号类型识别详情（member/free、是否副卡、到期时间）。"""
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    try:
        with _client_for(acc) as c:
            atype = c.detect_account_type()
    except (ApiError, AuthError) as e:
        raise HTTPException(502, f"识别失败：{e}")
    return atype


@app.get("/api/v1/accounts/{account}/models")
def account_models(
    account: str,
    kind: str = Query("all", description="all | video | image"),
    usable_only: bool = Query(False, description="只看该账号可用的模型"),
):
    """列出该账号可用的视频/图片模型，并标注每个模型是否可用（会员限制等）。

    可用性来自：账号类型 + 模型会员专属分类 + 当日权益豁免，
    再叠加该账号运行时学习到的 model_usable 缓存。
    """
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    try:
        with _client_for(acc) as c:
            snap = c.compute_model_usability()
    except (ApiError, AuthError) as e:
        raise HTTPException(502, f"获取模型失败：{e}")

    atype = snap["account_type"]["type"]
    benefits = set(snap.get("free_benefit_keys", []))
    # 合并运行时学习缓存
    learned = acc.model_usable or {}

    out: list[dict] = []
    for k in ("video", "image"):
        if kind not in ("all", k):
            continue
        for m in snap["models"][k]:
            key = m.get("model_key") or m.get("name")
            usable = m.get("usable")
            if key in learned:
                usable = bool(learned[key])
            m = dict(m)
            m["usable"] = usable
            if usable_only and not usable:
                continue
            out.append(m)
    return {
        "account": acc.account,
        "account_type": atype,
        "free_benefit_keys": sorted(benefits),
        "count": len(out),
        "models": out,
    }


# ---------------------------------------------------------------------------
# 导入 / 导出
# ---------------------------------------------------------------------------
# 导出路由已前置到 "/api/v1/accounts/{account}" 之前注册，避免被通配路由遮蔽。
def _export_accounts(path: Optional[str] = Query(None, description="可选：写入指定文件路径")):
    text = _store.export(path)
    if path:
        return {"exported_to": path, "count": len(_store)}
    return JSONResponse(
        content=__import__("json").loads(text),
        headers={"Content-Disposition": 'attachment; filename="liblib-accounts.json"'},
    )


@app.post("/api/v1/accounts/import")
def import_accounts(payload: dict = Body(...)):
    """导入账号并自动识别类型。

    支持 {"accounts": [...]}，或 {"path": "/path/to.json"}，或 {"raw": "<json 文本>"}。
    每个导入的账号都会触发一次同步以识别类型与模型可用性。
    """
    if "path" in (payload or {}):
        p = Path(payload["path"])
        if not p.exists():
            raise HTTPException(400, f"文件不存在：{p}")
        summary = _store.import_accounts(p, overwrite=bool(payload.get("overwrite")))
    elif "raw" in (payload or {}):
        summary = _store.import_accounts(payload["raw"], overwrite=bool(payload.get("overwrite")))
    elif "accounts" in (payload or {}):
        import json as _json
        summary = _store.import_accounts(_json.dumps({"accounts": payload["accounts"]}),
                                         overwrite=bool(payload.get("overwrite")))
    else:
        raise HTTPException(400, "请提供 accounts 数组、raw 文本或 path 路径")

    # 导入后逐个识别类型
    for acc in _store.list():
        if acc.account in [a.get("account") for a in (payload.get("accounts") or []) if isinstance(a, dict)] \
                or payload.get("path") or payload.get("raw"):
            try:
                _sync_account(acc)
            except (ApiError, AuthError):
                pass
    return {"summary": summary, "total": len(_store)}


@app.post("/api/v1/accounts/register-current")
def register_current(note: str = ""):
    """把本机已登录凭据（credentials.json）注册进账号池并识别类型。"""
    try:
        creds = CredentialStore().get()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"无本机凭据：{e}")
    acc = _register_credential(creds, note=note)
    return _account_view(acc)


def seed_from_local_credential(note: str = "") -> Optional[dict]:
    """供 CLI 使用的便捷函数：把本机凭据导入账号池并识别类型。"""
    try:
        creds = CredentialStore().get()
    except Exception:  # noqa: BLE001
        return None
    if not creds or not creds.access_token:
        return None
    if _store.get(creds.account or creds.extra.get("phone")):
        return _account_view(_store.get(creds.account or creds.extra.get("phone")))
    acc = _register_credential(creds, note=note)
    return _account_view(acc)


# ---------------------------------------------------------------------------
# 每日权益领取 / 积分
# ---------------------------------------------------------------------------
@app.post("/api/v1/accounts/{account}/claim")
def claim_daily_bonus(account: str):
    """领取该账号当日的免费算力权益。"""
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    with _client_for(acc) as c:
        ok = c.daily_claim()
        fp = c.free_power()
    today = time.strftime("%Y-%m-%d")
    _store.update(
        account,
        last_claim=today if ok else acc.last_claim,
        free_power=fp.get("freePower"),
    )
    return {"claimed": ok, "checked_in": ok, "free_power": fp.get("freePower"), "status": fp.get("status")}


@app.post("/api/v1/accounts/claim-all")
def claim_all_daily_bonus():
    """为账号池中全部账号领取当日免费算力权益。"""
    results = []
    today = time.strftime("%Y-%m-%d")
    for acc in _store.list():
        if not acc.access_token or acc.status == "disabled":
            continue
        try:
            with _client_for(acc) as c:
                ok = c.daily_claim()
                fp = c.free_power()
            _store.update(
                acc.account,
                last_claim=today if ok else acc.last_claim,
                free_power=fp.get("freePower"),
            )
            results.append({"account": acc.account, "ok": ok, "free_power": fp.get("freePower")})
        except Exception as e:  # noqa: BLE001
            results.append({"account": acc.account, "ok": False, "error": str(e)[:160]})
    # 领取结果摘要通知
    ok_count = sum(1 for r in results if r.get("ok"))
    fail = [r["account"] for r in results if not r.get("ok")]
    _notify(
        EVENT_DAILY_DIGEST,
        f"当日免费算力权益领取：成功 {ok_count}/{len(results)}",
        ("失败账号：" + "、".join(fail[:20])) if fail else "全部账号领取成功。",
        level="warning" if fail else "info",
        dedup_key=f"daily_digest:{today}",
    )
    if fail:
        _notify(
            EVENT_CLAIM_FAILED,
            f"权益领取失败 {len(fail)} 个账号",
            "、".join(fail[:20]),
            level="warning",
            dedup_key=f"claim_failed:{today}",
        )
    return {"results": results, "date": today}


# 兼容旧路径（等价于「权益领取」）
@app.post("/api/v1/accounts/{account}/checkin")
def checkin(account: str):
    """兼容别名：等价于 :func:`claim_daily_bonus`。"""
    return claim_daily_bonus(account)


@app.post("/api/v1/accounts/checkin-all")
def checkin_all():
    """兼容别名：等价于 :func:`claim_all_daily_bonus`。"""
    return claim_all_daily_bonus()


# ---------------------------------------------------------------------------
# 团队与成员（liblib 平台原生无团队功能，这里提供统一纳管层）
# ---------------------------------------------------------------------------
@app.get("/api/v1/teams")
def list_teams():
    """团队列表（含成员、额度概览与绑定账号）。"""
    teams = []
    for t in _teams.list_teams():
        members = [m for m in (_teams.get_member(mid) for mid in t.member_ids) if m]
        accounts = []
        for m in members:
            for acc_id in m.account_ids:
                acc = _store.get(acc_id)
                if acc:
                    accounts.append(_account_view(acc))
        teams.append({
            "id": t.id,
            "name": t.name,
            "note": t.note,
            "member_count": len(members),
            "account_count": len(accounts),
            "members": [m.to_dict() for m in members],
            "accounts": accounts,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        })
    return {"teams": teams, "count": len(teams)}


@app.post("/api/v1/teams")
def create_team(payload: dict = Body(...)):
    """创建团队。"""
    name = (payload or {}).get("name")
    if not name:
        raise HTTPException(400, "缺少 name")
    team = _teams.add_team(name=name, note=(payload or {}).get("note") or "")
    return {"ok": True, "team": team.to_dict()}


@app.patch("/api/v1/teams/{team_id}")
def update_team(team_id: str, payload: dict = Body(...)):
    """更新团队名称 / 备注。"""
    fields = {k: v for k, v in (payload or {}).items() if k in ("name", "note")}
    team = _teams.update_team(team_id, **fields)
    if not team:
        raise HTTPException(404, "团队不存在")
    return {"ok": True, "team": team.to_dict()}


@app.delete("/api/v1/teams/{team_id}")
def delete_team(team_id: str):
    """删除团队（成员一并移除，账号解除归属）。"""
    if not _teams.remove_team(team_id):
        raise HTTPException(404, "团队不存在")
    for acc in _store.list():
        if acc.team_id == team_id:
            _store.update(acc.account, team_id=None, member_id=None)
    return {"ok": True}


@app.get("/api/v1/members")
def list_all_members():
    """全部成员与额度概览。"""
    return {"members": _teams.quota_status(), "count": len(_teams)}


@app.get("/api/v1/teams/{team_id}/members")
def list_team_members(team_id: str):
    """某团队下的成员列表。"""
    if not _teams.get_team(team_id):
        raise HTTPException(404, "团队不存在")
    members = _teams.list_members(team_id)
    return {"members": [m.to_dict() for m in members], "count": len(members)}


@app.post("/api/v1/teams/{team_id}/members")
def add_team_member(team_id: str, payload: dict = Body(...)):
    """在团队下新增成员，可同时设置每日额度上限。"""
    name = (payload or {}).get("name")
    if not name:
        raise HTTPException(400, "缺少 name")
    limit = (payload or {}).get("quota_limit")
    member = _teams.add_member(
        team_id,
        name=name,
        note=(payload or {}).get("note") or "",
        quota_limit=float(limit) if limit is not None else None,
        identity=(payload or {}).get("identity"),
    )
    if not member:
        raise HTTPException(404, "团队不存在")
    return {"ok": True, "member": member.to_dict()}


@app.patch("/api/v1/members/{member_id}")
def update_member(member_id: str, payload: dict = Body(...)):
    """更新成员资料（姓名 / 备注 / 额度上限 / 身份标识）。"""
    fields = {
        k: v for k, v in (payload or {}).items()
        if k in ("name", "note", "quota_limit", "identity")
    }
    if "quota_limit" in fields and fields["quota_limit"] is not None:
        fields["quota_limit"] = float(fields["quota_limit"])
    member = _teams.update_member(member_id, **fields)
    if not member:
        raise HTTPException(404, "成员不存在")
    return {"ok": True, "member": member.to_dict()}


@app.post("/api/v1/members/{member_id}/quota")
def set_member_quota(member_id: str, payload: dict = Body(...)):
    """设置成员每日额度上限（算力点）；传 null 表示不限制。"""
    payload = payload or {}
    member = _teams.get_member(member_id)
    if not member:
        raise HTTPException(404, "成员不存在")
    limit = payload.get("quota_limit")
    if limit is not None:
        limit = float(limit)
        if limit < 0:
            raise HTTPException(400, "quota_limit 不能为负")
    if payload.get("reset_usage"):
        member.quota_used = 0.0
    updated = _teams.update_member(member_id, quota_limit=limit)
    return {"ok": True, "member": updated.to_dict()}


@app.delete("/api/v1/members/{member_id}")
def delete_member(member_id: str):
    """删除成员（其账号解除归属，不删除账号本身）。"""
    member = _teams.get_member(member_id)
    if not member:
        raise HTTPException(404, "成员不存在")
    for acc_id in list(member.account_ids):
        acc = _store.get(acc_id)
        if acc:
            _store.update(acc_id, member_id=None, team_id=None)
    _teams.remove_member(member_id)
    return {"ok": True}


@app.post("/api/v1/accounts/{account}/assign")
def assign_account(account: str, payload: dict = Body(...)):
    """把账号分配给团队成员，并可同时设置备注。

    未显式给出 remark 时，自动填成「<团队>·<成员> 的账号」。
    传 member_id=null 表示解除归属。
    """
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    payload = payload or {}
    member_id = payload.get("member_id")
    remark = payload.get("remark")
    if member_id:
        member = _teams.bind_account(account, member_id)
        if not member:
            raise HTTPException(404, "成员不存在")
        team = _teams.get_team(member.team_id)
        if remark is None:
            remark = f"{team.name if team else '团队'}·{member.name} 的账号"
        _store.update(account, member_id=member.id, team_id=member.team_id, note=remark)
    else:
        _teams.unbind_account(account)
        if remark is not None:
            _store.update(account, note=remark, member_id=None, team_id=None)
        else:
            _store.update(account, member_id=None, team_id=None)
    return {"ok": True, "account": _account_view(_store.get(account))}


@app.post("/api/v1/accounts/{account}/remark")
def set_account_remark(account: str, payload: dict = Body(...)):
    """设置账号备注（如「张三团队成员的账号」）。"""
    acc = _store.get(account)
    if not acc:
        raise HTTPException(404, "账号不存在")
    remark = str((payload or {}).get("remark") or "")
    _store.update(account, note=remark)
    return {"ok": True, "account": _account_view(_store.get(account))}


# ---------------------------------------------------------------------------
# 告警引擎（按规则扫描账号池与成员额度，命中即通知）
# ---------------------------------------------------------------------------
def _rule_enabled(event: str) -> bool:
    rule = _notifier.rules().get(event) or {}
    return bool(rule.get("enabled"))


def _notify(event: str, title: str, body: str, level: str = "info",
            dedup_key: str = "", force: bool = False) -> list:
    """发送一条通知（内部 helper）。"""
    if not force and not _rule_enabled(event):
        return []
    msg = NotifyMessage(
        event=event,
        title=title,
        body=body,
        level=level,
        dedup_key=dedup_key or f"{event}:{title}",
    )
    try:
        return _notifier.send(msg, force=force)
    except Exception as e:  # noqa: BLE001
        log.warning("通知发送异常：%s", e)
        return []


def run_alerts(force: bool = False) -> dict:
    """扫描账号池与成员额度，按规则发出告警。返回本次命中的告警摘要。"""
    rules = _notifier.rules()
    hits: list[dict] = []
    warn_days = int((rules.get(EVENT_MEMBER_EXPIRING) or {}).get("days") or cfg.MEMBER_EXPIRY_WARN_DAYS)
    low_threshold = float((rules.get(EVENT_POINTS_LOW) or {}).get("threshold") or 100)
    near_percent = float((rules.get(EVENT_QUOTA_NEAR_LIMIT) or {}).get("percent") or 90)

    # 1) 会员到期
    for acc in _store.list():
        info = expiry_info(acc.member_until, warn_days=warn_days)
        left = info.get("days_left")
        label = f"{acc.nickname or acc.account}"
        if info.get("expired"):
            hits.append({"event": EVENT_MEMBER_EXPIRED, "account": acc.account,
                         "title": f"会员已到期：{label}"})
        elif left is not None and left <= warn_days:
            hits.append({"event": EVENT_MEMBER_EXPIRING, "account": acc.account,
                         "title": f"会员即将到期（剩 {left} 天）：{label}"})

    # 2) 账号失效
    for acc in _store.list():
        if acc.alive is False:
            hits.append({"event": EVENT_ACCOUNT_INVALID, "account": acc.account,
                         "title": f"账号失效：{acc.nickname or acc.account}"})

    # 3) 算力点余额偏低
    for acc in _store.list():
        pts = acc.points
        if pts is not None and float(pts) < low_threshold:
            hits.append({"event": EVENT_POINTS_LOW, "account": acc.account,
                         "title": f"算力点余额偏低（{pts}）：{acc.nickname or acc.account}"})

    # 4) 成员额度
    for m in _teams.list_members():
        m.rollover()
        if m.quota_unlimited:
            continue
        if m.quota_exhausted():
            hits.append({"event": EVENT_QUOTA_EXHAUSTED, "account": None,
                         "title": f"成员额度已用尽：{m.name}"})
        else:
            pct = float(m.quota_used) / float(m.quota_limit or 1) * 100
            if pct >= near_percent:
                hits.append({"event": EVENT_QUOTA_NEAR_LIMIT, "account": None,
                             "title": f"成员额度接近上限（{pct:.0f}%）：{m.name}"})

    sent = []
    for hit in hits:
        event = hit["event"]
        body = f"账号：{hit['account']}" if hit.get("account") else "团队成员额度"
        level = "critical" if event in (EVENT_MEMBER_EXPIRED, EVENT_ACCOUNT_INVALID,
                                        EVENT_QUOTA_EXHAUSTED) else "warning"
        records = _notify(event, hit["title"], body, level=level, force=force)
        sent.append({**hit, "sent": len(records)})
    return {"checked": len(_store.list()), "hits": sent, "count": len(sent)}


@app.post("/api/v1/alerts/scan")
def api_scan_alerts(payload: dict = Body(default={})):
    """手动触发一次告警扫描。"""
    return run_alerts(force=bool((payload or {}).get("force")))


# ---------------------------------------------------------------------------
# 通知中心（邮件 / 企业微信机器人 / 控制台）
# ---------------------------------------------------------------------------
@app.get("/api/v1/notify/status")
def notify_status():
    """通道状态、告警规则与最近发送记录。"""
    return {
        "channels": _notifier.channel_status(),
        "rules": _notifier.rules(),
        "config": _notifier.config,
        "history": _notifier.history_list(30),
    }


@app.post("/api/v1/notify/config")
def notify_update_config(payload: dict = Body(...)):
    """保存通知通道配置（邮件 SMTP / 企业微信 Webhook / 控制台）。"""
    payload = payload or {}
    cfgd = _notifier.config
    for ch in ("email", "wecom", "console"):
        if isinstance(payload.get(ch), dict):
            merged = dict(cfgd.get(ch) or {})
            merged.update(payload[ch])
            cfgd[ch] = merged
    if isinstance(payload.get("quiet_hours"), dict):
        merged_q = dict(cfgd.get("quiet_hours") or {})
        merged_q.update(payload["quiet_hours"])
        cfgd["quiet_hours"] = merged_q
    _notifier.save_config(cfgd)
    return {"ok": True, "config": cfgd}


@app.post("/api/v1/notify/rule/{event}")
def notify_update_rule(event: str, payload: dict = Body(...)):
    """更新某类告警的规则（启停与阈值）。"""
    rule = _notifier.update_rule(event, payload or {})
    return {"ok": True, "event": event, "rule": rule}


@app.post("/api/v1/notify/test")
def notify_test(payload: dict = Body(default={})):
    """发送测试通知。"""
    channel = (payload or {}).get("channel") or ""
    records = _notifier.test(channel)
    return {"ok": all(r.ok for r in records) if records else False,
            "results": [r.to_dict() for r in records]}


@app.get("/api/v1/notify/history")
def notify_history(limit: int = Query(50, ge=1, le=200)):
    """最近的通知发送记录。"""
    return {"history": _notifier.history_list(limit)}


# ---------------------------------------------------------------------------
# 团队统计（算力点 / 用量 / 排行）
# ---------------------------------------------------------------------------
@app.get("/api/v1/stats")
def api_stats(days: int = Query(cfg.MEMBER_EXPIRY_WARN_DAYS, ge=1, le=365)):
    """团队统计：总览 + 成员维度 + 账号维度。"""
    return team_stats(_store, _teams, warn_days=days)


@app.get("/api/v1/stats/overview")
def api_stats_overview():
    """团队总览指标（轻量）。"""
    return team_stats(_store, _teams, warn_days=cfg.MEMBER_EXPIRY_WARN_DAYS)["overview"]


# ---------------------------------------------------------------------------
# 使用条例与合规声明（首次进入面板需阅读并同意）
# ---------------------------------------------------------------------------
TERMS_VERSION = "1.0"
TERMS_TITLE = "使用条例与合规声明"
TERMS_TEXT = """本工具面向团队自用，用于统一管理团队成员各自合法拥有的 liblib 账号。

一、适用范围
请仅用于你本人与本团队成员已合法拥有的账号；团队账号应来自成员自愿提供并知情的场景。

二、遵守平台规则
请遵守 liblib.tv 及相关平台的服务条款、计费与频控规则，不做滥用、刷量或绕过平台限制的操作。

三、不做逆向与破解
本项目仅调用平台对外提供的正常接口与官方授权流程，不用于绕过平台限制、破解付费能力、
批量注册账号或买卖账号。

四、凭据与隐私
账号令牌仅存储于运行本程序的本机（权限 0600），不外传、不写日志、不上传至第三方；
微信扫码走 OAuth 标准流程，手机号验证码由本人接收，本项目不收集密码。

五、团队数据的边界
平台原生没有团队功能，本项目在官方账号体系之上提供统一管理层（纳管账号、交叉选号、
额度限制、到期提醒），不修改平台任何机制，所有能力仍受账号自身权限与平台规则约束。

六、风险自担
所用接口随官方调整可能变动；因不当使用或账号受限造成的后果，由使用者自行承担。
本项目与 liblib 官方无隶属关系。"""


@app.get("/api/v1/terms")
def get_terms():
    """使用条例状态与全文。"""
    s = _load_settings()
    accepted_at = s.get("terms_accepted_at")
    version = s.get("terms_version")
    accepted = bool(accepted_at) and version == TERMS_VERSION
    return {
        "version": TERMS_VERSION,
        "title": TERMS_TITLE,
        "text": TERMS_TEXT,
        "accepted": accepted,
        "accepted_at": accepted_at,
        "accepted_version": version,
        "need_accept": not accepted,
    }


@app.post("/api/v1/terms/accept")
def accept_terms(payload: dict = Body(default={})):
    """记录使用条例同意状态（写入本机 settings.json）。"""
    s = _load_settings()
    s["terms_accepted_at"] = int(time.time())
    s["terms_version"] = TERMS_VERSION
    _save_settings(s)
    return {"ok": True, "version": TERMS_VERSION, "accepted_at": s["terms_accepted_at"]}


@app.get("/api/v1/points")
def get_points(account: Optional[str] = Query(None)):
    acc = _pick_account(account)
    with _client_for(acc) as c:
        member = c.member_account()
        fp = c.free_power()
    return {
        "account": acc.account,
        "account_type": acc.account_type,
        "member_name": member.get("name"),
        "account_level": member.get("accountLevel"),
        "effective": member.get("effective"),
        "has_get_power": member.get("hasGetPower"),
        "free_power": fp.get("freePower"),
        "free_power_status": fp.get("status"),
        "free_power_expire_at": fp.get("expireAt"),
    }


# ---------------------------------------------------------------------------
# 登录（手机号 / 微信扫码）
# ---------------------------------------------------------------------------
@app.post("/api/v1/auth/phone/send-code")
def phone_send_code(payload: dict = Body(...)):
    phone = (payload or {}).get("phone")
    proxy = (payload or {}).get("proxy")
    if not phone:
        raise HTTPException(400, "缺少 phone")
    from liblib2api.auth.phone import PhoneLogin

    try:
        p = PhoneLogin(proxy=proxy)
        res = p.send_code(phone)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"发送验证码失败：{e}")
    return {"phone": phone, "result": res}


@app.post("/api/v1/auth/phone/login")
def phone_login(payload: dict = Body(...)):
    phone = (payload or {}).get("phone")
    code = (payload or {}).get("code")
    proxy = (payload or {}).get("proxy")
    note = (payload or {}).get("note", "")
    if not phone or not code:
        raise HTTPException(400, "缺少 phone 或 code")
    from liblib2api.auth.phone import PhoneLogin

    try:
        p = PhoneLogin(proxy=proxy)
        creds = p.login(phone, code)
        info = p.user_info()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"登录失败：{e}")

    acc = Account(
        account=phone,
        access_token=creds.access_token,
        login_method="phone",
        webid=creds.extra.get("webid"),
        nickname=info.get("nickname") or creds.extra.get("nickname"),
        user_id=str(info.get("id")) if info.get("id") else None,
        uuid=info.get("uuid"),
        proxy=proxy,
        note=note,
    )
    _store.add(acc)
    try:
        _sync_account(acc)  # 登录后立即识别类型 + 模型可用性
    except (ApiError, AuthError) as e:
        log.warning("登录后同步失败：%s", e)
    return {"account": _account_view(acc)}


@app.get("/api/v1/auth/wechat/authorize")
def wechat_authorize(open_browser: bool = Query(False)):
    """生成微信扫码授权链接 + state。

    回调地址指向本面板的 /api/v1/auth/wechat/callback（而非 CLI 默认端口），
    这样用户扫码授权后，授权码会被本面板接收并完成登录。
    """
    from liblib2api.auth.wechat import WechatLoginFlow

    redirect_uri = f"{cfg.SERVER_PUBLIC_URL.rstrip('/')}/api/v1/auth/wechat/callback"
    try:
        flow = WechatLoginFlow(redirect_uri=redirect_uri)
        state, url = flow.begin(open_browser=open_browser)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"获取微信授权链接失败：{e}")
    _PENDING_WECHAT[state] = {"flow": flow, "url": url, "done": False, "error": None, "account": None}
    return {"state": state, "authorize_url": url}


@app.get("/api/v1/auth/wechat/callback")
def wechat_callback(code: str = Query(...), state: str = Query(...)):
    """微信 OAuth 回调：携带授权码回来，换取凭据并登记账号。"""
    item = _PENDING_WECHAT.get(state)
    if not item:
        return HTMLResponse("<h3>授权失败：state 不存在或已过期，请重新在面板发起扫码。</h3>", status_code=400)
    flow = item["flow"]
    try:
        creds = flow.finish(code, state)
    except Exception as e:  # noqa: BLE001
        item["error"] = str(e)
        return HTMLResponse(f"<h3>授权处理失败：{e}</h3>", status_code=400)
    acc = Account(
        account=creds.account or "wechat",
        access_token=creds.access_token,
        login_method="wechat",
        webid=creds.extra.get("webid"),
        nickname=creds.extra.get("nickname"),
        proxy=creds.extra.get("proxy"),
    )
    _store.add(acc)
    try:
        _sync_account(acc)
    except (ApiError, AuthError) as e:
        log.warning("微信登录后同步失败：%s", e)
    item["done"] = True
    item["account"] = _account_view(acc)
    return HTMLResponse("<h3>✅ LibTV 微信授权成功！可关闭此页面返回面板。</h3>")


@app.get("/api/v1/auth/wechat/poll")
def wechat_poll(state: str = Query(...)):
    """轮询扫码结果：pending / ok / error。"""
    item = _PENDING_WECHAT.get(state)
    if not item:
        raise HTTPException(404, "state 不存在或已过期，请重新获取授权链接")
    if item.get("error"):
        raise HTTPException(400, item["error"])
    if item.get("done"):
        return {"status": "ok", "account": item.get("account")}
    return {"status": "pending"}


@app.get("/api/v1/auth/wechat/qr")
def wechat_qr(state: str = Query(...)):
    """把微信授权链接渲染成二维码 PNG（data URI），供面板图形化展示。"""
    item = _PENDING_WECHAT.get(state)
    if not item:
        raise HTTPException(404, "state 不存在或已过期，请重新获取授权链接")
    url = item.get("url")
    if not url:
        raise HTTPException(400, "该 state 没有可用的授权链接")
    try:
        img = qrcode.make(url, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"二维码生成失败：{e}")
    return {
        "state": state,
        "qr_png": f"data:image/png;base64,{b64}",
        "authorize_url": url,
    }


# ---------------------------------------------------------------------------
# 管理员登录（单管理员：用户名/密码）
# ---------------------------------------------------------------------------
@app.post("/api/v1/admin/login")
def admin_login(payload: dict = Body(...)):
    user = (payload or {}).get("username")
    pw = (payload or {}).get("password")
    if not user or not pw:
        raise HTTPException(400, "缺少 username / password")
    if user != _admin_user or not (_admin_pass_hash and srv_auth.verify_password(pw, _admin_pass_hash)):
        raise HTTPException(401, "用户名或密码错误")
    token = srv_auth.make_token(_admin_user)
    needs = _load_settings().get("admin_needs_change", False)
    return {"token": token, "user": _admin_user, "needs_change": needs}


@app.post("/api/v1/admin/password")
def admin_change_password(payload: dict = Body(...)):
    global _admin_pass_hash
    old = (payload or {}).get("old_password")
    new = (payload or {}).get("new_password")
    if not old or not new:
        raise HTTPException(400, "缺少 old_password / new_password")
    if not (_admin_pass_hash and srv_auth.verify_password(old, _admin_pass_hash)):
        raise HTTPException(400, "旧密码错误")
    s = _load_settings()
    s["admin_pass_hash"] = srv_auth.hash_password(new)
    s["admin_needs_change"] = False
    _save_settings(s)
    _admin_pass_hash = s["admin_pass_hash"]
    return {"ok": True, "message": "密码已修改，请重新登录"}


@app.get("/api/v1/admin/apikey")
def admin_apikey():
    """返回当前对外 API Key（仅管理员可见）。"""
    return {"api_key": _api_key, "hint": "调用 /api/v1/* 时通过 Authorization: Bearer / X-Api-Key / ?api_key= 携带"}


# ---------------------------------------------------------------------------
# 监控
# ---------------------------------------------------------------------------
@app.get("/api/v1/monitor/status")
def monitor_status():
    return _monitor.status()


@app.post("/api/v1/monitor/check")
def monitor_check():
    results = _monitor.check_all()
    # 巡检后按规则扫描并发出告警（会员到期 / 账号失效 / 算力点偏低 / 额度超限）
    try:
        alerts = run_alerts()
    except Exception as e:  # noqa: BLE001
        alerts = {"count": 0, "hits": [], "error": str(e)}
    # 权益领取失败的账号单独提醒
    failed = [r.account for r in results if not r.ok]
    if failed:
        _notify(
            EVENT_CLAIM_FAILED,
            f"账号巡检异常 {len(failed)} 个",
            "、".join(failed[:20]),
            level="warning",
        )
    return {
        "checked_at": _monitor.last_run_at,
        "alerts": alerts,
        "results": [
            {
                "account": r.account,
                "ok": r.ok,
                "account_type": r.account_type,
                "points": r.points,
                "free_power": r.free_power,
                "checked_in": r.checked_in,
                "error": r.error,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# 设置（OpenAI 兼容 API / 每积分消耗 / 监控间隔）
# ---------------------------------------------------------------------------
@app.get("/api/v1/settings")
def get_settings():
    s = _load_settings()
    api_key = _api_key or s.get("api_key") or ""
    masked = (api_key[:7] + "****" + api_key[-4:]) if len(api_key) > 11 else (api_key or "未设置")
    return {
        "openai_base_url": s.get("openai_base_url", cfg.OPENAI_COMPATIBLE_BASE_URL),
        "openai_model": s.get("openai_model", cfg.OPENAI_COMPATIBLE_MODEL),
        "openai_configured": bool(s.get("openai_api_key")),
        "points_per_second": s.get("points_per_second", cfg.POINTS_PER_SECOND),
        "monitor_interval": s.get("monitor_interval", _monitor.interval),
        "admin_user": _admin_user,
        "admin_needs_change": s.get("admin_needs_change", False),
        "api_key_masked": masked,
        "api_key_set": bool(api_key),
    }


@app.post("/api/v1/settings")
def update_settings(payload: dict = Body(...)):
    s = _load_settings()
    for k in ("openai_base_url", "openai_api_key", "openai_model", "points_per_second", "monitor_interval"):
        if k in payload and payload[k] is not None:
            s[k] = payload[k]
    # 显式重设对外 API Key（或清空后由下次启动重新生成）
    if "api_key" in payload and payload["api_key"]:
        s["api_key"] = payload["api_key"]
        global _api_key
        _api_key = s["api_key"]
    if payload.get("regenerate_api_key"):
        s["api_key"] = srv_auth.new_api_key()
        _api_key = s["api_key"]
    _save_settings(s)
    # 若设置了监控间隔，立即对下一次巡检生效
    if s.get("monitor_interval"):
        try:
            _monitor.interval = int(s["monitor_interval"])
        except (TypeError, ValueError):
            pass
    return {
        "ok": True,
        "openai_configured": bool(s.get("openai_api_key")),
        "points_per_second": s.get("points_per_second", cfg.POINTS_PER_SECOND),
        "monitor_interval": _monitor.interval,
        "api_key": _api_key,
    }


# ---------------------------------------------------------------------------
# 生成（对外开放接口）
# ---------------------------------------------------------------------------
def _extract_prompt(p: dict) -> Optional[str]:
    """兼容多种写法：prompt / text / input / q / content / messages[].content。"""
    for k in ("prompt", "text", "input", "prompt_text", "q", "content"):
        if p.get(k):
            return str(p[k])
    msgs = p.get("messages")
    if isinstance(msgs, list):
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("content"):
                return str(m["content"])
    return None


def _adapt_generate_payload(p: dict, kind: str) -> dict:
    """把多兼容格式的请求体归一化为本项目内部字段。

    兼容：
      - prompt 别名：text / input / q / content / messages
      - model 别名：model_key / model_name / model_id
      - account 别名：account_id / account_name
      - 图片 size "1024x1024" → width/height；n → count
      - 视频 seconds 别名 → duration
    """
    p = dict(p or {})
    out = dict(p)
    prompt = _extract_prompt(p)
    if prompt is not None:
        out["prompt"] = prompt
    for src, dst in (
        ("model_key", "model"),
        ("model_name", "model"),
        ("model_id", "model"),
        ("account_id", "account"),
        ("account_name", "account"),
    ):
        if p.get(src):
            out[dst] = p[src]
    if kind == "image" and p.get("size"):
        m = re.match(r"(\d+)[xX](\d+)", str(p["size"]))
        if m:
            out["width"] = int(m.group(1))
            out["height"] = int(m.group(2))
    if p.get("n"):
        try:
            out["count"] = int(p["n"])
        except (TypeError, ValueError):
            pass
    if kind == "video" and p.get("seconds"):
        try:
            out["duration"] = int(p["seconds"])
        except (TypeError, ValueError):
            pass
    return out


def _scan_model_constraints(cfg_raw: Any) -> dict:
    """从模型的 baseConfig 中尽力提取动态约束（不同模型字段差异大，best-effort）。"""
    if isinstance(cfg_raw, str):
        try:
            cfg_raw = _json.loads(cfg_raw)
        except Exception:  # noqa: BLE001
            return {}
    if not isinstance(cfg_raw, dict):
        return {}
    flat: dict = {}

    def walk(d, pre=""):
        if isinstance(d, dict):
            for k, v in d.items():
                walk(v, (pre + "." + str(k)).lower() if pre else str(k).lower())
        elif isinstance(d, list):
            for i in d:
                walk(i, pre)
        else:
            flat[pre] = d

    walk(cfg_raw)
    out: dict = {}
    for k, v in flat.items():
        if isinstance(v, (int, float)) and any(x in k for x in ("maxduration", "maxsecond")):
            out["max_segment_seconds"] = max(int(out.get("max_segment_seconds", 0)), int(v))
        if "durations" in k or "durationlist" in k or "supportduration" in k:
            if isinstance(v, list):
                nums = [int(x) for x in v if str(x).isdigit()]
                if nums:
                    out["allowed_durations"] = nums
        if isinstance(v, (int, float)) and any(
            x in k for x in ("powerpersecond", "pointspersecond", "costpersecond", "pricepersecond")
        ):
            out["points_per_second"] = float(v)
    return out


def _resolve_video_constraints(model_key: Optional[str]) -> dict:
    """给定视频模型，从账号池里任一账号的模型清单中解析其动态约束。"""
    if not model_key:
        return {}
    for acc in _store.list():
        if not acc.access_token:
            continue
        try:
            with _client_for(acc) as c:
                snap = c.compute_model_usability()
        except Exception:  # noqa: BLE001
            continue
        for m in snap.get("models", {}).get("video", []):
            key = m.get("model_key") or m.get("name")
            if key != model_key:
                continue
            return _scan_model_constraints(m.get("config"))
    return {}


@app.post("/api/v1/generate/image")
def generate_image(payload: dict = Body(...)):
    """提交图片生成任务（交叉选号 + 真正调用 MCP 图片工具）。

    设置 dry_run=true 可只做选号+参数校验不真正消耗。
    """
    payload = _adapt_generate_payload(payload, "image")
    account = payload.get("account")
    if account:
        acc = _store.get(account)
        if not acc:
            raise HTTPException(404, f"账号不存在：{account}")
        reason = "指定账号"
    else:
        acc, reason = _selector.select_for_model(payload.get("model"), strategy=payload.get("strategy", "balanced"))
        if not acc:
            raise HTTPException(400, reason)
    prompt = payload.get("prompt")
    if not prompt:
        raise HTTPException(400, "缺少 prompt")
    model = payload.get("model")
    if model and not acc.can_use(model):
        raise HTTPException(
            400, f"账号 {acc.account}（{_type_label(acc.account_type)}）无法使用该图片模型（会员限制）。"
        )
    try:
        req = ImageGenerateRequest(
            **{k: v for k, v in payload.items() if k in ImageGenerateRequest.__dataclass_fields__}
        )
    except TypeError as e:
        raise HTTPException(400, f"参数错误：{e}")
    errs = req.validate()
    if errs:
        raise HTTPException(400, "；".join(errs))

    model_key = req.model
    args = build_image_arguments(req, model_key=model_key)

    dry_run = bool(payload.get("dry_run"))
    if dry_run:
        return {
            "account": acc.account,
            "selection_reason": reason,
            "account_type": acc.account_type,
            "model_key": model_key,
            "arguments": args,
            "dry_run": True,
        }

    acc.record_usage()
    _store.update(acc.account, last_used_at=acc.last_used_at)
    _record_quota_usage(acc.account, cfg.IMAGE_POINTS_ESTIMATE)

    tool = payload.get("tool") or _find_tool(acc.to_credentials(), "image")
    if not tool:
        raise HTTPException(
            424,
            "未能自动发现图片生成 MCP 工具。请先用 GET /api/v1/tools?kind=image 查看可用工具，"
            "并通过 payload.tool 显式指定工具名。",
        )
    try:
        from liblib2api.client import LiblibClient

        client = LiblibClient(store=None, credentials=acc.to_credentials())
        raw = client.call_tool(tool, args)
    except ModelUnavailableError:
        acc.mark_model_usable(model_key or "", False)
        _store.update(acc.account, model_usable=acc.model_usable)
        raise HTTPException(403, "该模型对当前账号不可用（会员限制），已记入可用性缓存。")
    except (ApiError, AuthError) as e:
        acc.record_error()
        _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
        raise HTTPException(502, f"生成调用失败：{e}")
    except Exception as e:  # noqa: BLE001
        acc.record_error()
        _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
        raise HTTPException(502, f"生成调用异常：{e}")

    result = normalize_media(raw, req, acc.account, media_type="image")
    return {
        "account": acc.account,
        "selection_reason": reason,
        "tool": tool,
        "result": result.to_dict(),
    }


@app.post("/api/v1/generate/video")
def generate_video(payload: dict = Body(...)):
    """提交视频生成任务（重点：支持多种格式输出）。

    请求示例：
      {
        "prompt": "一只猫在星空下奔跑",
        "model": "star-video2.5",        # 可选，缺省由选择器挑默认视频模型
        "duration": 10,                  # 5/10/15/30 秒
        "resolution": "1080p",           # 480p/720p/1080p/2k/4k
        "format": "mp4",                 # mp4/webm/mov/gif
        "fps": 30,
        "aspect_ratio": "16:9",
        "account": null,                 # 缺省交叉选号
        "strategy": "balanced",
        "references": [],                # 参考图/视频/音频
        "dry_run": false                 # true 仅校验+选号+展示参数，不真正消耗
      }

    说明：bridge 网关有 WAF，实际生成走 MCP 视频工具（call_tool）。
    若未指定 tool，会自动从工具列表探测一个视频生成工具；探测/调用失败会返回清晰错误。
    """
    payload = _adapt_generate_payload(payload, "video")
    try:
        req = VideoGenerateRequest(
            **{k: v for k, v in payload.items() if k in VideoGenerateRequest.__dataclass_fields__}
        )
    except TypeError as e:
        raise HTTPException(400, f"参数错误：{e}")
    errs = req.validate()
    if errs:
        raise HTTPException(400, "；".join(errs))

    # 交叉选号
    if req.account:
        acc = _store.get(req.account)
        if not acc:
            raise HTTPException(404, f"账号不存在：{req.account}")
        reason = "指定账号"
    else:
        acc, reason = _selector.select_for_model(req.model, strategy=req.strategy)
        if not acc:
            raise HTTPException(400, reason)
    if req.model and not acc.can_use(req.model):
        raise HTTPException(
            400,
            f"账号 {acc.account}（{acc.account_type}）无法使用该视频模型（会员限制）。"
            f"请指定会员账号或换用免费可用模型。",
        )

    model_key = req.model
    args = build_arguments(req, model_key=model_key)

    dry_run = bool(payload.get("dry_run"))
    if dry_run:
        return {
            "account": acc.account,
            "selection_reason": reason,
            "account_type": acc.account_type,
            "model_key": model_key,
            "arguments": args,
            "dry_run": True,
            "message": "dry_run：未真正发起生成，仅展示将发送给 MCP 的参数。",
        }

    acc.record_usage()
    _store.update(acc.account, last_used_at=acc.last_used_at)
    _record_quota_usage(acc.account, (req.duration or 0) * _current_pps())

    from liblib2api.client import LiblibClient

    tool_name = payload.get("tool") or _find_video_tool(acc.to_credentials())
    if not tool_name:
        raise HTTPException(
            424,
            "未能自动发现视频生成 MCP 工具。请先用 GET /api/v1/mcp/tools 查看可用工具，"
            "并通过 payload.tool 显式指定工具名。",
        )
    try:
        client = LiblibClient(store=None, credentials=acc.to_credentials())
        raw = client.call_tool(tool_name, args)
    except ModelUnavailableError:
        acc.mark_model_usable(model_key or "", False)
        _store.update(acc.account, model_usable=acc.model_usable)
        raise HTTPException(403, "该模型对当前账号不可用（会员限制），已记入可用性缓存。")
    except (ApiError, AuthError) as e:
        acc.record_error()
        _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
        raise HTTPException(502, f"生成调用失败：{e}")
    except Exception as e:  # noqa: BLE001
        acc.record_error()
        _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
        raise HTTPException(502, f"生成调用异常：{e}")

    result = normalize_result(raw, req, acc.account)
    return {
        "account": acc.account,
        "selection_reason": reason,
        "tool": tool_name,
        "result": result.to_dict(),
    }


@app.post("/api/v1/generate/audio")
def generate_audio(payload: dict = Body(...)):
    """提交音频生成任务（交叉选号 + 真正调用 MCP 音频工具）。

    设置 dry_run=true 可只做选号+参数校验不真正消耗。
    """
    payload = _adapt_generate_payload(payload, "audio")
    account = payload.get("account")
    if account:
        acc = _store.get(account)
        if not acc:
            raise HTTPException(404, f"账号不存在：{account}")
        reason = "指定账号"
    else:
        acc, reason = _selector.select_for_model(payload.get("model"), strategy=payload.get("strategy", "balanced"))
        if not acc:
            raise HTTPException(400, reason)
    prompt = payload.get("prompt")
    if not prompt:
        raise HTTPException(400, "缺少 prompt")
    model = payload.get("model")
    if model and not acc.can_use(model):
        raise HTTPException(
            400, f"账号 {acc.account}（{_type_label(acc.account_type)}）无法使用该音频模型（会员限制）。"
        )
    try:
        req = AudioGenerateRequest(
            **{k: v for k, v in payload.items() if k in AudioGenerateRequest.__dataclass_fields__}
        )
    except TypeError as e:
        raise HTTPException(400, f"参数错误：{e}")
    errs = req.validate()
    if errs:
        raise HTTPException(400, "；".join(errs))

    model_key = req.model
    args = build_audio_arguments(req, model_key=model_key)

    dry_run = bool(payload.get("dry_run"))
    if dry_run:
        return {
            "account": acc.account,
            "selection_reason": reason,
            "account_type": acc.account_type,
            "model_key": model_key,
            "arguments": args,
            "dry_run": True,
        }

    acc.record_usage()
    _store.update(acc.account, last_used_at=acc.last_used_at)
    _record_quota_usage(acc.account, (req.duration or 0) * _current_pps())

    tool = payload.get("tool") or _find_tool(acc.to_credentials(), "audio")
    if not tool:
        raise HTTPException(
            424,
            "未能自动发现音频生成 MCP 工具。请先用 GET /api/v1/tools?kind=audio 查看可用工具，"
            "并通过 payload.tool 显式指定工具名。",
        )
    try:
        from liblib2api.client import LiblibClient

        client = LiblibClient(store=None, credentials=acc.to_credentials())
        raw = client.call_tool(tool, args)
    except ModelUnavailableError:
        acc.mark_model_usable(model_key or "", False)
        _store.update(acc.account, model_usable=acc.model_usable)
        raise HTTPException(403, "该模型对当前账号不可用（会员限制），已记入可用性缓存。")
    except (ApiError, AuthError) as e:
        acc.record_error()
        _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
        raise HTTPException(502, f"生成调用失败：{e}")
    except Exception as e:  # noqa: BLE001
        acc.record_error()
        _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
        raise HTTPException(502, f"生成调用异常：{e}")

    result = normalize_media(raw, req, acc.account, media_type="audio")
    return {
        "account": acc.account,
        "selection_reason": reason,
        "tool": tool,
        "result": result.to_dict(),
    }


@app.get("/api/v1/tools")
def list_tools_kind(
    kind: str = Query("video", description="video | image | audio"),
    account: Optional[str] = Query(None, description="指定账号，留空则交叉选号"),
):
    """按媒体类型列出可用 MCP 工具，并推荐一个默认工具。"""
    acc = _pick_account(account)
    from liblib2api.client import LiblibClient

    try:
        client = LiblibClient(store=None, credentials=acc.to_credentials())
        tools = client.list_tools()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"获取工具列表失败：{e}")
    tagged = [t for t in tools if _tool_matches(t, kind)]
    recommended = _find_tool(acc.to_credentials(), kind)
    return {
        "account": acc.account,
        "kind": kind,
        "recommended_tool": recommended,
        "count": len(tagged),
        "tools": tagged,
    }


# ---------------------------------------------------------------------------
# 视频拆分生成（多账号接力）
# ---------------------------------------------------------------------------
@app.post("/api/v1/generate/video/balance")
def generate_video_balance(payload: dict = Body(...)):
    """算力均摊：仅当**没有任何单个账号能独立生成完整时长**时才分段接力。

    请求示例：
      {
        "prompt": "一只猫在星空下奔跑，镜头从特写拉到全景",
        "duration": 15,                 # 总时长（秒）
        "model": "star-video2.5",       # 可选
        "resolution": "720p",
        "format": "mp4",
        "fps": 30,
        "aspect_ratio": "16:9",
        "points_per_second": 10,        # 可选，覆盖默认每积分消耗
        "dry_run": false,               # true 仅规划+分配，不真正生成
        "tool": null                    # 可选，显式指定视频工具
      }

    行为：
      - 若存在单个账号算力点足以覆盖总时长 → strategy="single"，由该账号一次生成，
        不做分段与拼接；
      - 否则 → strategy="balance"，进入分段接力：先规划分段（可由 OpenAI 兼容 API 规划，
        否则确定性均分），再按各账号剩余算力点为每段贪心分配账号。
    动态约束：若指定 model，会自动读取该模型的真实配置（单段最长时长、允许的时长档位、
    每积分消耗），据此规划，避免不同模型「配置不同」导致分段不合规范。
    返回每个分段的生成结果（url），可在本地用 ffmpeg 拼接。
    """
    payload = _adapt_generate_payload(payload, "video")
    prompt = payload.get("prompt")
    if not prompt:
        raise HTTPException(400, "缺少 prompt")
    total = int(payload.get("duration") or 15)
    if total <= 0 or total > 120:
        raise HTTPException(400, "duration 需为 1~120 的整数（秒）")

    settings = _load_settings()
    pps = float(
        payload.get("points_per_second")
        or settings.get("points_per_second")
        or cfg.POINTS_PER_SECOND
    )

    # 动态约束：按模型真实配置覆盖 max_segment / allowed_durations / pps
    constraints = _resolve_video_constraints(payload.get("model"))
    if constraints.get("points_per_second"):
        pps = constraints["points_per_second"]

    accts = [
        {"account": a.account, "points": (a.points or 0) + (a.free_power or 0)}
        for a in _store.list()
        if a.status == "active" and a.access_token
    ]
    if not accts:
        raise HTTPException(400, "账号池为空，请先添加并登录账号")

    # ---- 关键判定：是否有单个账号能独立覆盖总时长 ----
    single_ok, single_acc = single_account_feasible(accts, total, pps)
    if single_ok:
        strategy = "single"
        note = (
            f"账号 {single_acc['account']} 算力点可独立覆盖 {total} 秒，"
            "无需均摊，直接由该账号生成"
        )
    else:
        strategy = "balance"
        note = "没有账号能独立覆盖完整时长，启用算力均摊（分段接力生成）"

    # 构建 OpenAI 兼容客户端（未配置则不走 LLM，回退均分）
    llm_client = None
    if settings.get("openai_api_key"):
        llm_client = OpenAICompatibleClient(
            base_url=settings.get("openai_base_url", cfg.OPENAI_COMPATIBLE_BASE_URL),
            api_key=settings.get("openai_api_key"),
            model=settings.get("openai_model", cfg.OPENAI_COMPATIBLE_MODEL),
        )
    planner = VideoSplitPlanner(llm_client)

    plan = planner.plan(prompt, total, accts, pps, constraints=constraints)
    plan_segments, assign_err = assign_accounts(plan, accts, pps)

    if bool(payload.get("dry_run")):
        return {
            "ok": assign_err is None,
            "dry_run": True,
            "strategy": strategy,
            "note": note,
            "single_account": single_acc["account"] if single_ok else None,
            "points_per_second": pps,
            "constraints": constraints,
            "openai_enabled": llm_client is not None,
            "assign_error": assign_err,
            "plan": plan.to_dict(),
            "accounts": [{"account": a["account"], "points": a["points"]} for a in accts],
        }

    model = payload.get("model")
    results = []
    for seg in plan_segments:
        if not seg.account:
            results.append({"seconds": seg.seconds, "account": None,
                            "error": "无算力点足够的账号可承接该段"})
            continue
        acc = _store.get(seg.account)
        if not acc:
            results.append({"seconds": seg.seconds, "account": seg.account, "error": "账号不存在"})
            continue
        tool = payload.get("tool") or _find_tool(acc.to_credentials(), "video")
        if not tool:
            results.append({"seconds": seg.seconds, "account": seg.account,
                            "error": "未能发现视频生成工具"})
            continue
        vreq = VideoGenerateRequest(
            prompt=seg.prompt or prompt,
            model=model,
            duration=seg.seconds,
            resolution=payload.get("resolution", "720p"),
            fmt=payload.get("format", "mp4"),
            fps=int(payload.get("fps", 30)),
            aspect_ratio=payload.get("aspect_ratio"),
            account=seg.account,
            strategy="balanced",
        )
        errs = vreq.validate(allow_any_duration=True)
        if errs:
            results.append({"seconds": seg.seconds, "account": seg.account,
                            "error": "；".join(errs)})
            continue
        args = build_arguments(vreq, model_key=model)
        try:
            from liblib2api.client import LiblibClient

            client = LiblibClient(store=None, credentials=acc.to_credentials())
            raw = client.call_tool(tool, args)
        except (ApiError, AuthError) as e:
            acc.record_error()
            _store.update(acc.account, error_count=acc.error_count, last_error_at=acc.last_error_at)
            results.append({"seconds": seg.seconds, "account": seg.account,
                            "error": f"生成调用失败：{e}"})
            continue
        except Exception as e:  # noqa: BLE001
            results.append({"seconds": seg.seconds, "account": seg.account,
                            "error": f"生成调用异常：{e}"})
            continue
        res = normalize_result(raw, vreq, acc.account)
        seg.tool = tool
        seg.result = res.to_dict()
        acc.record_usage()
        _store.update(acc.account, last_used_at=acc.last_used_at)
        # 成员额度记账（按本段时长估算消耗）
        _record_quota_usage(acc.account, seg.seconds * pps)
        results.append({
            "seconds": seg.seconds,
            "account": seg.account,
            "tool": tool,
            "result": res.to_dict(),
        })

    return {
        "ok": all(r.get("error") is None for r in results),
        "strategy": strategy,
        "note": note,
        "single_account": single_acc["account"] if single_ok else None,
        "points_per_second": pps,
        "openai_enabled": llm_client is not None,
        "assign_error": assign_err,
        "plan": plan.to_dict(),
        "segments": results,
        "ffmpeg_hint": "本地拼接：ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp4",
    }


# 兼容旧路径（等价于「算力均摊」）
@app.post("/api/v1/generate/video/split")
def generate_video_split(payload: dict = Body(...)):
    """兼容别名：等价于 :func:`generate_video_balance`。"""
    return generate_video_balance(payload)


@app.get("/api/v1/mcp/tools")
def mcp_tools(account: Optional[str] = Query(None)):
    from liblib2api.client import LiblibClient

    acc = _pick_account(account)
    try:
        client = LiblibClient(store=None, credentials=acc.to_credentials())
        tools = client.list_tools()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"获取工具列表失败：{e}")
    return {"account": acc.account, "count": len(tools), "tools": tools}


# ---------------------------------------------------------------------------
# 面板前端
# ---------------------------------------------------------------------------
PANEL_HTML = Path(__file__).parent / "panel.html"


@app.get("/panel", response_class=HTMLResponse)
def panel():
    if PANEL_HTML.exists():
        return PANEL_HTML.read_text(encoding="utf-8")
    return "<h1>LibTV-Team 面板</h1><p>panel.html 未找到</p>"


@app.get("/", response_class=HTMLResponse)
def index():
    # 优先返回构建版前端（Vue SPA）；未构建时退回旧的面板页。
    if _WEBUI_DIST is not None:
        try:
            return HTMLResponse((_WEBUI_DIST / "index.html").read_text(encoding="utf-8"))
        except OSError:  # noqa: BLE001
            pass
    return HTMLResponse(
        '<meta charset="utf-8"><meta http-equiv="refresh" content="0; url=/panel">'
        "<p>跳转到 <a href='/panel'>/panel</a></p>"
    )


if _WEBUI_DIST is not None:
    _WEBUI_ASSETS = _WEBUI_DIST / "assets"
    if _WEBUI_ASSETS.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_WEBUI_ASSETS), html=False),
            name="webui_assets",
        )

"""FastAPI 服务：把 LibTV 登录与能力以 HTTP API 暴露给自动化工作流。

启动：  python -m liblib2api.cli serve --port 8000
或：     uvicorn liblib2api.server:app --port 8000

设计目标：你的自动化系统（n8n / 自研调度 / 脚本）只需打这些 HTTP 接口即可：
  - 先登录一次（手机或微信），凭据落地 ~/.libtv/credentials.json
  - 之后所有创作能力走 POST /mcp（透传任意 MCP 工具调用）
  - 可选 Access Key 时，POST /openapi 透传 REST

鉴权：服务本身无独立账号体系，依赖本机凭据文件；请仅在可信网络/本机暴露。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import liblib2api.config as cfg
from liblib2api.auth.phone import PhoneLogin
from liblib2api.auth.wechat import WechatLoginFlow
from liblib2api.client import LiblibClient
from liblib2api.credentials import CredentialStore
from liblib2api.exceptions import LiblibError

app = FastAPI(title="Liblib2API", version="0.1.0")

# 模块级单例
_store = CredentialStore()
_wechat_flow = WechatLoginFlow(
    redirect_uri=f"{cfg.SERVER_PUBLIC_URL.rstrip('/')}/auth/wechat/callback"
)
_client = LiblibClient(store=_store)


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------
class PhoneSendReq(BaseModel):
    phone: str
    extra: Optional[dict] = None


class PhoneLoginReq(BaseModel):
    phone: str
    code: str
    extra: Optional[dict] = None


class McpReq(BaseModel):
    method: str
    params: Optional[dict] = None
    # 也可直接传完整 JSON-RPC（含 jsonrpc/id）
    jsonrpc: Optional[str] = None
    id: Optional[Any] = None


class OpenApiReq(BaseModel):
    path: str
    method: str = "POST"
    body: Optional[dict] = None


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "logged_in": _store.logged_in}


@app.get("/me")
def me():
    try:
        return _client.whoami()
    except LiblibError as e:
        return JSONResponse(status_code=401, content={"error": str(e)})


# ---------------------------------------------------------------------------
# 手机号登录
# ---------------------------------------------------------------------------
@app.post("/auth/phone/send-code")
def phone_send_code(req: PhoneSendReq):
    try:
        login = PhoneLogin(store=_store)
        resp = login.send_code(req.phone, req.extra)
        return {"ok": True, "server_response": resp}
    except LiblibError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/auth/phone/login")
def phone_login(req: PhoneLoginReq):
    try:
        login = PhoneLogin(store=_store)
        creds = login.login(req.phone, req.code, req.extra)
        return {"ok": True, "login_method": creds.login_method, "account": creds.account}
    except LiblibError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ---------------------------------------------------------------------------
# 微信扫码登录
# ---------------------------------------------------------------------------
@app.get("/auth/wechat/login")
def wechat_login(open_browser: bool = Query(False)):
    try:
        state, auth_url = _wechat_flow.begin(open_browser=open_browser)
    except LiblibError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {
        "state": state,
        "auth_url": auth_url,
        "hint": "请用微信扫码打开 auth_url 完成授权；浏览器会被重定向到本服务的 "
        "/auth/wechat/callback，随后用 GET /auth/wechat/status?state=... 轮询结果。",
    }


@app.get("/auth/wechat/callback")
def wechat_callback(code: str = Query(...), state: str = Query(...)):
    try:
        creds = _wechat_flow.finish(code, state)
        _store.save(creds)
    except LiblibError as e:
        return HTMLResponse(
            f"<h3>授权失败：{e}</h3>", status_code=400
        )
    return HTMLResponse("<h3>✅ LibTV 授权成功！可关闭此页面。</h3>")


@app.get("/auth/wechat/status")
def wechat_status(state: str = Query(...)):
    pend = _wechat_flow._pending.get(state)  # noqa: SLF001
    if pend is None:
        return JSONResponse(status_code=404, content={"status": "unknown_state"})
    if pend.get("error"):
        return {"status": "error", "error": pend["error"]}
    if pend.get("done"):
        return {"status": "done"}
    return {"status": "pending"}


# ---------------------------------------------------------------------------
# 注销
# ---------------------------------------------------------------------------
@app.post("/auth/logout")
def logout():
    _store.clear()
    return {"ok": True}


# ---------------------------------------------------------------------------
# MCP 透传（核心接入点）
# ---------------------------------------------------------------------------
@app.post("/mcp")
def mcp_proxy(req: McpReq):
    try:
        if req.jsonrpc:  # 透传完整 JSON-RPC
            result = _client.mcp.raw(req.method, req.params)
        else:
            result = _client.mcp_raw(req.method, req.params)
        return {"ok": True, "result": result}
    except LiblibError as e:
        return JSONResponse(status_code=401, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


# 便捷封装：列出工具 + 调用工具
@app.get("/mcp/tools")
def mcp_tools():
    try:
        return {"tools": _client.list_tools()}
    except LiblibError as e:
        return JSONResponse(status_code=401, content={"error": str(e)})


@app.post("/mcp/tools/call")
def mcp_call_tool(name: str, arguments: Optional[dict] = None):
    try:
        return {"result": _client.call_tool(name, arguments or {})}
    except LiblibError as e:
        return JSONResponse(status_code=401, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------------------------------------------------------
# OpenAPI REST 透传（需 Access Key）
# ---------------------------------------------------------------------------
@app.post("/openapi")
def openapi_proxy(req: OpenApiReq):
    try:
        key = cfg.OPENAPI_ACCESS_KEY
        if not key:
            return JSONResponse(
                status_code=400,
                content={"error": "未配置 LIBTV_ACCESS_KEY，无法使用 OpenAPI 代理"},
            )
        from liblib2api.openapi import OpenAPIClient

        cli = OpenAPIClient(access_key=key)
        out = cli._request(req.method.upper(), req.path, req.body)  # noqa: SLF001
        return {"ok": True, "data": out}
    except LiblibError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})

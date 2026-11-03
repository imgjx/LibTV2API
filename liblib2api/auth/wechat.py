"""微信扫码登录：OAuth 2.1 + PKCE（授权码模式）。

实现要点（与官方 LibTV Remote MCP 一致）：
  1. 从 issuer 的 /.well-known/oauth-authorization-server 动态发现
     authorization_endpoint / token_endpoint / registration_endpoint。
  2. 生成本地 code_verifier + code_challenge（S256），本地起回调服务
     或复用 FastAPI 服务的回调路由捕获授权码。
  3. 浏览器打开授权页，用户用微信扫码确认。
  4. 拿到 code 后向 token_endpoint 换取 access_token + refresh_token。
  5. 凭据写入 ~/.libtv/credentials.json（0600），access token 约 1 小时，
     由 refresh_token 自动续期。

注意：本模块只负责「把你本人账户的令牌签发到本机」，不会、也无法代你登录，
扫码这一步必须由你本人完成。令牌不出本机。
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

import httpx

import liblib2api.config as cfg
from liblib2api.auth.base import AuthMethod
from liblib2api.credentials import Credentials
from liblib2api.exceptions import AuthError, TokenError


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """返回 (code_verifier, code_challenge)。"""
    verifier = _b64url(secrets.token_bytes(32))
    # verifier 必须仅含 [A-Za-z0-9-._~]，urlsafe_b64encode 满足
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class WechatLoginFlow:
    """可复用的微信扫码登录流程（begin/finish 两段式）。

    既可用于 CLI 阻塞模式（自带本地回调服务器），也可嵌入 FastAPI 服务
    （由服务路由接管回调，用 in-memory 状态表跟踪）。
    """

    def __init__(
        self,
        issuer: str = cfg.LIBTV_ISSUER,
        mcp_url: str = cfg.LIBTV_MCP_URL,
        redirect_uri: Optional[str] = None,
        scope: str = cfg.OAUTH_SCOPE,
        client_id: Optional[str] = None,
        timeout: int = cfg.OAUTH_TIMEOUT,
        proxy: str = cfg.HTTP_PROXY,
        http_timeout: int = cfg.HTTP_TIMEOUT,
    ):
        self.issuer = issuer.rstrip("/")
        self.mcp_url = mcp_url
        self.redirect_uri = redirect_uri or self._default_redirect()
        self.scope = scope
        self.client_id = client_id or cfg.OAUTH_CLIENT_ID
        self.timeout = timeout
        self._client = httpx.Client(timeout=http_timeout)
        if proxy:
            self._client.proxies = proxy  # type: ignore[attr-defined]
        self._discovery: dict = {}
        self._pending: dict[str, dict] = {}  # state -> {verifier, done, creds, error}

    # ----- 端点发现 -----
    def discover(self) -> dict:
        if self._discovery:
            return self._discovery
        url = self.issuer + cfg.OAUTH_DISCOVERY_PATH
        try:
            resp = self._client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            self._discovery = resp.json()
        except httpx.HTTPError as e:
            raise AuthError(
                f"OAuth 发现失败（{url}）：{e}。可手动设置 LIBTV_ISSUER / "
                f"LIBTV_MCP_URL 或对应端点环境变量。"
            ) from e
        return self._discovery

    def _authorization_endpoint(self) -> str:
        return self.discover().get("authorization_endpoint") or f"{self.issuer}/authorize"

    def _token_endpoint(self) -> str:
        return self.discover().get("token_endpoint") or f"{self.issuer}/token"

    def _registration_endpoint(self) -> Optional[str]:
        return self.discover().get("registration_endpoint")

    def _default_redirect(self) -> str:
        return f"http://{cfg.OAUTH_REDIRECT_HOST}:{cfg.OAUTH_PORT}{cfg.OAUTH_REDIRECT_PATH}"

    # ----- 动态客户端注册（RFC 7591，可选）-----
    def _ensure_client_id(self) -> str:
        if self.client_id:
            return self.client_id
        reg = self._registration_endpoint()
        if reg:
            try:
                resp = self._client.post(
                    reg,
                    json={
                        "client_name": "liblib2api",
                        "redirect_uris": [self.redirect_uri],
                        "token_endpoint_auth_method": "none",
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                    },
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code < 400:
                    self.client_id = resp.json().get("client_id", "liblib2api")
                    return self.client_id
            except httpx.HTTPError:
                pass
        self.client_id = "liblib2api"
        return self.client_id

    # ----- 开始登录，返回授权链接 -----
    def begin(self, open_browser: bool = True) -> tuple[str, str]:
        """生成 state + 授权 URL，并把 verifier 记入 pending。"""
        state = secrets.token_urlsafe(24)
        verifier, challenge = generate_pkce()
        client_id = self._ensure_client_id()
        # scope 为空时采用发现文档中的 scopes_supported（实时作用域，避免被拒）
        if not self.scope:
            discovered = self.discover().get("scopes_supported") or []
            self.scope = " ".join(discovered).strip() or "openid"
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": self.scope,
        }
        auth_url = (
            self._authorization_endpoint() + "?" + urllib.parse.urlencode(params)
        )
        self._pending[state] = {"verifier": verifier, "done": False, "error": None}
        if open_browser:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass
        return state, auth_url

    # ----- 回调：用 code 换 token -----
    def finish(self, code: str, state: str) -> Credentials:
        pend = self._pending.get(state)
        if pend is None:
            raise AuthError(f"未知的 state：{state}（可能已过期或非法）")
        if pend.get("error"):
            raise AuthError(f"授权被拒绝：{pend['error']}")
        verifier = pend["verifier"]
        token_url = self._token_endpoint()
        client_id = self.client_id or self._ensure_client_id()
        try:
            resp = self._client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            raise TokenError(f"用授权码换 token 失败：{e}") from e
        if "error" in payload:
            raise TokenError(f"token 端点返回错误：{payload}")
        creds = self._to_credentials(payload)
        pend["done"] = True
        pend["creds"] = creds
        return creds

    def _to_credentials(self, payload: dict) -> Credentials:
        access = payload.get("access_token") or payload.get("accessToken")
        if not access:
            raise TokenError(f"token 响应缺少 access_token：{payload}")
        expires_in = payload.get("expires_in") or payload.get("expiresIn")
        expires_at = (
            int(time.time()) + int(expires_in) if expires_in is not None else None
        )
        return Credentials(
            access_token=access,
            token_type=payload.get("token_type", "Bearer"),
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scope=payload.get("scope", self.scope),
            login_method="wechat",
            account=payload.get("account") or "wechat",
            issuer=self.issuer,
            token_endpoint=self._token_endpoint(),
            client_id=self.client_id,
        )

    # ----- CLI 阻塞式：自带本地回调服务器 -----
    def login_blocking(
        self, open_browser: bool = True, store=None
    ) -> Credentials:
        from liblib2api.credentials import CredentialStore

        state, auth_url = self.begin(open_browser=open_browser)
        print("请在浏览器中用微信扫码登录：")
        print(f"  {auth_url}")
        print(f"（若未自动打开浏览器，请手动复制上面的链接。state={state}）")

        result: dict = {}
        barrier = threading.Event()

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # 静默
                pass

            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path.rstrip("/") != cfg.OAUTH_REDIRECT_PATH.rstrip("/"):
                    self.send_response(404)
                    self.end_headers()
                    return
                q = urllib.parse.parse_qs(parsed.query)
                rcv_state = (q.get("state") or [None])[0]
                code = (q.get("code") or [None])[0]
                error = (q.get("error") or [None])[0]
                if error:
                    result["error"] = error
                    self._reply("授权失败：" + error)
                elif code and rcv_state == state:
                    try:
                        result["creds"] = self.server.flow.finish(code, rcv_state)  # type: ignore
                        self._reply("✅ 授权成功！可关闭此页面返回终端。")
                    except Exception as e:  # noqa: BLE001
                        result["error"] = str(e)
                        self._reply("授权处理失败：" + str(e))
                else:
                    result["error"] = "state 不匹配或缺少 code"
                    self._reply("授权失败：state 不匹配")
                barrier.set()

            def _reply(self, text: str):
                body = (
                    "<html><head><meta charset='utf-8'></head><body>"
                    f"<h3>{text}</h3></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        host = urllib.parse.urlparse(self.redirect_uri).hostname or "127.0.0.1"
        port = urllib.parse.urlparse(self.redirect_uri).port or cfg.OAUTH_PORT
        server = HTTPServer((host, port), _Handler)
        server.flow = self  # type: ignore[attr-defined]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        got = barrier.wait(timeout=self.timeout)
        server.shutdown()
        if not got:
            raise AuthError("等待微信扫码授权超时，请重试。")
        if result.get("error"):
            raise AuthError(result["error"])
        creds = result["creds"]
        (store or CredentialStore()).save(creds)
        return creds


class WechatLogin(AuthMethod):
    """AuthMethod 适配：微信扫码登录。"""

    method = "wechat"

    def __init__(self, store=None, **flow_kwargs):
        super().__init__(store)
        self.flow = WechatLoginFlow(**flow_kwargs)

    def login(self, open_browser: bool = True) -> Credentials:
        return self.flow.login_blocking(open_browser=open_browser, store=self.store)

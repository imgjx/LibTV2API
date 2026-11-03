"""LibTV MCP 客户端（Streamable HTTP 传输）。

LibTV 把画布、图片/视频/音频生成、剧本、剪辑、导出等 86 个工具以 MCP 形式
暴露在 https://mcp.liblib.tv/mcp 。用微信/手机号登录拿到的 Bearer token 即其鉴权。

本客户端实现 MCP 的最小可用子集：
  - initialize 握手 + notifications/initialized
  - tools/list、tools/call、prompts/list、resources/list
  - 兼容 JSON 与 SSE(text/event-stream) 两种响应
  - 自动携带 Mcp-Session-Id、Bearer token，401 触发 refresh 后重放

对你的自动化工作流而言，call_tool() 就是调用任意一个 LibTV 能力的统一入口。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import httpx

import liblib2api.config as cfg
from liblib2api.credentials import CredentialStore, Credentials
from liblib2api.exceptions import McpError, NetworkError, NotLoggedInError


def _parse_sse(text: str) -> list[Any]:
    """把 SSE 文本解析为 JSON-RPC 消息列表。

    支持 `data: {...}` 单事件，以及多行 data 拼接。忽略注释行与 event 类型行，
    仅以 data 行承载 JSON 内容。
    """
    messages: list[Any] = []
    data_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())
        elif line == "":
            if data_lines:
                _flush(data_lines, messages)
                data_lines = []
    if data_lines:
        _flush(data_lines, messages)
    return messages


def _flush(data_lines: list[str], out: list[Any]) -> None:
    blob = "\n".join(data_lines)
    try:
        msg = json.loads(blob)
        out.append(msg)
    except json.JSONDecodeError:
        pass


class McpClient:
    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        credentials: Optional[Credentials] = None,
        mcp_url: str = cfg.LIBTV_MCP_URL,
        proxy: str = cfg.HTTP_PROXY,
        timeout: int = cfg.HTTP_TIMEOUT,
    ):
        self.store = store or CredentialStore()
        self._credentials = credentials
        self.mcp_url = mcp_url
        self._client = httpx.Client(timeout=timeout)
        if proxy:
            self._client.proxies = proxy  # type: ignore[attr-defined]
        self._session_id: Optional[str] = None
        self._initialized = False
        self._proto = cfg.MCP_PROTOCOL_VERSION

    # ----- 低级请求 -----
    def _headers(self) -> dict:
        creds: Optional[Credentials] = None
        if self._credentials is not None:
            creds = self._credentials
        else:
            try:
                creds = self.store.ensure_valid()
            except Exception as e:  # noqa: BLE001
                raise NotLoggedInError(f"未登录或令牌失效：{e}") from e
        assert creds is not None
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {creds.access_token}",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _rpc(self, method: str, params: Optional[dict] = None, is_notification: bool = False) -> Any:
        if not self._initialized and method != "initialize":
            self.initialize()
        rid = None if is_notification else str(uuid.uuid4())
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if rid is not None:
            payload["id"] = rid
        try:
            resp = self._client.post(self.mcp_url, headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise NetworkError(f"MCP 请求失败：{e}") from e
        if resp.status_code == 401:
            # 触发一次刷新并重放
            self.store.ensure_valid()
            try:
                resp = self._client.post(self.mcp_url, headers=self._headers(), json=payload)
            except httpx.HTTPError as e:
                raise NetworkError(f"MCP 重放失败：{e}") from e
            if resp.status_code == 401:
                raise NotLoggedInError("令牌失效且刷新失败，请重新登录。")
        if resp.status_code >= 400:
            raise NetworkError(
                f"MCP 返回 {resp.status_code}：{resp.text[:500]}", resp.status_code
            )
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        return self._parse(resp, rid)

    @staticmethod
    def _parse(resp: httpx.Response, rid: Optional[str]) -> Any:
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype or resp.text.lstrip().startswith("event:") or "data:" in resp.text[:200]:
            messages = _parse_sse(resp.text)
        else:
            try:
                messages = [resp.json()]
            except json.JSONDecodeError:
                messages = []
        if rid is None:
            return None
        # 取匹配 id 且含 result/error 的消息
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    err = msg["error"]
                    raise McpError(f"MCP 错误：{err}", err.get("code"))
                return msg.get("result")
        # 找不到匹配 id（部分实现把结果包在通知里）时，返回最后一条含 result 的
        for msg in reversed(messages):
            if isinstance(msg, dict) and "result" in msg:
                return msg["result"]
        return None

    # ----- 高级 API -----
    def initialize(self) -> dict:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": self._proto,
                "capabilities": {},
                "clientInfo": {
                    "name": cfg.MCP_CLIENT_NAME,
                    "version": cfg.MCP_CLIENT_VERSION,
                },
            },
        )
        # 发送 initialized 通知（部分网关要求）
        self._rpc("notifications/initialized", {}, is_notification=True)
        self._initialized = True
        return result or {}

    def list_tools(self) -> list[dict]:
        res = self._rpc("tools/list", {})
        return (res or {}).get("tools", [])

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return res

    def list_prompts(self) -> list[dict]:
        res = self._rpc("prompts/list", {})
        return (res or {}).get("prompts", [])

    def list_resources(self) -> list[dict]:
        res = self._rpc("resources/list", {})
        return (res or {}).get("resources", [])

    def raw(self, method: str, params: Optional[dict] = None) -> Any:
        """透传任意 MCP 方法，便于调用尚未封装的能力。"""
        return self._rpc(method, params)

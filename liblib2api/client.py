"""统一客户端门面。

对外暴露最常用的能力，并自动选择鉴权方式：
  - 登录态（微信/手机号 token）→ 走 MCP（call_tool 等）
  - 配置了 Access Key → 同时可用 OpenAPI REST

典型用法：
    from liblib2api import LiblibClient
    client = LiblibClient()          # 自动读取 ~/.libtv/credentials.json
    tools = client.list_tools()      # 列出全部能力
    res = client.call_tool("generate_video", {...})
"""
from __future__ import annotations

from typing import Any, Optional

from liblib2api.credentials import CredentialStore, Credentials
from liblib2api.exceptions import NotLoggedInError
from liblib2api.mcp import McpClient
from liblib2api.openapi import OpenAPIClient


class LiblibClient:
    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        credentials: Optional[Credentials] = None,
        mcp_url: str = "",
        openapi_key: str = "",
        proxy: str = "",
    ):
        self.store = store or CredentialStore()
        self._credentials = credentials
        self._mcp: Optional[McpClient] = None
        self._openapi: Optional[OpenAPIClient] = None
        self._mcp_url = mcp_url
        self._openapi_key = openapi_key
        self._proxy = proxy

    # ----- 惰性构建子客户端 -----
    @property
    def mcp(self) -> McpClient:
        if self._mcp is None:
            self._mcp = McpClient(
                store=self.store,
                credentials=self._credentials,
                mcp_url=self._mcp_url or "",
                proxy=self._proxy or "",
            )
        return self._mcp

    @property
    def openapi(self) -> OpenAPIClient:
        if self._openapi is None:
            self._openapi = OpenAPIClient(
                access_key=self._openapi_key or "", proxy=self._proxy or ""
            )
        return self._openapi

    # ----- MCP 便捷封装 -----
    def list_tools(self) -> list[dict]:
        return self.mcp.list_tools()

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        return self.mcp.call_tool(name, arguments)

    def list_prompts(self) -> list[dict]:
        return self.mcp.list_prompts()

    def mcp_raw(self, method: str, params: Optional[dict] = None) -> Any:
        return self.mcp.raw(method, params)

    # ----- 状态 -----
    def whoami(self) -> dict:
        try:
            creds = self.store.get()
        except Exception as e:  # noqa: BLE001
            raise NotLoggedInError(str(e)) from e
        return {
            "login_method": creds.login_method,
            "account": creds.account,
            "expires_at": creds.expires_at,
            "issuer": creds.issuer,
            "has_refresh": bool(creds.refresh_token),
        }

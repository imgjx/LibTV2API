"""LibTV OpenAPI REST 客户端（Access Key 鉴权，可选）。

端点：https://im.liblib.tv/openapi/...，请求头 Authorization: Bearer {ACCESS_KEY}。
Access Key 在 liblib.tv 用户中心 → Access Key 获取，与登录 token 是两套体系：
  - 登录 token（微信/手机号）→ 打 mcp.liblib.tv/mcp（MCP 工具）
  - Access Key（控制台）→ 打 im.liblib.tv/openapi（REST 会话接口）

本客户端供「已有 Access Key、想走 REST」的场景；若你只想用登录 token 驱动 MCP，
可忽略本文件。
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

import liblib2api.config as cfg
from liblib2api.exceptions import NetworkError


class OpenAPIClient:
    def __init__(
        self,
        access_key: str = cfg.OPENAPI_ACCESS_KEY,
        base_url: str = cfg.OPENAPI_BASE,
        proxy: str = cfg.HTTP_PROXY,
        timeout: int = cfg.HTTP_TIMEOUT,
    ):
        if not access_key:
            raise ValueError("缺少 LIBTV_ACCESS_KEY（OpenAPI 需要 Access Key）")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        if proxy:
            self._client.proxies = proxy  # type: ignore[attr-defined]
        self._headers = {
            "Authorization": f"Bearer {access_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self._client.request(method, url, headers=self._headers, json=body)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise NetworkError(f"OpenAPI 请求失败（{method} {url}）：{e}") from e

    # ----- 会话 / 画布 -----
    def create_session(self, message: Optional[str] = None, session_id: Optional[str] = None) -> Any:
        body: dict = {}
        if session_id:
            body["sessionId"] = session_id
        if message:
            body["message"] = message
        return self._request("POST", "/openapi/session", body).get("data", {})

    def query_session(self, session_id: str, after_seq: int = 0) -> Any:
        path = f"/openapi/session/{session_id}"
        if after_seq > 0:
            path += f"?afterSeq={after_seq}"
        return self._request("GET", path).get("data", {})

    def change_project(self) -> Any:
        return self._request("POST", "/openapi/session/change-project", {}).get("data", {})

    def upload_file(self, file_path: str) -> Any:
        with open(file_path, "rb") as f:
            files = {"file": f}
            headers = {k: v for k, v in self._headers.items() if k != "Content-Type"}
            try:
                resp = self._client.post(
                    f"{self.base_url}/openapi/file/upload",
                    headers=headers,
                    files=files,
                )
                resp.raise_for_status()
                return resp.json().get("data", {})
            except httpx.HTTPError as e:
                raise NetworkError(f"OpenAPI 上传失败：{e}") from e

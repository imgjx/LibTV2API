"""凭据的加载、持久化与安全存储。

凭据默认写入 ~/.libtv/credentials.json，权限 0600（仅本人可读写），
与官方 libtv CLI / dsh-libtv 的行为保持一致。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx

import liblib2api.config as cfg
from liblib2api.exceptions import CredentialError, TokenError


@dataclass
class Credentials:
    access_token: str
    token_type: str = "Bearer"
    refresh_token: Optional[str] = None
    # 过期时间戳（秒，UTC）。None 表示未知/长期有效。
    expires_at: Optional[int] = None
    scope: Optional[str] = None
    # 登录方式：wechat | phone
    login_method: Optional[str] = None
    # 账号标识（手机号 / 微信昵称等），仅用于展示
    account: Optional[str] = None
    # 续期所需上下文
    issuer: Optional[str] = None
    token_endpoint: Optional[str] = None
    client_id: Optional[str] = None
    # 任意扩展字段（如 webid）
    extra: dict = field(default_factory=dict)

    def is_expired(self, leeway: int = 60) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - leeway)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Credentials":
        data = dict(data)
        extra = data.pop("extra", {}) or {}
        return cls(**data, extra=extra)


class CredentialStore:
    """负责凭据的读写与刷新。"""

    def __init__(
        self,
        path: Path | str = cfg.CREDENTIALS_FILE,
        http_timeout: int = cfg.HTTP_TIMEOUT,
        proxy: str = cfg.HTTP_PROXY,
    ):
        self.path = Path(path)
        self._creds: Optional[Credentials] = None
        self._client = httpx.Client(timeout=http_timeout)
        if proxy:
            self._client.proxies = proxy  # type: ignore[attr-defined]

    # ----- 持久化 -----
    def save(self, creds: Credentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 先以严格权限创建，再写入，避免凭据短暂以宽松权限存在
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(creds.to_dict(), f, ensure_ascii=False, indent=2)
        finally:
            pass
        os.chmod(self.path, 0o600)
        self._creds = creds

    def load(self) -> Credentials:
        if self._creds is not None:
            return self._creds
        if not self.path.exists():
            raise CredentialError(f"未找到凭据文件：{self.path}（请先登录）")
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise CredentialError(f"凭据文件损坏：{e}") from e
        self._creds = Credentials.from_dict(data)
        return self._creds

    def clear(self) -> None:
        self._creds = None
        if self.path.exists():
            self.path.unlink()

    def get(self) -> Credentials:
        """返回已加载的凭据，不触发刷新。"""
        if self._creds is None:
            self.load()
        assert self._creds is not None
        return self._creds

    @property
    def logged_in(self) -> bool:
        try:
            return not self.get().is_expired()
        except CredentialError:
            return False

    # ----- 刷新 -----
    def ensure_valid(self) -> Credentials:
        """返回有效凭据；若临近过期则尝试用 refresh_token 续期。"""
        creds = self.get()
        if not creds.is_expired():
            return creds
        if not creds.refresh_token or not creds.token_endpoint:
            raise CredentialError("凭据已过期且无 refresh_token，请重新登录。")
        refreshed = self._refresh(creds)
        self.save(refreshed)
        return refreshed

    def _refresh(self, creds: Credentials) -> Credentials:
        try:
            resp = self._client.post(
                creds.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": creds.refresh_token,
                    "client_id": creds.client_id or "",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            raise TokenError(f"刷新 token 失败：{e}") from e
        return _merge_token(creds, payload)


def _merge_token(old: Credentials, payload: dict) -> Credentials:
    """把 OAuth token 响应合并进既有凭据。"""
    access = payload.get("access_token") or payload.get("accessToken")
    if not access:
        raise TokenError(f"token 响应缺少 access_token：{payload}")
    expires_in = payload.get("expires_in") or payload.get("expiresIn")
    expires_at = (
        int(time.time()) + int(expires_in)
        if expires_in is not None
        else old.expires_at
    )
    return Credentials(
        access_token=access,
        token_type=payload.get("token_type", old.token_type),
        refresh_token=payload.get("refresh_token", old.refresh_token),
        expires_at=expires_at,
        scope=payload.get("scope", old.scope),
        login_method=old.login_method,
        account=old.account,
        issuer=old.issuer,
        token_endpoint=old.token_endpoint,
        client_id=old.client_id,
        extra=old.extra,
    )

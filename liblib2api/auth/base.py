"""鉴权抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from liblib2api.credentials import Credentials, CredentialStore


class AuthMethod(ABC):
    """登录方式统一接口：login() 返回并持久化凭据。"""

    method: str = "base"

    def __init__(self, store: CredentialStore | None = None):
        self.store = store or CredentialStore()

    @abstractmethod
    def login(self, *args, **kwargs) -> Credentials:
        ...

    def _persist(self, creds: Credentials) -> Credentials:
        self.store.save(creds)
        return creds

"""统一异常体系。"""
from __future__ import annotations


class LiblibError(Exception):
    """所有 Liblib2API 异常的基类。"""


class ApiError(LiblibError):
    """调用 liblib 业务接口返回非预期结果（HTTP 4xx/5xx 或 code != 0）。"""


class ModelUnavailableError(LiblibError):
    """当前账号无权使用该模型（会员限制 / 额度不足 / 模型下架）。"""


class AuthError(LiblibError):
    """登录 / 鉴权失败。"""


class TokenError(AuthError):
    """Token 获取或刷新失败。"""


class CredentialError(AuthError):
    """凭据缺失或已失效。"""


class NetworkError(LiblibError):
    """网络层错误（连接 / 超时 / 非预期状态码）。"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class McpError(LiblibError):
    """MCP 协议层错误。"""

    def __init__(self, message: str, code: str | int | None = None):
        super().__init__(message)
        self.code = code


class NotLoggedInError(CredentialError):
    """尚未登录，或凭据已过期且无法刷新。"""

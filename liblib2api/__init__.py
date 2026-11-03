"""Liblib2API —— liblib.tv 登录与自动化接入层。

把 liblib.tv 的「手机号验证码 / 微信扫码」登录模块抓取并实现为可复用代码，
再以 MCP / OpenAPI 客户端 + FastAPI 服务的形式，供你的自动化工作流接入。
"""
from liblib2api.auth import PhoneLogin, WechatLogin, WechatLoginFlow
from liblib2api.client import LiblibClient
from liblib2api.credentials import CredentialStore, Credentials
from liblib2api.exceptions import (
    AuthError,
    CredentialError,
    LiblibError,
    McpError,
    NetworkError,
    NotLoggedInError,
    TokenError,
)
from liblib2api.accounts import Account, AccountStore
from liblib2api.mcp import McpClient
from liblib2api.media import ImageGenerateRequest, AudioGenerateRequest, MediaResult
from liblib2api.models import ModelInfo, classify_membership
from liblib2api.monitor import AccountMonitor
from liblib2api.openapi import OpenAPIClient
from liblib2api.selector import AccountSelector
from liblib2api.split_gen import VideoSplitPlanner, OpenAICompatibleClient, assign_accounts
from liblib2api.video_output import VideoGenerateRequest, VideoResult

__version__ = "0.3.0"

__all__ = [
    "LiblibClient",
    "CredentialStore",
    "Credentials",
    "Account",
    "AccountStore",
    "AccountMonitor",
    "AccountSelector",
    "ModelInfo",
    "classify_membership",
    "VideoGenerateRequest",
    "VideoResult",
    "ImageGenerateRequest",
    "AudioGenerateRequest",
    "MediaResult",
    "VideoSplitPlanner",
    "OpenAICompatibleClient",
    "assign_accounts",
    "McpClient",
    "OpenAPIClient",
    "PhoneLogin",
    "WechatLogin",
    "WechatLoginFlow",
    "LiblibError",
    "AuthError",
    "TokenError",
    "CredentialError",
    "NotLoggedInError",
    "NetworkError",
    "McpError",
]

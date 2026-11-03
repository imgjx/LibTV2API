"""LibTV-Team —— 团队账号统一管理与创作能力接入层。

面向团队场景：把团队成员各自的 liblib 会员 / 额度包账号统一纳入账号池，
由系统交叉选号、统一分配额度、监控会员与积分状态，并通过 MCP / OpenAPI
客户端 + FastAPI 服务供自动化工作流统一调用。
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
from liblib2api.analytics import account_stats, member_stats, team_overview, team_stats
from liblib2api.notify import NotifyCenter, NotifyMessage
from liblib2api.teams import Member, Team, TeamStore
from liblib2api.expiry import expiry_info, expiry_level, days_left
from liblib2api.mcp import McpClient
from liblib2api.media import ImageGenerateRequest, AudioGenerateRequest, MediaResult
from liblib2api.models import ModelInfo, classify_membership
from liblib2api.monitor import AccountMonitor
from liblib2api.openapi import OpenAPIClient
from liblib2api.selector import AccountSelector
from liblib2api.split_gen import VideoSplitPlanner, OpenAICompatibleClient, assign_accounts
from liblib2api.video_output import VideoGenerateRequest, VideoResult

__version__ = "0.5.0"

__all__ = [
    "LiblibClient",
    "CredentialStore",
    "Credentials",
    "Account",
    "AccountStore",
    "Team",
    "Member",
    "TeamStore",
    "team_stats",
    "team_overview",
    "member_stats",
    "account_stats",
    "NotifyCenter",
    "NotifyMessage",
    "expiry_info",
    "expiry_level",
    "days_left",
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

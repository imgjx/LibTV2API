"""鉴权子包。

包含两部分：
- 登录流程（base / phone / wechat）：liblib 平台的手机号、微信扫码登录。
- 面板与对外 API 鉴权（hash_password / verify_password / make_token /
  verify_token / new_api_key）：单管理员会话令牌 + 对外 API Key 兼容校验。
"""
from liblib2api.auth.base import AuthMethod
from liblib2api.auth.phone import PhoneLogin
from liblib2api.auth.wechat import WechatLogin, WechatLoginFlow

# --- 面板管理员 / 对外 API Key 鉴权（原先在 auth.py，与 auth/ 包同名冲突，并入此处） ---
import base64
import hashlib
import hmac
import json
import secrets
import time

import liblib2api.config as cfg

__all__ = [
    "AuthMethod",
    "PhoneLogin",
    "WechatLogin",
    "WechatLoginFlow",
    "AUTH_SECRET",
    "hash_password",
    "verify_password",
    "make_token",
    "verify_token",
    "new_api_key",
]


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


# 服务级签名密钥：优先 env 固定，否则每次启动随机（重启后旧令牌失效，属预期）
AUTH_SECRET = (cfg.AUTH_SECRET or secrets.token_hex(32)).encode("utf-8")


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    d = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2${salt}${d.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, salt, d = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2":
        return False
    nd = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return hmac.compare_digest(nd.hex(), d)


def make_token(username: str, ttl: int = 60 * 60 * 24 * 7) -> str:
    payload = _b64u(json.dumps({"u": username, "exp": int(time.time()) + ttl}).encode("utf-8"))
    sig = hmac.new(AUTH_SECRET, payload.encode("utf-8"), "sha256").hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str) -> str | None:
    try:
        payload, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(AUTH_SECRET, payload.encode("utf-8"), "sha256").hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        data = json.loads(_b64d(payload))
    except Exception:
        return None
    if data.get("exp", 0) < int(time.time()):
        return None
    return data.get("u")


def new_api_key() -> str:
    """生成一个新的对外 API Key。"""
    return "sk-" + secrets.token_urlsafe(24)

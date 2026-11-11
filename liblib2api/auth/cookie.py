"""Cookie 登录：从浏览器复制的会话 Cookie 直接登记账号。

适用场景
--------
用户在浏览器里已经登录 liblib，直接把开发者工具（Network / Application 面板）里
看到的 ``Cookie`` 字符串（或 JSON 对象）粘贴进来即可，**无需短信验证码、也无需
微信扫码**。对于「账号是别人/自己已在网页登录、只想要一份可复用凭据」的场景尤其方便。

实现要点
--------
- 解析 Cookie 字符串（``name=value; name2=value2`` 形式）或 JSON 对象 / 数组为 dict；
- 从 Cookie 中尽量提取平台 token（``usertoken`` / ``token`` / ``access_token`` /
  ``Authorization``），与 Cookie 一同交给 ``WebApiClient``：平台接受 ``Token`` 头或
  Cookie 任一鉴权方式；
- 调 ``user_info`` / ``member/account`` 校验登录态并拉取昵称 / uid / 手机号，
  校验失败（抛 ``AuthError``）说明 Cookie 已失效；
- 返回 ``Credentials``（``login_method="cookie"``），由面板 / 导入流程登记进账号池，
  凭据（含完整 Cookie）仅存本机 ``accounts.json``（权限 0600）。

安全提示
--------
Cookie 等价于「已登录会话」，请只粘贴你自己或团队成员已合法拥有的账号会话，
且不要泄露给他人。本工具不会、也无法将 Cookie 上传到任何第三方。
"""
from __future__ import annotations

import json
import time
from typing import Optional

import liblib2api.config as cfg
from liblib2api.auth.base import AuthMethod
from liblib2api.credentials import Credentials
from liblib2api.exceptions import AuthError
from liblib2api.webapi import WebApiClient

# 平台会话里常见的「token 类」cookie 名，按顺序尝试提取，作为 Token 头使用。
_TOKEN_COOKIE_KEYS = ("usertoken", "token", "access_token", "accessToken", "jwt")
# 平台设备指纹类 cookie 名（作为 Webid 使用，避免触发额外风控校验）。
_WEBID_COOKIE_KEYS = ("webid", "webId", "deviceid", "deviceId")


def parse_cookies(raw) -> dict:
    """把多种形态的 Cookie 输入解析成 ``{name: value}`` 字典。

    支持：
      - 字符串 ``"a=1; b=2"``（浏览器复制的 Cookie 头）
      - JSON 对象字符串 ``'{"a":"1","b":"2"}'``
      - JSON 数组 ``'[{"name":"a","value":"1"}]'``（Application 面板导出格式）
      - 已是 dict / list 的对象
    """
    if isinstance(raw, dict):
        # 可能是 {name: value}，也可能是 [{name, value}] 的 Application 导出格式。
        if raw and all(isinstance(v, dict) for v in raw.values()):
            # 形如 {"0": {"name":"a","value":"1"}} 不太常见，忽略。
            return dict(raw)
        # 普通 {name: value} 字典
        return {str(k): ("" if v is None else str(v)) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict = {}
        for item in raw:
            if isinstance(item, dict) and item.get("name") is not None:
                out[str(item["name"])] = "" if item.get("value") is None else str(item["value"])
        return out
    if not isinstance(raw, str):
        raise AuthError(f"无法识别的 Cookie 格式：{type(raw).__name__}")

    text = raw.strip()
    if not text:
        raise AuthError("Cookie 为空")
    # 先尝试作为 JSON 解析（对象或数组）
    if text.startswith("{") or text.startswith("["):
        try:
            obj = json.loads(text)
            return parse_cookies(obj)
        except (ValueError, TypeError):
            pass
    # 否则按 "name=value; name2=value2" 解析
    out = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
        else:
            out[part] = ""
    if not out:
        raise AuthError("未能从输入中解析出任何 Cookie 键值对")
    return out


class CookieLogin(AuthMethod):
    """从浏览器 Cookie 直接登记账号。"""

    method = "cookie"

    def __init__(
        self,
        store=None,
        proxy: str = cfg.HTTP_PROXY,
        token_target: str = cfg.PHONE_TOKEN_TARGET,
        http_timeout: int = cfg.HTTP_TIMEOUT,
    ):
        super().__init__(store)
        self.proxy = proxy
        self.token_target = token_target
        self._http_timeout = http_timeout

    # ----- 资源释放（与 PhoneLogin 一致，支持 `with`）-----
    def __enter__(self) -> "CookieLogin":
        return self

    def __exit__(self, *exc) -> None:
        return False

    # ----- 解析 -----
    @staticmethod
    def _extract_token(cookies: dict) -> Optional[str]:
        for key in _TOKEN_COOKIE_KEYS:
            if key in cookies and cookies[key]:
                return cookies[key]
        # Authorization: Bearer xxx 形式的 cookie
        auth = cookies.get("Authorization")
        if auth and " " in auth:
            return auth.split(" ", 1)[1]
        return None

    @staticmethod
    def _extract_webid(cookies: dict, fallback: Optional[str] = None) -> Optional[str]:
        for key in _WEBID_COOKIE_KEYS:
            if key in cookies and cookies[key]:
                return cookies[key]
        return fallback

    # ----- 校验并登记 -----
    def login(
        self,
        cookies,
        webid: Optional[str] = None,
        cid: Optional[str] = None,
        account_hint: Optional[str] = None,
    ) -> Credentials:
        """解析 cookies、校验登录态、返回 Credentials。

        :param cookies: 字符串 / 字典 / 数组（见 :func:`parse_cookies`）。
        :param webid: 可选显式 Webid（设备指纹）；否则从 cookie 提取。
        :param cid: 可选 cid；否则由平台交互时自动生成。
        :param account_hint: 调用方已知的账号标识（用于回退命名）。
        """
        try:
            cookie_dict = parse_cookies(cookies)
        except AuthError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AuthError(f"Cookie 解析失败：{e}") from e
        if not cookie_dict:
            raise AuthError("Cookie 为空或解析后无内容")

        token = self._extract_token(cookie_dict)
        webid = self._extract_webid(cookie_dict, webid)

        client = WebApiClient(
            access_token=token or "",
            webid=webid,
            proxy=self.proxy,
            cookies=cookie_dict,
            cid=cid,
            timeout=self._http_timeout,
        )
        try:
            info = client.user_info() or {}
            if not isinstance(info, dict):
                info = {}
        except (AuthError, Exception) as e:  # noqa: BLE001
            # 登录态校验未通过：Cookie 已失效。
            raise AuthError(
                f"Cookie 无效或已失效，请重新从浏览器复制最新的 Cookie：{e}"
            ) from e
        finally:
            client.close()

        nickname = info.get("nickname") or info.get("nickName") or info.get("name")
        user_id = info.get("id") or info.get("userId") or info.get("user_id") or info.get("uuid")
        mobile = info.get("mobile")
        # 账号标识优先级：手机号 > 昵称 > user_id > 调用方提示 > 兜底
        account = mobile or nickname or user_id or account_hint or "cookie"

        issued_at = int(time.time())
        return Credentials(
            access_token=token or "",
            token_type="Bearer",
            refresh_token=None,
            expires_at=None,
            scope=None,
            login_method="cookie",
            account=str(account),
            issuer=self.token_target,
            token_endpoint=None,
            extra={
                "webid": webid,
                "nickname": nickname,
                "user_id": str(user_id) if user_id else None,
                "uuid": info.get("uuid"),
                "mobile": mobile,
                "cid": cid,
                # 完整会话 Cookie：与 Token 头一并用于后续 API 鉴权。
                "cookies": cookie_dict,
                # 校验阶段已拉取的用户信息，供登记流程补全昵称/uid。
                "user_info": info,
                # 平台未返回到期时间，不再估算；是否失效以真实 API 响应判定。
                "token_issued_at": issued_at,
                "token_expires_at": None,
                "token_expires_estimated": False,
            },
        )

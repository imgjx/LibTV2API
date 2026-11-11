"""手机号验证码登录（liblib 账号体系，passport.liblib.art）。

流程：send_code(phone) 下发短信验证码 → login(phone, code) 用验证码换 token。

端点为实测可用值（已用真实手机号验证下发成功）：
    下发验证码  POST https://passport.liblib.art/api/www/login/sendLoginPhoneCode
    验证码登录  POST https://passport.liblib.art/api/www/login/loginByPhoneCode
    用户信息    POST https://passport.liblib.art/api/www/user/getUserInfo

请求约定：
  * 登录需要带 cid（毫秒时间戳 + 8 位小写字母数字随机串）
  * token 依次从 data.token / data.usertoken / data.accessToken、
    响应 Cookie(usertoken) / Set-Cookie 中提取
  * webid 由客户端生成（毫秒时间戳 + 8 位随机串），Web API 需携带

环境变量覆盖：
  LIBLIB_PHONE_SMS_SEND_URL / LIBLIB_PHONE_LOGIN_URL / LIBLIB_PHONE_USER_INFO_URL
  LIBLIB_PHONE_API_BASE / LIBLIB_PHONE_ORIGIN
"""
from __future__ import annotations

import re
import secrets
import string
import time
from typing import Optional

import httpx

import liblib2api.config as cfg
from liblib2api.auth.base import AuthMethod
from liblib2api.credentials import Credentials
from liblib2api.exceptions import AuthError, TokenError

_RAND_ALPHABET = string.ascii_lowercase + string.digits


def generate_cid() -> str:
    """cid：{毫秒时间戳}{8 位小写字母数字随机串}。"""
    ts = int(time.time() * 1000)
    rand = "".join(secrets.choice(_RAND_ALPHABET) for _ in range(8))
    return f"{ts}{rand}"


def generate_webid() -> str:
    """webid：{毫秒时间戳}{8 位小写字母数字随机串}（Web API 需要）。"""
    return generate_cid()


class PhoneLogin(AuthMethod):
    method = "phone"

    def __init__(
        self,
        store=None,
        sms_send_url: str = cfg.PHONE_SMS_SEND_URL,
        login_url: str = cfg.PHONE_LOGIN_URL,
        user_info_url: str = cfg.PHONE_USER_INFO_URL,
        origin: str = cfg.PHONE_ORIGIN,
        token_target: str = cfg.PHONE_TOKEN_TARGET,
        proxy: str = cfg.HTTP_PROXY,
        http_timeout: int = cfg.HTTP_TIMEOUT,
    ):
        super().__init__(store)
        self.sms_send_url = sms_send_url
        self.login_url = login_url
        self.user_info_url = user_info_url
        self.origin = origin
        self.token_target = token_target
        self._token: Optional[str] = None
        self._webid: Optional[str] = None
        self._client = httpx.Client(
            timeout=http_timeout,
            follow_redirects=True,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
                ),
                "Origin": origin,
                "Referer": origin + "/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh,en;q=0.9,zh-CN;q=0.8",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            },
        )
        if proxy:
            self._client.proxies = proxy  # type: ignore[attr-defined]

    # ----- 资源释放 -----
    def close(self) -> None:
        """释放底层 httpx 连接池；面板每次发码/登录都会新建本对象，必须关闭。"""
        self._client.close()

    def __enter__(self) -> "PhoneLogin":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----- 下发验证码 -----
    def send_code(self, phone: str, extra: Optional[dict] = None) -> dict:
        """请求下发短信验证码。返回服务端原始响应。"""
        if not self._valid_phone(phone):
            raise AuthError(f"手机号格式不正确：{phone}")
        body = {"phone": phone}
        if extra:
            body.update(extra)
        try:
            resp = self._client.post(self.sms_send_url, json=body)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            raise AuthError(f"发送验证码请求失败（{self.sms_send_url}）：{e}") from e
        self._raise_on_biz_error(payload, "发送验证码")
        return payload

    # ----- 验证码登录 -----
    def login(self, phone: str, code: str, extra: Optional[dict] = None) -> Credentials:
        if not self._valid_phone(phone):
            raise AuthError(f"手机号格式不正确：{phone}")
        if not code:
            raise AuthError("验证码不能为空")
        body = {"phone": phone, "code": code, "cid": generate_cid()}
        if extra:
            body.update(extra)
        try:
            resp = self._client.post(self.login_url, json=body)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            raise AuthError(f"登录请求失败（{self.login_url}）：{e}") from e

        self._raise_on_biz_error(payload, "登录")
        creds = self._extract_credentials(payload, phone)
        # 登录响应会下发会话 cookie：passport 的用户信息接口靠 cookie 判定登录态，
        # 之前这里只把 cookie 留在临时客户端里，登录结束即丢失，
        # 导致 token 过期后无法在本地续期，只能重新走短信验证码。
        cookies = {k: v for k, v in resp.cookies.items() if v}
        self._client.cookies.update(cookies)
        creds.extra["cookies"] = cookies
        creds.extra["cid"] = body.get("cid")
        # 把 token / webid 写进客户端请求头。
        #
        # 关键修复：此前 user_info() 复用同一个客户端却从未注入 Token 头，
        # 于是「登录成功后立刻校验登录态」必然返回「未登录」，
        # 让人误以为登录失败 / 账号被踢，实际上 token 是好的。
        # 平台（passport / api2）判定登录态看的就是 Token 头（+ Webid）。
        self._token = creds.access_token
        self._webid = creds.extra.get("webid")
        self._client.headers["Token"] = creds.access_token
        if self._webid:
            self._client.headers["Webid"] = str(self._webid)
        return self._persist(creds)

    def adopt_webid(self, webid: Optional[str]) -> None:
        """复用该账号此前使用过的 webid（设备指纹）。

        webid 是客户端生成的设备标识。同一账号每次登录都换新 webid 会让
        平台侧看起来像换了一台新设备，可能触发风控或额外的会话校验。
        因此重新登录时沿用历史 webid，除非平台在下发响应里给了新的。
        """
        if webid:
            self._webid = webid
            self._client.headers["Webid"] = str(webid)

    # ----- 用户信息（校验登录态）-----
    def user_info(self) -> dict:
        """查询当前登录用户信息。

        登录成功后本对象已注入 Token / Webid 头，可直接用于校验登录态。
        """
        try:
            resp = self._client.post(self.user_info_url, json={})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise AuthError(f"获取用户信息失败（{self.user_info_url}）：{e}") from e

    # ----- 业务错误（code != 0 即失败）-----
    @staticmethod
    def _raise_on_biz_error(payload: dict, action: str) -> None:
        if not isinstance(payload, dict):
            return
        code = payload.get("code")
        if code is None or code == 0:
            return
        msg = payload.get("msg") or payload.get("message") or "未知错误"
        raise AuthError(f"{action}失败：[{code}] {msg}")

    # ----- 凭据抽取 -----
    def _extract_credentials(self, payload: dict, phone: str) -> Credentials:
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}

        def pick(*keys):
            for src in (data, payload):
                for k in keys:
                    v = src.get(k)
                    if v:
                        return v
            return None

        access = pick("token", "usertoken", "accessToken", "access_token", "jwt")
        if not access:
            raise TokenError(
                f"登录响应中未找到 token 字段，请检查端点/请求体是否与官网一致：{payload}"
            )
        refresh = pick("refresh_token", "refreshToken")
        expires_in = pick("expires_in", "expiresIn")
        expires_at = (
            int(time.time()) + int(expires_in) if expires_in is not None else None
        )
        webid = pick("webid", "webId") or generate_webid()
        nickname = pick("nickname", "nickName", "userName", "username", "name")
        user_id = pick("userId", "user_id", "uid", "id")
        issued_at = int(time.time())

        return Credentials(
            access_token=access,
            token_type="Bearer",
            refresh_token=refresh,
            expires_at=expires_at if expires_in is not None else None,
            scope=pick("scope"),
            login_method="phone",
            account=phone,
            issuer=self.token_target,
            token_endpoint=None,  # 验证码登录无标准 refresh 端点，过期需重新登录
            extra={
                "webid": webid,
                "phone": phone,
                "nickname": nickname,
                "user_id": user_id,
                "cid": payload.get("cid"),
                # 令牌签发时刻落地，用于展示「已在线 N 天」。
                # 平台登录响应通常不给 expires_in，且实测表明手机号令牌并不会
                # 在 2.5 天内强制失效（手动登录可用 30 天以上）；因此**不再估算**
                # 到期时间，令牌是否真的失效以真实 API 响应（未登录）判定为准。
                "token_issued_at": issued_at,
                "token_expires_at": expires_at if expires_in is not None else None,
                "token_expires_estimated": bool(expires_in is not None),
            },
        )

    @staticmethod
    def _valid_phone(phone: str) -> bool:
        return bool(re.fullmatch(r"\+?[0-9]{6,15}", (phone or "").strip()))

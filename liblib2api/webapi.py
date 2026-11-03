"""liblib Web API 客户端（api2.liblib.art / passport.liblib.art）。

鉴权方式（已实测）：
    请求头  Token: <access_token>
            Webid: <webid>
    两者缺一不可，否则返回 {"code":401,"msg":"No login"}。

已验证的端点：
    用户信息   POST passport.liblib.art/api/www/user/getUserInfo
    会员信息   GET  api2.liblib.art/api/www/member/account?isApp=false
    子账号列表 GET  api2.liblib.art/api/www/account/list
    每日算力   POST api2.liblib.art/api/www/member/libtvFreePower
    积分明细   GET  api2.liblib.art/api/www/member/points?packageType=POWER
    视频模型   GET  api2.liblib.art/api/www/video/recommend-models
    图片模型   GET  api2.liblib.art/api/www/model/imgGenerator/modelCard/config
    每日登录   POST api2.liblib.art/api/www/client/event/report   body {"cid": webid}
    活动权益   GET  api2.liblib.art/api/www/commerce/activity/benefit?productTypes=2

注意：bridge.liblib.art 网关（生图/生视频提交）有 WAF，非浏览器指纹请求会返回 405，
因此生成类请求走 browser 通道（见 browser.py）或官方 MCP/OpenAPI。
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx

import liblib2api.config as cfg
from liblib2api.exceptions import ApiError, AuthError
from liblib2api.models import (
    annotate_availability,
    build_usability_map,
    normalize_image,
    normalize_video,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)


class WebApiClient:
    """针对单个账号的 Web API 客户端。每个账号可绑定独立代理。"""

    def __init__(
        self,
        access_token: str,
        webid: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: int = cfg.HTTP_TIMEOUT,
        origin: str = cfg.PHONE_ORIGIN,
    ):
        self.access_token = access_token
        self.webid = webid
        self.timeout = timeout
        self.origin = origin
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh,en;q=0.9,zh-CN;q=0.8",
                "User-Agent": USER_AGENT,
                "Origin": origin,
                "Referer": origin + "/",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Token": access_token,
            },
        )
        if webid:
            self._client.headers["Webid"] = webid
        if proxy:
            self._client.proxies = proxy  # type: ignore[attr-defined]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WebApiClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----- 底层请求 -----
    def _request(self, method: str, url: str, body: Optional[dict] = None) -> Any:
        try:
            resp = self._client.request(method, url, json=body)
        except httpx.HTTPError as e:
            raise ApiError(f"请求失败（{url}）：{e}") from e
        if resp.status_code == 401:
            raise AuthError("账号未登录或 token 已失效，请重新登录")
        if resp.status_code >= 400:
            raise ApiError(f"HTTP {resp.status_code}（{url}）：{resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError:
            raise ApiError(f"响应非 JSON（{url}）：{resp.text[:200]}")
        if isinstance(payload, dict) and payload.get("code") not in (0, None):
            msg = payload.get("msg") or payload.get("message") or "未知错误"
            raise ApiError(f"接口返回错误 [{payload.get('code')}]：{msg}")
        return payload.get("data") if isinstance(payload, dict) else payload

    # ----- 用户 / 会员 -----
    def user_info(self) -> dict:
        """当前登录用户信息（手机号、昵称、uuid 等）。"""
        return self._request("POST", f"{cfg.PASSPORT_BASE}/api/www/user/getUserInfo", {}) or {}

    def member_account(self) -> dict:
        """会员信息：等级、套餐、生效状态、是否已领每日算力。"""
        return self._request(
            "GET", f"{cfg.WEB_API_BASE}/api/www/member/account?isApp=false"
        ) or {}

    def sub_accounts(self) -> list[dict]:
        """账号下的子账号（团队/主账号体系）。"""
        data = self._request("GET", f"{cfg.WEB_API_BASE}/api/www/account/list") or {}
        return data.get("accounts") or []

    # ----- 积分 / 算力 -----
    def free_power(self) -> dict:
        """LibTV 每日免费算力：{freePower, status, reason, expireAt}。"""
        return self._request(
            "POST", f"{cfg.WEB_API_BASE}/api/www/member/libtvFreePower", {}
        ) or {}

    def points(self, package_type: str = "POWER") -> list[dict]:
        """积分（算力）明细流水。"""
        return self._request(
            "GET", f"{cfg.WEB_API_BASE}/api/www/member/points?packageType={package_type}"
        ) or []

    def daily_benefits(self, product_types: int = 2) -> list[dict]:
        """每日权益（免积分畅用等）。"""
        data = self._request(
            "GET",
            f"{cfg.WEB_API_BASE}/api/www/commerce/activity/benefit?productTypes={product_types}",
        ) or {}
        return data.get("list") or []

    # ----- 账号类型识别（导入/同步/监控共用）-----
    def detect_account_type(self) -> dict:
        """根据 member/account 自动识别账号类型。

        返回 {
            type: "member" | "free" | "unknown",
            level, name, effective, is_sub, owner_uuid, owner_type,
            package_type, member_until, raw_member
        }
        """
        member = self.member_account() or {}
        level = member.get("accountLevel")
        name = member.get("accountLevelName") or member.get("name") or "未知"
        effective = member.get("effective")
        owner_uuid = member.get("ownerUuid")
        owner_type = member.get("ownerType")
        package_type = member.get("packageType")
        member_until = member.get("endTime")

        if effective is True or (level not in (None, 0) and str(name) not in ("非会员", "未知")):
            atype = "member"
        elif str(name) == "非会员" or level == 0:
            atype = "free"
        else:
            atype = "unknown"

        is_sub = bool(owner_uuid)  # 有 ownerUuid 视为子账号/副卡
        return {
            "type": atype,
            "level": level,
            "name": name,
            "effective": effective,
            "is_sub": is_sub,
            "owner_uuid": owner_uuid,
            "owner_type": owner_type,
            "package_type": package_type,
            "member_until": member_until,
            "raw_member": member,
        }

    def free_benefit_model_keys(self) -> set[str]:
        """当前账号当日可免费用（freeRunTimes）的模型 key 集合。

        用于纠正「会员专属」关键词误判：被权益豁免的模型对非会员也可生成。
        """
        out: set[str] = set()
        for b in self.daily_benefits():
            if b.get("benefitType") == "freeRunTimes" and b.get("benefitStatus") != 0:
                k = b.get("targetKey")
                if k:
                    out.add(k)
        return out

    def compute_model_usability(self) -> dict:
        """一次性计算账号类型 + 每个模型的可用性映射 + 原始模型清单。

        返回 {
            account_type: {...}, free_benefit_keys: [...],
            usable: {model_key: bool}, models: {video:[...], image:[...]}
        }
        """
        atype = self.detect_account_type()
        benefits = self.free_benefit_model_keys()
        video = [normalize_video(m) for m in self.video_models()]
        image = [normalize_image(m) for m in self.image_models()]
        usable: dict[str, bool] = {}
        usable.update(build_usability_map(video, atype["type"], benefits))
        usable.update(build_usability_map(image, atype["type"], benefits))
        return {
            "account_type": atype,
            "free_benefit_keys": sorted(benefits),
            "usable": usable,
            "models": {
                "video": [m.to_dict() for m in video],
                "image": [m.to_dict() for m in image],
            },
        }

    # ----- 模型列表 -----
    def video_models(self) -> list[dict]:
        """可用视频模型（动态获取）。"""
        data = self._request("GET", f"{cfg.WEB_API_BASE}/api/www/video/recommend-models") or {}
        return data.get("models") or []

    def image_models(self) -> list[dict]:
        """可用图片模型（动态获取）。"""
        data = self._request(
            "GET", f"{cfg.WEB_API_BASE}/api/www/model/imgGenerator/modelCard/config"
        ) or {}
        return data.get("modelCards") or []

    # ----- 签到 -----
    def daily_checkin(self) -> bool:
        """触发每日登录事件（等价于「每天进一次网页自动签到」）。

        站点在页面加载时会 POST client/event/report 带 cid=Webid，
        服务端据此发放当日免费算力。这里直接复用该请求。
        """
        cid = self.webid or ""
        try:
            self._request(
                "POST",
                f"{cfg.WEB_API_BASE}/api/www/client/event/report",
                {"cid": cid},
            )
            return True
        except ApiError:
            return False

    # ----- 汇总 -----
    def snapshot(self) -> dict:
        """一次性拉取账号状态快照（面板用）。"""
        out: dict[str, Any] = {"account": None, "points": None, "error": None}
        try:
            info = self.user_info()
            out["account"] = {
                "user_id": info.get("id"),
                "uuid": info.get("uuid"),
                "mobile": info.get("mobile"),
                "nickname": info.get("nickname"),
                "avatar": info.get("avatar"),
            }
        except Exception as e:
            out["error"] = f"用户信息获取失败：{e}"

        try:
            member = self.member_account()
            out["member"] = {
                "name": member.get("name"),
                "account_level": member.get("accountLevel"),
                "account_level_name": member.get("accountLevelName"),
                "effective": member.get("effective"),
                "package_type": member.get("packageType"),
                "has_get_power": member.get("hasGetPower"),
                "end_time": member.get("endTime"),
            }
        except Exception as e:
            out.setdefault("errors", []).append(f"会员信息获取失败：{e}")

        try:
            fp = self.free_power()
            out["free_power"] = {
                "free_power": fp.get("freePower"),
                "status": fp.get("status"),
                "reason": fp.get("reason"),
                "expire_at": fp.get("expireAt"),
            }
        except Exception as e:
            out.setdefault("errors", []).append(f"免费算力获取失败：{e}")

        try:
            out["points"] = self.points()
        except Exception as e:
            out.setdefault("errors", []).append(f"积分明细获取失败：{e}")

        out["synced_at"] = int(time.time())
        return out

    # ----- 静态方法：模型清单（含算力消耗）-----
    @staticmethod
    def normalize_models(models: list[dict], kind: str) -> list[dict]:
        """统一模型结构，补充 kind / labels 等便于前端展示的字段。"""
        result = []
        for m in models:
            result.append(
                {
                    "kind": kind,
                    "name": m.get("modelName") or m.get("name"),
                    "description": m.get("description"),
                    "category": m.get("categoryName"),
                    "base_type": m.get("baseType"),
                    "checkpoint_id": m.get("checkpointId"),
                    "model_key": m.get("modelKey"),
                    "labels": m.get("labels") or [],
                    "cover_url": m.get("coverUrl") or m.get("imageUrl"),
                    "width": m.get("width"),
                    "height": m.get("height"),
                    "base_config": m.get("baseConfig"),
                }
            )
        return result

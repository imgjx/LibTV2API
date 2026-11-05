"""令牌有效期管理：预估到期时刻、计算剩余时间、给出预警等级。

背景
----
liblib 的手机号验证码登录只会下发一个 ``access_token``，**没有 refresh_token，
也没有标准 OAuth 续期端点**。实测该令牌寿命约 2～3 天：2026-11-02 23:48 登录，
11-04 当天权益领取仍正常，11-05 就已返回「未登录」。

这意味着令牌到期是**常态**，不是账号被封禁。但如果不记录签发时刻与有效期，
面板上完全看不出「这个账号的令牌还剩多久」，账号会在毫无预警的情况下突然不可用，
很容易被误判成账号退登。

本模块负责：
- 根据签发时刻与（平台给出的或实测估算的）有效期算出到期时刻；
- 计算剩余时间与预警等级，供面板展示与后台巡检告警使用。

等级约定
--------
- ``expired``   已过期（应立即重新登录）
- ``critical``  24 小时内到期（红，需尽快重新登录）
- ``warning``   3 天内到期（黄）
- ``ok``        3 天以上到期
- ``unknown``   无签发时刻信息（老账号升级上来时可能缺失）
"""
from __future__ import annotations

import time
from typing import Optional

#: 平台未给出 expires_in 时，按实测寿命估算的令牌有效期（秒）。
#: 实测：11-02 23:48 登录 → 11-04 领取正常 → 11-05 失效，故取 2.5 天。
TOKEN_TTL_ESTIMATE = int(2.5 * 24 * 3600)

#: 严重预警阈值（秒）—— 不足 1 天即需重新登录
CRITICAL_SECONDS = 24 * 3600
#: 预警阈值（秒）—— 不足 3 天
WARN_SECONDS = 3 * 24 * 3600

LEVEL_TEXT = {
    "expired": "已过期",
    "critical": "即将过期",
    "warning": "临近过期",
    "ok": "有效",
    "unknown": "—",
}


def resolve_expires_at(
    extra: Optional[dict],
    fallback_ttl: int = TOKEN_TTL_ESTIMATE,
) -> Optional[int]:
    """从账号的 ``extra`` 中解析令牌到期时刻（秒级时间戳）。

    优先使用平台下发的 ``token_expires_at``；缺失时用签发时刻 + 估算寿命补齐。
    """
    extra = extra or {}
    expires_at = extra.get("token_expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0:
        return int(expires_at)
    issued_at = extra.get("token_issued_at")
    if isinstance(issued_at, (int, float)) and issued_at > 0:
        return int(issued_at) + int(fallback_ttl)
    return None


def seconds_left(expires_at: Optional[int], now: Optional[int] = None) -> Optional[int]:
    """距离令牌到期的剩余秒数；负数表示已过期。无信息时返回 ``None``。"""
    if not expires_at:
        return None
    return int(expires_at) - int(now if now is not None else time.time())


def token_level(seconds: Optional[int]) -> str:
    """按剩余秒数给出预警等级。"""
    if seconds is None:
        return "unknown"
    if seconds <= 0:
        return "expired"
    if seconds <= CRITICAL_SECONDS:
        return "critical"
    if seconds <= WARN_SECONDS:
        return "warning"
    return "ok"


def humanize(seconds: Optional[int]) -> str:
    """把剩余秒数转成人类可读的短描述。"""
    if seconds is None:
        return "—"
    if seconds <= 0:
        over = -seconds
        if over >= 3600:
            return f"已过期 {over // 3600} 小时"
        return f"已过期 {max(over // 60, 1)} 分钟"
    if seconds >= 86400:
        return f"剩 {seconds // 86400} 天"
    if seconds >= 3600:
        return f"剩 {seconds // 3600} 小时"
    return f"剩 {max(seconds // 60, 1)} 分钟"


def token_info(
    extra: Optional[dict],
    now: Optional[int] = None,
    fallback_ttl: int = TOKEN_TTL_ESTIMATE,
) -> dict:
    """生成单个账号的令牌有效期信息。

    返回 ``{expires_at, seconds_left, level, level_text, expiring_soon, expired,
    text, estimated}``。
    """
    extra = extra or {}
    now_ts = int(now if now is not None else time.time())
    expires_at = resolve_expires_at(extra, fallback_ttl)
    left = seconds_left(expires_at, now_ts)
    level = token_level(left)
    estimated = not bool(extra.get("token_expires_at")) and bool(
        extra.get("token_issued_at")
    )
    return {
        "expires_at": expires_at,
        "expires_at_text": (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_at))
            if expires_at
            else None
        ),
        "seconds_left": left,
        "level": level,
        "level_text": LEVEL_TEXT.get(level, "—"),
        "expiring_soon": level in ("warning", "critical", "expired"),
        "expired": level == "expired",
        "text": humanize(left),
        "estimated": estimated,
    }


__all__ = [
    "TOKEN_TTL_ESTIMATE",
    "CRITICAL_SECONDS",
    "WARN_SECONDS",
    "LEVEL_TEXT",
    "resolve_expires_at",
    "seconds_left",
    "token_level",
    "humanize",
    "token_info",
]

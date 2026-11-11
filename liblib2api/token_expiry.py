"""令牌有效期管理：以平台真实返回为准，展示剩余时间 / 在线时长与预警等级。

背景与历史教训
--------------
liblib 手机号验证码登录只会下发一个 ``access_token``，**没有 refresh_token，
也没有标准续期端点**。早期版本曾依据「某次登录后第 3 天返回未登录」的**单次观察**，
把令牌寿命**估算**成约 2.5 天，并据此在面板上展示「剩余 N 天 / 即将过期」，
甚至触发「登录令牌即将过期，请重新登录」的告警。

但实测证明该估算是**错的**：用户手动登录后稳定使用超过 30 天仍可正常调用，
平台并未按 2.5 天强制失效。那次「第 3 天未登录」更可能是当时其它 bug（登录态
校验未带 Token 头 / 会话 cookie 未持久化等）造成的假象，而非令牌真的到期。

错误估算会带来两个真实危害：

1. 面板上大量账号**长期显示「已过期 / 即将过期」**，让人误以为账号退登、被限制；
2. 后台巡检据此不断推送「登录令牌即将过期」的**误报告警**。

因此本模块**彻底不再估算令牌寿命**：平台不返回 ``expires_in`` 时，我们就诚实地说
「不知道何时到期」，改为展示中性信息「已在线 N 天」；令牌是否真的失效，由**真实
API 响应**（``401`` / 未登录）在巡检与同步时判定（见 ``webapi._is_login_expired``、
``monitor`` / ``panel_server`` 的同步逻辑），那才是唯一可靠的信号。

只有在「平台确实下发了 ``expires_at``」的极少数情况下（例如部分 OAuth 流程会带
``expires_in``），才展示精确的剩余倒计时与预警等级。
"""
from __future__ import annotations

import time
from typing import Optional

#: 严重预警阈值（秒）—— 不足 1 天即需重新登录（仅对平台真实下发的到期时间生效）
CRITICAL_SECONDS = 24 * 3600
#: 预警阈值（秒）—— 不足 3 天（仅对平台真实下发的到期时间生效）
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
    fallback_ttl: Optional[int] = None,
) -> Optional[int]:
    """从账号的 ``extra`` 中解析令牌到期时刻（秒级时间戳）。

    **只信任平台真实下发的 ``token_expires_at``**（即 ``token_expires_estimated``
    为 ``False`` 或缺失且确实给了到期值的情况）。平台未返回到期时间时返回 ``None``，
    绝不自行估算。

    ``fallback_ttl`` 为历史兼容参数，现已**不再用于推算到期**（避免再次出现
    2.5 天假到期），保留仅为了不破坏旧调用点签名。
    """
    extra = extra or {}
    # 明确标记为「估算」的到期时间是旧版硬猜的假值，一律忽略。
    if extra.get("token_expires_estimated"):
        return None
    expires_at = extra.get("token_expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0:
        return int(expires_at)
    return None


def online_seconds(extra: Optional[dict], now: Optional[int] = None) -> Optional[int]:
    """距离令牌签发时刻已过去的秒数（即「已在线多久」）。无签发时刻时返回 ``None``。"""
    extra = extra or {}
    issued = extra.get("token_issued_at")
    if not isinstance(issued, (int, float)) or issued <= 0:
        return None
    return int(now if now is not None else time.time()) - int(issued)


def seconds_left(expires_at: Optional[int], now: Optional[int] = None) -> Optional[int]:
    """距离令牌到期的剩余秒数；负数表示已过期。无信息时返回 ``None``。"""
    if not expires_at:
        return None
    return int(expires_at) - int(now if now is not None else time.time())


def token_level(seconds: Optional[int]) -> str:
    """按剩余秒数给出预警等级（仅对平台真实到期时间有意义）。"""
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
    """把剩余秒数转成人类可读的短描述（针对「还剩多久」）。"""
    if seconds is None:
        return "—"
    if seconds <= 0:
        over = -seconds
        if over >= 3600:
            return f"已过期 {-seconds // 3600} 小时"
        return f"已过期 {max(-seconds // 60, 1)} 分钟"
    if seconds >= 86400:
        return f"剩 {seconds // 86400} 天"
    if seconds >= 3600:
        return f"剩 {seconds // 3600} 小时"
    return f"剩 {max(seconds // 60, 1)} 分钟"


def humanize_online(seconds: Optional[int]) -> str:
    """把在线秒数转成人类可读的「已在线多久」短描述。"""
    if seconds is None:
        return "—"
    if seconds < 60:
        return "刚登录"
    if seconds < 3600:
        return f"在线 {seconds // 60} 分钟"
    if seconds < 86400:
        return f"在线 {seconds // 3600} 小时"
    return f"已在线 {seconds // 86400} 天"


def token_info(
    extra: Optional[dict],
    now: Optional[int] = None,
    fallback_ttl: Optional[int] = None,
) -> dict:
    """生成单个账号的令牌有效期信息。

    返回字段：
    - ``expires_at`` / ``expires_at_text``：平台真实到期时刻（无则返回 ``None``）。
    - ``seconds_left``：剩余秒数（仅平台真实到期时有意义）。
    - ``online_seconds`` / ``online_days`` / ``online_text``：已在线时长（中性信息）。
    - ``issued_at`` / ``issued_at_text``：令牌签发时刻。
    - ``level`` / ``level_text``：预警等级（无真实到期时为 ``unknown``）。
    - ``expiring_soon`` / ``expired``：仅在平台真实到期判定下为真。
    - ``estimated``：是否基于估算（现在恒为 ``False``，不再估算）。
    - ``has_expiry``：平台是否真实下发了到期时间。
    - ``text``：面板主展示文案（优先剩余倒计时；否则已在线时长）。
    """
    extra = extra or {}
    now_ts = int(now if now is not None else time.time())
    expires_at = resolve_expires_at(extra, fallback_ttl)
    left = seconds_left(expires_at, now_ts)
    level = token_level(left)
    has_expiry = expires_at is not None
    # 已在线时长（始终可展示，中性信息）
    on_sec = online_seconds(extra, now_ts)
    on_days = (on_sec // 86400) if on_sec is not None else None

    if has_expiry:
        text = humanize(left)
    else:
        text = humanize_online(on_sec)

    return {
        "expires_at": expires_at,
        "expires_at_text": (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_at))
            if expires_at
            else None
        ),
        "seconds_left": left,
        "issued_at": extra.get("token_issued_at"),
        "issued_at_text": (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(extra["token_issued_at"]))
            if isinstance(extra.get("token_issued_at"), (int, float)) and extra["token_issued_at"] > 0
            else None
        ),
        "online_seconds": on_sec,
        "online_days": on_days,
        "online_text": humanize_online(on_sec),
        "level": level,
        "level_text": LEVEL_TEXT.get(level, "—"),
        "expiring_soon": has_expiry and level in ("warning", "critical", "expired"),
        "expired": has_expiry and level == "expired",
        "estimated": False,
        "has_expiry": has_expiry,
        "text": text,
    }


__all__ = [
    "CRITICAL_SECONDS",
    "WARN_SECONDS",
    "LEVEL_TEXT",
    "resolve_expires_at",
    "online_seconds",
    "seconds_left",
    "token_level",
    "humanize",
    "humanize_online",
    "token_info",
]

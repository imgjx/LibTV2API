"""会员到期提醒：解析会员到期时间、计算剩余天数并分级。

背景
----
liblib 平台原生没有团队 / 组织功能：每位成员的账号彼此独立、会员到期时间
互不相通，临近到期时往往无人知晓，容易出现"额度突然断档"。本模块把
`member/account` 返回的 `endTime`（即 :attr:`Account.member_until`）解析成
标准时间，计算剩余天数并给出提醒等级，供统一管理面板与外部巡检使用。

等级约定
--------
- ``expired``  已过期
- ``critical`` 7 天内到期（红）
- ``warning``  30 天内到期（黄）
- ``ok``       30 天以上
- ``unknown``  账号无会员到期信息（如免费账号未识别出会员）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

#: 严重提醒阈值（天）
CRITICAL_DAYS = 7
#: 预警提醒阈值（天）
WARN_DAYS = 30

_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y.%m.%d",
)

LEVEL_TEXT = {
    "expired": "已到期",
    "critical": "即将到期",
    "warning": "临近到期",
    "ok": "正常",
    "unknown": "—",
}


def parse_member_until(raw: Any) -> Optional[datetime]:
    """把平台返回的到期时间解析为 ``datetime``；无法解析时返回 ``None``。

    兼容常见写法：毫秒 / 秒级时间戳（含字符串）、``2026-01-31 23:59:59``、
    ``2026-01-31``、ISO8601（``2026-01-31T23:59:59``）与 ``2026/01/31``。
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):  # 避免 bool 被当成 int 时间戳
        return None
    if isinstance(raw, (int, float)):
        return _from_epoch(float(raw))
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit():
        return _from_epoch(float(text))
    # ISO8601：去掉时区与毫秒部分
    normalized = text.replace("T", " ").split("+")[0].split("Z")[0].strip()
    normalized = normalized.split(".")[0].strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def _from_epoch(value: float) -> Optional[datetime]:
    """秒级 / 毫秒级时间戳 → ``datetime``。"""
    if value > 1e11:  # 毫秒级
        value = value / 1000.0
    try:
        return datetime.fromtimestamp(value)
    except (OverflowError, OSError, ValueError):
        return None


def days_left(raw: Any, now: Optional[datetime] = None) -> Optional[int]:
    """距离到期的剩余天数（按自然日计算）；无有效到期时间返回 ``None``。

    已过期返回负数（例如 -3 表示已过期 3 天）。
    """
    dt = parse_member_until(raw)
    if dt is None:
        return None
    today = (now or datetime.now()).date()
    return (dt.date() - today).days


def expiry_level(days: Optional[int]) -> str:
    """按剩余天数给出提醒等级。"""
    if days is None:
        return "unknown"
    if days < 0:
        return "expired"
    if days <= CRITICAL_DAYS:
        return "critical"
    if days <= WARN_DAYS:
        return "warning"
    return "ok"


def expiry_info(
    raw: Any,
    warn_days: int = WARN_DAYS,
    now: Optional[datetime] = None,
) -> dict:
    """生成单个账号的到期提醒信息。

    返回 ``{member_until, days_left, level, level_text, expiring_soon, expired}``。
    """
    dt = parse_member_until(raw)
    left = days_left(raw, now=now)
    level = expiry_level(left)
    if level == "unknown":
        level = "warning" if (warn_days and left is not None and left <= warn_days) else level
    return {
        "member_until": raw,
        "member_until_text": dt.strftime("%Y-%m-%d %H:%M") if dt else None,
        "days_left": left,
        "level": level,
        "level_text": LEVEL_TEXT.get(level, "—"),
        "expiring_soon": level in ("warning", "critical", "expired"),
        "expired": level == "expired",
    }


__all__ = [
    "CRITICAL_DAYS",
    "WARN_DAYS",
    "LEVEL_TEXT",
    "parse_member_until",
    "days_left",
    "expiry_level",
    "expiry_info",
]

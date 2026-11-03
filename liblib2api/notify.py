"""通知中心。

把团队运营中需要「主动找人」的事件，通过多个通道推送给管理员：

* **邮件**（SMTP）：适合每日摘要与重要告警。
* **企业微信机器人 Webhook**：适合即时提醒（会员到期、账号失效、额度超限）。
* **控制台日志**：兜底通道，便于本地排查。

设计要点
--------
* 通道可独立启停，配置集中存放在 ``settings.json`` 的 ``notify`` 段。
* 告警规则（阈值）可配置，例如「算力点低于 100 时提醒」「成员额度使用率超过 90% 时提醒」。
* 相同事件在静默期内只通知一次，避免刷屏。
* 通知失败不会影响主流程，失败原因记录在发送历史里。
"""
from __future__ import annotations

import json
import smtplib
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

import liblib2api.config as cfg

# 事件类型
EVENT_MEMBER_EXPIRING = "member_expiring"      # 会员即将到期
EVENT_MEMBER_EXPIRED = "member_expired"        # 会员已到期
EVENT_ACCOUNT_INVALID = "account_invalid"      # 账号失效
EVENT_POINTS_LOW = "points_low"                # 算力点余额偏低
EVENT_QUOTA_NEAR_LIMIT = "quota_near_limit"    # 成员额度接近上限
EVENT_QUOTA_EXHAUSTED = "quota_exhausted"      # 成员额度已用尽
EVENT_CLAIM_FAILED = "claim_failed"            # 当日权益领取失败
EVENT_DAILY_DIGEST = "daily_digest"            # 每日摘要

EVENT_LABELS = {
    EVENT_MEMBER_EXPIRING: "会员即将到期",
    EVENT_MEMBER_EXPIRED: "会员已到期",
    EVENT_ACCOUNT_INVALID: "账号失效",
    EVENT_POINTS_LOW: "算力点余额偏低",
    EVENT_QUOTA_NEAR_LIMIT: "成员额度接近上限",
    EVENT_QUOTA_EXHAUSTED: "成员额度已用尽",
    EVENT_CLAIM_FAILED: "当日权益领取失败",
    EVENT_DAILY_DIGEST: "每日摘要",
}

# 默认阈值
DEFAULT_RULES: dict[str, dict] = {
    EVENT_MEMBER_EXPIRING: {"enabled": True, "days": 30},
    EVENT_MEMBER_EXPIRED: {"enabled": True},
    EVENT_ACCOUNT_INVALID: {"enabled": True},
    EVENT_POINTS_LOW: {"enabled": True, "threshold": 100},
    EVENT_QUOTA_NEAR_LIMIT: {"enabled": True, "percent": 90},
    EVENT_QUOTA_EXHAUSTED: {"enabled": True},
    EVENT_CLAIM_FAILED: {"enabled": True},
    EVENT_DAILY_DIGEST: {"enabled": False, "hour": 20},
}


@dataclass
class NotifyMessage:
    """一条待发送的通知。"""

    event: str
    title: str
    body: str = ""
    level: str = "info"          # info | warning | critical
    links: list[str] = field(default_factory=list)
    dedup_key: str = ""

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "event_label": EVENT_LABELS.get(self.event, self.event),
            "title": self.title,
            "body": self.body,
            "level": self.level,
            "links": self.links,
            "dedup_key": self.dedup_key,
        }


@dataclass
class SendRecord:
    """一次发送的结果记录。"""

    id: str
    at: int
    channel: str
    event: str
    title: str
    ok: bool
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "at": self.at,
            "channel": self.channel,
            "event": self.event,
            "event_label": EVENT_LABELS.get(self.event, self.event),
            "title": self.title,
            "ok": self.ok,
            "error": self.error,
        }


class EmailChannel:
    """SMTP 邮件通道。"""

    name = "email"

    def __init__(self, cfgd: dict):
        self.host = cfgd.get("smtp_host", "")
        self.port = int(cfgd.get("smtp_port") or 465)
        self.user = cfgd.get("smtp_user", "")
        self.password = cfgd.get("smtp_password", "")
        self.sender = cfgd.get("sender") or self.user
        self.receivers = [r for r in (cfgd.get("receivers") or []) if r]
        self.use_ssl = bool(cfgd.get("use_ssl", True))
        # 是否使用 STARTTLS（use_ssl=False 时生效）；显式配置优先
        self.starttls = bool(cfgd.get("starttls", not self.use_ssl))
        # 是否强制要求 SMTP 认证（内网自建邮件服务可关闭）
        self.require_login = bool(cfgd.get("require_login", True))
        self.timeout = int(cfgd.get("timeout") or 15)

    @property
    def configured(self) -> bool:
        return bool(self.host and self.receivers)

    def send(self, msg: NotifyMessage) -> tuple[bool, str]:
        if not self.configured:
            return False, "邮件通道未配置（SMTP 主机或收件人为空）"
        subject = Header(f"[LibTV-Team] {msg.title}", "utf-8")
        mime = MIMEText(msg.body or msg.title, "plain", "utf-8")
        mime["Subject"] = subject
        mime["From"] = self.sender
        mime["To"] = ", ".join(self.receivers)
        try:
            if self.use_ssl:
                ctx = ssl.create_default_context()
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=ctx)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                if self.starttls:
                    try:
                        server.starttls(context=ssl.create_default_context())
                    except Exception:  # noqa: BLE001
                        # 服务器不支持 STARTTLS 时降级为明文（仅限内网自建邮件服务）
                        pass
            try:
                if self.user and self.password:
                    try:
                        server.login(self.user, self.password)
                    except Exception as e:  # noqa: BLE001
                        # 部分内网邮件服务无需认证
                        if self.require_login:
                            return False, f"邮件登录失败：{e}"
                server.sendmail(self.sender, self.receivers, mime.as_string())
            finally:
                try:
                    server.quit()
                except Exception:  # noqa: BLE001
                    pass
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, f"邮件发送失败：{e}"


class WeComWebhookChannel:
    """企业微信群机器人 Webhook 通道。"""

    name = "wecom"

    def __init__(self, cfgd: dict):
        self.url = (cfgd.get("webhook_url") or "").strip()
        self.timeout = int(cfgd.get("timeout") or 10)
        self.mentioned = [m for m in (cfgd.get("mentioned") or []) if m]

    @property
    def configured(self) -> bool:
        return self.url.startswith("http")

    def send(self, msg: NotifyMessage) -> tuple[bool, str]:
        if not self.configured:
            return False, "企业微信通道未配置（Webhook 地址为空）"
        level_map = {"info": "info", "warning": "warning", "critical": "error"}
        lines = [f"**{msg.title}**", msg.body or ""]
        if msg.links:
            lines.append("相关链接：")
            lines.extend(f"- {link}" for link in msg.links)
        payload: dict[str, Any] = {
            "msgtype": "markdown",
            "markdown": {
                "content": "\n".join(lines),
                "mentioned_list": self.mentioned,
            },
        }
        try:
            resp = httpx.post(self.url, json=payload, timeout=self.timeout)
            data = resp.json()
            if resp.status_code != 200 or data.get("errcode") not in (0, None):
                return False, f"企业微信返回异常：HTTP {resp.status_code} {data}"
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, f"企业微信发送失败：{e}"


class ConsoleChannel:
    """控制台通道（兜底，始终可用）。"""

    name = "console"

    def __init__(self, cfgd: Optional[dict] = None):
        self.enabled = True

    @property
    def configured(self) -> bool:
        return True

    def send(self, msg: NotifyMessage) -> tuple[bool, str]:
        prefix = {"info": "[信息]", "warning": "[警告]", "critical": "[严重]"}.get(msg.level, "[信息]")
        print(f"{prefix} {msg.title} | {msg.body}".strip())
        return True, ""


class NotifyCenter:
    """通知中心：管理通道、规则、发送历史与去重。"""

    def __init__(self, settings_getter: Callable[[], dict], settings_setter: Callable[[dict], None]):
        self._get = settings_getter
        self._set = settings_setter
        self._lock = threading.Lock()
        self.history: list[SendRecord] = []

    # ----- 配置 -----
    @property
    def config(self) -> dict:
        cfgd = dict(self._get().get("notify") or {})
        cfgd.setdefault("email", {})
        cfgd.setdefault("wecom", {})
        cfgd.setdefault("console", {})
        cfgd.setdefault("rules", {})
        cfgd.setdefault("quiet_hours", {})
        return cfgd

    def save_config(self, cfgd: dict) -> None:
        s = self._get()
        s["notify"] = cfgd
        self._set(s)

    def rules(self) -> dict:
        r = dict(DEFAULT_RULES)
        r.update(self.config.get("rules") or {})
        return r

    def update_rule(self, event: str, values: dict) -> dict:
        s = self._get()
        notify = dict(s.get("notify") or {})
        rules = dict(notify.get("rules") or {})
        base = dict(DEFAULT_RULES.get(event, {"enabled": False}))
        base.update(rules.get(event) or {})
        base.update(values or {})
        rules[event] = base
        notify["rules"] = rules
        s["notify"] = notify
        self._set(s)
        return base

    # ----- 通道 -----
    def _channels(self) -> list:
        c = self.config
        out = []
        if c.get("email", {}).get("enabled"):
            out.append(EmailChannel(c.get("email") or {}))
        if c.get("wecom", {}).get("enabled"):
            out.append(WeComWebhookChannel(c.get("wecom") or {}))
        if c.get("console", {}).get("enabled", True):
            out.append(ConsoleChannel())
        return out

    def channel_status(self) -> list[dict]:
        c = self.config
        items = []
        for label, obj in (
            ("email", EmailChannel(c.get("email") or {})),
            ("wecom", WeComWebhookChannel(c.get("wecom") or {})),
            ("console", ConsoleChannel()),
        ):
            items.append({
                "name": label,
                "label": {"email": "邮件", "wecom": "企业微信机器人", "console": "控制台"}[label],
                "enabled": bool((c.get(label) or {}).get("enabled", label == "console")),
                "configured": obj.configured,
            })
        return items

    # ----- 去重 / 静默 -----
    def _dedup_hit(self, key: str) -> bool:
        if not key:
            return False
        quiet = int(self.config.get("quiet_hours", {}).get("dedup_seconds") or 3600)
        now = int(time.time())
        seen = self._get().get("notify_seen") or {}
        last = int(seen.get(key) or 0)
        if now - last < quiet:
            return True
        seen[key] = now
        s = self._get()
        s["notify_seen"] = seen
        self._set(s)
        return False

    # ----- 发送 -----
    def send(self, msg: NotifyMessage, force: bool = False) -> list[SendRecord]:
        """按已启用的通道发送一条通知，返回各通道结果。"""
        if not force and self._dedup_hit(msg.dedup_key or f"{msg.event}:{msg.title}"):
            return []
        records: list[SendRecord] = []
        for ch in self._channels():
            ok, err = ch.send(msg)
            rec = SendRecord(
                id=uuid.uuid4().hex[:10],
                at=int(time.time()),
                channel=ch.name,
                event=msg.event,
                title=msg.title,
                ok=ok,
                error=err,
            )
            records.append(rec)
        with self._lock:
            self.history = (records + self.history)[:200]
        return records

    def test(self, channel: str = "") -> list[SendRecord]:
        """发送一条测试通知。"""
        msg = NotifyMessage(
            event="test",
            title="LibTV-Team 通知测试",
            body="这是一条来自 LibTV-Team 的测试通知，收到即表示通道配置正确。",
            level="info",
        )
        if channel:
            chs = [c for c in self._channels() if c.name == channel]
            if not chs:
                return []
            records = []
            for ch in chs:
                ok, err = ch.send(msg)
                records.append(SendRecord(
                    id=uuid.uuid4().hex[:10], at=int(time.time()), channel=ch.name,
                    event=msg.event, title=msg.title, ok=ok, error=err))
            with self._lock:
                self.history = (records + self.history)[:200]
            return records
        return self.send(msg, force=True)

    def history_list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self.history[:limit]]

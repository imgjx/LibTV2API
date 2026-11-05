"""多账号管理。

一个团队往往有多个 liblib 账号（各自买额度包），因此需要：
  * 每个账号独立保存凭据、昵称、会员等级、积分余额
  * 每个账号可绑定独立代理 IP
  * 账号可批量导入 / 导出（JSON 文件）
  * 支持轮询（round-robin）与指定账号调用

数据落在 ~/.libtv/accounts.json（权限 0600），也可通过 LIBTV_HOME 覆盖。
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, Optional

import liblib2api.config as cfg
from liblib2api.credentials import Credentials


@dataclass
class Account:
    """一个 liblib 账号。"""

    # 账号标识（手机号 / 微信昵称），主键
    account: str
    access_token: str
    # token 类型：phone | wechat
    login_method: str = "phone"
    # Web API 必需的 Webid（客户端生成，随 token 一起使用）
    webid: Optional[str] = None
    # 展示用昵称
    nickname: Optional[str] = None
    # liblib 用户 id / uuid
    user_id: Optional[str] = None
    uuid: Optional[str] = None
    # 会员等级 / 套餐名
    member_name: Optional[str] = None
    account_level: Optional[int] = None
    # 账号类型（导入/同步时自动识别）：member（会员）| free（非会员/免费）| unknown
    account_type: Optional[str] = None
    # 是否副卡（子账号）：会员主账号下的共享额度副卡
    is_sub: bool = False
    # 主账号 uuid / 类型（来自 member/account 的 ownerUuid / ownerType）
    owner_uuid: Optional[str] = None
    owner_type: Optional[str] = None
    # 会员到期时间（member/account 的 endTime，字符串）
    member_until: Optional[str] = None
    # 套餐类型（packageType）
    package_type: Optional[str] = None
    # 每日免费算力（LibTV freePower）
    free_power: Optional[float] = None
    # 每日免费算力总额 / 已用（用于面板展示）
    daily_free_power_total: Optional[float] = None
    daily_free_power_used: Optional[float] = None
    # 每日是否已领取免费算力（hasGetPower）
    has_get_power: Optional[bool] = None
    # 积分（算力）余额，单位：点
    points: Optional[float] = None
    # 该账号专属代理，例如 http://user:pass@ip:port
    proxy: Optional[str] = None
    # 状态：active | disabled | expired | error
    status: str = "active"
    # 备注：如「视频组·张三 的账号」
    note: str = ""
    # 所属团队 ID（平台原生无团队功能，这里做统一纳管）
    team_id: Optional[str] = None
    # 所属成员 ID（团队内的自然人，可对其设置额度限制）
    member_id: Optional[str] = None
    # 时间戳
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    # 最后一次积分刷新时间
    last_sync: Optional[int] = None
    # 最后一次权益领取时间（日期字符串 YYYY-MM-DD）
    last_claim: Optional[str] = None
    # 最后一次活性检查（user_info 探测）时间
    last_alive_check: Optional[int] = None
    # 活性：是否仍可正常调用；None 表示尚未检查过
    alive: Optional[bool] = None
    # 最近一次活性检查/失败原因
    alive_error: Optional[str] = None
    # 登录态是否已过期（平台拒绝当前 token）。这与「账号被限制」是两回事：
    # 账号本身仍在登录，重新获取 token 后即可继续使用，故单独标记以便引导重新登录。
    auth_expired: bool = False
    # 调用计数（用于均衡策略）
    request_count: int = 0
    # 错误计数
    error_count: int = 0
    # 最近一次错误时间
    last_error_at: Optional[int] = None
    # 最近一次被使用时间（用于 least-recently-used 策略）
    last_used_at: Optional[int] = None
    # 每个模型 key 的可用性缓存（true=可用，false=已知不可用）
    # 经同步时计算 + 运行时学习（生成被拒时写入）得到
    model_usable: dict = field(default_factory=dict)
    # 扩展字段
    extra: dict = field(default_factory=dict)

    def to_credentials(self) -> Credentials:
        return Credentials(
            access_token=self.access_token,
            token_type="Bearer",
            refresh_token=self.extra.get("refresh_token"),
            expires_at=self.extra.get("expires_at"),
            scope=self.extra.get("scope"),
            login_method=self.login_method,
            account=self.account,
            issuer=cfg.WEB_API_BASE,
            token_endpoint=None,
            extra={
                "webid": self.webid,
                "nickname": self.nickname,
                "user_id": self.user_id,
                "uuid": self.uuid,
                "proxy": self.proxy,
                "cookies": self.extra.get("cookies") or {},
                "cid": self.extra.get("cid"),
            },
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        data = dict(data)
        extra = data.pop("extra", {}) or {}
        # 兼容历史字段名：签到 → 权益领取
        if "last_checkin" in data:
            data.setdefault("last_claim", data.get("last_checkin"))
            data.pop("last_checkin", None)
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["extra"] = extra
        return cls(**kwargs)

    # ----- 兼容别名 -----
    @property
    def last_checkin(self) -> Optional[str]:
        """历史别名：等价于 :attr:`last_claim`（最后一次权益领取时间）。"""
        return self.last_claim

    @property
    def remark(self) -> str:
        """备注（等价于 :attr:`note`）。"""
        return self.note

    # ----- 类型 / 可用性辅助 -----
    def is_member(self) -> bool:
        """是否会员账号（会员主卡或副卡）。"""
        if self.account_type == "member":
            return True
        if self.account_type in (None, "unknown") and self.member_name:
            return "会员" in (self.member_name or "")
        return False

    def can_use(self, model_key: Optional[str]) -> bool:
        """该账号是否可用指定模型（model_key 可为 key 或模型名）。

        规则：
          - 未记录过 → 乐观返回 True（不阻塞，交由运行时学习）
          - 已记录为 False → 直接返回 False
          - 会员账号对所有模型视为可用（模型本身限制之外）
        """
        if self.is_member():
            return True
        if not model_key:
            return True
        if model_key in self.model_usable:
            return bool(self.model_usable[model_key])
        return True

    def mark_model_usable(self, model_key: str, usable: bool) -> None:
        if model_key:
            self.model_usable[str(model_key)] = bool(usable)

    def record_usage(self) -> None:
        self.request_count += 1
        self.last_used_at = int(time.time())

    def record_error(self) -> None:
        self.error_count += 1
        self.last_error_at = int(time.time())

    def mark_alive(self, ok: bool, error: Optional[str] = None) -> None:
        self.alive = ok
        self.alive_error = error
        self.last_alive_check = int(time.time())
        if not ok:
            self.record_error()


class AccountStore:
    """多账号仓库：线程安全，读写 accounts.json。"""

    def __init__(self, path: Path | str = cfg.ACCOUNTS_FILE):
        self.path = Path(path)
        self._accounts: dict[str, Account] = {}
        self._lock = threading.RLock()
        self._rr_index = 0
        self.load()

    # ----- 持久化 -----
    def load(self) -> None:
        with self._lock:
            self._accounts = {}
            if not self.path.exists():
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError):
                return
            items = raw.get("accounts") if isinstance(raw, dict) else raw
            for item in items or []:
                try:
                    acc = Account.from_dict(item)
                    self._accounts[self._key(acc)] = acc
                except Exception:
                    continue

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "accounts": [a.to_dict() for a in self._accounts.values()]}
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.chmod(self.path, 0o600)

    @staticmethod
    def _key(acc: Account) -> str:
        return str(acc.account or acc.uuid or acc.nickname or "")

    # ----- CRUD -----
    def add(self, account: Account, save: bool = True) -> Account:
        with self._lock:
            account.updated_at = int(time.time())
            self._accounts[self._key(account)] = account
            if save:
                self.save()
            return account

    def remove(self, account: str) -> bool:
        with self._lock:
            key = str(account)
            if key in self._accounts:
                del self._accounts[key]
                self.save()
                return True
            return False

    def get(self, account: str) -> Optional[Account]:
        with self._lock:
            return self._accounts.get(str(account))

    def list(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    def update(self, account: str, **fields) -> Optional[Account]:
        with self._lock:
            acc = self._accounts.get(str(account))
            if not acc:
                return None
            for k, v in fields.items():
                if hasattr(acc, k):
                    setattr(acc, k, v)
            acc.updated_at = int(time.time())
            self.save()
            return acc

    def set_proxy(self, account: str, proxy: Optional[str]) -> Optional[Account]:
        """给指定账号绑定代理（传 None 清除）。"""
        return self.update(account, proxy=proxy or None)

    # ----- 轮询选取 -----
    def next_round_robin(self, only_active: bool = True) -> Optional[Account]:
        """取下一个可用账号（轮询，均摊团队额度）。"""
        with self._lock:
            candidates = [
                a for a in self._accounts.values()
                if not only_active or (a.status == "active" and a.access_token)
            ]
            if not candidates:
                return None
            acc = candidates[self._rr_index % len(candidates)]
            self._rr_index = (self._rr_index + 1) % len(candidates)
            return acc

    def __iter__(self) -> Iterator[Account]:
        return iter(self.list())

    def __len__(self) -> int:
        return len(self._accounts)

    # ----- 导入 / 导出 -----
    def export(self, path: Path | str | None = None, include_disabled: bool = True) -> str:
        """导出为 JSON 字符串（或写入文件），返回 JSON 文本。"""
        accounts = [a.to_dict() for a in self.list()
                    if include_disabled or a.status == "active"]
        payload = {
            "version": 1,
            "exported_at": int(time.time()),
            "accounts": accounts,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            os.chmod(p, 0o600)
        return text

    def import_accounts(self, data: str | Path, overwrite: bool = False) -> dict:
        """导入账号。可传 JSON 文本或文件路径。

        返回 {"imported": n, "skipped": n, "updated": n}。
        """
        if isinstance(data, Path) or (isinstance(data, str) and not data.strip().startswith(("{", "["))):
            text = Path(data).read_text(encoding="utf-8")
        else:
            text = str(data)
        raw = json.loads(text)
        items = raw.get("accounts") if isinstance(raw, dict) else raw
        imported = skipped = updated = 0
        for item in items or []:
            try:
                acc = Account.from_dict(item)
                if not acc.account or not acc.access_token:
                    skipped += 1
                    continue
                key = self._key(acc)
                with self._lock:
                    if key in self._accounts:
                        if not overwrite:
                            skipped += 1
                            continue
                        # 保留原有的代理与备注（导入不覆盖本机配置）
                        old = self._accounts[key]
                        acc.proxy = acc.proxy or old.proxy
                        acc.note = acc.note or old.note
                        acc.created_at = old.created_at
                        # last_checkin 是只读属性（等价于 last_claim），必须写实际字段，
                        # 否则覆盖导入会抛 AttributeError 并中断整个导入。
                        acc.last_claim = old.last_claim
                        self._accounts[key] = acc
                        updated += 1
                    else:
                        self._accounts[key] = acc
                        imported += 1
            except Exception:
                skipped += 1
                continue
        self.save()
        return {"imported": imported, "skipped": skipped, "updated": updated}

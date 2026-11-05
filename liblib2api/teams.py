"""团队与成员管理。

背景
----
liblib 平台原生没有团队 / 组织功能：每位成员的账号彼此独立、额度互不相通、
会员到期时间互不知晓。本模块在账号池之上补一层「团队 — 成员」结构，
用于统一纳管团队成员账号、限制成员额度、追踪用量与到期提醒。

概念
----
* **团队**（Team）：一个协作单位，如「视频组」。
* **成员**（Member）：团队内的自然人，如「张三」，可绑定多个自己的账号。
* **额度限制**（quota）：成员每日可消耗的算力点上限；``None`` 表示不限制。
  用量按自然日重置，跨天自动清零。

数据落在 ``~/.libtv/teams.json``（权限 0600），可通过 ``LIBTV_HOME`` 覆盖。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import liblib2api.config as cfg


def _today() -> str:
    return date.today().isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Member:
    """团队内的一个成员（自然人），可绑定多个账号。"""

    id: str
    name: str
    team_id: str
    # 备注：如「张三团队成员的账号」
    note: str = ""
    # 每日额度上限（算力点）；None = 不限制
    quota_limit: Optional[float] = None
    # 今日已用额度（算力点）
    quota_used: float = 0.0
    # 用量所属日期（YYYY-MM-DD），用于跨天重置
    quota_reset_date: Optional[str] = None
    # 绑定的账号标识列表
    account_ids: list[str] = field(default_factory=list)
    # 成员在平台侧的身份标识（可选，如成员的手机号/昵称）
    identity: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    # ----- 额度相关 -----
    def rollover(self, today: Optional[str] = None) -> None:
        """跨天重置用量。"""
        today = today or _today()
        if self.quota_reset_date != today:
            self.quota_reset_date = today
            self.quota_used = 0.0

    @property
    def quota_unlimited(self) -> bool:
        return self.quota_limit is None

    def quota_remaining(self) -> Optional[float]:
        """剩余额度；不限额时返回 None。"""
        if self.quota_limit is None:
            return None
        return max(0.0, float(self.quota_limit) - float(self.quota_used))

    def quota_exhausted(self) -> bool:
        """额度是否已用尽（不限额时恒为 False）。"""
        if self.quota_limit is None:
            return False
        return float(self.quota_used) >= float(self.quota_limit)

    def consume(self, points: float) -> None:
        """记账：累加今日已用额度。"""
        self.rollover()
        self.quota_used = round(float(self.quota_used) + float(points), 4)
        self.updated_at = int(time.time())

    def to_dict(self) -> dict:
        data = asdict(self)
        data["quota_remaining"] = self.quota_remaining()
        data["quota_unlimited"] = self.quota_unlimited
        data["quota_exhausted"] = self.quota_exhausted()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Member":
        data = dict(data)
        known = {f for f in cls.__dataclass_fields__}
        # 派生字段（只读属性）不入库，避免覆盖同名方法
        for derived in ("quota_remaining", "quota_unlimited", "quota_exhausted"):
            data.pop(derived, None)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Team:
    """一个团队（协作单位）。"""

    id: str
    name: str
    note: str = ""
    member_ids: list[str] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Team":
        data = dict(data)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class TeamStore:
    """团队与成员仓库：线程安全，读写 teams.json。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or cfg.TEAMS_FILE)
        self._teams: dict[str, Team] = {}
        self._members: dict[str, Member] = {}
        self._lock = threading.RLock()
        self.load()

    # ----- 持久化 -----
    def load(self) -> None:
        with self._lock:
            self._teams, self._members = {}, {}
            if not self.path.exists():
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            for item in raw.get("teams") or []:
                try:
                    team = Team.from_dict(item)
                    self._teams[team.id] = team
                except Exception:
                    continue
            for item in raw.get("members") or []:
                try:
                    member = Member.from_dict(item)
                    self._members[member.id] = member
                except Exception:
                    continue

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "teams": [t.to_dict() for t in self._teams.values()],
                "members": [m.to_dict() for m in self._members.values()],
            }
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.chmod(self.path, 0o600)

    # ----- 团队 CRUD -----
    def list_teams(self) -> list[Team]:
        with self._lock:
            return list(self._teams.values())

    def get_team(self, team_id: str) -> Optional[Team]:
        with self._lock:
            return self._teams.get(str(team_id))

    def add_team(self, name: str, note: str = "", team_id: Optional[str] = None) -> Team:
        with self._lock:
            team = Team(id=team_id or _new_id("team"), name=name, note=note)
            self._teams[team.id] = team
            self.save()
            return team

    def update_team(self, team_id: str, **fields) -> Optional[Team]:
        with self._lock:
            team = self._teams.get(str(team_id))
            if not team:
                return None
            for k, v in fields.items():
                if hasattr(team, k):
                    setattr(team, k, v)
            team.updated_at = int(time.time())
            self.save()
            return team

    def remove_team(self, team_id: str) -> bool:
        """删除团队（连带其成员与账号绑定关系）。"""
        with self._lock:
            team = self._teams.pop(str(team_id), None)
            if not team:
                return False
            # 成员随团队一并移除；账号侧的归属由调用方（API 层）统一清理。
            for mid in list(team.member_ids):
                self._members.pop(mid, None)
            self.save()
            return True

    # ----- 成员 CRUD -----
    def list_members(self, team_id: Optional[str] = None) -> list[Member]:
        with self._lock:
            members = list(self._members.values())
            if team_id is not None:
                members = [m for m in members if m.team_id == str(team_id)]
            return members

    def get_member(self, member_id: str) -> Optional[Member]:
        with self._lock:
            return self._members.get(str(member_id))

    def add_member(
        self,
        team_id: str,
        name: str,
        note: str = "",
        quota_limit: Optional[float] = None,
        identity: Optional[str] = None,
        member_id: Optional[str] = None,
    ) -> Optional[Member]:
        with self._lock:
            team = self._teams.get(str(team_id))
            if not team:
                return None
            member = Member(
                id=member_id or _new_id("member"),
                name=name,
                team_id=team.id,
                note=note,
                quota_limit=quota_limit,
                identity=identity,
                quota_reset_date=_today(),
            )
            self._members[member.id] = member
            if member.id not in team.member_ids:
                team.member_ids.append(member.id)
            team.updated_at = int(time.time())
            self.save()
            return member

    def update_member(self, member_id: str, **fields) -> Optional[Member]:
        with self._lock:
            member = self._members.get(str(member_id))
            if not member:
                return None
            for k, v in fields.items():
                if hasattr(member, k):
                    setattr(member, k, v)
            member.rollover()
            member.updated_at = int(time.time())
            self.save()
            return member

    def remove_member(self, member_id: str) -> bool:
        with self._lock:
            member = self._members.pop(str(member_id), None)
            if not member:
                return False
            team = self._teams.get(member.team_id)
            if team and member.id in team.member_ids:
                team.member_ids.remove(member.id)
            self.save()
            return True

    # ----- 账号绑定 -----
    def bind_account(self, account: str, member_id: str) -> Optional[Member]:
        """把账号绑定到成员（自动从旧成员解绑）。"""
        with self._lock:
            member = self._members.get(str(member_id))
            if not member:
                return None
            for other in self._members.values():
                if other.id != member.id and account in other.account_ids:
                    other.account_ids.remove(account)
            if account not in member.account_ids:
                member.account_ids.append(account)
            member.updated_at = int(time.time())
            self.save()
            return member

    def unbind_account(self, account: str) -> None:
        with self._lock:
            for member in self._members.values():
                if account in member.account_ids:
                    member.account_ids.remove(account)
            self.save()

    def member_of_account(self, account: str) -> Optional[Member]:
        with self._lock:
            for member in self._members.values():
                if account in member.account_ids:
                    return member
            return None

    # ----- 额度记账 -----
    def consume(self, account: str, points: float) -> Optional[Member]:
        """按账号所属成员记账消耗额度。"""
        with self._lock:
            member = self.member_of_account(account)
            if not member:
                return None
            member.consume(points)
            self.save()
            return member

    def quota_status(self) -> list[dict]:
        """所有成员的额度概览（含超限标记）。"""
        with self._lock:
            out = []
            for member in self._members.values():
                member.rollover()
                team = self._teams.get(member.team_id)
                data = member.to_dict()
                data["team_name"] = team.name if team else None
                out.append(data)
            return out

    def __len__(self) -> int:
        return len(self._members)


__all__ = ["Member", "Team", "TeamStore"]

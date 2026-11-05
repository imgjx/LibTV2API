"""团队用量与算力点统计。

面向团队管理场景，把账号池与成员额度汇总成可观测的视图：

* **总览**：账号数、会员数、算力点余额、免费算力总额、可用模型覆盖率。
* **成员维度**：每人名下账号数、算力点合计、今日额度用量与使用率。
* **账号维度**：调用次数、错误次数、最近使用时间、算力点余额排序。
* **健康度**：失效账号数、临近到期账号数、额度用尽成员数。

统计只做本地聚合，不产生任何额外平台请求。
"""
from __future__ import annotations

import time
from typing import Optional

from liblib2api.accounts import AccountStore
from liblib2api.expiry import expiry_info
from liblib2api.teams import TeamStore


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _member_label(m) -> str:
    return f"{m.team_name or ''}·{m.name}".strip("·") if m else ""


def team_overview(
    store: AccountStore,
    team_store: Optional[TeamStore] = None,
    warn_days: int = 30,
) -> dict:
    """团队总览指标。"""
    accounts = store.list()
    total_points = sum(_num(a.points) for a in accounts)
    total_free = sum(_num(a.free_power) for a in accounts)
    vip = sum(1 for a in accounts if a.account_type == "member")
    free = sum(1 for a in accounts if a.account_type == "free")
    alive = sum(1 for a in accounts if a.alive is True)
    dead = sum(1 for a in accounts if a.alive is False)
    expiring = 0
    expired = 0
    for a in accounts:
        info = expiry_info(a.member_until, warn_days=warn_days)
        if info.get("expired"):
            expired += 1
        elif info.get("days_left") is not None and info["days_left"] <= warn_days:
            expiring += 1
    usable_total = sum(len(a.model_usable or {}) for a in accounts)
    usable_ok = sum(sum(1 for v in (a.model_usable or {}).values() if v) for a in accounts)
    quota_exhausted = 0
    if team_store is not None:
        quota_exhausted = sum(1 for m in team_store.list_members() if m.quota_exhausted())
    return {
        "accounts": len(accounts),
        "vip_accounts": vip,
        "free_accounts": free,
        "alive_accounts": alive,
        "invalid_accounts": dead,
        "expiring_accounts": expiring,
        "expired_accounts": expired,
        "total_points": round(total_points, 2),
        "total_free_power": round(total_free, 2),
        "model_usable": usable_ok,
        "model_total": usable_total,
        "quota_exhausted_members": quota_exhausted,
        "generated_at": int(time.time()),
    }


def member_stats(store: AccountStore, team_store: TeamStore) -> list[dict]:
    """按成员聚合：名下账号、算力点合计、今日额度用量与使用率。"""
    items = []
    for m in team_store.list_members():
        m.rollover()
        t = team_store.get_team(m.team_id)
        team_name = t.name if t else ""
        accs = [a for a in store.list() if a.member_id == m.id]
        points = sum(_num(a.points) for a in accs)
        free = sum(_num(a.free_power) for a in accs)
        limit = m.quota_limit
        used = _num(m.quota_used)
        rate = round(used / limit * 100, 1) if limit else None
        items.append({
            "member_id": m.id,
            "name": m.name,
            "team_id": m.team_id,
            "team_name": team_name,
            "note": m.note,
            "identity": m.identity,
            "accounts": len(accs),
            "account_list": [a.account for a in accs],
            "points": round(points, 2),
            "free_power": round(free, 2),
            "quota_limit": limit,
            "quota_used": round(used, 2),
            "quota_remaining": m.quota_remaining(),
            "quota_unlimited": m.quota_unlimited,
            "quota_exhausted": m.quota_exhausted(),
            "quota_percent": rate,
            "request_count": sum(a.request_count for a in accs),
            "error_count": sum(a.error_count for a in accs),
            "updated_at": m.updated_at,
        })
    items.sort(key=lambda x: (-(_num(x["points"])), x["name"]))
    return items


def account_stats(store: AccountStore, team_store: Optional[TeamStore] = None) -> list[dict]:
    """按账号聚合的运营指标。"""
    items = []
    for a in store.list():
        info = expiry_info(a.member_until, warn_days=30)
        member_name = ""
        if team_store is not None and a.member_id:
            m = team_store.get_member(a.member_id)
            if m is not None:
                t = team_store.get_team(m.team_id)
                member_name = f"{t.name if t else ''}·{m.name}".strip("·")
        items.append({
            "account": a.account,
            "nickname": a.nickname,
            "account_type": a.account_type,
            "member_name": member_name,
            "note": a.note,
            "points": _num(a.points),
            "free_power": _num(a.free_power),
            "alive": a.alive,
            "alive_error": a.alive_error,
            "member_until": a.member_until,
            "days_left": info.get("days_left"),
            "expiry_level": info.get("level"),
            "expiry_level_text": info.get("level_text"),
            "request_count": a.request_count,
            "error_count": a.error_count,
            "last_used_at": a.last_used_at,
            "last_claim": a.last_claim,
            "model_usable_count": sum(1 for v in (a.model_usable or {}).values() if v),
            "model_total_count": len(a.model_usable or {}),
        })
    items.sort(key=lambda x: -_num(x["points"]))
    return items


def team_stats(
    store: AccountStore,
    team_store: Optional[TeamStore] = None,
    warn_days: int = 30,
) -> dict:
    """完整统计包，供面板与 API 使用。"""
    data = {
        "overview": team_overview(store, team_store, warn_days),
        "members": member_stats(store, team_store) if team_store is not None else [],
        "accounts": account_stats(store, team_store),
    }
    if team_store is not None:
        data["teams"] = [
            {
                "id": t.id,
                "name": t.name,
                "note": t.note,
                "members": len(team_store.list_members(t.id)),
                "accounts": sum(
                    1 for a in store.list()
                    if a.team_id == t.id
                ),
                "points": round(
                    sum(_num(a.points) for a in store.list() if a.team_id == t.id), 2
                ),
            }
            for t in team_store.list_teams()
        ]
    return data

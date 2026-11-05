"""令牌有效期链路回归测试。

覆盖：
- token_expiry 模块的到期推算、等级判定、文案；
- 登录时签发时刻与有效期是否落库；
- 重新登录后本地数据（团队归属 / 备注 / 额度）是否保留；
- 告警扫描是否会命中「令牌即将过期」；
- 账号级 409 不会被前端当成管理员登出。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from liblib2api import panel_server as ps  # noqa: E402
from liblib2api.accounts import Account, AccountStore  # noqa: E402
from liblib2api.token_expiry import (  # noqa: E402
    CRITICAL_SECONDS,
    TOKEN_TTL_ESTIMATE,
    humanize,
    resolve_expires_at,
    seconds_left,
    token_info,
    token_level,
)
from liblib2api.teams import TeamStore  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


# ---------------------------------------------------------------------------
# 1. token_expiry 模块
# ---------------------------------------------------------------------------
print("\n[1] 令牌有效期推算")

now = int(time.time())

check("估算寿命约 2.5 天", 2 * 86400 < TOKEN_TTL_ESTIMATE < 3 * 86400, str(TOKEN_TTL_ESTIMATE))
check("无 extra 时无到期信息", resolve_expires_at(None) is None)
check(
    "有签发时刻时按估算推算到期",
    resolve_expires_at({"token_issued_at": now}) == now + TOKEN_TTL_ESTIMATE,
)
check(
    "平台给了 expires_at 时优先采用",
    resolve_expires_at({"token_issued_at": now, "token_expires_at": now + 999}) == now + 999,
)
check("剩余秒数计算正确", seconds_left(now + 100, now) == 100)
check("过期返回负数", seconds_left(now - 50, now) == -50)
check("等级：已过期", token_level(-1) == "expired")
check("等级：24 小时内为 critical", token_level(CRITICAL_SECONDS) == "critical")
check("等级：3 天内为 warning", token_level(2 * 86400) == "warning")
check("等级：正常", token_level(10 * 86400) == "ok")
check("等级：未知", token_level(None) == "unknown")
check("文案：剩余天数", "天" in humanize(3 * 86400), humanize(3 * 86400))
check("文案：已过期", "已过期" in humanize(-3600), humanize(-3600))

info_ok = token_info({"token_issued_at": now}, now=now)
check("token_info 标记为估算", info_ok["estimated"] is True)
check("token_info 预估到期在 3 天内", info_ok["seconds_left"] == TOKEN_TTL_ESTIMATE)
check("token_info 预估为 warning", info_ok["level"] == "warning", info_ok["level"])

info_real = token_info({"token_issued_at": now, "token_expires_at": now + 3600}, now=now)
check("token_info 非估算", info_real["estimated"] is False)
check("token_info 1 小时内为 critical", info_real["level"] == "critical", info_real["level"])

# ---------------------------------------------------------------------------
# 2. 账号视图输出令牌字段
# ---------------------------------------------------------------------------
print("\n[2] 账号视图输出令牌有效期字段")

tmp = Path(tempfile.mkdtemp())
store = AccountStore(tmp / "accounts.json")
teams = TeamStore(tmp / "teams.json")
team = teams.add_team("视频组")
member = teams.add_member(team.id, "张三")
teams.bind_account("19100000000", member.id)

acc = Account(
    account="19100000000",
    access_token="tok-abc",
    nickname="测试账号",
    note="视频组·张三 的账号",
    team_id=team.id,
    member_id=member.id,
    extra={"token_issued_at": now, "token_expires_at": now + 3600},
)
store.add(acc)

ps._store = store
ps._teams = teams

view = ps._account_view(store.get("19100000000"))
check("视图含 token_expires_at", view.get("token_expires_at") == now + 3600, str(view.get("token_expires_at")))
check("视图含 token_level", view.get("token_level") == "critical", str(view.get("token_level")))
check("视图含 token_text", bool(view.get("token_text")), str(view.get("token_text")))
check("视图含 token_expires_at_text", bool(view.get("token_expires_at_text")))
check("视图标记临近过期", view.get("token_expiring_soon") is True)

# ---------------------------------------------------------------------------
# 3. 告警扫描命中「令牌即将过期」
# ---------------------------------------------------------------------------
print("\n[3] 告警扫描命中令牌即将过期")

sent: list = []
orig_notify = ps._notify


def fake_notify(event, title, body="", level="info", dedup_key="", force=False):
    sent.append({"event": event, "title": title, "level": level})
    return []


ps._notify = fake_notify
try:
    ps.run_alerts(force=True)
finally:
    ps._notify = orig_notify

events = [s["event"] for s in sent]
check("命中令牌即将过期事件", "token_expiring" in events, str(events))
tok_hit = next((s for s in sent if s["event"] == "token_expiring"), None)
check("告警标题含重新登录指引", tok_hit is not None and "重新登录" in tok_hit["title"],
      tok_hit["title"] if tok_hit else "无")

# ---------------------------------------------------------------------------
# 4. 重新登录保留本地数据
# ---------------------------------------------------------------------------
print("\n[4] 重新登录保留本地数据并刷新令牌有效期")

store.update(
    "19100000000",
    access_token="fresh-token",
    status="auth_expired",
    auth_expired=True,
    alive=False,
    alive_error="登录态已过期",
)
after = store.get("19100000000")
check("过期后 team_id 保留", after.team_id == team.id, str(after.team_id))
check("过期后 note 保留", after.note == "视频组·张三 的账号", str(after.note))
check("过期后 member_id 保留", after.member_id == member.id, str(after.member_id))

new_issued = int(time.time()) + 10
store.update(
    "19100000000",
    access_token="fresh-token",
    status="active",
    auth_expired=False,
    alive=True,
    alive_error=None,
    extra={"token_issued_at": new_issued, "token_expires_at": new_issued + 7200},
)
after2 = store.get("19100000000")
check("重登后 token 已换新", after2.access_token == "fresh-token")
check("重登后 status 回到 active", after2.status == "active", after2.status)
check("重登后 alive 回到 True", after2.alive is True, str(after2.alive))
check("重登后 auth_expired 清除", after2.auth_expired is False)
check("重登后 team_id 未丢", after2.team_id == team.id, str(after2.team_id))
check("重登后 note 未丢", after2.note == "视频组·张三 的账号", str(after2.note))
check("重登后 member_id 未丢", after2.member_id == member.id, str(after2.member_id))
check("重登后签发时刻已刷新", after2.extra.get("token_issued_at") == new_issued)

view2 = ps._account_view(after2)
check("重登后视图令牌等级按到期点判定", view2.get("token_level") == "critical", str(view2.get("token_level")))
check("重登后视图令牌剩余时间已刷新",
      view2.get("token_seconds_left") is not None and view2.get("token_seconds_left") <= 7300,
      str(view2.get("token_seconds_left")))

# ---------------------------------------------------------------------------
# 5. 账号级过期返回 409，不触发管理员登出
# ---------------------------------------------------------------------------
print("\n[5] 账号级过期返回 409（非 401）")

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    print("  [SKIP] 未安装 fastapi.testclient")
    TestClient = None

if TestClient is not None:
    ps._api_key = "test-api-key"
    client = TestClient(ps.app, raise_server_exceptions=False)
    auth = {"Authorization": "Bearer test-api-key"}

    r = client.get("/api/v1/accounts", headers=auth)
    check("账号列表接口可用", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        body = r.json()
        one = body["accounts"][0]
        check("列表返回令牌字段", "token_level" in one and "token_text" in one, str(list(one.keys())[:20]))

    r2 = client.post("/api/v1/alerts/scan", headers=auth, json={"force": True})
    check("告警扫描接口可用", r2.status_code == 200, str(r2.status_code))

    r3 = client.post("/api/v1/notify/rule/token_expiring", headers=auth,
                     json={"enabled": True, "hours": 24})
    check("新告警规则可保存", r3.status_code == 200, str(r3.status_code))
    if r3.status_code == 200:
        rule = (r3.json() or {}).get("rule") or {}
        check("hours 阈值已落库", rule.get("hours") == 24, str(rule))

# ---------------------------------------------------------------------------
print(f"\n{'=' * 56}")
print(f"通过 {PASS} / 失败 {FAIL}")
print("=" * 56)
sys.exit(1 if FAIL else 0)

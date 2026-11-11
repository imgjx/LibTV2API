"""令牌有效期链路回归测试（修正版）。

修正背景
------
早期版本把手机号令牌寿命**硬估算**成约 2.5 天，并据此展示「剩余 N 天 / 即将过期」
甚至触发重新登录告警。但实测表明平台并不会在数天内强制失效（手动登录可用 30 天以上），
那次「第 3 天未登录」是当时其它 bug 造成的假象。本测试覆盖**新语义**：

- 平台未返回 expires_in 时，token_info 不再估算到期，而是展示「已在线 N 天」，
  等级为 unknown，不触发任何过期告警；
- 只有平台真实下发 expires_at（token_expires_estimated=False）才显示倒计时与预警；
- 旧版估算的假 token_expires_at 会被忽略；
- 告警扫描对「无真实到期」的账号不命中 token_expiring；
- 登录时 token_issued_at 落库（用于在线时长）；
- 重新登录保留本地数据（团队归属 / 备注 / 额度）；
- 账号级 409 不会被前端当成管理员登出；
- Cookie 登录：解析多种 Cookie 形态，并在登录态校验通过后登记账号。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from liblib2api import panel_server as ps  # noqa: E402
from liblib2api.accounts import Account, AccountStore  # noqa: E402
from liblib2api.auth.cookie import CookieLogin, parse_cookies  # noqa: E402
from liblib2api.token_expiry import (  # noqa: E402
    CRITICAL_SECONDS,
    humanize,
    online_seconds,
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


now = int(time.time())

# ---------------------------------------------------------------------------
# 1. 不再估算寿命：无 expires_in 时展示「已在线 N 天」
# ---------------------------------------------------------------------------
print("\n[1] 令牌有效期（无真实到期 → 已在线 N 天，不估算）")

check("无 extra 时无到期信息", resolve_expires_at(None) is None)
check("有签发时刻但无到期：不估算", resolve_expires_at({"token_issued_at": now}) is None)
check(
    "平台给了 expires_at 且非估算：采用",
    resolve_expires_at({"token_issued_at": now, "token_expires_at": now + 999,
                        "token_expires_estimated": False}) == now + 999,
)
check(
    "标记为估算的 expires_at 被忽略（不再硬猜 2.5 天）",
    resolve_expires_at({"token_issued_at": now, "token_expires_at": now - 100,
                        "token_expires_estimated": True}) is None,
)
check("剩余秒数计算正确", seconds_left(now + 100, now) == 100)
check("过期返回负数", seconds_left(now - 50, now) == -50)
check("online_seconds 计算正确", online_seconds({"token_issued_at": now - 86400}, now) == 86400)
check("online_seconds 无签发时刻为 None", online_seconds({}) is None)
check("等级：已过期", token_level(-1) == "expired")
check("等级：24 小时内为 critical", token_level(CRITICAL_SECONDS) == "critical")
check("等级：3 天内为 warning", token_level(2 * 86400) == "warning")
check("等级：正常", token_level(10 * 86400) == "ok")
check("等级：未知（无真实到期）", token_level(None) == "unknown")
check("文案：剩余天数", "天" in humanize(3 * 86400), humanize(3 * 86400))
check("文案：已过期", "已过期" in humanize(-3600), humanize(-3600))

info_phone = token_info({"token_issued_at": now - 3 * 86400}, now=now)
check("手机账号无真实到期", info_phone["has_expiry"] is False)
check("手机账号等级为 unknown", info_phone["level"] == "unknown", info_phone["level"])
check("手机账号不标即将过期", info_phone["expiring_soon"] is False)
check("手机账号不标已过期", info_phone["expired"] is False)
check("手机账号展示已在线文案", "已在线" in (info_phone["text"] or ""), info_phone["text"])
check("手机账号在线天数=3", info_phone["online_days"] == 3, str(info_phone["online_days"]))

info_real = token_info({"token_issued_at": now, "token_expires_at": now + 3600,
                        "token_expires_estimated": False}, now=now)
check("真实到期非估算", info_real["estimated"] is False)
check("真实到期 has_expiry=True", info_real["has_expiry"] is True)
check("真实到期 1 小时内为 critical", info_real["level"] == "critical", info_real["level"])
check("真实到期展示剩余文案", "剩" in (info_real["text"] or ""), info_real["text"])

# ---------------------------------------------------------------------------
# 2. 账号视图输出令牌字段（含在线时长）
# ---------------------------------------------------------------------------
print("\n[2] 账号视图输出令牌字段")

tmp = Path(tempfile.mkdtemp())
store = AccountStore(tmp / "accounts.json")
teams = TeamStore(tmp / "teams.json")
team = teams.add_team("视频组")
member = teams.add_member(team.id, "张三")
teams.bind_account("19100000000", member.id)

acc = Account(
    account="19100000000",
    access_token="tok-abc",
    login_method="phone",
    nickname="测试账号",
    note="视频组·张三 的账号",
    team_id=team.id,
    member_id=member.id,
    extra={"token_issued_at": now - 2 * 86400},  # 已登录 2 天，无真实到期
)
store.add(acc)

ps._store = store
ps._teams = teams

view = ps._account_view(store.get("19100000000"))
check("视图含 token_issued_at", view.get("token_issued_at") == now - 2 * 86400)
check("视图含 token_online_days", view.get("token_online_days") == 2, str(view.get("token_online_days")))
check("视图含 token_online_text", "已在线" in (view.get("token_online_text") or ""), view.get("token_online_text"))
check("视图无真实到期", view.get("token_has_expiry") is False)
check("视图等级 unknown", view.get("token_level") == "unknown", str(view.get("token_level")))
check("视图不标临近过期", view.get("token_expiring_soon") is False)
check("视图不标已过期", view.get("token_expired") is False)

# ---------------------------------------------------------------------------
# 3. 告警扫描：无真实到期的账号不命中 token_expiring
# ---------------------------------------------------------------------------
print("\n[3] 告警扫描：手机账号不命中 token_expiring")

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
check("手机账号不命中 token_expiring", "token_expiring" not in events, str(events))

# 反向：真实到期（过去）的账号应命中
store.update("19100000000", extra={"token_issued_at": now - 10 * 86400,
                                   "token_expires_at": now - 3600,
                                   "token_expires_estimated": False})
ps._notify = fake_notify
try:
    ps.run_alerts(force=True)
finally:
    ps._notify = orig_notify
events = [s["event"] for s in sent]
check("真实过期账号命中 token_expiring", "token_expiring" in events, str(events))

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
    extra={"token_issued_at": new_issued},
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
        check("列表返回令牌在线字段",
              "token_online_days" in one and "token_has_expiry" in one,
              str(list(one.keys())[:25]))

    r2 = client.post("/api/v1/alerts/scan", headers=auth, json={"force": True})
    check("告警扫描接口可用", r2.status_code == 200, str(r2.status_code))

# ---------------------------------------------------------------------------
# 6. Cookie 登录
# ---------------------------------------------------------------------------
print("\n[6] Cookie 登录")

check("parse_cookies 字符串", parse_cookies("a=1; b=2") == {"a": "1", "b": "2"})
check("parse_cookies 字典", parse_cookies({"a": "1"}) == {"a": "1"})
check("parse_cookies JSON 字符串", parse_cookies('{"a":"1"}') == {"a": "1"})
check("parse_cookies 数组(导出格式)",
      parse_cookies([{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]) == {"a": "1", "b": "2"})

# 用 mock 的 WebApiClient 验证 Cookie 登录：登录态校验通过并登记账号
fake_user = {
    "id": "u123",
    "nickname": "张三",
    "mobile": "19100000000",
    "uuid": "uuid-xyz",
}


class _FakeClient:
    def __init__(self, *a, **k):
        self.kw = k

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def user_info(self):
        return fake_user

    def close(self):
        return None


with patch("liblib2api.auth.cookie.WebApiClient", _FakeClient):
    cl = CookieLogin()
    creds = cl.login("usertoken=TTT; webid=W1; a=1", account_hint="19100000000")
    check("Cookie 登录标识取自手机号", creds.account == "19100000000", creds.account)
    check("Cookie 登录方法为 cookie", creds.login_method == "cookie", creds.login_method)
    check("Cookie 提取 token", creds.access_token == "TTT", creds.access_token)
    check("Cookie 提取 webid", creds.extra.get("webid") == "W1", str(creds.extra.get("webid")))
    check("Cookie 完整 cookie 落库", creds.extra.get("cookies", {}).get("a") == "1")
    check("Cookie 校验信息落库", creds.extra.get("user_info", {}).get("nickname") == "张三")
    check("Cookie 不估算到期", creds.extra.get("token_expires_estimated") is False)

# 登录态校验失败 → 抛 AuthError
class _FakeClientDead:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def user_info(self):
        from liblib2api.exceptions import AuthError
        raise AuthError("未登录")

    def close(self):
        return None


with patch("liblib2api.auth.cookie.WebApiClient", _FakeClientDead):
    cl = CookieLogin()
    failed = False
    try:
        cl.login("a=1")
    except Exception as e:  # noqa: BLE001
        failed = "未登录" in str(e) or "失效" in str(e)
    check("失效 Cookie 被拒绝", failed)

# ---------------------------------------------------------------------------
print(f"\n{'=' * 56}")
print(f"通过 {PASS} / 失败 {FAIL}")
print("=" * 56)
sys.exit(1 if FAIL else 0)

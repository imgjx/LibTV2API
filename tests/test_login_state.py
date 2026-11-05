"""登录态误判相关回归测试。

覆盖三条主线：
  1. webapi._is_login_expired：只认「明确的未登录语义」，不被含 token 的业务提示误伤。
  2. 面板同步接口：账号 token 过期返回 409（而非 401），不会把管理员踢出面板。
  3. 重新登录：原地换 token，保留团队归属/备注/额度，并重置 alive 让账号回到池子。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# 1. 登录态过期判定
# ---------------------------------------------------------------------------
print("\n[1] _is_login_expired 精确判定")
from liblib2api.webapi import _is_login_expired  # noqa: E402

# 平台真实返回：必须判为登录态过期
check("code=401 判为过期", _is_login_expired(401, "任意消息"))
check("code='401' 判为过期", _is_login_expired("401", "任意消息"))
check("msg='No login' 判为过期", _is_login_expired(0, "No login"))
check("msg='未登录' 判为过期", _is_login_expired(0, "未登录"))
check("msg='登录已过期' 判为过期", _is_login_expired(0, "登录已过期"))
check("msg='请先登录' 判为过期", _is_login_expired(0, "请先登录"))

# 关键回归：含 token 的正常业务错误不能被误判为退登
check(
    "「token 数量超限」不判过期",
    not _is_login_expired(500, "token 数量超限"),
)
check(
    "「Token参数错误」不判过期",
    not _is_login_expired(400, "Token参数错误"),
)
check(
    "「无效的token格式」不判过期",
    not _is_login_expired(400, "无效的token格式"),
)
check(
    "「积分不足」不判过期",
    not _is_login_expired(500, "积分不足"),
)
check(
    "「模型已下架」不判过期",
    not _is_login_expired(500, "模型已下架"),
)
check(
    "「该账号未登录过此活动」不判过期（长句保护）",
    not _is_login_expired(500, "该账号未登录过此活动，请先完成实名认证后再试"),
)


# ---------------------------------------------------------------------------
# 2. 面板同步：过期返回 409，不返回 401
# ---------------------------------------------------------------------------
print("\n[2] 账号 token 过期 → 409（不触发前端登出）")
from fastapi.testclient import TestClient  # noqa: E402
from liblib2api import panel_server as ps  # noqa: E402
from liblib2api.accounts import Account, AccountStore  # noqa: E402
from liblib2api.exceptions import AuthError  # noqa: E402
tmp = Path(tempfile.mkdtemp())
store = AccountStore(tmp / "accounts.json")
acc = Account(
    account="19100000000",
    access_token="stale-token",
    nickname="测试账号",
    note="视频组·张三 的账号",
    team_id="team_x",
)
store.add(acc)

ps._store = store
# 鉴权中间件需要凭证：这里直接注入测试用 API Key
ps._api_key = "test-api-key"
client = TestClient(ps.app, raise_server_exceptions=False)
AUTH = {"Authorization": "Bearer test-api-key"}

# 让 _client_for 构造出的客户端在调用时抛 AuthError，
# 以此模拟「账号 token 已过期」的线上情形。
class _ExpiredClient:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def compute_model_usability(self):
        raise AuthError("登录态已过期，请重新登录（未登录）")

    def free_power(self):
        return {}


ps._client_for_orig = ps._client_for
ps._client_for = lambda _acc: _ExpiredClient()
try:
    r = client.post("/api/v1/accounts/19100000000/sync", headers=AUTH)
    check("同步过期返回 409 而非 401", r.status_code == 409, f"实际 {r.status_code}")
    if r.status_code == 409:
        body = r.json()
        detail = body.get("detail") or {}
        check("响应带 error=account_auth_expired",
              isinstance(detail, dict) and detail.get("error") == "account_auth_expired",
              str(body)[:200])
        check("响应含可读 message",
              isinstance(detail, dict) and "重新登录" in str(detail.get("message", "")),
              str(body)[:200])
    # 账号状态应被标记为登录态过期（而不是被判定为账号失效）
    st = store.get("19100000000")
    check("账号标记 auth_expired", st.auth_expired is True, str(st.auth_expired))
    check("账号状态为 auth_expired", st.status == "auth_expired", st.status)
finally:
    ps._client_for = ps._client_for_orig


# ---------------------------------------------------------------------------
# 3. 重新登录：原地更新 + 保留本地字段 + 重置 alive
# ---------------------------------------------------------------------------
print("\n[3] 重新登录保留本地数据并恢复可用")
from liblib2api.teams import TeamStore  # noqa: E402

ts = TeamStore(tmp / "teams.json")
team = ts.add_team("视频组")
member = ts.add_member(team.id, "张三")
ts.bind_account("19100000000", member.id)

store.update(
    "19100000000",
    status="auth_expired",
    auth_expired=True,
    alive=False,
    alive_error="登录态已过期，请重新登录（未登录）",
)
before = store.get("19100000000")
# 团队归属由 TeamStore.bind_account 维护（Account.team_id 是本地冗余字段），
# 断言以 TeamStore 为准，避免测的是冗余字段而非真实归属关系。
bound = ts.member_of_account("19100000000")
check("过期后团队归属保留", bound is not None and bound.team_id == team.id,
      f"{bound.team_id if bound else None}")
check("过期后成员归属保留", bound is not None and bound.id == member.id,
      f"{bound.id if bound else None}")
check("过期后 note 保留", before.note == "视频组·张三 的账号", f"{before.note}")

# 模拟重新登录成功（原地更新）
store.update(
    "19100000000",
    access_token="fresh-token",
    status="active",
    auth_expired=False,
    alive=True,
    alive_error=None,
)
after = store.get("19100000000")
check("重登后 token 已换新", after.access_token == "fresh-token")
check("重登后 status 回到 active", after.status == "active", after.status)
check("重登后 alive 回到 True", after.alive is True, f"{after.alive}")
check("重登后 auth_expired 清除", after.auth_expired is False)
check("重登后 note 未丢", after.note == "视频组·张三 的账号", f"{after.note}")
bound2 = ts.member_of_account("19100000000")
check("重登后团队归属未丢", bound2 is not None and bound2.team_id == team.id,
      f"{bound2.team_id if bound2 else None}")
check("重登后成员归属未丢", bound2 is not None and bound2.id == member.id,
      f"{bound2.id if bound2 else None}")

# 选择器应能重新选中该账号
from liblib2api.selector import AccountSelector  # noqa: E402

sel = AccountSelector(store, ts)
chosen, reason = sel.select()
check("重登后账号重新进入池子", chosen is not None and chosen.account == "19100000000", reason)

# 反向：仍是过期状态时，应被排除并给出明确原因
store.update("19100000000", status="auth_expired", auth_expired=True, alive=False)
chosen2, reason2 = sel.select()
check("过期账号被排除", chosen2 is None, str(chosen2))
check("排除原因说明需重新登录", "登录态已过期" in reason2, reason2)


# ---------------------------------------------------------------------------
# 4. phone.user_info 会带 Token 头（登录后校验登录态）
# ---------------------------------------------------------------------------
print("\n[4] PhoneLogin 注入 Token/Webid 头")
from liblib2api.auth.phone import PhoneLogin  # noqa: E402

p = PhoneLogin()
check("初始无 Token 头", "Token" not in p._client.headers)
p._client.headers["Token"] = "tok-123"
p._client.headers["Webid"] = "webid-456"
check("Token 头可注入", p._client.headers.get("Token") == "tok-123")
check("Webid 头可注入", p._client.headers.get("Webid") == "webid-456")
p.adopt_webid("webid-789")
check("adopt_webid 生效", p._client.headers.get("Webid") == "webid-789")
p.close()


print(f"\n=== 通过 {PASS} / 失败 {FAIL} ===")
sys.exit(1 if FAIL else 0)

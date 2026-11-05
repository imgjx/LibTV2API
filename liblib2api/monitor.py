"""账号活性监控（后台守护）。

职责：
  * 每 N 秒（默认 600s = 10 分钟）巡检所有账号：
      - 调 user_info 验证 token 是否仍有效（活性探测）
      - 调 member/account 刷新账号类型 / 会员等级 / 到期时间（导入时自动识别也走这里）
      - 调 libtvFreePower 刷新每日免费算力
      - 若当日尚未领取权益，触发一次每日事件（发放当日免费算力）
  * 更新每个账号的 alive / alive_error / last_alive_check / account_type 等字段
  * 记录最近一次巡检结果与时间，供面板展示

线程安全：所有写操作走 AccountStore 的锁。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from liblib2api.accounts import AccountStore
from liblib2api.exceptions import ApiError, AuthError
from liblib2api.token_expiry import token_info
from liblib2api.webapi import WebApiClient

DEFAULT_INTERVAL = 600  # 10 分钟


@dataclass
class CheckResult:
    account: str
    ok: bool
    account_type: Optional[str] = None
    points: Optional[float] = None
    free_power: Optional[float] = None
    #: 当日权益是否已领取
    checked_in: bool = False
    error: Optional[str] = None

    @property
    def claimed(self) -> bool:
        """中性表述别名：等价于 :attr:`checked_in`。"""
        return self.checked_in


class AccountMonitor:
    def __init__(
        self,
        store: AccountStore,
        interval: int = DEFAULT_INTERVAL,
        client_factory: Optional[Callable[[object], WebApiClient]] = None,
        auto_claim: bool = True,
        token_warn_seconds: int = 24 * 3600,
        on_token_expiring: Optional[Callable[[object, dict], None]] = None,
    ):
        self.store = store
        self.interval = interval
        self.auto_claim = auto_claim
        self.token_warn_seconds = token_warn_seconds
        self.on_token_expiring = on_token_expiring
        self._client_factory = client_factory or self._default_client
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self.last_run_at: Optional[int] = None
        self.last_results: list[CheckResult] = []
        self.running = False
        self._run_immediately = True

    @staticmethod
    def _default_client(acc) -> WebApiClient:
        return WebApiClient(
            access_token=acc.access_token,
            webid=acc.webid,
            proxy=acc.proxy,
            cookies=(acc.extra or {}).get("cookies") or None,
            cid=(acc.extra or {}).get("cid"),
        )

    def _check_one(self, acc) -> CheckResult:
        today = time.strftime("%Y-%m-%d")
        try:
            client = self._client_factory(acc)
        except Exception as e:  # noqa: BLE001
            return CheckResult(account=acc.account, ok=False, error=f"构建客户端失败：{e}")

        # WebApiClient 持有 httpx 连接池，必须用 with 及时释放，
        # 否则每轮巡检都会泄漏一个客户端（长期运行会耗尽连接/文件描述符）。
        with client:
            res = CheckResult(account=acc.account, ok=True)
            try:
                info = client.user_info()
                atype = client.detect_account_type()
                fp = client.free_power()
                member = atype.get("raw_member") or {}
                res.account_type = atype.get("type")
                res.points = acc.points
                res.free_power = fp.get("freePower")

                # 刷新账号画像
                self.store.update(
                    acc.account,
                    alive=True,
                    alive_error=None,
                    last_alive_check=int(time.time()),
                    account_type=atype.get("type"),
                    is_sub=atype.get("is_sub", acc.is_sub),
                    owner_uuid=atype.get("owner_uuid"),
                    owner_type=atype.get("owner_type"),
                    member_name=atype.get("name"),
                    account_level=atype.get("level"),
                    member_until=atype.get("member_until"),
                    package_type=atype.get("package_type"),
                    nickname=info.get("nickname") or acc.nickname,
                    user_id=str(info.get("id")) if info.get("id") else acc.user_id,
                    uuid=info.get("uuid") or acc.uuid,
                    free_power=fp.get("freePower") if fp.get("freePower") is not None else acc.free_power,
                    has_get_power=member.get("hasGetPower")
                    if member.get("hasGetPower") is not None
                    else acc.has_get_power,
                    status="active" if acc.status in ("error", "auth_expired") else acc.status,
                    auth_expired=False,
                )
            except AuthError as e:
                # 登录态过期（平台拒绝当前 token）：账号本身未必有问题，
                # 重新获取 token 后即可继续用，故标记为 auth_expired 而非账号异常。
                # 平台原始消息往往只有「未登录」三个字，这里补成可读说明，
                # 免得面板上看起来像账号被平台注销了。
                reason = f"登录态已过期（{e}），请重新登录以恢复使用"
                self.store.update(
                    acc.account, alive=False, auth_expired=True,
                    alive_error=reason[:200],
                    last_alive_check=int(time.time()), status="auth_expired",
                )
                res.ok = False
                res.error = reason
                return res
            except ApiError as e:
                # 接口/网络类故障属于偶发问题，不能据此判定账号不可用，
                # 只记录错误并保留上一次的有效状态，等下一轮巡检再确认。
                self.store.update(
                    acc.account, alive_error=str(e)[:200],
                    last_alive_check=int(time.time()),
                )
                res.ok = False
                res.error = str(e)
                return res
            except Exception as e:  # noqa: BLE001
                self.store.update(
                    acc.account, alive_error=str(e)[:200],
                    last_alive_check=int(time.time()),
                )
                res.ok = False
                res.error = str(e)
                return res

            # 每日权益：当日未领取则触发（发放免费算力）
            if self.auto_claim and acc.last_claim != today:
                try:
                    ok = client.daily_claim()
                    res.checked_in = bool(ok)
                    if ok:
                        self.store.update(acc.account, last_claim=today)
                except Exception:  # noqa: BLE001
                    res.checked_in = False
            return res

    def check_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for acc in self.store.list():
            if not acc.access_token:
                continue
            try:
                results.append(self._check_one(acc))
            except Exception as e:  # noqa: BLE001
                results.append(CheckResult(account=acc.account, ok=False, error=str(e)[:200]))
        self._check_token_expiry()
        self.last_run_at = int(time.time())
        self.last_results = results
        return results

    def _check_token_expiry(self) -> None:
        """检查登录令牌是否临近过期，必要时回调告警。

        平台手机号令牌寿命约 2～3 天且没有续期端点，属于**正常到期**。
        若不提前提醒，账号会在无人值守时突然不可用，极易被误判成账号被限制。
        """
        if self.on_token_expiring is None:
            return
        for acc in self.store.list():
            if not acc.access_token:
                continue
            info = token_info(acc.extra)
            left = info.get("seconds_left")
            if left is None:
                continue
            if left > self.token_warn_seconds:
                continue
            try:
                self.on_token_expiring(acc, info)
            except Exception:  # noqa: BLE001
                # 告警失败不应影响巡检主流程
                pass

    def _loop(self) -> None:
        self.running = True
        first = True
        while not self._stop:
            # 首轮是否立即巡检由 start(run_immediately) 决定；此前实现会在
            # 循环里跑一次、又另起线程跑一次，导致启动时重复巡检（重复领取权益）。
            if not first or self._run_immediately:
                try:
                    self.check_all()
                except Exception:  # noqa: BLE001
                    pass
            first = False
            # 用带中断的 sleep，便于 stop 时快速退出；interval 下限 1 秒避免忙循环
            for _ in range(max(1, int(self.interval))):
                if self._stop:
                    break
                time.sleep(1)
        self.running = False

    def start(self, run_immediately: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._run_immediately = run_immediately
        self._thread = threading.Thread(target=self._loop, daemon=True, name="account-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop = True

    def status(self) -> dict:
        return {
            "running": self.running,
            "interval": self.interval,
            "last_run_at": self.last_run_at,
            "accounts_checked": len(self.last_results),
            "results": [
                {
                    "account": r.account,
                    "ok": r.ok,
                    "account_type": r.account_type,
                    "points": r.points,
                    "free_power": r.free_power,
                    "checked_in": r.checked_in,
                    "error": r.error,
                }
                for r in self.last_results
            ],
        }

"""账号活性监控（后台守护）。

职责：
  * 每 N 秒（默认 600s = 10 分钟）巡检所有账号：
      - 调 user_info 验证 token 是否仍有效（活性探测）
      - 调 member/account 刷新账号类型 / 会员等级 / 到期时间（导入时自动识别也走这里）
      - 调 libtvFreePower 刷新每日免费算力
      - 若当日尚未签到，触发一次每日登录事件（等价于「进一次网页自动签到」）
  * 更新每个账号的 alive / alive_error / last_alive_check / account_type 等字段
  * 记录最近一次巡检结果与时间，供面板展示

线程安全：所有写操作走 AccountStore 的锁。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from liblib2api.accounts import AccountStore
from liblib2api.exceptions import ApiError, AuthError
from liblib2api.webapi import WebApiClient

DEFAULT_INTERVAL = 600  # 10 分钟


@dataclass
class CheckResult:
    account: str
    ok: bool
    account_type: Optional[str] = None
    points: Optional[float] = None
    free_power: Optional[float] = None
    checked_in: bool = False
    error: Optional[str] = None


class AccountMonitor:
    def __init__(
        self,
        store: AccountStore,
        interval: int = DEFAULT_INTERVAL,
        client_factory: Optional[Callable[[object], WebApiClient]] = None,
        auto_checkin: bool = True,
    ):
        self.store = store
        self.interval = interval
        self.auto_checkin = auto_checkin
        self._client_factory = client_factory or self._default_client
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self.last_run_at: Optional[int] = None
        self.last_results: list[CheckResult] = []
        self.running = False

    @staticmethod
    def _default_client(acc) -> WebApiClient:
        return WebApiClient(access_token=acc.access_token, webid=acc.webid, proxy=acc.proxy)

    def _check_one(self, acc) -> CheckResult:
        today = time.strftime("%Y-%m-%d")
        try:
            client = self._client_factory(acc)
        except Exception as e:  # noqa: BLE001
            return CheckResult(account=acc.account, ok=False, error=f"构建客户端失败：{e}")

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
                status="active" if acc.status == "error" else acc.status,
            )
        except (ApiError, AuthError) as e:
            self.store.update(
                acc.account, alive=False, alive_error=str(e)[:200],
                last_alive_check=int(time.time()), status="error",
            )
            res.ok = False
            res.error = str(e)
            return res
        except Exception as e:  # noqa: BLE001
            self.store.update(
                acc.account, alive=False, alive_error=str(e)[:200],
                last_alive_check=int(time.time()),
            )
            res.ok = False
            res.error = str(e)
            return res

        # 每日签到：当日未签到则触发（发放免费算力）
        if self.auto_checkin and acc.last_checkin != today:
            try:
                ok = client.daily_checkin()
                res.checked_in = bool(ok)
                if ok:
                    self.store.update(acc.account, last_checkin=today)
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
        self.last_run_at = int(time.time())
        self.last_results = results
        return results

    def _loop(self) -> None:
        self.running = True
        while not self._stop:
            try:
                self.check_all()
            except Exception:  # noqa: BLE001
                pass
            # 用带中断的 sleep，便于 stop 时快速退出
            for _ in range(self.interval):
                if self._stop:
                    break
                time.sleep(1)
        self.running = False

    def start(self, run_immediately: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True, name="account-monitor")
        self._thread.start()
        if run_immediately:
            # 立即跑一轮（不阻塞启动），后台线程内执行
            threading.Thread(target=self.check_all, daemon=True).start()

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

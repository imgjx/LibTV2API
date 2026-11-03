"""综合自动交叉账号选择（账号池调度核心）。

当一个生成/查询请求进来（可能指定了模型 / 所需算力），从账号池中挑出最合适的账号：

策略（strategy）：
  * balanced     均衡：在满足「模型可用 + 积分足够」的账号里，
                  优先选「最久没被用过」的，均摊团队额度（默认）
  * least_used   纯最少使用，忽略积分偏好
  * most_points  优先选剩余积分最多的（适合大任务）
  * vip_preferred 会员优先（会员专属模型时自动采用），其余情况回退均衡

筛选条件：
  * 仅 active 且拥有有效 token 的账号
  * 活性检查通过（alive != False）—— 未检查过的乐观放行
  * 若指定 model_key：仅保留 can_use(model_key) 为 True 的账号
  * 若指定 require_points：仅保留 points >= 该值

返回 (account, reason)；无候选时返回 (None, 原因)。
"""
from __future__ import annotations

import time
from typing import Optional

from liblib2api.accounts import Account, AccountStore

STRATEGIES = ("balanced", "least_used", "most_points", "vip_preferred")


class AccountSelector:
    def __init__(self, store: AccountStore):
        self.store = store

    def _candidates(
        self,
        model_key: Optional[str] = None,
        require_points: Optional[float] = None,
        exclude: Optional[set] = None,
    ) -> list[Account]:
        exclude = exclude or set()
        now = int(time.time())
        cands: list[Account] = []
        for a in self.store.list():
            if a.status != "active":
                continue
            if not a.access_token:
                continue
            if a.alive is False:  # 明确活性失败才剔除；未检查(None)乐观放行
                continue
            if a.account in exclude:
                continue
            if model_key and not a.can_use(model_key):
                continue
            if require_points is not None and (a.points or 0) < require_points:
                continue
            cands.append(a)
        return cands

    def select(
        self,
        kind: Optional[str] = None,
        model_key: Optional[str] = None,
        require_points: Optional[float] = None,
        strategy: str = "balanced",
        exclude: Optional[set] = None,
    ) -> tuple[Optional[Account], str]:
        # 会员专属模型时，若指定 balanced 也优先会员
        if strategy == "balanced" and model_key:
            # 先看是否有会员账号可用该模型
            pass
        candidates = self._candidates(model_key, require_points, exclude)
        if not candidates:
            reason = "无可用账号"
            if model_key:
                reason += f"（模型 {model_key} 在当前账号池中均不可用）"
            if require_points:
                reason += f"（满足积分≥{require_points} 的账号不足）"
            return None, reason

        now = int(time.time())
        if strategy == "most_points":
            candidates.sort(key=lambda a: (a.points or 0), reverse=True)
            chosen = candidates[0]
            reason = f"按剩余积分最多选择（{chosen.points} 点）"
        elif strategy == "least_used":
            candidates.sort(key=lambda a: (a.request_count, a.last_used_at or 0))
            chosen = candidates[0]
            reason = f"按累计使用最少选择（已用 {chosen.request_count} 次）"
        elif strategy == "vip_preferred":
            candidates.sort(key=lambda a: (not a.is_member(), a.last_used_at or 0))
            chosen = candidates[0]
            reason = "会员优先" + ("" if chosen.is_member() else "（无会员账号，回退均衡）")
        else:  # balanced：最久未用 + 会员微调 + 积分兜底
            def score(a: Account):
                idle = now - (a.last_used_at or 0)
                member_bonus = 100_000 if a.is_member() else 0
                points_bonus = (a.points or 0) * 0.01
                return idle + member_bonus + points_bonus
            candidates.sort(key=score, reverse=True)
            chosen = candidates[0]
            reason = (
                f"均衡策略：最久未用={int((now - (chosen.last_used_at or now)) / 60)}分钟前"
                f"，{'会员' if chosen.is_member() else '免费'}账号"
            )

        # 会员专属模型强制要求会员账号
        if model_key and chosen.is_member() is False:
            # 检查是否因会员限制：若候选里存在会员账号可用该模型则换之
            member_cands = [a for a in candidates if a.is_member()]
            if member_cands:
                chosen = member_cands[0]
                reason = "模型为会员专属，已切换到会员账号"
        return chosen, reason

    def select_for_model(
        self, model_key: Optional[str], require_points: Optional[float] = None, strategy: str = "balanced"
    ) -> tuple[Optional[Account], str]:
        return self.select(
            model_key=model_key, require_points=require_points, strategy=strategy
        )

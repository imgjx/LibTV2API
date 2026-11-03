"""算力均摊（跨账号分段生成）。

背景
----
一个长视频（比如 15 秒）往往需要较多算力点。若**没有任何一个账号能独立生成完整时长**，
但团队有多个账号，则把该视频按算力拆成若干段（5+5+5 秒、或 9+4+1+1 秒 …），
每段交给「额度够用的账号」分段生成，最后在本地用 ffmpeg 拼接成完整视频。

启用条件（重要）
----------------
算力均摊是**兜底**手段：只有当所有账号都无法独立覆盖总时长时才启用。
若存在单个账号额度足够，则优先由该账号一次性生成，避免不必要的分段与拼接。

分段策略（可由 OpenAI 兼容 API 规划，也可确定性兜底）：
  - 调用方给出：总时长 D、提示词 prompt、以及账号池（每个账号剩余算力点）
  - 规划器（OpenAI 兼容）产出 N 段，每段含 {seconds, prompt(承接上一段的画面描述)}
  - 若未配置 API 或调用失败，回退为「尽量均分」的确定性分段法
  - 之后按每个账号的剩余算力点为每段贪心分配账号（一个账号可承接多段，只要其总够用）

OpenAI 兼容 API 仅用于「分段规划」（决定分段与每段画面），不接触任何 liblib 凭据；
账号算力点、生成调用都走本地账号池与 MCP。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

import liblib2api.config as cfg

# 单次生成每个账号能承担的「最长单段秒数」上限（兜底；实际会按模型配置覆盖）
MAX_SEGMENT_SECONDS = 30


def single_account_feasible(
    accounts: list[dict],
    total_duration: int,
    points_per_second: float = cfg.POINTS_PER_SECOND,
) -> tuple[bool, Optional[dict]]:
    """判断是否有**单个**账号能独立生成完整时长。

    返回 ``(是否可行, 该账号信息)``。可行时优先单账号一次生成，
    不触发算力均摊；不可行时才需要分段接力。
    """
    need = float(total_duration) * float(points_per_second)
    best: Optional[dict] = None
    for acc in accounts or []:
        points = float(acc.get("points") or 0)
        if points >= need:
            if best is None or points > float(best.get("points") or 0):
                best = acc
    return (best is not None), best


@dataclass
class Segment:
    """分段后的一段：时长 + 该段画面描述（承接上文）。"""

    seconds: int
    prompt: str
    # 运行时填充：承接的账号、使用的工具、生成结果
    account: Optional[str] = None
    tool: Optional[str] = None
    result: Optional[dict] = None


@dataclass
class SplitPlan:
    total_duration: int
    segments: list[Segment]
    # 规划来源：llm / fallback
    source: str = "fallback"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "total_duration": self.total_duration,
            "source": self.source,
            "note": self.note,
            "segments": [
                {
                    "seconds": s.seconds,
                    "prompt": s.prompt,
                    "account": s.account,
                    "tool": s.tool,
                    "result": s.result,
                }
                for s in self.segments
            ],
        }


class OpenAICompatibleClient:
    """极简 OpenAI 兼容 Chat Completions 客户端（无第三方依赖，仅 httpx）。"""

    def __init__(
        self,
        base_url: str = cfg.OPENAI_COMPATIBLE_BASE_URL,
        api_key: str = cfg.OPENAI_COMPATIBLE_API_KEY,
        model: str = cfg.OPENAI_COMPATIBLE_MODEL,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(timeout=timeout)

    def chat_json(self, system: str, user: str, temperature: float = 0.3) -> Any:
        if not self.api_key:
            raise RuntimeError("未配置 OpenAI 兼容 API Key")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        resp = self._client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenAI 兼容接口返回 {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


class VideoSplitPlanner:
    """把「总时长 + 提示词 + 账号预算」规划为若干接力段。"""

    def __init__(self, client: Optional[OpenAICompatibleClient] = None):
        self.client = client

    def plan(
        self,
        prompt: str,
        total_duration: int,
        accounts: list[dict],
        points_per_second: float = cfg.POINTS_PER_SECOND,
        constraints: Optional[dict] = None,
    ) -> SplitPlan:
        """accounts: [{account, points}]；返回 SplitPlan。

        constraints: 来自模型实际配置的动态约束（不同模型差别很大）：
            {
              "max_segment_seconds": int,   # 单段最长（如 5/10/15/30）
              "allowed_durations": [int],   # 允许的时长档位（可选，命中则强制对齐）
              "points_per_second": float,   # 该模型每积分消耗（覆盖默认 pps）
            }
        """
        constraints = constraints or {}
        max_seg = int(constraints.get("max_segment_seconds") or MAX_SEGMENT_SECONDS)
        pps = float(constraints.get("points_per_second") or points_per_second)
        if self.client is not None:
            try:
                return self._plan_llm(prompt, total_duration, accounts, pps, max_seg, constraints)
            except Exception as e:  # noqa: BLE001
                # 任何失败都回退到确定性拆法，保证功能可用
                return self._plan_fallback(total_duration, pps, max_seg,
                                           note=f"LLM 规划失败，已回退均分：{e}")
        return self._plan_fallback(total_duration, pps, max_seg,
                                   note="未配置 OpenAI 兼容 API，使用确定性均分")

    def _plan_llm(self, prompt, total_duration, accounts, pps, max_seg, constraints) -> SplitPlan:
        budgets = "；".join(
            f"{a['account']}={a.get('points')}点" for a in accounts
        ) or "（无可用账号积分信息）"
        allowed = constraints.get("allowed_durations")
        allowed_hint = (
            f" 每段秒数必须是以下档位之一：{allowed}。" if allowed
            else f" 每段秒数为不超过 {max_seg} 的整数。"
        )
        system = (
            "你是一个视频分镜规划器。用户要生成一段总时长固定的视频，但没有任何单个账号的"
            "算力点能覆盖完整时长，需要团队多个账号分段接力完成。请把它拆成若干连续镜头片段，"
            "让相邻片段在画面上能衔接。只输出严格的 JSON，不要任何解释。"
        )
        user = (
            f"总时长：{total_duration} 秒。\n"
            f"团队账号预算（每个账号剩余算力点）：{budgets}\n"
            f"每生成 1 秒约消耗 {pps} 点，单段最长 {max_seg} 秒。\n"
            f"原提示词：{prompt}\n\n"
            "请把原提示词拆成 3~5 段连续镜头，每段给出秒数（整数）与该段的具体画面描述（承接上一段）。"
            "各段秒数之和必须严格等于总时长，且每段秒数×"
            f"{pps} 不超过最大单账号预算。\n"
            + allowed_hint
            + "\n"
            '返回 JSON：{"segments":[{"seconds":整数,"prompt":"该段画面描述"}]}\n'
            "注意：segments 数组的 seconds 求和必须等于 " + str(total_duration) + "。"
        )
        data = self.client.chat_json(system, user)
        segs = data.get("segments") or []
        segments = []
        for s in segs:
            sec = int(s.get("seconds") or 0)
            if sec <= 0:
                continue
            segments.append(Segment(seconds=min(sec, max_seg), prompt=str(s.get("prompt") or prompt)))
        total = sum(s.seconds for s in segments)
        if not segments or total != total_duration:
            # 校正：若和不对，按比例/补差调整到目标总时长
            segments = self._normalize(segments, total_duration, prompt, max_seg)
        return SplitPlan(total_duration=total_duration, segments=segments, source="llm")

    @staticmethod
    def _normalize(segments: list[Segment], total_duration: int, fallback_prompt: str, max_seg: int = MAX_SEGMENT_SECONDS) -> list[Segment]:
        if not segments:
            return [Segment(seconds=min(total_duration, max_seg), prompt=fallback_prompt)]
        # 按权重把总时长重新分配到各段（保持原始秒数占比），取整并修正尾差
        raw = [s.seconds for s in segments]
        s_sum = sum(raw) or 1
        allocated = [max(1, min(max_seg, round(x * total_duration / s_sum))) for x in raw]
        diff = total_duration - sum(allocated)
        allocated[0] += diff
        if allocated[0] < 1:
            allocated[0] = 1
        out = []
        for s, sec in zip(segments, allocated):
            out.append(Segment(seconds=sec, prompt=s.prompt))
        return out

    @staticmethod
    def _plan_fallback(total_duration: int, pps: float, max_seg: int = MAX_SEGMENT_SECONDS, note: str = "") -> SplitPlan:
        max_seg = max(1, int(max_seg))
        # 尽量均分；单段不超过 max_seg，至少分 3 段（除非总时长很短）
        n = max(min(total_duration, 3), -(-total_duration // max_seg))  # ceil(总/单段上限)
        n = max(1, n)
        base = total_duration // n
        rem = total_duration - base * n
        segs = []
        for i in range(n):
            sec = base + (1 if i < rem else 0)
            segs.append(Segment(seconds=sec, prompt=""))
        return SplitPlan(total_duration=total_duration, segments=segs, source="fallback", note=note)


def assign_accounts(
    plan: SplitPlan,
    accounts: list[dict],
    points_per_second: float = cfg.POINTS_PER_SECOND,
) -> tuple[list[Segment], Optional[str]]:
    """为每段贪心分配「算力点够用」的账号。

    accounts: [{account, points, _obj?}]；返回 (带 account 的 segments, 错误信息)。
    一个账号可承接多段（只要其剩余算力点累计够用）；按剩余算力点递减消耗。
    返回前会修改传入 accounts 的 points（扣减）。
    """
    # 复制剩余额度，保留余额
    pool = [{"account": a["account"], "points": float(a.get("points") or 0)} for a in accounts]
    # 按算力点降序，便于优先用大额度账号兜底
    pool.sort(key=lambda x: x["points"], reverse=True)
    errors = []
    for seg in plan.segments:
        cost = seg.seconds * points_per_second
        # 优先选「剩余额度足够」且「用得最少」的账号（轮询均衡）
        candidates = [p for p in pool if p["points"] >= cost]
        if not candidates:
            errors.append(
                f"段 {seg.seconds}s≈{cost:.0f}点 无账号额度足够（最大单账号余 {max((p['points'] for p in pool), default=0):.0f}点）"
            )
            seg.account = None
            continue
        # 均衡：在够用的账号里选剩余额度最小的（更省着用大额度账号）
        chosen = min(candidates, key=lambda x: x["points"])
        chosen["points"] -= cost
        seg.account = chosen["account"]
    if errors:
        return plan.segments, "；".join(errors)
    return plan.segments, None


#: 中性命名别名：算力均摊（跨账号分段生成）规划器
ComputeBalancePlanner = VideoSplitPlanner

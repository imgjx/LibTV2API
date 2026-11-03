"""视频拆分生成（多账号接力）。

背景
----
一个长视频（比如 15 秒）往往需要较多算力点，单个账号积分可能不够。但团队有多个账号，
于是把一个长视频拆成若干段（5+5+5 秒、或 9+4+1+1 秒 …），每段交给「积分够用的账号」接力生成，
最后在本地用 ffmpeg 拼接成完整视频。

拆条策略（可由 OpenAI 兼容 API 规划，也可确定性兜底）：
  - 调用方给出：总时长 D、提示词 prompt、以及账号池（每个账号剩余积分）
  - 规划器（OpenAI 兼容）产出 N 段，每段含 {seconds, prompt(承接上一段的画面描述)}
  - 若未配置 API 或调用失败，回退为「尽量均分」的确定性拆法
  - 之后按每个账号的剩余积分为每段贪心分配账号（一个账号可承接多段，只要其总积分够）

OpenAI 兼容 API 仅用于「创意拆条」（决定分段与每段画面），不接触任何 liblib 凭据；
账号积分、生成调用都走本地账号池与 MCP。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

import liblib2api.config as cfg

# 单次生成每个账号能承担的「最长单段秒数」上限（避免一段过长被平台拒绝）
MAX_SEGMENT_SECONDS = 30


@dataclass
class Segment:
    """拆条后的一段：时长 + 该段画面描述（承接上文）。"""

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
    ) -> SplitPlan:
        """accounts: [{account, points}]；返回 SplitPlan。"""
        if self.client is not None:
            try:
                return self._plan_llm(prompt, total_duration, accounts, points_per_second)
            except Exception as e:  # noqa: BLE001
                # 任何失败都回退到确定性拆法，保证功能可用
                return self._plan_fallback(total_duration, points_per_second,
                                           note=f"LLM 规划失败，已回退均分：{e}")
        return self._plan_fallback(total_duration, points_per_second,
                                   note="未配置 OpenAI 兼容 API，使用确定性均分")

    def _plan_llm(self, prompt, total_duration, accounts, pps) -> SplitPlan:
        budgets = "；".join(
            f"{a['account']}={a.get('points')}点" for a in accounts
        ) or "（无可用账号积分信息）"
        system = (
            "你是一个视频分镜拆分器。用户要生成一段总时长固定的视频，但单个账号算力点不足，"
            "需要用团队多个账号接力分段生成。请把它拆成若干连续镜头片段，让相邻片段在画面上能衔接。"
            "只输出严格的 JSON，不要任何解释。"
        )
        user = (
            f"总时长：{total_duration} 秒。\n"
            f"团队账号预算（每个账号剩余算力点）：{budgets}\n"
            f"每生成 1 秒约消耗 {pps} 点，单段最长 {MAX_SEGMENT_SECONDS} 秒。\n"
            f"原提示词：{prompt}\n\n"
            "请把原提示词拆成 3~5 段连续镜头，每段给出秒数（整数）与该段的具体画面描述（承接上一段）。"
            "各段秒数之和必须严格等于总时长，且每段秒数×"
            f"{pps} 不超过最大单账号预算。\n"
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
            segments.append(Segment(seconds=min(sec, MAX_SEGMENT_SECONDS), prompt=str(s.get("prompt") or prompt)))
        total = sum(s.seconds for s in segments)
        if not segments or total != total_duration:
            # 校正：若和不对，按比例/补差调整到目标总时长
            segments = self._normalize(segments, total_duration, prompt)
        return SplitPlan(total_duration=total_duration, segments=segments, source="llm")

    @staticmethod
    def _normalize(segments: list[Segment], total_duration: int, fallback_prompt: str) -> list[Segment]:
        if not segments:
            return [Segment(seconds=total_duration, prompt=fallback_prompt)]
        # 按权重把总时长重新分配到各段（保持原始秒数占比），取整并修正尾差
        raw = [s.seconds for s in segments]
        s_sum = sum(raw) or 1
        allocated = [max(1, round(x * total_duration / s_sum)) for x in raw]
        diff = total_duration - sum(allocated)
        allocated[0] += diff
        if allocated[0] < 1:
            allocated[0] = 1
        out = []
        for s, sec in zip(segments, allocated):
            out.append(Segment(seconds=sec, prompt=s.prompt))
        return out

    @staticmethod
    def _plan_fallback(total_duration: int, pps: float, note: str = "") -> SplitPlan:
        # 尽量均分；单段不超过 MAX_SEGMENT_SECONDS，至少分 3 段
        n = max(3, -(-total_duration // MAX_SEGMENT_SECONDS))  # ceil
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
    """为每段贪心分配「积分够用」的账号。

    accounts: [{account, points, _obj?}]；返回 (带 account 的 segments, 错误信息)。
    一个账号可承接多段（只要其剩余积分累计够用）；按剩余积分递减消耗。
    返回前会修改传入 accounts 的 points（扣减）。
    """
    # 复制剩余额度，保留余额
    pool = [{"account": a["account"], "points": float(a.get("points") or 0)} for a in accounts]
    # 按积分降序，便于优先用大额度账号兜底
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

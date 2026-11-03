"""模型注册表与可用性识别。

问题背景
--------
liblib 的模型列表接口（video/recommend-models、modelCard/config）**本身不返回
「当前账号能否使用」的标志**。但结合以下信号，可以较准确地识别每个账号可用的模型：

1. 账号类型（来自 member/account）：
   - member：已开会员（主卡或副卡，effective=true）
   - free  ：非会员 / 副卡未开会员（name=非会员，effective=false）
2. 模型「会员专属」分类（classify_membership）：
   - 名称 / 描述 / 标签含 VIP、会员专属、专属通道、SVIP、大会员 等关键词 → 标记为会员专属
   - 已知会员专属 modelKey 白名单（持续补充）
3. 每日权益（commerce/activity/benefit）：返回该账号当天可免费用哪些模型
   （benefitType=freeRunTimes），这些模型对该账号一定可用（可纠正关键词误判）
4. 运行时学习：若某账号在生成某模型时被后端以会员/权限原因拒绝，记入该账号的
   usable[model_key]=False，越用越准。

本模块只负责「识别与标注」，不负责调用 API；API 调用在 webapi.py，编排在
selector.py / panel_server.py。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 会员专属识别规则
# ---------------------------------------------------------------------------
VIP_KEYWORDS = [
    "vip", "svip", "会员专属", "会员专享", "专属通道", "专属模型",
    "大会员", "尊享", "pro会员", "pro 会员", "付费模型",
]

# 已知会员专属的 modelKey（实测补充）。无需穷举，关键词已能覆盖大部分。
KNOWN_VIP_MODEL_KEYS: set[str] = set()

# 免费账号（非会员）默认完全不可用的模型名片段（关键词无法覆盖时的兜底）
FREE_BLOCKED_HINTS = ["vip", "会员专属", "专属通道"]


@dataclass
class ModelInfo:
    """一个归一化后的模型，附带会员限制与可用性标注。"""

    kind: str                      # "video" | "image"
    name: str
    model_key: Optional[str] = None
    checkpoint_id: Optional[Any] = None
    base_type: Optional[int] = None
    category: Optional[str] = None
    description: Optional[str] = None
    labels: list = field(default_factory=list)
    cover_url: Optional[str] = None
    corner_labels: list = field(default_factory=list)
    # 是否会员专属（模型自身属性，与账号无关）
    requires_membership: bool = False
    # 对「非会员/免费」账号是否可用（账号无关；最终可用性还要结合账号类型）
    usable_for_free: bool = True
    # 解析自 baseConfig 的能力提示，供前端展示与视频参数校验
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "model_key": self.model_key,
            "checkpoint_id": self.checkpoint_id,
            "base_type": self.base_type,
            "category": self.category,
            "description": self.description,
            "labels": self.labels,
            "cover_url": self.cover_url,
            "requires_membership": self.requires_membership,
            "usable_for_free": self.usable_for_free,
            "config": self.config,
        }


def classify_membership(model: dict) -> bool:
    """判断一个模型是否「会员专属」。

    综合名称、描述、标签的关键词，以及 modelKey 白名单。
    命中任意一条即视为会员专属（免费账号不可用，除非被当日权益豁免）。
    """
    name = str(model.get("modelName") or model.get("name") or "")
    desc = str(model.get("description") or "")
    labels = model.get("labels") or []
    blob = " ".join([name, desc, *[str(x) for x in labels]]).lower()
    for kw in VIP_KEYWORDS:
        if kw.lower() in blob:
            return True
    key = str(model.get("modelKey") or "").lower()
    if key in KNOWN_VIP_MODEL_KEYS:
        return True
    return False


def _parse_base_config(model: dict) -> dict:
    raw = model.get("baseConfig")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def normalize_video(raw: dict) -> ModelInfo:
    cfg = _parse_base_config(raw)
    return ModelInfo(
        kind="video",
        name=raw.get("modelName") or raw.get("modelShortName") or raw.get("name") or "",
        model_key=raw.get("modelKey"),
        checkpoint_id=raw.get("checkpointId"),
        base_type=raw.get("baseType"),
        category=raw.get("categoryName"),
        description=raw.get("description"),
        labels=raw.get("labels") or [],
        cover_url=raw.get("coverUrl"),
        corner_labels=raw.get("cornerLabels") or [],
        requires_membership=classify_membership(raw),
        config=cfg,
    )


def normalize_image(raw: dict) -> ModelInfo:
    cfg = _parse_base_config(raw)
    return ModelInfo(
        kind="image",
        name=raw.get("name") or raw.get("modelName") or "",
        model_key=raw.get("modelKey") or str(raw.get("checkpointId")),
        checkpoint_id=raw.get("checkpointId"),
        base_type=raw.get("baseType"),
        category=raw.get("categoryName"),
        description=raw.get("description"),
        labels=raw.get("labels") or [],
        cover_url=raw.get("imageUrl") or raw.get("coverUrl"),
        corner_labels=raw.get("cornerLabels") or [],
        requires_membership=classify_membership(raw),
        config=cfg,
    )


def annotate_availability(
    models: list[ModelInfo],
    account_type: str,
    free_benefit_keys: Optional[set[str]] = None,
) -> list[dict]:
    """给模型列表标注「该账号是否可用」。

    account_type:
        "member" → 会员账号，全部可用（受积分限制，但模型本身可用）
        "free"   → 非会员/副卡，会员专属模型不可用，除非被当日权益豁免
        "unknown"→ 保守起见全部标记可用（不阻塞），由运行时学习补全

    返回每个模型的 dict，含 usable（该账号是否可用）字段。
    """
    free_benefit_keys = free_benefit_keys or set()
    out: list[dict] = []
    for m in models:
        d = m.to_dict()
        if account_type == "member":
            d["usable"] = True
        elif account_type == "free":
            if m.model_key in free_benefit_keys:
                d["usable"] = True
            else:
                d["usable"] = not m.requires_membership
        else:  # unknown
            d["usable"] = True
        out.append(d)
    return out


def build_usability_map(
    models: list[ModelInfo],
    account_type: str,
    free_benefit_keys: Optional[set[str]] = None,
) -> dict[str, bool]:
    """返回 {model_key: 该账号是否可用}，便于选择器与持久化。"""
    out: dict[str, bool] = {}
    for m in annotate_availability(models, account_type, free_benefit_keys):
        key = m.get("model_key") or m.get("name")
        if key:
            out[key] = m["usable"]
    return out

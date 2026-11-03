"""图片 / 音频生成的统一请求规范与参数构建。

与 video_output.py 对应：视频在那边，图片与音频在本文件。
三者都通过 MCP 工具执行（liblib 把图片/视频/音频能力以 MCP 工具形式暴露），
这里只负责把对外高级参数校验并映射为底层工具参数，以及结果归一化。

支持的媒体类型：
  - image：png / jpg / webp
  - audio：mp4 / wav / mp3（liblib 音频产出多为 mp4 容器或 wav）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 格式 / 尺寸 / 时长
# ---------------------------------------------------------------------------
IMAGE_FORMATS = ["png", "jpg", "webp"]
AUDIO_FORMATS = ["mp4", "wav", "mp3"]

# 图片常用尺寸预设
IMAGE_SIZES: dict[str, tuple[int, int]] = {
    "1k": (1024, 1024),
    "2k": (1536, 1536),
    "3k": (2048, 2048),
    "hd": (1280, 720),
    "portrait": (720, 1280),
}

AUDIO_DURATIONS = [5, 10, 15, 30, 60]  # 秒


@dataclass
class ImageGenerateRequest:
    """图片生成请求（对外统一口径）。"""

    prompt: str
    model: Optional[str] = None          # 模型名或 modelKey；为空由选择器挑默认图片模型
    width: int = 1024
    height: int = 1024
    fmt: str = "png"                     # png/jpg/webp
    negative_prompt: Optional[str] = None
    # 参考素材（图生图 / 垫图等）
    references: list[dict] = field(default_factory=list)
    seed: Optional[int] = None
    # 调度
    account: Optional[str] = None
    strategy: str = "balanced"
    webhook: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.prompt or not self.prompt.strip():
            errs.append("prompt 不能为空")
        if self.fmt not in IMAGE_FORMATS:
            errs.append(f"format 必须是 {IMAGE_FORMATS} 之一")
        if self.width < 64 or self.height < 64:
            errs.append("宽高不能小于 64")
        return errs


@dataclass
class AudioGenerateRequest:
    """音频生成请求（对外统一口径）。"""

    prompt: str
    model: Optional[str] = None          # 音频模型 / 工具名；为空由选择器挑音频工具
    duration: int = 15                   # 秒
    fmt: str = "mp4"                     # mp4/wav/mp3
    negative_prompt: Optional[str] = None
    # 参考（如参考一段旋律/人声）
    references: list[dict] = field(default_factory=list)
    seed: Optional[int] = None
    account: Optional[str] = None
    strategy: str = "balanced"
    webhook: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.prompt or not self.prompt.strip():
            errs.append("prompt 不能为空")
        if self.fmt not in AUDIO_FORMATS:
            errs.append(f"format 必须是 {AUDIO_FORMATS} 之一")
        if self.duration not in AUDIO_DURATIONS and self.duration <= 0:
            errs.append("duration 必须为正整数（秒）")
        return errs


@dataclass
class MediaResult:
    """归一化后的图片/音频结果。"""

    task_id: Optional[str] = None
    status: str = "submitted"
    account_used: Optional[str] = None
    model: Optional[str] = None
    media_type: str = "image"
    format: str = "png"
    # 主输出 url
    url: Optional[str] = None
    thumbnail: Optional[str] = None
    cost_power: Optional[float] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "account_used": self.account_used,
            "model": self.model,
            "media_type": self.media_type,
            "format": self.format,
            "url": self.url,
            "thumbnail": self.thumbnail,
            "cost_power": self.cost_power,
            "created_at": self.created_at,
            "error": self.error,
        }


def build_image_arguments(req: ImageGenerateRequest, model_key: Optional[str] = None) -> dict:
    """图片请求 → liblib 图片工具参数。"""
    args: dict[str, Any] = {
        "prompt": req.prompt,
        "modelKey": model_key or req.model,
        "width": req.width,
        "height": req.height,
        "format": req.fmt,
    }
    if req.negative_prompt:
        args["negativePrompt"] = req.negative_prompt
    if req.seed is not None:
        args["seed"] = req.seed
    if req.references:
        args["references"] = req.references
    args.update(req.extra or {})
    return args


def build_audio_arguments(req: AudioGenerateRequest, model_key: Optional[str] = None) -> dict:
    """音频请求 → liblib 音频工具参数。"""
    args: dict[str, Any] = {
        "prompt": req.prompt,
        "modelKey": model_key or req.model,
        "duration": req.duration,
        "format": req.fmt,
    }
    if req.negative_prompt:
        args["negativePrompt"] = req.negative_prompt
    if req.seed is not None:
        args["seed"] = req.seed
    if req.references:
        args["references"] = req.references
    args.update(req.extra or {})
    return args


def normalize_media(raw: Any, req: Any, account_used: Optional[str] = None,
                    media_type: str = "image") -> MediaResult:
    """把 MCP 工具返回归一化为 MediaResult（兼容多种 url 结构）。"""
    result = MediaResult(
        account_used=account_used,
        model=getattr(req, "model", None),
        media_type=media_type,
        format=getattr(req, "fmt", "png"),
        raw=raw if isinstance(raw, dict) else {"_raw": raw},
    )
    data: Any = raw
    if isinstance(raw, dict):
        data = raw.get("data", raw)
        result.task_id = raw.get("taskId") or raw.get("task_id") or (
            data.get("taskId") if isinstance(data, dict) else None
        )
        result.status = raw.get("status") or (
            data.get("status") if isinstance(data, dict) else "submitted"
        ) or "submitted"
    url = _extract_url(data) or _extract_url(raw)
    if url:
        result.url = url
        result.status = "succeeded" if result.status == "submitted" else result.status
    if isinstance(data, dict):
        result.thumbnail = data.get("thumbnail") or data.get("coverUrl")
        cp = data.get("costPower") or data.get("cost") or data.get("power")
        if cp is not None:
            result.cost_power = cp
    return result


def _extract_url(node: Any) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    for key in ("url", "imageUrl", "audioUrl", "videoUrl", "resourceUrl", "downloadUrl", "src"):
        v = node.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    for item in node.get("content", []) or []:
        if isinstance(item, dict):
            u = item.get("resourceUrl") or item.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u
    for sub in (node.get("result"), node.get("outputs")) or []:
        if isinstance(sub, list):
            for it in sub:
                if isinstance(it, dict):
                    u = it.get("url") or it.get("imageUrl") or it.get("audioUrl")
                    if isinstance(u, str) and u.startswith("http"):
                        return u
        elif isinstance(sub, dict):
            u = _extract_url(sub)
            if u:
                return u
    return None

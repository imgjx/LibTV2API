"""多格式视频生成：请求规范 + 结果归一化。

重点需求：对外 API 要支持「多种格式的视频输出」。
liblib 的视频生成最终产出通常是 mp4；但对外暴露时应让调用方明确选择：

  * 封装格式（format）：mp4（默认，最通用）/ webm（体积更小，适合 Web）/
                       mov（剪辑友好）/ gif（动图，短片段）
  * 分辨率（resolution）：480p / 720p / 1080p / 2k / 4k
  * 时长（duration）：5 / 10 / 15 / 30 秒（受模型上限约束，见 baseConfig.maxCount）
  * 帧率（fps）：24 / 25 / 30
  * 比例（aspect_ratio）：16:9 / 9:16 / 1:1 / 4:3 / 21:9

由于 bridge 网关有 WAF，实际生成走 MCP 工具（call_tool）。本模块负责：
  1. 把调用方的「高级参数」校验并映射为 liblib 视频工具的参数（build_arguments）
  2. 把工具返回的原始结果归一化为统一的 VideoResult（含多格式/多分辨率 url、
     任务状态、消耗算力、所用账号、所用模型），便于工作流直接消费
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 支持的格式 / 分辨率 / 时长
# ---------------------------------------------------------------------------
VIDEO_FORMATS = ["mp4", "webm", "mov", "gif"]

RESOLUTIONS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "2k": (2560, 1440),
    "4k": (3840, 2160),
}

DURATIONS = [5, 10, 15, 30]  # 秒

ASPECT_RATIOS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:3": (4, 3),
    "21:9": (21, 9),
}


@dataclass
class VideoGenerateRequest:
    """视频生成请求（对外统一口径）。"""

    prompt: str
    model: Optional[str] = None          # 模型名或 modelKey；为空则选择器挑默认视频模型
    duration: int = 5                    # 秒
    resolution: str = "720p"
    fmt: str = "mp4"                     # mp4/webm/mov/gif
    fps: int = 30
    aspect_ratio: Optional[str] = None   # 16:9 等；与 width/height 二选一
    width: Optional[int] = None
    height: Optional[int] = None
    negative_prompt: Optional[str] = None
    # 参考素材（图片/视频/音频），可为 URL 或本地已上传资源 id
    references: list[dict] = field(default_factory=list)
    seed: Optional[int] = None
    # 调度
    account: Optional[str] = None        # 指定账号；为空则交叉选择
    strategy: str = "balanced"          # 选择策略
    # 异步回调（若提供则任务完成后 POST 结果）
    webhook: Optional[str] = None
    # 透传给底层 MCP 工具的额外参数（高级用户）
    extra: dict = field(default_factory=dict)

    def validate(self, allow_any_duration: bool = False) -> list[str]:
        errs: list[str] = []
        if not self.prompt or not self.prompt.strip():
            errs.append("prompt 不能为空")
        if self.fmt not in VIDEO_FORMATS:
            errs.append(f"format 必须是 {VIDEO_FORMATS} 之一")
        if self.resolution not in RESOLUTIONS:
            errs.append(f"resolution 必须是 {list(RESOLUTIONS)} 之一")
        if allow_any_duration:
            if not (isinstance(self.duration, int) and 1 <= self.duration <= 30):
                errs.append("duration 必须为 1~30 的整数（秒）")
        elif self.duration not in DURATIONS:
            errs.append(f"duration 必须是 {DURATIONS} 之一（秒）")
        if self.fps not in (24, 25, 30):
            errs.append("fps 必须是 24/25/30 之一")
        if self.aspect_ratio and self.aspect_ratio not in ASPECT_RATIOS:
            errs.append(f"aspect_ratio 必须是 {list(ASPECT_RATIOS)} 之一")
        return errs

    def resolution_wh(self) -> tuple[int, int]:
        if self.width and self.height:
            return self.width, self.height
        return RESOLUTIONS.get(self.resolution, RESOLUTIONS["720p"])


@dataclass
class VideoResult:
    """归一化后的视频结果。"""

    task_id: Optional[str] = None
    status: str = "submitted"            # submitted | running | succeeded | failed
    account_used: Optional[str] = None
    model: Optional[str] = None
    format: str = "mp4"
    resolution: Optional[str] = None
    duration: Optional[int] = None
    # 多格式 / 多分辨率输出 URL：urls[format][resolution] = url
    urls: dict = field(default_factory=dict)
    # 主输出（按请求 format/resolution）
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
            "format": self.format,
            "resolution": self.resolution,
            "duration": self.duration,
            "urls": self.urls,
            "url": self.url,
            "thumbnail": self.thumbnail,
            "cost_power": self.cost_power,
            "created_at": self.created_at,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# 参数映射
# ---------------------------------------------------------------------------
def build_arguments(req: VideoGenerateRequest, model_key: Optional[str] = None) -> dict:
    """把高级请求映射为 liblib 视频工具的参数字典。

    说明：liblib 视频工具的精确参数名以 MCP tools/list 返回为准（不同模型略有差异），
    这里给出业界通用映射；若模型不接受某字段，会被忽略或按模型默认覆盖。
    extra 中的字段优先级最高，可覆盖下列默认映射。
    """
    w, h = req.resolution_wh()
    args: dict[str, Any] = {
        "prompt": req.prompt,
        "modelKey": model_key or req.model,
        "duration": req.duration,
        "width": w,
        "height": h,
        "fps": req.fps,
        "format": req.fmt,
    }
    if req.negative_prompt:
        args["negativePrompt"] = req.negative_prompt
    if req.aspect_ratio:
        args["aspectRatio"] = req.aspect_ratio
    if req.seed is not None:
        args["seed"] = req.seed
    if req.references:
        args["references"] = req.references
    # 调用方透传参数（最高优先级）
    args.update(req.extra or {})
    return args


def normalize_result(raw: Any, req: VideoGenerateRequest, account_used: Optional[str] = None) -> VideoResult:
    """把 MCP 工具返回的原始结果归一化为 VideoResult。

    不同工具返回结构不同，这里做尽量宽松的提取：
      - 任务 id / 状态
      - 视频 url（可能在 data.url / data.videoUrl / data.result[].url / content[].resourceUrl 等）
      - 缩略图、消耗算力
    """
    result = VideoResult(
        account_used=account_used,
        model=req.model,
        format=req.fmt,
        resolution=req.resolution,
        duration=req.duration,
        raw=raw if isinstance(raw, dict) else {"_raw": raw},
    )

    data: Any = raw
    if isinstance(raw, dict):
        data = raw.get("data", raw)
        result.task_id = (
            raw.get("taskId") or raw.get("task_id")
            or (data.get("taskId") if isinstance(data, dict) else None)
        )
        result.status = raw.get("status") or (data.get("status") if isinstance(data, dict) else "submitted") or "submitted"

    # 提取视频 url（多路径兼容）
    url = _extract_url(data) or _extract_url(raw)
    if url:
        result.url = url
        result.urls = {req.fmt: {req.resolution: url}}
        result.status = "succeeded" if result.status == "submitted" else result.status

    if isinstance(data, dict):
        result.thumbnail = data.get("thumbnail") or data.get("coverUrl")
        cp = data.get("costPower") or data.get("cost") or data.get("power")
        if cp is not None:
            result.cost_power = cp
    return result


def _extract_url(node: Any) -> Optional[str]:
    """从多种常见结构中提取视频 url。"""
    if not isinstance(node, dict):
        return None
    for key in ("url", "videoUrl", "video_url", "resourceUrl", "downloadUrl", "src"):
        v = node.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    # content 列表（MCP tool result 常见结构）
    for item in node.get("content", []) or []:
        if isinstance(item, dict):
            u = item.get("resourceUrl") or item.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u
    # result / outputs 列表
    for sub in (node.get("result"), node.get("outputs")) or []:
        if isinstance(sub, list):
            for it in sub:
                if isinstance(it, dict):
                    u = it.get("url") or it.get("videoUrl")
                    if isinstance(u, str) and u.startswith("http"):
                        return u
        elif isinstance(sub, dict):
            u = _extract_url(sub)
            if u:
                return u
    return None

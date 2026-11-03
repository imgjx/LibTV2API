"""自动化工作流接入示例。

场景：你的调度系统要批量生成视频。流程是「登录一次 → 调用 MCP 工具 → 轮询 → 取结果」。

前提：先完成登录（任选其一，凭据会落地 ~/.libtv/credentials.json）：
    python -m liblib2api.cli login wechat
    # 或
    python -m liblib2api.cli login phone --phone 13800138000 --code 123456

本示例用 Python SDK 直接驱动；如果你的自动化是 HTTP 调用，见 README 的「HTTP 服务接入」。
"""
from __future__ import annotations

import json
import time

from liblib2api import LiblibClient


def main():
    client = LiblibClient()

    # 1) 列出可用工具（首次会触发 MCP initialize 握手）
    tools = client.list_tools()
    print(f"可用工具 {len(tools)} 个，例如：")
    for t in tools[:5]:
        print("  -", t.get("name"))

    # 2) 调用某个生成类工具（工具名以你账号实际可用为准，先用 list_tools 查看）
    tool_name = input("请输入要调用的工具名（留空则跳过调用演示）：").strip()
    if not tool_name:
        print("未输入工具名，演示结束。")
        return

    args_raw = input("请输入该工具的 arguments（JSON，可留空 {}）：").strip() or "{}"
    arguments = json.loads(args_raw)

    print(f"调用 {tool_name} ...")
    result = client.call_tool(tool_name, arguments)
    print("调用结果：")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 3) 长任务轮询示例（按工具返回结构自行实现；此处仅给骨架）
    # many tools return a sessionId / taskId; 用 list_tools 看每个工具的参数与返回，
    # 再用 mcp_raw 调对应查询/状态接口轮询，直到终态。
    print("\n提示：视频/图片生成为长任务，请结合 list_tools 返回的查询工具做轮询。")


if __name__ == "__main__":
    main()

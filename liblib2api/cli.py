"""命令行入口。

用法：
  # 微信扫码登录（自动打开浏览器，本地 8765 端口收授权码）
  python -m liblib2api.cli login wechat

  # 手机号登录（两步）
  python -m liblib2api.cli login phone --phone 13800138000        # 下发验证码
  python -m liblib2api.cli login phone --phone 13800138000 --code 123456

  # 查看当前登录状态
  python -m liblib2api.cli status

  # 列出 MCP 工具
  python -m liblib2api.cli tools

  # 注销
  python -m liblib2api.cli logout

  # 启动 HTTP 服务（供自动化工作流接入）
  python -m liblib2api.cli serve --port 8000
"""
from __future__ import annotations

import argparse
import sys

from liblib2api import __version__
from liblib2api.auth.phone import PhoneLogin
from liblib2api.auth.wechat import WechatLogin
from liblib2api.credentials import CredentialStore
from liblib2api.exceptions import LiblibError


def cmd_login(args):
    store = CredentialStore()
    if args.method == "wechat":
        WechatLogin(store=store).login(open_browser=not args.no_browser)
        print("✅ 微信扫码登录成功，凭据已保存。")
        return
    # phone
    login = PhoneLogin(store=store)
    if not args.code:
        r = login.send_code(args.phone)
        print(f"📨 验证码已下发到 {args.phone}（服务端响应：{r}）。")
        print("   请带上 --code 再次执行完成登录。")
        return
    creds = login.login(args.phone, args.code)
    print(f"✅ 手机号登录成功（账号 {creds.account}），凭据已保存。")


def cmd_status(args):
    from liblib2api.client import LiblibClient

    store = CredentialStore()
    if not store.logged_in:
        print("⚠️  尚未登录或凭据已过期，请先执行 login。")
        return
    info = LiblibClient(store=store).whoami()
    print("当前登录：")
    for k, v in info.items():
        print(f"  {k}: {v}")


def cmd_tools(args):
    from liblib2api.client import LiblibClient

    tools = LiblibClient().list_tools()
    print(f"共 {len(tools)} 个工具：")
    for t in tools:
        print(f"  - {t.get('name')}: {t.get('description', '')[:60]}")


def cmd_logout(args):
    CredentialStore().clear()
    print("🧹 已注销，凭据已清除。")


def cmd_serve(args):
    import uvicorn

    # 让服务知道对外暴露的端口（用于拼接 OAuth 回调）
    import os

    os.environ["LIBLIB_SERVER_PORT"] = str(args.port)
    if args.public_url:
        os.environ["LIBLIB_SERVER_PUBLIC_URL"] = args.public_url
    # 多账号面板服务（含账号池 / 监控 / 模型可用性 / 视频生成）
    uvicorn.run("liblib2api.panel_server:app", host=args.host, port=args.port, reload=False)


def cmd_seed(args):
    from liblib2api import panel_server

    res = panel_server.seed_from_local_credential(note=args.note)
    if not res:
        print("⚠️  本机没有可用的登录凭据（credentials.json），请先执行 login。")
        return
    print(f"✅ 已把本机凭据导入账号池：{res['account']}（类型：{res['account_type']}，"
          f"会员：{res['is_member']}，可用模型 {res['model_usable_count']}/{res['model_total_count']}）")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="liblib2api", description="liblib.tv 登录与自动化接入工具")
    p.add_argument("--version", action="version", version=f"liblib2api {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("login", help="登录（wechat / phone）")
    pl.add_argument("method", choices=["wechat", "phone"])
    pl.add_argument("--phone", help="手机号（phone 方式必填）")
    pl.add_argument("--code", help="短信验证码（phone 第二步）")
    pl.add_argument("--no-browser", action="store_true", help="不自动打开浏览器（微信）")
    pl.set_defaults(func=cmd_login)

    sub.add_parser("status", help="查看登录状态").set_defaults(func=cmd_status)
    sub.add_parser("tools", help="列出 MCP 工具").set_defaults(func=cmd_tools)
    sub.add_parser("logout", help="注销并清除凭据").set_defaults(func=cmd_logout)
    sub.add_parser("seed", help="把本机登录凭据导入账号池并识别类型").add_argument(
        "--note", default="", help="账号备注"
    ).set_defaults(func=cmd_seed)

    ps = sub.add_parser("serve", help="启动 HTTP 服务（多账号面板）")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=8000)
    ps.add_argument("--public-url", default=None, help="OAuth 回调对外地址，如 http://host:8000")
    ps.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except LiblibError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

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
    if args.method == "cookie":
        return _login_cookie(args)
    # phone
    login = PhoneLogin(store=store)
    if not args.code:
        r = login.send_code(args.phone)
        print(f"📨 验证码已下发到 {args.phone}（服务端响应：{r}）。")
        print("   请带上 --code 再次执行完成登录。")
        return
    creds = login.login(args.phone, args.code)
    print(f"✅ 手机号登录成功（账号 {creds.account}），凭据已保存。")


def _login_cookie(args) -> None:
    """从浏览器 Cookie 直接登记账号到账号池（无需验证码/扫码）。"""
    from liblib2api.accounts import Account, AccountStore
    from liblib2api.auth.cookie import CookieLogin

    raw = args.cookies
    if not raw and args.cookies_file:
        from pathlib import Path

        p = Path(args.cookies_file)
        if not p.exists():
            print(f"❌ Cookie 文件不存在：{p}")
            return
        raw = p.read_text(encoding="utf-8")
    if not raw:
        print("❌ 请提供 --cookies 'a=1; b=2' 或 --cookies-file /path/to/cookies.txt")
        return

    try:
        creds = CookieLogin(proxy=args.proxy).login(raw, account_hint=args.account)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Cookie 登录失败：{e}")
        return

    info = creds.extra.get("user_info") or {}
    astore = AccountStore()
    old = astore.get(args.account) if args.account else astore.get(creds.account)
    key = old.account if old else creds.account
    if old is not None:
        astore.update(
            key,
            access_token=creds.access_token,
            webid=creds.extra.get("webid"),
            nickname=info.get("nickname") or creds.extra.get("nickname") or old.nickname,
            user_id=str(info.get("id")) if info.get("id") else old.user_id,
            uuid=info.get("uuid") or old.uuid,
            proxy=args.proxy or old.proxy,
            extra={
                **old.extra,
                "cookies": creds.extra.get("cookies") or {},
                "webid": creds.extra.get("webid") or old.webid,
                "cid": creds.extra.get("cid"),
                "token_issued_at": creds.extra.get("token_issued_at") or int(__import__("time").time()),
                "token_expires_at": creds.extra.get("token_expires_at"),
                "token_expires_estimated": creds.extra.get("token_expires_estimated", False),
            },
            status="active",
            auth_expired=False,
            alive=True,
            alive_error=None,
            last_alive_check=int(__import__("time").time()),
        )
    else:
        acc = Account(
            account=key,
            access_token=creds.access_token,
            login_method="cookie",
            webid=creds.extra.get("webid"),
            nickname=info.get("nickname") or creds.extra.get("nickname"),
            user_id=str(info.get("id")) if info.get("id") else None,
            uuid=info.get("uuid"),
            proxy=args.proxy,
            extra=creds.extra,
        )
        astore.add(acc)
    print(f"✅ Cookie 登录成功（账号 {key}），已登记到账号池（login_method=cookie）。")
    print("   请运行 `seed` 或直接启动面板（serve）使用该账号。")


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


def cmd_teams(args):
    """查看团队与成员的额度概览（平台原生无团队功能，这里是统一纳管视图）。"""
    from liblib2api.teams import TeamStore

    store = TeamStore()
    teams = store.list_teams()
    if not teams:
        print("暂无团队。可在面板「团队与成员」页创建，或调用 /api/v1/teams。")
        return
    for t in teams:
        print(f"\n🧑‍💼 {t.name}" + (f"（{t.note}）" if t.note else ""))
        members = store.list_members(t.id)
        if not members:
            print("   （暂无成员）")
            continue
        for m in members:
            quota = "不限额" if m.quota_unlimited else f"{m.quota_used}/{m.quota_limit} 点"
            accs = "、".join(m.account_ids) or "未绑定账号"
            print(f"   - {m.name}｜额度 {quota}｜账号 {accs}")


def cmd_notify(args):
    """通知中心：查看通道状态、发送测试通知。"""
    from liblib2api.panel_server import _notifier

    if args.test:
        records = _notifier.test(args.channel or "")
        if not records:
            print("没有匹配的通道，或通道未启用。")
            return
        for r in records:
            mark = "✅" if r.ok else "❌"
            print(f"{mark} {r.channel}：{r.title}" + (f"（{r.error}）" if r.error else ""))
        return
    print("通知通道状态：")
    for c in _notifier.channel_status():
        state = "已启用" if c["enabled"] else "未启用"
        conf = "已配置" if c["configured"] else "未配置"
        print(f"  - {c['label']}（{c['name']}）：{state} / {conf}")
    print("\n告警规则：")
    for event, rule in _notifier.rules().items():
        flag = "开" if rule.get("enabled") else "关"
        extra = {k: v for k, v in rule.items() if k != "enabled"}
        print(f"  - {event}：{flag}" + (f" {extra}" if extra else ""))


def cmd_stats(args):
    """团队算力点与用量统计概览。"""
    from liblib2api.accounts import AccountStore
    from liblib2api.analytics import team_stats as build_stats
    from liblib2api.teams import TeamStore

    store = AccountStore()
    teams = TeamStore()
    data = build_stats(store, teams)
    ov = data["overview"]
    print("团队总览：")
    print(f"  账号 {ov['accounts']} 个（VIP {ov['vip_accounts']} / 免费 {ov['free_accounts']}）")
    print(f"  算力点合计 {ov['total_points']}，每日免费算力 {ov['total_free_power']}")
    print(f"  在线 {ov['alive_accounts']}，失效 {ov['invalid_accounts']}，"
          f"临近到期 {ov['expiring_accounts']}")
    if data["members"]:
        print("\n成员用量：")
        for m in data["members"]:
            quota = "不限额" if m["quota_unlimited"] else f"{m['quota_used']}/{m['quota_limit']}"
            print(f"  - {m['team_name']}·{m['name']}｜账号 {m['accounts']} 个｜"
                  f"算力点 {m['points']}｜额度 {quota}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="libtv-team",
        description="liblib 团队账号统一管理工具（账号池 / 成员额度 / 创作能力调用）",
    )
    p.add_argument("--version", action="version", version=f"liblib2api {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("login", help="登录（wechat / phone / cookie）")
    pl.add_argument("method", choices=["wechat", "phone", "cookie"])
    pl.add_argument("--phone", help="手机号（phone 方式必填）")
    pl.add_argument("--code", help="短信验证码（phone 第二步）")
    pl.add_argument("--no-browser", action="store_true", help="不自动打开浏览器（微信）")
    pl.add_argument("--cookies", help="浏览器 Cookie 字符串（cookie 方式，如 'a=1; b=2'）")
    pl.add_argument("--cookies-file", help="Cookie 文件路径（cookie 方式，内容同上）")
    pl.add_argument("--account", help="已存在账号标识（cookie 刷新会话时保留团队/备注）")
    pl.add_argument("--proxy", help="代理地址（可选）")
    pl.set_defaults(func=cmd_login)

    sub.add_parser("status", help="查看登录状态").set_defaults(func=cmd_status)
    sub.add_parser("tools", help="列出 MCP 工具").set_defaults(func=cmd_tools)
    sub.add_parser("logout", help="注销并清除凭据").set_defaults(func=cmd_logout)

    pseed = sub.add_parser("seed", help="把本机登录凭据导入账号池并识别类型")
    pseed.add_argument("--note", default="", help="账号备注（如：张三团队成员的账号）")
    pseed.set_defaults(func=cmd_seed)

    pteams = sub.add_parser("teams", help="查看团队与成员额度概览")
    pteams.set_defaults(func=cmd_teams)

    pnotify = sub.add_parser("notify", help="通知中心（通道状态 / 测试发送）")
    pnotify.add_argument("--test", action="store_true", help="发送一条测试通知")
    pnotify.add_argument("--channel", default="", help="指定通道：email / wecom / console")
    pnotify.set_defaults(func=cmd_notify)

    pstats = sub.add_parser("stats", help="团队算力点与用量统计")
    pstats.set_defaults(func=cmd_stats)

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

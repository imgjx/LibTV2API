"""用真实浏览器带 token 访问 liblib.art，抓取所有 XHR/fetch 请求，
用于定位积分、模型列表、签到等服务端点。诊断脚本。"""
import asyncio, json, re, sys
from playwright.async_api import async_playwright

TOKEN = "1a16ab53b1794f3aa768005479d7218e12811145b5c68"
WEBID = "1793630885191zlbfjflk"
URLS = ["https://www.liblib.art/", "https://www.liblib.art/ai-tool/image-generator"]

async def main():
    hits = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1440,"height":900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([
            {"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
            {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"},
        ])
        await ctx.add_init_script(
            "localStorage.setItem('userToken', %r); localStorage.setItem('webid', %r);" % (TOKEN, WEBID))
        pg = await ctx.new_page()
        async def on_req(req):
            if req.resource_type in ("xhr","fetch"):
                body = req.post_data or ""
                if any(k in req.url for k in ("point","credit","integral","sign","check","model","user","account","balance","price","task","vip")):
                    hits.append({"url":req.url,"method":req.method,"body":body[:400],
                                 "headers":{k:v for k,v in req.headers.items() if k.lower() in ("token","webid","cookie","authorization")}})
        pg.on("request", on_req)
        for u in URLS:
            try:
                await pg.goto(u, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print("nav warn", u, str(e)[:90])
            await pg.wait_for_timeout(3500)
        # 打开个人中心/更多页面，触发签到与积分查询
        for u in ["https://www.liblib.art/user?tab=point","https://www.liblib.art/user",
                  "https://www.liblib.art/ai-tool/video-generator"]:
            try:
                await pg.goto(u, wait_until="networkidle", timeout=40000)
            except Exception as e:
                print("nav warn", u, str(e)[:90])
            await pg.wait_for_timeout(3000)
        await b.close()
    seen=set(); out=[]
    for h in hits:
        k=re.sub(r"\?.*","",h["url"])
        if k in seen: continue
        seen.add(k); out.append(h)
    print(f"=== 捕获 {len(out)} 个相关请求 ===")
    for h in out:
        print(f"\n{h['method']} {h['url']}")
        if h["body"]: print("  BODY:", h["body"])
        tok = h["headers"].get("Token") or h["headers"].get("token")
        if tok: print("  Token hdr:", tok[:12]+"...")
asyncio.run(main())

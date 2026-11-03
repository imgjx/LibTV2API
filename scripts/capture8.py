"""第八轮：点击【生成】抓取视频/图片提交端点 + /user 页签到按钮文本。"""
import asyncio, json, re
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
async def main():
    rec=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1600,"height":1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
                               {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"}])
        pg=await ctx.new_page()
        async def on_resp(r):
            u=r.url
            if not any(d in u for d in ("api2.liblib.art","bridge.liblib.art","api.liblib.tv")): return
            try: body=await r.text()
            except Exception: body=""
            rec.append({"m":r.request.method,"u":u,"pd":r.request.post_data,"b":body[:250]})
        pg.on("response",on_resp)
        # --- /user 页：找签到/算力按钮 ---
        await pg.goto("https://www.liblib.art/user",wait_until="domcontentloaded",timeout=45000)
        await pg.wait_for_timeout(5000)
        btns=await pg.eval_on_selector_all("button,a,[role=button]","els=>els.map(e=>(e.innerText||'').trim()).filter(t=>t&&t.length<24)")
        print("=== /user 页按钮文本 ===")
        print(sorted(set(btns))[:60])
        # --- 视频生成页：填提示词并点生成 ---
        await pg.goto("https://www.liblib.art/ai-tool/video-generator",wait_until="domcontentloaded",timeout=45000)
        await pg.wait_for_timeout(5000)
        try:
            ta=await pg.query_selector("textarea")
            if ta:
                await ta.click(); await ta.type("a red panda walking in snow", delay=25)
                await pg.wait_for_timeout(2500)
        except Exception as e: print("type warn",str(e)[:70])
        for sel in ["text=生成","button:has-text('生成')","text=立即生成","text=免费生成"]:
            try:
                el=await pg.query_selector(sel)
                if el:
                    await el.click(timeout=4000); print("clicked",sel); await pg.wait_for_timeout(7000); break
            except Exception as e: print("click warn",sel,str(e)[:50])
        await b.close()
    print("\n=== 提交/算力相关请求 ===")
    seen=set()
    for x in rec:
        if not any(k in x["u"] for k in ("generate","task","power","video","submit","publish","model/feed")): continue
        k=re.sub(r"\?.*","",x["u"])
        if k in seen: continue
        seen.add(k)
        print(f"\n{x['m']} {x['u']}")
        if x["pd"]: print("  REQ:", x["pd"][:600])
        print("  RES:", x["b"][:250])
asyncio.run(main())

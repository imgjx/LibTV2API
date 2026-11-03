"""第五轮：liblib.tv 侧端点 + 点击积分徽标找余额接口 + 找每日签到触发点。"""
import asyncio, json, re
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
BAL=("power","point","balance","remain","available","quota","算力","积分","credit")
async def main():
    resp_all=[]; tv=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1600,"height":900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        for d in (".liblib.art",".liblib.tv"):
            await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":d,"path":"/"},
                                   {"name":"webid","value":WEBID,"domain":d,"path":"/"}])
        pg=await ctx.new_page()
        async def on_resp(r):
            u=r.url
            if not any(x in u for x in ("api2.liblib.art","api.liblib.tv","api.liblib.art","bridge.liblib.art")): return
            try: body=await r.text()
            except Exception: body=""
            rec=(r.request.method,u,r.request.post_data or "",body)
            resp_all.append(rec)
            if "liblib.tv" in u: tv.append(rec)
        pg.on("response",on_resp)
        # --- liblib.tv 侧 ---
        for u in ["https://www.liblib.tv/","https://www.liblib.tv/canvas"]:
            try: await pg.goto(u,wait_until="domcontentloaded",timeout=40000)
            except Exception as e: print("warn tv",u,str(e)[:60])
            await pg.wait_for_timeout(5000)
        # --- liblib.art 点击积分徽标 ---
        try:
            await pg.goto("https://www.liblib.art/",wait_until="domcontentloaded",timeout=40000)
            await pg.wait_for_timeout(3000)
            for sel in ["text=积分超市","text=算力","[class*=point]","[class*=Point]","[class*=power]","[class*=Power]"]:
                try:
                    el=await pg.query_selector(sel)
                    if el:
                        await el.click(timeout=3000); await pg.wait_for_timeout(2500)
                        print("clicked",sel)
                except Exception: pass
        except Exception as e: print("warn art",str(e)[:60])
        await b.close()
    print("\n=== api.liblib.tv 全部端点 ===")
    seen=set()
    for m,u,req,body in tv:
        k=re.sub(r"\?.*","",u)
        if k in seen: continue
        seen.add(k); print(f"{m:4s} {u}\n      {body[:220]}")
    print("\n=== 含余额类字段的响应 ===")
    seen=set()
    for m,u,req,body in resp_all:
        low=body.lower()
        if not any(k in low for k in BAL): continue
        k=re.sub(r"\?.*","",u)
        if k in seen: continue
        seen.add(k); print(f"{m:4s} {u}\n      {body[:400]}\n")
asyncio.run(main())

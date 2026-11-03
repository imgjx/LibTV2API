"""第二轮抓包：专找积分(算力)余额与签到端点。"""
import asyncio, re
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
PAGES=["https://www.liblib.art/user","https://www.liblib.art/user/point","https://www.liblib.art/ai-tool/video-generator",
       "https://www.liblib.art/ai-tool/image-generator","https://www.liblib.art/?modal=signIn",
       "https://www.liblib.art/mine","https://www.liblib.art/activity"]
async def main():
    hits=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1440,"height":900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
                               {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"}])
        await ctx.add_init_script("try{localStorage.setItem('userToken',%r);localStorage.setItem('webid',%r)}catch(e){}"%(TOKEN,WEBID))
        pg=await ctx.new_page()
        def on_req(req):
            if req.resource_type not in ("xhr","fetch"): return
            u=req.url
            if "google-analytics" in u or "google.com" in u: return
            try: body=req.post_data or ""
            except Exception: body="<binary>"
            hits.append((req.method,u,body[:300]))
        pg.on("request",on_req)
        for u in PAGES:
            try: await pg.goto(u,wait_until="domcontentloaded",timeout=35000)
            except Exception as e: print("warn",u,str(e)[:70])
            await pg.wait_for_timeout(4000)
            # 尝试点击签到/算力相关按钮
            for sel in ["text=签到","text=每日签到","text=领取","[class*=sign]","[class*=Sign]","text=算力"]:
                try:
                    el=await pg.query_selector(sel)
                    if el: await el.click(timeout=3000); await pg.wait_for_timeout(2500)
                except Exception: pass
        await b.close()
    seen=set(); out=[]
    for m,u,bd in hits:
        k=re.sub(r"\?.*","",u)
        if k in seen: continue
        seen.add(k); out.append((m,u,bd))
    KW=("point","power","compute","sign","check","task","activity","award","reward","balance","integral","credit","daily")
    print(f"=== 全部 {len(out)} 个 API 请求 ===")
    for m,u,bd in out:
        mark="★★" if any(k in u.lower() for k in KW) else "  "
        print(f"{mark} {m:4s} {u.replace('https://api2.liblib.art','').replace('https://api.liblib.art','')}")
        if bd and bd!="<binary>": print("       BODY:",bd[:200])
asyncio.run(main())

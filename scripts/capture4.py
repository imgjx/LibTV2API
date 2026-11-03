"""第四轮：定位顶部「算力」徽标数据源 + 领取每日算力接口。"""
import asyncio, json, re
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
async def main():
    all_resp=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1600,"height":900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
                               {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"}])
        pg=await ctx.new_page()
        async def on_resp(resp):
            u=resp.url
            if not any(d in u for d in ("api2.liblib.art","api.liblib.tv","bridge.liblib.art")): return
            try: body=await resp.text()
            except Exception: return
            all_resp.append((resp.request.method,u,resp.request.post_data or "",body))
        pg.on("response",on_resp)
        await pg.goto("https://www.liblib.art/",wait_until="domcontentloaded",timeout=45000)
        await pg.wait_for_timeout(3500)
        # 提取所有含 "算力" 的元素文本
        els = await pg.query_selector_all("*")
        found=[]
        for el in els[:1200]:
            try:
                t=(await el.inner_text()).strip()
            except Exception: continue
            if re.search(r"算力|积分|\d+\s*点", t) and len(t)<60:
                found.append((await el.evaluate("e=>e.className||''"), t))
        print("=== 顶部/页面含算力的元素 ===")
        for c,t in found[:25]: print(f"  [{c[:60]}] {t!r}")
        await b.close()
    print("\n=== 所有 liblib API 响应（去重）===")
    seen=set()
    for m,u,req,body in all_resp:
        k=re.sub(r"\?.*","",u)
        if k in seen: continue
        seen.add(k)
        short=body[:200].replace("\n"," ")
        print(f"{m:4s} {u.replace('https://api2.liblib.art','').replace('https://api.liblib.tv','').replace('https://bridge.liblib.art/gateway/sd-api','')}\n      {short}")
asyncio.run(main())

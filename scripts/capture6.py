"""第六轮：录制 calculate-power / 每日算力领取 的原始请求（原样重放用）。"""
import asyncio, json
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
async def main():
    reqs=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1600,"height":900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
                               {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"}])
        pg=await ctx.new_page()
        async def on_resp(r):
            u=r.url
            if "calculate-power" not in u and "FreePower" not in u and "freePower" not in u: return
            try: body=await r.text()
            except Exception: body=""
            req=r.request
            reqs.append({"method":req.method,"url":u,"headers":await req.all_headers(),
                         "post_data":req.post_data,"resp":body[:300]})
        pg.on("response",on_resp)
        await pg.goto("https://www.liblib.art/ai-tool/video-generator",wait_until="domcontentloaded",timeout=45000)
        await pg.wait_for_timeout(6000)
        # 输入提示词触发算力计算
        for sel in ["textarea","input[type=text]"]:
            try:
                el=await pg.query_selector(sel)
                if el:
                    await el.click(timeout=3000)
                    await el.type("a happy cat running on the beach", delay=30)
                    await pg.wait_for_timeout(6000)
                    break
            except Exception as e: print("type warn",str(e)[:60])
        await pg.wait_for_timeout(4000)
        await b.close()
    print(f"=== 录制 {len(reqs)} 个请求 ===")
    print(json.dumps(reqs, ensure_ascii=False, indent=2)[:4000])
asyncio.run(main())

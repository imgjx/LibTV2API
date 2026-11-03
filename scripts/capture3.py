"""第三轮：读取 /user 页面显示的算力数值 + 捕获算力相关端点响应体。"""
import asyncio, json, re
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
async def main():
    bodies=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1440,"height":900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
                               {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"}])
        pg=await ctx.new_page()
        async def on_resp(resp):
            u=resp.url
            if "api2.liblib.art" not in u and "api.liblib.tv" not in u and "bridge" not in u: return
            if not any(k in u.lower() for k in ("power","point","member","activity","account","benefit","sign","user","task/","task/")): return
            try:
                txt=await resp.text()
            except Exception: return
            if any(k in txt for k in ("power","point","算力","积分","balance","sign")):
                bodies.append((resp.request.method,u,txt[:700]))
        pg.on("response",on_resp)
        for u in ["https://www.liblib.art/user","https://www.liblib.art/ai-tool/image-generator","https://www.liblib.art/ai-tool/video-generator"]:
            try: await pg.goto(u,wait_until="networkidle",timeout=40000)
            except Exception as e: print("warn",u,str(e)[:60])
            await pg.wait_for_timeout(3000)
        # 读取页面上的算力文本
        txt = await pg.inner_text("body")
        hits = re.findall(r"[^\n]{0,40}(?:算力|积分|点力|剩余)[^\n]{0,40}", txt)
        print("=== 页面文案中的算力/积分 ===")
        for h in set(hits): print("  ", h.strip())
        await b.close()
    print("\n=== 响应体含算力/积分的 API ===")
    seen=set()
    for m,u,t in bodies:
        k=re.sub(r"\?.*","",u)
        if k in seen: continue
        seen.add(k); print(f"\n{m} {u}\n  {t}")
asyncio.run(main())

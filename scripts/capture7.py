"""第七轮：在浏览器上下文内 fetch，验证算力端点 + 签到领取。"""
import asyncio, json
from playwright.async_api import async_playwright
TOKEN="1a16ab53b1794f3aa768005479d7218e12811145b5c68"; WEBID="1793630885191zlbfjflk"
JS = """
async ([payload]) => {
  const out = {};
  const h = {"Content-Type":"application/json","Token":%r,"Webid":%r};
  try {
    const r = await fetch("https://bridge.liblib.art/gateway/sd-api/generate/calculate-power/v1?timestamp="+Date.now(),
      {method:"POST",headers:h,body:JSON.stringify(payload)});
    out.calc = {status:r.status, body:(await r.text()).slice(0,300)};
  } catch(e){ out.calc = "ERR "+e; }
  try {
    const r2 = await fetch("https://api2.liblib.art/api/www/member/libtvFreePower",
      {method:"POST",headers:h,body:"{}"});
    out.freePower = {status:r2.status, body:(await r2.text()).slice(0,300)};
  } catch(e){ out.freePower = "ERR "+e; }
  try {
    const r3 = await fetch("https://api2.liblib.art/api/www/member/account?isApp=false",
      {method:"GET",headers:h});
    out.account = {status:r3.status, body:(await r3.text()).slice(0,500)};
  } catch(e){ out.account = "ERR "+e; }
  return out;
}
"""
async def main():
    gp=json.dumps({"prompt":"a cat","resolution":"1024x1024","model":"22111377","modeType":7,"seed":-1,"cfgScale":7},ensure_ascii=False)
    payload={"source":0,"bizType":22,"promptMagic":-1,"refinedTypeStr":"","generateType":40,"geniusPayload":gp,
             "originalPrompt":"a cat","taskQueuePriority":1,"referenceList":[],"additionalNetwork":[],
             "checkpointId":22111377,"infiniteSwitch":None,"disableBenefitTags":[""]}
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        await ctx.add_cookies([{"name":"usertoken","value":TOKEN,"domain":".liblib.art","path":"/"},
                               {"name":"webid","value":WEBID,"domain":".liblib.art","path":"/"}])
        pg=await ctx.new_page()
        await pg.goto("https://www.liblib.art/",wait_until="domcontentloaded",timeout=45000)
        await pg.wait_for_timeout(3000)
        res=await pg.evaluate(JS % (TOKEN, WEBID), [payload])
        print(json.dumps(res,ensure_ascii=False,indent=2))
        await b.close()
asyncio.run(main())

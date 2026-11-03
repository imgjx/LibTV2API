"""验证新功能：账号类型识别、模型可用性、交叉选号、监控、视频 dry_run。"""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, "/workspace/Liblib2API")

from liblib2api import panel_server as P
from liblib2api.accounts import AccountStore
from liblib2api.selector import AccountSelector

store = P._store
sel = P._selector

print("== 1) 用本机凭据注册账号池（自动识别类型）==")
res = P.seed_from_local_credential(note="主测副卡")
print(json.dumps(res, ensure_ascii=False, indent=2) if res else "无凭据")

print("\n== 2) 账号类型与模型可用性 ==")
acc = store.list()[0]
snap = P._sync_account(acc)
atype = snap["account_type"]
print("账号类型:", atype["type"], "| 名称:", atype["name"], "| 副卡:", atype["is_sub"])
print("免费权益模型 keys:", snap["free_benefit_keys"])
usable = snap["usable"]
vip_models = [k for k,v in usable.items() if v is False]
print(f"模型总数: {len(usable)}，其中当前账号不可用: {len(vip_models)}")
for k in vip_models[:8]:
    print("   不可用:", k)

print("\n== 3) 交叉选号 ==")
# 找一个 VIP 模型（不可用的）和一个可用的
vip_key = vip_models[0] if vip_models else None
free_key = next((k for k,v in usable.items() if v), None)
print("选 VIP 模型:", vip_key, "->", sel.select_for_model(vip_key))
print("选免费可用模型:", free_key, "->", sel.select_for_model(free_key))

print("\n== 4) 监控巡检一次 ==")
results = P._monitor.check_all()
for r in results:
    print(f"   {r.account}: ok={r.ok} type={r.account_type} points={r.points} free={r.free_power} checkin={r.checked_in} err={r.error}")

print("\n== 5) 视频生成 dry_run（多格式参数构建）==")
from liblib2api.video_output import VideoGenerateRequest, build_arguments, VIDEO_FORMATS
req = VideoGenerateRequest(prompt="测试视频", model=free_key, duration=10, resolution="1080p", fmt="webm", fps=30, aspect_ratio="16:9")
print("校验错误:", req.validate())
print("构建参数:", json.dumps(build_arguments(req, model_key=free_key), ensure_ascii=False))
# 走 HTTP 层 dry_run
from fastapi.testclient import TestClient
c = TestClient(P.app)
r = c.post("/api/v1/generate/video", json={"prompt":"测试","model":free_key,"format":"mp4","duration":5,"resolution":"720p","dry_run":True})
print("DRY_RUN HTTP 状态:", r.status_code)
print(json.dumps(r.json(), ensure_ascii=False)[:600])

print("\n== 6) /api/v1/accounts 视图 ==")
r = c.get("/api/v1/accounts")
print(json.dumps(r.json(), ensure_ascii=False)[:500])

print("\n== 全部验证完成 ==")

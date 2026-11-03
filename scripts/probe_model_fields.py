"""深挖模型对象里与会员限制相关的字段。"""
from __future__ import annotations
import json
import liblib2api.config as cfg
from liblib2api.credentials import CredentialStore
from liblib2api.webapi import WebApiClient

cs = CredentialStore()
creds = cs.get()
client = WebApiClient(access_token=creds.access_token, webid=creds.extra.get("webid"))

vms = client.video_models()
ims = client.image_models()

print("===== 视频模型全部 top-level 键 =====")
for m in vms:
    print(sorted(m.keys()))

print("\n===== 视频模型名称 + 疑似会员字段 =====")
for m in vms:
    flags = {k: m.get(k) for k in m.keys() if any(
        kw in k.lower() for kw in ("vip", "member", "level", "unlock", "auth", "limit", "power", "status", "open", "tag")
    )}
    print(f"- {m.get('modelName')!r}: {json.dumps(flags, ensure_ascii=False)}")

print("\n===== 图片模型名称 + 疑似会员字段 =====")
for m in ims:
    flags = {k: m.get(k) for k in m.keys() if any(
        kw in k.lower() for kw in ("vip", "member", "level", "unlock", "auth", "limit", "power", "status", "open", "tag")
    )}
    print(f"- {m.get('name')!r}: {json.dumps(flags, ensure_ascii=False)}")

client.close()

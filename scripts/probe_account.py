"""用已登录凭据探测会员信息与模型列表的真实结构。

仅用于开发期核对字段，输出会脱敏 token。
"""
from __future__ import annotations

import json
import time

import liblib2api.config as cfg
from liblib2api.credentials import CredentialStore
from liblib2api.webapi import WebApiClient


def redact(text: str) -> str:
    tok = cs.get().access_token
    return text.replace(tok, "***TOKEN***")


cs = CredentialStore()
creds = cs.get()
acc = cfg.ACCOUNTS_FILE  # noqa: F841

client = WebApiClient(
    access_token=creds.access_token,
    webid=creds.extra.get("webid"),
)

print("===== 会员信息 member/account =====")
ma = client.member_account()
print(json.dumps(ma, ensure_ascii=False, indent=2)[:2000])

print("\n===== 免费算力 libtvFreePower =====")
fp = client.free_power()
print(json.dumps(fp, ensure_ascii=False, indent=2)[:800])

print("\n===== 视频模型 video/recommend-models (前 2 个原始结构) =====")
vms = client.video_models()
print("视频模型数量:", len(vms))
print(json.dumps(vms[:2], ensure_ascii=False, indent=2)[:2500])

print("\n===== 图片模型 modelCard/config (前 2 个原始结构) =====")
ims = client.image_models()
print("图片模型数量:", len(ims))
print(json.dumps(ims[:2], ensure_ascii=False, indent=2)[:2500])

print("\n===== 权益 activity/benefit =====")
try:
    b = client.daily_benefits()
    print(json.dumps(b, ensure_ascii=False, indent=2)[:1200])
except Exception as e:
    print("benefit error:", e)

client.close()

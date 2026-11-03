"""探测 liblib Web API 的真实鉴权头与端点（诊断用，可删）。"""
import httpx, json, sys, itertools

TOK = "1a16ab53b1794f3aa768005479d7218e12811145b5c68"
WEBID = "1793630885191zlbfjflk"
UID = "12811145"
BASE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Origin": "https://www.liblib.art",
    "Referer": "https://www.liblib.art/",
    "Accept": "application/json, text/plain, */*",
}

AUTH_VARIANTS = {
    "none": {},
    "bearer": {"Authorization": f"Bearer {TOK}"},
    "usertoken_hdr": {"usertoken": TOK},
    "cookie_tok": {"Cookie": f"usertoken={TOK}"},
    "cookie_tok_uid": {"Cookie": f"usertoken={TOK}; user_id={UID}"},
    "cookie_tok_wid": {"Cookie": f"usertoken={TOK}; webid={WEBID}"},
    "cookie_full": {"Cookie": f"usertoken={TOK}; user_id={UID}; webid={WEBID}"},
    "hdr_tok_wid": {"usertoken": TOK, "webid": WEBID},
}

ENDPOINTS = [
    ("POST", "https://passport.liblib.art/api/www/user/getUserInfo", {}),
    ("GET",  "https://api.liblib.art/api/user/info", None),
    ("GET",  "https://api.liblib.art/api/user/point", None),
    ("POST", "https://api.liblib.art/api/user/getUserInfo", {}),
]

def call(method, url, body, hdr):
    h = dict(BASE); h.update(hdr)
    try:
        r = httpx.request(method, url, json=body, headers=h, timeout=15, follow_redirects=True)
        t = r.text.strip().replace("\n", " ")
        return f"{r.status_code} {t[:170]}"
    except Exception as e:
        return f"ERR {type(e).__name__} {str(e)[:110]}"

for (m, u, b), (an, ah) in itertools.product(ENDPOINTS, AUTH_VARIANTS.items()):
    out = call(m, u, b, ah)
    tag = "HIT" if ("未登录" not in out and "No login" not in out and "ERR" not in out) else "   "
    print(f"{tag} {an:16s} {m:4s} {u.replace('https://',''):52s} {out}")

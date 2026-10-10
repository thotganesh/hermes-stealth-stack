#!/usr/bin/env python3
"""
Camofox Router — un solo endpoint, tre backend (VPS/Tor/I2P).
"""
import os
import re
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()

BACKENDS = {
    "vps": os.environ.get("CAMOFOX_VPS_URL", "http://camofox:9377"),
    "tor": os.environ.get("CAMOFOX_TOR_URL", "http://camofox-tor:9377"),
    "i2p": os.environ.get("CAMOFOX_I2P_URL", "http://camofox-i2p:9377"),
}

SESSIONS = {}     # sessionKey -> backend
TAB_BACKENDS = {} # tabId -> backend
USER_BACKENDS = {} # userId -> backend

PREFIX_RE = re.compile(r"^(tor|i2p)\+(.*)$", re.IGNORECASE)


def _pick(url: str):
    if not url:
        return "vps", url
    m = PREFIX_RE.match(url)
    if m:
        return m.group(1).lower(), m.group(2)
    if ".onion" in url:
        return "tor", url
    if ".i2p" in url:
        return "i2p", url
    return "vps", url


@app.get("/health")
async def health():
    out = {}
    async with httpx.AsyncClient(timeout=3) as c:
        for n, base in BACKENDS.items():
            try:
                r = await c.get(f"{base}/health")
                out[n] = r.json()
            except Exception as e:
                out[n] = {"error": str(e)}
    return out


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    import json as _json
    backend = None
    body_json = None

    if request.method == "POST":
        try:
            body_json = await request.json()
        except Exception:
            body_json = None

    # 1. Se POST /tabs con url, scegli backend
    if body_json and path == "tabs":
        url = body_json.get("url", "")
        sk = body_json.get("sessionKey")
        uid = body_json.get("userId")
        if sk and sk in SESSIONS:
            backend = SESSIONS[sk]
            picked, clean = _pick(url)
            if picked != "vps":
                backend = picked
                body_json["url"] = clean
        else:
            picked, clean = _pick(url)
            backend = picked
            if picked != "vps":
                body_json["url"] = clean
            if sk:
                SESSIONS[sk] = backend
        if uid:
            USER_BACKENDS[uid] = backend

    # 2. Se GET/POST su tab specifico, usa tabId o userId o sessionKey per instradare
    if backend is None:
        # a. tabId nel path?
        m = re.search(r"tabs/([a-f0-9-]{36})", path)
        if m:
            tab_id = m.group(1)
            backend = TAB_BACKENDS.get(tab_id)
        # b. userId nei query params?
        if backend is None:
            uid = request.query_params.get("userId")
            if uid and uid in USER_BACKENDS:
                backend = USER_BACKENDS[uid]
        # c. sessionKey nei query params?
        if backend is None:
            sk = request.query_params.get("sessionKey")
            if sk and sk in SESSIONS:
                backend = SESSIONS[sk]

    if backend is None:
        backend = "vps"

    # 3. Inoltra
    target = f"{BACKENDS[backend]}/{path}"
    if request.url.query:
        target += f"?{request.url.query}"

    h = dict(request.headers)
    h.pop("host", None)
    h.pop("content-length", None)

    async with httpx.AsyncClient(timeout=120) as c:
        if body_json is not None:
            r = await c.request(request.method, target, json=body_json, headers=h)
        else:
            body = await request.body()
            r = await c.request(request.method, target, content=body, headers=h)

    # 4. Se è una POST /tabs andata a buon fine, salva tabId -> backend
    if request.method == "POST" and path == "tabs" and r.status_code == 200:
        try:
            resp_json = r.json()
            tid = resp_json.get("tabId")
            if tid:
                TAB_BACKENDS[tid] = backend
        except Exception:
            pass

    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9378)

#!/usr/bin/env python3
"""
Camofox Router - one endpoint, three backends (VPS/Tor/I2P).

Prefix in URL:
  tor+https://...  -> camofox-tor
  i2p+http://...   -> camofox-i2p
  https://...      -> camofox (VPS)
  *.onion          -> camofox-tor (auto)
  *.i2p            -> camofox-i2p (auto)
"""
import os
import re
import time
import json
import httpx
from collections import OrderedDict
from fastapi import FastAPI, Request, Response

app = FastAPI()

BACKENDS = {
    "vps": os.environ.get("CAMOFOX_VPS_URL", "http://camofox:9377"),
    "tor": os.environ.get("CAMOFOX_TOR_URL", "http://camofox-tor:9377"),
    "i2p": os.environ.get("CAMOFOX_I2P_URL", "http://camofox-i2p:9377"),
}

# TTL per le mappe in memoria (secondi). Dopo questo tempo le entry scadono.
STATE_TTL = int(os.environ.get("ROUTER_STATE_TTL", "3600"))  # 1 ora
MAX_ENTRIES = int(os.environ.get("ROUTER_MAX_ENTRIES", "10000"))


class TTLCache:
    """Simple TTL + LRU-bounded dict. Thread-safe enough for our single worker."""

    def __init__(self, ttl: int, max_entries: int):
        self._ttl = ttl
        self._max = max_entries
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str):
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > self._ttl:
            del self._data[key]
            return None
        # touch: move to end for LRU
        self._data.move_to_end(key)
        return val

    def set(self, key: str, val: str):
        self._data[key] = (time.time(), val)
        self._data.move_to_end(key)
        # evict oldest if over capacity
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def cleanup(self):
        now = time.time()
        stale = [k for k, (ts, _) in self._data.items() if now - ts > self._ttl]
        for k in stale:
            del self._data[k]


SESSIONS = TTLCache(STATE_TTL, MAX_ENTRIES)
TAB_BACKENDS = TTLCache(STATE_TTL, MAX_ENTRIES)
USER_BACKENDS = TTLCache(STATE_TTL, MAX_ENTRIES)

PREFIX_RE = re.compile(r"^(tor|i2p)\+(.*)$", re.IGNORECASE)
# tabId is usually a UUID v4 (36 chars) but we accept any hex+hyphen token >=16 chars
TABID_RE = re.compile(r"tabs/([a-zA-Z0-9-]{16,})")


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


@app.get("/router/stats")
async def stats():
    return {
        "sessions": len(SESSIONS._data),
        "tabs": len(TAB_BACKENDS._data),
        "users": len(USER_BACKENDS._data),
        "ttl_seconds": STATE_TTL,
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    backend = None
    body_json = None

    if request.method == "POST":
        try:
            body_json = await request.json()
        except Exception:
            body_json = None

    # 1. POST /tabs with url: pick backend
    if body_json and path == "tabs":
        url = body_json.get("url", "")
        sk = body_json.get("sessionKey")
        uid = body_json.get("userId")
        if sk and SESSIONS.get(sk):
            backend = SESSIONS.get(sk)
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
                SESSIONS.set(sk, backend)
        if uid:
            USER_BACKENDS.set(uid, backend)

    # 2. Route GET/POST on a specific tab: use tabId, userId or sessionKey
    if backend is None:
        m = TABID_RE.search(path)
        if m:
            tab_id = m.group(1)
            backend = TAB_BACKENDS.get(tab_id)
            # CRITICAL: if we know the request targets a tab but can't
            # resolve its backend, DO NOT silently fall back to VPS.
            # That would leak an anonymous session through the host IP.
            if backend is None:
                return Response(
                    content=json.dumps({
                        "error": "tab backend unknown (expired or router restarted)",
                        "code": "tab_backend_unknown",
                        "hint": "create a new tab with POST /tabs",
                    }),
                    status_code=409,
                    media_type="application/json",
                )

        if backend is None:
            uid = request.query_params.get("userId")
            if uid:
                backend = USER_BACKENDS.get(uid)

        if backend is None:
            sk = request.query_params.get("sessionKey")
            if sk:
                backend = SESSIONS.get(sk)

    if backend is None:
        backend = "vps"

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

    # 3. On successful POST /tabs, remember tabId -> backend
    if request.method == "POST" and path == "tabs" and r.status_code == 200:
        try:
            resp_json = r.json()
            tid = resp_json.get("tabId")
            if tid:
                TAB_BACKENDS.set(tid, backend)
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

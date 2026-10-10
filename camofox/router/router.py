#!/usr/bin/env python3
"""Camofox Router v2 - fail-closed. Backends: vps / tor / i2p."""
import os, re, json, time, ipaddress
from collections import OrderedDict
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()

BACKENDS = {
    "vps": os.environ.get("CAMOFOX_VPS_URL", "http://camofox:9377"),
    "tor": os.environ.get("CAMOFOX_TOR_URL", "http://camofox-tor:9377"),
    "i2p": os.environ.get("CAMOFOX_I2P_URL", "http://camofox-i2p:9377"),
}
STATE_TTL = int(os.environ.get("ROUTER_STATE_TTL", "3600"))
MAX_ENTRIES = int(os.environ.get("ROUTER_MAX_ENTRIES", "10000"))
ALLOW_UPLOAD = os.environ.get("ROUTER_ALLOW_UPLOAD", "0") == "1"


class TTLCache:
    """TTL scorrevole + LRU."""
    def __init__(self, ttl, max_entries):
        self._ttl, self._max = ttl, max_entries
        self._data = OrderedDict()

    def get(self, key):
        e = self._data.get(key)
        if e is None:
            return None
        ts, val = e
        now = time.time()
        if now - ts > self._ttl:
            del self._data[key]
            return None
        self._data[key] = (now, val)
        self._data.move_to_end(key)
        return val

    def set(self, key, val):
        self._data[key] = (time.time(), val)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def delete(self, key):
        self._data.pop(key, None)


SESSIONS = TTLCache(STATE_TTL, MAX_ENTRIES)       # sessionKey -> backend
TAB_BACKENDS = TTLCache(STATE_TTL, MAX_ENTRIES)   # tabId -> backend
USER_BACKENDS = TTLCache(STATE_TTL, MAX_ENTRIES)  # userId -> [backend,...]

PREFIX_RE = re.compile(r"^(tor|i2p)\+(.*)$", re.IGNORECASE | re.DOTALL)
TAB_PATH = re.compile(r"^tabs/([A-Za-z0-9-]{16,})(/[a-z-]+)?$")
SESS_PATH = re.compile(r"^sessions/([^/]+)(/(?:cookies|traces)(?:/[^/]+)?)?$")
NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*")
HOP = {"host", "content-length", "connection", "transfer-encoding", "x-camofox-backend"}


def _err(status, code, **extra):
    return Response(json.dumps({"error": code, **extra}),
                    status_code=status, media_type="application/json")


def _wanted(url):
    """-> (backend esplicito o None, url pulito). Decide sull'hostname."""
    if not isinstance(url, str) or not url:
        return None, url
    m = PREFIX_RE.match(url)
    if m:
        return m.group(1).lower(), m.group(2)
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None, url
    if host.endswith(".onion"):
        return "tor", url
    if host.endswith(".i2p"):
        return "i2p", url
    return None, url


def _check_url(url, backend):
    """None se ok, altrimenti messaggio di errore."""
    if not url:
        return None
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return "url non valido"
    if u.scheme not in ("http", "https"):
        return "schema non consentito"
    if not host:
        return "host mancante"
    if backend != "vps":
        return None
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return "host non consentito"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            return "IP non pubblico"
    elif NUMERIC_HOST.fullmatch(host):
        return "host numerico ambiguo"
    elif "." not in host:
        return "host senza dominio (rete interna?)"
    return None


@app.get("/health")
async def health():
    out = {}
    async with httpx.AsyncClient(timeout=3) as c:
        for n, base in BACKENDS.items():
            try:
                out[n] = (await c.get(f"{base}/health")).json()
            except Exception as e:
                out[n] = {"error": str(e)}
    return out


@app.get("/router/stats")
async def stats():
    return {"sessions": len(SESSIONS._data), "tabs": len(TAB_BACKENDS._data),
            "users": len(USER_BACKENDS._data), "ttl_seconds": STATE_TTL}


async def _send(client, backend, method, path, query, headers, body_json, raw):
    target = f"{BACKENDS[backend]}/{path}"
    if query:
        target += f"?{query}"
    if body_json is not None:
        return await client.request(method, target, json=body_json, headers=headers)
    return await client.request(method, target, content=raw, headers=headers)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    method = request.method
    create = path == "tabs" and method == "POST"
    listing = path == "tabs" and method == "GET"
    tab_m = TAB_PATH.match(path)
    sess_m = SESS_PATH.match(path)

    if not (create or listing or tab_m or sess_m):
        return _err(404, "route_not_supported",
                    hint="global/legacy endpoints are blocked by the router")

    raw, body_json = None, None
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        raw = await request.body()
        if raw:
            try:
                body_json = json.loads(raw)
            except Exception:
                return _err(400, "invalid_json")
            if not isinstance(body_json, dict):
                return _err(400, "invalid_json", hint="object expected")

    targets, uid, action = [], None, ""

    if create:
        if body_json is None:
            return _err(400, "body_required")
        if "proxy" in body_json:
            return _err(400, "proxy_override_not_allowed")
        url = body_json.get("url", "")
        sk, uid = body_json.get("sessionKey"), body_json.get("userId")
        wanted, clean = _wanted(url)
        backend = wanted or (SESSIONS.get(sk) if sk else None) or "vps"
        msg = _check_url(clean, backend)
        if msg:
            return _err(400, "url_rejected", detail=msg)
        if url:
            body_json["url"] = clean
        if sk and SESSIONS.get(sk) is None:
            SESSIONS.set(sk, backend)
        targets = [backend]

    elif tab_m:
        tab_id, action = tab_m.group(1), tab_m.group(2) or ""
        if action == "/upload" and not ALLOW_UPLOAD:
            return _err(403, "upload_disabled", hint="set ROUTER_ALLOW_UPLOAD=1")
        backend = TAB_BACKENDS.get(tab_id)
        if backend is None:
            return _err(409, "tab_backend_unknown",
                        hint="expired or router restarted: create a new tab")
        if body_json and "url" in body_json:
            wanted, clean = _wanted(body_json["url"])
            if wanted and wanted != backend:
                return _err(409, "backend_mismatch",
                            tab_backend=backend, requested=wanted)
            msg = _check_url(clean, backend)
            if msg:
                return _err(400, "url_rejected", detail=msg)
            body_json["url"] = clean
        targets = [backend]

    elif sess_m:
        uid = sess_m.group(1)
        known = USER_BACKENDS.get(uid) or []
        forced = request.headers.get("x-camofox-backend")
        if forced:
            if forced not in known:
                return _err(409, "backend_not_known_for_user", known=known)
            targets = [forced]
        elif not known:
            return _err(409, "session_backend_unknown")
        elif method == "DELETE" and path == f"sessions/{uid}":
            targets = list(known)
        elif len(known) == 1:
            targets = list(known)
        else:
            return _err(409, "ambiguous_backend", known=known,
                        hint="send header X-Camofox-Backend")

    else:  # GET /tabs
        uid = request.query_params.get("userId")
        known = (USER_BACKENDS.get(uid) or []) if uid else []
        if len(known) != 1:
            return _err(409, "backend_unknown_or_ambiguous", hint="pass userId (single backend)")
        targets = list(known)

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    query = request.url.query

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            if len(targets) > 1:
                out = {}
                for b in targets:
                    try:
                        out[b] = (await _send(c, b, method, path, query, headers, None, raw)).status_code
                    except httpx.HTTPError as e:
                        out[b] = f"error: {e}"
                if all(isinstance(v, int) and v < 300 for v in out.values()):
                    USER_BACKENDS.delete(uid)
                return Response(json.dumps(out), media_type="application/json")
            backend = targets[0]
            r = await _send(c, backend, method, path, query, headers, body_json, raw)
    except httpx.HTTPError as e:
        return _err(502, "backend_unreachable", backend=targets[0], detail=str(e))

    ok = 200 <= r.status_code < 300
    if create and ok:
        try:
            tid = r.json().get("tabId")
            if tid:
                TAB_BACKENDS.set(tid, backend)
                if uid:
                    USER_BACKENDS.set(uid, sorted(set(USER_BACKENDS.get(uid) or []) | {backend}))
        except Exception:
            pass
    if tab_m and method == "DELETE" and not action and ok:
        TAB_BACKENDS.delete(tab_m.group(1))
    if sess_m and method == "DELETE" and path == f"sessions/{uid}" and ok:
        USER_BACKENDS.delete(uid)

    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9378)

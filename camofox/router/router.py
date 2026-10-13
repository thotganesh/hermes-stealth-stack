#!/usr/bin/env python3
"""Camofox Router v3 - fail-closed, multi-engine. Backends: vps / tor / i2p.

Modello: ogni tab "pubblica" (quella che Hermes conosce) e' un TABSET:
  {uid, lk, active, tabs: {backend: realTabId}}
Snapshot/click/type vanno sempre al tab attivo. Navigare con un prefisso
esplicito (vps+, tor+, i2p+) su un backend diverso NON naviga mai il tab
sbagliato: crea (o riattiva) un tab sul backend richiesto e parcheggia l'altro.
"""
import os, re, json, time, ipaddress, logging, socket
from collections import OrderedDict
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()
log = logging.getLogger("uvicorn.error")

BACKENDS = {
    "vps": os.environ.get("CAMOFOX_VPS_URL", "http://camofox:9377"),
    "tor": os.environ.get("CAMOFOX_TOR_URL", "http://camofox-tor:9377"),
    "i2p": os.environ.get("CAMOFOX_I2P_URL", "http://camofox-i2p:9377"),
}
STATE_TTL = int(os.environ.get("ROUTER_STATE_TTL", "3600"))
MAX_ENTRIES = int(os.environ.get("ROUTER_MAX_ENTRIES", "10000"))
ALLOW_UPLOAD = os.environ.get("ROUTER_ALLOW_UPLOAD", "0") == "1"
AUTO_SWITCH = os.environ.get("ROUTER_AUTO_SWITCH", "1") == "1"
ROUTER_API_KEY = os.environ.get("ROUTER_API_KEY", "").strip()

# Backend di default per i nuovi tab senza prefisso (vps / tor / i2p).
# Override con ROUTER_DEFAULT_BACKEND. Valore non valido -> "vps".
DEFAULT_BACKEND = os.environ.get("ROUTER_DEFAULT_BACKEND", "vps").strip() or "vps"
if DEFAULT_BACKEND not in BACKENDS:
    DEFAULT_BACKEND = "vps"



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

    def peek(self, key):
        """Come get() ma senza rinnovare il TTL."""
        e = self._data.get(key)
        if e is None:
            return None
        if time.time() - e[0] > self._ttl:
            del self._data[key]
            return None
        return e[1]

    def set(self, key, val):
        self._data[key] = (time.time(), val)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def delete(self, key):
        self._data.pop(key, None)


SESSIONS = TTLCache(STATE_TTL, MAX_ENTRIES)       # sessionKey/listItemId -> backend
TABSETS = TTLCache(STATE_TTL, MAX_ENTRIES)        # publicTabId -> tabset
REAL_INDEX = TTLCache(STATE_TTL, MAX_ENTRIES)     # realTabId -> publicTabId
USER_BACKENDS = TTLCache(STATE_TTL, MAX_ENTRIES)  # userId -> {backend: set(publicTabId)}

PREFIX_RE = re.compile(r"^(vps|tor|i2p)\+(.*)$", re.IGNORECASE | re.DOTALL)
TAB_PATH = re.compile(r"^tabs/([A-Za-z0-9-]{16,})(/[a-z-]+)?$")
SESS_PATH = re.compile(r"^sessions/([A-Za-z0-9_-]{1,128})(/(?:cookies|traces)(?:/[^/]+)?)?$")
NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*")
HOP = {"host", "content-length", "connection", "transfer-encoding",
       "x-camofox-backend", "authorization"}


def _err(status, code, **extra):
    return Response(json.dumps({"error": code, **extra}),
                    status_code=status, media_type="application/json")


def _jresp(obj, backend=None, status=200):
    h = {"x-router-backend": backend} if backend else None
    return Response(json.dumps(obj), status_code=status,
                    media_type="application/json", headers=h)


def _passthrough(r, backend):
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"),
                    headers={"x-router-backend": backend})


def _okstatus(code):
    return isinstance(code, int) and (200 <= code < 300 or code == 404)


def _wanted(url):
    """-> (backend esplicito o None, url pulito). Decide sull'hostname."""
    if not isinstance(url, str) or not url:
        return None, url
    m = PREFIX_RE.match(url)
    if m:
        prefix = m.group(1).lower()
        if prefix in BACKENDS:
            return prefix, m.group(2)
        # Unknown prefix: leave the URL untouched; _check_url will reject
        # the scheme instead of causing a KeyError in _send.
        return None, url
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None, url
    if host.endswith(".onion"):
        return "tor", url
    if host.endswith(".i2p"):
        return "i2p", url
    return None, url


_PRIV_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa", ".docker", ".svc")
_DNS_TTL = 60
_DNS_CACHE = {}


def _resolve_sync(host):
    """Ritorna la lista di IP (ipaddress) o None se il nome non risolve."""
    now = time.time()
    hit = _DNS_CACHE.get(host)
    if hit and now - hit[0] < _DNS_TTL:
        return hit[1]
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return None
    ips = []
    for _, _, _, _, sockaddr in infos:
        try:
            ips.append(ipaddress.ip_address(sockaddr[0].split("%")[0]))
        except ValueError:
            continue
    if len(_DNS_CACHE) > 2000:
        _DNS_CACHE.clear()
    _DNS_CACHE[host] = (now, ips)
    return ips


def _check_url(url, backend):
    """None se ok, altrimenti messaggio di errore. Fail-closed."""
    if not url:
        return None
    if not isinstance(url, str):
        return "url non valido"
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower().rstrip(".")
    except (ValueError, TypeError):
        return "url non valido"
    if u.scheme not in ("http", "https"):
        return "schema non consentito"
    if not host:
        return "host mancante"
    if u.username or u.password:
        return "userinfo non consentito"

    # .onion / .i2p: mai via clearnet, mai risolti in DNS locale
    if host.endswith(".onion"):
        return None if backend == "tor" else "host .onion richiede il backend tor"
    if host.endswith(".i2p"):
        return None if backend == "i2p" else "host .i2p richiede il backend i2p"

    # Nomi interni: mai consentiti, qualunque backend
    if host == "localhost" or host.endswith(_PRIV_SUFFIXES):
        return "host non consentito"

    # IP letterali: controllati SEMPRE, anche per tor/i2p
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.version == 6 and getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return "IP non pubblico"
        return None

    if NUMERIC_HOST.fullmatch(host):
        return "host numerico ambiguo"
    if "." not in host:
        return "host senza dominio (rete interna?)"

    # Solo clearnet: risolvi il nome e verifica TUTTI i record A/AAAA.
    # Per tor/i2p NON risolvere (perderebbe DNS/anonimato).
    if backend != "vps":
        return None
    ips = _resolve_sync(host)
    if ips is None:
        return "DNS non risolvibile"
    for a in ips:
        if a.version == 6 and getattr(a, "ipv4_mapped", None):
            a = a.ipv4_mapped
        if not a.is_global:
            return "IP non pubblico (DNS)"
    return None


# ---------------------------------------------------------------- stato

def _register(uid, pub, backend, real, lk=None, activate=True):
    ts = TABSETS.peek(pub)
    if ts is None:
        ts = {"uid": uid, "lk": lk, "active": backend, "tabs": {}}
        TABSETS.set(pub, ts)
    ts["tabs"][backend] = real
    if activate:
        ts["active"] = backend
    if lk and not ts.get("lk"):
        ts["lk"] = lk
    REAL_INDEX.set(real, pub)
    if uid:
        ub = USER_BACKENDS.peek(uid)
        if ub is None:
            ub = {}
            USER_BACKENDS.set(uid, ub)
        ub.setdefault(backend, set()).add(pub)


def _unregister(pub):
    ts = TABSETS.peek(pub)
    if not ts:
        return
    for real in ts["tabs"].values():
        REAL_INDEX.delete(real)
    ub = USER_BACKENDS.peek(ts.get("uid")) if ts.get("uid") else None
    if ub:
        for b in ub:
            ub[b].discard(pub)  # la chiave resta: il backend e' "noto" per la sessione
    TABSETS.delete(pub)


def _drop_backend_for_user(uid, backend):
    """Dopo DELETE /sessions/<uid> riuscito su un backend."""
    ub = USER_BACKENDS.peek(uid)
    if not ub:
        return
    for pub in list(ub.get(backend, ())):
        ts = TABSETS.peek(pub)
        if not ts:
            continue
        real = ts["tabs"].pop(backend, None)
        if real:
            REAL_INDEX.delete(real)
        if not ts["tabs"]:
            TABSETS.delete(pub)
        elif ts["active"] == backend:
            ts["active"] = sorted(ts["tabs"])[0]
    ub.pop(backend, None)
    if not ub:
        USER_BACKENDS.delete(uid)


def _user_state(uid):
    """{backend: set(pub vivi)} - le chiavi senza tab restano (backend 'noti')."""
    ub = USER_BACKENDS.peek(uid) or {}
    for b in list(ub):
        ub[b] = {p for p in ub[b]
                 if (TABSETS.peek(p) or {}).get("tabs", {}).get(b)}
    return ub


# ---------------------------------------------------------------- endpoint

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
    return {"sessions": len(SESSIONS._data), "tabs": len(TABSETS._data),
            "users": len(USER_BACKENDS._data), "ttl_seconds": STATE_TTL,
            "auto_switch": AUTO_SWITCH}


async def _send(client, backend, method, path, query, headers, body_json, raw):
    target = f"{BACKENDS[backend]}/{path}"
    if query:
        target += f"?{query}"
    if body_json is not None:
        return await client.request(method, target, json=body_json, headers=headers)
    return await client.request(method, target, content=raw, headers=headers)


async def _list_tabs(c, uid, headers):
    """GET /tabs?userId=: sola lettura (nessun egress) -> merge di piu' backend."""
    state = _user_state(uid)
    targets = sorted(state) or sorted(BACKENDS)  # utente ignoto (router riavviato): sonda tutti
    results, per_backend = {}, {}
    for b in targets:
        try:
            r = await _send(c, b, "GET", "tabs", f"userId={uid}", headers, None, None)
            per_backend[b] = r.status_code
            if r.status_code < 300:
                results[b] = [t for t in (r.json().get("tabs") or []) if isinstance(t, dict)]
        except Exception as e:
            per_backend[b] = f"error: {e}"
    if not results:
        return _err(502, "backend_unreachable", backends=per_backend)
    count = {}
    for tabs in results.values():
        for t in tabs:
            count[t.get("tabId")] = count.get(t.get("tabId"), 0) + 1
    merged = []
    for b, tabs in results.items():
        for t in tabs:
            tid = t.get("tabId")
            if not tid:
                continue
            pub = REAL_INDEX.peek(tid) or (tid if TABSETS.peek(tid) else None)
            if pub is None and count[tid] == 1:   # riabilita dopo restart del router
                _register(uid, tid, b, tid, lk=t.get("listItemId"))
                pub = tid
            item = dict(t)
            item["backend"] = b
            ts = TABSETS.peek(pub) if pub else None
            item["_active"] = bool(ts and ts["active"] == b and ts["tabs"].get(b) == tid)
            merged.append(item)
    merged.sort(key=lambda t: t["_active"])      # gli attivi in coda (Hermes adotta l'ultimo)
    for t in merged:
        t.pop("_active", None)
    return _jresp({"tabs": merged, "backends": per_backend})


async def _tab_alive(c, backend, uid, real, headers):
    """True/False se il backend conosce il tab; None se non verificabile (non droppare)."""
    try:
        r = await _send(c, backend, "GET", "tabs", f"userId={uid}", headers, None, None)
        if r.status_code >= 300:
            return None
        return any(isinstance(t, dict) and t.get("tabId") == real
                   for t in (r.json().get("tabs") or []))
    except Exception:
        return None


def _drop_tab(ts, backend):
    real = ts["tabs"].pop(backend, None)
    if real:
        REAL_INDEX.delete(real)
    return real


async def _switch(c, pub, ts, wanted, clean, body_json, headers):
    """navigate con backend esplicito diverso da quello attivo. Mai sul tab sbagliato."""
    prev = ts["active"]
    uid = ts.get("uid") or body_json.get("userId")
    real = ts["tabs"].get(wanted)
    recreated = False
    if not clean:                                    # "tor+" da solo: riattiva senza ricaricare
        if not real:
            return _err(409, "no_tab_on_backend", backend=wanted,
                        hint=f"navigate to {wanted}+https://... to open one")
        if await _tab_alive(c, wanted, uid, real, headers) is False:
            _drop_tab(ts, wanted)
            log.warning("switch pub=%s %s->%s: tab morto sul backend, rimosso", pub, prev, wanted)
            return _err(409, "no_tab_on_backend", backend=wanted, detail="tab_gone",
                        hint=f"navigate to {wanted}+https://... to open a new one")
        ts["active"] = wanted
        if ts.get("lk"):
            SESSIONS.set(ts["lk"], wanted)
        log.info("switch pub=%s %s->%s (riattivato)", pub, prev, wanted)
        return _jresp({"ok": True, "switched": True, "tabId": pub, "backend": wanted,
                       "switched_from": prev, "url": ""}, wanted)
    msg = _check_url(clean, wanted)
    if msg:
        return _err(400, "url_rejected", detail=msg)
    if real:                                         # tab parcheggiato: navigalo
        nb = dict(body_json)
        nb["url"] = clean
        r = await _send(c, wanted, "POST", f"tabs/{real}/navigate", "", headers, nb, None)
        if r.status_code in (404, 410):
            log.warning("switch pub=%s %s->%s: tab parcheggiato morto (%s), ricreo",
                        pub, prev, wanted, r.status_code)
            _drop_tab(ts, wanted)
            real = None
            recreated = True
        else:
            if 200 <= r.status_code < 300:
                ts["active"] = wanted
                if ts.get("lk"):
                    SESSIONS.set(ts["lk"], wanted)
                log.info("switch pub=%s %s->%s (navigate su tab parcheggiato)", pub, prev, wanted)
            return _passthrough(r, wanted)
    nb = {"userId": uid, "url": clean}               # nuovo tab sul backend giusto
    if ts.get("lk"):
        nb["listItemId"] = ts["lk"]
    r = await _send(c, wanted, "POST", "tabs", "", headers, nb, None)
    if not 200 <= r.status_code < 300:
        return _passthrough(r, wanted)
    try:
        new_real = r.json().get("tabId")
    except Exception:
        new_real = None
    if not new_real:
        return _err(502, "backend_bad_response", backend=wanted)
    _register(uid, pub, wanted, new_real, lk=ts.get("lk"), activate=True)
    if ts.get("lk"):
        SESSIONS.set(ts["lk"], wanted)
    log.info("switch pub=%s %s->%s (nuovo tab %s)", pub, prev, wanted, new_real)
    out = r.json()
    out.update({"tabId": pub, "backend": wanted, "switched_from": prev, "switched": True,
                "recreated": recreated})
    return _jresp(out, wanted)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    method = request.method

    if ROUTER_API_KEY:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:].strip() != ROUTER_API_KEY:
            return _err(401, "unauthorized",
                        hint="set Authorization: Bearer <ROUTER_API_KEY>")

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

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    query = request.url.query
    targets, uid, action, fwd_path, pub, lk = [], None, "", path, None, None

    if listing:
        uid = request.query_params.get("userId")
        if not uid:
            return _err(400, "userId_required")
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                return await _list_tabs(c, uid, headers)
        except httpx.HTTPError as e:
            return _err(502, "backend_unreachable", detail=str(e))

    if create:
        if body_json is None:
            return _err(400, "body_required")
        if "proxy" in body_json:
            return _err(400, "proxy_override_not_allowed")
        url = body_json.get("url", "")
        # Hermes manda listItemId, il camofox "classico" sessionKey
        lk = body_json.get("sessionKey") or body_json.get("listItemId")
        uid = body_json.get("userId")
        wanted, clean = _wanted(url)
        if wanted and not clean:
            return _err(400, "url_rejected",
                        detail=f"prefisso {wanted}+ senza URL: usa {wanted}+https://...")
        backend = wanted or (SESSIONS.get(lk) if lk else None) or DEFAULT_BACKEND
        msg = _check_url(clean, backend)
        if msg:
            return _err(400, "url_rejected", detail=msg)
        if url:
            body_json["url"] = clean
        if lk and SESSIONS.get(lk) is None:
            SESSIONS.set(lk, backend)
        log.info("create uid=%s lk=%s backend=%s explicit=%s", uid, lk, backend, bool(wanted))
        targets = [backend]

    elif tab_m:
        tab_id, action = tab_m.group(1), tab_m.group(2) or ""
        if action == "/upload" and not ALLOW_UPLOAD:
            return _err(403, "upload_disabled", hint="set ROUTER_ALLOW_UPLOAD=1")
        pub = REAL_INDEX.peek(tab_id) or tab_id
        ts = TABSETS.get(pub)
        if ts is None:
            return _err(409, "tab_backend_unknown",
                        hint="expired or router restarted: create a new tab")
        uid = ts.get("uid")
        backend = ts["active"]

        if method == "DELETE" and not action:      # chiude TUTTI i tab del tabset
            try:
                async with httpx.AsyncClient(timeout=120) as c:
                    res = {}
                    for b, real in list(ts["tabs"].items()):
                        try:
                            r = await _send(c, b, "DELETE", f"tabs/{real}", query, headers, None, raw)
                            res[b] = r.status_code
                        except httpx.HTTPError as e:
                            res[b] = f"error: {e}"
            except httpx.HTTPError as e:
                return _err(502, "backend_unreachable", detail=str(e))
            if all(_okstatus(v) for v in res.values()):
                _unregister(pub)
                return _jresp(res)
            for b, v in res.items():
                if _okstatus(v):
                    real = ts["tabs"].pop(b, None)
                    if real:
                        REAL_INDEX.delete(real)
            return _jresp(res, status=207)

        if body_json and "url" in body_json:
            wanted, clean = _wanted(body_json["url"])
            if wanted and wanted != backend:
                if not (AUTO_SWITCH and action == "/navigate" and method == "POST"):
                    return _err(409, "backend_mismatch",
                                tab_backend=backend, requested=wanted)
                try:
                    async with httpx.AsyncClient(timeout=120) as c:
                        return await _switch(c, pub, ts, wanted, clean, body_json, headers)
                except httpx.HTTPError as e:
                    return _err(502, "backend_unreachable", backend=wanted, detail=str(e))
            msg = _check_url(clean, backend)
            if msg:
                return _err(400, "url_rejected", detail=msg)
            body_json["url"] = clean
        fwd_path = f"tabs/{ts['tabs'][backend]}{action}"
        targets = [backend]

    else:  # sessions/<uid>/...
        uid = sess_m.group(1)
        state = _user_state(uid)
        known = sorted(state)
        live = sorted(b for b, p in state.items() if p)
        forced = request.headers.get("x-camofox-backend")
        is_sess_delete = method == "DELETE" and path == f"sessions/{uid}"
        if forced:
            if forced not in known:
                return _err(409, "backend_not_known_for_user", known=known)
            targets = [forced]
        elif not known:
            return _err(409, "session_backend_unknown")
        elif is_sess_delete:
            targets = known
        elif len(live) == 1:
            targets = live
        elif len(known) == 1:
            targets = known
        else:
            return _err(409, "ambiguous_backend", known=known,
                        hint="use a tab-scoped endpoint or send X-Camofox-Backend")

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            if len(targets) > 1 or (sess_m and method == "DELETE" and path == f"sessions/{uid}"):
                out = {}
                for b in targets:
                    try:
                        r = await _send(c, b, method, fwd_path, query, headers, None, raw)
                        out[b] = r.status_code
                        if _okstatus(r.status_code):
                            _drop_backend_for_user(uid, b)
                    except httpx.HTTPError as e:
                        out[b] = f"error: {e}"
                allok = all(_okstatus(v) for v in out.values())
                return _jresp(out, status=200 if allok else 207)
            backend = targets[0]
            r = await _send(c, backend, method, fwd_path, query, headers, body_json, raw)
    except httpx.HTTPError as e:
        return _err(502, "backend_unreachable", backend=targets[0], detail=str(e))

    if tab_m and r.status_code == 410:
        dead = ts["tabs"].pop(backend, None)
        if dead:
            REAL_INDEX.delete(dead)
        if not ts["tabs"]:
            _unregister(pub)
        else:
            ts["active"] = sorted(ts["tabs"])[0]
        log.warning("tab pub=%s backend=%s: 410 dal backend, tab rimosso (404 backend_tab_gone)",
                    pub, backend)
        return _err(404, "backend_tab_gone", backend=backend,
                    hint="tab destroyed by backend: create a new tab")

    if create and 200 <= r.status_code < 300:
        try:
            tid = r.json().get("tabId")
            if tid:
                _register(uid, tid, backend, tid, lk=lk)
        except Exception:
            pass
    return _passthrough(r, backend)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9378)

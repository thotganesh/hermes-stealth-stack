import requests


# ===== URL validation (defense in depth, clearnet) =====
import ipaddress as _ipa, re as _re, socket as _sock
from urllib.parse import urlparse as _urlparse

_NUM_HOST = _re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*")
_PRIV_SUFFIX = (".local", ".internal", ".localhost", ".lan", ".home.arpa", ".docker", ".svc")


def validate_url(url):
    """None se OK, altrimenti stringa con il motivo."""
    if not isinstance(url, str) or not url:
        return "URL mancante o non valido"
    try:
        u = _urlparse(url)
        host = (u.hostname or "").lower().rstrip(".")
    except ValueError:
        return "URL non valido"
    if u.scheme not in ("http", "https"):
        return "schema non consentito"
    if not host or host == "localhost" or host.endswith(_PRIV_SUFFIX):
        return "host non consentito"
    if host.endswith(".onion") or host.endswith(".i2p"):
        return "host .onion/.i2p non gestito da browser_clear"
    try:
        ips = [_ipa.ip_address(host)]
    except ValueError:
        if _NUM_HOST.fullmatch(host):
            return "host numerico ambiguo"
        if "." not in host:
            return "host senza dominio (rete interna?)"
        try:
            infos = _sock.getaddrinfo(host, None)
        except OSError:
            return "DNS non risolvibile"
        ips = []
        for _, _, _, _, sa in infos:
            try:
                ips.append(_ipa.ip_address(sa[0].split("%")[0]))
            except ValueError:
                continue
        if not ips:
            return "DNS non risolvibile"
    for ip in ips:
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return f"IP non pubblico ({ip})"
    return None

def register(ctx):
    schema = {
        "name": "browser_clear",
        "description": "Naviga un URL tramite browser clear web",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da visitare"},
                "wait_selector": {"type": "string", "description": "Selettore CSS opzionale"}
            },
            "required": ["url"]
        }
    }

    def handler(args=None, **kwargs):
        a = {**kwargs, **(args if isinstance(args, dict) else {})}
        url = a.get("url") or (args if isinstance(args, str) else None)
        if not url:
            return "Errore: parametro url mancante"
        try:
            why = validate_url(url)
            if why:
                return f"Errore: URL rifiutato ({why})"
            payload = {"url": url, "extract_text": True, "block_media": True}
            if a.get("wait_selector"):
                payload["wait_selector"] = a["wait_selector"]
            resp = requests.post("http://browser-clear:8080/browse", json=payload, timeout=60)
            if resp.status_code == 400:
                return f"Errore: URL rifiutato ({resp.json().get('detail', '')})"
            resp.raise_for_status()
            import json as _json
            return _json.dumps(resp.json(), ensure_ascii=False)[:5000]
        except Exception as e:
            return f"Errore Clear browser: {e}"

    ctx.register_tool(name="browser_clear", toolset="browser_clear", schema=schema,
                      handler=handler, description="Naviga un URL tramite browser clear web")

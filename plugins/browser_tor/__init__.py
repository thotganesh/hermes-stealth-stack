import json, os
import requests


# ===== URL validation (defense in depth, no DNS resolution) =====
import ipaddress as _ipa
from urllib.parse import urlparse as _urlparse


def validate_url(url):
    """None se OK, altrimenti stringa con il motivo.
    Non risolve l'hostname: perderebbe DNS e anonimato su Tor."""
    if not isinstance(url, str) or not url:
        return "URL mancante o non valido"
    try:
        u = _urlparse(url)
        host = (u.hostname or "").lower().rstrip(".")
    except ValueError:
        return "URL non valido"
    if u.scheme not in ("http", "https"):
        return "schema non consentito"
    if not host:
        return "host mancante"
    try:
        ip = _ipa.ip_address(host)
    except ValueError:
        return None  # hostname: lasciato a Tor
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        return f"IP non pubblico ({ip})"
    return None

BROWSER_TOR_URL = os.environ.get("BROWSER_TOR_URL", "http://browser-tor:8081").rstrip("/")


def register(ctx):
    schema = {
        "name": "browser_tor",
        "description": "Naviga un URL tramite browser Tor isolato",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da visitare"},
                "wait_selector": {"type": "string", "description": "Selettore CSS opzionale"},
            },
            "required": ["url"],
        },
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
            payload = {"url": url, "extract_text": True, "block_media": True, "js_enabled": False}
            if a.get("wait_selector"):
                payload["wait_selector"] = a["wait_selector"]
            resp = requests.post(f"{BROWSER_TOR_URL}/browse", json=payload, timeout=130)
            if resp.status_code == 400:
                return f"Errore: URL rifiutato ({resp.json().get('detail', '')})"
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data.get("text"), str):
                data["text"] = data["text"][:4500]
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Errore Tor: {e}"

    ctx.register_tool(name="browser_tor", toolset="browser_tor", schema=schema,
                      handler=handler, description="Naviga un URL tramite browser Tor isolato")

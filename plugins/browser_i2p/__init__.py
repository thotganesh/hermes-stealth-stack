import requests


# ===== URL validation (defense in depth, .i2p only, no DNS resolution) =====
import ipaddress as _ipa
from urllib.parse import urlparse as _urlparse


def validate_url(url):
    """None se OK, altrimenti stringa con il motivo.
    browser_i2p legge solo .i2p; nessuna risoluzione DNS."""
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
    if not host.endswith(".i2p"):
        return "browser_i2p legge solo host .i2p"
    try:
        ip = _ipa.ip_address(host)
    except ValueError:
        return None  # hostname .i2p: lasciato a I2P
    if not ip.is_global:
        return f"IP non pubblico ({ip})"
    return None

def register(ctx):
    schema = {
        "name": "browser_i2p",
        "description": "Naviga un URL tramite browser I2P isolato",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da visitare"}
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
            resp = requests.post("http://browser-i2p:8083/browse",
                                 json={"url": url, "extract_text": True, "block_media": True, "js_enabled": False},
                                 timeout=160)
            resp.raise_for_status()
            import json as _json
            return _json.dumps(resp.json(), ensure_ascii=False)[:5000]
        except Exception as e:
            return f"Errore I2P: {e}"

    ctx.register_tool(name="browser_i2p", toolset="browser_i2p", schema=schema,
                      handler=handler, description="Naviga un URL tramite browser I2P isolato")

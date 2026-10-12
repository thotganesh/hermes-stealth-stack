import ipaddress, json, os, re
from urllib.parse import urlparse
import requests

SOLVERR_URL = os.environ.get("SOLVERR_URL", "http://solverr:8191").rstrip("/")
NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*")


def validate_url(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("schema non consentito")
    host = (u.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("host non consentito")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise ValueError("IP non pubblico")
    elif NUMERIC_HOST.fullmatch(host):
        raise ValueError("host numerico ambiguo")
    elif "." not in host:
        raise ValueError("host senza dominio (rete interna?)")


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def register(ctx):
    schema = {
        "name": "solverr_fetch",
        "description": "Risolve pagine protette da Cloudflare",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da risolvere"},
                "max_timeout": {"type": "integer", "default": 60000, "description": "Timeout in ms (5000-80000)"},
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
            validate_url(url)
            max_timeout = max(5000, min(int(a.get("max_timeout") or 60000), 80000))
            resp = requests.post(f"{SOLVERR_URL}/v1",
                                 json={"cmd": "request.get", "url": url, "maxTimeout": max_timeout},
                                 timeout=max_timeout / 1000 + 10)
            resp.raise_for_status()
            data = resp.json()
            sol = data.get("solution", {}) or {}
            return json.dumps({
                "status": data.get("status"),
                "url": sol.get("url"),
                "text": html_to_text(str(sol.get("response", "")))[:4000],
            }, ensure_ascii=False)
        except (ValueError, TypeError) as e:
            return f"Errore: {e}"
        except Exception as e:
            return f"Errore Solverr: {e}"

    ctx.register_tool(name="solverr_fetch", toolset="solverr_fetch", schema=schema,
                      handler=handler, description="Risolve pagine protette da Cloudflare")

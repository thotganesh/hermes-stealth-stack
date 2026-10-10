import requests

def register(ctx):
    schema = {
        "name": "browser_tor",
        "description": "Naviga un URL tramite browser Tor isolato",
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
            payload = {"url": url, "extract_text": True, "block_media": True, "js_enabled": True}
            if a.get("wait_selector"):
                payload["wait_selector"] = a["wait_selector"]
            resp = requests.post("http://browser-tor:8081/browse", json=payload, timeout=60)
            resp.raise_for_status()
            return str(resp.json())[:5000]
        except Exception as e:
            return f"Errore Tor: {e}"

    ctx.register_tool(name="browser_tor", toolset="browser_tor", schema=schema,
                      handler=handler, description="Naviga un URL tramite browser Tor isolato")

import requests

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
            payload = {"url": url, "extract_text": True, "block_media": True}
            if a.get("wait_selector"):
                payload["wait_selector"] = a["wait_selector"]
            resp = requests.post("http://browser-clear:8080/browse", json=payload, timeout=60)
            resp.raise_for_status()
            return str(resp.json())[:5000]
        except Exception as e:
            return f"Errore Clear browser: {e}"

    ctx.register_tool(name="browser_clear", toolset="browser_clear", schema=schema,
                      handler=handler, description="Naviga un URL tramite browser clear web")

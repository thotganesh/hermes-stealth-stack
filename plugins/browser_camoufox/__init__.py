import requests

def register(ctx):
    schema = {
        "name": "browser_camoufox",
        "description": "Naviga un URL tramite Camoufox (stealth anti-detection)",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da visitare"},
                "wait_ms": {"type": "integer", "default": 5000, "description": "Attesa in ms"}
            },
            "required": ["url"]
        }
    }

    def handler(args=None, **kwargs):
        a = {**kwargs, **(args if isinstance(args, dict) else {})}
        url = a.get("url") or (args if isinstance(args, str) else None)
        wait_ms = int(a.get("wait_ms") or 5000)
        if not url:
            return "Errore: parametro url mancante"
        try:
            resp = requests.post("http://browser-camoufox:8085/browse",
                                 json={"url": url, "block_media": False, "humanize": True, "os": "windows", "wait_ms": wait_ms},
                                 timeout=90)
            resp.raise_for_status()
            import json as _json
            return _json.dumps(resp.json(), ensure_ascii=False)[:5000]
        except Exception as e:
            return f"Errore Camoufox: {e}"

    ctx.register_tool(name="browser_camoufox", toolset="browser_camoufox", schema=schema,
                      handler=handler, description="Naviga un URL tramite Camoufox (stealth anti-detection)")

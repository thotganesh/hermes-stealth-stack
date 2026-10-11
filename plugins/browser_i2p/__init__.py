import requests

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

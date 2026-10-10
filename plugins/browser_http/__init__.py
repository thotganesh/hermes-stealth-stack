import requests

def register(ctx):
    schema = {
        "name": "browser_http",
        "description": "Fetch HTTP diretto (veloce, senza JS)",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da fetchare"}
            },
            "required": ["url"]
        }
    }

    def handler(args=None, **kwargs):
        try:
            if isinstance(args, dict):
                url = args.get("url")
            elif isinstance(args, str):
                url = args
            else:
                url = kwargs.get("url")
            if not url:
                return "Errore: parametro url mancante"
            resp = requests.post(
                "http://browser-http:8084/browse",
                json={"url": url},
                timeout=30,
            )
            resp.raise_for_status()
            import json as _json
            return _json.dumps(resp.json(), ensure_ascii=False)[:5000]
        except Exception as e:
            return f"Errore HTTP browser: {e}"

    ctx.register_tool(
        name="browser_http",
        toolset="browser_http",
        schema=schema,
        handler=handler,
        description="Fetch HTTP diretto (veloce, senza JS)"
    )

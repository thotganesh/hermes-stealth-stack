import requests

def register(ctx):
    schema = {
        "name": "solverr_fetch",
        "description": "Risolve pagine protette da Cloudflare",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da risolvere"},
                "max_timeout": {"type": "integer", "default": 60000, "description": "Timeout in ms"}
            },
            "required": ["url"]
        }
    }

    def handler(args=None, **kwargs):
        a = {**kwargs, **(args if isinstance(args, dict) else {})}
        url = a.get("url") or (args if isinstance(args, str) else None)
        max_timeout = int(a.get("max_timeout") or 60000)
        if not url:
            return "Errore: parametro url mancante"
        try:
            resp = requests.post("http://solverr:8191/v1",
                                 json={"cmd": "request.get", "url": url, "maxTimeout": max_timeout},
                                 timeout=90)
            resp.raise_for_status()
            data = resp.json()
            solution = data.get("solution", {})
            import json as _json
            return _json.dumps({"status": data.get("status"), "url": solution.get("url"),
                        "response": str(solution.get("response", ""))[:4000]}, ensure_ascii=False)
        except Exception as e:
            return f"Errore Solverr: {e}"

    ctx.register_tool(name="solverr_fetch", toolset="solverr_fetch", schema=schema,
                      handler=handler, description="Risolve pagine protette da Cloudflare")

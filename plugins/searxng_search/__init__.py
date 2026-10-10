import requests

def register(ctx):
    schema = {
        "name": "searxng_search",
        "description": "Cerca sul web tramite SearXNG",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "La query di ricerca"},
                "limit": {"type": "integer", "default": 5, "description": "Numero massimo di risultati"}
            },
            "required": ["query"]
        }
    }

    def handler(args=None, **kwargs):
        a = {**kwargs, **(args if isinstance(args, dict) else {})}
        query = a.get("query") or (args if isinstance(args, str) else None)
        limit = int(a.get("limit") or 5)
        if not query:
            return "Errore: parametro query mancante"
        try:
            resp = requests.get("http://searxng:8080/search", params={"q": query, "format": "json"}, timeout=30)
            resp.raise_for_status()
            results = resp.json().get("results", [])[:limit]
            if not results:
                return "Nessun risultato."
            out = []
            for r in results:
                title = r.get("title")
                url = r.get("url")
                content = (r.get("content") or "")[:200]
                out.append("- " + str(title) + "\n  " + str(url) + "\n  " + content)
            return "\n\n".join(out)
        except Exception as e:
            return f"Errore SearXNG: {e}"

    ctx.register_tool(name="searxng_search", toolset="searxng_search", schema=schema,
                      handler=handler, description="Cerca sul web tramite SearXNG")

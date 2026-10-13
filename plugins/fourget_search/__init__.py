import requests


def register(ctx):
    schema = {
        "name": "fourget_search",
        "description": "Ricerca web multi-engine (Google, Brave, DDG, Startpage) con fallback SearXNG",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query di ricerca"},
                "engine": {"type": "string", "description": "Motore: google, brave, ddg, startpage (default auto)"},
                "limit": {"type": "integer", "description": "Numero massimo di risultati (default 8)"},
            },
            "required": ["query"],
        },
    }

    def handler(args=None, **kwargs):
        try:
            if isinstance(args, dict):
                query = args.get("query")
                engine = args.get("engine", "auto")
                limit = args.get("limit", 8)
            else:
                query = args
                engine = "auto"
                limit = 8
            if not query:
                return "Errore: parametro query mancante"

            results = []
            try:
                resp = requests.get(
                    "http://fourget:80/api/v1/web",
                    params={"s": query, "scraper": engine},
                    timeout=30,
                )
                if resp.ok:
                    data = resp.json()
                    results = data.get("web", [])[:limit]
            except Exception as e:
                print(f"[fourget] errore: {e}")

            if not results:
                resp2 = requests.get(
                    "http://searxng:8080/search",
                    params={"q": query, "format": "json", "language": "it-IT"},
                    timeout=20,
                )
                if resp2.ok:
                    data2 = resp2.json()
                    results = [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "description": (r.get("content") or "")[:200],
                        }
                        for r in data2.get("results", [])[:limit]
                    ]

            if not results:
                return "Nessun risultato da 4get né SearXNG."

            out = []
            for i, r in enumerate(results, 1):
                out.append(
                    f"{i}. {r.get('title')}\n"
                    f"   {r.get('url')}\n"
                    f"   {(r.get('description') or '')[:200]}"
                )
            return "\n".join(out)
        except Exception as e:
            return f"Errore 4get: {e}"

    ctx.register_tool(
        name="fourget_search",
        toolset="web",
        schema=schema,
        handler=handler,
        description="Ricerca web multi-engine (Google, Brave, DDG, Startpage) con fallback SearXNG",
    )

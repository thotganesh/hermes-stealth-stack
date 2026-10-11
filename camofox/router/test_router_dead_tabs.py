"""Tests for dead tab handling (v1.0.12). Run inside the router container:
    docker cp test_router_dead_tabs.py camofox-router:/app/ && \
    docker exec camofox-router python /app/test_router_dead_tabs.py
"""
import asyncio
import httpx
import router

PUB = "11111111-1111-4111-8111-111111111111"
REAL_VPS = "22222222-2222-4222-8222-222222222222"
REAL_TOR = "33333333-3333-4333-8333-333333333333"
NEW = "44444444-4444-4444-8444-444444444444"


class FakeResponse:
    def __init__(self, code, data=None):
        self.status_code = code
        self.headers = {}
        self.data = data or {}
        self.content = b"{}"

    def json(self):
        return self.data


MODE = {}


async def fake_send(c, backend, method, path, query, headers, body_json, raw):
    if method == "GET" and path == "tabs":
        if MODE.get("probe") == "error":
            raise httpx.ConnectError("down")
        return FakeResponse(200, {"tabs": MODE.get("tabs", [])})
    if method == "POST" and path.endswith("/navigate"):
        return FakeResponse(MODE.get("navigate", 200), {})
    if method == "POST" and path == "tabs":
        return FakeResponse(200, {"tabId": NEW})
    return FakeResponse(MODE.get("generic", 200), {})


router._send = fake_send


def setup():
    MODE.clear()
    router._unregister(PUB)
    router._register("u1", PUB, "vps", REAL_VPS, lk="lk1")
    router._register("u1", PUB, "tor", REAL_TOR, lk="lk1", activate=False)


async def navigate(c, url):
    return await c.post(f"/tabs/{PUB}/navigate", json={"userId": "u1", "url": url})


async def main():
    transport = httpx.ASGITransport(app=router.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # 1. backend 410 on a tab route -> 404 backend_tab_gone, tab removed
        setup()
        MODE["generic"] = 410
        r = await c.get(f"/tabs/{PUB}/snapshot?userId=u1")
        assert r.status_code == 404 and r.json()["error"] == "backend_tab_gone", r.text
        ts = router.TABSETS.peek(PUB)
        assert "vps" not in ts["tabs"] and router.REAL_INDEX.peek(REAL_VPS) is None
        print("1 OK: 410 mapped to 404 backend_tab_gone, dead tab dropped")

        # 2. bare switch, tab gone on backend -> 409 no_tab_on_backend, tab dropped
        setup()
        MODE["tabs"] = []
        r = await navigate(c, "tor+")
        ts = router.TABSETS.peek(PUB)
        assert r.status_code == 409 and r.json()["error"] == "no_tab_on_backend", r.text
        assert "tor" not in ts["tabs"] and ts["active"] == "vps"
        assert router.REAL_INDEX.peek(REAL_TOR) is None
        print("2 OK: bare switch detects dead tab")

        # 3. bare switch, live tab -> 200
        setup()
        MODE["tabs"] = [{"tabId": REAL_TOR}]
        r = await navigate(c, "tor+")
        assert r.status_code == 200 and router.TABSETS.peek(PUB)["active"] == "tor"
        print("3 OK: live tab reactivated")

        # 4. probe unreachable -> tab kept
        setup()
        MODE["probe"] = "error"
        r = await navigate(c, "tor+")
        assert r.status_code == 200 and "tor" in router.TABSETS.peek(PUB)["tabs"]
        print("4 OK: unverifiable probe keeps the tab")

        # 5. parked tab dead on navigate (410) -> recreated
        setup()
        MODE["navigate"] = 410
        r = await navigate(c, "tor+https://check.torproject.org/api/ip")
        ts = router.TABSETS.peek(PUB)
        assert r.status_code == 200 and r.json().get("recreated") is True, r.text
        assert ts["tabs"]["tor"] == NEW and ts["active"] == "tor"
        print("5 OK: dead parked tab recreated")

    print("ALL TESTS PASSED")


asyncio.run(main())

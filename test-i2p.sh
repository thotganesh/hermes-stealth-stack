#!/usr/bin/env bash
set -u
C="${CURL_CONTAINER:-open-webui}"
R="${ROUTER_URL:-http://camofox-router:9378}"
J='Content-Type: application/json'
body() { docker exec "$C" curl -s "$@"; }
code() { docker exec "$C" curl -s -o /dev/null -w '%{http_code}' "$@"; }
[ -n "$(docker ps -q --filter 'name=^/i2p-proxy$')" ] || { echo "i2p-proxy non in esecuzione: salto"; exit 0; }
trap 'docker start i2p-proxy >/dev/null 2>&1' EXIT

echo "== Fallback: i2p-proxy fermo, tab i2p+ verso un sito clearnet"
docker stop i2p-proxy >/dev/null
RESP=$(body -X POST $R/tabs -H "$J" -d '{"userId":"i2t","sessionKey":"i2t-1","url":"i2p+https://check.torproject.org/api/ip"}')
TAB=$(echo "$RESP" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("tabId",""))
except Exception: print("")')
sleep 6
SNAP=""
[ -n "$TAB" ] && SNAP=$(body "$R/tabs/$TAB/snapshot?userId=i2t")
if echo "$RESP$SNAP" | grep -qiE 'IsTor|"IP"'; then
  echo "  FAIL  il tab i2p+ ha raggiunto internet con proxy fermo (leak)"; RC=1
else
  echo "  OK    nessun accesso diretto con i2p-proxy fermo"; RC=0
fi
[ -n "$TAB" ] && code -X DELETE "$R/tabs/$TAB?userId=i2t" >/dev/null
code -X DELETE "$R/sessions/i2t" >/dev/null
docker start i2p-proxy >/dev/null
echo "== i2p-proxy riavviato"
exit $RC

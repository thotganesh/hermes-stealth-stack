#!/usr/bin/env bash
set -u
C="${CURL_CONTAINER:-open-webui}"
R="${ROUTER_URL:-http://camofox-router:9378}"
OK=0; KO=0
code() { docker exec "$C" curl -s -o /dev/null -w '%{http_code}' "$@"; }
body() { docker exec "$C" curl -s "$@"; }
J='Content-Type: application/json'
check() { # nome atteso ottenuto
  if [ "$2" = "$3" ]; then echo "  OK    $1"; OK=$((OK+1)); else echo "  FAIL  $1 (atteso $2, ottenuto $3)"; KO=$((KO+1)); fi; }

echo "== 1. Rotte legacy/globali bloccate"
check "POST /tabs/open" 404 "$(code -X POST $R/tabs/open -H "$J" -d '{"url":"tor+https://x.com"}')"
check "POST /navigate"  404 "$(code -X POST $R/navigate  -H "$J" -d '{"url":"tor+https://x.com"}')"
check "POST /start"     404 "$(code -X POST $R/start)"
check "POST /act"       404 "$(code -X POST $R/act -H "$J" -d '{}')"

echo "== 2. Tab vps: nessun downgrade/leak su navigate"
VPS=$(body -X POST $R/tabs -H "$J" -d '{"userId":"rt","sessionKey":"rt-vps","url":"https://example.com"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tabId",""))')
[ -n "$VPS" ] || { echo "  FAIL  creazione tab vps"; KO=$((KO+1)); }
check "navigate tor+ su tab vps"  409 "$(code -X POST $R/tabs/$VPS/navigate -H "$J" -d '{"url":"tor+https://check.torproject.org"}')"
check "navigate .onion su tab vps" 409 "$(code -X POST $R/tabs/$VPS/navigate -H "$J" -d '{"url":"http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"}')"
check "navigate file://"          400 "$(code -X POST $R/tabs/$VPS/navigate -H "$J" -d '{"url":"file:///etc/passwd"}')"
check "navigate IP privato"       400 "$(code -X POST $R/tabs/$VPS/navigate -H "$J" -d '{"url":"http://169.254.169.254/"}')"
check "navigate host interno"     400 "$(code -X POST $R/tabs/$VPS/navigate -H "$J" -d '{"url":"http://searxng:8080/"}')"

echo "== 3. Fail-closed"
check "tabId sconosciuto" 409 "$(code $R/tabs/00000000-0000-0000-0000-000000000000/snapshot)"
check "campo proxy"       400 "$(code -X POST $R/tabs -H "$J" -d '{"userId":"rt","url":"https://example.com","proxy":"http://x:1"}')"
check "sessione ignota"   409 "$(code -X DELETE $R/sessions/utente-mai-visto)"

echo "== 4. Tab Tor esce da Tor"
TOR=$(body -X POST $R/tabs -H "$J" -d '{"userId":"rt2","sessionKey":"rt-tor","url":"tor+https://check.torproject.org/api/ip"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tabId",""))')
sleep 6
SNAP=$(body "$R/tabs/$TOR/snapshot?userId=rt2")
if echo "$SNAP" | grep -qi 'istor[^a-z]\{1,6\}true'; then echo "  OK    IsTor true"; OK=$((OK+1)); else echo "  FAIL  IsTor non confermato"; KO=$((KO+1)); fi

echo "== Pulizia"
for t in "$VPS:rt" "$TOR:rt2"; do code -X DELETE "$R/tabs/${t%%:*}?userId=${t##*:}" >/dev/null; done
code -X DELETE $R/sessions/rt >/dev/null; code -X DELETE $R/sessions/rt2 >/dev/null

echo; echo "RISULTATO: $OK ok, $KO falliti"; [ "$KO" -eq 0 ]

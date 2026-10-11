#!/usr/bin/env bash
# Multi-tab / multi-engine: tab vps e tor in parallelo, switch, merge, cleanup.
set -u
C="${CURL_CONTAINER:-open-webui}"
R="${ROUTER_URL:-http://camofox-router:9378}"
J='Content-Type: application/json'
body() { docker exec "$C" curl -s -m 120 "$@"; }
code() { docker exec "$C" curl -s -m 120 -o /dev/null -w '%{http_code}' "$@"; }
tid()  { python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("tabId",""))
except Exception: print("")'; }
fail=0
ok()  { echo "  OK    $*"; }
bad() { echo "  FAIL  $*"; fail=1; }
U="mt$$"

echo "== 1. tab vps + tab tor, stesso utente e stessa listItemId (nessun 409)"
A=$(body -X POST $R/tabs -H "$J" -d "{\"userId\":\"$U\",\"listItemId\":\"mt\",\"url\":\"vps+https://example.com\"}" | tid)
B=$(body -X POST $R/tabs -H "$J" -d "{\"userId\":\"$U\",\"listItemId\":\"mt\",\"url\":\"tor+https://check.torproject.org/api/ip\"}" | tid)
[ -n "$A" ] && [ -n "$B" ] && ok "A(vps)=$A B(tor)=$B" || bad "creazione tab fallita (A='$A' B='$B')"
sleep 10

echo "== 2. GET /tabs fa il merge dei due backend"
L=$(body "$R/tabs?userId=$U")
echo "$L" | grep -q "$A" && echo "$L" | grep -q "$B" && ok "entrambi i tab elencati" || bad "merge incompleto: $L"

echo "== 3. il tab tor esce da Tor"
body "$R/tabs/$B/snapshot?userId=$U" | grep -qE 'IsTor[^a-zA-Z]{0,6}true' && ok "IsTor: true" || bad "tab tor non esce da Tor"

echo "== 4. switch: il tab A (vps) naviga con tor+ -> deve passare da Tor, senza leak"
body -X POST "$R/tabs/$A/navigate" -H "$J" -d "{\"userId\":\"$U\",\"url\":\"tor+https://check.torproject.org/api/ip\"}" | grep -q '"switched"' && ok "switch eseguito" || bad "switch non eseguito"
sleep 10
body "$R/tabs/$A/snapshot?userId=$U" | grep -qE 'IsTor[^a-zA-Z]{0,6}true' && ok "dopo lo switch il tab A esce da Tor" || bad "LEAK? il tab A dopo tor+ non risulta Tor"

echo "== 5. vps+ riattiva il tab vps parcheggiato senza ricaricare"
body -X POST "$R/tabs/$A/navigate" -H "$J" -d "{\"userId\":\"$U\",\"url\":\"vps+\"}" | grep -q '"switched"' && ok "riattivato" || bad "riattivazione fallita"
body "$R/tabs/$A/snapshot?userId=$U" | grep -qi 'documentation examples' && ok "stato del tab vps conservato" || bad "tab vps non conservato"

echo "== 6. URL privato su vps rifiutato anche via switch"
[ "$(code -X POST "$R/tabs/$A/navigate" -H "$J" -d "{\"userId\":\"$U\",\"url\":\"vps+http://127.0.0.1:8080\"}")" = "400" ] && ok "400 url_rejected" || bad "URL privato non rifiutato"

echo "== 7. cleanup: DELETE sessione (fan-out) e lista vuota"
[ "$(code -X DELETE "$R/sessions/$U")" = "200" ] && ok "DELETE sessione 200" || bad "DELETE sessione non pulito"
body "$R/tabs?userId=$U" | grep -qE '"tabs": ?\[\]' && ok "nessun tab residuo" || bad "tab residui"

echo; [ "$fail" = 0 ] && echo "RESULT: tutti i controlli superati." || echo "RESULT: ci sono controlli falliti."
exit "$fail"

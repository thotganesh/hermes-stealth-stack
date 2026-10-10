#!/usr/bin/env bash
# Privacy checks funzionali per Hermes Stealth Stack (v1.0.3).
# Verifica: WebRTC disattivato, uscita da Tor, nessun UDP/DNS fuori dal proxy.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  . ./.env
  set +a
fi
NET="${DOCKER_NETWORK:-ai-net}"
CURLI="${CURL_IMAGE:-curlimages/curl:latest}"
fail=0

api() { docker run --rm --network "$NET" "$CURLI" -s -m 90 "$@"; }
open_tab() { # host url user
  api -X POST "http://$1:9377/tabs" -H 'Content-Type: application/json' \
    -d "{\"userId\":\"$3\",\"sessionKey\":\"s1\",\"url\":\"$2\"}" \
    | sed -n -E 's/.*"tabId":"([^"]+)".*/\1/p'
}
evaluate() { # host tab user expression
  api -X POST "http://$1:9377/tabs/$2/evaluate" -H 'Content-Type: application/json' \
    -d "{\"userId\":\"$3\",\"expression\":\"$4\"}"
}
ok()  { echo "  OK    $*"; }
bad() { echo "  FAIL  $*"; fail=1; }

echo "== 1. WebRTC disattivato (RTCPeerConnection deve essere 'undefined')"
for t in "camofox|https://example.com" "camofox-tor|https://check.torproject.org" "camofox-i2p|http://stats.i2p"; do
  h="${t%%|*}"; u="${t##*|}"
  tab="$(open_tab "$h" "$u" ptest)"
  if [ -z "$tab" ]; then bad "$h: tab non aperta (I2P: riprova tra qualche minuto)"; continue; fi
  if evaluate "$h" "$tab" ptest "typeof RTCPeerConnection" | grep -q '"result":"undefined"'; then
    ok "$h"
  else
    bad "$h: WebRTC ancora attivo"
  fi
done

echo "== 2. camofox-tor esce da Tor"
tab="$(open_tab camofox-tor https://check.torproject.org/api/ip ptest2)"
if [ -n "$tab" ] && evaluate camofox-tor "$tab" ptest2 "document.body.innerText" | grep -q 'IsTor\\":true'; then
  ok "IsTor: true"
else
  bad "camofox-tor non risulta uscire da Tor"
fi

echo "== 3. Nessun UDP/DNS fuori dal proxy (cattura 35s su camofox-tor)"
docker pull -q nicolaka/netshoot >/dev/null
TORIP="$(docker inspect "${TOR_SOCKS_HOST:-tor-proxy}" --format "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}")"
cap="$(mktemp)"
docker run --rm --net container:camofox-tor nicolaka/netshoot \
  timeout 35 tcpdump -ni any -l \
  "(not host $TORIP and not net 127.0.0.0/8 and not arp and not port 9377) or port 53" \
  > "$cap" 2>/dev/null &
sleep 8
tab="$(open_tab camofox-tor https://example.org ptest3)"
[ -n "$tab" ] || bad "tab di test non aperta"
wait || true
leaks="$(grep -vE '127\.0\.0\.11' "$cap" || true)"
dnsq="$(grep -E ' (A|AAAA)\? ' "$cap" | grep -v "${TOR_SOCKS_HOST:-tor-proxy}" || true)"
if [ -z "$leaks" ] && [ -z "$dnsq" ]; then
  ok "nessun traffico fuori dal proxy, nessuna query DNS oltre al nome del proxy"
else
  bad "traffico sospetto:"; echo "$leaks" | head -10; echo "$dnsq" | head -10
fi
rm -f "$cap"

echo
if [ "$fail" = "0" ]; then echo "RESULT: tutti i controlli superati."; else echo "RESULT: ci sono controlli falliti."; fi
exit "$fail"

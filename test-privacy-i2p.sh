#!/usr/bin/env bash
# DNS/UDP leak check for camofox-i2p (HTTP proxy). Exit: 0 ok, 1 leak, 2 inconclusive.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
NET="${DOCKER_NETWORK:-ai-net}"
CURLI="${CURL_IMAGE:-curlimages/curl:latest}"
PHOST="${I2P_HTTP_HOST:-i2p-proxy}"
URL="${I2P_TEST_URL:-http://stats.i2p}"

api() { docker run --rm --network "$NET" "$CURLI" -s -m 120 "$@"; }

echo "== DNS/UDP fuori dal proxy su camofox-i2p (cattura 60s)"
PIP="$(docker inspect "$PHOST" --format "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" 2>/dev/null)"
[ -n "$PIP" ] || { echo "  SKIP  $PHOST non trovato sulla rete $NET"; exit 2; }
docker pull -q nicolaka/netshoot >/dev/null
CIP="$(docker inspect camofox-i2p --format "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}")"
cap="$(mktemp)"
docker run --rm --net container:camofox-i2p nicolaka/netshoot \
  timeout 60 tcpdump -ni any -l \
  "(src host $CIP and not dst host $PIP and not net 127.0.0.0/8 and not arp and not port 9377 and (udp or (tcp[tcpflags] & (tcp-syn|tcp-ack) = tcp-syn))) or port 53" \
  > "$cap" 2>/dev/null &
sleep 8
tab="$(api -X POST "http://camofox-i2p:9377/tabs" -H 'Content-Type: application/json' \
  -d "{\"userId\":\"ptest4\",\"sessionKey\":\"s1\",\"url\":\"$URL\"}" \
  | sed -n -E 's/.*"tabId":"([^"]+)".*/\1/p')"
wait || true
[ -n "$tab" ] && api -X DELETE "http://camofox-i2p:9377/tabs/$tab?userId=ptest4" >/dev/null
api -X DELETE "http://camofox-i2p:9377/sessions/ptest4" >/dev/null
if [ -z "$tab" ]; then
  echo "  INCONCLUSIVO  tab I2P non aperto (tunnel non pronto?). Riprova tra qualche minuto."
  rm -f "$cap"; exit 2
fi
leaks="$(grep -vE '127\.0\.0\.11' "$cap" || true)"
dnsq="$(grep -E ' (A|AAAA)\? ' "$cap" | grep -v "$PHOST" || true)"
rm -f "$cap"
if [ -z "$leaks" ] && [ -z "$dnsq" ]; then
  echo "  OK    nessun traffico fuori dal proxy, nessuna query DNS oltre al nome del proxy"; exit 0
fi
echo "  FAIL  traffico sospetto:"; echo "$leaks" | head -10; echo "$dnsq" | head -10; exit 1

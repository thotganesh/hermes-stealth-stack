#!/usr/bin/env bash
# Smoke test end-to-end del router camofox-router.
set -u

R="http://camofox-router:9378"
SUFFIX="$(date +%s)"

post_tabs() {
  local user="$1" url="$2"
  docker run --rm --network ai-net curlimages/curl:latest -s -m 120 \
    -X POST "$R/tabs" \
    -H 'Content-Type: application/json' \
    -d "{\"userId\":\"$user\",\"sessionKey\":\"$user-1\",\"url\":\"$url\"}"
}

test_url() {
  local label="$1" user="$2" url="$3" retries="${4:-1}"
  echo "============================================================"
  echo "TEST: $label"
  echo "USER: $user"
  echo "URL:  $url"
  echo "============================================================"

  local attempt resp tabid
  for ((attempt = 1; attempt <= retries; attempt++)); do
    echo "  tentativo $attempt/$retries"
    resp="$(post_tabs "$user-$attempt" "$url")"
    tabid="$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tabId',''))" 2>/dev/null || echo "")"
    if [ -n "$tabid" ]; then
      echo "  OK: $resp"
      echo
      return 0
    fi
    echo "  FALLITO: $resp"
    if [ "$attempt" -lt "$retries" ]; then
      echo "  attesa 20s prima del retry..."
      sleep 20
    fi
  done
  echo "  ESITO: FALLITO dopo $retries tentativi"
  echo
  return 1
}

test_url "Clearnet su vps"   "smoke-vps-$SUFFIX"   "vps+https://example.com"                                   1
test_url "Tor"               "smoke-tor-$SUFFIX"   "tor+https://check.torproject.org/api/ip"                   1
test_url "Onion automatico"  "smoke-onion-$SUFFIX" "http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/" 1
test_url "I2P automatico"    "smoke-i2p-$SUFFIX"   "http://stats.i2p/"                                         3

echo "============================================================"
echo "SMOKE TEST COMPLETATO"
echo "============================================================"

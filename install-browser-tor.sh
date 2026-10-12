#!/usr/bin/env bash
# Installs the browser-tor container used by the browser_tor plugin.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[ -f .env ] || cp .env.example .env
set -a; . ./.env; set +a
# --- Guard: check if ai-stack already provides a browser-tor ---
if [ -f "$HOME/ai-stack/docker-compose.yml" ] && \
   grep -qE '^[[:space:]]+browser-tor:' "$HOME/ai-stack/docker-compose.yml"; then
  echo "[i] ai-stack fornisce un browser-tor (vedi ~/ai-stack/docker-compose.yml)."
  echo "    Hermes lo userà via rete ai-net. Per avviarlo:"
  echo "      cd ~/ai-stack && docker compose up -d browser-tor"
  echo "    Lancia questo script solo se vuoi una variante Hermes separata."
  exit 0
fi

# --- Guard: any container named browser-tor already? ---
if [ -n "$(docker ps -aq --filter 'name=^/browser-tor$')" ]; then
  OWNER=$(docker inspect browser-tor --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || echo "unknown")
  echo "[+] browser-tor già presente (project: ${OWNER}) — non lo tocco."
  if [ "$OWNER" != "hermes-stealth-browser-tor" ]; then
    echo "    Se vuoi FORZARE la variante Hermes: docker rm -f browser-tor && $0"
  fi
  exit 0
fi
[ -n "${TOR_CONTROL_PASSWORD:-}" ] || { echo "[x] Set TOR_CONTROL_PASSWORD in .env (same password as tor-proxy ControlPort 9151)" >&2; exit 1; }
docker compose -p hermes-stealth-browser-tor -f docker-compose.browser-tor.yml up -d --build
echo "[+] browser-tor started. Test: docker exec open-webui curl -s http://browser-tor:8081/health"

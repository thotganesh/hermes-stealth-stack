#!/usr/bin/env bash
# Installs the browser-tor container used by the browser_tor plugin.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[ -f .env ] || cp .env.example .env
set -a; . ./.env; set +a
if [ -n "$(docker ps -aq --filter 'name=^/browser-tor$')" ]; then
  echo "[+] browser-tor already exists: not touching it"; exit 0
fi
[ -n "${TOR_CONTROL_PASSWORD:-}" ] || { echo "[x] Set TOR_CONTROL_PASSWORD in .env (same password as tor-proxy ControlPort 9151)" >&2; exit 1; }
docker compose -p hermes-stealth-browser-tor -f docker-compose.browser-tor.yml up -d --build
echo "[+] browser-tor started. Test: docker exec open-webui curl -s http://browser-tor:8081/health"

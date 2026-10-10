#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; exit 1; }

log "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || err "Docker not found"
docker compose version >/dev/null 2>&1 || err "Docker Compose v2 not found"

[ -f .env ] || { warn ".env not found, copying from .env.example"; cp .env.example .env; }
source .env

NETWORK="${DOCKER_NETWORK:-ai-net}"
if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  warn "Network $NETWORK does not exist, creating it"
  docker network create "$NETWORK"
fi
log "Network $NETWORK OK"

for c in tor-proxy i2p-proxy; do
  if docker ps --format '{{.Names}}' | grep -q "^$c$"; then
    log "Container $c detected"
  else
    warn "Container $c not found"
  fi
done

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins"
[ -d "$PLUGIN_DIR" ] || mkdir -p "$PLUGIN_DIR"

log "Installing 7 plugins into $PLUGIN_DIR..."
for p in browser_http browser_clear browser_camoufox browser_tor browser_i2p searxng_search solverr_fetch; do
  if [ -d "plugins/$p" ]; then
    rm -rf "$PLUGIN_DIR/$p"
    cp -r "plugins/$p" "$PLUGIN_DIR/$p"
    log "  + $p"
  else
    warn "  - $p not found, skipping"
  fi
done

log "Starting Camofox stack + router..."
docker compose up -d

log "Waiting for router..."
for i in {1..30}; do
  if docker exec open-webui curl -sf http://camofox-router:9378/health >/dev/null 2>&1 || \
     curl -sf http://127.0.0.1:9378/health >/dev/null 2>&1; then
    log "Router ready"
    break
  fi
  sleep 2
done

HERMES_ENV="$HERMES_HOME/.env"
if [ -f "$HERMES_ENV" ]; then
  if grep -q '^CAMOFOX_URL=' "$HERMES_ENV"; then
    sed -i.bak 's|^CAMOFOX_URL=.*|CAMOFOX_URL=http://camofox-router:9378|' "$HERMES_ENV"
  else
    echo 'CAMOFOX_URL=http://camofox-router:9378' >> "$HERMES_ENV"
  fi
  log "CAMOFOX_URL updated"
else
  warn "$HERMES_ENV not found"
fi

if docker ps --format '{{.Names}}' | grep -q '^hermes$'; then
  log "Enabling plugins in Hermes..."
  docker exec hermes hermes plugins enable \
    browser_http browser_clear browser_camoufox browser_tor browser_i2p \
    searxng_search solverr_fetch 2>/dev/null || warn "Enable manually"
fi

echo ""
log "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Check: docker compose ps"
echo "  2. Test:  docker exec open-webui curl -s http://camofox-router:9378/health"
echo "  3. Restart: docker restart hermes"
echo "  4. From Telegram: /new -> 'visit tor+https://check.torproject.org'"

#!/usr/bin/env bash
# Hermes Stealth Stack - installer
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: $0 [--dry-run]"
      echo "  --dry-run   mostra le modifiche a .env senza scrivere"
      exit 0
      ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; exit 1; }

container_running() {
  [ -n "$(docker ps -q --filter "name=^/${1}$")" ]
}

# 0 = healthy, 1 = timeout/non healthy, 2 = container senza healthcheck
wait_healthy() {
  local c="$1" tries="${2:-30}" status i
  for ((i = 0; i < tries; i++)); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c" 2>/dev/null || echo missing)"
    case "$status" in
      healthy) return 0 ;;
      none)    return 2 ;;
    esac
    sleep 2
  done
  return 1
}

# KEY=VAL in un .env senza sed -i, preservando permessi.
# Con --dry-run non scrive; al primo tocco di ogni file fa un backup.
set_env_var() {
  local file="$1" key="$2" val="$3" tmp
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "[dry-run] $file: $key=$val"
    return 0
  fi
  if [ -f "$file" ] && [ ! -f "${file}.bak.installer" ]; then
    cp -a "$file" "${file}.bak.installer" 2>/dev/null || true
  fi
  tmp="$(mktemp)"
  if grep -q "^${key}=" "$file"; then
    sed "s|^${key}=.*|${key}=${val}|" "$file" > "$tmp"
  else
    cat "$file" > "$tmp"
    if [ -s "$file" ] && [ -n "$(tail -c1 "$file")" ]; then echo >> "$tmp"; fi
    echo "${key}=${val}" >> "$tmp"
  fi
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

log "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || err "Docker not found"
docker compose version >/dev/null 2>&1 || err "Docker Compose v2 not found"

[ -f .env ] || { warn ".env not found, copying from .env.example"; cp .env.example .env; }
set -a
# shellcheck source=/dev/null
. ./.env
set +a

NETWORK="${DOCKER_NETWORK:-ai-net}"
if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  warn "Network $NETWORK does not exist, creating it"
  docker network create "$NETWORK"
fi
log "Network $NETWORK OK"

for c in tor-proxy i2p-proxy; do
  if container_running "$c"; then
    log "Container $c detected"
  else
    warn "Container $c not found (needed by camofox-tor / camofox-i2p)"
  fi
done

# proxy-net: isolated network for tor-proxy / i2p-proxy and their consumers
PROXY_NETWORK="${PROXY_NETWORK:-proxy-net}"
if ! docker network inspect "$PROXY_NETWORK" >/dev/null 2>&1; then
  log "Creating Docker network $PROXY_NETWORK"
  docker network create "$PROXY_NETWORK" >/dev/null
fi

# INSTALL_FULL controls whether Hermes creates its own searxng/solverr
# containers. Leave it false if ai-stack already provides them on the
# shared network (the common case).
INSTALL_FULL="${INSTALL_FULL:-false}"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins"
[ -d "$PLUGIN_DIR" ] || mkdir -p "$PLUGIN_DIR"

# All 7 plugins are installed regardless of INSTALL_FULL. The extra two
# (searxng_search, solverr_fetch) talk to containers that normally live in
# ai-stack; if they are missing, the plugin returns an error string.
PLUGINS=(browser_http browser_clear browser_camoufox browser_tor browser_i2p searxng_search solverr_fetch)

log "Installing ${#PLUGINS[@]} plugins into $PLUGIN_DIR..."
for p in "${PLUGINS[@]}"; do
  if [ -d "plugins/$p" ]; then
    rm -rf "${PLUGIN_DIR:?}/$p"
    cp -r "plugins/$p" "$PLUGIN_DIR/$p"
    log "  + $p"
  else
    warn "  - $p not found, skipping"
  fi
done

container_exists() {
  [ -n "$(docker ps -aq --filter "name=^/${1}$")" ]
}

SERVICES=(camofox camofox-tor camofox-i2p camofox-router)
CREATE_SEARXNG=false
if [ "$INSTALL_FULL" = "true" ]; then
  for s in searxng solverr; do
    if container_exists "$s"; then
      log "Reusing existing container '$s' (not touched)"
    else
      SERVICES+=("$s")
      if [ "$s" = "searxng" ]; then CREATE_SEARXNG=true; fi
    fi
  done
fi

if [ "$CREATE_SEARXNG" = "true" ] && [ -z "${SEARXNG_SECRET:-}" ]; then
  log "Generating SEARXNG_SECRET"
  SEARXNG_SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  set_env_var .env SEARXNG_SECRET "$SEARXNG_SECRET"
  export SEARXNG_SECRET
fi

log "Starting: ${SERVICES[*]}"
docker compose --profile full up -d --build "${SERVICES[@]}"

log "Waiting for router..."
rc=0
wait_healthy camofox-router 30 || rc=$?
case "$rc" in
  0) log "Router healthy" ;;
  2) warn "camofox-router has no healthcheck (old compose?)"
     sleep 10 ;;
  *) warn "Router not healthy after 60s. Check: docker logs camofox-router --tail 30"
     warn "Installation will continue, but Hermes may not reach the router." ;;
esac

HERMES_ENV="$HERMES_HOME/.env"
if [ -f "$HERMES_ENV" ]; then
  set_env_var "$HERMES_ENV" CAMOFOX_URL "http://camofox-router:9378"
  if [ "$INSTALL_FULL" = "true" ]; then
    set_env_var "$HERMES_ENV" SEARXNG_URL "${SEARXNG_URL:-http://searxng:8080}"
    set_env_var "$HERMES_ENV" SOLVERR_URL "${SOLVERR_URL:-http://solverr:8191}"
  fi
  log "Hermes .env updated"
else
  warn "$HERMES_ENV not found: set CAMOFOX_URL (and SEARXNG_URL / SOLVERR_URL) manually"
fi

if container_running hermes; then
  log "Enabling plugins in Hermes..."
  for p in "${PLUGINS[@]}"; do
    docker exec hermes hermes plugins enable "$p" \
      || warn "Could not enable '$p': run 'hermes plugins enable $p' manually"
  done

  log "Restarting Hermes to apply changes..."
  docker restart hermes >/dev/null
  rc=0
  wait_healthy hermes 30 || rc=$?
  if [ "$rc" = "2" ]; then
    sleep 10
  elif [ "$rc" != "0" ]; then
    warn "Hermes not healthy yet: check docker logs hermes --tail 30"
  fi
else
  warn "Container 'hermes' not running: restart it manually after installing"
fi

if [ -n "${HERMES_RESTART_UNIT:-}" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl restart "$HERMES_RESTART_UNIT" 2>/dev/null \
    || warn "Could not restart $HERMES_RESTART_UNIT"
fi

echo ""
log "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Check:    docker compose ps"
echo "  2. Privacy:  ./test-privacy.sh   (verifies user.js / WebRTC / DNS)"
echo "  3. Try:      from Telegram: /new -> 'visit tor+https://check.torproject.org'"

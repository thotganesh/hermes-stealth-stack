#!/usr/bin/env bash
# Hermes Stealth Stack - one-shot installer.
#
#   Part 1: openwebui-tor-i2p-scraper (Tor + Snowflake, I2P, reader containers)
#   Part 2: this stack (router, Camofox engines, Hermes plugins) via ./install.sh
#
# Options (environment variables):
#   SCRAPER_DIR    where the scraper project lives (default: ~/openwebui-tor-i2p-scraper).
#                  An existing directory is used as is, e.g. SCRAPER_DIR=~/ai-stack
#   SCRAPER_REPO   git URL to clone when SCRAPER_DIR does not exist
#   SCRAPER_REF    branch or tag to check out after cloning (optional)
#   BROWSER_TOR    scraper (default) | hermes : which browser-tor container to run
#   SKIP_SCRAPER=1 skip part 1
#   SKIP_HERMES=1  skip part 2
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")"
STACK_DIR="$(pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; exit 1; }

SCRAPER_REPO="${SCRAPER_REPO:-https://github.com/thotganesh/openwebui-tor-i2p-scraper.git}"
SCRAPER_DIR="${SCRAPER_DIR:-$HOME/openwebui-tor-i2p-scraper}"
SCRAPER_REF="${SCRAPER_REF:-}"
BROWSER_TOR="${BROWSER_TOR:-scraper}"
SKIP_SCRAPER="${SKIP_SCRAPER:-0}"
SKIP_HERMES="${SKIP_HERMES:-0}"

case "$BROWSER_TOR" in scraper|hermes) ;; *) err "BROWSER_TOR must be 'scraper' or 'hermes'" ;; esac

env_get() { # file key -> value (empty if missing)
  local v
  v="$(grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2-)" || true
  printf '%s' "$v"
}

set_env_var() { # file key value, backup + --dry-run
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

in_list() { local x="$1" i; shift; for i in "$@"; do if [ "$i" = "$x" ]; then return 0; fi; done; return 1; }

make_hash() { # plain password -> Tor hashed control password (16:...)
  docker run --rm debian:bookworm-slim bash -c \
    "apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq tor >/dev/null 2>&1 && tor --hash-password '$1'" 2>/dev/null \
    | grep -E '^16:' | tail -1 || true
}

log "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || err "Docker not found"
docker compose version >/dev/null 2>&1 || err "Docker Compose v2 not found"

[ -f .env ] || { warn ".env not found, copying from .env.example"; cp .env.example .env; }
NETWORK="$(env_get .env DOCKER_NETWORK)"; NETWORK="${NETWORK:-ai-net}"
if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  log "Creating Docker network $NETWORK"
  docker network create "$NETWORK" >/dev/null
fi
log "Network $NETWORK OK"

# ------------------------------------------------------------------ part 1
if [ "$SKIP_SCRAPER" != "1" ]; then
  log "Part 1/2: openwebui-tor-i2p-scraper in $SCRAPER_DIR"

  # Guard: if a tor-proxy container already exists, refuse to clone a
  # second copy of the scraper. This is the scenario that used to end in a
  # name conflict (two projects trying to create tor-proxy / browser-tor).
  if docker ps -a --filter "name=^/tor-proxy$" --format '{{.Names}}' | grep -q .; then
    EXISTING_DIR="$(docker inspect tor-proxy --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
    if [ -n "$EXISTING_DIR" ] && [ "$EXISTING_DIR" != "$SCRAPER_DIR" ]; then
      err "A tor-proxy container already exists from $EXISTING_DIR, but SCRAPER_DIR is $SCRAPER_DIR.
    To reuse the running stack: SCRAPER_DIR=$EXISTING_DIR $0
    To skip part 1 entirely: SKIP_SCRAPER=1 $0"
    fi
  fi

  if [ -d "$SCRAPER_DIR/.git" ]; then
    log "Updating existing clone (fast-forward only)"
    git -C "$SCRAPER_DIR" pull --ff-only || warn "git pull failed, using the current checkout"
  elif [ -f "$SCRAPER_DIR/docker-compose.yml" ]; then
    log "Using existing directory as is"
  else
    command -v git >/dev/null 2>&1 || err "git not found"
    git clone "$SCRAPER_REPO" "$SCRAPER_DIR"
    if [ -n "$SCRAPER_REF" ]; then git -C "$SCRAPER_DIR" checkout "$SCRAPER_REF"; fi
  fi
  [ -f "$SCRAPER_DIR/docker-compose.yml" ] || err "No docker-compose.yml in $SCRAPER_DIR"
  cd "$SCRAPER_DIR"

  [ -f .env ] || { [ -f .env.example ] || err "No .env or .env.example in $SCRAPER_DIR"; cp .env.example .env; }
  chmod 600 .env

  # Tor ControlPort credentials: generate only what is missing, never print them
  PW="$(env_get .env TOR_CONTROL_PASSWORD)"
  HASH="$(env_get .env TOR_CONTROL_HASH)"
  PW_OK=true;   if [ -z "$PW" ] || [ "$PW" = "change-me" ]; then PW_OK=false; fi
  HASH_OK=true; case "$HASH" in ""|*PASTE*) HASH_OK=false ;; esac
  if [ "$PW_OK" = "false" ]; then
    log "Generating Tor ControlPort password and hash"
    PW="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    HASH="$(make_hash "$PW")"
    [ -n "$HASH" ] || err "Could not generate the Tor control hash (is Docker able to pull debian:bookworm-slim?)"
    set_env_var .env TOR_CONTROL_PASSWORD "$PW"
    set_env_var .env TOR_CONTROL_HASH "$HASH"
  elif [ "$HASH_OK" = "false" ]; then
    log "Computing Tor control hash from the existing password"
    HASH="$(make_hash "$PW")"
    [ -n "$HASH" ] || err "Could not generate the Tor control hash"
    set_env_var .env TOR_CONTROL_HASH "$HASH"
  else
    log "Tor control credentials already set, keeping them"
  fi

  # Which services to start: only what exists in this compose file and has its files
  mapfile -t AVAILABLE < <(docker compose config --services)
  SERVICES=()
  add() { # service [required-dir]
    if ! in_list "$1" "${AVAILABLE[@]}"; then return 0; fi
    if [ -n "${2:-}" ] && [ ! -d "$2" ]; then
      warn "Skipping $1: ./$2 not found in $SCRAPER_DIR"
      return 0
    fi
    SERVICES+=("$1")
  }
  add tor-proxy tor-snowflake
  add i2p-proxy
  add browser-clear browser-clear
  add browser-i2p browser-i2p
  add browser-http browser-http
  add browser-camoufox browser-camoufox
  add solverr
  add searxng searxng-config
  if [ "$BROWSER_TOR" = "scraper" ]; then add browser-tor browser-tor; fi
  [ "${#SERVICES[@]}" -gt 0 ] || err "No services to start"

  for need in browser-http browser-camoufox; do
    if ! in_list "$need" "${SERVICES[@]}"; then
      warn "$need not started: the matching Hermes plugin will return errors until that container exists"
    fi
  done

  if in_list i2p-proxy "${SERVICES[@]}"; then
    mkdir -p i2p-data
    # i2pd runs as UID 100, GID 65533 inside the container. Give it write
    # access and keep the directory private (750, not 777).
    chown -R 100:65533 i2p-data 2>/dev/null || true
    chmod -R 750 i2p-data
  fi

  log "Starting: ${SERVICES[*]}"
  log "The first build can take several minutes (Snowflake + Playwright images)"
  docker compose up -d --build "${SERVICES[@]}"

  if in_list tor-proxy "${SERVICES[@]}"; then
    log "Waiting for Tor to bootstrap (up to 5 minutes)..."
    BOOT=false
    for ((i = 0; i < 150; i++)); do
      LOGS="$(docker logs tor-proxy 2>&1 || true)"
      case "$LOGS" in *"Bootstrapped 100%"*) BOOT=true; break ;; esac
      sleep 2
    done
    if [ "$BOOT" = "true" ]; then log "Tor is up"; else warn "Tor did not report 100% yet: check 'docker logs tor-proxy' (outgoing UDP must be open for Snowflake)"; fi
  fi
  if in_list i2p-proxy "${SERVICES[@]}"; then
    warn "i2pd needs about 3-5 minutes on its first boot before .i2p sites resolve"
  fi

  cd "$STACK_DIR"
  # Keep the Hermes stack's .env in sync (used by install-browser-tor.sh)
  set_env_var .env TOR_CONTROL_PASSWORD "$PW"
  chmod 600 .env
else
  log "Skipping part 1 (SKIP_SCRAPER=1)"
fi

# ------------------------------------------------------------------ part 2
if [ "$SKIP_HERMES" != "1" ]; then
  log "Part 2/2: Hermes Stealth Stack"

  if [ "$BROWSER_TOR" = "hermes" ]; then
    log "Installing the Hermes variant of browser-tor"
    ./install-browser-tor.sh
  fi

  if [ -n "$(docker ps -q --filter 'name=^/hermes$')" ]; then
    NETS="$(docker inspect hermes --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}')"
    case " $NETS " in
      *" $NETWORK "*) ;;
      *) log "Connecting container 'hermes' to $NETWORK"; docker network connect "$NETWORK" hermes ;;
    esac
  fi

  ./install.sh
else
  log "Skipping part 2 (SKIP_HERMES=1)"
fi

echo ""
log "All done."
echo ""
echo "Next steps:"
printf '  1. Status:   docker ps --format "table {{.Names}}\\t{{.Status}}"\n'
echo "  2. Privacy:  ./test-privacy.sh"
echo "  3. Tabs:     CURL_CONTAINER=<a container with curl on $NETWORK> ./test-multitab.sh"
echo "  4. Hermes:   /new -> 'visit tor+https://check.torproject.org/api/ip'"

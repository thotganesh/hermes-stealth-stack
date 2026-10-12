#!/usr/bin/env bash
# Update hermes-stealth-stack from origin/main.
# Requires ai-stack to be up and healthy (this stack depends on it).
set -euo pipefail

cd "$(dirname "$0")"

log()  { printf '\033[0;32m[+]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
err()  { printf '\033[0;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[ -d .git ] || err "not a git checkout: run from the hermes-stealth-stack repo"

# ---------- 1. pre-check: ai-stack must be up ----------
log "pre-check: ai-stack containers"
MISSING=()
for c in tor-proxy i2p-proxy browser-tor browser-i2p browser-clear browser-camoufox browser-http solverr searxng; do
    if ! docker ps --format '{{.Names}}' | grep -qx "$c"; then
        MISSING+=("$c")
    fi
done
if [ "${#MISSING[@]}" -gt 0 ]; then
    err "ai-stack is missing containers: ${MISSING[*]}
    Update ai-stack first:  cd ~/ai-stack && ./update.sh"
fi
log "ai-stack OK"

# ---------- 2. refuse if working tree is dirty ----------
if ! git diff --quiet || ! git diff --cached --quiet; then
    err "working tree has local changes. Commit or stash them first:
    git -C $(pwd) status"
fi

# ---------- 3. backup ----------
BK="$HOME/stack-backup-$(date +%Y%m%d-%H%M%S)-hermes"
log "backup -> $BK"
mkdir -p "$BK"
for f in .env docker-compose.yml docker-compose.override.yml; do
    [ -f "$f" ] && cp -a "$f" "$BK/$f"
done
git rev-parse HEAD > "$BK/HEAD"
log "backup done"

# ---------- 4. pull ----------
log "git fetch + pull --ff-only"
git fetch origin
BEFORE=$(git rev-parse HEAD)
git pull --ff-only origin main
AFTER=$(git rev-parse HEAD)
if [ "$BEFORE" = "$AFTER" ]; then
    log "already up to date ($AFTER)"
else
    log "updated $BEFORE -> $AFTER"
    git log --oneline "$BEFORE..$AFTER" | head -20
fi

# ---------- 5. build (only the local services) ----------
log "docker compose build (camofox-router only)"
docker compose build camofox-router

# ---------- 6. up ----------
log "docker compose up -d --remove-orphans"
docker compose up -d --remove-orphans

# ---------- 7. copy plugins into ~/.hermes/plugins/ (does not touch hermes container) ----------
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
if [ -d "$HERMES_HOME/plugins" ]; then
    log "syncing plugins to $HERMES_HOME/plugins/"
    for p in browser_http browser_clear browser_camoufox browser_tor browser_i2p searxng_search solverr_fetch; do
        if [ -d "plugins/$p" ]; then
            rm -rf "$HERMES_HOME/plugins/$p"
            cp -r "plugins/$p" "$HERMES_HOME/plugins/$p"
            log "  + $p"
        fi
    done
fi

# ---------- 8. status ----------
log "container status"
docker compose ps

log "hermes-stealth-stack update complete. Backup at $BK"
warn "if Hermes plugins changed, restart the hermes container:
    docker restart hermes"

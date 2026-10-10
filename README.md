# Hermes Stealth Stack

Stealth browser + Tor + I2P for [Hermes Agent](https://github.com/NousResearch/hermes-agent), with an automatic router for anonymity.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What it does

Gives Hermes two complementary web navigation systems.

### 1. Fast readers (7 custom plugins)

| Plugin | Purpose | Backend |
|--------|---------|---------|
| `browser_http` | Direct HTTP fetch | curl_cffi (Chrome impersonation) |
| `browser_clear` | JS-heavy pages | Patchright (stealth Chromium) |
| `browser_camoufox` | Anti-bot pages | Camoufox (C++ patched Firefox) |
| `browser_tor` | Anonymous reads | Tor (NEWNYM per request) |
| `browser_i2p` | I2P network | i2pd HTTP proxy |
| `searxng_search` | Web search | Self-hosted SearXNG |
| `solverr_fetch` | Cloudflare challenges | FlareSolverr |

### 2. Interactive browsers (Camofox + Router)

Three Camofox instances with different exits, dispatched by a small FastAPI router.

| URL prefix | Backend | Exit |
|------------|---------|------|
| (none) | `camofox` | Host IP |
| `tor+` | `camofox-tor` | Tor exit node |
| `i2p+` | `camofox-i2p` | I2P network |
| `*.onion` | `camofox-tor` (auto) | Tor |
| `*.i2p` | `camofox-i2p` (auto) | I2P |

Supports clicks, form fill, login, JavaScript execution, persistent sessions.

## When to use what

| Task | Tool |
|------|------|
| Read a simple page | `browser_http` |
| Read a JS page | `browser_clear` |
| Read a bot-protected site | `browser_camoufox` |
| Read anonymously | `browser_tor` |
| Read a `.i2p` site | `browser_i2p` |
| Fill a form / log in | `browser_navigate` + `browser_type` |
| Navigate anonymously + interact | `browser_navigate` with `tor+https://...` |
| Visit a `.onion` | `browser_navigate` with `tor+http://xxx.onion` |

## Quick install

Clone, copy env, run installer:

    git clone https://github.com/thotganesh/hermes-stealth-stack.git
    cd hermes-stealth-stack
    cp .env.example .env
    ./install.sh

The script:

1. Checks prerequisites (Docker, `ai-net` network)
2. Copies the 7 plugins into `~/.hermes/plugins/`
3. Starts the stack with `docker compose up -d`
4. Sets `CAMOFOX_URL=http://camofox-router:9378` in Hermes' `.env`
5. Enables the plugins
6. Restarts Hermes

## Requirements

- Docker + Docker Compose v2
- Hermes Agent running in Docker
- `ai-net` Docker network shared by Hermes, Camofox, router
- `tor-proxy` container (SOCKS5 on `:9150`) for `camofox-tor`
- `i2p-proxy` container (HTTP proxy on `:4444`) for `camofox-i2p`

If you need `tor-proxy` or `i2p-proxy`, see [openwebui-tor-i2p-scraper](https://github.com/thotganesh/openwebui-tor-i2p-scraper).

## Layout

    hermes-stealth-stack/
    ├── plugins/              # 7 Hermes plugins
    ├── camofox/
    │   ├── router/           # FastAPI router
    │   └── prefs/            # user.js (WebRTC off + remote DNS)
    ├── docs/                 # Architecture, install, tools
    ├── docker-compose.yml
    ├── install.sh
    └── .env.example

## Privacy hardening (v1.0.3)

camofox-browser does **not** read Firefox `user.js` files: it launches Camoufox through
`camoufox-js` with a temporary Playwright profile, so `camofox/prefs/user.js` has no effect.
Instead, `camofox/Dockerfile` builds a small derived image that patches the launch options:
`block_webrtc: true` plus `firefox_user_prefs` (`network.proxy.socks_remote_dns=true`,
`media.peerconnection.enabled=false`).

Verify it on your own host with `./test-privacy.sh` (WebRTC off, Tor exit, no UDP/DNS outside
the proxy). Limits: the un-prefixed backend (`camofox`) exits with the host IP by design; the
patch relies on a string in upstream `server.js`, so the image build fails loudly if upstream
changes it (pin `CAMOFOX_IMAGE` to a digest for reproducible builds). These checks do not
guarantee anonymity.

## Privacy & anonymity

- Separate sessions per backend (VPS / Tor / I2P)
- Persistent storage state for multi-turn logins
- Idle shutdown after 120s to save RAM

### Important disclaimer on anonymity

Camoufox with Tor is **not** equivalent to Tor Browser:

- The fingerprint is different. Tor Browser patches Firefox specifically to
  match a uniform fingerprint shared by all users. Camoufox randomizes the
  fingerprint instead. This is *usually* fine, but it is not the same threat
  model, and it will not protect you from advanced correlation attacks.
- The default backend (`camofox`) exits from your **host IP**. You must
  explicitly prefix URLs with `tor+` to route through Tor. Forgetting the
  prefix means the request goes out from your server's real address.
- Traffic analysis, timing attacks, and compromised exit nodes are outside
  the scope of this project. If you need strong anonymity guarantees, use
  the Tor Browser directly.

Use this stack as a **convenience layer for scripted browsing**, not as a
replacement for a proper anonymity setup.

## Security model

This stack assumes the Docker network (default: `ai-net`) is trusted.

- The router has no authentication. Any container on the same network can
  create tabs, read snapshots, and impersonate another userId. This is
  intentional: the router is designed for a private, single-user deployment
  where only Hermes and the Camofox backends share the network.
- Do not expose port 9378 publicly. If you need remote access, put the router
  behind a reverse proxy with authentication, or use an SSH tunnel.
- State is in-memory. Sessions, tabs and user-backend mappings live only in
  the router process. A restart clears them. Sessions expire after 1 hour of
  inactivity (configurable via ROUTER_STATE_TTL), and the maps are bounded
  to 10,000 entries (configurable via ROUTER_MAX_ENTRIES).
- Tab backend is never guessed. If a tab ID is unknown (expired or after a
  router restart), the router returns HTTP 409 instead of silently routing
  the request through the default (VPS) backend. This prevents an anonymous
  session from accidentally leaking through the host IP.

### SSRF risk from CAMOFOX_ALLOW_PRIVATE_NETWORK

The Camofox containers with proxies (camofox-tor, camofox-i2p) run with
CAMOFOX_ALLOW_PRIVATE_NETWORK=true. This is required for the browser to
reach the proxy containers (tor-proxy:9150, i2p-proxy:4444) on the Docker
network, but it also means the browser can navigate to any service on that
network, including hermes, open-webui, or any other container you have there.

If an attacker (or a malicious page through an agent-driven navigation)
convinces the browser to open internal URLs like http://hermes:5225/...,
those services become reachable from the browser context.

Mitigations:

- Keep the Camofox stack on a dedicated Docker network shared only with the
  proxies, not with your other services.
- Do not let untrusted input drive the browser_navigate tool without review.
- If your setup allows, use firewall rules to block the Camofox containers
  from reaching anything except the proxy ports.


### Note on the Solverr image

The compose file uses `ghcr.io/unseensnick/solverr`, a community fork of
FlareSolverr that is more actively maintained than the upstream image and
works with the current Cloudflare challenges. If you prefer the official
image, override `SOLVERR_IMAGE` in your `.env`.

## License

MIT - see LICENSE.

## Credits

- Camoufox (https://camoufox.com/) by daijiro
- camofox-browser (https://github.com/jo-inc/camofox-browser) by jo-inc
- Hermes Agent (https://github.com/NousResearch/hermes-agent) by Nous Research

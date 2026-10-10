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

If you need `tor-proxy` or `i2p-proxy`, see openwebui-tor-i2p-scraper.

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

## Privacy & anonymity

- WebRTC disabled in every Camofox instance
- Remote DNS forced via SOCKS5
- Separate sessions per backend (VPS / Tor / I2P)
- Persistent storage state for multi-turn logins
- Idle shutdown after 120s to save RAM

## License

MIT - see LICENSE.

## Credits

- Camoufox (https://camoufox.com/) by daijiro
- camofox-browser (https://github.com/jo-inc/camofox-browser) by jo-inc
- Hermes Agent (https://github.com/NousResearch/hermes-agent) by Nous Research

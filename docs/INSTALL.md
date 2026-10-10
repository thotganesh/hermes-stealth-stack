# Installation

## Prerequisites

- Docker + Docker Compose v2
- Hermes Agent running in Docker
- A Docker network (default `ai-net`) shared by Hermes, Camofox and the router
- Optional: `tor-proxy` (SOCKS5 on `:9150`) and `i2p-proxy` (HTTP on `:4444`)

## Steps

1. Clone the repo

    git clone https://github.com/thotganesh/hermes-stealth-stack.git
    cd hermes-stealth-stack

2. Configure environment

    cp .env.example .env

3. Run the installer

    ./install.sh

4. Verify

    docker compose ps
    docker exec open-webui curl -s http://camofox-router:9378/health

5. Restart Hermes

    docker restart hermes

6. Test from Telegram

    /new
    Use browser_navigate to visit tor+https://check.torproject.org

## Troubleshooting

### browser_exec cannot connect to Docker daemon

Hermes is using Browser Use mode. The stack bypasses it via CAMOFOX_URL.
Verify CAMOFOX_URL points to the router and the Camofox container is healthy.

### proxy pool created but browser pre-warm failed

Tor/I2P proxies may be slow to start. Wait 30-60 seconds and retry.
Check logs:

    docker logs camofox-tor --tail 20
    docker logs camofox-i2p --tail 20

### Router not reachable from Hermes

All containers must be on the same Docker network:

    docker network inspect ai-net

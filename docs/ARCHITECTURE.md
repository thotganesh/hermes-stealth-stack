# Architecture

## Overview

The router sits between Hermes and the three Camofox backends:

- Hermes calls CAMOFOX_URL (http://camofox-router:9378)
- The router inspects the URL and picks a backend
- Backend returns a tab; router remembers tab -> backend mapping
- Subsequent snapshot/click calls are routed correctly

## Routing logic

- URL starts with `tor+` -> strip prefix, send to camofox-tor
- URL starts with `i2p+` -> strip prefix, send to camofox-i2p
- URL contains `.onion` -> send to camofox-tor
- URL contains `.i2p` -> send to camofox-i2p
- Otherwise -> send to camofox (host IP)

The router stores two maps:

- sessionKey -> backend
- tabId -> backend

The second map is what makes GET /snapshot work after POST /tabs.

## Session isolation

Each backend keeps its own Camoufox profile. Cookies and localStorage
are not shared between VPS, Tor and I2P. This prevents cross-contamination
of identities.

## Privacy

- `user.js` disables WebRTC (media.peerconnection.enabled = false)
- Remote DNS (network.proxy.socks_remote_dns = true) forces DNS through the proxy
- Camoufox patches Canvas, WebGL, Audio, fonts, timezone
- Idle shutdown after 120s to keep RAM usage low

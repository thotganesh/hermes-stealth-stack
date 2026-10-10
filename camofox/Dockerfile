ARG BASE_IMAGE=ghcr.io/jo-inc/camofox-browser:latest
FROM ${BASE_IMAGE}
# camofox-browser non legge user.js: passa le preferenze a camoufox-js (launchOptions)
RUN sed -i 's|humanize: true,|humanize: true, block_webrtc: true, firefox_user_prefs: {"network.proxy.socks_remote_dns": true, "media.peerconnection.enabled": false},|' /app/server.js \
 && grep -q 'block_webrtc: true' /app/server.js

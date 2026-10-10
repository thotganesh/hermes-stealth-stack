// NOTE (v1.0.3): this file is NOT read by camofox-browser. Prefs are applied by camofox/Dockerfile.
// Forza il DNS remoto via proxy SOCKS5 (necessario per I2P)
user_pref("network.proxy.socks_remote_dns", true);
// Disabilita WebRTC (evita leak IP)
user_pref("media.peerconnection.enabled", false);

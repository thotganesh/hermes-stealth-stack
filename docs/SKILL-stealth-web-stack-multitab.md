## Multi-engine nel browser (router v3)

Un solo tab per task, ma puoi cambiare engine con un prefisso nell'URL di
browser_navigate:

- tor+https://sito -> Tor | i2p+http://sito -> I2P | vps+https://sito -> IP host
- .onion e .i2p scelgono da soli Tor / I2P
- tor+ / vps+ / i2p+ SENZA URL = torna al tab gia' aperto su quell'engine,
  senza ricaricare (ping-pong: signup su Tor <-> email su VPS)
- URL senza prefisso = resta sull'engine corrente
- Dopo uno switch snapshot/click/type agiscono sul tab ora attivo
- 409 no_tab_on_backend: non esiste ancora un tab su quell'engine,
  naviga con engine+https://... per aprirne uno
- 409 tab_backend_unknown: router riavviato o tab scaduto, riapri
- Idle timeout Camofox: 120s (alzare browser.inactivity_timeout a 600)

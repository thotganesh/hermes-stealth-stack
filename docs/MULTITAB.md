# Multi-engine tabs (router v3, v1.0.11)

Hermes ha un solo tab per task. Il router associa a quel tab un tabset
(un tab reale per backend: vps / tor / i2p). Snapshot, click e type vanno
sempre al tab attivo.

## Scegliere l'engine (URL di browser_navigate)

- `tor+https://...`  passa a Tor (crea il tab o riusa quello parcheggiato)
- `i2p+http://...`   passa a I2P
- `vps+https://...`  passa al VPS (IP dell'host)
- `*.onion` / `*.i2p` forzano Tor / I2P
- `tor+` da solo     riattiva il tab Tor parcheggiato senza ricaricare
- URL senza prefisso resta sull'engine attivo (mai un cambio silenzioso)

## Garanzie

- Nessuna richiesta va al backend sbagliato: un cambio engine crea o
  riattiva un tab sul backend richiesto, non naviga quello corrente.
- Il tab in background conserva pagina e cookie finche' non scade l'idle
  timeout di Camofox; se scade, Hermes ne ricrea uno nuovo.
- Contesti isolati: lo stesso sito su vps e su tor sono due browser distinti.
- URL privati/interni restano bloccati su vps anche via switch.
- upload disabilitato di default; scritture di sessione ambigue danno 409.
- ROUTER_AUTO_SWITCH=0 ripristina il vecchio 409 backend_mismatch.

## Parallelismo reale

Piu' task Hermes (subagent) hanno userId diversi: contesti separati, ognuno
sul proprio engine, senza passare dallo switch.

## Test

./test-multitab.sh (usa il container open-webui come client curl).

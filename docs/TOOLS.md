# Tools reference

## Fast readers (Hermes plugins)

### browser_http

Direct HTTP fetch via curl_cffi with Chrome impersonation.

- Speed: ~200 ms
- JavaScript: no
- Use case: simple pages, API endpoints, plain HTML

### browser_clear

Stealth Chromium (Patchright) for JS-heavy pages.

- Speed: 1-3 s
- JavaScript: yes
- Use case: modern SPAs, pages with anti-bot protection

### browser_camoufox

Firefox stealth with humanize enabled.

- Speed: 2-5 s
- JavaScript: yes
- Use case: sites that block Chromium (403, Cloudflare)

### browser_tor

Anonymous reads via Tor. Default engine (`browser-tor`): NEWNYM before every request. With `BROWSER_TOR_URL` pointing to `browser-tor-real` (`ai-stack` v3.7): official Tor Browser, no NEWNYM.

- Speed: 3-10 s (default engine)
- JavaScript: yes (default engine), no with `browser-tor-real`
- Use case: anonymous reading, .onion fallback

### browser_i2p

Reads via the I2P network (HTTP proxy on i2p-proxy:4444).

- Speed: 10-60 s
- JavaScript: yes
- Use case: .i2p sites

### searxng_search

Self-hosted metasearch. JSON API.

- Speed: <1 s
- Use case: general web search

### solverr_fetch

Solves Cloudflare / Turnstile challenges via FlareSolverr.

- Speed: 10-30 s
- Use case: Cloudflare-protected pages

## Interactive browsers (Camofox + Router)

### browser_navigate

Opens a URL in the selected backend.

- Input: url (string). Prefix with tor+ or i2p+ to choose the exit.
- Output: {tabId, url, httpStatus, navigationOk}

### browser_snapshot

Returns a structured DOM snapshot of the current tab.

- Input: userId, tabId

### browser_click

Clicks an element identified by ref.

### browser_type

Types text into a form field.

### browser_scroll, browser_back, browser_press

Navigation helpers.

### browser_console

Executes JavaScript in the page context.

## Decision tree

Is it a simple read?
- Yes: use a plugin (browser_http / browser_clear / browser_camoufox)
- No (need interaction: click, form, login):
  - Default exit (host IP): browser_navigate with plain URL
  - Anonymous exit: browser_navigate with tor+ URL
  - I2P exit: browser_navigate with i2p+ URL

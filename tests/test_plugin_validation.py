"""Tests for the URL validation in Hermes reader plugins.

These run in CI with no container running: each plugin exposes a
top-level ``validate_url(url) -> str | None`` that is pure Python
(plus ``requests`` at module level, which CI installs).

Each case is (url, expected_substring_or_None):
- expected None  -> URL must be accepted (validate_url returns None)
- expected str   -> URL must be rejected, and the returned message
                    must contain the substring.
"""

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGINS_DIR = REPO_ROOT / "plugins"


def _load(plugin_name):
    path = PLUGINS_DIR / plugin_name / "__init__.py"
    spec = importlib.util.spec_from_file_location(f"_pl_{plugin_name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    if not hasattr(mod, "validate_url"):
        pytest.skip(f"{plugin_name} does not expose validate_url")
    return mod


def _invoke(mod, url):
    """Normalizza l'API tra plugin.

    browser_clear/browser_tor/browser_i2p: return str | None.
    solverr_fetch: raise ValueError. Lo uniformiamo qui cosi' i casi
    di test sono identici per tutti i plugin.
    """
    try:
        return mod.validate_url(url)
    except ValueError as e:
        return str(e)


# ---------------- browser_clear (clearnet, with DNS) ----------------
CLEAR_CASES = [
    ("https://example.com/",        None),
    ("http://1.1.1.1/",             None),
    ("http://127.0.0.1:8080/",      "IP non pubblico"),
    ("http://10.0.0.5/",            "IP non pubblico"),
    ("http://169.254.169.254/",     "IP non pubblico"),
    ("http://192.168.1.1/",         "IP non pubblico"),
    ("http://localhost/",           "host non consentito"),
    ("http://foo.local/",           "host non consentito"),
    ("http://foo.internal/",        "host non consentito"),
    ("http://stats.i2p/",           ".onion/.i2p"),
    ("http://abc.onion/",           ".onion/.i2p"),
    ("file:///etc/passwd",          "schema non consentito"),
    ("ftp://example.com/",          "schema non consentito"),
    ("http://0x7f.1/",              "host numerico"),
    ("http://internalservice/",     "senza dominio"),
]


# ---------------- browser_tor (no DNS, .onion ok) ----------------
TOR_CASES = [
    ("https://example.com/",        None),
    ("http://abc.onion/",           None),
    ("http://127.0.0.1/",           "IP non pubblico"),
    ("http://10.0.0.5/",            "IP non pubblico"),
    ("http://169.254.169.254/",     "IP non pubblico"),
    ("file:///etc/passwd",          "schema non consentito"),
    # hostname is left to Tor; we do NOT resolve it here
    ("http://localhost/",           None),
]


# ---------------- browser_i2p (only .i2p, no DNS) ----------------
I2P_CASES = [
    ("http://stats.i2p/",           None),
    ("http://example.com/",         "solo host .i2p"),
    ("http://abc.onion/",           "solo host .i2p"),
    ("http://127.0.0.1/",           "solo host .i2p"),
    ("file:///etc/passwd",          "schema non consentito"),
]


# ---------------- solverr_fetch (clearnet, no DNS in validator) ----------------
SOLVERR_CASES = [
    ("https://example.com/",        None),
    ("http://127.0.0.1:8191/",      "IP non pubblico"),
    ("http://10.0.0.5/",            "IP non pubblico"),
    ("http://169.254.169.254/",     "IP non pubblico"),
    ("file:///etc/passwd",          "schema non consentito"),
    ("http://localhost/",           "host non consentito"),
    ("http://0x7f.1/",              "host numerico"),
]


@pytest.mark.parametrize("url,expected", CLEAR_CASES)
def test_browser_clear(url, expected):
    mod = _load("browser_clear")
    _check(_invoke(mod, url), expected, "browser_clear", url)


@pytest.mark.parametrize("url,expected", TOR_CASES)
def test_browser_tor(url, expected):
    mod = _load("browser_tor")
    _check(_invoke(mod, url), expected, "browser_tor", url)


@pytest.mark.parametrize("url,expected", I2P_CASES)
def test_browser_i2p(url, expected):
    mod = _load("browser_i2p")
    _check(_invoke(mod, url), expected, "browser_i2p", url)


@pytest.mark.parametrize("url,expected", SOLVERR_CASES)
def test_solverr_fetch(url, expected):
    mod = _load("solverr_fetch")
    _check(_invoke(mod, url), expected, "solverr_fetch", url)


def _check(got, expected, plugin, url):
    if expected is None:
        assert got is None, f"{plugin}: {url} should be accepted, got {got!r}"
    else:
        assert got is not None, f"{plugin}: {url} should be rejected"
        assert expected in got, (
            f"{plugin}: {url} rejected but message is {got!r}, "
            f"expected substring {expected!r}"
        )

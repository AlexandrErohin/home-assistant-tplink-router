"""Plaintext → web-encrypted password helper for TP-Link LuCI extenders/APs.

The RE LuCI firmware family (RE505X, RE813XE, RE700X, …) never accepts a
plaintext admin password over the wire. The login page encrypts it with the
device's RSA public key (PKCS#1 v1.5) before POSTing it as a single 256-hex
blob, and the ``tplinkrouterc6u`` RE clients require exactly that pre-encrypted
value (their ``supports()``/``authorize()`` reject passwords shorter than 200
chars).

Instead of asking the user to hunt the encrypted value out of the browser's
devtools, this helper lets the integration do what the login page does:

  1. read the device's RSA public key via
     ``GET {host}/cgi-bin/luci/;stok=/login?form=login&operation=read``
     (which returns ``password: ["<n hex>", "<e hex>"]``);
  2. RSA-encrypt the plaintext with PKCS#1 v1.5 → 256-hex value.

Devices that do *not* expose that endpoint (every other TP-Link firmware the
library supports) are left untouched: the password is passed through unchanged,
so this helper is a no-op for them.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
import json

_LOGGER = logging.getLogger(__package__)

# 1024-bit RSA -> 128 bytes -> 256 hex chars. A "web-encrypted" password is
# always this length, far above the 200-char floor the RE clients check.
_WEB_ENC_MIN = 200


def _fetch_rsa_key(host: str, timeout: float = 8.0) -> tuple[str, str] | None:
    """Return (modulus_n, exponent_e) hex strings, or None if unsupported.

    Raises on hard HTTP/parse failures so callers can distinguish "not this
    firmware" (None) from "device is unreachable/broken" (exception).
    """
    parsed = urllib.parse.urlparse(host)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    origin = f"{scheme}://{netloc}"
    url = f"{scheme}://{netloc}/cgi-bin/luci/;stok=/login?form=login&operation=read"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Safari/605.1.15"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{origin}/webpages/login.html",
            "Origin": origin,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (LAN device)
        raw = resp.read().decode("utf-8", errors="replace")

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    pwd_key = data.get("password") if isinstance(data, dict) else None
    if not isinstance(pwd_key, list) or len(pwd_key) < 2:
        return None

    n_hex, e_hex = str(pwd_key[0]), str(pwd_key[1])
    # Sanity checks: n ~ a 256-hex RSA modulus (2048-bit) and a short exponent.
    if not (200 <= len(n_hex) <= 512 and 0 < len(e_hex) <= 8):
        return None
    return n_hex, e_hex


def _rsa_pkcs1_encrypt_hex(plaintext: str, n_hex: str, e_hex: str) -> str | None:
    """Encrypt plaintext with device RSA key (PKCS#1 v1.5) → uppercase 256-hex."""
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5

    try:
        key = RSA.construct((int(n_hex, 16), int(e_hex, 16)))
        cipher = PKCS1_v1_5.new(key)
        blob = cipher.encrypt(plaintext.encode("utf-8"))
    except Exception:  # noqa: BLE001 - key malformed or too large for the modulus
        _LOGGER.warning("TPLink Router failed to RSA-encrypt web password", exc_info=True)
        return None
    return blob.hex().upper()


def web_encrypt_password(host: str, password: str) -> str:
    """Return a web-encrypted password for RE LuCI, or the input unchanged.

    If ``password`` already looks web-encrypted (>= 200 chars) or the device
    does not expose the RSA-key endpoint, the input is returned untouched.
    """
    if not password or len(password) >= _WEB_ENC_MIN:
        return password

    try:
        key = _fetch_rsa_key(host)
    except Exception:
        # Reachable device but the probe failed at transport level — do not
        # mangle the password; let the normal client handle the error.
        _LOGGER.debug("TPLink Router key probe failed; using password as-is", exc_info=True)
        return password

    if key is None:
        # Not the web-encrypted LuCI firmware — pass through unchanged.
        return password

    encrypted = _rsa_pkcs1_encrypt_hex(password, key[0], key[1])
    if encrypted is None:
        return password
    return encrypted

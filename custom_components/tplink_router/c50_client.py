"""
TPLink Archer C50 client.

The Archer C50 (and AC1200-series routers with INCLUDE_LOGIN_GDPR_ENCRYPT=1
and a 512-bit RSA key) use a different auth mechanism than the standard MR
client:

  * Login:  POST /cgi_gdpr  with  sign=<PKCS1v1.5 RSA>\r\ndata=<AES-CBC>\r\n
            Plaintext data format:  8\r\n[/cgi/login#...]0,2\r\nusername=...\r\npassword=...\r\n
  * Data:   POST /cgi_gdpr  same envelope, reusing the AES key and RSA params
            from the login exchange.  Sign omits the AES key (non-login mode).

The critical differences from TPLinkMRClient:
  - RSA key is 512-bit, requires PKCS#1 v1.5 padding (53-byte chunks).
  - MR client uses raw RSA with 64-byte chunks on a 1024-bit key.
  - Login payload uses CGI action format, not just "username\\npassword".
  - RSA/AES session params are reused for all requests (no per-request key).
"""

from __future__ import annotations

import re
from base64 import b64decode, b64encode
from binascii import b2a_hex
from datetime import datetime
from hashlib import md5
from logging import Logger
from random import randint
from time import sleep, time
from typing import Optional

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey.RSA import construct
from Crypto.Util.Padding import pad, unpad
from requests import Session

from tplinkrouterc6u.client.mr import TPLinkMRClient
from tplinkrouterc6u.common.exception import AuthorizeError, ClientException


class TPLinkC50Client(TPLinkMRClient):
    """Client for Archer C50 and similar AC1200-series routers."""

    ROUTER_NAME = "TP Link Router C50"

    # RSA key size for this family: 512-bit → 64 bytes → 128 hex chars
    _RSA_KEY_HEX_LEN = 128
    # PKCS#1 v1.5 max plaintext per block: 64 - 11 = 53 bytes
    _RSA_CHUNK = 53

    def __init__(
        self,
        host: str,
        password: str,
        username: str = "admin",
        logger: Logger = None,
        verify_ssl: bool = True,
        timeout: int = 30,
    ) -> None:
        super().__init__(host, password, username, logger, verify_ssl, timeout)
        self._session = Session()
        if not self._verify_ssl:
            self._session.verify = False

        # Set during authorize(); reused for all subsequent requests
        self._aes_key: Optional[str] = None
        self._aes_iv: Optional[str] = None
        self._login_nn: Optional[str] = None
        self._login_ee: Optional[str] = None
        self._login_seq: Optional[int] = None

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def supports(self) -> bool:
        """
        Return True when the router has INCLUDE_LOGIN_GDPR_ENCRYPT=1 *and*
        a 512-bit RSA key *and* uses PKCS#1 v1.5 padding (flag=1).

        We intentionally do NOT attempt a full login here, because the parent
        class' supports() already does a plain RSA-key fetch and falsely
        claims support for this family too (it has the same endpoint).

        Detection strategy:
        1. The RSA key must be exactly 512-bit (128 hex chars).
        2. The oid_str.js must declare INCLUDE_LOGIN_GDPR_ENCRYPT=1.
        3. The tpEncrypt.js must use RSA flag=1 (PKCS#1 v1.5, 53-byte chunks).
           Some routers (e.g. TL-WR841N) also have a 512-bit key and
           INCLUDE_LOGIN_GDPR_ENCRYPT=1 but use flag=0 (raw RSA, 64-byte
           chunks) and are handled by the standard MR client.
        """
        try:
            nn, _ee, _seq = self._fetch_rsa_key()
            if len(nn) != self._RSA_KEY_HEX_LEN:
                # Not a 512-bit key — leave it for the standard MR client
                return False

            # Confirm INCLUDE_LOGIN_GDPR_ENCRYPT=1 is declared in oid_str.js
            r = self._session.get(
                f"{self.host}/js/oid_str.js",
                headers=self._base_headers(),
                timeout=self.timeout,
                verify=self._verify_ssl,
            )
            if not (r.status_code == 200 and "INCLUDE_LOGIN_GDPR_ENCRYPT=1" in r.text):
                return False

            # Confirm PKCS#1 v1.5 padding (flag=1) is used in tpEncrypt.js.
            # Routers with flag=0 use raw RSA and are handled by the standard client.
            r2 = self._session.get(
                f"{self.host}/js/tpEncrypt.js",
                headers=self._base_headers(),
                timeout=self.timeout,
                verify=self._verify_ssl,
            )
            return r2.status_code == 200 and "512,1" in r2.text
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authorize(self) -> None:
        # Always start with a clean HTTP session so stale JSESSIONID cookies
        # from a previous login do not confuse the router on re-login.
        self._session = Session()
        if not self._verify_ssl:
            self._session.verify = False

        nn, ee, seq = self._fetch_rsa_key()

        ts = str(round(time() * 1000))
        aes_key = (ts + str(randint(100_000_000, 999_999_999)))[:16]
        aes_iv = (ts + str(randint(100_000_000, 999_999_999)))[:16]
        pw_hash = md5(f"{self.username}{self.password}".encode()).hexdigest()

        login_plain = (
            f"8\r\n"
            f"[/cgi/login#0,0,0,0,0,0#0,0,0,0,0,0]0,2\r\n"
            f"username={self.username}\r\n"
            f"password={self.password}\r\n"
        )

        enc_data = self._aes_enc(login_plain, aes_key, aes_iv)
        sign = self._make_sign(
            seq + len(enc_data),
            is_login=True,
            pw_hash=pw_hash,
            nn=nn,
            ee=ee,
            aes_key=aes_key,
            aes_iv=aes_iv,
        )

        body = f"sign={sign}\r\ndata={enc_data}\r\n"
        response = self._session.post(
            f"{self.host}/cgi_gdpr",
            headers=self._base_headers(),
            data=body,
            timeout=self.timeout,
            stream=True,
        )
        raw = self._read_chunked(response)

        if self._logger:
            self._logger.warning(
                "%s - authorize: HTTP %s raw_len=%s raw_prefix=%s",
                self.ROUTER_NAME,
                response.status_code,
                len(raw),
                repr(raw[:120]),
            )

        if response.status_code != 200:
            raise ClientException(
                f"{self.ROUTER_NAME} - authorize: HTTP {response.status_code}"
            )

        try:
            decrypted = self._aes_dec(raw, aes_key, aes_iv)
        except Exception as exc:
            raise ClientException(
                f"{self.ROUTER_NAME} - authorize: AES decrypt failed: {exc}; "
                f"raw_len={len(raw)} raw_prefix={repr(raw[:120])}"
            ) from exc

        if "$.ret=0" not in decrypted:
            ret_match = re.search(r"\$\.ret=(\d+)", decrypted)
            ret_code = int(ret_match.group(1)) if ret_match else -1
            if ret_code == self.HTTP_ERR_USER_PWD_NOT_CORRECT:
                raise AuthorizeError(
                    f"{self.ROUTER_NAME} - Login failed: wrong password"
                )
            raise ClientException(
                f"{self.ROUTER_NAME} - Login failed. Error code: {ret_code}"
            )

        # The router requires a GET / after login to fully initialize the
        # server-side session before it will accept /cgi_gdpr data requests.
        # A browser does this automatically via the post-login redirect.
        root_resp = self._session.get(
            self.host + "/",
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*",
                "User-Agent": self._base_headers()["User-Agent"],
                "Referer": self._base_headers()["Referer"],
            },
            timeout=self.timeout,
            verify=self._verify_ssl,
        )
        if self._logger:
            self._logger.debug(
                "%s - authorize: GET / status=%s cookies=%s",
                self.ROUTER_NAME,
                root_resp.status_code,
                dict(self._session.cookies),
            )

        # Persist session params for subsequent requests
        self._login_nn = nn
        self._login_ee = ee
        self._login_seq = seq
        self._aes_key = aes_key
        self._aes_iv = aes_iv
        self._token = "c50_session"  # sentinel so base-class guards pass
        self._authorized_at = datetime.now()

    def logout(self) -> None:
        # Clear local session state.  The next authorize() creates a fresh
        # HTTP session (new JSESSIONID), so no explicit HTTP logout request
        # is needed — the router will time out the old server-side session.
        self._aes_key = None
        self._aes_iv = None
        self._login_nn = None
        self._login_ee = None
        self._login_seq = None
        self._token = None

    # ------------------------------------------------------------------
    # Request layer — overrides parent to use C50 encryption
    # ------------------------------------------------------------------

    def req_act(self, acts: list):
        """Send a CGI action list via the GDPR-encrypted endpoint."""
        if not self._aes_key:
            raise ClientException(
                f"{self.ROUTER_NAME} - req_act called without active session"
            )

        act_types, act_data = self._fill_acts(acts)
        data_str = "&".join(act_types) + "\r\n" + "".join(act_data)

        pw_hash = md5(f"{self.username}{self.password}".encode()).hexdigest()
        enc_data = self._aes_enc(data_str, self._aes_key, self._aes_iv)
        sign = self._make_sign(
            self._login_seq + len(enc_data),
            is_login=False,
            pw_hash=pw_hash,
            nn=self._login_nn,
            ee=self._login_ee,
        )

        body = f"sign={sign}\r\ndata={enc_data}\r\n"

        if self._logger:
            self._logger.debug(
                "%s - req_act: cookies=%s seq=%s enc_len=%s",
                self.ROUTER_NAME,
                dict(self._session.cookies),
                self._login_seq + len(enc_data),
                len(enc_data),
            )

        # Retry up to REQUEST_RETRIES times on transient 500/406 errors,
        # matching the retry behaviour of the parent TPLinkMRClient._request().
        for attempt in range(self.REQUEST_RETRIES):
            response = self._session.post(
                f"{self.host}/cgi_gdpr",
                headers=self._base_headers(),
                data=body,
                timeout=self.timeout,
                stream=True,
            )
            raw = self._read_chunked(response)
            if self._logger:
                self._logger.debug(
                    "%s - req_act attempt %s: HTTP %s raw_len=%s raw_prefix=%s",
                    self.ROUTER_NAME,
                    attempt,
                    response.status_code,
                    len(raw),
                    repr(raw[:60]),
                )
            if response.status_code not in (500, 406):
                break
            sleep(0.5)

        if response.status_code != 200:
            raise ClientException(
                f"{self.ROUTER_NAME} - req_act HTTP {response.status_code}"
            )

        try:
            decrypted = self._aes_dec(raw, self._aes_key, self._aes_iv)
        except Exception as exc:
            raise ClientException(
                f"{self.ROUTER_NAME} - req_act AES decrypt failed: {exc}"
            ) from exc

        result = self._merge_response(decrypted)
        return decrypted, result.get("0") if len(result) == 1 and result.get("0") else result

    # ------------------------------------------------------------------
    # Crypto helpers
    # ------------------------------------------------------------------

    def _fetch_rsa_key(self) -> tuple[str, str, int]:
        """Fetch nn, ee, seq from /cgi/getParm."""
        r = self._session.post(
            f"{self.host}/cgi/getParm",
            headers=self._base_headers(),
            timeout=self.timeout,
        )
        try:
            ee = re.search(r'var ee="(.*)";', r.text).group(1)
            nn = re.search(r'var nn="(.*)";', r.text).group(1)
            seq = int(re.search(r'var seq="(.*)";', r.text).group(1))
            return nn, ee, seq
        except Exception as exc:
            raise ClientException(
                f"{self.ROUTER_NAME} - RSA key fetch failed: {exc}; "
                f"response: {r.text[:200]}"
            ) from exc

    @staticmethod
    def _rsa_pkcs_encrypt(data: str, nn: str, ee: str) -> str:
        """Encrypt a chunk with RSA PKCS#1 v1.5."""
        n = int(nn, 16)
        e = int(ee, 16)
        key = construct((n, e))
        cipher = PKCS1_v1_5.new(key)
        return b2a_hex(cipher.encrypt(data.encode("utf-8"))).decode()

    def _make_sign(
        self,
        seq: int,
        is_login: bool,
        pw_hash: str,
        nn: str,
        ee: str,
        aes_key: str = "",
        aes_iv: str = "",
    ) -> str:
        """Build the RSA-encrypted signature string."""
        if is_login:
            s = f"key={aes_key}&iv={aes_iv}&h={pw_hash}&s={seq}"
        else:
            s = f"h={pw_hash}&s={seq}"

        sign = ""
        for i in range(0, len(s), self._RSA_CHUNK):
            sign += self._rsa_pkcs_encrypt(s[i : i + self._RSA_CHUNK], nn, ee)
        return sign

    @staticmethod
    def _aes_enc(data: str, key: str, iv: str) -> str:
        """AES-128-CBC encrypt, return base64 string."""
        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
        encrypted = cipher.encrypt(pad(data.encode("utf-8"), 16, "pkcs7"))
        return b64encode(encrypted).decode("utf-8")

    @staticmethod
    def _aes_dec(data: str, key: str, iv: str) -> str:
        """AES-128-CBC decrypt a base64 string."""
        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
        decrypted = cipher.decrypt(b64decode(data))
        return unpad(decrypted, 16, "pkcs7").decode("utf-8")

    def _base_headers(self) -> dict:
        return {
            "Accept": "*/*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) "
                "Gecko/20100101 Firefox/90.0"
            ),
            "Referer": f"{self.host}/",
            "Content-Type": "text/plain",
        }

    @staticmethod
    def _read_chunked(response) -> str:  # noqa: E301
        """Read a potentially chunked HTTP response safely."""
        raw = b""
        try:
            for chunk in response.iter_content(chunk_size=None):
                raw += chunk
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")


class TPLinkWR841NClient(TPLinkC50Client):
    """
    Client for GDPR-encrypted routers using raw RSA (flag=0, 512-bit key).

    These routers share the same /cgi_gdpr + AES-128-CBC protocol as the C50
    family, but use raw RSA (no PKCS#1 v1.5 padding) for the sign field:
      - tpEncrypt.js: $.rsa.encrypt(..., 512, 0)  ← flag=0
      - Block size: 64 bytes (full 512-bit key, no padding overhead)

    Examples: TL-WR841N v14
    """

    ROUTER_NAME = "TP Link Router WR841N"

    # Raw RSA: full 64-byte block (no PKCS#1 overhead)
    _RSA_CHUNK = 64

    def supports(self) -> bool:
        """
        Return True for GDPR-encrypted routers with a 512-bit key and raw
        RSA (flag=0): INCLUDE_LOGIN_GDPR_ENCRYPT=1 and "512,0" in tpEncrypt.js.
        """
        try:
            nn, _ee, _seq = self._fetch_rsa_key()
            if len(nn) != self._RSA_KEY_HEX_LEN:
                return False

            r = self._session.get(
                f"{self.host}/js/oid_str.js",
                headers=self._base_headers(),
                timeout=self.timeout,
                verify=self._verify_ssl,
            )
            if not (r.status_code == 200 and "INCLUDE_LOGIN_GDPR_ENCRYPT=1" in r.text):
                return False

            r2 = self._session.get(
                f"{self.host}/js/tpEncrypt.js",
                headers=self._base_headers(),
                timeout=self.timeout,
                verify=self._verify_ssl,
            )
            return r2.status_code == 200 and "512,0" in r2.text
        except Exception:
            return False

    @staticmethod
    def _rsa_pkcs_encrypt(data: str, nn: str, ee: str) -> str:
        """Raw RSA encryption (no padding) — flag=0, 512-bit key."""
        n = int(nn, 16)
        e = int(ee, 16)
        block_size = (n.bit_length() + 7) // 8  # 64 bytes for 512-bit key
        m_bytes = data.encode("utf-8").rjust(block_size, b"\x00")
        m = int.from_bytes(m_bytes, "big")
        c = pow(m, e, n)
        return hex(c)[2:].zfill(block_size * 2)

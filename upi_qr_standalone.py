#!/usr/bin/env python3
"""
upi_qr_standalone.py — Standalone, no-proxy UPI QR generator (Termux-ready)
===========================================================================

Reverse-engineered from upi.vaultvip.pro ("Vault × OpenAI — UPI QR Gen"),
which is a hosted front-end over the `gpt_signup_hybrid` UPI pipeline
(web/upi_runner.py + pay_upi_http.py + stripe_token.py). The hosted site
demands Indian rotating proxies only because it runs on the operator's
foreign server; run from YOUR Indian IP it needs no proxy at all.

Pipeline (1:1 with the original):

    checkout       POST chatgpt.com/backend-api/payments/checkout
                   (chatgptplusplan, IN/INR, promo plus-1-month-free, custom UI)
                   → checkout_session_id (cs_live_…) + Stripe publishable key
    stripe_init    POST api.stripe.com/v1/payment_pages/{cs}/init
                   → init_checksum + payment-page id
    tax_update     POST chatgpt.com/backend-api/payments/checkout/update
                   (re-applies the ₹0 promo)
    payment_method GET  api.stripe.com/v1/elements/sessions
                   (deferred subscription intent, INR, UPI)
    stripe_confirm POST api.stripe.com/v1/payment_pages/{cs}/confirm
                   (payment_method_data.type=upi, upi.flow=qr_code, plus the
                   js_checksum / rv_timestamp anti-bot tokens computed by
                   fetching and parsing Stripe's own custom-checkout JS bundle)
    instructions   the confirm/refresh response carries
                   next_action.upi_handle_redirect_or_display_qr_code with
                   hosted_instructions_url  ← THE PAYMENT LINK (what the
                   website shows as "Copy Link") + qr image urls + expires_at
    approve        poll POST …/payments/checkout/approve until result=="approved"
                   — this is the AUTO-DETECT: after you scan & pay in any UPI
                   app, the script notices, verifies Plus went live, and exits.

What you get:
  • The PAYMENT LINK (payments.stripe.com/upi/instructions/…) — open it
    anywhere, it shows the QR and can deep-link into your UPI app.
  • The raw upi://pay?… mandate URI.
  • A QR rendered right in the terminal (Termux-friendly) plus PNG/SVG files.

Termux notes
------------
    pkg install python -y
    pip install httpx qrcode
    python upi_qr_standalone.py

Pure-Python HTTP (httpx, or stdlib urllib fallback) — no curl_cffi, no
compilers, no rust toolchain. Nothing here is Termux-incompatible.

Usage
-----
    python upi_qr_standalone.py                        # interactive
    python upi_qr_standalone.py --token "eyJ…"          # auto-waits for payment
    python upi_qr_standalone.py --token "eyJ…" --no-wait
    python upi_qr_standalone.py --tokens-file t.txt     # bulk, like the site
    python upi_qr_standalone.py --vpa you@oksbi         # intent flow (optional)
    python upi_qr_standalone.py --selftest              # offline verification
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import string
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

try:
    import httpx  # type: ignore[import-untyped]
except ImportError:
    httpx = None

try:
    import qrcode  # type: ignore[import-untyped]
except ImportError:
    qrcode = None

LogFn = Callable[[str], None]

# ─────────────────────────────────────────────────────────────────────
# Constants (mirrors of the original pipeline)
# ─────────────────────────────────────────────────────────────────────

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Chromium";v="145", "Google Chrome";v="145", "Not-A.Brand";v="99"'
SEC_CH_UA_MOBILE = "?0"
SEC_CH_UA_PLATFORM = '"Windows"'

STRIPE_VERSION = (
    "2025-03-31.basil; checkout_server_update_beta=v1; "
    "checkout_manual_approval_preview=v1"
)

CHATGPT_CHECKOUT_URL = "https://chatgpt.com/backend-api/payments/checkout"
CHATGPT_UPDATE_URL = "https://chatgpt.com/backend-api/payments/checkout/update"
CHATGPT_APPROVE_URL = "https://chatgpt.com/backend-api/payments/checkout/approve"
CHATGPT_ME_URL = "https://chatgpt.com/backend-api/me"
CHATGPT_SESSION_URL = "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27"
STRIPE_INIT_URL = "https://api.stripe.com/v1/payment_pages/{id}/init"
STRIPE_PAGE_URL = "https://api.stripe.com/v1/payment_pages/{id}"
STRIPE_CONFIRM_URL = "https://api.stripe.com/v1/payment_pages/{id}/confirm"
STRIPE_ELEMENTS_URL = "https://api.stripe.com/v1/elements/sessions"
STRIPE_JS_ENTRY_URL = "https://js.stripe.com/v3/"

INSTRUCTIONS_PREFIX = "https://payments.stripe.com/upi/instructions/"

PROXIES = None  # no proxy, ever — that's the whole point


# ─────────────────────────────────────────────────────────────────────
# HTTP layer — httpx if available, else stdlib urllib. Same interface.
# ─────────────────────────────────────────────────────────────────────


class HttpResponse:
    """Minimal response object shared by both backends."""

    def __init__(self, status_code: int, headers: dict[str, str], content: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self._text_cache: str | None = None

    @property
    def text(self) -> str:
        if self._text_cache is None:
            self._text_cache = self.content.decode("utf-8", errors="replace")
        return self._text_cache

    def json(self) -> Any:
        return json.loads(self.text)


class _UrllibBackend:
    """Stdlib fallback — zero dependencies, works anywhere Python runs."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | list[tuple[str, str]] | None = None,
        data: list[tuple[str, str]] | dict | str | bytes | None = None,
        json_body: Any = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}{'&' if '?' in url else '?'}{query}"

        body: bytes | None = None
        headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            if isinstance(data, list):
                body = urllib.parse.urlencode(data).encode("utf-8")
            elif isinstance(data, dict):
                body = urllib.parse.urlencode(data).encode("utf-8")
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = data
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        req.timeout = timeout
        opener = urllib.request.build_opener()
        if PROXIES:
            opener.add_handler(urllib.request.ProxyHandler({"http": PROXIES, "https": PROXIES}))
        try:
            with opener.open(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, dict(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read())

    def get(self, url: str, **kw: Any) -> HttpResponse:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> HttpResponse:
        return self.request("POST", url, **kw)

    def head(self, url: str, **kw: Any) -> HttpResponse:
        return self.request("HEAD", url, **kw)


class _HttpxBackend:
    def __init__(self) -> None:
        limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
        self._client = httpx.Client(
            http2=False,
            timeout=httpx.Timeout(30.0, connect=15.0),
            limits=limits,
            follow_redirects=True,
            proxy=PROXIES,
            headers={"User-Agent": UA},
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: Any = None,
        data: Any = None,
        json_body: Any = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        kwargs: dict[str, Any] = {"headers": headers, "params": params, "timeout": timeout}
        if json_body is not None:
            kwargs["json"] = json_body
        elif data is not None:
            kwargs["content"] = (
                urllib.parse.urlencode(data).encode("utf-8")
                if isinstance(data, (list, dict))
                else (data.encode("utf-8") if isinstance(data, str) else data)
            )
            if "Content-Type" not in (headers or {}):
                kwargs["headers"] = {**(headers or {}), "Content-Type": "application/x-www-form-urlencoded"}
        resp = self._client.request(method, url, **kwargs)
        return HttpResponse(resp.status_code, dict(resp.headers.items()), resp.content)

    def get(self, url: str, **kw: Any) -> HttpResponse:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> HttpResponse:
        return self.request("POST", url, **kw)

    def head(self, url: str, **kw: Any) -> HttpResponse:
        return self.request("HEAD", url, **kw)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


def make_session() -> Any:
    if httpx is not None:
        return _HttpxBackend()
    return _UrllibBackend()


def retry_call(fn: Callable[[], HttpResponse], *, attempts: int = 3, backoff: float = 2.0,
               label: str, log: LogFn) -> HttpResponse:
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — network/timeout → retry
            last = exc
            log(f"      {label} attempt {i}/{attempts} failed: {type(exc).__name__}: {str(exc)[:120]}")
            if i < attempts:
                time.sleep(backoff * i)
    assert last is not None
    raise last


# ─────────────────────────────────────────────────────────────────────
# Console formatting
# ─────────────────────────────────────────────────────────────────────


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return bool(sys.stdout.isatty())


_USE_COLOR = _supports_color()


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _USE_COLOR else text


def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)
def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def cyan(t: str) -> str:   return _c("36", t)


def short(s: str, head: int = 14, tail: int = 8) -> str:
    if not s or len(s) <= head + tail + 1:
        return s or ""
    return f"{s[:head]}…{s[-tail:]}"


def log_step(tag: str, label: str, status: str, detail: str = "", log: LogFn = print) -> None:
    icons = {"start": "▸", "ok": green("✓"), "fail": red("✗"), "warn": yellow("⚠"), "info": "·"}
    icon = icons.get(status, "·")
    color = {"ok": green, "fail": red, "warn": yellow}.get(status, str)
    line = f"  [{tag}] {color(label)}"
    if detail:
        line += f"  {dim(detail)}"
    log(f"{icon} {line}")


# ─────────────────────────────────────────────────────────────────────
# India billing profile generator (matches original random_india_profile)
# ─────────────────────────────────────────────────────────────────────

_IN_FIRST_NAMES = (
    "Aarav", "Aditya", "Arjun", "Ayaan", "Dhruv", "Ishaan", "Kabir", "Karan",
    "Krishna", "Reyansh", "Rohan", "Rudra", "Sai", "Shaurya", "Vihaan", "Vivaan",
    "Aanya", "Aadhya", "Ananya", "Anika", "Diya", "Ira", "Kavya", "Myra",
    "Navya", "Neha", "Pari", "Pooja", "Priya", "Riya", "Saanvi", "Tara",
)
_IN_LAST_NAMES = (
    "Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Reddy", "Nair",
    "Iyer", "Rao", "Das", "Bose", "Chopra", "Mehta", "Jain", "Shah",
    "Agarwal", "Pillai", "Menon", "Banerjee", "Chatterjee", "Mukherjee",
    "Desai", "Kapoor", "Malhotra", "Joshi", "Saxena", "Bhat", "Nayak", "Sinha",
)
_IN_CITIES = (
    ("Mumbai", "Maharashtra", "4000"),
    ("Delhi", "Delhi", "1100"),
    ("Bengaluru", "Karnataka", "5600"),
    ("Chennai", "Tamil Nadu", "6000"),
    ("Hyderabad", "Telangana", "5000"),
    ("Kolkata", "West Bengal", "7000"),
    ("Pune", "Maharashtra", "4110"),
    ("Ahmedabad", "Gujarat", "3800"),
    ("Jaipur", "Rajasthan", "3020"),
    ("Lucknow", "Uttar Pradesh", "2260"),
)
_IN_STREETS = (
    "MG Road", "Brigade Road", "Linking Road", "Park Street", "Anna Salai",
    "Connaught Place", "Banjara Hills", "Koramangala", "Andheri West",
    "Salt Lake", "Jubilee Hills", "Indiranagar", "Sector 18", "Civil Lines",
)


def random_india_profile() -> dict[str, str]:
    first = secrets.choice(_IN_FIRST_NAMES)
    last = secrets.choice(_IN_LAST_NAMES)
    city, state, pin_prefix = secrets.choice(_IN_CITIES)
    house_no = secrets.randbelow(999) + 1
    street = secrets.choice(_IN_STREETS)
    postal_code = f"{pin_prefix}{secrets.randbelow(100):02d}"
    return {
        "name": f"{first} {last}",
        "phone": f"+91{secrets.choice('6789')}{''.join(secrets.choice(string.digits) for _ in range(9))}",
        "address_line1": f"{house_no}, {street}",
        "city": city,
        "state": state,
        "postal_code": postal_code,
    }


# ─────────────────────────────────────────────────────────────────────
# Stripe token engine (js_checksum / rv_timestamp) — port of stripe_token.py
# ─────────────────────────────────────────────────────────────────────


def caesar_shift(s: str, n: int) -> str:
    """JS: String.fromCharCode((charCodeAt(a)-32+n)%95+32)."""
    return "".join(chr((ord(c) - 32 + n) % 95 + 32) for c in s)


def stripe_encode(s: str) -> str:
    """Stripe module 9107 P.l(): xor-5 each byte, base64, urlencode.

    Quirk kept: pad = 3 - len(s) % 3 (never re-modulo'd) → always 1..3 spaces.
    """
    pad = 3 - len(s) % 3
    padded = s + " " * pad
    xored = bytes(5 ^ ord(c) for c in padded)
    return urllib.parse.quote(
        base64.b64encode(xored).decode("ascii"),
        safe="-_.!~*'()",
    )


def _js_stringify(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


_CAESAR_FN_RE = re.compile(
    r"\b[a-zA-Z_$][\w$]{0,3}\s*=\s*function\s*\(\s*"
    r"[a-zA-Z_$][\w$]{0,3}\s*,\s*"
    r"[a-zA-Z_$][\w$]{0,3}\s*\)\s*\{"
    r"[^{}]*?charCodeAt\([^)]*?\)\s*-\s*32\s*\+\s*[a-zA-Z_$][\w$]{0,3}\s*\)\s*%\s*95\s*\+\s*32"
    r"[^{}]*?\}"
)

_JS_CHECKSUM_RE = re.compile(
    r"\b(?P<fn>[a-zA-Z_$][\w$]{0,3})\s*\(\s*"
    r"\(\s*0\s*,\s*(?P<encmod>[a-zA-Z_$][\w$]{0,3})\s*\.\s*(?P<encfn>[a-zA-Z_$][\w$]{0,3})\s*\)"
    r"\s*\(\s*JSON\s*\.\s*stringify\s*\(\s*\{\s*id\s*:\s*[a-zA-Z_$][\w$]*\s*\}\s*\)\s*\)"
    r"\s*,\s*(?P<shift>\d+)\s*\)"
)

_RV_TIMESTAMP_RE = re.compile(
    r"rv_timestamp\s*:\s*[a-zA-Z_$][\w$]{0,3}"
    r"\s*\(\s*\(\s*0\s*,\s*[a-zA-Z_$][\w$]{0,3}\s*\.\s*[a-zA-Z_$][\w$]{0,3}\s*\)"
    r"\s*\(\s*JSON\s*\.\s*stringify\s*\(\s*\{(?P<keys>[^}]+)\}\s*\)\s*\)"
    r"\s*,\s*(?P<shift>\d+)\s*\)"
)

_WEBPACK_REQUIRE_RE = re.compile(
    r"\b(?P<lhs>[a-zA-Z_$][\w$]{0,3})\s*=\s*[a-zA-Z_$][\w$]{0,3}\s*\(\s*(?P<id>\d+)\s*\)"
)


class StripeTokenExtractError(Exception):
    """Could not extract the token config from Stripe's bundle."""


class _StripeTokenConfig:
    __slots__ = ("bundle_hash", "shift", "rv_ts", "rv", "sv")

    def __init__(self, bundle_hash: str, shift: int, rv_ts: str, rv: str, sv: str) -> None:
        self.bundle_hash = bundle_hash
        self.shift = shift
        self.rv_ts = rv_ts
        self.rv = rv
        self.sv = sv

    def __repr__(self) -> str:
        return f"StripeTokenConfig(shift={self.shift}, rv={self.rv[:8]}…, sv={self.sv[:8]}…)"


def _balanced_brace(body: str, open_pos: int) -> int:
    depth = 0
    in_str = False
    ch_str = ""
    i = open_pos
    while i < len(body):
        c = body[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == ch_str:
                in_str = False
        else:
            if c in ("'", '"', "`"):
                in_str = True
                ch_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _extract_webpack_module(body: str, mod_id: int) -> str:
    pattern = re.compile(rf"[\s,{{(]{mod_id}\s*:\s*", re.MULTILINE)
    for m in pattern.finditer(body):
        rest = body[m.end(): m.end() + 200]
        sig = re.match(
            r"\s*(?:function\s*\([^)]*\)|\([^)]*\)\s*=>|[a-zA-Z_$][\w$]*\s*=>)\s*\{",
            rest,
        )
        if not sig:
            continue
        brace_open = m.end() + sig.end() - 1
        brace_close = _balanced_brace(body, brace_open)
        if brace_close < 0:
            continue
        return body[m.start(): brace_close + 1]
    return ""


def _extract_constants_from_module(mod_body: str) -> dict[str, str]:
    export_map: dict[str, str] = {}
    for m in re.finditer(
        r"([a-zA-Z_$][\w$]{0,3})\s*:\s*function\s*\(\s*\)\s*\{\s*return\s+([a-zA-Z_$][\w$]{0,3})\s*\}",
        mod_body,
    ):
        export_map[m.group(1)] = m.group(2)
    var_values: dict[str, str] = {}
    for m in re.finditer(
        r'\b([a-zA-Z_$][\w$]{0,3})\s*=\s*(?:/\*[^*]*(?:\*(?!/)[^*]*)*\*/\s*)?"([^"]*)"',
        mod_body,
    ):
        var_values.setdefault(m.group(1), m.group(2))
    out: dict[str, str] = {}
    for export_name, local_name in export_map.items():
        if local_name in var_values:
            out[export_name] = var_values[local_name]
    return out


def extract_config(bundle_source: str, *, fallback_sources: list[str] | None = None) -> _StripeTokenConfig:
    bundle_hash = hashlib.sha256(bundle_source.encode("utf-8")).hexdigest()

    if not _CAESAR_FN_RE.search(bundle_source):
        raise StripeTokenExtractError(
            "Caesar-shift function pattern not found — Stripe may have changed its obfuscation."
        )

    js_match = _JS_CHECKSUM_RE.search(bundle_source)
    if not js_match:
        raise StripeTokenExtractError(
            "js_checksum builder pattern not found — Stripe may have changed its payload structure."
        )
    shift = int(js_match.group("shift"))

    rv_match = _RV_TIMESTAMP_RE.search(bundle_source)
    if not rv_match:
        raise StripeTokenExtractError("rv_timestamp builder pattern not found.")
    if int(rv_match.group("shift")) != shift:
        raise StripeTokenExtractError(
            f"shift mismatch: js_checksum={shift} vs rv_timestamp={rv_match.group('shift')}"
        )

    member_refs = re.findall(
        r"(\w+)\s*:\s*([a-zA-Z_$][\w$]*)\s*\.\s*([a-zA-Z_$][\w$]*)",
        rv_match.group("keys"),
    )
    if len(member_refs) != 3:
        raise StripeTokenExtractError(
            f"rv_timestamp keys layout changed — expected 3 refs, got {member_refs}"
        )

    scope = bundle_source[
        max(0, rv_match.start() - 4000): min(len(bundle_source), rv_match.start() + 4000)
    ]
    constants_local = member_refs[0][1]
    constants_module_id: int | None = None
    for rm in _WEBPACK_REQUIRE_RE.finditer(scope):
        if rm.group("lhs") == constants_local:
            constants_module_id = int(rm.group("id"))
            break
    if constants_module_id is None:
        raise StripeTokenExtractError(
            f"could not resolve module id for constants local {constants_local!r}"
        )

    mod_body = _extract_webpack_module(bundle_source, constants_module_id)
    if not mod_body:
        for fb in fallback_sources or []:
            mod_body = _extract_webpack_module(fb, constants_module_id)
            if mod_body:
                break
    if not mod_body:
        raise StripeTokenExtractError(
            f"module {constants_module_id} body not found in any bundle source"
        )

    constants = _extract_constants_from_module(mod_body)
    expected_keys = {ref[2] for ref in member_refs}
    missing = expected_keys - set(constants)
    if missing:
        raise StripeTokenExtractError(
            f"constants module {constants_module_id} missing keys {missing}; got {list(constants)}"
        )

    key_to_member = {ref[0]: ref[2] for ref in member_refs}
    return _StripeTokenConfig(
        bundle_hash=bundle_hash,
        shift=shift,
        rv_ts=constants[key_to_member["rvTs"]],
        rv=constants[key_to_member["rv"]],
        sv=constants[key_to_member["sv"]],
    )


async def _noop() -> None:  # placeholder kept out of the way
    return None


def fetch_bundles_live(sess: Any, *, log: LogFn, use_cache: bool = True) -> tuple[str, str]:
    """Fetch Stripe entry JS + fingerprinted custom-checkout chunk.

    1. GET https://js.stripe.com/v3/
    2. Parse the webpack chunk-name / chunk-hash maps from the entry
    3. GET the fingerprinted custom-checkout-<hash>.js chunk

    Returns (cc_src, entry_src) — the rv/sv constants live in the entry.
    """
    common_headers = {
        "User-Agent": UA,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "Accept": "*/*",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    log("  · fetching Stripe entry https://js.stripe.com/v3/")
    r_entry = retry_call(
        lambda: sess.get(
            STRIPE_JS_ENTRY_URL,
            headers={**common_headers, "Referer": "https://chatgpt.com/"},
            timeout=30,
        ),
        label="stripe entry",
        log=log,
    )
    if r_entry.status_code != 200:
        raise StripeTokenExtractError(
            f"entry HTTP {r_entry.status_code}: {r_entry.text[:200]}"
        )
    entry = r_entry.text
    entry_hash = hashlib.sha256(entry.encode("utf-8")).hexdigest()

    cache_dir = (
        Path.home() / ".cache" / "upi_qr_standalone" / "stripe_bundles" / entry_hash[:16]
    )
    cc_cache = cache_dir / "custom_checkout.js"
    entry_cache = cache_dir / "entry.js"
    if use_cache and cc_cache.exists() and entry_cache.exists():
        log("  · stripe bundle cache hit")
        return cc_cache.read_text(encoding="utf-8"), entry_cache.read_text(encoding="utf-8")

    chunk_names: dict[int, str] = {}
    chunk_hashes: dict[int, str] = {}

    name_map_match = re.search(r'"fingerprinted/js/"[^}]*?\{([^}]+)\}', entry)
    if name_map_match:
        for em in re.finditer(r'(\d+):"([a-z][a-zA-Z0-9_-]+)"', name_map_match.group(1)):
            chunk_names[int(em.group(1))] = em.group(2)

    for m in re.finditer(r'\{(\d+:"[a-f0-9]{20,}",?){3,40}\}', entry):
        for em in re.finditer(r'(\d+):"([a-f0-9]{20,})"', m.group(0)):
            chunk_hashes[int(em.group(1))] = em.group(2)
        if chunk_hashes:
            break

    if not chunk_names or not chunk_hashes:
        raise StripeTokenExtractError(
            f"could not parse webpack chunk map (names={len(chunk_names)}, hashes={len(chunk_hashes)})"
        )

    cc_id = next((cid for cid, n in chunk_names.items() if n == "custom-checkout"), None)
    if cc_id is None:
        raise StripeTokenExtractError(
            f"no 'custom-checkout' chunk in map: {list(chunk_names.values())[:20]}"
        )
    cc_hash = chunk_hashes.get(cc_id)
    if not cc_hash:
        raise StripeTokenExtractError(f"no hash for chunk {cc_id} (custom-checkout)")

    cc_url = f"https://js.stripe.com/v3/fingerprinted/js/custom-checkout-{cc_hash}.js"
    log(f"  · fetching custom-checkout chunk ({cc_hash[:12]}…)")
    r_cc = retry_call(
        lambda: sess.get(
            cc_url,
            headers={
                **common_headers,
                "Referer": "https://js.stripe.com/v3/",
                "Sec-Fetch-Dest": "script",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "same-origin",
            },
            timeout=60,
        ),
        label="stripe cc chunk",
        log=log,
    )
    if r_cc.status_code != 200:
        raise StripeTokenExtractError(
            f"custom_checkout HTTP {r_cc.status_code}: {r_cc.text[:200]}"
        )
    cc_src = r_cc.text

    if use_cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cc_cache.write_text(cc_src, encoding="utf-8")
            entry_cache.write_text(entry, encoding="utf-8")
        except OSError:
            pass

    return cc_src, entry


def extract_config_live(sess: Any, *, log: LogFn, use_cache: bool = True) -> _StripeTokenConfig:
    cc_src, entry_src = fetch_bundles_live(sess, log=log, use_cache=use_cache)
    cfg = extract_config(cc_src, fallback_sources=[entry_src] if entry_src else [])
    log(f"  ✓ token config: shift={cfg.shift} rv={short(cfg.rv, 8, 4)} sv={short(cfg.sv, 8, 4)}")
    return cfg


def compute_js_checksum(ppage_id: str, *, shift: int = 11) -> str:
    return caesar_shift(stripe_encode(_js_stringify({"id": ppage_id})), shift)


def compute_rv_timestamp(config: _StripeTokenConfig) -> str:
    payload = _js_stringify({"rvTs": config.rv_ts, "rv": config.rv, "sv": config.sv})
    return caesar_shift(stripe_encode(payload), config.shift)


def build_token_fields(*, ppage_id: str, config: _StripeTokenConfig) -> dict[str, str]:
    return {
        "js_checksum": compute_js_checksum(ppage_id, shift=config.shift),
        "rv_timestamp": compute_rv_timestamp(config),
    }


# ─────────────────────────────────────────────────────────────────────
# Form helpers (Stripe form-urlencoded flattening)
# ─────────────────────────────────────────────────────────────────────


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]", v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif value is None:
        return
    elif isinstance(value, bool):
        out.append((prefix, "true" if value else "false"))
    else:
        out.append((prefix, str(value)))


def to_form(data: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        _flatten(k, v, out)
    return out


def _stripe_guid() -> str:
    return f"{uuid.uuid4()}{uuid.uuid4().hex[:10]}"


# ─────────────────────────────────────────────────────────────────────
# UPI response mining
# ─────────────────────────────────────────────────────────────────────


def _find_matches(value: Any, *, source: str, path: str = "$") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}"
            if any(
                term in k.lower()
                for term in ("qr", "upi", "intent", "collect", "vpa",
                             "next_action", "hosted_instructions", "image_url", "display_qr")
            ):
                out.append({"source": source, "path": p, "kind": "key", "key": k, "value": v})
            out.extend(_find_matches(v, source=source, path=p))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            out.extend(_find_matches(item, source=source, path=f"{path}[{i}]"))
    return out


def _find_upi_uri(matches: list[dict[str, Any]]) -> str | None:
    for match in matches:
        value = match.get("value")
        if isinstance(value, str) and value.lower().startswith("upi://"):
            return value
    return None


def _find_qr_image_url(matches: list[dict[str, Any]]) -> str | None:
    for match in matches:
        value = match.get("value")
        path = str(match.get("path") or "").lower()
        if (
            isinstance(value, str)
            and value.startswith("https://")
            and "qr" in path
            and (value.endswith(".png") or value.endswith(".svg") or "qr" in value.lower())
        ):
            return value
    return None


def _find_qr_expires_at(matches: list[dict[str, Any]]) -> int | None:
    for match in matches:
        value = match.get("value")
        if not isinstance(value, dict):
            continue
        expires_at = value.get("expires_at")
        if (
            isinstance(expires_at, int)
            and not isinstance(expires_at, bool)
            and expires_at > 0
            and ("image_url_png" in value or "image_url_svg" in value)
        ):
            return expires_at
    return None


def _find_hosted_instructions_url(matches: list[dict[str, Any]]) -> str | None:
    for match in matches:
        value = match.get("value")
        if isinstance(value, str) and value.startswith(INSTRUCTIONS_PREFIX):
            return value
    for match in matches:
        value = match.get("value")
        if not isinstance(value, dict):
            continue
        block = value.get("upi_handle_redirect_or_display_qr_code")
        if isinstance(block, dict):
            url = block.get("hosted_instructions_url")
            if isinstance(url, str) and url.startswith(INSTRUCTIONS_PREFIX):
                return url
        url = value.get("hosted_instructions_url")
        if isinstance(url, str) and url.startswith(INSTRUCTIONS_PREFIX):
            return url
    return None


class _PayloadMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.payload_message: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {key.lower(): value for key, value in attrs if value is not None}
        if values.get("id") == "payload":
            self.payload_message = values.get("data-message")


def _extract_hosted_instruction_upi_uri(html_text: str) -> str | None:
    parser = _PayloadMetaParser()
    parser.feed(html_text)
    message = parser.payload_message
    if not message:
        return None
    padded = message + ("=" * (-len(message) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:
        return None
    uri = payload.get("mobile_auth_url") if isinstance(payload, dict) else None
    return uri if isinstance(uri, str) and uri.startswith("upi:") else None


def _extract_amount(init_data: dict[str, Any]) -> int:
    elements_options = init_data.get("elements_options")
    if isinstance(elements_options, dict) and isinstance(elements_options.get("amount"), int):
        return elements_options["amount"]
    total_summary = init_data.get("total_summary")
    if isinstance(total_summary, dict):
        for key in ("due", "total"):
            value = total_summary.get(key)
            if isinstance(value, int):
                return value
    invoice = init_data.get("invoice")
    if isinstance(invoice, dict):
        for key in ("amount_due", "total"):
            value = invoice.get(key)
            if isinstance(value, int):
                return value
    value = init_data.get("amount_total")
    return value if isinstance(value, int) else 0


# ─────────────────────────────────────────────────────────────────────
# QR output — terminal + PNG/SVG, via the pure-Python qrcode package
# ─────────────────────────────────────────────────────────────────────
# The 'qrcode' package is 100% pure Python (zero C extensions), so it
# installs cleanly in Termux:  pip install qrcode


def _qr_matrix(data: bytes) -> list[list[bool]]:
    """QR module matrix (byte mode, EC level M) via the qrcode package."""
    if qrcode is None:
        raise RuntimeError(
            "The 'qrcode' package is required for QR output.\n"
            "Install it with:  pip install qrcode"
        )
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


    if r == 6 or c == 6:
        return False
    if (r <= 8 and c <= 8) or (r <= 8 and c >= size - 8) or (r >= size - 8 and c <= 8):
        return False
    return True


def qr_terminal(uri: str, log: LogFn = print) -> None:
    """Render a scannable QR in the terminal (Termux-friendly)."""
    try:
        if qrcode is not None:
            # preferred: the real qrcode lib (handles everything)
            from io import StringIO
            qr = qrcode.QRCode(border=2)
            qr.add_data(uri)
            qr.make(fit=True)
            buf = StringIO()
            qr.print_ascii(out=buf, invert=True)
            for line in buf.getvalue().splitlines():
                log(line)
            return
        matrix = _qr_matrix(uri.encode("utf-8"))
        size = len(matrix)
        quiet = 2
        for r in range(-quiet, size + quiet):
            line = []
            for c in range(-quiet, size + quiet):
                if 0 <= r < size and 0 <= c < size:
                    line.append("██" if matrix[r][c] else "  ")
                else:
                    line.append("  ")
            log("".join(line))
    except Exception as exc:  # noqa: BLE001 — QR display is best-effort
        log(dim(f"  (terminal QR unavailable: {exc} — use the link/PNG instead)"))


def _render_qr_png(payload: str, out_path: Path) -> None:
    if qrcode is not None:
        img = qrcode.make(payload)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return
    matrix = _qr_matrix(payload.encode("utf-8"))
    size = len(matrix)
    scale = 8
    quiet = 4
    dim_px = (size + quiet * 2) * scale
    # minimal valid PNG writer (pure python, zlib via stdlib)
    import zlib
    raw = bytearray()
    for r in range(-quiet, size + quiet):
        raw.append(0)  # filter none
        for c in range(-quiet, size + quiet):
            dark = 0 <= r < size and 0 <= c < size and matrix[r][c]
            px = b"\x00\x00\x00" if dark else b"\xff\xff\xff"
            for _ in range(scale):
                raw.extend(px)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (len(data).to_bytes(4, "big") + tag + data
                + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big"))

    ihdr = (dim_px).to_bytes(4, "big") + (dim_px).to_bytes(4, "big") + bytes(
        [8, 2, 0, 0, 0]
    )
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)


def _render_qr_svg(payload: str, out_path: Path) -> None:
    matrix = _qr_matrix(payload.encode("utf-8"))
    size = len(matrix)
    quiet = 4
    dim = (size + quiet * 2) * 8
    rects = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                rects.append(
                    f'<rect x="{(c + quiet) * 8}" y="{(r + quiet) * 8}" width="8" height="8"/>'
                )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" '
        f'viewBox="0 0 {dim} {dim}" shape-rendering="crispEdges">'
        f'<rect width="{dim}" height="{dim}" fill="white"/><g fill="black">'
        + "".join(rects) + "</g></svg>"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")


def _save_html_link_page(payment_link: str, upi_uri: str | None, out_path: Path) -> None:
    """Tiny offline page that shows the QR + link — open it in any browser."""
    qr_svg = ""
    try:
        import tempfile
        tmp_svg = Path(tempfile.gettempdir()) / f"upiqr_{int(time.time())}.svg"
        _render_qr_svg(upi_uri or payment_link, tmp_svg)
        qr_svg = tmp_svg.read_text(encoding="utf-8")
        tmp_svg.unlink(missing_ok=True)
    except Exception:
        qr_svg = ""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>UPI Payment</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
gap:1rem;padding:2rem;background:#0f172a;color:#e2e8f0}}
a{{color:#7dd3fc;word-break:break-all;text-align:center}}
.qr{{background:#fff;padding:12px;border-radius:12px}}
button{{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:.7rem 1.4rem;
font-size:1rem}}
</style></head><body>
<h2>Scan &amp; pay — ₹0 ChatGPT Plus mandate</h2>
<div class="qr">{qr_svg}</div>
<p><a href="{payment_link}">{payment_link}</a></p>
{f'<a href="{upi_uri}"><button>Open UPI app</button></a>' if upi_uri else ''}
<p>After paying, keep the script running — it auto-detects the approval.</p>
<script>function copy(){{navigator.clipboard.writeText("{payment_link}")}}</script>
</body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def _open_externally(target: str) -> bool:
    """Open a URL/file with the platform opener. Returns True on success."""
    try:
        if sys.platform == "linux" and "com.termux" in os.environ.get("PREFIX", "").lower():
            subprocess.Popen(["termux-open", target], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        if sys.platform == "linux":
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
    except Exception:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────
# Pipeline steps
# ─────────────────────────────────────────────────────────────────────


def _headers_common() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "Accept-Language": "en-IN,en;q=0.9",
    }


def get_account_email(sess: Any, *, access_token: str, log: LogFn = print) -> str:
    headers = {
        **_headers_common(),
        "Authorization": f"Bearer {access_token}",
        "Accept": "*/*",
    }
    try:
        resp = retry_call(
            lambda: sess.get(CHATGPT_ME_URL, headers=headers, timeout=30),
            label="me", log=log,
        )
        if resp.status_code == 200:
            email = resp.json().get("email")
            if isinstance(email, str) and "@" in email:
                return email
    except Exception:
        pass
    return "user@chatgpt.local"


def create_chatgpt_checkout(sess: Any, *, access_token: str, log: LogFn) -> dict[str, Any]:
    body = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": "IN", "currency": "INR"},
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": "custom",
    }
    headers = {
        **_headers_common(),
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/?promo_campaign=plus-1-month-free",
        "x-openai-target-path": "/backend-api/payments/checkout",
        "x-openai-target-route": "/backend-api/payments/checkout",
        "OAI-Language": "en-IN",
    }
    resp = retry_call(
        lambda: sess.post(CHATGPT_CHECKOUT_URL, headers=headers, json_body=body, timeout=30),
        label="checkout", log=log,
    )
    if resp.status_code != 200:
        raise UpiQrError(f"checkout HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    missing = [k for k in ("checkout_session_id", "publishable_key") if not data.get(k)]
    if missing:
        raise UpiQrError(f"checkout response missing {missing}: {data}")
    return data


def update_chatgpt_checkout(sess: Any, *, access_token: str, session_id: str, log: LogFn) -> dict[str, Any]:
    headers = {
        **_headers_common(),
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://chatgpt.com",
        "Referer": f"https://chatgpt.com/checkout/openai_llc/{session_id}",
    }
    payload = {
        "checkout_session_id": session_id,
        "processor_entity": "openai_llc",
        "plan_name": "chatgptplusplan",
        "price_interval": "month",
        "seat_quantity": 1,
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
    }
    resp = retry_call(
        lambda: sess.post(CHATGPT_UPDATE_URL, headers=headers, json_body=payload, timeout=30),
        label="checkout/update", log=log,
    )
    if resp.status_code != 200:
        raise UpiQrError(f"checkout/update HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def stripe_init(sess: Any, *, session_id: str, publishable_key: str, stripe_js_id: str, log: LogFn) -> dict[str, Any]:
    form = to_form({
        "browser_locale": "en-IN",
        "browser_timezone": "Asia/Kolkata",
        "elements_session_client": {
            "client_betas": [
                "custom_checkout_server_updates_1",
                "custom_checkout_manual_approval_1",
            ],
            "elements_init_source": "custom_checkout",
            "referrer_host": "chatgpt.com",
            "stripe_js_id": stripe_js_id,
            "locale": "en",
            "is_aggregation_expected": "false",
        },
        "elements_options_client": {
            "saved_payment_method": {"enable_save": "auto", "enable_redisplay": "auto"},
        },
        "key": publishable_key,
        "_stripe_version": STRIPE_VERSION,
    })
    headers = {
        **_headers_common(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
    }
    resp = retry_call(
        lambda: sess.post(STRIPE_INIT_URL.format(id=session_id), headers=headers, data=form, timeout=30),
        label="stripe init", log=log,
    )
    if resp.status_code != 200:
        raise UpiQrError(f"stripe init HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("init_checksum") or not data.get("config_id"):
        raise UpiQrError(f"stripe init missing init_checksum/config_id: keys={list(data)[:20]}")
    return data


def stripe_elements_session(
    sess: Any, *, session_id: str, publishable_key: str, stripe_js_id: str,
    amount: int, log: LogFn,
) -> dict[str, Any]:
    params = {
        "client_betas[0]": "custom_checkout_server_updates_1",
        "client_betas[1]": "custom_checkout_manual_approval_1",
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": str(amount),
        "deferred_intent[currency]": "inr",
        "deferred_intent[setup_future_usage]": "off_session",
        "deferred_intent[payment_method_types][0]": "card",
        "deferred_intent[payment_method_types][1]": "link",
        "deferred_intent[payment_method_types][2]": "upi",
        "currency": "inr",
        "key": publishable_key,
        "_stripe_version": STRIPE_VERSION,
        "elements_init_source": "custom_checkout",
        "referrer_host": "chatgpt.com",
        "stripe_js_id": stripe_js_id,
        "locale": "en",
        "type": "deferred_intent",
        "checkout_session_id": session_id,
    }
    headers = {
        **_headers_common(),
        "Accept": "application/json",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
    }
    resp = retry_call(
        lambda: sess.get(STRIPE_ELEMENTS_URL, headers=headers, params=params, timeout=30),
        label="elements", log=log,
    )
    if resp.status_code != 200:
        raise UpiQrError(f"elements/sessions HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("session_id"):
        raise UpiQrError(f"elements/sessions missing session_id: keys={list(data)[:20]}")
    return data


def stripe_confirm_upi(
    sess: Any, *, session_id: str, publishable_key: str, stripe_js_id: str,
    init_data: dict[str, Any], elements_data: dict[str, Any],
    profile: dict[str, str], email: str, amount: int, vpa: str | None,
    token_config: _StripeTokenConfig | None, log: LogFn,
) -> dict[str, Any]:
    elements_session_id = elements_data.get("session_id")
    elements_session_config_id = elements_data.get("config_id") or ""
    init_config_id = init_data.get("config_id") or ""
    ppage_id = init_data.get("id") or ""
    init_checksum = init_data["init_checksum"]

    if token_config is not None:
        tokens = build_token_fields(ppage_id=ppage_id, config=token_config)
        js_checksum = tokens["js_checksum"]
        rv_timestamp = tokens["rv_timestamp"]
    else:
        js_checksum = None
        rv_timestamp = None

    client_attribution_metadata = {
        "checkout_config_id": init_config_id,
        "checkout_session_id": session_id,
        "client_session_id": stripe_js_id,
        "elements_session_config_id": elements_session_config_id,
        "elements_session_id": elements_session_id,
        "merchant_integration_additional_elements": ["expressCheckout", "payment", "address"],
        "merchant_integration_source": "checkout",
        "merchant_integration_subtype": "payment-element",
        "merchant_integration_version": "custom",
        "payment_intent_creation_flow": "deferred",
        "payment_method_selection_flow": "merchant_specified",
    }
    pmd_client_attribution = dict(client_attribution_metadata)
    pmd_client_attribution["merchant_integration_source"] = "elements"
    pmd_client_attribution["merchant_integration_version"] = "2021"

    upi_payload: dict[str, Any] = {"vpa": vpa} if vpa else {"flow": "qr_code"}

    form = to_form({
        "_stripe_version": STRIPE_VERSION,
        "client_attribution_metadata": client_attribution_metadata,
        "elements_options_client": {
            "saved_payment_method": {"enable_redisplay": "auto", "enable_save": "auto"},
        },
        "elements_session_client": {
            "client_betas": [
                "custom_checkout_server_updates_1", "custom_checkout_manual_approval_1",
            ],
            "elements_init_source": "custom_checkout",
            "is_aggregation_expected": "false",
            "locale": "en",
            "referrer_host": "chatgpt.com",
            "session_id": elements_session_id,
            "stripe_js_id": stripe_js_id,
        },
        "expected_amount": amount,
        "expected_payment_method_type": "upi",
        "guid": _stripe_guid(),
        "init_checksum": init_checksum,
        "js_checksum": js_checksum,
        "rv_timestamp": rv_timestamp,
        "passive_captcha_ekey": None,
        "passive_captcha_token": None,
        "key": publishable_key,
        "muid": _stripe_guid(),
        "sid": _stripe_guid(),
        "payment_method_data": {
            "billing_details": {
                "address": {
                    "city": profile["city"],
                    "country": "IN",
                    "line1": profile["address_line1"],
                    "postal_code": profile["postal_code"],
                    "state": profile["state"],
                },
                "email": email,
                "name": profile["name"],
            },
            "client_attribution_metadata": pmd_client_attribution,
            "payment_user_agent": (
                "stripe.js/e5ebd5e1e6; stripe-js-v3/e5ebd5e1e6; "
                "payment-element; deferred-intent"
            ),
            "referrer": "https://chatgpt.com",
            "time_on_page": int(time.time() * 1000) % 100000,
            "type": "upi",
            "upi": upi_payload,
        },
        "return_url": f"https://checkout.stripe.com/c/pay/{session_id}",
        "version": "e5ebd5e1e6",
    })
    headers = {
        **_headers_common(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
    }
    resp = retry_call(
        lambda: sess.post(STRIPE_CONFIRM_URL.format(id=session_id), headers=headers, data=form, timeout=30),
        label="confirm", log=log,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": resp.text[:1000]}
    return {
        "http_status": resp.status_code,
        "ok": resp.status_code == 200,
        "data": data if resp.status_code == 200 else None,
        "error": (data.get("error") if isinstance(data, dict) else None),
    }


def stripe_payment_page_refresh(
    sess: Any, *, session_id: str, publishable_key: str, stripe_js_id: str,
    elements_data: dict[str, Any], log: LogFn,
) -> dict[str, Any]:
    params = to_form({
        "elements_session_client": {
            "client_betas": [
                "custom_checkout_server_updates_1", "custom_checkout_manual_approval_1",
            ],
            "elements_init_source": "custom_checkout",
            "referrer_host": "chatgpt.com",
            "stripe_js_id": stripe_js_id,
            "locale": "en",
            "is_aggregation_expected": "false",
            "session_id": elements_data.get("session_id") or "",
        },
        "elements_options_client": {
            "saved_payment_method": {"enable_save": "auto", "enable_redisplay": "auto"},
        },
        "key": publishable_key,
        "_stripe_version": STRIPE_VERSION,
    })
    headers = {
        **_headers_common(),
        "Accept": "application/json",
        "Origin": "https://js.stripe.com",
        "Referer": "https://js.stripe.com/",
    }
    resp = retry_call(
        lambda: sess.get(STRIPE_PAGE_URL.format(id=session_id), headers=headers, params=params, timeout=30),
        label="page refresh", log=log,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": resp.text[:1000]}
    return {
        "http_status": resp.status_code,
        "ok": resp.status_code == 200,
        "data": data if resp.status_code == 200 else None,
    }


def chatgpt_approve(
    sess: Any, *, access_token: str, session_id: str, log: LogFn,
) -> dict[str, Any]:
    body = {"checkout_session_id": session_id, "processor_entity": "openai_llc"}
    headers = {
        **_headers_common(),
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Origin": "https://chatgpt.com",
        "Referer": f"https://chatgpt.com/checkout/openai_llc/{session_id}",
        "x-openai-target-path": "/backend-api/payments/checkout/approve",
        "x-openai-target-route": "/backend-api/payments/checkout/approve",
        "OAI-Language": "en-IN",
    }
    resp = retry_call(
        lambda: sess.post(CHATGPT_APPROVE_URL, headers=headers, json_body=body, timeout=30),
        label="approve", log=log,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": resp.text[:1000]}
    result = data.get("result") if isinstance(data, dict) else None
    return {
        "http_status": resp.status_code,
        "ok": resp.status_code == 200 and result == "approved",
        "result": result,
        "data": data if resp.status_code == 200 else None,
    }


def check_plan_plus(sess: Any, *, access_token: str, log: LogFn) -> bool:
    """Verify the account actually has Plus after approval."""
    headers = {
        **_headers_common(),
        "Authorization": f"Bearer {access_token}",
        "Accept": "*/*",
    }
    try:
        resp = sess.get(CHATGPT_SESSION_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            text = resp.text.lower()
            return '"plan_type": "plus"' in text or '"plan_type":"plus"' in text or "chatgptplusplan" in text
    except Exception as exc:  # noqa: BLE001
        log(f"  ⚠ plan check failed: {type(exc).__name__}: {str(exc)[:120]}")
    return False


# ─────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────


class UpiQrError(Exception):
    """Fatal flow error."""


def run_upi_qr(
    *,
    access_token: str,
    vpa: str | None = None,
    out_dir: Path = Path("qr_codes"),
    wait_for_payment: bool = True,
    approve_polls: int = 100,
    approve_delay: float = 5.0,
    use_cache: bool = True,
    auto_open: bool = True,
    log: LogFn = print,
) -> dict[str, Any]:
    """Full pipeline → payment link + QR + auto-detect payment.

    Returns a result dict; never raises (fatal errors land in `error`).
    """
    started = time.monotonic()
    profile = random_india_profile()
    out_dir.mkdir(parents=True, exist_ok=True)
    token_short = short(access_token, 10, 6)

    result: dict[str, Any] = {
        "ok": False,
        "access_token": token_short,
        "profile": profile["name"],
        "payment_link": None,
        "upi_uri": None,
        "qr_path": None,
        "html_path": None,
        "amount": None,
        "checkout_session": None,
        "approved": False,
        "already_paid": False,
        "plan_plus": False,
        "error": None,
        "elapsed_seconds": None,
    }

    def _fail(error: str) -> dict[str, Any]:
        result["error"] = error
        result["elapsed_seconds"] = round(time.monotonic() - started, 1)
        log_step("done", "FAILED", "fail", error)
        return result

    log("")
    log(bold(cyan("═" * 72)))
    log(bold(cyan("  UPI QR Generator — standalone · no proxy · Termux-ready")))
    log(bold(cyan("═" * 72)))
    log(f"  token    : {dim(token_short)}")
    log(f"  vpa      : {vpa or dim('(none — QR flow)')}")
    log(f"  billing  : {bold(profile['name'])} | {profile['city']}, {profile['state']} | {profile['postal_code']}")
    log(f"  proxy    : {green('NONE (direct from your IP)')}")
    log(f"  http     : {'httpx' if httpx is not None else yellow('stdlib urllib (install httpx for keep-alive)')}")
    log(bold(cyan("═" * 72)))

    sess = make_session()
    try:
        # ── Step 1 — checkout ──
        log_step("1/6", "creating ChatGPT checkout session", "start")
        checkout = create_chatgpt_checkout(sess, access_token=access_token, log=log)
        session_id = checkout["checkout_session_id"]
        publishable_key = checkout["publishable_key"]
        result["checkout_session"] = short(session_id)
        log_step("1/6", "checkout", "ok", f"cs={short(session_id)}")

        # ── Step 2 — Stripe init ──
        log_step("2/6", "stripe init", "start")
        stripe_js_id = str(uuid.uuid4())
        init_data = stripe_init(
            sess, session_id=session_id, publishable_key=publishable_key,
            stripe_js_id=stripe_js_id, log=log,
        )
        amount = _extract_amount(init_data)
        result["amount"] = amount
        log_step("2/6", "stripe init", "ok",
                 f"amount={amount} ppage={short(str(init_data.get('id') or ''))}")

        # ── Step 2b — tax_update (re-apply promo; the site's stage order) ──
        try:
            update_chatgpt_checkout(sess, access_token=access_token, session_id=session_id, log=log)
            log_step("2/6", "tax_update (promo re-apply)", "ok")
        except Exception as exc:  # noqa: BLE001
            log_step("2/6", "tax_update (promo re-apply)", "warn",
                     f"{type(exc).__name__}: {str(exc)[:120]}")

        # ── account email ──
        email = get_account_email(sess, access_token=access_token, log=log)
        log_step("acct", "account email", "ok", email)

        if amount > 0:
            log_step("upi", "no free offer", "warn",
                     f"amount={amount} paise (₹{amount / 100:.2f}) — the ₹0 promo is NOT "
                     "active on this account/IP; the QR would charge real money.")
            result["error"] = f"no free offer (amount={amount})"

        # ── Step 3 — elements session ──
        log_step("3/6", "stripe elements session", "start")
        elements_data = stripe_elements_session(
            sess, session_id=session_id, publishable_key=publishable_key,
            stripe_js_id=stripe_js_id, amount=amount, log=log,
        )
        log_step("3/6", "stripe elements session", "ok",
                 f"session={short(str(elements_data.get('session_id') or ''))}")

        # ── Step 4 — Stripe token config (js_checksum engine) ──
        log_step("4/6", "stripe token config", "start")
        token_config: _StripeTokenConfig | None = None
        try:
            token_config = extract_config_live(sess, log=log, use_cache=use_cache)
        except Exception as exc:  # noqa: BLE001
            log_step("4/6", "stripe token config", "warn",
                     f"{type(exc).__name__}: {str(exc)[:140]} — confirm will run without "
                     "js_checksum (Stripe may reject)")

        # ── Step 5 — confirm (UPI) + page refresh (materialize the QR) ──
        log_step("5/6", "stripe confirm (UPI)", "start")
        confirm = stripe_confirm_upi(
            sess,
            session_id=session_id,
            publishable_key=publishable_key,
            stripe_js_id=stripe_js_id,
            init_data=init_data,
            elements_data=elements_data,
            profile=profile,
            email=email,
            amount=amount,
            vpa=vpa,
            token_config=token_config,
            log=log,
        )
        if not confirm["ok"]:
            err = confirm.get("error") or {}
            code = err.get("code") or err.get("type") or ""
            return _fail(
                f"stripe confirm rejected (HTTP {confirm['http_status']}) {code}: "
                f"{json.dumps(err, default=str)[:300]}"
            )
        log_step("5/6", "stripe confirm (UPI)", "ok")

        refresh = stripe_payment_page_refresh(
            sess, session_id=session_id, publishable_key=publishable_key,
            stripe_js_id=stripe_js_id, elements_data=elements_data, log=log,
        )
        if refresh["ok"]:
            log_step("5/6", "payment page refresh", "ok")
        else:
            log_step("5/6", "payment page refresh", "warn", f"HTTP {refresh['http_status']}")

        # ── Aggregate QR candidates ──
        matches: list[dict[str, Any]] = []
        for source, payload in (
            ("chatgpt_checkout", checkout),
            ("stripe_init", init_data),
            ("stripe_elements", elements_data),
            ("stripe_confirm", confirm.get("data") or {}),
            ("stripe_refresh", refresh.get("data") or {}),
        ):
            matches.extend(_find_matches(payload, source=source))

        upi_uri = _find_upi_uri(matches)
        qr_image_url = _find_qr_image_url(matches)
        qr_expires_at = _find_qr_expires_at(matches)
        payment_link = _find_hosted_instructions_url(matches)

        result["upi_uri"] = upi_uri
        result["payment_link"] = payment_link

        stamp = time.strftime("%Y%m%d-%H%M%S")

        # QR payload for terminal/files: prefer the upi:// URI, else the link.
        qr_payload = upi_uri or payment_link
        if qr_payload is None and qr_image_url:
            # download Stripe's QR image; the HTML variant hides the upi:// URI
            ext = ".svg" if qr_image_url.lower().endswith(".svg") else ".png"
            target = out_dir / f"upi_qr_{stamp}{ext}"
            dl = _download_qr_image(sess, url=qr_image_url, out_path=target, log=log)
            if dl.get("rendered") and dl.get("path"):
                result["qr_path"] = dl["path"]
                if dl.get("source") == "hosted_instructions_html":
                    result["upi_uri"] = upi_uri = dl.get("upi_uri")
                    qr_payload = upi_uri
            else:
                log_step("qr", "stripe QR image download failed", "warn", dl.get("reason", ""))

        if qr_payload is None:
            return _fail(
                "no UPI QR / payment link found in any response — the account may "
                "already be on a paid plan or the ₹0 offer is gone"
            )

        # ── THE OUTPUTS (link first, like the website's Copy Link) ──
        log("")
        log(bold(green("  ── PAYMENT LINK (open in any browser — shows the QR) ──")))
        log(f"  {payment_link or qr_payload}")
        log("")
        if upi_uri:
            log(bold(green("  ── UPI INTENT URI ──")))
            log(f"  {upi_uri}")
            log("")

        # terminal QR
        log(bold("  Terminal QR (scan with any UPI app):"))
        log("")
        qr_terminal(qr_payload, log=log)
        log("")

        # files: html page (link + qr), png, svg
        html_path = out_dir / f"upi_payment_{stamp}.html"
        try:
            _save_html_link_page(payment_link or qr_payload, upi_uri, html_path)
            result["html_path"] = str(html_path)
            log_step("out", "offline payment page", "ok", str(html_path))
        except Exception as exc:  # noqa: BLE001
            log_step("out", "offline payment page", "warn", str(exc)[:120])

        png_path = out_dir / f"upi_qr_{stamp}.png"
        try:
            _render_qr_png(qr_payload, png_path)
            result["qr_path"] = str(png_path)
            log_step("out", "QR image (png)", "ok", str(png_path))
        except Exception as exc:  # noqa: BLE001
            log_step("out", "QR image (png)", "warn", str(exc)[:120])

        try:
            _render_qr_svg(qr_payload, out_dir / f"upi_qr_{stamp}.svg")
            log_step("out", "QR image (svg)", "ok", str(out_dir / f'upi_qr_{stamp}.svg'))
        except Exception as exc:  # noqa: BLE001
            log_step("out", "QR image (svg)", "warn", str(exc)[:120])

        if qr_expires_at:
            log(f"  {dim('QR expires at:')} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(qr_expires_at))}")

        if auto_open:
            opened = _open_externally(payment_link or str(html_path))
            if opened:
                log_step("open", "opened in browser/upi app", "ok")

        # ── Step 6 — auto-detect payment (approve loop) ──
        if not wait_for_payment:
            result["ok"] = True
            result["elapsed_seconds"] = round(time.monotonic() - started, 1)
            log("")
            log(green(bold("  ✔ Done — scan the QR / open the link, pay, and Plus activates.")))
            log(dim("     (Rerun with --wait or without --no-wait to auto-detect the payment.)"))
            return result

        log("")
        log_step("6/6", "auto-detect payment", "start",
                 f"polling /approve every {approve_delay:g}s (max {approve_polls} polls) — "
                 "scan & pay in your UPI app now")

        approved = False
        already_paid = False
        consecutive_errors = 0
        for i in range(1, approve_polls + 1):
            try:
                attempt = chatgpt_approve(
                    sess, access_token=access_token, session_id=session_id, log=log,
                )
                consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    return _fail(f"approve loop lost network: {type(exc).__name__}: {str(exc)[:200]}")
                log(f"  ⚠ poll {i} network error ({type(exc).__name__}) — retrying")
                time.sleep(approve_delay)
                continue

            body_text = json.dumps(attempt.get("data") or attempt.get("result") or "", default=str)
            if attempt["ok"]:
                approved = True
                log(f"  ✓ poll {i}: APPROVED")
                break
            if "already paid" in body_text.lower():
                already_paid = True
                log(f"  ✓ poll {i}: account already on a paid plan")
                break
            if i == 1 or i % 12 == 0:
                log(f"  · poll {i}/{approve_polls}: waiting for your payment…")

            # QR expiry re-mint: if we know the expiry and it passed, refresh the
            # payment page — Stripe returns a fresh QR in the refresh response.
            if (
                qr_expires_at
                and time.time() > qr_expires_at + 5
                and (i % 4 == 0)
            ):
                try:
                    log_step("qr", "QR expired — re-minting", "warn")
                    fresh = stripe_payment_page_refresh(
                        sess, session_id=session_id, publishable_key=publishable_key,
                        stripe_js_id=stripe_js_id, elements_data=elements_data, log=log,
                    )
                    if fresh["ok"]:
                        fm = _find_matches(fresh["data"] or {}, source="refresh_remint")
                        new_uri = _find_upi_uri(fm) or upi_uri
                        new_link = _find_hosted_instructions_url(fm) or payment_link
                        if new_uri and new_uri != upi_uri:
                            upi_uri = new_uri
                            result["upi_uri"] = new_uri
                            qr_payload = new_uri
                            png_path = out_dir / f"upi_qr_{stamp}.png"
                            _render_qr_png(qr_payload, png_path)
                            log_step("qr", "fresh QR rendered", "ok", str(png_path))
                            qr_terminal(qr_payload, log=log)
                        if new_link and new_link != payment_link:
                            payment_link = new_link
                            result["payment_link"] = new_link
                            log_step("link", "new payment link", "ok", new_link)
                    new_expiry = _find_qr_expires_at(fm)
                    if new_expiry:
                        qr_expires_at = new_expiry
                except Exception as exc:  # noqa: BLE001
                    log_step("qr", "re-mint failed", "warn", str(exc)[:140])

            if i < approve_polls:
                time.sleep(approve_delay)

        if already_paid:
            result["already_paid"] = True
            result["ok"] = True
        elif not approved:
            result["error"] = f"payment not detected after {approve_polls} polls"
            log_step("6/6", "auto-detect", "fail", result["error"])
            return result
        else:
            result["approved"] = True

        # post-approval plan check
        plus = check_plan_plus(sess, access_token=access_token, log=log)
        result["plan_plus"] = plus
        result["ok"] = True
        result["elapsed_seconds"] = round(time.monotonic() - started, 1)
        log("")
        if plus:
            log(green(bold("  ✔ PAYMENT DETECTED + APPROVED — plan check: PLUS IS LIVE ✅")))
        else:
            log(green(bold("  ✔ APPROVED — Plus should be active (plan check inconclusive).")))
        log(bold(cyan("═" * 72)))
        return result

    except UpiQrError as exc:
        return _fail(str(exc))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        return _fail(f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        close = getattr(sess, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _download_qr_image(sess: Any, *, url: str, out_path: Path, log: LogFn) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = retry_call(lambda: sess.get(url, timeout=30), label="qr image", log=log)
    except Exception as exc:  # noqa: BLE001
        return {"rendered": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if resp.status_code != 200:
        return {"rendered": False, "reason": f"HTTP {resp.status_code}"}
    content_type = str(resp.headers.get("content-type") or "").lower()
    content = resp.content
    if "text/html" in content_type or content.lstrip().lower().startswith(b"<html"):
        html_text = content.decode("utf-8", errors="replace")
        upi_uri = _extract_hosted_instruction_upi_uri(html_text)
        if not upi_uri:
            return {"rendered": False, "reason": "hosted instructions HTML had no mobile_auth_url"}
        _render_qr_png(upi_uri, out_path)
        return {"rendered": True, "path": str(out_path), "source": "hosted_instructions_html",
                "upi_uri": upi_uri}
    out_path.write_bytes(content)
    return {"rendered": True, "path": str(out_path), "source": "stripe_image"}


# ─────────────────────────────────────────────────────────────────────
# Self-test (offline) — verifies the crypto/token/QR machinery on device
# ─────────────────────────────────────────────────────────────────────


def selftest() -> int:
    ok = 0
    fails: list[str] = []

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        if cond:
            ok += 1
            print(f"  {green('✓')} {name}")
        else:
            fails.append(name)
            print(f"  {red('✗')} {name}")

    print(bold("1. Caesar shift (Stripe obfuscation primitive)"))
    check("round-trip", caesar_shift(caesar_shift("Hello, World! {id:123} ~", 11), -11) == "Hello, World! {id:123} ~")
    check("space→+ @ n=11", caesar_shift(" ", 11) == "+")

    print(bold("2. stripe_encode (xor-5 + base64 + urlencode)"))
    orig = '{"id":"cs_test_123"}'
    xored = base64.b64decode(urllib.parse.unquote(stripe_encode(orig)).encode()).decode("latin1")
    recovered = "".join(chr(ord(c) ^ 5) for c in xored)
    check("payload survives", recovered.startswith(orig))
    check("pad 1..3 spaces", 1 <= len(recovered) - len(orig) <= 3 and set(recovered[len(orig):]) == {" "})

    print(bold("3. token fields"))
    cfg = _StripeTokenConfig("h", 11, "2024-01-01 00:00:00 -0000", "e5ebd5e1e6xyz", "saltvalue")
    tf = build_token_fields(ppage_id="ppage_abc", config=cfg)
    check("js_checksum present", len(tf.get("js_checksum", "")) > 10)
    check("rv_timestamp present", len(tf.get("rv_timestamp", "")) > 20)

    print(bold("4. form flattening (Stripe bracket convention)"))
    form = dict(to_form({"a": {"b": {"c": "1"}}, "list": ["x", "y"], "n": None, "flag": True}))
    check("nested", form.get("a[b][c]") == "1")
    check("list", form.get("list[0]") == "x" and form.get("list[1]") == "y")
    check("null skipped / bool", "n" not in form and form.get("flag") == "true")

    print(bold("5. amount extraction"))
    check("elements_options", _extract_amount({"elements_options": {"amount": 0}}) == 0)
    check("total_summary", _extract_amount({"total_summary": {"due": 1999}}) == 1999)
    check("invoice", _extract_amount({"invoice": {"amount_due": 0}}) == 0)

    print(bold("6. hosted-instructions meta parser"))
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps({"mobile_auth_url": "upi://pay?pa=x@y&am=0.00&cu=INR"}).encode()
    ).decode().rstrip("=")
    uri = _extract_hosted_instruction_upi_uri(f'<meta id="payload" data-message="{payload_b64}">')
    check("mobile_auth_url extracted", uri == "upi://pay?pa=x@y&am=0.00&cu=INR")

    print(bold("7. response mining (payment link / QR / expiry)"))
    mm = _find_matches({"next_action": {"upi_handle_redirect_or_display_qr_code": {
        "hosted_instructions_url": "https://payments.stripe.com/upi/instructions/xyz",
        "qr_code": {"expires_at": 1770000000, "image_url_png": "https://q.stripe.com/qr.png"},
    }}}, source="t")
    check("payment link", _find_hosted_instructions_url(mm) == "https://payments.stripe.com/upi/instructions/xyz")
    check("qr image url", _find_qr_image_url(mm) == "https://q.stripe.com/qr.png")
    check("qr expiry", _find_qr_expires_at(mm) == 1770000000)
    check("upi uri", _find_upi_uri(_find_matches({"a": {"upi_uri": "upi://pay?pa=x@y"}}, source="t")) == "upi://pay?pa=x@y")

    print(bold("8. webpack pattern matchers"))
    synth = ('var u=function(e,n){for(var t=[],a=0;a<e.length;a++)t.push(String.fromCharCode('
             '(e.charCodeAt(a)-32+n)%95+32));return t.join("")};')
    check("caesar pattern", bool(_CAESAR_FN_RE.search(synth)))
    m2 = _JS_CHECKSUM_RE.search("js_checksum: v((0,P.l)(JSON.stringify({id:e})),11)")
    check("js_checksum pattern", bool(m2) and m2.group("shift") == "11")
    m3 = _RV_TIMESTAMP_RE.search("rv_timestamp: v((0,C.sK)(JSON.stringify({rvTs:C.dG,rv:C.QJ,sv:C.W})),11)")
    check("rv_timestamp pattern", bool(m3) and m3.group("keys") == "rvTs:C.dG,rv:C.QJ,sv:C.W")

    print(bold("9. terminal QR"))
    import io
    buf = io.StringIO()
    try:
        qr_terminal("upi://pay?pa=test@upi&am=0.00&cu=INR&tn=Selftest", log=buf.write)
        out = buf.getvalue()
        check("renders blocks", ("█" in out or "▀" in out) and len(out) > 100)
    except Exception as exc:  # noqa: BLE001
        check(f"renders blocks (raised {exc})", False)

    print(bold("10. PNG writer"))
    import tempfile
    tmp = Path(tempfile.gettempdir()) / f"upi_selftest_{int(time.time())}.png"
    try:
        _render_qr_png("upi://pay?pa=test@upi", tmp)
        data = tmp.read_bytes()
        check("valid PNG magic", data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 300)
        tmp.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        check(f"png written (raised {exc})", False)

    print(bold("11. HTML payment page"))
    tmp = Path(tempfile.gettempdir()) / f"upi_selftest_{int(time.time())}.html"
    try:
        _save_html_link_page("https://payments.stripe.com/upi/instructions/abc", "upi://pay?pa=a@b", tmp)
        content = tmp.read_text(encoding="utf-8")
        check("contains link + qr", "payments.stripe.com" in content and "<svg" in content)
        tmp.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        check(f"html written (raised {exc})", False)

    print(bold("12. HTTP backend"))
    be = make_session()
    check(f"backend = {'httpx' if httpx is not None else 'urllib'}", be is not None)
    close = getattr(be, "close", None)
    if callable(close):
        close()

    print()
    if fails:
        print(red(f"SELFTEST: {len(fails)} failed → {fails}"))
        return 1
    print(green(bold(f"SELFTEST: all {ok} checks passed ✔")))
    return 0


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


def _read_tokens(path: Path) -> list[str]:
    tokens = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t.startswith("eyJ") and len(t) > 50:
            tokens.append(t)
    return tokens


def _interactive_token() -> str:
    print()
    print(bold("Getting your ChatGPT access token:"))
    print("  1. Open chatgpt.com in your browser (logged in)")
    print("  2. F12 → Network tab → send any message in chat")
    print("  3. Click any backend-api/ request")
    print("  4. Under Request Headers find 'Authorization:'")
    print("  5. Copy everything after 'Bearer ' (starts with 'eyJ')")
    print()
    try:
        return input("Paste access token: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)


def _interactive_vpa() -> str | None:
    try:
        vpa = input("UPI VPA (e.g. name@oksbi) — blank for QR flow: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    return vpa or None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="upi_qr_standalone",
        description=(
            "₹0 UPI Autopay QR for ChatGPT Plus — standalone, no proxy, "
            "Termux-ready. Gives you the payment link + QR and auto-detects "
            "when you pay."
        ),
    )
    p.add_argument("--token", help="ChatGPT access token (starts with 'eyJ')")
    p.add_argument("--tokens-file", help="file with one access token per line (bulk)")
    p.add_argument("--vpa", help="your UPI VPA (name@bank); omit for QR-code flow")
    p.add_argument("--out", default="qr_codes", help="output directory (default: ./qr_codes)")
    p.add_argument("--wait", dest="wait", action="store_true", default=True,
                   help="auto-detect the payment after you scan (default)")
    p.add_argument("--no-wait", dest="wait", action="store_false",
                   help="generate link/QR and exit without polling")
    p.add_argument("--polls", type=int, default=100,
                   help="max approve polls when waiting (default 100 = ~8 min @5s)")
    p.add_argument("--delay", type=float, default=5.0, help="seconds between polls (default 5)")
    p.add_argument("--no-open", action="store_true", help="don't auto-open the payment link")
    p.add_argument("--no-cache", action="store_true", help="don't cache Stripe JS bundles")
    p.add_argument("--selftest", action="store_true",
                   help="run offline verification of all machinery and exit")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    tokens: list[str] = []
    if args.token:
        tokens.append(args.token.strip())
    if args.tokens_file:
        tokens.extend(_read_tokens(Path(args.tokens_file)))
    if not tokens:
        tokens.append(_interactive_token())

    vpa = args.vpa
    if len(tokens) == 1 and not vpa and sys.stdin.isatty():
        vpa = _interactive_vpa()

    out_dir = Path(args.out)
    rc = 0
    for index, token in enumerate(tokens, start=1):
        if len(tokens) > 1:
            print()
            print(bold(cyan(f"── token {index}/{len(tokens)} " + "─" * 48)))
        try:
            result = run_upi_qr(
                access_token=token,
                vpa=vpa,
                out_dir=out_dir,
                wait_for_payment=args.wait,
                approve_polls=args.polls,
                approve_delay=args.delay,
                use_cache=not args.no_cache,
                auto_open=not args.no_open,
            )
        except KeyboardInterrupt:
            print("\ninterrupted")
            rc = 130
            break
        if not result.get("ok"):
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
upi_qr_standalone.py — Standalone, no-proxy rewrite of upi.vaultvip.pro
=======================================================================

upi.vaultvip.pro ("Vault × OpenAI — UPI QR Gen") is a web front-end over the
same pipeline as `gpt_signup_hybrid`'s web/upi_runner.py + pay_upi_http.py:

    stage checkout      → POST https://chatgpt.com/backend-api/payments/checkout
                          (plan chatgptplusplan, billing IN/INR, promo
                           plus-1-month-free, custom UI mode) → returns
                           checkout_session_id (cs_live_…) + Stripe publishable key
    stage stripe_init   → POST https://api.stripe.com/v1/payment_pages/{cs}/init
                          → returns init_checksum + config_id + payment page id
    stage tax_update    → POST https://chatgpt.com/backend-api/payments/checkout/update
                          (re-applies the ₹0 promo / tax fields)
    stage payment_method→ GET  https://api.stripe.com/v1/elements/sessions
                          (deferred intent, subscription, INR, UPI in method types)
    stage stripe_confirm→ POST https://api.stripe.com/v1/payment_pages/{cs}/confirm
                          with payment_method_data.type=upi and
                          upi.flow="qr_code" → Stripe returns next_action.
                          upi_handle_redirect_or_display_qr_code with
                          hosted_instructions_url + qr image urls + upi:// URI
    stage instructions  → GET  hosted_instructions_url HTML → <meta id="payload"
                          data-message="base64url"> → JSON {mobile_auth_url}
                          = the "upi://pay?…" string
    stage approve       → poll POST https://chatgpt.com/backend-api/payments/checkout/approve
                          until result=="approved" (after you scan & pay in a
                          UPI app) — this is what actually activates Plus.

The hosted site demands Indian rotating proxies because its operator runs it
from non-Indian IPs and because Stripe/OpenAI risk-score by IP. This script
does everything from YOUR machine — as an Indian user you are already on an
Indian IP, so no proxy is needed or used. Everything runs through curl_cffi
(Chrome TLS impersonation) exactly like the original, and the confirm step
computes Stripe's js_checksum/rv_timestamp anti-bot tokens by fetching and
parsing Stripe's own custom-checkout JS bundle — same as the original tool.

Result: a scannable UPI QR (PNG/SVG) + the hosted payment-instructions link,
plus an optional approve loop that waits until you pay.

Usage
-----
    # interactive (asks for the access token)
    python upi_qr_standalone.py

    # token on CLI (ChatGPT access token — the same "eyJ…" Bearer token that
    # upi.vaultvip.pro asks you to paste)
    python upi_qr_standalone.py --token "eyJhbGciOi..."

    # with your UPI VPA (intent flow, QR opens your exact UPI app) + approve
    python upi_qr_standalone.py --token "eyJ..." --vpa yourname@oksbi --wait

    # tokens from a file, one per line (bulk, like the site's bulk extractor)
    python upi_qr_standalone.py --tokens-file tokens.txt --out qr_codes/

Dependencies: pip install curl_cffi qrcode[pil]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import random
import re
import secrets
import string
import sys
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

try:
    from curl_cffi.requests import AsyncSession
except ImportError:  # pragma: no cover
    sys.exit(
        "Missing dependency: curl_cffi.\n"
        "Install with:  pip install curl_cffi qrcode[pil]"
    )

try:
    import qrcode  # type: ignore[import-untyped]
except ImportError:
    qrcode = None  # QR rendering falls back to Stripe's own QR image download


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
IMPERSONATE = "chrome145"

STRIPE_VERSION = (
    "2025-03-31.basil; checkout_server_update_beta=v1; "
    "checkout_manual_approval_preview=v1"
)

CHATGPT_CHECKOUT_URL = "https://chatgpt.com/backend-api/payments/checkout"
CHATGPT_UPDATE_URL = "https://chatgpt.com/backend-api/payments/checkout/update"
CHATGPT_APPROVE_URL = "https://chatgpt.com/backend-api/payments/checkout/approve"
STRIPE_INIT_URL = "https://api.stripe.com/v1/payment_pages/{id}/init"
STRIPE_PAGE_URL = "https://api.stripe.com/v1/payment_pages/{id}"
STRIPE_CONFIRM_URL = "https://api.stripe.com/v1/payment_pages/{id}/confirm"
STRIPE_ELEMENTS_URL = "https://api.stripe.com/v1/elements/sessions"

STRIPE_JS_ENTRY_URL = "https://js.stripe.com/v3/"

INSTRUCTIONS_PREFIX = "https://payments.stripe.com/upi/instructions/"

# The original runs stage-2 onward via an Indian proxy. Here: no proxy, ever.
PROXIES = None

LogFn = Callable[[str], None]


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
def blue(t: str) -> str:   return _c("34", t)
def cyan(t: str) -> str:   return _c("36", t)


def short(s: str, head: int = 14, tail: int = 8) -> str:
    if not s or len(s) <= head + tail + 1:
        return s
    return f"{s[:head]}…{s[-tail:]}"


def log_step(tag: str, label: str, status: str, detail: str = "", log: LogFn = print) -> None:
    icons = {"start": "▸", "ok": green("✓"), "fail": red("✗"), "warn": yellow("⚠"), "info": "·"}
    icon = icons.get(status, "·")
    color = {
        "ok": green, "fail": red, "warn": yellow,
    }.get(status, str)
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
    return "".join(chr((ord(c) - 32 + n) % 95 + 32) for c in s)


def stripe_encode(s: str) -> str:
    """Stripe module 9107 P.l(): xor-5 each byte, base64, urlencode.

    Quirk kept from the original: pad = 3 - len(s) % 3 (never re-modulo'd),
    so padding is always 1..3 spaces.
    """
    import urllib.parse

    pad = 3 - len(s) % 3
    padded = s + " " * pad
    xored = bytes(5 ^ ord(c) for c in padded)
    return urllib.parse.quote(
        base64.b64encode(xored).decode("ascii"),
        safe="-_.!~*'()",
    )


def _js_stringify(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# ---- bundle extraction patterns (anti-fragile: match the algorithm, not names) ----

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
        return (
            f"StripeTokenConfig(shift={self.shift}, rv={self.rv[:8]}…, "
            f"sv={self.sv[:8]}…)"
        )


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
    """Extract {sK, dG, QJ} from the constants module (webpack export map)."""
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
    """Parse Stripe's custom-checkout bundle and extract the token constants."""
    bundle_hash = hashlib.sha256(bundle_source.encode("utf-8")).hexdigest()

    if not _CAESAR_FN_RE.search(bundle_source):
        raise StripeTokenExtractError(
            "Caesar-shift function pattern not found — Stripe may have changed "
            "its obfuscation."
        )

    js_match = _JS_CHECKSUM_RE.search(bundle_source)
    if not js_match:
        raise StripeTokenExtractError(
            "js_checksum builder pattern not found — Stripe may have changed "
            "its payload structure."
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


async def fetch_bundles_live(
    sess: Any, *, log: LogFn, use_cache: bool = True
) -> tuple[str, str]:
    """Fetch Stripe's entry JS + fingerprinted custom-checkout chunk.

    1. GET https://js.stripe.com/v3/ (entry)
    2. Parse the webpack chunk-name / chunk-hash maps from the entry
    3. GET the fingerprinted custom-checkout-<hash>.js chunk

    Returns (cc_src, entry_src) — module 114 constants live in the entry.
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
    r_entry = await sess.get(
        STRIPE_JS_ENTRY_URL,
        headers={**common_headers, "Referer": "https://chatgpt.com/"},
        timeout=30,
        proxies=PROXIES,
    )
    if r_entry.status_code != 200:
        raise StripeTokenExtractError(
            f"entry HTTP {r_entry.status_code}: {(r_entry.text or '')[:200]}"
        )
    entry = r_entry.text or ""
    entry_hash = hashlib.sha256(entry.encode("utf-8")).hexdigest()

    cache_dir = Path.home() / ".cache" / "upi_qr_standalone" / "stripe_bundles" / entry_hash[:16]
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
            f"could not parse webpack chunk map (names={len(chunk_names)}, "
            f"hashes={len(chunk_hashes)})"
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
    r_cc = await sess.get(
        cc_url,
        headers={
            **common_headers,
            "Referer": "https://js.stripe.com/v3/",
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
        },
        timeout=60,
        proxies=PROXIES,
    )
    if r_cc.status_code != 200:
        raise StripeTokenExtractError(
            f"custom_checkout HTTP {r_cc.status_code}: {(r_cc.text or '')[:200]}"
        )
    cc_src = r_cc.text or ""

    if use_cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cc_cache.write_text(cc_src, encoding="utf-8")
            entry_cache.write_text(entry, encoding="utf-8")
        except OSError:
            pass

    return cc_src, entry


async def extract_config_live(sess: Any, *, log: LogFn, use_cache: bool = True) -> _StripeTokenConfig:
    try:
        cc_src, entry_src = await fetch_bundles_live(sess, log=log, use_cache=use_cache)
    except Exception as exc:
        log(f"  ⚠ stripe token config fetch failed: {type(exc).__name__}: {str(exc)[:140]}")
        raise
    cfg = extract_config(cc_src, fallback_sources=[entry_src] if entry_src else [])
    log(f"  ✓ token config: shift={cfg.shift} rv={short(cfg.rv, 8, 4)} sv={short(cfg.sv, 8, 4)}")
    return cfg


def compute_js_checksum(ppage_id: str, *, shift: int = 11) -> str:
    payload = _js_stringify({"id": ppage_id})
    return caesar_shift(stripe_encode(payload), shift)


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
# UPI response mining (find QR / instructions URL in any response)
# ─────────────────────────────────────────────────────────────────────


def _find_matches(value: Any, *, source: str, path: str = "$") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}"
            if any(term in k.lower() for term in ("qr", "upi", "intent", "collect", "vpa", "next_action", "hosted_instructions", "image_url", "display_qr")):
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
    prefix = INSTRUCTIONS_PREFIX
    for match in matches:
        value = match.get("value")
        if isinstance(value, str) and value.startswith(prefix):
            return value
    for match in matches:
        value = match.get("value")
        if not isinstance(value, dict):
            continue
        block = value.get("upi_handle_redirect_or_display_qr_code")
        if isinstance(block, dict):
            url = block.get("hosted_instructions_url")
            if isinstance(url, str) and url.startswith(prefix):
                return url
        url = value.get("hosted_instructions_url")
        if isinstance(url, str) and url.startswith(prefix):
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


def _render_qr_png(payload: str, out_path: Path) -> None:
    if qrcode is None:
        raise RuntimeError("qrcode library not installed — pip install 'qrcode[pil]'")
    img = qrcode.make(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


async def _download_qr_image(sess: Any, *, url: str, out_path: Path) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = await sess.get(url, timeout=30, proxies=PROXIES)
    except Exception as exc:
        return {"rendered": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if resp.status_code != 200:
        return {"rendered": False, "reason": f"HTTP {resp.status_code}"}
    content_type = str(resp.headers.get("content-type") or "").lower()
    content = resp.content
    if "text/html" in content_type or content.lstrip().lower().startswith(b"<html"):
        html_text = content.decode("utf-8", errors="replace")
        upi_uri = _extract_hosted_instruction_upi_uri(html_text)
        if not upi_uri:
            return {
                "rendered": False,
                "reason": "hosted instructions HTML had no mobile_auth_url",
            }
        _render_qr_png(upi_uri, out_path)
        return {"rendered": True, "path": str(out_path), "source": "hosted_instructions_html"}
    out_path.write_bytes(content)
    return {"rendered": True, "path": str(out_path), "source": "stripe_image"}


# ─────────────────────────────────────────────────────────────────────
# Pipeline steps (1:1 with the original; PROXIES is always None here)
# ─────────────────────────────────────────────────────────────────────


def _headers_common() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "Accept-Language": "en-IN,en;q=0.9",
    }


async def get_account_email(sess: Any, *, access_token: str) -> str:
    """Resolve the account email via /backend-api/me (used for billing_details)."""
    headers = {
        **_headers_common(),
        "Authorization": f"Bearer {access_token}",
        "Accept": "*/*",
    }
    try:
        resp = await sess.get(
            "https://chatgpt.com/backend-api/me",
            headers=headers, timeout=30, proxies=PROXIES,
        )
        if resp.status_code == 200:
            data = resp.json()
            email = data.get("email")
            if isinstance(email, str) and "@" in email:
                return email
    except Exception:
        pass
    return "user@chatgpt.local"


async def create_chatgpt_checkout(
    sess: Any, *, access_token: str, log: LogFn
) -> dict[str, Any]:
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
    resp = await sess.post(
        CHATGPT_CHECKOUT_URL, headers=headers, json=body, timeout=30, proxies=PROXIES
    )
    if resp.status_code != 200:
        raise UpiQrError(f"checkout HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    missing = [k for k in ("checkout_session_id", "publishable_key") if not data.get(k)]
    if missing:
        raise UpiQrError(f"checkout response missing {missing}: {data}")
    log_step("checkout", "ChatGPT checkout", "ok",
             f"cs={short(data['checkout_session_id'])} ui_mode={data.get('checkout_ui_mode')}")
    return data


async def update_chatgpt_checkout(
    sess: Any, *, access_token: str, session_id: str, log: LogFn
) -> dict[str, Any]:
    """tax_update stage — re-applies the ₹0 promo on the live session."""
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
    resp = await sess.post(
        CHATGPT_UPDATE_URL, headers=headers, json=payload, timeout=30, proxies=PROXIES
    )
    if resp.status_code != 200:
        raise UpiQrError(f"checkout/update HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def stripe_init(
    sess: Any, *, session_id: str, publishable_key: str, stripe_js_id: str, log: LogFn
) -> dict[str, Any]:
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
            "saved_payment_method": {
                "enable_save": "auto",
                "enable_redisplay": "auto",
            },
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
    resp = await sess.post(
        STRIPE_INIT_URL.format(id=session_id),
        headers=headers, data=form, timeout=30, proxies=PROXIES,
    )
    if resp.status_code != 200:
        raise UpiQrError(f"stripe init HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("init_checksum") or not data.get("config_id"):
        raise UpiQrError(
            f"stripe init missing init_checksum/config_id: keys={list(data)[:20]}"
        )
    return data


async def stripe_elements_session(
    sess: Any, *, session_id: str, publishable_key: str, stripe_js_id: str, amount: int, log: LogFn
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
    resp = await sess.get(
        STRIPE_ELEMENTS_URL, headers=headers, params=params, timeout=30, proxies=PROXIES
    )
    if resp.status_code != 200:
        raise UpiQrError(f"elements/sessions HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("session_id"):
        raise UpiQrError(f"elements/sessions missing session_id: keys={list(data)[:20]}")
    return data


async def stripe_confirm_upi(
    sess: Any,
    *,
    session_id: str,
    publishable_key: str,
    stripe_js_id: str,
    init_data: dict[str, Any],
    elements_data: dict[str, Any],
    profile: dict[str, str],
    email: str,
    amount: int,
    vpa: str | None,
    token_config: _StripeTokenConfig | None,
    log: LogFn,
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
        "merchant_integration_additional_elements": [
            "expressCheckout", "payment", "address",
        ],
        "merchant_integration_source": "checkout",
        "merchant_integration_subtype": "payment-element",
        "merchant_integration_version": "custom",
        "payment_intent_creation_flow": "deferred",
        "payment_method_selection_flow": "merchant_specified",
    }
    pmd_client_attribution = dict(client_attribution_metadata)
    pmd_client_attribution["merchant_integration_source"] = "elements"
    pmd_client_attribution["merchant_integration_version"] = "2021"

    # UPI payload variants — the original tries several shapes.
    if vpa:
        upi_payload: dict[str, Any] = {"vpa": vpa}
    else:
        upi_payload = {"flow": "qr_code"}

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
    resp = await sess.post(
        STRIPE_CONFIRM_URL.format(id=session_id),
        headers=headers, data=form, timeout=30, proxies=PROXIES,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": (resp.text or "")[:1000]}
    return {
        "http_status": resp.status_code,
        "ok": resp.status_code == 200,
        "data": data if resp.status_code == 200 else None,
        "error": (data.get("error") if isinstance(data, dict) else None),
    }


async def stripe_payment_page_refresh(
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
    resp = await sess.get(
        STRIPE_PAGE_URL.format(id=session_id),
        headers=headers, params=params, timeout=30, proxies=PROXIES,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": (resp.text or "")[:1000]}
    return {
        "http_status": resp.status_code,
        "ok": resp.status_code == 200,
        "data": data if resp.status_code == 200 else None,
    }


async def chatgpt_approve(
    sess: Any, *, access_token: str, session_id: str, log: LogFn
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
    resp = await sess.post(
        CHATGPT_APPROVE_URL, headers=headers, json=body, timeout=30, proxies=PROXIES
    )
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": (resp.text or "")[:1000]}
    result = data.get("result") if isinstance(data, dict) else None
    return {
        "http_status": resp.status_code,
        "ok": resp.status_code == 200 and result == "approved",
        "result": result,
        "data": data if resp.status_code == 200 else None,
    }


# ─────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────


class UpiQrError(Exception):
    """Fatal flow error."""


async def run_upi_qr(
    *,
    access_token: str,
    vpa: str | None = None,
    out_dir: Path = Path("qr_codes"),
    wait_for_payment: bool = False,
    approve_polls: int = 40,
    approve_delay: float = 5.0,
    log: LogFn = print,
) -> dict[str, Any]:
    """Run the full pipeline and save a scannable UPI QR.

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
        "qr_path": None,
        "payment_link": None,
        "upi_uri": None,
        "amount": None,
        "checkout_session": None,
        "approved": False,
        "already_paid": False,
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
    log(bold(cyan("  UPI QR Generator — standalone (no proxy)")))
    log(bold(cyan("═" * 72)))
    log(f"  token    : {dim(token_short)}")
    log(f"  vpa      : {vpa or dim('(none — QR flow)')}")
    log(f"  billing  : {bold(profile['name'])} | {profile['city']}, {profile['state']} | {profile['postal_code']}")
    log(f"  proxy    : {green('NONE (direct from your IP)')}")
    log(bold(cyan("═" * 72)))

    try:
        async with AsyncSession(impersonate=IMPERSONATE) as sess:
            # ── Step 2a — checkout ──
            log_step("1/6", "creating ChatGPT checkout session", "start")
            checkout = await create_chatgpt_checkout(sess, access_token=access_token, log=log)
            session_id = checkout["checkout_session_id"]
            publishable_key = checkout["publishable_key"]
            result["checkout_session"] = short(session_id)

            # ── Step 3 — Stripe init ──
            log_step("2/6", "stripe init", "start")
            stripe_js_id = str(uuid.uuid4())
            init_data = await stripe_init(
                sess, session_id=session_id, publishable_key=publishable_key,
                stripe_js_id=stripe_js_id, log=log,
            )
            amount = _extract_amount(init_data)
            result["amount"] = amount
            log_step("2/6", "stripe init", "ok",
                     f"amount={amount} ppage={short(str(init_data.get('id') or ''))}")

            # ── Step 2b — tax_update (re-apply promo, mirrors the site's stage order) ──
            try:
                await update_chatgpt_checkout(
                    sess, access_token=access_token, session_id=session_id, log=log
                )
                log_step("1/6", "tax_update (promo re-apply)", "ok")
            except Exception as exc:
                log_step("1/6", "tax_update (promo re-apply)", "warn",
                         f"{type(exc).__name__}: {str(exc)[:120]}")

            # Resolve the account email for billing_details.
            email = await get_account_email(sess, access_token=access_token)
            log_step("acct", "account email", "ok", email)

            if amount > 0:
                log_step("upi", "no free offer", "warn",
                         f"amount={amount} paise ({amount / 100:.2f} INR) — the ₹0 promo is "
                         "NOT active on this account/IP; QR would charge real money.")
                result["error"] = f"no free offer (amount={amount})"
                # Continue anyway so the user can still see the QR — but flag it.

            # ── Step 4 — elements session ──
            log_step("3/6", "stripe elements session", "start")
            elements_data = await stripe_elements_session(
                sess, session_id=session_id, publishable_key=publishable_key,
                stripe_js_id=stripe_js_id, amount=amount, log=log,
            )
            log_step("3/6", "stripe elements session", "ok",
                     f"session={short(str(elements_data.get('session_id') or ''))}")

            # ── Step 5a — Stripe token config (js_checksum engine) ──
            log_step("4/6", "stripe token config", "start")
            token_config: _StripeTokenConfig | None = None
            try:
                token_config = await extract_config_live(sess, log=log)
            except Exception as exc:
                log_step("4/6", "stripe token config", "warn",
                         f"{type(exc).__name__}: {str(exc)[:140]} — confirm will run "
                         "without js_checksum (Stripe may reject)")

            # ── Step 5b — confirm (QR flow) ──
            log_step("5/6", "stripe confirm (UPI)", "start")
            confirm = await stripe_confirm_upi(
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
                    f"{json.dumps(err)[:300]}"
                )
            log_step("5/6", "stripe confirm (UPI)", "ok")

            # ── Step 5c — page refresh (materialize QR) ──
            refresh = await stripe_payment_page_refresh(
                sess,
                session_id=session_id,
                publishable_key=publishable_key,
                stripe_js_id=stripe_js_id,
                elements_data=elements_data,
                log=log,
            )
            if refresh["ok"]:
                log_step("5/6", "payment page refresh", "ok")
            else:
                log_step("5/6", "payment page refresh", "warn",
                         f"HTTP {refresh['http_status']}")

            # ── Aggregate QR candidates from every response ──
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

            # ── Step 6 — QR rendering ──
            qr_path: Path | None = None
            stamp = time.strftime("%Y%m%d-%H%M%S")
            if qr_image_url:
                ext = ".svg" if qr_image_url.lower().endswith(".svg") else ".png"
                target = out_dir / f"upi_qr_{stamp}{ext}"
                dl = await _download_qr_image(sess, url=qr_image_url, out_path=target)
                if dl.get("rendered") and dl.get("path"):
                    qr_path = Path(dl["path"])
                    log_step("qr", "QR saved (stripe image)", "ok", str(qr_path))
                else:
                    log_step("qr", "stripe QR image download failed", "warn", dl.get("reason", ""))
            if qr_path is None and upi_uri:
                try:
                    target = out_dir / f"upi_qr_{stamp}.png"
                    _render_qr_png(upi_uri, target)
                    qr_path = target
                    log_step("qr", "QR rendered from upi:// URI", "ok", str(qr_path))
                except Exception as exc:
                    log_step("qr", "QR render failed", "warn", f"{type(exc).__name__}: {exc}")

            if qr_path is None:
                return _fail("no UPI QR found in any response — "
                             "account may already be on a paid plan or the offer is gone")

            result["qr_path"] = str(qr_path)
            if qr_expires_at:
                log(f"  {dim('QR expires at')} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(qr_expires_at))}")

            # ── Step 7 — hosted instructions fallback (if no QR yet) ──
            if payment_link:
                log_step("upi", "payment link", "ok", payment_link)

            # ── Step 8 — approve loop (optional) ──
            if not wait_for_payment:
                result["ok"] = True
                result["elapsed_seconds"] = round(time.monotonic() - started, 1)
                log("")
                log(green(bold("  ✔ QR generated — open/scan it with any UPI app.")))
                if payment_link:
                    log(f"     Payment page: {payment_link}")
                log(dim("     (Run again with --wait to have the script poll for payment/approval.)"))
                return result

            log_step("6/6", "approve loop", "start",
                     f"polls={approve_polls} delay={approve_delay:g}s — scan & pay in your UPI app")
            approved = False
            already_paid = False
            for i in range(1, approve_polls + 1):
                attempt = await chatgpt_approve(
                    sess, access_token=access_token, session_id=session_id, log=log
                )
                body_text = json.dumps(attempt.get("data") or attempt.get("result") or "")
                if attempt["ok"]:
                    approved = True
                    break
                if "already paid" in body_text.lower():
                    already_paid = True
                    break
                if i < approve_polls:
                    await asyncio.sleep(approve_delay)

            if already_paid:
                result["already_paid"] = True
                result["ok"] = True
                log_step("6/6", "account already on paid plan", "ok")
                result["elapsed_seconds"] = round(time.monotonic() - started, 1)
                return result
            if not approved:
                result["error"] = f"not approved after {approve_polls} polls"
                log_step("6/6", "approve", "fail", result["error"])
                return result

            result["approved"] = True
            result["ok"] = True
            result["elapsed_seconds"] = round(time.monotonic() - started, 1)
            log("")
            log(green(bold("  ✔ APPROVED — Plus is now active on the account.")))
            return result

    except UpiQrError as exc:
        return _fail(str(exc))
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {str(exc)[:300]}")


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
    print("  1. Open chatgpt.com in Chrome (logged in)")
    print("  2. F12 → Network tab → type anything in chat and press Enter")
    print("  3. Click any backend-api/ request")
    print("  4. Under Request Headers find 'Authorization:'")
    print("  5. Copy everything after 'Bearer ' (it starts with 'eyJ')")
    print()
    try:
        return input("Paste access token: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)


def _interactive_vpa() -> str | None:
    try:
        vpa = input("UPI VPA (e.g. yourname@oksbi) — blank for pure QR flow: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    return vpa or None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="upi_qr_standalone",
        description=(
            "Generate ₹0 UPI Autopay QR codes for ChatGPT Plus — standalone, "
            "no proxy needed (the hosted site upi.vaultvip.pro requires an "
            "Indian proxy because it runs remotely; you don't, since you're "
            "already in India)."
        ),
    )
    p.add_argument("--token", help="ChatGPT access token (starts with 'eyJ')")
    p.add_argument("--tokens-file", help="file with one access token per line")
    p.add_argument("--vpa", help="your UPI VPA (name@bank); omit for QR-code flow")
    p.add_argument("--out", default="qr_codes", help="output directory (default: ./qr_codes)")
    p.add_argument("--wait", action="store_true",
                   help="poll /approve until the payment completes (or --wait-polls)")
    p.add_argument("--wait-polls", type=int, default=40,
                   help="approve poll count when --wait is set (default 40)")
    p.add_argument("--delay", type=float, default=5.0,
                   help="approve poll delay seconds (default 5)")
    p.add_argument("--no-cache", action="store_true",
                   help="don't use the disk cache for Stripe JS bundles")
    args = p.parse_args(argv)

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
            result = asyncio.run(run_upi_qr(
                access_token=token,
                vpa=vpa,
                out_dir=out_dir,
                wait_for_payment=args.wait,
                approve_polls=args.wait_polls,
                approve_delay=args.delay,
            ))
        except KeyboardInterrupt:
            print("\ninterrupted")
            rc = 130
            break
        if not result.get("ok"):
            rc = 1

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
vault_sig.py — Python replica of the signature generation in the deobfuscated
extension's lib/vault-fetch.js (see ../README-deobfuscated.md).

Original (vaultFetch, function v8):
    var v20 = String(Date.now());            // X-Vault-Ts: ms since epoch, as a string
    v19.set("X-Vault-Ts", v20);
    v19.set("X-Vault-Sig", await v7(v20));   // v7 = hex(HMAC-SHA256(SECRET, ts))
So the signed message is ONLY the timestamp string; the secret is the constant
embedded in the client (function v2). hexdigest() lowercase matches the
byte->hex padStart(2,'0') loop (v6).

Usage:
    python3 vault_sig.py              # print X-Vault-Ts / X-Vault-Sig for "now"
    python3 vault_sig.py 1727350000000  # reproduce the signature for a fixed ts
"""
import hashlib
import hmac
import sys
import time

# v2 in lib/vault-fetch.js — embedded in the shipped client, hence public
SECRET = "r5XRzxtFq7OLciZhGzBwaq8rFLkrXj78uIcru5DnvfaRaWc"


def gen_sig(ts: str | None = None) -> tuple[str, str]:
    """Return (X-Vault-Ts, X-Vault-Sig) exactly like the extension would send."""
    ts = ts if ts is not None else str(int(time.time() * 1000))  # String(Date.now())
    sig = hmac.new(SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return ts, sig


if __name__ == "__main__":
    fixed = sys.argv[1] if len(sys.argv) > 1 else None
    ts, sig = gen_sig(fixed)
    print(f"X-Vault-Ts: {ts}")
    print(f"X-Vault-Sig: {sig}")

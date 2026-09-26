# Nftools-injector (2.3.7) — deobfuscated

Source: only `https://github.com/SaloniTae/Flowpay/blob/Useless/Nftools-injector(2.3.7).zip`
(manifest.json and lib/jszip.min.js excluded per request; CSS/HTML were already
readable and are copied unchanged).

## What was done

The six JS files were obfuscated with `javascript-obfuscator` (string-array +
custom base64/RC4 decoder + array rotation + per-scope aliasing + mangled
identifiers). Each file was processed with an AST-based deobfuscator that:

1. Sandbox-executed only the string-array machinery (array builder, decoder,
   rotation IIFE, aliases) with stubbed browser globals, so the rotation loop
   self-completes.
2. Probed the real decoder functions and inlined every call site — 3,262 string
   calls resolved across the six files, zero unresolved.
3. Removed the machinery, folded all hex arithmetic and boolean tricks
   (`!![]` → `true`), demangled every `_0x…` identifier, converted
   `obj['prop']` → `obj.prop`, and re-emitted formatted source.

All outputs pass `node --check`. Identifiers were machine-generated (v1, v2, …)
per scope; a couple of longer names (e.g. `vaultUser`, `vaultQuota`, `adConfig`)
are original because the obfuscator left globals unmangled.

## What the extension actually does

**Name:** "Cookies Vault" v2.3.7 (MV3; service worker = `scripts/vault-telemetry.js`).

- **lib/vault-fetch.js** — signed-fetch helper. Every request to the backend
  gets `X-Vault-Ts` + `X-Vault-Sig` (HMAC-SHA256 over the timestamp with a
  hardcoded secret `r5XRzxtFq7OLciZhGzBwaq8rFLkrXj78uIcru5DnvfaRaWc`).
- **scripts/background.js** — cookie engine. Message handlers:
  `GET_COOKIES_FOR_URL`, `SET_COOKIE` (with multi-stage retry: https →
  secure → drop sameSite → drop domain → path=/), `FIND_TABS_FOR_DOMAIN`,
  `RELOAD_TABS`, `OPEN_DOMAIN`. Every handler is gated behind a
  SHA-256 self-integrity check (`BG_EXPECTED_HASHES` over all 13 files);
  tamper ⇒ badge `!` + notification + refusal.
- **scripts/vault-telemetry.js** — telemetry, despite the manifest description
  claiming "no data ever leaves your device." Sends heartbeats every 2 minutes
  to `https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app`
  (`/api/public/extension/heartbeat`) with: random installation UUID, extension
  version, browser family, platform, event type, and **timezone**. Also runs
  forced-update enforcement (disables the popup when outdated).
- **ui/auth-gate.js** — paywall/access gate. Requires joining Telegram channels
  + verifying via a bot (`/api/public/extension/auth/{request,status,session}`);
  stores `vault_auth` locally; supports remote **ban** (replaces UI with a ban
  screen).
- **ui/popup.js** — main UI. Cookie import (JSON / Netscape / header / ZIP),
  restore-into-browser, export (JSON / Netscape / header / copy), themes, and
  the "NFTools injector" feature: fetches cookie **sessions for third-party
  services** from `…/extension/cookies?service=…&username=…` and injects them
  into the browser, quota-limited (10/day) and gated behind a **forced ad watch**
  (15 s countdown tab, 1 h cooldown) — ad events are reported to the backend.
- **lib/vault-size.js** — second anti-tamper layer: exact byte-size check of
  the whole bundle (`EXPECTED_TOTAL_SIZE = 391751`).

### Security-relevant notes

- **Claims vs. behavior:** the manifest/description says everything "runs
  locally — no data ever leaves your device," yet telemetry with timezone +
  install UUID runs every 2 minutes, and the injector flows send your Telegram
  username with each request.
- **Hardcoded HMAC secret** in client code (anyone can forge valid signatures;
  it only stops casual third-party use of the API).
- **Self-integrity checks** are anti-modification, not security for the user:
  they brick modified builds and steer re-installation to `t.me/cookies_vault`.
- **Permissions are broad:** `cookies` + `tabs` + `storage` + `alarms` with
  `<all_urls>` host access — full read/write of every site's cookies.
- Injected "sessions" for third-party services are shared credential pools
  (classic cookie-injection account pooling); using them with your own accounts
  is the risk surface.

## Files (same names as the zip)

| Path | Bytes | Note |
|---|---|---|
| `lib/vault-fetch.js` | 994 | fully deobfuscated |
| `lib/vault-size.js` | 6,190 | fully deobfuscated |
| `scripts/background.js` | 6,684 | fully deobfuscated |
| `scripts/vault-telemetry.js` | 3,449 | fully deobfuscated |
| `ui/auth-gate.js` | 7,509 | fully deobfuscated |
| `ui/popup.js` | 68,862 | fully deobfuscated |
| `ui/popup.css` / `ui/popup.html` | — | were not obfuscated; copied as-is |

(function (v1) {
  'use strict';

  var v2 = "r5XRzxtFq7OLciZhGzBwaq8rFLkrXj78uIcru5DnvfaRaWc",
    v3 = new TextEncoder(),
    v4 = null;
  function v5() {
    return !v4 && (v4 = crypto.subtle.importKey("raw", v3.encode(v2), {
      'name': "HMAC",
      'hash': 'SHA-256'
    }, false, ['sign'])), v4;
  }
  function v6(v9) {
    var v10 = new Uint8Array(v9),
      v11 = '';
    for (var v12 = 0; v12 < v10.length; v12++) {
      v11 += v10[v12].toString(16).padStart(2, '0');
    }
    return v11;
  }
  async function v7(v13) {
    var v14 = await v5(),
      v15 = await crypto.subtle.sign("HMAC", v14, v3.encode(v13));
    return v6(v15);
  }
  async function v8(v16, v17) {
    var v18 = v17 ? Object.assign({}, v17) : {},
      v19 = new Headers(v18.headers || {}),
      v20 = String(Date.now());
    return v19.set("X-Vault-Ts", v20), v19.set("X-Vault-Sig", await v7(v20)), v18.headers = v19, fetch(v16, v18);
  }
  v1.vaultFetch = v8;
})(typeof self !== "undefined" ? self : this);
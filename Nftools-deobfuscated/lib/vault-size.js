(function () {
  const v1 = "lib/vault-size.js",
    v2 = "ui/popup.js",
    v3 = "scripts/background.js",
    v4 = /\/\/ <size-manifest>[\s\S]*?\/\/ <\/size-manifest>/,
    v5 = /\/\/ <integrity-manifest>[\s\S]*?\/\/ <\/integrity-manifest>/,
    v6 = /\/\/ <bg-integrity-manifest>[\s\S]*?\/\/ <\/bg-integrity-manifest>/;
  async function v7(v13) {
    const v14 = await fetch(chrome.runtime.getURL(v13), {
      'cache': "no-store"
    });
    if (!v14.ok) throw new Error('missing\x20' + v13);
    if (v13 === v1) {
      const v15 = (await v14.text()).replace(v4, '');
      return new TextEncoder().encode(v15).length;
    }
    if (v13 === v2) {
      const v16 = (await v14.text()).replace(v5, '');
      return new TextEncoder().encode(v16).length;
    }
    if (v13 === v3) {
      const v17 = (await v14.text()).replace(v6, '');
      return new TextEncoder().encode(v17).length;
    }
    return (await v14.arrayBuffer()).byteLength;
  }
  async function v8() {
    let v18 = 0;
    for (const v19 of SIZE_MANIFEST_FILES) v18 += await v7(v19);
    return v18;
  }
  async function v9() {
    try {
      const {
        vault_latest_release: v20
      } = await chrome.storage.local.get("vault_latest_release");
      if (v20 && v20.download_url) return v20.download_url;
    } catch (v21) {}
    try {
      if (typeof window.vaultFetch === "function") {
        const v22 = await window.vaultFetch("/api/public/extension/version", {
            'cache': "no-store"
          }),
          v23 = await v22.json();
        if (v23 && v23.download_url) return v23.download_url;
      }
    } catch (v24) {}
    return "https://t.me/cookies_vault";
  }
  function v10() {
    try {
      document.documentElement.style.height = '100%', document.body.style.margin = '0', document.body.innerHTML = "<div style=\"position:fixed;inset:0;width:100%;height:100%;min-height:480" + "px;paddi" + 'ng:32px\x20' + "26px;box" + "-sizing:" + "border-b" + 'ox;displ' + "ay:flex;" + "flex-dir" + "ection:c" + 'olumn;al' + "ign-item" + "s:center" + ";justify" + "-content" + ":center;" + 'text-ali' + "gn:cente" + "r;font-f" + "amily:sy" + "stem-ui," + "-apple-s" + "ystem,'S" + "egoe UI'" + ",sans-se" + "rif;back" + "ground:r" + "adial-gr" + "adient(1" + "20% 80% " + "at 50% -" + '10%,\x20rgb' + "a(239,68" + ',68,.18)' + ',\x20transp' + "arent 60" + "%),radia" + "l-gradie" + "nt(90% 6" + "0% at 50" + "% 110%, " + "rgba(250" + ",204,21," + ".08), tr" + 'ansparen' + "t 60%),#" + '05080f;\x22' + '>' + ("<div style=\"width:68px;height:68px;margin:0 auto 18px;border-radius:20px" + ";backgro" + "und:line" + "ar-gradi" + "ent(135d" + "eg,#fca5" + 'a5,#ef44' + '44\x2045%,#' + "b91c1c);" + "display:" + "flex;ali" + "gn-items" + ":center;" + "justify-" + 'content:' + "center;f" + "ont-size" + ":32px;fo" + "nt-weigh" + "t:900;co" + 'lor:#050' + '80f;box-' + 'shadow:0' + " 0 0 8px" + " rgba(23" + '9,68,68,' + ".08), 0 " + "12px 30p" + "x rgba(2" + "39,68,68" + ",.28);\">" + "!</div>") + ("<div style=\"font-size:10px;letter-spacing:.18em;text-transform:uppercase" + ';color:#' + "ef4444;f" + "ont-weig" + 'ht:800;m' + "argin-bo" + 'ttom:8px' + ";\">Secur" + 'ity\x20chec' + "k failed" + "</div>") + ("<h1 style=\"font-size:19px;margin:0 0 10px;color:#fff;\">Modified build de" + "tected</" + "h1>") + ("<p style=\"font-size:12.5px;line-height:1.6;color:#94a3b8;margin:0 0 14px" + ";max-wid" + "th:300px" + ";\">Cooki" + 'es\x20Vault' + '\x20found\x20c' + "hanges t" + "o its fi" + "les and " + "will not" + " run. Re" + "install " + "the offi" + "cial bui" + 'ld\x20to\x20co' + "ntinue.<" + "/p>") + ("<div style=\"display:inline-block;padding:7px 12px;border-radius:10px;bac" + 'kground:' + "#0b1220;" + "border:1" + "px solid" + " #1e293b" + ';color:#' + "64748b;f" + "ont-size" + ":11px;fo" + "nt-weigh" + "t:700;ma" + 'rgin-bot' + "tom:20px" + ';word-br' + "eak:brea" + 'k-all;ma' + "x-width:" + '300px;\x22>' + "bundle s" + "ize</div" + '>') + ("<a id=\"vaultOfficialDlSize\" href=\"https://t.me/cookies_vault\" target=\"_b" + 'lank\x22\x20re' + 'l=\x22noope' + "ner\" sty" + "le=\"disp" + "lay:bloc" + "k;width:" + "100%;max" + "-width:3" + "00px;box" + "-sizing:" + "border-b" + "ox;paddi" + 'ng:14px\x20' + "18px;bor" + 'der-radi' + "us:14px;" + "text-dec" + "oration:" + 'none;bac' + 'kground:' + "linear-g" + "radient(" + "90deg,#f" + 'de68a,#f' + "acc15 40" + "%,#ca8a0" + "4);color" + ':#05080f' + ";font-we" + 'ight:900' + ";font-si" + 'ze:14px;' + "box-shad" + "ow:0 12p" + "x 26px r" + "gba(250," + '204,21,.' + "22);\">Do" + "wnload o" + "fficial " + "version<" + '/a>') + ("<p style=\"margin-top:16px;font-size:11px;color:#475569;line-height:1.5;m" + 'ax-width' + ":300px;\"" + ">Downloa" + "ds come " + "from the" + '\x20officia' + "l Cookie" + "s Vault " + 'release\x20' + "channel." + "</p>") + ("<div style=\"margin-top:18px;font-size:10px;letter-spacing:.16em;text-tra" + "nsform:u" + "ppercase" + ";color:#" + "334155;f" + 'ont-weig' + "ht:700;\"" + '>Cookies' + " Vault</" + "div>") + '</div>', v9().then(v25 => {
        const v26 = document.getElementById("vaultOfficialDlSize");
        if (v26) v26.href = v25;
      });
    } catch (v27) {}
  }
  async function v11() {
    if (!SIZE_MANIFEST_FILES.length || !EXPECTED_TOTAL_SIZE) return {
      'ok': true
    };
    let v28;
    try {
      v28 = await v8();
    } catch (v29) {
      return v10(), {
        'ok': false,
        'reason': "read-error"
      };
    }
    if (v28 !== EXPECTED_TOTAL_SIZE) return v10(), {
      'ok': false,
      'expected': EXPECTED_TOTAL_SIZE,
      'actual': v28
    };
    return {
      'ok': true
    };
  }
  window.vaultVerifyBundleSize = v11;
  const v12 = () => {
    v11();
  };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", v12, {
    'once': true
  }) : v12();
})();
// <size-manifest>
var SIZE_MANIFEST_FILES = ["icons/icon128.png", "icons/icon16.png", "icons/icon48.png", "lib/jszip.min.js", "lib/vault-fetch.js", "lib/vault-size.js", "manifest.json", "scripts/background.js", "scripts/vault-telemetry.js", "ui/auth-gate.js", "ui/popup.css", "ui/popup.html", "ui/popup.js"],
  EXPECTED_TOTAL_SIZE = 391751;
// </size-manifest>
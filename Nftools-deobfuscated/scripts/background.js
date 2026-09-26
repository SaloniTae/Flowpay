const BG_EXPECTED_HASHES =
  // <bg-integrity-manifest>
  {
    "icons/icon128.png": "24b46998ccac3aea9c67ec3841d7c1cca84834edfb2d8757cea15c4b06a1a0e9",
    "icons/icon16.png": "8cf325f9da2c04a86674e03f67321556425c69556e9b205e75120f92210ab9c7",
    "icons/icon48.png": "9a7a0fdd3aa6c5c610a6e54626c60723638239c2e094feebba76b3a9adb041a8",
    "lib/jszip.min.js": "acc7e41455a80765b5fd9c7ee1b8078a6d160bbbca455aeae854de65c947d59e",
    "lib/vault-fetch.js": "6dd385ebbd15d4fbfca92eee42f9ffa09d36cef25c2c3f1fae13d65439de0bac",
    "lib/vault-size.js": "699630c9c5fc307008ff330730c11aa34bbd67678e73c2c71eaab0e343181583",
    "manifest.json": "a739e66cb63fc4a13acbfb453d21092b808133f88bf7fe95284671c906831c5e",
    "scripts/background.js": "b53193cf1eb6003eaa5524a7ca698ec4430e69e39ee34e0e826c85f2a6679ba0",
    "scripts/vault-telemetry.js": "8e53b9ff5bb9937cfcf6e0b0e56b24b790fbd65479c6cbc083b9bdffa46d6ee6",
    "ui/auth-gate.js": "f7ef1a7300e797c14b39178a56e8870a52f4d05331fe1402027525256b0e0e7e",
    "ui/popup.css": "3160ef4d84d2d9a6df506990fb88d3286a64716f8045c231489890a4ef358627",
    "ui/popup.html": "3f476fbf4de5c963ac1b77362c7cbe8befd600df8533e13492f9863b0751659b",
    "ui/popup.js": "2bf935a8546fabcdb4afbab43ca402f57fdebbe71e1230b1db91ce8207cef24b"
  }
  // </bg-integrity-manifest>
  ,
  BG_SELF_PATH = "scripts/background.js",
  POPUP_PATH = "ui/popup.js",
  SIZE_PATH = "lib/vault-size.js",
  BG_MANIFEST_RE = /\/\/ <bg-integrity-manifest>[\s\S]*?\/\/ <\/bg-integrity-manifest>/,
  POPUP_MANIFEST_RE = /\/\/ <integrity-manifest>[\s\S]*?\/\/ <\/integrity-manifest>/,
  SIZE_MANIFEST_RE = /\/\/ <size-manifest>[\s\S]*?\/\/ <\/size-manifest>/;
async function bgSha256Hex(v1) {
  const v2 = await crypto.subtle.digest("SHA-256", v1);
  return Array.from(new Uint8Array(v2)).map(v3 => v3.toString(16).padStart(2, '0')).join('');
}
let bgIntegrityPromise = null,
  bgTampered = false,
  bgTamperedFile = null;
async function bgVerifyIntegrity() {
  const v4 = Object.entries(BG_EXPECTED_HASHES);
  if (!v4.length) return true;
  for (const [v5, v6] of v4) {
    try {
      const v7 = await fetch(chrome.runtime.getURL(v5), {
        'cache': 'no-store'
      });
      if (!v7.ok) throw new Error("missing");
      let v8;
      if (v5 === BG_SELF_PATH) {
        const v9 = (await v7.text()).replace(BG_MANIFEST_RE, '');
        v8 = await bgSha256Hex(new TextEncoder().encode(v9));
      } else {
        if (v5 === POPUP_PATH) {
          const v10 = (await v7.text()).replace(POPUP_MANIFEST_RE, '');
          v8 = await bgSha256Hex(new TextEncoder().encode(v10));
        } else {
          if (v5 === SIZE_PATH) {
            const v11 = (await v7.text()).replace(SIZE_MANIFEST_RE, '');
            v8 = await bgSha256Hex(new TextEncoder().encode(v11));
          } else v8 = await bgSha256Hex(await v7.arrayBuffer());
        }
      }
      if (v8 !== v6) return bgTampered = true, bgTamperedFile = v5, false;
    } catch (v12) {
      return bgTampered = true, bgTamperedFile = v5, false;
    }
  }
  return true;
}
function ensureBgIntegrity() {
  if (!bgIntegrityPromise) bgIntegrityPromise = bgVerifyIntegrity();
  return bgIntegrityPromise;
}
async function notifyTamper() {
  try {
    await chrome.action.setBadgeText({
      'text': '!'
    }), await chrome.action.setBadgeBackgroundColor({
      'color': "#dc2626"
    });
  } catch {}
  try {
    await chrome.notifications.create({
      'type': "basic",
      'iconUrl': chrome.runtime.getURL("icons/icon128.png"),
      'title': "Cookies Vault — Tampered build",
      'message': "Modified extension files detected (" + (bgTamperedFile || "unknown") + "). Re-install from the official channel.",
      'priority': 0x2
    });
  } catch {}
}
ensureBgIntegrity().then(v13 => {
  if (!v13) notifyTamper();
});
function refuseIfTampered(v14) {
  notifyTamper(), v14({
    'ok': false,
    'error': "tampered build",
    'tampered': true,
    'file': bgTamperedFile
  });
}
chrome.runtime.onMessage.addListener((v15, v16, v17) => {
  if (v15 && v15.type === "BG_INTEGRITY_STATUS") return ensureBgIntegrity().then(v19 => v17({
    'ok': v19,
    'file': bgTamperedFile
  })), true;
  const v18 = v20 => {
    return ensureBgIntegrity().then(v21 => {
      if (!v21) return refuseIfTampered(v17);
      try {
        v20();
      } catch (v22) {
        v17({
          'ok': false,
          'error': String(v22)
        });
      }
    }), true;
  };
  if (v15.type === "GET_COOKIES_FOR_URL") return v18(() => {
    chrome.cookies.getAll({
      'url': v15.url
    }, v23 => v17({
      'cookies': v23
    }));
  });
  if (v15.type === "SET_COOKIE") return v18(() => {
    const v24 = v25 => new Promise(v26 => {
      chrome.cookies.set(v25, v27 => {
        if (chrome.runtime.lastError) v26({
          'ok': false,
          'error': chrome.runtime.lastError.message
        });else !v27 ? v26({
          'ok': false,
          'error': "rejected by browser"
        }) : v26({
          'ok': true
        });
      });
    });
    (async () => {
      const v28 = {
        ...v15.details
      };
      let v29 = await v24(v28);
      if (v29.ok) return v17(v29);
      const v30 = {
        ...v28
      };
      if (v30.url) v30.url = v30.url.replace(/^http:\/\//i, "https://");
      v30.secure = true, v29 = await v24(v30);
      if (v29.ok) return v17(v29);
      const v31 = {
        ...v30
      };
      delete v31.sameSite, v29 = await v24(v31);
      if (v29.ok) return v17(v29);
      const v32 = {
        ...v31
      };
      delete v32.domain, v29 = await v24(v32);
      if (v29.ok) return v17(v29);
      const v33 = {
        ...v32,
        'path': '/'
      };
      if (v33.url) try {
        const v34 = new URL(v33.url);
        v33.url = v34.protocol + '//' + v34.hostname + '/';
      } catch {}
      v29 = await v24(v33), v17(v29);
    })();
  });
  if (v15.type === "FIND_TABS_FOR_DOMAIN") return v18(() => {
    const v35 = (v15.domain || '').toLowerCase();
    chrome.tabs.query({}, v36 => {
      const v37 = (v36 || []).filter(v38 => {
        if (!v38.url) return false;
        try {
          const v39 = new URL(v38.url).hostname.toLowerCase();
          return v39 === v35 || v39.endsWith('.' + v35);
        } catch {
          return false;
        }
      });
      v17({
        'tabIds': v37.map(v40 => v40.id)
      });
    });
  });
  if (v15.type === "RELOAD_TABS") return v18(() => {
    (v15.tabIds || []).forEach(v41 => chrome.tabs.reload(v41)), v17({
      'ok': true
    });
  });
  if (v15.type === "OPEN_DOMAIN") return v18(() => {
    chrome.tabs.create({
      'url': "https://" + v15.domain + '/'
    }), v17({
      'ok': true
    });
  });
});
(() => {
  const v1 = "vault_auth",
    v2 = "vault_join_ack",
    v3 = "vault_auth_pending",
    v4 = "https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app/api/pu" + "blic/ext" + 'ension/a' + "uth",
    v5 = v29 => document.querySelector(v29),
    v6 = document.body,
    v7 = v5("#authGate");
  if (!v7) return;
  const v8 = Array.from(v7.querySelectorAll(".ag-join")),
    v9 = v5("#agUsername"),
    v10 = v5("#agCodeBtn"),
    v11 = v5("#agCodeBox"),
    v12 = v5("#agCode"),
    v13 = v5("#agBotBtn"),
    v14 = v5("#agVerifyBtn"),
    v15 = v5("#agMsg"),
    v16 = v5("#agStepBot");
  let v17 = {},
    v18 = null,
    v19 = null;
  const v20 = async v30 => {
    v28();
    const v31 = await chrome.storage.local.get([v1]),
      v32 = v30 && v30.username || v31[v1] && v31[v1].username || '';
    await chrome.storage.local.remove(v1);
    const v33 = document.getElementById("banReason"),
      v34 = document.getElementById("banUser");
    if (v33 && v30 && v30.message) v33.textContent = v30.message;
    if (v34 && v32) v34.textContent = '@' + v32;
    v6.classList.remove("auth-checking", "auth-required", 'authed'), v6.classList.add('banned');
  };
  window.vaultShowBanned = v20;
  const v21 = (v35, v36) => {
      v15.textContent = v35 || '', v15.dataset.kind = v36 || '', v15.classList.toggle("hidden", !v35);
    },
    v22 = () => {
      v8.forEach(v38 => v38.classList.toggle("done", !!v17[v38.dataset.channel]));
      const v37 = v8.every(v39 => v17[v39.dataset.channel]);
      return v7.classList.toggle("step-unlocked", v37), v9.disabled = !v37, v10.disabled = !v37, v37;
    },
    v23 = v40 => {
      v18 = v40, v12.textContent = v40.code, v11.classList.remove("hidden"), v16.classList.remove("hidden"), v14.classList.remove("hidden"), v13.dataset.url = v40.bot_url, v10.querySelector('span').textContent = "Get a new code", v27();
    },
    v24 = async v41 => {
      v28();
      const v42 = {
        'token': v41.token || 'ok',
        'username': v41.username,
        'display_name': v41.display_name || '',
        'at': Date.now(),
        'last_check': Date.now()
      };
      try {
        await chrome.storage.local.set({
          [v1]: v42
        }), await chrome.storage.local.remove(v3);
      } catch {}
      v21("Verified — welcome, @" + v41.username + '.', 'ok'), v7.classList.add("ag-unlocking"), setTimeout(() => {
        v6.classList.remove("auth-required"), v6.classList.add("authed"), window.dispatchEvent(new CustomEvent("vault-auth", {
          'detail': v42
        }));
      }, 380);
    },
    v25 = async v43 => {
      if (!v43.token || v43.token === 'ok') return;
      try {
        const v44 = await vaultFetch(v4 + "/session?token=" + encodeURIComponent(v43.token), {
            'cache': "no-store"
          }),
          v45 = await v44.json().catch(() => ({}));
        if (v45 && v45.banned) return v20({
          ...v45,
          'username': v43.username
        });
        if (v44.ok && v45.valid) {
          await chrome.storage.local.set({
            [v1]: {
              ...v43,
              'username': v45.username || v43.username,
              'display_name': v45.display_name || v43.display_name,
              'last_check': Date.now()
            }
          });
          return;
        }
        (v44.status === 404 || v44.status === 403) && (await chrome.storage.local.remove(v1), location.reload());
      } catch {}
    };
  async function v26(v46, v47) {
    if (!v18) return false;
    const v48 = v18.code,
      v49 = Math.max(1, v47 || 1);
    for (let v50 = 0; v50 < v49; v50++) {
      if (!v18 || v18.code !== v48) return false;
      if (v50 > 0) await new Promise(v53 => setTimeout(v53, 1200));
      let v51, v52;
      try {
        v51 = await vaultFetch(v4 + "/status?code=" + encodeURIComponent(v48) + "&t=" + Date.now(), {
          'cache': "no-store"
        });
        const v54 = await v51.text();
        v52 = v54 ? JSON.parse(v54) : {};
      } catch {
        if (!v46) v21("Network problem. Check your connection and try again.", "err");
        return false;
      }
      if (v52 && v52.banned) return v20({
        ...v52,
        'username': v18 && v18.username
      });
      if (v51.ok && v52.verified) return await v24({
        ...v52,
        'username': v52.username || v18.username
      }), true;
      if (v52.expired) return v28(), v21("That code expired. Generate a new one.", 'err'), false;
      if (v51.status === 404 && !v52.error) {
        if (!v46) v21("This build can no longer reach the server. Install the latest version fr" + "om the o" + "fficial " + "channel.", "err");
        return false;
      }
      if (!v51.ok && v52.error && v51.status !== 404) {
        if (!v46) v21(v52.error, "err");
        return false;
      }
    }
    if (!v46) v21("Verification has not synced yet. Wait a moment, then tap Verify & Unlock" + " again.", "warn");
    return false;
  }
  const v27 = () => {
      v28(), v19 = setInterval(() => v26(true), 3000);
    },
    v28 = () => {
      if (v19) clearInterval(v19);
      v19 = null;
    };
  v8.forEach(v55 => {
    v55.addEventListener("click", () => {
      chrome.tabs.create({
        'url': v55.dataset.url
      }), v17[v55.dataset.channel] = true, chrome.storage.local.set({
        [v2]: v17
      }), v22(), v21("Join the channel in the new tab, then continue below.", 'warn');
    });
  }), v10.addEventListener("click", async () => {
    const v56 = v9.value.trim().replace(/^@+/, '');
    if (!/^[A-Za-z0-9_]{5,32}$/.test(v56)) {
      v21("Enter your real Telegram username (without @).", "err"), v9.focus();
      return;
    }
    v10.disabled = true, v21("Generating your secret code…", "busy");
    try {
      const v57 = await vaultFetch(v4 + '/request', {
          'method': "POST",
          'headers': {
            'content-type': "application/json"
          },
          'body': JSON.stringify({
            'username': v56
          })
        }),
        v58 = await v57.json();
      if (!v57.ok) throw new Error(v58.error || "Request failed");
      v58.username = v56, await chrome.storage.local.set({
        [v3]: v58
      }), v23(v58), v21("Code ready. Open the bot and press Start to send it.", 'ok');
    } catch (v59) {
      v21(v59.message || "Could not generate a code. Try again.", "err");
    } finally {
      v10.disabled = false;
    }
  }), v13.addEventListener("click", () => {
    if (!v18) return;
    chrome.tabs.create({
      'url': v13.dataset.url || v18.bot_url
    }), v21("Press Start in the bot, then come back and tap Verify & Unlock.", "warn");
  }), v11.addEventListener('click', () => {
    if (!v18) return;
    navigator.clipboard?.["writeText"](v18.code), v21("Code copied.", 'ok');
  }), v14.addEventListener("click", async () => {
    v14.disabled = true, v21("Checking your verification…", "busy"), await v26(false, 5), v14.disabled = false;
  }), (async () => {
    const v60 = await chrome.storage.local.get([v1, v2, v3]),
      v61 = v60[v1];
    if (v61 && v61.token) {
      v6.classList.add("authed"), v6.classList.remove("auth-checking", "auth-required"), window.dispatchEvent(new CustomEvent("vault-auth", {
        'detail': v61
      })), v25(v61);
      return;
    }
    v17 = v60[v2] || {}, v6.classList.remove("auth-checking"), v6.classList.add("auth-required"), v22();
    if (v60[v3] && v60[v3].code) {
      const v62 = v60[v3];
      v9.value = v62.username || '', v23(v62), v26(true);
    }
  })();
})();
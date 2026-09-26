importScripts("../lib/vault-fetch.js", "background.js");
const VAULT_ENDPOINT = "https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app/api/pu" + "blic/ext" + "ension/h" + 'eartbeat',
  VERSION_ENDPOINT = "https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app/api/pu" + 'blic/ext' + "ension/v" + "ersion",
  HEARTBEAT_MINUTES = 2;
function isOutdated(v1, v2) {
  const v3 = String(v1).split('.').map(Number),
    v4 = String(v2).split('.').map(Number);
  for (let v5 = 0; v5 < Math.max(v3.length, v4.length); v5++) {
    const v6 = v3[v5] || 0,
      v7 = v4[v5] || 0;
    if (v6 !== v7) return v6 < v7;
  }
  return false;
}
async function enforceLatestVersion() {
  try {
    const v8 = await vaultFetch(VERSION_ENDPOINT, {
      'cache': "no-store"
    });
    if (!v8.ok) return;
    const v9 = await v8.json();
    if (!v9 || !v9.version) return;
    await chrome.storage.local.set({
      'vault_latest_release': v9
    });
    const v10 = chrome.runtime.getManifest().version;
    isOutdated(v10, v9.version) ? (await chrome.action.setPopup({
      'popup': "ui/update-required.html"
    }), await chrome.action.setBadgeText({
      'text': '!'
    }), await chrome.action.setBadgeBackgroundColor({
      'color': "#facc15"
    })) : (await chrome.action.setPopup({
      'popup': "ui/popup.html"
    }), await chrome.action.setBadgeText({
      'text': ''
    }));
  } catch (v11) {}
}
function detectBrowser() {
  const v12 = navigator.userAgent || '';
  if (v12.includes("Edg/")) return "Edge";
  if (v12.includes("OPR/") || v12.includes("Opera")) return 'Opera';
  if (v12.includes("Brave")) return "Brave";
  if (v12.includes('Firefox')) return "Firefox";
  if (v12.includes("Chrome")) return "Chrome";
  return "Unknown";
}
async function getInstallationId() {
  const v13 = await chrome.storage.local.get("vault_installation_id");
  if (v13.vault_installation_id) return v13.vault_installation_id;
  const v14 = crypto.randomUUID();
  return await chrome.storage.local.set({
    'vault_installation_id': v14
  }), v14;
}
async function sendHeartbeat(v15) {
  try {
    const v16 = await getInstallationId(),
      v17 = chrome.runtime.getManifest();
    await vaultFetch(VAULT_ENDPOINT, {
      'method': "POST",
      'headers': {
        'content-type': "application/json"
      },
      'body': JSON.stringify({
        'installation_id': v16,
        'extension_version': v17.version,
        'browser_family': detectBrowser(),
        'platform': navigator.platform || "unknown",
        'event_type': v15 || null,
        'timezone': Intl.DateTimeFormat().resolvedOptions().timeZone
      })
    });
  } catch (v18) {}
}
chrome.runtime.onInstalled.addListener(() => {
  sendHeartbeat("extension_installed"), enforceLatestVersion(), chrome.alarms.create("vault-heartbeat", {
    'periodInMinutes': HEARTBEAT_MINUTES
  });
}), chrome.runtime.onStartup.addListener(() => {
  sendHeartbeat("browser_startup"), enforceLatestVersion(), chrome.alarms.create("vault-heartbeat", {
    'periodInMinutes': HEARTBEAT_MINUTES
  });
}), chrome.alarms.onAlarm.addListener(v19 => {
  v19.name === "vault-heartbeat" && (sendHeartbeat(null), enforceLatestVersion());
}), chrome.runtime.onMessage.addListener(v20 => {
  if (v20 && v20.type) sendHeartbeat("extension_used");
  return false;
}), chrome.runtime.onConnect.addListener(() => sendHeartbeat("popup_opened")), sendHeartbeat("worker_started"), enforceLatestVersion();
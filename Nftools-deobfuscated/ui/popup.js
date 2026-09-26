const VAULT_REQUIRED_LIBS = [["lib/vault-size.js", "vaultVerifyBundleSize"], ["lib/vault-fetch.js", "vaultFetch"], ["lib/jszip.min.js", "JSZip"]];
let vaultLibGuardOk = false;
async function vaultAssertLibs() {
  for (const [v1, v2] of VAULT_REQUIRED_LIBS) {
    if (typeof window[v2] === "undefined") return showTamperError(v1), false;
    try {
      const v3 = await fetch(chrome.runtime.getURL(v1), {
        'cache': "no-store"
      });
      if (!v3.ok) throw new Error('missing');
      const v4 = (await v3.arrayBuffer()).byteLength;
      if (!v4) throw new Error("empty");
    } catch (v5) {
      return showTamperError(v1), false;
    }
  }
  return vaultLibGuardOk = true, true;
}
vaultAssertLibs();
let STORAGE_KEY = "cookieVaultScan";
async function isIncognitoWindow() {
  try {
    const [v6] = await chrome.tabs.query({
      'active': true,
      'currentWindow': true
    });
    return !!v6?.["incognito"];
  } catch {
    return false;
  }
}
async function resolveStorageKey() {
  const v7 = await isIncognitoWindow();
  return STORAGE_KEY = v7 ? "cookieVaultScan_incognito" : "cookieVaultScan_normal", v7;
}
const state = {
  'parsedEntries': [],
  'selectedIndex': -1,
  'manualDomain': '',
  'searchQuery': '',
  'activeFolder': null,
  'isIncognito': false
};
function $(v8) {
  return document.querySelector(v8);
}
function $all(v9) {
  return Array.from(document.querySelectorAll(v9));
}
function setStatus(v10, v11, v12) {
  v10.innerHTML = '', v10.className = "status" + (v12 ? '\x20' + v12 : '');
  if (v11) {
    const v13 = document.createElement("div");
    v13.className = "status-step", v13.textContent = v11, v10.appendChild(v13);
  }
}
async function setStatusAnimated(v14, v15, v16) {
  v14.innerHTML = '', v14.className = 'status' + (v16 ? '\x20' + v16 : '');
  for (let v17 = 0; v17 < v15.length; v17++) {
    const v18 = document.createElement('div');
    v18.className = "status-step", v18.style.animationDelay = v17 * 0.15 + 's';
    const v19 = document.createElement("div");
    v19.className = "pulse-dot";
    const v20 = document.createElement("span");
    v20.textContent = v15[v17], v18.appendChild(v19), v18.appendChild(v20), v14.appendChild(v18), v17 < v15.length - 1 && (await new Promise(v21 => setTimeout(v21, 400)));
  }
}
function escapeHtml(v22) {
  const v23 = document.createElement("div");
  return v23.textContent = v22, v23.innerHTML;
}
function toBool(v24) {
  if (typeof v24 === "boolean") return v24;
  if (typeof v24 === "string") return v24.trim().toLowerCase() === 'true';
  return !!v24;
}
function showConfirm(v25, v26, v27) {
  const v28 = $("#confirmOverlay"),
    v29 = $("#confirmOkBtn"),
    v30 = $("#confirmCancelBtn");
  return $("#confirmTitle").textContent = v25, $("#confirmBody").textContent = v26, v29.textContent = v27 || "Confirm", v28.classList.remove("hidden"), v29.focus(), new Promise(v31 => {
    function v32(v37) {
      v28.classList.add("hidden"), v29.removeEventListener('click', v33), v30.removeEventListener("click", v34), v28.removeEventListener("click", v35), document.removeEventListener("keydown", v36), v31(v37);
    }
    function v33() {
      v32(true);
    }
    function v34() {
      v32(false);
    }
    function v35(v38) {
      if (v38.target === v28) v32(false);
    }
    function v36(v39) {
      if (v39.key === 'Escape') v32(false);
    }
    v29.addEventListener("click", v33), v30.addEventListener('click', v34), v28.addEventListener("click", v35), document.addEventListener('keydown', v36);
  });
}
function parseNetscape(v40) {
  const v41 = [],
    v42 = v40.split(/\r?\n/);
  for (const v43 of v42) {
    const v44 = v43.trim();
    if (!v44 || v44.startsWith('#')) continue;
    const v45 = v44.split('\x09');
    if (v45.length < 7) continue;
    const [v46,, v47, v48, v49, v50, v51] = v45;
    if (!v50) continue;
    v41.push({
      'domain': v46,
      'path': v47 || '/',
      'secure': v48 === 'TRUE',
      'expirationDate': Number(v49) || undefined,
      'session': Number(v49) === 0,
      'name': v50,
      'value': v51 ?? ''
    });
  }
  return v41;
}
function normalizeJsonCookie(v52) {
  if (!v52 || typeof v52 !== "object" || !v52.name) return null;
  const v53 = typeof v52.url === "string" ? v52.url : '';
  let v54 = typeof v52.domain === "string" ? v52.domain.trim() : '';
  if (!v54 && v53) try {
    v54 = new URL(v53).hostname;
  } catch {}
  let v55 = v52.expirationDate ?? v52.expiry ?? v52.expires;
  if (typeof v55 === "string") {
    const v57 = Number(v55);
    if (Number.isFinite(v57)) v55 = v57;else {
      const v58 = Date.parse(v55);
      v55 = isNaN(v58) ? undefined : v58 / 1000;
    }
  }
  typeof v55 === "number" && v55 > 100000000000 && (v55 /= 1000);
  if (v55 === -1) v55 = undefined;
  let v56 = v52.sameSite;
  if (typeof v56 === 'string') {
    const v59 = v56.toLowerCase();
    if (v59 === "no_restriction" || v59 === "none") v56 = "no_restriction";else {
      if (v59 === 'lax') v56 = "lax";else {
        if (v59 === "strict") v56 = "strict";else v56 = undefined;
      }
    }
  } else v56 = undefined;
  return {
    'name': v52.name,
    'value': String(v52.value ?? ''),
    'domain': v54 || null,
    'path': v52.path || '/',
    'secure': toBool(v52.secure),
    'httpOnly': toBool(v52.httpOnly ?? v52.httponly),
    'sameSite': v56,
    'expirationDate': v55,
    'session': v52.session ?? v55 === undefined
  };
}
function parseJsonCookies(v60) {
  let v61;
  try {
    v61 = JSON.parse(v60);
  } catch {
    return null;
  }
  let v62 = null;
  if (v61 && Array.isArray(v61.cookies)) v62 = v61.cookies;else {
    if (Array.isArray(v61)) v62 = v61;else {
      if (v61 && typeof v61 === "object" && v61.name) v62 = [v61];
    }
  }
  if (v62) {
    const v63 = v62.map(normalizeJsonCookie).filter(Boolean);
    return v63.length ? v63 : null;
  }
  return null;
}
function parseHeaderString(v64) {
  const v65 = v64.trim(),
    v66 = v65.replace(/^cookie:\s*/i, '');
  if (!v66 || !v66.includes('=')) return null;
  const v67 = v66.split(/[;\n]/).map(v69 => v69.trim()).filter(Boolean),
    v68 = [];
  for (const v70 of v67) {
    const v71 = v70.indexOf('=');
    if (v71 === -1) continue;
    const v72 = v70.slice(0, v71).trim(),
      v73 = v70.slice(v71 + 1).trim();
    if (!v72) continue;
    v68.push({
      'name': v72,
      'value': v73,
      'domain': null,
      'path': '/',
      'secure': false,
      'httpOnly': false,
      'session': true
    });
  }
  return v68.length ? v68 : null;
}
function detectAndParse(v74, v75) {
  const v76 = v75.toLowerCase();
  if (v76.endsWith(".json")) {
    const v80 = parseJsonCookies(v74);
    if (v80) return {
      'cookies': v80,
      'format': "json"
    };
  }
  const v77 = parseNetscape(v74);
  if (v77.length) return {
    'cookies': v77,
    'format': "netscape"
  };
  const v78 = parseJsonCookies(v74);
  if (v78) return {
    'cookies': v78,
    'format': "json"
  };
  const v79 = parseHeaderString(v74);
  if (v79) return {
    'cookies': v79,
    'format': "header"
  };
  return null;
}
function guessDomainFromCookies(v81) {
  const v82 = {};
  for (const v84 of v81) {
    const v85 = (v84.domain || '').replace(/^\./, '');
    if (!v85) continue;
    v82[v85] = (v82[v85] || 0) + 1;
  }
  const v83 = Object.entries(v82).sort((v86, v87) => v87[1] - v86[1]);
  return v83.length ? v83[0][0] : null;
}
function splitPath(v88) {
  const v89 = v88.lastIndexOf('/');
  if (v89 === -1) return {
    'folder': '',
    'name': v88
  };
  return {
    'folder': v88.slice(0, v89),
    'name': v88.slice(v89 + 1)
  };
}
async function saveScanToStorage() {
  try {
    await chrome.storage.local.set({
      [STORAGE_KEY]: {
        'parsedEntries': state.parsedEntries,
        'selectedIndex': state.selectedIndex,
        'manualDomain': state.manualDomain,
        'activeFolder': state.activeFolder
      }
    });
  } catch {}
}
async function clearScanStorage() {
  try {
    await chrome.storage.local.remove(STORAGE_KEY);
  } catch {}
}
async function restoreScanFromStorage() {
  try {
    const v90 = await chrome.storage.local.get(STORAGE_KEY),
      v91 = v90?.[STORAGE_KEY];
    if (!v91 || !Array.isArray(v91.parsedEntries) || !v91.parsedEntries.length) return false;
    state.parsedEntries = v91.parsedEntries, state.selectedIndex = typeof v91.selectedIndex === "number" ? v91.selectedIndex : -1, state.manualDomain = v91.manualDomain || '', state.activeFolder = typeof v91.activeFolder === "string" ? v91.activeFolder : null;
    const v92 = state.parsedEntries[state.selectedIndex];
    v92 && v92.folder && state.activeFolder === null && (state.activeFolder = v92.folder);
    renderFileList(), updateDomainPrompt(), updateRestoreButton(), scrollSelectedIntoView();
    const v93 = state.parsedEntries.length;
    return setStatus($("#scanStatus"), "Restored " + v93 + '\x20file' + (v93 === 1 ? '' : 's') + " from last time.", "info"), true;
  } catch {
    return false;
  }
}
async function init() {
  if (!(await verifyIntegrity())) return;
  populateVersionLabels();
  if (await checkForcedUpdate()) return;
  state.isIncognito = await resolveStorageKey(), state.isIncognito && $("#incognitoBadge").classList.remove("hidden"), await restoreScanFromStorage(), await restoreTheme(), checkActiveSession();
}
async function restoreTheme() {
  try {
    const v94 = await chrome.storage.local.get("cookieVaultTheme"),
      v95 = v94?.["cookieVaultTheme"] || "default";
    applyTheme(v95);
  } catch {}
}
function applyTheme(v96) {
  const v97 = document.body;
  v97.classList.remove("theme-royal-purple", "theme-emerald-deep", "theme-crimson-night", "theme-ocean-depths"), v96 !== "default" && v97.classList.add("theme-" + v96), $all(".theme-swatch").forEach(v98 => {
    v98.classList.toggle("active", v98.dataset.theme === v96);
  }), chrome.storage.local.set({
    'cookieVaultTheme': v96
  });
}
$("#themeGrid").addEventListener("click", v99 => {
  const v100 = v99.target.closest(".theme-swatch");
  v100 && applyTheme(v100.dataset.theme);
});
async function checkActiveSession() {
  try {
    const [v101] = await chrome.tabs.query({
      'active': true,
      'currentWindow': true
    });
    if (!v101?.['url']) return;
    const v102 = new URL(v101.url),
      v103 = v102.hostname.replace(/^www\./, '');
    chrome.cookies.getAll({
      'domain': v103
    }, v104 => {
      v104 && v104.length > 0 ? $(".brand-mark").classList.add("session-active") : $(".brand-mark").classList.remove("session-active");
    });
  } catch (v105) {
    console.error("Session guard error:", v105);
  }
}
const dropzone = $("#dropzone"),
  fileInput = $("#fileInput");
dropzone.addEventListener("dragover", v106 => {
  v106.preventDefault(), dropzone.classList.add("drag-over");
}), dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over")), dropzone.addEventListener('drop', v107 => {
  v107.preventDefault(), dropzone.classList.remove("drag-over");
  const v108 = v107.dataTransfer.files[0];
  if (v108) onFileChosen(v108);
}), fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) onFileChosen(fileInput.files[0]);
  fileInput.value = '';
});
const pasteInput = document.getElementById("pasteInput"),
  pasteLoadBtn = document.getElementById("pasteLoadBtn");
pasteLoadBtn.addEventListener("click", async () => {
  const v109 = pasteInput.value.trim();
  if (!v109) {
    setStatus($("#scanStatus"), "Paste some cookie text first.", "err");
    return;
  }
  if (state.parsedEntries.length > 0) {
    const v110 = state.parsedEntries.length,
      v111 = await showConfirm("Replace the current file?", "You currently have " + v110 + " cookie file" + (v110 === 1 ? '' : 's') + " loaded. Loading pasted text will replace " + (v110 === 1 ? 'it' : "them") + '.', "Replace");
    if (!v111) return;
  }
  await processPastedText(v109), pasteInput.value = '';
});
async function processPastedText(v112) {
  const v113 = $("#scanStatus");
  $("#fileListWrap").classList.add("hidden"), $("#domainPrompt").classList.add('hidden'), $("#restoreBtn").classList.add("hidden"), $("#restoreActions").innerHTML = '', setStatus($("#restoreStatus"), '', ''), $("#searchInput").value = '', state.parsedEntries = [], state.selectedIndex = -1, state.manualDomain = '', state.searchQuery = '', state.activeFolder = null;
  const v114 = v112.trim().startsWith('[') || v112.trim().startsWith('{') ? "pasted.json" : "pasted.txt",
    v115 = detectAndParse(v112, v114);
  if (!v115) {
    setStatus(v113, "Couldn't recognize cookie data in the pasted text.", 'err');
    return;
  }
  state.parsedEntries.push({
    'path': v114,
    'folder': '',
    'name': v114,
    'domain': guessDomainFromCookies(v115.cookies),
    'format': v115.format,
    'cookies': v115.cookies
  }), finalizeEntries(v113), await saveScanToStorage();
}
async function onFileChosen(v116) {
  if (state.parsedEntries.length > 0) {
    const v117 = state.parsedEntries.length,
      v118 = await showConfirm("Replace the current file?", "You currently have " + v117 + " cookie file" + (v117 === 1 ? '' : 's') + " loaded. Choosing a new file will replace " + (v117 === 1 ? 'it' : "them") + '.', "Replace");
    if (!v118) return;
  }
  await processFile(v116);
}
async function processFile(v119) {
  const v120 = $("#scanStatus");
  $("#fileListWrap").classList.add("hidden"), $("#domainPrompt").classList.add("hidden"), $("#restoreBtn").classList.add('hidden'), $("#restoreActions").innerHTML = '', setStatus($("#restoreStatus"), '', ''), $("#searchInput").value = '', state.parsedEntries = [], state.selectedIndex = -1, state.manualDomain = '', state.searchQuery = '', state.activeFolder = null;
  const v121 = v119.name.toLowerCase();
  try {
    if (v121.endsWith('.zip')) await scanZip(v119, v120);else {
      if (v121.endsWith('.txt') || v121.endsWith('.json')) await scanSingleFile(v119, v120);else {
        setStatus(v120, "Unsupported file type. Use .zip, .txt, or .json.", "err");
        return;
      }
    }
  } catch (v122) {
    setStatus(v120, "Couldn't read the file: " + v122.message, "err");
    return;
  }
  finalizeEntries(v120), await saveScanToStorage();
}
async function scanSingleFile(v123, v124) {
  setStatus(v124, "Reading file…", "info");
  const v125 = await v123.text(),
    v126 = detectAndParse(v125, v123.name);
  if (!v126) {
    setStatus(v124, "No recognizable cookie data in this file.", 'err');
    return;
  }
  state.parsedEntries.push({
    'path': v123.name,
    'folder': '',
    'name': v123.name,
    'domain': guessDomainFromCookies(v126.cookies),
    'format': v126.format,
    'cookies': v126.cookies
  });
}
async function scanZip(v127, v128) {
  setStatus(v128, "Scanning archive…", "info");
  const v129 = await JSZip.loadAsync(v127),
    v130 = [];
  v129.forEach((v131, v132) => {
    if (v132.dir) return;
    const v133 = v131.toLowerCase();
    if (v133.endsWith('.txt') || v133.endsWith(".json")) v130.push(v132);
  });
  if (!v130.length) {
    setStatus(v128, "No .txt or .json files found inside the archive.", "err");
    return;
  }
  setStatus(v128, "Parsing " + v130.length + " file" + (v130.length === 1 ? '' : 's') + '…', "info");
  for (const v134 of v130) {
    const v135 = await v134.async('string'),
      v136 = detectAndParse(v135, v134.name);
    if (v136) {
      const {
        folder: v137,
        name: v138
      } = splitPath(v134.name);
      state.parsedEntries.push({
        'path': v134.name,
        'folder': v137,
        'name': v138,
        'domain': guessDomainFromCookies(v136.cookies),
        'format': v136.format,
        'cookies': v136.cookies
      });
    }
  }
}
function finalizeEntries(v139) {
  if (!state.parsedEntries.length) {
    setStatus(v139, "Found files, but none contained valid cookie data.", 'err');
    return;
  }
  state.parsedEntries.length === 1 && (state.selectedIndex = 0);
  renderFileList(), updateDomainPrompt(), updateRestoreButton();
  const v140 = state.parsedEntries.length;
  setStatus(v139, "Found " + v140 + " cookie file" + (v140 === 1 ? '' : 's') + '.', 'ok');
}
$("#searchInput").addEventListener("input", v141 => {
  state.searchQuery = v141.target.value.trim().toLowerCase(), renderFileList();
});
function matchesSearch(v142) {
  if (!state.searchQuery) return true;
  const v143 = ((v142.domain || '') + '\x20' + v142.path).toLowerCase();
  return v143.includes(state.searchQuery);
}
function folderIconSvg() {
  return "<svg width=\"11\" height=\"11\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"curr" + "entColor" + '\x22\x20stroke' + "-width=\"" + "2\">\n    " + '<path\x20d=' + "\"M3 7a2 " + "2 0 012-" + "2h4l2 2h" + '8a2\x202\x200\x20' + "012 2v8a" + "2 2 0 01" + "-2 2H5a2" + " 2 0 01-" + "2-2V7z\"/" + '>\x0a\x20\x20</sv' + 'g>';
}
function backArrowSvg() {
  return "<svg width=\"13\" height=\"13\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"curr" + "entColor" + "\" stroke" + "-width=\"" + '2\x22>\x0a\x20\x20\x20\x20' + "<path d=" + "\"M19 12H" + "5M11 18l" + "-6-6 6-6" + "\" stroke" + '-linecap' + "=\"round\"" + " stroke-" + "linejoin" + "=\"round\"" + '/>\x0a\x20\x20</s' + 'vg>';
}
function groupByFolder(v144) {
  const v145 = new Map();
  for (const v146 of v144) {
    const v147 = v146.entry.folder || '';
    if (!v145.has(v147)) v145.set(v147, []);
    v145.get(v147).push(v146);
  }
  return v145;
}
function renderFileList() {
  const v148 = $("#fileListWrap"),
    v149 = $("#fileList"),
    v150 = $("#foundCountBadge"),
    v151 = $("#fileListTitle"),
    v152 = state.parsedEntries.map((v155, v156) => ({
      'entry': v155,
      'idx': v156
    }));
  v150.textContent = state.parsedEntries.length, v149.innerHTML = '';
  if (state.searchQuery) {
    const v157 = v152.filter(({
      entry: v158
    }) => matchesSearch(v158));
    v151.textContent = v157.length + " of " + state.parsedEntries.length + '\x20match';
    if (!v157.length) v149.innerHTML = "<div class=\"no-results\">No files match \"" + escapeHtml(state.searchQuery) + "\".</div>";else for (const [v159, v160] of groupByFolder(v157).entries()) {
      v149.appendChild(renderStaticGroup(v159, v160));
    }
    v148.classList.remove("hidden");
    return;
  }
  if (state.activeFolder !== null) {
    const v161 = v152.filter(({
      entry: v162
    }) => (v162.folder || '') === state.activeFolder);
    v151.textContent = state.activeFolder, v149.appendChild(renderBackHeader());
    for (const {
      entry: v163,
      idx: v164
    } of v161) {
      v149.appendChild(renderFileItem(v163, v164));
    }
    v148.classList.remove("hidden");
    return;
  }
  v151.textContent = "Files found";
  const v153 = v152.filter(({
      entry: v165
    }) => !v165.folder),
    v154 = [...new Set(v152.filter(({
      entry: v166
    }) => v166.folder).map(({
      entry: v167
    }) => v167.folder))];
  for (const v168 of v154) {
    const v169 = v152.filter(({
      entry: v170
    }) => v170.folder === v168).length;
    v149.appendChild(renderFolderButton(v168, v169));
  }
  for (const {
    entry: v171,
    idx: v172
  } of v153) {
    v149.appendChild(renderFileItem(v171, v172));
  }
  v148.classList.remove('hidden');
}
function scrollSelectedIntoView() {
  if (state.selectedIndex === -1) return;
  requestAnimationFrame(() => {
    const v173 = document.querySelector("#fileList .file-item.checked");
    v173 && typeof v173.scrollIntoView === "function" && v173.scrollIntoView({
      'block': "center",
      'behavior': "auto"
    });
  });
}
function renderStaticGroup(v174, v175) {
  const v176 = document.createElement("div");
  v176.className = "file-group";
  if (v174) {
    const v177 = document.createElement("div");
    v177.className = "file-group-header", v177.innerHTML = folderIconSvg() + "<span>" + escapeHtml(v174) + '</span>', v176.appendChild(v177);
  }
  for (const {
    entry: v178,
    idx: v179
  } of v175) {
    v176.appendChild(renderFileItem(v178, v179));
  }
  return v176;
}
function renderFolderButton(v180, v181) {
  const v182 = document.createElement('div');
  return v182.className = "folder-button", v182.innerHTML = "\n    " + folderIconSvg() + "\n    <span class=\"folder-button-name\">" + escapeHtml(v180) + "</span>\n    <span class=\"folder-button-count\">" + v181 + "</span>\n  ", v182.addEventListener('click', () => openFolder(v180)), v182;
}
function renderBackHeader() {
  const v183 = document.createElement("div");
  return v183.className = "folder-back", v183.innerHTML = backArrowSvg() + "<span>All folders</span>", v183.addEventListener("click", () => openFolder(null)), v183;
}
async function openFolder(v184) {
  state.activeFolder = v184, renderFileList(), await saveScanToStorage();
}
function renderFileItem(v185, v186) {
  const v187 = document.createElement("div");
  v187.className = "file-item" + (state.selectedIndex === v186 ? " checked" : '');
  const v188 = v185.domain ? "<div class=\"file-item-domain\">" + escapeHtml(v185.domain) + "</div>" : "<div class=\"file-item-domain unknown\">domain unknown</div>";
  return v187.innerHTML = "\n    <div class=\"radio-dot\"></div>\n    <div class=\"file-item-meta\">\n    " + "  <div c" + 'lass=\x22fi' + "le-item-" + "name\">" + escapeHtml(v185.name) + "</div>\n      " + v188 + "\n    </div>\n    <span class=\"file-item-count\">" + v185.cookies.length + "</span>\n    <span class=\"file-item-format\">" + v185.format + "</span>\n  ", v187.addEventListener('click', () => selectEntry(v186)), v187;
}
async function selectEntry(v189) {
  state.selectedIndex = v189, state.manualDomain = '', $("#manualDomainInput").value = '', renderFileList(), updateDomainPrompt(), updateRestoreButton(), await saveScanToStorage();
}
function updateDomainPrompt() {
  const v190 = $("#domainPrompt"),
    v191 = state.parsedEntries[state.selectedIndex],
    v192 = v191 && !v191.domain;
  v190.classList.toggle("hidden", !v192), v190.classList.remove("needs-attention");
}
$("#manualDomainInput").addEventListener("input", v193 => {
  state.manualDomain = v193.target.value.trim(), $("#domainPrompt").classList.remove("needs-attention"), updateRestoreButton();
});
function updateRestoreButton() {
  $("#restoreBtn").classList.toggle("hidden", state.selectedIndex === -1);
}
function resolvedDomain(v194) {
  const v195 = v194.domain || state.manualDomain || '';
  return v195.replace(/^\./, '').trim();
}
$("#restoreBtn").addEventListener("click", async () => {
  const v196 = $("#restoreStatus"),
    v197 = $("#restoreActions");
  v197.innerHTML = '';
  const v198 = state.parsedEntries[state.selectedIndex];
  if (!v198) return;
  if (!resolvedDomain(v198)) {
    $("#domainPrompt").classList.add("needs-attention"), setStatus(v196, "Type a domain before restoring.", "err");
    return;
  }
  await setStatusAnimated(v196, ["Cookies Injection", "Reading cookie data...", "Processing domains...", "Finalizing restore..."], "info");
  let v199 = 0,
    v200 = 0;
  const v201 = [],
    v202 = new Set(),
    v203 = Date.now() / 1000,
    v204 = resolvedDomain(v198);
  for (const v205 of v198.cookies) {
    const v206 = v205.domain ? v205.domain.replace(/^\./, '') : v204;
    if (!v206) {
      v200++, v201.push(v205.name + ": no domain");
      continue;
    }
    let v207 = toBool(v205.secure),
      v208 = v205.sameSite;
    if (v208 === "no_restriction") v207 = true;
    const v209 = v207 ? "https" : "http",
      v210 = v205.path && v205.path.startsWith('/') ? v205.path : '/',
      v211 = {
        'url': v209 + '://' + v206 + v210,
        'name': v205.name,
        'value': v205.value ?? '',
        'path': v210,
        'secure': v207,
        'httpOnly': toBool(v205.httpOnly)
      };
    v205.domain && v205.domain.startsWith('.') && (v211.domain = v205.domain);
    let v212 = v205.expirationDate;
    if (v212 && v212 <= v203) v212 = undefined;
    if (!v205.session && v212) v211.expirationDate = Number(v212);
    v208 && ["no_restriction", "lax", "strict"].includes(v208) && (v211.sameSite = v208);
    const v213 = await new Promise(v214 => {
      chrome.runtime.sendMessage({
        'type': "SET_COOKIE",
        'details': v211
      }, v214);
    });
    v213?.['ok'] ? (v199++, v202.add(v206)) : (v200++, v201.push(v205.name + '@' + v206 + ':\x20' + (v213?.["error"] || "unknown error")));
  }
  if (v199 && !v200) setStatus(v196, "Restored " + v199 + " cookie" + (v199 === 1 ? '' : 's') + '.', 'ok');else v199 && v200 ? setStatus(v196, v199 + " restored, " + v200 + " failed.", "info") : setStatus(v196, "Nothing could be restored.", "err");
  if (v201.length) {
    const v215 = document.createElement("div");
    v215.className = "error-detail", v215.textContent = v201.slice(0, 3).join(" · ") + (v201.length > 3 ? " · +" + (v201.length - 3) + " more" : ''), v196.appendChild(v215);
  }
  for (const v216 of v202) {
    const v217 = await new Promise(v219 => {
        chrome.runtime.sendMessage({
          'type': "FIND_TABS_FOR_DOMAIN",
          'domain': v216
        }, v219);
      }),
      v218 = v217?.["tabIds"] || [];
    if (v218.length) {
      chrome.runtime.sendMessage({
        'type': "RELOAD_TABS",
        'tabIds': v218
      });
      const v220 = document.createElement("button");
      v220.className = "action-link", v220.textContent = "Reloaded " + v218.length + " open tab" + (v218.length === 1 ? '' : 's') + " on " + v216, v220.disabled = true, v197.appendChild(v220);
    } else {
      const v221 = document.createElement("button");
      v221.className = "action-link", v221.textContent = 'Open\x20' + v216 + '\x20→', v221.addEventListener("click", () => {
        chrome.runtime.sendMessage({
          'type': "OPEN_DOMAIN",
          'domain': v216
        });
      }), v197.appendChild(v221);
    }
  }
}), $("#clearScanBtn").addEventListener('click', async () => {
  const v222 = state.parsedEntries.length;
  if (!v222) return;
  const v223 = await showConfirm("Remove this file?", "This removes " + v222 + " cookie file" + (v222 === 1 ? '' : 's') + (" from Cookie Vault. This can't be undone — you'll need to upload it agai" + 'n\x20to\x20res' + "tore fro" + "m it."), 'Remove');
  if (!v223) return;
  await clearScanStorage(), state.parsedEntries = [], state.selectedIndex = -1, state.manualDomain = '', state.searchQuery = '', state.activeFolder = null, $("#fileListWrap").classList.add("hidden"), $("#domainPrompt").classList.add("hidden"), $("#restoreBtn").classList.add('hidden'), $("#restoreActions").innerHTML = '', $("#searchInput").value = '', setStatus($("#restoreStatus"), '', ''), setStatus($("#scanStatus"), "File removed.", "info");
});
async function getCurrentTab() {
  const [v224] = await chrome.tabs.query({
    'active': true,
    'currentWindow': true
  });
  return v224;
}
async function getCurrentSiteCookies() {
  const v225 = await getCurrentTab();
  if (!v225?.['url'] || !/^https?:/i.test(v225.url)) throw new Error("Open a regular http(s) page first.");
  const v226 = new URL(v225.url),
    v227 = v225.cookieStoreId,
    v228 = v227 ? {
      'url': v225.url,
      'storeId': v227
    } : {
      'url': v225.url
    },
    v229 = await chrome.cookies.getAll(v228),
    v230 = v226.hostname.replace(/^www\./, ''),
    v231 = v227 ? {
      'domain': v230,
      'storeId': v227
    } : {
      'domain': v230
    },
    v232 = await chrome.cookies.getAll(v231),
    v233 = new Set(),
    v234 = [];
  for (const v235 of [...v229, ...v232]) {
    const v236 = v235.name + '\x00' + v235.domain + '\x00' + v235.path;
    if (v233.has(v236)) continue;
    v233.add(v236), v234.push(v235);
  }
  return {
    'tab': v225,
    'url': v226,
    'cookies': v234
  };
}
function toJsonExport(v237) {
  return JSON.stringify(v237.map(v238 => ({
    'name': v238.name,
    'value': v238.value,
    'domain': v238.domain,
    'path': v238.path,
    'secure': v238.secure,
    'httpOnly': v238.httpOnly,
    'sameSite': v238.sameSite,
    'hostOnly': v238.hostOnly,
    'session': v238.session,
    'expirationDate': v238.expirationDate
  })), null, 2);
}
function toNetscapeExport(v239) {
  const v240 = ["# Netscape HTTP Cookie File", "# Exported by Cookies Vault", ''];
  for (const v241 of v239) {
    const v242 = v241.domain,
      v243 = v242.startsWith('.') ? "TRUE" : "FALSE",
      v244 = v241.path || '/',
      v245 = v241.secure ? "TRUE" : "FALSE",
      v246 = Math.floor(v241.expirationDate || 0);
    v240.push([v242, v243, v244, v245, v246, v241.name, v241.value].join('\x09'));
  }
  return v240.join('\x0a');
}
function toHeaderExport(v247) {
  return v247.map(v248 => v248.name + '=' + v248.value).join(';\x20');
}
function downloadText(v249, v250, v251 = "text/plain") {
  const v252 = new Blob([v250], {
      'type': v251
    }),
    v253 = document.createElement('a');
  v253.href = URL.createObjectURL(v252), v253.download = v249, document.body.appendChild(v253), v253.click(), v253.remove(), setTimeout(() => URL.revokeObjectURL(v253.href), 1000);
}
function safeName(v254) {
  return v254.replace(/[^a-z0-9.-]+/gi, '_');
}
async function refreshExportBadge() {
  try {
    const v255 = await getCurrentTab();
    v255?.["url"] && /^https?:/i.test(v255.url) ? $("#exportDomainBadge").textContent = new URL(v255.url).hostname : $("#exportDomainBadge").textContent = "no site";
  } catch {}
}
async function handleExport(v256) {
  const v257 = $("#exportStatus");
  try {
    const {
      url: v258,
      cookies: v259
    } = await getCurrentSiteCookies();
    if (!v259.length) {
      setStatus(v257, "No cookies found for this site.", 'warn');
      return;
    }
    const v260 = safeName(v258.hostname),
      v261 = new Date().toISOString().slice(0, 10);
    if (v256 === "json") downloadText(v260 + '-' + v261 + ".cookies.json", toJsonExport(v259), "application/json");else {
      if (v256 === 'netscape') downloadText(v260 + '-' + v261 + ".cookies.txt", toNetscapeExport(v259), "text/plain");else {
        if (v256 === "header") downloadText(v260 + '-' + v261 + ".header.txt", toHeaderExport(v259), "text/plain");else {
          if (v256 === "copy") {
            await navigator.clipboard.writeText(toJsonExport(v259)), setStatus(v257, "Copied " + v259.length + " cookies to clipboard.", 'success');
            return;
          }
        }
      }
    }
    setStatus(v257, "Exported " + v259.length + " cookies.", "success");
  } catch (v262) {
    setStatus(v257, v262.message || "Export failed.", "error");
  }
}
$("#exportJsonBtn").addEventListener('click', () => handleExport("json")), $("#exportNetscapeBtn").addEventListener("click", () => handleExport("netscape")), $("#exportHeaderBtn").addEventListener("click", () => handleExport("header")), $("#copyJsonBtn").addEventListener("click", () => handleExport("copy")), refreshExportBadge();
const mainPanel = document.querySelector(".panel:not(.fa-view)"),
  faView = $("#freeAccessView"),
  faStatus = $("#faStatus"),
  faInjectBtn = $("#faInjectBtn"),
  faGrid = $("#faGrid"),
  faEmpty = $("#faEmpty"),
  faCount = $("#faCount");
let faSelected = null,
  faServices = [];
function faSetStatus(v263, v264, v265) {
  const v266 = faStatus.querySelector("strong"),
    v267 = faStatus.querySelector('p');
  faStatus.dataset.state = v265 || "idle", [v266, v267].forEach(v268 => {
    v268.classList.remove("fa-text-in"), void v268.offsetWidth, v268.classList.add("fa-text-in");
  }), v266.textContent = v263, v267.textContent = v264 || '';
}
const FA_ORIGIN = "https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app/api/pu" + 'blic/ext' + 'ension',
  FA_API_BASE = FA_ORIGIN + "/cookies",
  FA_SERVICES_URL = FA_ORIGIN + "/services",
  faEscape = v269 => String(v269 == null ? '' : v269).replace(/[&<>"']/g, v270 => ({
    '&': "&amp;",
    '<': "&lt;",
    '>': "&gt;",
    '\x22': '&quot;',
    '\x27': "&#39;"
  })[v270]);
function faLogoMarkup(v271) {
  if (v271.logo_svg && /^\s*<svg[\s>]/i.test(v271.logo_svg)) return v271.logo_svg;
  if (v271.logo_url) return "<img class=\"fa-logo-img\" src=\"" + faEscape(v271.logo_url) + '\x22\x20alt=\x22' + faEscape(v271.name) + '\x22>';
  return "<span class=\"fa-logo-fallback\">" + faEscape((v271.name || '?').slice(0, 1).toUpperCase()) + "</span>";
}
function faRenderServices(v272) {
  faServices = Array.isArray(v272) ? v272 : [], faSelected = null, faInjectBtn.disabled = true, faCount.textContent = String(faServices.length), faGrid.innerHTML = '', faEmpty.classList.toggle("hidden", faServices.length > 0), faServices.forEach(v273 => {
    const v274 = !v273.available,
      v275 = document.createElement("button");
    v275.type = "button", v275.className = "fa-card" + (v274 ? " locked" : ''), v275.dataset.service = v273.slug, v275.style.setProperty("--brand", v273.brand_color || "#facc15");
    if (v274) v275.setAttribute("aria-disabled", "true");
    v275.innerHTML = "<span class=\"fa-icon\">" + faLogoMarkup(v273) + "</span>" + ("<span class=\"fa-name\">" + faEscape(v273.name) + '</span>') + ("<span class=\"fa-meta\">" + (v274 ? "Unavailable" : faEscape(v273.category || '')) + '</span>') + ("<span class=\"fa-check\"><svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"curr" + "entColor" + "\" stroke" + '-width=\x22' + "3.2\" str" + "oke-line" + "cap=\"rou" + "nd\" stro" + "ke-linej" + "oin=\"rou" + "nd\"><pat" + 'h\x20d=\x22M20' + " 6L9 17l" + "-5-5\"/><" + "/svg></s" + "pan>"), v275.addEventListener("click", () => {
      if (v274) return;
      Array.from(faGrid.children).forEach(v276 => v276.classList.toggle('selected', v276 === v275)), faSelected = v273.slug, faInjectBtn.disabled = false, faSetStatus(v273.name + " ready", v273.available + " cookie session" + (v273.available === 1 ? '' : 's') + " available — press Inject & Connect.", 'ready');
    }), faGrid.appendChild(v275);
  });
}
async function faLoadServices() {
  try {
    const v277 = await vaultFetch(FA_SERVICES_URL, {
      'cache': "no-store"
    });
    if (!v277.ok) throw new Error("HTTP " + v277.status);
    const v278 = await v277.json();
    faRenderServices(v278.services || []), faSetStatus("Select a service above", '', "idle");
  } catch (v279) {
    faRenderServices([]), faSetStatus("Could not load services", "Check your connection and reopen the popup.", "error");
  }
}
const FA_VIEW_KEY = "vault_last_view";
function faOpenView(v280) {
  mainPanel.classList.add('hidden'), faView.classList.remove("hidden");
  if (v280 !== false) try {
    chrome.storage.local.set({
      [FA_VIEW_KEY]: 'fa'
    });
  } catch {}
  faLoadServices();
}
$("#freeAccessBtn").addEventListener("click", () => faOpenView(true)), $("#faBackBtn").addEventListener("click", () => {
  faView.classList.add("hidden"), mainPanel.classList.remove('hidden');
  try {
    chrome.storage.local.set({
      [FA_VIEW_KEY]: "main"
    });
  } catch {}
}), (async () => {
  try {
    const v281 = await chrome.storage.local.get(FA_VIEW_KEY);
    if (v281 && v281[FA_VIEW_KEY] === 'fa') faOpenView(false);
  } catch {}
})();
async function faApplyCookies(v282) {
  const v283 = Date.now() / 1000;
  let v284 = 0,
    v285 = 0;
  for (const v286 of v282 || []) {
    const v287 = v286.domain ? String(v286.domain).replace(/^\./, '') : '';
    if (!v287 || !v286.name) {
      v285++;
      continue;
    }
    let v288 = v286.secure === true || v286.secure === "TRUE",
      v289 = typeof v286.sameSite === "string" ? v286.sameSite.toLowerCase() : undefined;
    if (v289 === "none") v289 = "no_restriction";
    if (v289 === "no_restriction") v288 = true;
    const v290 = v286.path && String(v286.path).startsWith('/') ? v286.path : '/',
      v291 = {
        'url': (v288 ? 'https' : "http") + "://" + v287 + v290,
        'name': v286.name,
        'value': v286.value == null ? '' : String(v286.value),
        'path': v290,
        'secure': v288,
        'httpOnly': v286.httpOnly === true
      };
    if (typeof v286.domain === 'string' && v286.domain.startsWith('.')) v291.domain = v286.domain;
    let v292 = v286.expirationDate;
    if (typeof v292 === 'string') v292 = Number(v292);
    if (v292 && v292 > v283) v291.expirationDate = Number(v292);
    if (v289 && ["no_restriction", "lax", "strict"].includes(v289)) v291.sameSite = v289;
    const v293 = await new Promise(v294 => chrome.runtime.sendMessage({
      'type': "SET_COOKIE",
      'details': v291
    }, v294));
    if (v293 && v293.ok) v284++;else v285++;
  }
  return {
    'ok': v284,
    'fail': v285
  };
}
async function faRunInject() {
  if (!faSelected) return;
  const v295 = faView.querySelector(".fa-card.selected .fa-name").textContent;
  if (!vaultUser || !vaultUser.username) {
    faSetStatus("Verification required", "Sign in with Telegram to use the injector.", "warn");
    return;
  }
  if (vaultQuota && vaultQuota.remaining === 0) {
    faSetStatus("Daily limit reached", "You've used all " + (vaultQuota.limit || DAILY_INJECT_LIMIT) + " injections today. Resets at 00:00 UTC.", "error");
    return;
  }
  faInjectBtn.disabled = true, faSetStatus("Fetching session for " + v295 + '…', "Verifying a working profile before inject.", "busy");
  try {
    const v296 = FA_API_BASE + "?service=" + encodeURIComponent(faSelected) + ("&username=" + encodeURIComponent(vaultUser.username)),
      v297 = await vaultFetch(v296, {
        'cache': "no-store"
      });
    if (v297.status === 403) {
      const v303 = await v297.json().catch(() => ({}));
      if (v303 && v303.banned && window.vaultShowBanned) return window.vaultShowBanned(v303);
    }
    if (v297.status === 429) {
      const v304 = await v297.json().catch(() => ({}));
      vaultQuota = {
        'limit': v304.limit || DAILY_INJECT_LIMIT,
        'used': v304.used || DAILY_INJECT_LIMIT,
        'remaining': 0x0
      }, acctPaintQuota(), faSetStatus("Daily limit reached", "You've used all " + vaultQuota.limit + " injections today. Resets in " + resetCountdownText() + " (00:00 UTC).", "error"), faInjectBtn.disabled = false;
      return;
    }
    if (v297.status === 503) {
      const v305 = await v297.json().catch(() => ({}));
      faSetStatus("No valid " + v295 + " session", (v305.rotated ? v305.rotated + " expired set(s) rotated out. " : '') + "No quota used — try again shortly.", "warn"), faInjectBtn.disabled = false;
      return;
    }
    if (v297.status === 404) {
      faSetStatus('No\x20' + v295 + " session available", "Try again in a few minutes.", "warn"), faInjectBtn.disabled = false;
      return;
    }
    if (!v297.ok) throw new Error("HTTP " + v297.status);
    const v298 = await v297.json();
    v298.quota && (vaultQuota = v298.quota, acctPaintQuota());
    const v299 = v298.rotated ? " (rotated " + v298.rotated + " expired set" + (v298.rotated > 1 ? 's' : '') + ')' : '';
    faSetStatus("Injecting " + v295 + " session…", "Applying verified cookies" + v299 + '.', 'busy');
    const {
      ok: v300,
      fail: v301
    } = await faApplyCookies(v298.cookies);
    if (v300 === 0) {
      await vaultFetch(FA_API_BASE, {
        'method': 'POST',
        'headers': {
          'content-type': "application/json"
        },
        'body': JSON.stringify({
          'id': v298.id
        })
      }).catch(() => {});
      throw new Error("Could not apply any cookies");
    }
    const v302 = vaultQuota ? " · " + vaultQuota.remaining + '/' + vaultQuota.limit + " injections left today" : '';
    faSetStatus(v295 + " ready — opening…", v300 + " cookies applied" + (v301 ? ',\x20' + v301 + " skipped" : '') + v302 + '.', "success"), v298.redirect_url && (await chrome.tabs.create({
      'url': v298.redirect_url
    }));
  } catch (v306) {
    faSetStatus("Injection failed", v306 && v306.message || "Try again shortly.", "error");
  } finally {
    faInjectBtn.disabled = false;
  }
}
const FA_ADS_URL = FA_ORIGIN + '/ads';
let adUserKey = "anon";
const adSeenKey = () => "vault_ad_seen_at_v3_" + adUserKey,
  adDeadlineKey = () => "vault_ad_deadline_v3_" + adUserKey,
  adTabKey = () => "vault_ad_tab_v3_" + adUserKey;
let adTabId = null,
  adConfig = {
    'ad': null,
    'watch_seconds': 0xf,
    'cooldown_hours': 0x1
  },
  adSeenAt = 0,
  adBusy = false;
const adBox = $("#adBox"),
  adOpenBtn = $("#adOpenBtn"),
  adCount = $("#adCount"),
  adRing = $("#adRing"),
  adProgress = $("#adProgress"),
  adInjectLabel = () => faInjectBtn.querySelector('span');
function adCooldownActive() {
  const v307 = adConfig.cooldown_hours || 1;
  return adSeenAt > 0 && Date.now() - adSeenAt < v307 * 3600 * 1000;
}
function adRequired() {
  return Boolean(adConfig.ad && adConfig.ad.url) && !adCooldownActive();
}
function faUpdateInjectLabel() {
  const v308 = adInjectLabel();
  if (!v308) return;
  adRequired() ? (v308.textContent = "Watch ads to continue", faInjectBtn.classList.add('is-ad')) : (v308.textContent = "Inject & Connect", faInjectBtn.classList.remove("is-ad"));
}
let adResumeResolve = null;
async function adResolveUserKey() {
  try {
    const v309 = await chrome.storage.local.get("vault_auth"),
      v310 = v309 && v309.vault_auth;
    if (v310 && v310.username) return String(v310.username).toLowerCase();
  } catch {}
  return 'anon';
}
async function adInit() {
  var v311 = 0;
  try {
    adUserKey = await adResolveUserKey();
    const v312 = await chrome.storage.local.get([adSeenKey(), adDeadlineKey(), adTabKey()]);
    adSeenAt = Number(v312 && v312[adSeenKey()]) || 0, v311 = Number(v312 && v312[adDeadlineKey()]) || 0, adTabId = Number(v312 && v312[adTabKey()]) || null;
  } catch {}
  try {
    const v313 = await vaultFetch(FA_ADS_URL, {
      'cache': 'no-store'
    });
    if (v313.ok) adConfig = await v313.json();
  } catch {}
  faUpdateInjectLabel();
  if (v311 && v311 > Date.now() && (await adTabAlive())) {
    if (adBusy) return;
    adBusy = true, faInjectBtn.disabled = true, adRunCountdown(v311).then(() => {
      adBusy = false, faInjectBtn.disabled = false;
    });
  } else v311 && adClearPending();
}
adInit(), window.addEventListener("vault-auth", () => adInit());
async function adTabAlive() {
  if (!adTabId) return false;
  try {
    const v314 = await chrome.tabs.get(adTabId);
    return Boolean(v314 && v314.id);
  } catch {
    return false;
  }
}
function adClearPending() {
  adTabId = null;
  try {
    chrome.storage.local.remove([adDeadlineKey(), adTabKey()]);
  } catch {}
}
async function adOpenTab(v315) {
  const v316 = adConfig.ad && adConfig.ad.url;
  if (!v316) return null;
  try {
    const v317 = await chrome.tabs.create({
      'url': v316,
      'active': v315 === true
    });
    adTabId = v317 && v317.id || null;
    if (adTabId) try {
      await chrome.storage.local.set({
        [adTabKey()]: adTabId
      });
    } catch {}
    return adTabId;
  } catch {
    try {
      window.open(v316, "_blank", "noopener");
    } catch {}
    return null;
  }
}
function adRunCountdown(v318) {
  return new Promise(v319 => {
    const v320 = Math.max(3, Number(adConfig.watch_seconds) || 15),
      v321 = 119.4,
      v322 = document.getElementById('adLoad'),
      v323 = document.getElementById('adHint'),
      v324 = v323 ? v323.textContent : '';
    adBox.classList.remove('hidden');
    if (v322) v322.classList.remove('hidden');
    setTimeout(() => {
      if (v322) v322.classList.add("hidden");
    }, 2500);
    const v325 = () => {
      const v328 = Math.max(0, Math.ceil((v318 - Date.now()) / 1000));
      adCount.textContent = String(v328);
      const v329 = Math.min(1, Math.max(0, (v320 - v328) / v320));
      return adRing.style.strokeDashoffset = String(v321 * v329), adProgress.style.width = v329 * 100 + '%', v328;
    };
    v325();
    let v326 = false;
    const v327 = setInterval(async () => {
      const v330 = v325();
      if (v330 > 0) {
        if (v326) return;
        v326 = true;
        const v331 = await adTabAlive();
        v326 = false;
        if (!v331) {
          clearInterval(v327), adBox.classList.add("hidden");
          if (v323) v323.textContent = v324;
          adClearPending(), faUpdateInjectLabel(), faSetStatus("Sponsor page closed", "Keep the sponsor tab open for the full countdown, then try again.", "error"), v319(false);
        }
        return;
      }
      clearInterval(v327), adBox.classList.add("hidden"), adSeenAt = Date.now();
      try {
        await chrome.storage.local.set({
          [adSeenKey()]: adSeenAt
        });
      } catch {}
      adClearPending(), faUpdateInjectLabel(), v319(true);
    }, 250);
  });
}
async function adWatch() {
  const v332 = Math.max(3, Number(adConfig.watch_seconds) || 15),
    v333 = Date.now() + v332 * 1000;
  try {
    await chrome.storage.local.set({
      [adDeadlineKey()]: v333
    });
  } catch {}
  return await adOpenTab(false), vaultFetch(FA_ADS_URL, {
    'method': "POST",
    'headers': {
      'content-type': "application/json"
    },
    'body': JSON.stringify({
      'id': adConfig.ad && adConfig.ad.id
    })
  }).catch(() => {}), adRunCountdown(v333);
}
if (adOpenBtn) adOpenBtn.addEventListener("click", () => adOpenTab(true));
faInjectBtn.addEventListener("click", async () => {
  if (adBusy) return;
  if (!faSelected) return;
  if (adRequired()) {
    adBusy = true, faInjectBtn.disabled = true;
    let v334 = false;
    try {
      v334 = await adWatch(), v334 && faSetStatus("Ad completed", "Thanks for supporting NFTools — connecting now.", 'busy');
    } finally {
      adBusy = false, faInjectBtn.disabled = false;
    }
    if (!v334) return;
  }
  await faRunInject();
});
const aboutOverlay = $("#aboutOverlay"),
  aboutBtn = $("#aboutToggleBtn"),
  openAbout = () => {
    aboutOverlay.classList.remove("hidden"), aboutBtn.classList.add('active');
  },
  closeAbout = () => {
    aboutOverlay.classList.add("hidden"), aboutBtn.classList.remove('active');
  };
aboutBtn.addEventListener("click", () => {
  aboutOverlay.classList.contains("hidden") ? openAbout() : closeAbout();
}), $("#aboutCloseBtn").addEventListener("click", closeAbout), aboutOverlay.addEventListener("click", v335 => {
  if (v335.target === aboutOverlay) closeAbout();
}), document.addEventListener("keydown", v336 => {
  if (v336.key === "Escape" && !aboutOverlay.classList.contains("hidden")) closeAbout();
});
const VAULT_AUTH_KEY = "vault_auth",
  FA_QUOTA_URL = FA_ORIGIN + "/quota",
  DAILY_INJECT_LIMIT = 10,
  acctBtn = $("#accountToggleBtn"),
  acctOverlay = $("#accountOverlay"),
  acctUsernameEl = $("#acctUsername"),
  acctTitleEl = $("#acctTitle"),
  acctQuotaText = $("#acctQuotaText"),
  acctQuotaBar = $("#acctQuotaBar"),
  acctQuotaNote = $("#acctQuotaNote"),
  acctInitial = $("#acctInitial"),
  acctStatUsed = $("#acctStatUsed"),
  acctStatLeft = $("#acctStatLeft"),
  acctStatReset = $("#acctStatReset");
let vaultUser = null,
  vaultQuota = null;
const faQuotaText = $("#faQuotaText"),
  faQuotaBar = $("#faQuotaBar"),
  faQuotaNote = $("#faQuotaNote"),
  faQuotaCountdown = $("#faQuotaCountdown");
function msUntilReset() {
  const v337 = new Date(),
    v338 = Date.UTC(v337.getUTCFullYear(), v337.getUTCMonth(), v337.getUTCDate() + 1, 0, 0, 0, 0);
  return Math.max(v338 - v337.getTime(), 0);
}
function resetCountdownText() {
  const v339 = msUntilReset(),
    v340 = Math.floor(v339 / 3600000),
    v341 = Math.floor(v339 % 3600000 / 60000),
    v342 = Math.floor(v339 % 60000 / 1000);
  return v340 > 0 ? v340 + 'h\x20' + v341 + 'm' : v341 > 0 ? v341 + 'm\x20' + v342 + 's' : v342 + 's';
}
function acctPaintQuota() {
  const v343 = vaultQuota && vaultQuota.limit || DAILY_INJECT_LIMIT,
    v344 = vaultQuota ? vaultQuota.remaining : null,
    v345 = acctQuotaBar.parentElement,
    v346 = faQuotaBar ? faQuotaBar.parentElement : null,
    v347 = resetCountdownText(),
    v348 = "Resets in " + v347 + " · daily at 00:00 UTC";
  if (v344 == null) {
    acctQuotaText.textContent = "— / " + v343, acctQuotaBar.style.width = '0%', acctQuotaNote.textContent = "Checking your quota… " + v348;
    if (acctStatUsed) acctStatUsed.textContent = '—';
    if (acctStatLeft) acctStatLeft.textContent = '—';
    if (acctStatReset) acctStatReset.textContent = v347;
    acctBtn.classList.remove("has-quota", "low", 'out');
    if (faQuotaText) {
      faQuotaText.textContent = "— / " + v343, faQuotaBar.style.width = '0%', faQuotaNote.textContent = "Resets daily at 00:00 UTC";
      if (faQuotaCountdown) faQuotaCountdown.textContent = v347;
    }
    return;
  }
  const v349 = v343 - v344;
  acctQuotaText.textContent = v344 + " / " + v343 + " left", acctQuotaBar.style.width = Math.round(v344 / v343 * 100) + '%', acctQuotaNote.textContent = (v344 === 0 ? "You've used all " + v343 + " injections today. " : "Used " + v349 + " of " + v343 + " today · ") + v348;
  if (acctStatUsed) acctStatUsed.textContent = String(v349);
  if (acctStatLeft) acctStatLeft.textContent = String(v344);
  if (acctStatReset) acctStatReset.textContent = v347;
  v345.classList.toggle("low", v344 > 0 && v344 <= 3), v345.classList.toggle("out", v344 === 0), acctBtn.classList.add("has-quota"), acctBtn.classList.toggle("low", v344 > 0 && v344 <= 3), acctBtn.classList.toggle("out", v344 === 0);
  if (faQuotaText) {
    faQuotaText.textContent = v349 + " / " + v343 + " used", faQuotaBar.style.width = Math.round(v344 / v343 * 100) + '%', faQuotaNote.textContent = v344 === 0 ? "Daily limit reached · resets 00:00 UTC" : v344 + " left today · resets 00:00 UTC";
    if (faQuotaCountdown) faQuotaCountdown.textContent = v347;
    v346 && (v346.classList.toggle("low", v344 > 0 && v344 <= 3), v346.classList.toggle('out', v344 === 0));
  }
}
setInterval(() => acctPaintQuota(), 1000);
async function acctRefreshQuota() {
  if (!vaultUser || !vaultUser.username) return;
  try {
    const v350 = await vaultFetch(FA_QUOTA_URL + "?username=" + encodeURIComponent(vaultUser.username), {
        'cache': 'no-store'
      }),
      v351 = await v350.json().catch(() => ({}));
    if (v350.status === 403 && v351 && v351.banned && window.vaultShowBanned) {
      window.vaultShowBanned({
        ...v351,
        'username': vaultUser.username
      });
      return;
    }
    if (!v350.ok) throw new Error("HTTP " + v350.status);
    vaultQuota = v351;
  } catch {
    vaultQuota = null;
  }
  acctPaintQuota();
}
async function acctInit() {
  try {
    const v352 = await chrome.storage.local.get(VAULT_AUTH_KEY),
      v353 = v352 && v352[VAULT_AUTH_KEY];
    if (!v353 || !v353.token || !v353.username) return;
    vaultUser = v353, acctBtn.classList.remove("hidden"), document.getElementById("logoutBtn")?.["classList"]["remove"]('hidden'), acctUsernameEl.textContent = '@' + v353.username, acctTitleEl.textContent = v353.display_name || "Signed in";
    if (acctInitial) {
      const v354 = (v353.display_name || v353.username || '?').trim();
      acctInitial.textContent = (v354[0] || '?').toUpperCase();
    }
    acctPaintQuota(), acctRefreshQuota();
  } catch {}
}
const openAccount = () => {
    acctOverlay.classList.remove('hidden'), acctBtn.classList.add("active"), acctRefreshQuota();
  },
  closeAccount = () => {
    acctOverlay.classList.add("hidden"), acctBtn.classList.remove("active");
  };
acctBtn.addEventListener('click', () => {
  acctOverlay.classList.contains("hidden") ? openAccount() : closeAccount();
}), $("#acctCloseBtn").addEventListener('click', closeAccount), acctOverlay.addEventListener("click", v355 => {
  if (v355.target === acctOverlay) closeAccount();
}), document.addEventListener("keydown", v356 => {
  if (v356.key === "Escape" && !acctOverlay.classList.contains("hidden")) closeAccount();
});
const logoutBtn = $("#logoutBtn"),
  logoutOverlay = $("#logoutOverlay"),
  logoutDialog = logoutOverlay ? logoutOverlay.querySelector(".logout-dialog") : null;
function openLogoutConfirm() {
  closeAccount();
  if (!logoutOverlay) return vaultLogout();
  const v357 = $("#logoutSub");
  v357 && vaultUser && vaultUser.username && (v357.textContent = '@' + vaultUser.username + (" will be signed out. You'll need to verify with Telegram again to unlock" + " premium" + " access.")), logoutDialog?.["classList"]["remove"]('bye'), logoutOverlay.classList.remove("hidden");
}
function closeLogoutConfirm() {
  logoutOverlay?.["classList"]["add"]('hidden');
}
async function vaultLogout() {
  if (logoutDialog) {
    logoutDialog.classList.add("bye");
    const v358 = $("#logoutTitle");
    if (v358) v358.textContent = "Signing you out…";
  }
  document.body.classList.add("vault-signing-out");
  try {
    await chrome.storage.local.remove([VAULT_AUTH_KEY, "vault_auth_pending", "vault_fa_view"]);
  } catch {}
  await new Promise(v359 => setTimeout(v359, 460));
  try {
    window.location.reload();
  } catch {}
}
logoutBtn?.["addEventListener"]("click", openLogoutConfirm), $("#acctLogoutBtn")?.["addEventListener"]("click", openLogoutConfirm), $("#logoutCancelBtn")?.["addEventListener"]("click", closeLogoutConfirm), $("#logoutConfirmBtn")?.["addEventListener"]("click", vaultLogout), logoutOverlay?.["addEventListener"]("click", v360 => {
  if (v360.target === logoutOverlay) closeLogoutConfirm();
}), document.addEventListener("keydown", v361 => {
  if (v361.key === "Escape" && logoutOverlay && !logoutOverlay.classList.contains("hidden")) closeLogoutConfirm();
}), acctInit(), window.addEventListener("vault-auth", () => acctInit()), chrome.storage?.["onChanged"]?.["addListener"]((v362, v363) => {
  v363 === 'local' && v362[VAULT_AUTH_KEY] && (vaultUser = null, acctBtn.classList.add('hidden'), document.getElementById("logoutBtn")?.["classList"]["add"]('hidden'), acctInit(), adInit());
});
const SELF_PATH = "ui/popup.js",
  BG_PATH_INT = "scripts/background.js",
  SIZE_PATH_INT = "lib/vault-size.js",
  MANIFEST_RE = /\/\/ <integrity-manifest>[\s\S]*?\/\/ <\/integrity-manifest>/,
  BG_MANIFEST_RE_INT = /\/\/ <bg-integrity-manifest>[\s\S]*?\/\/ <\/bg-integrity-manifest>/,
  SIZE_MANIFEST_RE_INT = /\/\/ <size-manifest>[\s\S]*?\/\/ <\/size-manifest>/;
async function sha256Hex(v364) {
  const v365 = await crypto.subtle.digest("SHA-256", v364);
  return Array.from(new Uint8Array(v365)).map(v366 => v366.toString(16).padStart(2, '0')).join('');
}
async function verifyIntegrity() {
  let v367;
  try {
    v367 = Object.entries(EXPECTED_HASHES);
    if (!v367.length) return true;
  } catch (v368) {
    return true;
  }
  for (const [v369, v370] of v367) {
    let v371;
    try {
      const v372 = await fetch(chrome.runtime.getURL(v369), {
        'cache': "no-store"
      });
      if (!v372.ok) throw new Error("missing");
      if (v369 === SELF_PATH) {
        const v373 = (await v372.text()).replace(MANIFEST_RE, '');
        v371 = await sha256Hex(new TextEncoder().encode(v373));
      } else {
        if (v369 === BG_PATH_INT) {
          const v374 = (await v372.text()).replace(BG_MANIFEST_RE_INT, '');
          v371 = await sha256Hex(new TextEncoder().encode(v374));
        } else {
          if (v369 === SIZE_PATH_INT) {
            const v375 = (await v372.text()).replace(SIZE_MANIFEST_RE_INT, '');
            v371 = await sha256Hex(new TextEncoder().encode(v375));
          } else v371 = await sha256Hex(await v372.arrayBuffer());
        }
      }
    } catch (v376) {
      return console.error("Integrity check could not read " + v369, v376), showTamperError(v369), false;
    }
    if (v371 !== v370) return console.error("Integrity violation in " + v369), showTamperError(v369), false;
  }
  if (typeof window.vaultVerifyBundleSize !== 'function') return showTamperError("lib/vault-size.js"), false;
  try {
    const v377 = await window.vaultVerifyBundleSize();
    if (v377 && v377.ok === false) return showTamperError("bundle size"), false;
  } catch (v378) {
    return showTamperError("bundle size"), false;
  }
  return true;
}
const VAULT_VERSION_ENDPOINT = "https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app/api/pu" + "blic/ext" + 'ension/v' + 'ersion',
  VAULT_LINKS_ENDPOINT = "https://project--90c2f89e-1987-47d7-8a1e-bbdbf2ccfb39.lovable.app/api/pu" + "blic/ext" + 'ension/l' + 'inks';
function applyChannelLinks(v379) {
  if (!v379) return;
  const v380 = v382 => String(v382).replace(/^https?:\/\//, '').replace(/\/$/, ''),
    v381 = (v383, v384, v385) => {
      const v386 = document.getElementById(v383);
      if (!v386 || !v384) return;
      v386.href = v384;
      if (v385) v386.textContent = v380(v384);
    };
  v381("footerVaultLink", v379.cookies_vault_url), v381("footerNftoolsLink", v379.nftools_url), v381("aboutVaultLink", v379.cookies_vault_url, true), v381("aboutNftoolsLink", v379.nftools_url, true);
}
(async () => {
  try {
    const v387 = await chrome.storage.local.get("vault_channel_links");
    applyChannelLinks(v387.vault_channel_links);
  } catch (v388) {}
  try {
    const v389 = await vaultFetch(VAULT_LINKS_ENDPOINT, {
      'cache': "no-store"
    });
    if (!v389.ok) return;
    const v390 = await v389.json();
    applyChannelLinks(v390), await chrome.storage.local.set({
      'vault_channel_links': v390
    });
  } catch (v391) {}
})();
async function getOfficialDownloadUrl() {
  try {
    const {
      vault_latest_release: v392
    } = await chrome.storage.local.get("vault_latest_release");
    if (v392 && v392.download_url) return v392.download_url;
  } catch (v393) {}
  try {
    const v394 = await vaultFetch(VAULT_VERSION_ENDPOINT, {
        'cache': "no-store"
      }),
      v395 = await v394.json();
    if (v395 && v395.download_url) return v395.download_url;
  } catch (v396) {}
  return "https://t.me/cookies_vault";
}
function showTamperError(v397) {
  document.documentElement.style.height = "100%", document.body.style.margin = '0', document.body.innerHTML = "\n    <div style=\"position:fixed;inset:0;width:100%;height:100%;min-heigh" + "t:480px;" + "padding:" + "32px 26p" + 'x;box-si' + 'zing:bor' + "der-box;" + 'display:' + 'flex;fle' + "x-direct" + 'ion:colu' + 'mn;align' + '-items:c' + "enter;ju" + "stify-co" + "ntent:ce" + "nter;tex" + 't-align:' + "center;f" + 'ont-fami' + "ly:syste" + "m-ui,-ap" + "ple-syst" + "em,'Sego" + "e UI',sa" + 'ns-serif' + ";backgro" + "und:radi" + 'al-gradi' + "ent(120%" + " 80% at " + '50%\x20-10%' + ", rgba(2" + "39,68,68" + ",.18), t" + "ranspare" + "nt 60%)," + "radial-g" + "radient(" + "90% 60% " + "at 50% 1" + '10%,\x20rgb' + "a(250,20" + "4,21,.08" + "), trans" + "parent 6" + '0%),#050' + '80f;\x22>\x0a\x20' + "     <di" + "v style=" + "\"width:6" + "8px;heig" + "ht:68px;" + "margin:0" + " auto 18" + "px;borde" + 'r-radius' + ":20px;ba" + "ckground" + ':linear-' + "gradient" + "(135deg," + "#fca5a5," + "#ef4444 " + '45%,#b91' + "c1c);dis" + "play:fle" + "x;align-" + "items:ce" + "nter;jus" + "tify-con" + "tent:cen" + "ter;font" + "-size:32" + "px;font-" + 'weight:9' + "00;color" + ":#05080f" + ";box-sha" + "dow:0 0 " + '0\x208px\x20rg' + "ba(239,6" + "8,68,.08" + "), 0 12p" + "x 30px r" + "gba(239," + "68,68,.2" + "8);\">!</" + 'div>\x0a\x20\x20\x20' + '\x20\x20\x20<div\x20' + "style=\"f" + "ont-size" + ":10px;le" + "tter-spa" + "cing:.18" + 'em;text-' + "transfor" + 'm:upperc' + "ase;colo" + 'r:#ef444' + "4;font-w" + "eight:80" + "0;margin" + "-bottom:" + "8px;\">Se" + "curity c" + "heck fai" + "led</div" + ">\n      " + "<h1 styl" + 'e=\x22font-' + 'size:19p' + "x;margin" + ":0 0 10p" + "x;color:" + "#fff;\">M" + "odified " + ("build detected</h1>\n      <p style=\"font-size:12.5px;line-height:1.6;col" + "or:#94a3" + "b8;margi" + 'n:0\x200\x2014' + "px;max-w" + "idth:300" + 'px;\x22>Coo' + "kies Vau" + "lt found" + " changes" + '\x20to\x20its\x20' + "files an" + "d will n" + 'ot\x20run.\x20' + "Reinstal" + "l the of" + "ficial b" + 'uild\x20to\x20' + "continue" + '.</p>\x0a\x20\x20' + "    <div" + " style=\"" + "display:" + 'inline-b' + "lock;pad" + 'ding:7px' + " 12px;bo" + "rder-rad" + "ius:10px" + ";backgro" + "und:#0b1" + "220;bord" + "er:1px s" + "olid #1e" + '293b;col' + "or:#6474" + "8b;font-" + "size:11p" + "x;font-w" + 'eight:70' + "0;margin" + "-bottom:" + "20px;wor" + "d-break:" + "break-al" + "l;max-wi" + "dth:300p" + 'x;\x22>') + v397 + ("</div>\n      <a id=\"vaultOfficialDl\" href=\"https://t.me/cookies_vault\" t" + "arget=\"_" + 'blank\x22\x20r' + "el=\"noop" + "ener\"\n  " + "       s" + "tyle=\"di" + "splay:bl" + "ock;widt" + 'h:100%;m' + "ax-width" + ":300px;b" + "ox-sizin" + "g:border" + '-box;pad' + "ding:14p" + "x 18px;b" + "order-ra" + "dius:14p" + 'x;text-d' + "ecoratio" + "n:none;b" + "ackgroun" + 'd:linear' + "-gradien" + "t(90deg," + "#fde68a," + "#facc15 " + '40%,#ca8' + "a04);col" + "or:#0508" + "0f;font-" + "weight:9" + "00;font-" + "size:14p" + "x;box-sh" + "adow:0 1" + '2px\x2026px' + " rgba(25" + "0,204,21" + ",.22);\">" + "\n       " + " Downloa" + 'd\x20offici' + "al versi" + 'on\x0a\x20\x20\x20\x20\x20' + " </a>\n  " + "    <p s" + "tyle=\"ma" + "rgin-top" + ":16px;fo" + "nt-size:" + "11px;col" + "or:#4755" + '69;line-' + "height:1" + ".5;max-w" + "idth:300" + "px;\">Dow" + "nloads c" + "ome from" + " the off" + "icial Co" + "okies Va" + "ult rele" + "ase chan" + "nel.</p>" + "\n      <" + 'div\x20styl' + "e=\"margi" + "n-top:18" + "px;font-" + "size:10p" + "x;letter" + "-spacing" + ":.16em;t" + "ext-tran" + "sform:up" + "percase;" + "color:#3" + "34155;fo" + 'nt-weigh' + "t:700;\">" + 'Cookies\x20' + "Vault</d" + 'iv>\x0a\x20\x20\x20\x20' + "</div>\n " + '\x20'), getOfficialDownloadUrl().then(v398 => {
    const v399 = document.getElementById("vaultOfficialDl");
    if (v399) v399.href = v398;
  });
}
function populateVersionLabels() {
  try {
    const v400 = chrome.runtime.getManifest().version,
      v401 = document.getElementById("versionPill"),
      v402 = document.getElementById("versionFull");
    if (v401) v401.textContent = 'v' + v400;
    if (v402) v402.textContent = v400;
  } catch (v403) {}
}
function isOutdated(v404, v405) {
  const v406 = String(v404).split('.').map(Number),
    v407 = String(v405).split('.').map(Number);
  for (let v408 = 0; v408 < Math.max(v406.length, v407.length); v408++) {
    const v409 = v406[v408] || 0,
      v410 = v407[v408] || 0;
    if (v409 !== v410) return v409 < v410;
  }
  return false;
}
function showUpdateRequired(v411, v412) {
  document.documentElement.style.height = "100%", document.body.style.margin = '0', document.body.innerHTML = "\n    <div style=\"position:fixed;inset:0;width:100%;height:100%;min-heigh" + "t:480px;" + "padding:" + "32px 26p" + 'x;box-si' + 'zing:bor' + "der-box;" + "display:" + "flex;fle" + "x-direct" + "ion:colu" + 'mn;align' + "-items:c" + 'enter;ju' + "stify-co" + "ntent:ce" + 'nter;tex' + "t-align:" + "center;f" + "ont-fami" + "ly:syste" + "m-ui,-ap" + 'ple-syst' + "em,'Sego" + "e UI',sa" + "ns-serif" + ';backgro' + "und:radi" + "al-gradi" + "ent(120%" + " 80% at " + "50% -10%" + ", rgba(2" + "50,204,2" + "1,.16), " + 'transpar' + "ent 60%)" + ",radial-" + 'gradient' + "(90% 60%" + " at 50% " + "110%, rg" + 'ba(202,1' + "38,4,.12" + '),\x20trans' + 'parent\x206' + "0%),#050" + "80f;colo" + "r:#e2e8f" + '0;\x22>\x0a\x20\x20\x20' + "   <div " + "style=\"w" + 'idth:68p' + 'x;height' + ':68px;ma' + "rgin:0 a" + 'uto\x2018px' + ";border-" + "radius:2" + "0px;back" + "ground:l" + "inear-gr" + "adient(1" + "35deg,#f" + "de68a,#f" + 'acc15\x2045' + '%,#ca8a0' + "4);displ" + "ay:flex;" + "align-it" + "ems:cent" + "er;justi" + "fy-conte" + 'nt:cente' + 'r;font-s' + 'ize:32px' + ";font-we" + "ight:900" + ";color:#" + "05080f;b" + "ox-shado" + "w:0 0 0 " + "8px rgba" + '(250,204' + ",21,.08)" + ", 0 12px" + " 30px rg" + "ba(250,2" + "04,21,.2" + "8);\">!</" + "div>\n   " + "   <div " + 'style=\x22f' + 'ont-size' + ":10px;le" + "tter-spa" + "cing:.18" + "em;text-" + 'transfor' + "m:upperc" + "ase;colo" + "r:#facc1" + "5;font-w" + "eight:80" + "0;margin" + '-bottom:' + '8px;\x22>Ma' + "ndatory " + "update</" + "div>\n   " + "   <h1 s" + "tyle=\"fo" + "nt-size:" + '19px;mar' + 'gin:0\x200\x20' + '10px;col' + "or:#fff;" + ("\">A new version is available</h1>\n      <p style=\"font-size:12.5px;line-" + "height:1" + '.6;color' + ":#94a3b8" + ";margin:" + "0 0 18px" + ";max-wid" + "th:300px" + ";\">This " + 'build\x20of' + " Cookies" + " Vault i" + 's\x20outdat' + "ed and h" + "as been " + "disabled" + " for you" + "r securi" + "ty. Inst" + 'all\x20the\x20' + "latest r" + "elease t" + "o contin" + "ue.</p>\n" + "      <d" + "iv style" + "=\"displa" + "y:flex;a" + 'lign-ite' + "ms:cente" + 'r;justif' + "y-conten" + 't:center' + ";gap:10p" + "x;margin" + "-bottom:" + "20px;fon" + 't-size:1' + '2px;font' + "-weight:" + "800;\">\n " + "       <" + "span sty" + "le=\"padd" + "ing:7px " + "12px;bor" + "der-radi" + "us:10px;" + "backgrou" + 'nd:#0b12' + "20;borde" + "r:1px so" + 'lid\x20#1e2' + "93b;colo" + "r:#64748" + "b;\">curr" + 'ent\x20v') + v411 + ("</span>\n        <span style=\"color:#475569;font-size:13px;\">→</span>\n   " + "     <sp" + "an style" + "=\"paddin" + "g:7px 12" + "px;borde" + "r-radius" + ":10px;ba" + 'ckground' + ":rgba(25" + '0,204,21' + ',.12);co' + "lor:#fac" + "c15;bord" + 'er:1px\x20s' + "olid rgb" + "a(250,20" + '4,21,.35' + ');\x22>late' + "st v") + v412.version + "</span>\n      </div>\n      <a id=\"vaultUpdateDl\" href=\"" + (v412.download_url || "https://t.me/cookies_vault") + ("\" target=\"_blank\" rel=\"noopener\"\n         style=\"display:block;width:100" + "%;max-wi" + "dth:300p" + 'x;box-si' + "zing:bor" + "der-box;" + "padding:" + "14px 18p" + "x;border" + '-radius:' + '14px;tex' + 't-decora' + "tion:non" + "e;backgr" + "ound:lin" + "ear-grad" + "ient(90d" + "eg,#fde6" + '8a,#facc' + "15 40%,#" + 'ca8a04);' + 'color:#0' + "5080f;fo" + "nt-weigh" + 't:900;fo' + 'nt-size:' + "14px;box" + "-shadow:" + "0 12px 2" + "6px rgba" + "(250,204" + ",21,.22)" + ";\">\n    " + "    Down" + "load lat" + "est vers" + "ion\n    " + "  </a>\n " + '\x20\x20\x20\x20\x20<p\x20' + 'style=\x22m' + 'argin-to' + 'p:16px;f' + "ont-size" + ":11px;co" + "lor:#475" + "569;line" + "-height:" + '1.5;max-' + 'width:30' + "0px;\">Un" + 'zip\x20and\x20' + "reload t" + 'he\x20exten' + "sion at " + "chrome:/" + "/extensi" + 'ons\x20afte' + "r instal" + "ling.</p" + ">\n      " + '<div\x20sty' + "le=\"marg" + "in-top:1" + "8px;font" + "-size:10" + 'px;lette' + "r-spacin" + 'g:.16em;' + "text-tra" + "nsform:u" + 'ppercase' + ";color:#" + '334155;f' + 'ont-weig' + 'ht:700;\x22' + '>Cookies' + '\x20Vault</' + "div>\n   " + '\x20</div>\x0a' + '\x20\x20');
}
async function checkForcedUpdate() {
  const v413 = chrome.runtime.getManifest().version;
  let v414 = null;
  try {
    const v415 = await chrome.storage.local.get("vault_latest_release");
    if (v415 && v415.vault_latest_release) v414 = v415.vault_latest_release;
  } catch (v416) {}
  try {
    const v417 = await vaultFetch(VAULT_VERSION_ENDPOINT, {
      'cache': "no-store"
    });
    if (v417.ok) {
      const v418 = await v417.json();
      if (v418 && v418.version) {
        v414 = v418;
        try {
          await chrome.storage.local.set({
            'vault_latest_release': v418
          });
        } catch (v419) {}
      }
    }
  } catch (v420) {}
  if (v414 && v414.version && isOutdated(v413, v414.version)) return showUpdateRequired(v413, v414), true;
  return false;
}
queueMicrotask(init), (() => {
  const v421 = document.querySelector('.app');
  if (!v421) return;
  setTimeout(() => v421.classList.add("anim-done"), 500);
})(), (() => {
  const v422 = () => Array.from(document.querySelectorAll(".overlay")),
    v423 = () => {
      const v425 = v422().some(v426 => !v426.classList.contains("hidden"));
      document.body.classList.toggle("modal-open", v425);
    },
    v424 = new MutationObserver(v423);
  v422().forEach(v427 => v424.observe(v427, {
    'attributes': true,
    'attributeFilter': ['class']
  })), v423();
})();
// <integrity-manifest>
const EXPECTED_HASHES = {
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
};
// </integrity-manifest>
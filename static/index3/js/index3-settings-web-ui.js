/* Settings web-search/network configuration split from index3-settings-ui.js. */
const WEB_SETTINGS_DEFAULTS = {
  WEB_SETTINGS_SCHEMA_VERSION: 12,
  SEARXNG_URL: "",
  SEARXNG_API_PATH: "/search",
  SEARCH_PROVIDER: "uapipro",
  SEARCH_FALLBACK_PROVIDER: "none",
  WHOOGLE_URL: "",
  EXTERNAL_SEARCH_URL: "",
  EXTERNAL_SEARCH_API_KEY: "",
  EXTERNAL_IMAGE_SEARCH_URL: "",
  EXTERNAL_IMAGE_SEARCH_API_KEY: "",
  UAPIPRO_BASE_URL: "https://uapis.cn/api/v1",
  UAPIPRO_API_KEY: "",
  IMAGE_SEARCH_PROVIDER: "external",
  IMAGE_SEARCH_FALLBACK_PROVIDER: "serper",
  IMAGE_SEARCH_MAX_QUERIES: 3,
  CONTENT_PROVIDER: "auto",
  CONTENT_FALLBACK_PROVIDER: "tavily",
  SERPER_API_KEY: "",
  TAVILY_API_KEY: "",
  TAVILY_EXTRACT_DEPTH: "basic",
  PLAYWRIGHT_ENABLE: 1,
  WEB_FETCH_AUTO_RENDER: 1,
  BROWSER_GEO_ENABLE: 0,
  AUTO_WEB_K_RESULTS: 6,
  MAX_WEB_SEARCH_CALLS: 1,
  AUTO_WEB_FAST_MAX_PAGES: 2,
  AUTO_WEB_MAX_PAGES: 3,
  AUTO_WEB_FETCH_WORKERS: 6,
  AUTO_WEB_PAGE_TIMEOUT: 4,
  AUTO_WEB_PAGE_MAX_CHARS: 4500,
  AUTO_WEB_PAGE_SNIPPET_CHARS: 1800,
};

const REMOVED_SEARCH_PROVIDER_VALUES = new Set([
  ['browser', 'search'].join('_'),
]);
function isRemovedSearchProvider(value){
  const provider = String(value || '').trim().toLowerCase();
  return !!provider && REMOVED_SEARCH_PROVIDER_VALUES.has(provider);
}

const LEGACY_WEB_SETTINGS_DEFAULTS_V2 = {
  SEARXNG_URL: "http://127.0.0.1:8080",
  WHOOGLE_URL: "http://127.0.0.1:5000",
  IMAGE_SEARCH_MAX_QUERIES: 4,
  TAVILY_EXTRACT_DEPTH: "advanced",
  AUTO_WEB_K_RESULTS: 8,
  MAX_WEB_SEARCH_CALLS: 2,
  AUTO_WEB_FAST_MAX_PAGES: 2,
  AUTO_WEB_MAX_PAGES: 6,
  AUTO_WEB_FETCH_WORKERS: 12,
  AUTO_WEB_PAGE_TIMEOUT: 6,
  AUTO_WEB_PAGE_MAX_CHARS: 4500,
  AUTO_WEB_PAGE_SNIPPET_CHARS: 1800,
};
const REMOVED_WEB_SETTINGS_KEYS = [
  "WEB_SEARCH_PLANNER_MODEL",
  "WEB_SEARCH_PLANNER_THINKING_TYPE",
  "QUERY_GENERATION_MODEL",
  "QUERY_GENERATION_THINKING_TYPE",
  "TOOL_PREFETCH_MODEL",
  "TOOL_PREFETCH_THINKING_TYPE",
  "AUTO_WEB_MAX_QUERIES",
];
function stripRemovedWebSettingsKeys(value){
  const out = value && typeof value === "object" && !Array.isArray(value) ? { ...value } : {};
  REMOVED_WEB_SETTINGS_KEYS.forEach(key => { delete out[key]; });
  return out;
}
function hasRemovedWebSettingsKeys(value){
  return !!(value && typeof value === "object" && REMOVED_WEB_SETTINGS_KEYS.some(key => Object.prototype.hasOwnProperty.call(value, key)));
}

function getWebSettings(){
  try{
    const parsed = JSON.parse(readAccountScopedSettingItem(WEB_SETTINGS_KEY) || "{}") || {};
    const removedKeysChanged = hasRemovedWebSettingsKeys(parsed);
    const raw = stripRemovedWebSettingsKeys(parsed);
    const merged = stripRemovedWebSettingsKeys({ ...WEB_SETTINGS_DEFAULTS, ...raw });
    const schemaVersion = Number(raw.WEB_SETTINGS_SCHEMA_VERSION || 0);
    const needsUpgrade = schemaVersion < WEB_SETTINGS_DEFAULTS.WEB_SETTINGS_SCHEMA_VERSION;
    if(needsUpgrade){
      const adoptDefault = (key)=>{
        const value = raw[key];
        const legacyValue = LEGACY_WEB_SETTINGS_DEFAULTS_V2[key];
        if(value === undefined || value === null || value === "" || value === legacyValue){
          merged[key] = WEB_SETTINGS_DEFAULTS[key];
        }
      };
      [
        "SEARXNG_URL",
        "WHOOGLE_URL",
        "EXTERNAL_SEARCH_URL",
        "EXTERNAL_SEARCH_API_KEY",
        "EXTERNAL_IMAGE_SEARCH_URL",
        "EXTERNAL_IMAGE_SEARCH_API_KEY",
        "UAPIPRO_BASE_URL",
        "IMAGE_SEARCH_MAX_QUERIES",
        "TAVILY_EXTRACT_DEPTH",
        "BROWSER_GEO_ENABLE",
        "AUTO_WEB_K_RESULTS",
        "MAX_WEB_SEARCH_CALLS",
        "AUTO_WEB_FAST_MAX_PAGES",
        "AUTO_WEB_MAX_PAGES",
        "AUTO_WEB_FETCH_WORKERS",
        "AUTO_WEB_PAGE_TIMEOUT",
        "AUTO_WEB_PAGE_MAX_CHARS",
        "AUTO_WEB_PAGE_SNIPPET_CHARS",
      ].forEach(adoptDefault);
      if(!raw.SEARCH_PROVIDER || isRemovedSearchProvider(raw.SEARCH_PROVIDER)) merged.SEARCH_PROVIDER = WEB_SETTINGS_DEFAULTS.SEARCH_PROVIDER;
      if(!raw.SEARCH_FALLBACK_PROVIDER || (String(raw.SEARCH_FALLBACK_PROVIDER).trim().toLowerCase() === 'serper' || isRemovedSearchProvider(raw.SEARCH_FALLBACK_PROVIDER))) merged.SEARCH_FALLBACK_PROVIDER = WEB_SETTINGS_DEFAULTS.SEARCH_FALLBACK_PROVIDER;
      if(!raw.IMAGE_SEARCH_PROVIDER) merged.IMAGE_SEARCH_PROVIDER = WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_PROVIDER;
      if(!raw.IMAGE_SEARCH_FALLBACK_PROVIDER) merged.IMAGE_SEARCH_FALLBACK_PROVIDER = WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_FALLBACK_PROVIDER;
      merged.WEB_SETTINGS_SCHEMA_VERSION = WEB_SETTINGS_DEFAULTS.WEB_SETTINGS_SCHEMA_VERSION;
      writeAccountScopedSettingItem(WEB_SETTINGS_KEY, JSON.stringify(stripRemovedWebSettingsKeys(merged)));
    }else if(removedKeysChanged){
      writeAccountScopedSettingItem(WEB_SETTINGS_KEY, JSON.stringify(stripRemovedWebSettingsKeys(merged)));
    }
    return stripRemovedWebSettingsKeys(merged);
  }catch(_){
    return { ...WEB_SETTINGS_DEFAULTS };
  }
}
function saveWebSettings(v){ writeAccountScopedSettingItem(WEB_SETTINGS_KEY, JSON.stringify(stripRemovedWebSettingsKeys(v))); }

function fillWebSettingsForm(){
  const ws = getWebSettings();
  const setVal = (id, v)=>{ const el = document.getElementById(id); if(!el) return; if(el.type === "checkbox") el.checked = String(v ?? "") === "1" || String(v ?? "").toLowerCase() === "true"; else el.value = v; };
  setVal("wsSearxUrl", ws.SEARXNG_URL || WEB_SETTINGS_DEFAULTS.SEARXNG_URL);
  setVal("wsSearxPath", ws.SEARXNG_API_PATH || WEB_SETTINGS_DEFAULTS.SEARXNG_API_PATH);
  setVal("wsSearchProvider", ws.SEARCH_PROVIDER || WEB_SETTINGS_DEFAULTS.SEARCH_PROVIDER);
  setVal("wsSearchFallbackProvider", ws.SEARCH_FALLBACK_PROVIDER || WEB_SETTINGS_DEFAULTS.SEARCH_FALLBACK_PROVIDER);
  setVal("wsWhoogleUrl", ws.WHOOGLE_URL || WEB_SETTINGS_DEFAULTS.WHOOGLE_URL);
  setVal("wsExternalSearchUrl", ws.EXTERNAL_SEARCH_URL || WEB_SETTINGS_DEFAULTS.EXTERNAL_SEARCH_URL);
  setVal("wsExternalSearchApiKey", ws.EXTERNAL_SEARCH_API_KEY || WEB_SETTINGS_DEFAULTS.EXTERNAL_SEARCH_API_KEY);
  setVal("wsExternalImageSearchUrl", ws.EXTERNAL_IMAGE_SEARCH_URL || WEB_SETTINGS_DEFAULTS.EXTERNAL_IMAGE_SEARCH_URL);
  setVal("wsExternalImageSearchApiKey", ws.EXTERNAL_IMAGE_SEARCH_API_KEY || WEB_SETTINGS_DEFAULTS.EXTERNAL_IMAGE_SEARCH_API_KEY);
  setVal("wsUapiProBaseUrl", ws.UAPIPRO_BASE_URL || WEB_SETTINGS_DEFAULTS.UAPIPRO_BASE_URL);
  setVal("wsUapiProApiKey", ws.UAPIPRO_API_KEY || WEB_SETTINGS_DEFAULTS.UAPIPRO_API_KEY);
  setVal("wsImageSearchProvider", ws.IMAGE_SEARCH_PROVIDER || WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_PROVIDER);
  setVal("wsImageSearchFallbackProvider", ws.IMAGE_SEARCH_FALLBACK_PROVIDER || WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_FALLBACK_PROVIDER);
  setVal("wsImageMaxQueries", ws.IMAGE_SEARCH_MAX_QUERIES ?? WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_MAX_QUERIES);
  setVal("wsContentProvider", ws.CONTENT_PROVIDER || WEB_SETTINGS_DEFAULTS.CONTENT_PROVIDER);
  setVal("wsContentFallbackProvider", ws.CONTENT_FALLBACK_PROVIDER || WEB_SETTINGS_DEFAULTS.CONTENT_FALLBACK_PROVIDER);
  setVal("wsSerperApiKey", ws.SERPER_API_KEY || WEB_SETTINGS_DEFAULTS.SERPER_API_KEY);
  setVal("wsTavilyApiKey", ws.TAVILY_API_KEY || WEB_SETTINGS_DEFAULTS.TAVILY_API_KEY);
  setVal("wsTavilyExtractDepth", ws.TAVILY_EXTRACT_DEPTH || WEB_SETTINGS_DEFAULTS.TAVILY_EXTRACT_DEPTH);
  setVal("wsPlaywrightEnable", String(ws.PLAYWRIGHT_ENABLE ?? WEB_SETTINGS_DEFAULTS.PLAYWRIGHT_ENABLE));
  setVal("wsAutoRender", String(ws.WEB_FETCH_AUTO_RENDER ?? WEB_SETTINGS_DEFAULTS.WEB_FETCH_AUTO_RENDER));
  setVal("wsK", ws.AUTO_WEB_K_RESULTS ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_K_RESULTS);
  setVal("wsMaxSearchCalls", ws.MAX_WEB_SEARCH_CALLS ?? WEB_SETTINGS_DEFAULTS.MAX_WEB_SEARCH_CALLS);
  setVal("wsFastPages", ws.AUTO_WEB_FAST_MAX_PAGES ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_FAST_MAX_PAGES);
  setVal("wsMaxPages", ws.AUTO_WEB_MAX_PAGES ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_MAX_PAGES);
  setVal("wsWorkers", ws.AUTO_WEB_FETCH_WORKERS ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_FETCH_WORKERS);
  setVal("wsTimeout", ws.AUTO_WEB_PAGE_TIMEOUT ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_PAGE_TIMEOUT);
  setVal("wsPageChars", ws.AUTO_WEB_PAGE_MAX_CHARS ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_PAGE_MAX_CHARS);
  setVal("wsSnippetChars", ws.AUTO_WEB_PAGE_SNIPPET_CHARS ?? WEB_SETTINGS_DEFAULTS.AUTO_WEB_PAGE_SNIPPET_CHARS);
}
function readWebSettingsForm(){
  const num = (id, d)=>{ const v = Number(document.getElementById(id)?.value); return Number.isFinite(v) ? v : d; };
  const str = (id, d="")=>{ const el = document.getElementById(id); if(!el) return (d ?? "").toString().trim(); if(el.type === "checkbox") return el.checked ? "1" : "0"; return (el.value ?? d).toString().trim(); };
  const out = {
    ...getWebSettings(),
    WEB_SETTINGS_SCHEMA_VERSION: WEB_SETTINGS_DEFAULTS.WEB_SETTINGS_SCHEMA_VERSION,
    SEARXNG_URL: str("wsSearxUrl", WEB_SETTINGS_DEFAULTS.SEARXNG_URL),
    SEARXNG_API_PATH: str("wsSearxPath", WEB_SETTINGS_DEFAULTS.SEARXNG_API_PATH) || WEB_SETTINGS_DEFAULTS.SEARXNG_API_PATH,
    SEARCH_PROVIDER: str("wsSearchProvider", WEB_SETTINGS_DEFAULTS.SEARCH_PROVIDER),
    SEARCH_FALLBACK_PROVIDER: str("wsSearchFallbackProvider", WEB_SETTINGS_DEFAULTS.SEARCH_FALLBACK_PROVIDER),
    WHOOGLE_URL: str("wsWhoogleUrl", WEB_SETTINGS_DEFAULTS.WHOOGLE_URL),
    EXTERNAL_SEARCH_URL: str("wsExternalSearchUrl", WEB_SETTINGS_DEFAULTS.EXTERNAL_SEARCH_URL),
    EXTERNAL_SEARCH_API_KEY: str("wsExternalSearchApiKey", WEB_SETTINGS_DEFAULTS.EXTERNAL_SEARCH_API_KEY),
    EXTERNAL_IMAGE_SEARCH_URL: str("wsExternalImageSearchUrl", WEB_SETTINGS_DEFAULTS.EXTERNAL_IMAGE_SEARCH_URL),
    EXTERNAL_IMAGE_SEARCH_API_KEY: str("wsExternalImageSearchApiKey", WEB_SETTINGS_DEFAULTS.EXTERNAL_IMAGE_SEARCH_API_KEY),
    UAPIPRO_BASE_URL: str("wsUapiProBaseUrl", WEB_SETTINGS_DEFAULTS.UAPIPRO_BASE_URL) || WEB_SETTINGS_DEFAULTS.UAPIPRO_BASE_URL,
    UAPIPRO_API_KEY: str("wsUapiProApiKey", WEB_SETTINGS_DEFAULTS.UAPIPRO_API_KEY),
    IMAGE_SEARCH_PROVIDER: str("wsImageSearchProvider", WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_PROVIDER),
    IMAGE_SEARCH_FALLBACK_PROVIDER: str("wsImageSearchFallbackProvider", WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_FALLBACK_PROVIDER),
    IMAGE_SEARCH_MAX_QUERIES: num("wsImageMaxQueries", WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_MAX_QUERIES),
    CONTENT_PROVIDER: str("wsContentProvider", WEB_SETTINGS_DEFAULTS.CONTENT_PROVIDER),
    CONTENT_FALLBACK_PROVIDER: str("wsContentFallbackProvider", WEB_SETTINGS_DEFAULTS.CONTENT_FALLBACK_PROVIDER),
    SERPER_API_KEY: str("wsSerperApiKey", WEB_SETTINGS_DEFAULTS.SERPER_API_KEY),
    TAVILY_API_KEY: str("wsTavilyApiKey", WEB_SETTINGS_DEFAULTS.TAVILY_API_KEY),
    TAVILY_EXTRACT_DEPTH: str("wsTavilyExtractDepth", WEB_SETTINGS_DEFAULTS.TAVILY_EXTRACT_DEPTH),
    BROWSER_GEO_ENABLE: Number((getWebSettings().BROWSER_GEO_ENABLE ?? WEB_SETTINGS_DEFAULTS.BROWSER_GEO_ENABLE)),
    PLAYWRIGHT_ENABLE: Number(str("wsPlaywrightEnable", String(WEB_SETTINGS_DEFAULTS.PLAYWRIGHT_ENABLE))),
    WEB_FETCH_AUTO_RENDER: Number(str("wsAutoRender", String(WEB_SETTINGS_DEFAULTS.WEB_FETCH_AUTO_RENDER))),
    AUTO_WEB_K_RESULTS: num("wsK", WEB_SETTINGS_DEFAULTS.AUTO_WEB_K_RESULTS),
    MAX_WEB_SEARCH_CALLS: num("wsMaxSearchCalls", WEB_SETTINGS_DEFAULTS.MAX_WEB_SEARCH_CALLS),
    AUTO_WEB_FAST_MAX_PAGES: num("wsFastPages", WEB_SETTINGS_DEFAULTS.AUTO_WEB_FAST_MAX_PAGES),
    AUTO_WEB_MAX_PAGES: num("wsMaxPages", WEB_SETTINGS_DEFAULTS.AUTO_WEB_MAX_PAGES),
    AUTO_WEB_FETCH_WORKERS: num("wsWorkers", WEB_SETTINGS_DEFAULTS.AUTO_WEB_FETCH_WORKERS),
    AUTO_WEB_PAGE_TIMEOUT: num("wsTimeout", WEB_SETTINGS_DEFAULTS.AUTO_WEB_PAGE_TIMEOUT),
    AUTO_WEB_PAGE_MAX_CHARS: num("wsPageChars", WEB_SETTINGS_DEFAULTS.AUTO_WEB_PAGE_MAX_CHARS),
    AUTO_WEB_PAGE_SNIPPET_CHARS: num("wsSnippetChars", WEB_SETTINGS_DEFAULTS.AUTO_WEB_PAGE_SNIPPET_CHARS),
  };
  if(isRemovedSearchProvider(out.SEARCH_PROVIDER)) out.SEARCH_PROVIDER = WEB_SETTINGS_DEFAULTS.SEARCH_PROVIDER;
  if(isRemovedSearchProvider(out.SEARCH_FALLBACK_PROVIDER)) out.SEARCH_FALLBACK_PROVIDER = WEB_SETTINGS_DEFAULTS.SEARCH_FALLBACK_PROVIDER;
  if(!out.SEARCH_FALLBACK_PROVIDER) out.SEARCH_FALLBACK_PROVIDER = WEB_SETTINGS_DEFAULTS.SEARCH_FALLBACK_PROVIDER;
  if(!out.IMAGE_SEARCH_FALLBACK_PROVIDER) out.IMAGE_SEARCH_FALLBACK_PROVIDER = WEB_SETTINGS_DEFAULTS.IMAGE_SEARCH_FALLBACK_PROVIDER;
  return out;
}

function setWebSettingsHint(text, type=""){
  const el = document.getElementById("webSettingsHint");
  if(!el) return;
  const msg = String(text || "").trim();
  el.textContent = msg;
  const show = !!msg;
  el.hidden = !show;
  el.classList.toggle("show", show);
  el.classList.toggle("warn", type === "warn");
}
function getEnabledSearchProvidersForValidation(ws = getWebSettings()){
  const out = [];
  const primaryProvider = String(ws.SEARCH_PROVIDER || "").trim().toLowerCase();
  const fallbackProvider = String(ws.SEARCH_FALLBACK_PROVIDER || "").trim().toLowerCase();
  if(primaryProvider && !isRemovedSearchProvider(primaryProvider)) out.push(primaryProvider);
  if(fallbackProvider && fallbackProvider !== "none" && !isRemovedSearchProvider(fallbackProvider)) out.push(fallbackProvider);
  return Array.from(new Set(out));
}
async function validateWebSettings(next){
  const providers = getEnabledSearchProvidersForValidation(next);
  if(!providers.length) return { ok:true, results:[], message:"" };
  try{
    const res = await fetch("/api3/web_settings/validate", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ web_settings: next, validate_targets: providers })
    });
    const raw = await res.text().catch(()=> "");
    let data = {};
    try{ data = JSON.parse(raw || "{}"); }catch(_){ }
    if(!res.ok){
      return { ok:false, results:[], message:(data && (data.message || data.error)) || raw || ("HTTP " + res.status) };
    }
    return (data && typeof data === "object") ? data : { ok:true, results:[], message:"" };
  }catch(_){
    return { ok:false, results:[], code:'validation_failed', message:window.AperviaI18n?.t('settings.web.validation_failed') || "Unable to validate web settings. Try again later." };
  }
}
function webSettingsValidationMessage(item){
  const row = item && typeof item === 'object' ? item : {};
  const code = String(row.code || '').trim();
  const keys = {
    uapipro_api_key_missing:'settings.web.uapipro_api_key_missing',
    uapipro_base_url_missing:'settings.web.uapipro_base_url_missing',
    validation_failed:'settings.web.validation_failed',
  };
  if(keys[code]) return window.AperviaI18n?.t(keys[code]) || String(row.message || '').trim();
  const raw = String(row.message || '').trim();
  if(raw === '已启用 UApiPro，但还没有填写 API Key') return window.AperviaI18n?.t('settings.web.uapipro_api_key_missing') || raw;
  if(raw === '已启用 UApiPro，但还没有填写 Base URL') return window.AperviaI18n?.t('settings.web.uapipro_base_url_missing') || raw;
  return raw;
}
function summarizeWebSettingsValidation(report){
  if(!report || report.ok) return "";
  const items = Array.isArray(report.results) ? report.results : [];
  const providerLabels = { searxng: "SearxNG", whoogle: "Whoogle", ddgs: "DDGS", external: "external", uapipro: "UApiPro", serper: "Serper", tavily: "Tavily" };
  const parts = items
    .filter(item => item && item.ok === false && (item.message || item.code))
    .map(item => `${providerLabels[String(item.provider || "").toLowerCase()] || item.provider || "Web settings"}: ${webSettingsValidationMessage(item)}`);
  if(parts.length) return parts.join("；");
  return webSettingsValidationMessage(report);
}
function explainSearchProviderStreamError(message, ws = getWebSettings()){
  const raw = String(message || "").trim();
  if(!raw) return raw;
  const lower = raw.toLowerCase();
  const providers = getEnabledSearchProvidersForValidation(ws);
  const hints = [];
  const connectionLike = /(connecterror|connection refused|failed to establish a new connection|getaddrinfo|name or service not known|nodename nor servname|timeout|timed out|返回 http|http\s*\d{3}|连接失败|连接超时|接口路径|响应不是有效 json|响应格式不正确)/i.test(raw);
  if(providers.includes("searxng") && /searxng/i.test(raw) && connectionLike){
    hints.push("请检查 SearxNG 地址、端口和搜索接口路径是否正确，并确认服务已启动。");
  }
  if(providers.includes("whoogle") && /whoogle/i.test(raw) && connectionLike){
    hints.push("请检查 Whoogle 地址和端口是否正确，并确认服务已启动。");
  }
  if(providers.includes("ddgs") && /(ddgs|duckduckgo)/i.test(raw) && connectionLike){
    hints.push("DDGS 是免费直连链路，可能被 DuckDuckGo 限流或当前网络拦截；可以稍后重试，或把 SearXNG/Serper 放到兜底。");
  }
  if(providers.includes("external") && /external/i.test(raw) && connectionLike){
    hints.push("请检查 external 搜索接口地址、端口和密钥是否正确，并确认服务已启动。");
  }
  if(!hints.length && providers.includes("searxng") && /未配置\s*searxng_url/i.test(lower)){
    hints.push("当前搜索配置已经用到 SearxNG，但还没有填写地址。");
  }
  if(!hints.length && providers.includes("whoogle") && /未配置\s*whoogle_url/i.test(lower)){
    hints.push("当前搜索配置已经用到 Whoogle，但还没有填写地址。");
  }
  if(!hints.length && providers.includes("external") && /未配置\s*external_search_url/i.test(lower)){
    hints.push("当前搜索配置已经用到 external，但还没有填写搜索接口地址。");
  }
  if(!hints.length) return raw;
  return `${raw}
提示：${hints.join("")}`;
}

const WEB_SETTINGS_DRAFT_COMPARE_KEYS = [
  'SEARXNG_URL','SEARXNG_API_PATH','SEARCH_PROVIDER','SEARCH_FALLBACK_PROVIDER','WHOOGLE_URL',
  'EXTERNAL_SEARCH_URL','EXTERNAL_SEARCH_API_KEY','EXTERNAL_IMAGE_SEARCH_URL','EXTERNAL_IMAGE_SEARCH_API_KEY',
  'UAPIPRO_BASE_URL','UAPIPRO_API_KEY','IMAGE_SEARCH_PROVIDER','IMAGE_SEARCH_FALLBACK_PROVIDER','IMAGE_SEARCH_MAX_QUERIES',
  'CONTENT_PROVIDER','CONTENT_FALLBACK_PROVIDER','SERPER_API_KEY','TAVILY_API_KEY','TAVILY_EXTRACT_DEPTH',
  'PLAYWRIGHT_ENABLE','WEB_FETCH_AUTO_RENDER','AUTO_WEB_K_RESULTS','MAX_WEB_SEARCH_CALLS','AUTO_WEB_FAST_MAX_PAGES',
  'AUTO_WEB_MAX_PAGES','AUTO_WEB_FETCH_WORKERS','AUTO_WEB_PAGE_TIMEOUT','AUTO_WEB_PAGE_MAX_CHARS','AUTO_WEB_PAGE_SNIPPET_CHARS',
  'BROWSER_GEO_ENABLE'
];
function webSettingsDraftComparable(raw){
  const src = stripRemovedWebSettingsKeys(raw || {});
  const merged = stripRemovedWebSettingsKeys({ ...WEB_SETTINGS_DEFAULTS, ...src });
  const out = {};
  WEB_SETTINGS_DRAFT_COMPARE_KEYS.forEach((key)=>{ out[key] = merged[key]; });
  return out;
}

async function saveWebSettingsFormWithFeedback(){
  const prev = getWebSettings();
  const wasGeoEnabled = isSettingTruthyValue(prev.BROWSER_GEO_ENABLE);
  const next = readWebSettingsForm();
  const isGeoEnabled = isSettingTruthyValue(next.BROWSER_GEO_ENABLE);
  saveWebSettings(next);
  syncBrowserGeoSettingAfterSave(wasGeoEnabled, isGeoEnabled);
  const report = await validateWebSettings(next);
  const summary = summarizeWebSettingsValidation(report);
  refreshThinkingControlUi();
  if(summary){
    setWebSettingsHint(summary, "warn");
    toast(window.AperviaI18n?.t('settings.web.saved_check') || 'Saved, but some web access settings need attention.');
    return;
  }
  setWebSettingsHint("", "");
  toast(isGeoEnabled && !wasGeoEnabled
    ? (window.AperviaI18n?.t('settings.web.saved_location') || 'Web access settings saved. Requesting location permission.')
    : (window.AperviaI18n?.t('settings.web.saved') || 'Web access settings saved'));
}
function resetWebSettingsToDefaults(){
  const currentGeoEnabled = getWebSettings().BROWSER_GEO_ENABLE ?? WEB_SETTINGS_DEFAULTS.BROWSER_GEO_ENABLE;
  saveWebSettings({...WEB_SETTINGS_DEFAULTS, BROWSER_GEO_ENABLE: currentGeoEnabled});
  fillWebSettingsForm();
  refreshThinkingControlUi();
  setWebSettingsHint("", "");
  toast(window.AperviaI18n?.t('settings.web.default_restored') || 'Default web access settings restored');
}

function bindWebSettingsUi(){
  document.getElementById("webSettingsSaveBtn")?.addEventListener("click", async ()=>{
    await saveWebSettingsFormWithFeedback();
    refreshSettingsDraftActions();
  });
  document.getElementById("webSettingsResetBtn")?.addEventListener("click", ()=>{
    resetWebSettingsToDefaults();
    refreshSettingsDraftActions();
  });
}

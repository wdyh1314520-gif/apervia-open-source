/* Chat API profile settings.*/
function dedupeStrings(values, limit=800){
  const out = [];
  const seen = new Set();
  for(const item of Array.isArray(values) ? values : []){
    const v = String(item || "").trim();
    if(!v) continue;
    const key = v.toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    out.push(v);
    if(out.length >= limit) break;
  }
  return out;
}
function shortApiBase(base){
  const raw = String(base || "").trim();
  if(!raw) return window.AperviaI18n?.t('settings.api.base_missing') || "Base URL not entered";
  try{
    const u = new URL(raw);
    return `${u.hostname}${u.pathname && u.pathname !== '/' ? u.pathname : ''}`;
  }catch(_){
    return raw;
  }
}
function apiVendorDisplayName(vendor, host="", fallback=""){
  const normalized = String(vendor || "unknown").trim().toLowerCase();
  const stableLabels = {
    openrouter:"OpenRouter", openai:"OpenAI", anthropic:"Anthropic", google:"Google", xai:"xAI",
    deepseek:"DeepSeek", moonshot:"Moonshot", dashscope:"DashScope", siliconflow:"SiliconFlow",
    groq:"Groq", vveai:"VVEAI",
  };
  if(stableLabels[normalized]) return stableLabels[normalized];
  if(normalized === "zhipu") return window.AperviaI18n?.t('settings.api.vendor.zhipu') || 'Zhipu AI';
  if(normalized === "doubao") return window.AperviaI18n?.t('settings.api.vendor.doubao') || 'Doubao / Volcano Engine';
  if(normalized === "openai_compatible") return window.AperviaI18n?.t('settings.api.vendor.openai_compatible', {host:host ? ` · ${host}` : ''}) || (host ? `OpenAI-compatible · ${host}` : 'OpenAI-compatible');
  if(normalized === "follow_chat") return window.AperviaI18n?.t('settings.image.follow_chat') || 'Use chat API';
  if(normalized === "unknown") return host
    ? (window.AperviaI18n?.t('settings.api.vendor.unknown_host', {host}) || `Unknown provider · ${host}`)
    : (window.AperviaI18n?.t('settings.api.vendor.unknown') || 'Unknown provider');
  return String(fallback || vendor || '').trim() || (window.AperviaI18n?.t('settings.api.vendor.unknown') || 'Unknown provider');
}
function detectVendorMeta(api_key="", api_base=""){
  const key = String(api_key || "").trim();
  const base = String(api_base || "").trim();
  let host = "";
  try{ host = new URL(base).hostname.toLowerCase(); }catch(_){ host = ""; }
  const matchers = [
    {vendor:"openrouter", label:"OpenRouter", source:"api_base", test:()=> /(^|\.)openrouter\.ai$/.test(host)},
    {vendor:"openai", label:"OpenAI", source:"api_base", test:()=> /(^|\.)openai\.com$/.test(host)},
    {vendor:"anthropic", label:"Anthropic", source:"api_base", test:()=> /(^|\.)anthropic\.com$/.test(host)},
    {vendor:"google", label:"Google", source:"api_base", test:()=> /googleapis\.com$|google\.com$|google\.ai$|gemini/i.test(host)},
    {vendor:"xai", label:"xAI", source:"api_base", test:()=> /(^|\.)x\.ai$|(^|\.)xai\.com$/.test(host)},
    {vendor:"deepseek", label:"DeepSeek", source:"api_base", test:()=> /deepseek\.com$/.test(host)},
    {vendor:"moonshot", label:"Moonshot", source:"api_base", test:()=> /moonshot\.cn$|kimi\.moonshot\.cn$/.test(host)},
    {vendor:"dashscope", label:"DashScope", source:"api_base", test:()=> /dashscope|aliyuncs\.com/.test(host)},
    {vendor:"siliconflow", label:"SiliconFlow", source:"api_base", test:()=> /siliconflow\.cn$/.test(host)},
    {vendor:"zhipu", label:"Zhipu AI", source:"api_base", test:()=> /(^|\.)z\.ai$|bigmodel\.cn$|zhipu/i.test(host)},
    {vendor:"doubao", label:"Doubao / Volcano Engine", source:"api_base", test:()=> /volces\.com$|volcengine\.com$|ark/i.test(host)},
    {vendor:"groq", label:"Groq", source:"api_base", test:()=> /(^|\.)groq\.com$/.test(host)},
  ];
  for(const item of matchers){
    try{ if(item.test()) return {vendor:item.vendor, label:item.label, source:item.source, host}; }catch(_){ }
  }
  if(/^sk-or-v1-/i.test(key)) return {vendor:"openrouter", label:"OpenRouter", source:"api_key", host};
  if(/^sk-ant/i.test(key)) return {vendor:"anthropic", label:"Anthropic", source:"api_key", host};
  if(/^AIza/i.test(key)) return {vendor:"google", label:"Google", source:"api_key", host};
  if(/^gsk_/i.test(key)) return {vendor:"groq", label:"Groq", source:"api_key", host};
  if(/^sk-/i.test(key)) return {vendor:"openai_compatible", label:host ? `OpenAI compatible · ${host}` : "OpenAI compatible", source:"api_key", host};
  return {vendor:"unknown", label:host ? `Unknown · ${host}` : "Unknown provider", source:host ? "api_base" : "unknown", host};
}
function apiVendorDisplayLabel(value, apiKey="", apiBase="", options={}){
  const row = value && typeof value === "object" ? value : {vendor:value};
  const key = String(apiKey || row.api_key || "").trim();
  const base = String(apiBase || row.api_base || row.base_url || "").trim();
  const detected = detectVendorMeta(key, base);
  const vendor = String(row.vendor || detected.vendor || "unknown").trim().toLowerCase() || "unknown";
  const host = String(row.host || detected.host || "").trim().toLowerCase();
  const fallbacks = {
    openrouter:"OpenRouter", openai:"OpenAI", anthropic:"Anthropic", google:"Google", xai:"xAI",
    deepseek:"DeepSeek", moonshot:"Moonshot", dashscope:"DashScope", siliconflow:"SiliconFlow",
    zhipu:"Zhipu AI", doubao:"Doubao / Volcano Engine", groq:"Groq",
    openai_compatible:"OpenAI compatible", follow_chat:"Use chat API", unknown:"Unknown provider",
  };
  const fallback = fallbacks[vendor] || String(row.label || detected.label || fallbacks.unknown);
  const label = window.AperviaI18n?.t(`settings.vendor.${vendor}`, null, fallback) || fallback;
  if(vendor === "unknown" && host){
    return window.AperviaI18n?.t('settings.models.unknown_host', {host}, `Unknown · ${host}`) || `Unknown · ${host}`;
  }
  if(vendor === "openai_compatible" && host && options?.includeHost !== false){
    return window.AperviaI18n?.t('settings.vendor.with_host', {vendor:label, host}, `${label} · ${host}`) || `${label} · ${host}`;
  }
  return label;
}
function normalizeModelMetadataMap(value){
  const rows = Array.isArray(value)
    ? value
    : (value && typeof value === "object"
      ? Object.entries(value).map(([id, item])=>({ id, ...(item && typeof item === "object" ? item : {}) }))
      : []);
  const out = {};
  for(const raw of rows){
    const item = raw && typeof raw === "object" ? raw : {};
    const id = String(item.id || item.name || "").trim();
    if(!id) continue;
    const contextWindow = normalizeApiOptionalPositiveInt(item.context_window_tokens ?? item.context_length ?? item.context_window ?? item.max_context_tokens, {max:10000000});
    const maxOutput = normalizeApiOptionalPositiveInt(item.max_output_tokens ?? item.max_completion_tokens ?? item.output_token_limit, {max:1000000});
    const detail = {};
    if(contextWindow) detail.context_window_tokens = contextWindow;
    if(maxOutput) detail.max_output_tokens = maxOutput;
    if(item.owned_by) detail.owned_by = String(item.owned_by).slice(0,120);
    if(item.created) detail.created = Number(item.created) || 0;
    out[id] = detail;
  }
  return out;
}
function modelMetadataForProfileModel(profile, model){
  const target = String(model || "").trim().toLowerCase();
  if(!target) return {};
  const metadata = normalizeModelMetadataMap(profile?.model_details || profile?.models_meta || {});
  for(const [id, detail] of Object.entries(metadata)){
    if(String(id || "").trim().toLowerCase() === target) return detail || {};
  }
  return {};
}
function normalizeApiProfile(name, raw){
  const item = raw && typeof raw === "object" ? raw : {};
  const normalizedBase = normalizeApiBaseInputValue(item.api_base || item.base_url || item.apiBase || '');
  const meta = detectVendorMeta(item.api_key || "", normalizedBase);
  const selectedModels = dedupeStrings(item.selected_models || item.selectedModels || item.models || []);
  const modelsCache = dedupeStrings(item.models_cache || item.modelsCache || item.model_catalog || []);
  let lastModel = String(item.last_model || item.lastModel || "").trim();
  if(!lastModel && selectedModels.length) lastModel = selectedModels[0];
  return {
    api_key: String(item.api_key || "").trim(),
    api_base: normalizedBase,
    vendor: String(item.vendor || meta.vendor || "unknown"),
    vendor_label: String(meta.label || "Unknown provider"),
    api_endpoint_mode: normalizeApiEndpointMode(item.api_endpoint_mode || item.endpoint_mode || item.apiMode || item.interface_mode),
    responses_reasoning_effort: normalizeResponsesReasoningEffort(item.responses_reasoning_effort || item.responsesReasoningEffort || item.RESPONSES_REASONING_EFFORT || 'auto'),
    responses_reasoning_summary: normalizeResponsesReasoningSummary(item.responses_reasoning_summary || item.responsesReasoningSummary || item.RESPONSES_REASONING_SUMMARY || 'detailed'),
    responses_reasoning_context: normalizeResponsesReasoningContext(item.responses_reasoning_context || item.responsesReasoningContext || item.RESPONSES_REASONING_CONTEXT || 'auto'),
    generation_context_window_tokens: normalizeApiOptionalPositiveInt(item.generation_context_window_tokens ?? item.context_window_tokens ?? item.context_window ?? item.max_context_tokens, {max:2000000}),
    generation_max_tokens: normalizeApiOptionalPositiveInt(item.generation_max_tokens ?? item.max_output_tokens ?? item.max_completion_tokens ?? item.max_tokens, {max:200000}),
    generation_temperature: normalizeApiOptionalFloat(item.generation_temperature ?? item.temperature, {min:0, max:2}),
    generation_top_p: normalizeApiOptionalFloat(item.generation_top_p ?? item.top_p, {min:0, max:1}),
    generation_response_format: normalizeApiResponseFormat(item.generation_response_format ?? item.response_format),
    generation_include_usage: normalizeApiTriState(item.generation_include_usage ?? item.stream_include_usage ?? item.include_usage),
    api_base_options: normalizeApiBaseOptionList(item.api_base_options || item.apiBaseOptions || item.base_options || item.baseUrls || item.base_urls || [], normalizedBase),
    selected_models: selectedModels,
    models_cache: modelsCache,
    model_details: normalizeModelMetadataMap(item.model_details || item.models_meta || item.model_metadata || {}),
    last_model: lastModel,
    model_search_at: Number(item.model_search_at || item.modelSearchAt || 0) || 0,
    model_probe_error: String(item.model_probe_error || item.modelProbeError || '').trim(),
    model_probe_failed: !!(item.model_probe_failed || item.modelProbeFailed),
  };
}
function getApiProfiles(){
  let raw = {};
  try{ raw = JSON.parse(readAccountScopedSettingItem(API_PROFILES_KEY) || "{}") || {}; }catch(_){ raw = {}; }
  const out = {};
  if(raw && typeof raw === "object"){
    for(const [name, value] of Object.entries(raw)){
      const key = String(name || "").trim();
      if(!key) continue;
      out[key] = normalizeApiProfile(key, value);
    }
  }
  if(!Object.keys(out).length){
    out[DEFAULT_API_PROFILE_NAME] = normalizeApiProfile(DEFAULT_API_PROFILE_NAME, {api_key:"", api_base:"", selected_models:[], last_model:""});
  }
  writeAccountScopedSettingItem(API_PROFILES_KEY, JSON.stringify(out));
  return out;
}
function saveApiProfiles(profiles){
  const normalized = {};
  for(const [name, value] of Object.entries(profiles || {})){
    const key = String(name || "").trim();
    if(!key) continue;
    normalized[key] = normalizeApiProfile(key, value);
  }
  if(!Object.keys(normalized).length){
    normalized[DEFAULT_API_PROFILE_NAME] = normalizeApiProfile(DEFAULT_API_PROFILE_NAME, {api_key:"", api_base:"", selected_models:[], last_model:""});
  }
  writeAccountScopedSettingItem(API_PROFILES_KEY, JSON.stringify(normalized));
}
function ensureApiProfileForMode(mode){
  const targetMode = normalizeApiEndpointMode(mode);
  let profiles = getApiProfiles();
  const existing = getFirstApiProfileNameForMode(profiles, targetMode);
  if(existing) return existing;

  const legacyActive = String(readAccountScopedSettingItem(ACTIVE_API_KEY) || "").trim();
  const sourceName = (legacyActive && profiles[legacyActive]) ? legacyActive : (Object.keys(profiles)[0] || DEFAULT_API_PROFILE_NAME);
  const source = profiles[sourceName] || normalizeApiProfile(sourceName, {api_key:"", api_base:"", selected_models:[], last_model:""});
  const nextName = buildApiProfileNameForMode(sourceName, targetMode, profiles);
  profiles[nextName] = normalizeApiProfile(nextName, {
    ...source,
    api_endpoint_mode: targetMode,
    model_search_at: 0,
    model_probe_error: "",
    model_probe_failed: false,
  });
  saveApiProfiles(profiles);
  return nextName;
}
function getActiveApiEndpointMode(){
  return getStoredApiEndpointMode();
}
function getActiveApiName(mode = getActiveApiEndpointMode()){
  const targetMode = normalizeApiEndpointMode(mode);
  let profiles = getApiProfiles();
  const map = getActiveApiModeMap();
  const mapped = String(map[targetMode] || "").trim();
  if(mapped && profiles[mapped] && apiProfileMatchesMode(profiles[mapped], targetMode)){
    saveActiveApiNameForMode(targetMode, mapped);
    return mapped;
  }

  const legacy = String(readAccountScopedSettingItem(ACTIVE_API_KEY) || "").trim();
  if(legacy && profiles[legacy] && apiProfileMatchesMode(profiles[legacy], targetMode)){
    saveActiveApiNameForMode(targetMode, legacy);
    return legacy;
  }

  let first = getFirstApiProfileNameForMode(profiles, targetMode);
  if(!first){
    first = ensureApiProfileForMode(targetMode);
    profiles = getApiProfiles();
  }
  saveActiveApiNameForMode(targetMode, first);
  return first;
}
function getCurrentApiProfile(){
  const mode = getActiveApiEndpointMode();
  const profiles = getApiProfiles();
  const name = getActiveApiName(mode);
  return { name, ...(profiles[name] || normalizeApiProfile(name, {api_endpoint_mode: mode})), api_endpoint_mode: mode };
}
function getApiProfileForEndpointMode(mode){
  const targetMode = normalizeApiEndpointMode(mode);
  let profiles = getApiProfiles();
  const map = getActiveApiModeMap();
  let name = String(map[targetMode] || "").trim();
  if(!(name && profiles[name] && apiProfileMatchesMode(profiles[name], targetMode))){
    name = getFirstApiProfileNameForMode(profiles, targetMode);
  }
  if(!name){
    name = ensureApiProfileForMode(targetMode);
    profiles = getApiProfiles();
  }
  return { name, ...(profiles[name] || normalizeApiProfile(name, {api_endpoint_mode: targetMode})), api_endpoint_mode: targetMode };
}
function apiProfileForRequest(profile){
  const row = profile && typeof profile === "object" ? profile : {};
  return {
    api_key: String(row.api_key || "").trim(),
    api_base: String(row.api_base || "").trim(),
    profile_name: String(row.name || row.profile_name || "").trim(),
    api_endpoint_mode: normalizeApiEndpointMode(row.api_endpoint_mode),
  };
}
function setActiveApiName(name, {syncModel=true, refreshModelUi=true}={}){
  const profiles = getApiProfiles();
  let target = profiles[name] ? name : "";
  if(!target){
    const mode = getActiveApiEndpointMode();
    target = getFirstApiProfileNameForMode(profiles, mode) || ensureApiProfileForMode(mode);
  }
  const targetMode = apiProfileMode(profiles[target] || {});
  setStoredApiEndpointMode(targetMode);
  saveActiveApiNameForMode(targetMode, target);
  updateApiButton();
  renderApiSavedList();
  fillApiFormFromCurrent();
  if(syncModel) syncModelOptionsForActiveProfile({ensureSessionValue:true});
  refreshThinkingControlUi();
  if(refreshModelUi) renderModelManagementUi();
  try{ syncComposerAddMenuUi(); }catch(_){}
}
function updateCurrentApiProfile(updater){
  const profiles = getApiProfiles();
  const mode = getActiveApiEndpointMode();
  const name = getActiveApiName(mode);
  const current = profiles[name] || normalizeApiProfile(name, {api_endpoint_mode: mode});
  const next = typeof updater === "function" ? updater({...current, api_endpoint_mode: mode}) : {...current, ...(updater || {}), api_endpoint_mode: mode};
  profiles[name] = normalizeApiProfile(name, {...next, api_endpoint_mode: mode});
  saveApiProfiles(profiles);
  return profiles[name];
}

function syncApiToggleBackedField(inputId, toggleId, stateId, value, opts = {}){
  const hidden = document.getElementById(inputId);
  const toggle = document.getElementById(toggleId);
  const state = stateId ? document.getElementById(stateId) : null;
  const onValue = String(opts.onValue ?? "enabled");
  const offValue = String(opts.offValue ?? "disabled");
  const normalized = typeof opts.normalize === "function" ? opts.normalize(value) : String(value || "");
  const isOn = typeof opts.isOn === "function" ? !!opts.isOn(normalized) : normalized === onValue;
  const nextValue = isOn ? onValue : offValue;
  if(hidden) hidden.value = nextValue;
  if(toggle){
    toggle.checked = isOn;
    try{ toggle.setAttribute("aria-checked", isOn ? "true" : "false"); }catch(_){}
  }
  if(state) state.textContent = isOn
    ? (opts.onText || window.AperviaI18n?.t('common.on') || 'On')
    : (opts.offText || window.AperviaI18n?.t('common.off') || 'Off');
  return nextValue;
}
function readApiToggleBackedField(inputId, toggleId, opts = {}){
  const hidden = document.getElementById(inputId);
  const toggle = document.getElementById(toggleId);
  const onValue = String(opts.onValue ?? "enabled");
  const offValue = String(opts.offValue ?? "disabled");
  if(toggle) return toggle.checked ? onValue : offValue;
  return hidden?.value || offValue;
}
function syncApiGenerationSwitchControls(){
  const fmt = normalizeApiResponseFormat(document.getElementById("apiResponseFormatInput")?.value || "auto");
  syncApiToggleBackedField("apiResponseFormatInput", "apiResponseFormatToggle", "apiResponseFormatState", fmt, {
    onValue:"json_object",
    offValue:"auto",
    normalize: normalizeApiResponseFormat,
    isOn: (v)=> normalizeApiResponseFormat(v) === "json_object",
    onText:window.AperviaI18n?.t('common.on') || "On",
    offText:window.AperviaI18n?.t('common.off') || "Off",
  });
  const usage = normalizeApiTriState(document.getElementById("apiStreamUsageInput")?.value || "disabled");
  syncApiToggleBackedField("apiStreamUsageInput", "apiStreamUsageToggle", "apiStreamUsageState", usage, {
    onValue:"enabled",
    offValue:"disabled",
    normalize: normalizeApiTriState,
    isOn: (v)=> normalizeApiTriState(v) === "enabled",
    onText:window.AperviaI18n?.t('common.on') || "On",
    offText:window.AperviaI18n?.t('common.off') || "Off",
  });
}
function bindApiToggleBackedField(inputId, toggleId, stateId, opts = {}){
  const toggle = document.getElementById(toggleId);
  if(!toggle || toggle.dataset.apiToggleBound === "1") return;
  toggle.dataset.apiToggleBound = "1";
  toggle.addEventListener("change", ()=>{
    syncApiToggleBackedField(inputId, toggleId, stateId, toggle.checked ? opts.onValue : opts.offValue, opts);
    persistCurrentApiGenerationParams({silent:true});
    try{ syncGenerationSettingsContextUi(); }catch(_){}
  });
}

function collectApiGenerationParamsFromForm(){
  return normalizeGenerationSettings({
    responses_reasoning_effort: document.getElementById("responsesReasoningEffortInput")?.value || "auto",
    responses_reasoning_summary: document.getElementById("responsesReasoningSummaryInput")?.value || "detailed",
    responses_reasoning_context: document.getElementById("responsesReasoningContextInput")?.value || "auto",
    generation_context_window_tokens: document.getElementById("apiContextWindowInput")?.value || "",
    generation_max_tokens: document.getElementById("apiMaxTokensInput")?.value || "",
    generation_temperature: document.getElementById("apiTemperatureInput")?.value || "",
    generation_top_p: document.getElementById("apiTopPInput")?.value || "",
    generation_response_format: readApiToggleBackedField("apiResponseFormatInput", "apiResponseFormatToggle", {onValue:"json_object", offValue:"auto"}),
    generation_include_usage: readApiToggleBackedField("apiStreamUsageInput", "apiStreamUsageToggle", {onValue:"enabled", offValue:"disabled"}),
  });
}
function fillApiGenerationParamsForm(profile){
  const row = normalizeGenerationSettings(getGenerationSettings());
  const contextEl = document.getElementById("apiContextWindowInput");
  const maxEl = document.getElementById("apiMaxTokensInput");
  const tempEl = document.getElementById("apiTemperatureInput");
  const topPEl = document.getElementById("apiTopPInput");
  const fmtEl = document.getElementById("apiResponseFormatInput");
  const usageEl = document.getElementById("apiStreamUsageInput");
  if(contextEl) contextEl.value = row.generation_context_window_tokens || "";
  if(maxEl) maxEl.value = row.generation_max_tokens || "";
  if(tempEl) tempEl.value = row.generation_temperature !== "" ? row.generation_temperature : "";
  if(topPEl) topPEl.value = row.generation_top_p !== "" ? row.generation_top_p : "";
  if(fmtEl) fmtEl.value = normalizeApiResponseFormat(row.generation_response_format);
  if(usageEl) usageEl.value = normalizeApiTriState(row.generation_include_usage) === "enabled" ? "enabled" : "disabled";
  try{ syncResponsesReasoningEffortSlider(row.responses_reasoning_effort || "auto"); }catch(_){}
  try{ syncResponsesReasoningSummaryUi(row.responses_reasoning_summary || "detailed"); }catch(_){}
  try{ syncResponsesReasoningContextChoice(row.responses_reasoning_context || "auto"); }catch(_){}
  syncApiGenerationSwitchControls();
  syncApiGenerationSettingsUi();
}
function persistCurrentApiGenerationParams({silent=true} = {}){
  try{
    const previousUsage = normalizeApiTriState(getGenerationSettings()?.generation_include_usage);
    const nextParams = collectApiGenerationParamsFromForm();
    saveGenerationSettings(nextParams);
    if(!silent) toast(window.AperviaI18n?.t('settings.api.generation_saved') || "Generation settings saved");
    try{ syncGenerationSettingsContextUi(); }catch(_){}
    if(previousUsage !== normalizeApiTriState(nextParams.generation_include_usage)){
      try{ invalidateChatRenderCache(); }catch(_){}
      try{ safeRenderAll(); }catch(_){}
    }
    return true;
  }catch(_){ return false; }
}
function setCurrentApiEndpointMode(mode, {silent=false} = {}){
  const prevMode = getActiveApiEndpointMode();
  const nextMode = normalizeApiEndpointMode(mode);
  const changed = prevMode !== nextMode;
  setStoredApiEndpointMode(nextMode);
  const targetName = getActiveApiName(nextMode);
  if(targetName) saveActiveApiNameForMode(nextMode, targetName);

  const endpointModeEl = document.getElementById("apiEndpointModeInput");
  if(endpointModeEl) endpointModeEl.value = nextMode;
  updateApiButton();
  fillApiFormFromCurrent();
  updateApiVendorPreview();
  renderApiQuickMenu();
  renderApiSavedList();
  refreshThinkingControlUi();
  syncModelOptionsForActiveProfile({ensureSessionValue:true});
  renderModelManagementUi();
  try{ syncComposerAddMenuUi(); }catch(_){}
  if(!silent && changed){
    try{ toast(window.AperviaI18n?.t('settings.api.mode_switched', {mode:apiEndpointModeLabel(nextMode)}) || ("Switched to separate mode: " + apiEndpointModeLabel(nextMode))); }catch(_){ }
  }
  return getCurrentApiProfile();
}

function getRequestSettings(requestModel=""){
  const api = getCurrentApiProfile();
  const endpointMode = getActiveApiEndpointMode();
  const chatApi = getApiProfileForEndpointMode(API_ENDPOINT_MODE_CHAT);
  const responsesApi = getApiProfileForEndpointMode(API_ENDPOINT_MODE_RESPONSES);
  const generationSettings = generationSettingsForRequest();
  const selectedModel = currentResponsesReasoningModel(requestModel);
  const currentApiPayload = applyGenerationSettingsToApiPayload(apiProfileForRequest(api), generationSettings, selectedModel);
  const chatApiPayload = applyGenerationSettingsToApiPayload(apiProfileForRequest(chatApi), generationSettings, endpointMode === API_ENDPOINT_MODE_CHAT ? selectedModel : (chatApi.last_model || ""));
  const responsesApiPayload = applyGenerationSettingsToApiPayload(apiProfileForRequest(responsesApi), generationSettings, endpointMode === API_ENDPOINT_MODE_RESPONSES ? selectedModel : (responsesApi.last_model || ""));
  const web = {
    ...getWebSettings(),
    CHAT_THINKING_TYPE: getCurrentChatThinkingType(),
  };
  if(endpointMode === API_ENDPOINT_MODE_RESPONSES){
    web.RESPONSES_REASONING_EFFORT = normalizeResponsesReasoningEffort(generationSettings.responses_reasoning_effort || "auto");
    web.RESPONSES_REASONING_SUMMARY = normalizeResponsesReasoningSummary(generationSettings.responses_reasoning_summary || "detailed");
    if(responsesModelSupportsReasoningContext(selectedModel)){
      web.RESPONSES_REASONING_CONTEXT = normalizeResponsesReasoningContext(generationSettings.responses_reasoning_context || "auto");
    }else{
      delete web.RESPONSES_REASONING_CONTEXT;
    }
  }else{
    delete web.RESPONSES_REASONING_EFFORT;
    delete web.RESPONSES_REASONING_SUMMARY;
    delete web.RESPONSES_REASONING_CONTEXT;
  }
  return {
    api_key: currentApiPayload.api_key || "",
    api_base: currentApiPayload.api_base || API_DEFAULT_BASE,
    api_endpoint_mode: endpointMode,
    api_settings: currentApiPayload,
    chat_api_settings: chatApiPayload,
    responses_api_settings: responsesApiPayload,
    generation_settings: generationSettings,
    api_profiles_by_mode: {
      [API_ENDPOINT_MODE_CHAT]: chatApiPayload,
      [API_ENDPOINT_MODE_RESPONSES]: responsesApiPayload,
    },
    web_settings: web,
    web_k: Number(web.AUTO_WEB_K_RESULTS || WEB_SETTINGS_DEFAULTS.AUTO_WEB_K_RESULTS),
    web_max_pages: Number(web.AUTO_WEB_MAX_PAGES || WEB_SETTINGS_DEFAULTS.AUTO_WEB_MAX_PAGES),
    image_generation_settings: getImageGenerationSettings(),
    voice_settings: getVoiceSettings(),
  };
}
function updateApiButton(){
  const select = document.getElementById("apiQuickSelect");
  if(!select) return;
  const active = getActiveApiName();
  if(select.value !== active){
    select.value = active;
  }
}
function renderApiQuickMenu(){
  const select = document.getElementById("apiQuickSelect");
  if(!select) return;
  const mode = getActiveApiEndpointMode();
  ensureApiProfileForMode(mode);
  const profiles = getApiProfiles();
  const active = getActiveApiName(mode);
  select.innerHTML = "";
  const names = Object.keys(profiles).filter(name => apiProfileMatchesMode(profiles[name], mode));
  names.forEach(name=>{
    const option = document.createElement("option");
    option.value = name;
    option.textContent = apiProfileDisplayName(name);
    select.appendChild(option);
  });
  if(!select.options.length){
    const option = document.createElement("option");
    option.value = active;
    option.textContent = apiProfileDisplayName(active || DEFAULT_API_PROFILE_NAME);
    select.appendChild(option);
  }
  select.value = active;
}
function fillApiFormFromCurrent(){
  const cur = getCurrentApiProfile();
  apiProfileEditorMode = "edit";
  const nameEl = document.getElementById("apiProfileName");
  const keyEl = document.getElementById("apiKeyInput");
  const baseEl = document.getElementById("apiBaseInput");
  const endpointModeEl = document.getElementById("apiEndpointModeInput");
  if(nameEl) nameEl.value = apiProfileDisplayName(cur.name || DEFAULT_API_PROFILE_NAME);
  if(keyEl) keyEl.value = cur.api_key || "";
  if(baseEl) baseEl.value = normalizeApiBaseInputValue(cur.api_base || '') || String(cur.api_base || '').trim();
  if(endpointModeEl) endpointModeEl.value = normalizeApiEndpointMode(cur.api_endpoint_mode);
  const globalGeneration = getGenerationSettings();
  const responsesReasoningEffortEl = document.getElementById("responsesReasoningEffortInput");
  const currentEffort = normalizeResponsesReasoningEffort(globalGeneration.responses_reasoning_effort || "auto");
  if(responsesReasoningEffortEl) responsesReasoningEffortEl.value = currentEffort;
  try{ syncResponsesReasoningEffortSlider(currentEffort); }catch(_){}
  fillApiGenerationParamsForm(globalGeneration);
  syncApiSettingsModeUi();
  try{ syncGenerationSettingsContextUi(cur); }catch(_){}
  const badge = document.getElementById("apiVendorBadge");
  const hint = document.getElementById("apiVendorHint");
  if(badge){ badge.textContent = ''; badge.hidden = true; badge.style.display = 'none'; }
  if(hint){ hint.textContent = ''; hint.hidden = true; hint.style.display = 'none'; }
  updateApiVendorPreview();
  closeApiBaseSuggestMenu();
}
function beginNewApiProfileDraft(){
  apiProfileEditorMode = "new";
  const profileNameEl = document.getElementById("apiProfileName");
  const keyEl = document.getElementById("apiKeyInput");
  const baseEl = document.getElementById("apiBaseInput");
  const endpointModeEl = document.getElementById("apiEndpointModeInput");
  if(profileNameEl) profileNameEl.value = "";
  if(keyEl) keyEl.value = "";
  if(baseEl) baseEl.value = "";
  if(endpointModeEl) endpointModeEl.value = getActiveApiEndpointMode();
  const globalGeneration = getGenerationSettings();
  const responsesReasoningEffortEl = document.getElementById("responsesReasoningEffortInput");
  if(responsesReasoningEffortEl) responsesReasoningEffortEl.value = normalizeResponsesReasoningEffort(globalGeneration.responses_reasoning_effort || "auto");
  try{ syncResponsesReasoningEffortSlider(globalGeneration.responses_reasoning_effort || "auto"); }catch(_){}
  fillApiGenerationParamsForm(globalGeneration);
  syncApiSettingsModeUi();
  try{ syncGenerationSettingsContextUi({ name:window.AperviaI18n?.t('settings.api.new_key') || "New key", api_base:"" }); }catch(_){}
  const badge = document.getElementById("apiVendorBadge");
  const hint = document.getElementById("apiVendorHint");
  if(badge){ badge.textContent = ''; badge.hidden = true; badge.style.display = 'none'; }
  if(hint){ hint.textContent = ''; hint.hidden = true; hint.style.display = 'none'; }
  updateApiVendorPreview();
  closeApiBaseSuggestMenu();
  profileNameEl?.focus();
}
function renderApiSavedList(){
  const wrap = document.getElementById("apiSavedList");
  if(!wrap) return;
  const mode = getActiveApiEndpointMode();
  const profiles = getApiProfiles();
  const active = getActiveApiName(mode);
  const names = Object.keys(profiles).filter(name => apiProfileMatchesMode(profiles[name], mode));
  wrap.innerHTML = "";
  syncApiSettingsModeUi();
  if(!names.length){
    const empty = document.createElement("div");
    empty.className = "settings-empty";
    empty.textContent = window.AperviaI18n?.t('settings.api.no_saved_keys') || 'No keys have been saved yet.';
    wrap.appendChild(empty);
    return;
  }
  names.forEach(name=>{
    const item = profiles[name] || {};
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "settings-key-item" + (name === active ? " active" : "");
    const selectedCount = Number((item.selected_models || []).length || 0);
    const baseOptionsCount = normalizeApiBaseOptionList(item.api_base_options || [], item.api_base || '').length;
    const metaBits = [];
    metaBits.push(selectedCount > 0
      ? (window.AperviaI18n?.t('settings.api.models_selected', {count:selectedCount}) || `已选 ${selectedCount} 个模型`)
      : (window.AperviaI18n?.t('settings.api.no_model') || '未选模型'));
    if(baseOptionsCount > 1) metaBits.push(window.AperviaI18n?.t('settings.api.address_count', {count:baseOptionsCount}) || `地址 ${baseOptionsCount} 个`);
    const baseLabel = shortApiBase(item.api_base || '');
    if(baseLabel) metaBits.push(baseLabel);
    btn.innerHTML = `
      <span class="settings-key-main">
        <span class="settings-key-name">${escapeHtml(apiProfileDisplayName(name))}</span>
        <span class="settings-key-meta">${escapeHtml(metaBits.join(' · '))}</span>
      </span>
      <span class="settings-badge">${escapeHtml(window.AperviaI18n?.t(name === active ? 'settings.api.in_use' : 'settings.api.switch') || (name === active ? '当前使用' : '切换'))}</span>
    `;
    btn.addEventListener("click", ()=> setActiveApiName(name));
    wrap.appendChild(btn);
  });
}

function bindApiProfileSettingsUi(){
  document.getElementById("apiQuickSelect")?.addEventListener("change", (e)=>{
    const nextName = String(e.target?.value || "").trim();
    if(nextName) setActiveApiName(nextName);
  });
  document.querySelectorAll('[data-api-settings-mode]').forEach(btn => btn.addEventListener('click', ()=> activateApiSettingsMode(btn.getAttribute('data-api-settings-mode') || API_ENDPOINT_MODE_CHAT)));
  initApiBaseAutocomplete();
  // API 接口类型现在由上方 Chat Completions / Responses 分区切换控制。
  // apiEndpointModeInput 保留为隐藏字段，供保存当前 Key 时写入对应类型。
  // Responses 推理强度用文字档位，不再用连续滑条。保留旧 slider 监听的兼容，不存在时自动跳过。
  document.getElementById("responsesReasoningEffortSlider")?.addEventListener("input", (e)=>{
    const nextEffort = responsesReasoningEffortFromSliderIndex(e.target?.value || 0);
    const hidden = document.getElementById("responsesReasoningEffortInput");
    if(hidden) hidden.value = nextEffort;
    try{ syncResponsesReasoningEffortSlider(nextEffort); }catch(_){}
  });
  document.getElementById("responsesReasoningEffortSlider")?.addEventListener("change", (e)=>{
    const nextEffort = responsesReasoningEffortFromSliderIndex(e.target?.value || 0);
    const hidden = document.getElementById("responsesReasoningEffortInput");
    if(hidden){
      hidden.value = nextEffort;
      hidden.dispatchEvent(new Event("change", { bubbles:true }));
    }
  });
  document.querySelectorAll('[data-reasoning-effort-value]').forEach(btn=> btn.addEventListener('click', ()=>{
    const nextEffort = normalizeResponsesReasoningEffort(btn.getAttribute('data-reasoning-effort-value') || 'auto');
    const hidden = document.getElementById("responsesReasoningEffortInput");
    if(hidden){
      hidden.value = nextEffort;
      try{ syncResponsesReasoningEffortSlider(nextEffort); }catch(_){}
      hidden.dispatchEvent(new Event("change", { bubbles:true }));
    }
  }));
  document.getElementById("responsesReasoningEffortInput")?.addEventListener("change", (e)=>{
    const nextEffort = normalizeResponsesReasoningEffort(e.target?.value || "auto");
    const nextSettings = saveGenerationSettings({ ...getGenerationSettings(), responses_reasoning_effort: nextEffort });
    try{ syncResponsesReasoningEffortSlider(nextSettings.responses_reasoning_effort); }catch(_){}
    try{ syncGenerationSettingsContextUi(); }catch(_){}
    try{ toast(window.AperviaI18n?.t('settings.api.reasoning_effort_saved', {effort:responsesReasoningEffortLabel(nextSettings.responses_reasoning_effort)}) || ("Responses reasoning effort: " + responsesReasoningEffortLabel(nextSettings.responses_reasoning_effort))); }catch(_){ }
  });
  const bindReasoningChoice = ({selector, inputId, settingsKey, normalizer, syncer, labeler, toastPrefix})=>{
    document.querySelectorAll(selector).forEach(btn=> btn.addEventListener("click", ()=>{
      const nextValue = normalizer(btn.getAttribute(selector.slice(1, -1)) || "auto");
      const hidden = document.getElementById(inputId);
      if(!hidden) return;
      hidden.value = nextValue;
      syncer(nextValue);
      hidden.dispatchEvent(new Event("change", { bubbles:true }));
    }));
    document.getElementById(inputId)?.addEventListener("change", (e)=>{
      const nextValue = normalizer(e.target?.value || "auto");
      const nextSettings = saveGenerationSettings({ ...getGenerationSettings(), [settingsKey]: nextValue });
      syncer(nextSettings[settingsKey]);
      try{ syncGenerationSettingsContextUi(); }catch(_){ }
      try{ toast(toastPrefix + labeler(nextSettings[settingsKey])); }catch(_){ }
    });
  };
  bindReasoningChoice({
    selector:"[data-reasoning-summary-value]",
    inputId:"responsesReasoningSummaryInput",
    settingsKey:"responses_reasoning_summary",
    normalizer:normalizeResponsesReasoningSummary,
    syncer:syncResponsesReasoningSummaryUi,
    labeler:responsesReasoningSummaryLabel,
    toastPrefix:"统一 Responses 推理摘要：",
  });
  bindReasoningChoice({
    selector:"[data-reasoning-context-value]",
    inputId:"responsesReasoningContextInput",
    settingsKey:"responses_reasoning_context",
    normalizer:normalizeResponsesReasoningContext,
    syncer:syncResponsesReasoningContextChoice,
    labeler:responsesReasoningContextLabel,
    toastPrefix:"统一 Responses 推理上下文：",
  });
  document.getElementById("apiKeyInput")?.addEventListener("input", updateApiVendorPreview);
  document.getElementById("apiKeyInput")?.addEventListener("change", updateApiVendorPreview);
  document.getElementById("apiContextWindowSlider")?.addEventListener("input", (e)=>{
    const idx = Math.max(0, Math.min(GENERATION_CONTEXT_WINDOW_SLIDER_VALUES.length - 1, Math.round(Number(e.target?.value || 0))));
    const next = GENERATION_CONTEXT_WINDOW_SLIDER_VALUES[idx] || "";
    const el = document.getElementById("apiContextWindowInput");
    if(el) el.value = next;
    try{ syncGenerationRangeControls(); }catch(_){}
  });
  document.getElementById("apiContextWindowSlider")?.addEventListener("change", (e)=>{
    const idx = Math.max(0, Math.min(GENERATION_CONTEXT_WINDOW_SLIDER_VALUES.length - 1, Math.round(Number(e.target?.value || 0))));
    setGenerationHiddenValue("apiContextWindowInput", GENERATION_CONTEXT_WINDOW_SLIDER_VALUES[idx] || "");
  });
  document.getElementById("apiMaxTokensSlider")?.addEventListener("input", (e)=>{
    const idx = Math.max(0, Math.min(GENERATION_MAX_TOKEN_SLIDER_VALUES.length - 1, Math.round(Number(e.target?.value || 0))));
    const next = GENERATION_MAX_TOKEN_SLIDER_VALUES[idx] || "";
    const el = document.getElementById("apiMaxTokensInput");
    if(el) el.value = next;
    try{ syncGenerationRangeControls(); }catch(_){}
  });
  document.getElementById("apiMaxTokensSlider")?.addEventListener("change", (e)=>{
    const idx = Math.max(0, Math.min(GENERATION_MAX_TOKEN_SLIDER_VALUES.length - 1, Math.round(Number(e.target?.value || 0))));
    setGenerationHiddenValue("apiMaxTokensInput", GENERATION_MAX_TOKEN_SLIDER_VALUES[idx] || "");
  });
  document.getElementById("apiTemperatureSlider")?.addEventListener("input", (e)=>{
    const next = normalizeGenerationDecimal(e.target?.value || "", {min:0, max:2, decimals:2});
    const el = document.getElementById("apiTemperatureInput");
    if(el) el.value = next;
    try{ syncGenerationRangeControls(); }catch(_){}
  });
  document.getElementById("apiTemperatureSlider")?.addEventListener("change", (e)=>{
    setGenerationHiddenValue("apiTemperatureInput", normalizeGenerationDecimal(e.target?.value || "", {min:0, max:2, decimals:2}));
  });
  document.getElementById("apiTopPSlider")?.addEventListener("input", (e)=>{
    const next = normalizeGenerationDecimal(e.target?.value || "", {min:0, max:1, decimals:2});
    const el = document.getElementById("apiTopPInput");
    if(el) el.value = next;
    try{ syncGenerationRangeControls(); }catch(_){}
  });
  document.getElementById("apiTopPSlider")?.addEventListener("change", (e)=>{
    setGenerationHiddenValue("apiTopPInput", normalizeGenerationDecimal(e.target?.value || "", {min:0, max:1, decimals:2}));
  });
  document.querySelectorAll('[data-generation-auto]').forEach(btn=> btn.addEventListener('click', ()=>{
    const kind = String(btn.getAttribute('data-generation-auto') || '').trim();
    if(kind === 'temperature') setGenerationHiddenValue("apiTemperatureInput", "");
    else if(kind === 'top_p') setGenerationHiddenValue("apiTopPInput", "");
  }));
  document.querySelectorAll('[data-generation-preset]').forEach(btn=> btn.addEventListener('click', ()=>{
    const kind = String(btn.getAttribute('data-generation-preset') || '').trim();
    const val = String(btn.getAttribute('data-generation-value') || '').trim();
    if(kind === 'temperature') setGenerationHiddenValue("apiTemperatureInput", normalizeGenerationDecimal(val, {min:0, max:2, decimals:2}));
    else if(kind === 'top_p') setGenerationHiddenValue("apiTopPInput", normalizeGenerationDecimal(val, {min:0, max:1, decimals:2}));
  }));
  ["apiContextWindowInput","apiMaxTokensInput","apiTemperatureInput","apiTopPInput","apiResponseFormatInput","apiStreamUsageInput"].forEach(id=>{
    document.getElementById(id)?.addEventListener("change", ()=>{
      if(id === "apiResponseFormatInput" || id === "apiStreamUsageInput") syncApiGenerationSwitchControls();
      persistCurrentApiGenerationParams({silent:true});
      try{ syncGenerationSettingsContextUi(); }catch(_){}
    });
  });
  bindApiToggleBackedField("apiResponseFormatInput", "apiResponseFormatToggle", "apiResponseFormatState", {
    onValue:"json_object", offValue:"auto", normalize:normalizeApiResponseFormat, isOn:(v)=>normalizeApiResponseFormat(v)==="json_object", onText:"开启", offText:"关闭"
  });
  bindApiToggleBackedField("apiStreamUsageInput", "apiStreamUsageToggle", "apiStreamUsageState", {
    onValue:"enabled", offValue:"disabled", normalize:normalizeApiTriState, isOn:(v)=>normalizeApiTriState(v)==="enabled", onText:"开启", offText:"关闭"
  });
  document.getElementById("apiSaveBtn")?.addEventListener("click", ()=>{
    const enteredName = String(document.getElementById("apiProfileName")?.value || "").trim();
    const nextKey = String(document.getElementById("apiKeyInput")?.value || "").trim();
    const rawBase = String(document.getElementById("apiBaseInput")?.value || "").trim();
    const nextBase = normalizeApiBaseInputValue(rawBase);
    const baseInputEl = document.getElementById("apiBaseInput");
    if(baseInputEl) baseInputEl.value = nextBase;
    const nextEndpointMode = normalizeApiEndpointMode(document.getElementById("apiEndpointModeInput")?.value || "");
    const profiles = getApiProfiles();
    const activeName = getActiveApiName();
    const isNewDraft = apiProfileEditorMode === "new";
    const sourceName = isNewDraft ? "" : activeName;
    const nextName = apiProfileInputName(enteredName, sourceName, isNewDraft);
    if(isNewDraft && profiles[nextName]){
      toast(window.AperviaI18n?.t('settings.api.name_exists') || "A key with this name already exists. Choose a new name.");
      return;
    }
    if(!isNewDraft && nextName !== sourceName && profiles[nextName]){
      toast(window.AperviaI18n?.t('settings.api.name_overwrite_blocked') || "A key with this name already exists and cannot be overwritten.");
      return;
    }
    const prev = sourceName ? (profiles[sourceName] || normalizeApiProfile(sourceName, {})) : normalizeApiProfile(nextName, {});
    const meta = detectVendorMeta(nextKey, nextBase);
    const connectionChanged = String(prev.api_key || '') !== nextKey || String(prev.api_base || '') !== nextBase;
    const endpointChanged = normalizeApiEndpointMode(prev.api_endpoint_mode) !== nextEndpointMode;
    const signatureChanged = connectionChanged || endpointChanged;
    const keptSelected = connectionChanged ? [] : (prev.selected_models || []);
    const keptCache = connectionChanged ? [] : (prev.models_cache || []);
    const keptLastModel = connectionChanged ? '' : String(prev.last_model || '').trim();
    if(sourceName && nextName !== sourceName) delete profiles[sourceName];
    profiles[nextName] = normalizeApiProfile(nextName, {
      ...prev,
      api_key: nextKey,
      api_base: nextBase,
      api_base_options: mergeApiBaseOptions(prev.api_base_options || [], nextBase),
      api_endpoint_mode: nextEndpointMode,
      vendor: meta.vendor,
      vendor_label: meta.label,
      selected_models: keptSelected,
      models_cache: keptCache,
      last_model: keptLastModel,
      model_search_at: signatureChanged ? 0 : Number(prev.model_search_at || 0),
    });
    saveApiProfiles(profiles);
    setStoredApiEndpointMode(nextEndpointMode);
    saveActiveApiNameForMode(nextEndpointMode, nextName);
    setActiveApiName(nextName, {syncModel:true, refreshModelUi:true});
    renderApiQuickMenu();
    fillApiFormFromCurrent();
    renderModelManagementUi();
    if(isNewDraft){
      toast(window.AperviaI18n?.t(signatureChanged ? 'settings.api.key_created_reset' : 'settings.api.key_created') || (signatureChanged ? "Key created. The model list was reset for the new provider." : "Key created"));
    }else{
      toast(window.AperviaI18n?.t(signatureChanged ? 'settings.api.key_saved_reset' : 'settings.api.key_saved') || (signatureChanged ? "Key saved. The model list was reset for the new provider." : "Key saved"));
    }
  });
  document.getElementById("apiNewBtn")?.addEventListener("click", ()=>{
    beginNewApiProfileDraft();
  });
  document.getElementById("apiDeleteBtn")?.addEventListener("click", async ()=>{
    if(apiProfileEditorMode === "new"){
      fillApiFormFromCurrent();
      renderApiQuickMenu();
      renderApiSavedList();
      renderModelManagementUi();
      toast(window.AperviaI18n?.t('settings.api.new_cancelled') || "New key cancelled");
      return;
    }
    const active = getActiveApiName();
    const profiles = getApiProfiles();
    if(!profiles[active]) return;
    const confirmed = await askDeleteApiKeyConfirm(apiProfileDisplayName(active), document.getElementById("apiDeleteBtn"));
    if(!confirmed) return;
    const mode = getActiveApiEndpointMode();
    delete profiles[active];
    if(!Object.keys(profiles).length) profiles[DEFAULT_API_PROFILE_NAME] = normalizeApiProfile(DEFAULT_API_PROFILE_NAME, {api_key:"", api_base:"", api_endpoint_mode:mode, selected_models:[], last_model:""});
    saveApiProfiles(profiles);
    const nextActive = getFirstApiProfileNameForMode(getApiProfiles(), mode) || ensureApiProfileForMode(mode);
    setActiveApiName(nextActive);
    fillApiFormFromCurrent();
    renderApiQuickMenu();
    renderApiSavedList();
    renderModelManagementUi();
  });
}

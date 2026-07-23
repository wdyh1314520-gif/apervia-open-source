/* Settings, API/profile, personalization shell, archive/data-management UI split from index3.js. */
// ====== API Key / Web settings ======
const API_PROFILES_KEY = "webai_api_profiles_v1";
const ACTIVE_API_KEY = "webai_active_api_v1";
const WEB_SETTINGS_KEY = "webai_web_settings_v1";
const IMAGE_GENERATION_SETTINGS_KEY = "webai_image_generation_settings_v1";
const GENERATION_SETTINGS_KEY = "webai_generation_settings_v1";
const IMAGE_API_PROFILES_KEY = "webai_image_api_profiles_v1";
const ACTIVE_IMAGE_API_KEY = "webai_active_image_api_v1";
const VOICE_SETTINGS_KEY = "webai_voice_settings_v1";
const READ_ALOUD_SETTINGS_KEY = "webai_read_aloud_settings_v1";
const SETTINGS_LAST_TAB_KEY = "webai_settings_last_tab_v1";
const SETTINGS_TABS = ["api","generation","web","mcp","image","voice","models","personalization","backup","storage","account"];
function normalizeSettingsTab(value){
  const tab = String(value || "").trim();
  return SETTINGS_TABS.includes(tab) ? tab : "api";
}
const THINKING_SUPPORT_CACHE_KEY = "webai_thinking_support_v1";
const API_DEFAULT_BASE = "";
const DEFAULT_API_PROFILE_NAME = "默认API";
function apiProfileDisplayName(name){
  const raw = String(name || "").trim();
  const localized = window.AperviaI18n?.t('settings.api.default_profile') || 'Default API';
  if(!raw || raw === DEFAULT_API_PROFILE_NAME) return localized;
  if(raw.startsWith(DEFAULT_API_PROFILE_NAME + ' · ')) return localized + raw.slice(DEFAULT_API_PROFILE_NAME.length);
  return raw;
}
function apiProfileInputName(value, sourceName='', isNew=false){
  const entered = String(value || '').trim();
  const source = String(sourceName || '').trim();
  if(!entered) return DEFAULT_API_PROFILE_NAME;
  if(!isNew && source && entered === apiProfileDisplayName(source)) return source;
  return entered;
}
const API_ENDPOINT_MODE_CHAT = "chat_completions";
const API_ENDPOINT_MODE_RESPONSES = "responses";
const ACTIVE_API_ENDPOINT_MODE_KEY = "webai_active_api_endpoint_mode_v1";
const ACTIVE_API_BY_MODE_KEY = "webai_active_api_by_mode_v1";
const ACCOUNT_SCOPED_SECRET_SETTING_KEYS = [
  API_PROFILES_KEY,
  ACTIVE_API_KEY,
  WEB_SETTINGS_KEY,
  IMAGE_GENERATION_SETTINGS_KEY,
  GENERATION_SETTINGS_KEY,
  IMAGE_API_PROFILES_KEY,
  ACTIVE_IMAGE_API_KEY,
  VOICE_SETTINGS_KEY,
  READ_ALOUD_SETTINGS_KEY,
  ACTIVE_API_ENDPOINT_MODE_KEY,
  ACTIVE_API_BY_MODE_KEY,
];
function accountScopedSettingEmail(scopeEmail = currentAccountEmail){
  try{ return normalizeAccountScopeEmail(scopeEmail || currentAccountEmail || ''); }
  catch(_){ return String(scopeEmail || currentAccountEmail || '').trim().toLowerCase(); }
}
function accountScopedSettingStorageKey(baseKey, scopeEmail = currentAccountEmail){
  const key = String(baseKey || '').trim();
  if(!key) return key;
  const email = accountScopedSettingEmail(scopeEmail);
  return email ? `${key}::acct::${encodeURIComponent(email)}` : key;
}
function readAccountScopedSettingItem(baseKey, scopeEmail = currentAccountEmail){
  try{ return localStorage.getItem(accountScopedSettingStorageKey(baseKey, scopeEmail)); }
  catch(_){ return null; }
}
function writeAccountScopedSettingItem(baseKey, value, scopeEmail = currentAccountEmail){
  try{ localStorage.setItem(accountScopedSettingStorageKey(baseKey, scopeEmail), String(value)); }catch(_){ }
}
function refreshAccountScopedSecretSettingsUi(reason = ''){
  try{ updateApiButton(); }catch(_){ }
  try{ renderApiQuickMenu(); }catch(_){ }
  try{ renderApiSavedList(); }catch(_){ }
  try{ fillApiFormFromCurrent(); }catch(_){ }
  try{ syncApiSettingsModeUi(); }catch(_){ }
  try{ updateApiVendorPreview(); }catch(_){ }
  try{ syncModelOptionsForActiveProfile({ ensureSessionValue:false }); }catch(_){ }
  try{ renderModelManagementUi(); }catch(_){ }
  try{ fillWebSettingsForm(); }catch(_){ }
  try{ syncMcpDeveloperModeUi(); }catch(_){ }
  try{ refreshThinkingControlUi(); }catch(_){ }
  try{ fillImageApiFormFromCurrent(); }catch(_){ }
  try{ renderImageApiSavedList(); }catch(_){ }
  try{ fillImageGenerationSettingsForm(); }catch(_){ }
  try{ fillVoiceSettingsForm(); }catch(_){ }
  try{ fillReadAloudSettingsForm(); }catch(_){ }
  try{ refreshVoiceInputAvailability(); }catch(_){ }
  try{ syncComposerAddMenuUi(); }catch(_){ }
  try{ initSecretInputToggles(document.getElementById('settingsModal') || document); }catch(_){ }
}
function normalizeApiEndpointMode(value){
  const raw = String(value || "").trim().toLowerCase();
  if(raw === "responses" || raw === "response" || raw === "/responses") return API_ENDPOINT_MODE_RESPONSES;
  return API_ENDPOINT_MODE_CHAT;
}
function isExplicitApiEndpointMode(value){
  const raw = String(value || "").trim().toLowerCase();
  return raw === API_ENDPOINT_MODE_CHAT || raw === "chat" || raw === "chat_completions" || raw === "chat-completions" || raw === "completions"
    || raw === API_ENDPOINT_MODE_RESPONSES || raw === "response" || raw === "/responses";
}
function apiEndpointModeLabel(value){
  return normalizeApiEndpointMode(value) === API_ENDPOINT_MODE_RESPONSES ? "Responses" : "Chat Completions";
}
function normalizeResponsesReasoningEffort(value){
  const raw = String(value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
  const aliases = {
    "": "auto",
    "default": "auto",
    "automatic": "auto",
    "自动": "auto",
    "off": "none",
    "false": "none",
    "no": "none",
    "disable": "none",
    "disabled": "none",
    "关闭": "none",
    "none": "none",
    "minimal": "minimal",
    "mini": "minimal",
    "最低": "minimal",
    "low": "low",
    "低": "low",
    "medium": "medium",
    "mid": "medium",
    "normal": "medium",
    "中": "medium",
    "high": "high",
    "hight": "high",
    "高": "high",
    "enabled": "high",
    "enable": "high",
    "on": "high",
    "true": "high",
    "yes": "high",
    "xhigh": "xhigh",
    "x_high": "xhigh",
    "extra_high": "xhigh",
    "very_high": "xhigh",
    "max": "max",
    "极高": "xhigh",
  };
  return aliases[raw] || "auto";
}
function responsesReasoningEffortLabel(value){
  const mode = normalizeResponsesReasoningEffort(value);
  if(mode === "none") return "无";
  if(mode === "minimal") return "极低";
  if(mode === "low") return "低";
  if(mode === "medium") return "中";
  if(mode === "high") return "高";
  if(mode === "xhigh") return "极高";
  if(mode === "max") return "最大";
  return "自动";
}
function normalizeResponsesReasoningSummary(value){
  const raw = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if(["off","false","no","disable","disabled","none","关闭"].includes(raw)) return "off";
  if(raw === "concise" || raw === "简洁") return "concise";
  if(raw === "detailed" || raw === "详细") return "detailed";
  return "auto";
}
function responsesReasoningSummaryLabel(value){
  const mode = normalizeResponsesReasoningSummary(value);
  if(mode === "off") return "关闭";
  if(mode === "concise") return "简洁";
  if(mode === "detailed") return "详细";
  return "自动";
}
function normalizeResponsesReasoningContext(value){
  const raw = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if(["current","current_turn","turn","本轮"].includes(raw)) return "current_turn";
  if(["all","all_turns","persistent","全部轮次"].includes(raw)) return "all_turns";
  return "auto";
}
function responsesReasoningContextLabel(value){
  const mode = normalizeResponsesReasoningContext(value);
  if(mode === "current_turn") return "仅本轮";
  if(mode === "all_turns") return "全部轮次";
  return "自动";
}
function responsesModelSupportsReasoningContext(value){
  const raw = String(value || "").trim().toLowerCase();
  if(!raw) return false;
  const modelId = raw.split("/").pop() || raw;
  if(["sol", "terra", "luna"].includes(modelId)) return true;
  return /^gpt[-_.]?5[._-]?6(?:$|[-_.])/.test(modelId);
}
function currentResponsesReasoningModel(value=""){
  const explicit = String(value || "").trim();
  if(explicit) return explicit;
  const selected = String(document.getElementById("model")?.value || "").trim();
  if(selected) return selected;
  try{
    const activeModel = String((typeof getActive === "function" ? getActive()?.model : "") || "").trim();
    if(activeModel) return activeModel;
  }catch(_){ }
  try{
    const profileModel = String((typeof getCurrentApiProfile === "function" ? getCurrentApiProfile()?.last_model : "") || "").trim();
    if(profileModel) return profileModel;
  }catch(_){ }
  return "";
}
function syncResponsesReasoningChoice(value, {normalizer, values, inputId, labelId, labeler, dataAttribute}){
  const normalized = normalizer(value);
  const selected = values.includes(normalized) ? normalized : values[0];
  const hidden = document.getElementById(inputId);
  const label = document.getElementById(labelId);
  if(hidden && hidden.value !== selected) hidden.value = selected;
  if(label) label.textContent = labeler(selected);
  document.querySelectorAll(`[${dataAttribute}]`).forEach(btn=>{
    const btnMode = normalizer(btn.getAttribute(dataAttribute) || values[0]);
    btn.classList.toggle("active", btnMode === selected);
  });
  return selected;
}
const RESPONSES_REASONING_EFFORT_SLIDER_VALUES = ["auto", "none", "low", "medium", "high", "xhigh", "max"];
function responsesReasoningEffortSliderIndex(value){
  const mode = normalizeResponsesReasoningEffort(value);
  const idx = RESPONSES_REASONING_EFFORT_SLIDER_VALUES.indexOf(mode);
  return idx >= 0 ? idx : 0;
}
function responsesReasoningEffortFromSliderIndex(index){
  const idx = Math.max(0, Math.min(RESPONSES_REASONING_EFFORT_SLIDER_VALUES.length - 1, Math.round(Number(index) || 0)));
  return RESPONSES_REASONING_EFFORT_SLIDER_VALUES[idx] || "auto";
}
function syncResponsesReasoningEffortSlider(value){
  const sliderMode = syncResponsesReasoningChoice(value, {
    normalizer: normalizeResponsesReasoningEffort,
    values: RESPONSES_REASONING_EFFORT_SLIDER_VALUES,
    inputId: "responsesReasoningEffortInput",
    labelId: "responsesReasoningEffortValue",
    labeler: responsesReasoningEffortLabel,
    dataAttribute: "data-reasoning-effort-value",
  });
  const idx = responsesReasoningEffortSliderIndex(sliderMode);
  const slider = document.getElementById("responsesReasoningEffortSlider");
  if(slider && String(slider.value) !== String(idx)) slider.value = String(idx);
}
function syncResponsesReasoningSummaryUi(value){
  return syncResponsesReasoningChoice(value, {
    normalizer: normalizeResponsesReasoningSummary,
    values: ["auto", "concise", "detailed", "off"],
    inputId: "responsesReasoningSummaryInput",
    labelId: "responsesReasoningSummaryValue",
    labeler: responsesReasoningSummaryLabel,
    dataAttribute: "data-reasoning-summary-value",
  });
}
function syncResponsesReasoningContextChoice(value){
  return syncResponsesReasoningChoice(value, {
    normalizer: normalizeResponsesReasoningContext,
    values: ["auto", "current_turn", "all_turns"],
    inputId: "responsesReasoningContextInput",
    labelId: "responsesReasoningContextValue",
    labeler: responsesReasoningContextLabel,
    dataAttribute: "data-reasoning-context-value",
  });
}

const GENERATION_MAX_TOKEN_SLIDER_VALUES = ["", "512", "1024", "2048", "4096", "8192", "16384"];
const GENERATION_CONTEXT_WINDOW_SLIDER_VALUES = ["", "16000", "32000", "64000", "128000", "200000", "1000000"];
function normalizeGenerationDecimal(value, {min=0, max=1, decimals=2}={}){
  const raw = String(value ?? "").trim();
  if(!raw) return "";
  const num = Number(raw);
  if(!Number.isFinite(num)) return "";
  const clamped = Math.max(min, Math.min(max, num));
  return String(Number(clamped.toFixed(decimals)));
}
function generationMaxTokensSliderIndex(value){
  const raw = String(value || "").trim();
  if(!raw) return 0;
  const idx = GENERATION_MAX_TOKEN_SLIDER_VALUES.indexOf(raw);
  if(idx >= 0) return idx;
  const num = Number(raw);
  if(!Number.isFinite(num) || num <= 0) return 0;
  let best = 1;
  let bestDiff = Infinity;
  GENERATION_MAX_TOKEN_SLIDER_VALUES.forEach((item, index)=>{
    if(!item) return;
    const n = Number(item);
    const diff = Math.abs(n - num);
    if(diff < bestDiff){ bestDiff = diff; best = index; }
  });
  return best;
}
function generationMaxTokensLabel(value){
  const raw = String(value || "").trim();
  if(!raw) return "自动";
  const num = Number(raw);
  if(!Number.isFinite(num)) return "自动";
  if(num >= 1000) return `${Math.round(num / 100) / 10}K tokens`;
  return `${num} tokens`;
}
function generationContextWindowSliderIndex(value){
  const raw = String(value || "").trim();
  if(!raw) return 0;
  const idx = GENERATION_CONTEXT_WINDOW_SLIDER_VALUES.indexOf(raw);
  if(idx >= 0) return idx;
  const num = Number(raw);
  if(!Number.isFinite(num) || num <= 0) return 0;
  let best = 1;
  let bestDiff = Infinity;
  GENERATION_CONTEXT_WINDOW_SLIDER_VALUES.forEach((item, index)=>{
    if(!item) return;
    const n = Number(item);
    const diff = Math.abs(n - num);
    if(diff < bestDiff){ bestDiff = diff; best = index; }
  });
  return best;
}
function syncGenerationRangeControls(){
  const contextInput = document.getElementById("apiContextWindowInput");
  const contextSlider = document.getElementById("apiContextWindowSlider");
  const contextValue = document.getElementById("apiContextWindowValue");
  const contextRaw = String(contextInput?.value || "").trim();
  if(contextSlider){
    const idx = generationContextWindowSliderIndex(contextRaw);
    if(String(contextSlider.value) !== String(idx)) contextSlider.value = String(idx);
  }
  if(contextValue) contextValue.textContent = generationMaxTokensLabel(contextRaw);

  const maxInput = document.getElementById("apiMaxTokensInput");
  const maxSlider = document.getElementById("apiMaxTokensSlider");
  const maxValue = document.getElementById("apiMaxTokensValue");
  const maxRaw = String(maxInput?.value || "").trim();
  if(maxSlider){
    const idx = generationMaxTokensSliderIndex(maxRaw);
    if(String(maxSlider.value) !== String(idx)) maxSlider.value = String(idx);
  }
  if(maxValue) maxValue.textContent = generationMaxTokensLabel(maxRaw);

  const tempInput = document.getElementById("apiTemperatureInput");
  const tempSlider = document.getElementById("apiTemperatureSlider");
  const tempValue = document.getElementById("apiTemperatureValue");
  const tempRaw = normalizeGenerationDecimal(tempInput?.value || "", {min:0, max:2, decimals:2});
  if(tempInput && tempInput.value !== tempRaw) tempInput.value = tempRaw;
  if(tempSlider){
    const tempAuto = !tempRaw;
    const tempNext = tempAuto ? String(tempSlider.min || "0") : String(tempRaw);
    if(String(tempSlider.value) !== tempNext) tempSlider.value = tempNext;
    tempSlider.classList.toggle("is-auto", tempAuto);
    try{ tempSlider.closest(".generation-range-control")?.classList.toggle("is-auto", tempAuto); }catch(_){ }
  }
  if(tempValue) tempValue.textContent = tempRaw ? tempRaw : "自动";

  const topPInput = document.getElementById("apiTopPInput");
  const topPSlider = document.getElementById("apiTopPSlider");
  const topPValue = document.getElementById("apiTopPValue");
  const topPRaw = normalizeGenerationDecimal(topPInput?.value || "", {min:0, max:1, decimals:2});
  if(topPInput && topPInput.value !== topPRaw) topPInput.value = topPRaw;
  if(topPSlider){
    const topPAuto = !topPRaw;
    const topPNext = topPAuto ? String(topPSlider.min || "0") : String(topPRaw);
    if(String(topPSlider.value) !== topPNext) topPSlider.value = topPNext;
    topPSlider.classList.toggle("is-auto", topPAuto);
    try{ topPSlider.closest(".generation-range-control")?.classList.toggle("is-auto", topPAuto); }catch(_){ }
  }
  if(topPValue) topPValue.textContent = topPRaw ? topPRaw : "自动";

  document.querySelectorAll('[data-generation-auto]').forEach(btn=>{
    const kind = String(btn.getAttribute('data-generation-auto') || '').trim();
    const isAuto = kind === 'temperature' ? !tempRaw : kind === 'top_p' ? !topPRaw : false;
    btn.classList.toggle('active', isAuto);
  });
  document.querySelectorAll('[data-generation-preset]').forEach(btn=>{
    const kind = String(btn.getAttribute('data-generation-preset') || '').trim();
    const val = String(btn.getAttribute('data-generation-value') || '').trim();
    const cur = kind === 'temperature' ? tempRaw : kind === 'top_p' ? topPRaw : '';
    btn.classList.toggle('active', !!cur && cur === normalizeGenerationDecimal(val, {min: kind === 'temperature' ? 0 : 0, max: kind === 'temperature' ? 2 : 1, decimals:2}));
  });
}
function setGenerationHiddenValue(inputId, value){
  const el = document.getElementById(inputId);
  if(!el) return;
  el.value = String(value ?? "").trim();
  try{ syncGenerationRangeControls(); }catch(_){}
  el.dispatchEvent(new Event("change", { bubbles:true }));
}
function syncGenerationSettingsContextUi(profile){
  const cur = profile && typeof profile === "object" ? profile : getCurrentApiProfile();
  const mode = getActiveApiEndpointMode();
  const generation = getGenerationSettings();
  const title = document.getElementById("generationSettingsTitle");
  const badge = document.getElementById("generationSettingsBadge");
  const hint = document.getElementById("generationSettingsHint");
  if(title) title.textContent = window.AperviaI18n?.t('settings.generation.title') || "统一生成设置";
  if(badge) badge.textContent = window.AperviaI18n?.t('settings.generation.global') || "全局";
  if(hint){
    const params = apiGenerationParamsSummary(generation);
    hint.textContent = window.AperviaI18n?.t('settings.generation.context', {mode:apiEndpointModeLabel(mode), params:params ? ` · ${params}` : ''}) || `全局生效 · 当前 ${apiEndpointModeLabel(mode)}${params ? ` · ${params}` : ""}`;
  }
}
function normalizeApiOptionalPositiveInt(value, {max=200000} = {}){
  const raw = String(value ?? "").trim();
  if(!raw || /^(auto|default|默认|自动)$/i.test(raw)) return "";
  const n = Math.floor(Number(raw));
  if(!Number.isFinite(n) || n <= 0) return "";
  return Math.max(1, Math.min(Number(max || 200000) || 200000, n));
}
function normalizeApiOptionalFloat(value, {min=0, max=1} = {}){
  const raw = String(value ?? "").trim();
  if(!raw || /^(auto|default|默认|自动)$/i.test(raw)) return "";
  const n = Number(raw);
  if(!Number.isFinite(n)) return "";
  const lo = Number(min);
  const hi = Number(max);
  const clipped = Math.max(Number.isFinite(lo) ? lo : 0, Math.min(Number.isFinite(hi) ? hi : 1, n));
  return Number(clipped.toFixed(4));
}
function normalizeApiResponseFormat(value){
  const raw = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if(raw === "json" || raw === "json_object" || raw === "object") return "json_object";
  return "auto";
}
function normalizeApiTriState(value){
  const raw = String(value || "").trim().toLowerCase();
  if(["1","true","yes","on","enable","enabled","开启","打开"].includes(raw)) return "enabled";
  if(["0","false","no","off","disable","disabled","关闭"].includes(raw)) return "disabled";
  return "auto";
}
function normalizeGenerationSettings(raw){
  const item = raw && typeof raw === "object" ? raw : {};
  return {
    responses_reasoning_effort: normalizeResponsesReasoningEffort(item.responses_reasoning_effort || item.responsesReasoningEffort || item.RESPONSES_REASONING_EFFORT || "auto"),
    responses_reasoning_summary: normalizeResponsesReasoningSummary(item.responses_reasoning_summary || item.responsesReasoningSummary || item.RESPONSES_REASONING_SUMMARY || "detailed"),
    responses_reasoning_context: normalizeResponsesReasoningContext(item.responses_reasoning_context || item.responsesReasoningContext || item.RESPONSES_REASONING_CONTEXT || "auto"),
    generation_context_window_tokens: normalizeApiOptionalPositiveInt(item.generation_context_window_tokens ?? item.context_window_tokens ?? item.context_window ?? item.max_context_tokens, {max:2000000}),
    generation_max_tokens: normalizeApiOptionalPositiveInt(item.generation_max_tokens ?? item.max_output_tokens ?? item.max_completion_tokens ?? item.max_tokens, {max:200000}),
    generation_temperature: normalizeApiOptionalFloat(item.generation_temperature ?? item.temperature, {min:0, max:2}),
    generation_top_p: normalizeApiOptionalFloat(item.generation_top_p ?? item.top_p, {min:0, max:1}),
    generation_response_format: normalizeApiResponseFormat(item.generation_response_format ?? item.response_format),
    generation_include_usage: normalizeApiTriState(item.generation_include_usage ?? item.stream_include_usage ?? item.include_usage),
  };
}
function generationSettingsAreDefault(settings){
  const row = normalizeGenerationSettings(settings || {});
  return !row.generation_context_window_tokens
    && !row.generation_max_tokens
    && row.generation_temperature === ""
    && row.generation_top_p === ""
    && row.generation_response_format === "auto"
    && row.generation_include_usage === "auto"
    && row.responses_reasoning_effort === "auto"
    && row.responses_reasoning_summary === "detailed"
    && row.responses_reasoning_context === "auto";
}
function getGenerationSettings(){
  let raw = null;
  try{ raw = JSON.parse(readAccountScopedSettingItem(GENERATION_SETTINGS_KEY) || "null"); }catch(_){ raw = null; }
  if(!raw || typeof raw !== "object"){
    // 兼容旧版本：第一次升级时，把当前 Key 里的生成参数迁移成统一参数。
    try{
      const cur = typeof getCurrentApiProfile === "function" ? getCurrentApiProfile() : null;
      if(cur && typeof cur === "object"){
        const migrated = normalizeGenerationSettings(cur);
        if(!generationSettingsAreDefault(migrated)){
          writeAccountScopedSettingItem(GENERATION_SETTINGS_KEY, JSON.stringify(migrated));
          return migrated;
        }
      }
    }catch(_){ }
    return normalizeGenerationSettings({});
  }
  return normalizeGenerationSettings(raw);
}
function saveGenerationSettings(settings){
  const normalized = normalizeGenerationSettings(settings || {});
  writeAccountScopedSettingItem(GENERATION_SETTINGS_KEY, JSON.stringify(normalized));
  return normalized;
}
function generationSettingsForRequest(){
  return normalizeGenerationSettings(getGenerationSettings());
}
function applyGenerationSettingsToApiPayload(payload, generationSettings, selectedModel=""){
  const out = { ...(payload || {}) };
  const gen = normalizeGenerationSettings(generationSettings || getGenerationSettings());
  const endpointMode = normalizeApiEndpointMode(out.api_endpoint_mode || out.endpoint_mode || API_ENDPOINT_MODE_CHAT);
  const reasoningModel = currentResponsesReasoningModel(selectedModel || out.model || "");
  let upstreamModelMeta = {};
  try{
    if(typeof modelMetadataForProfileModel === "function" && typeof getCurrentApiProfile === "function"){
      upstreamModelMeta = modelMetadataForProfileModel(getCurrentApiProfile(), out.model || "");
    }
  }catch(_){ upstreamModelMeta = {}; }
  if(endpointMode === API_ENDPOINT_MODE_RESPONSES){
    out.responses_reasoning_effort = gen.responses_reasoning_effort;
    out.responses_reasoning_summary = gen.responses_reasoning_summary;
    if(responsesModelSupportsReasoningContext(reasoningModel)){
      out.responses_reasoning_context = gen.responses_reasoning_context;
    }else{
      delete out.responses_reasoning_context;
    }
  }else{
    delete out.responses_reasoning_effort;
    delete out.responses_reasoning_summary;
    delete out.responses_reasoning_context;
  }
  out.generation_context_window_tokens = gen.generation_context_window_tokens || upstreamModelMeta.context_window_tokens || "";
  out.generation_max_tokens = gen.generation_max_tokens;
  out.generation_upstream_max_output_tokens = upstreamModelMeta.max_output_tokens || "";
  out.generation_context_window_source = gen.generation_context_window_tokens ? "configured" : (upstreamModelMeta.context_window_tokens ? "upstream_models" : "");
  out.generation_temperature = gen.generation_temperature;
  out.generation_top_p = gen.generation_top_p;
  out.generation_response_format = gen.generation_response_format;
  out.generation_include_usage = gen.generation_include_usage;
  return out;
}
function apiGenerationParamsSummary(settings){
  const row = normalizeGenerationSettings(settings || getGenerationSettings());
  const bits = [];
  if(row.generation_context_window_tokens) bits.push(window.AperviaI18n?.t('settings.generation.context_param', {value:generationMaxTokensLabel(row.generation_context_window_tokens)}) || `上下文 ${generationMaxTokensLabel(row.generation_context_window_tokens)}`);
  if(row.generation_max_tokens) bits.push(window.AperviaI18n?.t('settings.generation.output_param', {value:row.generation_max_tokens}) || `输出 ${row.generation_max_tokens}`);
  if(row.generation_temperature !== "") bits.push(`T ${row.generation_temperature}`);
  if(row.generation_top_p !== "") bits.push(`P ${row.generation_top_p}`);
  if(row.generation_response_format === "json_object") bits.push("JSON");
  if(row.generation_include_usage === "enabled") bits.push(window.AperviaI18n?.t('settings.generation.usage_param') || "显示用量");
  if(row.responses_reasoning_effort !== "auto") bits.push(window.AperviaI18n?.t('settings.generation.reasoning_param', {value:responsesReasoningEffortLabel(row.responses_reasoning_effort)}) || `Responses 推理${responsesReasoningEffortLabel(row.responses_reasoning_effort)}`);
  if(row.responses_reasoning_summary !== "detailed") bits.push(window.AperviaI18n?.t('settings.generation.summary_param', {value:responsesReasoningSummaryLabel(row.responses_reasoning_summary)}) || `摘要${responsesReasoningSummaryLabel(row.responses_reasoning_summary)}`);
  if(row.responses_reasoning_context !== "auto") bits.push(window.AperviaI18n?.t('settings.generation.reasoning_context_param', {value:responsesReasoningContextLabel(row.responses_reasoning_context)}) || `推理上下文${responsesReasoningContextLabel(row.responses_reasoning_context)}`);
  return bits.join(" · ");
}
function syncResponsesReasoningEffortFieldVisibility(){
  const isResponses = getActiveApiEndpointMode() === API_ENDPOINT_MODE_RESPONSES;
  const supportsReasoningContext = isResponses && responsesModelSupportsReasoningContext(currentResponsesReasoningModel());
  ["responsesReasoningEffortField", "responsesReasoningSummaryField"].forEach(id=>{
    const field = document.getElementById(id);
    if(!field) return;
    field.hidden = !isResponses;
    field.style.display = isResponses ? "" : "none";
  });
  const contextField = document.getElementById("responsesReasoningContextField");
  if(contextField){
    contextField.hidden = !supportsReasoningContext;
    contextField.style.display = supportsReasoningContext ? "" : "none";
  }
}
function syncApiGenerationSettingsUi(){
  const mode = getActiveApiEndpointMode();
  const isResponses = mode === API_ENDPOINT_MODE_RESPONSES;
  const maxLabel = document.getElementById("apiMaxTokensLabel");
  if(maxLabel) maxLabel.textContent = "最大输出 Tokens";
  const responseLabel = document.getElementById("apiResponseFormatLabel");
  if(responseLabel) responseLabel.textContent = "JSON 输出";
  const note = document.getElementById("apiResponseFormatNote");
  if(note) note.textContent = "";
  try{ syncGenerationSettingsContextUi(); }catch(_){}
  const usageField = document.getElementById("apiStreamUsageField");
  if(usageField){
    usageField.hidden = false;
    usageField.style.display = "";
  }
  try{ syncGenerationRangeControls(); }catch(_){}
}
function syncApiSettingsModeUi(){
  const mode = getActiveApiEndpointMode();
  const isResponses = mode === API_ENDPOINT_MODE_RESPONSES;
  document.querySelectorAll('[data-api-settings-mode]').forEach(btn=>{
    const btnMode = normalizeApiEndpointMode(btn.getAttribute('data-api-settings-mode') || '');
    btn.classList.toggle('active', btnMode === mode);
    btn.setAttribute('aria-selected', btnMode === mode ? 'true' : 'false');
  });
  const currentTitle = document.getElementById('apiCurrentTitle');
  if(currentTitle) currentTitle.textContent = '当前 Key';
  const savedTitle = document.getElementById('apiSavedTitle');
  if(savedTitle) savedTitle.textContent = '已保存 Key';
  const savedHint = document.getElementById('apiSavedHint');
  if(savedHint) savedHint.textContent = '';
  try{ syncGenerationSettingsContextUi(); }catch(_){}
  const endpointModeEl = document.getElementById('apiEndpointModeInput');
  if(endpointModeEl && normalizeApiEndpointMode(endpointModeEl.value) !== mode) endpointModeEl.value = mode;
  const endpointModeDisplay = document.getElementById('apiEndpointModeDisplay');
  if(endpointModeDisplay){
    endpointModeDisplay.textContent = isResponses ? 'Responses（/responses）' : 'Chat Completions（/chat/completions）';
  }
  syncResponsesReasoningEffortFieldVisibility();
  syncApiGenerationSettingsUi();
}
function activateApiSettingsMode(mode){
  const nextMode = normalizeApiEndpointMode(mode);
  setCurrentApiEndpointMode(nextMode);
  syncApiSettingsModeUi();
}
function getStoredApiEndpointMode(){
  try{
    const saved = String(readAccountScopedSettingItem(ACTIVE_API_ENDPOINT_MODE_KEY) || "").trim();
    if(isExplicitApiEndpointMode(saved)) return normalizeApiEndpointMode(saved);
  }catch(_){ }
  try{
    const legacyActive = String(readAccountScopedSettingItem(ACTIVE_API_KEY) || "").trim();
    const rawProfiles = JSON.parse(readAccountScopedSettingItem(API_PROFILES_KEY) || "{}");
    const legacy = rawProfiles && typeof rawProfiles === "object" ? rawProfiles[legacyActive] : null;
    if(legacy && typeof legacy === "object" && isExplicitApiEndpointMode(legacy.api_endpoint_mode || legacy.endpoint_mode || legacy.apiMode || legacy.interface_mode)){
      return normalizeApiEndpointMode(legacy.api_endpoint_mode || legacy.endpoint_mode || legacy.apiMode || legacy.interface_mode);
    }
  }catch(_){ }
  return API_ENDPOINT_MODE_CHAT;
}
function setStoredApiEndpointMode(mode){
  const nextMode = normalizeApiEndpointMode(mode);
  try{ writeAccountScopedSettingItem(ACTIVE_API_ENDPOINT_MODE_KEY, nextMode); }catch(_){ }
  return nextMode;
}
function getActiveApiModeMap(){
  try{
    const parsed = JSON.parse(readAccountScopedSettingItem(ACTIVE_API_BY_MODE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  }catch(_){
    return {};
  }
}
function saveActiveApiNameForMode(mode, name){
  const nextMode = normalizeApiEndpointMode(mode);
  const nextName = String(name || "").trim();
  if(!nextName) return;
  const map = getActiveApiModeMap();
  map[nextMode] = nextName;
  try{ writeAccountScopedSettingItem(ACTIVE_API_BY_MODE_KEY, JSON.stringify(map)); }catch(_){ }
  try{ writeAccountScopedSettingItem(ACTIVE_API_KEY, nextName); }catch(_){ }
}
function apiProfileMode(profile){
  return normalizeApiEndpointMode((profile || {}).api_endpoint_mode || (profile || {}).endpoint_mode || (profile || {}).apiMode || (profile || {}).interface_mode);
}
function apiProfileMatchesMode(profile, mode){
  return apiProfileMode(profile || {}) === normalizeApiEndpointMode(mode);
}
function getFirstApiProfileNameForMode(profiles, mode){
  const targetMode = normalizeApiEndpointMode(mode);
  for(const [name, profile] of Object.entries(profiles || {})){
    if(apiProfileMatchesMode(profile, targetMode)) return String(name || "").trim();
  }
  return "";
}
function buildApiProfileNameForMode(baseName, mode, profiles){
  const suffix = normalizeApiEndpointMode(mode) === API_ENDPOINT_MODE_RESPONSES ? "Responses" : "Chat";
  const cleanBase = String(baseName || DEFAULT_API_PROFILE_NAME).replace(/\s*[·-]\s*(Responses|Chat|Chat Completions)$/i, "").trim() || DEFAULT_API_PROFILE_NAME;
  const first = `${cleanBase} · ${suffix}`;
  if(!(profiles || {})[first]) return first;
  for(let i = 2; i <= 99; i++){
    const candidate = `${first} ${i}`;
    if(!(profiles || {})[candidate]) return candidate;
  }
  return `${first} ${Date.now()}`;
}
const DEFAULT_MODEL = "gpt-5.4-nano";
let SETTINGS_MODAL_OPEN = false;
let settingsLastFocusedEl = null;
let settingsActiveTab = normalizeSettingsTab(localStorage.getItem(SETTINGS_LAST_TAB_KEY) || "api");
let apiProfileEditorMode = "edit";
let imageApiProfileEditorMode = "edit";
let imageSettingsActiveSubtab = (["image_api","image_gen","image_edit"].includes(localStorage.getItem("ow_image_settings_last_subtab") || "") ? (localStorage.getItem("ow_image_settings_last_subtab") || "image_api") : "image_api");
let webSettingsActiveSubtab = (["search_api","image_search","content_fetch","limits"].includes(localStorage.getItem("ow_web_settings_last_subtab") || "") ? (localStorage.getItem("ow_web_settings_last_subtab") || "search_api") : "search_api");

function imageGenDraftComparable(raw){
  const cfg = normalizeImageGenerationSettings(raw || {});
  return {
    engine: cfg.engine,
    model: cfg.model,
    api_base: cfg.api_base,
    api_key: cfg.api_key,
    size: cfg.size,
    extra_body: cfg.extra_body,
  };
}
function imageEditDraftComparable(raw){
  const cfg = normalizeImageGenerationSettings(raw || {});
  return {
    edit_enabled: !!cfg.edit_enabled,
    edit_engine: cfg.edit_engine,
    edit_model: cfg.edit_model,
    edit_api_base: cfg.edit_api_base,
    edit_api_key: cfg.edit_api_key,
    edit_size: cfg.edit_size,
    edit_extra_body: cfg.edit_extra_body,
  };
}
const SETTINGS_DRAFT_CONTROLLERS = new Map();
function settingsDraftStableStringify(value){
  try{ return JSON.stringify(value === undefined ? null : value); }catch(_){ return ''; }
}
function registerSettingsDraftController(id, controller){
  const key = String(id || '').trim();
  if(!key || !controller) return;
  SETTINGS_DRAFT_CONTROLLERS.set(key, controller);
}
function getActiveSettingsDraftControllerId(){
  if(settingsActiveTab === 'personalization') return 'personalization';
  if(settingsActiveTab === 'voice') return 'voice';
  if(settingsActiveTab === 'web') return 'web';
  if(settingsActiveTab === 'image'){
    if(imageSettingsActiveSubtab === 'image_gen') return 'image_gen';
    if(imageSettingsActiveSubtab === 'image_edit') return 'image_edit';
  }
  return '';
}
function getSettingsDraftController(id = getActiveSettingsDraftControllerId()){
  const key = String(id || '').trim();
  return key ? (SETTINGS_DRAFT_CONTROLLERS.get(key) || null) : null;
}
function isSettingsDraftDirty(id = getActiveSettingsDraftControllerId()){
  const controller = getSettingsDraftController(id);
  if(!controller) return false;
  if(typeof controller.isDirty === 'function') return !!controller.isDirty();
  const read = typeof controller.read === 'function' ? controller.read() : null;
  const saved = typeof controller.saved === 'function' ? controller.saved() : null;
  return settingsDraftStableStringify(read) !== settingsDraftStableStringify(saved);
}
function setSettingsDraftActionsVisible(visible, opts={}){
  const bar = document.getElementById('settingsDraftActions');
  const saveBtn = document.getElementById('settingsDraftSaveBtn');
  const cancelBtn = document.getElementById('settingsDraftCancelBtn');
  const workspace = document.querySelector('#settingsModal .settings-workspace');
  if(!bar) return;
  const shouldShow = !!visible;
  const busy = !!opts.busy;
  bar.hidden = !shouldShow;
  bar.classList.toggle('is-busy', busy);
  if(workspace) workspace.classList.toggle('has-draft-actions', shouldShow);
  if(saveBtn) saveBtn.disabled = busy;
  if(cancelBtn) cancelBtn.disabled = busy;
}
function refreshSettingsDraftActions(){
  const id = getActiveSettingsDraftControllerId();
  const controller = getSettingsDraftController(id);
  const visible = isSettingsModalOpen() && !!controller && isSettingsDraftDirty(id);
  const bar = document.getElementById('settingsDraftActions');
  if(bar) bar.dataset.settingsDraft = visible ? id : '';
  setSettingsDraftActionsVisible(visible);
}
function handleSettingsDraftInput(){
  const controller = getSettingsDraftController();
  try{ controller?.onInput?.(); }catch(_){ }
  refreshSettingsDraftActions();
}
async function saveActiveSettingsDraftFromActions(){
  const id = getActiveSettingsDraftControllerId();
  const controller = getSettingsDraftController(id);
  if(!controller || typeof controller.save !== 'function') return;
  const wasVisible = !document.getElementById('settingsDraftActions')?.hidden;
  try{
    setSettingsDraftActionsVisible(true, { busy:true });
    await controller.save();
    try{ controller.afterSave?.(); }catch(_){ }
    refreshSettingsDraftActions();
  }catch(err){
    try{ controller.cancel?.({ failed:true }); }catch(_){ }
    setSettingsDraftActionsVisible(wasVisible && isSettingsDraftDirty(id));
    try{ toast(err?.message || window.AperviaI18n?.t('common.save_failed') || 'Save failed'); }catch(_){ }
  }
}
function cancelActiveSettingsDraftFromActions(){
  const controller = getSettingsDraftController();
  try{ document.activeElement?.blur?.(); }catch(_){ }
  try{ controller?.cancel?.({ discard:true }); }catch(_){ }
  refreshSettingsDraftActions();
}
function shouldConfirmSettingsDraftExit(){
  return isSettingsModalOpen() && isSettingsDraftDirty();
}
async function confirmAndDiscardSettingsDraft(returnFocusEl = null){
  if(!shouldConfirmSettingsDraftExit()) return true;
  const ok = await askSettingsUnsavedExit(returnFocusEl);
  if(!ok) return false;
  cancelActiveSettingsDraftFromActions();
  return true;
}
async function requestCloseSettingsModal(opts = {}){
  const returnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : document.getElementById('settingsCloseBtn');
  if(!(await confirmAndDiscardSettingsDraft(returnFocusEl))) return false;
  closeSettingsModal(opts);
  return true;
}
async function requestActivateSettingsTab(tab, opts = {}){
  const nextTab = normalizeSettingsTab(tab);
  if(nextTab !== settingsActiveTab){
    const returnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if(!(await confirmAndDiscardSettingsDraft(returnFocusEl))) return false;
  }
  activateSettingsTab(nextTab, opts);
  refreshSettingsDraftActions();
  return true;
}
async function requestActivateImageSettingsSubtab(tab){
  const nextTab = ["image_api","image_gen","image_edit"].includes(String(tab || '').trim()) ? String(tab).trim() : "image_api";
  if(settingsActiveTab === 'image' && nextTab !== imageSettingsActiveSubtab){
    const returnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if(!(await confirmAndDiscardSettingsDraft(returnFocusEl))) return false;
  }
  activateImageSettingsSubtab(nextTab);
  refreshSettingsDraftActions();
  return true;
}
async function requestActivateWebSettingsSubtab(tab){
  const nextTab = ["search_api","image_search","content_fetch","limits"].includes(String(tab || '').trim()) ? String(tab).trim() : "search_api";
  // 联网设置四个子页共用同一个草稿和保存入口；切换子页不能丢弃未保存内容。
  activateWebSettingsSubtab(nextTab);
  refreshSettingsDraftActions();
  return true;
}
function bindSettingsDraftFields(ids){
  (ids || []).forEach((id)=>{
    const el = document.getElementById(id);
    if(!el || el.dataset.settingsDraftBound === '1') return;
    el.dataset.settingsDraftBound = '1';
    el.addEventListener('input', handleSettingsDraftInput);
    el.addEventListener('change', handleSettingsDraftInput);
  });
}
function bindSettingsDraftControllers(){
  registerSettingsDraftController('personalization', {
    read: personalizationDraftComparableFromForm,
    saved: ()=>personalizationDraftComparableFromState(getPersonalizationState()),
    save: async()=>{
      await savePersonalizationSettings({ immediate:true, throwOnError:true });
      try{ toast(window.AperviaI18n?.t('memory.personalization_saved') || 'Personalization settings saved'); }catch(_){ }
    },
    cancel: ()=>{ renderPersonalizationUi(); },
    onInput: ()=>{ updatePersonalizationSummary(readPersonalizationFormState()); refreshPersonalizationAboutTextareaScroll(); },
  });
  registerSettingsDraftController('voice', {
    read: ()=>({
      voice: normalizeVoiceSettings(readVoiceSettingsForm()),
      read_aloud: normalizeReadAloudSettings(readReadAloudSettingsForm()),
    }),
    saved: ()=>({
      voice: normalizeVoiceSettings(getVoiceSettings()),
      read_aloud: normalizeReadAloudSettings(getReadAloudSettings()),
    }),
    save: ()=>{
      saveVoiceSettingsFormWithFeedback({silent:true});
      saveReadAloudSettingsFormWithFeedback({silent:true});
      setVoiceSettingsHint("", "");
      toast(window.AperviaI18n?.t('settings.voice.saved') || 'Voice settings saved');
    },
    cancel: ()=>{ fillVoiceSettingsForm(); fillReadAloudSettingsForm(); },
    onInput: ()=>{ updateVoiceSettingsFormState(); updateReadAloudSettingsFormState(); },
  });
  registerSettingsDraftController('web', {
    read: ()=>webSettingsDraftComparable(readWebSettingsForm()),
    saved: ()=>webSettingsDraftComparable(getWebSettings()),
    save: ()=>saveWebSettingsFormWithFeedback(),
    cancel: ()=>fillWebSettingsForm(),
  });
  registerSettingsDraftController('image_gen', {
    read: ()=>imageGenDraftComparable(getImageGenFormPatch()),
    saved: ()=>imageGenDraftComparable(getStoredImageGenerationSettings()),
    save: ()=>{ saveImageGenSettingsOnly(); toast(window.AperviaI18n?.t('settings.image.generation_saved') || 'Image generation settings saved'); },
    cancel: ()=>fillImageGenerationSettingsForm(),
    onInput: ()=>updateImageEngineUi(),
  });
  registerSettingsDraftController('image_edit', {
    read: ()=>imageEditDraftComparable(getImageEditFormPatch()),
    saved: ()=>imageEditDraftComparable(getStoredImageGenerationSettings()),
    save: ()=>{ saveImageEditSettingsOnly(); toast(window.AperviaI18n?.t('settings.image.editing_saved') || 'Image editing settings saved'); },
    cancel: ()=>fillImageGenerationSettingsForm(),
    onInput: ()=>updateImageEditEngineUi(),
  });
  bindSettingsDraftFields([
    'personalizationCustomInstruction','personalizationProfileNickname','personalizationProfileOccupation','personalizationProfileDetails',
    'personalizationResponseStylePreset','personalizationStructurePreference','personalizationEmojiPreference',
    'voiceInputEnabled','voiceMimeTypesInput','voiceEngineInput','voiceProviderPreset','voiceTranscribeUrlInput','voiceFollowChatApi','voiceApiKeyInput','voiceModelInput',
    'voiceResponseFormatInput','voiceLocalModelInput','voiceLocalDeviceInput','voiceLocalComputeInput','voiceLocalVadFilter','voiceLanguageInput','voicePromptInput',
    'readAloudProviderInput','readAloudFollowChatApi','readAloudBaseUrlInput','readAloudApiKeyInput','readAloudModelInput','readAloudPresetInput','readAloudVoiceInput','readAloudFormatInput','readAloudFallbackBrowser','readAloudInstructionsInput',
    'wsSearxUrl','wsSearxPath','wsSearchProvider','wsSearchFallbackProvider','wsWhoogleUrl','wsExternalSearchUrl','wsExternalSearchApiKey',
    'wsUapiProBaseUrl','wsUapiProApiKey','wsImageSearchProvider','wsImageSearchFallbackProvider','wsImageMaxQueries','wsExternalImageSearchUrl',
    'wsExternalImageSearchApiKey','wsSerperApiKey','wsContentProvider','wsContentFallbackProvider','wsTavilyApiKey','wsTavilyExtractDepth',
    'wsPlaywrightEnable','wsAutoRender','wsK','wsMaxSearchCalls','wsFastPages','wsMaxPages','wsWorkers','wsTimeout','wsPageChars','wsSnippetChars',
    'wsImageGenEngine','wsImageGenModel','wsImageGenBaseUrl','wsImageGenApiKey','wsImageGenSize','wsImageGenExtraBody',
    'wsImageEditEnabled','wsImageEditEngine','wsImageEditModel','wsImageEditBaseUrl','wsImageEditApiKey','wsImageEditSize','wsImageEditExtraBody'
  ]);
  document.getElementById('settingsDraftSaveBtn')?.addEventListener('click', saveActiveSettingsDraftFromActions);
  document.getElementById('settingsDraftCancelBtn')?.addEventListener('click', cancelActiveSettingsDraftFromActions);
  refreshSettingsDraftActions();
}

function activateSettingsTab(tab, opts={}){
  const nextTab = normalizeSettingsTab(tab);
  settingsActiveTab = nextTab;
  try{ localStorage.setItem(SETTINGS_LAST_TAB_KEY, nextTab); }catch(_){ }
  const scope = document.getElementById('settingsModal') || document;
  scope.querySelectorAll('[data-settings-tab]').forEach(btn=>{
    const active = btn.getAttribute('data-settings-tab') === nextTab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  scope.querySelectorAll('[data-settings-panel]').forEach(panel=>{
    panel.classList.toggle('active', panel.getAttribute('data-settings-panel') === nextTab);
  });
  if(isSettingsModalOpen() && opts.syncRoute !== false){
    syncModalRoute('settings', nextTab, { replace:!!opts.replaceRoute, returnUrl:opts.returnUrl || '' });
  }
  if(opts.hydrate !== false) scheduleSettingsTabHydration(nextTab, { force:!!opts.force });
  try{ scheduleUiAfterPaint(()=>initSecretInputToggles(scope)); }catch(_){ }
}
function activateImageSettingsSubtab(tab){
  const nextTab = ["image_api","image_gen","image_edit"].includes(String(tab || "").trim()) ? String(tab).trim() : "image_api";
  imageSettingsActiveSubtab = nextTab;
  try{ localStorage.setItem("ow_image_settings_last_subtab", nextTab); }catch(_){ }
  document.querySelectorAll('[data-image-settings-tab]').forEach(btn=> btn.classList.toggle('active', btn.getAttribute('data-image-settings-tab') === nextTab));
  document.querySelectorAll('[data-image-settings-panel]').forEach(panel=> panel.classList.toggle('active', panel.getAttribute('data-image-settings-panel') === nextTab));
  try{ initSecretInputToggles(document.getElementById('settingsModal') || document); }catch(_){ }
  try{ refreshSettingsDraftActions(); }catch(_){ }
}
function activateWebSettingsSubtab(tab){
  const nextTab = ["search_api","image_search","content_fetch","limits"].includes(String(tab || "").trim()) ? String(tab).trim() : "search_api";
  webSettingsActiveSubtab = nextTab;
  try{ localStorage.setItem("ow_web_settings_last_subtab", nextTab); }catch(_){ }
  document.querySelectorAll('[data-web-settings-tab]').forEach(btn=> btn.classList.toggle('active', btn.getAttribute('data-web-settings-tab') === nextTab));
  document.querySelectorAll('[data-web-settings-panel]').forEach(panel=> panel.classList.toggle('active', panel.getAttribute('data-web-settings-panel') === nextTab));
  try{ initSecretInputToggles(document.getElementById('settingsModal') || document); }catch(_){ }
  try{ refreshSettingsDraftActions(); }catch(_){ }
}

function isSettingsModalOpen(){
  return SETTINGS_MODAL_OPEN || !!document.getElementById("settingsModal")?.classList.contains("open");
}
function activeChatJobInProgress(){
  const sid = String(store?.activeId || '').trim();
  if(!sid || isHomeLandingView || !store?.sessions?.[sid]) return false;
  return !!(isSessionStreaming(sid) || getSessionPendingJobId(sid) || getSessionPromise(sid));
}
function keepActiveChatJobAlive(reason=''){
  const sid = String(store?.activeId || '').trim();
  if(!sid || isHomeLandingView || !store?.sessions?.[sid]) return;
  try{
    if(getSessionPendingJobId(sid)) maybeResumeSessionJob(sid, { force:true });
  }catch(_){ }
  try{ refreshStatusForActiveSession(); }catch(_){ }
  try{ syncChatCenterLoading(); }catch(_){ }
}
function renderPassiveUiForModal(){
  renderList();
  refreshStatusForActiveSession();
  syncChatCenterLoading();
}

let _settingsHydrationSeq = 0;
let _personalizationHydrationSeq = 0;

function scheduleUiAfterPaint(fn){
  if(typeof fn !== 'function') return;
  const run = () => {
    try{ fn(); }catch(err){ try{ console.warn('deferred ui task failed:', err); }catch(_){ } }
  };
  try{
    if(typeof requestAnimationFrame === 'function'){
      requestAnimationFrame(()=> setTimeout(run, 0));
      return;
    }
  }catch(_){ }
  setTimeout(run, 0);
}


function scheduleUiIdle(fn){
  if(typeof fn !== 'function') return;
  try{
    if(typeof requestIdleCallback === 'function'){
      requestIdleCallback(()=>{
        try{ fn(); }catch(err){ try{ console.warn('idle ui task failed:', err); }catch(_){ } }
      }, { timeout: 800 });
      return;
    }
  }catch(_){ }
  scheduleUiAfterPaint(fn);
}

function runDeferredUiTasks(tasks, opts={}){
  const queue = Array.isArray(tasks) ? tasks.filter(fn => typeof fn === 'function') : [];
  if(!queue.length) return;
  const isCurrent = typeof opts.isCurrent === 'function' ? opts.isCurrent : null;
  const useIdle = !!opts.idle;
  const step = () => {
    if(isCurrent && !isCurrent()) return;
    const task = queue.shift();
    if(!task) return;
    try{ task(); }catch(err){ try{ console.warn('deferred ui task failed:', err); }catch(_){ } }
    if(!queue.length) return;
    const schedule = useIdle ? scheduleUiIdle : scheduleUiAfterPaint;
    schedule(step);
  };
  scheduleUiAfterPaint(step);
}

function refreshBackendPersonalizationForVisible(opts={}){
  if(!isBackendPersonalizationActive()) return Promise.resolve(null);
  const currentSeq = ++_personalizationHydrationSeq;
  return fetchBackendPersonalizationState({ render:false, persist:false }).then((state)=>{
    const memoryModalOpen = !!document.getElementById('personalizationMemoryModal')?.classList.contains('open');
    const customModalOpen = !!document.getElementById('personalizationCustomInstructionModal')?.classList.contains('open');
    const personalizationPanelOpen = isSettingsModalOpen() && settingsActiveTab === 'personalization';
    if(currentSeq === _personalizationHydrationSeq && (memoryModalOpen || customModalOpen || personalizationPanelOpen) && !PERSONALIZATION_MEMORY_EDITOR_OPEN){
      renderPersonalizationUi();
    }
    return state;
  }).catch(err=>{
    try{ console.warn('refresh backend personalization failed:', err); }catch(_){ }
    return null;
  });
}

function schedulePersonalizationUiHydration(opts={}){
  const seq = ++_personalizationHydrationSeq;
  scheduleUiAfterPaint(()=>{
    const memoryModalOpen = !!document.getElementById('personalizationMemoryModal')?.classList.contains('open');
    const customModalOpen = !!document.getElementById('personalizationCustomInstructionModal')?.classList.contains('open');
    const personalizationPanelOpen = isSettingsModalOpen() && settingsActiveTab === 'personalization';
    if(seq !== _personalizationHydrationSeq || !(memoryModalOpen || customModalOpen || personalizationPanelOpen)) return;
    if(!PERSONALIZATION_MEMORY_EDITOR_OPEN) renderPersonalizationUi();
    if(opts.refreshBackend !== false) refreshBackendPersonalizationForVisible();
    if(opts.focusCustomInstruction) document.getElementById('personalizationCustomInstruction')?.focus();
  });
}

function hydrateSettingsTab(tab, opts={}){
  const currentTab = normalizeSettingsTab(tab);
  if(!isSettingsModalOpen()) return;
  if(settingsActiveTab !== currentTab && !opts.force) return;
  const isCurrent = () => isSettingsModalOpen() && (settingsActiveTab === currentTab || !!opts.force);
  const tasks = [];
  if(currentTab === 'api'){
    tasks.push(
      ()=>fillApiFormFromCurrent(),
      ()=>renderApiSavedList(),
      ()=>renderApiQuickMenu(),
      ()=>syncApiSettingsModeUi(),
      ()=>updateApiVendorPreview(),
    );
  }else if(currentTab === 'generation'){
    tasks.push(
      ()=>fillApiFormFromCurrent(),
      ()=>renderApiQuickMenu(),
      ()=>syncApiSettingsModeUi(),
      ()=>syncGenerationSettingsContextUi(),
    );
  }else if(currentTab === 'web'){
    tasks.push(
      ()=>fillWebSettingsForm(),
      ()=>activateWebSettingsSubtab(webSettingsActiveSubtab),
      ()=>refreshThinkingControlUi(),
      ()=>setWebSettingsHint('', ''),
    );
  }else if(currentTab === 'mcp'){
    tasks.push(()=>hydrateMcpSettingsUi());
  }else if(currentTab === 'image'){
    tasks.push(
      ()=>fillImageApiFormFromCurrent(),
      ()=>renderImageApiSavedList(),
      ()=>fillImageGenerationSettingsForm(),
      ()=>activateImageSettingsSubtab(imageSettingsActiveSubtab),
    );
  }else if(currentTab === 'voice'){
    tasks.push(
      ()=>fillVoiceSettingsForm(),
      ()=>updateVoiceSettingsFormState(),
    );
  }else if(currentTab === 'models'){
    tasks.push(()=>renderModelManagementUi());
  }else if(currentTab === 'personalization'){
    tasks.push(
      ()=>renderPersonalizationUi(),
      ()=>refreshBackendPersonalizationForVisible(),
    );
  }else if(currentTab === 'backup'){
    tasks.push(()=>renderDataManagementUi());
  }else if(currentTab === 'storage'){
    tasks.push(()=>refreshStorageSpaceUi({ force:false }));
  }else if(currentTab === 'account'){
    tasks.push(
      ()=>renderAccountSettingsUi(),
      ()=>refreshAccountSettingsUi(),
    );
  }
  tasks.push(()=>initSecretInputToggles(document.getElementById('settingsModal') || document));
  tasks.push(()=>refreshSettingsDraftActions());
  runDeferredUiTasks(tasks, { isCurrent, idle: currentTab === 'models' || currentTab === 'personalization' });
}

function scheduleSettingsTabHydration(tab, opts={}){
  const targetTab = normalizeSettingsTab(tab);
  const seq = ++_settingsHydrationSeq;
  scheduleUiAfterPaint(()=>{
    if(seq !== _settingsHydrationSeq || !isSettingsModalOpen()) return;
    hydrateSettingsTab(targetTab, opts);
  });
}
function openSettingsModal(tab=settingsActiveTab, opts={}){
  const modal = document.getElementById("settingsModal");
  if(!modal) return;
  const preserveActiveChatJob = activeChatJobInProgress();
  try{
    if(window.innerWidth <= 900 && document.body.classList.contains('mobile-sidebar-open')){
      if(typeof applySidebarCollapsed === 'function') applySidebarCollapsed(true, false);
      document.body.classList.remove('mobile-sidebar-open');
    }
  }catch(_){ }
  const targetTab = normalizeSettingsTab(tab || settingsActiveTab);
  settingsLastFocusedEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  activateSettingsTab(targetTab, { hydrate:false, syncRoute:false });
  SETTINGS_MODAL_OPEN = true;
  document.body.classList.add("modal-open");
  modal.classList.add("open");
  modal.removeAttribute("inert");
  modal.setAttribute("aria-hidden", "false");
  if(opts?.syncRoute !== false){
    syncModalRoute('settings', targetTab, { replace:!!opts?.replaceRoute, returnUrl:opts?.returnUrl || '' });
  }
  if(preserveActiveChatJob) keepActiveChatJobAlive('settings_open');
  scheduleSettingsTabHydration(targetTab, { force:true });
  setTimeout(()=>{
    if(preserveActiveChatJob){
      keepActiveChatJobAlive('settings_open_focus_deferred');
      return;
    }
    if(window.innerWidth <= 900) return;
    if(targetTab === 'models') document.getElementById('modelSearchInput')?.focus();
    else if(targetTab === 'image'){
      if(imageSettingsActiveSubtab === 'image_edit') document.getElementById('wsImageEditModel')?.focus();
      else if(imageSettingsActiveSubtab === 'image_gen') document.getElementById('wsImageGenModel')?.focus();
      else document.getElementById('imageApiProfileName')?.focus();
    }
    else if(targetTab === 'personalization') document.getElementById('personalizationCustomInstruction')?.focus();
    else if(targetTab === 'generation') document.getElementById('apiMaxTokensInput')?.focus();
    else if(targetTab === 'voice') document.getElementById('voiceTranscribeUrlInput')?.focus();
    else if(targetTab === 'backup') document.getElementById('dataLocationRow')?.focus();
    else if(targetTab === 'storage') document.getElementById('storageSpaceRefreshBtn')?.focus();
    else if(targetTab === 'account') document.getElementById('accountSettingsEditProfileBtn')?.focus();
    else document.getElementById("apiProfileName")?.focus();
  },0);
}
function closeSettingsModal(opts={}){
  const modal = document.getElementById("settingsModal");
  if(!modal) return;
  if(document.activeElement && modal.contains(document.activeElement)) document.activeElement.blur();
  SETTINGS_MODAL_OPEN = false;
  try{ setSettingsDraftActionsVisible(false); }catch(_){ }
  document.body.classList.remove("modal-open");
  modal.classList.remove("open");
  modal.setAttribute("inert", "");
  modal.setAttribute("aria-hidden", "true");
  const target = settingsLastFocusedEl && typeof settingsLastFocusedEl.focus === "function" ? settingsLastFocusedEl : (document.getElementById("accountCard") || document.getElementById("openSettingsBtn"));
  settingsLastFocusedEl = null;
  if(opts?.syncRoute !== false && getRouteSettingsTab()) restoreModalReturnRoute({ replace:opts?.replaceRoute !== false });
  try{ target?.focus(); }catch(_){ }
}

function bindSettingsUi(){
  updateApiButton();
  renderApiQuickMenu();
  renderApiSavedList();
  fillApiFormFromCurrent();
  syncModelOptionsForActiveProfile({ensureSessionValue:false});
  fillWebSettingsForm();
  activateWebSettingsSubtab(webSettingsActiveSubtab);
  fillImageApiFormFromCurrent();
  renderImageApiSavedList();
  fillImageGenerationSettingsForm();
  refreshThinkingControlUi();
  renderPersonalizationUi();
  bindPersonalizationUi();
  bindSettingsDraftControllers();
  document.getElementById("chatThinkingToggle")?.addEventListener("click", async ()=>{
    const modelName = currentChatModelForThinking();
    const result = await probeThinkingSupport(modelName, { silent:true });
    if(!(result && result.ok && result.supported)){
      refreshThinkingControlUi();
      toast(window.AperviaI18n?.t('settings.thinking_unsupported') || 'The current model does not support deep-thinking controls.');
      return;
    }
    setCurrentChatThinkingType(cycleThinkingType(getCurrentChatThinkingType()));
  });
  (document.getElementById("openSettingsSidebar") || document.getElementById("openSettingsBtn"))?.addEventListener("click", ()=> openSettingsModal(settingsActiveTab));
  document.getElementById("settingsCloseBtn")?.addEventListener("click", ()=>requestCloseSettingsModal());
  document.querySelector("#settingsModal .settings-panel")?.addEventListener("click", (e)=> e.stopPropagation());
  document.addEventListener("keydown", (e)=>{ if(e.key === "Escape" && isSettingsModalOpen()) requestCloseSettingsModal(); });
  document.querySelectorAll('[data-settings-tab]').forEach(btn => btn.addEventListener('click', (e)=>{
    e.preventDefault();
    requestActivateSettingsTab(btn.getAttribute('data-settings-tab') || 'api', { force:true });
  }));
  document.addEventListener('apervia:languagechange', ()=>{
    if(isSettingsModalOpen()) scheduleSettingsTabHydration(settingsActiveTab, {force:true});
  });
  document.querySelectorAll('[data-image-settings-tab]').forEach(btn => btn.addEventListener('click', ()=> requestActivateImageSettingsSubtab(btn.getAttribute('data-image-settings-tab') || 'image_api')));
  document.querySelectorAll('[data-web-settings-tab]').forEach(btn => btn.addEventListener('click', ()=> requestActivateWebSettingsSubtab(btn.getAttribute('data-web-settings-tab') || 'search_api')));
  bindApiProfileSettingsUi();
  bindMcpSettingsUi();
  bindWebSettingsUi();
  bindVoiceSettingsUi();
  bindImageSettingsUi();
  bindModelManagementSettingsUi();
  bindDataManagementSettingsUi();
  modelEl?.addEventListener('change', ()=>{
    const value = String(modelEl?.value || '').trim();
    if(value) persistActiveModelSelection(value, {silent:true});
  });
}

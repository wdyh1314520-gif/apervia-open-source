/* Settings voice-input configuration split from index3-settings-ui.js. */
const VOICE_SETTINGS_DEFAULTS = {
  VOICE_SETTINGS_SCHEMA_VERSION: 2,
  enabled: true,
  engine: "openai_compatible",
  provider: "custom",
  mime_types: "",
  transcribe_url: "",
  api_key: "",
  follow_chat_api: true,
  model: "whisper-1",
  language: "zh",
  response_format: "json",
  prompt: "",
  local_model: "base",
  local_device: "auto",
  local_compute_type: "auto",
  local_vad_filter: true,
};
const VOICE_ENGINE_OPTIONS = ["openai_compatible", "local_whisper", "web_api"];
const VOICE_PROVIDER_PRESETS = {
  openai: { transcribe_url: "https://api.openai.com/v1/audio/transcriptions", model: "whisper-1" },
  yunwu: { transcribe_url: "https://yunwu.ai/v1/audio/transcriptions", model: "whisper-1" },
  vectorengine: { transcribe_url: "https://api.vectorengine.ai/v1/audio/transcriptions", model: "gpt-4o-transcribe" },
};

function normalizeVoiceTranscribeUrl(value){
  const raw = String(value || "").trim();
  if(!raw) return "";
  try{
    const url = new URL(raw);
    if(url.protocol !== "http:" && url.protocol !== "https:") return "";
    return raw;
  }catch(_){
    return "";
  }
}
function normalizeVoiceMimeTypes(value){
  return String(value || "")
    .split(/[，,\n]+/)
    .map(x => String(x || "").trim().toLowerCase())
    .filter(Boolean)
    .filter(x => /^[a-z0-9.+-]+\/(?:[a-z0-9.+*-]+)$/i.test(x))
    .filter((x, idx, arr)=> arr.indexOf(x) === idx)
    .slice(0, 24)
    .join(',');
}
function normalizeVoiceEngine(value){
  const raw = String(value || "").trim().toLowerCase();
  if(raw === "openai" || raw === "remote" || raw === "custom") return "openai_compatible";
  if(raw === "whisper" || raw === "faster_whisper" || raw === "local") return "local_whisper";
  if(raw === "browser" || raw === "web" || raw === "webapi") return "web_api";
  return VOICE_ENGINE_OPTIONS.includes(raw) ? raw : VOICE_SETTINGS_DEFAULTS.engine;
}
function normalizeVoiceSettings(raw){
  const src = raw && typeof raw === "object" ? raw : {};
  const out = { ...VOICE_SETTINGS_DEFAULTS, ...src };
  out.enabled = !(out.enabled === false || out.enabled === 0 || String(out.enabled).toLowerCase() === "false" || String(out.enabled) === "0");
  out.engine = normalizeVoiceEngine(out.engine || out.stt_engine || out.provider_engine || (out.provider === "web_api" ? "web_api" : ""));
  out.provider = ["custom", "openai", "yunwu", "vectorengine"].includes(String(out.provider || "").trim()) ? String(out.provider).trim() : "custom";
  out.mime_types = normalizeVoiceMimeTypes(out.mime_types || out.supported_mime_types || out.allowed_mime_types || "");
  out.transcribe_url = normalizeVoiceTranscribeUrl(out.transcribe_url || out.endpoint || out.url || "");
  out.api_key = String(out.api_key || out.apiKey || "").trim();
  out.follow_chat_api = !(out.follow_chat_api === false || out.follow_chat_api === 0 || String(out.follow_chat_api).toLowerCase() === "false" || String(out.follow_chat_api) === "0");
  out.model = String(out.model || VOICE_SETTINGS_DEFAULTS.model).trim() || VOICE_SETTINGS_DEFAULTS.model;
  out.language = String(out.language || VOICE_SETTINGS_DEFAULTS.language).trim().replace('_','-') || VOICE_SETTINGS_DEFAULTS.language;
  if(!/^(auto|[a-z]{2,3})(-[a-z0-9]+)?$/i.test(out.language)) out.language = VOICE_SETTINGS_DEFAULTS.language;
  out.response_format = String(out.response_format || "json").trim().toLowerCase();
  if(!["json", "text", "verbose_json", "srt", "vtt"].includes(out.response_format)) out.response_format = "json";
  out.prompt = String(out.prompt || "").trim().slice(0, 1000);
  out.local_model = String(out.local_model || out.whisper_model || VOICE_SETTINGS_DEFAULTS.local_model).trim() || VOICE_SETTINGS_DEFAULTS.local_model;
  out.local_device = ["auto", "cpu", "cuda"].includes(String(out.local_device || "").trim().toLowerCase()) ? String(out.local_device).trim().toLowerCase() : VOICE_SETTINGS_DEFAULTS.local_device;
  out.local_compute_type = ["auto", "int8", "float16", "float32"].includes(String(out.local_compute_type || "").trim().toLowerCase()) ? String(out.local_compute_type).trim().toLowerCase() : VOICE_SETTINGS_DEFAULTS.local_compute_type;
  out.local_vad_filter = !(out.local_vad_filter === false || out.local_vad_filter === 0 || String(out.local_vad_filter).toLowerCase() === "false" || String(out.local_vad_filter) === "0");
  out.VOICE_SETTINGS_SCHEMA_VERSION = VOICE_SETTINGS_DEFAULTS.VOICE_SETTINGS_SCHEMA_VERSION;
  return out;
}
function getVoiceSettings(){
  try{
    const raw = JSON.parse(readAccountScopedSettingItem(VOICE_SETTINGS_KEY) || "{}");
    const normalized = normalizeVoiceSettings(raw || {});
    if(!raw || Number(raw.VOICE_SETTINGS_SCHEMA_VERSION || 0) < VOICE_SETTINGS_DEFAULTS.VOICE_SETTINGS_SCHEMA_VERSION){
      writeAccountScopedSettingItem(VOICE_SETTINGS_KEY, JSON.stringify(normalized));
    }
    return normalized;
  }catch(_){
    return { ...VOICE_SETTINGS_DEFAULTS };
  }
}
function saveVoiceSettings(value){
  const normalized = normalizeVoiceSettings(value);
  writeAccountScopedSettingItem(VOICE_SETTINGS_KEY, JSON.stringify(normalized));
  return normalized;
}


const READ_ALOUD_SETTINGS_DEFAULTS = {
  READ_ALOUD_SETTINGS_SCHEMA_VERSION: 2,
  provider: "browser",
  follow_chat_api: true,
  base_url: "",
  api_key: "",
  model: "gpt-4o-mini-tts",
  preset: "qinglan",
  voice: "sage",
  response_format: "mp3",
  fallback_browser: false,
  instructions: "全程使用标准普通话中文朗读。语速自然，吐字清晰，停顿舒服。",
};
const READ_ALOUD_PROVIDER_OPTIONS = ["browser", "openai_compatible"];
const READ_ALOUD_FORMAT_OPTIONS = ["mp3", "opus", "wav", "pcm"];
const READ_ALOUD_PRESETS = {
  qinglan: { label: "青岚", voice: "sage", tone: "讲题清楚", desc: "讲题、解释、学习，吐字清楚", instructions: "全程使用标准普通话中文朗读。语速自然，吐字清晰，适合讲题和解释。重点处稍作停顿。" },
  xinglan: { label: "星澜", voice: "cedar", tone: "沉稳长文", desc: "长文、技术、总结，稳重一点", instructions: "全程使用标准普通话中文朗读。语气沉稳，适合长文阅读和技术说明。不要夸张。" },
  xiaolu: { label: "小鹿", voice: "coral", tone: "轻快陪聊", desc: "陪聊、轻快、日常回答", instructions: "全程使用标准普通话中文朗读。语气轻快自然，有陪伴感，但不要夸张。" },
  yunshan: { label: "云杉", voice: "nova", tone: "自然通用", desc: "通用默认，比较自然", instructions: "全程使用标准普通话中文朗读。语气自然通用，适合普通聊天回答。" },
  shensong: { label: "深松", voice: "onyx", tone: "低沉正式", desc: "低沉、正式、长内容", instructions: "全程使用标准普通话中文朗读。语气低沉稳重，适合正式说明和长内容阅读。" }
};
function normalizeReadAloudBaseUrl(value){
  let raw = String(value || "").trim();
  if(!raw) return "";
  if(!/^[a-z][a-z0-9+.-]*:\/\//i.test(raw) && /^[A-Za-z0-9.-]+(?::\d+)?(?:\/.*)?$/.test(raw)) raw = `https://${raw}`;
  raw = raw.replace(/\s+/g, '').replace(/\/+$/, '');
  try{ const u = new URL(raw); if(u.protocol !== "http:" && u.protocol !== "https:") return ""; return u.toString().replace(/\/+$/, ''); }catch(_){ return ""; }
}
function normalizeReadAloudSettings(raw){
  const src = raw && typeof raw === "object" ? raw : {};
  const out = { ...READ_ALOUD_SETTINGS_DEFAULTS, ...src };
  out.provider = READ_ALOUD_PROVIDER_OPTIONS.includes(String(out.provider || "").trim()) ? String(out.provider).trim() : READ_ALOUD_SETTINGS_DEFAULTS.provider;
  out.follow_chat_api = !(out.follow_chat_api === false || out.follow_chat_api === 0 || String(out.follow_chat_api).toLowerCase() === "false" || String(out.follow_chat_api) === "0");
  out.base_url = normalizeReadAloudBaseUrl(out.base_url || out.api_base || out.baseUrl || "");
  out.api_key = String(out.api_key || out.apiKey || "").trim();
  out.model = String(out.model || READ_ALOUD_SETTINGS_DEFAULTS.model).trim() || READ_ALOUD_SETTINGS_DEFAULTS.model;
  out.preset = Object.prototype.hasOwnProperty.call(READ_ALOUD_PRESETS, String(out.preset || "").trim()) ? String(out.preset).trim() : READ_ALOUD_SETTINGS_DEFAULTS.preset;
  const preset = READ_ALOUD_PRESETS[out.preset] || READ_ALOUD_PRESETS.qinglan;
  out.voice = String(out.voice || preset.voice || READ_ALOUD_SETTINGS_DEFAULTS.voice).trim() || READ_ALOUD_SETTINGS_DEFAULTS.voice;
  out.response_format = READ_ALOUD_FORMAT_OPTIONS.includes(String(out.response_format || "").trim()) ? String(out.response_format).trim() : READ_ALOUD_SETTINGS_DEFAULTS.response_format;
  out.fallback_browser = !(out.fallback_browser === false || out.fallback_browser === 0 || String(out.fallback_browser).toLowerCase() === "false" || String(out.fallback_browser) === "0");
  out.instructions = String(out.instructions || preset.instructions || READ_ALOUD_SETTINGS_DEFAULTS.instructions).trim().slice(0, 1200) || READ_ALOUD_SETTINGS_DEFAULTS.instructions;
  out.READ_ALOUD_SETTINGS_SCHEMA_VERSION = READ_ALOUD_SETTINGS_DEFAULTS.READ_ALOUD_SETTINGS_SCHEMA_VERSION;
  return out;
}
function getReadAloudSettings(){
  try{
    const raw = JSON.parse(readAccountScopedSettingItem(READ_ALOUD_SETTINGS_KEY) || "{}");
    const src = raw && typeof raw === "object" ? { ...raw } : {};
    if(Number(src.READ_ALOUD_SETTINGS_SCHEMA_VERSION || 0) < 2){
          }
    const normalized = normalizeReadAloudSettings(src || {});
    if(!raw || Number(raw.READ_ALOUD_SETTINGS_SCHEMA_VERSION || 0) < READ_ALOUD_SETTINGS_DEFAULTS.READ_ALOUD_SETTINGS_SCHEMA_VERSION){ writeAccountScopedSettingItem(READ_ALOUD_SETTINGS_KEY, JSON.stringify(normalized)); }
    return normalized;
  }catch(_){ return { ...READ_ALOUD_SETTINGS_DEFAULTS }; }
}
function saveReadAloudSettings(value){ const normalized = normalizeReadAloudSettings(value); writeAccountScopedSettingItem(READ_ALOUD_SETTINGS_KEY, JSON.stringify(normalized)); return normalized; }
function renderReadAloudPresetCards(){
  const wrap = document.getElementById("readAloudPresetCards"); if(!wrap) return;
  const current = String(document.getElementById("readAloudPresetInput")?.value || getReadAloudSettings().preset || "qinglan").trim();
  wrap.innerHTML = "";
  Object.entries(READ_ALOUD_PRESETS).forEach(([key, item])=>{
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "read-aloud-card"; btn.dataset.readAloudPreset = key; btn.setAttribute("role", "radio"); btn.setAttribute("aria-checked", key === current ? "true" : "false"); btn.classList.toggle("active", key === current);
    btn.innerHTML = `<span class="read-aloud-card-main"><b>${item.label}</b><em>${item.tone}</em></span><span>${item.desc}</span>`;
    btn.addEventListener("click", ()=>{ const hidden = document.getElementById("readAloudPresetInput"); if(hidden) hidden.value = key; const voiceEl = document.getElementById("readAloudVoiceInput"); if(voiceEl) voiceEl.value = item.voice || ""; const instEl = document.getElementById("readAloudInstructionsInput"); if(instEl) instEl.value = item.instructions || ""; renderReadAloudPresetCards(); updateReadAloudSettingsFormState(); refreshSettingsDraftActions(); });
    wrap.appendChild(btn);
  });
}
function readReadAloudSettingsFormLoose(){ return normalizeReadAloudSettings({ provider: String(document.getElementById("readAloudProviderInput")?.value || READ_ALOUD_SETTINGS_DEFAULTS.provider).trim(), follow_chat_api: isCheckboxEnabled(document.getElementById("readAloudFollowChatApi")), base_url: String(document.getElementById("readAloudBaseUrlInput")?.value || "").trim(), api_key: String(document.getElementById("readAloudApiKeyInput")?.value || "").trim(), model: String(document.getElementById("readAloudModelInput")?.value || READ_ALOUD_SETTINGS_DEFAULTS.model).trim(), preset: String(document.getElementById("readAloudPresetInput")?.value || READ_ALOUD_SETTINGS_DEFAULTS.preset).trim(), voice: String(document.getElementById("readAloudVoiceInput")?.value || "").trim(), response_format: String(document.getElementById("readAloudFormatInput")?.value || "mp3").trim(), fallback_browser: isCheckboxEnabled(document.getElementById("readAloudFallbackBrowser")), instructions: String(document.getElementById("readAloudInstructionsInput")?.value || "").trim() }); }
function updateReadAloudSettingsFormState(){ bindBooleanFieldState("readAloudFollowChatApi", "开启", "关闭"); bindBooleanFieldState("readAloudFallbackBrowser", "开启", "关闭"); const cfg = readReadAloudSettingsFormLoose(); const isRemote = cfg.provider === "openai_compatible"; document.querySelectorAll(".read-aloud-api-grid .field").forEach(el=>{ const id = String(el?.querySelector?.("input,select,textarea")?.id || ""); if(id === "readAloudProviderInput" || id === "readAloudFallbackBrowser") return; el.style.display = isRemote ? "" : "none"; }); const badge = document.getElementById("readAloudCurrentBadge"); const preset = READ_ALOUD_PRESETS[cfg.preset] || READ_ALOUD_PRESETS.qinglan; if(badge) badge.textContent = cfg.provider === "browser" ? "系统默认" : (preset?.label || "青岚"); const keyEl = document.getElementById("readAloudApiKeyInput"); if(keyEl) keyEl.placeholder = cfg.follow_chat_api ? "留空时跟随主聊天 Key" : "TTS API Key"; }
function fillReadAloudSettingsForm(){ const cfg = getReadAloudSettings(); const setVal = (id, v)=>{ const el = document.getElementById(id); if(el) el.value = v; }; setVal("readAloudProviderInput", cfg.provider); setCheckboxLikeValue(document.getElementById("readAloudFollowChatApi"), !!cfg.follow_chat_api); setVal("readAloudBaseUrlInput", cfg.base_url || ""); setVal("readAloudApiKeyInput", cfg.api_key || ""); setVal("readAloudModelInput", cfg.model || READ_ALOUD_SETTINGS_DEFAULTS.model); setVal("readAloudPresetInput", cfg.preset || "qinglan"); setVal("readAloudVoiceInput", cfg.voice || "sage"); setVal("readAloudFormatInput", cfg.response_format || "mp3"); setCheckboxLikeValue(document.getElementById("readAloudFallbackBrowser"), !!cfg.fallback_browser); setVal("readAloudInstructionsInput", cfg.instructions || ""); renderReadAloudPresetCards(); updateReadAloudSettingsFormState(); }
function readReadAloudSettingsForm(){ return readReadAloudSettingsFormLoose(); }
function saveReadAloudSettingsFormWithFeedback({silent=false}={}){ const next = saveReadAloudSettings(readReadAloudSettingsForm()); updateReadAloudSettingsFormState(); if(!silent){ if(next.provider === "openai_compatible" && !next.base_url && !next.follow_chat_api) setVoiceSettingsHint(window.AperviaI18n?.t('settings.voice.read_aloud_base_missing') || "Enter a TTS Base URL for read aloud.", "warn"); toast(window.AperviaI18n?.t('settings.voice.read_aloud_saved') || "Read-aloud settings saved"); } return next; }
function resetReadAloudSettingsToDefaults(){ saveReadAloudSettings({ ...READ_ALOUD_SETTINGS_DEFAULTS }); fillReadAloudSettingsForm(); }

function setVoiceSettingsHint(text, type=""){
  const el = document.getElementById("voiceSettingsHint");
  if(!el) return;
  const msg = String(text || "").trim();
  el.textContent = msg;
  const show = !!msg;
  el.hidden = !show;
  el.classList.toggle("show", show);
  el.classList.toggle("warn", type === "warn");
}
function applyVoiceProviderPresetToForm(force=false){
  const presetEl = document.getElementById("voiceProviderPreset");
  const urlEl = document.getElementById("voiceTranscribeUrlInput");
  const modelEl = document.getElementById("voiceModelInput");
  const preset = String(presetEl?.value || "custom").trim();
  const info = VOICE_PROVIDER_PRESETS[preset];
  if(!info) return;
  if(urlEl && (force || !String(urlEl.value || "").trim())) urlEl.value = info.transcribe_url || "";
  if(modelEl && (force || !String(modelEl.value || "").trim())) modelEl.value = info.model || VOICE_SETTINGS_DEFAULTS.model;
}
function setVoiceGroupVisible(id, visible){
  const el = document.getElementById(id);
  if(!el) return;
  el.hidden = !visible;
  el.style.display = visible ? 'contents' : 'none';
}
function isBrowserSpeechRecognitionSupported(){
  try{
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }catch(_){
    return false;
  }
}
function updateVoiceSettingsFormState(){
  bindBooleanFieldState("voiceInputEnabled", "开启", "关闭");
  bindBooleanFieldState("voiceFollowChatApi", "开启", "关闭");
  bindBooleanFieldState("voiceLocalVadFilter", "开启", "关闭");
  const engine = normalizeVoiceEngine(document.getElementById("voiceEngineInput")?.value || getVoiceSettings().engine);
  const isRemote = engine === "openai_compatible";
  const isLocal = engine === "local_whisper";
  const isWebApi = engine === "web_api";
  setVoiceGroupVisible("voiceRemoteFields", isRemote);
  setVoiceGroupVisible("voiceLocalFields", isLocal);
  setVoiceGroupVisible("voiceWebApiFields", isWebApi);
  const follow = isCheckboxEnabled(document.getElementById("voiceFollowChatApi"));
  const keyEl = document.getElementById("voiceApiKeyInput");
  if(keyEl){
    keyEl.placeholder = follow ? "留空时跟随主聊天 Key" : "语音 API Key";
  }
  if(isWebApi && !isBrowserSpeechRecognitionSupported()){
    setVoiceSettingsHint("当前浏览器不支持网页 API 语音识别，建议切回 OpenAI 兼容或本地 Whisper。", "warn");
  }else{
    const hintEl = document.getElementById("voiceSettingsHint");
    if(hintEl && !hintEl.hidden && /当前浏览器不支持网页 API/.test(String(hintEl.textContent || ""))) setVoiceSettingsHint("", "");
  }
}
function fillVoiceSettingsForm(){
  const cfg = getVoiceSettings();
  const setVal = (id, v)=>{ const el = document.getElementById(id); if(el) el.value = v; };
  setCheckboxLikeValue(document.getElementById("voiceInputEnabled"), !!cfg.enabled);
  setVal("voiceMimeTypesInput", cfg.mime_types || "");
  setVal("voiceEngineInput", cfg.engine || VOICE_SETTINGS_DEFAULTS.engine);
  setVal("voiceProviderPreset", cfg.provider || "custom");
  setVal("voiceTranscribeUrlInput", cfg.transcribe_url || "");
  setCheckboxLikeValue(document.getElementById("voiceFollowChatApi"), !!cfg.follow_chat_api);
  setVal("voiceApiKeyInput", cfg.api_key || "");
  setVal("voiceModelInput", cfg.model || VOICE_SETTINGS_DEFAULTS.model);
  setVal("voiceLocalModelInput", cfg.local_model || VOICE_SETTINGS_DEFAULTS.local_model);
  setVal("voiceLocalDeviceInput", cfg.local_device || VOICE_SETTINGS_DEFAULTS.local_device);
  setVal("voiceLocalComputeInput", cfg.local_compute_type || VOICE_SETTINGS_DEFAULTS.local_compute_type);
  setCheckboxLikeValue(document.getElementById("voiceLocalVadFilter"), !!cfg.local_vad_filter);
  setVal("voiceLanguageInput", cfg.language || VOICE_SETTINGS_DEFAULTS.language);
  setVal("voiceResponseFormatInput", cfg.response_format || "json");
  setVal("voicePromptInput", cfg.prompt || "");
  updateVoiceSettingsFormState();
  setVoiceSettingsHint("", "");
}
function readVoiceSettingsForm(){
  return normalizeVoiceSettings({
    enabled: isCheckboxEnabled(document.getElementById("voiceInputEnabled")),
    mime_types: String(document.getElementById("voiceMimeTypesInput")?.value || "").trim(),
    engine: String(document.getElementById("voiceEngineInput")?.value || VOICE_SETTINGS_DEFAULTS.engine).trim(),
    provider: String(document.getElementById("voiceProviderPreset")?.value || "custom").trim(),
    transcribe_url: String(document.getElementById("voiceTranscribeUrlInput")?.value || "").trim(),
    follow_chat_api: isCheckboxEnabled(document.getElementById("voiceFollowChatApi")),
    api_key: String(document.getElementById("voiceApiKeyInput")?.value || "").trim(),
    model: String(document.getElementById("voiceModelInput")?.value || VOICE_SETTINGS_DEFAULTS.model).trim(),
    local_model: String(document.getElementById("voiceLocalModelInput")?.value || VOICE_SETTINGS_DEFAULTS.local_model).trim(),
    local_device: String(document.getElementById("voiceLocalDeviceInput")?.value || VOICE_SETTINGS_DEFAULTS.local_device).trim(),
    local_compute_type: String(document.getElementById("voiceLocalComputeInput")?.value || VOICE_SETTINGS_DEFAULTS.local_compute_type).trim(),
    local_vad_filter: isCheckboxEnabled(document.getElementById("voiceLocalVadFilter")),
    language: String(document.getElementById("voiceLanguageInput")?.value || VOICE_SETTINGS_DEFAULTS.language).trim(),
    response_format: String(document.getElementById("voiceResponseFormatInput")?.value || "json").trim(),
    prompt: String(document.getElementById("voicePromptInput")?.value || "").trim(),
  });
}
function validateVoiceSettingsForSave(cfg){
  const item = normalizeVoiceSettings(cfg);
  if(!item.enabled) return "";
  if(item.engine === "openai_compatible"){
    if(item.transcribe_url && !normalizeVoiceTranscribeUrl(item.transcribe_url)) return "完整转写地址不正确";
    if(!item.transcribe_url) return "未填写完整转写地址时，会回退到主聊天 API Base 拼接 /audio/transcriptions";
  }
  if(item.engine === "local_whisper"){
    if(!item.local_model) return "本地 Whisper 需要填写模型名";
    return "本地 Whisper 需要服务器安装 faster-whisper；未安装时会返回明确错误。";
  }
  if(item.engine === "web_api" && !isBrowserSpeechRecognitionSupported()) return "当前浏览器不支持网页 API 语音识别";
  return "";
}

function saveVoiceSettingsFormWithFeedback({silent=false}={}){
  const next = saveVoiceSettings(readVoiceSettingsForm());
  refreshVoiceInputAvailability();
  updateVoiceSettingsFormState();
  const hint = validateVoiceSettingsForSave(next);
  if(hint){
    setVoiceSettingsHint(hint, "warn");
    if(!silent) toast(window.AperviaI18n?.t('settings.voice.saved_check_address') || "Voice settings saved. Check the address.");
    return next;
  }
  setVoiceSettingsHint("", "");
  if(!silent) toast(window.AperviaI18n?.t('settings.voice.saved') || "Voice settings saved");
  return next;
}
function resetVoiceSettingsToDefaults(){
  saveVoiceSettings({ ...VOICE_SETTINGS_DEFAULTS });
  resetReadAloudSettingsToDefaults();
  fillVoiceSettingsForm();
  fillReadAloudSettingsForm();
  refreshVoiceInputAvailability();
  toast(window.AperviaI18n?.t('settings.voice.default_restored') || "Default voice settings restored");
}

function bindVoiceSettingsUi(){
  document.getElementById("voiceEngineInput")?.addEventListener("change", ()=>{ updateVoiceSettingsFormState(); refreshVoiceInputAvailability(); refreshSettingsDraftActions(); });
  document.getElementById("voiceProviderPreset")?.addEventListener("change", ()=>{ applyVoiceProviderPresetToForm(true); refreshSettingsDraftActions(); });
  document.getElementById("voiceInputEnabled")?.addEventListener("change", ()=>{ updateVoiceSettingsFormState(); refreshVoiceInputAvailability(); refreshSettingsDraftActions(); });
  document.getElementById("voiceFollowChatApi")?.addEventListener("change", ()=>{ updateVoiceSettingsFormState(); refreshSettingsDraftActions(); });
  document.getElementById("voiceLocalVadFilter")?.addEventListener("change", ()=>{ updateVoiceSettingsFormState(); refreshSettingsDraftActions(); });
  ["readAloudProviderInput","readAloudFollowChatApi","readAloudBaseUrlInput","readAloudApiKeyInput","readAloudModelInput","readAloudVoiceInput","readAloudFormatInput","readAloudFallbackBrowser","readAloudInstructionsInput"].forEach(id=>{
    document.getElementById(id)?.addEventListener("input", ()=>{ updateReadAloudSettingsFormState(); refreshSettingsDraftActions(); });
    document.getElementById(id)?.addEventListener("change", ()=>{ updateReadAloudSettingsFormState(); refreshSettingsDraftActions(); });
  });
  renderReadAloudPresetCards();
  updateReadAloudSettingsFormState();
  document.getElementById("voiceSettingsSaveBtn")?.addEventListener("click", ()=>{
    saveVoiceSettingsFormWithFeedback({silent:true});
    saveReadAloudSettingsFormWithFeedback({silent:true});
    setVoiceSettingsHint("", "");
    toast(window.AperviaI18n?.t('settings.voice.saved') || "Voice settings saved");
    refreshSettingsDraftActions();
  });
  document.getElementById("voiceSettingsResetBtn")?.addEventListener("click", ()=>{
    resetVoiceSettingsToDefaults();
    refreshSettingsDraftActions();
  });
}

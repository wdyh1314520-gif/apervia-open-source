/* Settings image-generation configuration split from index3-settings-ui.js. */
const IMAGE_GENERATION_SETTINGS_DEFAULTS = {
  engine: "openai_compatible",
  model: "gpt-image-1",
  api_base: "",
  api_key: "",
  size: "",
  extra_body: "{}",
  edit_enabled: false,
  edit_engine: "openai_compatible",
  edit_model: "gpt-image-1",
  edit_api_base: "",
  edit_api_key: "",
  edit_size: "",
  edit_extra_body: "{}",
};

const IMAGE_GENERATION_LEGACY_DEFAULT_SIZE = "1024x1024";
const DEFAULT_IMAGE_API_NAME = "默认图片API";
function imageApiDisplayName(name){
  const raw = String(name || "").trim();
  return !raw || raw === DEFAULT_IMAGE_API_NAME
    ? (window.AperviaI18n?.t('settings.image.default_api') || 'Default image API')
    : raw;
}
function normalizeImageSizeValue(value){
  return String(value || "").trim().replace(/×/g, "x").replace(/\s+/g, "").toLowerCase();
}
function shouldAutoMigrateLegacyImageGenerationSize(raw){
  const src = raw && typeof raw === "object" ? raw : {};
  const size = normalizeImageSizeValue(src.size || src.image_size);
  if(size !== IMAGE_GENERATION_LEGACY_DEFAULT_SIZE) return false;
  const engine = String(src.engine || src.provider || src.engine_type || "").trim().toLowerCase();
  const model = String(src.model || "").trim();
  const apiBase = String(src.api_base || src.base_url || src.apiBase || "").trim();
  const apiKey = String(src.api_key || src.apiKey || "").trim();
  const extraBody = String(src.extra_body || src.extra_params || src.extra || "").trim();
  const editSrc = (src.edit && typeof src.edit === "object") ? src.edit : {};
  const editSize = normalizeImageSizeValue(editSrc.size || src.edit_size || src.image_edit_size);
  const editApiBase = String(editSrc.api_base || editSrc.base_url || src.edit_api_base || src.image_edit_api_base || src.edit_base_url || "").trim();
  const editApiKey = String(editSrc.api_key || editSrc.apiKey || src.edit_api_key || src.image_edit_api_key || "").trim();
  const editExtraBody = String(editSrc.extra_body || editSrc.extra_params || editSrc.extra || src.edit_extra_body || src.edit_extra_params || src.image_edit_extra_body || "").trim();
  const engineCustomized = !!(engine && !["openai_compatible", "openai", "default", "relay"].includes(engine));
  const modelCustomized = !!(model && model !== IMAGE_GENERATION_SETTINGS_DEFAULTS.model);
  const hasExtra = !!(extraBody && extraBody !== "{}" && extraBody !== "null");
  const hasEditSpecific = !!(editSize || editApiBase || editApiKey || (editExtraBody && editExtraBody !== "{}" && editExtraBody !== "null"));
  return !engineCustomized && !modelCustomized && !apiBase && !apiKey && !hasExtra && !hasEditSpecific;
}

function _readRawImageGenerationSettingsObject(){
  try{
    const raw = JSON.parse(readAccountScopedSettingItem(IMAGE_GENERATION_SETTINGS_KEY) || "null") || {};
    return raw && typeof raw === "object" ? raw : {};
  }catch(_){
    return {};
  }
}
function normalizeImageApiProfile(name, raw){
  const item = raw && typeof raw === "object" ? raw : {};
  const apiKey = String(item.api_key || item.apiKey || "").trim();
  const apiBase = String(item.api_base || item.apiBase || item.base_url || "").trim();
  const meta = apiKey || apiBase ? detectVendorMeta(apiKey, apiBase || API_DEFAULT_BASE) : {vendor:"follow_chat", label:"跟随聊天 API", source:"empty", host:""};
  return {
    api_key: apiKey,
    api_base: apiBase,
    vendor: String(item.vendor || meta.vendor || "unknown"),
    vendor_label: String(item.vendor_label || meta.label || "未识别厂商"),
    updated_at: Number(item.updated_at || item.updatedAt || 0) || 0,
  };
}
function getImageApiProfiles(){
  let raw = {};
  try{ raw = JSON.parse(readAccountScopedSettingItem(IMAGE_API_PROFILES_KEY) || "{}"); }catch(_){ raw = {}; }
  const out = {};
  if(raw && typeof raw === "object"){
    for(const [name, value] of Object.entries(raw)){
      const key = String(name || "").trim();
      if(!key) continue;
      out[key] = normalizeImageApiProfile(key, value);
    }
  }
  if(!Object.keys(out).length){
    const legacy = _readRawImageGenerationSettingsObject();
    const legacyApiBase = String(legacy.api_base || legacy.base_url || legacy.apiBase || "").trim();
    const legacyApiKey = String(legacy.api_key || legacy.apiKey || "").trim();
    out[DEFAULT_IMAGE_API_NAME] = normalizeImageApiProfile(DEFAULT_IMAGE_API_NAME, {api_key: legacyApiKey, api_base: legacyApiBase, updated_at: Date.now()});
    if(legacyApiBase || legacyApiKey){
      const migrated = { ...legacy, api_base: "", api_key: "", base_url: "", apiBase: "", apiKey: "" };
      const edit = migrated.edit && typeof migrated.edit === "object" ? { ...migrated.edit } : null;
      const editApiBase = String((edit && (edit.api_base || edit.base_url)) || migrated.edit_api_base || migrated.image_edit_api_base || migrated.edit_base_url || "").trim();
      const editApiKey = String((edit && (edit.api_key || edit.apiKey)) || migrated.edit_api_key || migrated.image_edit_api_key || "").trim();
      if(editApiBase && editApiBase === legacyApiBase){
        migrated.edit_api_base = "";
        migrated.image_edit_api_base = "";
        migrated.edit_base_url = "";
        if(edit){ edit.api_base = ""; edit.base_url = ""; }
      }
      if(editApiKey && editApiKey === legacyApiKey){
        migrated.edit_api_key = "";
        migrated.image_edit_api_key = "";
        if(edit){ edit.api_key = ""; edit.apiKey = ""; }
      }
      if(edit) migrated.edit = edit;
      try{ saveImageGenerationSettings(migrated); }catch(_){ }
    }
  }
  writeAccountScopedSettingItem(IMAGE_API_PROFILES_KEY, JSON.stringify(out));
  return out;
}
function saveImageApiProfiles(profiles){
  const normalized = {};
  for(const [name, value] of Object.entries(profiles || {})){
    const key = String(name || "").trim();
    if(!key) continue;
    normalized[key] = normalizeImageApiProfile(key, value);
  }
  if(!Object.keys(normalized).length){
    normalized[DEFAULT_IMAGE_API_NAME] = normalizeImageApiProfile(DEFAULT_IMAGE_API_NAME, {api_key:"", api_base:""});
  }
  writeAccountScopedSettingItem(IMAGE_API_PROFILES_KEY, JSON.stringify(normalized));
}
function getActiveImageApiName(){
  const profiles = getImageApiProfiles();
  const saved = readAccountScopedSettingItem(ACTIVE_IMAGE_API_KEY) || DEFAULT_IMAGE_API_NAME;
  if(profiles[saved]) return saved;
  const first = Object.keys(profiles)[0] || DEFAULT_IMAGE_API_NAME;
  writeAccountScopedSettingItem(ACTIVE_IMAGE_API_KEY, first);
  return first;
}
function getCurrentImageApiProfile(){
  const profiles = getImageApiProfiles();
  const name = getActiveImageApiName();
  return { name, ...(profiles[name] || normalizeImageApiProfile(name, {})) };
}
function setActiveImageApiName(name){
  const profiles = getImageApiProfiles();
  const target = profiles[name] ? name : (Object.keys(profiles)[0] || DEFAULT_IMAGE_API_NAME);
  writeAccountScopedSettingItem(ACTIVE_IMAGE_API_KEY, target);
  fillImageApiFormFromCurrent();
  renderImageApiSavedList();
}
function applyImageApiProfileToImageGenerationSettings(settings){
  const cfg = normalizeImageGenerationSettings(settings);
  const imageApi = getCurrentImageApiProfile();
  if(!String(cfg.api_base || "").trim() && String(imageApi.api_base || "").trim()) cfg.api_base = String(imageApi.api_base || "").trim();
  if(!String(cfg.api_key || "").trim() && String(imageApi.api_key || "").trim()) cfg.api_key = String(imageApi.api_key || "").trim();
  return normalizeImageGenerationSettings(cfg);
}
function fillImageApiFormFromCurrent(){
  const cur = getCurrentImageApiProfile();
  imageApiProfileEditorMode = "edit";
  const nameEl = document.getElementById("imageApiProfileName");
  const keyEl = document.getElementById("imageApiKeyInput");
  const baseEl = document.getElementById("imageApiBaseInput");
  if(nameEl) nameEl.value = imageApiDisplayName(cur.name);
  if(keyEl) keyEl.value = cur.api_key || "";
  if(baseEl) baseEl.value = cur.api_base || "";
  const badge = document.getElementById("imageApiVendorBadge");
  const hint = document.getElementById("imageApiVendorHint");
  const followChatLabel = window.AperviaI18n?.t('settings.image.follow_chat') || "跟随聊天 API";
  const label = cur.vendor_label || (cur.api_key || cur.api_base ? detectVendorMeta(cur.api_key, cur.api_base).label : followChatLabel);
  if(badge) badge.textContent = label;
  const baseText = cur.api_base ? shortApiBase(cur.api_base) : followChatLabel;
  const profileName = imageApiDisplayName(cur.name);
  if(hint) hint.textContent = window.AperviaI18n?.t('settings.image.current', {name:profileName, source:baseText}) || `当前：${profileName} · ${baseText}`;
}
function beginNewImageApiProfileDraft(){
  imageApiProfileEditorMode = "new";
  const profileNameEl = document.getElementById("imageApiProfileName");
  const keyEl = document.getElementById("imageApiKeyInput");
  const baseEl = document.getElementById("imageApiBaseInput");
  if(profileNameEl) profileNameEl.value = "";
  if(keyEl) keyEl.value = "";
  if(baseEl) baseEl.value = "";
  const badge = document.getElementById("imageApiVendorBadge");
  const hint = document.getElementById("imageApiVendorHint");
  if(badge) badge.textContent = "待识别";
  if(hint) hint.textContent = "新建图片 Key";
  profileNameEl?.focus();
}
function renderImageApiSavedList(){
  const wrap = document.getElementById("imageApiSavedList");
  if(!wrap) return;
  const profiles = getImageApiProfiles();
  const active = getActiveImageApiName();
  wrap.innerHTML = "";
  Object.entries(profiles).forEach(([name, value])=>{
    const item = value || {};
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "settings-key-item" + (name === active ? " active" : "");
    const apiState = (item.api_key || item.api_base) ? `${escapeHtml(String(item.vendor_label || '未识别厂商'))} · ${escapeHtml(shortApiBase(item.api_base || ''))}` : "跟随聊天 API";
    btn.innerHTML = `
      <span class="settings-key-main">
        <span class="settings-key-name">${escapeHtml(imageApiDisplayName(name))}</span>
        <span class="settings-key-meta">${apiState}</span>
      </span>
      <span class="settings-badge">${name === active ? '当前图片' : '点击切换'}</span>
    `;
    btn.addEventListener("click", ()=> setActiveImageApiName(name));
    wrap.appendChild(btn);
  });
}

function normalizeImageGenerationSettings(raw){
  const src = raw && typeof raw === "object" ? raw : {};
  const out = { ...IMAGE_GENERATION_SETTINGS_DEFAULTS, ...src };
  const normalizeEngine = (value, fallback=IMAGE_GENERATION_SETTINGS_DEFAULTS.engine)=>{
    const rawEngine = String(value || "").trim().toLowerCase();
    return ({ openai: "openai_compatible", default: "openai_compatible", openai_compatible: "openai_compatible", relay: "openai_compatible", comfyui: "comfyui", a1111: "automatic1111", automatic1111: "automatic1111", "automatic-1111": "automatic1111", gemini: "gemini" }[rawEngine] || fallback);
  };
  const parseExtraBody = (...values)=>{
    let extraObj = {};
    for(const value of values){
      if(value === undefined || value === null) continue;
      if(value && typeof value === "object" && !Array.isArray(value)){
        extraObj = { ...extraObj, ...value };
        continue;
      }
      if(typeof value === "string" && value.trim()){
        try{
          const parsed = JSON.parse(value);
          if(parsed && typeof parsed === "object" && !Array.isArray(parsed)) extraObj = { ...extraObj, ...parsed };
        }catch(_){ }
      }
    }
    return extraObj;
  };
  out.engine = normalizeEngine(out.engine || out.provider || out.engine_type);
  out.model = String(out.model || IMAGE_GENERATION_SETTINGS_DEFAULTS.model).trim() || IMAGE_GENERATION_SETTINGS_DEFAULTS.model;
  out.api_base = String(out.api_base || out.base_url || out.apiBase || "").trim();
  out.api_key = String(out.api_key || out.apiKey || "").trim();
  out.size = String(out.size || IMAGE_GENERATION_SETTINGS_DEFAULTS.size).trim().replace(/×/g, "x").replace(/\s+/g, "").toLowerCase() || IMAGE_GENERATION_SETTINGS_DEFAULTS.size;
  if(!out.size) out.size = IMAGE_GENERATION_SETTINGS_DEFAULTS.size;
  let extraObj = parseExtraBody(src.extra_body, src.extra_params, src.extraParams, src.extra);
  const legacyQuality = String(src.quality || "").trim();
  const legacyBackground = String(src.background || "").trim();
  const legacyFormat = String(src.output_format || src.format || "").trim();
  if(legacyQuality && extraObj.quality === undefined) extraObj.quality = legacyQuality;
  if(legacyBackground && extraObj.background === undefined) extraObj.background = legacyBackground;
  if(legacyFormat && extraObj.output_format === undefined && extraObj.format === undefined) extraObj.output_format = legacyFormat;
  out.extra_body = JSON.stringify(extraObj, null, 2);
  if(!String(out.extra_body || "").trim()) out.extra_body = IMAGE_GENERATION_SETTINGS_DEFAULTS.extra_body;

  const editSrc = (src.edit && typeof src.edit === "object") ? src.edit : {};
  const editEnabledRaw = (editSrc.enabled ?? src.edit_enabled ?? src.image_edit_enabled ?? src.enable_image_edit ?? false);
  out.edit_enabled = !!(editEnabledRaw === true || editEnabledRaw === 1 || String(editEnabledRaw || "").toLowerCase() === "true" || String(editEnabledRaw || "") === "1");
  out.edit_engine = normalizeEngine(editSrc.engine || src.edit_engine || src.image_edit_engine || out.edit_engine, IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_engine);
  out.edit_model = String(editSrc.model || src.edit_model || src.image_edit_model || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_model).trim() || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_model;
  out.edit_api_base = String(editSrc.api_base || editSrc.base_url || src.edit_api_base || src.image_edit_api_base || src.edit_base_url || "").trim();
  out.edit_api_key = String(editSrc.api_key || editSrc.apiKey || src.edit_api_key || src.image_edit_api_key || "").trim();
  out.edit_size = String(editSrc.size || src.edit_size || src.image_edit_size || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_size || "").trim().replace(/×/g, "x").replace(/\s+/g, "").toLowerCase();
  let editExtraObj = parseExtraBody(editSrc.extra_body, editSrc.extra_params, editSrc.extra, src.edit_extra_body, src.edit_extra_params, src.image_edit_extra_body);
  out.edit_extra_body = JSON.stringify(editExtraObj, null, 2);
  if(!String(out.edit_extra_body || "").trim()) out.edit_extra_body = IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_extra_body;
  return out;
}
function updateImageEngineUi(){
  const engine = String(document.getElementById("wsImageGenEngine")?.value || IMAGE_GENERATION_SETTINGS_DEFAULTS.engine).trim();
  const extraEl = document.getElementById("wsImageGenExtraBody");
  if(extraEl){
    if(engine === "comfyui"){
      extraEl.placeholder = `{
  "workflow": {
    "1": { "inputs": { "text": "{{prompt}}" } }
  },
  "text_node_ids": ["1"]
}`;
    }else if(engine === "automatic1111"){
      extraEl.placeholder = `{
  "steps": 28,
  "cfg_scale": 7,
  "sampler_name": "DPM++ 2M Karras",
  "negative_prompt": "low quality, blurry"
}`;
    }else{
      extraEl.placeholder = `{
  "quality": "high",
  "output_format": "png"
}`;
    }
  }
}
function updateImageEditEngineUi(){
  const engine = String(document.getElementById("wsImageEditEngine")?.value || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_engine).trim();
  const extraEl = document.getElementById("wsImageEditExtraBody");
  if(extraEl){
    if(engine === "automatic1111"){
      extraEl.placeholder = `{
  "denoising_strength": 0.55,
  "steps": 28,
  "cfg_scale": 7,
  "negative_prompt": "low quality, blurry"
}`;
    }else if(engine === "comfyui"){
      extraEl.placeholder = `{
  "workflow": {},
  "image_node_ids": ["LoadImage"],
  "text_node_ids": ["Prompt"]
}`;
    }else{
      extraEl.placeholder = `{
  "quality": "high",
  "input_fidelity": "high",
  "output_format": "png"
}`;
    }
  }
}
function getStoredImageGenerationSettings(){
  try{
    const raw = _readRawImageGenerationSettingsObject();
    const normalized = normalizeImageGenerationSettings(raw);
    if(shouldAutoMigrateLegacyImageGenerationSize(raw)){
      const migrated = { ...normalized, size: "" };
      try{ saveImageGenerationSettings(migrated); }catch(_){ }
      return migrated;
    }
    return normalized;
  }
  catch(_){ return { ...IMAGE_GENERATION_SETTINGS_DEFAULTS }; }
}
function getImageGenerationSettings(){
  return applyImageApiProfileToImageGenerationSettings(getStoredImageGenerationSettings());
}
function saveImageGenerationSettings(v){ writeAccountScopedSettingItem(IMAGE_GENERATION_SETTINGS_KEY, JSON.stringify(normalizeImageGenerationSettings(v))); }

function fillImageGenerationSettingsForm(){
  const cfg = getStoredImageGenerationSettings();
  const setVal = (id, v)=>{ const el = document.getElementById(id); if(el) el.value = v; };
  setVal("wsImageGenEngine", cfg.engine || IMAGE_GENERATION_SETTINGS_DEFAULTS.engine);
  setVal("wsImageGenModel", cfg.model || IMAGE_GENERATION_SETTINGS_DEFAULTS.model);
  setVal("wsImageGenBaseUrl", cfg.api_base || IMAGE_GENERATION_SETTINGS_DEFAULTS.api_base);
  setVal("wsImageGenApiKey", cfg.api_key || IMAGE_GENERATION_SETTINGS_DEFAULTS.api_key);
  setVal("wsImageGenSize", cfg.size || IMAGE_GENERATION_SETTINGS_DEFAULTS.size);
  setVal("wsImageGenExtraBody", cfg.extra_body || IMAGE_GENERATION_SETTINGS_DEFAULTS.extra_body);
  setCheckboxLikeValue(document.getElementById("wsImageEditEnabled"), !!cfg.edit_enabled);
  setVal("wsImageEditEngine", cfg.edit_engine || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_engine);
  setVal("wsImageEditModel", cfg.edit_model || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_model);
  setVal("wsImageEditBaseUrl", cfg.edit_api_base || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_api_base);
  setVal("wsImageEditApiKey", cfg.edit_api_key || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_api_key);
  setVal("wsImageEditSize", cfg.edit_size || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_size);
  setVal("wsImageEditExtraBody", cfg.edit_extra_body || IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_extra_body);
  updateImageEngineUi();
  updateImageEditEngineUi();
  bindBooleanFieldState("wsImageEditEnabled", "开启", "关闭");
}
function readImageGenerationSettingsForm(){
  const val = (id, d="")=> String(document.getElementById(id)?.value ?? d).trim();
  return normalizeImageGenerationSettings({
    engine: val("wsImageGenEngine", IMAGE_GENERATION_SETTINGS_DEFAULTS.engine),
    model: val("wsImageGenModel", IMAGE_GENERATION_SETTINGS_DEFAULTS.model),
    api_base: val("wsImageGenBaseUrl", IMAGE_GENERATION_SETTINGS_DEFAULTS.api_base),
    api_key: val("wsImageGenApiKey", IMAGE_GENERATION_SETTINGS_DEFAULTS.api_key),
    size: val("wsImageGenSize", IMAGE_GENERATION_SETTINGS_DEFAULTS.size),
    extra_body: val("wsImageGenExtraBody", IMAGE_GENERATION_SETTINGS_DEFAULTS.extra_body),
    edit_enabled: isCheckboxEnabled(document.getElementById("wsImageEditEnabled")),
    edit_engine: val("wsImageEditEngine", IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_engine),
    edit_model: val("wsImageEditModel", IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_model),
    edit_api_base: val("wsImageEditBaseUrl", IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_api_base),
    edit_api_key: val("wsImageEditApiKey", IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_api_key),
    edit_size: val("wsImageEditSize", IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_size),
    edit_extra_body: val("wsImageEditExtraBody", IMAGE_GENERATION_SETTINGS_DEFAULTS.edit_extra_body),
  });
}

function getImageGenFormPatch(){
  const cfg = readImageGenerationSettingsForm();
  return {
    engine: cfg.engine,
    model: cfg.model,
    api_base: cfg.api_base,
    api_key: cfg.api_key,
    size: cfg.size,
    extra_body: cfg.extra_body,
  };
}
function getImageEditFormPatch(){
  const cfg = readImageGenerationSettingsForm();
  return {
    edit_enabled: cfg.edit_enabled,
    edit_engine: cfg.edit_engine,
    edit_model: cfg.edit_model,
    edit_api_base: cfg.edit_api_base,
    edit_api_key: cfg.edit_api_key,
    edit_size: cfg.edit_size,
    edit_extra_body: cfg.edit_extra_body,
  };
}
function saveImageGenSettingsOnly(){
  const current = getImageGenerationSettings();
  const next = normalizeImageGenerationSettings({ ...current, ...getImageGenFormPatch() });
  saveImageGenerationSettings(next);
  fillImageGenerationSettingsForm();
}
function saveImageEditSettingsOnly(){
  const current = getImageGenerationSettings();
  const next = normalizeImageGenerationSettings({ ...current, ...getImageEditFormPatch() });
  saveImageGenerationSettings(next);
  fillImageGenerationSettingsForm();
}
function resetImageGenSettingsOnly(){
  const current = getImageGenerationSettings();
  const defaults = IMAGE_GENERATION_SETTINGS_DEFAULTS;
  const next = normalizeImageGenerationSettings({
    ...current,
    engine: defaults.engine,
    model: defaults.model,
    api_base: defaults.api_base,
    api_key: defaults.api_key,
    size: defaults.size,
    extra_body: defaults.extra_body,
  });
  saveImageGenerationSettings(next);
  fillImageGenerationSettingsForm();
}
function resetImageEditSettingsOnly(){
  const current = getImageGenerationSettings();
  const defaults = IMAGE_GENERATION_SETTINGS_DEFAULTS;
  const next = normalizeImageGenerationSettings({
    ...current,
    edit_enabled: defaults.edit_enabled,
    edit_engine: defaults.edit_engine,
    edit_model: defaults.edit_model,
    edit_api_base: defaults.edit_api_base,
    edit_api_key: defaults.edit_api_key,
    edit_size: defaults.edit_size,
    edit_extra_body: defaults.edit_extra_body,
  });
  saveImageGenerationSettings(next);
  fillImageGenerationSettingsForm();
}

function bindImageSettingsUi(){
  document.getElementById("imageApiSaveBtn")?.addEventListener("click", ()=>{
    const enteredName = String(document.getElementById("imageApiProfileName")?.value || "").trim();
    const nextKey = String(document.getElementById("imageApiKeyInput")?.value || "").trim();
    const nextBase = String(document.getElementById("imageApiBaseInput")?.value || "").trim();
    const profiles = getImageApiProfiles();
    const activeName = getActiveImageApiName();
    const isNewDraft = imageApiProfileEditorMode === "new";
    const sourceName = isNewDraft ? "" : activeName;
    const localizedDefaultName = imageApiDisplayName(DEFAULT_IMAGE_API_NAME);
    const nextName = !enteredName || (!isNewDraft && sourceName === DEFAULT_IMAGE_API_NAME && enteredName === localizedDefaultName)
      ? DEFAULT_IMAGE_API_NAME
      : enteredName;
    if(isNewDraft && profiles[nextName]){
      toast(window.AperviaI18n?.t('settings.image.name_exists') || "An image key with this name already exists. Choose a new name.");
      return;
    }
    if(!isNewDraft && nextName !== sourceName && profiles[nextName]){
      toast(window.AperviaI18n?.t('settings.image.name_overwrite_blocked') || "An image key with this name already exists and cannot be overwritten.");
      return;
    }
    const prev = sourceName ? (profiles[sourceName] || normalizeImageApiProfile(sourceName, {})) : normalizeImageApiProfile(nextName, {});
    const meta = nextKey || nextBase ? detectVendorMeta(nextKey, nextBase || API_DEFAULT_BASE) : {vendor:"follow_chat", label:"跟随聊天 API"};
    if(sourceName && nextName !== sourceName) delete profiles[sourceName];
    profiles[nextName] = normalizeImageApiProfile(nextName, {
      ...prev,
      api_key: nextKey,
      api_base: nextBase,
      vendor: meta.vendor,
      vendor_label: meta.label,
      updated_at: Date.now(),
    });
    saveImageApiProfiles(profiles);
    setActiveImageApiName(nextName);
    toast(window.AperviaI18n?.t(isNewDraft ? 'settings.image.key_created' : 'settings.image.key_saved') || (isNewDraft ? "Image key created" : "Image key saved"));
  });
  document.getElementById("imageApiNewBtn")?.addEventListener("click", ()=>{
    beginNewImageApiProfileDraft();
  });
  document.getElementById("imageApiDeleteBtn")?.addEventListener("click", async ()=>{
    if(imageApiProfileEditorMode === "new"){
      fillImageApiFormFromCurrent();
      renderImageApiSavedList();
      toast(window.AperviaI18n?.t('settings.image.new_cancelled') || "New image key cancelled");
      return;
    }
    const active = getActiveImageApiName();
    const profiles = getImageApiProfiles();
    if(!profiles[active]) return;
    const confirmed = await askDeleteApiKeyConfirm(imageApiDisplayName(active), document.getElementById("imageApiDeleteBtn"));
    if(!confirmed) return;
    delete profiles[active];
    if(!Object.keys(profiles).length) profiles[DEFAULT_IMAGE_API_NAME] = normalizeImageApiProfile(DEFAULT_IMAGE_API_NAME, {api_key:"", api_base:""});
    saveImageApiProfiles(profiles);
    setActiveImageApiName(Object.keys(profiles)[0]);
    renderImageApiSavedList();
  });
  document.getElementById("wsImageGenEngine")?.addEventListener("change", ()=>{ updateImageEngineUi(); refreshSettingsDraftActions(); });
  document.getElementById("wsImageEditEngine")?.addEventListener("change", ()=>{ updateImageEditEngineUi(); refreshSettingsDraftActions(); });
  document.getElementById("wsImageEditEnabled")?.addEventListener("change", ()=>{ refreshBooleanFieldState("wsImageEditEnabled", "开启", "关闭"); refreshSettingsDraftActions(); });
  document.getElementById("imageGenSettingsSaveBtn")?.addEventListener("click", ()=>{
    saveImageGenSettingsOnly();
    toast(window.AperviaI18n?.t('settings.image.generation_saved') || "Image generation settings saved");
    refreshSettingsDraftActions();
  });
  document.getElementById("imageGenSettingsResetBtn")?.addEventListener("click", ()=>{
    resetImageGenSettingsOnly();
    toast(window.AperviaI18n?.t('settings.image.generation_default_restored') || 'Default image-generation settings restored');
    refreshSettingsDraftActions();
  });
  document.getElementById("imageEditSettingsSaveBtn")?.addEventListener("click", ()=>{
    saveImageEditSettingsOnly();
    toast(window.AperviaI18n?.t('settings.image.editing_saved') || "Image editing settings saved");
    refreshSettingsDraftActions();
  });
  document.getElementById("imageEditSettingsResetBtn")?.addEventListener("click", ()=>{
    resetImageEditSettingsOnly();
    toast(window.AperviaI18n?.t('settings.image.editing_default_restored') || 'Default image-editing settings restored');
    refreshSettingsDraftActions();
  });
}

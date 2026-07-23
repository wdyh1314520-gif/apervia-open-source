/* Settings model-management UI split from index3-settings-ui.js. */
let rebuildModelPickerOptions = null;
let modelCatalogLoading = false;

function ensureModelOptions(currentValue=""){
  const profile = getCurrentApiProfile();
  const selected = dedupeStrings(profile.selected_models || []);
  const extras = dedupeStrings([currentValue, profile.last_model || ""]);
  return dedupeStrings([...selected, ...extras]);
}
function rebuildModelSelectOptions(nextOptions, preferredValue=""){
  if(!modelEl) return String(preferredValue || "").trim();
  const options = dedupeStrings(nextOptions || []);
  const html = [
    `<option value="">${escapeHtml(window.AperviaI18n?.t('settings.models.not_selected') || 'No model selected')}</option>`,
    ...options.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`),
  ].join("");
  modelEl.innerHTML = html;
  const preferred = String(preferredValue || "").trim();
  const nextValue = options.includes(preferred) ? preferred : "";
  modelEl.value = nextValue;
  if(typeof rebuildModelPickerOptions === "function") rebuildModelPickerOptions();
  syncModelPickerFromSelect();
  return nextValue;
}
function persistActiveModelSelection(modelValue, {selectInSession=false, silent=false}={}){
  const value = String(modelValue || "").trim();
  if(!value) return;
  const profile = updateCurrentApiProfile((cur)=>{
    const selected = dedupeStrings([...(cur.selected_models || []), value]);
    return { ...cur, selected_models: selected, last_model: value };
  });
  if(selectInSession && typeof updateActive === "function"){
    updateActive(s => { s.model = value; });
  }
  rebuildModelSelectOptions(ensureModelOptions(value), value);
  renderApiSavedList();
  renderApiQuickMenu();
  renderModelManagementUi();
  if(!silent) toast(window.AperviaI18n?.t('settings.models.added_dropdown', {model:value}) || ('Added to the model menu: ' + value));
  return profile;
}
function removeModelFromActiveProfile(modelValue){
  const target = String(modelValue || "").trim();
  if(!target) return;
  const activeSession = typeof getActive === "function" ? getActive() : null;
  const currentSessionModel = String(activeSession?.model || "").trim();
  const nextProfile = updateCurrentApiProfile((cur)=>{
    const selected = dedupeStrings((cur.selected_models || []).filter(v => String(v || "").trim() !== target));
    const nextLast = String(cur.last_model || "").trim() === target ? "" : String(cur.last_model || "").trim();
    return { ...cur, selected_models: selected, last_model: nextLast };
  });
  let preferred = currentSessionModel;
  if(currentSessionModel === target){
    preferred = "";
    if(typeof updateActive === "function") updateActive(s => { s.model = preferred; });
  }
  rebuildModelSelectOptions(ensureModelOptions(preferred), preferred);
  renderApiSavedList();
  renderApiQuickMenu();
  renderModelManagementUi();
  toast(window.AperviaI18n?.t('settings.models.removed', {model:target}) || ('Removed model: ' + target));
}
async function fetchModelsForCurrentProfile({force=false}={}){
  if(modelCatalogLoading) return null;
  const profile = getCurrentApiProfile();
  if(!String(profile.api_key || "").trim()) throw new Error(window.AperviaI18n?.t('settings.models.save_current_key') || "Save the current key first");
  if(!force && Array.isArray(profile.models_cache) && profile.models_cache.length){
    return { ok:true, vendor:{ vendor: profile.vendor, label: profile.vendor_label }, models: profile.models_cache };
  }
  modelCatalogLoading = true;
  renderModelManagementUi();
  try{
    const res = await fetch("/api3/models/search", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ api_settings:{ api_key: profile.api_key || "", api_base: profile.api_base || API_DEFAULT_BASE, profile_name: profile.name, api_endpoint_mode: normalizeApiEndpointMode(profile.api_endpoint_mode) }, limit: 600 })
    });
    const raw = await res.text().catch(()=> "");
    let data = {};
    try{ data = JSON.parse(raw || "{}"); }catch(_){ }
    const upstreamError = String((data && (data.error || data.message)) || raw || ("HTTP " + res.status)).trim();
    if(!res.ok){
      throw new Error(upstreamError);
    }
    const models = dedupeStrings(data.models || [], 800);
    const modelDetails = normalizeModelMetadataMap(data.model_details || data.models_meta || []);
    const vendor = data.vendor && typeof data.vendor === "object" ? data.vendor : {};
    const probeFailed = !models.length || data.ok === false;
    const updated = updateCurrentApiProfile((cur)=>({
      ...cur,
      vendor: String(vendor.vendor || cur.vendor || "unknown"),
      vendor_label: String(vendor.label || cur.vendor_label || "Unknown provider"),
      models_cache: probeFailed ? [] : models,
      model_details: probeFailed ? {} : modelDetails,
      model_search_at: Date.now(),
      model_probe_error: probeFailed ? upstreamError : '',
      model_probe_failed: probeFailed,
    }));
    if(!probeFailed && !updated.selected_models.length && String(updated.last_model || "").trim()){
      persistActiveModelSelection(updated.last_model, {silent:true});
    }else{
      rebuildModelSelectOptions(ensureModelOptions(String((typeof getActive === 'function' ? getActive()?.model : '') || '')), String((typeof getActive === 'function' ? getActive()?.model : '') || ''));
      renderApiSavedList();
      renderApiQuickMenu();
      renderModelManagementUi();
    }
    return { ...data, ok: !probeFailed, manual_model_id_supported: true, error: upstreamError };
  }finally{
    modelCatalogLoading = false;
    renderModelManagementUi();
  }
}
function filterModelCatalog(models, keyword){
  const query = String(keyword || "").trim().toLowerCase();
  const rows = dedupeStrings(models || [], 800);
  if(!query) return rows;
  return rows.filter(name => String(name || "").toLowerCase().includes(query));
}
function addManualModelToCurrentProfile(modelValue){
  const value = String(modelValue || '').trim();
  if(!value){
    toast(window.AperviaI18n?.t('settings.models.enter_model_id') || 'Enter a model ID');
    return false;
  }
  const added = persistActiveModelSelection(value, {selectInSession:true, silent:true});
  rebuildModelSelectOptions(ensureModelOptions(value), value);
  if(modelEl){
    modelEl.value = value;
    modelEl.dispatchEvent(new Event('change', {bubbles:true}));
  }
  const input = document.getElementById('modelManualInput');
  if(input) input.value = '';
  renderApiSavedList();
  renderApiQuickMenu();
  renderModelManagementUi();
  toast(window.AperviaI18n?.t('settings.models.added', {model:value}) || ('Added model: ' + value));
  return !!added;
}

const MODEL_MOBILE_PANE_KEY = "webai_model_mobile_pane_v1";
let modelMobilePane = localStorage.getItem(MODEL_MOBILE_PANE_KEY) === 'selected' ? 'selected' : 'catalog';
let _modelManagementRenderSeq = 0;
function applyModelMobilePane(pane, persist=true){
  modelMobilePane = pane === 'selected' ? 'selected' : 'catalog';
  const panel = document.querySelector('[data-settings-panel="models"]');
  if(panel) panel.setAttribute('data-mobile-pane', modelMobilePane);
  document.querySelectorAll('[data-model-mobile-switch] [data-model-pane]').forEach(btn=>{
    const active = btn.getAttribute('data-model-pane') === modelMobilePane;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  if(persist){
    try{ localStorage.setItem(MODEL_MOBILE_PANE_KEY, modelMobilePane); }catch(_){ }
  }
}

function renderModelManagementUi(){
  const seq = ++_modelManagementRenderSeq;
  const profile = getCurrentApiProfile();
  const rawVendorLabel = String(profile.vendor_label || detectVendorMeta(profile.api_key, profile.api_base).label || "未识别厂商").trim();
  const vendorLabel = rawVendorLabel === '未识别厂商'
    ? (window.AperviaI18n?.t('settings.models.unknown_provider') || rawVendorLabel)
    : (rawVendorLabel.startsWith('未识别 · ')
      ? (window.AperviaI18n?.t('settings.models.unknown_host', {host:rawVendorLabel.slice(6)}) || rawVendorLabel)
      : rawVendorLabel);
  const vendorBadge = document.getElementById("modelVendorBadge");
  const hintEl = document.getElementById("modelManageHint");
  const profileNameEl = document.getElementById("modelManageProfileName");
  const catalogStatEl = document.getElementById("modelCatalogStat");
  const selectedStatEl = document.getElementById("modelSelectedStat");
  const catalogMobileCountEl = document.getElementById("modelCatalogMobileCount");
  const selectedMobileCountEl = document.getElementById("modelSelectedMobileCount");
  const catalogCount = String((profile.models_cache || []).length || 0);
  const selectedCount = String((profile.selected_models || []).length || 0);
  if(vendorBadge) vendorBadge.textContent = vendorLabel;
  if(profileNameEl) profileNameEl.textContent = apiProfileDisplayName(profile.name || DEFAULT_API_PROFILE_NAME);
  if(catalogStatEl) catalogStatEl.textContent = catalogCount;
  if(selectedStatEl) selectedStatEl.textContent = selectedCount;
  if(catalogMobileCountEl) catalogMobileCountEl.textContent = catalogCount;
  if(selectedMobileCountEl) selectedMobileCountEl.textContent = selectedCount;
  applyModelMobilePane(modelMobilePane, false);
  if(hintEl){
    let suffix = modelCatalogLoading
      ? (window.AperviaI18n?.t('settings.models.loading') || 'Loading models…')
      : (!profile.api_key
        ? (window.AperviaI18n?.t('settings.models.key_empty') || 'The current key is empty. Save it before loading models.')
        : (window.AperviaI18n?.t('settings.models.endpoint', {endpoint:shortApiBase(profile.api_base || '')}) || `Current endpoint: ${shortApiBase(profile.api_base || '')}`));
    if(!modelCatalogLoading && profile.api_key && profile.model_probe_failed){
      const rawErr = String(profile.model_probe_error || '').trim();
      const errorDetail = rawErr ? (window.AperviaI18n?.t('settings.models.upstream_error', {error:rawErr}) || ' Upstream response: ' + rawErr) : '';
      suffix = window.AperviaI18n?.t('settings.models.probe_failed', {error:errorDetail}) || `The upstream endpoint does not support automatic model discovery. Enter a model ID manually.${errorDetail}`;
    }
    hintEl.textContent = window.AperviaI18n?.t('settings.models.detected', {vendor:vendorLabel, detail:suffix}) || `Detected provider: ${vendorLabel}. ${suffix}`;
  }
  const selectedWrap = document.getElementById("modelSelectedList");
  if(selectedWrap){
    selectedWrap.innerHTML = "";
    const selected = dedupeStrings(profile.selected_models || []);
    if(!selected.length){
      selectedWrap.innerHTML = `<div class="settings-empty">${escapeHtml(window.AperviaI18n?.t('settings.models.selected_empty') || 'No models are selected. Load models first or add a model ID manually.')}</div>`;
    }else{
      const currentModel = String((typeof getActive === 'function' ? getActive()?.model : '') || '').trim();
      let selectedIndex = 0;
      const appendSelectedBatch = () => {
        if(seq !== _modelManagementRenderSeq || settingsActiveTab !== 'models') return;
        const frag = document.createDocumentFragment();
        const end = Math.min(selectedIndex + 40, selected.length);
        for(; selectedIndex < end; selectedIndex++){
          const name = selected[selectedIndex];
          const row = document.createElement("div");
          row.className = "model-selected-item";
          row.innerHTML = `
            <div class="model-row-main">
              <div class="model-row-title">${escapeHtml(name)}</div>
              <div class="model-row-sub">${escapeHtml(window.AperviaI18n?.t(currentModel === name ? 'settings.models.current_model' : 'settings.models.selected_model') || (currentModel === name ? 'Currently used by this chat' : 'Available in the main chat model list'))}</div>
            </div>
            <div class="model-row-actions">
              <button type="button" data-action="use">${escapeHtml(window.AperviaI18n?.t('settings.models.use') || 'Use')}</button>
              <button type="button" data-action="remove">${escapeHtml(window.AperviaI18n?.t('settings.models.remove') || 'Remove')}</button>
            </div>
          `;
          row.querySelector('[data-action="use"]')?.addEventListener('click', ()=>{
            persistActiveModelSelection(name, {selectInSession:true, silent:true});
            rebuildModelSelectOptions(ensureModelOptions(name), name);
            if(modelEl){
              modelEl.value = name;
              modelEl.dispatchEvent(new Event('change', {bubbles:true}));
            }
            toast(window.AperviaI18n?.t('settings.models.switched', {model:name}) || ('Switched model: ' + name));
          });
          row.querySelector('[data-action="remove"]')?.addEventListener('click', ()=> removeModelFromActiveProfile(name));
          frag.appendChild(row);
        }
        selectedWrap.appendChild(frag);
        if(selectedIndex < selected.length) scheduleUiAfterPaint(appendSelectedBatch);
      };
      appendSelectedBatch();
    }
  }
  const resultsWrap = document.getElementById("modelSearchResults");
  if(resultsWrap){
    resultsWrap.innerHTML = "";
    const keyword = String(document.getElementById("modelSearchInput")?.value || "").trim();
    const selectedSet = new Set(dedupeStrings(profile.selected_models || []).map(v => v.toLowerCase()));
    const rows = filterModelCatalog(profile.models_cache || [], keyword).slice(0, 240);
    if(modelCatalogLoading){
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.render(resultsWrap, { variant:'compact-list', rows:5, label:window.AperviaI18n?.t('settings.models.loading') || 'Loading models…' });
      else resultsWrap.innerHTML = `<div class="settings-empty">${escapeHtml(window.AperviaI18n?.t('settings.models.loading') || 'Loading models…')}</div>`;
    }else if(!profile.api_key){
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(resultsWrap);
      resultsWrap.innerHTML = `<div class="settings-empty">${escapeHtml(window.AperviaI18n?.t('settings.models.results_key_empty') || 'The current key is empty. Save it in API settings, then return to load models.')}</div>`;
    }else if(!(profile.models_cache || []).length){
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(resultsWrap);
      if(profile.model_probe_failed){
        const rawErr = String(profile.model_probe_error || '').trim();
        const probeMessage = window.AperviaI18n?.t('settings.models.results_probe_failed') || 'The upstream endpoint does not support automatic model discovery. Enter a model ID above to add it.';
        const probeError = rawErr ? `<br>${escapeHtml(window.AperviaI18n?.t('settings.models.upstream_error', {error:rawErr}) || `Upstream response: ${rawErr}`)}` : '';
        resultsWrap.innerHTML = `<div class="settings-empty">${escapeHtml(probeMessage)}${probeError}</div>`;
      }else{
        resultsWrap.innerHTML = `<div class="settings-empty">${escapeHtml(window.AperviaI18n?.t('settings.models.available_empty') || 'No models have been loaded. Select Detect and load models above, or enter a model ID manually.')}</div>`;
      }
    }else if(!rows.length){
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(resultsWrap);
      resultsWrap.innerHTML = `<div class="settings-empty">${escapeHtml(window.AperviaI18n?.t('settings.models.no_match', {keyword}) || `No models matching “${keyword}” were found.`)}</div>`;
    }else{
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(resultsWrap);
      let rowIndex = 0;
      const appendResultBatch = () => {
        if(seq !== _modelManagementRenderSeq || settingsActiveTab !== 'models') return;
        const frag = document.createDocumentFragment();
        const end = Math.min(rowIndex + 48, rows.length);
        for(; rowIndex < end; rowIndex++){
          const name = rows[rowIndex];
          const active = selectedSet.has(String(name || '').toLowerCase());
          const row = document.createElement("div");
          row.className = "model-result-item" + (active ? " active" : "");
          row.innerHTML = `
            <div class="model-row-main">
              <div class="model-row-title">${escapeHtml(name)}</div>
              <div class="model-row-sub">${escapeHtml(window.AperviaI18n?.t(active ? 'settings.models.joined_short' : 'settings.models.join_hint') || (active ? 'Available in the main chat menu' : 'Add this model to the main chat menu'))}</div>
            </div>
            <div class="model-row-actions">
              <button type="button">${escapeHtml(window.AperviaI18n?.t(active ? 'settings.models.use' : 'settings.models.add') || (active ? 'Use' : 'Add'))}</button>
            </div>
          `;
          row.querySelector('button')?.addEventListener('click', ()=>{
            persistActiveModelSelection(name, {selectInSession:true, silent:active});
            if(modelEl){
              modelEl.value = name;
              modelEl.dispatchEvent(new Event('change', {bubbles:true}));
            }
          });
          frag.appendChild(row);
        }
        resultsWrap.appendChild(frag);
        if(rowIndex < rows.length) scheduleUiAfterPaint(appendResultBatch);
      };
      appendResultBatch();
    }
  }
}

function syncModelOptionsForActiveProfile({preferredModel='', ensureSessionValue=true}={}){
  const currentSession = typeof getActive === 'function' ? getActive() : null;
  const requested = String(preferredModel || currentSession?.model || '').trim();
  const options = ensureModelOptions(requested);
  const nextValue = rebuildModelSelectOptions(options, requested || (getCurrentApiProfile().last_model || ''));
  if(ensureSessionValue && currentSession && nextValue && !String(currentSession.model || '').trim()){
    updateActive(s => { s.model = nextValue; });
  }
  return nextValue;
}

function bindModelManagementSettingsUi(){
  document.getElementById("modelFetchBtn")?.addEventListener("click", async ()=>{
    try{
      const data = await fetchModelsForCurrentProfile({force:false});
      if(data && data.ok === false) toast(window.AperviaI18n?.t('settings.models.discovery_unsupported') || "The upstream endpoint does not support automatic model discovery. Enter a model ID manually.");
      else toast(window.AperviaI18n?.t('settings.models.list_loaded') || "Model list loaded");
    }catch(err){
      toast(err?.message || window.AperviaI18n?.t('settings.models.load_failed') || "Unable to load models");
    }
  });
  document.getElementById("modelRefreshBtn")?.addEventListener("click", async ()=>{
    try{
      const data = await fetchModelsForCurrentProfile({force:true});
      if(data && data.ok === false) toast(window.AperviaI18n?.t('settings.models.discovery_unsupported') || "The upstream endpoint does not support automatic model discovery. Enter a model ID manually.");
      else toast(window.AperviaI18n?.t('settings.models.list_refreshed') || "Model list refreshed");
    }catch(err){
      toast(err?.message || window.AperviaI18n?.t('settings.models.refresh_failed') || "Unable to refresh models");
    }
  });
  document.getElementById("modelManualAddBtn")?.addEventListener("click", ()=>{
    addManualModelToCurrentProfile(document.getElementById("modelManualInput")?.value || "");
  });
  document.getElementById("modelManualInput")?.addEventListener("keydown", (e)=>{
    if(e.key === 'Enter'){
      e.preventDefault();
      addManualModelToCurrentProfile(e.target?.value || "");
    }
  });
  document.getElementById("modelSearchInput")?.addEventListener("input", ()=> renderModelManagementUi());
  document.querySelectorAll("[data-model-mobile-switch] [data-model-pane]").forEach(btn=>{
    btn.addEventListener("click", ()=> applyModelMobilePane(btn.getAttribute("data-model-pane") || "catalog"));
  });
  applyModelMobilePane(modelMobilePane, false);
}

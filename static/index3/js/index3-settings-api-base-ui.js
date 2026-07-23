/* API Base URL autocomplete for settings API profiles. Split from index3-settings-ui.js. */
const API_BASE_PRESETS = [
  { label:"OpenAI", value:"https://api.openai.com/v1", tag:"官方" },
  { label:"OpenRouter", value:"https://openrouter.ai/api/v1", tag:"聚合" },
  { label:"Anthropic", value:"https://api.anthropic.com/v1", tag:"官方" },
  { label:"Google Gemini", value:"https://generativelanguage.googleapis.com/v1beta/openai", tag:"Gemini" },
  { label:"xAI", value:"https://api.x.ai/v1", tag:"官方" },
  { label:"DeepSeek", value:"https://api.deepseek.com/v1", tag:"官方" },
  { label:"Moonshot", value:"https://api.moonshot.cn/v1", tag:"官方" },
  { label:"DashScope", value:"https://dashscope.aliyuncs.com/compatible-mode/v1", tag:"阿里云" },
  { label:"SiliconFlow", value:"https://api.siliconflow.cn/v1", tag:"官方" },
  { label:"智谱", value:"https://open.bigmodel.cn/api/paas/v4", tag:"官方" },
  { label:"Groq", value:"https://api.groq.com/openai/v1", tag:"官方" },
  { label:"Cerebras", value:"https://api.cerebras.ai/v1", tag:"官方" },
  { label:"自定义域名示例", value:"https://api.example.com/v1", tag:"示例" },
];
let apiBaseSuggestState = { open:false, items:[], activeIndex:-1 };

function isRemovedDefaultApiBase(value){
  const key = normalizeApiBaseInputValue(value).toLowerCase();
  return key === 'https://api.vveai.com/v1'
    || key === 'https://api.yveai.com/v1'
    || key === 'https://api.vvapi.com/v1';
}

function normalizeApiBaseInputValue(raw){
  let value = String(raw || '').trim();
  if(!value) return '';
  if(!/^[a-z][a-z0-9+.-]*:\/\//i.test(value) && /^[A-Za-z0-9.-]+\//.test(value)) value = `https://${value}`;
  else if(!/^[a-z][a-z0-9+.-]*:\/\//i.test(value) && /^[A-Za-z0-9.-]+$/.test(value)) value = `https://${value}`;
  value = value.replace(/\s+/g, '').replace(/\/+$/, '');
  try{
    const u = new URL(value);
    // Do not auto-append /v1. Some OpenAI-compatible providers expose audio/chat
    // endpoints directly under a host:port or a custom path. Preserve exactly what
    // the user typed, only trimming trailing slashes.
    return u.toString().replace(/\/+$/, '');
  }catch(_){ }
  return value;
}
function normalizeApiBaseOptionList(values, currentBase=''){
  const out = [];
  const seen = new Set();
  const currentKey = normalizeApiBaseInputValue(currentBase).toLowerCase();
  const add = (value)=>{
    const url = normalizeApiBaseInputValue(value);
    if(!url) return;
    const key = url.toLowerCase();
    if(seen.has(key)) return;
    seen.add(key);
    out.push(url);
  };
  add(currentBase);
  if(Array.isArray(values)) values.forEach(add);
  return out.slice(0, 30);
}
function mergeApiBaseOptions(values, currentBase=''){
  return normalizeApiBaseOptionList(values, currentBase);
}
function getApiBaseSuggestInput(){ return document.getElementById('apiBaseInput'); }
function getApiBaseSuggestMenu(){ return document.getElementById('apiBaseSuggestMenu'); }
function getApiBaseSuggestCombo(){ return document.getElementById('apiBaseCombo'); }
function getApiBaseSuggestRoot(){ return document.getElementById('apiBaseField') || getApiBaseSuggestCombo(); }
function getApiBaseSuggestButton(){ return document.getElementById('apiBaseSuggestBtn'); }
function getApiBaseSuggestionPresets(){
  const out = [];
  const seen = new Set();
  const push = (label, value, tag='常用', extra={})=>{
    const url = normalizeApiBaseInputValue(value);
    if(!url) return;
    const key = url.toLowerCase();
    if(seen.has(key)) return;
    seen.add(key);
    out.push({
      label:String(label || shortApiBase(url)).trim() || shortApiBase(url),
      value:url,
      tag:String(tag || '常用').trim() || '常用',
      canDelete: !!extra.canDelete,
    });
  };

  let profiles = {};
  try{ profiles = getApiProfiles(); }catch(_){ profiles = {}; }
  let activeName = '';
  try{ activeName = apiProfileEditorMode === "edit" ? String(getActiveApiName() || '').trim() : ''; }catch(_){ activeName = ''; }
  const currentInput = normalizeApiBaseInputValue(document.getElementById('apiBaseInput')?.value || '');

  if(activeName && profiles[activeName]){
    const active = profiles[activeName] || {};
    const savedBase = normalizeApiBaseInputValue(active.api_base || API_DEFAULT_BASE) || API_DEFAULT_BASE;
    const options = normalizeApiBaseOptionList(active.api_base_options || [], savedBase);
    options.forEach((value)=>{
      const key = value.toLowerCase();
      const savedKey = savedBase.toLowerCase();
      const tag = currentInput && key === currentInput.toLowerCase()
        ? '当前'
        : (key === savedKey ? '已保存' : '备用地址');
      push(shortApiBase(value), value, tag, { canDelete: true });
    });
    if(currentInput && !options.some(value => value.toLowerCase() === currentInput.toLowerCase())){
      push(shortApiBase(currentInput), currentInput, '当前输入', { transient: true });
    }
    return out;
  }

  API_BASE_PRESETS.forEach(item => push(item.label, item.value, item.tag));
  return out;
}

function collectApiBaseSuggestionItems(query=''){
  const q = String(query || '').trim().toLowerCase();
  const rows = getApiBaseSuggestionPresets();
  const filtered = !q ? rows : rows.filter(item => {
    const text = `${item.label} ${item.value} ${item.tag}`.toLowerCase();
    return text.includes(q);
  });
  const exactUrlSet = new Set(filtered.map(item => String(item.value || '').trim().toLowerCase()));
  const normalizedQuery = normalizeApiBaseInputValue(query);
  if(normalizedQuery && !exactUrlSet.has(normalizedQuery.toLowerCase())){
    filtered.unshift({ label:'使用当前输入', value:normalizedQuery, tag:'自定义' });
  }
  return filtered.slice(0, 12);
}
function closeApiBaseSuggestMenu(){
  apiBaseSuggestState.open = false;
  apiBaseSuggestState.items = [];
  apiBaseSuggestState.activeIndex = -1;
  const root = getApiBaseSuggestRoot();
  const combo = getApiBaseSuggestCombo();
  const menu = getApiBaseSuggestMenu();
  const btn = getApiBaseSuggestButton();
  root?.classList.remove('open');
  combo?.classList.remove('open');
  if(menu){ menu.hidden = true; menu.innerHTML = ''; }
  if(btn){ btn.setAttribute('aria-expanded', 'false'); btn.textContent = '常用'; }
}
function applyApiBaseSuggestion(value, {focusInput=true} = {}){
  const input = getApiBaseSuggestInput();
  const next = normalizeApiBaseInputValue(value);
  if(input) input.value = next || value || '';
  updateApiVendorPreview();
  closeApiBaseSuggestMenu();
  if(focusInput) input?.focus();
}
function removeApiBaseSuggestion(value){
  const target = normalizeApiBaseInputValue(value);
  if(!target) return;
  let activeName = '';
  try{ activeName = apiProfileEditorMode === "edit" ? String(getActiveApiName() || '').trim() : ''; }catch(_){ activeName = ''; }
  if(!activeName) return;
  const profiles = getApiProfiles();
  const prev = profiles[activeName];
  if(!prev) return;
  const currentBase = normalizeApiBaseInputValue(prev.api_base || API_DEFAULT_BASE) || API_DEFAULT_BASE;
  const allOptions = normalizeApiBaseOptionList(prev.api_base_options || [], currentBase);
  const nextOptions = allOptions.filter(url => url.toLowerCase() !== target.toLowerCase());
  const isCurrentBase = currentBase && target.toLowerCase() === currentBase.toLowerCase();
  const nextBase = isCurrentBase ? (nextOptions[0] || API_DEFAULT_BASE) : currentBase;
  profiles[activeName] = normalizeApiProfile(activeName, {
    ...prev,
    api_base: nextBase,
    api_base_options: nextOptions,
  });
  saveApiProfiles(profiles);
  const input = getApiBaseSuggestInput();
  if(input && isCurrentBase) input.value = nextBase || '';
  updateApiVendorPreview();
  renderApiQuickMenu();
  renderApiSavedList();
  if(apiBaseSuggestState.open) renderApiBaseSuggestMenu('');
  toast(window.AperviaI18n?.t('settings.api.base_removed') || 'Address removed');
}

function renderApiBaseSuggestMenu(query=''){
  const root = getApiBaseSuggestRoot();
  const combo = getApiBaseSuggestCombo();
  const menu = getApiBaseSuggestMenu();
  const btn = getApiBaseSuggestButton();
  if(!root || !combo || !menu) return;
  const items = collectApiBaseSuggestionItems(query);
  apiBaseSuggestState.open = true;
  apiBaseSuggestState.items = items;
  apiBaseSuggestState.activeIndex = items.length ? 0 : -1;
  root.classList.add('open');
  combo.classList.add('open');
  menu.hidden = false;
  if(btn){ btn.setAttribute('aria-expanded', 'true'); btn.textContent = '收起'; }

  const suggestTitle = apiProfileEditorMode === 'edit' ? '当前 Key 地址' : '常用地址';
  const head = `<div class="api-base-suggest-head"><span>${escapeHtml(suggestTitle)}</span><button type="button" class="api-base-suggest-close" aria-label="收起常用 API Base URL">收起</button></div>`;
  if(!items.length){
    menu.innerHTML = `${head}<div class="api-base-suggest-empty">没有匹配的常用地址，你可以继续直接输入完整 API Base URL。</div>`;
    menu.querySelector('.api-base-suggest-close')?.addEventListener('click', closeApiBaseSuggestMenu);
    return;
  }
  const body = document.createElement('div');
  body.className = 'api-base-suggest-body';
  items.forEach((item, idx) => {
    const rowEl = document.createElement('div');
    rowEl.className = 'api-base-suggest-row' + (item.canDelete ? ' can-delete' : '');
    const btnEl = document.createElement('button');
    btnEl.type = 'button';
    btnEl.className = 'api-base-suggest-chip' + (apiBaseSuggestState.activeIndex === idx ? ' active' : '');
    btnEl.dataset.index = String(idx);
    btnEl.innerHTML = `<span class="api-base-suggest-label">${escapeHtml(item.label || '')}</span><span class="api-base-suggest-url">${escapeHtml(item.value || '')}</span><span class="api-base-suggest-tag">${escapeHtml(item.tag || '常用')}</span>`;
    btnEl.addEventListener('click', ()=> applyApiBaseSuggestion(item.value));
    rowEl.appendChild(btnEl);
    if(item.canDelete){
      const delEl = document.createElement('button');
      delEl.type = 'button';
      delEl.className = 'api-base-suggest-delete';
      delEl.setAttribute('aria-label', `删除地址 ${item.value || ''}`);
      delEl.textContent = '×';
      delEl.addEventListener('click', (e)=>{
        e.preventDefault();
        e.stopPropagation();
        removeApiBaseSuggestion(item.value);
      });
      rowEl.appendChild(delEl);
    }
    body.appendChild(rowEl);
  });
  menu.innerHTML = head;
  menu.querySelector('.api-base-suggest-close')?.addEventListener('click', closeApiBaseSuggestMenu);
  menu.appendChild(body);
}
function updateApiVendorPreview(){
  const key = String(document.getElementById('apiKeyInput')?.value || '').trim();
  const baseRaw = String(document.getElementById('apiBaseInput')?.value || '').trim();
  const base = normalizeApiBaseInputValue(baseRaw) || baseRaw || API_DEFAULT_BASE;
  const meta = key || baseRaw ? detectVendorMeta(key, base) : { label:'待识别', vendor:'unknown' };
  const badge = document.getElementById('apiVendorBadge');
  const hint = document.getElementById('apiVendorHint');
  if(badge){ badge.textContent = ''; badge.hidden = true; badge.style.display = 'none'; }
  if(hint){ hint.textContent = ''; hint.hidden = true; hint.style.display = 'none'; }
}
function persistCurrentApiProfileFormIfSafe({silent=true} = {}){
  try{
    if(apiProfileEditorMode === "new") return false;
    const activeName = getActiveApiName();
    const formName = apiProfileInputName(document.getElementById("apiProfileName")?.value, activeName, false);
    if(!activeName || formName !== activeName) return false;
    const profiles = getApiProfiles();
    const prev = profiles[activeName] || normalizeApiProfile(activeName, {});
    const nextKey = String(document.getElementById("apiKeyInput")?.value || "").trim();
    const rawBase = String(document.getElementById("apiBaseInput")?.value || "").trim();
    const nextBase = normalizeApiBaseInputValue(rawBase) || API_DEFAULT_BASE;
    const nextEndpointMode = getActiveApiEndpointMode();
    const baseInputEl = document.getElementById("apiBaseInput");
    if(baseInputEl && rawBase && baseInputEl.value !== nextBase) baseInputEl.value = nextBase;
    const connectionChanged = String(prev.api_key || '') !== nextKey || String(prev.api_base || '') !== nextBase;
    if(!connectionChanged) return false;
    const meta = detectVendorMeta(nextKey, nextBase);
    profiles[activeName] = normalizeApiProfile(activeName, {
      ...prev,
      api_key: nextKey,
      api_base: nextBase,
      api_base_options: mergeApiBaseOptions(prev.api_base_options || [], nextBase),
      api_endpoint_mode: nextEndpointMode,
      responses_reasoning_effort: normalizeResponsesReasoningEffort(document.getElementById("responsesReasoningEffortInput")?.value || prev.responses_reasoning_effort || "auto"),
      responses_reasoning_summary: normalizeResponsesReasoningSummary(document.getElementById("responsesReasoningSummaryInput")?.value || prev.responses_reasoning_summary || "detailed"),
      responses_reasoning_context: normalizeResponsesReasoningContext(document.getElementById("responsesReasoningContextInput")?.value || prev.responses_reasoning_context || "auto"),
      vendor: meta.vendor,
      vendor_label: meta.label,
      selected_models: connectionChanged ? [] : (prev.selected_models || []),
      models_cache: connectionChanged ? [] : (prev.models_cache || []),
      last_model: connectionChanged ? '' : String(prev.last_model || '').trim(),
      model_search_at: connectionChanged ? 0 : Number(prev.model_search_at || 0),
    });
    saveApiProfiles(profiles);
    renderApiQuickMenu();
    renderApiSavedList();
    refreshThinkingControlUi();
    renderModelManagementUi();
    if(!silent) toast(window.AperviaI18n?.t('settings.api.key_saved_reset') || 'Key saved. The model list was reset for the new provider.');
    return true;
  }catch(_){ return false; }
}

function moveApiBaseSuggestion(step){
  if(!apiBaseSuggestState.open || !apiBaseSuggestState.items.length) return;
  const total = apiBaseSuggestState.items.length;
  apiBaseSuggestState.activeIndex = (apiBaseSuggestState.activeIndex + step + total) % total;
  const buttons = Array.from(getApiBaseSuggestMenu()?.querySelectorAll('.api-base-suggest-chip') || []);
  buttons.forEach((el, idx) => el.classList.toggle('active', idx === apiBaseSuggestState.activeIndex));
  buttons[apiBaseSuggestState.activeIndex]?.scrollIntoView({ block:'nearest' });
}
function chooseActiveApiBaseSuggestion(){
  if(!apiBaseSuggestState.open || apiBaseSuggestState.activeIndex < 0) return false;
  const item = apiBaseSuggestState.items[apiBaseSuggestState.activeIndex];
  if(!item) return false;
  applyApiBaseSuggestion(item.value);
  return true;
}
function initApiBaseAutocomplete(){
  const input = getApiBaseSuggestInput();
  const btn = getApiBaseSuggestButton();
  const root = getApiBaseSuggestRoot();
  if(!input || !btn || !root || root.dataset.enhanced === '1') return;
  root.dataset.enhanced = '1';
  input.setAttribute('autocomplete', 'off');
  input.addEventListener('input', ()=>{ if(apiBaseSuggestState.open) renderApiBaseSuggestMenu(input.value || ''); updateApiVendorPreview(); });
  input.addEventListener('change', ()=>{ input.value = normalizeApiBaseInputValue(input.value || '') || String(input.value || '').trim(); updateApiVendorPreview(); persistCurrentApiProfileFormIfSafe({silent:true}); });
  input.addEventListener('keydown', (e)=>{
    if(!apiBaseSuggestState.open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')){
      renderApiBaseSuggestMenu(input.value || '');
      e.preventDefault();
      return;
    }
    if(e.key === 'ArrowDown'){ e.preventDefault(); moveApiBaseSuggestion(1); return; }
    if(e.key === 'ArrowUp'){ e.preventDefault(); moveApiBaseSuggestion(-1); return; }
    if(e.key === 'Enter' && apiBaseSuggestState.open){ if(chooseActiveApiBaseSuggestion()) e.preventDefault(); return; }
    if(e.key === 'Escape' && apiBaseSuggestState.open){ e.preventDefault(); closeApiBaseSuggestMenu(); }
  });
  btn.addEventListener('click', (e)=>{
    e.preventDefault();
    if(apiBaseSuggestState.open) closeApiBaseSuggestMenu();
    else renderApiBaseSuggestMenu('');
    input.focus();
  });
  document.addEventListener('click', (e)=>{ if(!root.contains(e.target)) closeApiBaseSuggestMenu(); });
}

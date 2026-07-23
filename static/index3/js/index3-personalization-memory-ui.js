const PERSONALIZATION_SCHEMA_VERSION = 3;
const PERSONALIZATION_MEMORY_MAX_ITEMS = 80;
const PERSONALIZATION_MEMORY_MAX_TEXT = 600;
const PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_TEXT = 900;
function personalizationMemoryT(key, params, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

let PERSONALIZATION_BACKEND_SAVE_SEQ = 0;
let PERSONALIZATION_BACKEND_LOADED_EMAIL = '';
const PERSONALIZATION_DEFAULTS = {
  schemaVersion: PERSONALIZATION_SCHEMA_VERSION,
  memoryEnabled: true,
  memoryAutoManageEnabled: true,
  historyReferenceEnabled: true,
  customInstruction: '',
  profileNickname: '',
  profileOccupation: '',
  profileDetails: '',
  customAboutUser: '',
  customResponseStyle: '',
  memoryInstruction: '',
  responseStylePreset: '',
  structurePreference: '',
  emojiPreference: '',
  memoryItems: [],
};

function _memoryTrim(v, maxLen=PERSONALIZATION_MEMORY_MAX_TEXT){
  return String(v ?? '')
    .replace(/\r\n?/g, '\n')
    .trim()
    .slice(0, maxLen);
}

function normalizeMemoryItem(raw, idx=0){
  let text = '';
  let createdAt = now();
  let updatedAt = createdAt;
  let id = '';
  if(typeof raw === 'string'){
    text = _memoryTrim(raw);
  }else if(raw && typeof raw === 'object'){
    text = _memoryTrim(raw.text);
    createdAt = Number(raw.createdAt || now()) || now();
    updatedAt = Number(raw.updatedAt || createdAt) || createdAt;
    id = String(raw.id || '').trim();
  }
  if(!text) return null;
  if(!id) id = `mem_${createdAt.toString(16)}_${Math.random().toString(16).slice(2, 8)}_${idx}`;
  return { id, text, createdAt, updatedAt, ruleType:'soft' };
}

function normalizePersonalizationChoice(value, allowed){
  const raw = String(value || '').trim().toLowerCase();
  return allowed.includes(raw) ? raw : '';
}
function personalizationExpressionPreferenceLine(state){
  const styleMap = { professional:'专业可靠', friendly:'亲和友善', direct:'直言不讳', practical:'高效务实' };
  const structureMap = { more:'多用标题/列表', less:'少用标题/列表' };
  const emojiMap = { more:'可多用表情', less:'少用表情' };
  const parts = [];
  const style = styleMap[String(state?.responseStylePreset || '')];
  const structure = structureMap[String(state?.structurePreference || '')];
  const emoji = emojiMap[String(state?.emojiPreference || '')];
  if(style) parts.push(style);
  if(structure) parts.push(structure);
  if(emoji) parts.push(emoji);
  return parts.length ? ('表达偏好：' + parts.join('；') + '。仅影响表达，不影响事实/工具。') : '';
}
function normalizePersonalizationState(raw){
  const src = raw && typeof raw === 'object' ? raw : {};
  const out = {
    schemaVersion: PERSONALIZATION_SCHEMA_VERSION,
    memoryEnabled: src.memoryEnabled === undefined ? PERSONALIZATION_DEFAULTS.memoryEnabled : !!src.memoryEnabled,
    memoryAutoManageEnabled: src.memoryAutoManageEnabled === undefined ? PERSONALIZATION_DEFAULTS.memoryAutoManageEnabled : !!src.memoryAutoManageEnabled,
    historyReferenceEnabled: src.historyReferenceEnabled === undefined ? PERSONALIZATION_DEFAULTS.historyReferenceEnabled : !!src.historyReferenceEnabled,
    customInstruction: _memoryTrim(src.customInstruction || src.customResponseStyle || src.responseStyle || src.responseInstruction || '', PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_TEXT),
    profileNickname: _memoryTrim(src.profileNickname || src.nickname || src.displayName || '', 120),
    profileOccupation: _memoryTrim(src.profileOccupation || src.occupation || src.jobTitle || '', 180),
    profileDetails: _memoryTrim(src.profileDetails || src.customAboutUser || src.aboutUser || src.userProfileInstruction || '', 700),
    customAboutUser: '',
    customResponseStyle: '',
    memoryInstruction: _memoryTrim(src.memoryInstruction || '', 1800),
    responseStylePreset: normalizePersonalizationChoice(src.responseStylePreset || src.stylePreset || '', ['professional','friendly','direct','practical']),
    structurePreference: normalizePersonalizationChoice(src.structurePreference || src.titleListPreference || '', ['more','less']),
    emojiPreference: normalizePersonalizationChoice(src.emojiPreference || '', ['more','less']),
    memoryItems: [],
  };
  const seen = new Set();
  const items = Array.isArray(src.memoryItems) ? src.memoryItems : [];
  for(const item of items){
    const normalized = normalizeMemoryItem(item, out.memoryItems.length);
    if(!normalized) continue;
    const key = normalized.text.toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    out.memoryItems.push(normalized);
    if(out.memoryItems.length >= PERSONALIZATION_MEMORY_MAX_ITEMS) break;
  }
  return out;
}
function ensureStorePersonalization(targetStore=store){
  const target = targetStore && typeof targetStore === 'object' ? targetStore : null;
  if(!target) return normalizePersonalizationState();
  const normalized = normalizePersonalizationState(target.personalization || {});
  target.personalization = normalized;
  return normalized;
}
function getPersonalizationState(){
  return ensureStorePersonalization(store);
}
function clonePersonalizationState(){
  try{ return JSON.parse(JSON.stringify(getPersonalizationState())); }catch(_){ return normalizePersonalizationState(getPersonalizationState()); }
}
function buildPersonalizationMemorySystemPrompt(raw){
  const state = normalizePersonalizationState(raw);
  const items = Array.isArray(state.memoryItems) ? state.memoryItems : [];
  const customInstruction = _memoryTrim(state.customInstruction || '', PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_TEXT);
  const nickname = _memoryTrim(state.profileNickname || '', 120);
  const occupation = _memoryTrim(state.profileOccupation || '', 180);
  const details = _memoryTrim(state.profileDetails || '', 700);
  const extra = _memoryTrim(state.memoryInstruction || '', 1800);
  const expressionPreference = personalizationExpressionPreferenceLine(state);
  const memoryOn = !!state.memoryEnabled;
  const hasProfile = !!(nickname || occupation || details);
  const hasMemory = memoryOn && (items.length || extra);
  if(!customInstruction && !expressionPreference && !hasProfile && !hasMemory) return '';
  const lines = [
    '【个性化】',
    '- 本轮用户明确要求优先；不要主动提到个性化、记忆或自定义指令。',
  ];
  if(expressionPreference) lines.push(expressionPreference);
  if(customInstruction){
    lines.push('', '【自定义指令】', customInstruction);
  }
  if(hasProfile){
    lines.push('', '【关于你】');
    if(nickname) lines.push('昵称：' + nickname);
    if(occupation) lines.push('职业：' + occupation);
    if(details) lines.push('详情：' + details);
  }
  if(hasMemory){
    lines.push('', '【保存的记忆】');
    if(extra) lines.push('说明：' + extra);
    items.forEach((item, idx) => lines.push(`${idx + 1}. ${item.text}`));
  }
  return lines.join('\n');
}
function isBackendPersonalizationActive(){
  return !!normalizeAccountScopeEmail(currentAccountEmail || '');
}
function buildPersonalizationStateForServer(raw){
  return normalizePersonalizationState(raw || getPersonalizationState());
}
async function fetchBackendPersonalizationState(opts={}){
  const scopeEmail = normalizeAccountScopeEmail(currentAccountEmail || '');
  if(!scopeEmail || authKickRedirecting) return null;
  const res = await fetch('/api3/personalization/memory', { cache:'no-store', credentials:'same-origin' });
  const data = await res.json().catch(()=>({}));
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || personalizationMemoryT('account.session_expired', null, 'Your session has expired. Sign in again.'))) return null;
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  const state = normalizePersonalizationState(data?.state || {});
  if(normalizeAccountScopeEmail(currentAccountEmail || '') !== scopeEmail) return state;
  store.personalization = state;
  PERSONALIZATION_BACKEND_LOADED_EMAIL = scopeEmail;
  if(opts.persist !== false){
    try{ if(opts.immediate) saveStore(); else saveStoreThrottled(); }catch(_){ }
  }
  if(opts.render !== false) renderPersonalizationUi();
  return state;
}
async function saveBackendPersonalizationState(raw, opts={}){
  const scopeEmail = normalizeAccountScopeEmail(currentAccountEmail || '');
  if(!scopeEmail || authKickRedirecting) return null;
  const seq = ++PERSONALIZATION_BACKEND_SAVE_SEQ;
  const body = JSON.stringify({ state: buildPersonalizationStateForServer(raw) });
  const res = await fetch('/api3/personalization/memory', {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body,
    cache:'no-store',
    credentials:'same-origin',
  });
  const data = await res.json().catch(()=>({}));
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || personalizationMemoryT('account.session_expired', null, 'Your session has expired. Sign in again.'))) return null;
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  if(seq !== PERSONALIZATION_BACKEND_SAVE_SEQ) return normalizePersonalizationState(data?.state || raw || {});
  if(normalizeAccountScopeEmail(currentAccountEmail || '') !== scopeEmail) return normalizePersonalizationState(data?.state || raw || {});
  const state = normalizePersonalizationState(data?.state || raw || {});
  store.personalization = state;
  PERSONALIZATION_BACKEND_LOADED_EMAIL = scopeEmail;
  if(opts.persist !== false){
    try{ if(opts.immediate) saveStore(); else saveStoreThrottled(); }catch(_){ }
  }
  if(opts.render) renderPersonalizationUi();
  return state;
}
function syncBackendPersonalizationState(raw, opts={}){
  if(!isBackendPersonalizationActive()) return;
  saveBackendPersonalizationState(raw, opts).catch(err=>{
    console.warn('sync backend personalization failed:', err);
  });
}
function commitPersonalizationState(next, opts={}){
  const normalized = normalizePersonalizationState(next);
  store.personalization = normalized;
  if(opts.persist !== false){
    if(opts.immediate) saveStore();
    else saveStoreThrottled();
  }
  if(opts.syncBackend !== false) syncBackendPersonalizationState(normalized, { immediate:!!opts.immediate, persist:false, render:false });
  return normalized;
}
async function commitPersonalizationStateAndWait(next, opts={}){
  const normalized = normalizePersonalizationState(next);
  if(opts.syncBackend !== false && isBackendPersonalizationActive()){
    try{
      const saved = await saveBackendPersonalizationState(normalized, { immediate:!!opts.immediate, persist:opts.persist !== false, render:false });
      return saved || getPersonalizationState();
    }catch(err){
      console.warn('sync backend personalization failed:', err);
      throw err;
    }
  }
  store.personalization = normalized;
  if(opts.persist !== false){
    if(opts.immediate) saveStore();
    else saveStoreThrottled();
  }
  return normalized;
}
let PERSONALIZATION_MEMORY_EDITOR_OPEN = false;
let PERSONALIZATION_MEMORY_SEARCH_QUERY = '';
let PERSONALIZATION_MEMORY_SORT_ASC = false;
let PERSONALIZATION_MEMORY_HISTORY = [];
let PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID = '';
let PERSONALIZATION_MEMORY_HISTORY_LOADING = false;
let _personalizationMemoryRenderSeq = 0;
function setPersonalizationMemoryMoreOpen(open){
  const wrap = document.querySelector('.memory-modal-more-wrap');
  const menu = document.getElementById('personalizationMemoryMoreMenu');
  const btn = document.getElementById('personalizationMemoryMoreBtn');
  const shouldOpen = !!open;
  if(wrap) wrap.classList.toggle('open', shouldOpen);
  if(menu) menu.hidden = !shouldOpen;
  if(btn) btn.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
}
function setPersonalizationMemorySortOpen(open){
  const wrap = document.querySelector('.memory-modal-sort-wrap');
  const menu = document.getElementById('personalizationMemorySortMenu');
  const btn = document.getElementById('personalizationMemoryModalSortBtn');
  const shouldOpen = !!open;
  if(wrap) wrap.classList.toggle('open', shouldOpen);
  if(menu) menu.hidden = !shouldOpen;
  if(btn) btn.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
}
function updatePersonalizationMemorySortUi(){
  const descBtn = document.getElementById('personalizationMemorySortDescBtn');
  const ascBtn = document.getElementById('personalizationMemorySortAscBtn');
  const sortBtn = document.getElementById('personalizationMemoryModalSortBtn');
  if(descBtn) descBtn.setAttribute('aria-checked', PERSONALIZATION_MEMORY_SORT_ASC ? 'false' : 'true');
  if(ascBtn) ascBtn.setAttribute('aria-checked', PERSONALIZATION_MEMORY_SORT_ASC ? 'true' : 'false');
  if(sortBtn) sortBtn.title = personalizationMemoryT(
    PERSONALIZATION_MEMORY_SORT_ASC ? 'memory.sort_oldest' : 'memory.sort_newest',
    null,
    PERSONALIZATION_MEMORY_SORT_ASC ? 'Oldest first' : 'Newest first',
  );
}
function setPersonalizationMemorySortMode(ascending){
  PERSONALIZATION_MEMORY_SORT_ASC = !!ascending;
  updatePersonalizationMemorySortUi();
  setPersonalizationMemorySortOpen(false);
  renderPersonalizationMemoryList(getPersonalizationState());
}
function setPersonalizationMemoryHistoryMoreOpen(open){
  const wrap = document.querySelector('.memory-history-detail-actions');
  const menu = document.getElementById('personalizationMemoryHistoryActionMenu');
  const btn = document.getElementById('personalizationMemoryHistoryMoreBtn');
  const shouldOpen = !!open;
  if(wrap) wrap.classList.toggle('open', shouldOpen);
  if(menu) menu.hidden = !shouldOpen;
  if(btn) btn.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
}
function normalizePersonalizationMemoryHistoryEntry(raw){
  const row = raw && typeof raw === 'object' ? raw : {};
  const rawItems = Array.isArray(row.memoryItems) ? row.memoryItems : [];
  const items = rawItems.map((item, idx)=>normalizeMemoryItem(item, idx)).filter(Boolean);
  let createdTs = Number(row.created_ts || row.createdTs || 0) || 0;
  if(!createdTs){
    const seconds = Number(row.created_at || row.createdAt || 0) || 0;
    if(seconds > 0) createdTs = seconds > 100000000000 ? seconds : Math.round(seconds * 1000);
  }
  return {
    id: String(row.id || row.history_id || '').trim(),
    created_ts: createdTs,
    created_at_text: String(row.created_at_text || '').trim(),
    action: String(row.action || '').trim().toLowerCase() || 'update',
    before_count: Math.max(0, Number(row.before_count ?? row.beforeCount ?? items.length) || 0),
    after_count: Math.max(0, Number(row.after_count ?? row.afterCount ?? row.count ?? items.length) || 0),
    change_count: Math.max(0, Number(row.change_count ?? row.changeCount ?? 0) || 0),
    count: Number(row.count || items.length) || items.length,
    memoryItems: items,
  };
}
function formatPersonalizationMemoryHistoryTime(ts){
  const value = Number(ts || 0) || 0;
  if(!value) return personalizationMemoryT('memory.history_unknown_time', null, 'Unknown time');
  const d = new Date(value);
  const locale = window.AperviaI18n?.language === 'zh-CN' ? 'zh-CN' : 'en-US';
  try{
    return new Intl.DateTimeFormat(locale, {
      month:locale === 'zh-CN' ? 'numeric' : 'short',
      day:'numeric',
      hour:'2-digit',
      minute:'2-digit',
      hour12:false,
    }).format(d);
  }catch(_){
    return d.toISOString().slice(5, 16).replace('T', ' ');
  }
}
function personalizationMemoryHistorySummary(row, index, rows){
  const action = String(row?.action || 'update').trim().toLowerCase();
  const total = Math.max(0, Number(row?.after_count ?? row?.count ?? row?.memoryItems?.length ?? 0) || 0);
  const older = Array.isArray(rows) ? rows[index + 1] : null;
  const storedBefore = Number(row?.before_count);
  const olderCount = Number(older?.after_count ?? older?.count ?? older?.memoryItems?.length);
  const before = Number.isFinite(storedBefore) && (storedBefore !== total || Number(row?.change_count) > 0)
    ? Math.max(0, storedBefore)
    : (Number.isFinite(olderCount) ? Math.max(0, olderCount) : total);
  const storedChange = Math.max(0, Number(row?.change_count) || 0);
  const change = storedChange || Math.abs(total - before) || (['add', 'delete'].includes(action) ? 1 : 0);
  const key = {
    add:'memory.history_summary_add',
    delete:'memory.history_summary_delete',
    clear:'memory.history_summary_clear',
    restore:'memory.history_summary_restore',
    update:'memory.history_summary_update',
  }[action] || 'memory.history_summary_saved';
  const fallback = {
    add:`Added ${change} · ${total} total`,
    delete:`Deleted ${change} · ${total} remaining`,
    clear:`Cleared ${change} · ${total} remaining`,
    restore:`Restored · ${total} total`,
    update:`Updated · ${total} total`,
  }[action] || `Saved · ${total} total`;
  return personalizationMemoryT(key, {change, count:total}, fallback);
}
function currentPersonalizationMemoryHistorySelection(){
  return PERSONALIZATION_MEMORY_HISTORY.find(x => String(x.id || '') === String(PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID || '')) || PERSONALIZATION_MEMORY_HISTORY[0] || null;
}
async function fetchPersonalizationMemoryHistory(){
  if(!isBackendPersonalizationActive()){
    PERSONALIZATION_MEMORY_HISTORY = [];
    return [];
  }
  PERSONALIZATION_MEMORY_HISTORY_LOADING = true;
  try{
    const res = await fetch('/api3/personalization/memory/history', { cache:'no-store', credentials:'same-origin' });
    const data = await res.json().catch(()=>({}));
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || personalizationMemoryT('account.session_expired', null, 'Your session has expired. Sign in again.'))) return [];
    if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
    const rows = Array.isArray(data?.history) ? data.history : [];
    PERSONALIZATION_MEMORY_HISTORY = rows.map(normalizePersonalizationMemoryHistoryEntry).filter(x=>x.id);
    if(!PERSONALIZATION_MEMORY_HISTORY.find(x=>x.id === PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID)){
      PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID = PERSONALIZATION_MEMORY_HISTORY[0]?.id || '';
    }
    return PERSONALIZATION_MEMORY_HISTORY;
  }finally{
    PERSONALIZATION_MEMORY_HISTORY_LOADING = false;
  }
}
function renderPersonalizationMemoryHistoryModal(){
  const listEl = document.getElementById('personalizationMemoryHistoryList');
  const emptyEl = document.getElementById('personalizationMemoryHistoryEmpty');
  const titleEl = document.getElementById('personalizationMemoryHistoryDetailTitle');
  const metaEl = document.getElementById('personalizationMemoryHistoryDetailMeta');
  const snapshotEl = document.getElementById('personalizationMemoryHistorySnapshot');
  const moreBtn = document.getElementById('personalizationMemoryHistoryMoreBtn');
  if(!listEl || !emptyEl || !titleEl || !metaEl || !snapshotEl) return;
  listEl.innerHTML = '';
  const rows = Array.isArray(PERSONALIZATION_MEMORY_HISTORY) ? PERSONALIZATION_MEMORY_HISTORY : [];
  emptyEl.hidden = rows.length > 0 || PERSONALIZATION_MEMORY_HISTORY_LOADING;
  if(PERSONALIZATION_MEMORY_HISTORY_LOADING && !rows.length){
    emptyEl.hidden = true;
    if(typeof AppLoadingUi !== 'undefined'){
      AppLoadingUi.render(listEl, { variant:'compact-list', rows:5, label:personalizationMemoryT('memory.history_loading', null, 'Loading memory history') });
      AppLoadingUi.render(snapshotEl, { variant:'list', rows:4, label:personalizationMemoryT('memory.history_detail_loading', null, 'Loading memory details') });
    }else{
      emptyEl.hidden = false;
      emptyEl.textContent = personalizationMemoryT('common.loading', null, 'Loading…');
    }
    if(moreBtn) moreBtn.disabled = true;
    return;
  }else if(!rows.length){
    emptyEl.textContent = personalizationMemoryT('memory.history_none', null, 'No history.');
  }
  if(typeof AppLoadingUi !== 'undefined'){
    AppLoadingUi.ready(listEl);
    AppLoadingUi.ready(snapshotEl);
  }
  rows.forEach((row, index)=>{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'memory-history-version' + (String(row.id || '') === String(PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID || '') ? ' active' : '');
    btn.innerHTML = `<strong>${escapeHtml(formatPersonalizationMemoryHistoryTime(row.created_ts))}</strong><span>${escapeHtml(personalizationMemoryHistorySummary(row, index, rows))}</span>`;
    btn.addEventListener('click', ()=>{
      PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID = String(row.id || '');
      setPersonalizationMemoryHistoryMoreOpen(false);
      renderPersonalizationMemoryHistoryModal();
    });
    listEl.appendChild(btn);
  });
  const selected = currentPersonalizationMemoryHistorySelection();
  if(!selected){
    titleEl.textContent = personalizationMemoryT('memory.history_select', null, 'Select a version');
    metaEl.textContent = '';
    snapshotEl.innerHTML = `<div class="memory-history-placeholder">${escapeHtml(personalizationMemoryT('memory.history_empty', null, 'No history versions are available.'))}</div>`;
    if(moreBtn) moreBtn.disabled = true;
    setPersonalizationMemoryHistoryMoreOpen(false);
    return;
  }
  if(moreBtn) moreBtn.disabled = false;
  titleEl.textContent = formatPersonalizationMemoryHistoryTime(selected.created_ts);
  const selectedIndex = Math.max(0, rows.findIndex(row => String(row.id || '') === String(selected.id || '')));
  metaEl.textContent = personalizationMemoryHistorySummary(selected, selectedIndex, rows);
  snapshotEl.innerHTML = '';
  const items = Array.isArray(selected.memoryItems) ? selected.memoryItems : [];
  if(!items.length){
    snapshotEl.innerHTML = `<div class="memory-history-placeholder">${escapeHtml(personalizationMemoryT('memory.history_snapshot_empty', null, 'This version has no saved memories.'))}</div>`;
    return;
  }
  const frag = document.createDocumentFragment();
  items.forEach((item)=>{
    const card = document.createElement('div');
    card.className = 'memory-history-snapshot-item';
    const text = document.createElement('div');
    text.className = 'memory-history-snapshot-text';
    text.textContent = String(item.text || '').trim();
    card.appendChild(text);
    frag.appendChild(card);
  });
  snapshotEl.appendChild(frag);
}
async function setPersonalizationMemoryHistoryModalOpen(open){
  const modal = document.getElementById('personalizationMemoryHistoryModal');
  if(!modal) return;
  const shouldOpen = !!open;
  modal.classList.toggle('open', shouldOpen);
  modal.toggleAttribute('inert', !shouldOpen);
  modal.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
  setPersonalizationMemoryHistoryMoreOpen(false);
  if(!shouldOpen) return;
  renderPersonalizationMemoryHistoryModal();
  try{
    await fetchPersonalizationMemoryHistory();
  }catch(err){
    try{ toast(personalizationMemoryT('memory.history_load_failed', {error:err?.message || err}, `Unable to load memory history: ${err?.message || err}`)); }catch(_){ }
  }
  renderPersonalizationMemoryHistoryModal();
}
async function restorePersonalizationMemoryHistoryVersion(){
  const selected = currentPersonalizationMemoryHistorySelection();
  if(!selected) return;
  setPersonalizationMemoryHistoryMoreOpen(false);
  const ok = await askKbDangerConfirm({
    title:personalizationMemoryT('memory.restore_title', null, 'Restore this version?'),
    desc:personalizationMemoryT('memory.restore_desc', null, 'This will replace the currently saved memories.'),
    confirmText:personalizationMemoryT('memory.restore', null, 'Restore'),
    cancelText:personalizationMemoryT('common.cancel', null, 'Cancel'),
  }, document.getElementById('personalizationMemoryHistoryRestoreBtn'));
  if(!ok) return;
  try{
    const res = await fetch('/api3/personalization/memory/history/restore', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body:JSON.stringify({ id:selected.id }),
      cache:'no-store',
      credentials:'same-origin',
    });
    const data = await res.json().catch(()=>({}));
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || personalizationMemoryT('account.session_expired', null, 'Your session has expired. Sign in again.'))) return;
    if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
    if(data?.state){
      store.personalization = normalizePersonalizationState(data.state);
      try{ saveStoreThrottled(); }catch(_){ }
    }
    PERSONALIZATION_MEMORY_HISTORY = (Array.isArray(data?.history) ? data.history : []).map(normalizePersonalizationMemoryHistoryEntry).filter(x=>x.id);
    PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID = PERSONALIZATION_MEMORY_HISTORY[0]?.id || selected.id || '';
    renderPersonalizationUi();
    renderPersonalizationMemoryHistoryModal();
    try{ toast(personalizationMemoryT('memory.restored', null, 'Version restored')); }catch(_){ }
  }catch(err){
    try{ toast(personalizationMemoryT('memory.restore_failed', {error:err?.message || err}, `Unable to restore this version: ${err?.message || err}`)); }catch(_){ }
  }
}
async function deletePersonalizationMemoryHistoryVersion(){
  const selected = currentPersonalizationMemoryHistorySelection();
  if(!selected) return;
  setPersonalizationMemoryHistoryMoreOpen(false);
  const ok = await askKbDangerConfirm({
    title:personalizationMemoryT('memory.delete_version_title', null, 'Delete this version?'),
    desc:personalizationMemoryT('memory.delete_version_desc', null, 'This cannot be undone.'),
    confirmText:personalizationMemoryT('common.delete', null, 'Delete'),
    cancelText:personalizationMemoryT('common.cancel', null, 'Cancel'),
  }, document.getElementById('personalizationMemoryHistoryDeleteBtn'));
  if(!ok) return;
  try{
    const res = await fetch('/api3/personalization/memory/history/delete', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body:JSON.stringify({ id:selected.id }),
      cache:'no-store',
      credentials:'same-origin',
    });
    const data = await res.json().catch(()=>({}));
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || personalizationMemoryT('account.session_expired', null, 'Your session has expired. Sign in again.'))) return;
    if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
    PERSONALIZATION_MEMORY_HISTORY = (Array.isArray(data?.history) ? data.history : []).map(normalizePersonalizationMemoryHistoryEntry).filter(x=>x.id);
    PERSONALIZATION_MEMORY_HISTORY_SELECTED_ID = PERSONALIZATION_MEMORY_HISTORY[0]?.id || '';
    renderPersonalizationMemoryHistoryModal();
    try{ toast(personalizationMemoryT('memory.version_deleted', null, 'Version deleted')); }catch(_){ }
  }catch(err){
    try{ toast(personalizationMemoryT('memory.delete_failed', {error:err?.message || err}, `Delete failed: ${err?.message || err}`)); }catch(_){ }
  }
}
function setPersonalizationEditorVisible(visible, opts={}){
  const mask = document.getElementById('personalizationMemoryEditorMask');
  const wrap = document.getElementById('personalizationMemoryEditorWrap');
  const titleEl = document.getElementById('personalizationMemoryEditorTitle');
  const addBtn = document.getElementById('personalizationMemoryAddBtn');
  const shouldOpen = !!visible;
  PERSONALIZATION_MEMORY_EDITOR_OPEN = shouldOpen;
  if(mask){
    mask.hidden = !shouldOpen;
    mask.classList.toggle('open', shouldOpen);
  }
  if(wrap) wrap.hidden = !shouldOpen;
  if(titleEl) titleEl.textContent = opts.mode === 'edit'
    ? personalizationMemoryT('memory.edit_title', null, 'Edit memory')
    : personalizationMemoryT('memory.add_title', null, 'Add memory');
  if(addBtn) addBtn.textContent = opts.mode === 'edit'
    ? personalizationMemoryT('common.save', null, 'Save')
    : personalizationMemoryT('memory.add', null, 'Add');
}

function readPersonalizationFormState(){
  const current = clonePersonalizationState();
  const previousMemoryEnabled = !!current.memoryEnabled;
  const nextMemoryEnabled = !!document.getElementById('personalizationMemoryEnabled')?.checked;
  current.memoryEnabled = nextMemoryEnabled;
  const autoManageEl = document.getElementById('personalizationMemoryAutoManageEnabled');
  current.memoryAutoManageEnabled = autoManageEl ? !!autoManageEl.checked : current.memoryAutoManageEnabled !== false;
  const historyEnabledEl = document.getElementById('personalizationHistoryReferenceEnabled');
  if(historyEnabledEl){
    if(!nextMemoryEnabled || !previousMemoryEnabled) current.historyReferenceEnabled = current.historyReferenceEnabled !== false;
    else current.historyReferenceEnabled = !!historyEnabledEl.checked;
  }else{
    current.historyReferenceEnabled = current.historyReferenceEnabled !== false;
  }
  current.customInstruction = _memoryTrim(document.getElementById('personalizationCustomInstruction')?.value || '', PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_TEXT);
  current.profileNickname = _memoryTrim(document.getElementById('personalizationProfileNickname')?.value || '', 120);
  current.profileOccupation = _memoryTrim(document.getElementById('personalizationProfileOccupation')?.value || '', 180);
  current.profileDetails = _memoryTrim(document.getElementById('personalizationProfileDetails')?.value || '', 700);
  current.customAboutUser = '';
  current.customResponseStyle = '';
  current.memoryInstruction = _memoryTrim(document.getElementById('personalizationMemoryInstruction')?.value || '', 1800);
  current.responseStylePreset = document.getElementById('personalizationResponseStylePreset')?.value || '';
  current.structurePreference = document.getElementById('personalizationStructurePreference')?.value || '';
  current.emojiPreference = document.getElementById('personalizationEmojiPreference')?.value || '';
  return normalizePersonalizationState(current);
}
function resetPersonalizationEditor(opts={}){
  const editor = document.getElementById('personalizationMemoryEditor');
  const note = document.getElementById('personalizationMemoryEditorNote');
  if(editor){
    if(opts.clear !== false) editor.value = '';
    delete editor.dataset.editId;
  }
  if(note) note.textContent = personalizationMemoryT('memory.editor_note', null, 'Only add information that remains useful over time.');
  setPersonalizationEditorVisible(false, { mode:'add' });
}
function formatPersonalizationMemoryTime(ts){
  const value = Number(ts || 0) || 0;
  if(!value) return personalizationMemoryT('memory.just_now', null, 'Just now');
  const diffMs = Math.max(0, Date.now() - value);
  const diffMin = Math.floor(diffMs / 60000);
  if(diffMin < 1) return personalizationMemoryT('memory.just_now', null, 'Just now');
  if(diffMin < 60) return personalizationMemoryT('memory.minutes_ago', {count:diffMin}, `${diffMin} min ago`);
  const diffHour = Math.floor(diffMin / 60);
  if(diffHour < 24) return personalizationMemoryT('memory.hours_ago', {count:diffHour}, `${diffHour} hr ago`);
  const date = new Date(value);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${month}-${day}`;
}
function updatePersonalizationSummary(state=getPersonalizationState()){
  const badge = document.getElementById('personalizationMemoryBadge');
  const countEl = document.getElementById('personalizationMemoryCount');
  const statusText = document.getElementById('personalizationMemoryStatusText');
  const modalCount = document.getElementById('personalizationMemoryModalCount');
  const modalStatus = document.getElementById('personalizationMemoryModalStatus');
  const autoManageBadge = document.getElementById('personalizationMemoryAutoManageBadge');
  const historyBadge = document.getElementById('personalizationHistoryReferenceBadge');
  const customBadge = document.getElementById('personalizationCustomInstructionBadge');
  const expressionBadge = document.getElementById('personalizationExpressionPreferenceBadge');
  const customSummary = document.getElementById('personalizationCustomInstructionSummary');
  const items = Array.isArray(state?.memoryItems) ? state.memoryItems : [];
  const enabled = !!state?.memoryEnabled;
  const autoManageEnabled = state?.memoryAutoManageEnabled !== false;
  const historyEnabled = !!state?.memoryEnabled && state?.historyReferenceEnabled !== false;
  const hasCustomInstructions = !!String(state?.customInstruction || '').trim();
  const hasExpressionPreference = !!personalizationExpressionPreferenceLine(state);
  if(badge) badge.textContent = personalizationMemoryT(enabled ? 'common.on' : 'common.off', null, enabled ? 'On' : 'Off');
  if(autoManageBadge) autoManageBadge.textContent = personalizationMemoryT(autoManageEnabled ? 'common.on' : 'common.off', null, autoManageEnabled ? 'On' : 'Off');
  if(historyBadge) historyBadge.textContent = personalizationMemoryT(historyEnabled ? 'common.on' : 'common.off', null, historyEnabled ? 'On' : 'Off');
  if(customBadge) customBadge.textContent = hasCustomInstructions
    ? personalizationMemoryT('personalization.configured', null, 'Configured')
    : personalizationMemoryT('personalization.not_set', null, 'Not set');
  if(expressionBadge) expressionBadge.textContent = hasExpressionPreference
    ? personalizationMemoryT('personalization.configured', null, 'Configured')
    : personalizationMemoryT('personalization.default', null, 'Default');
  if(customSummary){
    const instruction = String(state?.customInstruction || '').trim();
    customSummary.textContent = hasCustomInstructions
      ? instruction.slice(0, 80)
      : personalizationMemoryT('personalization.custom_instructions_summary', null, 'Behavior, style, and tone preferences');
    customSummary.classList.toggle('is-placeholder', !hasCustomInstructions);
  }
  const countKey = items.length === 1 ? 'memory.count_one' : 'memory.count';
  const countFallback = items.length === 1 ? '1 item' : `${items.length} items`;
  if(countEl) countEl.textContent = personalizationMemoryT(countKey, {count:items.length}, countFallback);
  if(statusText) statusText.textContent = personalizationMemoryT(enabled ? 'common.on' : 'common.off', null, enabled ? 'On' : 'Off');
  if(modalCount) modalCount.textContent = personalizationMemoryT(countKey, {count:items.length}, countFallback);
  if(modalStatus) modalStatus.textContent = personalizationMemoryT(enabled ? 'common.on' : 'common.off', null, enabled ? 'On' : 'Off');
  updatePersonalizationMemorySortUi();
}
function renderPersonalizationMemoryPreview(state=getPersonalizationState()){
  const previewEl = document.getElementById('personalizationMemoryPreview');
  const emptyInlineEl = document.getElementById('personalizationMemoryEmptyInline');
  if(!previewEl || !emptyInlineEl) return;
  previewEl.innerHTML = '';
  const items = Array.isArray(state?.memoryItems) ? state.memoryItems : [];
  emptyInlineEl.hidden = items.length > 0;
  if(!items.length) return;
  items.slice(0, 3).forEach((item, idx) => {
    const row = document.createElement('div');
    row.className = 'personalization-memory-preview-item';
    const textEl = document.createElement('div');
    textEl.className = 'personalization-memory-preview-text';
    textEl.textContent = `${idx + 1}. ${String(item.text || '').trim()}`;
    const metaEl = document.createElement('div');
    metaEl.className = 'personalization-memory-preview-meta';
    metaEl.textContent = formatPersonalizationMemoryTime(item.updatedAt || item.createdAt || 0);
    row.appendChild(textEl);
    row.appendChild(metaEl);
    previewEl.appendChild(row);
  });
}
function renderPersonalizationMemoryList(state=getPersonalizationState()){
  const listEl = document.getElementById('personalizationMemoryList');
  const emptyEl = document.getElementById('personalizationMemoryEmpty');
  if(!listEl || !emptyEl) return;
  const seq = ++_personalizationMemoryRenderSeq;
  listEl.innerHTML = '';
  const rawItems = Array.isArray(state?.memoryItems) ? state.memoryItems : [];
  const query = String(PERSONALIZATION_MEMORY_SEARCH_QUERY || '').trim().toLowerCase();
  const items = rawItems
    .filter(item => !query || String(item?.text || '').toLowerCase().includes(query))
    .slice()
    .sort((a, b)=>{
      const av = Number(a?.updatedAt || a?.createdAt || 0) || 0;
      const bv = Number(b?.updatedAt || b?.createdAt || 0) || 0;
      return PERSONALIZATION_MEMORY_SORT_ASC ? av - bv : bv - av;
    });
  emptyEl.hidden = items.length > 0;
  if(!items.length){
    emptyEl.textContent = query
      ? personalizationMemoryT('memory.no_match', null, 'No matching memories')
      : personalizationMemoryT('memory.available_hint', null, 'Memories available to the language model appear here.');
    return;
  }
  const isVisible = () => {
    if(seq !== _personalizationMemoryRenderSeq) return false;
    const memoryModalOpen = !!document.getElementById('personalizationMemoryModal')?.classList.contains('open');
    const personalizationPanelOpen = isSettingsModalOpen() && settingsActiveTab === 'personalization';
    return memoryModalOpen || personalizationPanelOpen;
  };
  let index = 0;
  const appendBatch = () => {
    if(!isVisible()) return;
    const frag = document.createDocumentFragment();
    const end = Math.min(index + 36, items.length);
    for(; index < end; index++){
      const item = items[index];
      const row = document.createElement('div');
      row.className = 'personalization-memory-item';

      const content = document.createElement('div');
      content.className = 'personalization-memory-content';

      const textEl = document.createElement('div');
      textEl.className = 'personalization-memory-text';
      textEl.textContent = String(item.text || '').trim();

      const metaEl = document.createElement('div');
      metaEl.className = 'personalization-memory-meta';
      metaEl.textContent = formatPersonalizationMemoryTime(item.updatedAt || item.createdAt || 0);

      content.appendChild(textEl);
      content.appendChild(metaEl);

      const actions = document.createElement('div');
      actions.className = 'personalization-memory-actions';

      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.textContent = personalizationMemoryT('memory.edit', null, 'Edit');
      editBtn.addEventListener('click', ()=>{
        setPersonalizationMemoryModalOpen(true, { focusEditor:true, mode:'edit' });
        const editor = document.getElementById('personalizationMemoryEditor');
        const note = document.getElementById('personalizationMemoryEditorNote');
        if(editor){
          editor.value = String(item.text || '');
          editor.dataset.editId = String(item.id || '');
        }
        if(note) note.textContent = personalizationMemoryT('memory.editing_note', null, 'Editing. Saving will replace the existing content.');
      });

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
    deleteBtn.textContent = personalizationMemoryT('common.delete', null, 'Delete');
      deleteBtn.addEventListener('click', async ()=>{
        const ok = await askKbDangerConfirm({
          title:personalizationMemoryT('memory.delete_item_title', null, 'Delete this memory?'),
          desc:personalizationMemoryT('memory.delete_item_desc', null, 'This memory cannot be recovered after deletion.'),
          confirmText:personalizationMemoryT('common.confirm', null, 'Confirm'),
          cancelText:personalizationMemoryT('common.cancel', null, 'Cancel'),
        }, deleteBtn);
        if(!ok) return;
        const next = readPersonalizationFormState();
        next.memoryItems = next.memoryItems.filter(entry => String(entry.id || '') !== String(item.id || ''));
        try{
          await commitPersonalizationStateAndWait(next, { immediate:true });
          renderPersonalizationUi();
          if(document.getElementById('personalizationMemoryHistoryModal')?.classList.contains('open')){
            try{ await fetchPersonalizationMemoryHistory(); renderPersonalizationMemoryHistoryModal(); }catch(_){ }
          }
          try{ toast(personalizationMemoryT('memory.deleted', null, 'Deleted')); }catch(_){ }
        }catch(err){
          renderPersonalizationUi();
          try{ toast(err?.message || personalizationMemoryT('common.operation_failed', null, 'Operation failed')); }catch(_){ }
        }
      });

      actions.appendChild(editBtn);
      actions.appendChild(deleteBtn);
      row.appendChild(content);
      row.appendChild(actions);
      frag.appendChild(row);
    }
    listEl.appendChild(frag);
    if(index < items.length) scheduleUiAfterPaint(appendBatch);
  };
  appendBatch();
}
function renderPersonalizationUi(){
  const state = getPersonalizationState();
  const enabledEl = document.getElementById('personalizationMemoryEnabled');
  const autoManageEl = document.getElementById('personalizationMemoryAutoManageEnabled');
  const historyEnabledEl = document.getElementById('personalizationHistoryReferenceEnabled');
  const customInstructionEl = document.getElementById('personalizationCustomInstruction');
  const responseStyleEl = document.getElementById('personalizationResponseStylePreset');
  const structureEl = document.getElementById('personalizationStructurePreference');
  const emojiEl = document.getElementById('personalizationEmojiPreference');
  const nicknameEl = document.getElementById('personalizationProfileNickname');
  const occupationEl = document.getElementById('personalizationProfileOccupation');
  const detailsEl = document.getElementById('personalizationProfileDetails');
  const instructionEl = document.getElementById('personalizationMemoryInstruction');
  if(enabledEl) enabledEl.checked = !!state.memoryEnabled;
  if(autoManageEl) autoManageEl.checked = state.memoryAutoManageEnabled !== false;
  if(historyEnabledEl){
    historyEnabledEl.checked = !!state.memoryEnabled && state.historyReferenceEnabled !== false;
    historyEnabledEl.disabled = !state.memoryEnabled;
    historyEnabledEl.title = state.memoryEnabled
      ? personalizationMemoryT('personalization.history_reference_title', null, 'Reference chat history')
      : personalizationMemoryT('personalization.history_reference_disabled_title', null, 'Enable saved-memory reference first');
  }
  if(customInstructionEl && document.activeElement !== customInstructionEl) customInstructionEl.value = String(state.customInstruction || '');
  if(responseStyleEl && document.activeElement !== responseStyleEl) responseStyleEl.value = String(state.responseStylePreset || '');
  if(structureEl && document.activeElement !== structureEl) structureEl.value = String(state.structurePreference || '');
  if(emojiEl && document.activeElement !== emojiEl) emojiEl.value = String(state.emojiPreference || '');
  if(nicknameEl && document.activeElement !== nicknameEl) nicknameEl.value = String(state.profileNickname || '');
  if(occupationEl && document.activeElement !== occupationEl) occupationEl.value = String(state.profileOccupation || '');
  if(detailsEl && document.activeElement !== detailsEl) detailsEl.value = String(state.profileDetails || '');
  if(instructionEl) instructionEl.value = String(state.memoryInstruction || '');
  refreshPersonalizationAboutTextareaScroll();
  try{ requestAnimationFrame(refreshPersonalizationAboutTextareaScroll); }catch(_){ }
  const searchEl = document.getElementById('personalizationMemorySearchInput');
  if(searchEl && document.activeElement !== searchEl) searchEl.value = PERSONALIZATION_MEMORY_SEARCH_QUERY;
  updatePersonalizationSummary(state);
  renderPersonalizationMemoryPreview(state);
  renderPersonalizationMemoryList(state);
  resetPersonalizationEditor({ clear:false });
  refreshSettingsDraftActions();
}
async function savePersonalizationSettings(opts={}){
  try{
    const next = readPersonalizationFormState();
    if(opts.syncBackend === false || !isBackendPersonalizationActive()){
      const normalized = commitPersonalizationState(next, { immediate:!!opts.immediate, syncBackend:false });
      renderPersonalizationUi();
      return normalized;
    }
    const saved = await commitPersonalizationStateAndWait(next, { immediate:!!opts.immediate });
    renderPersonalizationUi();
    return saved;
  }catch(err){
    renderPersonalizationUi();
    if(opts.throwOnError) throw err;
    console.warn('save personalization failed:', err);
    try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
    return getPersonalizationState();
  }
}
async function upsertPersonalizationMemoryFromEditor(){
  const editor = document.getElementById('personalizationMemoryEditor');
  if(!editor) return;
  const text = _memoryTrim(editor.value || '');
  if(!text){
    try{ toast(personalizationMemoryT('memory.enter_required', null, 'Enter a memory to save first.')); }catch(_){ }
    editor.focus();
    return;
  }
  const editId = String(editor.dataset.editId || '').trim();
  const next = readPersonalizationFormState();
  const nowTs = now();
  let replaced = false;
  next.memoryItems = (Array.isArray(next.memoryItems) ? next.memoryItems : []).map((item)=>{
    const normalized = normalizeMemoryItem(item);
    if(!normalized) return null;
    if(editId && String(normalized.id || '') === editId){
      replaced = true;
      return normalizeMemoryItem({ ...normalized, text, updatedAt: nowTs }, 0);
    }
    return normalized;
  }).filter(Boolean);
  if(!replaced){
    next.memoryItems.unshift(normalizeMemoryItem({ text, createdAt: nowTs, updatedAt: nowTs }, 0));
  }
  next.memoryItems = normalizePersonalizationState(next).memoryItems;
  try{
    await commitPersonalizationStateAndWait(next, { immediate:true });
    renderPersonalizationUi();
    if(document.getElementById('personalizationMemoryHistoryModal')?.classList.contains('open')){
      try{ await fetchPersonalizationMemoryHistory(); renderPersonalizationMemoryHistoryModal(); }catch(_){ }
    }
    resetPersonalizationEditor({ clear:true });
    try{ toast(personalizationMemoryT(replaced ? 'memory.updated' : 'memory.added', null, replaced ? 'Memory updated' : 'Memory added')); }catch(_){ }
  }catch(err){
    renderPersonalizationUi();
    try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
  }
}

function setPersonalizationMemoryModalOpen(open, opts={}){
  const modal = document.getElementById('personalizationMemoryModal');
  if(!modal) return;
  const shouldOpen = !!open;
  modal.classList.toggle('open', shouldOpen);
  modal.toggleAttribute('inert', !shouldOpen);
  modal.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
  if(shouldOpen){
    setPersonalizationMemoryMoreOpen(false);
    setPersonalizationMemorySortOpen(false);
    if(opts.focusEditor){
      renderPersonalizationUi();
      setPersonalizationEditorVisible(true, { mode: opts.mode === 'edit' ? 'edit' : 'add' });
      requestAnimationFrame(()=> document.getElementById('personalizationMemoryEditor')?.focus());
    }else{
      setPersonalizationEditorVisible(false, { mode:'add' });
      schedulePersonalizationUiHydration({ refreshBackend:true });
    }
  }else{
    setPersonalizationMemoryMoreOpen(false);
    setPersonalizationMemorySortOpen(false);
    resetPersonalizationEditor({ clear:false });
  }
}
function setPersonalizationCustomInstructionModalOpen(open){
  const modal = document.getElementById('personalizationCustomInstructionModal');
  if(!modal) return;
  const shouldOpen = !!open;
  modal.classList.toggle('open', shouldOpen);
  modal.toggleAttribute('inert', !shouldOpen);
  modal.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
  if(shouldOpen){
    schedulePersonalizationUiHydration({ refreshBackend:true, focusCustomInstruction:true });
  }
}

function personalizationDraftComparableFromState(raw){
  const state = normalizePersonalizationState(raw || {});
  return {
    customInstruction: _memoryTrim(state.customInstruction || '', PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_TEXT),
    profileNickname: _memoryTrim(state.profileNickname || '', 120),
    profileOccupation: _memoryTrim(state.profileOccupation || '', 180),
    profileDetails: _memoryTrim(state.profileDetails || '', 700),
    responseStylePreset: String(state.responseStylePreset || ''),
    structurePreference: String(state.structurePreference || ''),
    emojiPreference: String(state.emojiPreference || ''),
  };
}
function personalizationDraftComparableFromForm(){
  return {
    customInstruction: _memoryTrim(document.getElementById('personalizationCustomInstruction')?.value || '', PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_TEXT),
    profileNickname: _memoryTrim(document.getElementById('personalizationProfileNickname')?.value || '', 120),
    profileOccupation: _memoryTrim(document.getElementById('personalizationProfileOccupation')?.value || '', 180),
    profileDetails: _memoryTrim(document.getElementById('personalizationProfileDetails')?.value || '', 700),
    responseStylePreset: String(document.getElementById('personalizationResponseStylePreset')?.value || ''),
    structurePreference: String(document.getElementById('personalizationStructurePreference')?.value || ''),
    emojiPreference: String(document.getElementById('personalizationEmojiPreference')?.value || ''),
  };
}
function getPersonalizationAboutScrollParent(el){
  return el?.closest?.('.settings-tab-panel.active') || el?.closest?.('.settings-workspace') || null;
}
function redirectPersonalizationAboutScroll(el, deltaY){
  const parent = getPersonalizationAboutScrollParent(el);
  if(!parent || !Number.isFinite(deltaY) || Math.abs(deltaY) < 0.5) return false;
  const before = parent.scrollTop || 0;
  parent.scrollTop = before + deltaY;
  return Math.abs((parent.scrollTop || 0) - before) > 0.5;
}
function bindPersonalizationAboutTextareaScrollBridge(el){
  if(!el || el.dataset.personalizationScrollBridgeBound === '1') return;
  el.dataset.personalizationScrollBridgeBound = '1';
  let touchStartY = 0;
  el.addEventListener('wheel', (e)=>{
    const max = Math.max(0, (el.scrollHeight || 0) - (el.clientHeight || 0));
    const deltaY = Number(e.deltaY || 0);
    const atTop = (el.scrollTop || 0) <= 1;
    const atBottom = (el.scrollTop || 0) >= max - 1;
    const shouldPassToPanel = max <= 2 || (deltaY < 0 && atTop) || (deltaY > 0 && atBottom);
    if(shouldPassToPanel && redirectPersonalizationAboutScroll(el, deltaY)){
      e.preventDefault();
    }
  }, { passive:false });
  el.addEventListener('touchstart', (e)=>{
    touchStartY = Number(e.touches?.[0]?.clientY || 0);
  }, { passive:true });
  el.addEventListener('touchmove', (e)=>{
    const currentY = Number(e.touches?.[0]?.clientY || 0);
    const deltaY = touchStartY ? touchStartY - currentY : 0;
    if(Math.abs(deltaY) < 1) return;
    const max = Math.max(0, (el.scrollHeight || 0) - (el.clientHeight || 0));
    const atTop = (el.scrollTop || 0) <= 1;
    const atBottom = (el.scrollTop || 0) >= max - 1;
    const shouldPassToPanel = max <= 2 || (deltaY < 0 && atTop) || (deltaY > 0 && atBottom);
    if(shouldPassToPanel && redirectPersonalizationAboutScroll(el, deltaY)){
      touchStartY = currentY;
      e.preventDefault();
    }
  }, { passive:false });
}
function refreshPersonalizationAboutTextareaScroll(){
  ['personalizationProfileNickname','personalizationProfileOccupation','personalizationProfileDetails'].forEach((id)=>{
    const el = document.getElementById(id);
    if(!el) return;
    bindPersonalizationAboutTextareaScrollBridge(el);
    const canScroll = (el.scrollHeight - el.clientHeight) > 2;
    el.classList.toggle('has-inner-scroll', canScroll);
  });
}

function bindPersonalizationUi(){
  document.getElementById('personalizationSaveBtn')?.addEventListener('click', async ()=>{
    try{
      await savePersonalizationSettings({ immediate:true, throwOnError:true });
      try{ toast(personalizationMemoryT('memory.personalization_saved', null, 'Personalization settings saved')); }catch(_){ }
    }catch(err){
      try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
    }
  });
  document.getElementById('personalizationMemoryManageBtn')?.addEventListener('click', ()=> setPersonalizationMemoryModalOpen(true));
  document.getElementById('personalizationMemoryModalCloseBtn')?.addEventListener('click', ()=> setPersonalizationMemoryModalOpen(false));
  document.getElementById('personalizationMemoryModal')?.addEventListener('click', (e)=>{
    if(e.target === e.currentTarget) setPersonalizationMemoryModalOpen(false);
  });
  document.getElementById('personalizationMemoryEditorMask')?.addEventListener('click', (e)=>{
    if(e.target === e.currentTarget) resetPersonalizationEditor({ clear:true });
  });
  document.getElementById('personalizationMemoryModalAddFocusBtn')?.addEventListener('click', ()=>{
    resetPersonalizationEditor({ clear:true });
    setPersonalizationMemoryMoreOpen(false);
    setPersonalizationMemorySortOpen(false);
    setPersonalizationMemoryModalOpen(true, { focusEditor:true, mode:'add' });
  });
  document.getElementById('personalizationMemoryModalSortBtn')?.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    setPersonalizationMemoryMoreOpen(false);
    const menu = document.getElementById('personalizationMemorySortMenu');
    setPersonalizationMemorySortOpen(!!menu?.hidden);
  });
  document.getElementById('personalizationMemorySortMenu')?.addEventListener('click', (e)=>{
    e.stopPropagation();
  });
  document.getElementById('personalizationMemorySortDescBtn')?.addEventListener('click', ()=>{
    setPersonalizationMemorySortMode(false);
  });
  document.getElementById('personalizationMemorySortAscBtn')?.addEventListener('click', ()=>{
    setPersonalizationMemorySortMode(true);
  });
  document.getElementById('personalizationMemoryMoreBtn')?.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    setPersonalizationMemorySortOpen(false);
    const menu = document.getElementById('personalizationMemoryMoreMenu');
    setPersonalizationMemoryMoreOpen(!!menu?.hidden);
  });
  document.getElementById('personalizationMemoryMoreMenu')?.addEventListener('click', (e)=>{
    e.stopPropagation();
  });
  document.getElementById('personalizationMemoryHistoryBtn')?.addEventListener('click', ()=>{
    setPersonalizationMemoryMoreOpen(false);
    setPersonalizationMemoryHistoryModalOpen(true);
  });
  document.getElementById('personalizationMemoryHistoryCloseBtn')?.addEventListener('click', ()=>setPersonalizationMemoryHistoryModalOpen(false));
  document.getElementById('personalizationMemoryHistoryModal')?.addEventListener('click', (e)=>{
    if(e.target === e.currentTarget) setPersonalizationMemoryHistoryModalOpen(false);
  });
  document.getElementById('personalizationMemoryHistoryMoreBtn')?.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    const menu = document.getElementById('personalizationMemoryHistoryActionMenu');
    setPersonalizationMemoryHistoryMoreOpen(!!menu?.hidden);
  });
  document.getElementById('personalizationMemoryHistoryActionMenu')?.addEventListener('click', (e)=>e.stopPropagation());
  document.getElementById('personalizationMemoryHistoryRestoreBtn')?.addEventListener('click', restorePersonalizationMemoryHistoryVersion);
  document.getElementById('personalizationMemoryHistoryDeleteBtn')?.addEventListener('click', deletePersonalizationMemoryHistoryVersion);
  document.getElementById('personalizationMemorySearchInput')?.addEventListener('input', (e)=>{
    PERSONALIZATION_MEMORY_SEARCH_QUERY = String(e.target?.value || '').trim();
    renderPersonalizationMemoryList(getPersonalizationState());
  });
  document.getElementById('personalizationMemoryAddBtn')?.addEventListener('click', upsertPersonalizationMemoryFromEditor);
  document.getElementById('personalizationMemoryCancelEditBtn')?.addEventListener('click', ()=> resetPersonalizationEditor({ clear:true }));
  document.getElementById('personalizationMemoryEditorCloseBtn')?.addEventListener('click', ()=> resetPersonalizationEditor({ clear:true }));
  document.getElementById('personalizationMemoryClearBtn')?.addEventListener('click', async ()=>{
    const btn = document.getElementById('personalizationMemoryClearBtn');
    setPersonalizationMemoryMoreOpen(false);
    const state = readPersonalizationFormState();
    if(!Array.isArray(state.memoryItems) || !state.memoryItems.length){
      try{ toast(personalizationMemoryT('memory.no_clearable', null, 'There are no memories to clear.')); }catch(_){ }
      return;
    }
    const ok = await askKbDangerConfirm({
      title:personalizationMemoryT('memory.clear_title', null, 'Delete all memories?'),
      desc:personalizationMemoryT('memory.clear_desc', {count:state.memoryItems.length}, `This will delete ${state.memoryItems.length} memories.`),
      confirmText:personalizationMemoryT('common.confirm', null, 'Confirm'),
      cancelText:personalizationMemoryT('common.cancel', null, 'Cancel'),
    }, btn);
    if(!ok) return;
    state.memoryItems = [];
    try{
      await commitPersonalizationStateAndWait(state, { immediate:true });
      renderPersonalizationUi();
      if(document.getElementById('personalizationMemoryHistoryModal')?.classList.contains('open')){
        try{ await fetchPersonalizationMemoryHistory(); renderPersonalizationMemoryHistoryModal(); }catch(_){ }
      }
      try{ toast(personalizationMemoryT('memory.cleared', null, 'Memories cleared')); }catch(_){ }
    }catch(err){
      renderPersonalizationUi();
      try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
    }
  });
  document.getElementById('personalizationMemoryEnabled')?.addEventListener('change', async ()=>{
    try{
      await savePersonalizationSettings({ immediate:true, throwOnError:true });
      try{ toast(personalizationMemoryT('memory.settings_saved', null, 'Memory settings saved')); }catch(_){ }
    }catch(err){
      renderPersonalizationUi();
      try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
    }
  });
  document.getElementById('personalizationMemoryAutoManageEnabled')?.addEventListener('change', async ()=>{
    try{
      await savePersonalizationSettings({ immediate:true, throwOnError:true });
      try{ toast(personalizationMemoryT('memory.auto_manage_saved', null, 'Automatic memory saving and updating settings saved')); }catch(_){ }
    }catch(err){
      renderPersonalizationUi();
      try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
    }
  });
  document.getElementById('personalizationHistoryReferenceEnabled')?.addEventListener('change', async ()=>{
    try{
      await savePersonalizationSettings({ immediate:true, throwOnError:true });
      try{ toast(personalizationMemoryT('memory.history_reference_saved', null, 'Chat-history reference settings saved')); }catch(_){ }
    }catch(err){
      renderPersonalizationUi();
      try{ toast(err?.message || personalizationMemoryT('common.save_failed', null, 'Save failed')); }catch(_){ }
    }
  });
  document.getElementById('personalizationMemoryInstruction')?.addEventListener('input', ()=> updatePersonalizationSummary(readPersonalizationFormState()));
  document.addEventListener('click', (e)=>{
    const moreWrap = document.querySelector('.memory-modal-more-wrap');
    if(moreWrap && !moreWrap.contains(e.target)) setPersonalizationMemoryMoreOpen(false);
    const sortWrap = document.querySelector('.memory-modal-sort-wrap');
    if(sortWrap && !sortWrap.contains(e.target)) setPersonalizationMemorySortOpen(false);
    const historyActionWrap = document.querySelector('.memory-history-detail-actions');
    if(historyActionWrap && !historyActionWrap.contains(e.target)) setPersonalizationMemoryHistoryMoreOpen(false);
  });
  document.getElementById('personalizationMemoryEditor')?.addEventListener('keydown', (e)=>{
    if((e.ctrlKey || e.metaKey) && e.key === 'Enter'){
      e.preventDefault();
      upsertPersonalizationMemoryFromEditor();
    }
    if(e.key === 'Escape'){
      e.preventDefault();
      resetPersonalizationEditor({ clear:true });
    }
  });
  document.addEventListener('keydown', (e)=>{
    if(e.key !== 'Escape') return;
    if(PERSONALIZATION_MEMORY_EDITOR_OPEN){
      e.preventDefault();
      resetPersonalizationEditor({ clear:true });
      return;
    }
    if(document.getElementById('personalizationMemoryHistoryModal')?.classList.contains('open')){
      e.preventDefault();
      setPersonalizationMemoryHistoryModalOpen(false);
      return;
    }
    if(document.getElementById('personalizationCustomInstructionModal')?.classList.contains('open')){
      e.preventDefault();
      setPersonalizationCustomInstructionModalOpen(false);
      return;
    }
    if(document.getElementById('personalizationMemoryModal')?.classList.contains('open')){
      e.preventDefault();
      setPersonalizationMemoryModalOpen(false);
    }
  });
}

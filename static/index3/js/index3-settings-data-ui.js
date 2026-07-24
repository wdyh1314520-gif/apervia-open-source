/* Settings data-management, archived chats, storage-space UI.*/
function settingsDataT(key, params, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

function syncBrowserGeoSettingAfterSave(wasEnabled, isEnabled){
  if(!isEnabled){
    clearUserGeoCache();
    _lastGeoErrorMeta = null;
    return;
  }
  if(wasEnabled) return;
  try{ setStatus(settingsDataT('settings.data.location_requesting', null, 'Requesting browser location permission…')); }catch(_){ }
  getUserGeoCached({ preferFresh:true, allowStored:false }).then((geo)=>{
    if(geo){
      try{ toast(settingsDataT('settings.data.location_enabled', null, 'Location enabled')); }catch(_){ }
      try{ setStatus(settingsDataT('settings.data.location_enabled', null, 'Location enabled')); }catch(_){ }
      return;
    }
    if(_lastGeoErrorMeta) notifyGeoUserHint(_lastGeoErrorMeta);
  }).catch((err)=>{
    _lastGeoErrorMeta = buildGeoErrorMeta(err, { reason:'unknown', message:settingsDataT('settings.data.location_request_failed', null, 'Location request failed') });
    notifyGeoUserHint(_lastGeoErrorMeta);
  });
}
function getSessionArchivedAtMs(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return 0;
  const candidates = [s.archivedAt, s.archived_at, s.archived_at_ms, s.archiveAt, s.archive_at];
  for(const value of candidates){
    const ts = Number(value || 0);
    if(Number.isFinite(ts) && ts > 0) return ts < 100000000000 ? ts * 1000 : ts;
  }
  return s.archived === true ? (Number(s.updatedAt || s.createdAt || Date.now()) || Date.now()) : 0;
}

function isSessionArchived(session){
  return getSessionArchivedAtMs(session) > 0 || !!(session && typeof session === 'object' && session.archived === true);
}

function normalizeSessionArchiveFields(session, archivedAt=0){
  if(!session || typeof session !== 'object') return session;
  const ts = Number(archivedAt || 0) || 0;
  if(ts > 0){
    session.archived = true;
    session.archivedAt = ts;
    session.archived_at = ts;
  }else{
    session.archived = false;
    session.archivedAt = 0;
    session.archived_at = 0;
  }
  return session;
}

function getArchivedSessions(){
  return Object.values(store?.sessions || {})
    .filter(s => s && typeof s === 'object' && isSessionArchived(s))
    .sort((a,b)=>{
      const ba = getSessionArchivedAtMs(b) || sessionRealUpdatedAtMs(b);
      const aa = getSessionArchivedAtMs(a) || sessionRealUpdatedAtMs(a);
      if(ba !== aa) return ba - aa;
      return String(a.title || '').localeCompare(String(b.title || ''));
    });
}

function getArchivableSessions(){
  return Object.values(store?.sessions || {})
    .filter(s => s && typeof s === 'object' && !isSessionArchived(s) && sessionShouldAppearInSidebar(s));
}

function formatArchivedChatDate(ts){
  const value = Number(ts || 0) || 0;
  if(!value) return '';
  const date = new Date(value < 100000000000 ? value * 1000 : value);
  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  const d = date.getDate();
  return `${y}年${m}月${d}日`;
}

function refreshArchivedComposerState(){
  const archived = !isHomeLandingView && isSessionArchived(getActive());
  const notice = document.getElementById('activeArchivedNotice');
  const unarchiveBtn = document.getElementById('activeUnarchiveBtn');
  const composerEl = notice?.closest?.('.composer') || document.querySelector('.composer');
  if(notice) notice.hidden = !archived;
  if(composerEl) composerEl.classList.toggle('is-archived', !!archived);
  if(unarchiveBtn) unarchiveBtn.disabled = !archived;
  if(inputEl){
    inputEl.disabled = !!archived;
    inputEl.setAttribute('aria-disabled', archived ? 'true' : 'false');
  }
  if(addFileBtn) addFileBtn.disabled = !!archived;
  if(voiceInputBtn) voiceInputBtn.disabled = !!archived;
  try{ refreshComposerLayoutSoon(); }catch(_){ }
}

async function archiveSession(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  const session = sid ? store?.sessions?.[sid] : null;
  if(!sid || !session || typeof session !== 'object') return false;
  if(isSessionArchived(session)) return true;
  const previousUpdatedAt = session.updatedAt;
  const archivedAt = Date.now();
  normalizeSessionArchiveFields(session, archivedAt);
  if(previousUpdatedAt !== undefined) session.updatedAt = previousUpdatedAt;
  saveStore();
  invalidateSidebarRenderCache();
  invalidateChatRenderCache();
  safeRenderAll();
  renderArchivedChatsModal();
  renderDataManagementUi();
  if(opts.toast !== false){
    try{ toast(settingsDataT('settings.data.archived_notice', null, 'Archived chats are available in Settings.')); }catch(_){ }
  }
  return true;
}

async function restoreSessionFromArchive(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  const session = sid ? store?.sessions?.[sid] : null;
  if(!sid || !session || typeof session !== 'object') return false;
  const previousUpdatedAt = session.updatedAt;
  normalizeSessionArchiveFields(session, 0);
  if(previousUpdatedAt !== undefined) session.updatedAt = previousUpdatedAt;
  saveStore();
  invalidateSidebarRenderCache();
  invalidateChatRenderCache();
  if(opts.openSession){
    setActive(sid);
  }else{
    safeRenderAll();
  }
  renderArchivedChatsModal();
  renderDataManagementUi();
  if(opts.toast !== false){
    try{ toast(window.AperviaI18n?.t('settings.data.unarchived') || 'Chat unarchived'); }catch(_){ }
  }
  return true;
}

async function askAndArchiveAllChats(returnFocusEl=null){
  const sessions = getArchivableSessions();
  if(!sessions.length){
    try{ toast(window.AperviaI18n?.t('settings.data.no_archivable_toast') || 'There are no chats to archive.'); }catch(_){ }
    return;
  }
  const ok = await askKbDangerConfirm({
    title:window.AperviaI18n?.t('settings.data.archive_all_title') || 'Archive all chats?',
    desc:window.AperviaI18n?.t('settings.data.archive_all_desc', {count:sessions.length}) || `This will hide ${sessions.length} chats from the sidebar. You can restore them in Settings.`,
    confirmText:window.AperviaI18n?.t('settings.data.archive_all') || 'Archive all',
    cancelText:window.AperviaI18n?.t('common.cancel') || 'Cancel',
    variant:'default',
  }, returnFocusEl);
  if(!ok) return;
  const archivedAt = Date.now();
  for(const session of sessions){
    const previousUpdatedAt = session.updatedAt;
    normalizeSessionArchiveFields(session, archivedAt);
    if(previousUpdatedAt !== undefined) session.updatedAt = previousUpdatedAt;
  }
  saveStore();
  invalidateSidebarRenderCache();
  invalidateChatRenderCache();
  safeRenderAll();
  renderArchivedChatsModal();
  renderDataManagementUi();
  try{ toast(window.AperviaI18n?.t('settings.data.archived_notice') || 'Archived chats are available in Settings.'); }catch(_){ }
}

async function deleteArchivedSession(sessionId, returnFocusEl=null){
  const sid = String(sessionId || '').trim();
  const session = sid ? store?.sessions?.[sid] : null;
  if(!sid || !session) return false;
  const confirmed = await askDeleteSessionConfirm(session, returnFocusEl);
  if(!confirmed) return false;
  const deletingCurrentSession = !isHomeLandingView && store.activeId === sid;
  const btn = returnFocusEl && returnFocusEl.tagName ? returnFocusEl : null;
  const oldText = btn ? btn.textContent : '';
  if(btn){
    btn.disabled = true;
    btn.textContent = '删除中';
  }
  let deleteResult = null;
  try{
    deleteResult = await deleteSessionsEverywhere([sid], { statusText:'正在删除会话…' });
  }catch(err){
    if(btn){
      btn.disabled = false;
      btn.textContent = oldText || '删除';
    }
    try{ toast(settingsDataT('settings.data.session_delete_failed', {error:err?.message || err}, `Unable to delete conversation: ${err?.message || err}`)); }catch(_){ }
    return false;
  }
  if(deletingCurrentSession){
    enterHomeLandingView({ replace:true });
  }else{
    syncSessionRoute({ replace:true });
  }
  invalidateSidebarRenderCache();
  invalidateChatRenderCache();
  safeRenderAll();
  renderArchivedChatsModal();
  renderDataManagementUi();
  if(deleteResult?.cloud_pending){
    try{ toast(settingsDataT('settings.data.session_delete_pending', null, 'Conversation deleted. Cloud sync will resume when the network is available.')); }catch(_){ }
  }
  return true;
}

let _archivedChatsRenderSeq = 0;

function setArchivedChatsModalOpen(open){
  const modal = document.getElementById('archivedChatsModal');
  if(!modal) return;
  const shouldOpen = !!open;
  modal.classList.toggle('open', shouldOpen);
  modal.toggleAttribute('inert', !shouldOpen);
  modal.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
  document.body.classList.toggle('modal-open', shouldOpen || isSettingsModalOpen());
  if(shouldOpen){
    scheduleUiAfterPaint(()=> renderArchivedChatsModal());
    requestAnimationFrame(()=> document.getElementById('archivedChatsModalCloseBtn')?.focus?.());
  }else{
    _archivedChatsRenderSeq++;
  }
}

function buildArchivedChatRow(session){
  const row = document.createElement('div');
  row.className = 'archived-chat-row';
  row.dataset.sessionId = String(session.id || '');

  const openBtn = document.createElement('button');
  openBtn.type = 'button';
  openBtn.className = 'archived-chat-title-btn';
  openBtn.innerHTML = '<span class="archived-chat-dot" aria-hidden="true"></span><span></span>';
  openBtn.querySelector('span:last-child').textContent = sessionDisplayTitle(session.title);
  openBtn.title = openBtn.querySelector('span:last-child').textContent;
  openBtn.addEventListener('click', ()=>{
    setArchivedChatsModalOpen(false);
    setActive(session.id);
  });

  const date = document.createElement('div');
  date.className = 'archived-chat-date';
  date.textContent = formatArchivedChatDate(Number(session.createdAt || session.created_at || 0) || getSessionArchivedAtMs(session));

  const actions = document.createElement('div');
  actions.className = 'archived-chat-actions';
  const restoreBtn = document.createElement('button');
  restoreBtn.type = 'button';
  restoreBtn.className = 'archived-chat-action-btn';
  restoreBtn.title = window.AperviaI18n?.t('settings.data.unarchive') || 'Unarchive';
  restoreBtn.setAttribute('aria-label', restoreBtn.title);
  restoreBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16v13H4z"></path><path d="M8 7V4h8v3"></path><path d="M12 17V11"></path><path d="M9.5 13.5 12 11l2.5 2.5"></path></svg>';
  restoreBtn.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    restoreSessionFromArchive(session.id, { toast:true });
  });
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'archived-chat-action-btn delete';
  deleteBtn.title = window.AperviaI18n?.t('common.delete') || 'Delete';
  deleteBtn.setAttribute('aria-label', deleteBtn.title);
  deleteBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M6 7l1 14h10l1-14"></path><path d="M9 7V4h6v3"></path></svg>';
  deleteBtn.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    deleteArchivedSession(session.id, deleteBtn);
  });
  actions.appendChild(restoreBtn);
  actions.appendChild(deleteBtn);

  row.appendChild(openBtn);
  row.appendChild(date);
  row.appendChild(actions);
  return row;
}

function renderArchivedChatsModal(){
  const modal = document.getElementById('archivedChatsModal');
  const list = document.getElementById('archivedChatsList');
  const empty = document.getElementById('archivedChatsEmpty');
  if(!list || !modal?.classList.contains('open')) return;
  const sessions = getArchivedSessions();
  const seq = ++_archivedChatsRenderSeq;
  list.innerHTML = '';
  if(empty){
    empty.hidden = sessions.length > 0;
    if(!sessions.length) empty.textContent = window.AperviaI18n?.t('settings.data.no_archived') || 'No archived chats.';
  }
  if(!sessions.length) return;

  let index = 0;
  const batchSize = 32;
  const appendBatch = () => {
    if(seq !== _archivedChatsRenderSeq || !modal.classList.contains('open')) return;
    const frag = document.createDocumentFragment();
    const end = Math.min(index + batchSize, sessions.length);
    for(; index < end; index++){
      frag.appendChild(buildArchivedChatRow(sessions[index]));
    }
    list.appendChild(frag);
    if(index < sessions.length) requestAnimationFrame(appendBatch);
  };
  requestAnimationFrame(appendBatch);
}

const REMOTE_BROWSER_SITE_DATA_KEY = "webai_remote_browser_site_data_v1";
const REMOTE_BROWSER_DATA_CLEARED_AT_KEY = "webai_remote_browser_data_cleared_at_v1";

function getRemoteBrowserSiteDataEnabled(){
  try{
    const raw = localStorage.getItem(REMOTE_BROWSER_SITE_DATA_KEY);
    if(raw === null || raw === undefined || raw === '') return true;
    return raw !== '0';
  }catch(_){
    return true;
  }
}

function setRemoteBrowserSiteDataEnabled(enabled){
  try{ localStorage.setItem(REMOTE_BROWSER_SITE_DATA_KEY, enabled ? '1' : '0'); }catch(_){ }
}

function showDataManagementView(name='home'){
  const targetName = String(name || 'home').trim();
  const map = {
    home: document.getElementById('dataManagementHomeView'),
    location: document.getElementById('dataLocationView'),
    remoteBrowser: document.getElementById('dataRemoteBrowserView'),
  };
  Object.entries(map).forEach(([key, el])=>{
    if(!el) return;
    const active = key === targetName;
    el.hidden = !active;
    el.classList.toggle('active', active);
  });
  renderDataManagementUi();
}

function updateBrowserGeoSettingFromDataManagement(enabled){
  const wasEnabled = isBrowserGeoSettingEnabled();
  const nextEnabled = !!enabled;
  const ws = {...getWebSettings(), BROWSER_GEO_ENABLE: nextEnabled ? 1 : 0};
  saveWebSettings(ws);
  fillWebSettingsForm();
  renderDataManagementUi();
  syncBrowserGeoSettingAfterSave(wasEnabled, nextEnabled);
  try{ toast(settingsDataT(nextEnabled ? 'settings.data.location_on' : 'settings.data.location_off', null, nextEnabled ? 'Location: On' : 'Location: Off')); }catch(_){ }
}

function renderDataManagementUi(){
  const ws = getWebSettings();
  const geoEnabled = isSettingTruthyValue(ws.BROWSER_GEO_ENABLE);
  const remoteSiteDataEnabled = getRemoteBrowserSiteDataEnabled();
  const sessionCount = Object.keys(store?.sessions || {}).length;
  const archivedCount = getArchivedSessions().length;
  const archivableCount = getArchivableSessions().length;
  const locationState = document.getElementById('dataLocationState');
  const browserState = document.getElementById('dataRemoteBrowserState');
  const chatsCount = document.getElementById('dataChatsCount');
  const archivedChatsCount = document.getElementById('dataArchivedChatsCount');
  const archiveAllChatsCount = document.getElementById('dataArchiveAllChatsCount');
  const archiveAllBtn = document.getElementById('dataArchiveAllChatsBtn');
  const summary = document.getElementById('dataManagementSummary');
  const locationToggle = document.getElementById('dataLocationToggle');
  const remoteKeepToggle = document.getElementById('dataRemoteBrowserKeepToggle');
  const enabledLabel = window.AperviaI18n?.t('common.enabled') || '启用';
  const disabledLabel = window.AperviaI18n?.t('common.disabled') || '关闭';
  const onLabel = window.AperviaI18n?.t('common.on') || '开';
  const offLabel = window.AperviaI18n?.t('common.off') || '关';
  if(locationState) locationState.textContent = geoEnabled ? enabledLabel : disabledLabel;
  if(browserState) browserState.textContent = remoteSiteDataEnabled ? onLabel : offLabel;
  if(chatsCount) chatsCount.textContent = sessionCount
    ? (window.AperviaI18n?.t('settings.data.chats', {count:sessionCount, archived:archivedCount ? (window.AperviaI18n?.t('settings.data.archived_suffix', {count:archivedCount}) || `，其中 ${archivedCount} 个已归档`) : ''}) || `当前共有 ${sessionCount} 个会话。`)
    : (window.AperviaI18n?.t('settings.data.no_chats') || '当前没有可删除的会话。');
  if(archivedChatsCount) archivedChatsCount.textContent = archivedCount ? (window.AperviaI18n?.t('settings.data.archived_count', {count:archivedCount}) || `当前有 ${archivedCount} 个已归档的聊天。`) : (window.AperviaI18n?.t('settings.data.no_archived') || '暂无已归档的聊天。');
  if(archiveAllChatsCount) archiveAllChatsCount.textContent = archivableCount ? (window.AperviaI18n?.t('settings.data.archivable_count', {count:archivableCount}) || `可归档 ${archivableCount} 个聊天。`) : (window.AperviaI18n?.t('settings.data.no_archivable') || '没有可归档的聊天。');
  if(archiveAllBtn) archiveAllBtn.disabled = archivableCount <= 0;
  if(summary) summary.textContent = window.AperviaI18n?.t('settings.data.summary', {chats:sessionCount, archived:archivedCount, location:geoEnabled ? enabledLabel : disabledLabel, remote:remoteSiteDataEnabled ? enabledLabel : disabledLabel}) || `聊天 ${sessionCount} 个 · 归档 ${archivedCount} 个`;
  if(locationToggle) locationToggle.checked = !!geoEnabled;
  if(remoteKeepToggle) remoteKeepToggle.checked = !!remoteSiteDataEnabled;
}

let storageSpaceCache = null;
let storageSpaceLoading = false;
let storageSpaceError = "";

function storageSpaceFormatBytes(value){
  const n = Math.max(0, Number(value || 0) || 0);
  if(typeof fmtBytes === 'function'){
    try{ return fmtBytes(n); }catch(_){ }
  }
  const units = ['B','KB','MB','GB','TB'];
  let size = n;
  let idx = 0;
  while(size >= 1024 && idx < units.length - 1){ size /= 1024; idx += 1; }
  return idx === 0 ? `${Math.round(size)}${units[idx]}` : `${size.toFixed(1)}${units[idx]}`;
}

function storageSpaceNormalizeQuota(payload){
  const data = payload && typeof payload === 'object' ? payload : {};
  return data.quota && typeof data.quota === 'object' ? data.quota : data;
}

function storageSpaceFallbackRows(quota){
  const used = Math.max(0, Number(quota?.used_bytes || 0) || 0);
  if(!used) return [];
  return [{
    key:'account',
    label:'账号数据',
    used_bytes:used,
    used_text:quota?.used_text || storageSpaceFormatBytes(used),
    count_text:'当前账号存储',
    action:'backup',
  }];
}

function storageSpaceT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback;
}

function storageSpaceCategoryCount(row){
  const key = String(row?.key || '').trim();
  const count = Math.max(0, Number(row?.count || 0) || 0);
  if(['files','images','sandboxes','chats'].includes(key)){
    return storageSpaceT(`settings.storage.count.${key}.${count ? 'other' : 'zero'}`, {count}, String(row?.count_text || ''));
  }
  return String(row?.count_text || (count ? storageSpaceT('settings.storage.items', {count}, `${count} 项`) : '')).trim();
}

function renderStorageSpaceUi(){
  const card = document.querySelector('.storage-space-card');
  const usedEl = document.getElementById('storageSpaceUsageText');
  const barEl = document.getElementById('storageSpaceBar');
  const availableEl = document.getElementById('storageSpaceAvailableText');
  const updatedEl = document.getElementById('storageSpaceUpdated');
  const rowsEl = document.getElementById('storageSpaceRows');
  if(!usedEl || !barEl || !availableEl || !rowsEl) return;
  const quota = storageSpaceNormalizeQuota(storageSpaceCache || {});
  if(!quota || !Object.keys(quota).length){
    usedEl.textContent = '-';
    barEl.style.width = '0%';
    availableEl.textContent = storageSpaceError ? storageSpaceT('settings.storage.read_failed', null, '当前未能读取账号空间。') : storageSpaceT('settings.storage.read_hint', null, '打开后会读取当前账号已使用空间。');
    if(updatedEl) updatedEl.textContent = storageSpaceError ? storageSpaceT('settings.storage.read_failed', null, '读取失败') : (storageSpaceLoading ? storageSpaceT('settings.storage.loading', null, '正在读取…') : storageSpaceT('settings.storage.not_loaded', null, '尚未读取'));
    rowsEl.innerHTML = storageSpaceError
      ? `<div class="storage-space-empty">${escapeHtml(storageSpaceT('settings.storage.failed_detail', {error:storageSpaceError}, `读取失败：${storageSpaceError}`))}</div>`
      : `<div class="storage-space-empty">${escapeHtml(storageSpaceT('settings.storage.loading_detail', null, '正在读取存储空间…'))}</div>`;
    card?.classList.toggle('is-loading', !!storageSpaceLoading);
    return;
  }
  const usedBytes = Math.max(0, Number(quota.used_bytes || 0) || 0);
  const limitBytes = Math.max(0, Number(quota.limit_bytes || 0) || 0);
  const availableBytes = Math.max(0, Number(quota.available_bytes || Math.max(0, limitBytes - usedBytes)) || 0);
  const usedText = quota.used_text || storageSpaceFormatBytes(usedBytes);
  const limitText = quota.limit_text || storageSpaceFormatBytes(limitBytes);
  const availableText = quota.available_text || storageSpaceFormatBytes(availableBytes);
  const percent = limitBytes > 0 ? Math.max(0, Math.min(100, Number(quota.percent || (usedBytes / limitBytes * 100)) || 0)) : 0;
  usedEl.textContent = storageSpaceT('settings.storage.usage', {used:usedText, limit:limitText}, `已使用 ${usedText}，共 ${limitText}`);
  barEl.style.width = `${percent}%`;
  availableEl.textContent = storageSpaceT('settings.storage.remaining', {available:availableText}, `剩余 ${availableText}`);
  if(updatedEl) updatedEl.textContent = quota.updated_at_text ? storageSpaceT('settings.storage.updated', {time:quota.updated_at_text}, `更新于 ${quota.updated_at_text}`) : (storageSpaceLoading ? storageSpaceT('settings.storage.loading', null, '正在读取…') : storageSpaceT('settings.storage.current_account', null, '当前账号'));
  const rawRows = Array.isArray(quota.categories) ? quota.categories : (Array.isArray(quota.summary?.categories) ? quota.summary.categories : storageSpaceFallbackRows(quota));
  const rows = rawRows.filter(row => row && typeof row === 'object');
  if(!rows.length){
    rowsEl.innerHTML = `<div class="storage-space-empty">${escapeHtml(storageSpaceT('settings.storage.empty', null, '暂无可管理的数据。'))}</div>`;
    card?.classList.toggle('is-loading', !!storageSpaceLoading);
    return;
  }
  rowsEl.innerHTML = rows.map(row => {
    const categoryKey = String(row.key || '').trim();
    const key = escapeHtml(categoryKey);
    const label = escapeHtml(storageSpaceT(`settings.storage.category.${categoryKey}`, null, row.label || storageSpaceT('settings.storage.data', null, '数据')));
    const used = escapeHtml(row.used_text || storageSpaceFormatBytes(row.used_bytes || 0));
    const count = escapeHtml(storageSpaceCategoryCount(row));
    const desc = [used, count].filter(Boolean).join(' · ');
    return `<button class="storage-space-row" type="button" role="listitem" data-storage-space-action="${key}"><span class="storage-space-row-copy"><span class="storage-space-row-name">${label}</span><span class="storage-space-row-desc">${desc || escapeHtml(storageSpaceT('settings.storage.no_usage', null, '暂无占用'))}</span></span><span class="storage-space-row-side"><span class="storage-space-row-chevron" aria-hidden="true">›</span></span></button>`;
  }).join('');
  card?.classList.toggle('is-loading', !!storageSpaceLoading);
}

async function refreshStorageSpaceUi({ force=false } = {}){
  if(storageSpaceLoading) return;
  if(storageSpaceCache && !force){
    renderStorageSpaceUi();
    return;
  }
  storageSpaceLoading = true;
  renderStorageSpaceUi();
  try{
    const res = await fetch('/api3/storage/quota', { credentials:'same-origin', cache:'no-store' });
    let data = {};
    try{ data = await res.json(); }catch(_){ data = {}; }
    if(!res.ok || data?.ok === false){
      throw new Error(data?.error || data?.message || ('HTTP ' + res.status));
    }
    storageSpaceError = '';
    storageSpaceCache = data;
  }catch(err){
    storageSpaceError = String(err?.message || err || '读取失败');
  }finally{
    storageSpaceLoading = false;
    renderStorageSpaceUi();
  }
}

function openStorageSpaceTarget(key){
  const raw = String(key || '').trim();
  if(raw === 'files' || raw === 'images' || raw === 'knowledge_base'){
    const targetTab = raw === 'knowledge_base' ? 'knowledge' : 'files';
    try{ closeSettingsModal({ syncRoute:false }); }catch(_){ }
    setTimeout(()=>{
      try{ openLibraryRoute(targetTab, { replaceRoute:false }); }catch(_){ window.openKnowledgeBaseModal?.(); }
    }, 0);
    return;
  }
  activateSettingsTab('backup', { force:true });
}

async function clearRemoteBrowserData(returnFocusEl=null){
  const ok = await askKbDangerConfirm({
    title:settingsDataT('settings.data.remote_delete_title', null, 'Delete remote browser data?'),
    desc:settingsDataT('settings.data.remote_delete_desc', null, 'This clears the remote-browser site-data state recorded by Apervia. It does not delete conversations.'),
    confirmText:settingsDataT('settings.data.delete_all', null, 'Delete all'),
    cancelText:settingsDataT('common.cancel', null, 'Cancel'),
  }, returnFocusEl);
  if(!ok) return;
  const btn = returnFocusEl && returnFocusEl.tagName ? returnFocusEl : null;
  const oldText = btn ? btn.textContent : '';
  if(btn){
    btn.disabled = true;
    btn.textContent = settingsDataT('settings.data.remote_deleting', null, 'Deleting…');
  }
  try{
    const res = await fetch('/api3/remote-browser-data/clear', {
      method:'POST',
      credentials:'same-origin',
      cache:'no-store',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ keep_site_data:getRemoteBrowserSiteDataEnabled() }),
    });
    let data = {};
    try{ data = await res.json(); }catch(_){ data = {}; }
    if(!res.ok || data?.ok === false){
      throw new Error(data?.message || data?.error || ('HTTP ' + res.status));
    }
    try{ localStorage.setItem(REMOTE_BROWSER_DATA_CLEARED_AT_KEY, String(Date.now())); }catch(_){ }
    try{ toast(settingsDataT('settings.data.remote_deleted', null, 'Remote browser data deleted')); }catch(_){ }
  }catch(err){
    try{ toast(settingsDataT('settings.data.remote_delete_failed', {error:err?.message || err}, `Unable to delete remote browser data: ${err?.message || err}`)); }catch(_){ }
  }finally{
    if(btn){
      btn.disabled = false;
      btn.textContent = oldText || settingsDataT('settings.data.delete_all', null, 'Delete all');
    }
    renderDataManagementUi();
  }
}

async function resetAllChatsData(){
  const oldSessionIds = Object.keys(store?.sessions || {});
  try{
    await deleteSessionsEverywhere(oldSessionIds, { statusText:'正在删除所有聊天…' });
  }catch(err){
    try{ toast(settingsDataT('settings.data.delete_all_failed', {error:err?.message || err}, `Unable to delete all conversations: ${err?.message || err}`)); }catch(_){ }
    return false;
  }
  store = { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
  isHomeLandingView = true;
  saveStore();
  syncSessionRoute({ replace:true, forceHome:true });
  clearPastedImages();
  restoreComposerForCurrentView();
  safeRenderAll();
  rtReset();
  setStatus('就绪');
  renderDataManagementUi();
  return true;
}

async function askAndResetAllChats(returnFocusEl=null){
  const count = Object.keys(store?.sessions || {}).length;
  if(!count){
    try{ toast(window.AperviaI18n?.t('settings.data.no_chats') || 'There are no conversations to delete.'); }catch(_){ }
    return;
  }
  const ok = await askKbDangerConfirm({
    title:window.AperviaI18n?.t('settings.data.delete_all_title') || 'Delete all chats?',
    desc:window.AperviaI18n?.t('settings.data.delete_all_desc', {count}) || `This will delete the current ${count} conversations. This cannot be undone.`,
    confirmText:window.AperviaI18n?.t('settings.data.delete_all') || 'Delete all',
    cancelText:window.AperviaI18n?.t('common.cancel') || 'Cancel',
  }, returnFocusEl);
  if(!ok) return;
  const btn = returnFocusEl && returnFocusEl.tagName ? returnFocusEl : null;
  const oldText = btn ? btn.textContent : '';
  if(btn){
    btn.disabled = true;
    btn.textContent = window.AperviaI18n?.t('common.deleting') || 'Deleting…';
  }
  const done = await resetAllChatsData();
  if(btn && !done){
    btn.disabled = false;
    btn.textContent = oldText || window.AperviaI18n?.t('settings.data.delete_all') || 'Delete all';
  }
}

function makeStoreBackupPayload(){
  return {
    version: 1,
    exportedAt: new Date().toISOString(),
    app: "Apervia",
    store
  };
}
function downloadTextFile(filename, text, mime="application/json"){
  const blob = new Blob([text], {type:mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1500);
}
function exportChatsBackup(){
  try{
    const stamp = new Date();
    const pad = (n)=> String(n).padStart(2, "0");
    const filename = `webai-chat-backup-${stamp.getFullYear()}${pad(stamp.getMonth()+1)}${pad(stamp.getDate())}-${pad(stamp.getHours())}${pad(stamp.getMinutes())}.json`;
    downloadTextFile(filename, JSON.stringify(makeStoreBackupPayload(), null, 2));
    setStatus("已导出聊天备份");
  }catch(e){
    reportAppError("导出失败：" + (e?.message || e));
  }
}
async function importChatsBackupFile(file){
  if(!file) return;
  const text = await file.text();
  let obj = null;
  try{ obj = JSON.parse(text); }catch(_){ throw new Error("备份文件不是合法 JSON"); }
  const nextStore = obj && obj.store ? obj.store : obj;
  if(!nextStore || typeof nextStore !== "object" || !nextStore.sessions || !nextStore.activeId) throw new Error("备份文件格式不正确");
  const ok = await askKbDangerConfirm({
    title:'要导入这份数据吗？',
    desc:'导入会覆盖当前本地聊天记录。',
    confirmText:'导入',
    cancelText:'取消',
  }, document.getElementById('importChatsBtn'));
  if(!ok) return;
  store = nextStore;
  ensureStorePersonalization(store);
  applyRouteSessionToStore(store);
  saveStore();
  syncSessionRoute({ replace:true });
  safeRenderAll();
  restoreComposerForCurrentView();
  setStatus("已导入聊天备份");
}

function bindDataManagementSettingsUi(){
  document.getElementById('dataLocationRow')?.addEventListener('click', ()=> showDataManagementView('location'));
  document.getElementById('storageSpaceRefreshBtn')?.addEventListener('click', ()=> refreshStorageSpaceUi({ force:true }));
  document.getElementById('storageSpaceRows')?.addEventListener('click', (e)=>{
    const row = e.target?.closest?.('[data-storage-space-action]');
    if(row) openStorageSpaceTarget(row.getAttribute('data-storage-space-action') || '');
  });
  document.getElementById('dataRemoteBrowserRow')?.addEventListener('click', ()=> showDataManagementView('remoteBrowser'));
  document.getElementById('dataLocationBackBtn')?.addEventListener('click', ()=> showDataManagementView('home'));
  document.getElementById('dataRemoteBrowserBackBtn')?.addEventListener('click', ()=> showDataManagementView('home'));
  document.getElementById('dataLocationToggle')?.addEventListener('change', (e)=> updateBrowserGeoSettingFromDataManagement(!!e.target.checked));
  document.getElementById('dataRemoteBrowserKeepToggle')?.addEventListener('change', (e)=>{ setRemoteBrowserSiteDataEnabled(!!e.target.checked); renderDataManagementUi(); try{ toast(settingsDataT(e.target.checked ? 'settings.data.remote_enabled' : 'settings.data.remote_disabled', null, e.target.checked ? 'Remote browser data: On' : 'Remote browser data: Off')); }catch(_){ } });
  document.getElementById('dataRemoteBrowserClearBtn')?.addEventListener('click', (e)=> clearRemoteBrowserData(e.currentTarget));
  document.getElementById('dataArchivedChatsManageBtn')?.addEventListener('click', ()=> setArchivedChatsModalOpen(true));
  document.getElementById('dataArchiveAllChatsBtn')?.addEventListener('click', (e)=> askAndArchiveAllChats(e.currentTarget));
  document.getElementById('dataDeleteAllChatsBtn')?.addEventListener('click', (e)=> askAndResetAllChats(e.currentTarget));
  document.getElementById('archivedChatsModalCloseBtn')?.addEventListener('click', ()=> setArchivedChatsModalOpen(false));
  document.getElementById('archivedChatsModal')?.addEventListener('click', (e)=>{ if(e.target === e.currentTarget) setArchivedChatsModalOpen(false); });
  document.getElementById('activeUnarchiveBtn')?.addEventListener('click', ()=> restoreSessionFromArchive(store?.activeId, { toast:true }));
  document.getElementById("exportChatsBtn")?.addEventListener("click", exportChatsBackup);
  document.getElementById("importChatsBtn")?.addEventListener("click", ()=> document.getElementById("importChatsInput")?.click());
  document.getElementById("importChatsInput")?.addEventListener("change", async (e)=>{
    const file = e.target?.files?.[0];
    if(!file) return;
    try{ await importChatsBackupFile(file); }catch(err){ reportAppError(err?.message || err); }
    e.target.value = "";
  });
}

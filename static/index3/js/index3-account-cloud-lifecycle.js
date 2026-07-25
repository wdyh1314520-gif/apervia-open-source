/* Account/auth and cloud lifecycle.*/

const accountMenuWrapEl = document.getElementById("accountMenuWrap");
const accountCardEl = document.getElementById("accountCard");
const accountEmailEl = document.getElementById("accountEmail");
const accountSubLabelEl = document.getElementById("accountSubLabel");
const accountAvatarEl = document.getElementById("accountAvatar");
const accountMenuEl = document.getElementById("accountMenu");
const accountMenuEmailEl = document.getElementById("accountMenuEmail");
const accountMenuSubLabelEl = document.getElementById("accountMenuSubLabel");
const accountMenuAvatarEl = document.getElementById("accountMenuAvatar");
const accountMenuProfileBtnEl = document.getElementById("accountMenuProfileBtn");
const accountMenuPersonalizationBtnEl = document.getElementById("accountMenuPersonalizationBtn");
const accountMenuSettingsBtnEl = document.getElementById("accountMenuSettingsBtn");
const accountMenuAdminBtnEl = document.getElementById("accountMenuAdminBtn");
const accountProfileModalEl = document.getElementById("accountProfileModal");
const accountProfileCloseBtnEl = document.getElementById("accountProfileCloseBtn");
const accountProfileCancelBtnEl = document.getElementById("accountProfileCancelBtn");
const accountProfileSaveBtnEl = document.getElementById("accountProfileSaveBtn");
const accountProfileAvatarEl = document.getElementById("accountProfileAvatar");
const accountProfileCameraBtnEl = document.getElementById("accountProfileCameraBtn");
const accountProfileAvatarInputEl = document.getElementById("accountProfileAvatarInput");
const accountProfileDisplayNameEl = document.getElementById("accountProfileDisplayName");
const accountProfileUsernameEl = document.getElementById("accountProfileUsername");
const accountProfileEmailEl = document.getElementById("accountProfileEmail");
const accountSettingsStatusEl = document.getElementById("accountSettingsStatus");
const accountSettingsNameEl = document.getElementById("accountSettingsName");
const accountSettingsEmailEl = document.getElementById("accountSettingsEmail");
const accountSettingsLoginMethodEl = document.getElementById("accountSettingsLoginMethod");
const accountLanguageSelectEl = document.getElementById("accountLanguageSelect");
const accountVersionCurrentEl = document.getElementById("accountVersionCurrent");
const accountVersionStatusEl = document.getElementById("accountVersionStatus");
const accountVersionCheckBtnEl = document.getElementById("accountVersionCheckBtn");
const accountVersionReleaseLinkEl = document.getElementById("accountVersionReleaseLink");
const accountSettingsEditProfileBtnEl = document.getElementById("accountSettingsEditProfileBtn");
const accountSettingsLogoutBtnEl = document.getElementById("accountSettingsLogoutBtn");
const accountSettingsExportBtnEl = document.getElementById("accountSettingsExportBtn");
const accountSettingsDeleteBtnEl = document.getElementById("accountSettingsDeleteBtn");
const accountDeleteModalEl = document.getElementById("accountDeleteModal");
const accountDeleteCloseBtnEl = document.getElementById("accountDeleteCloseBtn");
const accountDeleteCancelBtnEl = document.getElementById("accountDeleteCancelBtn");
const accountDeleteConfirmBtnEl = document.getElementById("accountDeleteConfirmBtn");
const accountDeleteConfirmEmailEl = document.getElementById("accountDeleteConfirmEmail");
const accountDeleteErrorEl = document.getElementById("accountDeleteError");
const logoutBtnEl = document.getElementById("logoutBtn");
let authKickRedirecting = false;
let currentAccountProfile = null;
let currentAccountProfileEmail = "";
let accountProfileSaving = false;
let accountProfilePendingAvatarDataUrl = "";
let accountDeleteSubmitting = false;
let exitLogoutTriggered = false;
const ACCOUNT_PROFILE_UI_CACHE_KEY = 'webai_account_profile_ui_cache_v1';
const AUTH_ME_LAST_GOOD_KEY = 'webai_auth_last_good_v1';
const AUTH_ME_LAST_GOOD_TTL_MS = 24 * 3600 * 1000;
const AUTH_ME_SOFT_RETRY_MAX_MS = 120000;
let lastGoodAccountUiData = loadLastGoodAccountUiData();
let authMeSoftFailCount = 0;
let authMeRetryTimer = null;
let accountVersionCheckState = {
  status:'idle',
  currentVersion:'',
  latestVersion:'',
  releaseUrl:'',
};


function accountUiT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || String(fallback || key || '');
}

function accountInitialsFromText(text){
  const raw = String(text || '').trim();
  if(!raw) return 'AI';
  const beforeAt = raw.split('@')[0] || raw;
  const parts = beforeAt.replace(/[_\-.]+/g, ' ').split(/\s+/).map(x => x.trim()).filter(Boolean);
  if(parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  const chars = [...beforeAt.replace(/\s+/g, '')].filter(Boolean);
  return (chars.slice(0, 2).join('') || 'AI').toUpperCase();
}

const ACCOUNT_AVATAR_COLORS = Object.freeze([
  '#9a722f', '#6d7f3d', '#3f7c75', '#3f6f96',
  '#655c9a', '#875a91', '#a04f65', '#9a5d43',
  '#5d718a', '#4f7a55', '#806648', '#6f5b86',
]);

function accountDefaultDisplayNameFromEmail(email){
  const raw = String(email || '').trim();
  if(!raw) return '';
  return String(raw.split('@')[0] || raw).trim();
}

function accountAvatarColorFromText(text){
  const raw = String(text || '').trim().toLowerCase();
  if(!raw) return ACCOUNT_AVATAR_COLORS[0];
  let hash = 2166136261;
  for(const char of raw){
    hash ^= Number(char.codePointAt(0) || 0);
    hash = Math.imul(hash, 16777619);
  }
  return ACCOUNT_AVATAR_COLORS[(hash >>> 0) % ACCOUNT_AVATAR_COLORS.length];
}

function setAccountMenuOpen(open){
  const isOpen = !!open;
  if(accountMenuEl){
    accountMenuEl.classList.toggle('open', isOpen);
    accountMenuEl.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
  }
  if(accountCardEl) accountCardEl.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}
function toggleAccountMenu(){
  setAccountMenuOpen(!(accountMenuEl && accountMenuEl.classList.contains('open')));
}
function closeAccountMenu(){
  setAccountMenuOpen(false);
}
if(accountCardEl){
  accountCardEl.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    toggleAccountMenu();
  });
}
if(accountMenuProfileBtnEl){
  accountMenuProfileBtnEl.addEventListener('click', ()=>{
    closeAccountMenu();
    openAccountProfileModal();
  });
}
if(accountMenuPersonalizationBtnEl){
  accountMenuPersonalizationBtnEl.addEventListener('click', ()=>{
    closeAccountMenu();
    try{
      if(typeof openSettingsModal === 'function') openSettingsModal('personalization');
      else document.getElementById('openSettingsBtn')?.click?.();
    }catch(_){ }
  });
}
if(accountMenuSettingsBtnEl){
  accountMenuSettingsBtnEl.addEventListener('click', ()=>{
    closeAccountMenu();
    try{
      if(typeof openSettingsModal === 'function') openSettingsModal(settingsActiveTab);
      else document.getElementById('openSettingsBtn')?.click?.();
    }catch(_){ }
  });
}
if(accountMenuAdminBtnEl){
  accountMenuAdminBtnEl.addEventListener('click', ()=>{
    closeAccountMenu();
    window.location.href = '/admin';
  });
}
document.addEventListener('click', (e)=>{
  if(accountMenuWrapEl && accountMenuWrapEl.contains(e.target)) return;
  if(accountMenuEl && accountMenuEl.classList.contains('open')) closeAccountMenu();
});
document.addEventListener('keydown', (e)=>{
  if(e.key === 'Escape' && accountDeleteModalEl && accountDeleteModalEl.classList.contains('open')){
    e.preventDefault();
    setAccountDeleteModalOpen(false);
    return;
  }
  if(e.key === 'Escape' && accountProfileModalEl && accountProfileModalEl.classList.contains('open')){
    e.preventDefault();
    setAccountProfileModalOpen(false);
    return;
  }
  if(e.key === 'Escape' && accountMenuEl && accountMenuEl.classList.contains('open')){
    closeAccountMenu();
    return;
  }
});
function normalizeAccountProfile(profile){
  const row = profile && typeof profile === 'object' ? profile : {};
  return {
    display_name: String(row.display_name || row.displayName || row.name || '').trim().slice(0, 80),
    username: String(row.username || row.user_name || '').trim().replace(/^@+/, '').slice(0, 48),
    avatar_data_url: String(row.avatar_data_url || row.avatarDataUrl || row.avatar || '').trim(),
    email: String(row.email || '').trim(),
    email_masked: String(row.email_masked || '').trim(),
    ui_language: String(row.ui_language || row.uiLanguage || 'en').trim() === 'zh-CN' ? 'zh-CN' : 'en',
    has_custom_profile: !!row.has_custom_profile,
    updated_ts: Number(row.updated_ts || row.updatedAtTs || 0) || 0,
  };
}

function accountProfileHasCustom(profile){
  const row = normalizeAccountProfile(profile || {});
  return !!(row.display_name || row.username || row.avatar_data_url || row.has_custom_profile);
}

function accountProfileCacheMap(){
  try{
    const raw = localStorage.getItem(ACCOUNT_PROFILE_UI_CACHE_KEY);
    const obj = raw ? JSON.parse(raw) : {};
    return obj && typeof obj === 'object' ? obj : {};
  }catch(_){ return {}; }
}

function saveAccountProfileCacheMap(map){
  try{ localStorage.setItem(ACCOUNT_PROFILE_UI_CACHE_KEY, JSON.stringify(map && typeof map === 'object' ? map : {})); }catch(_){ }
}

function accountProfileEmailKeyFromData(data){
  const row = data && typeof data === 'object' ? data : {};
  const profile = normalizeAccountProfile(row.profile || currentAccountProfile || {});
  return normalizeAccountScopeEmail(row.scope_email || row.email || profile.email || currentAccountProfileEmail || '');
}

function loadCachedAccountProfile(email){
  const key = normalizeAccountScopeEmail(email || '');
  if(!key) return null;
  const map = accountProfileCacheMap();
  const cached = normalizeAccountProfile(map[key] || {});
  return accountProfileHasCustom(cached) ? cached : null;
}

function saveCachedAccountProfile(email, profile){
  const key = normalizeAccountScopeEmail(email || '');
  if(!key) return;
  const map = accountProfileCacheMap();
  const row = normalizeAccountProfile(profile || {});
  if(accountProfileHasCustom(row)){
    map[key] = { display_name: row.display_name, username: row.username, avatar_data_url: row.avatar_data_url, ui_language: row.ui_language, email: key, email_masked: row.email_masked || '', saved_at: Date.now() };
  }else{
    delete map[key];
  }
  saveAccountProfileCacheMap(map);
}

function mergeAccountProfileFallback(data){
  const row = data && typeof data === 'object' ? { ...data } : {};
  const profile = normalizeAccountProfile(row.profile || {});
  if(accountProfileHasCustom(profile)) return row;
  const emailKey = accountProfileEmailKeyFromData(row);
  const cached = loadCachedAccountProfile(emailKey);
  if(!cached) return row;
  row.profile = {
    ...profile,
    ...cached,
    email: profile.email || cached.email || emailKey,
    email_masked: profile.email_masked || cached.email_masked || row.email_masked || '',
    has_custom_profile: true,
  };
  return row;
}

function accountProfilePrimaryText(data){
  const row = data && typeof data === 'object' ? data : {};
  const profile = normalizeAccountProfile(row.profile || currentAccountProfile || {});
  const email = String(row.email || row.email_masked || profile.email || profile.email_masked || '').trim();
  const explicitName = String(profile.display_name || row.name || row.display_name || '').trim();
  return explicitName || accountDefaultDisplayNameFromEmail(email);
}

function accountProfileSecondaryText(data){
  const row = data && typeof data === 'object' ? data : {};
  const profile = normalizeAccountProfile(row.profile || currentAccountProfile || {});
  const emailText = String(profile.email_masked || row.email_masked || profile.email || row.email || '').trim();
  if(profile.username) return '@' + profile.username;
  if(emailText) return emailText;
  return '';
}

function applyAccountAvatar(el, avatarDataUrl, fallbackText, colorSeed = ''){
  if(!el) return;
  const imageUrl = String(avatarDataUrl || '').trim();
  const stableColorSeed = String(colorSeed || fallbackText || '').trim();
  el.classList.toggle('has-image', !!imageUrl);
  el.style.setProperty('--account-avatar-bg', accountAvatarColorFromText(stableColorSeed));
  el.style.backgroundImage = imageUrl ? `url("${imageUrl.replace(/"/g, '%22')}")` : '';
  el.textContent = imageUrl ? '' : (String(fallbackText || '').trim() || 'AI');
}

function applyAccountIdentityRow({ primary = '', secondary = '', initials = '', avatarDataUrl = '', avatarColorSeed = '' } = {}){
  const mainText = String(primary || '').trim() || '-';
  const subText = String(secondary || '').trim();
  const avatarText = String(initials || accountInitialsFromText(mainText)).trim() || 'AI';
  if(accountEmailEl) accountEmailEl.textContent = mainText;
  if(accountMenuEmailEl) accountMenuEmailEl.textContent = mainText;
  if(accountSubLabelEl) accountSubLabelEl.textContent = subText || '';
  if(accountMenuSubLabelEl) accountMenuSubLabelEl.textContent = subText || '';
  applyAccountAvatar(accountAvatarEl, avatarDataUrl, avatarText, avatarColorSeed || mainText);
  applyAccountAvatar(accountMenuAvatarEl, avatarDataUrl, avatarText, avatarColorSeed || mainText);
}

function applyAuthoritativeAccountProfile(data, opts={}){
  const row = data && typeof data === 'object' ? data : {};
  const email = normalizeAccountScopeEmail(row.email || row.scope_email || currentAccountProfileEmail || currentAccountEmail || '');
  if(currentAccountEmail && email && email !== normalizeAccountScopeEmail(currentAccountEmail)) return false;
  const profile = normalizeAccountProfile(row.profile || {});
  currentAccountProfile = profile;
  if(window.AperviaI18n && profile.ui_language){
    window.AperviaI18n.setLanguage(profile.ui_language).catch(() => null);
  }
  currentAccountProfileEmail = String(email || profile.email || currentAccountProfileEmail || '').trim();
  saveCachedAccountProfile(currentAccountProfileEmail || profile.email || '', profile);
  lastGoodAccountUiData = {
    ...(lastGoodAccountUiData || {}),
    ...row,
    email: currentAccountProfileEmail || profile.email || row.email || '',
    email_masked: profile.email_masked || row.email_masked || lastGoodAccountUiData?.email_masked || '',
    profile,
  };
  persistLastGoodAccountUiData(lastGoodAccountUiData);
  applyAccountUi(lastGoodAccountUiData);
  if(opts?.renderSettings !== false) renderAccountSettingsUi();
  if(opts?.populateModal === true) populateAccountProfileModal(lastGoodAccountUiData);
  return true;
}

function setAccountProfileModalOpen(open){
  if(!accountProfileModalEl) return;
  const isOpen = !!open;
  accountProfileModalEl.hidden = !isOpen;
  accountProfileModalEl.classList.toggle('open', isOpen);
  accountProfileModalEl.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
  if(isOpen) document.body.classList.add('modal-open');
  else if(!isSettingsModalOpen()) document.body.classList.remove('modal-open');
  if(!isOpen){
    accountProfileSaving = false;
    if(accountProfileSaveBtnEl) accountProfileSaveBtnEl.disabled = false;
  }
}

function populateAccountProfileModal(data){
  const row = data && typeof data === 'object' ? data : {};
  const profile = normalizeAccountProfile(row.profile || currentAccountProfile || {});
  const email = String(row.email || row.email_masked || currentAccountProfileEmail || profile.email || profile.email_masked || '').trim();
  const primary = accountProfilePrimaryText({ ...row, profile }) || accountDefaultDisplayNameFromEmail(email);
  if(accountProfileDisplayNameEl) accountProfileDisplayNameEl.value = profile.display_name || primary || '';
  if(accountProfileUsernameEl) accountProfileUsernameEl.value = profile.username || '';
  if(accountProfileEmailEl) accountProfileEmailEl.value = email || '';
  accountProfilePendingAvatarDataUrl = profile.avatar_data_url || '';
  applyAccountAvatar(accountProfileAvatarEl, accountProfilePendingAvatarDataUrl, accountInitialsFromText(primary || email), email || primary);
}

function readAccountAvatarFile(file){
  return new Promise((resolve, reject)=>{
    const reader = new FileReader();
    reader.onerror = ()=>reject(new Error(accountUiT('account.avatar_read_failed', null, '无法读取头像图片')));
    reader.onload = ()=>resolve(String(reader.result || ''));
    reader.readAsDataURL(file);
  });
}

function loadAccountAvatarImage(dataUrl){
  return new Promise((resolve, reject)=>{
    const img = new Image();
    img.onload = ()=>resolve(img);
    img.onerror = ()=>reject(new Error(accountUiT('account.avatar_open_failed', null, '头像图片无法打开')));
    img.src = dataUrl;
  });
}

async function prepareAccountAvatar(file){
  if(!file || !/^image\/(?:jpeg|png|webp)$/i.test(String(file.type || ''))) throw new Error(accountUiT('account.avatar_format_invalid', null, '请选择 JPG、PNG 或 WebP 图片'));
  if(Number(file.size || 0) > 12 * 1024 * 1024) throw new Error(accountUiT('account.avatar_too_large', null, '头像原图不能超过 12 MB'));
  const source = await readAccountAvatarFile(file);
  const img = await loadAccountAvatarImage(source);
  const sourceWidth = Math.max(1, Number(img.naturalWidth || img.width || 1));
  const sourceHeight = Math.max(1, Number(img.naturalHeight || img.height || 1));
  const side = Math.min(sourceWidth, sourceHeight);
  const sx = Math.max(0, Math.floor((sourceWidth - side) / 2));
  const sy = Math.max(0, Math.floor((sourceHeight - side) / 2));
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d', { alpha:true });
  if(!ctx) throw new Error(accountUiT('account.avatar_unsupported', null, '当前浏览器无法处理头像图片'));
  ctx.drawImage(img, sx, sy, side, side, 0, 0, 512, 512);
  let result = canvas.toDataURL('image/webp', .86);
  if(!String(result).startsWith('data:image/webp')) result = canvas.toDataURL('image/jpeg', .88);
  if(result.length > 1024 * 1024) result = canvas.toDataURL('image/jpeg', .72);
  if(result.length > 1024 * 1024) throw new Error(accountUiT('account.avatar_compressed_too_large', null, '头像压缩后仍然过大，请换一张图片'));
  return result;
}

async function fetchAccountProfile(){
  const res = await fetch('/api3/auth/profile', { cache:'no-store', credentials:'same-origin' });
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  return data || {};
}

async function saveAccountProfile(){
  if(accountProfileSaving) return;
  accountProfileSaving = true;
  if(accountProfileSaveBtnEl) accountProfileSaveBtnEl.disabled = true;
  try{
    const displayName = String(accountProfileDisplayNameEl?.value || '').trim();
    const username = String(accountProfileUsernameEl?.value || '').trim().replace(/^@+/, '');
    const res = await fetch('/api3/auth/profile', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      credentials:'same-origin',
      body:JSON.stringify({ display_name: displayName, username, avatar_data_url: accountProfilePendingAvatarDataUrl, ui_language: currentAccountProfile?.ui_language || window.AperviaI18n?.language || 'en' }),
    });
    const data = await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
    applyAuthoritativeAccountProfile(data, { renderSettings:true });
    setAccountProfileModalOpen(false);
    const savedText = accountUiT('account.profile_saved', null, 'Profile saved');
    try{ toast(savedText); }catch(_){ setStatus(savedText); }
  }catch(err){
    const saveFailedText = err?.message || accountUiT('common.save_failed', null, 'Save failed');
    try{ toast(saveFailedText); }catch(_){ setStatus(saveFailedText); }
  }finally{
    accountProfileSaving = false;
    if(accountProfileSaveBtnEl) accountProfileSaveBtnEl.disabled = false;
  }
}

async function openAccountProfileModal(){
  if(!accountProfileModalEl) return;
  populateAccountProfileModal(lastGoodAccountUiData || {});
  setAccountProfileModalOpen(true);
  setTimeout(()=>{ try{ accountProfileDisplayNameEl?.focus?.(); }catch(_){ } }, 0);
  try{
    const data = mergeAccountProfileFallback(await fetchAccountProfile());
    applyAuthoritativeAccountProfile(data, { renderSettings:true, populateModal:true });
  }catch(err){
    try{ console.warn('auth/profile refresh failed:', err); }catch(_){ }
  }
}

if(accountProfileCloseBtnEl) accountProfileCloseBtnEl.addEventListener('click', ()=>setAccountProfileModalOpen(false));
if(accountProfileCancelBtnEl) accountProfileCancelBtnEl.addEventListener('click', ()=>setAccountProfileModalOpen(false));
if(accountProfileSaveBtnEl) accountProfileSaveBtnEl.addEventListener('click', ()=>saveAccountProfile());
if(accountProfileCameraBtnEl) accountProfileCameraBtnEl.addEventListener('click', ()=>accountProfileAvatarInputEl?.click?.());
if(accountProfileAvatarInputEl){
  accountProfileAvatarInputEl.addEventListener('change', async ()=>{
    const file = accountProfileAvatarInputEl.files?.[0];
    accountProfileAvatarInputEl.value = '';
    if(!file) return;
    try{
      accountProfilePendingAvatarDataUrl = await prepareAccountAvatar(file);
      const seed = String(accountProfileDisplayNameEl?.value || accountProfileEmailEl?.value || '').trim();
      applyAccountAvatar(accountProfileAvatarEl, accountProfilePendingAvatarDataUrl, accountInitialsFromText(seed), accountProfileEmailEl?.value || seed);
    }catch(err){
      const errorText = err?.message || accountUiT('account.avatar_processing_failed', null, '头像处理失败');
      try{ toast(errorText); }catch(_){ setStatus(errorText); }
    }
  });
}
if(accountProfileModalEl){
  accountProfileModalEl.addEventListener('click', (e)=>{
    if(e.target === accountProfileModalEl) setAccountProfileModalOpen(false);
  });
}
if(accountProfileDisplayNameEl){
  accountProfileDisplayNameEl.addEventListener('input', ()=>{
    const seed = String(accountProfileDisplayNameEl.value || accountProfileEmailEl?.value || '').trim();
    applyAccountAvatar(accountProfileAvatarEl, accountProfilePendingAvatarDataUrl, accountInitialsFromText(seed), accountProfileEmailEl?.value || seed);
  });
}

function accountCurrentData(){
  return mergeAccountProfileFallback(lastGoodAccountUiData || { profile: currentAccountProfile || {}, email: currentAccountProfileEmail || '' });
}

function renderAccountVersionUi(row={}){
  const currentVersion = String(accountVersionCheckState.currentVersion || row?.app_version || '').trim();
  if(accountVersionCurrentEl) accountVersionCurrentEl.textContent = currentVersion || '-';

  let statusText = accountUiT('account.version_not_checked', null, 'Not checked');
  if(accountVersionCheckState.status === 'checking'){
    statusText = accountUiT('account.version_checking', null, 'Checking...');
  }else if(accountVersionCheckState.status === 'current'){
    statusText = accountUiT('account.version_latest', {version:accountVersionCheckState.latestVersion || currentVersion}, 'You have the latest version');
  }else if(accountVersionCheckState.status === 'update'){
    statusText = accountUiT('account.version_available', {version:accountVersionCheckState.latestVersion}, 'Version {version} is available');
  }else if(accountVersionCheckState.status === 'failed'){
    statusText = accountUiT('account.version_failed', null, 'Unable to check for updates');
  }
  if(accountVersionStatusEl) accountVersionStatusEl.textContent = statusText;
  if(accountVersionCheckBtnEl){
    accountVersionCheckBtnEl.disabled = accountVersionCheckState.status === 'checking';
    accountVersionCheckBtnEl.textContent = accountVersionCheckState.status === 'checking'
      ? accountUiT('account.version_checking', null, 'Checking...')
      : accountUiT('account.version_check', null, 'Check for updates');
  }
  if(accountVersionReleaseLinkEl){
    const visible = accountVersionCheckState.status === 'update' && /^https:\/\/github\.com\//i.test(accountVersionCheckState.releaseUrl);
    accountVersionReleaseLinkEl.hidden = !visible;
    accountVersionReleaseLinkEl.href = visible ? accountVersionCheckState.releaseUrl : '#';
    accountVersionReleaseLinkEl.textContent = accountUiT('account.version_release_notes', null, 'Release notes');
  }
}

async function checkAccountVersion(){
  if(accountVersionCheckState.status === 'checking') return;
  accountVersionCheckState = {...accountVersionCheckState, status:'checking', releaseUrl:''};
  renderAccountVersionUi(accountCurrentData());
  try{
    const response = await fetch('/api3/auth/version-check', {cache:'no-store', credentials:'same-origin'});
    const data = await response.json().catch(()=>({}));
    if(!response.ok || data?.ok !== true) throw new Error(data?.error || ('HTTP ' + response.status));
    accountVersionCheckState = {
      status:data.update_available ? 'update' : 'current',
      currentVersion:String(data.current_version || ''),
      latestVersion:String(data.latest_version || ''),
      releaseUrl:String(data.release_url || ''),
    };
  }catch(error){
    accountVersionCheckState = {...accountVersionCheckState, status:'failed', releaseUrl:''};
    try{ console.warn('release update check failed:', error); }catch(_){ }
  }
  renderAccountVersionUi(accountCurrentData());
}

function renderAccountSettingsUi(){
  const row = accountCurrentData();
  const profile = normalizeAccountProfile(row.profile || currentAccountProfile || {});
  const email = String(row.email || profile.email || currentAccountProfileEmail || row.email_masked || profile.email_masked || '').trim();
  const primary = accountProfilePrimaryText(row) || email || '-';
  const method = String(row.login_method || '').trim() === 'password'
    ? (window.AperviaI18n?.t('account.password_login') || '密码登录')
    : String(row.login_method_label || row.login_method || '-').trim();
  if(accountSettingsNameEl) accountSettingsNameEl.textContent = primary || '-';
  if(accountSettingsEmailEl) accountSettingsEmailEl.textContent = email || '-';
  if(accountSettingsLoginMethodEl) accountSettingsLoginMethodEl.textContent = method || '-';
  if(accountSettingsStatusEl) accountSettingsStatusEl.textContent = window.AperviaI18n?.t(row.logged_in === false ? 'account.signed_out' : 'account.current') || (row.logged_in === false ? '未登录' : '当前登录账号');
  if(accountLanguageSelectEl) accountLanguageSelectEl.value = profile.ui_language || window.AperviaI18n?.language || 'en';
  renderAccountVersionUi(row);
  const unavailable = !email || row.logged_in === false;
  if(accountSettingsExportBtnEl){
    accountSettingsExportBtnEl.disabled = unavailable;
    accountSettingsExportBtnEl.title = '';
  }
  if(accountSettingsDeleteBtnEl){
    accountSettingsDeleteBtnEl.disabled = unavailable;
    accountSettingsDeleteBtnEl.title = '';
  }
}

async function refreshAccountSettingsUi(){
  renderAccountSettingsUi();
  try{
    applyAuthoritativeAccountProfile(await fetchAccountProfile(), { renderSettings:true });
  }catch(err){
    try{ console.warn('account settings refresh failed:', err); }catch(_){ }
  }
}

function setAccountDeleteError(message){
  const text = String(message || '').trim();
  if(!accountDeleteErrorEl) return;
  accountDeleteErrorEl.hidden = !text;
  accountDeleteErrorEl.textContent = text;
}

function setAccountDeleteModalOpen(open){
  if(!accountDeleteModalEl) return;
  const isOpen = !!open;
  accountDeleteModalEl.hidden = !isOpen;
  accountDeleteModalEl.classList.toggle('open', isOpen);
  accountDeleteModalEl.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
  document.body.classList.toggle('modal-open', isOpen);
  if(isOpen){
    setAccountDeleteError('');
    const data = accountCurrentData();
    const email = String(data.email || currentAccountProfileEmail || '').trim();
    if(accountDeleteConfirmEmailEl){
      accountDeleteConfirmEmailEl.value = '';
      accountDeleteConfirmEmailEl.placeholder = email || accountUiT('account.current_email', null, '当前邮箱');
    }
    setTimeout(()=>{ try{ accountDeleteConfirmEmailEl?.focus?.(); }catch(_){ } }, 0);
  }else{
    accountDeleteSubmitting = false;
    if(accountDeleteConfirmBtnEl) accountDeleteConfirmBtnEl.disabled = false;
  }
}

async function deleteCurrentAccount(){
  if(accountDeleteSubmitting) return;
  const data = accountCurrentData();
  const email = String(data.email || currentAccountProfileEmail || '').trim();
  const confirmEmail = String(accountDeleteConfirmEmailEl?.value || '').trim();
  if(!email){
    setAccountDeleteError(accountUiT('account.email_not_found', null, '未找到当前账号邮箱'));
    return;
  }
  if(confirmEmail.toLowerCase() !== email.toLowerCase()){
    setAccountDeleteError(accountUiT('account.confirm_email_required', null, '请完整输入当前账号邮箱确认删除'));
    return;
  }
  accountDeleteSubmitting = true;
  if(accountDeleteConfirmBtnEl) accountDeleteConfirmBtnEl.disabled = true;
  setAccountDeleteError('');
  try{
    const res = await fetch('/api3/auth/delete-account', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      credentials:'same-origin',
      body:JSON.stringify({ confirm_email: confirmEmail }),
    });
    const payload = await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(payload?.error || ('HTTP ' + res.status));
    exitLogoutTriggered = true;
    currentAccountEmail = '';
    currentAccountProfile = null;
    currentAccountProfileEmail = '';
    currentCloudStoreUpdatedTs = 0;
    currentCloudStoreRevision = 0;
    cloudSyncQueuedPayload = '';
    lastCloudSyncedPayload = '';
    lastGoodAccountUiData = null;
    try{ localStorage.removeItem(AUTH_ME_LAST_GOOD_KEY); }catch(_){ }
    try{ toast(accountUiT('account.deletion_started', null, 'Account deletion period started')); }catch(_){ }
    const url = new URL('/login', location.origin);
    url.searchParams.set('message', accountUiT('account.deletion_login_message', null, 'Account deletion is pending. Sign in within 30 days to cancel.'));
    window.location.replace(url.pathname + url.search);
  }catch(err){
    accountDeleteSubmitting = false;
    if(accountDeleteConfirmBtnEl) accountDeleteConfirmBtnEl.disabled = false;
    setAccountDeleteError(err?.message || accountUiT('account.deletion_failed', null, 'Deletion failed'));
  }
}

if(accountSettingsEditProfileBtnEl) accountSettingsEditProfileBtnEl.addEventListener('click', ()=>openAccountProfileModal());
if(accountVersionCheckBtnEl) accountVersionCheckBtnEl.addEventListener('click', ()=>checkAccountVersion());
if(accountLanguageSelectEl){
  accountLanguageSelectEl.addEventListener('change', async () => {
    const previous = currentAccountProfile?.ui_language || window.AperviaI18n?.language || 'en';
    const language = accountLanguageSelectEl.value === 'en' ? 'en' : 'zh-CN';
    accountLanguageSelectEl.disabled = true;
    try{
      const data = await window.AperviaI18n.setLanguage(language, {persistAccount:true});
      applyAuthoritativeAccountProfile({
        ...(lastGoodAccountUiData || {}),
        profile: data?.profile || {...(currentAccountProfile || {}), ui_language:language},
      }, {renderSettings:true});
      if(activeAppAnnouncementConfig) closeAppAnnouncementModal();
      await refreshAccountUi().catch(() => null);
      try{ toast(window.AperviaI18n.t('account.language_saved')); }catch(_){ }
    }catch(error){
      await window.AperviaI18n?.setLanguage(previous).catch(() => null);
      accountLanguageSelectEl.value = previous;
      try{ toast(error?.message || window.AperviaI18n?.t('common.save_failed') || 'Save failed'); }catch(_){ }
    }finally{
      accountLanguageSelectEl.disabled = false;
    }
  });
}
if(accountSettingsLogoutBtnEl) accountSettingsLogoutBtnEl.addEventListener('click', ()=>logoutBtnEl?.click?.());
if(accountSettingsExportBtnEl) accountSettingsExportBtnEl.addEventListener('click', ()=>{ window.location.href = '/api3/auth/export-account'; });
if(accountSettingsDeleteBtnEl) accountSettingsDeleteBtnEl.addEventListener('click', ()=>setAccountDeleteModalOpen(true));
if(accountDeleteCloseBtnEl) accountDeleteCloseBtnEl.addEventListener('click', ()=>setAccountDeleteModalOpen(false));
if(accountDeleteCancelBtnEl) accountDeleteCancelBtnEl.addEventListener('click', ()=>setAccountDeleteModalOpen(false));
if(accountDeleteConfirmBtnEl) accountDeleteConfirmBtnEl.addEventListener('click', ()=>deleteCurrentAccount());
if(accountDeleteModalEl){
  accountDeleteModalEl.addEventListener('click', (e)=>{
    if(e.target === accountDeleteModalEl) setAccountDeleteModalOpen(false);
  });
}
if(accountDeleteConfirmEmailEl){
  accountDeleteConfirmEmailEl.addEventListener('input', ()=>setAccountDeleteError(''));
}

function shouldAutoExitLogout(){
  return !!(currentAccountEmail || String(accountEmailEl?.textContent || '').trim());
}
function sendExitLogout(){
  if(exitLogoutTriggered || !shouldAutoExitLogout()) return;
  exitLogoutTriggered = true;
  try{
    const body = JSON.stringify({ auto_exit:true });
    if(navigator.sendBeacon){
      const blob = new Blob([body], { type:'application/json' });
      if(navigator.sendBeacon('/api3/auth/logout', blob)) return;
    }
    fetch('/api3/auth/logout', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body,
      keepalive:true,
      credentials:'same-origin',
    }).catch(()=>{});
  }catch(_){ }
}

function buildLoginRedirectUrl(message){
  const nextPath = (!location.pathname || location.pathname.startsWith('/login'))
    ? '/'
    : ((location.pathname || '/') + (location.search || '') + (location.hash || ''));
  const url = new URL('/login', location.origin);
  url.searchParams.set('next', nextPath || '/');
  const msg = String(message || '').trim();
  if(msg) url.searchParams.set('message', msg);
  return url.pathname + url.search;
}
function isForcedLoginPayload(payload){
  const data = payload && typeof payload === 'object' ? payload : {};
  const error = String(data.error || data.code || '').trim();
  const reason = String(data.reason_code || '').trim();
  if(data.login_required === true) return true;
  if(['login_required', 'account_disabled', 'account_deleted', 'account_delete_pending', 'login_disabled'].includes(error)) return true;
  if(['login_disabled', 'account_blacklisted', 'account_disabled', 'account_deleted', 'account_delete_pending'].includes(reason)) return true;
  return false;
}

function preserveLocalConversationStateForAuthSuspended(message=''){
  const email = normalizeAccountScopeEmail(currentAccountEmail || currentAccountProfileEmail || '');
  try{
    if(isValidStoreShape(store)){
      for(const session of Object.values(store.sessions || {})){
        if(!session || typeof session !== 'object') continue;
        try{
          if(typeof cloudSyncEnsureConversationSyncFields === 'function') cloudSyncEnsureConversationSyncFields(session, session.id || '', { status:'auth_suspended' });
          if(typeof cloudSyncSessionHasProtectedLocalState === 'function' && cloudSyncSessionHasProtectedLocalState(session)){
            session.syncStatus = String(session.syncStatus || session.sync_status || 'auth_suspended').trim() || 'auth_suspended';
            session.sync_status = session.syncStatus;
            if(session.conversationRecovery && typeof session.conversationRecovery === 'object') session.conversationRecovery.status = session.syncStatus;
          }
        }catch(_){ }
      }
      const normalized = buildPersistableStorePayload(store);
      persistStorePayloadLocally(normalized.payload, normalized.slim, email || currentAccountEmail);
      if(email){
        markScopedStoreDirty(email, { localUpdatedAt: storeLatestUpdatedAtMs(store) });
        writeScopedCloudSyncPending(email, String(cloudSyncQueuedPayload || normalized.payload || '').trim(), {
          lastReason: 'auth_suspended',
          retryCount: cloudSyncRetryCount,
          localUpdatedAt: storeLatestUpdatedAtMs(store),
          authSuspended:true,
        });
        writeScopedStoreMeta(email, {
          authStatus: 'auth_suspended',
          auth_status: 'auth_suspended',
          authSuspendedAt: Date.now(),
          authMessage: String(message || '').trim(),
        });
      }
    }
  }catch(err){
    try{ console.warn('preserve local conversation state for auth suspended failed:', err); }catch(_){ }
  }
}

function handleForcedLogin(payload, fallbackMessage){
  const data = payload && typeof payload === 'object' ? payload : {};
  const needLogin = isForcedLoginPayload(data);
  if(!needLogin) return false;
  const message = String(data.message || fallbackMessage || '').trim();
  if(authKickRedirecting) return true;
  preserveLocalConversationStateForAuthSuspended(message || fallbackMessage || '');
  authKickRedirecting = true;
  const finalMessage = message || accountUiT('account.session_expired', null, '当前登录已失效，请重新登录');
  try{ toast(finalMessage); }catch(_){ }
  window.location.replace(buildLoginRedirectUrl(finalMessage));
  return true;
}

function applyAccountUi(data){
  const row = mergeAccountProfileFallback(data && typeof data === 'object' ? data : {});
  const profile = normalizeAccountProfile(row.profile || currentAccountProfile || {});
  currentAccountProfile = profile;
  if(window.AperviaI18n && profile.ui_language){
    window.AperviaI18n.setLanguage(profile.ui_language).catch(() => null);
  }
  const email = String(row.email || row.email_masked || profile.email || profile.email_masked || '').trim();
  currentAccountProfileEmail = String(row.email || profile.email || email || currentAccountProfileEmail || '').trim();
  const primary = accountProfilePrimaryText(row) || email;
  const secondary = accountProfileSecondaryText(row);
  const initials = accountInitialsFromText(primary || email);
  applyAccountIdentityRow({ primary, secondary, initials, avatarDataUrl: profile.avatar_data_url, avatarColorSeed: email || primary });
  if(accountCardEl) accountCardEl.classList.toggle("is-hidden", !(primary || email));
  if(accountMenuAdminBtnEl){
    const isAdmin = String(row.role || row.user?.role || '').trim().toLowerCase() === 'admin' || String(row.admin_url || '').trim() === '/admin';
    accountMenuAdminBtnEl.hidden = !isAdmin;
  }
  if(!(primary || email)) closeAccountMenu();
}

function persistLastGoodAccountUiData(data){
  try{
    if(!data || typeof data !== 'object' || (!data.email && !data.email_masked && !data.scope_email)) return;
    localStorage.setItem(AUTH_ME_LAST_GOOD_KEY, JSON.stringify({ data, savedAt: Date.now() }));
  }catch(_){ }
}

function loadLastGoodAccountUiData(){
  try{
    const raw = localStorage.getItem(AUTH_ME_LAST_GOOD_KEY);
    if(!raw) return null;
    const obj = JSON.parse(raw);
    const savedAt = Number(obj?.savedAt || 0) || 0;
    if(savedAt && Date.now() - savedAt > AUTH_ME_LAST_GOOD_TTL_MS){
      localStorage.removeItem(AUTH_ME_LAST_GOOD_KEY);
      return null;
    }
    return (obj?.data && typeof obj.data === 'object') ? obj.data : null;
  }catch(_){ return null; }
}

function scheduleAuthUiSoftRetry(){
  if(authKickRedirecting || authMeRetryTimer) return;
  let delay = stableBackoffMs(authMeSoftFailCount, 3500, AUTH_ME_SOFT_RETRY_MAX_MS);
  if(isNavigatorOffline()) delay = Math.max(delay, 15000 + stableJitterMs(3000));
  if(document.visibilityState === 'hidden') delay = Math.max(delay, 12000 + stableJitterMs(2500));
  if(anyStreamingActive()) delay = Math.max(delay, 8000 + stableJitterMs(1200));
  authMeRetryTimer = setTimeout(()=>{
    authMeRetryTimer = null;
    refreshAccountUi().catch(()=>{});
  }, Math.max(2000, Math.min(AUTH_ME_SOFT_RETRY_MAX_MS, delay)));
}

try{ if(lastGoodAccountUiData) applyAccountUi(lastGoodAccountUiData); }catch(_){ }

const dismissedAppAnnouncementIds = new Set();
let activeAppAnnouncementConfig = null;
let appAnnouncementReturnFocus = null;
let appAnnouncementAckInFlight = false;
let appAnnouncementCloseTimer = 0;

function appAnnouncementReducedMotion(){
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
}

function clearAppAnnouncementEffects(mask){
  if(appAnnouncementCloseTimer){
    clearTimeout(appAnnouncementCloseTimer);
    appAnnouncementCloseTimer = 0;
  }
  mask?.classList.remove('closing', 'celebrating');
  mask?.querySelector('.app-announcement-confetti')?.remove();
}

function createAppAnnouncementCelebration(mask){
  if(!mask || appAnnouncementReducedMotion()) return;
  const burst = document.createElement('div');
  burst.className = 'app-announcement-confetti';
  burst.setAttribute('aria-hidden', 'true');
  const vectors = [
    [-210,-145,-160],[-158,-212,-110],[-86,-242,-62],[-18,-224,-20],
    [62,-238,28],[138,-205,72],[206,-142,126],[225,-55,166],
    [198,38,208],[134,92,246],[62,118,286],[-18,126,326],
    [-92,108,365],[-164,72,405],[-218,18,452],[-232,-68,506],
  ];
  vectors.forEach(([x,y,rotation], index) => {
    const piece = document.createElement('i');
    piece.style.setProperty('--announcement-x', `${x}px`);
    piece.style.setProperty('--announcement-y', `${y}px`);
    piece.style.setProperty('--announcement-r', `${rotation}deg`);
    piece.style.setProperty('--announcement-delay', `${(index % 4) * 18}ms`);
    piece.dataset.shape = index % 3 === 0 ? 'dot' : 'bar';
    burst.appendChild(piece);
  });
  mask.appendChild(burst);
}

function normalizeAppAnnouncementConfig(value){
  const row = value && typeof value === 'object' ? value : {};
  const id = String(row.id || '').trim();
  const title = String(row.title || '').trim();
  const body = String(row.body || '').trim();
  const buttonText = String(row.button_text || '').trim() || window.AperviaI18n?.t('announcement.confirm') || '我知道了';
  if(!row.enabled || row.acknowledged || !id || !title || !body) return null;
  return {
    id,
    title,
    body,
    buttonText,
    version: String(row.version || id).trim(),
    categoryLabel: String(row.category_label || window.AperviaI18n?.t('announcement.update') || '版本更新').trim(),
    publishedAt: String(row.published_at || '').trim(),
  };
}

function ensureAppAnnouncementModal(){
  let mask = document.getElementById('appAnnouncementModal');
  if(mask) return mask;
  mask = document.createElement('div');
  mask.id = 'appAnnouncementModal';
  mask.className = 'app-announcement-modal-mask';
  mask.setAttribute('aria-hidden', 'true');
  mask.innerHTML = `
    <div class="app-announcement-modal" role="dialog" aria-modal="true" aria-labelledby="appAnnouncementTitle" aria-describedby="appAnnouncementBody">
      <div class="app-announcement-accent" aria-hidden="true"></div>
      <div class="app-announcement-glow" aria-hidden="true"><i></i><i></i><i></i></div>
      <header class="app-announcement-head">
        <div class="app-announcement-heading">
          <span class="app-announcement-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none"><path d="M5.5 13.5V10a6.5 6.5 0 0 1 13 0v3.5l1.4 2.2a1 1 0 0 1-.84 1.55H4.94a1 1 0 0 1-.84-1.55l1.4-2.2Z"/><path d="M9.5 19a2.75 2.75 0 0 0 5 0"/><path d="M18.5 4.25 20 2.75M5.5 4.25 4 2.75"/></svg>
          </span>
          <div class="app-announcement-heading-copy">
             <div id="appAnnouncementEyebrow" class="app-announcement-eyebrow">Apervia · <span data-i18n="announcement.product">产品公告</span></div>
            <h2 id="appAnnouncementTitle" class="app-announcement-title"></h2>
          </div>
        </div>
         <button id="appAnnouncementClose" class="app-announcement-close" type="button" aria-label="关闭公告" data-i18n-aria-label="announcement.close">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>
        </button>
      </header>
       <div id="appAnnouncementMeta" class="app-announcement-meta" aria-label="公告信息" data-i18n-aria-label="announcement.info"></div>
      <div class="app-announcement-content">
        <div id="appAnnouncementBody" class="app-announcement-body"></div>
      </div>
      <footer class="app-announcement-actions">
        <div class="app-announcement-once-note">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"/><path d="M12 10v6M12 7.25v.5"/></svg>
           <span data-i18n="announcement.once">确认后，本账号不再重复展示</span>
        </div>
         <button id="appAnnouncementConfirm" class="app-announcement-confirm" type="button"><span id="appAnnouncementConfirmText">我知道了</span><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button>
      </footer>
    </div>`;
  mask.addEventListener('click', (event) => {
    if(event.target === mask) closeAppAnnouncementModal({ dismiss:true });
  });
  document.body.appendChild(mask);
  return mask;
}

function closeAppAnnouncementModal({ dismiss=false, celebrate=false }={}){
  const mask = document.getElementById('appAnnouncementModal');
  const closingId = String(activeAppAnnouncementConfig?.id || '').trim();
  if(dismiss && closingId) dismissedAppAnnouncementIds.add(closingId);
  activeAppAnnouncementConfig = null;
  document.documentElement.classList.remove('app-announcement-open');
  document.removeEventListener('keydown', handleAppAnnouncementKeydown);
  const finishClose = () => {
    if(mask){
      mask.classList.remove('open', 'closing', 'celebrating');
      mask.setAttribute('aria-hidden', 'true');
      mask.querySelector('.app-announcement-confetti')?.remove();
    }
    if(appAnnouncementReturnFocus && typeof appAnnouncementReturnFocus.focus === 'function'){
      try{ appAnnouncementReturnFocus.focus({ preventScroll:true }); }catch(_){ }
    }
    appAnnouncementReturnFocus = null;
    appAnnouncementCloseTimer = 0;
  };
  if(!mask || appAnnouncementReducedMotion()){
    finishClose();
    return;
  }
  mask.classList.add('closing');
  if(celebrate){
    mask.classList.add('celebrating');
    createAppAnnouncementCelebration(mask);
  }
  appAnnouncementCloseTimer = window.setTimeout(finishClose, celebrate ? 760 : 260);
}

function handleAppAnnouncementKeydown(event){
  if(event.key !== 'Escape' || !activeAppAnnouncementConfig) return;
  event.preventDefault();
  closeAppAnnouncementModal({ dismiss:true });
}

async function acknowledgeAppAnnouncement(config){
  if(appAnnouncementAckInFlight || !config?.id) return;
  const confirmBtn = document.getElementById('appAnnouncementConfirm');
  const confirmText = document.getElementById('appAnnouncementConfirmText');
  appAnnouncementAckInFlight = true;
  if(confirmBtn) confirmBtn.disabled = true;
  if(confirmText) confirmText.textContent = window.AperviaI18n?.t('announcement.confirming') || '正在确认…';
  try{
    const response = await fetch('/api3/auth/release-announcement/acknowledge', {
      method:'POST',
      cache:'no-store',
      headers:{ 'Content-Type':'application/json' },
      body:JSON.stringify({ id:config.id }),
    });
    const data = await response.json().catch(() => ({}));
    if(!response.ok) throw new Error(data.message || data.error || window.AperviaI18n?.t('announcement.confirm_failed') || '确认失败，请稍后重试');
    closeAppAnnouncementModal({ celebrate:true });
  }catch(error){
    if(typeof toastError === 'function') toastError(error?.message || window.AperviaI18n?.t('announcement.confirm_failed') || '确认失败，请稍后重试');
    if(confirmBtn) confirmBtn.disabled = false;
    if(confirmText) confirmText.textContent = config.buttonText || accountUiT('announcement.confirm', null, 'Got it');
  }finally{
    appAnnouncementAckInFlight = false;
  }
}

function showAppAnnouncementModal(config){
  const mask = ensureAppAnnouncementModal();
  clearAppAnnouncementEffects(mask);
  const titleEl = document.getElementById('appAnnouncementTitle');
  const bodyEl = document.getElementById('appAnnouncementBody');
  const eyebrowEl = document.getElementById('appAnnouncementEyebrow');
  const metaEl = document.getElementById('appAnnouncementMeta');
  const closeBtn = document.getElementById('appAnnouncementClose');
  const confirmBtn = document.getElementById('appAnnouncementConfirm');
  const confirmText = document.getElementById('appAnnouncementConfirmText');
  if(eyebrowEl) eyebrowEl.textContent = `Apervia · ${config.categoryLabel || window.AperviaI18n?.t('announcement.update') || '版本更新'}`;
  if(titleEl) titleEl.textContent = config.title || window.AperviaI18n?.t('announcement.latest') || '最近更新内容';
  if(metaEl){
    const meta = [config.version, config.publishedAt].filter(Boolean);
    metaEl.innerHTML = meta.map(item => `<span>${escapeHtml(item)}</span>`).join('');
    metaEl.hidden = !meta.length;
  }
  if(bodyEl){
    if(typeof renderTextSectionHtml === 'function') bodyEl.innerHTML = renderTextSectionHtml(config.body || '');
    else bodyEl.textContent = config.body || '';
  }
  if(closeBtn) closeBtn.onclick = () => closeAppAnnouncementModal({ dismiss:true });
  if(confirmBtn){
    confirmBtn.disabled = false;
    if(confirmText) confirmText.textContent = config.buttonText || accountUiT('announcement.confirm', null, 'Got it');
    confirmBtn.onclick = () => acknowledgeAppAnnouncement(config);
  }
  appAnnouncementReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  activeAppAnnouncementConfig = config;
  document.documentElement.classList.add('app-announcement-open');
  document.removeEventListener('keydown', handleAppAnnouncementKeydown);
  document.addEventListener('keydown', handleAppAnnouncementKeydown);
  mask.classList.remove('closing', 'celebrating');
  mask.classList.add('open');
  mask.setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => {
    try{ confirmBtn?.focus({ preventScroll:true }); }catch(_){ }
  });
}

function maybeShowAppAnnouncementFromAuthData(data){
  const config = normalizeAppAnnouncementConfig(data?.release_announcement);
  if(!config) return;
  if(dismissedAppAnnouncementIds.has(config.id) || activeAppAnnouncementConfig?.id === config.id) return;
  setTimeout(() => {
    if(dismissedAppAnnouncementIds.has(config.id)) return;
    showAppAnnouncementModal(config);
  }, 220);
}

async function refreshAccountUi(){
  if(!accountCardEl || authKickRedirecting) return null;
  try{
    const ctl = new AbortController();
    const timeoutId = setTimeout(()=>{
      try{ ctl.abort('auth_me_timeout'); }catch(_){ }
    }, computeWeakFetchTimeoutMs('auth_me'));
    let res = null;
    let data = {};
    try{
      res = await fetch('/api3/auth/me', { cache:'no-store', credentials:'same-origin', signal: ctl.signal });
      data = await res.json().catch(()=>({}));
    }finally{
      try{ clearTimeout(timeoutId); }catch(_){ }
    }
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '该账号疑似滥用，已被停用')) return null;
    if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
    if(data?.login_required && !data?.logged_in){
      handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录');
      return null;
    }
    authMeSoftFailCount = 0;
    const mergedData = mergeAccountProfileFallback(data && typeof data === 'object' ? data : {});
    lastGoodAccountUiData = mergedData;
    persistLastGoodAccountUiData(lastGoodAccountUiData);
    applyAccountUi(mergedData || {});
    const email = normalizeAccountScopeEmail(mergedData?.scope_email || mergedData?.email || '');
    if(data?.logged_in && email){
      if(currentAccountEmail !== email || lastLoadedStoreScopeKey !== buildScopedStoreKey(email)){
        await switchStoreScope(email);
      }
      maybeShowAppAnnouncementFromAuthData(data);
    }else if(currentAccountEmail){
      await switchStoreScope('');
    }
    return data || null;
  }catch(err){
    authMeSoftFailCount += 1;
    if(!lastGoodAccountUiData) lastGoodAccountUiData = loadLastGoodAccountUiData();
    if(lastGoodAccountUiData){
      applyAccountUi(lastGoodAccountUiData);
    }
    scheduleAuthUiSoftRetry();
    try{ console.warn('auth/me soft refresh failed:', err); }catch(_){ }
    return lastGoodAccountUiData || null;
  }
}

let stableForegroundRecoveryLastAt = 0;
let accountCloudRefreshPollInFlight = false;
function triggerStableForegroundRecovery(reason='foreground'){
  if(authKickRedirecting) return;
  const now = Date.now();
  if(now - stableForegroundRecoveryLastAt < 2500) return;
  stableForegroundRecoveryLastAt = now;
  try{ if(authMeRetryTimer){ clearTimeout(authMeRetryTimer); authMeRetryTimer = null; } }catch(_){ }
  refreshAccountUi().catch(()=>{});
  if(currentAccountEmail){
    try{
      const pendingPayload = getScopedCloudSyncPendingPayload(currentAccountEmail);
      if(pendingPayload){
        restorePendingCloudSyncForScope(currentAccountEmail, {
          payload: pendingPayload,
          reason: String(reason || 'foreground'),
          delayMs: isNavigatorOffline() ? 15000 : 700,
        });
      }
    }catch(_){ }
    try{ if(!isNavigatorOffline()) refreshCloudStoreIfChanged(); }catch(_){ }
  }
  try{ if(typeof retryPendingInlineImages === 'function') retryPendingInlineImages(reason); }catch(_){ }
}

function applyFetchedCloudStoreSnapshot(data, opts={}){
  const serverData = (data && typeof data === 'object') ? data : {};
  const remoteTs = Number(serverData?.updated_ts || 0) || 0;
  if(!remoteTs) return false;
  const remoteStore = (serverData?.store && isValidStoreShape(serverData.store)) ? serverData.store : null;
  if(!remoteStore) return false;
  try{ if(typeof receiveCloudSessionDeleteTombstones === 'function') receiveCloudSessionDeleteTombstones(serverData, currentAccountEmail); }catch(_){ }
  try{ if(typeof cloudSyncRehydrateStoreBodiesInPlace === 'function') cloudSyncRehydrateStoreBodiesInPlace(remoteStore); }catch(_){ }
  try{ if(typeof applySessionDeleteTombstonesToStore === 'function') applySessionDeleteTombstonesToStore(remoteStore, currentAccountEmail, (typeof extractCloudSessionDeleteTombstones === 'function') ? extractCloudSessionDeleteTombstones(serverData) : null); }catch(_){ }
  const o = opts || {};
  if(o.ignoreLocalActivity !== true && shouldDeferCloudRefreshForLocalState()) return false;
  if(storeHasPendingAssistantSnapshot(store)) return false;
  if(o.requireNewer !== false && remoteTs <= Number(currentCloudStoreUpdatedTs || 0)) return false;

  const preferredActiveId = String(o.preserveActiveId || '').trim();
  const activeBeforeApply = String(store?.activeId || '').trim();
  const visualBefore = captureActiveChatVisualState();
  const composerSnapshot = captureComposerDraftForStoreApply(preferredActiveId || activeBeforeApply);
  const rememberedScroll = preferredActiveId ? (chatScrollMemory[preferredActiveId] || null) : null;
  const draftId = preferredActiveId || activeBeforeApply;
  if(draftId){
    try{ saveCurrentChatScrollState(draftId); }catch(_){ }
    try{
      const ownerId = (typeof getComposerInputOwnerSessionId === 'function') ? String(getComposerInputOwnerSessionId() || '').trim() : '';
      const targetDraftId = ownerId || draftId;
      if(targetDraftId && store?.sessions?.[targetDraftId]) persistComposerDraft(targetDraftId, inputEl?.value || '');
    }catch(_){ }
  }

  let nextStore = remoteStore;
  if(preferredActiveId && remoteStore.sessions?.[preferredActiveId] && remoteStore.activeId !== preferredActiveId){
    const cloned = cloneStoreDeep(remoteStore);
    if(cloned && cloned.sessions?.[preferredActiveId]){
      cloned.activeId = preferredActiveId;
      nextStore = cloned;
    }
  }

  try{ if(typeof applySessionDeleteTombstonesToStore === 'function') applySessionDeleteTombstonesToStore(store, currentAccountEmail); }catch(_){ }
  nextStore = cloudSyncMergeStorePreservingLiveLocal(nextStore, store, { preserveActiveId: preferredActiveId || activeBeforeApply, preserveActive:true });
  try{ if(typeof applySessionDeleteTombstonesToStore === 'function') applySessionDeleteTombstonesToStore(nextStore, currentAccountEmail); }catch(_){ }
  applyComposerDraftSnapshotToStore(composerSnapshot, nextStore);
  store = nextStore;
  enforceAccountStoreLimitsInPlace('silent');
  updateAccountChatLimits(serverData?.limits);
  currentCloudStoreUpdatedTs = remoteTs;
  const remoteRevision = Number(serverData?.server_revision ?? serverData?.revision ?? 0) || 0;
  if(remoteRevision > 0) currentCloudStoreRevision = remoteRevision;
  lastLoadedStoreScopeKey = buildScopedStoreKey(currentAccountEmail);
  const { slim, payload } = buildPersistableStorePayload(store);
  persistStorePayloadLocally(payload, slim, currentAccountEmail);
  clearScopedStoreDirty(currentAccountEmail, { cloudUpdatedTs: remoteTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
  lastCloudSyncedPayload = payload;
  const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
  if(chatDomUpdated) restoreComposerDraft(store.activeId);
  if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
  if(rememberedScroll){
    requestAnimationFrame(()=>{
      if(String(store?.activeId || '').trim() !== String(preferredActiveId || '').trim()) return;
      try{ restoreChatScrollState(rememberedScroll); }catch(_){ }
    });
  }
  const statusText = String(o.statusText || '').trim();
  if(statusText) setStatus(statusText);
  return true;
}

const SESSION_SWITCH_HYDRATE_MIN_INTERVAL_MS = 2500;
let sessionSwitchHydrateInFlight = false;
let sessionSwitchHydrateInFlightId = '';
let sessionSwitchHydrateToken = 0;
let sessionSwitchHydrateLastAt = 0;
let sessionSwitchHydrateLastId = '';

function cancelSessionCloudHydration(sessionId=''){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  let changed = false;
  if(sessionSwitchHydrateInFlightId === sid){
    sessionSwitchHydrateToken += 1;
    sessionSwitchHydrateInFlight = false;
    sessionSwitchHydrateInFlightId = '';
    changed = true;
  }
  if(sessionSwitchHydrateLastId === sid){
    sessionSwitchHydrateLastId = '';
    sessionSwitchHydrateLastAt = 0;
    changed = true;
  }
  try{ clearActiveCloudSessionHydrateTimer(sid); }catch(_){ }
  return changed;
}


async function hydrateActiveSessionAfterSwitch(sessionId, opts={}){
  const targetId = String(sessionId || '').trim();
  if(!targetId || !currentAccountEmail || authKickRedirecting) return false;
  if(!store.sessions?.[targetId]) return false;
  const o = opts || {};
  const force = !!o.force;
  const nowTs = Date.now();
  if(sessionSwitchHydrateInFlight && sessionSwitchHydrateInFlightId === targetId) return false;
  if(sessionSwitchHydrateLastId === targetId && (nowTs - sessionSwitchHydrateLastAt) < SESSION_SWITCH_HYDRATE_MIN_INTERVAL_MS) return false;
  if(!force){
    if(sessionSwitchHydrateInFlight || cloudSyncInFlight || cloudSyncQueuedPayload) return false;
    if(anyStreamingActive() || storeHasPendingAssistantSnapshot(store)) return false;
    if(readScopedStoreMeta(currentAccountEmail)?.dirty && !isCloudSessionStub(store.sessions?.[targetId])) return false;
  }
  sessionSwitchHydrateLastId = targetId;
  sessionSwitchHydrateLastAt = nowTs;

  const token = ++sessionSwitchHydrateToken;
  sessionSwitchHydrateInFlight = true;
  sessionSwitchHydrateInFlightId = targetId;
  const shouldBlockChatForHydrate = !!(isCloudSessionStub(store?.sessions?.[targetId]) && !chatHasVisibleContentForCenterLoading());
  if(shouldBlockChatForHydrate) setChatCenterLoadingForced(true);
  try{
    const data = await fetchCloudSessionSnapshot(targetId);
    if(token !== sessionSwitchHydrateToken) return false;
    if(String(store?.activeId || '').trim() !== targetId) return false;
    if(data?.session){
      return applyCloudSessionSnapshotToStore(data, targetId, {
        force,
        preserveActive:true,
        statusText: o.statusText || '已加载当前会话',
      });
    }
    const fallback = await fetchCloudStoreSnapshot();
    if(token !== sessionSwitchHydrateToken) return false;
    if(String(store?.activeId || '').trim() !== targetId) return false;
    const remoteStore = (fallback?.store && isValidStoreShape(fallback.store)) ? fallback.store : null;
    if(!remoteStore?.sessions?.[targetId]) return false;
    return applyFetchedCloudStoreSnapshot(fallback, {
      requireNewer: false,
      preserveActiveId: targetId,
      statusText: o.statusText || '已更新当前会话',
    });
  }catch(e){
    console.warn('hydrate active session after switch failed:', e);
    if(isCloudSessionStub(store.sessions?.[targetId])){
      try{ setStatus(accountUiT('sync.conversation_loading_retry', null, 'This conversation is still loading. Apervia will retry when the network is available.')); }catch(_){ }
      setTimeout(()=>{
        if(String(store?.activeId || '').trim() === targetId && !authKickRedirecting){
          hydrateActiveSessionAfterSwitch(targetId, { force:true, statusText:'已加载当前会话' }).catch(()=>{});
        }
      }, stableBackoffMs(1, 1800, 12000));
    }
    return false;
  }finally{
    if(token === sessionSwitchHydrateToken){
      sessionSwitchHydrateInFlight = false;
      sessionSwitchHydrateInFlightId = '';
    }
    if(shouldBlockChatForHydrate) setChatCenterLoadingForced(false);
  }
}
function hasLocalRuntimeActivityForCloudRefresh(){
  try{ if(_saveStoreTimer) return true; }catch(_){ }
  try{ if(cloudSyncInFlight || cloudSyncQueuedPayload) return true; }catch(_){ }
  try{ if(anyStreamingActive() || storeHasPendingAssistantSnapshot(store)) return true; }catch(_){ }
  try{
    for(const sid of Object.keys(sessionRuntime || {})){
      const rt = sessionRuntime[sid] || {};
      if(rt.streaming) return true;
      if(String(rt.statusText || rt.draftText || rt.draftProcessText || '').trim()) return true;
      if(Array.isArray(rt.draftFiles) && rt.draftFiles.length) return true;
      if(Array.isArray(rt.draftImageReplies) && rt.draftImageReplies.length) return true;
      if(Array.isArray(rt.reasoning) && rt.reasoning.length) return true;
      if(Array.isArray(rt.sources) && rt.sources.length) return true;
    }
  }catch(_){ }
  try{
    for(const session of Object.values(store?.sessions || {})){
      if(!session || typeof session !== 'object') continue;
      if(String(session.pendingJobId || '').trim()) return true;
      if(sessionHasPendingAssistantSnapshot(session)) return true;
    }
  }catch(_){ }
  return false;
}

function shouldDeferCloudRefreshForLocalState(){
  if(!currentAccountEmail || authKickRedirecting) return true;
  try{ if(getActiveTemporarySession()) return true; }catch(_){ }
  try{ if(getScopedCloudSyncPendingPayload(currentAccountEmail)) return true; }catch(_){ }
  try{
    if(readScopedStoreMeta(currentAccountEmail)?.dirty){
      return hasLocalRuntimeActivityForCloudRefresh();
    }
  }catch(_){ }
  return hasLocalRuntimeActivityForCloudRefresh();
}

async function refreshCloudStoreIfChanged(){
  if(!currentAccountEmail || authKickRedirecting) return;
  if(shouldDeferCloudRefreshForLocalState()){
    const pendingPayload = getScopedCloudSyncPendingPayload(currentAccountEmail);
    if(pendingPayload && !cloudSyncInFlight) queueCloudStoreSync(pendingPayload);
    return;
  }
  if(restorePendingCloudSyncForScope(currentAccountEmail, {
    reason:'foreground_resume',
    delayMs:500,
  })) return;
  if(shouldDeferCloudRefreshForLocalState()){
    const pendingPayload = getScopedCloudSyncPendingPayload(currentAccountEmail);
    if(pendingPayload && !cloudSyncInFlight) queueCloudStoreSync(pendingPayload);
    return;
  }
  let shouldFallbackToManifest = false;
  try{
    const data = await fetchCloudOpsSnapshot(currentCloudStoreRevision);
    if(shouldDeferCloudRefreshForLocalState()) return;
    if(data){
      const applied = applyCloudOpsSnapshotToStore(data, {
        preserveActiveId: String(store?.activeId || '').trim(),
        statusText: '',
      });
      if(applied){
        const ready = await ensureActiveCloudSessionHydratedForReady('ops_refresh_ready', {
          attempts: 2,
          loadingText: accountUiT('sync.current_loading', null, 'Syncing the current conversation…'),
        });
        setStatus(ready.ok
          ? accountUiT('sync.account_synced', null, 'Account conversations synced')
          : accountUiT('sync.account_updated_current_pending', null, 'Account conversations updated; the current conversation is still syncing.'));
        return;
      }
      if(data?.snapshot_required && Array.isArray(data?.sessions)) return;
      return;
    }
    shouldFallbackToManifest = true;
  }catch(e){
    shouldFallbackToManifest = true;
    if(!isSoftNetworkError(e)) console.warn('refresh cloud ops failed:', e);
  }
  if(!shouldFallbackToManifest || shouldDeferCloudRefreshForLocalState()) return;
  try{
    const data = await fetchCloudManifestSnapshot();
    if(shouldDeferCloudRefreshForLocalState()) return;
    if(data && Array.isArray(data.sessions)){
      const activeBefore = String(store?.activeId || '').trim();
      const beforePayload = String(buildPersistableStorePayload(store).payload || '');
      const cloudManifestBaselineStore = buildCloudManifestBaselineStore(data, store?.personalization || {});
      let cloudManifestBaselinePayload = '';
      try{ cloudManifestBaselinePayload = String(buildPersistableStorePayload(cloudManifestBaselineStore).payload || ''); }catch(_){ cloudManifestBaselinePayload = ''; }
      const nextStore = mergeCloudManifestIntoLocalStore(store, data, { preserveLocalExtra:false, useLocalHydratedContent:true });
      if(shouldDeferCloudRefreshForLocalState()) return;
      const composerSnapshot = captureComposerDraftForStoreApply(activeBefore);
      applyComposerDraftSnapshotToStore(composerSnapshot, nextStore);
      preserveActiveTemporarySessionForRuntime(nextStore, activeBefore);
      if(activeBefore && nextStore.sessions?.[activeBefore]) nextStore.activeId = activeBefore;
      const updatedTs = Number(data?.updated_ts || 0) || 0;
      const revision = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
      const normalized = buildPersistableStorePayload(nextStore);
      if(updatedTs > 0) currentCloudStoreUpdatedTs = updatedTs;
      if(revision > 0) currentCloudStoreRevision = revision;
      if(normalized.payload === beforePayload){
        clearScopedStoreDirty(currentAccountEmail, { cloudUpdatedTs: updatedTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
        lastCloudSyncedPayload = cloudManifestBaselinePayload || normalized.payload;
        const ready = await ensureActiveCloudSessionHydratedForReady('manifest_refresh_same_ready', {
          attempts: 2,
          loadingText: accountUiT('sync.current_loading', null, 'Syncing the current conversation…'),
        });
        setStatus(ready.ok
          ? accountUiT('sync.account_synced', null, 'Account conversations synced')
          : accountUiT('sync.account_list_updated_current_pending', null, 'Conversation list updated; the current conversation is still syncing.'));
        return;
      }
      const visualBefore = captureActiveChatVisualState();
      store = nextStore;
      persistStorePayloadLocally(normalized.payload, normalized.slim, currentAccountEmail);
      clearScopedStoreDirty(currentAccountEmail, { cloudUpdatedTs: updatedTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
      lastCloudSyncedPayload = cloudManifestBaselinePayload || normalized.payload;
      const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
      if(chatDomUpdated) restoreComposerDraft(store.activeId);
      const ready = await ensureActiveCloudSessionHydratedForReady('manifest_refresh_ready', {
        attempts: 2,
        loadingText: accountUiT('sync.current_loading', null, 'Syncing the current conversation…'),
      });
      setStatus(ready.ok
        ? accountUiT('sync.account_synced', null, 'Account conversations synced')
        : accountUiT('sync.account_list_updated_current_pending', null, 'Conversation list updated; the current conversation is still syncing.'));
    }
  }catch(e){
    if(!isSoftNetworkError(e)) console.warn('refresh cloud manifest failed:', e);
  }
}

function startAccountCloudRefreshPoller(){
  if(window.__webaiAccountCloudRefreshPollerStarted) return;
  window.__webaiAccountCloudRefreshPollerStarted = true;
  setInterval(()=>{
    if(accountCloudRefreshPollInFlight) return;
    if(authKickRedirecting || !currentAccountEmail || isNavigatorOffline()) return;
    if(document.visibilityState && document.visibilityState !== 'visible') return;
    if(typeof isAccountRealtimeSyncHealthy === 'function' && isAccountRealtimeSyncHealthy()) return;
    accountCloudRefreshPollInFlight = true;
    Promise.resolve(refreshCloudStoreIfChanged())
      .catch((err)=>{
        if(!isSoftNetworkError(err)) console.warn('cloud refresh poll failed:', err);
      })
      .finally(()=>{ accountCloudRefreshPollInFlight = false; });
  }, 15000);
}

startAccountCloudRefreshPoller();

let logoutConfirmPending = false;
if(logoutBtnEl){
  logoutBtnEl.addEventListener('click', async ()=>{
    if(logoutBtnEl.disabled || logoutConfirmPending) return;
    closeAccountMenu();
    const returnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : logoutBtnEl;
    logoutConfirmPending = true;
    let confirmed = false;
    try{
      confirmed = typeof askKbDangerConfirm === 'function'
        ? await askKbDangerConfirm({
            title:accountUiT('account.logout_title', null, '确定退出登录吗？'),
            desc:accountUiT('account.logout_desc', null, '退出后，此设备需要重新登录才能继续访问账号中的会话、文件和设置。'),
            confirmText:accountUiT('account.sign_out', null, '退出登录'),
            cancelText:accountUiT('common.cancel', null, '取消'),
            variant:'danger',
          }, returnFocusEl)
        : confirm(`${accountUiT('account.logout_title', null, '确定退出登录吗？')}\n\n${accountUiT('account.logout_desc', null, '退出后，此设备需要重新登录才能继续访问账号中的会话、文件和设置。')}`);
    }finally{
      logoutConfirmPending = false;
    }
    if(!confirmed || logoutBtnEl.disabled) return;
    exitLogoutTriggered = true;
    const logoutLabelEl = logoutBtnEl.querySelector('span:last-child');
    const prevText = logoutLabelEl ? (logoutLabelEl.textContent || accountUiT('account.sign_out', null, '退出登录')) : (logoutBtnEl.textContent || accountUiT('account.sign_out', null, '退出登录'));
    logoutBtnEl.disabled = true;
    const busyText = accountUiT('account.logging_out', null, '退出中…');
    if(logoutLabelEl) logoutLabelEl.textContent = busyText;
    else logoutBtnEl.textContent = busyText;
    try{
      const res = await fetch('/api3/auth/logout', {
        method:'POST',
        headers:{ 'Content-Type':'application/json' },
        body:'{}'
      });
      const data = await res.json().catch(()=>({}));
      if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
      currentAccountEmail = '';
      currentCloudStoreUpdatedTs = 0;
      currentCloudStoreRevision = 0;
      cloudSyncQueuedPayload = '';
      lastCloudSyncedPayload = '';
      applyAccountUi({});
      try{ toast(accountUiT('account.logged_out', null, 'Signed out')); }catch(_){ }
      window.location.replace('/login');
    }catch(err){
      exitLogoutTriggered = false;
      logoutBtnEl.disabled = false;
      if(logoutLabelEl) logoutLabelEl.textContent = prevText;
      else logoutBtnEl.textContent = prevText;
      try{ toast(accountUiT('account.logout_failed', {error:err?.message || err}, `Sign-out failed: ${err?.message || err}`)); }catch(_){ }
    }
  });
}

const AUTO_EXIT_LOGOUT_ENABLED = false;
function handlePageExitPersistence(){
  try{ persistStreamingDraftsToStore({ immediate:false }); }catch(_){ }
  try{ flushPendingStoreWrites({ cloud:true, keepalive:true, reason:'page_exit_persisted' }); }catch(_){ }
  if(AUTO_EXIT_LOGOUT_ENABLED) sendExitLogout();
}

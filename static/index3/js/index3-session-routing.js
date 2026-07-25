/* Product frontend module.
 * Purpose: Application route parsing, URL synchronization, and route-to-session projection.
 * Loaded before index3.js; classic-script globals preserve the existing single runtime.
 */

function getRouteChatSessionId(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const path = String(url.pathname || '/').replace(/\/+$/, '');
    const match = path.match(/^\/c\/([^\/]+)$/);
    if(match){
      try{ return decodeURIComponent(String(match[1] || '')).trim(); }catch(_){ return String(match[1] || '').trim(); }
    }
    return String(url.searchParams.get(CHAT_SESSION_QUERY_KEY) || "").trim();
  }catch(_){
    return "";
  }
}

function getRouteChatShareToken(href){
  try{
    if(typeof getChatShareRouteToken === 'function') return getChatShareRouteToken(href || location.href);
    const url = new URL(String(href || location.href), location.origin);
    const match = String(url.pathname || '').match(/^\/share\/([A-Za-z0-9_-]{20,120})\/?$/);
    return match ? decodeURIComponent(String(match[1] || '')).trim() : '';
  }catch(_){ return ''; }
}

function getRouteTemporaryChatEnabled(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const raw = String(url.searchParams.get(TEMPORARY_CHAT_QUERY_KEY) || '').trim().toLowerCase();
    return raw === 'true' || raw === '1' || raw === 'yes' || raw === 'on';
  }catch(_){
    return false;
  }
}


const SETTINGS_ROUTE_SLUGS = {
  api:'api',
  voice:'voice',
  web:'web',
  image:'image',
  models:'models',
  personalization:'personalization',
  backup:'data',
  storage:'storage',
  account:'account',
};
const SETTINGS_ROUTE_TABS = {
  api:'api',
  voice:'voice',
  web:'web',
  image:'image',
  models:'models',
  model:'models',
  personalization:'personalization',
  personal:'personalization',
  profile:'personalization',
  data:'backup',
  backup:'backup',
  'data-management':'backup',
  storage:'storage',
  'storage-space':'storage',
  account:'account',
};
const LIBRARY_ROUTE_TABS = {
  all:'files',
  files:'files',
  file:'files',
  uploads:'files',
  images:'files',
  image:'files',
  knowledge:'knowledge',
  kb:'knowledge',
  docs:'knowledge',
  documents:'knowledge',
};

const LIBRARY_ROUTE_FILE_TYPES = {
  all:'all',
  images:'image',
  image:'image',
  files:'file',
  file:'file',
  uploads:'all',
};

function routePathParts(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    return String(url.pathname || '/').split('/').map(x => decodeURIComponent(String(x || '').trim())).filter(Boolean);
  }catch(_){
    return [];
  }
}

function routeHashParts(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const raw = String(url.hash || '').replace(/^#/, '').replace(/^\/+/, '').trim();
    if(!raw) return [];
    return raw.split('/').map(x => decodeURIComponent(String(x || '').trim())).filter(Boolean);
  }catch(_){
    return [];
  }
}

function isAppHashRoute(href){
  const parts = routeHashParts(href || location.href);
  return parts[0] === 'settings' || parts[0] === 'library' || parts[0] === 'temporary-chat';
}

function stripModalHashFromHref(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const parts = routeHashParts(url.href);
    if(parts[0] === 'settings' || parts[0] === 'library') url.hash = '';
    return url.pathname + url.search + url.hash;
  }catch(_){
    return '/';
  }
}

function modalRouteUrlFromReturnUrl(returnUrl, routeHash){
  try{
    const url = new URL(String(returnUrl || '/'), location.origin);
    url.hash = String(routeHash || '').replace(/^#?/, '#');
    return url.pathname + url.search + url.hash;
  }catch(_){
    return String(routeHash || '').replace(/^#?/, '/#');
  }
}

function getRouteSettingsTab(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const hashParts = routeHashParts(url.href);
    if(hashParts[0] === 'settings'){
      const slug = String(hashParts[1] || url.searchParams.get('section') || url.searchParams.get('tab') || '').trim().toLowerCase();
      return normalizeSettingsTab(SETTINGS_ROUTE_TABS[slug] || slug || settingsActiveTab || 'api');
    }
    const parts = routePathParts(url.href);
    if(parts[0] === 'settings'){
      const slug = String(parts[1] || url.searchParams.get('section') || url.searchParams.get('tab') || '').trim().toLowerCase();
      return normalizeSettingsTab(SETTINGS_ROUTE_TABS[slug] || slug || settingsActiveTab || 'api');
    }
    const queryTab = String(url.searchParams.get('settings') || '').trim().toLowerCase();
    if(queryTab) return normalizeSettingsTab(SETTINGS_ROUTE_TABS[queryTab] || queryTab);
  }catch(_){ }
  return '';
}

function getRouteLibraryTab(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const hashParts = routeHashParts(url.href);
    if(hashParts[0] === 'library'){
      const slug = String(hashParts[1] || url.searchParams.get('tab') || '').trim().toLowerCase();
      return LIBRARY_ROUTE_TABS[slug] || 'files';
    }
    const parts = routePathParts(url.href);
    if(parts[0] === 'library'){
      const slug = String(parts[1] || url.searchParams.get('tab') || '').trim().toLowerCase();
      return LIBRARY_ROUTE_TABS[slug] || 'files';
    }
    const queryTab = String(url.searchParams.get('library') || '').trim().toLowerCase();
    if(queryTab) return LIBRARY_ROUTE_TABS[queryTab] || 'files';
  }catch(_){ }
  return '';
}

function getRouteLibraryFileType(href){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const hashParts = routeHashParts(url.href);
    if(hashParts[0] === 'library'){
      // 旧版 #library/files 表示整个文件库，不把它误迁移成“仅文件”。
      const legacySlug = String(hashParts[1] || '').trim().toLowerCase();
      return legacySlug === 'images' || legacySlug === 'image' ? 'image' : 'all';
    }
    const parts = routePathParts(url.href);
    if(parts[0] !== 'library') return '';
    const slug = String(url.searchParams.get('tab') || parts[1] || 'all').trim().toLowerCase();
    return LIBRARY_ROUTE_FILE_TYPES[slug] || (LIBRARY_ROUTE_TABS[slug] === 'knowledge' ? '' : 'all');
  }catch(_){
    return '';
  }
}

function isImagePullbackRoute(href){
  try{
    const parts = routePathParts(href || location.href);
    return parts[0] === 'image-pullback';
  }catch(_){
    return false;
  }
}

function getRouteTemporaryChatPathEnabled(href){
  try{
    const hashParts = routeHashParts(href || location.href);
    if(hashParts[0] === 'temporary-chat') return true;
    const parts = routePathParts(href || location.href);
    return parts[0] === 'temporary-chat';
  }catch(_){ return false; }
}

function isModalRoute(href){
  return !!getRouteSettingsTab(href);
}

function isLibraryRoute(href){
  return !!getRouteLibraryTab(href);
}

function isNonChatRoute(href){
  return isModalRoute(href) || isLibraryRoute(href) || isImagePullbackRoute(href);
}

function settingsTabRoutePath(tab){
  const normalized = normalizeSettingsTab(tab || settingsActiveTab || 'api');
  return '#settings/' + encodeURIComponent(SETTINGS_ROUTE_SLUGS[normalized] || normalized);
}

function libraryTabRoutePath(tab, fileType='all'){
  const normalized = String(tab || '').trim() === 'knowledge' ? 'knowledge' : 'files';
  const normalizedType = String(fileType || '').trim().toLowerCase();
  const slug = normalized === 'knowledge'
    ? 'knowledge'
    : (normalizedType === 'image' ? 'images' : normalizedType === 'file' ? 'files' : 'all');
  return '/library?tab=' + encodeURIComponent(slug);
}

function imagePullbackRoutePath(){
  return '/image-pullback';
}

function getCurrentSessionViewState(opts={}){
  const o = opts || {};
  if(o.href){
    const sharedToken = getRouteChatShareToken(o.href);
    if(sharedToken) return { sessionId:'', home:false, temporary:false, sharedToken, hasState:true };
    if(getRouteTemporaryChatEnabled(o.href) || getRouteTemporaryChatPathEnabled(o.href)) return { sessionId:'', home:false, temporary:true, hasState:true };
    const routeId = getRouteChatSessionId(o.href);
    if(routeId) return { sessionId: routeId, home:false, temporary:false, hasState:true };
    return { sessionId:'', home:true, temporary:false, hasState:false };
  }
  const sharedToken = getRouteChatShareToken();
  if(sharedToken) return { sessionId:'', home:false, temporary:false, sharedToken, hasState:true };
  if(getRouteTemporaryChatEnabled() || getRouteTemporaryChatPathEnabled()) return { sessionId:'', home:false, temporary:true, hasState:true };

  // The visible URL is the source of truth after a hard refresh.  Browser
  // history.state/sessionStorage can survive from the page state that opened a
  // settings/library hash route, so checking them before /c/:id can make the app
  // render a blank home view while the address still points at a real chat.
  const routeId = getRouteChatSessionId();
  if(routeId) return { sessionId: routeId, home:false, temporary:false, hasState:true };

  const historyView = getHistoryStateSessionView();
  if(historyView.hasState) return historyView;
  const ephemeralView = readEphemeralSessionView();
  if(ephemeralView.hasState) return ephemeralView;
  return { sessionId:'', home:true, temporary:false, hasState:false };
}

function sessionHasMeaningfulConversation(session){
  const s = session && typeof session === 'object' ? session : null;
  const msgs = Array.isArray(s?.messages) ? s.messages : [];
  for(let i = 0; i < msgs.length; i++){
    const msg = msgs[i];
    if(!msg) continue;
    if(i === 0 && msg.role === 'system') continue;
    if(typeof msg.content === 'string' && msg.content.trim()) return true;
    if(Array.isArray(msg.content) && msg.content.length) return true;
    if(msg.content && typeof msg.content === 'object') return true;
  }
  return false;
}

function findReusableHomeSessionId(targetStore){
  const target = targetStore && typeof targetStore === 'object' ? targetStore : store;
  const sessions = target?.sessions || {};
  const ids = Object.keys(sessions);
  if(!ids.length) return '';
  const candidates = ids.filter(id => !sessionHasMeaningfulConversation(sessions[id]));
  if(!candidates.length) return '';
  candidates.sort((a, b)=>{
    const sa = sessions[a] || {};
    const sb = sessions[b] || {};
    const ta = Number(sa.updatedAt || sa.createdAt || 0) || 0;
    const tb = Number(sb.updatedAt || sb.createdAt || 0) || 0;
    return tb - ta;
  });
  return String(candidates[0] || '').trim();
}

function ensureLandingHomeSession(targetStore){
  const target = targetStore && typeof targetStore === 'object' ? targetStore : store;
  if(!isValidStoreShape(target) || !target.sessions) return false;
  const reusableId = findReusableHomeSessionId(target);
  if(reusableId){
    if(target.activeId !== reusableId){
      target.activeId = reusableId;
      return true;
    }
    return false;
  }
  const session = defaultSession(window.AperviaI18n?.t('nav.new_session') || 'New conversation');
  target.sessions[session.id] = session;
  target.activeId = session.id;
  return true;
}

function buildSessionRouteUrl(sessionId, opts){
  const o = opts || {};
  const sessions = o.sessions || store?.sessions || {};
  const rawId = String(sessionId || "").trim();
  const validId = rawId && sessions?.[rawId] ? rawId : "";
  const targetSession = validId ? sessions?.[validId] : null;
  const useTemporaryRoute = !!(o.temporaryChat || (validId && isTemporarySession(targetSession)));
  const useRouteId = !useTemporaryRoute && validId && sessionShouldUseAddressRoute(targetSession) ? validId : "";
  try{
    const url = new URL(String(o.href || location.href), location.origin);
    url.searchParams.delete(CHAT_SESSION_QUERY_KEY);
    url.searchParams.delete(TEMPORARY_CHAT_QUERY_KEY);
    if(useTemporaryRoute){
      url.pathname = '/';
      url.searchParams.set(TEMPORARY_CHAT_QUERY_KEY, 'true');
      if(isAppHashRoute(url.href)) url.hash = '';
    }else{
      url.pathname = useRouteId ? `/c/${encodeURIComponent(useRouteId)}` : '/';
      if(isAppHashRoute(url.href)) url.hash = '';
    }
    return url.pathname + url.search + url.hash;
  }catch(_){
    return "";
  }
}


function currentAppReturnUrlForNonChatRoute(){
  try{
    const state = history.state && typeof history.state === 'object' ? history.state : null;
    const existing = String(state?.webaiModalReturnUrl || state?.webaiSettingsReturnUrl || state?.webaiLibraryReturnUrl || state?.webaiImagePullbackReturnUrl || '').trim();
    if(existing && !isNonChatRoute(existing)) return stripModalHashFromHref(existing);
  }catch(_){ }
  try{
    if(isHomeLandingView) return stripModalHashFromHref(buildSessionRouteUrl('', { href:location.href }) || '/');
    const activeId = String(store?.activeId || '').trim();
    const active = activeId ? store?.sessions?.[activeId] : null;
    return stripModalHashFromHref(buildSessionRouteUrl(activeId, { href:location.href, temporaryChat:isTemporarySession(active) }) || '/');
  }catch(_){ return '/'; }
}

function syncModalRoute(kind, tab, opts={}){
  if(kind !== 'settings') return;
  const o = opts || {};
  const returnUrl = stripModalHashFromHref(String(o.returnUrl || currentAppReturnUrlForNonChatRoute() || '/').trim() || '/');
  const returnView = getCurrentSessionViewState({ href:returnUrl });
  const nextState = {
    ...(history.state && typeof history.state === 'object' ? history.state : {}),
    webaiChatSessionId: returnView.temporary ? null : (returnView.sessionId || null),
    webaiHomeLanding: !returnView.temporary && !!returnView.home,
    webaiTemporaryChat: !!returnView.temporary,
    webaiModalOpen: true,
    webaiModalKind: 'settings',
    webaiModalReturnUrl: returnUrl,
    webaiSettingsOpen: true,
    webaiSettingsTab: normalizeSettingsTab(tab || settingsActiveTab || 'api'),
    webaiSettingsReturnUrl: returnUrl,
    webaiLibraryOpen: false,
    webaiLibraryTab: null,
    webaiLibraryFileType: null,
    webaiLibraryReturnUrl: null,
    webaiImagePullbackOpen:false,
    webaiImagePullbackReturnUrl:null,
  };
  const nextUrl = modalRouteUrlFromReturnUrl(returnUrl, settingsTabRoutePath(tab));
  const currentUrl = (location.pathname || '/') + (location.search || '') + (location.hash || '');
  try{
    if(nextUrl === currentUrl){
      history.replaceState(nextState, '', currentUrl);
      return;
    }
    if(o.replace) history.replaceState(nextState, '', nextUrl);
    else history.pushState(nextState, '', nextUrl);
  }catch(_){ }
}

function syncLibraryRoute(tab='files', opts={}){
  const o = opts || {};
  const libraryTab = String(tab || '').trim() === 'knowledge' ? 'knowledge' : 'files';
  const libraryFileType = libraryTab === 'files'
    ? (String(o.fileType || '').trim().toLowerCase() || getRouteLibraryFileType() || 'all')
    : '';
  const returnUrl = stripModalHashFromHref(String(o.returnUrl || currentAppReturnUrlForNonChatRoute() || '/').trim() || '/');
  const returnView = getCurrentSessionViewState({ href:returnUrl });
  const nextState = {
    ...(history.state && typeof history.state === 'object' ? history.state : {}),
    webaiChatSessionId: returnView.temporary ? null : (returnView.sessionId || null),
    webaiHomeLanding: !returnView.temporary && !!returnView.home,
    webaiTemporaryChat: !!returnView.temporary,
    webaiModalOpen:false,
    webaiModalKind:null,
    webaiModalReturnUrl:null,
    webaiSettingsOpen:false,
    webaiSettingsTab:null,
    webaiSettingsReturnUrl:null,
    webaiLibraryOpen:true,
    webaiLibraryTab:libraryTab,
    webaiLibraryFileType:libraryFileType,
    webaiLibraryReturnUrl:returnUrl,
    webaiImagePullbackOpen:false,
    webaiImagePullbackReturnUrl:null,
  };
  const nextUrl = libraryTabRoutePath(libraryTab, libraryFileType);
  const currentUrl = (location.pathname || '/') + (location.search || '') + (location.hash || '');
  try{
    if(nextUrl === currentUrl){
      history.replaceState(nextState, '', currentUrl);
      return;
    }
    if(o.replace) history.replaceState(nextState, '', nextUrl);
    else history.pushState(nextState, '', nextUrl);
  }catch(_){ }
}

function syncImagePullbackRoute(opts={}){
  const o = opts || {};
  const returnUrl = stripModalHashFromHref(String(o.returnUrl || currentAppReturnUrlForNonChatRoute() || '/').trim() || '/');
  const returnView = getCurrentSessionViewState({ href:returnUrl });
  const nextState = {
    ...(history.state && typeof history.state === 'object' ? history.state : {}),
    webaiChatSessionId: returnView.temporary ? null : (returnView.sessionId || null),
    webaiHomeLanding: !returnView.temporary && !!returnView.home,
    webaiTemporaryChat: !!returnView.temporary,
    webaiModalOpen:false,
    webaiModalKind:null,
    webaiModalReturnUrl:null,
    webaiSettingsOpen:false,
    webaiSettingsTab:null,
    webaiSettingsReturnUrl:null,
    webaiLibraryOpen:false,
    webaiLibraryTab:null,
    webaiLibraryFileType:null,
    webaiLibraryReturnUrl:null,
    webaiImagePullbackOpen:true,
    webaiImagePullbackReturnUrl:returnUrl,
  };
  const nextUrl = imagePullbackRoutePath();
  const currentUrl = (location.pathname || '/') + (location.search || '') + (location.hash || '');
  try{
    if(nextUrl === currentUrl){
      history.replaceState(nextState, '', currentUrl);
      return;
    }
    if(o.replace) history.replaceState(nextState, '', nextUrl);
    else history.pushState(nextState, '', nextUrl);
  }catch(_){ }
}

function restoreModalReturnRoute(opts={}){
  const o = opts || {};
  let returnUrl = '';
  try{
    const state = history.state && typeof history.state === 'object' ? history.state : null;
    returnUrl = String(state?.webaiModalReturnUrl || state?.webaiSettingsReturnUrl || state?.webaiLibraryReturnUrl || state?.webaiImagePullbackReturnUrl || '').trim();
  }catch(_){ }
  if(!returnUrl || isNonChatRoute(returnUrl)) returnUrl = currentAppReturnUrlForNonChatRoute() || '/';
  returnUrl = stripModalHashFromHref(returnUrl);
  const nextState = {
    ...(history.state && typeof history.state === 'object' ? history.state : {}),
    webaiModalOpen:false,
    webaiModalKind:null,
    webaiModalReturnUrl:null,
    webaiSettingsOpen:false,
    webaiSettingsTab:null,
    webaiSettingsReturnUrl:null,
    webaiLibraryOpen:false,
    webaiLibraryTab:null,
    webaiLibraryReturnUrl:null,
    webaiImagePullbackOpen:false,
    webaiImagePullbackReturnUrl:null,
  };
  try{
    if(o.replace !== false) history.replaceState(nextState, '', returnUrl);
    else history.pushState(nextState, '', returnUrl);
  }catch(_){ }
}

function restoreLibraryReturnRoute(opts={}){
  const o = opts || {};
  let returnUrl = '';
  try{
    const state = history.state && typeof history.state === 'object' ? history.state : null;
    returnUrl = String(state?.webaiLibraryReturnUrl || state?.webaiModalReturnUrl || '').trim();
  }catch(_){ }
  if(!returnUrl || isNonChatRoute(returnUrl)) returnUrl = currentAppReturnUrlForNonChatRoute() || '/';
  returnUrl = stripModalHashFromHref(returnUrl);
  const nextState = {
    ...(history.state && typeof history.state === 'object' ? history.state : {}),
    webaiLibraryOpen:false,
    webaiLibraryTab:null,
    webaiLibraryFileType:null,
    webaiLibraryReturnUrl:null,
  };
  try{
    if(o.replace !== false) history.replaceState(nextState, '', returnUrl);
    else history.pushState(nextState, '', returnUrl);
  }catch(_){ }
}

function restoreImagePullbackReturnRoute(opts={}){
  const o = opts || {};
  let returnUrl = '';
  try{
    const state = history.state && typeof history.state === 'object' ? history.state : null;
    returnUrl = String(state?.webaiImagePullbackReturnUrl || state?.webaiModalReturnUrl || '').trim();
  }catch(_){ }
  if(!returnUrl || isNonChatRoute(returnUrl)) returnUrl = currentAppReturnUrlForNonChatRoute() || '/';
  returnUrl = stripModalHashFromHref(returnUrl);
  const nextState = {
    ...(history.state && typeof history.state === 'object' ? history.state : {}),
    webaiImagePullbackOpen:false,
    webaiImagePullbackReturnUrl:null,
  };
  try{
    if(o.replace !== false) history.replaceState(nextState, '', returnUrl);
    else history.pushState(nextState, '', returnUrl);
  }catch(_){ }
}

function openLibraryRoute(tab='files', opts={}){
  try{ window.closeMobileSidebarAfterNavigation?.(); }catch(_){ }
  const nextTab = String(tab || '').trim() === 'knowledge' ? 'knowledge' : 'files';
  const currentUi = typeof window.getKnowledgeBaseUiSettings === 'function' ? window.getKnowledgeBaseUiSettings() : {};
  const nextFileType = nextTab === 'files'
    ? (String(opts?.fileType || '').trim().toLowerCase() || getRouteLibraryFileType() || String(currentUi?.fileType || 'all'))
    : String(currentUi?.fileType || 'all');
  const preserveActiveChatJob = activeChatJobInProgress();
  try{ window.closeImagePullbackWorkspace?.({ syncRoute:false }); }catch(_){ }
  try{
    const uiGetter = window.getKnowledgeBaseUiSettings;
    const uiSaver = window.saveKnowledgeBaseUiSettings;
    if(typeof uiGetter === 'function' && typeof uiSaver === 'function'){
      uiSaver({ ...uiGetter(), libraryTab: nextTab, fileType: nextFileType });
    }
  }catch(_){ }
  if(opts?.syncRoute !== false) syncLibraryRoute(nextTab, { replace:!!opts?.replaceRoute, returnUrl:opts?.returnUrl || '', fileType:nextFileType });
  if(preserveActiveChatJob) keepActiveChatJobAlive('library_open');
  try{
    const opened = window.openKnowledgeBaseModal?.({ libraryTab: nextTab, preserveActiveChatJob });
    if(opened && typeof opened.finally === 'function'){
      opened.finally(()=>{ if(preserveActiveChatJob) keepActiveChatJobAlive('library_open_done'); });
    }
  }catch(_){ }
}

function closeLibraryRoute(opts={}){
  const preserveActiveChatJob = activeChatJobInProgress();
  try{ window.closeKnowledgeBaseModal?.({ syncRoute:false, preserveActiveChatJob }); }catch(_){ }
  if(opts?.syncRoute !== false && getRouteLibraryTab()) restoreLibraryReturnRoute({ replace:opts?.replaceRoute !== false });
  if(preserveActiveChatJob) keepActiveChatJobAlive('library_close');
}

function openImagePullbackRoute(opts={}){
  try{ window.closeMobileSidebarAfterNavigation?.(); }catch(_){ }
  const o = opts || {};
  const preserveActiveChatJob = activeChatJobInProgress();
  const returnUrl = String(o.returnUrl || currentAppReturnUrlForNonChatRoute() || '/').trim() || '/';
  try{ closeLibraryRoute({ syncRoute:false }); }catch(_){ }
  try{ closeSettingsModal({ syncRoute:false }); }catch(_){ }
  if(o.syncRoute !== false) syncImagePullbackRoute({ replace:!!o.replaceRoute, returnUrl });
  if(preserveActiveChatJob) keepActiveChatJobAlive('image_pullback_open');
  try{ window.openImagePullbackWorkspace?.({ syncRoute:false, routeOpen:true }); }catch(_){ }
}

function closeImagePullbackRoute(opts={}){
  const o = opts || {};
  const preserveActiveChatJob = activeChatJobInProgress();
  try{ window.closeImagePullbackWorkspace?.({ syncRoute:false }); }catch(_){ }
  if(o.syncRoute !== false && isImagePullbackRoute()) restoreImagePullbackReturnRoute({ replace:o.replaceRoute !== false });
  if(preserveActiveChatJob) keepActiveChatJobAlive('image_pullback_close');
}

function applyModalRouteFromLocation(opts={}){
  const settingsTab = getRouteSettingsTab();
  if(settingsTab){
    try{ closeLibraryRoute({ syncRoute:false }); }catch(_){ }
    try{ window.closeImagePullbackWorkspace?.({ syncRoute:false }); }catch(_){ }
    openSettingsModal(settingsTab, { syncRoute:false, routeOpen:true });
    syncModalRoute('settings', settingsTab, { replace:true });
    keepActiveChatJobAlive('settings_route_apply');
    return true;
  }
  const libraryTab = getRouteLibraryTab();
  if(libraryTab){
    const libraryFileType = getRouteLibraryFileType() || 'all';
    try{ closeSettingsModal({ syncRoute:false }); }catch(_){ }
    try{ window.closeImagePullbackWorkspace?.({ syncRoute:false }); }catch(_){ }
    openLibraryRoute(libraryTab, { syncRoute:false, routeOpen:true, fileType:libraryFileType });
    syncLibraryRoute(libraryTab, { replace:true, fileType:libraryFileType });
    keepActiveChatJobAlive('library_route_apply');
    return true;
  }
  if(isImagePullbackRoute()){
    try{ closeSettingsModal({ syncRoute:false }); }catch(_){ }
    try{ closeLibraryRoute({ syncRoute:false }); }catch(_){ }
    openImagePullbackRoute({ syncRoute:false, routeOpen:true });
    syncImagePullbackRoute({ replace:true });
    keepActiveChatJobAlive('image_pullback_route_apply');
    return true;
  }
  return false;
}

function syncSessionRoute(opts){
  const o = opts || {};
  if(!o.leaveSharedPreview && getRouteChatShareToken(o.href || location.href)){
    const explicitSessionId = String(o.sessionId || '').trim();
    const explicitSession = explicitSessionId ? (o.sessions || store?.sessions || {})?.[explicitSessionId] : null;
    const targetsSharedPreview = !!(explicitSession && typeof isSharedChatPreviewSession === 'function' && isSharedChatPreviewSession(explicitSession));
    if(!o.forceHome && (!explicitSessionId || targetsSharedPreview)) return;
  }
  if(o.preserveModalRoute !== false && isNonChatRoute()){
    const sessionId = o.forceHome ? '' : String(o.sessionId || (isHomeLandingView ? '' : store?.activeId || '')).trim();
    const targetSession = sessionId ? (o.sessions || store?.sessions || {})?.[sessionId] : null;
    const nextTemporary = !!(!o.forceHome && (o.temporaryChat || isTemporarySession(targetSession)));
    const nextHome = !nextTemporary && !!(o.forceHome || !sessionId);
    writeEphemeralSessionView(nextTemporary ? '' : sessionId, { forceHome: nextHome, temporaryChat: nextTemporary });
    return;
  }
  const sessions = o.sessions || store?.sessions || {};
  const sessionId = o.forceHome ? "" : String(o.sessionId || (isHomeLandingView ? "" : store?.activeId || "")).trim();
  const targetSession = sessionId ? sessions?.[sessionId] : null;
  const nextTemporary = !!(!o.forceHome && (o.temporaryChat || isTemporarySession(targetSession)));
  const nextUrl = buildSessionRouteUrl(sessionId, { sessions, href: o.href, temporaryChat: nextTemporary });
  if(!nextUrl) return;
  const currentUrl = (location.pathname || '/') + (location.search || '') + (location.hash || '');
  const nextHome = !nextTemporary && !!(o.forceHome || !sessionId);
  const currentStateView = getHistoryStateSessionView();
  const currentStateId = String(currentStateView.sessionId || '').trim();
  const currentStateHome = !!currentStateView.home;
  const currentStateTemporary = !!currentStateView.temporary;
  const nextState = { ...(history.state && typeof history.state === 'object' ? history.state : {}), webaiChatSessionId: nextTemporary ? null : (sessionId || null), webaiHomeLanding: nextHome, webaiTemporaryChat: nextTemporary };
  writeEphemeralSessionView(nextTemporary ? '' : sessionId, { forceHome: nextHome, temporaryChat: nextTemporary });
  try{
    if(nextUrl === currentUrl){
      if(currentStateView.hasState && currentStateId === (nextTemporary ? '' : sessionId) && currentStateHome === nextHome && currentStateTemporary === nextTemporary) return;
      history.replaceState(nextState, '', currentUrl);
      return;
    }
    if(o.replace) history.replaceState(nextState, '', nextUrl);
    else history.pushState(nextState, '', nextUrl);
  }catch(_){ }
}

function applyRouteSessionToStore(targetStore, opts){
  const target = targetStore && typeof targetStore === 'object' ? targetStore : store;
  if(!isValidStoreShape(target) || !target.sessions || !Object.keys(target.sessions).length) return false;
  const explicitSessionId = String(opts?.sessionId || '').trim();
  const routeId = explicitSessionId || getRouteChatSessionId(opts?.href);
  if(routeId && target.sessions?.[routeId]){
    isHomeLandingView = false;
    if(target.activeId !== routeId){
      target.activeId = routeId;
      return true;
    }
    return false;
  }
  return false;
}

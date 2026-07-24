/* Sidebar session list, session search and sidebar rename UI.*/
function sidebarUiT(key, params, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

function sidebarSessionDisplayTitle(value){
  const title = String(value || '').trim();
  if(!title || title === '新会话' || title === 'New conversation'){
    return sidebarUiT('nav.new_session', null, 'New conversation');
  }
  return title;
}

function setSidebarSessionPinned(sessionId, pinned){
  const sid = String(sessionId || '').trim();
  const session = store?.sessions?.[sid];
  if(!sid || !session) return false;
  const nextPinned = !!pinned;
  session.pinned = nextPinned;
  session.pinnedAt = nextPinned ? Date.now() : 0;
  session.pinned_at = session.pinnedAt;
  saveStore();
  invalidateSidebarRenderCache();
  renderList({ force:true });
  try{ toast(sidebarUiT(nextPinned ? 'nav.pinned_chat' : 'nav.unpinned_chat')); }catch(_){ }
  return true;
}
function sidebarSessionGroupLabel(ts){
  const value = Number(ts || 0) || 0;
  if(!value) return sidebarUiT('nav.group_older', null, 'Older');
  const nowDate = new Date();
  const todayStart = new Date(nowDate.getFullYear(), nowDate.getMonth(), nowDate.getDate()).getTime();
  const yesterdayStart = todayStart - 24 * 60 * 60 * 1000;
  if(value >= todayStart) return sidebarUiT('nav.group_today', null, 'Today');
  if(value >= yesterdayStart) return sidebarUiT('nav.group_yesterday', null, 'Yesterday');
  const date = new Date(value);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function sessionShouldAppearInSidebar(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(isTemporarySession(s)) return false;
  if(isSessionArchived(s)) return false;
  if(isCloudSessionStub(s)) return true;
  if(sessionHasMeaningfulConversation(s)) return true;
  if(String(s.composerDraft || '').trim()) return true;
  if(normalizeAssistantQuoteText(s?.composerQuoteDraft?.text || '')) return true;
  if(composerAttachmentDraftHasItems(s.composerAttachmentDraft)) return true;
  if(getSessionPendingJobId(s.id)) return true;
  if(pendingAssistantSnapshotForSession(s.id, store)) return true;
  if(getSessionBackendErrorPayload(s)) return true;
  return false;
}

function formatSidebarSessionTime(ts){
  const value = Number(ts || 0) || 0;
  if(!value) return "";
  const diffMs = Math.max(0, Date.now() - value);
  const diffMin = Math.floor(diffMs / 60000);
  if(diffMin < 1) return sidebarUiT('nav.time_just_now', null, 'Just now');
  if(diffMin < 60) return sidebarUiT('nav.time_minutes_ago', {count:diffMin}, `${diffMin} min ago`);
  const diffHour = Math.floor(diffMin / 60);
  if(diffHour < 24) return sidebarUiT('nav.time_hours_ago', {count:diffHour}, `${diffHour} hr ago`);
  const diffDay = Math.floor(diffHour / 24);
  if(diffDay < 7) return sidebarUiT('nav.time_days_ago', {count:diffDay}, `${diffDay} days ago`);
  const date = new Date(value);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${month}-${day}`;
}

function messageCreatedTimeMs(message){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg) return 0;
  const candidates = [
    msg.created_at_ms,
    msg.createdAtMs,
    msg.createdAt,
    msg.created_at,
    msg.timestamp,
    msg.ts,
  ];
  for(const value of candidates){
    const ts = Number(value || 0);
    if(Number.isFinite(ts) && ts > 0) return ts < 100000000000 ? ts * 1000 : ts;
  }
  return 0;
}

function sessionRealUpdatedAtMs(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return 0;
  let latest = 0;
  const messages = Array.isArray(s.messages) ? s.messages : [];
  for(const msg of messages){
    if(!msg || typeof msg !== 'object') continue;
    if(String(msg.role || '').toLowerCase() === 'system') continue;
    const ts = messageCreatedTimeMs(msg);
    if(ts > latest) latest = ts;
  }
  if(latest > 0) return latest;
  const fallback = Number(s.updatedAt || s.updated_at || s.createdAt || s.created_at || 0) || 0;
  return fallback < 100000000000 && fallback > 0 ? fallback * 1000 : fallback;
}


function compareSidebarSessions(a, b){
  const pinDiff = Number(!!b?.pinned) - Number(!!a?.pinned);
  if(pinDiff) return pinDiff;
  if(a?.pinned && b?.pinned){
    const pinnedAtDiff = (Number(b.pinnedAt || b.pinned_at || 0) || 0) - (Number(a.pinnedAt || a.pinned_at || 0) || 0);
    if(pinnedAtDiff) return pinnedAtDiff;
  }
  return sessionRealUpdatedAtMs(b) - sessionRealUpdatedAtMs(a);
}

function getSidebarSessions(keyword=""){
  const q = String(keyword || "").trim().toLowerCase();
  return Object.values(store.sessions)
    .filter(s => sessionShouldAppearInSidebar(s))
    .sort(compareSidebarSessions)
    .filter(s=>{
      if(!q) return true;
      const title = String(s.title || "").toLowerCase();
      const model = String(s.model || "").toLowerCase();
      return title.includes(q) || model.includes(q);
    });
}

function renderSessionSearchResults(){
  if(!sessionSearchResultsEl) return;
  sessionSearchResultsEl.innerHTML = "";

  const newRow = document.createElement("button");
  newRow.type = "button";
  newRow.className = "session-search-new-chat";
  newRow.innerHTML = `
    <span class="session-search-icon" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 5H6.8A2.8 2.8 0 0 0 4 7.8v9.4A2.8 2.8 0 0 0 6.8 20h9.4a2.8 2.8 0 0 0 2.8-2.8V12"></path><path d="M14.5 4.8 19.2 9.5"></path><path d="M20 4.1a1.9 1.9 0 0 1 0 2.7l-8.8 8.8-3.6.8.8-3.6 8.8-8.8a1.9 1.9 0 0 1 2.8.1Z"></path></svg></span>
    <span class="session-search-row-main">
      <span class="session-search-row-title">${escapeHtml(sidebarUiT('nav.search_new_chat', null, 'New chat'))}</span>
    </span>
  `;
  newRow.addEventListener("click", ()=>{
    closeSessionSearchModal();
    newChatBtn?.click();
  });
  sessionSearchResultsEl.appendChild(newRow);

  const sessions = getSidebarSessions(sessionSearchText);
  if(!sessions.length){
    const empty = document.createElement("div");
    empty.className = "session-search-empty";
    empty.textContent = sessionSearchText
      ? sidebarUiT('nav.search_no_match', null, 'No matching chats')
      : sidebarUiT('nav.search_empty', null, 'No chats yet. Start a new one.');
    sessionSearchResultsEl.appendChild(empty);
    return;
  }

  let currentGroup = "";
  sessions.forEach(s=>{
    const sessionTime = sessionRealUpdatedAtMs(s);
    const groupLabel = sidebarSessionGroupLabel(sessionTime);
    if(groupLabel !== currentGroup){
      currentGroup = groupLabel;
      const groupEl = document.createElement("div");
      groupEl.className = "session-search-group";
      groupEl.textContent = groupLabel;
      sessionSearchResultsEl.appendChild(groupEl);
    }

    const row = document.createElement("button");
    row.type = "button";
    row.className = "session-search-item" + (!isHomeLandingView && s.id === store.activeId ? " active" : "");
    row.dataset.sessionId = s.id;
    const rt = ensureSessionRuntime(s.id);
    const draftMark = (s.composerDraft && String(s.composerDraft).trim())
      ? ` · ${sidebarUiT('nav.draft', null, 'Draft')}`
      : (composerAttachmentDraftHasItems(s.composerAttachmentDraft) ? ` · ${sidebarUiT('nav.attachment_draft', null, 'Attachment draft')}` : "");
    const hasPendingSnapshot = !!pendingAssistantSnapshotForSession(s.id, store);
    const pendingMark = (!rt.streaming && hasPendingSnapshot) ? ` · ${sidebarUiT('nav.incomplete', null, 'Incomplete')}` : "";
    const livePreview = rt.streaming ? getSessionAnswerPreview(s.id, { maxLen: 64 }) : '';
    const rowSub = (s.model || DEFAULT_MODEL) + (rt.streaming ? (livePreview ? " · " + livePreview : ` · ${sidebarUiT('nav.generating', null, 'Generating')}`) : (pendingMark || draftMark));
    row.innerHTML = `
      <span class="session-search-icon" aria-hidden="true">○</span>
      <span class="session-search-row-main">
        <span class="session-search-row-title">${escapeHtml(sidebarSessionDisplayTitle(s.title))}</span>
        <span class="session-search-row-sub">${escapeHtml(rowSub)}</span>
      </span>
      <span class="session-search-row-time">${escapeHtml(formatSidebarSessionTime(sessionTime))}</span>
    `;
    row.addEventListener("click", ()=>{
      closeSessionSearchModal();
      setActive(s.id);
    });
    sessionSearchResultsEl.appendChild(row);
  });
}

function openSessionSearchModal(){
  if(!sessionSearchModalEl) return;
  sessionSearchModalEl.hidden = false;
  sessionSearchModalEl.classList.add("open");
  sessionSearchModalEl.setAttribute("aria-hidden", "false");
  document.body.classList.add("session-search-open");
  sessionSearchText = "";
  if(sessionSearchEl) sessionSearchEl.value = "";
  renderSessionSearchResults();
  setTimeout(()=>{
    sessionSearchEl?.focus();
    sessionSearchEl?.select?.();
  }, 0);
}

function closeSessionSearchModal(){
  if(!sessionSearchModalEl) return;
  sessionSearchModalEl.classList.remove("open");
  sessionSearchModalEl.setAttribute("aria-hidden", "true");
  sessionSearchModalEl.hidden = true;
  document.body.classList.remove("session-search-open");
  sessionSearchText = "";
  if(sessionSearchEl) sessionSearchEl.value = "";
}

let _sidebarRenameSessionId = "";
let _sidebarRenameDraft = "";
let _sidebarRenameRestoreFocus = false;

function sidebarRenameSelectorValue(value){
  const raw = String(value || "").trim();
  if(!raw) return "";
  try{
    if(window.CSS?.escape) return window.CSS.escape(raw);
  }catch(_){ }
  return raw.replace(/\\/g, "\\\\").replace(/\"/g, '\\"');
}

function isSidebarSessionRenaming(sessionId){
  const sid = String(sessionId || '').trim();
  return !!sid && _sidebarRenameSessionId === sid;
}

function getActiveSidebarRenameInput(sessionId = ''){
  const sid = String(sessionId || _sidebarRenameSessionId || '').trim();
  if(!sid) return null;
  try{
    return chatListEl?.querySelector(`.ow-chat-title-input[data-session-rename-input="${sidebarRenameSelectorValue(sid)}"]`) || null;
  }catch(_){
    return null;
  }
}

function sidebarRenameInputIsActive(sessionId = ''){
  const input = getActiveSidebarRenameInput(sessionId);
  return !!input && document.activeElement === input;
}
function startSidebarSessionRename(sessionId, initialTitle = "", opts = {}){
  const sid = String(sessionId || '').trim();
  if(!sid || !store?.sessions?.[sid]) return;
  _sidebarRenameSessionId = sid;
  _sidebarRenameDraft = sidebarSessionDisplayTitle(initialTitle ?? store.sessions[sid]?.title);
  _sidebarRenameRestoreFocus = !!opts.restoreFocus;
  closeSidebarSessionMenus();
  renderList();
  requestAnimationFrame(()=>{
    const input = chatListEl?.querySelector(`.ow-chat-title-input[data-session-rename-input="${sidebarRenameSelectorValue(sid)}"]`);
    if(!input) return;
    try{
      input.focus({ preventScroll:true });
    }catch(_){
      input.focus();
    }
    try{ input.select(); }catch(_){ }
  });
}

function cancelSidebarSessionRename(opts = {}){
  const sid = String(_sidebarRenameSessionId || '').trim();
  const shouldRestoreFocus = !!opts.restoreFocus || !!_sidebarRenameRestoreFocus;
  _sidebarRenameSessionId = "";
  _sidebarRenameDraft = "";
  _sidebarRenameRestoreFocus = false;
  if(!sid) return;
  renderList();
  if(shouldRestoreFocus){
    requestAnimationFrame(()=>{
      const item = chatListEl?.querySelector(`.ow-chat-item[data-session-id="${sidebarRenameSelectorValue(sid)}"]`);
      item?.focus?.({ preventScroll:true });
    });
  }
}

function commitSidebarSessionRename(sessionId, rawValue, opts = {}){
  const sid = String(sessionId || '').trim();
  if(!sid || !store?.sessions?.[sid]){
    cancelSidebarSessionRename(opts);
    return;
  }
  const nextTitle = String(rawValue ?? '').trim();
  if(!nextTitle){
    cancelSidebarSessionRename(opts);
    return;
  }
  const session = store.sessions[sid];
  const prevTitle = String(session.title || '').trim();
  _sidebarRenameSessionId = "";
  _sidebarRenameDraft = "";
  _sidebarRenameRestoreFocus = false;
  if(prevTitle !== nextTitle){
    session.title = nextTitle;
    session.titleAutoLocked = true;
    session.updatedAt = now();
    if(!isHomeLandingView && store?.activeId === sid && activeTitleEl){
      activeTitleEl.textContent = nextTitle;
    }
    saveStore();
  }
  renderList();
  if(opts.restoreFocus){
    requestAnimationFrame(()=>{
      const item = chatListEl?.querySelector(`.ow-chat-item[data-session-id="${sidebarRenameSelectorValue(sid)}"]`);
      item?.focus?.({ preventScroll:true });
    });
  }
}

document.addEventListener('pointerdown', (e)=>{
  const sid = String(_sidebarRenameSessionId || '').trim();
  if(!sid) return;
  const target = e.target;
  if(target?.closest?.(`[data-session-rename-root="${sidebarRenameSelectorValue(sid)}"]`)) return;
  const input = getActiveSidebarRenameInput(sid);
  const value = input ? input.value : _sidebarRenameDraft;
  requestAnimationFrame(()=>{
    if(_sidebarRenameSessionId === sid){
      commitSidebarSessionRename(sid, value);
    }
  });
}, true);

document.addEventListener('keydown', (e)=>{
  if(e.key !== 'Escape') return;
  if(!_sidebarRenameSessionId) return;
  e.preventDefault();
  e.stopPropagation();
  cancelSidebarSessionRename({ restoreFocus:true });
}, true);

function closeSidebarSessionMenuItem(item){
  if(!item) return;
  item.classList.remove('menu-open');
  item.querySelector('.ow-chat-menu-trigger')?.setAttribute('aria-expanded', 'false');
  const menu = item.querySelector('.ow-chat-menu');
  if(menu){
    menu.classList.remove('open-up');
    menu.style.left = '';
    menu.style.top = '';
  }
}

function closeSidebarSessionMenus(){
  chatListEl?.querySelectorAll('.item.menu-open').forEach(closeSidebarSessionMenuItem);
}

function sidebarSessionMenuDirection(triggerRect={}, menuHeight=0, boundaryRect={}, viewportHeight=0){
  const gap = 4;
  const edge = 8;
  const fitTolerance = 8;
  const viewportBottom = Math.max(edge * 2, Number(viewportHeight || 0) || 0) - edge;
  const boundaryTopValue = Number(boundaryRect?.top || 0) || 0;
  const boundaryBottomValue = Number(boundaryRect?.bottom || 0) || viewportBottom;
  const topLimit = Math.max(edge, boundaryTopValue);
  const bottomLimit = Math.min(viewportBottom, boundaryBottomValue);
  const triggerTop = Number(triggerRect?.top || 0) || 0;
  const triggerBottom = Number(triggerRect?.bottom || triggerTop) || triggerTop;
  const needed = Math.max(0, Number(menuHeight || 0) || 0);
  const below = Math.max(0, bottomLimit - triggerBottom - gap);
  const above = Math.max(0, triggerTop - topLimit - gap);
  if(below + fitTolerance >= needed) return 'down';
  return above > below ? 'up' : 'down';
}

function positionSidebarSessionMenu(item, trigger, menu){
  if(!item || !trigger || !menu || !item.classList.contains('menu-open')) return;
  menu.classList.remove('open-up');
  const triggerRect = trigger.getBoundingClientRect();
  const viewportWidth = Math.max(0, window.innerWidth || document.documentElement.clientWidth || 0);
  const viewportHeight = Math.max(0, window.innerHeight || document.documentElement.clientHeight || 0);
  const listRect = chatListEl?.getBoundingClientRect?.();
  const sidebarShell = item.closest?.('.ow-sidebar-shell');
  const shellRect = sidebarShell?.getBoundingClientRect?.();
  const footerRect = sidebarShell?.querySelector?.('.sidebar-footer')?.getBoundingClientRect?.();
  const boundaryRect = {
    top:Number(shellRect?.top || 0) || 0,
    bottom:Number(footerRect?.top || listRect?.bottom || viewportHeight) || viewportHeight,
  };
  const menuHeight = Math.max(1, menu.offsetHeight || menu.scrollHeight || 0);
  const menuWidth = Math.max(172, menu.offsetWidth || menu.scrollWidth || 0);
  const direction = sidebarSessionMenuDirection(triggerRect, menuHeight, boundaryRect, viewportHeight);
  const gap = 4;
  const edge = 8;
  const leftLimit = Math.max(edge, Number(shellRect?.left || 0) + edge);
  const rightLimit = Math.min(viewportWidth - edge, Number(shellRect?.right || viewportWidth) - edge);
  const preferredLeft = triggerRect.right - menuWidth;
  const left = Math.max(leftLimit, Math.min(preferredLeft, rightLimit - menuWidth));
  const topLimit = Math.max(edge, boundaryRect.top + edge);
  const bottomLimit = Math.min(viewportHeight - edge, boundaryRect.bottom);
  const preferredTop = direction === 'up'
    ? triggerRect.top - menuHeight - gap
    : triggerRect.bottom + gap;
  const top = Math.max(topLimit, Math.min(preferredTop, bottomLimit - menuHeight));
  menu.classList.toggle('open-up', direction === 'up');
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
}

function repositionOpenSidebarSessionMenu(){
  const item = chatListEl?.querySelector('.item.menu-open');
  if(!item) return;
  positionSidebarSessionMenu(
    item,
    item.querySelector('.ow-chat-menu-trigger'),
    item.querySelector('.ow-chat-menu'),
  );
}

let _sidebarSessionMenuWindowPositionBound = false;
function ensureSidebarSessionMenuPositionBindings(){
  if(chatListEl && chatListEl.dataset.sessionMenuPositionBound !== '1'){
    chatListEl.addEventListener('scroll', closeSidebarSessionMenus, { passive:true });
    chatListEl.dataset.sessionMenuPositionBound = '1';
  }
  if(!_sidebarSessionMenuWindowPositionBound){
    window.addEventListener('resize', repositionOpenSidebarSessionMenu, { passive:true });
    _sidebarSessionMenuWindowPositionBound = true;
  }
}


let _lastSidebarRenderSignature = "";
let _sidebarRenderSeq = 0;
function buildSidebarRenderSignature(){
  try{
    const sessions = getSidebarSessions();
    const rows = sessions.map((s)=>{
      const sessionTime = sessionRealUpdatedAtMs(s);
      const rt = ensureSessionRuntime(s.id);
      const hasUnreadCompletedReply = !rt.streaming && sessionHasUnreadCompletedReply(s);
      return [
        String(s.id || ''),
        sidebarSessionDisplayTitle(s.title),
        s.pinned ? sidebarUiT('nav.pinned') : sidebarSessionGroupLabel(sessionTime),
        formatSidebarSessionTime(sessionTime),
        s.pinned ? String(Number(s.pinnedAt || s.pinned_at || 0) || 1) : '',
        rt.streaming ? 'streaming' : '',
        hasUnreadCompletedReply ? 'unread' : '',
        isCloudSessionStub(s) ? 'stub' : '',
      ].join('\u001f');
    });
    return JSON.stringify({
      activeId: isHomeLandingView ? '' : String(store?.activeId || ''),
      home: !!isHomeLandingView,
      renaming: String(_sidebarRenameSessionId || ''),
      renameDraft: String(_sidebarRenameDraft || ''),
      language: String(window.AperviaI18n?.language || ''),
      rows,
    });
  }catch(_){
    return '';
  }
}
function invalidateSidebarRenderCache(){
  _lastSidebarRenderSignature = "";
  _sidebarRenderSeq++;
}

function renderList(opts = {}){
  if(newChatBtn){
    const homeActive = !!isHomeLandingView;
    newChatBtn.classList.toggle('is-active', homeActive);
    if(homeActive) newChatBtn.setAttribute('aria-current', 'page');
    else newChatBtn.removeAttribute('aria-current');
  }
  if(!chatListEl) return;
  ensureSidebarSessionMenuPositionBindings();
  if(!opts?.force && _sidebarRenameSessionId && sidebarRenameInputIsActive(_sidebarRenameSessionId)){
    const input = getActiveSidebarRenameInput(_sidebarRenameSessionId);
    if(input) _sidebarRenameDraft = input.value;
    _lastSidebarRenderSignature = buildSidebarRenderSignature();
    return;
  }
  const signature = buildSidebarRenderSignature();
  if(!opts?.force && signature && signature === _lastSidebarRenderSignature && chatListEl.childElementCount > 0){
    return;
  }
  _lastSidebarRenderSignature = signature;
  chatListEl.innerHTML = "";
  const sessions = getSidebarSessions();

  if(!sessions.length){
    const empty = document.createElement("div");
    empty.className = "ow-chat-empty";
    empty.textContent = window.AperviaI18n?.t('nav.no_conversations') || "还没有会话，先新建一个吧。";
    chatListEl.appendChild(empty);
    return;
  }

  let currentGroup = "";
  let groupEl = null;

  let renderIndex = 0;
  const seq = ++_sidebarRenderSeq;
  const batchSize = 36;
  const appendBatch = () => {
    if(seq !== _sidebarRenderSeq) return;
    const end = Math.min(renderIndex + batchSize, sessions.length);
    for(; renderIndex < end; renderIndex++){
      const s = sessions[renderIndex];
    const sessionTime = sessionRealUpdatedAtMs(s);
    const groupLabel = s.pinned ? sidebarUiT('nav.pinned', null, 'Pinned') : sidebarSessionGroupLabel(sessionTime);
    if(groupLabel !== currentGroup){
      currentGroup = groupLabel;
      groupEl = document.createElement("div");
      groupEl.className = "ow-chat-group" + (s.pinned ? ' ow-chat-group-pinned' : '');
      const labelEl = document.createElement("div");
      labelEl.className = "ow-chat-group-label";
      labelEl.textContent = groupLabel;
      groupEl.appendChild(labelEl);
      chatListEl.appendChild(groupEl);
    }

    const item = document.createElement("a");
    item.className = "item ow-chat-item" + (!isHomeLandingView && s.id === store.activeId ? " active" : "") + (s.pinned ? " pinned" : "");
    item.href = buildSessionRouteUrl(s.id, { sessions: store.sessions, href: location.href }) || "#";
    item.dataset.sessionId = s.id;

    item.addEventListener("click", (e)=>{
      if(e.target.closest(".ow-chat-menu") || e.target.closest(".ow-chat-menu-trigger")) return;
      if(e.target.closest(".ow-chat-title-input")) return;
      if(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
      e.preventDefault();
      closeSidebarSessionMenus();
      setActive(s.id);
    });

    const body = document.createElement("div");
    body.className = "ow-chat-body";

    const mainline = document.createElement("div");
    mainline.className = "ow-chat-mainline";

    const title = document.createElement("div");
    title.className = "item-title ow-chat-title";
    title.dataset.sessionRenameRoot = s.id;
    if(isSidebarSessionRenaming(s.id)){
      title.classList.add("ow-chat-title-editing");
      const titleInput = document.createElement("input");
      titleInput.type = "text";
      titleInput.className = "ow-chat-title-input";
      titleInput.value = _sidebarRenameDraft || sidebarSessionDisplayTitle(s.title);
      titleInput.setAttribute("aria-label", sidebarUiT('nav.rename_session', null, 'Rename conversation'));
      titleInput.dataset.sessionRenameInput = s.id;
      titleInput.spellcheck = false;
      titleInput.autocomplete = "off";
      titleInput.addEventListener("click", (e)=>{
        e.preventDefault();
        e.stopPropagation();
      });
      titleInput.addEventListener("dblclick", (e)=>{
        e.preventDefault();
        e.stopPropagation();
      });
      titleInput.addEventListener("pointerdown", (e)=>{
        e.stopPropagation();
      });
      titleInput.addEventListener("input", ()=>{
        _sidebarRenameDraft = titleInput.value;
      });
      titleInput.addEventListener("keydown", (e)=>{
        if(e.key === "Enter"){
          e.preventDefault();
          e.stopPropagation();
          commitSidebarSessionRename(s.id, titleInput.value, { restoreFocus:true });
          return;
        }
        if(e.key === "Escape"){
          e.preventDefault();
          e.stopPropagation();
          cancelSidebarSessionRename({ restoreFocus:true });
        }
      });
      titleInput.addEventListener("blur", ()=>{
        const value = titleInput.value;
        requestAnimationFrame(()=>{
          if(_sidebarRenameSessionId === s.id){
            commitSidebarSessionRename(s.id, value);
          }
        });
      });
      title.appendChild(titleInput);
    }else{
      title.textContent = sidebarSessionDisplayTitle(s.title);
      title.title = sidebarSessionDisplayTitle(s.title);
      title.addEventListener("dblclick", (e)=>{
        e.preventDefault();
        e.stopPropagation();
        startSidebarSessionRename(s.id, sidebarSessionDisplayTitle(s.title));
      });
    }

    const time = document.createElement("div");
    time.className = "ow-chat-time";

    mainline.appendChild(title);

    const rt = ensureSessionRuntime(s.id);
    const thinkingText = sidebarUiT('stream.thinking', null, 'Thinking…');
    const liveStatusText = String(rt.statusText || thinkingText).trim() || thinkingText;
    const livePreviewText = rt.streaming ? getSessionAnswerPreview(s.id, { maxLen: 72 }) : '';
    const hasUnreadCompletedReply = !rt.streaming && sessionHasUnreadCompletedReply(s);
    if(rt.streaming){
      item.classList.add("has-live-indicator");
      time.classList.add("ow-chat-time-streaming");
      time.innerHTML = '<span class="ow-chat-spinner" aria-hidden="true"></span>';
      time.title = liveStatusText;
      time.setAttribute('aria-label', liveStatusText);
    }else if(hasUnreadCompletedReply){
      time.classList.add("ow-chat-time-unread");
      time.innerHTML = '<span class="ow-chat-unread-dot" aria-hidden="true"></span>';
      time.title = sidebarUiT('nav.unread_completed', null, 'This conversation has a new completed reply');
      time.setAttribute('aria-label', time.title);
    }else if(s.pinned){
      time.hidden = true;
    }else{
      time.textContent = formatSidebarSessionTime(sessionTime);
    }

    mainline.appendChild(time);

    body.appendChild(mainline);

    const actions = document.createElement("div");
    actions.className = "item-actions ow-chat-actions" + (s.pinned ? ' ow-chat-pinned-actions' : '');

    if(s.pinned){
      const quickUnpinBtn = document.createElement('button');
      quickUnpinBtn.type = 'button';
      quickUnpinBtn.className = 'ow-chat-pin-toggle';
      quickUnpinBtn.setAttribute('aria-label', sidebarUiT('nav.unpin', null, 'Unpin'));
      quickUnpinBtn.title = sidebarUiT('nav.unpin', null, 'Unpin');
      quickUnpinBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M14.5 4.5l5 5-3 1.5-3.5 3.5.5 4-1 1-3.5-4-4-3.5 1-1 4 .5L9.5 8l1.5-3 3.5-.5Z"/><path d="M8.5 15.5 4 20"/><path d="M4 4l16 16"/></svg>';
      quickUnpinBtn.addEventListener('click', (e)=>{
        e.preventDefault();
        e.stopPropagation();
        closeSidebarSessionMenus();
        setSidebarSessionPinned(s.id, false);
      });
      actions.appendChild(quickUnpinBtn);
    }

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "ow-chat-menu-trigger";
    trigger.setAttribute("aria-label", sidebarUiT('nav.session_actions', null, 'Conversation actions'));
    trigger.setAttribute('aria-haspopup', 'menu');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.textContent = "⋯";
    trigger.addEventListener("click", (e)=>{
      e.preventDefault();
      e.stopPropagation();
      const opening = !item.classList.contains("menu-open");
      closeSidebarSessionMenus();
      if(!opening) return;
      item.classList.add('menu-open');
      trigger.setAttribute('aria-expanded', 'true');
      positionSidebarSessionMenu(item, trigger, menu);
    });

    const menu = document.createElement("div");
    menu.className = "ow-chat-menu";
    menu.setAttribute('role', 'menu');

    const shareBtn = document.createElement('button');
    shareBtn.type = 'button';
    shareBtn.className = 'ow-chat-menu-btn';
    shareBtn.setAttribute('role', 'menuitem');
    shareBtn.innerHTML = `<span class="ow-chat-menu-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 16V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 13v6h14v-6"/></svg></span><span>${escapeHtml(sidebarUiT('nav.share', null, 'Share'))}</span>`;
    shareBtn.addEventListener('click', async (e)=>{
      e.preventDefault();
      e.stopPropagation();
      closeSidebarSessionMenuItem(item);
      if(typeof openChatShareModal === 'function') await openChatShareModal(s.id, null, trigger);
    });

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "ow-chat-menu-btn";
    renameBtn.setAttribute('role', 'menuitem');
    renameBtn.innerHTML = `<span class="ow-chat-menu-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M4 20h4.5L19 9.5a2.12 2.12 0 0 0 0-3L17.5 5a2.12 2.12 0 0 0-3 0L4 15.5V20Z"/><path d="M13.5 6 18 10.5"/></svg></span><span>${escapeHtml(sidebarUiT('nav.rename', null, 'Rename'))}</span>`;
    renameBtn.addEventListener("click", (e)=>{
      e.preventDefault();
      e.stopPropagation();
      closeSidebarSessionMenuItem(item);
      startSidebarSessionRename(s.id, sidebarSessionDisplayTitle(s.title));
    });

    const pinBtn = document.createElement('button');
    pinBtn.type = 'button';
    pinBtn.className = 'ow-chat-menu-btn';
    pinBtn.setAttribute('role', 'menuitem');
    pinBtn.innerHTML = `<span class="ow-chat-menu-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M14.5 4.5l5 5-3 1.5-3.5 3.5.5 4-1 1-3.5-4-4-3.5 1-1 4 .5L9.5 8l1.5-3 3.5-.5Z"/><path d="M8.5 15.5 4 20"/></svg></span><span>${escapeHtml(sidebarUiT(s.pinned ? 'nav.unpin' : 'nav.pin_chat', null, s.pinned ? 'Unpin' : 'Pin chat'))}</span>`;
    pinBtn.addEventListener('click', (e)=>{
      e.preventDefault();
      e.stopPropagation();
      closeSidebarSessionMenuItem(item);
      const session = store?.sessions?.[s.id];
      if(!session) return;
      setSidebarSessionPinned(s.id, !session.pinned);
    });

    const archiveBtn = document.createElement("button");
    archiveBtn.type = "button";
    archiveBtn.className = "ow-chat-menu-btn";
    archiveBtn.setAttribute('role', 'menuitem');
    archiveBtn.innerHTML = `<span class="ow-chat-menu-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M4 7h16v13H4z"/><path d="M8 7V4h8v3"/><path d="M12 11v6"/><path d="M9.5 14.5 12 17l2.5-2.5"/></svg></span><span>${escapeHtml(sidebarUiT('nav.archive', null, 'Archive'))}</span>`;
    archiveBtn.addEventListener("click", async (e)=>{
      e.preventDefault();
      e.stopPropagation();
      closeSidebarSessionMenuItem(item);
      await archiveSession(s.id, { toast:true });
    });

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "ow-chat-menu-btn delete";
    delBtn.setAttribute('role', 'menuitem');
    delBtn.innerHTML = `<span class="ow-chat-menu-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M6 7l1 14h10l1-14"/><path d="M9 7V4h6v3"/></svg></span><span>${escapeHtml(sidebarUiT('common.delete', null, 'Delete'))}</span>`;
    delBtn.addEventListener("click", async (e)=>{
      e.preventDefault();
      e.stopPropagation();
      closeSidebarSessionMenuItem(item);
      const confirmed = await askDeleteSessionConfirm(s, delBtn);
      if(!confirmed) return;
      const deletingCurrentSession = !isHomeLandingView && store.activeId === s.id;
      delBtn.disabled = true;
      let deleteResult = null;
      try{
        deleteResult = await deleteSessionsEverywhere([s.id], { statusText:sidebarUiT('nav.delete_session_busy', null, 'Deleting conversation…') });
      }catch(err){
        delBtn.disabled = false;
        try{ toast(sidebarUiT('nav.delete_session_failed', {error:err?.message || err}, `Unable to delete conversation: ${err?.message || err}`)); }catch(_){ }
        return;
      }

      if(deletingCurrentSession){
        enterHomeLandingView({ replace:true });
      }else{
        syncSessionRoute({ replace:true });
      }
      safeRenderAll();
      if(deleteResult?.cloud_pending){
        try{ toast(sidebarUiT('nav.delete_sync_pending', null, 'Conversation deleted. Cloud sync will resume when the network is available.')); }catch(_){ }
      }
    });

    menu.appendChild(shareBtn);
    menu.appendChild(renameBtn);
    menu.appendChild(pinBtn);
    menu.appendChild(archiveBtn);
    menu.appendChild(delBtn);
    actions.appendChild(trigger);

    item.appendChild(body);
    item.appendChild(actions);
    item.appendChild(menu);
    groupEl.appendChild(item);

    }
    if(renderIndex < sessions.length) scheduleUiAfterPaint(appendBatch);
  };
  appendBatch();
}

document.addEventListener('apervia:languagechange', ()=>{
  invalidateSidebarRenderCache();
  renderList({ force:true });
  if(sessionSearchModalEl && !sessionSearchModalEl.hidden) renderSessionSearchResults();
});

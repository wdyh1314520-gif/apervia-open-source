/* WebAI public static boot shim: CSP-safe replacement for the old inline compatibility script. */
(function(){
  try{
    var n = ["isRemovedBrowser","SearchProvider"].join("");
    if(!window[n]){
      window[n] = function(v){
        return String(v || "").trim().toLowerCase() === ["browser","search"].join("_");
      };
    }
    window.__webaiKatexReady = !!window.katex;
    window.__webaiMermaidReady = !!window.mermaid;
  }catch(e){}
})();





/* Theme */
const THEME_KEY = "webai_theme_v1";
const themeBtn = document.getElementById("themeToggle");
const temporaryChatToggleBtn = document.getElementById("temporaryChatToggle");
const scrollBottomBtn = document.getElementById("scrollBottomBtn");
const sidebarToggleBtn = document.getElementById("sidebarToggle");
const sidebarToggleGhostBtn = document.getElementById("sidebarToggleGhost");
const sidebarToggleIcon = document.getElementById("sidebarToggleIcon");
const SIDEBAR_COLLAPSED_KEY = "webai_sidebar_collapsed_v1";
const chatSectionToggleBtn = document.getElementById("chatSectionToggle");
const chatListEl = document.getElementById("chatList");
const CHAT_SECTION_COLLAPSED_KEY = "webai_chat_section_collapsed_v1";

/* Dialog/confirm modal UI helpers are loaded from index3-dialogs.js. */

function applyTheme(theme){
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  themeBtn.textContent = theme === "dark" ? "☀️" : "🌙";
  themeBtn.title = theme === "dark" ? "切到浅色" : "切到深色";
  try{ rerenderMermaidBlocks(document); }catch(_){ }
}
function applySidebarCollapsed(collapsed, persist = true){
  document.body.classList.toggle("sidebar-collapsed", !!collapsed);
  if(persist){
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  }
  const isCollapsed = !!collapsed;
  if(sidebarToggleBtn){
    sidebarToggleBtn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    sidebarToggleBtn.setAttribute("aria-label", isCollapsed ? "展开侧边栏" : "收起侧边栏");
    sidebarToggleBtn.title = isCollapsed ? "展开侧边栏" : "收起侧边栏";
  }
  if(sidebarToggleGhostBtn){
    sidebarToggleGhostBtn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    sidebarToggleGhostBtn.setAttribute("aria-label", isCollapsed ? "展开侧边栏" : "收起侧边栏");
    sidebarToggleGhostBtn.title = isCollapsed ? "展开侧边栏" : "收起侧边栏";
  }
  if(sidebarToggleIcon){
    sidebarToggleIcon.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="4" y="5" width="16" height="14" rx="3"></rect><path d="M10 5v14"></path></svg>`;
  }
}

function initSidebarCollapsed(){
  const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
  applySidebarCollapsed(saved === "1");
}

(function initTheme(){
  const saved = localStorage.getItem(THEME_KEY);
  if(saved === "light" || saved === "dark") applyTheme(saved);
  else applyTheme("dark");
})();
themeBtn.addEventListener("click", ()=>{
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
});
initSidebarCollapsed();
if(sidebarToggleBtn){
  sidebarToggleBtn.addEventListener("click", ()=>{
    applySidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  });
}
if(sidebarToggleGhostBtn){
  sidebarToggleGhostBtn.addEventListener("click", ()=>{
    applySidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  });
}
function applyChatSectionCollapsed(collapsed, persist = true){
  const isCollapsed = !!collapsed;
  if(chatListEl){
    chatListEl.hidden = isCollapsed;
  }
  if(chatSectionToggleBtn){
    chatSectionToggleBtn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    chatSectionToggleBtn.title = isCollapsed ? "展开对话" : "收起对话";
  }
  if(persist){
    localStorage.setItem(CHAT_SECTION_COLLAPSED_KEY, isCollapsed ? "1" : "0");
  }
}

function initChatSectionCollapsed(){
  const saved = localStorage.getItem(CHAT_SECTION_COLLAPSED_KEY);
  applyChatSectionCollapsed(saved === "1", false);
}

if(chatSectionToggleBtn){
  chatSectionToggleBtn.addEventListener("click", ()=>{
    applyChatSectionCollapsed(!(chatListEl && chatListEl.hidden));
  });
}
initChatSectionCollapsed();
initTopbarSecondaryUI();
initSecretInputToggles();


/* Topbar secondary menu and secret input toggle UI helpers are loaded from index3-topbar-secret-ui.js. */


/* Split module loaded from index3-shared-render-reasoning.js. */
/* App */

/* Store/cloud-sync core is loaded from index3-store-cloud-sync.js. */
const mainEl = document.getElementById("main");
const chatEl = document.getElementById("chat");
let chatCenterLoadingForceCount = 0;
const codeRunDockEl = document.getElementById("codeRunDock");
const codeRunDockBodyEl = document.getElementById("codeRunDockBody");
const codeRunDockTitleEl = document.getElementById("codeRunDockTitle");
const codeRunDockKindEl = document.getElementById("codeRunDockKind");
const codeRunDockCloseEl = document.getElementById("codeRunDockClose");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const composerInputShellEl = document.getElementById("composerInputShell");
const composerQuoteBarEl = document.getElementById("composerQuoteBar");
const composerQuoteTextEl = document.getElementById("composerQuoteText");
const composerQuoteClearEl = document.getElementById("composerQuoteClear");
const composerEditBarEl = document.getElementById("composerEditBar");
const composerEditTitleEl = document.getElementById("composerEditTitle");
const composerEditDescEl = document.getElementById("composerEditDesc");
const composerEditCancelEl = document.getElementById("composerEditCancel");
const aiQuotePopoverEl = document.getElementById("aiQuotePopover");
const aiQuoteAskBtnEl = document.getElementById("aiQuoteAskBtn");
codeRunDockCloseEl?.addEventListener('click', ()=>{
  if(activeCodeRunnerState) destroyCodeRunner(activeCodeRunnerState);
  else hideCodeRunDock();
});

let composerQuoteState = null;
function resolveComposerMaxInputHeight(){
  const viewportHeight = Math.max(0, window.innerHeight || document.documentElement.clientHeight || 0);
  const oneThirdViewport = viewportHeight > 0 ? Math.round(viewportHeight * 0.33) : 320;
  const raw = String(getComputedStyle(document.documentElement).getPropertyValue("--gpt-composer-max-input-h") || "").trim().toLowerCase();
  let cssValue = NaN;
  if(raw.endsWith("px")){
    cssValue = parseFloat(raw);
  }else if(raw.endsWith("vh")){
    cssValue = viewportHeight * (parseFloat(raw) / 100);
  }else if(/^min\(/.test(raw)){
    const values = [];
    raw.replace(/([0-9.]+)\s*(px|vh)/g, (_m, num, unit)=>{
      const n = parseFloat(num);
      if(!Number.isFinite(n)) return "";
      values.push(unit === "vh" ? viewportHeight * (n / 100) : n);
      return "";
    });
    if(values.length) cssValue = Math.min(...values);
  }else{
    cssValue = parseFloat(raw);
  }
  const preferred = Number.isFinite(cssValue) && cssValue > 0 ? cssValue : oneThirdViewport;
  return Math.max(148, Math.min(preferred, Math.max(168, oneThirdViewport), 420));
}
function autoResizeInput(){
  if(!inputEl) return;
  const shell = document.getElementById("composerInputShell");
  if(shell) shell.classList.remove("is-multiline");
  inputEl.style.height = "0px";

  const baseStyles = getComputedStyle(inputEl);
  const lineHeight = parseFloat(baseStyles.lineHeight) || 22;
  const basePaddingTop = parseFloat(baseStyles.paddingTop) || 0;
  const basePaddingBottom = parseFloat(baseStyles.paddingBottom) || 0;
  const baseVerticalPadding = basePaddingTop + basePaddingBottom;
  const maxHeight = resolveComposerMaxInputHeight();
  const baseScrollHeight = inputEl.scrollHeight || 0;
  const baseContentHeight = Math.max(0, baseScrollHeight - baseVerticalPadding);
  const value = String(inputEl.value || "");
  const selectionStart = typeof inputEl.selectionStart === "number" ? inputEl.selectionStart : value.length;
  const selectionEnd = typeof inputEl.selectionEnd === "number" ? inputEl.selectionEnd : value.length;
  const caretNearEnd = selectionStart >= Math.max(0, value.length - 1) && selectionEnd >= Math.max(0, value.length - 1);
  const isMultiline = value.includes("\n") || baseContentHeight > (lineHeight * 1.55);

  if(shell) shell.classList.toggle("is-multiline", isMultiline);

  const finalStyles = getComputedStyle(inputEl);
  const finalLineHeight = parseFloat(finalStyles.lineHeight) || lineHeight;
  const finalPaddingTop = parseFloat(finalStyles.paddingTop) || 0;
  const finalPaddingBottom = parseFloat(finalStyles.paddingBottom) || 0;
  const finalMarginBottom = parseFloat(finalStyles.marginBottom) || 0;
  const finalVerticalPadding = finalPaddingTop + finalPaddingBottom;
  inputEl.style.height = "0px";
  const finalScrollHeight = inputEl.scrollHeight || 0;
  const minHeight = finalLineHeight + finalVerticalPadding;
  const maxInputHeight = isMultiline
    ? Math.max(minHeight, maxHeight - finalMarginBottom)
    : maxHeight;
  const next = Math.max(minHeight, Math.min(finalScrollHeight, maxInputHeight));
  const isScrollable = finalScrollHeight > maxInputHeight;
  inputEl.style.height = next + "px";
  inputEl.style.overflowY = isScrollable ? "auto" : "hidden";
  inputEl.style.scrollbarGutter = isScrollable ? "stable" : "auto";
  if(isScrollable && caretNearEnd){
    const keepBottomVisible = ()=>{
      try{ inputEl.scrollTop = inputEl.scrollHeight; }catch(_err){}
    };
    keepBottomVisible();
    try{ requestAnimationFrame(keepBottomVisible); }catch(_err){}
  }
}
const stopBtn = document.getElementById("stop");
const dropOverlayEl = document.getElementById("dropOverlay");
const imageLightboxEl = document.getElementById("imageLightbox");
const imageLightboxImgEl = document.getElementById("imageLightboxImg");
const imageLightboxCloseEl = document.getElementById("imageLightboxClose");
const imageLightboxPrevEl = document.getElementById("imageLightboxPrev");
const imageLightboxNextEl = document.getElementById("imageLightboxNext");
const imageLightboxCounterEl = document.getElementById("imageLightboxCounter");
let lightboxItems = [];
let lightboxIndex = 0;
const modelEl = document.getElementById("model");
const modelPickerEl = document.getElementById("modelPicker");
const modelPickerBtn = document.getElementById("modelPickerBtn");
const modelPickerPanel = document.getElementById("modelPickerPanel");
const modelPickerLabel = document.getElementById("modelPickerLabel");
const webToggleEl = document.getElementById("webToggle");
const imageGenToggleEl = document.getElementById("imageGenToggle");
const aiTitleToggleEl = document.getElementById("aiTitleToggle");
const statusEl = document.getElementById("status"); // may be null after UI cleanup
const rtTimerEl = document.getElementById("rtTimer");
const activeTitleEl = document.getElementById("activeTitle");
const topbarSubtitleEl = document.querySelector(".topbar-subtitle");
const sessionSearchEl = document.getElementById("sessionSearch");
const newChatBtn = document.getElementById("newChat");
const brandNewChatBtn = document.getElementById("brandNewChat");
const clearAllBtn = document.getElementById("clearAll");
const focusSessionSearchBtn = document.getElementById("focusSessionSearch");
const sessionSearchModalEl = document.getElementById("sessionSearchModal");
const sessionSearchResultsEl = document.getElementById("sessionSearchResults");
const sessionSearchCloseBtn = document.getElementById("sessionSearchClose");
const crossSessionNoticeHostEl = document.getElementById("crossSessionNoticeHost");
const openSettingsSidebarBtn = document.getElementById("openSettingsSidebar");
const fileEl = document.getElementById("file");
const addFileBtn = document.getElementById("addFile");
const voiceInputBtn = document.getElementById("voiceInput");
const voiceDictationUiEl = document.getElementById("voiceDictationUi");
const voiceDictationMeterEl = document.getElementById("voiceDictationMeter");
const voiceDictationWaveEl = document.getElementById("voiceDictationWave");
const voiceInputCancelBtn = document.getElementById("voiceInputCancel");
const voiceInputAcceptBtn = document.getElementById("voiceInputAccept");
const imagePreviewEl = document.getElementById("imagePreview");
let sessionSearchText = "";
let shouldAutoStickBottom = true;

initAiTitleUI();

/* Split module loaded from index3-settings-ui.js. */
// ====== 图片预览（统一走 imageLightbox，支持组图切换） ======
chatEl.addEventListener("click", async (e)=>{
  const t = e.target;
  const imgEl = (t && t.closest) ? t.closest("img.inline-img, .file-thumb img") : null;
  if(!imgEl) return;

  e.preventDefault();
  e.stopPropagation();

  // 统一复用组图预览逻辑，避免这里把组图错误降级成单图
  await attachPreviewableImageOpen(imgEl);
}, true);


/* Product module moved to index3-composer-draft-runtime.js. */

function uid(){ return "s_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16); }
function now(){ return Date.now(); }
/* Store persistence and pending assistant snapshots are loaded from index3-store-cloud-sync.js. */
function newAttId(){ return "att_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16); }

function buildDefaultSystemPrompt(){
  return "";
}

function isLegacyDefaultSystemMessage(message){
  if(!message || typeof message !== "object" || String(message.role || "").trim().toLowerCase() !== "system") return false;
  const content = typeof message.content === "string" ? message.content : "";
  const text = String(content || "").replace(/\s+/g, " ").trim();
  return text === "你是 WebAI。请直接、自然地回答用户当前问题；默认保持简洁，除非用户要求详细展开。 不要主动罗列能力菜单，也不要把普通聊天改写成文件、联网、天气、图片或其他工具任务。";
}

function isLegacyAssistantQuoteContextSystemMessage(message){
  if(!message || typeof message !== "object" || String(message.role || "").trim().toLowerCase() !== "system") return false;
  const content = typeof message.content === "string" ? message.content : "";
  const text = String(content || "").replace(/\s+/g, " ").trim();
  return text.startsWith("以下是用户在当前提问中引用的上一段 AI 回复，请将其视为本次问题的直接上下文，并优先围绕这段内容回答：");
}

function cleanLegacyDefaultSystemMessagesFromSession(session){
  if(!session || typeof session !== "object" || !Array.isArray(session.messages)) return false;
  const before = session.messages.length;
  session.messages = session.messages.filter(m => !isLegacyDefaultSystemMessage(m) && !isLegacyAssistantQuoteContextSystemMessage(m));
  return session.messages.length !== before;
}

function cleanLegacyDefaultSystemMessagesFromStore(targetStore){
  const target = targetStore && typeof targetStore === "object" ? targetStore : null;
  const sessions = target?.sessions && typeof target.sessions === "object" ? target.sessions : null;
  if(!sessions) return false;
  let changed = false;
  for(const session of Object.values(sessions)){
    if(cleanLegacyDefaultSystemMessagesFromSession(session)) changed = true;
  }
  return changed;
}

function defaultSession(title="新会话"){
  const prefs = getCurrentChatPrefs();
  const sessionId = uid();
  const mode = (typeof cloudSyncCurrentConversationMode === 'function') ? cloudSyncCurrentConversationMode() : 'chat';
  const endpointMode = (typeof cloudSyncCurrentApiEndpointModeForConversation === 'function') ? cloudSyncCurrentApiEndpointModeForConversation(mode) : (mode === 'response' ? 'responses' : 'chat_completions');
  const localId = sessionId;
  const opId = (typeof makeCloudSyncOpId === 'function') ? makeCloudSyncOpId('create_conversation', localId) : ('create_conversation:' + localId);
  const nowTs = now();
  return {
    id: sessionId,
    localId,
    local_id: localId,
    opId,
    op_id: opId,
    conversationMode: mode,
    conversation_mode: mode,
    api_endpoint_mode: endpointMode,
    endpoint_mode: endpointMode,
    syncStatus: "pending",
    sync_status: "pending",
    serverVersion: 0,
    server_version: 0,
    conversationRecovery: {
      mode,
      local_id: localId,
      server_id: sessionId,
      op_id: opId,
      server_version: 0,
      status: "pending",
      updated_at: nowTs
    },
    title,
    model: prefs.model,
    messages: [],
    createdAt: nowTs,
    updatedAt: nowTs,
    titleAutoLocked: false,
    aiTitleDone: false,
    webEnabled: !!prefs.webEnabled,
    imageGenerationEnabled: !!prefs.imageGenerationEnabled,
    chatThinkingType: normalizeThinkingType(prefs.chatThinkingType),
    composerDraft: "",
    composerQuoteDraft: null,
    composerAttachmentDraft: { files:[], images:[] }
  };
}

function isTemporarySession(session){
  const s = session && typeof session === 'object' ? session : null;
  return !!(s && (s.temporaryChat === true || s.temporary_chat === true || s.isTemporary === true || s._temporaryChat === true));
}

function getActiveTemporarySession(){
  if(isHomeLandingView) return null;
  const sid = String(store?.activeId || '').trim();
  const s = sid ? store?.sessions?.[sid] : null;
  if(typeof isSharedChatPreviewSession === 'function' && isSharedChatPreviewSession(s)) return null;
  return isTemporarySession(s) ? s : null;
}

function refreshTemporaryChatUi(){
  const activeSession = getActiveTemporarySession();
  const active = !!activeSession;
  const showEntry = !!(active || isHomeLandingView);
  const hasConversation = active && sessionHasMeaningfulConversation(activeSession);
  try{
    document.body.classList.toggle('temporary-chat-active', active);
    document.body.classList.toggle('temporary-chat-entry-visible', showEntry);
    document.body.classList.toggle('temporary-chat-empty-active', active && !hasConversation);
  }catch(_){ }
  if(temporaryChatToggleBtn){
    temporaryChatToggleBtn.hidden = !showEntry;
    temporaryChatToggleBtn.classList.toggle('active', active);
    temporaryChatToggleBtn.classList.toggle('can-cancel', active && !hasConversation);
    temporaryChatToggleBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
    temporaryChatToggleBtn.title = active
      ? (hasConversation ? (window.AperviaI18n?.t('temporary.active_title') || 'Temporary chat: this conversation will not appear in your history, and messages will not be saved') : (window.AperviaI18n?.t('temporary.return_home') || 'Temporary chat, click to return home'))
      : (window.AperviaI18n?.t('temporary.label') || 'Temporary chat');
    temporaryChatToggleBtn.setAttribute('aria-label', active
      ? (hasConversation ? (window.AperviaI18n?.t('temporary.in_use') || 'Using temporary chat') : (window.AperviaI18n?.t('temporary.return_home') || 'Temporary chat, click to return home'))
      : (window.AperviaI18n?.t('temporary.label') || 'Temporary chat'));
  }
}

function makeTemporarySession(){
  syncHomeLandingPrefsFromUi();
  const session = defaultSession('临时聊天');
  session.temporaryChat = true;
  session.temporary_chat = true;
  session.titleAutoLocked = true;
  session.aiTitleDone = true;
  session.composerDraft = '';
  session.composerQuoteDraft = null;
  session.webEnabled = !!homeLandingPrefs.webEnabled;
  session.imageGenerationEnabled = !!homeLandingPrefs.imageGenerationEnabled;
  session.chatThinkingType = normalizeThinkingType(homeLandingPrefs.chatThinkingType);
  return session;
}

function canDiscardTemporarySession(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  const s = store?.sessions?.[sid];
  if(!isTemporarySession(s)) return false;
  try{ if(isSessionStreaming(sid)) return false; }catch(_){ }
  try{ if(getSessionPendingJobId(sid)) return false; }catch(_){ }
  try{ if(pendingAssistantSnapshotForSession(sid, store)) return false; }catch(_){ }
  return true;
}

function cleanupInactiveTemporarySessions(keepSessionId=''){
  const keep = String(keepSessionId || '').trim();
  const sessions = store?.sessions || {};
  let changed = false;
  for(const sid of Object.keys(sessions)){
    if(sid === keep) continue;
    if(canDiscardTemporarySession(sid)){
      try{ delete sessions[sid]; changed = true; }catch(_){ }
    }
  }
  return changed;
}

function cloneTemporarySessionForRuntime(session){
  try{
    const cloned = JSON.parse(JSON.stringify(session || {}));
    if(cloned && cloned.id){
      cloned.temporaryChat = true;
      cloned.temporary_chat = true;
    }
    return cloned;
  }catch(_){
    return session && typeof session === 'object' ? { ...session, temporaryChat:true, temporary_chat:true } : null;
  }
}

function preserveActiveTemporarySessionForRuntime(targetStore, preferredSessionId=''){
  const target = targetStore && typeof targetStore === 'object' ? targetStore : null;
  if(!target || !target.sessions || typeof target.sessions !== 'object') return false;
  const sid = String(preferredSessionId || store?.activeId || '').trim();
  if(!sid) return false;
  const session = store?.sessions?.[sid];
  if(!isTemporarySession(session)) return false;
  const cloned = cloneTemporarySessionForRuntime(session);
  if(!cloned || !cloned.id) return false;
  target.sessions[sid] = cloned;
  target.activeId = sid;
  isHomeLandingView = false;
  try{ writeEphemeralSessionView(sid, { forceHome:false }); }catch(_){ }
  return true;
}

function stripTemporarySessionsFromPersistableStore(target){
  const out = target && typeof target === 'object' ? target : null;
  if(!out || !out.sessions || typeof out.sessions !== 'object') return;
  for(const sid of Object.keys(out.sessions)){
    if(isTemporarySession(out.sessions[sid])) delete out.sessions[sid];
  }
  if(out.activeId && out.sessions[out.activeId]) return;
  const ids = Object.keys(out.sessions || {});
  ids.sort((a, b)=> sessionRealUpdatedAtMs(out.sessions[b]) - sessionRealUpdatedAtMs(out.sessions[a]));
  out.activeId = ids[0] || null;
}


function cancelTemporaryChat(opts={}){
  const currentId = String(store?.activeId || '').trim();
  const current = currentId ? store?.sessions?.[currentId] : null;
  if(!isTemporarySession(current) || sessionHasMeaningfulConversation(current)){
    refreshTemporaryChatUi();
    return false;
  }
  cleanupInactiveTemporarySessions('');
  if(currentId && store?.sessions?.[currentId]){
    try{ delete store.sessions[currentId]; }catch(_){ }
  }
  enterHomeLandingView({ replace: opts?.replace !== false });
  setStatus('就绪');
  safeRenderAll();
  try{ inputEl.focus(); }catch(_){ }
  return true;
}

function enterTemporaryChat(opts={}){
  const current = getActiveTemporarySession();
  if(current && !sessionHasMeaningfulConversation(current)){
    syncSessionRoute({ sessionId: current.id, temporaryChat:true, replace: opts?.replace !== false });
    refreshTemporaryChatUi();
    safeRenderAll();
    try{ inputEl.focus(); }catch(_){ }
    return current;
  }
  const previousId = String(store?.activeId || '').trim();
  if(previousId){
    try{
      const ownerId = (typeof persistVisibleComposerDraftBeforeSessionChange === 'function') ? persistVisibleComposerDraftBeforeSessionChange(previousId) : '';
      persistComposerAttachmentDraft(ownerId || previousId);
    }catch(_){
      persistComposerDraft(previousId, inputEl.value || '');
      persistComposerAttachmentDraft(previousId);
    }
  }
  cleanupInactiveTemporarySessions('');
  const session = makeTemporarySession();
  store.sessions[session.id] = session;
  store.activeId = session.id;
  try{ if(typeof setComposerInputOwnerSessionId === 'function') setComposerInputOwnerSessionId(session.id); }catch(_){ }
  isHomeLandingView = false;
  homeDraftText = '';
  homeQuoteDraft = null;
  inputEl.value = '';
  composerQuoteState = null;
  renderComposerQuoteBar();
  resizeComposer();
  updateComposerActionState();
  updateComposerPlaceholder();
  clearPastedImages();
  clearComposerEditState();
  pendingFiles = [];
  imagePreviewEl?.querySelectorAll('.file-card').forEach(el=>el.remove());
  syncSessionRoute({ sessionId: session.id, temporaryChat:true, replace: opts?.replace !== false });
  setStatus('临时聊天已开启');
  safeRenderAll();
  try{ inputEl.focus(); }catch(_){ }
  return session;
}

function ensureTemporaryRouteSession(opts={}){
  const preserveExisting = opts?.preserveExisting !== false;
  const activeId = String(store?.activeId || '').trim();
  const active = activeId ? store?.sessions?.[activeId] : null;
  if(preserveExisting && isTemporarySession(active)){
    isHomeLandingView = false;
    return active;
  }
  cleanupInactiveTemporarySessions('');
  const session = makeTemporarySession();
  store.sessions[session.id] = session;
  store.activeId = session.id;
  try{ if(typeof setComposerInputOwnerSessionId === 'function') setComposerInputOwnerSessionId(session.id); }catch(_){ }
  isHomeLandingView = false;
  homeDraftText = '';
  homeQuoteDraft = null;
  return session;
}

const CHAT_SESSION_QUERY_KEY = "chat";
const TEMPORARY_CHAT_QUERY_KEY = "temporary-chat";
const CHAT_SESSION_EPHEMERAL_KEY = "webai_active_session_v1";
const HOME_LANDING_VIRTUAL_ID = "__home__";
const CHAT_PREFS_KEY = "webai_chat_prefs_v1";
let isHomeLandingView = false;

function readEphemeralSessionView(){
  try{
    const raw = sessionStorage.getItem(CHAT_SESSION_EPHEMERAL_KEY);
    if(!raw) return { sessionId:'', home:false, temporary:false, hasState:false };
    const parsed = JSON.parse(raw);
    const temporary = !!parsed?.temporaryChat;
    const sessionId = String(parsed?.sessionId || '').trim();
    const home = !temporary && (!!parsed?.home || !sessionId);
    return { sessionId: home || temporary ? '' : sessionId, home, temporary, hasState:true };
  }catch(_){
    return { sessionId:'', home:false, temporary:false, hasState:false };
  }
}

function writeEphemeralSessionView(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  const temporary = !!opts?.temporaryChat;
  const home = !temporary && !!(opts?.forceHome || !sid);
  try{
    sessionStorage.setItem(CHAT_SESSION_EPHEMERAL_KEY, JSON.stringify({
      sessionId: home || temporary ? '' : sid,
      home,
      temporaryChat: temporary,
      updatedAt: Date.now()
    }));
  }catch(_){ }
}

function getHistoryStateSessionView(){
  try{
    const st = history.state && typeof history.state === 'object' ? history.state : null;
    if(!st || (!('webaiChatSessionId' in st) && !('webaiHomeLanding' in st) && !('webaiTemporaryChat' in st))){
      return { sessionId:'', home:false, temporary:false, hasState:false };
    }
    const temporary = !!st?.webaiTemporaryChat;
    const sessionId = String(st?.webaiChatSessionId || '').trim();
    const home = !temporary && (!!st?.webaiHomeLanding || !sessionId);
    return { sessionId: home || temporary ? '' : sessionId, home, temporary, hasState:true };
  }catch(_){
    return { sessionId:'', home:false, temporary:false, hasState:false };
  }
}
let homeDraftText = "";
let homeQuoteDraft = null;

function normalizeChatPrefs(raw){
  const src = raw && typeof raw === "object" ? raw : {};
  return {
    model: String(src.model || "").trim(),
    webEnabled: !!src.webEnabled,
    imageGenerationEnabled: !!src.imageGenerationEnabled,
    chatThinkingType: normalizeThinkingType(src.chatThinkingType)
  };
}

function loadChatPrefs(){
  try{
    const raw = JSON.parse(localStorage.getItem(CHAT_PREFS_KEY) || "{}") || {};
    return normalizeChatPrefs(raw);
  }catch(_){
    return normalizeChatPrefs({});
  }
}

function saveChatPrefs(patch={}){
  const next = normalizeChatPrefs({ ...loadChatPrefs(), ...(patch || {}) });
  try{ localStorage.setItem(CHAT_PREFS_KEY, JSON.stringify(next)); }catch(_){ }
  return next;
}

function applyChatPrefsToHomeLandingPrefs(prefs){
  const next = normalizeChatPrefs(prefs);
  homeLandingPrefs.model = next.model;
  homeLandingPrefs.webEnabled = !!next.webEnabled;
  homeLandingPrefs.imageGenerationEnabled = !!next.imageGenerationEnabled;
  homeLandingPrefs.chatThinkingType = normalizeThinkingType(next.chatThinkingType);
  return homeLandingPrefs;
}

function getCurrentChatPrefs(){
  return normalizeChatPrefs(loadChatPrefs());
}

const homeLandingPrefs = normalizeChatPrefs(loadChatPrefs());

function currentHomeLandingModel(){
  return String(homeLandingPrefs.model || modelEl?.value || "").trim();
}

function normalizeThinkingType(value){
  const raw = String(value || "").trim().toLowerCase();
  return raw === "enabled" || raw === "disabled" ? raw : "auto";
}
function cycleThinkingType(value){
  const cur = normalizeThinkingType(value);
  if(cur === "auto") return "enabled";
  if(cur === "enabled") return "disabled";
  return "auto";
}
function normalizeThinkingSupportCacheKey(modelName, apiBase=""){
  const model = String(modelName || "").trim().toLowerCase();
  const base = String(apiBase || "").trim().toLowerCase().replace(/\/+$/, "");
  return model ? `${base}\n${model}` : "";
}
function getThinkingSupportCache(){
  try{
    const raw = JSON.parse(localStorage.getItem(THINKING_SUPPORT_CACHE_KEY) || "{}") || {};
    if(raw && typeof raw === "object") return raw;
  }catch(_){ }
  return {};
}
function saveThinkingSupportCache(cache){
  try{ localStorage.setItem(THINKING_SUPPORT_CACHE_KEY, JSON.stringify(cache || {})); }catch(_){ }
}
function getThinkingSupportCacheEntry(modelName, apiBase=""){
  const key = normalizeThinkingSupportCacheKey(modelName, apiBase);
  if(!key) return null;
  const cache = getThinkingSupportCache();
  const item = cache[key];
  if(!item || typeof item !== "object") return null;
  const nowTs = Date.now();
  const checkedAt = Number(item.checked_at || item.checkedAt || 0) || 0;
  const expiresAt = Number(item.expires_at || item.expiresAt || 0) || 0;
  if(expiresAt > 0 && nowTs >= expiresAt){
    delete cache[key];
    saveThinkingSupportCache(cache);
    return null;
  }
  if(expiresAt <= 0 && checkedAt > 0 && (nowTs - checkedAt) > 7 * 24 * 3600 * 1000){
    delete cache[key];
    saveThinkingSupportCache(cache);
    return null;
  }
  return item;
}
function setThinkingSupportCacheEntry(modelName, apiBase="", entry={}){
  const key = normalizeThinkingSupportCacheKey(modelName, apiBase);
  if(!key) return null;
  const cache = getThinkingSupportCache();
  const checkedAt = Number(entry.checked_at || entry.checkedAt || Date.now()) || Date.now();
  const cooldownUntil = Number(entry.cooldown_until || entry.cooldownUntil || 0) || 0;
  let expiresAt = Number(entry.expires_at || entry.expiresAt || 0) || 0;
  if(!(expiresAt > 0)){
    expiresAt = cooldownUntil > checkedAt ? cooldownUntil : (checkedAt + 7 * 24 * 3600 * 1000);
  }
  cache[key] = {
    ok: entry.ok !== false,
    supported: !!entry.supported,
    definitive: entry.definitive !== false,
    checked_at: checkedAt,
    source: String(entry.source || "probe").trim() || "probe",
    message: String(entry.message || "").trim(),
    probe_attempts: Number(entry.probe_attempts || entry.probeAttempts || 0) || 0,
    probe_limit_reached: !!entry.probe_limit_reached,
    cooldown_until: cooldownUntil,
    retry_after_s: Number(entry.retry_after_s || entry.retryAfterS || 0) || 0,
    expires_at: expiresAt,
  };
  saveThinkingSupportCache(cache);
  return cache[key];
}
const thinkingSupportProbeInflight = new Map();
let thinkingUiRefreshSeq = 0;
async function probeThinkingSupport(modelName, {force=false, silent=true}={}){
  const profile = getCurrentApiProfile();
  const model = String(modelName || "").trim();
  const apiBase = String(profile.api_base || API_DEFAULT_BASE || "").trim();
  const apiKey = String(profile.api_key || "").trim();
  if(!model) return { ok:false, supported:false, message:"missing_model", definitive:false };
  if(!apiKey) return { ok:false, supported:false, message:window.AperviaI18n?.t('settings.models.save_current_key') || "Save the current key first", definitive:false };
  const cached = !force ? getThinkingSupportCacheEntry(model, apiBase) : null;
  if(cached && typeof cached.supported === "boolean"){
    return {
      ok: cached.ok !== false,
      supported: !!cached.supported,
      message: String(cached.message || "").trim(),
      cached: true,
      definitive: cached.definitive !== false,
      source: String(cached.source || "cache"),
      checked_at: Number(cached.checked_at || 0) || 0,
      probe_attempts: Number(cached.probe_attempts || 0) || 0,
      probe_limit_reached: !!cached.probe_limit_reached,
      cooldown_until: Number(cached.cooldown_until || 0) || 0,
      retry_after_s: Number(cached.retry_after_s || 0) || 0,
    };
  }
  const cacheKey = normalizeThinkingSupportCacheKey(model, apiBase);
  if(!force && thinkingSupportProbeInflight.has(cacheKey)) return thinkingSupportProbeInflight.get(cacheKey);
  const job = (async ()=>{
    try{
      const res = await fetch("/api3/thinking_capability_probe", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ model, api_settings:{ api_key: profile.api_key || "", api_base: apiBase, profile_name: profile.name, api_endpoint_mode: normalizeApiEndpointMode(profile.api_endpoint_mode) } })
      });
      const raw = await res.text().catch(()=>"");
      let data = {};
      try{ data = JSON.parse(raw || "{}"); }catch(_){ }
      if(!res.ok){
        const message = (data && (data.error || data.message)) || raw || ("HTTP " + res.status);
        if(!silent) toast(message || window.AperviaI18n?.t('settings.thinking_probe_failed') || 'Deep-thinking capability detection failed.');
        return { ok:false, supported:false, message, definitive:false };
      }
      const result = {
        ok: !!data.ok,
        supported: !!data.supported,
        message: String(data.message || "").trim(),
        definitive: !!data.definitive,
        cached: !!data.cached,
        source: String(data.source || "probe").trim() || "probe",
        checked_at: Number(data.checked_at || Date.now()) || Date.now(),
        probe_attempts: Number(data.probe_attempts || data.probeAttempts || 0) || 0,
        probe_limit_reached: !!data.probe_limit_reached,
        cooldown_until: Number(data.cooldown_until || data.cooldownUntil || 0) || 0,
        retry_after_s: Number(data.retry_after_s || data.retryAfterS || 0) || 0,
      };
      if(result.ok && (result.supported || result.definitive)){
        setThinkingSupportCacheEntry(model, apiBase, result);
      }else if(result.probe_limit_reached || result.cooldown_until > Date.now()){
        setThinkingSupportCacheEntry(model, apiBase, result);
      }
      if(!result.ok && !silent){
        toast(result.message || window.AperviaI18n?.t('settings.thinking_probe_failed') || 'Deep-thinking capability detection failed.');
      }
      return result;
    }catch(err){
      const message = err?.message || "深度思考能力探测失败";
      if(!silent) toast(message);
      return { ok:false, supported:false, message, definitive:false };
    }finally{
      thinkingSupportProbeInflight.delete(cacheKey);
    }
  })();
  thinkingSupportProbeInflight.set(cacheKey, job);
  return job;
}
function thinkingTypeButtonLabel(value){
  const mode = normalizeThinkingType(value);
  if(mode === "enabled") return window.AperviaI18n?.t('composer.thinking_on') || "✦ 深度思考";
  if(mode === "disabled") return window.AperviaI18n?.t('composer.thinking_off') || "✦ 关闭思考";
  return window.AperviaI18n?.t('composer.thinking_auto') || "✦ 自动思考";
}
function currentChatModelForThinking(){
  if(isHomeLandingView) return currentHomeLandingModel();
  const active = typeof getActive === "function" ? getActive() : null;
  return String(active?.model || modelEl?.value || currentHomeLandingModel() || "").trim();
}
function getCurrentChatThinkingType(){
  if(isHomeLandingView) return normalizeThinkingType(homeLandingPrefs.chatThinkingType);
  const active = typeof getActive === "function" ? getActive() : null;
  return normalizeThinkingType(active?.chatThinkingType);
}
function setCurrentChatThinkingType(value){
  const next = normalizeThinkingType(value);
  if(isHomeLandingView){
    homeLandingPrefs.chatThinkingType = next;
  }else{
    updateActive(s => { s.chatThinkingType = next; });
  }
  saveChatPrefs({ chatThinkingType: next });
  refreshThinkingControlUi();
}
function resolveThinkingControlModel(rawValue){
  const raw = String(rawValue || "").trim();
  if(!raw || /^(follow_current|current|same_as_chat|same)$/i.test(raw)) return currentChatModelForThinking();
  return raw;
}
function modelSupportsThinkingType(modelName, apiBase="", vendorHint=""){
  const cached = getThinkingSupportCacheEntry(modelName, apiBase);
  if(cached && typeof cached.supported === "boolean") return !!cached.supported;
  const name = String(modelName || "").trim().toLowerCase();
  if(!name) return false;
  const vendorMeta = detectVendorMeta("", apiBase || "");
  const vendor = String(vendorHint || vendorMeta.vendor || "").trim().toLowerCase();
  if(/^glm(?:[-._]|$)/i.test(name)) return true;
  if(/(^|[\/:_-])glm[-_ ]?(?:4(?:\.[567])?|5)(?:[^a-z0-9]|$)/i.test(name)) return true;
  if(vendor === "zhipu" && /glm/i.test(name)) return true;
  return false;
}
async function updateChatThinkingToggleUi(refreshSeq=0){
  const btn = document.getElementById("chatThinkingToggle");
  const shell = document.getElementById("composerInputShell");
  if(!btn || !shell) return;
  const api = getCurrentApiProfile();
  const modelName = currentChatModelForThinking();
  const hasModel = !!String(modelName || "").trim();
  const hasApiKey = !!String(api?.api_key || "").trim();
  const cached = getThinkingSupportCacheEntry(modelName, api.api_base);
  const hasCachedSupport = !!(cached && typeof cached.supported === "boolean");
  const supported = hasCachedSupport ? !!cached.supported : modelSupportsThinkingType(modelName, api.api_base);
  if(refreshSeq && refreshSeq !== thinkingUiRefreshSeq) return;
  const shouldShowThinkingToggle = !!(hasModel && (hasApiKey || supported));
  btn.hidden = !shouldShowThinkingToggle;
  shell.classList.toggle("has-chat-thinking", shouldShowThinkingToggle);
  try{ autoResizeInput(); }catch(_err){}
  if(btn.hidden) return;
  const mode = getCurrentChatThinkingType();
  btn.dataset.mode = mode;
  btn.textContent = thinkingTypeButtonLabel(mode);
  btn.setAttribute("aria-pressed", mode === "enabled" ? "true" : "false");
  if(supported){
    btn.title = `${modelName} 支持思考控制；点击切换 自动 / 开启 / 关闭`;
    return;
  }
  btn.title = hasApiKey
    ? `${modelName} 未做自动探测；点击后会先探测，再切换 自动 / 开启 / 关闭`
    : (window.AperviaI18n?.t('settings.models.save_current_key') || 'Save the current key first');
}
function isCheckboxEnabled(el){
  if(!el) return false;
  if(el.type === "checkbox") return !!el.checked;
  return String(el.value || "0") === "1";
}
function setCheckboxLikeValue(el, enabled){
  if(!el) return;
  if(el.type === "checkbox") el.checked = !!enabled;
  else el.value = enabled ? "1" : "0";
}
function refreshBooleanFieldState(id, onText="开启", offText="关闭"){
  const el = document.getElementById(id);
  const stateEl = document.getElementById(`${id}State`);
  if(stateEl) stateEl.textContent = isCheckboxEnabled(el) ? onText : offText;
}
function bindBooleanFieldState(id, onText="开启", offText="关闭"){
  const el = document.getElementById(id);
  if(!el || el.dataset.stateBound === "1"){
    refreshBooleanFieldState(id, onText, offText);
    return;
  }
  const apply = ()=> refreshBooleanFieldState(id, onText, offText);
  el.addEventListener("change", apply);
  el.dataset.stateBound = "1";
  apply();
}
async function ensureAuxThinkingToggleSupported(modelInputId, toggleId, label, {silent=false}={}){
  const toggle = document.getElementById(toggleId);
  const input = document.getElementById(modelInputId);
  if(!toggle || !input) return false;
  if(!isCheckboxEnabled(toggle)) return false;
  const modelName = resolveThinkingControlModel(input.value);
  if(!String(modelName || "").trim()){
    setCheckboxLikeValue(toggle, false);
    refreshBooleanFieldState(toggleId, "开启", /ThinkingEnabled$/.test(toggleId) ? "关闭（默认）" : "关闭");
    if(!silent) toast(window.AperviaI18n?.t('settings.thinking_missing_model', {label}) || `${label} was not enabled because no model is selected.`);
    return false;
  }
  const result = await probeThinkingSupport(modelName, { silent:true });
  if(result && result.ok && result.supported){
    refreshBooleanFieldState(toggleId, "开启", /ThinkingEnabled$/.test(toggleId) ? "关闭（默认）" : "关闭");
    return true;
  }
  setCheckboxLikeValue(toggle, false);
  refreshBooleanFieldState(toggleId, "开启", /ThinkingEnabled$/.test(toggleId) ? "关闭（默认）" : "关闭");
  if(!silent) toast(window.AperviaI18n?.t('settings.thinking_not_supported', {label}) || `${label} is unavailable or unsupported and remains off.`);
  return false;
}
async function syncAuxThinkingToggleUi(){
  bindBooleanFieldState("wsPlaywrightEnable", "开启", "关闭");
  bindBooleanFieldState("wsAutoRender", "开启", "关闭");
}
function refreshThinkingControlUi(){
  const seq = ++thinkingUiRefreshSeq;
  updateChatThinkingToggleUi(seq);
  syncAuxThinkingToggleUi();
}

function syncHomeLandingPrefsFromUi(){
  const nextModel = String(modelEl?.value || homeLandingPrefs.model || "").trim();
  homeLandingPrefs.model = nextModel;
  if(webToggleEl) homeLandingPrefs.webEnabled = !!webToggleEl.checked;
  if(imageGenToggleEl) homeLandingPrefs.imageGenerationEnabled = !!imageGenToggleEl.checked;
  homeLandingPrefs.chatThinkingType = normalizeThinkingType(homeLandingPrefs.chatThinkingType);
  saveChatPrefs(homeLandingPrefs);
}

function getHomeLandingVirtualSession(){
  return {
    id: HOME_LANDING_VIRTUAL_ID,
    title: '',
    model: currentHomeLandingModel(),
    messages: [],
    createdAt: now(),
    updatedAt: now(),
    titleAutoLocked: false,
    aiTitleDone: true,
    webEnabled: !!homeLandingPrefs.webEnabled,
    imageGenerationEnabled: !!homeLandingPrefs.imageGenerationEnabled,
    chatThinkingType: normalizeThinkingType(homeLandingPrefs.chatThinkingType),
    composerDraft: homeDraftText || '',
    composerQuoteDraft: homeQuoteDraft || null,
    composerAttachmentDraft: homeComposerAttachmentDraft || { files:[], images:[] }
  };
}

function restoreHomeLandingComposer(){
  try{ if(typeof setComposerInputOwnerSessionId === 'function') setComposerInputOwnerSessionId(''); }catch(_){ }
  inputEl.value = homeDraftText || '';
  composerQuoteState = homeQuoteDraft ? { ...homeQuoteDraft } : null;
  restoreComposerAttachmentDraft('');
  renderComposerQuoteBar();
  resizeComposer();
  updateComposerActionState();
  updateComposerPlaceholder();
}

function restoreComposerForCurrentView(){
  if(isHomeLandingView){
    restoreHomeLandingComposer();
    return;
  }
  restoreComposerDraft(store?.activeId);
}

function enterHomeLandingView(opts={}){
  const o = opts || {};
  applyChatPrefsToHomeLandingPrefs(loadChatPrefs());
  cleanupInactiveTemporarySessions('');
  isHomeLandingView = true;
  writeEphemeralSessionView('', { forceHome:true });
  homeDraftText = '';
  homeQuoteDraft = null;
  homeComposerAttachmentDraft = { files:[], images:[] };
  inputEl.value = '';
  composerQuoteState = null;
  renderComposerQuoteBar();
  resizeComposer();
  updateComposerActionState();
  updateComposerPlaceholder();
  refreshThinkingControlUi();
  clearPastedImages();
  clearComposerEditState();
  pendingFiles = [];
  imagePreviewEl?.querySelectorAll('.file-card').forEach(el=>el.remove());
  if(o.syncHistory !== false) syncSessionRoute({ replace: !!o.replace, forceHome: true });
}

function createSessionFromHomeLanding(){
  syncHomeLandingPrefsFromUi();
  const session = defaultSession('新会话');
  session.model = String(homeLandingPrefs.model || currentHomeLandingModel() || "").trim();
  session.webEnabled = !!homeLandingPrefs.webEnabled;
  session.imageGenerationEnabled = !!homeLandingPrefs.imageGenerationEnabled;
  session.chatThinkingType = normalizeThinkingType(homeLandingPrefs.chatThinkingType);
  store.sessions[session.id] = session;
  store.activeId = session.id;
  try{ if(typeof setComposerInputOwnerSessionId === 'function') setComposerInputOwnerSessionId(session.id); }catch(_){ }
  isHomeLandingView = false;
  homeDraftText = '';
  homeQuoteDraft = null;
  homeComposerAttachmentDraft = { files:[], images:[] };
  return session;
}

/* Product module moved to index3-session-routing.js. */

// 启动阶段不要先读取浏览器会话缓存；登录账号场景必须等云端返回后再渲染。
let store = { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
ensureStorePersonalization(store);

function createDefaultStore(title="新会话"){
  const s = defaultSession(title);
  return { sessions:{ [s.id]: s }, activeId:s.id, personalization: normalizePersonalizationState() };
}


async function switchStoreScope(nextEmail){
  const targetEmail = normalizeAccountScopeEmail(nextEmail);
  const targetScopeKey = buildScopedStoreKey(targetEmail);
  if(lastLoadedStoreScopeKey === targetScopeKey && currentAccountEmail === targetEmail && isValidStoreShape(store) && (storeHasActiveSession(store) || !Object.keys(store.sessions || {}).length)){
    return;
  }

  if(targetEmail){
    setStatus('正在加载账号云端会话…');
  }

  const previousEmail = currentAccountEmail;
  const previousSnapshot = hasMeaningfulStoreHistory(store)
    ? (buildPersistableStorePayload(store).slim || null)
    : null;
  const canBootstrapFromPrevious = !!previousSnapshot && (
    (!targetEmail && !previousEmail) ||
    (!!targetEmail && !!previousEmail && previousEmail === targetEmail)
  );

  currentAccountEmail = targetEmail;
  if(previousEmail !== targetEmail){
    try{ stopAccountRealtimeSync('scope_switch'); }catch(_){ }
    refreshAccountScopedSecretSettingsUi('scope_switch');
  }
  currentCloudStoreUpdatedTs = 0;
  currentCloudStoreRevision = 0;
  lastCloudSyncedPayload = '';
  cloudSyncQueuedPayload = '';

  let nextStore = await readPersistedStoreForScope(targetEmail);
  let pendingPayloadForScope = '';
  let pendingStoreForScope = null;
  let pendingRecordForScope = null;
  let pendingShouldSurviveCloudLoad = false;
  if(targetEmail){
    pendingRecordForScope = readScopedCloudSyncPending(targetEmail);
    pendingPayloadForScope = String(pendingRecordForScope?.payload || getScopedCloudSyncPendingPayload(targetEmail) || '').trim();
    pendingStoreForScope = parseCloudSyncPayload(pendingPayloadForScope);
    if(isValidStoreShape(pendingStoreForScope)){
      // 未确认落云的本地写入必须作为启动基线，不能被旧云端 manifest 先覆盖。
      if(isLocalStorageFallbackStorePayload(nextStore) || !isValidStoreShape(nextStore) || storeLatestUpdatedAtMs(pendingStoreForScope) >= storeLatestUpdatedAtMs(nextStore)){
        nextStore = pendingStoreForScope;
      }
    }
  }
  let shouldPushToCloud = false;
  let cloudLoaded = false;
  let cloudLoadSoftFailed = false;
  let manifestOnlyLoaded = false;

  if(targetEmail){
    try{
      const cloudData = await fetchCloudManifestSnapshot();
      let cloudDeleteTombstones = {};
      try{ cloudDeleteTombstones = receiveCloudSessionDeleteTombstones(cloudData, targetEmail); }catch(_){ cloudDeleteTombstones = {}; }
      try{ if(isValidStoreShape(nextStore)) applySessionDeleteTombstonesToStore(nextStore, targetEmail, cloudDeleteTombstones); }catch(_){ }
      const fullCloudStore = isValidStoreShape(cloudData?._fullStore)
        ? cloudData._fullStore
        : (isValidStoreShape(cloudData?.store) ? cloudData.store : null);
      if(fullCloudStore){
        try{ applySessionDeleteTombstonesToStore(fullCloudStore, targetEmail, cloudDeleteTombstones); }catch(_){ }
        normalizeStoreActiveIdInPlace(fullCloudStore);
      }
      const cloudUpdatedTs = Number(cloudData?.updated_ts || 0) || 0;
      const cloudRevision = Number(cloudData?.server_revision ?? cloudData?.revision ?? 0) || 0;

      if(!cloudData){
        cloudLoadSoftFailed = true;
        shouldPushToCloud = false;
      }else if(cloudUpdatedTs > 0){
        currentCloudStoreUpdatedTs = cloudUpdatedTs;
      }
      if(cloudData && cloudRevision > 0) currentCloudStoreRevision = cloudRevision;

      pendingShouldSurviveCloudLoad = cloudSyncPendingShouldSurviveCloudLoad(targetEmail, pendingRecordForScope, pendingStoreForScope, cloudUpdatedTs);

      if(cloudData && fullCloudStore){
        try{ lastCloudSyncedPayload = String(buildPersistableStorePayload(fullCloudStore).payload || ''); }catch(_){ }
        const cloudBase = cloneStoreDeep(fullCloudStore) || JSON.parse(JSON.stringify(fullCloudStore));
        if(pendingShouldSurviveCloudLoad){
          nextStore = cloudSyncMergeStorePreservingLiveLocal(cloudBase, pendingStoreForScope, {
            preserveActiveId: String(pendingStoreForScope?.activeId || nextStore?.activeId || '').trim(),
            preserveActive:true,
            preserveLocalProgress:true,
          });
          shouldPushToCloud = true;
        }else{
          nextStore = cloudBase;
          shouldPushToCloud = false;
        }
        normalizeStoreActiveIdInPlace(nextStore);
        cloudLoaded = true;
        if(!pendingShouldSurviveCloudLoad){
          clearScopedCloudSyncPending(targetEmail);
          clearScopedStoreDirty(targetEmail, { cloudUpdatedTs, localUpdatedAt: storeLatestUpdatedAtMs(nextStore), authoritative:true });
        }
      }else if(cloudData && Array.isArray(cloudData.sessions)){
        const manifestBaseStore = pendingShouldSurviveCloudLoad
          ? (pendingStoreForScope || { sessions:{}, activeId:null, personalization: normalizePersonalizationState(nextStore?.personalization || {}) })
          : { sessions:{}, activeId:null, personalization: normalizePersonalizationState(nextStore?.personalization || {}) };
        const cloudManifestBaselineStore = buildCloudManifestBaselineStore(cloudData, nextStore?.personalization || {});
        nextStore = mergeCloudManifestIntoLocalStore(manifestBaseStore, cloudData, {
          preserveLocalExtra:!!pendingShouldSurviveCloudLoad,
          useLocalHydratedContent:!!pendingShouldSurviveCloudLoad,
          allowStaleHydratedContent:!!pendingShouldSurviveCloudLoad,
        });
        if(pendingShouldSurviveCloudLoad){
          nextStore = cloudSyncMergeStorePreservingLiveLocal(nextStore, pendingStoreForScope, {
            preserveActiveId: String(pendingStoreForScope?.activeId || nextStore?.activeId || '').trim(),
            preserveActive:true,
            preserveLocalProgress:true,
          });
          shouldPushToCloud = true;
        }else{
          shouldPushToCloud = false;
        }
        manifestOnlyLoaded = true;
        cloudLoaded = true;
        if(!pendingShouldSurviveCloudLoad){
          clearScopedCloudSyncPending(targetEmail);
        }
        try{ lastCloudSyncedPayload = String(buildPersistableStorePayload(cloudManifestBaselineStore).payload || ''); }catch(_){ }
        if(!pendingShouldSurviveCloudLoad){
          clearScopedStoreDirty(targetEmail, { cloudUpdatedTs, localUpdatedAt: storeLatestUpdatedAtMs(nextStore), authoritative:true });
        }
      }else if(cloudData && isValidStoreShape(nextStore)){
        if(pendingShouldSurviveCloudLoad){
          const emptyCloudBaseStore = { sessions:{}, activeId:null, personalization: normalizePersonalizationState(nextStore?.personalization || {}) };
          nextStore = cloudSyncMergeStorePreservingLiveLocal(emptyCloudBaseStore, pendingStoreForScope, {
            preserveActiveId: String(pendingStoreForScope?.activeId || nextStore?.activeId || '').trim(),
            preserveActive:true,
            preserveLocalProgress:true,
          });
          shouldPushToCloud = true;
          cloudLoaded = true;
        }else{
          shouldPushToCloud = false;
          nextStore = { sessions:{}, activeId:null, personalization: normalizePersonalizationState(nextStore?.personalization || {}) };
          cloudLoaded = true;
          clearScopedCloudSyncPending(targetEmail);
          clearScopedStoreDirty(targetEmail, { cloudUpdatedTs, localUpdatedAt: 0, authoritative:true });
        }
      }else if(cloudData && canBootstrapFromPrevious){
        nextStore = previousSnapshot;
        shouldPushToCloud = false;
        cloudLoadSoftFailed = true;
      }
    }catch(e){
      cloudLoadSoftFailed = true;
      shouldPushToCloud = false;
      console.warn('load cloud manifest soft failed, using local cache:', e);
      if(!isValidStoreShape(nextStore) && canBootstrapFromPrevious){
        nextStore = previousSnapshot;
      }
    }
  }

  if(isValidStoreShape(nextStore)){
    try{ applySessionDeleteTombstonesToStore(nextStore, targetEmail); }catch(_){ }
    normalizeStoreActiveIdInPlace(nextStore);
  }else{
    nextStore = { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
    ensureStorePersonalization(nextStore);
    if(targetEmail && !cloudLoaded && !currentCloudStoreUpdatedTs){
      shouldPushToCloud = false;
    }
  }

  const identityPromptCleaned = cleanLegacyDefaultSystemMessagesFromStore(nextStore);
  if(identityPromptCleaned && (!targetEmail || cloudLoaded || currentCloudStoreRevision > 0 || (!cloudLoadSoftFailed && hasMeaningfulStoreHistory(nextStore)))) shouldPushToCloud = true;
  preserveActiveTemporarySessionForRuntime(nextStore);
  try{ if(targetEmail) applySessionDeleteTombstonesToStore(nextStore, targetEmail); }catch(_){ }
  store = nextStore;
  if(targetEmail){
    try{
      await fetchBackendPersonalizationState({ render:false, persist:false });
    }catch(e){
      console.warn('load backend personalization failed:', e);
    }
  }else{
    PERSONALIZATION_BACKEND_LOADED_EMAIL = '';
  }
  enforceAccountStoreLimitsInPlace('silent');
  const targetRouteView = getCurrentSessionViewState();
  let routeSessionLoadedFromCloud = false;
  const routeSessionId = String(targetRouteView.sessionId || '').trim();
  if(targetEmail && routeSessionId && !store.sessions?.[routeSessionId]){
    try{
      routeSessionLoadedFromCloud = await ensureCloudSessionLoadedIntoStore(routeSessionId, { makeActive:true, force:true });
      if(routeSessionLoadedFromCloud){
        cloudLoaded = true;
        manifestOnlyLoaded = false;
        normalizeStoreActiveIdInPlace(store);
      }
    }catch(e){
      console.warn('[chat-sync] route session cloud load failed:', e);
    }
  }
  const activeForBareModal = String(store?.activeId || '').trim();
  const keepActiveForNonChatRoute = !!(isNonChatRoute() && !targetRouteView.sessionId && !targetRouteView.temporary && activeForBareModal && sessionShouldUseAddressRoute(store.sessions?.[activeForBareModal]));
  if(targetRouteView.temporary) ensureTemporaryRouteSession({ preserveExisting:true });
  else if(targetRouteView.sessionId && store.sessions?.[targetRouteView.sessionId]) applyRouteSessionToStore(store, { sessionId: targetRouteView.sessionId });
  else if(keepActiveForNonChatRoute) isHomeLandingView = false;
  else isHomeLandingView = !!targetRouteView.home;
  if(!isHomeLandingView && store?.activeId) clearSessionUnreadWhenOpened(store.activeId, { render:false });
  lastLoadedStoreScopeKey = targetScopeKey;
  const { slim, payload } = buildPersistableStorePayload(store);
  persistStorePayloadLocally(payload, slim, targetEmail);
  if(routeSessionLoadedFromCloud && targetEmail && !shouldPushToCloud){
    lastCloudSyncedPayload = String(payload || lastCloudSyncedPayload || '');
  }
  if(targetEmail){
    if(shouldPushToCloud) markScopedStoreDirty(targetEmail, { localUpdatedAt: storeLatestUpdatedAtMs(store) });
    else clearScopedStoreDirty(targetEmail, { cloudUpdatedTs: currentCloudStoreUpdatedTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
  }
  let restoredPendingForScope = false;
  if(targetEmail && shouldPushToCloud){
    queueCloudStoreSync(payload);
  }else if(targetEmail){
    restoredPendingForScope = restorePendingCloudSyncForScope(targetEmail, {
      reason:'scope_switch',
      delayMs:0,
    });
  }
  syncSessionRoute({ replace:true });

  safeRenderAll();
  restoreComposerForCurrentView();
  if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
  let readyHydrate = { ok:true, needed:false };
  let readySync = { ok:true, needed:false };
  if(targetEmail && !cloudLoadSoftFailed && !isHomeLandingView && store?.activeId){
    readyHydrate = await ensureActiveCloudSessionHydratedForReady('scope_switch_ready', {
      sessionId: store.activeId,
      attempts: 2,
      loadingText: manifestOnlyLoaded ? '正在同步当前会话正文…' : '正在确认当前会话…',
    });
  }
  if(targetEmail && (shouldPushToCloud || restoredPendingForScope || cloudSyncHasUnsettledLocalWork(targetEmail))){
    readySync = await waitForCloudSyncSettledForReady(targetEmail, {
      timeoutMs: 7000,
      loadingText: '正在确认账号会话已落云…',
    });
  }
  if(targetEmail){
    if(cloudLoadSoftFailed) setStatus('已使用本地缓存，云端恢复后继续同步');
    else if(!readyHydrate.ok) setStatus('账号会话列表已加载，当前会话仍在同步');
    else if(!readySync.ok) setStatus('账号会话已加载，本地更改仍在同步');
    else setStatus('账号会话已同步');
    try{ startAccountRealtimeSync({ reason:'scope_switch_done', force:true }); }catch(_){ }
  }else{
    try{ stopAccountRealtimeSync('local_scope'); }catch(_){ }
    setStatus('已加载本地会话');
  }
  if(previousEmail !== targetEmail) refreshAccountScopedSecretSettingsUi('scope_switch_done');
  if(targetEmail && !readyHydrate.ok){
    scheduleActiveCloudSessionHydrate('scope_switch_pending', { delayMs: 1200, force:true, statusText: '已同步当前会话' });
  }
}


// ✅ 启动：账号会话先等云端；本地缓存只作为未登录/云端失败后的兜底
async function initStore(){
  setStatus('正在加载账号会话…');

  let authData = null;
  try{
    authData = await refreshAccountUi();
  }catch(e){
    try{ console.warn('initial auth refresh failed:', e); }catch(_){ }
  }

  const cachedAuthEmail = normalizeAccountScopeEmail(
    authData?.scope_email ||
    authData?.email ||
    lastGoodAccountUiData?.scope_email ||
    lastGoodAccountUiData?.email ||
    ''
  );
  if(!currentAccountEmail && cachedAuthEmail && authData?.logged_in !== false){
    try{
      await switchStoreScope(cachedAuthEmail);
    }catch(e){
      try{ console.warn('initial cloud scope load failed:', e); }catch(_){ }
    }
  }

  if(currentAccountEmail && typeof initializeSharedChatPreviewFromRoute === 'function'){
    const sharedPreviewReady = await initializeSharedChatPreviewFromRoute();
    if(sharedPreviewReady){
      applyModalRouteFromLocation({ initial:true });
      return;
    }
  }

  if(currentAccountEmail && isValidStoreShape(store)){
    applyModalRouteFromLocation({ initial:true });
    if(storeHasActiveSession(store)){
      const ready = await ensureActiveCloudSessionHydratedForReady('initial_account_store_ready', {
        sessionId: store.activeId,
        attempts: 2,
        loadingText: '正在确认当前会话…',
      });
      if(!ready.ok){
        scheduleActiveCloudSessionHydrate('initial_account_store_pending', { delayMs: 1200, force:true, statusText: '已同步当前会话' });
      }
      maybeResumeSessionJob(store.activeId, { force:true });
    }
    return;
  }

  const localStore = await readPersistedStoreForScope('');
  if(isValidStoreShape(localStore)){
    cleanLegacyDefaultSystemMessagesFromStore(localStore);
    normalizeStoreActiveIdInPlace(localStore);
    store = localStore;
  }

  if(isValidStoreShape(store)){
    normalizeStoreActiveIdInPlace(store);
  }else{
    store = { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
    saveStore();
  }

  if(typeof initializeSharedChatPreviewFromRoute === 'function'){
    const sharedPreviewReady = await initializeSharedChatPreviewFromRoute();
    if(sharedPreviewReady){
      lastLoadedStoreScopeKey = buildScopedStoreKey(currentAccountEmail);
      applyModalRouteFromLocation({ initial:true });
      return;
    }
  }

  const bootRouteView = getCurrentSessionViewState();
  const bootRouteSessionId = String(bootRouteView.sessionId || '').trim();
  const bootRouteMatchedLocal = !!(bootRouteSessionId && store.sessions?.[bootRouteSessionId]);
  const bootActiveForBareModal = String(store?.activeId || '').trim();
  const keepBootActiveForNonChatRoute = !!(isNonChatRoute() && !bootRouteSessionId && !bootRouteView.temporary && bootActiveForBareModal && sessionShouldUseAddressRoute(store.sessions?.[bootActiveForBareModal]));
  const shouldDeferInitialRouteSync = !!(bootRouteSessionId && !bootRouteMatchedLocal);
  if(bootRouteView.temporary) ensureTemporaryRouteSession({ preserveExisting:true });
  else if(bootRouteMatchedLocal) applyRouteSessionToStore(store, { sessionId: bootRouteSessionId });
  else if(keepBootActiveForNonChatRoute) isHomeLandingView = false;
  else isHomeLandingView = !!bootRouteView.home;
  if(!isHomeLandingView && store?.activeId) clearSessionUnreadWhenOpened(store.activeId, { render:false });
  lastLoadedStoreScopeKey = buildScopedStoreKey(currentAccountEmail);
  if(!shouldDeferInitialRouteSync) syncSessionRoute({ replace:true });
  safeRenderAll();
  restoreComposerForCurrentView();
  setStatus('已加载本地会话');
  if(shouldDeferInitialRouteSync) syncSessionRoute({ replace:true });
  applyModalRouteFromLocation({ initial:true });
  scheduleActiveCloudSessionHydrate('initial_local_store', { delayMs: 0, statusText: '已加载当前会话' });
  maybeResumeSessionJob(store.activeId, { force:true });
}

/* Account/auth and cloud lifecycle is loaded from index3-account-cloud-lifecycle.js. */

/* Composer quote/draft runtime is loaded from index3-composer-quote-runtime-ui.js. */

/* Stream/session runtime is loaded from index3-stream-runtime-ui.js. */

async function setActive(id, opts){
  const o = opts || {};
  if(!store.sessions[id]) return;
  const leavingLibraryPage = !!getRouteLibraryTab();
  const leavingImagePullbackPage = isImagePullbackRoute();
  const leavingUtilityPage = leavingLibraryPage || leavingImagePullbackPage;
  const wasHomeLandingView = !!isHomeLandingView;
  const prevActiveId = store.activeId;
  if(!leavingUtilityPage && !wasHomeLandingView && prevActiveId === id){
    clearSessionUnreadWhenOpened(id);
    const ready = await ensureActiveCloudSessionHydratedForReady('active_session_reselect_ready', {
      sessionId: id,
      attempts: 2,
      loadingText: '正在同步当前会话正文…',
    });
    if(!ready.ok) scheduleActiveCloudSessionHydrate('active_session_reselect_pending', { delayMs: 1200, force:true, statusText: '已同步当前会话' });
    return;
  }
  if(prevActiveId) saveCurrentChatScrollState(prevActiveId);
  try{
    const ownerId = (typeof persistVisibleComposerDraftBeforeSessionChange === 'function') ? persistVisibleComposerDraftBeforeSessionChange(prevActiveId) : '';
    persistComposerAttachmentDraft(ownerId || prevActiveId);
  }catch(_){
    persistComposerDraft(prevActiveId, inputEl.value || "");
    persistComposerAttachmentDraft(prevActiveId);
  }
  clearPinnedQuoteHighlight();
  isHomeLandingView = false;
  store.activeId = id;
  cleanupInactiveTemporarySessions(id);
  dismissCrossSessionCompletionNotice(id);
  setSessionUnreadCompletedReply(id, false);
  saveStore();
  if(leavingLibraryPage){
    try{ closeLibraryRoute({ syncRoute:false }); }catch(_){ }
  }
  if(leavingImagePullbackPage){
    try{ closeImagePullbackRoute({ syncRoute:false }); }catch(_){ }
  }
  if(o.syncHistory !== false) syncSessionRoute({ sessionId:id, preserveModalRoute:!leavingUtilityPage });
  clearPastedImages({ preserveLocalCache:true, preservePreviewUrls:true });
  clearComposerEditState();
  restoreComposerDraft(id);
  refreshStatusForActiveSession();
  maybeResumeSessionJob(id, { force:true });
  renderAll();
  const ready = await ensureActiveCloudSessionHydratedForReady('active_session_switch_ready', {
    sessionId: id,
    attempts: 2,
    loadingText: '正在同步当前会话正文…',
  });
  if(!ready.ok) scheduleActiveCloudSessionHydrate('active_session_switch_pending', { delayMs: 1200, force:true, statusText: '已同步当前会话' });
  const remembered = chatScrollMemory[id];
  requestAnimationFrame(()=>{
    if(store.activeId !== id) return;
    if(remembered) restoreChatScrollState(remembered);
    else chatEl.scrollTop = chatEl.scrollHeight;
    scrollChatToBottom(false);
  });
  rtSyncActiveDisplay();
}

async function updateSessionById(id, fn, opts){
  const s = getSessionById(id);
  if(!s) return;
  const o = opts || {};
  const touchUpdatedAt = o.touchUpdatedAt !== false && o.preserveUpdatedAt !== true;
  const previousUpdatedAt = s.updatedAt;

  // 先更新并渲染，保证用户消息“点发送就出现”
  fn(s);
  if(touchUpdatedAt){
    s.updatedAt = now();
  }else if(previousUpdatedAt !== undefined){
    s.updatedAt = previousUpdatedAt;
  }
  commitSessionToStoreWithoutRollback(s);
  saveStore();
  if(!o.skipRender) safeRenderAll();
}

async function updateActive(fn, opts){
  return updateSessionById(store.activeId, fn, opts);
}

/* Product module moved to index3-app-errors.js. */

/* Product module moved to index3-browser-context.js. */

// ====== Round-trip Timer: user send -> AI done ======
let _rtTicker = null;

function _rtFmtMs(ms){
  const s = ms / 1000;
  return (s < 100 ? s.toFixed(2) : s.toFixed(1)) + "s";
}

function _rtGetDisplayState(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return { running:false, label:"本次耗时：0.00s" };
  const rt = ensureSessionRuntime(sid);
  const completedAssistant = sessionObjectLastVisibleMessageIsAssistant(getSessionById(sid));
  if(completedAssistant && !getSessionPromise(sid)){
    let changed = false;
    if(rt.streaming){ rt.streaming = false; changed = true; }
    if(Number(rt.rtStartAt || 0)){ rt.rtStartAt = 0; changed = true; }
    if(String(rt.draftText || rt.statusText || rt.draftProcessText || '').trim()){
      rt.draftText = '';
      rt.statusText = '';
      rt.draftProcessText = '';
      changed = true;
    }
    if((Array.isArray(rt.draftFiles) && rt.draftFiles.length) || (Array.isArray(rt.draftImageReplies) && rt.draftImageReplies.length) || (Array.isArray(rt.sources) && rt.sources.length)){
      rt.draftFiles = [];
      rt.draftImageReplies = [];
      rt.sources = [];
      changed = true;
    }
    try{ if(String(getSessionPendingJobId(sid) || '').trim()) clearSessionPendingJob(sid, { immediate:true }); }catch(_){ }
    try{ if(pendingAssistantSnapshotForSession(sid, store)) clearPendingAssistantSnapshot(sid); }catch(_){ }
    if(changed) _rtPersistSessionState(sid, rt);
  }
  const startAt = completedAssistant && !getSessionPromise(sid) ? 0 : _rtNormalizeStartAtForSession(sid, Number(rt.rtStartAt || 0));
  if(startAt > 0){
    if(startAt !== Number(rt.rtStartAt || 0)) rt.rtStartAt = startAt;
    return { running:true, label:"本次耗时：" + _rtFmtMs(Math.max(0, Date.now() - startAt)) };
  }
  // 已完成会话的最终耗时以持久化会话/最后一条助手消息为准。
  // sessionRuntime 是内存缓存，切换会话或云端回填后可能滞后，不能只读它。
  const persisted = _rtReadPersistedSessionState(sid);
  const persistedFinalMs = Math.max(0, Number(persisted?.rtFinalMs || 0) || 0);
  if(persistedFinalMs > 0 && Math.abs(persistedFinalMs - Math.max(0, Number(rt.rtFinalMs || 0) || 0)) > 1){
    rt.rtFinalMs = persistedFinalMs;
    rt.rtStartAt = 0;
  }
  const finalMs = _rtClampElapsedMsForSession(sid, Math.max(0, Number(rt.rtFinalMs || persistedFinalMs || 0)));
  if(finalMs !== Number(rt.rtFinalMs || 0)) rt.rtFinalMs = finalMs;
  return { running:false, label:"本次耗时：" + (finalMs > 0 ? _rtFmtMs(finalMs) : "0.00s") };
}

function _rtEnsureTicker(){
  if(_rtTicker) return;
  _rtTicker = setInterval(()=>{
    const activeId = isHomeLandingView ? '' : String(store?.activeId || '').trim();
    const view = _rtGetDisplayState(activeId);
    if(rtTimerEl) rtTimerEl.textContent = view.label;
    if(!view.running){
      clearInterval(_rtTicker);
      _rtTicker = null;
    }
  }, 100);
}

function rtSyncActiveDisplay(){
  const activeId = isHomeLandingView ? '' : String(store?.activeId || '').trim();
  const view = _rtGetDisplayState(activeId);
  if(rtTimerEl) rtTimerEl.textContent = view.label;
  if(view.running) _rtEnsureTicker();
  else if(_rtTicker){
    clearInterval(_rtTicker);
    _rtTicker = null;
  }
}

function rtReset(sessionId=''){
  const sid = String(sessionId || '').trim();
  if(sid){
    const rt = ensureSessionRuntime(sid);
    rt.rtStartAt = 0;
    rt.rtFinalMs = 0;
    _rtPersistSessionState(sid, rt, { immediate:true });
  }
  rtSyncActiveDisplay();
}

function rtStart(sessionId='', opts={}){
  const sid = String(sessionId || '').trim() || String(store?.activeId || '').trim();
  if(!sid) return;
  const rt = ensureSessionRuntime(sid);
  const force = !!(opts && opts.force);
  if(force || !Number(rt.rtStartAt)){
    rt.rtStartAt = _rtCurrentTurnStartAt(sid);
  }else{
    rt.rtStartAt = _rtNormalizeStartAtForSession(sid, rt.rtStartAt);
  }
  rt.rtFinalMs = 0;
  _rtPersistSessionState(sid, rt, { immediate: force });
  rtSyncActiveDisplay();
}

function rtStop(sessionId='', finalize=true){
  const sid = String(sessionId || '').trim() || String(store?.activeId || '').trim();
  if(!sid){
    rtSyncActiveDisplay();
    return;
  }
  const rt = ensureSessionRuntime(sid);
  const startAt = _rtNormalizeStartAtForSession(sid, Number(rt.rtStartAt || 0));
  if(startAt > 0){
    if(finalize) rt.rtFinalMs = _rtClampElapsedMsForSession(sid, Date.now() - startAt);
    rt.rtStartAt = 0;
  }
  _rtPersistSessionState(sid, rt, { immediate:true });
  rtSyncActiveDisplay();
}
let _statusCoreText = "";
let _statusMetaText = "";

function setStatus(t){
  _statusCoreText = (t ?? "");
  _statusMetaText = "";
  if(statusEl) statusEl.textContent = "状态：" + _statusCoreText;
}

let _toastTimer = null;
let _errorToastDedupKey = '';
let _errorToastDedupTs = 0;
function toast(message, duration=1800, opts=null){
  const host = document.getElementById("toastHost");
  const msg = String(message || "").trim();
  if(!msg){
    return;
  }
  const optionObj = typeof opts === 'string' ? { variant: opts } : (opts && typeof opts === 'object' ? opts : {});
  if(!host){
    try{ setStatus(msg); }catch(_){ }
    return;
  }
  try{ if(_toastTimer) clearTimeout(_toastTimer); }catch(_){ }
  host.innerHTML = "";
  const item = document.createElement("div");
  item.className = "toast-item";
  const variant = String(optionObj.variant || '').trim().toLowerCase();
  if(variant) item.classList.add('toast-' + variant.replace(/[^a-z0-9_-]+/g, ''));
  item.textContent = msg;
  host.appendChild(item);
  requestAnimationFrame(()=> item.classList.add("show"));
  _toastTimer = setTimeout(()=>{
    item.classList.add("hide");
    setTimeout(()=>{
      if(host.contains(item)) host.removeChild(item);
    }, 220);
  }, Math.max(1200, Number(duration) || 1800));
}

function toastError(message, duration=6000){
  const msg = typeof normalizeCompactErrorText === 'function'
    ? normalizeCompactErrorText(message)
    : String(message || '').trim();
  if(!msg) return;
  const ts = Date.now();
  if(msg === _errorToastDedupKey && (ts - _errorToastDedupTs) < 1600) return;
  _errorToastDedupKey = msg;
  _errorToastDedupTs = ts;
  toast(msg, duration, { variant:'error' });
}

const crossSessionNoticeTimers = Object.create(null);
const crossSessionNoticeItems = Object.create(null);
const crossSessionNoticeKeys = Object.create(null);

function dismissCrossSessionCompletionNotice(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  const item = crossSessionNoticeItems[sid];
  if(!item) return;
  try{ if(crossSessionNoticeTimers[sid]) clearTimeout(crossSessionNoticeTimers[sid]); }catch(_){ }
  delete crossSessionNoticeTimers[sid];
  delete crossSessionNoticeItems[sid];
  delete crossSessionNoticeKeys[sid];
  item.classList.add('hide');
  setTimeout(()=>{
    try{ if(item.parentNode) item.parentNode.removeChild(item); }catch(_){ }
  }, 220);
}

function isSessionVisibleInMainView(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  if(isHomeLandingView) return false;
  if(String(store?.activeId || '').trim() !== sid) return false;
  // GPT/OpenWebUI style streaming belongs to the active conversation.
  // After edit/regenerate the DOM marker can lag one render tick; do not let
  // a stale visibleChatSessionId swallow the next assistant stream.
  const visibleSid = String(visibleChatSessionId || '').trim();
  return !visibleSid || visibleSid === sid;
}

function _compactSessionPreviewText(text, maxLen=120){
  let s = String(text || '').replace(/```[\s\S]*?```/g, ' ').replace(/\s+/g, ' ').trim();
  if(!s) return '';
  if(/^已命中联网研究|^正在规划搜索|^判断联网研究策略/.test(s)) return '';
  const limit = Math.max(18, Number(maxLen || 120) || 120);
  if(s.length <= limit) return s;
  return `${s.slice(0, Math.max(0, limit - 1)).trim()}…`;
}

function sessionAssistantMessageHasVisibleReply(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').trim().toLowerCase() !== 'assistant') return false;
  const content = m.content;
  if(typeof content === 'string' && content.trim()) return true;
  if(Array.isArray(content) && content.length) return true;
  if(content && typeof content === 'object') return true;
  if(Array.isArray(m.imageReplies) && m.imageReplies.length) return true;
  if(Array.isArray(m.image_replies) && m.image_replies.length) return true;
  if(Array.isArray(m.files) && m.files.length) return true;
  return false;
}

function sessionLatestCompletedAssistantReadKey(sessionOrId){
  const s = typeof sessionOrId === 'string' ? getSessionById(sessionOrId) : sessionOrId;
  if(!s || typeof s !== 'object') return '';
  const msgs = Array.isArray(s.messages) ? s.messages : [];
  let last = null;
  let lastIndex = -1;
  let assistantOrdinal = 0;
  let lastOrdinal = 0;
  for(let i = 0; i < msgs.length; i += 1){
    const msg = msgs[i];
    if(!sessionAssistantMessageHasVisibleReply(msg)) continue;
    assistantOrdinal += 1;
    last = msg;
    lastIndex = i;
    lastOrdinal = assistantOrdinal;
  }
  if(!last) return '';
  let identity = '';
  try{ identity = messageStableClientIdentity(last) || ''; }catch(_){ identity = ''; }
  let created = 0;
  try{ created = Math.floor(messageCreatedTimeMs(last) || 0); }catch(_){ created = 0; }
  let fingerprint = '';
  try{
    fingerprint = chatRenderLightFingerprint({
      role: 'assistant',
      kind: last._kind || '',
      content: last.content,
      imageReplies: last.imageReplies || last.image_replies || [],
      files: last.files || [],
    }, 900);
  }catch(_){
    try{ fingerprint = cloudSyncStableStringify([last.role || '', last._kind || '', last.content || '', last.imageReplies || last.image_replies || [], last.files || []]).slice(0, 900); }catch(__){ fingerprint = ''; }
  }
  return [String(lastOrdinal), String(lastIndex), String(created), String(identity), String(fingerprint)].join('|');
}

function _sessionReadDoneAtMs(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return 0;
  const raw = Number(s.sidebarReadDoneAt || s.sidebarLastReadDoneAt || s.sidebarReadAt || 0) || 0;
  return raw > 0 && raw < 100000000000 ? raw * 1000 : raw;
}

function _sessionUnreadDoneAtMs(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return 0;
  const raw = Number(s.sidebarUnreadDoneAt || s.sidebarUnreadAt || 0) || 0;
  return raw > 0 && raw < 100000000000 ? raw * 1000 : raw;
}

function sessionReadStateCoversUnread(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  const latestKey = sessionLatestCompletedAssistantReadKey(s);
  const readKey = String(s.sidebarReadDoneKey || s.sidebarLastReadDoneKey || '').trim();
  const unreadKey = String(s.sidebarUnreadDoneKey || '').trim();
  if(readKey && (readKey === unreadKey || (latestKey && readKey === latestKey))) return true;
  const readAt = _sessionReadDoneAtMs(s);
  const unreadAt = _sessionUnreadDoneAtMs(s);
  if(readAt > 0 && unreadAt > 0 && readAt >= unreadAt) return true;
  return false;
}

function sessionHasUnreadCompletedReply(sessionOrId){
  const s = typeof sessionOrId === 'string' ? getSessionById(sessionOrId) : sessionOrId;
  if(!s || !s.sidebarUnreadDone) return false;
  if(!sessionLatestCompletedAssistantReadKey(s)) return false;
  return !sessionReadStateCoversUnread(s);
}

function setSessionUnreadCompletedReply(sessionId, enabled){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  const s = getSessionById(sid);
  if(!s) return false;
  const nextOn = !!enabled;
  const latestKey = sessionLatestCompletedAssistantReadKey(s);
  const nowTs = Date.now();
  const before = cloudSyncStableStringify({
    unread: !!s.sidebarUnreadDone,
    unreadKey: s.sidebarUnreadDoneKey || '',
    unreadAt: s.sidebarUnreadDoneAt || 0,
    readKey: s.sidebarReadDoneKey || '',
    readAt: s.sidebarReadDoneAt || 0,
  });
  if(nextOn){
    if(!latestKey) return false;
    const readKey = String(s.sidebarReadDoneKey || '').trim();
    if(readKey && readKey === latestKey){
      delete s.sidebarUnreadDone;
      delete s.sidebarUnreadDoneKey;
      delete s.sidebarUnreadDoneAt;
    }else{
      const prevUnreadKey = String(s.sidebarUnreadDoneKey || '').trim();
      s.sidebarUnreadDone = true;
      s.sidebarUnreadDoneKey = latestKey;
      if(prevUnreadKey !== latestKey || !_sessionUnreadDoneAtMs(s)) s.sidebarUnreadDoneAt = nowTs;
    }
  }else{
    if(!s.sidebarUnreadDone && latestKey && String(s.sidebarReadDoneKey || '').trim() === latestKey) return false;
    delete s.sidebarUnreadDone;
    delete s.sidebarUnreadDoneKey;
    delete s.sidebarUnreadDoneAt;
    if(latestKey) s.sidebarReadDoneKey = latestKey;
    s.sidebarReadDoneAt = nowTs;
  }
  const after = cloudSyncStableStringify({
    unread: !!s.sidebarUnreadDone,
    unreadKey: s.sidebarUnreadDoneKey || '',
    unreadAt: s.sidebarUnreadDoneAt || 0,
    readKey: s.sidebarReadDoneKey || '',
    readAt: s.sidebarReadDoneAt || 0,
  });
  if(before === after) return false;
  saveStore();
  return true;
}

function clearSessionUnreadWhenOpened(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  const changed = setSessionUnreadCompletedReply(sid, false);
  if(changed && opts?.render !== false){
    try{ renderList({ force:true }); }catch(_){ }
  }
  return changed;
}

function acknowledgeVisibleSessionUnread(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid || isHomeLandingView) return false;
  if(String(store?.activeId || '').trim() !== sid) return false;
  if(String(visibleChatSessionId || '').trim() !== sid) return false;
  if(!chatEl || !chatEl.childElementCount) return false;
  return clearSessionUnreadWhenOpened(sid, opts);
}

function getSessionAnswerPreview(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return '';
  const maxLen = Math.max(18, Number(opts.maxLen || 120) || 120);
  const preferred = _compactSessionPreviewText(opts.currentText || '', maxLen);
  if(preferred) return preferred;
  const rt = ensureSessionRuntime(sid);
  const draftPreview = _compactSessionPreviewText(getArtifactDraftPreviewText(rt?.draftText || ''), maxLen);
  if(draftPreview) return draftPreview;
  const session = getSessionById(sid);
  const msgs = Array.isArray(session?.messages) ? session.messages : [];
  for(let i = msgs.length - 1; i >= 0; i -= 1){
    const msg = msgs[i];
    if(String(msg?.role || '').trim() !== 'assistant') continue;
    const preview = _compactSessionPreviewText(bubbleMessageTextForComposer(msg), maxLen);
    if(preview) return preview;
  }
  return '';
}

function showCrossSessionCompletionNotice(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid || !crossSessionNoticeHostEl) return;
  if(isSessionVisibleInMainView(sid)) return;
  const s = getSessionById(sid);
  if(!s) return;
  const stateRaw = String(opts.state || 'done').trim().toLowerCase();
  const state = ['done','stopped','error','interrupted'].includes(stateRaw) ? stateRaw : 'done';
  const unreadChanged = state === 'done' ? setSessionUnreadCompletedReply(sid, true) : false;
  if(unreadChanged) renderList();
  const kicker = String(opts.kicker || '').trim();
  const title = String(opts.title || s.title || '新会话').trim() || '新会话';
  const previewText = getSessionAnswerPreview(sid, { currentText: opts.previewText || opts.message || '', maxLen: 120 });
  const fallbackSub = state === 'done' ? '回答已完成，点击查看' : state === 'stopped' ? '已停止生成，点击查看' : state === 'interrupted' ? '连接中断，点击查看' : '生成结束，点击查看';
  const sub = String(previewText || opts.message || fallbackSub).trim();
  const dedupeKey = `${state}|${kicker}|${title}|${sub}`;
  if(crossSessionNoticeKeys[sid] === dedupeKey) return;
  crossSessionNoticeKeys[sid] = dedupeKey;
  dismissCrossSessionCompletionNotice(sid);
  const item = document.createElement('button');
  item.type = 'button';
  item.className = 'cross-session-notice';
  item.dataset.state = state;
  item.innerHTML = `
    <span class="cross-session-notice-icon" aria-hidden="true"></span>
    <span class="cross-session-notice-body">
      ${kicker ? `<span class="cross-session-notice-kicker">${escapeHtml(kicker)}</span>` : ''}
      <span class="cross-session-notice-title">${escapeHtml(title)}</span>
      <span class="cross-session-notice-sub">${escapeHtml(sub)}</span>
    </span>
    <span class="cross-session-notice-arrow" aria-hidden="true">↗</span>
  `;
  item.addEventListener('click', ()=>{
    dismissCrossSessionCompletionNotice(sid);
    setActive(sid);
  });
  crossSessionNoticeHostEl.appendChild(item);
  crossSessionNoticeItems[sid] = item;
  requestAnimationFrame(()=> item.classList.add('show'));
  crossSessionNoticeTimers[sid] = setTimeout(()=> dismissCrossSessionCompletionNotice(sid), Math.max(3600, Number(opts.duration) || 6800));
}

function _fmtMeta(meta){
  // 已禁用 meta 调试信息（rounds/web/server/tokens 等）
  return "";
}



function isNearBottom(threshold=120){
  return (chatEl.scrollHeight - chatEl.clientHeight - chatEl.scrollTop) <= threshold;
}

function maybeAutoScroll(force=false){
  if(force || shouldAutoStickBottom){
    chatEl.scrollTop = chatEl.scrollHeight;
  }
  scrollChatToBottom(false);
}

function setSendButtonMode(mode){
  const isStreaming = mode === "streaming";
  if(chatEl){
    const sid = String(store?.activeId || visibleChatSessionId || '').trim();
    const locked = isStreaming && !!sid && isSessionStreamingUiLocked(sid);
    chatEl.classList.toggle('chat-regenerate-actions-locked', locked);
    try{ document.body?.classList?.toggle('chat-regenerate-actions-locked', locked); }catch(_){ }
    scheduleRefreshRegenerateActionsForVisibleSession(sid);
  }
  if(sendBtn){
    sendBtn.textContent = isStreaming ? "■" : "↑";
    sendBtn.title = isStreaming ? (window.AperviaI18n?.t('composer.stop') || "停止生成") : (window.AperviaI18n?.t('composer.send') || "发送");
    sendBtn.setAttribute("aria-label", sendBtn.title);
    sendBtn.dataset.mode = isStreaming ? "stop" : "send";
    sendBtn.disabled = false;
  }
  if(stopBtn){
    stopBtn.classList.add("send-stop-hidden");
    stopBtn.disabled = !isStreaming;
  }
  autoResizeInput();
updateComposerActionState();
}

function hasPendingComposerAttachments(){
  return (Array.isArray(pendingFiles) && pendingFiles.length > 0) || (Array.isArray(pastedImages) && pastedImages.length > 0);
}

function updateComposerPlaceholder(){
  if(!inputEl) return;
  let placeholder = window.AperviaI18n?.t('composer.placeholder') || "有问题，尽管问";
  if(Array.isArray(pastedImages) && pastedImages.length > 0) placeholder = window.AperviaI18n?.t('composer.image_placeholder') || "结合图片提问";
  else if(hasPendingComposerAttachments()) placeholder = window.AperviaI18n?.t('composer.attachment_placeholder') || "基于附件提问";
  inputEl.placeholder = placeholder;
  document.documentElement.style.setProperty('--composer-placeholder', JSON.stringify(placeholder));
}

function syncComposerAttachmentLayoutState(){
  const hasAttachments = !!(imagePreviewEl && imagePreviewEl.children.length > 0);
  if(composerInputShellEl) composerInputShellEl.classList.toggle("has-attachments", hasAttachments);
  return hasAttachments;
}

function updateComposerActionState(){
  syncComposerAttachmentLayoutState();
  if(!sendBtn) return;
  if(sendBtn.dataset.mode === "stop"){
    sendBtn.disabled = false;
    updateComposerPlaceholder();
    refreshArchivedComposerState();
    return;
  }
  if(!isHomeLandingView && isSessionArchived(getActive())){
    sendBtn.disabled = true;
    updateComposerPlaceholder();
    refreshArchivedComposerState();
    return;
  }
  const hasText = !!String(inputEl?.value || "").trim();
  const hasPending = hasPendingComposerAttachments();
  const hasQuote = !!normalizeAssistantQuoteText(composerQuoteState?.text || '');
  const hasUploadBlock = (typeof hasBlockingComposerAttachmentUploads === 'function') && hasBlockingComposerAttachmentUploads();
  sendBtn.disabled = hasUploadBlock || !(hasText || hasPending || hasQuote);
  updateComposerPlaceholder();
  refreshArchivedComposerState();
}

function beginComposerEditMessage(btn, messageIndex, msg){
  const s = getActive();
  if(!s || isSessionStreaming(s.id)) return;
  const idx = Number(messageIndex);
  const sourceMsg = Number.isInteger(idx) ? (s.messages || [])[idx] : msg;
  if(!Number.isInteger(idx) || !isInlineEditableUserMessage(sourceMsg || msg)) return;
  beginInlineMessageEdit(btn, idx);
}

async function beginRegenerateAnswer(btn, assistantIndex){
  const s = getActive();
  if(!s || isSessionStreaming(s.id)) return;
  const userIndex = findPrevUserMessageIndex(s.messages || [], assistantIndex);
  if(userIndex < 0) return;
  const askMsg = s.messages[userIndex];
  const assistantMsg = (s.messages || [])[Number(assistantIndex)];
  const ask = bubbleMessageTextForComposer(askMsg);
  if(!ask) return;
  setComposerEditState({
    mode: "regenerate",
    userIndex,
    assistantIndex: Number(assistantIndex),
    userClientId: (typeof messageStableClientIdentity === 'function' ? messageStableClientIdentity(askMsg) : ''),
    userCreatedAtMs: (typeof messageCreatedAtComparableMs === 'function' ? messageCreatedAtComparableMs(askMsg) : 0),
    userTextSig: (typeof userMessageComparableText === 'function' ? userMessageComparableText(askMsg) : ''),
    assistantClientId: (typeof messageStableClientIdentity === 'function' ? messageStableClientIdentity(assistantMsg) : ''),
    assistantCreatedAtMs: (typeof messageCreatedAtComparableMs === 'function' ? messageCreatedAtComparableMs(assistantMsg) : 0),
    assistantTextSig: (typeof assistantMessageComparableText === 'function' ? assistantMessageComparableText(assistantMsg) : ''),
    assistantImageSig: (typeof assistantImageReplyComparableSignature === 'function' ? assistantImageReplyComparableSignature(assistantMsg) : ''),
    assistantContentKind: (typeof assistantMessageContentKind === 'function' ? assistantMessageContentKind(assistantMsg) : ''),
    preview: getMessageDisplaySnippet(askMsg)
  });
  inputEl.value = ask;
  autoResizeInput();
  updateComposerActionState();
  try{
    if(typeof persistActiveComposerDraft === 'function') persistActiveComposerDraft(inputEl.value);
    else persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value);
  }catch(_){ persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value); }
  try{ btn?.closest('.bubble')?.classList.add('bubble-editing'); setTimeout(()=>btn?.closest('.bubble')?.classList.remove('bubble-editing'), 1200); }catch(_){ }
  try{ scrollComposerIntoView(); }catch(_){ }
  await send();
}

function assistantContinuationPromptFromText(baseText){
  const text = String(baseText || '').trim();
  if(!text) return '';
  return [
    '请继续上一条助手回答，从它停止的位置自然接着写。',
    '不要重复已经写过的内容，不要重新开头，不要解释“我将继续”。',
    '如果上一条回答明显未完成，请直接补完整；如果已经完成，请补充下一步有价值的内容。',
  ].join('\n');
}

async function beginContinueAssistantAnswer(btn, assistantIndex){
  const s = getActive();
  const sid = String(s?.id || store?.activeId || '').trim();
  if(!s || !sid || isSessionStreaming(sid)) return;
  if(isSessionArchived(s)){
    refreshArchivedComposerState();
    try{ toast(window.AperviaI18n?.t('composer.archived') || 'This conversation is archived. Unarchive it before continuing.'); }catch(_){ }
    return;
  }
  if(isCloudSessionStub(s)){
    setStatus('正在加载当前对话，加载完成后再继续…');
    const hydrated = await hydrateActiveSessionAfterSwitch(sid, { force:true, statusText:'已加载当前会话' });
    if(!hydrated && isCloudSessionStub(getSessionById(sid))){
      try{ toast(window.AperviaI18n?.t('composer.loading_wait') || 'This conversation is still loading. Try again shortly.'); }catch(_){ }
      return;
    }
  }
  const idx = Number(assistantIndex);
  const rows = Array.isArray(getSessionById(sid)?.messages) ? getSessionById(sid).messages : [];
  const msg = Number.isInteger(idx) && idx >= 0 ? rows[idx] : null;
  if(!msg || String(msg.role || '').toLowerCase() !== 'assistant') return;
  const baseText = bubbleMessageTextForComposer(msg).trim();
  if(!baseText) return;
  const continuationPrompt = assistantContinuationPromptFromText(baseText);
  if(!continuationPrompt) return;
  const streamCheck = canStartStreamingForSession(sid);
  if(!streamCheck.ok){
    const blockText = describeParallelStreamBlock(streamCheck);
    if(blockText) setStatus(blockText);
    return;
  }
  const messageId = String(
    (typeof messageStableClientIdentity === 'function' ? messageStableClientIdentity(msg) : '')
    || msg.localId || msg.local_id || msg.messageLocalId || msg.message_local_id || ''
  ).trim();
  const continuationTarget = {
    messageIndex: idx,
    messageId,
    baseText,
  };
  try{
    if(btn){
      btn.disabled = true;
      btn.classList.add('is-loading');
    }
  }catch(_){ }
  clearSessionBackendError(sid, { render:false });
  dismissCrossSessionCompletionNotice(sid);
  clearGlobalAppError();
  prepareSessionForCleanAssistantTurn(sid, { immediate:true });
  try{ webaiOfficialCleanupStaleRuntimeBeforeSend(sid); }catch(_){ }
  const startedAt = Date.now();
  persistPendingAssistantSnapshot(sid, {
    draft: '',
    status: '继续回答中…',
    streaming: true,
    files: [],
    imageReplies: [],
    rtStartAt: startedAt,
    rtFinalMs: 0,
  }, { immediate:true });
  const rt = ensureSessionRuntime(sid);
  rt.assistantContinuationTarget = continuationTarget;
  rt.streaming = true;
  rt.statusText = '继续回答中…';
  rt.draftText = '';
  rt.draftProcessText = '';
  rt.draftFiles = [];
  rt.draftImageReplies = [];
  rt.draftWeatherPayload = null;
  rt.reasoning = [];
  rt.reasoningMeta = {};
  rt.sources = [];
  rt.generationUsage = null;
  rt.rtStartAt = startedAt;
  rt.rtFinalMs = 0;
  try{ btn?.closest('.bubble')?.classList.add('bubble-editing'); setTimeout(()=>btn?.closest('.bubble')?.classList.remove('bubble-editing'), 1200); }catch(_){ }
  setStatus('继续回答中…');
  const requestBody = await buildAsyncChatRequestBodyForSession(sid, {
    text: continuationPrompt,
    localImgMap: new Map(),
    maxMessageIndex: idx,
    extraRequestMessages: [{ role:'user', content: continuationPrompt }],
  });
  requestBody.disable_tools = true;
  requestBody.skip_prepare_messages = true;
  requestBody.disable_visual_prefetch = true;
  requestBody.web_enabled = false;
  requestBody.image_generation_enabled = false;
  requestBody.kb_enabled = false;
  return attachSessionToAsyncJob(sid, { requestBody, assistantContinuationTarget: continuationTarget });
}

function scrollComposerIntoView(){
  const composer = document.querySelector('.composer');
  if(!composer) return;
  composer.scrollIntoView({ block:'end', behavior:'smooth' });
}



/* Message media/content rendering is loaded from index3-message-media-render-ui.js. */

/* Chat render/edit/branch UI is loaded from index3-chat-render-ui.js. */

/* Sidebar session/search/render UI moved to index3-sidebar-session-ui.js. */

function bindComposerAndSidebarUiEvents(){
  if(sessionSearchEl && sessionSearchEl.dataset.searchInputBound !== '1'){
    sessionSearchEl.addEventListener("input", ()=>{
      sessionSearchText = String(sessionSearchEl.value || "").trim().toLowerCase();
      renderSessionSearchResults();
    });
    sessionSearchEl.dataset.searchInputBound = '1';
  }

  if(focusSessionSearchBtn && focusSessionSearchBtn.dataset.searchOpenBound !== '1'){
    focusSessionSearchBtn.addEventListener("click", ()=>{
      openSessionSearchModal();
    });
    focusSessionSearchBtn.dataset.searchOpenBound = '1';
  }
  if(sessionSearchCloseBtn && sessionSearchCloseBtn.dataset.searchCloseBound !== '1'){
    sessionSearchCloseBtn.addEventListener("click", ()=>{
      closeSessionSearchModal();
    });
    sessionSearchCloseBtn.dataset.searchCloseBound = '1';
  }
  if(sessionSearchModalEl && sessionSearchModalEl.dataset.searchBackdropBound !== '1'){
    sessionSearchModalEl.addEventListener("click", (event)=>{
      if(event.target === sessionSearchModalEl) closeSessionSearchModal();
    });
    sessionSearchModalEl.dataset.searchBackdropBound = '1';
  }
  if(openSettingsSidebarBtn && openSettingsSidebarBtn.dataset.settingsOpenBound !== '1'){
    openSettingsSidebarBtn.addEventListener("click", ()=>{
      document.getElementById("openSettingsBtn")?.click();
    });
    openSettingsSidebarBtn.dataset.settingsOpenBound = '1';
  }
  if(document.body?.dataset?.sidebarMenuGlobalBound !== '1'){
    document.addEventListener("pointerdown", (event)=>{
      if(!chatListEl) return;
      if(event.target.closest(".ow-chat-menu") || event.target.closest(".ow-chat-menu-trigger")) return;
      closeSidebarSessionMenus();
    }, true);
    document.addEventListener("keydown", (event)=>{
      if(event.key !== "Escape") return;
      if(sessionSearchModalEl?.classList.contains("open")){
        closeSessionSearchModal();
        return;
      }
      closeSidebarSessionMenus();
    });
    document.body.dataset.sidebarMenuGlobalBound = '1';
  }
  if(inputEl && inputEl.dataset.enterSendBound !== '1'){
    inputEl.addEventListener("keydown", (e)=>{
      if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        send();
      }
    });
    inputEl.dataset.enterSendBound = '1';
  }
}
bindComposerAndSidebarUiEvents();


function syncModelPickerFromSelect(){
  if(modelPickerLabel) modelPickerLabel.textContent = modelEl?.value
    ? (modelEl?.selectedOptions?.[0]?.textContent || modelEl.value)
    : "未选择模型";
  if(modelPickerPanel){
    modelPickerPanel.querySelectorAll(".model-option").forEach((btn)=>{
      const active = btn.dataset.value === modelEl.value;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
  }
  try{
    if(typeof syncResponsesReasoningEffortFieldVisibility === "function") syncResponsesReasoningEffortFieldVisibility();
  }catch(_){ }
}

function closeModelPicker(){
  modelPickerEl?.classList.remove("open");
  modelPickerBtn?.setAttribute("aria-expanded", "false");
}
function openModelPicker(){
  modelPickerEl?.classList.add("open");
  modelPickerBtn?.setAttribute("aria-expanded", "true");
}
function bindModelPicker(){
  if(!modelEl || !modelPickerPanel || !modelPickerBtn) return;
  rebuildModelPickerOptions = ()=>{
    const options = Array.from(modelEl.options || []);
    modelPickerPanel.innerHTML = "";
    for(const opt of options){
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "model-option";
      btn.dataset.value = opt.value;
      btn.setAttribute("role", "option");
      btn.innerHTML = `<span>${escapeHtml(opt.textContent || opt.value)}</span>`;
      btn.addEventListener("click", ()=>{
        const nextValue = opt.value;
        const prevValue = modelEl.value;
        if(prevValue !== nextValue){
          modelEl.value = nextValue;
          modelEl.dispatchEvent(new Event("change", {bubbles:true}));
        }
        closeModelPicker();
        modelPickerBtn.focus();
      });
      modelPickerPanel.appendChild(btn);
    }
    syncModelPickerFromSelect();
  };
  rebuildModelPickerOptions();
  modelPickerBtn.addEventListener("click", (e)=>{
    e.stopPropagation();
    if(modelPickerEl?.classList.contains("open")) closeModelPicker(); else openModelPicker();
  });
  modelPickerPanel.addEventListener("click", (e)=> e.stopPropagation());
  document.addEventListener("click", (e)=>{ if(!e.target?.closest?.("#modelPicker")) closeModelPicker(); });
  document.addEventListener("keydown", (e)=>{ if(e.key === "Escape") closeModelPicker(); });
}

function renderAll(){
  const s = getActive() || {};
  refreshTemporaryChatUi();
  if(typeof syncActiveChatShareButton === "function") syncActiveChatShareButton();
  activeTitleEl.textContent = isHomeLandingView ? "" : s.title;
  syncModelOptionsForActiveProfile({preferredModel: s.model || "", ensureSessionValue:true});
  if(webToggleEl) webToggleEl.checked = !!s.webEnabled;
  if(imageGenToggleEl) imageGenToggleEl.checked = !!s.imageGenerationEnabled;
  refreshThinkingControlUi();
  // ✅ 只有正在查看“当前流式输出的那个会话”时，才避免重渲染 chat
  if(isHomeLandingView || !isSessionStreaming(s.id) || visibleChatSessionId !== s.id) renderChat();
  renderList();
  refreshComposerEditBar();
  refreshArchivedComposerState();
  refreshStatusForActiveSession();
}

document.addEventListener('apervia:languagechange', () => {
  try{ invalidateSidebarRenderCache(); }catch(_){ }
  try{ invalidateChatRenderCache(); }catch(_){ }
  try{ updateComposerPlaceholder(); }catch(_){ }
  try{ renderAll(); }catch(error){ console.warn('language rerender failed:', error); }
});

modelEl.addEventListener("change", ()=>{
  const current = getActive();
  const prevModel = String(current?.model || "").trim();
  const nextModel = String(modelEl.value || "").trim();
  const modelChanged = prevModel !== nextModel;
  syncModelPickerFromSelect();
  if(isHomeLandingView){
    homeLandingPrefs.model = nextModel;
    if(modelChanged){
      homeLandingPrefs.chatThinkingType = "auto";
      saveChatPrefs(homeLandingPrefs);
      if(nextModel) persistActiveModelSelection(nextModel, {silent:true});
      else updateCurrentApiProfile(cur => ({ ...cur, last_model:"" }));
      toast(nextModel
        ? (window.AperviaI18n?.t('settings.model_switched', {model:modelEl?.selectedOptions?.[0]?.textContent || nextModel}) || `Switched successfully: ${modelEl?.selectedOptions?.[0]?.textContent || nextModel}`)
        : (window.AperviaI18n?.t('settings.model_cleared') || 'Model selection cleared'));
      safeRenderAll();
    }else{
      saveChatPrefs(homeLandingPrefs);
      refreshThinkingControlUi();
    }
    return;
  }
  if(modelChanged){
    updateActive(s => {
      s.model = nextModel;
      s.chatThinkingType = "auto";
    });
    saveChatPrefs({ model: nextModel, chatThinkingType: "auto" });
    if(nextModel) persistActiveModelSelection(nextModel, {silent:true});
    else updateCurrentApiProfile(cur => ({ ...cur, last_model:"" }));
    toast(nextModel
      ? (window.AperviaI18n?.t('settings.model_switched', {model:modelEl?.selectedOptions?.[0]?.textContent || nextModel}) || `Switched successfully: ${modelEl?.selectedOptions?.[0]?.textContent || nextModel}`)
      : (window.AperviaI18n?.t('settings.model_cleared') || 'Model selection cleared'));
    return;
  }
  refreshThinkingControlUi();
});

if(webToggleEl){
  webToggleEl.addEventListener("change", ()=>{
    const enabled = !!webToggleEl.checked;
    if(isHomeLandingView){
      homeLandingPrefs.webEnabled = enabled;
      saveChatPrefs(homeLandingPrefs);
      return;
    }
    saveChatPrefs({ webEnabled: enabled });
    updateActive(s => { s.webEnabled = enabled; });
  });
}

if(imageGenToggleEl){
  imageGenToggleEl.addEventListener("change", ()=>{
    const enabled = !!imageGenToggleEl.checked;
    if(isHomeLandingView){
      homeLandingPrefs.imageGenerationEnabled = enabled;
      saveChatPrefs(homeLandingPrefs);
      return;
    }
    saveChatPrefs({ imageGenerationEnabled: enabled });
    updateActive(s => { s.imageGenerationEnabled = enabled; });
  });
}

function updateComposerWidth(){
  if(!inputEl) return;
  document.documentElement.style.setProperty("--gpt-composer-width", window.innerWidth <= 980 ? "calc(100% - 32px)" : "760px");
}

function updateComposerBottomSpace(){
  try{
    const composerEl = document.querySelector(".composer");
    if(!composerEl){
      document.documentElement.style.removeProperty("--composer-bottom-space");
      document.documentElement.style.removeProperty("--composer-input-underlay-height");
      return;
    }
    const isHomeEmpty = document.body.classList.contains("home-empty") && mainEl?.classList.contains("home-empty");
    if(isHomeEmpty){
      document.documentElement.style.setProperty("--composer-bottom-space", "28px");
      document.documentElement.style.removeProperty("--composer-input-underlay-height");
      return;
    }
    const rect = composerEl.getBoundingClientRect();
    const composerHeight = Math.ceil(rect?.height || composerEl.offsetHeight || 0);
    const isFloatingComposer = getComputedStyle(composerEl).position === "fixed";
    const reserveExtra = isFloatingComposer ? 44 : 16;
    const viewportHeight = Math.max(0, window.innerHeight || document.documentElement.clientHeight || 0);
    if(isFloatingComposer){
      const underlayHeight = Math.max(0, Math.ceil(viewportHeight - Math.floor(rect?.top || 0)));
      document.documentElement.style.setProperty("--composer-input-underlay-height", underlayHeight + "px");
    }else{
      document.documentElement.style.removeProperty("--composer-input-underlay-height");
    }
    const floatingReserve = Math.ceil(viewportHeight * 0.4);
    const next = Math.max(isFloatingComposer ? floatingReserve : 72, composerHeight + reserveExtra);
    document.documentElement.style.setProperty("--composer-bottom-space", next + "px");
  }catch(_err){}
}

function resizeComposer(){
  updateComposerWidth();
  autoResizeInput();
  updateComposerBottomSpace();
}

function refreshComposerLayoutSoon(){
  try{
    resizeComposer();
    requestAnimationFrame(()=>resizeComposer());
    setTimeout(()=>resizeComposer(), 80);
  }catch(_err){}
}

function clearComposerPreviewDomForSend(){
  try{
    if(imagePreviewEl) imagePreviewEl.innerHTML = "";
    refreshComposerLayoutSoon();
  }catch(_err){}
}

try{
  if(imagePreviewEl && typeof MutationObserver !== "undefined"){
    const composerPreviewObserver = new MutationObserver(()=>{
      syncComposerAttachmentLayoutState();
      refreshComposerLayoutSoon();
    });
    composerPreviewObserver.observe(imagePreviewEl, { childList:true, subtree:false });
  }
}catch(_err){}

inputEl.addEventListener("input", ()=>{
  try{
    if(typeof persistActiveComposerDraft === 'function') persistActiveComposerDraft(inputEl.value || "");
    else persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value || "");
  }catch(_){ persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value || ""); }
  resizeComposer();
  updateComposerActionState();
});
window.addEventListener("resize", resizeComposer);
resizeComposer();
updateComposerBottomSpace();
updateComposerActionState();
initAssistantSelectionQuoteUi();
try{ queueMicrotask(()=>initVoiceInput()); }catch(_){ setTimeout(()=>initVoiceInput(), 0); }


inputEl.addEventListener("paste", async (e)=>{
  const items = Array.from(e.clipboardData?.items || []);
  const html = String(e.clipboardData?.getData?.('text/html') || '');
  const text = String(e.clipboardData?.getData?.('text/plain') || '');
  const uriList = String(e.clipboardData?.getData?.('text/uri-list') || '');

  const fileItems = items.filter(item => item.kind === "file");
  if(fileItems.length){
    e.preventDefault();
    let hasAny = false;
    for(const item of fileItems){
      const file = item.getAsFile?.();
      if(!file) continue;
      hasAny = true;
      if(isLikelyLocalImageFile(file)){
        await addImageFileToPreview(file);
        continue;
      }
      const previewId = addLocalUploadingPreview(file);
      try{
        await uploadOneFile(file, previewId);
      }catch(err){
        markLocalUploadingPreviewError(previewId, composerAttachmentT('composer.attachment.add_failed', null, 'Failed to add'));
        reportAppError(`粘贴文件失败：${file.name || "未命名文件"}：${err.message}`);
      }
    }
    if(hasAny) updateComposerActionState();
    return;
  }

  const remoteUrls = pickRemoteImageUrlsFromClipboardLikeData({ html, text, uriList });
  if(remoteUrls.length){
    e.preventDefault();
    await importRemoteImageUrls(remoteUrls, '粘贴的图片链接');
    return;
  }

  const autoTxtPlan = maybeAutoConvertLongMessageToTxt(text);
  if(autoTxtPlan?.converted){
    e.preventDefault();
    const previewId = addLocalUploadingPreview(autoTxtPlan.file);
    try{
      await uploadOneFile(autoTxtPlan.file, previewId);
      setStatus('长文本已添加为 txt 附件（待发送）');
      inputEl.focus();
    }catch(err){
      markLocalUploadingPreviewError(previewId, composerAttachmentT('composer.attachment.add_failed', null, 'Failed to add'));
      reportAppError(`长文本转 txt 失败：${err.message}`);
    }
  }
});

/* Async chat streaming/send pipeline is loaded from index3-async-chat-stream-ui.js. */

/* Upload and drag/drop UI is loaded from index3-upload-dragdrop-ui.js. */

/* 新建/清空 */
newChatBtn.addEventListener("click", async ()=>{
  if(getRouteLibraryTab()){
    try{ closeLibraryRoute({ replaceRoute:true }); }catch(_){ }
  }
  if(isImagePullbackRoute()){
    try{ closeImagePullbackRoute({ replaceRoute:true }); }catch(_){ }
  }
  enterHomeLandingView({ replace:true });
  safeRenderAll();
  rtReset();
  refreshStatusForActiveSession();
  try{ inputEl.focus(); }catch(_){ }
});
brandNewChatBtn?.addEventListener("click", ()=>{
  newChatBtn?.click();
});

temporaryChatToggleBtn?.addEventListener("click", async ()=>{
  const active = getActiveTemporarySession();
  if(active){
    if(!sessionHasMeaningfulConversation(active)){
      cancelTemporaryChat({ replace:true });
      return;
    }
    return;
  }
  if(!isHomeLandingView) return;
  const ok = await askTemporaryChatIntro(temporaryChatToggleBtn);
  if(!ok) return;
  enterTemporaryChat({ replace:true });
});

if(clearAllBtn){
  clearAllBtn.addEventListener("click", async ()=>{
    await askAndResetAllChats(clearAllBtn);
  });
}

// ✅ 启动：账号会话云端优先；未登录才读本地缓存
bindSettingsUi();
initComposerAddMenuUI();
bindModelPicker();
initStore();

function handleAppRouteChange(source='popstate'){
  if(applyModalRouteFromLocation({ source })) return;
  if(isSettingsModalOpen()) closeSettingsModal({ syncRoute:false });
  try{ if(document.getElementById('kbModalMask')?.classList.contains('open')) closeLibraryRoute({ syncRoute:false }); }catch(_){ }
  try{ if(document.getElementById('imagePullbackWorkspace')?.classList.contains('open')) closeImagePullbackRoute({ syncRoute:false }); }catch(_){ }
  const routeView = getCurrentSessionViewState();
  if(routeView.temporary){
    ensureTemporaryRouteSession({ preserveExisting:true });
    clearPastedImages({ preserveLocalCache:true, preservePreviewUrls:true });
    restoreComposerForCurrentView();
    clearComposerEditState();
    refreshStatusForActiveSession();
    safeRenderAll();
    return;
  }
  const routeId = String(routeView.sessionId || '').trim();
  if(routeId && store?.sessions?.[routeId]){
    isHomeLandingView = false;
    if(routeId !== store.activeId) setActive(routeId, { syncHistory:false });
    else {
      clearSessionUnreadWhenOpened(routeId, { render:false });
      clearPastedImages({ preserveLocalCache:true, preservePreviewUrls:true });
      restoreComposerForCurrentView();
      clearComposerEditState();
      refreshStatusForActiveSession();
      safeRenderAll();
    }
    return;
  }
  enterHomeLandingView({ syncHistory:false });
  refreshStatusForActiveSession();
  safeRenderAll();
}

window.addEventListener('popstate', ()=> handleAppRouteChange('popstate'));
window.addEventListener('hashchange', ()=> handleAppRouteChange('hashchange'));

/* Mobile shell/sidebar UI is loaded from index3-mobile-shell-ui.js. */

/* Knowledge base/file-library UI is loaded from index3-knowledge-base-ui.js. */
/* Image pullback workspace UI is loaded from index3-image-pullback-ui.js. */

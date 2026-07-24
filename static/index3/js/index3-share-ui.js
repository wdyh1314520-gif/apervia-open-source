/* 顶部分享与回答操作共用的真实会话快照弹窗。 */
const chatShareModalEl = document.getElementById('chatShareModal');
const chatShareTitleEl = document.getElementById('chatShareTitle');
const chatSharePreviewEl = document.getElementById('chatSharePreview');
const chatShareErrorEl = document.getElementById('chatShareError');
const chatShareCloseBtnEl = document.getElementById('chatShareCloseBtn');
const chatShareCopyBtnEl = document.getElementById('chatShareCopyBtn');
const chatShareWechatBtnEl = document.getElementById('chatShareWechatBtn');
const chatShareQqBtnEl = document.getElementById('chatShareQqBtn');
const chatShareWeiboBtnEl = document.getElementById('chatShareWeiboBtn');
const activeChatShareBtnEl = document.getElementById('activeChatShareBtn');
let chatShareState = { url:'', title:'', returnFocusEl:null, opening:false };
let chatShareOpenSeq = 0;
let activeChatShareCopying = false;

function getChatShareRouteToken(href=''){
  try{
    const url = new URL(String(href || location.href), location.origin);
    const match = String(url.pathname || '').match(/^\/share\/([A-Za-z0-9_-]{20,120})\/?$/);
    return match ? decodeURIComponent(String(match[1] || '')).trim() : '';
  }catch(_){ return ''; }
}

function isSharedChatPreviewSession(session){
  const row = session && typeof session === 'object' ? session : null;
  return !!(row && row._webaiSharedPreview === true && String(row.sharedFromToken || row.shared_from_token || '').trim());
}

async function initializeSharedChatPreviewFromRoute(){
  const token = getChatShareRouteToken();
  if(!token || typeof store === 'undefined' || !store?.sessions) return false;
  const previewId = 's_share_preview_' + token.slice(0, 32);
  const current = store.sessions?.[previewId];
  if(isSharedChatPreviewSession(current)){
    store.activeId = previewId;
    isHomeLandingView = false;
    safeRenderAll();
    restoreComposerForCurrentView();
    return true;
  }
  try{
    setStatus('正在读取分享会话…');
    const response = await fetch('/api3/chat-shares/' + encodeURIComponent(token), {
      method:'GET', credentials:'same-origin', cache:'no-store',
    });
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data?.error || ('HTTP ' + response.status));
    const rows = Array.isArray(data.messages) ? data.messages : [];
    const nowMs = Date.now();
    const messages = rows.map((item, index)=>({
      role:String(item?.role || 'assistant'),
      content:String(item?.content || ''),
      createdAt:nowMs + index,
      created_at:nowMs + index,
      _webai_shared_snapshot:true,
    })).filter(item=>item.content.trim() && (item.role === 'user' || item.role === 'assistant'));
    if(!messages.length) throw new Error('分享内容没有可预览的消息');
    const mode = String(data.conversation_mode || '').trim().toLowerCase() === 'response' ? 'response' : 'chat';
    const endpointMode = mode === 'response' ? 'responses' : 'chat_completions';
    const previewSession = {
      id:previewId,
      title:String(data.title || '分享的聊天'),
      model:String(data.model || ''),
      createdAt:nowMs,
      updatedAt:nowMs + messages.length,
      conversationMode:mode,
      conversation_mode:mode,
      api_endpoint_mode:endpointMode,
      endpoint_mode:endpointMode,
      temporaryChat:true,
      temporary_chat:true,
      titleAutoLocked:true,
      aiTitleDone:true,
      sharedFromToken:token,
      shared_from_token:token,
      _webaiSharedPreview:true,
      messages,
      composerDraft:'',
      composerQuoteDraft:null,
      composerAttachmentDraft:{ files:[], images:[] },
    };
    cleanupInactiveTemporarySessions(previewId);
    store.sessions[previewId] = previewSession;
    store.activeId = previewId;
    isHomeLandingView = false;
    try{ if(typeof setComposerInputOwnerSessionId === 'function') setComposerInputOwnerSessionId(previewId); }catch(_){ }
    safeRenderAll();
    restoreComposerForCurrentView();
    setStatus('分享会话预览');
    try{ inputEl?.focus?.({ preventScroll:true }); }catch(_){ }
    return true;
  }catch(err){
    try{ reportAppError(err?.message || err || '无法打开分享会话'); }catch(_){ }
    setStatus('分享会话打开失败');
    return false;
  }
}

async function promoteSharedChatPreviewForSend(sessionId=''){
  const previewId = String(sessionId || store?.activeId || '').trim();
  const preview = store?.sessions?.[previewId];
  if(!isSharedChatPreviewSession(preview)) return previewId;
  const token = String(preview.sharedFromToken || preview.shared_from_token || '').trim();
  if(!token) return '';
  try{
    setStatus('正在创建你的独立会话…');
    const response = await fetch('/api3/chat-shares/' + encodeURIComponent(token) + '/continue', {
      method:'POST', credentials:'same-origin', headers:{ 'Content-Type':'application/json' }, body:'{}',
    });
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data?.error || ('HTTP ' + response.status));
    const stableId = String(data.session_id || '').trim();
    if(!stableId) throw new Error('没有创建稳定会话');
    let stableSession = null;
    if(data.existing && typeof ensureCloudSessionLoadedIntoStore === 'function'){
      try{
        await ensureCloudSessionLoadedIntoStore(stableId, { makeActive:true, force:true });
        stableSession = store?.sessions?.[stableId] || null;
      }catch(_){ }
    }
    if(!stableSession){
      stableSession = { ...preview, id:stableId, temporaryChat:false, temporary_chat:false, _webaiSharedPreview:false, syncStatus:'active', sync_status:'active' };
      delete stableSession.isTemporary;
      delete stableSession._temporaryChat;
      store.sessions[stableId] = stableSession;
    }
    delete store.sessions[previewId];
    store.activeId = stableId;
    isHomeLandingView = false;
    try{ if(typeof currentCloudStoreRevision !== 'undefined') currentCloudStoreRevision = Math.max(Number(currentCloudStoreRevision || 0), Number(data.revision || 0)); }catch(_){ }
    try{ if(typeof setComposerInputOwnerSessionId === 'function') setComposerInputOwnerSessionId(stableId); }catch(_){ }
    saveStore();
    syncSessionRoute({ sessionId:stableId, replace:true, leaveSharedPreview:true });
    return stableId;
  }catch(err){
    try{ toast(window.AperviaI18n?.t('share.create_conversation_failed', {error:err?.message || err}) || `Unable to create a separate conversation: ${err?.message || err}`); }catch(_){ }
    setStatus('独立会话创建失败');
    return '';
  }
}

function syncActiveChatShareButton(){
  if(!activeChatShareBtnEl) return;
  const session = store?.sessions?.[store?.activeId];
  const isTemporary = !!session && typeof isTemporarySession === 'function' && isTemporarySession(session);
  const visible = !isHomeLandingView && !!session && !isTemporary;
  activeChatShareBtnEl.hidden = !visible;
  activeChatShareBtnEl.disabled = activeChatShareCopying || !visible || !chatShareVisibleRows(session).length;
}

function chatShareMessageText(message){
  const msg = message && typeof message === 'object' ? message : {};
  let text = '';
  try{ text = bubbleMessageTextForComposer(msg); }catch(_){ }
  if(!String(text || '').trim()){
    try{ text = getMessageDisplaySnippet(msg); }catch(_){ }
  }
  if(!String(text || '').trim()){
    const content = msg.content;
    const kind = content && typeof content === 'object' && !Array.isArray(content) ? String(content._kind || content.kind || '') : '';
    text = kind === 'image_reply' || kind === 'image' ? '[图片]' : (kind === 'file' ? '[文件]' : '');
  }
  text = String(text || '').replace(/\x00/g, '').trim();
  if(String(msg.role || '').trim().toLowerCase() === 'assistant' && typeof normalizeCompactErrorText === 'function' && /^AI服务异常\s*[：:]/.test(text)){
    text = normalizeCompactErrorText(text);
  }
  return text;
}

function chatShareVisibleRows(session, throughMessageIndex=null){
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const hasCutoff = throughMessageIndex !== null && throughMessageIndex !== undefined && Number.isInteger(Number(throughMessageIndex));
  const cutoffIndex = hasCutoff ? Number(throughMessageIndex) : Number.POSITIVE_INFINITY;
  const rows = [];
  messages.forEach((message, index)=>{
    if(index > cutoffIndex) return;
    const role = String(message?.role || '').trim().toLowerCase();
    if(role !== 'user' && role !== 'assistant') return;
    const content = chatShareMessageText(message);
    if(!content) return;
    rows.push({ role, content });
  });
  return rows;
}

function setChatShareError(message=''){
  if(!chatShareErrorEl) return;
  const text = String(message || '').trim();
  chatShareErrorEl.hidden = !text;
  chatShareErrorEl.textContent = text;
}

function setChatShareActionsEnabled(enabled){
  [chatShareCopyBtnEl, chatShareWechatBtnEl, chatShareQqBtnEl, chatShareWeiboBtnEl].forEach(btn=>{
    if(btn) btn.disabled = !enabled;
  });
}

function renderChatSharePreview(rows){
  if(!chatSharePreviewEl) return;
  chatSharePreviewEl.replaceChildren();
  const list = Array.isArray(rows) ? rows : [];
  list.forEach((row)=>{
    const card = document.createElement('article');
    card.className = `chat-share-preview-message ${row.role === 'user' ? 'user' : 'assistant'}`;
    const text = document.createElement('div');
    text.className = 'chat-share-preview-text bubble-body';
    if(row.role === 'assistant'){
      try{ text.innerHTML = renderMessageHtml('assistant', row.content); }
      catch(_){ text.textContent = row.content; }
    }else{
      text.textContent = row.content;
    }
    card.appendChild(text);
    chatSharePreviewEl.appendChild(card);
  });
  const brand = document.createElement('div');
  brand.className = 'chat-share-preview-brand';
  brand.textContent = 'Apervia';
  chatSharePreviewEl.appendChild(brand);
}

function closeChatShareModal(){
  if(!chatShareModalEl) return;
  chatShareOpenSeq += 1;
  chatShareModalEl.classList.remove('open');
  chatShareModalEl.hidden = true;
  chatShareModalEl.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  const focusEl = chatShareState.returnFocusEl;
  chatShareState = { url:'', title:'', returnFocusEl:null, opening:false };
  try{ focusEl?.focus?.({ preventScroll:true }); }catch(_){ }
}

async function openChatShareModal(sessionId='', messageIndex=null, returnFocusEl=null){
  if(!chatShareModalEl || chatShareState.opening) return false;
  const sid = String(sessionId || store?.activeId || '').trim();
  let session = store?.sessions?.[sid];
  if(!sid || !session) return false;
  if(typeof isTemporarySession === 'function' && isTemporarySession(session)){
    try{ toast(window.AperviaI18n?.t('share.temporary_unavailable') || 'Temporary chats are not saved and cannot be shared publicly.'); }catch(_){ }
    return false;
  }
  const openSeq = ++chatShareOpenSeq;
  const displayTitle = sessionDisplayTitle(session.title || window.AperviaI18n?.t('share.chat_fallback') || 'Shared conversation');
  chatShareState = { url:'', title:displayTitle, returnFocusEl:returnFocusEl || null, opening:true };
  chatShareModalEl.hidden = false;
  chatShareModalEl.classList.add('open');
  chatShareModalEl.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  setChatShareError('');
  setChatShareActionsEnabled(false);
  if(chatShareTitleEl) chatShareTitleEl.textContent = displayTitle;
  if(chatSharePreviewEl) chatSharePreviewEl.innerHTML = '<div class="chat-share-preview-more">正在准备安全快照…</div>';
  try{
    if(typeof sessionNeedsCloudHydrate === 'function' && sessionNeedsCloudHydrate(session) && typeof ensureCloudSessionLoadedIntoStore === 'function'){
      await ensureCloudSessionLoadedIntoStore(sid, { makeActive:false, force:true });
      if(openSeq !== chatShareOpenSeq) return false;
      session = store?.sessions?.[sid] || session;
    }
    const rows = chatShareVisibleRows(session, messageIndex);
    if(!rows.length) throw new Error('这部分内容暂时无法分享');
    renderChatSharePreview(rows);
    const response = await fetch('/api3/chat-shares', {
      method:'POST',
      credentials:'same-origin',
      headers:{ 'Content-Type':'application/json' },
      body:JSON.stringify({
        session_id:sid,
        scope:'conversation',
        title:String(session.title || '分享的聊天'),
        model:String(session.model || ''),
        conversation_mode:typeof sessionConversationMode === 'function' ? sessionConversationMode(session) : String(session.conversationMode || session.conversation_mode || 'chat'),
        messages:rows,
      }),
    });
    const data = await response.json().catch(()=>({}));
    if(openSeq !== chatShareOpenSeq) return false;
    if(!response.ok) throw new Error(data?.error || ('HTTP ' + response.status));
    chatShareState.url = String(data.url || '').trim();
    chatShareState.title = sessionDisplayTitle(data.title || session.title || window.AperviaI18n?.t('share.chat_fallback') || 'Shared conversation');
    if(!chatShareState.url) throw new Error('没有生成分享链接');
    setChatShareActionsEnabled(true);
    chatShareState.opening = false;
    try{ chatShareCopyBtnEl?.focus?.({ preventScroll:true }); }catch(_){ }
    return true;
  }catch(err){
    if(openSeq !== chatShareOpenSeq) return false;
    chatShareState.opening = false;
    setChatShareError(err?.message || err || '创建分享失败');
    return false;
  }
}

async function copyChatShareLink(){
  const url = String(chatShareState.url || '').trim();
  if(!url) return;
  try{
    if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(url);
    else copyText(url);
    flashChatShareCopyState();
  }catch(_){
    try{
      copyText(url);
      flashChatShareCopyState();
    }catch(__){ }
  }
}

function flashChatShareCopyState(){
  if(!chatShareCopyBtnEl) return;
  const label = chatShareCopyBtnEl.querySelector('strong');
  if(!label) return;
  const restoreText = String(label.dataset.restoreText || label.textContent || window.AperviaI18n?.t('share.copy_link') || 'Copy link').trim() || 'Copy link';
  label.dataset.restoreText = restoreText;
  label.textContent = window.AperviaI18n?.t('share.link_copied') || 'Link copied!';
  chatShareCopyBtnEl.classList.add('copied');
  clearTimeout(chatShareCopyBtnEl._copiedTimer);
  chatShareCopyBtnEl._copiedTimer = setTimeout(()=>{
    label.textContent = restoreText;
    chatShareCopyBtnEl.classList.remove('copied');
  }, 1500);
}

async function copyActiveChatShareLinkDirect(){
  if(activeChatShareCopying) return false;
  const sid = String(store?.activeId || '').trim();
  let session = store?.sessions?.[sid];
  if(!sid || !session) return false;
  if(typeof isTemporarySession === 'function' && isTemporarySession(session)){
    try{ toast(window.AperviaI18n?.t('share.temporary_unavailable') || 'Temporary chats are not saved and cannot be shared publicly.'); }catch(_){ }
    return false;
  }
  activeChatShareCopying = true;
  syncActiveChatShareButton();
  try{
    if(typeof sessionNeedsCloudHydrate === 'function' && sessionNeedsCloudHydrate(session) && typeof ensureCloudSessionLoadedIntoStore === 'function'){
      await ensureCloudSessionLoadedIntoStore(sid, { makeActive:false, force:true });
      session = store?.sessions?.[sid] || session;
    }
    const rows = chatShareVisibleRows(session);
    if(!rows.length) throw new Error('当前会话没有可分享的内容');
    const response = await fetch('/api3/chat-shares', {
      method:'POST',
      credentials:'same-origin',
      headers:{ 'Content-Type':'application/json' },
      body:JSON.stringify({
        session_id:sid,
        scope:'conversation',
        title:String(session.title || '分享的聊天'),
        model:String(session.model || ''),
        conversation_mode:typeof sessionConversationMode === 'function' ? sessionConversationMode(session) : String(session.conversationMode || session.conversation_mode || 'chat'),
        messages:rows,
      }),
    });
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data?.error || ('HTTP ' + response.status));
    const url = String(data.url || '').trim();
    if(!url) throw new Error('没有生成分享链接');
    if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(url);
    else copyText(url);
    try{ toast(window.AperviaI18n?.t('share.link_copied_toast') || 'Share link copied'); }catch(_){ }
    return true;
  }catch(err){
    try{ toast(window.AperviaI18n?.t('share.copy_failed', {error:err?.message || err}) || `Unable to copy the share link: ${err?.message || err}`); }catch(_){ }
    return false;
  }finally{
    activeChatShareCopying = false;
    syncActiveChatShareButton();
  }
}

async function shareChatToWechat(){
  const url = String(chatShareState.url || '').trim();
  if(!url) return;
  try{
    if(navigator.clipboard?.writeText) await navigator.clipboard.writeText(url);
    else copyText(url);
    try{ toast(window.AperviaI18n?.t('share.wechat_copied') || 'Link copied. Open WeChat and paste it to share.'); }catch(_){ }
  }catch(_){
    try{
      copyText(url);
      toast(window.AperviaI18n?.t('share.wechat_copied') || 'Link copied. Open WeChat and paste it to share.');
    }catch(__){ }
  }
}

function openChatShareNetwork(kind){
  const url = String(chatShareState.url || '').trim();
  const title = String(chatShareState.title || 'Apervia 分享').trim();
  if(!url) return;
  const encodedUrl = encodeURIComponent(url);
  const encodedTitle = encodeURIComponent(title);
  const target = kind === 'qq'
    ? `https://connect.qq.com/widget/shareqq/index.html?url=${encodedUrl}&title=${encodedTitle}`
    : `https://service.weibo.com/share/share.php?url=${encodedUrl}&title=${encodedTitle}`;
  window.open(target, '_blank', 'noopener,noreferrer');
}

chatShareCloseBtnEl?.addEventListener('click', closeChatShareModal);
chatShareModalEl?.addEventListener('click', (event)=>{ if(event.target === chatShareModalEl) closeChatShareModal(); });
chatShareCopyBtnEl?.addEventListener('click', copyChatShareLink);
chatShareWechatBtnEl?.addEventListener('click', shareChatToWechat);
chatShareQqBtnEl?.addEventListener('click', ()=>openChatShareNetwork('qq'));
chatShareWeiboBtnEl?.addEventListener('click', ()=>openChatShareNetwork('weibo'));
activeChatShareBtnEl?.addEventListener('click', ()=>{
  copyActiveChatShareLinkDirect();
});
document.addEventListener('keydown', (event)=>{
  if(event.key === 'Escape' && chatShareModalEl?.classList.contains('open')) closeChatShareModal();
});

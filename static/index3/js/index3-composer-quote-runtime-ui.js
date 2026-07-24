/* Composer quote/draft runtime.*/

function getActive(){ return isHomeLandingView ? getHomeLandingVirtualSession() : store.sessions[store.activeId]; }
function getSessionById(id){ return store.sessions[id]; }

let composerDraftOwnerSessionId = "";

function normalizeComposerOwnerSessionId(sessionId){
  return String(sessionId || '').trim();
}

function setComposerInputOwnerSessionId(sessionId){
  composerDraftOwnerSessionId = normalizeComposerOwnerSessionId(sessionId);
  try{
    if(inputEl){
      if(composerDraftOwnerSessionId) inputEl.dataset.composerSessionId = composerDraftOwnerSessionId;
      else delete inputEl.dataset.composerSessionId;
    }
  }catch(_){ }
  return composerDraftOwnerSessionId;
}

function getComposerInputOwnerSessionId(){
  const explicit = normalizeComposerOwnerSessionId(composerDraftOwnerSessionId || inputEl?.dataset?.composerSessionId || '');
  if(explicit) return explicit;
  return isHomeLandingView ? '' : normalizeComposerOwnerSessionId(store?.activeId || '');
}

function composerInputBelongsToSession(sessionId){
  const sid = normalizeComposerOwnerSessionId(sessionId);
  if(!sid) return false;
  return !isHomeLandingView && normalizeComposerOwnerSessionId(store?.activeId || '') === sid && getComposerInputOwnerSessionId() === sid;
}

function persistVisibleComposerDraftBeforeSessionChange(fallbackSessionId=''){
  const ownerId = getComposerInputOwnerSessionId();
  const sid = ownerId || normalizeComposerOwnerSessionId(fallbackSessionId || store?.activeId || '');
  if(isHomeLandingView && !ownerId){
    persistComposerDraft('', inputEl?.value || '');
    return '';
  }
  if(sid && store?.sessions?.[sid]){
    persistComposerDraft(sid, inputEl?.value || '');
    return sid;
  }
  return '';
}

function persistActiveComposerDraft(text, opts={}){
  const sid = getComposerInputOwnerSessionId();
  return persistComposerDraft(sid || store?.activeId, text, opts);
}

function _composerDraftStamp(opts={}){
  const n = Number(opts?.stamp || opts?.updatedAt || 0);
  return Number.isFinite(n) && n > 0 ? n : Date.now();
}

function persistComposerDraft(sessionId, text, opts={}){
  const next = String(text ?? "");
  const sidRaw = normalizeComposerOwnerSessionId(sessionId || '');
  if(isHomeLandingView && (!sidRaw || sidRaw === normalizeComposerOwnerSessionId(store?.activeId || ''))){
    if(homeDraftText !== next) homeDraftText = next;
    return;
  }
  const sid = sidRaw || normalizeComposerOwnerSessionId(store?.activeId || '');
  if(!sid || !store?.sessions?.[sid]) return;
  const session = store.sessions[sid];
  const stamp = _composerDraftStamp(opts);
  const changedText = String(session.composerDraft || "") !== next;
  const forceMeta = !!opts?.forceMeta || !!opts?.reason;
  if(!changedText && !forceMeta) return;
  session.composerDraft = next;
  session.composerDraftUpdatedAt = Math.max(Number(session.composerDraftUpdatedAt || 0) || 0, stamp);
  if(next.trim()){
    delete session.composerDraftClearedAt;
    delete session.composerDraftSentClearAt;
    delete session.composerDraftClearReason;
  }else{
    session.composerDraftClearedAt = Math.max(Number(session.composerDraftClearedAt || 0) || 0, stamp);
    const reason = String(opts?.reason || '').trim();
    if(reason){
      session.composerDraftClearReason = reason;
      if(reason === 'send_clear') session.composerDraftSentClearAt = Math.max(Number(session.composerDraftSentClearAt || 0) || 0, stamp);
    }
  }
  // Composer typing is a draft-only change. Do not bump session updatedAt here;
  // otherwise background cloud/session merges may treat an old equal-length
  // transcript as newer and briefly switch the chat between old and new messages.
  if(opts?.immediateLocal){
    try{ saveStoreLocalOnly(); }catch(_){ saveStoreLocalOnlyThrottled(); }
  }else{
    saveStoreLocalOnlyThrottled();
  }
}

function persistComposerQuoteDraft(sessionId, payload){
  const next = payload && typeof payload === 'object' ? {
    text: String(payload.text || ''),
    msgIndex: Number.isFinite(payload.msgIndex) ? Number(payload.msgIndex) : null,
    messageId: String(payload.messageId || '').trim().slice(0, 220),
    sourceOffset: Number.isInteger(Number(payload.sourceOffset)) && Number(payload.sourceOffset) >= 0 ? Number(payload.sourceOffset) : null,
  } : null;
  if(isHomeLandingView && (!sessionId || sessionId === store?.activeId)){
    if(JSON.stringify(homeQuoteDraft || null) === JSON.stringify(next)) return;
    homeQuoteDraft = next;
    return;
  }
  const sid = sessionId || getComposerInputOwnerSessionId() || store?.activeId;
  if(!sid || !store?.sessions?.[sid]) return;
  const prevRaw = store.sessions[sid].composerQuoteDraft || null;
  const prev = prevRaw && typeof prevRaw === 'object' ? {
    text: String(prevRaw.text || ''),
    msgIndex: Number.isFinite(prevRaw.msgIndex) ? Number(prevRaw.msgIndex) : null,
    messageId: String(prevRaw.messageId || '').trim().slice(0, 220),
    sourceOffset: Number.isInteger(Number(prevRaw.sourceOffset)) && Number(prevRaw.sourceOffset) >= 0 ? Number(prevRaw.sourceOffset) : null,
  } : null;
  if(JSON.stringify(prev) === JSON.stringify(next)) return;
  store.sessions[sid].composerQuoteDraft = next;
  store.sessions[sid].updatedAt = now();
  saveStoreLocalOnlyThrottled();
}

function getComposerQuoteDraft(sessionId){
  if(isHomeLandingView && (!sessionId || sessionId === store?.activeId)){
    const raw = homeQuoteDraft;
    if(!raw || typeof raw !== 'object') return null;
    const text = normalizeAssistantQuoteText(raw.text || '');
    if(!text) return null;
    return {
      text,
      msgIndex: Number.isFinite(raw.msgIndex) ? Number(raw.msgIndex) : null,
      messageId: String(raw.messageId || '').trim().slice(0, 220),
      sourceOffset: Number.isInteger(Number(raw.sourceOffset)) && Number(raw.sourceOffset) >= 0 ? Number(raw.sourceOffset) : null,
    };
  }
  const sid = sessionId || store?.activeId;
  const s = sid ? store?.sessions?.[sid] : null;
  const raw = s?.composerQuoteDraft;
  if(!raw || typeof raw !== 'object') return null;
  const text = normalizeAssistantQuoteText(raw.text || '');
  if(!text) return null;
  return {
    text,
    msgIndex: Number.isFinite(raw.msgIndex) ? Number(raw.msgIndex) : null,
    messageId: String(raw.messageId || '').trim().slice(0, 220),
    sourceOffset: Number.isInteger(Number(raw.sourceOffset)) && Number(raw.sourceOffset) >= 0 ? Number(raw.sourceOffset) : null,
  };
}

function getComposerQuotePreviewText(text){
  return String(normalizeAssistantQuoteText(text) || '').replace(/\s+/g, ' ').trim();
}

function getMessageQuoteText(msg){
  if(!msg || typeof msg !== 'object') return '';
  return normalizeAssistantQuoteText(msg._quote || msg.quoteText || msg.quote || '');
}

function getMessageQuoteSourceIndex(msg){
  if(!msg || typeof msg !== 'object') return null;
  const candidates = [
    msg._quote_msg_index,
    msg.quote_msg_index,
    msg.quoteMessageIndex,
    msg.quote_source_index,
    msg.quoteSourceIndex,
  ];
  for(const value of candidates){
    const n = Number(value);
    if(Number.isInteger(n) && n >= 0) return n;
  }
  return null;
}

function assistantQuoteMessageIdentity(msg){
  const item = msg && typeof msg === 'object' ? msg : null;
  if(!item) return '';
  try{
    const stable = typeof messageStableClientIdentity === 'function' ? String(messageStableClientIdentity(item) || '').trim() : '';
    if(stable) return stable.slice(0, 220);
  }catch(_){ }
  for(const key of ['localId','local_id','messageLocalId','message_local_id','_webai_history_id','id','message_id','messageId','_id']){
    const value = String(item[key] || '').trim();
    if(value) return value.slice(0, 220);
  }
  return '';
}

function getMessageQuoteSourceId(msg){
  if(!msg || typeof msg !== 'object') return '';
  for(const key of ['_quote_msg_id','quote_msg_id','quoteMessageId','quote_source_id','quoteSourceId']){
    const value = String(msg[key] || '').trim();
    if(value) return value.slice(0, 220);
  }
  return '';
}

function getMessageQuoteSourceOffset(msg){
  if(!msg || typeof msg !== 'object') return null;
  for(const key of ['_quote_source_offset','quote_source_offset','quoteSourceOffset']){
    const value = Number(msg[key]);
    if(Number.isInteger(value) && value >= 0) return value;
  }
  return null;
}

function quoteComparableText(text){
  return String(text || '')
    .replace(/ /g, ' ')
    .replace(/[\*_`>#\[\](){}~|]+/g, ' ')
    .replace(/https?:\/\/\S+/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function assistantQuoteSourceText(message){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg) return '';
  const direct = bubbleMessageTextForComposer(msg);
  if(direct) return direct;
  const c = msg.content;
  if(c && typeof c === 'object' && !Array.isArray(c)){
    return String(c.text || c.answer || c.title || c.prompt || '').trim();
  }
  return '';
}

function resolveQuotedAssistantMessageIndex(quoteText, msg, fallbackUserIndex=null){
  const s = getActive();
  const messages = Array.isArray(s?.messages) ? s.messages : [];
  if(!messages.length) return null;
  const q = quoteComparableText(quoteText);
  if(!q) return null;
  const matchesQuote = item=>{
    if(String(item?.role || '').toLowerCase() !== 'assistant') return false;
    const source = quoteComparableText(assistantQuoteSourceText(item));
    return !!(source && (source.includes(q) || q.includes(source)));
  };
  const explicitId = getMessageQuoteSourceId(msg);
  if(explicitId){
    const byId = messages.findIndex(item => assistantQuoteMessageIdentity(item) === explicitId && matchesQuote(item));
    if(byId >= 0) return byId;
  }
  const explicit = getMessageQuoteSourceIndex(msg);
  if(Number.isInteger(explicit) && messages[explicit] && matchesQuote(messages[explicit])) return explicit;
  const userIndex = Number.isInteger(Number(fallbackUserIndex)) && Number(fallbackUserIndex) >= 0
    ? Number(fallbackUserIndex)
    : messages.findIndex(item => item === msg);
  const beforeIndex = userIndex >= 0 ? userIndex - 1 : messages.length - 1;
  for(let i = Math.min(beforeIndex, messages.length - 1); i >= 0; i--){
    const item = messages[i];
    if(matchesQuote(item)) return i;
  }
  return null;
}

function ensureBubbleQuoteClickStyle(){
  if(document.getElementById('webai-bubble-quote-click-style')) return;
  const style = document.createElement('style');
  style.id = 'webai-bubble-quote-click-style';
  style.textContent = `
.bubble-quote-ref.is-clickable{cursor:pointer;transition:background .16s ease,border-color .16s ease,box-shadow .16s ease,transform .16s ease;}
.bubble-quote-ref.is-clickable:hover{background:color-mix(in srgb,var(--panel) 72%,var(--card));border-color:color-mix(in srgb,var(--outline) 34%,var(--border));box-shadow:0 8px 24px rgba(0,0,0,.08);transform:translateY(-1px);}
.bubble-quote-ref.is-clickable:active{transform:translateY(0) scale(.995);}
.bubble-quote-ref.is-clickable:focus-visible{outline:2px solid color-mix(in srgb,var(--outline) 72%,transparent);outline-offset:2px;}
.webai-quote-source-segment{padding:0;margin:0;border:0;outline:0;box-shadow:none;border-radius:0;background:rgba(250,204,21,.34);animation:webaiQuoteSourceSegmentPulse 1.55s ease both;scroll-margin-block:160px;}
.webai-quote-source-segment.is-pinned{background:rgba(250,204,21,.36);animation:none;}
[data-theme="dark"] .webai-quote-source-segment{background:rgba(250,204,21,.25);box-shadow:none;}
[data-theme="dark"] .webai-quote-source-segment.is-pinned{background:rgba(250,204,21,.31);}
@keyframes webaiQuoteSourceSegmentPulse{0%{background:rgba(250,204,21,0);}14%{background:rgba(250,204,21,.48);}68%{background:rgba(250,204,21,.32);}100%{background:rgba(250,204,21,0);}}
`;
  document.head.appendChild(style);
}

function findRenderedBubbleByMessageIndex(messageIndex, quoteText=''){
  const idx = Number(messageIndex);
  if(!Number.isInteger(idx) || idx < 0 || !chatEl?.querySelector) return null;
  const candidates = Array.from(chatEl.querySelectorAll(`.bubble.a[data-msg-index="${idx}"]`));
  if(!candidates.length){
    const fallback = chatEl.querySelector(`.bubble[data-msg-index="${idx}"]`);
    return fallback || null;
  }
  const needle = quoteMatchNormalizeWithMap(getComposerQuotePreviewText(quoteText)).text;
  if(needle){
    const matched = candidates.find(candidate=>{
      const root = candidate.querySelector?.('.reasoning-answer-wrap') || candidate.querySelector?.('.bubble-body') || candidate;
      const text = collectTextNodes(root).map(row => String(row.node?.nodeValue || '')).join('');
      return quoteMatchNormalizeWithMap(text).text.includes(needle);
    });
    if(matched) return matched;
  }
  return candidates.find(candidate=>candidate.querySelector?.('.reasoning-answer-wrap')) || candidates[0];
}

function quoteMatchNormalizeWithMap(text){
  const raw = String(text || '').replace(/\u00a0/g, ' ');
  const chars = [];
  const map = [];
  let lastWasSpace = true;
  for(let i = 0; i < raw.length; i++){
    const ch = raw[i];
    if(/\s/u.test(ch)){
      if(!lastWasSpace){
        chars.push(' ');
        map.push(i);
        lastWasSpace = true;
      }
      continue;
    }
    chars.push(ch.toLowerCase());
    map.push(i);
    lastWasSpace = false;
  }
  while(chars.length && chars[chars.length - 1] === ' '){
    chars.pop();
    map.pop();
  }
  return { text: chars.join(''), map };
}

const quoteSourceHighlightTimers = new WeakMap();
let quotePinnedHighlightState = null;

function cancelQuoteSourceHighlightTimer(root){
  const target = root?.querySelector?.('.bubble-body') || root;
  if(!target) return;
  try{
    const timer = quoteSourceHighlightTimers.get(target);
    if(timer) window.clearTimeout(timer);
    quoteSourceHighlightTimers.delete(target);
  }catch(_){ }
}

function unwrapQuoteSourceSegmentHighlights(root){
  if(!root?.querySelectorAll) return;
  cancelQuoteSourceHighlightTimer(root);
  const spans = Array.from(root.querySelectorAll('.webai-quote-source-segment'));
  for(const span of spans){
    try{
      const text = document.createTextNode(span.textContent || '');
      span.replaceWith(text);
    }catch(_){ }
  }
  try{ root.normalize?.(); }catch(_){ }
}

function clearQuoteSourceHighlights(root=chatEl){
  if(!root?.querySelectorAll) return;
  try{
    root.querySelectorAll('.bubble-body').forEach(body => unwrapQuoteSourceSegmentHighlights(body));
    unwrapQuoteSourceSegmentHighlights(root);
  }catch(_){ }
}

function clearPinnedQuoteHighlight(){
  quotePinnedHighlightState = null;
  clearQuoteSourceHighlights(chatEl);
}

function collectTextNodes(root){
  const rows = [];
  if(!root) return rows;
  try{
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node){
        const value = String(node?.nodeValue || '');
        if(!value) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if(parent?.closest?.('.bubble-actions,.bubble-head,.reasoning-panels,.bubble-sources,.bubble-quote-ref')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    let offset = 0;
    let node;
    while((node = walker.nextNode())){
      const value = String(node.nodeValue || '');
      rows.push({ node, start: offset, end: offset + value.length });
      offset += value.length;
    }
  }catch(_){ }
  return rows;
}

function resolveQuotedTextNormalizedMatch(hayText, needleText, sourceOffset=null){
  const hay = String(hayText || '');
  const needle = String(needleText || '');
  if(!hay || !needle) return null;
  const requestedOffset = Number(sourceOffset);
  let matchedNeedle = needle;
  let start = Number.isInteger(requestedOffset) && requestedOffset >= 0 && hay.slice(requestedOffset, requestedOffset + needle.length) === needle
    ? requestedOffset
    : hay.indexOf(needle);
  if(start < 0 && needle.length > 40){
    matchedNeedle = needle.slice(0, Math.max(40, Math.floor(needle.length * 0.72)));
    start = hay.indexOf(matchedNeedle);
  }
  return start >= 0 ? { start, length:matchedNeedle.length } : null;
}

function highlightQuotedSegmentInBubble(target, quoteText, opts={}){
  const body = target?.querySelector?.('.bubble-body') || target;
  if(!body) return null;
  const persistent = !!opts?.persistent;
  unwrapQuoteSourceSegmentHighlights(body);
  const answerRoot = body.querySelector?.('.reasoning-answer-wrap') || body;
  const nodes = collectTextNodes(answerRoot);
  const rawText = nodes.map(row => String(row.node?.nodeValue || '')).join('');
  const needleRaw = getComposerQuotePreviewText(quoteText);
  const needle = quoteMatchNormalizeWithMap(needleRaw).text;
  if(!rawText.trim() || !needle) return null;
  const hay = quoteMatchNormalizeWithMap(rawText);
  const match = resolveQuotedTextNormalizedMatch(hay.text, needle, opts?.sourceOffset);
  if(!match) return null;
  const startNorm = match.start;
  const endNorm = Math.min(hay.map.length - 1, startNorm + Math.min(match.length, hay.text.length - startNorm) - 1);
  const matchStart = hay.map[startNorm];
  const matchEnd = (hay.map[endNorm] ?? matchStart) + 1;
  if(!Number.isInteger(matchStart) || !Number.isInteger(matchEnd) || matchEnd <= matchStart) return null;

  const spans = [];
  for(const row of nodes.slice().reverse()){
    const overlapStart = Math.max(matchStart, row.start);
    const overlapEnd = Math.min(matchEnd, row.end);
    if(overlapEnd <= overlapStart) continue;
    try{
      const value = String(row.node.nodeValue || '');
      const localStart = overlapStart - row.start;
      const localEnd = overlapEnd - row.start;
      const frag = document.createDocumentFragment();
      const before = value.slice(0, localStart);
      const mid = value.slice(localStart, localEnd);
      const after = value.slice(localEnd);
      if(before) frag.appendChild(document.createTextNode(before));
      if(mid){
        const span = document.createElement('span');
        span.className = persistent ? 'webai-quote-source-segment is-pinned' : 'webai-quote-source-segment';
        span.textContent = mid;
        frag.appendChild(span);
        spans.unshift(span);
      }
      if(after) frag.appendChild(document.createTextNode(after));
      row.node.replaceWith(frag);
    }catch(_){ }
  }
  if(!spans.length) return null;
  const first = spans[0];
  if(!persistent){
    const timer = window.setTimeout(()=>{
      try{
        if(quoteSourceHighlightTimers.get(body) === timer) unwrapQuoteSourceSegmentHighlights(body);
      }catch(_){ }
    }, 2100);
    quoteSourceHighlightTimers.set(body, timer);
  }
  return first;
}

function scrollQuoteSourceIntoView(target){
  if(!target) return false;
  const run = ()=>{
    try{
      if(chatEl && chatEl.contains(target) && typeof chatEl.getBoundingClientRect === 'function'){
        const scrollerRect = chatEl.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const targetTop = Number(chatEl.scrollTop || 0) + (targetRect.top - scrollerRect.top);
        const centeredTop = targetTop - Math.max(0, (Number(chatEl.clientHeight || 0) - Number(targetRect.height || 0)) / 2);
        const maxTop = Math.max(0, Number(chatEl.scrollHeight || 0) - Number(chatEl.clientHeight || 0));
        const top = Math.max(0, Math.min(centeredTop, maxTop));
        if(typeof chatEl.scrollTo === 'function') chatEl.scrollTo({ top, behavior:'smooth' });
        else chatEl.scrollTop = top;
        return;
      }
      target.scrollIntoView({ behavior:'smooth', block:'center' });
    }catch(_){
      try{ target.scrollIntoView(); }catch(__){ }
    }
  };
  try{ window.requestAnimationFrame(()=>window.requestAnimationFrame(run)); }
  catch(_){ run(); }
  return true;
}

function focusQuotedAssistantMessage(quoteText, msg, userMessageIndex, opts={}){
  const sourceIndex = resolveQuotedAssistantMessageIndex(quoteText, msg, userMessageIndex);
  const target = findRenderedBubbleByMessageIndex(sourceIndex, quoteText);
  if(!target){
    try{ setStatus('未找到引用来源'); }catch(_){ }
    try{ toast(window.AperviaI18n?.t('composer.quote_not_found') || 'The quoted source could not be found.'); }catch(_){ }
    return false;
  }
  const persistent = !!opts?.persistent;
  if(persistent){
    clearQuoteSourceHighlights(chatEl);
  }
  const sourceOffset = Number.isInteger(Number(opts?.sourceOffset)) && Number(opts.sourceOffset) >= 0
    ? Number(opts.sourceOffset)
    : getMessageQuoteSourceOffset(msg);
  const highlighted = highlightQuotedSegmentInBubble(target, quoteText, { persistent, sourceOffset });
  const scrollTarget = highlighted || target;
  scrollQuoteSourceIntoView(scrollTarget);
  if(persistent && highlighted){
    quotePinnedHighlightState = {
      sessionId: String(store?.activeId || ''),
      sourceIndex,
      quoteText: normalizeAssistantQuoteText(quoteText),
      sourceOffset,
    };
  }
  try{ setStatus(persistent && highlighted ? '已常驻高亮引用内容' : (highlighted ? '已定位引用内容' : '已定位引用来源')); }catch(_){ }
  return true;
}

function restorePinnedQuoteHighlightForActiveSession(){
  const state = quotePinnedHighlightState && typeof quotePinnedHighlightState === 'object' ? quotePinnedHighlightState : null;
  if(!state) return;
  const activeId = String(store?.activeId || '');
  if(String(state.sessionId || '') !== activeId) return;
  const target = findRenderedBubbleByMessageIndex(Number(state.sourceIndex), state.quoteText);
  if(!target) return;
  window.requestAnimationFrame(()=>{
    try{ highlightQuotedSegmentInBubble(target, state.quoteText, { persistent:true, sourceOffset:state.sourceOffset }); }catch(_){ }
  });
}

function createBubbleQuoteNode(text, opts={}){
  const normalized = normalizeAssistantQuoteText(text);
  if(!normalized) return null;
  ensureBubbleQuoteClickStyle();
  const node = document.createElement('div');
  node.className = 'bubble-quote-ref is-clickable';
  node.tabIndex = 0;
  node.setAttribute('role', 'button');
  node.title = '单击定位引用，双击常驻高亮';
  const icon = document.createElement('span');
  icon.className = 'bubble-quote-ref-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = '↳';
  const body = document.createElement('div');
  body.className = 'bubble-quote-ref-text';
  body.textContent = `引用：${getComposerQuotePreviewText(normalized)}`;
  node.appendChild(icon);
  node.appendChild(body);
  const sourceMsg = opts?.message || null;
  const userIndexRaw = Number(opts?.messageIndex);
  const userIndex = Number.isInteger(userIndexRaw) && userIndexRaw >= 0 ? userIndexRaw : null;
  let quoteClickTimer = 0;
  let quotePersistentHandledUntil = 0;
  const activate = (e, activateOpts={})=>{
    e.preventDefault();
    e.stopPropagation();
    focusQuotedAssistantMessage(normalized, sourceMsg, userIndex, activateOpts);
  };
  const clearQuoteClickTimer = ()=>{
    if(quoteClickTimer){
      window.clearTimeout(quoteClickTimer);
      quoteClickTimer = 0;
    }
  };
  node.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    const detail = Number(e.detail || 0) || 0;
    if(detail >= 2){
      clearQuoteClickTimer();
      quotePersistentHandledUntil = Date.now() + 520;
      focusQuotedAssistantMessage(normalized, sourceMsg, userIndex, { persistent:true });
      return;
    }
    clearQuoteClickTimer();
    quoteClickTimer = window.setTimeout(()=>{
      quoteClickTimer = 0;
      focusQuotedAssistantMessage(normalized, sourceMsg, userIndex, {});
    }, 240);
  });
  node.addEventListener('dblclick', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    clearQuoteClickTimer();
    if(Date.now() <= quotePersistentHandledUntil) return;
    quotePersistentHandledUntil = Date.now() + 520;
    focusQuotedAssistantMessage(normalized, sourceMsg, userIndex, { persistent:true });
  });
  node.addEventListener('keydown', (e)=>{
    if(e.key === 'Enter' || e.key === ' '){
      clearQuoteClickTimer();
      activate(e);
    }
  });
  return node;
}

function injectMessageQuoteIntoBubble(bubble, msg){
  const quoteText = getMessageQuoteText(msg);
  if(!bubble || !quoteText) return;
  const body = bubble.querySelector('.bubble-body');
  if(!body || body.querySelector(':scope > .bubble-quote-ref')) return;
  const messageIndexRaw = Number(bubble?.dataset?.msgIndex);
  const node = createBubbleQuoteNode(quoteText, {
    message: msg,
    messageIndex: Number.isInteger(messageIndexRaw) && messageIndexRaw >= 0 ? messageIndexRaw : null,
  });
  if(!node) return;
  body.prepend(node);
}

let composerQuoteLayoutObserver = null;
let composerQuoteLayoutFrame = 0;

function syncComposerQuoteLayoutHeight(){
  const shell = composerInputShellEl;
  const bar = composerQuoteBarEl;
  if(!shell || !bar) return;
  if(!bar.classList.contains('show')){
    shell.style.removeProperty('--composer-quote-height');
    return;
  }
  const measured = Math.ceil(Number(bar.getBoundingClientRect?.().height || 0));
  const height = Math.max(44, Math.min(86, measured || 44));
  const next = `${height}px`;
  if(shell.style.getPropertyValue('--composer-quote-height') !== next){
    shell.style.setProperty('--composer-quote-height', next);
  }
}

function scheduleComposerQuoteLayoutSync(){
  if(composerQuoteLayoutFrame) return;
  composerQuoteLayoutFrame = window.requestAnimationFrame(()=>{
    composerQuoteLayoutFrame = 0;
    syncComposerQuoteLayoutHeight();
  });
}

function ensureComposerQuoteLayoutObserver(){
  if(composerQuoteLayoutObserver || !composerQuoteBarEl || typeof ResizeObserver !== 'function') return;
  composerQuoteLayoutObserver = new ResizeObserver(scheduleComposerQuoteLayoutSync);
  composerQuoteLayoutObserver.observe(composerQuoteBarEl);
}

function renderComposerQuoteBar(){
  if(!composerQuoteBarEl || !composerQuoteTextEl) return;
  const text = normalizeAssistantQuoteText(composerQuoteState?.text || '');
  if(!text){
    composerQuoteBarEl.classList.remove('show');
    composerInputShellEl?.classList.remove('has-quote-bar');
    composerInputShellEl?.style.removeProperty('--composer-quote-height');
    composerQuoteTextEl.textContent = '';
    return;
  }
  composerQuoteTextEl.textContent = `引用：${getComposerQuotePreviewText(text)}`;
  composerQuoteBarEl.classList.add('show');
  composerInputShellEl?.classList.add('has-quote-bar');
  ensureComposerQuoteLayoutObserver();
  scheduleComposerQuoteLayoutSync();
}

function setComposerQuoteState(payload, opts={}){
  const nextText = normalizeAssistantQuoteText(payload?.text || '');
  composerQuoteState = nextText ? {
    text: nextText,
    msgIndex: Number.isFinite(payload?.msgIndex) ? Number(payload.msgIndex) : null,
    messageId: String(payload?.messageId || '').trim().slice(0, 220),
    sourceOffset: Number.isInteger(Number(payload?.sourceOffset)) && Number(payload.sourceOffset) >= 0 ? Number(payload.sourceOffset) : null,
  } : null;
  renderComposerQuoteBar();
  resizeComposer();
  updateComposerActionState();
  updateComposerPlaceholder();
  if(opts?.persist !== false) persistComposerQuoteDraft(getComposerInputOwnerSessionId() || store?.activeId, composerQuoteState);
}

function clearComposerQuoteState(opts={}){
  const hadQuote = !!composerQuoteState;
  composerQuoteState = null;
  renderComposerQuoteBar();
  resizeComposer();
  updateComposerActionState();
  updateComposerPlaceholder();
  if(opts?.persist !== false) persistComposerQuoteDraft(getComposerInputOwnerSessionId() || store?.activeId, null);
  if(hadQuote && !opts?.silent){
    try{ setStatus('已移除引用'); }catch(_){ }
  }
}

function restoreComposerDraft(sessionId){
  if(isHomeLandingView && (!sessionId || sessionId === store?.activeId)){
    setComposerInputOwnerSessionId('');
    restoreHomeLandingComposer();
    return;
  }
  const sid = sessionId || getComposerInputOwnerSessionId() || store?.activeId;
  const s = sid ? store?.sessions?.[sid] : null;
  setComposerInputOwnerSessionId(sid || '');
  inputEl.value = s?.composerDraft || "";
  composerQuoteState = getComposerQuoteDraft(sid);
  restoreComposerAttachmentDraft(sid);
  renderComposerQuoteBar();
  resizeComposer();
  updateComposerActionState();
  updateComposerPlaceholder();
}

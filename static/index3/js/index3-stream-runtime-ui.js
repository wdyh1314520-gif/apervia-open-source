/* Stream/session runtime split from index3.js. */

const streamControllers = Object.create(null);
const streamPromises = Object.create(null);
const streamAbortReasons = Object.create(null);
const sessionRuntime = Object.create(null);
const PARALLEL_CHAT_STREAMS_ENABLED = true;
const MAX_PARALLEL_CHAT_STREAMS = 4;

function setSessionRuntimeGenerationUsage(id, payload, opts={}){
  const rt = ensureSessionRuntime(id);
  const usage = normalizeAssistantUsagePayload(payload);
  if(!usage) return rt;
  rt.generationUsage = usage;
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  return rt;
}

function _rtMessageElapsedMs(msg){
  if(!msg || typeof msg !== 'object') return 0;
  const candidates = [
    msg.rtFinalMs,
    msg.elapsedMs,
    msg.elapsed_ms,
    msg.responseElapsedMs,
    msg.response_elapsed_ms,
  ];
  for(const value of candidates){
    const n = Math.max(0, Number(value || 0) || 0);
    if(n > 0) return n;
  }
  return 0;
}

function _rtMessageCreatedMs(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  const candidates = [m.created_at_ms, m.createdAtMs, m.created_at, m.createdAt, m.timestamp, m.ts];
  for(const value of candidates){
    const n = Number(value || 0);
    if(Number.isFinite(n) && n > 0) return n < 100000000000 ? n * 1000 : n;
  }
  return 0;
}

function _rtSessionForTiming(sessionOrId){
  return typeof sessionOrId === 'string' ? getSessionById(sessionOrId) : sessionOrId;
}

function _rtLatestUserCreatedMs(sessionOrId){
  const s = _rtSessionForTiming(sessionOrId);
  const msgs = Array.isArray(s?.messages) ? s.messages : [];
  for(let i = msgs.length - 1; i >= 0; i--){
    const m = msgs[i];
    if(String(m?.role || '').toLowerCase() !== 'user') continue;
    const ts = _rtMessageCreatedMs(m);
    if(ts > 0) return ts;
  }
  return 0;
}

function _rtLastAssistantTiming(sessionOrId){
  const s = _rtSessionForTiming(sessionOrId);
  const msgs = Array.isArray(s?.messages) ? s.messages : [];
  for(let i = msgs.length - 1; i >= 0; i--){
    const m = msgs[i];
    if(String(m?.role || '').toLowerCase() !== 'assistant') continue;
    const assistantMs = _rtMessageCreatedMs(m);
    let prevUserMs = 0;
    for(let j = i - 1; j >= 0; j--){
      const u = msgs[j];
      if(String(u?.role || '').toLowerCase() !== 'user') continue;
      prevUserMs = _rtMessageCreatedMs(u);
      break;
    }
    return { assistantMs, prevUserMs, message:m };
  }
  return { assistantMs:0, prevUserMs:0, message:null };
}

function _rtCurrentTurnStartAt(sessionOrId){
  return _rtLatestUserCreatedMs(sessionOrId) || Date.now();
}

function _rtNormalizeStartAtForSession(sessionOrId, startAt){
  const raw = Math.max(0, Number(startAt || 0) || 0);
  if(raw <= 0) return 0;
  const latestUserMs = _rtLatestUserCreatedMs(sessionOrId);
  if(latestUserMs > 0 && raw < latestUserMs - 2000) return latestUserMs;
  return raw;
}

function _rtClampElapsedMsForSession(sessionOrId, elapsedMs){
  let ms = Math.max(0, Number(elapsedMs || 0) || 0);
  if(ms <= 0) return 0;
  const s = _rtSessionForTiming(sessionOrId);
  const nowMs = Date.now();
  let maxByTurn = 0;
  const timing = _rtLastAssistantTiming(s);
  if(timing.assistantMs > 0 && timing.prevUserMs > 0 && timing.assistantMs >= timing.prevUserMs){
    maxByTurn = Math.max(maxByTurn, timing.assistantMs - timing.prevUserMs + 5000);
  }
  const latestUserMs = _rtLatestUserCreatedMs(s);
  if(latestUserMs > 0 && nowMs >= latestUserMs){
    maxByTurn = Math.max(maxByTurn, nowMs - latestUserMs + 5000);
  }
  if(maxByTurn > 0 && ms > maxByTurn) ms = maxByTurn;
  return Math.max(0, ms);
}

function _rtLastAssistantElapsedMs(sessionOrId){
  const s = _rtSessionForTiming(sessionOrId);
  const msgs = Array.isArray(s?.messages) ? s.messages : [];
  for(let i = msgs.length - 1; i >= 0; i--){
    const m = msgs[i];
    if(String(m?.role || '').toLowerCase() !== 'assistant') continue;
    const ms = _rtMessageElapsedMs(m);
    if(ms > 0) return _rtClampElapsedMsForSession(s, ms);
    break;
  }
  return 0;
}

function _rtPersistFinalMsToLastAssistant(id, finalMs){
  const sid = String(id || '').trim();
  const s = sid ? getSessionById(sid) : null;
  const ms = _rtClampElapsedMsForSession(s || sid, finalMs);
  if(!s || ms <= 0 || !Array.isArray(s.messages)) return false;
  for(let i = s.messages.length - 1; i >= 0; i--){
    const m = s.messages[i];
    if(String(m?.role || '').toLowerCase() !== 'assistant') continue;
    const prev = _rtClampElapsedMsForSession(s, _rtMessageElapsedMs(m));
    if(prev === ms && Number(s.rtFinalMs || 0) === ms) return false;
    m.rtFinalMs = ms;
    m.elapsedMs = ms;
    m.elapsed_ms = ms;
    s.rtFinalMs = ms;
    s.rtStartAt = 0;
    store.sessions[sid] = s;
    saveStore();
    return true;
  }
  return false;
}

function _rtReadPersistedSessionState(id){
  const sid = String(id || '').trim();
  const s = sid ? getSessionById(sid) : null;
  if(!s) return { rtStartAt:0, rtFinalMs:0 };
  const hasCompletedAssistant = sessionObjectLastVisibleMessageIsAssistant(s);
  const hasRecoverableLiveTurn = !hasCompletedAssistant && !!(
    String(s.pendingJobId || '').trim()
    || !!s.pendingAssistantStreaming
  );
  const persistedStartAt = hasRecoverableLiveTurn
    ? _rtNormalizeStartAtForSession(s, Math.max(0, Number(s.rtStartAt || s.pendingAssistantRtStartAt || 0) || 0))
    : 0;
  const persistedFinalMs = _rtClampElapsedMsForSession(s, Math.max(0, Number(s.rtFinalMs || s.pendingAssistantRtFinalMs || _rtLastAssistantElapsedMs(s) || 0) || 0));
  return { rtStartAt:persistedStartAt, rtFinalMs:persistedFinalMs };
}

function _rtPersistSessionState(id, rt, opts={}){
  const sid = String(id || '').trim();
  const s = sid ? getSessionById(sid) : null;
  if(!s) return;
  const startAt = _rtNormalizeStartAtForSession(s, Math.max(0, Number(rt?.rtStartAt || 0) || 0));
  const finalMs = _rtClampElapsedMsForSession(s, Math.max(0, Number(rt?.rtFinalMs || 0) || 0));
  if((Number(s.rtStartAt || 0) || 0) === startAt && (Number(s.rtFinalMs || 0) || 0) === finalMs) return;
  // 运行耗时只是恢复/展示元数据，不能刷新会话的聊天时间。
  s.rtStartAt = startAt;
  s.rtFinalMs = finalMs;
  if(rt && typeof rt === 'object'){
    rt.rtStartAt = startAt;
    rt.rtFinalMs = finalMs;
  }
  if(opts?.immediate) saveStore();
  else saveStoreThrottled();
}

function ensureSessionRuntime(id){
  if(!id) return { streaming:false, statusText:"", draftText:"", draftProcessText:"", draftFiles:[], draftImageReplies:[], draftWeatherPayload:null, reasoning:[], reasoningMeta:{}, sources:[], generationUsage:null, rtStartAt:0, rtFinalMs:0 };
  if(!sessionRuntime[id]){
    const persistedRt = _rtReadPersistedSessionState(id);
    sessionRuntime[id] = { streaming:false, statusText:"", draftText:"", draftProcessText:"", draftFiles:[], draftImageReplies:[], draftWeatherPayload:null, reasoning:[], reasoningMeta:{}, sources:[], generationUsage:null, rtStartAt:persistedRt.rtStartAt, rtFinalMs:persistedRt.rtFinalMs };
  }else if(!Array.isArray(sessionRuntime[id].draftImageReplies)) sessionRuntime[id].draftImageReplies = [];
  if(!normalizeAssistantWeatherPayload(sessionRuntime[id].draftWeatherPayload)) sessionRuntime[id].draftWeatherPayload = null;
  if(!Array.isArray(sessionRuntime[id].reasoning)) sessionRuntime[id].reasoning = [];
  if(!Array.isArray(sessionRuntime[id].sources)) sessionRuntime[id].sources = [];
  sessionRuntime[id].generationUsage = normalizeAssistantUsagePayload(sessionRuntime[id].generationUsage || sessionRuntime[id].generation_usage || null);
  sessionRuntime[id].reasoningMeta = _normalizePendingAssistantReasoningMeta(sessionRuntime[id].reasoningMeta);
  if(typeof sessionRuntime[id].draftProcessText !== "string") sessionRuntime[id].draftProcessText = "";
  if(!Number.isFinite(Number(sessionRuntime[id].rtStartAt))) sessionRuntime[id].rtStartAt = 0;
  if(!Number.isFinite(Number(sessionRuntime[id].rtFinalMs))) sessionRuntime[id].rtFinalMs = 0;
  return sessionRuntime[id];
}
const STREAM_PENDING_SNAPSHOT_DEBOUNCE_MS = 320;
const _streamPendingSnapshotTimers = Object.create(null);
function _flushSessionRuntimePendingSnapshot(id, immediate=false){
  const sid = String(id || '').trim();
  if(!sid) return null;
  const timer = _streamPendingSnapshotTimers[sid];
  if(timer){
    try{ clearTimeout(timer); }catch(_){ }
    delete _streamPendingSnapshotTimers[sid];
  }
  const rt = ensureSessionRuntime(sid);
  persistPendingAssistantSnapshot(sid, {
    draft: rt.draftText,
    process: rt.draftProcessText,
    files: rt.draftFiles,
    imageReplies: rt.draftImageReplies,
    status: rt.statusText,
    streaming: rt.streaming,
    reasoning: rt.reasoning,
    reasoningMeta: rt.reasoningMeta,
    sources: rt.sources,
    generationUsage: rt.generationUsage,
    rtStartAt: rt.rtStartAt,
    rtFinalMs: rt.rtFinalMs,
  }, immediate ? { immediate:true } : undefined);
  return rt;
}
function _scheduleSessionRuntimePendingSnapshot(id, opts={}){
  const sid = String(id || '').trim();
  if(!sid) return null;
  const rt = ensureSessionRuntime(sid);
  const immediate = !!opts.immediate;
  const debounceMs = Math.max(80, Number(opts.debounceMs || STREAM_PENDING_SNAPSHOT_DEBOUNCE_MS) || STREAM_PENDING_SNAPSHOT_DEBOUNCE_MS);
  if(immediate || !rt.streaming){
    return _flushSessionRuntimePendingSnapshot(sid, immediate);
  }
  if(_streamPendingSnapshotTimers[sid]) return rt;
  _streamPendingSnapshotTimers[sid] = setTimeout(()=>{
    delete _streamPendingSnapshotTimers[sid];
    _flushSessionRuntimePendingSnapshot(sid, false);
  }, debounceMs);
  return rt;
}
function markSessionStreaming(id, on, statusText, opts={}){
  const rt = ensureSessionRuntime(id);
  const nextOn = !!on;
  const wasOn = !!rt.streaming;
  const forceNewTimer = !!(opts && opts.forceNewTimer);
  rt.streaming = nextOn;
  if(typeof statusText === "string") rt.statusText = statusText;
  else if(!nextOn) rt.statusText = "";
  if(nextOn){
    const currentStartAt = _rtNormalizeStartAtForSession(id, Number(rt.rtStartAt || 0));
    if(forceNewTimer || !currentStartAt || currentStartAt !== Number(rt.rtStartAt || 0)){
      rt.rtStartAt = _rtCurrentTurnStartAt(id);
    }else{
      rt.rtStartAt = currentStartAt;
    }
    rt.rtFinalMs = 0;
    rt.generationUsage = null;
  }else{
    const startAt = _rtNormalizeStartAtForSession(id, Number(rt.rtStartAt || 0));
    if(startAt > 0){
      rt.rtFinalMs = _rtClampElapsedMsForSession(id, Date.now() - startAt);
    }
    rt.rtStartAt = 0;
  }
  const preserveRecoverablePendingDraft = !nextOn && !!String(getSessionPendingJobId(id) || '').trim();
  if(!nextOn && !preserveRecoverablePendingDraft){
    rt.draftText = "";
    rt.draftProcessText = "";
    rt.draftFiles = [];
    rt.draftImageReplies = [];
    rt.draftWeatherPayload = null;
    rt.reasoning = [];
    rt.reasoningMeta = {};
    rt.sources = [];
    rt.generationUsage = null;
  }
  _rtPersistSessionState(id, rt, { immediate: !nextOn || forceNewTimer });
  _scheduleSessionRuntimePendingSnapshot(id, { immediate: !nextOn || forceNewTimer || typeof statusText === "string" });
  if(!nextOn && preserveRecoverablePendingDraft){
    rt.draftText = "";
    rt.draftProcessText = "";
    rt.draftFiles = [];
    rt.draftImageReplies = [];
    rt.draftWeatherPayload = null;
  }
  if((wasOn !== nextOn || store?.activeId === id) && typeof rtSyncActiveDisplay === 'function') rtSyncActiveDisplay();
  scheduleRefreshRegenerateActionsForVisibleSession(id);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function setSessionRuntimeDraftText(id, txt, opts={}){
  const rt = ensureSessionRuntime(id);
  rt.draftText = String(txt ?? "");
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}

function setSessionRuntimeProcessText(id, txt, opts={}){
  const rt = ensureSessionRuntime(id);
  rt.draftProcessText = String(txt ?? "");
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function pushSessionRuntimeDraftFiles(id, files, opts={}){
  const rt = ensureSessionRuntime(id);
  if(!Array.isArray(rt.draftFiles)) rt.draftFiles = [];
  if(Array.isArray(files)){
    for(const f of files){
      if(!f) continue;
      const key = String(f.download_url || "") + "|" + String(f.filename || "");
      if(!rt.draftFiles.some(x => (String(x.download_url||"") + "|" + String(x.filename||"")) === key)){
        rt.draftFiles.push(f);
      }
    }
  }
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  return rt;
}
function pushSessionRuntimeImageReplies(id, imageReplies, opts={}){
  const rt = ensureSessionRuntime(id);
  rt.draftImageReplies = _normalizePendingAssistantImageReplies([...(Array.isArray(rt.draftImageReplies) ? rt.draftImageReplies : []), ...(Array.isArray(imageReplies) ? imageReplies : [])]);
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  return rt;
}
function setSessionRuntimeWeatherPayload(id, payload, opts={}){
  const rt = ensureSessionRuntime(id);
  rt.draftWeatherPayload = normalizeAssistantWeatherPayload(payload);
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  return rt;
}
function pushSessionRuntimeSourceItems(id, items, opts={}){
  const rt = ensureSessionRuntime(id);
  rt.sources = mergeAssistantSourceItems(Array.isArray(rt.sources) ? rt.sources : [], items);
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  return rt;
}

function pushSessionRuntimeFileProgress(id, progress, opts={}){
  const rt = ensureSessionRuntime(id);
  const prevMeta = _normalizePendingAssistantReasoningMeta(rt.reasoningMeta || {});
  const incoming = _normalizeReasoningFileProgressItems(progress, 4);
  if(!incoming.length) return rt;
  let previousProgress = Array.isArray(prevMeta.fileProgressItems) ? prevMeta.fileProgressItems : [];
  const replaceStages = new Set(['sandbox_arguments_streaming']);
  const incomingStableKeys = new Set();
  for(const item of incoming){
    const stage = String(item?.stage || '').trim();
    const tool = String(item?.tool || '').trim();
    const stable = (typeof _sandboxProgressStableKey === 'function') ? _sandboxProgressStableKey(item) : '';
    if(stable) incomingStableKeys.add(stable);
    if(replaceStages.has(stage)){
      previousProgress = previousProgress.filter(prev => !(String(prev?.stage || '').trim() === stage && String(prev?.tool || '').trim() === tool));
    }
  }
  if(incomingStableKeys.size){
    previousProgress = previousProgress.filter(prev => {
      const stable = (typeof _sandboxProgressStableKey === 'function') ? _sandboxProgressStableKey(prev) : '';
      return !(stable && incomingStableKeys.has(stable));
    });
  }
  const mergedProgress = _normalizeReasoningFileProgressItems([
    ...previousProgress,
    ...incoming,
  ], 16);
  const incomingProgressEvents = (typeof _progressEventFromFileProgress === 'function')
    ? incoming.map(item => _progressEventFromFileProgress(item)).filter(Boolean)
    : [];
  const mergedProgressEvents = (typeof _normalizeReasoningProgressEvents === 'function')
    ? _normalizeReasoningProgressEvents([
        ...(Array.isArray(prevMeta.progressEvents) ? prevMeta.progressEvents : []),
        ...incomingProgressEvents,
      ], 30)
    : (Array.isArray(prevMeta.progressEvents) ? prevMeta.progressEvents : []);
  rt.reasoningMeta = {
    ...prevMeta,
    fileProgressItems: mergedProgress,
    ...(mergedProgressEvents.length ? { progressEvents: mergedProgressEvents } : {}),
    fileToolUsed: true,
  };
  const lastProgress = mergedProgress[mergedProgress.length - 1];
  const entry = _fileProgressReasoningEntry(lastProgress);
  if(entry){
    const entryStable = (typeof _sandboxProgressStableKey === 'function') ? _sandboxProgressStableKey(entry) : '';
    if(entryStable){
      rt.reasoning = _normalizePendingAssistantReasoning(rt.reasoning || []).filter(prev => {
        const stable = (typeof _sandboxProgressStableKey === 'function') ? _sandboxProgressStableKey(prev) : '';
        return !(stable && stable === entryStable);
      });
    }
    rt.reasoning = _upsertReasoningEntry(rt.reasoning, entry);
  }
  _persistSessionRuntimeSnapshot(id);
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function setSessionRuntimeStatus(id, txt, opts={}){
  const rt = ensureSessionRuntime(id);
  rt.statusText = String(txt ?? "");
  _scheduleSessionRuntimePendingSnapshot(id, opts);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function getSessionController(id){
  return id ? (streamControllers[id] || null) : null;
}
function getSessionPromise(id){
  return id ? (streamPromises[id] || null) : null;
}
function getSessionAbortReason(id){
  return id ? (streamAbortReasons[id] || "") : "";
}
function setSessionAbortReason(id, reason){
  if(!id) return;
  streamAbortReasons[id] = String(reason || "");
}
function clearSessionStreamState(id){
  if(!id) return;
  delete streamControllers[id];
  delete streamPromises[id];
  delete streamAbortReasons[id];
}
function isAnySessionStreaming(){
  return Object.values(sessionRuntime).some(rt => !!rt?.streaming);
}
function anyStreamingActive(){
  return isAnySessionStreaming();
}
function isSessionStreaming(id){
  const sid = String(id || '').trim();
  if(!sid) return false;
  const rt = ensureSessionRuntime(sid);
  if(rt.streaming && !getSessionPromise(sid) && sessionObjectLastVisibleMessageIsAssistant(getSessionById(sid))){
    rt.streaming = false;
    rt.rtStartAt = 0;
    rt.draftText = '';
    rt.statusText = '';
    rt.draftProcessText = '';
    rt.draftFiles = [];
    rt.draftImageReplies = [];
    rt.sources = [];
    rt.generationUsage = null;
    _rtPersistSessionState(sid, rt);
    return false;
  }
  return !!rt.streaming;
}
function isSessionStreamingUiLocked(id){
  const sid = String(id || '').trim();
  if(!sid) return false;
  try{
    const rt = ensureSessionRuntime(sid);
    if(rt && rt.streaming) return true;
  }catch(_){ }
  try{
    const pending = pendingAssistantSnapshotForSession(sid, store);
    if(pending && pending.streaming) return true;
  }catch(_){ }
  try{ if(String(getSessionPendingJobId(sid) || '').trim()) return true; }catch(_){ }
  try{ if(getSessionPromise(sid)) return true; }catch(_){ }
  return false;
}

function isRegenerateActionButton(btn){
  if(!btn || !btn.matches || !btn.matches('button')) return false;
  const kind = String(btn.dataset?.actionKind || '').trim().toLowerCase();
  if(kind === 'regenerate') return true;
  const label = [
    btn.getAttribute('aria-label'),
    btn.getAttribute('title'),
    btn.dataset?.actionLabel,
    btn.dataset?.restoreLabel,
    btn.textContent,
  ].map(v => String(v || '').trim()).filter(Boolean).join(' ');
  return /重新生成/.test(label);
}

function collectRegenerateActionButtons(root){
  const scope = root && root.querySelectorAll ? root : chatEl;
  if(!scope) return [];
  return Array.from(scope.querySelectorAll('.bubble-actions-assistant button')).filter(isRegenerateActionButton);
}

function collectBranchVersionControls(root){
  const scope = root && root.querySelectorAll ? root : chatEl;
  if(!scope) return [];
  return Array.from(scope.querySelectorAll('.bubble-version-controls'));
}

function setBranchVersionControlsLocked(root, locked){
  try{
    const controls = collectBranchVersionControls(root);
    controls.forEach((wrap)=>{
      if(!wrap) return;
      const buttons = Array.from(wrap.querySelectorAll('button'));
      if(locked){
        wrap.hidden = true;
        wrap.setAttribute('aria-hidden', 'true');
        wrap.classList.add('bubble-version-locked-hidden');
        wrap.style.display = 'none';
        buttons.forEach((btn)=>{
          btn.disabled = true;
          btn.tabIndex = -1;
        });
      }else{
        wrap.hidden = false;
        wrap.removeAttribute('aria-hidden');
        wrap.classList.remove('bubble-version-locked-hidden');
        wrap.style.display = '';
        buttons.forEach((btn)=>{
          btn.disabled = false;
          btn.removeAttribute('tabindex');
        });
      }
    });
  }catch(_){ }
}

let _regenActionVisibilityFrame = 0;
function refreshRegenerateActionsForVisibleSession(sessionId){
  try{
    if(!chatEl) return;
    const sid = String(sessionId || visibleChatSessionId || store?.activeId || '').trim();
    const activeSid = !isHomeLandingView ? String(store?.activeId || '').trim() : '';
    const visibleSid = String(visibleChatSessionId || '').trim();
    const viewSid = visibleSid || activeSid || sid;
    const appliesToVisibleChat = !!sid && !!viewSid && (sid === viewSid || sid === activeSid || (!visibleSid && sid === activeSid));
    const locked = appliesToVisibleChat && isSessionStreamingUiLocked(sid);
    chatEl.classList.toggle('chat-regenerate-actions-locked', locked);
    chatEl.classList.toggle('chat-branch-controls-locked', locked);
    try{ document.body?.classList?.toggle('chat-regenerate-actions-locked', locked); }catch(_){ }
    try{ document.body?.classList?.toggle('chat-branch-controls-locked', locked); }catch(_){ }
    setBranchVersionControlsLocked(chatEl, locked);
    const buttons = collectRegenerateActionButtons(chatEl);
    buttons.forEach((btn)=>{
      if(!btn) return;
      if(locked){
        btn.hidden = true;
        btn.disabled = true;
        btn.setAttribute('aria-hidden', 'true');
        btn.tabIndex = -1;
        btn.classList.add('bubble-regenerate-locked-hidden');
        btn.style.display = 'none';
      }else{
        btn.hidden = false;
        btn.disabled = false;
        btn.removeAttribute('aria-hidden');
        btn.removeAttribute('tabindex');
        btn.classList.remove('bubble-regenerate-locked-hidden');
        btn.style.display = '';
      }
    });
  }catch(_){ }
}

function scheduleRefreshRegenerateActionsForVisibleSession(sessionId){
  try{
    if(_regenActionVisibilityFrame) cancelAnimationFrame(_regenActionVisibilityFrame);
    const sid = String(sessionId || visibleChatSessionId || store?.activeId || '').trim();
    _regenActionVisibilityFrame = requestAnimationFrame(()=>{
      _regenActionVisibilityFrame = 0;
      refreshRegenerateActionsForVisibleSession(sid);
    });
  }catch(_){
    try{ refreshRegenerateActionsForVisibleSession(sessionId); }catch(__){ }
  }
}

function getStreamingSessionIds(){
  return Object.keys(sessionRuntime).filter(id => sessionRuntime[id]?.streaming);
}
function getOtherStreamingSessionIds(activeId){
  return getStreamingSessionIds().filter(id => id && id !== activeId && store?.sessions?.[id]);
}
function canStartStreamingForSession(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return { ok:false, reason:'missing_session', count:0 };
  if(isSessionStreaming(sid)) return { ok:false, reason:'same_session_streaming', count:getOtherStreamingSessionIds(sid).length };
  const otherStreamingIds = getOtherStreamingSessionIds(sid);
  const otherCount = otherStreamingIds.length;
  if(!PARALLEL_CHAT_STREAMS_ENABLED && otherCount > 0){
    return { ok:false, reason:'other_session_streaming', count:otherCount, ids:otherStreamingIds };
  }
  if(MAX_PARALLEL_CHAT_STREAMS > 0 && otherCount >= MAX_PARALLEL_CHAT_STREAMS){
    return { ok:false, reason:'parallel_limit', count:otherCount, ids:otherStreamingIds };
  }
  return { ok:true, reason:'ok', count:otherCount, ids:otherStreamingIds };
}
function describeParallelStreamBlock(check){
  const info = check || {};
  if(info.reason === 'parallel_limit') return `当前最多同时进行 ${MAX_PARALLEL_CHAT_STREAMS} 个会话，请先等一个会话完成。`;
  if(info.reason === 'other_session_streaming') return '当前有其他会话正在生成，请稍后再试。';
  return '';
}
function refreshStatusForActiveSession(){
  const activeId = isHomeLandingView ? '' : (store?.activeId || '');
  const otherStreamingIds = getOtherStreamingSessionIds(activeId);
  const otherCount = otherStreamingIds.length;
  setSendButtonMode(activeId && isSessionStreaming(activeId) ? "streaming" : "idle");
  refreshRegenerateActionsForVisibleSession(activeId);
  if(activeId && store?.sessions?.[activeId]){
    const rt = ensureSessionRuntime(activeId);
    if(rt.streaming){
      const activeStatus = rt.statusText || "思考中…";
      setStatus(otherCount > 0 ? `${activeStatus}（另有 ${otherCount} 个会话进行中）` : activeStatus);
      return;
    }
  }
  if(otherCount > 0){
    if(otherCount === 1){
      const otherId = otherStreamingIds[0];
      const otherTitle = store.sessions[otherId]?.title || "其他会话";
      const otherStatus = sessionRuntime[otherId]?.statusText || "思考中…";
      setStatus(`其他会话「${otherTitle}」${otherStatus}`);
    }else{
      setStatus(`另有 ${otherCount} 个会话正在进行中`);
    }
    return;
  }
  if(!_statusCoreText || /^(思考中…|抓网中…|等待响应中…（如果一直卡住，检查后端 \/api3\/(?:chat_stream|chat_async\/poll) 是否可访问）|完成|已停止|停止中…|出错|就绪)$/.test(_statusCoreText)){
    setStatus("就绪");
  }
}

async function requestAsyncChatJobStop(jobId){
  const targetJobId = String(jobId || '').trim();
  if(!targetJobId) return false;
  let ctl = null;
  let timeoutId = null;
  try{
    ctl = new AbortController();
    timeoutId = setTimeout(()=>{
      try{ ctl.abort('stop_timeout'); }catch(_){ }
    }, 2500);
    const res = await fetch('/api3/chat_async/stop', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ job_id: targetJobId }),
      cache:'no-store',
      signal: ctl.signal,
    });
    const data = await res.json().catch(()=>({}));
    if(!res.ok){
      if(Number(res.status || 0) === 404) return false;
      if(handleForcedLogin(data, data?.message || data?.error || ('HTTP ' + res.status))) return false;
      throw new Error(data?.error || ('HTTP ' + res.status));
    }
    return !!data?.ok;
  }catch(err){
    console.warn('stop async chat job failed:', err);
    return false;
  }finally{
    try{ if(timeoutId) clearTimeout(timeoutId); }catch(_){ }
  }
}

function getSessionPendingJobId(id){
  return String(store?.sessions?.[id]?.pendingJobId || '').trim();
}
function getSessionPendingJobCursor(id){
  const raw = Number(store?.sessions?.[id]?.pendingJobCursor || 0);
  return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;
}
function stableAsyncChatTurnIdForSession(id, session=null){
  const sid = String(id || session?.id || '').trim();
  const s = session && typeof session === 'object' ? session : getSessionById(sid);
  const rows = Array.isArray(s?.messages) ? s.messages : [];
  for(let i = rows.length - 1; i >= 0; i--){
    const msg = rows[i];
    if(!msg || String(msg.role || '').trim().toLowerCase() !== 'user') continue;
    let identity = '';
    try{ if(typeof messageStableClientIdentity === 'function') identity = String(messageStableClientIdentity(msg) || '').trim(); }catch(_){ }
    identity = identity || String(msg._client_send_id || msg.client_send_id || msg._client_msg_id || msg.client_msg_id || msg.localId || msg.local_id || '').trim();
    const createdAt = Number(msg.created_at_ms || msg.createdAtMs || msg.created_at || msg.createdAt || 0) || 0;
    if(!identity && createdAt > 0) identity = 't' + Math.floor(createdAt).toString(36);
    if(identity) return `${sid || 'session'}:${identity}`.slice(0, 240);
  }
  return '';
}
function setSessionPendingJob(id, jobId, cursor=0, turnId=''){
  const s = getSessionById(id);
  if(!s) return '';
  const nextJobId = String(jobId || '').trim();
  const nextTurnId = String(turnId || s.pendingJobTurnKey || s.runRecovery?.turn_key || stableAsyncChatTurnIdForSession(id, s) || '').trim();
  if(!nextJobId){
    delete s.pendingJobId;
    delete s.pendingJobCursor;
    delete s.pendingJobTurnKey;
  }else{
    s.pendingJobId = nextJobId;
    s.pendingJobCursor = Math.max(0, Math.floor(Number(cursor) || 0));
    if(nextTurnId) s.pendingJobTurnKey = nextTurnId;
    s.runRecovery = {
      ...(s.runRecovery && typeof s.runRecovery === 'object' ? s.runRecovery : {}),
      mode: (typeof sessionConversationMode === 'function' ? sessionConversationMode(s) : 'chat'),
      conversation_id: String(s.id || id || '').trim(),
      server_run_id: nextJobId,
      turn_key: nextTurnId,
      cursor: '',
      status: 'server_owned_inflight',
      updated_at: Date.now(),
    };
    delete s.runRecoveryClearedAt;
    delete s.run_recovery_cleared_at;
    s.syncStatus = 'server_owned_inflight';
    s.sync_status = 'server_owned_inflight';
  }
  // pendingJob* 只是后台任务恢复用元数据，不能刷新会话时间。
  store.sessions[id] = s;
  saveStoreThrottled();
  return nextJobId;
}
function setSessionPendingJobCursor(id, cursor){
  const s = getSessionById(id);
  if(!s) return 0;
  const next = Math.max(0, Math.floor(Number(cursor) || 0));
  if(next <= getSessionPendingJobCursor(id)) return getSessionPendingJobCursor(id);
  s.pendingJobCursor = next;
  // 轮询游标不是聊天内容，不能刷新会话时间。
  store.sessions[id] = s;
  saveStoreThrottled();
  return next;
}
function clearSessionPendingJob(id, opts={}){
  const s = getSessionById(id);
  if(!s) return;
  delete s.pendingJobId;
  delete s.pendingJobCursor;
  delete s.pendingJobTurnKey;
  delete s.runRecovery;
  s.runRecoveryClearedAt = Date.now();
  s.run_recovery_cleared_at = s.runRecoveryClearedAt;
  if(String(s.syncStatus || s.sync_status || '').trim().toLowerCase() === 'server_owned_inflight'){
    s.syncStatus = 'active';
    s.sync_status = 'active';
  }
  // 清理后台任务状态不代表新聊天内容，不能刷新会话时间。
  store.sessions[id] = s;
  if(opts && opts.immediate) saveStore();
  else saveStoreThrottled();
}

function resetSessionTerminalRuntimeState(id, opts={}){
  const sid = String(id || '').trim();
  if(!sid) return;
  const o = opts || {};
  try{
    const timer = _streamPendingSnapshotTimers[sid];
    if(timer){ clearTimeout(timer); delete _streamPendingSnapshotTimers[sid]; }
  }catch(_){ }
  try{
    const rt = ensureSessionRuntime(sid);
    const keepReasoning = !!o.preserveReasoning;
    const keptReasoningMeta = keepReasoning ? _normalizePendingAssistantReasoningMeta(rt.reasoningMeta || {}) : {};
    const keptReasoning = keepReasoning ? _mergeNativeReasoningEntry(rt.reasoning || [], keptReasoningMeta) : [];
    const keptSources = keepReasoning ? normalizeAssistantSourceItems(rt.sources || []) : [];
    const keptGenerationUsage = keepReasoning ? normalizeAssistantUsagePayload(rt.generationUsage || null) : null;
    const startAt = _rtNormalizeStartAtForSession(sid, Number(rt.rtStartAt || 0));
    if(o.finalizeTimer !== false && startAt > 0){
      rt.rtFinalMs = _rtClampElapsedMsForSession(sid, Date.now() - startAt);
    }
    rt.rtStartAt = 0;
    rt.streaming = false;
    rt.statusText = '';
    rt.draftText = '';
    rt.draftProcessText = '';
    rt.draftFiles = [];
    rt.draftImageReplies = [];
    rt.reasoning = keptReasoning;
    rt.reasoningMeta = keptReasoningMeta;
    rt.sources = keptSources;
    rt.generationUsage = keptGenerationUsage;
    _rtPersistSessionState(sid, rt, { immediate:true });
  }catch(_){ }
  try{ clearPendingAssistantSnapshot(sid, { immediate:true }); }catch(_){ }
  try{ clearSessionPendingJob(sid, { immediate:true }); }catch(_){ }
  try{ removeVisibleDraftBubbleForSession(sid); }catch(_){ }
  try{ if(String(store?.activeId || '').trim() === sid) setSendButtonMode('idle'); }catch(_){ }
  try{ rtSyncActiveDisplay(); }catch(_){ }
  try{ refreshStatusForActiveSession(); }catch(_){ }
}

function settleSessionStreamingTerminalState(id, statusText=''){
  const sid = String(id || '').trim();
  if(!sid) return;
  resetSessionTerminalRuntimeState(sid, { finalizeTimer:true, preserveReasoning:true });
  try{
    const rt = ensureSessionRuntime(sid);
    rt.statusText = String(statusText || '');
  }catch(_){ }
}

async function stopStreamingForAction(reason, sessionId, opts={}){
  const targetId = sessionId || store?.activeId;
  if(!targetId || !isSessionStreaming(targetId)) return;
  const preserveDraft = opts?.preserveDraft !== false;
  setSessionAbortReason(targetId, reason || "manual");
  if(preserveDraft){
    try{ persistStreamingDraftsToStore({ immediate:true }); }catch(_){ }
    try{ flushPendingStoreWrites({ cloud:false, keepalive:false, reason:'manual_stop_preserve_draft' }); }catch(_){ }
  }
  const controller = getSessionController(targetId);
  if(controller && typeof controller.abort === 'function'){
    try{ controller.abort(); }catch(_){ }
  }
  const pendingJobId = getSessionPendingJobId(targetId);
  const stopReqPromise = pendingJobId
    ? requestAsyncChatJobStop(pendingJobId).catch(()=> false)
    : Promise.resolve(false);
  try{
    const promise = getSessionPromise(targetId);
    if(promise) await promise;
  }catch(_){ }
  try{ await stopReqPromise; }catch(_){ }
}

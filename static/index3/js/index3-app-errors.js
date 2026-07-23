/* Product frontend module.
 * Purpose: Session/global error normalization, presentation, and transport error observation.
 * Loaded before index3.js; classic-script globals preserve the existing single runtime.
 */

function normalizeSessionBackendErrorPayload(value){
  if(!value) return null;
  if(typeof value === 'string'){
    const text = normalizeCompactErrorText(value);
    return text ? { text, ts: now() } : null;
  }
  if(typeof value !== 'object') return null;
  const text = normalizeCompactErrorText(value.text || value.error || value.message || '');
  if(!text) return null;
  const rawTs = Number(value.ts || value.updatedAt || value.createdAt || 0);
  return { text, ts: Number.isFinite(rawTs) && rawTs > 0 ? rawTs : now() };
}

function getSessionBackendErrorPayload(sessionOrId){
  const s = typeof sessionOrId === 'string' ? getSessionById(sessionOrId) : sessionOrId;
  return normalizeSessionBackendErrorPayload(s?.lastBackendError || null);
}

let _globalAppErrorPayload = null;
let _globalAppErrorTimer = null;
const GLOBAL_APP_ERROR_POPUP_DURATION = 6000;
let _lastCompactErrorKey = '';
let _lastCompactErrorTs = 0;

function normalizeCompactErrorText(value){
  let text = '';
  if(value && typeof value === 'object'){
    const code = String(value.code || value.error_code || value.reason_code || '').trim().toLowerCase();
    if(code){
      const params = value.params && typeof value.params === 'object'
        ? value.params
        : (value.details && typeof value.details === 'object' ? value.details : {});
      try{
        const localized = window.AperviaI18n?.t(`error.code.${code}`, params);
        if(localized && localized !== `error.code.${code}`) return String(localized).slice(0, 1600);
      }catch(_){ }
    }
    text = String(value.message || value.error || value.reason || value.text || '').trim();
  }else{
    text = String(value || '').trim();
  }
  if(!text) return '';
  text = text.replace(/^[A-Za-z_]+Error:\s*/g, '').trim();
  text = text.replace(/^RuntimeError:\s*/i, '').trim();
  text = text.replace(/\s+/g, ' ').trim();
  if(/^Error:\s*/i.test(text)) text = text.replace(/^Error:\s*/i, '').trim();
  const uploadPartialMatch = text.match(/^(?:上传文件|上传|上传目录|同步目录)部分失败[：:]\s*成功\s*(\d+)\s*[，,]\s*失败\s*(\d+)/i);
  if(uploadPartialMatch){
    text = window.AperviaI18n?.t('error.upload_partial', {success:uploadPartialMatch[1], failed:uploadPartialMatch[2]}) || `${uploadPartialMatch[1]} succeeded and ${uploadPartialMatch[2]} failed.`;
  }
  if(/^仅支持\s*http\/https(?:\s*网页地址)?$/i.test(text)){
    text = window.AperviaI18n?.t('error.code.kb_url_scheme_invalid') || 'Only HTTP and HTTPS webpage URLs are supported.';
  }
  const storageFreeMatch = text.match(/^服务器剩余空间暂时不足[\s\S]*?当前剩余\s*([^，。]+)[，。][\s\S]*?至少需要保留\s*([^，。]+)[，。]/i);
  if(storageFreeMatch){
    text = window.AperviaI18n?.t('error.code.storage_system_min_free', {free:storageFreeMatch[1].trim(), minimum:storageFreeMatch[2].trim()}) || `The server does not have enough free space for a safe write. ${storageFreeMatch[1].trim()} is available; ${storageFreeMatch[2].trim()} must remain free.`;
  }
  const aiServiceMatch = text.match(/^AI服务异常\s*[：:]?\s*([\s\S]*)$/i);
  if(aiServiceMatch){
    const detail = String(aiServiceMatch[1] || '').trim();
    text = detail
      ? (window.AperviaI18n?.t('error.ai_service_detail', {detail}) || `AI service error: ${detail}`)
      : (window.AperviaI18n?.t('error.ai_service') || 'AI service error');
  }
  if(text === '请先登录' || text === '请先登录 Apervia。'){
    text = window.AperviaI18n?.t('common.login_required') || 'Please sign in first';
  }else if(text === '已启用 UApiPro，但还没有填写 API Key'){
    text = window.AperviaI18n?.t('settings.web.uapipro_api_key_missing') || 'UApiPro is enabled, but its API key is missing';
  }else if(text === '已启用 UApiPro，但还没有填写 Base URL'){
    text = window.AperviaI18n?.t('settings.web.uapipro_base_url_missing') || 'UApiPro is enabled, but its base URL is missing';
  }
  return text.slice(0, 1600);
}

function isSoftBackgroundControlErrorText(text){
  const raw = normalizeCompactErrorText(text);
  if(!raw) return true;
  const lower = raw.toLowerCase();
  return lower === 'auth_me_timeout'
    || lower === 'auth me timeout'
    || lower === 'auth/me timeout'
    || lower.includes('auth_me_timeout');
}

function shouldIgnoreCompactError(text){
  const raw = normalizeCompactErrorText(text);
  if(!raw) return true;
  const lower = raw.toLowerCase();
  if(lower === '__async_chat_job_stopped__') return true;
  if(lower === 'manual_stop') return true;
  if(isSoftBackgroundControlErrorText(raw)) return true;
  if(isFetchAbortLikeError(raw)) return true;
  if(lower.includes('aborterror')) return true;
  if(lower.includes('fetch is aborted')) return true;
  if(lower.includes('signal is aborted')) return true;
  if(lower.includes('operation was aborted')) return true;
  if(lower.includes('request aborted')) return true;
  if(lower.includes('the user aborted a request')) return true;
  if(lower.includes('upload aborted')) return true;
  if(lower.includes('upload_canceled')) return true;
  if(lower.includes('上传已取消')) return true;
  if(lower.includes('上传已取消')) return true;
  return false;
}

function _normalizeObservedApiPath(url){
  const raw = String(url || '').trim();
  if(!raw) return '';
  try{
    return new URL(raw, window.location.origin).pathname || '';
  }catch(_){
    const match = raw.match(/^(?:https?:\/\/[^\/]+)?([^?#]+)/i);
    return match ? String(match[1] || '') : raw;
  }
}

function isUploadTransportApiPath(path){
  const raw = String(path || '').trim();
  return raw === '/api3/upload'
    || raw === '/api3/upload_chunk/init'
    || raw === '/api3/upload_chunk/finish'
    || raw === '/api3/upload_chunk/cancel'
    || raw.startsWith('/api3/upload_chunk/raw_part')
    || raw.startsWith('/api3/upload_chunk/part');
}

function isRetryableObservedHttpStatus(status){
  const code = Number(status || 0) || 0;
  return code === 0 || code === 408 || code === 409 || code === 425 || code === 429
    || code === 500 || code === 502 || code === 503 || code === 504;
}

function isGenericRetryableRequestErrorText(text){
  const raw = normalizeCompactErrorText(text);
  if(!raw) return false;
  const lower = raw.toLowerCase();
  if(raw === '请求失败' || raw === '网络错误') return true;
  if(lower === 'failed to fetch' || lower === 'load failed' || lower === 'networkerror') return true;
  if(lower.includes('network error')) return true;
  if(lower.includes('network request failed')) return true;
  if(lower.includes('timeout') || lower.includes('timed out')) return true;
  if(lower.includes('connection reset') || lower.includes('connection refused')) return true;
  if(lower.includes('temporarily unavailable')) return true;
  const httpMatch = lower.match(/\bhttp\s+(\d{3})\b/);
  return httpMatch ? isRetryableObservedHttpStatus(Number(httpMatch[1])) : false;
}

function isBackgroundRetryableApiPath(path){
  const raw = String(path || '').trim();
  if(!raw) return false;
  return raw === '/api3/auth/me'
    || raw.startsWith('/api3/chat-sync/')
    || raw.startsWith('/api3/image-pullback/')
    || raw.startsWith('/api3/user/')
    || raw.startsWith('/api3/account/')
    || raw.startsWith('/api3/files/')
    || raw.startsWith('/api3/artifacts/');
}

function shouldSilenceRetryableBackgroundError(text, opts, sessionId){
  if(sessionId) return false;
  const o = opts && typeof opts === 'object' ? opts : {};
  const source = String(o.source || '').trim().toLowerCase();
  const path = _normalizeObservedApiPath(o.url || '');
  const status = Number(o.status || 0) || 0;
  const retryableStatus = isRetryableObservedHttpStatus(status);
  const retryableText = isGenericRetryableRequestErrorText(text);
  if(!retryableText && !retryableStatus) return false;
  if(path && isBackgroundRetryableApiPath(path)) return true;
  if(path && /^\/api3\//.test(path) && retryableText) return true;
  if(!path && (source === 'unhandledrejection' || source === 'fetch_throw' || source === 'xhr_error') && retryableText) return true;
  return false;
}

let _lastSilentBackgroundRetryKey = '';
let _lastSilentBackgroundRetryTs = 0;

function noteSilentBackgroundRetry(message, opts){
  const o = opts && typeof opts === 'object' ? opts : {};
  const text = normalizeCompactErrorText(message) || 'retryable_request_error';
  const path = _normalizeObservedApiPath(o.url || '');
  const key = `${path || String(o.source || 'background')}:${text}`;
  const ts = now();
  if(key !== _lastSilentBackgroundRetryKey || (ts - _lastSilentBackgroundRetryTs) > 5000){
    _lastSilentBackgroundRetryKey = key;
    _lastSilentBackgroundRetryTs = ts;
    try{ console.debug('[webai] silent background retryable error:', { path, status:o.status || 0, text }); }catch(_){ }
  }
  try{
    if(path.startsWith('/api3/chat-sync/') && typeof restorePendingCloudSyncForScope === 'function'){
      restorePendingCloudSyncForScope(currentAccountEmail, {
        reason: 'silent_retryable_request_error',
        delayMs: typeof stableBackoffMs === 'function' ? stableBackoffMs(1, 1800, 15000) : 3000,
        allowDirtyFallback: true,
        allowStaleAfterCloudAuthority: true,
      });
    }else if(path === '/api3/auth/me' && typeof scheduleAuthUiSoftRetry === 'function'){
      scheduleAuthUiSoftRetry();
    }
  }catch(_){ }
}

function compactErrorDedupKey(message, sessionId){
  return `${String(sessionId || '').trim()}__${normalizeCompactErrorText(message)}`;
}

function shouldSkipCompactErrorReport(message, sessionId){
  const text = normalizeCompactErrorText(message);
  if(shouldIgnoreCompactError(text)) return true;
  const key = compactErrorDedupKey(text, sessionId);
  const ts = now();
  if(key && key === _lastCompactErrorKey && (ts - _lastCompactErrorTs) < 1200){
    return true;
  }
  _lastCompactErrorKey = key;
  _lastCompactErrorTs = ts;
  return false;
}

function resolveCompactErrorSessionId(preferredSessionId){
  const sid = String(preferredSessionId || '').trim();
  if(sid && getSessionById(sid)) return sid;
  const activeId = String(store?.activeId || '').trim();
  if(activeId && getSessionById(activeId)) return activeId;
  return '';
}

function resolveReportErrorSessionId(opts){
  const o = opts && typeof opts === 'object' ? opts : {};
  const rawSid = String(o.sessionId || '').trim();
  if(!rawSid || !getSessionById(rawSid)) return '';
  if(o.bindToSession === true) return rawSid;
  const source = String(o.source || '').trim().toLowerCase();
  if(source === 'chat' || source.startsWith('chat_') || source === 'stream' || source === 'async_chat') return rawSid;
  if(_isChatTransportApiRequestUrl(o.url || '')) return rawSid;
  return '';
}


function getAssistantBackendErrorPayload(message){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg || String(msg.role || '').trim().toLowerCase() !== 'assistant') return null;
  const direct = msg._backend_error || msg.backendError || msg.backend_error || null;
  const fromDirect = normalizeSessionBackendErrorPayload(direct);
  if(fromDirect) return fromDirect;
  const content = msg.content;
  if(content && typeof content === 'object' && !Array.isArray(content)){
    const kind = String(content._kind || '').trim().toLowerCase();
    if(kind === 'backend_error' || kind === 'model_error' || kind === 'chat_error'){
      return normalizeSessionBackendErrorPayload(content);
    }
  }
  return null;
}

function buildBackendErrorCardNode(payload){
  const data = normalizeSessionBackendErrorPayload(payload);
  if(!data || !data.text) return null;
  const card = document.createElement('div');
  card.className = 'backend-error-card';
  card.setAttribute('role', 'alert');
  const icon = document.createElement('span');
  icon.className = 'backend-error-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = 'i';
  const text = document.createElement('div');
  text.className = 'backend-error-text';
  text.textContent = data.text;
  card.appendChild(icon);
  card.appendChild(text);
  return card;
}

function createBackendErrorAssistantMessage(sessionId, payload, opts={}){
  const data = normalizeSessionBackendErrorPayload(payload);
  if(!data || !data.text) return null;
  const sid = String(sessionId || store?.activeId || '').trim();
  const ts = Number(data.ts || Date.now()) || Date.now();
  const jobKey = String(opts.jobKey || opts.job_key || getSessionPendingJobId(sid) || '').trim();
  const msg = decorateOutgoingAssistantMessage({
    role:'assistant',
    created_at_ms: ts,
    createdAtMs: ts,
    content: data.text,
    _backend_error: { text:data.text, ts },
    backendError: { text:data.text, ts },
  }, sid, ts, jobKey, 'backend_error');
  const branchCtx = opts.branchContext && typeof opts.branchContext === 'object' ? opts.branchContext : null;
  if(branchCtx && branchCtx.groupId && String(branchCtx.kind || '') === 'assistant_regen'){
    msg._webai_conv_branch_id = String(branchCtx.groupId || '');
    msg._webai_conv_branch_version = Number(branchCtx.versionIndex || 0) || 0;
    msg._webai_conv_branch_kind = 'assistant_regen';
    msg._webai_conv_branch_control = true;
  }
  return msg;
}

function findBackendErrorAssistantIndexInCurrentTurn(messages, payload){
  const rows = Array.isArray(messages) ? messages : [];
  const data = normalizeSessionBackendErrorPayload(payload);
  const targetText = String(data?.text || '').trim();
  for(let i = rows.length - 1; i >= 0; i -= 1){
    const msg = rows[i];
    if(!msg || String(msg.role || '').trim().toLowerCase() === 'system') continue;
    if(String(msg.role || '').trim().toLowerCase() === 'user') break;
    const existing = getAssistantBackendErrorPayload(msg);
    if(existing && (!targetText || existing.text === targetText)) return i;
  }
  return -1;
}

function persistSessionBackendErrorAsAssistantMessage(session, sessionId, payload){
  const s = session && typeof session === 'object' ? session : null;
  const data = normalizeSessionBackendErrorPayload(payload);
  const sid = String(sessionId || s?.id || store?.activeId || '').trim();
  if(!s || !data || !data.text || !sid) return false;
  if(!Array.isArray(s.messages)) s.messages = [];
  const rt = ensureSessionRuntime(sid);
  const pendingBranchForSave = rt?.pendingBranchSave || s._webaiPendingConversationBranch || null;
  if(pendingBranchForSave && pendingBranchForSave.groupId){
    try{ webaiBranchPreparePendingTailForSave(s, pendingBranchForSave); }catch(_){ }
  }
  const branchCtx = pendingBranchForSave || rt?.pendingBranchSave || s._webaiPendingConversationBranch || null;
  const errorMsg = createBackendErrorAssistantMessage(sid, data, { branchContext: branchCtx });
  if(!errorMsg) return false;
  const duplicateIndex = findBackendErrorAssistantIndexInCurrentTurn(s.messages, data);
  if(duplicateIndex >= 0){
    const old = s.messages[duplicateIndex];
    s.messages[duplicateIndex] = { ...(old || {}), ...errorMsg, _client_msg_id: old?._client_msg_id || errorMsg._client_msg_id };
  }else{
    s.messages.push(errorMsg);
  }
  try{
    const pendingBranchForCommit = branchCtx || rt?.pendingBranchSave || s._webaiPendingConversationBranch || null;
    if(pendingBranchForCommit && pendingBranchForCommit.groupId){
      webaiBranchCommitActiveVersion(s, pendingBranchForCommit);
      try{ delete rt.pendingBranchSave; }catch(_){ }
    }else{
      webaiBranchCommitActiveVersion(s, null);
    }
  }catch(_){ }
  try{ webaiOfficialPersistActivePath(s); }catch(_){ }
  try{ clearPendingAssistantFieldsFromSession(s); }catch(_){ }
  try{ delete s.lastBackendError; }catch(_){ }
  return true;
}

function setSessionBackendError(sessionId, message){
  const sid = resolveCompactErrorSessionId(sessionId);
  const payload = normalizeSessionBackendErrorPayload({ text: message, ts: now() });
  if(!payload || !sid) return;
  updateSessionById(sid, s => {
    persistSessionBackendErrorAsAssistantMessage(s, sid, payload);
  }, { skipCompress:true, touchUpdatedAt:false }).catch(()=>{});
}

function clearSessionBackendError(sessionId, opts){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  const s = getSessionById(sid);
  if(!s || !s.lastBackendError) return;
  const previousUpdatedAt = s.updatedAt;
  delete s.lastBackendError;
  if(previousUpdatedAt !== undefined) s.updatedAt = previousUpdatedAt;
  store.sessions[sid] = s;
  saveStore();
  if(!(opts && opts.render === false)) safeRenderAll();
}

function setGlobalAppError(message){
  const payload = normalizeSessionBackendErrorPayload({ text: message, ts: now() });
  if(!payload) return;
  showAppErrorPopup(payload.text, GLOBAL_APP_ERROR_POPUP_DURATION, { title:window.AperviaI18n?.t('common.system_error') || 'System error' });
}

function clearGlobalAppError(){
  _globalAppErrorPayload = null;
  try{ if(_globalAppErrorTimer) clearTimeout(_globalAppErrorTimer); }catch(_){ }
  _globalAppErrorTimer = null;
  renderGlobalAppErrorDock();
}

function showAppErrorPopup(message, duration=GLOBAL_APP_ERROR_POPUP_DURATION, opts=null){
  const payload = normalizeSessionBackendErrorPayload({ text: message, ts: now() });
  if(!payload) return;
  const optionObj = opts && typeof opts === 'object' ? opts : {};
  const defaultTitle=window.AperviaI18n?.t('common.error')||'Error';
  payload.title = String(optionObj.title || defaultTitle).trim() || defaultTitle;
  _globalAppErrorPayload = payload;
  renderGlobalAppErrorDock();
  try{ if(_globalAppErrorTimer) clearTimeout(_globalAppErrorTimer); }catch(_){ }
  const ms = Math.max(2400, Number(duration) || GLOBAL_APP_ERROR_POPUP_DURATION);
  _globalAppErrorTimer = setTimeout(()=>{
    _globalAppErrorPayload = null;
    _globalAppErrorTimer = null;
    renderGlobalAppErrorDock();
  }, ms);
}

function ensureGlobalAppErrorDock(){
  let dock = document.getElementById('globalAppErrorDock');
  if(dock) return dock;
  dock = document.createElement('div');
  dock.id = 'globalAppErrorDock';
  dock.className = 'global-error-dock';
  dock.setAttribute('role', 'dialog');
  dock.setAttribute('aria-modal', 'false');
  dock.setAttribute('aria-live', 'assertive');
  dock.innerHTML = '<div class="global-error-dock-head"><div class="global-error-dock-title">Error</div><button type="button" class="global-error-dock-close" aria-label="Close">×</button></div><pre class="global-error-dock-pre"></pre>';
  const closeBtn = dock.querySelector('.global-error-dock-close');
  closeBtn?.addEventListener('click', clearGlobalAppError);
  document.body.appendChild(dock);
  return dock;
}

function renderGlobalAppErrorDock(){
  const dock = ensureGlobalAppErrorDock();
  const titleEl = dock.querySelector('.global-error-dock-title');
  const pre = dock.querySelector('.global-error-dock-pre');
  const closeBtn=dock.querySelector('.global-error-dock-close');
  const defaultTitle=window.AperviaI18n?.t('common.error')||'Error';
  if(closeBtn) closeBtn.setAttribute('aria-label',window.AperviaI18n?.t('common.close')||'Close');
  const data = normalizeSessionBackendErrorPayload(_globalAppErrorPayload);
  if(!data){
    dock.classList.remove('show');
    if(titleEl) titleEl.textContent = defaultTitle;
    if(pre) pre.textContent = '';
    return;
  }
  if(titleEl) titleEl.textContent = String((_globalAppErrorPayload && _globalAppErrorPayload.title) || defaultTitle).trim() || defaultTitle;
  if(pre) pre.textContent = data.text;
  dock.classList.add('show');
}

function reportAppError(message, opts){
  const o = opts || {};
  const text = normalizeCompactErrorText(message);
  const sid = resolveReportErrorSessionId(o);
  if(shouldSilenceRetryableBackgroundError(text, o, sid)){
    noteSilentBackgroundRetry(text, o);
    return;
  }
  if(shouldSkipCompactErrorReport(text, sid || 'global')) return;
  if(sid){
    setSessionBackendError(sid, text);
    return;
  }
  setGlobalAppError(text);
}

function _resolveObservedRequestUrl(input){
  try{
    if(typeof input === 'string') return new URL(input, window.location.origin).toString();
    if(input && typeof input.url === 'string') return new URL(input.url, window.location.origin).toString();
  }catch(_){ }
  return String(input || '');
}

function _isObservedApiRequestUrl(url){
  const raw = String(url || '').trim();
  if(!raw) return false;
  return /^\/api3\//.test(raw) || /^https?:\/\/[^\/]+\/api3\//i.test(raw);
}

function _isChatTransportApiRequestUrl(url){
  const raw = String(url || '').trim();
  if(!raw) return false;
  try{
    const parsed = new URL(raw, window.location.origin);
    return /^\/api3\/chat_async\/(start|poll|stream|stop)\b/.test(parsed.pathname || '');
  }catch(_){
    return /^\/api3\/chat_async\/(start|poll|stream|stop)\b/.test(raw);
  }
}

async function _readObservedErrorTextFromResponse(response){
  if(!(response instanceof Response)) return '';
  const contentType = String(response.headers.get('content-type') || '').toLowerCase();
  if(contentType.includes('text/event-stream')) return '';
  const clone = response.clone();
  if(contentType.includes('application/json') || contentType.includes('+json')){
    try{
      const data = await clone.json();
      if(!response.ok){
        return normalizeCompactErrorText(data || ('HTTP ' + response.status));
      }
      if(data && typeof data === 'object'){
        if(data.ok === false || data.success === false){
          return normalizeCompactErrorText(data || 'Request failed');
        }
        if((data.reason_code && data.message) || (typeof data.error === 'string' && data.error.trim())){
          return normalizeCompactErrorText(data);
        }
      }
      return '';
    }catch(_){
      if(response.ok) return '';
    }
  }
  if(response.ok) return '';
  try{
    const raw = String(await clone.text() || '').trim();
    return normalizeCompactErrorText(raw || ('HTTP ' + response.status));
  }catch(_){
    return normalizeCompactErrorText('HTTP ' + response.status);
  }
}

function _observeFetchError(response, requestUrl, init){
  const url = String(requestUrl || '').trim();
  if(!_isObservedApiRequestUrl(url)) return;
  const observedSessionId = init && init.__sessionId ? String(init.__sessionId || '').trim() : '';
  if(_isChatTransportApiRequestUrl(url) && !observedSessionId) return;
  Promise.resolve().then(async ()=>{
    const text = await _readObservedErrorTextFromResponse(response);
    if(!text) return;
    reportAppError(text, {
      sessionId: observedSessionId,
      bindToSession: !!observedSessionId,
      source: observedSessionId ? 'chat_fetch' : 'fetch',
      url,
      status: Number(response?.status || 0) || 0,
    });
  }).catch(()=>{});
}

function installCompactAppErrorHooks(){
  if(window.__webaiCompactErrorHooksInstalled) return;
  window.__webaiCompactErrorHooksInstalled = true;

  if(typeof window.fetch === 'function'){
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function(input, init){
      const requestUrl = _resolveObservedRequestUrl(input);
      try{
        const response = await nativeFetch(input, init);
        _observeFetchError(response, requestUrl, init);
        return response;
      }catch(err){
        if(_isObservedApiRequestUrl(requestUrl) && !isFetchAbortLikeError(err)){
          const observedSessionId = init && init.__sessionId ? String(init.__sessionId || '').trim() : '';
          if(!(_isChatTransportApiRequestUrl(requestUrl) && !observedSessionId)){
            reportAppError(err, {
              sessionId: observedSessionId,
              bindToSession: !!observedSessionId,
              source: observedSessionId ? 'chat_fetch_throw' : 'fetch_throw',
              url: requestUrl,
            });
          }
        }
        throw err;
      }
    };
  }

  if(typeof XMLHttpRequest === 'function' && XMLHttpRequest.prototype){
    const nativeOpen = XMLHttpRequest.prototype.open;
    const nativeSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url){
      try{ this.__webaiObservedUrl = _resolveObservedRequestUrl(url); }catch(_){ this.__webaiObservedUrl = String(url || ''); }
      return nativeOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body){
      if(!this.__webaiObservedBound){
        this.__webaiObservedBound = true;
        this.addEventListener('loadend', ()=>{
          const url = String(this.__webaiObservedUrl || '').trim();
          if(!_isObservedApiRequestUrl(url)) return;
          const path = _normalizeObservedApiPath(url);
          const status = Number(this.status || 0) || 0;
          if(this.__webaiObservedAborted || (status === 0 && isUploadTransportApiPath(path))) return;
          if(status >= 200 && status < 300) return;
          let text = '';
          try{
            const raw = String(this.responseText || '').trim();
            if(raw){
              try{
                const data = JSON.parse(raw);
                text = normalizeCompactErrorText(data || raw);
              }catch(_){
                text = normalizeCompactErrorText(raw);
              }
            }
          }catch(_){ }
          reportAppError(text || ('HTTP ' + status), { source:'xhr', url });
        });
        this.addEventListener('error', ()=>{
          const url = String(this.__webaiObservedUrl || '').trim();
          if(!_isObservedApiRequestUrl(url)) return;
          if(isUploadTransportApiPath(_normalizeObservedApiPath(url))) return;
          reportAppError('网络错误', { source:'xhr_error', url });
        });
        this.addEventListener('abort', ()=>{
          this.__webaiObservedAborted = true;
        });
      }
      return nativeSend.apply(this, arguments);
    };
  }

  window.addEventListener('error', (event)=>{
    const text = normalizeCompactErrorText(event?.message || event?.error || 'Script error');
    if(!text || text === 'Script error') return;
    reportAppError(text, { source:'window_error' });
  });

  window.addEventListener('unhandledrejection', (event)=>{
    reportAppError(event?.reason || 'Unhandled promise rejection', { source:'unhandledrejection' });
  });
}

installCompactAppErrorHooks();

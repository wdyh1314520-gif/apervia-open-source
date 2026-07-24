/* Store persistence, account-scoped storage, and cloud sync.*/
const STORE_KEY = "webai_sessions_v3";
const STORE_KEY_BASE = STORE_KEY;
const CLOUD_SYNC_DEBOUNCE_MS = 350;
const CLOUD_SYNC_FETCH_TIMEOUT_MS = 30000;
const CLOUD_SYNC_RETRY_MAX_MS = 180000;
const CLOUD_SYNC_PROTOCOL_VERSION = 5;
const CLOUD_SYNC_OP_PAYLOAD_SOFT_LIMIT = 640 * 1024;
const LOCAL_STORAGE_FULL_STORE_SOFT_LIMIT = 512 * 1024;
const CLOUD_SYNC_DEVICE_ID_KEY = "webai_cloudsync_device_id_v2";
const CLOUD_SYNC_DELETED_SESSIONS_MAX = 2000;
const CLOUD_SYNC_DELETED_SESSION_RETENTION_MS = 90 * 24 * 3600 * 1000;
const ACCOUNT_CHAT_LIMITS_DEFAULTS = Object.freeze({
  maxSessions: 0,
  maxMessagesPerSession: 0,
  maxTextChars: 0,
  maxStoreBytes: 24 * 1024 * 1024,
});
let accountChatLimits = { ...ACCOUNT_CHAT_LIMITS_DEFAULTS };
let currentAccountEmail = "";
let currentCloudStoreUpdatedTs = 0;
let currentCloudStoreRevision = 0;
let cloudSyncTimer = null;
let cloudSyncInFlight = false;
let cloudSyncQueuedPayload = "";
let lastCloudSyncedPayload = "";
let cloudSyncErrorShown = "";
let cloudSyncRetryCount = 0;
let cloudSyncLastReason = "";
let cloudSyncLastPushBuildMeta = { partial:false, totalOps:0, sentOps:0, error:'' };
let pendingCloudSessionDeletes = new Map();
let lastLoadedStoreScopeKey = STORE_KEY;

function _usageNumber(value){
  const n = Math.floor(Number(value || 0) || 0);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function normalizeAssistantUsagePayload(payload){
  if(!payload || typeof payload !== 'object') return null;
  const input = _usageNumber(payload.input_tokens ?? payload.prompt_tokens ?? payload.inputTokens ?? payload.promptTokens);
  const output = _usageNumber(payload.output_tokens ?? payload.completion_tokens ?? payload.outputTokens ?? payload.completionTokens);
  const total = _usageNumber(payload.total_tokens ?? payload.totalTokens) || (input + output);
  const reasoning = _usageNumber(payload.reasoning_tokens ?? payload.reasoningTokens);
  const cached = _usageNumber(payload.cached_tokens ?? payload.cachedTokens);
  const callCount = _usageNumber(payload.call_count ?? payload.callCount) || (Array.isArray(payload.calls) ? payload.calls.length : 0);
  if(!input && !output && !total && !reasoning && !cached) return null;
  const calls = Array.isArray(payload.calls) ? payload.calls.filter(x => x && typeof x === 'object').slice(-12).map(x => ({
    phase: String(x.phase || ''),
    model: String(x.model || ''),
    endpoint: String(x.endpoint || ''),
    input_tokens: _usageNumber(x.input_tokens ?? x.prompt_tokens ?? x.inputTokens ?? x.promptTokens),
    output_tokens: _usageNumber(x.output_tokens ?? x.completion_tokens ?? x.outputTokens ?? x.completionTokens),
    total_tokens: _usageNumber(x.total_tokens ?? x.totalTokens),
    reasoning_tokens: _usageNumber(x.reasoning_tokens ?? x.reasoningTokens),
    cached_tokens: _usageNumber(x.cached_tokens ?? x.cachedTokens),
  })) : [];
  return {
    input_tokens: input,
    prompt_tokens: input,
    output_tokens: output,
    completion_tokens: output,
    total_tokens: total,
    reasoning_tokens: reasoning,
    cached_tokens: cached,
    call_count: callCount || calls.length,
    endpoint: String(payload.endpoint || ''),
    calls,
  };
}

function assistantUsageText(payload){
  const usage = normalizeAssistantUsagePayload(payload);
  if(!usage) return '';
  const t = (key, params, fallback)=> window.AperviaI18n?.t(key, params, fallback) || fallback;
  const parts = [];
  if(usage.input_tokens) parts.push(t('chat.usage.input', {count:usage.input_tokens}, `Input ${usage.input_tokens}`));
  if(usage.output_tokens) parts.push(t('chat.usage.output', {count:usage.output_tokens}, `Output ${usage.output_tokens}`));
  if(usage.total_tokens) parts.push(t('chat.usage.total', {count:usage.total_tokens}, `Total ${usage.total_tokens}`));
  if(usage.reasoning_tokens) parts.push(t('chat.usage.reasoning', {count:usage.reasoning_tokens}, `Reasoning ${usage.reasoning_tokens}`));
  if(usage.cached_tokens) parts.push(t('chat.usage.cached', {count:usage.cached_tokens}, `Cached ${usage.cached_tokens}`));
  return parts.length
    ? t('chat.usage.summary', {parts:parts.join(' · ')}, `Usage: ${parts.join(' · ')} tokens`)
    : '';
}

function getAssistantMessageGenerationUsage(message){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg) return null;
  return normalizeAssistantUsagePayload(
    msg.generationUsage || msg.generation_usage || msg.usage || msg.tokenUsage || msg.token_usage || null
  );
}

function normalizeAccountScopeEmail(email){
  return String(email || "").trim().toLowerCase();
}
function buildScopedStoreKey(email){
  const normalized = normalizeAccountScopeEmail(email);
  return normalized ? `${STORE_KEY_BASE}::acct::${encodeURIComponent(normalized)}` : STORE_KEY_BASE;
}
function currentStoreStorageKey(){
  return buildScopedStoreKey(currentAccountEmail);
}
function currentIdbKey(){
  return currentStoreStorageKey();
}
function buildScopedStoreMetaKey(email){
  return buildScopedStoreKey(email) + "::meta";
}
function buildScopedCloudSyncPendingKey(email){
  return buildScopedStoreKey(email) + "::cloudsync_pending";
}
function buildScopedDeletedSessionsKey(email){
  return buildScopedStoreKey(email) + "::deleted_sessions";
}
function cloudSyncNormalizeDeletedAtMs(value){
  let n = Number(value || 0) || 0;
  if(n > 0 && n < 100000000000) n *= 1000;
  return Math.max(0, Math.floor(n));
}
function normalizeCloudSessionDeleteTombstones(value){
  const out = {};
  const add = (sidRaw, rowRaw={}) => {
    const sid = String(sidRaw || rowRaw?.session_id || rowRaw?.sessionId || rowRaw?.id || '').trim();
    if(!sid) return;
    const row = rowRaw && typeof rowRaw === 'object' ? rowRaw : {};
    const deletedAt = cloudSyncNormalizeDeletedAtMs(row.deleted_at ?? row.deletedAt ?? row.ts ?? row.time ?? Date.now()) || Date.now();
    const prev = out[sid];
    if(prev && Number(prev.deleted_at || 0) > deletedAt) return;
    out[sid] = {
      session_id: sid,
      deleted_at: deletedAt,
      device_id: String(row.device_id || row.deviceId || '').trim() || getCloudSyncDeviceId(),
      server_revision: Number(row.server_revision ?? row.revision ?? row.deleted_revision ?? row.deletedRevision ?? 0) || 0,
    };
  };
  if(Array.isArray(value)){
    for(const row of value){
      if(typeof row === 'string') add(row, { deleted_at: Date.now() });
      else if(row && typeof row === 'object') add(row.session_id || row.sessionId || row.id, row);
    }
  }else if(value && typeof value === 'object'){
    for(const [sid, row] of Object.entries(value)){
      if(row && typeof row === 'object') add(sid, row);
      else if(row) add(sid, { deleted_at: row });
    }
  }
  return out;
}
function readScopedSessionDeleteTombstones(scopeEmail=currentAccountEmail){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return {};
  try{
    const raw = localStorage.getItem(buildScopedDeletedSessionsKey(normalized));
    if(!raw) return {};
    return normalizeCloudSessionDeleteTombstones(JSON.parse(raw));
  }catch(_){
    return {};
  }
}
function writeScopedSessionDeleteTombstones(scopeEmail=currentAccountEmail, tombstones={}){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return {};
  const now = Date.now();
  const rows = Object.values(normalizeCloudSessionDeleteTombstones(tombstones))
    .filter(row => row && row.session_id && (!row.deleted_at || now - Number(row.deleted_at || 0) <= CLOUD_SYNC_DELETED_SESSION_RETENTION_MS))
    .sort((a,b)=> (Number(b.deleted_at || 0) - Number(a.deleted_at || 0)) || String(a.session_id).localeCompare(String(b.session_id)))
    .slice(0, CLOUD_SYNC_DELETED_SESSIONS_MAX);
  const next = {};
  for(const row of rows) next[row.session_id] = row;
  try{
    if(Object.keys(next).length) localStorage.setItem(buildScopedDeletedSessionsKey(normalized), JSON.stringify(next));
    else localStorage.removeItem(buildScopedDeletedSessionsKey(normalized));
  }catch(_){ }
  return next;
}
function mergeScopedSessionDeleteTombstones(scopeEmail=currentAccountEmail, incoming={}){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return {};
  const current = readScopedSessionDeleteTombstones(normalized);
  const rows = normalizeCloudSessionDeleteTombstones(incoming);
  for(const [sid, row] of Object.entries(rows)){
    const prev = current[sid];
    const prevRev = Number(prev?.server_revision || 0) || 0;
    const rowRev = Number(row?.server_revision || 0) || 0;
    const prevAt = Number(prev?.deleted_at || 0) || 0;
    const rowAt = Number(row?.deleted_at || 0) || 0;
    if(!prev || rowRev > prevRev || rowAt >= prevAt) current[sid] = row;
  }
  return writeScopedSessionDeleteTombstones(normalized, current);
}
function markLocalSessionDeleteTombstone(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  const email = normalizeAccountScopeEmail(opts?.scopeEmail || currentAccountEmail);
  if(!sid || !email) return false;
  const deletedAt = cloudSyncNormalizeDeletedAtMs(opts?.deleted_at ?? opts?.deletedAt ?? Date.now()) || Date.now();
  mergeScopedSessionDeleteTombstones(email, {
    [sid]: {
      session_id: sid,
      deleted_at: deletedAt,
      device_id: String(opts?.device_id || opts?.deviceId || getCloudSyncDeviceId()).trim(),
      server_revision: Number(opts?.server_revision ?? opts?.revision ?? 0) || 0,
    },
  });
  return true;
}
function extractCloudSessionDeleteTombstones(payload){
  const obj = payload && typeof payload === 'object' ? payload : {};
  const out = {};
  const merge = (value) => Object.assign(out, normalizeCloudSessionDeleteTombstones(value));
  merge(obj.deleted_sessions || obj.deletedSessions || obj.deleted_session_tombstones || obj.deletedSessionTombstones || obj.session_tombstones || obj.tombstones);
  if(obj.store && typeof obj.store === 'object'){
    merge(obj.store._deleted_sessions || obj.store.deleted_sessions || obj.store.deletedSessions || obj.store.deleted_session_tombstones || obj.store.deletedSessionTombstones || obj.store._deletedSessionTombstones);
  }
  if(Array.isArray(obj.ops)){
    for(const op of obj.ops){
      if(!op || typeof op !== 'object') continue;
      const type = String(op.op_type || op.type || '').trim().toLowerCase();
      if(type !== 'delete_session') continue;
      const payload = op.payload && typeof op.payload === 'object' ? op.payload : {};
      const sid = String(op.session_id || op.sessionId || payload.session_id || payload.sessionId || '').trim();
      if(!sid) continue;
      out[sid] = {
        session_id: sid,
        deleted_at: cloudSyncNormalizeDeletedAtMs(payload.deleted_at ?? payload.deletedAt ?? op.created_at ?? op.createdAt ?? Date.now()) || Date.now(),
        device_id: String(op.device_id || op.deviceId || payload.device_id || payload.deviceId || '').trim(),
        server_revision: Number(op.revision ?? op.server_revision ?? payload.revision ?? payload.server_revision ?? 0) || 0,
      };
    }
  }
  return out;
}
function receiveCloudSessionDeleteTombstones(payload, scopeEmail=currentAccountEmail){
  const rows = extractCloudSessionDeleteTombstones(payload);
  return mergeScopedSessionDeleteTombstones(scopeEmail, rows);
}
function isSessionDeletedByTombstones(sessionId, scopeEmail=currentAccountEmail, extraTombstones=null){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  const rows = { ...readScopedSessionDeleteTombstones(scopeEmail), ...normalizeCloudSessionDeleteTombstones(extraTombstones || {}) };
  return !!rows[sid];
}
function applySessionDeleteTombstonesToStore(targetStore, scopeEmail=currentAccountEmail, extraTombstones=null){
  const st = targetStore && typeof targetStore === 'object' ? targetStore : null;
  if(!st || !st.sessions || typeof st.sessions !== 'object') return false;
  const rows = { ...readScopedSessionDeleteTombstones(scopeEmail), ...normalizeCloudSessionDeleteTombstones(extraTombstones || {}) };
  const ids = Object.keys(rows);
  if(!ids.length) return false;
  let changed = false;
  for(const sid of ids){
    if(st.sessions && Object.prototype.hasOwnProperty.call(st.sessions, sid)){
      delete st.sessions[sid];
      changed = true;
    }
  }
  if(st.activeId && (!st.sessions || !st.sessions[st.activeId])){
    st.activeId = Object.keys(st.sessions || {})[0] || null;
    changed = true;
  }
  try{ normalizeStoreActiveIdInPlace(st); }catch(_){ }
  return changed;
}
function readScopedCloudSyncPending(scopeEmail=currentAccountEmail){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return {};
  try{
    const raw = localStorage.getItem(buildScopedCloudSyncPendingKey(normalized));
    if(!raw) return {};
    const obj = JSON.parse(raw);
    return (obj && typeof obj === 'object') ? obj : {};
  }catch(_){
    return {};
  }
}
function writeScopedCloudSyncPending(scopeEmail=currentAccountEmail, payload='', info=null){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return {};
  const rawPayload = String(payload || '').trim();
  if(!rawPayload){
    try{ localStorage.removeItem(buildScopedCloudSyncPendingKey(normalized)); }catch(_){ }
    return {};
  }
  const prev = readScopedCloudSyncPending(normalized);
  const nowMs = Date.now();
  const next = {
    ...(prev && typeof prev === 'object' ? prev : {}),
    email: normalized,
    payload: rawPayload,
    firstSavedAt: Number(prev?.firstSavedAt || prev?.savedAt || nowMs) || nowMs,
    savedAt: nowMs,
  };
  if(info && typeof info === 'object'){
    for(const [k, v] of Object.entries(info)){
      if(v === undefined) delete next[k];
      else next[k] = v;
    }
  }
  try{ localStorage.setItem(buildScopedCloudSyncPendingKey(normalized), JSON.stringify(next)); }catch(_){ }
  return next;
}
function clearScopedCloudSyncPending(scopeEmail=currentAccountEmail){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return;
  try{ localStorage.removeItem(buildScopedCloudSyncPendingKey(normalized)); }catch(_){ }
}
function getScopedCloudSyncPendingPayload(scopeEmail=currentAccountEmail){
  const rec = readScopedCloudSyncPending(scopeEmail);
  return String(rec?.payload || '').trim();
}


function cloudSyncTimestampToMs(value){
  const n = Number(value || 0) || 0;
  if(!Number.isFinite(n) || n <= 0) return 0;
  return Math.floor(n < 100000000000 ? n * 1000 : n);
}
function cloudSyncPendingStoreTimestampMs(scopeEmail=currentAccountEmail, pendingRec=null, pendingStore=null){
  const rec = pendingRec && typeof pendingRec === 'object' ? pendingRec : readScopedCloudSyncPending(scopeEmail);
  let latest = Math.max(
    cloudSyncTimestampToMs(rec?.savedAt),
    cloudSyncTimestampToMs(rec?.firstSavedAt),
    cloudSyncTimestampToMs(rec?.localUpdatedAt)
  );
  try{
    if(isValidStoreShape(pendingStore)) latest = Math.max(latest, storeLatestUpdatedAtMs(pendingStore));
  }catch(_){ }
  return latest;
}
function cloudSyncPendingShouldSurviveCloudLoad(scopeEmail=currentAccountEmail, pendingRec=null, pendingStore=null, cloudUpdatedTs=0){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized || !isValidStoreShape(pendingStore)) return false;
  const payload = String((pendingRec && pendingRec.payload) || getScopedCloudSyncPendingPayload(normalized) || '').trim();
  if(!payload) return false;
  if(!hasMeaningfulStoreHistory(pendingStore) && !storeHasPendingAssistantSnapshot(pendingStore)) return false;
  const pendingAt = cloudSyncPendingStoreTimestampMs(normalized, pendingRec, pendingStore);
  const cloudAt = cloudSyncTimestampToMs(cloudUpdatedTs || currentCloudStoreUpdatedTs || 0);
  if(!cloudAt) return true;
  return pendingAt >= cloudAt - 300;
}

function cloudSyncPendingPredatesAuthoritativeCloud(scopeEmail=currentAccountEmail, pendingRec=null){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized) return false;
  const meta = readScopedStoreMeta(normalized);
  const authoritativeAt = Math.max(
    Number(meta?.cloudAuthoritativeAt || 0) || 0,
    Number(meta?.lastSyncedAt || 0) || 0
  );
  if(!authoritativeAt) return false;
  const rec = pendingRec && typeof pendingRec === 'object' ? pendingRec : readScopedCloudSyncPending(normalized);
  const pendingAt = Math.max(
    Number(rec?.savedAt || 0) || 0,
    Number(rec?.firstSavedAt || 0) || 0,
    Number(rec?.localUpdatedAt || 0) || 0
  );
  return !!(pendingAt <= 0 || pendingAt <= authoritativeAt + 1500);
}

function getCloudSyncDeviceId(){
  try{
    let id = String(localStorage.getItem(CLOUD_SYNC_DEVICE_ID_KEY) || '').trim();
    if(!id){
      const randomPart = (crypto?.randomUUID ? crypto.randomUUID() : (Date.now().toString(36) + '_' + Math.random().toString(16).slice(2)));
      id = 'dev_' + String(randomPart).replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 96);
      localStorage.setItem(CLOUD_SYNC_DEVICE_ID_KEY, id);
    }
    return id;
  }catch(_){
    return 'dev_' + Date.now().toString(36) + '_' + Math.random().toString(16).slice(2, 10);
  }
}
function makeCloudSyncOpId(opType='', sessionId=''){
  const type = String(opType || 'op').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 32);
  const sid = String(sessionId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 42);
  return [getCloudSyncDeviceId(), Date.now().toString(36), Math.random().toString(16).slice(2, 10), type, sid].filter(Boolean).join(':').slice(0, 160);
}
function markCloudSessionDeletedForSync(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  const deletedAt = Date.now();
  pendingCloudSessionDeletes.set(sid, {
    session_id: sid,
    deleted_at: deletedAt,
    device_id: getCloudSyncDeviceId(),
  });
  markLocalSessionDeleteTombstone(sid, { deleted_at: deletedAt });
  return true;
}
function clearPendingCloudSessionDeletes(){
  try{ pendingCloudSessionDeletes.clear(); }catch(_){ pendingCloudSessionDeletes = new Map(); }
}
function forgetPendingCloudSessionDeletes(sessionIds){
  const ids = new Set((Array.isArray(sessionIds) ? sessionIds : [sessionIds])
    .map(id => String(id || '').trim())
    .filter(Boolean));
  if(!ids.size) return;
  try{ ids.forEach(id => pendingCloudSessionDeletes.delete(id)); }catch(_){ }
}
function buildCloudSessionDeleteOps(sessionIds){
  const ids = Array.from(new Set((Array.isArray(sessionIds) ? sessionIds : [sessionIds])
    .map(id => String(id || '').trim())
    .filter(Boolean)));
  const tombstones = readScopedSessionDeleteTombstones(currentAccountEmail);
  return ids.map(sid => {
    const deletedAt = cloudSyncNormalizeDeletedAtMs(tombstones?.[sid]?.deleted_at) || Date.now();
    return {
      op_id: makeCloudSyncOpId('delete_session', sid),
      op_type: 'delete_session',
      device_id: getCloudSyncDeviceId(),
      session_id: sid,
      payload: { session_id: sid, deleted_at: deletedAt },
      created_at: deletedAt,
    };
  });
}
async function pushCloudSessionDeletesNow(sessionIds, opts={}){
  const ids = Array.from(new Set((Array.isArray(sessionIds) ? sessionIds : [sessionIds])
    .map(id => String(id || '').trim())
    .filter(Boolean)));
  if(!ids.length) return { ok:true, skipped:true };
  if(!currentAccountEmail || authKickRedirecting) return { ok:true, local_only:true };
  if(typeof isNavigatorOffline === 'function' && isNavigatorOffline()){
    throw new Error('当前网络离线，删除未执行');
  }
  const ops = buildCloudSessionDeleteOps(ids);
  if(!ops.length) return { ok:true, skipped:true };
  const statusText = String(opts?.statusText || '').trim();
  if(statusText && typeof setStatus === 'function') setStatus(statusText);
  const ctl = new AbortController();
  const timeoutMs = Math.max(CLOUD_SYNC_FETCH_TIMEOUT_MS, computeWeakFetchTimeoutMs('cloud_post'));
  const timeoutId = setTimeout(()=>{
    try{ ctl.abort('cloud_delete_timeout'); }catch(_){ }
  }, timeoutMs);
  let res = null;
  let data = {};
  try{
    res = await fetch('/api3/chat-sync/push', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({
        protocol:'ops_v3_incremental',
        protocol_version:CLOUD_SYNC_PROTOCOL_VERSION,
        device_id:getCloudSyncDeviceId(),
        base_revision:Number(currentCloudStoreRevision || 0) || 0,
        client_store_updated_at:storeLatestUpdatedAtMs(store),
        ops,
      }),
      cache:'no-store',
      credentials:'same-origin',
      signal: ctl.signal,
    });
    data = await res.json().catch(()=>({}));
  }finally{
    try{ clearTimeout(timeoutId); }catch(_){ }
  }
  if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')){
    throw new Error(data?.message || data?.error || '当前登录已失效');
  }
  if(res.status === 404 || data?.sync_protocol === 'unsupported') throw new Error(data?.error || 'chat_sync_push_unavailable');
  if(!res.ok || data?.ok === false) throw new Error(data?.message || data?.error || ('HTTP ' + res.status));
  updateAccountChatLimits(data?.limits);
  const updatedTs = Number(data?.updated_ts || 0) || 0;
  const revision = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
  if(updatedTs > 0) currentCloudStoreUpdatedTs = updatedTs;
  if(revision > 0) currentCloudStoreRevision = revision;
  try{ receiveCloudSessionDeleteTombstones(data, currentAccountEmail); }catch(_){ }
  for(const sid of ids){
    markLocalSessionDeleteTombstone(sid, { server_revision:Number(data?.server_revision ?? data?.revision ?? 0) || 0 });
  }
  if(data?.store && isValidStoreShape(data.store)){
    try{ cloudSyncRehydrateStoreBodiesInPlace(data.store); }catch(_){ }
    try{ applySessionDeleteTombstonesToStore(data.store, currentAccountEmail, extractCloudSessionDeleteTombstones(data)); }catch(_){ }
    try{
      const serverBaseline = buildPersistableStorePayload(data.store);
      if(serverBaseline?.payload) lastCloudSyncedPayload = String(serverBaseline.payload || '');
    }catch(_){ }
  }
  forgetPendingCloudSessionDeletes(ids);
  return { ok:true, data };
}
function buildPendingCloudDeleteOps(){
  const ops = [];
  const pendingById = new Map();
  for(const row of pendingCloudSessionDeletes.values()){
    const sid = String(row?.session_id || '').trim();
    if(sid) pendingById.set(sid, row);
  }
  for(const row of Object.values(readScopedSessionDeleteTombstones(currentAccountEmail))){
    const sid = String(row?.session_id || '').trim();
    if(!sid || Number(row?.server_revision || 0) > 0 || pendingById.has(sid)) continue;
    pendingById.set(sid, row);
  }
  const rows = Array.from(pendingById.values());
  for(const row of rows){
    const sid = String(row?.session_id || '').trim();
    if(!sid) continue;
    ops.push({
      op_id: makeCloudSyncOpId('delete_session', sid),
      op_type: 'delete_session',
      device_id: getCloudSyncDeviceId(),
      session_id: sid,
      payload: { session_id: sid, deleted_at: Number(row?.deleted_at || Date.now()) || Date.now() },
      created_at: Date.now(),
    });
  }
  return ops;
}

async function deleteSessionsEverywhere(sessionIds, opts={}){
  const ids = Array.from(new Set((Array.isArray(sessionIds) ? sessionIds : [sessionIds])
    .map(id => String(id || '').trim())
    .filter(Boolean)));
  if(!ids.length) return { ok:true, skipped:true, cloud_synced:true };

  const stopPromises = [];
  for(const sid of ids){
    markCloudSessionDeletedForSync(sid);
    try{ clearActiveCloudSessionHydrateTimer(sid); }catch(_){ }
    try{ if(typeof cancelSessionCloudHydration === 'function') cancelSessionCloudHydration(sid); }catch(_){ }
    try{
      if(typeof stopStreamingForAction === 'function'){
        stopPromises.push(Promise.resolve(stopStreamingForAction('delete_session', sid, { preserveDraft:false })));
      }
    }catch(_){ }
  }

  for(const sid of ids){
    if(store?.sessions && Object.prototype.hasOwnProperty.call(store.sessions, sid)) delete store.sessions[sid];
  }
  try{ normalizeStoreActiveIdInPlace(store); }catch(_){ }
  saveStore();

  let cloudResult = null;
  let cloudError = null;
  try{
    cloudResult = await pushCloudSessionDeletesNow(ids, { statusText:String(opts?.statusText || '正在删除会话…') });
  }catch(err){
    cloudError = err;
    try{ requestCloudMessageRealtimeFlush('delete_session_retry', { delayMs:0 }); }catch(_){ }
  }

  try{ await Promise.allSettled(stopPromises); }catch(_){ }
  for(const sid of ids){
    try{ clearPendingAssistantSnapshot(sid, { immediate:false }); }catch(_){ }
    try{ if(typeof clearSessionStreamState === 'function') clearSessionStreamState(sid); }catch(_){ }
    try{ delete sessionRuntime[sid]; }catch(_){ }
    try{ delete streamControllers[sid]; }catch(_){ }
    try{ delete streamPromises[sid]; }catch(_){ }
    try{ delete streamAbortReasons[sid]; }catch(_){ }
  }

  if(cloudError){
    try{ setStatus('会话已在本地删除，云端删除将在网络恢复后重试'); }catch(_){ }
  }
  return {
    ok:true,
    deleted_ids:ids,
    cloud_synced:!cloudError && !cloudResult?.local_only,
    cloud_pending:!!cloudError,
    error:cloudError ? String(cloudError?.message || cloudError) : '',
  };
}
function cloudSyncStableStringify(value){
  try{ return JSON.stringify(value === undefined ? null : value); }catch(_){ return ''; }
}


const CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS = 6000;
const CLOUD_SYNC_ARTIFACT_TEXT_FIELD_MAX_CHARS = 3000;
const CLOUD_SYNC_BODY_CHUNK_TEXT_CHARS = 24000;
const CLOUD_SYNC_BODY_CHUNK_TRIGGER_CHARS = 36000;
const CLOUD_SYNC_BODY_PREVIEW_CHARS = 6000;

function cloudSyncCompactLargeText(value, limit = CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS, label = '内容'){
  const raw = String(value ?? '');
  const max = Math.max(800, Number(limit || 0) || CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS);
  if(raw.length <= max) return raw;
  const headLen = Math.max(400, Math.floor(max * 0.58));
  const tailLen = Math.max(240, max - headLen - 180);
  const head = raw.slice(0, headLen).trimEnd();
  const tail = raw.slice(Math.max(0, raw.length - tailLen)).trimStart();
  return `${head}\n\n…（云端同步已精简${label}，完整内容仍保留在本机会话与生成文件中）…\n\n${tail}`;
}

function cloudSyncClone(value){
  try{ return JSON.parse(JSON.stringify(value)); }catch(_){ return value && typeof value === 'object' ? { ...value } : value; }
}


function cloudSyncBuildChunkedBodyPreviewText(value, limit=CLOUD_SYNC_BODY_PREVIEW_CHARS){
  const raw = String(value ?? '');
  const max = Math.max(1200, Number(limit || 0) || CLOUD_SYNC_BODY_PREVIEW_CHARS);
  if(raw.length <= max) return raw;
  const headLen = Math.max(700, Math.floor(max * 0.62));
  const tailLen = Math.max(360, max - headLen - 160);
  const head = raw.slice(0, headLen).trimEnd();
  const tail = raw.slice(Math.max(0, raw.length - tailLen)).trimStart();
  return `${head}\n\n…（云端正文已分块保存，正在恢复完整内容）…\n\n${tail}`;
}

function cloudSyncTextHashForChunks(text){
  const raw = String(text ?? '');
  let h1 = 0x811c9dc5;
  let h2 = 0x27d4eb2d;
  for(let i = 0; i < raw.length; i++){
    const c = raw.charCodeAt(i);
    h1 ^= c;
    h1 = Math.imul(h1, 16777619) >>> 0;
    h2 = Math.imul(h2 ^ c, 2246822519) >>> 0;
  }
  return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0') + ':' + raw.length).slice(0, 80);
}

function cloudSyncSplitTextChunks(text, chunkChars=CLOUD_SYNC_BODY_CHUNK_TEXT_CHARS){
  const raw = String(text ?? '');
  const size = Math.max(8000, Number(chunkChars || 0) || CLOUD_SYNC_BODY_CHUNK_TEXT_CHARS);
  const chunks = [];
  for(let i = 0; i < raw.length; i += size) chunks.push(raw.slice(i, i + size));
  return chunks.length ? chunks : [''];
}

function cloudSyncMessageBodyState(msg, field='content'){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return null;
  const body = m.__cloud_sync_body && typeof m.__cloud_sync_body === 'object' ? m.__cloud_sync_body : null;
  if(!body) return null;
  const key = String(field || 'content').trim() || 'content';
  const state = body[key] && typeof body[key] === 'object' ? body[key] : (key === 'content' && body.field ? body : null);
  return state && typeof state === 'object' ? state : null;
}

function cloudSyncRehydrateMessageBodyInPlace(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return false;
  let changed = false;
  const body = m.__cloud_sync_body && typeof m.__cloud_sync_body === 'object' ? m.__cloud_sync_body : null;
  if(!body) return false;
  for(const [fieldKey, stateValue] of Object.entries(body)){
    if(!stateValue || typeof stateValue !== 'object') continue;
    const field = String(stateValue.field || fieldKey || 'content').trim() || 'content';
    if(field !== 'content' && field !== 'reasoning' && field !== 'process') continue;
    const chunks = Array.isArray(stateValue.chunks) ? stateValue.chunks : [];
    const chunkCount = Math.max(0, Number(stateValue.chunk_count || stateValue.chunkCount || chunks.length || 0) || 0);
    if(!chunkCount || chunks.length < chunkCount) continue;
    const ready = chunks.slice(0, chunkCount).every(v => typeof v === 'string');
    if(!ready) continue;
    const full = chunks.slice(0, chunkCount).join('');
    const expectedLength = Number(stateValue.length || stateValue.text_length || stateValue.textLength || 0) || 0;
    if(expectedLength > 0 && full.length !== expectedLength) continue;
    const expectedHash = String(stateValue.hash || stateValue.text_hash || stateValue.textHash || '').trim();
    if(expectedHash && expectedHash !== cloudSyncTextHashForChunks(full)) continue;
    if(m[field] !== full){
      m[field] = full;
      changed = true;
    }
    if(stateValue.complete !== true){
      stateValue.complete = true;
      changed = true;
    }
  }
  return changed;
}

function cloudSyncRehydrateSessionBodiesInPlace(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s || !Array.isArray(s.messages)) return false;
  let changed = false;
  for(const msg of s.messages){
    if(cloudSyncRehydrateMessageBodyInPlace(msg)) changed = true;
  }
  return changed;
}

function cloudSyncRehydrateStoreBodiesInPlace(candidate){
  if(!isValidStoreShape(candidate)) return false;
  let changed = false;
  for(const session of Object.values(candidate.sessions || {})){
    if(cloudSyncRehydrateSessionBodiesInPlace(session)) changed = true;
  }
  return changed;
}

function cloudSyncMessageIdentityValueForChunks(msg, sessionId='', indexHint=0){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return '';
  let identity = '';
  try{ identity = (typeof messageStableClientIdentity === 'function') ? messageStableClientIdentity(m) : ''; }catch(_){ identity = ''; }
  if(!identity){
    const role = String(m.role || 'msg').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 24) || 'msg';
    const created = Number(m.created_at_ms || m.createdAtMs || m.createdAt || m.created_at || Date.now()) || Date.now();
    const sid = String(sessionId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 48);
    const content = typeof m.content === 'string' ? m.content : '';
    const sig = cloudSyncTextHashForChunks(content || cloudSyncStableStringify(m)).replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 40);
    identity = ['cloudmsg', sid, role, created.toString(36), indexHint, sig].filter(v => String(v || '').trim()).join('_').slice(0, 220);
    m._client_msg_id = identity;
  }
  return String(identity || '').slice(0, 220);
}

function cloudSyncPrepareChunkedMessageForTransport(msg, sessionId='', indexHint=0){
  const m = cloudSyncClone(msg);
  if(!m || typeof m !== 'object') return { message:m, chunkOps:[] };
  try{ cloudSyncEnsureMessageSyncFields(m, sessionId, ''); }catch(_){ }
  const rawContent = typeof m.content === 'string' ? String(m.content) : '';
  if(rawContent.length < CLOUD_SYNC_BODY_CHUNK_TRIGGER_CHARS) return { message:m, chunkOps:[] };
  const identity = cloudSyncMessageIdentityValueForChunks(m, sessionId, indexHint);
  const chunks = cloudSyncSplitTextChunks(rawContent);
  const textHash = cloudSyncTextHashForChunks(rawContent);
  const preview = cloudSyncBuildChunkedBodyPreviewText(rawContent, CLOUD_SYNC_BODY_PREVIEW_CHARS);
  m.content = preview;
  const body = m.__cloud_sync_body && typeof m.__cloud_sync_body === 'object' ? cloudSyncClone(m.__cloud_sync_body) : {};
  body.content = {
    version: 1,
    field: 'content',
    mode: 'chunks',
    complete: false,
    length: rawContent.length,
    hash: textHash,
    chunk_count: chunks.length,
    received_count: 0,
  };
  m.__cloud_sync_body = body;
  m.__cloud_sync_body_preview = true;
  const chunkOps = chunks.map((chunkText, idx) => ({
    op_id: makeCloudSyncOpId('message_body_chunk', sessionId),
    op_type: 'message_body_chunk',
    device_id: getCloudSyncDeviceId(),
    session_id: String(sessionId || '').trim(),
    payload: {
      message_identity: identity,
      field: 'content',
      chunk_index: idx,
      chunk_count: chunks.length,
      chunk_text: chunkText,
      text_hash: textHash,
      text_length: rawContent.length,
    },
    created_at: Date.now(),
  }));
  return { message:m, chunkOps };
}

function cloudSyncBuildMessageBodyChunkOps(sessionId, message, indexHint=0, field='content'){
  const sid = String(sessionId || '').trim();
  const m = cloudSyncClone(message);
  if(!sid || !m || typeof m !== 'object') return [];
  const safeField = ['content', 'reasoning', 'process'].includes(String(field || '').trim()) ? String(field || '').trim() : 'content';
  const rawContent = typeof m[safeField] === 'string' ? String(m[safeField]) : '';
  if(!rawContent) return [];
  try{ cloudSyncEnsureMessageSyncFields(m, sid, ''); }catch(_){ }
  const identity = cloudSyncMessageIdentityValueForChunks(m, sid, indexHint);
  if(!identity) return [];
  const chunks = cloudSyncSplitTextChunks(rawContent);
  const textHash = cloudSyncTextHashForChunks(rawContent);
  const seed = cloudSyncSlimMessageForTransport(m);
  if(seed && typeof seed === 'object' && typeof seed.content === 'string'){
    seed.content = cloudSyncBuildChunkedBodyPreviewText(rawContent, CLOUD_SYNC_BODY_PREVIEW_CHARS);
  }
  return chunks.map((chunkText, idx) => ({
    op_id: makeCloudSyncOpId('message_body_chunk', sid),
    op_type: 'message_body_chunk',
    device_id: getCloudSyncDeviceId(),
    session_id: sid,
    payload: {
      message_identity: identity,
      field: safeField,
      chunk_index: idx,
      chunk_count: chunks.length,
      chunk_text: chunkText,
      text_hash: textHash,
      text_length: rawContent.length,
      ...(idx === 0 && seed ? { message_seed: seed } : {}),
    },
    created_at: Date.now(),
  }));
}

function cloudSyncApplyBodyChunkToSession(session, payload){
  const s = session && typeof session === 'object' ? session : null;
  const p = payload && typeof payload === 'object' ? payload : {};
  if(!s) return false;
  const identity = String(p.message_identity || p.messageIdentity || '').trim();
  const field = String(p.field || 'content').trim() || 'content';
  const chunkIndex = Number(p.chunk_index ?? p.chunkIndex);
  const chunkCount = Number(p.chunk_count ?? p.chunkCount);
  const text = String(p.chunk_text ?? p.text ?? '');
  if(!identity || !Number.isFinite(chunkIndex) || chunkIndex < 0 || !Number.isFinite(chunkCount) || chunkCount <= 0 || chunkIndex >= chunkCount) return false;
  if(!Array.isArray(s.messages)) s.messages = [];
  let idx = s.messages.findIndex(m => m && typeof m === 'object' && cloudSyncMessageIdentityKey(m) === ('client:' + identity));
  if(idx < 0) idx = s.messages.findIndex(m => m && typeof m === 'object' && String(m._client_msg_id || m.client_msg_id || m.clientMessageId || '').trim() === identity);
  if(idx < 0) return false;
  const msg = s.messages[idx] && typeof s.messages[idx] === 'object' ? s.messages[idx] : {};
  const body = msg.__cloud_sync_body && typeof msg.__cloud_sync_body === 'object' ? msg.__cloud_sync_body : {};
  const state = body[field] && typeof body[field] === 'object' ? body[field] : {
    version: 1,
    field,
    mode: 'chunks',
    complete: false,
    length: Number(p.text_length || p.textLength || 0) || 0,
    hash: String(p.text_hash || p.textHash || '').trim(),
    chunk_count: chunkCount,
    received_count: 0,
    chunks: [],
  };
  const chunks = Array.isArray(state.chunks) ? state.chunks.slice() : [];
  const before = chunks[chunkIndex];
  chunks[chunkIndex] = text;
  state.chunks = chunks;
  state.chunk_count = chunkCount;
  state.length = Number(p.text_length || p.textLength || state.length || 0) || 0;
  state.hash = String(p.text_hash || p.textHash || state.hash || '').trim();
  let received = 0;
  for(let i = 0; i < chunkCount; i++) if(typeof chunks[i] === 'string') received += 1;
  state.received_count = received;
  state.complete = received >= chunkCount;
  body[field] = state;
  msg.__cloud_sync_body = body;
  s.messages[idx] = msg;
  const rehydrated = cloudSyncRehydrateMessageBodyInPlace(msg);
  return before !== text || rehydrated;
}

function cloudSyncSlimArtifactRecordForTransport(file){
  const f = cloudSyncClone(file);
  if(!f || typeof f !== 'object') return f;
  const largeKeys = [
    'content','text','source','raw','data','data_url','dataUrl','full_text','fullText',
    'preview_text','previewText','code','html','css','javascript','diff','patch',
    'exact_old','exactOld','replacement','old_text','oldText','new_text','newText'
  ];
  for(const key of largeKeys){
    if(typeof f[key] === 'string' && f[key].length > CLOUD_SYNC_ARTIFACT_TEXT_FIELD_MAX_CHARS){
      f[key] = cloudSyncCompactLargeText(f[key], CLOUD_SYNC_ARTIFACT_TEXT_FIELD_MAX_CHARS, '文件记录字段');
    }
  }
  for(const auditKey of ['edit_audit','file_edit_audit','editAudit','fileEditAudit']){
    const audit = f[auditKey];
    if(audit && typeof audit === 'object'){
      const nextAudit = cloudSyncClone(audit);
      for(const key of ['diff','patch','diff_summary','diffSummary','exact_old','exactOld','replacement']){
        if(typeof nextAudit[key] === 'string' && nextAudit[key].length > CLOUD_SYNC_ARTIFACT_TEXT_FIELD_MAX_CHARS){
          nextAudit[key] = cloudSyncCompactLargeText(nextAudit[key], CLOUD_SYNC_ARTIFACT_TEXT_FIELD_MAX_CHARS, '文件修改记录');
        }
      }
      f[auditKey] = nextAudit;
    }
  }
  return f;
}

function cloudSyncSlimMessageForTransport(msg){
  const m = cloudSyncClone(msg);
  if(!m || typeof m !== 'object') return m;
  try{ cloudSyncEnsureMessageSyncFields(m, '', ''); }catch(_){ }
  for(const key of ['fileProcessText','file_process_text','draftProcessText']){
    if(typeof m[key] === 'string' && m[key].length > CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS){
      m[key] = cloudSyncCompactLargeText(m[key], CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS, '文件过程正文');
    }
  }
  if(typeof m.fileProcessText === 'string' && typeof m.file_process_text === 'string' && m.fileProcessText === m.file_process_text){
    delete m.file_process_text;
  }
  for(const key of ['generatedFiles','generated_files','files']){
    if(Array.isArray(m[key])) m[key] = m[key].map(cloudSyncSlimArtifactRecordForTransport).filter(Boolean);
  }
  const snapshot = m.pendingAssistantSnapshot || m.pending_assistant_snapshot;
  if(snapshot && typeof snapshot === 'object'){
    const nextSnapshot = cloudSyncClone(snapshot);
    if(typeof nextSnapshot.process === 'string' && nextSnapshot.process.length > CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS){
      nextSnapshot.process = cloudSyncCompactLargeText(nextSnapshot.process, CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS, '文件过程正文');
    }
    if(m.pendingAssistantSnapshot) m.pendingAssistantSnapshot = nextSnapshot;
    if(m.pending_assistant_snapshot) m.pending_assistant_snapshot = nextSnapshot;
  }
  return m;
}

function cloudSyncSlimSessionForTransport(session){
  if(!session || typeof session !== 'object') return session;
  const s = cloudSyncClone(session);
  try{ cloudSyncEnsureConversationSyncFields(s, s.id || ''); }catch(_){ }
  try{ cloudSyncAttachRunRecoveryForTransport(s); }catch(_){ }
  for(const key of [
    'pendingJobId','pendingJobCursor','pendingJobTurnKey',
    'pendingAssistantDraft','pendingAssistantStatus','pendingAssistantProcess','pendingAssistantStreaming',
    'pendingAssistantFiles','pendingAssistantImageReplies','pendingAssistantWeatherPayload','pendingAssistantReasoning',
    'pendingAssistantReasoningMeta','pendingAssistantSources','pendingAssistantRtStartAt','pendingAssistantRtFinalMs',
    'pendingAssistantUpdatedAt','pendingAssistantTurnKey','pendingAssistantUserCreatedAtMs',
    'pending_job_id','pending_job_cursor','pending_job_turn_key',
    'pending_assistant_draft','pending_assistant_status','pending_assistant_process','pending_assistant_streaming',
    'pending_assistant_files','pending_assistant_image_replies','pending_assistant_weather_payload','pending_assistant_reasoning',
    'pending_assistant_reasoning_meta','pending_assistant_sources','pending_assistant_rt_start_at','pending_assistant_rt_final_ms',
    'pending_assistant_updated_at','pending_assistant_turn_key','pending_assistant_user_created_at_ms',
    'composerDraft','composerDraftUpdatedAt','composerDraftClearedAt','composerDraftSentClearAt','composerDraftClearReason',
    'composerAttachmentDraft','composerAttachmentDraftUpdatedAt','composerQuoteDraft',
    'composer_draft','composer_draft_updated_at','composer_draft_cleared_at','composer_draft_sent_clear_at','composer_draft_clear_reason',
    'composer_attachment_draft','composer_attachment_draft_updated_at','composer_quote_draft'
  ]){
    try{ delete s[key]; }catch(_){ }
  }
  if(Array.isArray(s.messages)) s.messages = s.messages.map(cloudSyncSlimMessageForTransport).filter(Boolean);
  for(const key of ['pendingAssistantProcess','pending_assistant_process']){
    if(typeof s[key] === 'string' && s[key].length > CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS){
      s[key] = cloudSyncCompactLargeText(s[key], CLOUD_SYNC_FILE_PROCESS_TEXT_MAX_CHARS, '文件过程正文');
    }
  }
  for(const key of ['pendingAssistantFiles','pending_assistant_files','generatedFiles','generated_files']){
    if(Array.isArray(s[key])) s[key] = s[key].map(cloudSyncSlimArtifactRecordForTransport).filter(Boolean);
  }
  return s;
}
function parseCloudSyncPayload(payload){
  try{
    const obj = JSON.parse(String(payload || '').trim() || 'null');
    if(isValidStoreShape(obj)){
      try{ cloudSyncRehydrateStoreBodiesInPlace(obj); }catch(_){ }
      return obj;
    }
    return null;
  }catch(_){
    return null;
  }
}
function cloudSyncSessionChanged(prevSession, nextSession){
  return cloudSyncStableStringify(cloudSyncSlimSessionForTransport(prevSession) || null) !== cloudSyncStableStringify(cloudSyncSlimSessionForTransport(nextSession) || null);
}

function cloudSyncMessageFingerprint(msg){
  return cloudSyncStableStringify(cloudSyncSlimMessageForTransport(msg) || null);
}
function cloudSyncMessageListHasSamePrefix(prevMessages, nextMessages){
  const prev = Array.isArray(prevMessages) ? prevMessages : [];
  const next = Array.isArray(nextMessages) ? nextMessages : [];
  if(next.length < prev.length) return false;
  for(let i = 0; i < prev.length; i++){
    if(cloudSyncMessageFingerprint(prev[i]) !== cloudSyncMessageFingerprint(next[i])) return false;
  }
  return true;
}
function cloudSyncMessageIdentityKey(msg){
  const id = messageStableClientIdentity(msg);
  return id ? ('client:' + id) : '';
}
function cloudSyncMessageBaseGuard(messages){
  const rows = Array.isArray(messages) ? messages : [];
  const last = rows.length ? rows[rows.length - 1] : null;
  return {
    base_message_count: rows.length,
    base_message_fingerprint: last ? cloudSyncMessageFingerprint(last) : '',
    base_message_identity: last ? cloudSyncMessageIdentityKey(last) : '',
  };
}

function cloudSyncMessageBaseGuardMatchesSession(session, payload, opts={}){
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  const rawCount = payload?.base_message_count;
  if(rawCount === undefined || rawCount === null || rawCount === '') return true;
  const baseCount = Math.max(0, Number(rawCount || 0) || 0);
  if(rows.length < baseCount) return false;
  if(opts?.strictLength === true && rows.length !== baseCount) return false;
  if(baseCount <= 0) return true;
  const last = rows[baseCount - 1];
  const expectedIdentity = String(payload?.base_message_identity || '').trim();
  if(expectedIdentity && cloudSyncMessageIdentityKey(last) !== expectedIdentity) return false;
  const expectedFingerprint = String(payload?.base_message_fingerprint || '').trim();
  if(expectedFingerprint && cloudSyncMessageFingerprint(last) !== expectedFingerprint) return false;
  return true;
}

function richUserAttachmentClone(value){
  try{ return JSON.parse(JSON.stringify(value)); }catch(_){ return value && typeof value === 'object' ? { ...value } : value; }
}
function richUserAttachmentTextKey(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  if(String(m.role || '').toLowerCase() !== 'user') return '';
  const c = m.content;
  let text = '';
  if(typeof c === 'string') text = c;
  else if(Array.isArray(c)) text = c.filter(p => p && p.type === 'text').map(p => String(p.text || '')).join('\n');
  else if(c && typeof c === 'object') text = String(c.text || c.filename || c.name || '').trim();
  text = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 260);
  const t = Number(m.created_at_ms || m.createdAtMs || m.createdAt || m.created_at || 0) || 0;
  return text ? ['usertext', Math.floor(t / 1000), text].join(':') : '';
}
function userStructuredImageParts(msg){
  const c = msg && typeof msg === 'object' ? msg.content : null;
  return Array.isArray(c) ? c.filter(p => p && p.type === 'image_url') : [];
}
function userFileAttachmentRows(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  const rows = [];
  for(const key of ['file_attachments','attachments','_composer_file_attachments','files']){
    if(Array.isArray(m[key])) rows.push(...m[key]);
  }
  const c = m.content;
  if(c && typeof c === 'object' && !Array.isArray(c) && c._kind === 'file') rows.push(c);
  return rows.filter(Boolean);
}
function userMessageRichAttachmentScore(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').toLowerCase() !== 'user') return 0;
  let score = 0;
  const c = m.content;
  if(Array.isArray(c)){
    for(const part of c){
      if(!part || part.type !== 'image_url') continue;
      score += 4;
      const values = [part.image_url?.url, part.preview_url, part.view_url, part.download_url, part.persisted_url, part.server_url, part.storage_ref, part.model_storage_ref, part.file_library_id, part.library_file_id];
      if(values.some(v => String(v || '').trim())) score += 2;
    }
  }else if(c && typeof c === 'object'){
    if(c._kind === 'file') score += 6;
    if(c._kind === 'image') score += 6;
  }
  const files = userFileAttachmentRows(m);
  if(files.length) score += files.length * 5;
  return score;
}
function messageHasSameUserAttachmentIdentity(a, b){
  const ak = cloudSyncMessageIdentityKey(a);
  const bk = cloudSyncMessageIdentityKey(b);
  if(ak && bk && ak === bk) return true;
  const at = richUserAttachmentTextKey(a);
  const bt = richUserAttachmentTextKey(b);
  return !!(at && bt && at === bt);
}

function cloudSyncEnsureMessageSyncFields(msg, sessionId='', mode=''){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return m;
  const normalizedMode = normalizeConversationSyncMode(mode || m.conversationMode || m.conversation_mode || '');
  let identity = '';
  try{ identity = messageStableClientIdentity(m); }catch(_){ identity = ''; }
  if(!identity){
    const role = String(m.role || 'msg').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 24) || 'msg';
    const created = Number(m.created_at_ms || m.createdAtMs || m.createdAt || m.created_at || Date.now()) || Date.now();
    const sid = String(sessionId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 48);
    const sig = cloudSyncTextHashForChunks(cloudSyncStableStringify({ role:m.role || '', content:m.content || '' })).replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 40);
    identity = ['msg', sid, role, created.toString(36), sig].filter(Boolean).join('_').slice(0, 220);
    m._client_msg_id = identity;
  }
  const localId = String(m.localId || m.local_id || m.messageLocalId || m.message_local_id || identity || '').trim();
  if(localId){
    m.localId = localId;
    m.local_id = localId;
    m.messageLocalId = localId;
    m.message_local_id = localId;
  }
  const opPrefix = String(m.role || '').toLowerCase() === 'assistant' ? 'append_assistant_message' : 'append_message';
  const opId = String(m.opId || m.op_id || m.messageOpId || m.message_op_id || makeCloudSyncOpId(opPrefix, localId || identity || sessionId)).trim();
  if(opId){
    m.opId = opId;
    m.op_id = opId;
    m.messageOpId = opId;
    m.message_op_id = opId;
  }
  m.conversationMode = normalizedMode;
  m.conversation_mode = normalizedMode;
  const statusRaw = String(m.syncStatus || m.sync_status || m.messageRecovery?.status || '').trim().toLowerCase();
  const serverVersion = Number(m.serverVersion || m.server_version || m.messageRecovery?.server_version || 0) || 0;
  const role = String(m.role || '').toLowerCase();
  const status = ['pending','sending','streaming','complete','sent','failed','failed_retryable','server_owned_inflight'].includes(statusRaw)
    ? statusRaw
    : (serverVersion > 0 ? (role === 'assistant' ? 'complete' : 'sent') : (role === 'assistant' ? 'pending' : 'sending'));
  m.syncStatus = status;
  m.sync_status = status;
  if(serverVersion > 0){
    m.serverVersion = serverVersion;
    m.server_version = serverVersion;
  }
  m.messageRecovery = {
    ...(m.messageRecovery && typeof m.messageRecovery === 'object' ? m.messageRecovery : {}),
    mode: normalizedMode,
    local_id: localId || identity,
    op_id: opId,
    server_version: serverVersion,
    status,
    created_at: Number(m.created_at_ms || m.createdAtMs || m.created_at || m.createdAt || Date.now()) || Date.now(),
  };
  return m;
}

function cloudSyncMessageHasProtectedLocalState(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return false;
  const status = String(m.syncStatus || m.sync_status || m.messageRecovery?.status || '').trim().toLowerCase();
  return ['pending','sending','streaming','failed_retryable','server_owned_inflight'].includes(status);
}

function mergeMessageSyncRecoveryFields(targetMsg, sourceMsg){
  const target = targetMsg && typeof targetMsg === 'object' ? targetMsg : null;
  const source = sourceMsg && typeof sourceMsg === 'object' ? sourceMsg : null;
  if(!target || !source) return false;
  const before = cloudSyncStableStringify({
    localId: target.localId,
    opId: target.opId,
    syncStatus: target.syncStatus,
    serverVersion: target.serverVersion,
    messageRecovery: target.messageRecovery,
  });
  const targetVersion = Number(target.serverVersion || target.server_version || target.messageRecovery?.server_version || 0) || 0;
  const sourceVersion = Number(source.serverVersion || source.server_version || source.messageRecovery?.server_version || 0) || 0;
  for(const [camel, snake] of [['localId','local_id'], ['messageLocalId','message_local_id'], ['opId','op_id'], ['messageOpId','message_op_id']]){
    const value = source[camel] ?? source[snake];
    if((target[camel] === undefined || target[camel] === null || target[camel] === '') && value !== undefined && value !== null && value !== ''){
      target[camel] = value;
      target[snake] = value;
    }
  }
  if(sourceVersion > targetVersion){
    target.serverVersion = sourceVersion;
    target.server_version = sourceVersion;
    const role = String(target.role || source.role || '').toLowerCase();
    if(!cloudSyncMessageHasProtectedLocalState(target) || ['pending','sending'].includes(String(target.syncStatus || target.sync_status || '').toLowerCase())){
      target.syncStatus = role === 'assistant' ? 'complete' : 'sent';
      target.sync_status = target.syncStatus;
    }
  }else if(cloudSyncMessageHasProtectedLocalState(target)){
    // 本地刚发/刚流式的状态优先，旧云端消息不能把它降级。
  }else if(source.syncStatus || source.sync_status){
    target.syncStatus = source.syncStatus || source.sync_status;
    target.sync_status = target.syncStatus;
  }
  if(source.messageRecovery && typeof source.messageRecovery === 'object'){
    const targetRecoveryVersion = Number(target.messageRecovery?.server_version || 0) || 0;
    const sourceRecoveryVersion = Number(source.messageRecovery.server_version || 0) || 0;
    if(!target.messageRecovery || sourceRecoveryVersion >= targetRecoveryVersion){
      target.messageRecovery = { ...(target.messageRecovery || {}), ...source.messageRecovery };
    }
  }
  cloudSyncEnsureMessageSyncFields(target, '', target.conversationMode || source.conversationMode || '');
  return before !== cloudSyncStableStringify({
    localId: target.localId,
    opId: target.opId,
    syncStatus: target.syncStatus,
    serverVersion: target.serverVersion,
    messageRecovery: target.messageRecovery,
  });
}

function mergeRichUserAttachmentMessage(targetMsg, sourceMsg){
  const target = targetMsg && typeof targetMsg === 'object' ? targetMsg : null;
  const source = sourceMsg && typeof sourceMsg === 'object' ? sourceMsg : null;
  if(!target || !source) return false;
  if(String(target.role || '').toLowerCase() !== 'user' || String(source.role || '').toLowerCase() !== 'user') return false;
  if(!messageHasSameUserAttachmentIdentity(target, source)) return false;
  const sourceScore = userMessageRichAttachmentScore(source);
  if(sourceScore <= 0) return false;
  let changed = false;
  const targetScore = userMessageRichAttachmentScore(target);
  const sourceImages = userStructuredImageParts(source);
  const targetImages = userStructuredImageParts(target);
  if(sourceImages.length && (sourceImages.length > targetImages.length || sourceScore > targetScore)){
    target.content = richUserAttachmentClone(source.content);
    changed = true;
  }else if(source.content && typeof source.content === 'object' && !Array.isArray(source.content) && sourceScore > targetScore){
    target.content = richUserAttachmentClone(source.content);
    changed = true;
  }
  for(const key of ['file_attachments','attachments','_composer_file_attachments']){
    const src = Array.isArray(source[key]) ? source[key] : [];
    const dst = Array.isArray(target[key]) ? target[key] : [];
    if(src.length && (!dst.length || src.length > dst.length)){
      target[key] = richUserAttachmentClone(src);
      changed = true;
    }
  }
  if(mergeMessageSyncRecoveryFields(target, source)) changed = true;
  return changed;
}
function mergeRichUserAttachmentsAcrossMessageLists(targetMessages, sourceMessages){
  const target = Array.isArray(targetMessages) ? richUserAttachmentClone(targetMessages) : [];
  const source = Array.isArray(sourceMessages) ? sourceMessages : [];
  if(!target.length || !source.length) return target;
  const byIdentity = new Map();
  const byText = new Map();
  for(const msg of source){
    if(!msg || typeof msg !== 'object' || String(msg.role || '').toLowerCase() !== 'user') continue;
    if(userMessageRichAttachmentScore(msg) <= 0) continue;
    const ik = cloudSyncMessageIdentityKey(msg);
    if(ik && !byIdentity.has(ik)) byIdentity.set(ik, msg);
    const tk = richUserAttachmentTextKey(msg);
    if(tk && !byText.has(tk)) byText.set(tk, msg);
  }
  for(const msg of target){
    if(!msg || typeof msg !== 'object' || String(msg.role || '').toLowerCase() !== 'user') continue;
    const src = byIdentity.get(cloudSyncMessageIdentityKey(msg)) || byText.get(richUserAttachmentTextKey(msg));
    if(src) mergeRichUserAttachmentMessage(msg, src);
  }
  return target;
}
function preserveSessionUserAttachmentsFromSource(targetSession, sourceSession){
  const target = targetSession && typeof targetSession === 'object' ? targetSession : null;
  const source = sourceSession && typeof sourceSession === 'object' ? sourceSession : null;
  if(!target || !source) return false;
  const before = cloudSyncStableStringify(target.messages || []);
  target.messages = mergeRichUserAttachmentsAcrossMessageLists(target.messages || [], source.messages || []);
  return before !== cloudSyncStableStringify(target.messages || []);
}
function cloudSyncMergeMessageLists(existingMessages, incomingMessages){
  const existing = Array.isArray(existingMessages) ? JSON.parse(JSON.stringify(existingMessages)) : [];
  const incoming = Array.isArray(incomingMessages) ? JSON.parse(JSON.stringify(incomingMessages)) : [];
  if(!existing.length) return incoming;
  if(!incoming.length) return existing;
  if(cloudSyncMessageListHasSamePrefix(existing, incoming)) return mergeRichUserAttachmentsAcrossMessageLists(incoming, existing);
  if(cloudSyncMessageListHasSamePrefix(incoming, existing)) return mergeRichUserAttachmentsAcrossMessageLists(existing, incoming);
  const seen = new Set(existing.map(msg => cloudSyncMessageFingerprint(msg)));
  const seenIdentity = new Set(existing.map(msg => cloudSyncMessageIdentityKey(msg)).filter(Boolean));
  const merged = existing.slice();
  for(const msg of incoming){
    const identityKey = cloudSyncMessageIdentityKey(msg);
    if(identityKey && seenIdentity.has(identityKey)){
      const idx = merged.findIndex(x => cloudSyncMessageIdentityKey(x) === identityKey);
      if(idx >= 0){
        mergeRichUserAttachmentMessage(merged[idx], msg);
        mergeMessageSyncRecoveryFields(merged[idx], msg);
      }
      continue;
    }
    const key = cloudSyncMessageFingerprint(msg);
    if(key in seen || seen.has(key)) continue;
    seen.add(key);
    if(identityKey) seenIdentity.add(identityKey);
    merged.push(msg);
  }
  return mergeRichUserAttachmentsAcrossMessageLists(merged, incoming);
}
function preserveSessionReadStateFromSource(targetSession, sourceSession){
  const target = targetSession && typeof targetSession === 'object' ? targetSession : null;
  const source = sourceSession && typeof sourceSession === 'object' ? sourceSession : null;
  if(!target || !source) return false;
  let changed = false;
  const sourceReadKey = String(source.sidebarReadDoneKey || source.sidebarLastReadDoneKey || '').trim();
  const sourceReadAt = _sessionReadDoneAtMs(source);
  const targetReadAt = _sessionReadDoneAtMs(target);
  if(sourceReadKey && (!String(target.sidebarReadDoneKey || '').trim() || sourceReadAt >= targetReadAt)){
    if(String(target.sidebarReadDoneKey || '') !== sourceReadKey){
      target.sidebarReadDoneKey = sourceReadKey;
      changed = true;
    }
  }
  if(sourceReadAt > 0 && sourceReadAt > targetReadAt){
    target.sidebarReadDoneAt = sourceReadAt;
    changed = true;
  }
  const targetUnreadKey = String(target.sidebarUnreadDoneKey || '').trim();
  if(target.sidebarUnreadDone && sourceReadKey && (!targetUnreadKey || sourceReadKey === targetUnreadKey || sourceReadKey === sessionLatestCompletedAssistantReadKey(target))){
    delete target.sidebarUnreadDone;
    delete target.sidebarUnreadDoneKey;
    delete target.sidebarUnreadDoneAt;
    changed = true;
  }else if(target.sidebarUnreadDone && sourceReadAt > 0){
    const unreadAt = _sessionUnreadDoneAtMs(target);
    if(unreadAt > 0 && sourceReadAt >= unreadAt){
      delete target.sidebarUnreadDone;
      delete target.sidebarUnreadDoneKey;
      delete target.sidebarUnreadDoneAt;
      changed = true;
    }
  }
  return changed;
}

function normalizeSessionUnreadStateAfterMerge(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s || !s.sidebarUnreadDone) return false;
  if(!sessionLatestCompletedAssistantReadKey(s) || sessionReadStateCoversUnread(s)){
    delete s.sidebarUnreadDone;
    delete s.sidebarUnreadDoneKey;
    delete s.sidebarUnreadDoneAt;
    return true;
  }
  return false;
}


function composerDraftMergeStamp(session){
  const s = session && typeof session === 'object' ? session : {};
  const values = [
    Number(s.composerDraftUpdatedAt || 0) || 0,
    Number(s.composerDraftClearedAt || 0) || 0,
    Number(s.composerDraftSentClearAt || 0) || 0,
  ];
  return Math.max(0, ...values.filter(Number.isFinite));
}

function copyComposerDraftFields(target, source){
  const out = target && typeof target === 'object' ? target : null;
  const src = source && typeof source === 'object' ? source : {};
  if(!out) return false;
  let changed = false;
  const nextDraft = String(src.composerDraft ?? '');
  if(String(out.composerDraft ?? '') !== nextDraft){
    out.composerDraft = nextDraft;
    changed = true;
  }else if(!Object.prototype.hasOwnProperty.call(out, 'composerDraft')){
    out.composerDraft = nextDraft;
    changed = true;
  }
  for(const key of ['composerDraftUpdatedAt','composerDraftClearedAt','composerDraftSentClearAt','composerDraftClearReason']){
    if(Object.prototype.hasOwnProperty.call(src, key) && src[key] !== undefined && src[key] !== null && src[key] !== ''){
      if(out[key] !== src[key]){ out[key] = src[key]; changed = true; }
    }else if(Object.prototype.hasOwnProperty.call(out, key)){
      delete out[key];
      changed = true;
    }
  }
  return changed;
}

function applyMergedComposerDraftFields(merged, existing, incoming, existingUpdated=0, incomingUpdated=0){
  const out = merged && typeof merged === 'object' ? merged : null;
  if(!out) return false;
  const a = existing && typeof existing === 'object' ? existing : {};
  const b = incoming && typeof incoming === 'object' ? incoming : {};
  const aStamp = composerDraftMergeStamp(a);
  const bStamp = composerDraftMergeStamp(b);
  const aDraft = String(a.composerDraft ?? '');
  const bDraft = String(b.composerDraft ?? '');
  let chosen = null;
  if(aStamp > 0 || bStamp > 0){
    if(aStamp > bStamp) chosen = a;
    else if(bStamp > aStamp) chosen = b;
    else {
      const aClear = Math.max(Number(a.composerDraftClearedAt || 0) || 0, Number(a.composerDraftSentClearAt || 0) || 0);
      const bClear = Math.max(Number(b.composerDraftClearedAt || 0) || 0, Number(b.composerDraftSentClearAt || 0) || 0);
      if(aClear > bClear) chosen = a;
      else if(bClear > aClear) chosen = b;
      else chosen = (Number(incomingUpdated || 0) >= Number(existingUpdated || 0)) ? b : a;
    }
  }else if(aDraft.trim() && !bDraft.trim()){
    chosen = a;
  }else if(bDraft.trim() && !aDraft.trim()){
    chosen = b;
  }else{
    chosen = (Number(incomingUpdated || 0) >= Number(existingUpdated || 0)) ? b : a;
  }
  return copyComposerDraftFields(out, chosen || {});
}

function preserveNewerLocalComposerDraft(remoteSession, localSession){
  const remote = remoteSession && typeof remoteSession === 'object' ? remoteSession : null;
  const local = localSession && typeof localSession === 'object' ? localSession : null;
  if(!remote || !local) return false;
  const remoteStamp = composerDraftMergeStamp(remote);
  const localStamp = composerDraftMergeStamp(local);
  if(localStamp > 0 && localStamp >= remoteStamp){
    return copyComposerDraftFields(remote, local);
  }
  return false;
}

function composerAttachmentDraftMergeStamp(session){
  const s = session && typeof session === 'object' ? session : {};
  return Math.max(
    Number(s.composerAttachmentDraftUpdatedAt || 0) || 0,
    Number(s.composer_attachment_draft_updated_at || 0) || 0
  );
}

function copyComposerAttachmentDraftFields(target, source){
  const out = target && typeof target === 'object' ? target : null;
  const src = source && typeof source === 'object' ? source : {};
  if(!out) return false;
  const nextDraft = normalizeComposerAttachmentDraftForCloudApply(src.composerAttachmentDraft || src.composer_attachment_draft);
  const previousDraft = normalizeComposerAttachmentDraftForCloudApply(out.composerAttachmentDraft || out.composer_attachment_draft);
  let changed = cloudSyncStableStringify(previousDraft) !== cloudSyncStableStringify(nextDraft);
  out.composerAttachmentDraft = nextDraft;
  const stamp = composerAttachmentDraftMergeStamp(src);
  if(stamp > 0 && Number(out.composerAttachmentDraftUpdatedAt || 0) !== stamp){
    out.composerAttachmentDraftUpdatedAt = stamp;
    changed = true;
  }
  return changed;
}

function applyMergedComposerAttachmentDraftFields(merged, existing, incoming, existingUpdated=0, incomingUpdated=0){
  const a = existing && typeof existing === 'object' ? existing : {};
  const b = incoming && typeof incoming === 'object' ? incoming : {};
  const aStamp = composerAttachmentDraftMergeStamp(a);
  const bStamp = composerAttachmentDraftMergeStamp(b);
  let chosen = null;
  if(aStamp !== bStamp) chosen = aStamp > bStamp ? a : b;
  else {
    const aHasItems = composerAttachmentDraftHasItems(a.composerAttachmentDraft || a.composer_attachment_draft);
    const bHasItems = composerAttachmentDraftHasItems(b.composerAttachmentDraft || b.composer_attachment_draft);
    if(aHasItems !== bHasItems) chosen = aHasItems ? a : b;
    else chosen = Number(incomingUpdated || 0) >= Number(existingUpdated || 0) ? b : a;
  }
  return copyComposerAttachmentDraftFields(merged, chosen || {});
}

function preserveNewerLocalComposerAttachmentDraft(remoteSession, localSession){
  const remote = remoteSession && typeof remoteSession === 'object' ? remoteSession : null;
  const local = localSession && typeof localSession === 'object' ? localSession : null;
  if(!remote || !local) return false;
  const remoteStamp = composerAttachmentDraftMergeStamp(remote);
  const localStamp = composerAttachmentDraftMergeStamp(local);
  if(localStamp > remoteStamp) return copyComposerAttachmentDraftFields(remote, local);
  if(localStamp === remoteStamp && composerAttachmentDraftHasItems(local.composerAttachmentDraft) && !composerAttachmentDraftHasItems(remote.composerAttachmentDraft)){
    return copyComposerAttachmentDraftFields(remote, local);
  }
  return false;
}

function cloudSyncRandomToken(prefix='id'){
  const p = String(prefix || 'id').replace(/[^0-9A-Za-z_-]/g, '_').slice(0, 24) || 'id';
  try{
    if(window.crypto?.getRandomValues){
      const arr = new Uint32Array(2);
      window.crypto.getRandomValues(arr);
      return `${p}_${arr[0].toString(16)}${arr[1].toString(16)}_${Date.now().toString(16)}`;
    }
  }catch(_){ }
  return `${p}_${Math.random().toString(16).slice(2)}_${Date.now().toString(16)}`;
}

function normalizeConversationSyncMode(value, fallback=''){
  const raw = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  if(raw === 'response' || raw === 'responses' || raw === '/responses') return 'response';
  if(raw === 'chat' || raw === 'chat_completion' || raw === 'chat_completions' || raw === 'completions') return 'chat';
  const fb = String(fallback || '').trim().toLowerCase();
  if(fb) return normalizeConversationSyncMode(fb, '');
  return 'chat';
}

function conversationModeFromApiEndpointMode(value){
  try{
    if(typeof normalizeApiEndpointMode === 'function'){
      return normalizeApiEndpointMode(value) === 'responses' ? 'response' : 'chat';
    }
  }catch(_){ }
  return normalizeConversationSyncMode(value);
}

function sessionConversationMode(session, fallback=''){
  const s = session && typeof session === 'object' ? session : {};
  const explicit = s.conversationMode || s.conversation_mode || s.syncMode || s.sync_mode || s.chatMode || s.chat_mode || '';
  if(explicit) return normalizeConversationSyncMode(explicit, fallback);
  const endpoint = s.api_endpoint_mode || s.endpoint_mode || s.apiEndpointMode || s.endpointMode || '';
  if(endpoint) return conversationModeFromApiEndpointMode(endpoint);
  return normalizeConversationSyncMode(fallback || '');
}

function cloudSyncCurrentConversationMode(){
  try{
    if(typeof getActiveApiEndpointMode === 'function') return conversationModeFromApiEndpointMode(getActiveApiEndpointMode());
  }catch(_){ }
  return 'chat';
}

function cloudSyncCurrentApiEndpointModeForConversation(mode=''){
  const normalized = normalizeConversationSyncMode(mode || cloudSyncCurrentConversationMode());
  if(normalized === 'response') return 'responses';
  return 'chat_completions';
}

function cloudSyncEnsureConversationSyncFields(session, sid='', opts={}){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return s;
  const sessionId = String(sid || s.id || '').trim();
  if(sessionId) s.id = String(s.id || sessionId).trim() || sessionId;
  const mode = sessionConversationMode(s, opts?.mode || '');
  const endpointMode = cloudSyncCurrentApiEndpointModeForConversation(mode);
  s.conversationMode = mode;
  s.conversation_mode = mode;
  s.api_endpoint_mode = String(s.api_endpoint_mode || s.endpoint_mode || s.apiEndpointMode || endpointMode).trim() || endpointMode;
  s.endpoint_mode = String(s.endpoint_mode || s.api_endpoint_mode || endpointMode).trim() || endpointMode;
  const localId = String(s.localId || s.local_id || sessionId || '').trim() || cloudSyncRandomToken('local_conv');
  s.localId = localId;
  s.local_id = localId;
  const opId = String(s.opId || s.op_id || '').trim() || makeCloudSyncOpId('conversation', localId || sessionId);
  s.opId = opId;
  s.op_id = opId;
  const status = String(s.syncStatus || s.sync_status || opts?.status || '').trim().toLowerCase();
  const meaningful = sessionHasMeaningfulConversation(s) || Number(s.serverVersion || s.server_version || s._cloudRevision || 0) > 0;
  const nextStatus = ['pending','sending','generating','server_owned_inflight','failed_retryable','failed_final','active','archived','deleted','auth_suspended'].includes(status)
    ? status
    : (meaningful ? 'active' : 'pending');
  s.syncStatus = nextStatus;
  s.sync_status = nextStatus;
  if(Number(s.serverVersion || s.server_version || s._cloudRevision || 0) > 0){
    const version = Number(s.serverVersion || s.server_version || s._cloudRevision || 0) || 0;
    s.serverVersion = version;
    s.server_version = version;
  }
  const recovery = s.conversationRecovery && typeof s.conversationRecovery === 'object' ? s.conversationRecovery : {};
  s.conversationRecovery = {
    ...recovery,
    mode,
    local_id: localId,
    server_id: sessionId || String(recovery.server_id || '').trim(),
    op_id: opId,
    server_version: Number(s.serverVersion || s.server_version || recovery.server_version || 0) || 0,
    status: nextStatus,
    updated_at: Number(s.updatedAt || s.updated_at || recovery.updated_at || Date.now()) || Date.now(),
  };
  return s;
}

function cloudSyncSessionHasProtectedLocalState(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  const status = String(s.syncStatus || s.sync_status || s.conversationRecovery?.status || '').trim().toLowerCase();
  if(['pending','sending','generating','server_owned_inflight','failed_retryable','auth_suspended'].includes(status)) return true;
  if(sessionHasPendingAssistantSnapshot(s)) return true;
  if(String(s.pendingJobId || s.pending_job_id || '').trim()) return true;
  if(s.runRecovery && typeof s.runRecovery === 'object'){
    const runStatus = String(s.runRecovery.status || '').trim().toLowerCase();
    if(['pending_submit','server_owned_inflight','auth_suspended','failed_retryable'].includes(runStatus)) return true;
  }
  return false;
}

function cloudSyncRunRecoveryIsActive(runRecovery){
  const run = runRecovery && typeof runRecovery === 'object' ? runRecovery : null;
  if(!run) return false;
  const jobId = String(run.server_run_id || run.serverRunId || '').trim();
  const status = String(run.status || '').trim().toLowerCase();
  if(!jobId) return false;
  return ['server_owned_inflight','claimed','queued','running','stopping','auth_suspended','failed_retryable'].includes(status);
}

function cloudSyncHydrateRunRecoveryRuntimeFields(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  const run = s.runRecovery && typeof s.runRecovery === 'object' ? s.runRecovery : null;
  const clearedAt = Math.max(0, Number(s.runRecoveryClearedAt || s.run_recovery_cleared_at || 0) || 0);
  const runUpdatedAt = Math.max(0, Number(run?.updated_at || run?.updatedAt || 0) || 0);
  if(run && clearedAt > 0 && clearedAt >= runUpdatedAt){
    const staleJobId = String(run.server_run_id || run.serverRunId || '').trim();
    delete s.runRecovery;
    if(!staleJobId || String(s.pendingJobId || s.pending_job_id || '').trim() === staleJobId){
      delete s.pendingJobId;
      delete s.pending_job_id;
      delete s.pendingJobCursor;
      delete s.pending_job_cursor;
      delete s.pendingJobTurnKey;
      delete s.pending_job_turn_key;
    }
    if(String(s.syncStatus || s.sync_status || '').trim().toLowerCase() === 'server_owned_inflight'){
      s.syncStatus = 'active';
      s.sync_status = 'active';
    }
    return false;
  }
  if(!cloudSyncRunRecoveryIsActive(run)) return false;
  const jobId = String(run.server_run_id || run.serverRunId || '').trim();
  const turnKey = String(run.turn_key || run.turnKey || '').trim();
  const previousJobId = String(s.pendingJobId || s.pending_job_id || '').trim();
  s.pendingJobId = jobId;
  delete s.pending_job_id;
  // SSE 游标是设备本地消费位置。另一台设备必须从 0 重放，不能继承上传者游标。
  s.pendingJobCursor = previousJobId === jobId ? Math.max(0, Number(s.pendingJobCursor || 0) || 0) : 0;
  delete s.pending_job_cursor;
  if(turnKey){
    s.pendingJobTurnKey = turnKey;
    delete s.pending_job_turn_key;
  }
  s.syncStatus = 'server_owned_inflight';
  s.sync_status = 'server_owned_inflight';
  return true;
}

function cloudSyncAttachRunRecoveryForTransport(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  cloudSyncHydrateRunRecoveryRuntimeFields(s);
  const recoveryJobId = cloudSyncRunRecoveryIsActive(s.runRecovery)
    ? String(s.runRecovery?.server_run_id || s.runRecovery?.serverRunId || '').trim()
    : '';
  const jobId = String(s.pendingJobId || s.pending_job_id || recoveryJobId || '').trim();
  const turnKey = String(s.pendingJobTurnKey || s.pending_job_turn_key || s.runRecovery?.turn_key || s.runRecovery?.turnKey || '').trim();
  const responseId = String(s.responseId || s.response_id || s.runRecovery?.response_id || '').trim();
  if(!(jobId || turnKey || responseId || sessionHasPendingAssistantSnapshot(s))) return false;
  const mode = sessionConversationMode(s);
  const localId = String(s.localId || s.local_id || s.id || '').trim();
  const opId = String(s.opId || s.op_id || '').trim() || makeCloudSyncOpId('run_recovery', localId || s.id || jobId);
  s.runRecovery = {
    ...(s.runRecovery && typeof s.runRecovery === 'object' ? s.runRecovery : {}),
    mode,
    conversation_local_id: localId,
    conversation_id: String(s.id || '').trim(),
    local_run_id: String(s.runRecovery?.local_run_id || s.runRecovery?.localRunId || opId).trim(),
    server_run_id: jobId,
    response_id: responseId,
    cursor: '',
    turn_key: turnKey,
    op_id: opId,
    status: jobId ? 'server_owned_inflight' : 'pending_submit',
    updated_at: Date.now(),
  };
  s.syncStatus = jobId ? 'server_owned_inflight' : (String(s.syncStatus || s.sync_status || 'pending').trim() || 'pending');
  s.sync_status = s.syncStatus;
  return true;
}

function preserveConversationSyncRecoveryFields(targetSession, sourceSession){
  const target = targetSession && typeof targetSession === 'object' ? targetSession : null;
  const source = sourceSession && typeof sourceSession === 'object' ? sourceSession : null;
  if(!target || !source) return false;
  let changed = false;
  const before = cloudSyncStableStringify({
    conversationMode: target.conversationMode,
    api_endpoint_mode: target.api_endpoint_mode,
    localId: target.localId,
    opId: target.opId,
    syncStatus: target.syncStatus,
    conversationRecovery: target.conversationRecovery,
    runRecovery: target.runRecovery,
    runRecoveryClearedAt: target.runRecoveryClearedAt,
  });
  const sourceMode = sessionConversationMode(source);
  if(sourceMode && (!target.conversationMode || target.conversationMode !== sourceMode)){
    target.conversationMode = sourceMode;
    target.conversation_mode = sourceMode;
  }
  for(const [camel, snake] of [['localId','local_id'], ['opId','op_id'], ['serverVersion','server_version']]){
    const value = source[camel] ?? source[snake];
    if((target[camel] === undefined || target[camel] === null || target[camel] === '') && value !== undefined && value !== null && value !== ''){
      target[camel] = value;
      target[snake] = value;
    }
  }
  if(source.conversationRecovery && typeof source.conversationRecovery === 'object'){
    target.conversationRecovery = { ...(target.conversationRecovery || {}), ...source.conversationRecovery };
  }
  if(source.runRecovery && typeof source.runRecovery === 'object'){
    const targetRunUpdated = Number(target.runRecovery?.updated_at || target.runRecovery?.updatedAt || 0) || 0;
    const sourceRunUpdated = Number(source.runRecovery.updated_at || source.runRecovery.updatedAt || 0) || 0;
    if(!target.runRecovery || sourceRunUpdated >= targetRunUpdated){
      target.runRecovery = { ...source.runRecovery };
    }
  }
  const targetRunClearedAt = Math.max(0, Number(target.runRecoveryClearedAt || target.run_recovery_cleared_at || 0) || 0);
  const sourceRunClearedAt = Math.max(0, Number(source.runRecoveryClearedAt || source.run_recovery_cleared_at || 0) || 0);
  if(sourceRunClearedAt > targetRunClearedAt){
    target.runRecoveryClearedAt = sourceRunClearedAt;
    target.run_recovery_cleared_at = sourceRunClearedAt;
  }
  cloudSyncHydrateRunRecoveryRuntimeFields(target);
  const sourceProtected = cloudSyncSessionHasProtectedLocalState(source);
  const targetStatus = String(target.syncStatus || target.sync_status || '').trim().toLowerCase();
  const sourceStatus = String(source.syncStatus || source.sync_status || source.conversationRecovery?.status || '').trim().toLowerCase();
  if(sourceProtected && sourceStatus && targetStatus !== 'active'){
    target.syncStatus = sourceStatus;
    target.sync_status = sourceStatus;
  }
  cloudSyncEnsureConversationSyncFields(target, target.id || source.id || '');
  changed = before !== cloudSyncStableStringify({
    conversationMode: target.conversationMode,
    api_endpoint_mode: target.api_endpoint_mode,
    localId: target.localId,
    opId: target.opId,
    syncStatus: target.syncStatus,
    conversationRecovery: target.conversationRecovery,
    runRecovery: target.runRecovery,
    runRecoveryClearedAt: target.runRecoveryClearedAt,
  });
  return changed;
}

function cloudSyncBranchUpdatedAtForCompare(session){
  try{ return Math.max(0, Number(webaiBranchMaxUpdatedAt(session) || 0) || 0); }catch(_){ }
  const s = session && typeof session === 'object' ? session : null;
  return Math.max(0, Number(s?.updatedAt || s?.updated_at || s?.createdAt || s?.created_at || 0) || 0);
}

function cloudSyncChooseBranchAuthoritativeSession(existing, incoming, existingUpdated, incomingUpdated){
  const existingHasBranchState = webaiBranchSessionHasState(existing);
  const incomingHasBranchState = webaiBranchSessionHasState(incoming);
  if(!existingHasBranchState && !incomingHasBranchState) return null;
  const existingVisible = countCloudMergeVisibleMessages(existing);
  const incomingVisible = countCloudMergeVisibleMessages(incoming);
  if(existingHasBranchState && !incomingHasBranchState){
    if(incomingVisible > existingVisible && incomingUpdated > existingUpdated + 1000) return incoming;
    return existing;
  }
  if(!existingHasBranchState && incomingHasBranchState){
    if(existingVisible > incomingVisible && existingUpdated > incomingUpdated + 1000) return existing;
    return incoming;
  }
  const existingBranchUpdated = cloudSyncBranchUpdatedAtForCompare(existing);
  const incomingBranchUpdated = cloudSyncBranchUpdatedAtForCompare(incoming);
  if(existingBranchUpdated > incomingBranchUpdated + 250 && existingVisible >= incomingVisible) return existing;
  if(incomingBranchUpdated > existingBranchUpdated + 250 && incomingVisible >= existingVisible) return incoming;
  if(existingVisible > incomingVisible && existingBranchUpdated >= incomingBranchUpdated - 250) return existing;
  if(incomingVisible > existingVisible && incomingBranchUpdated >= existingBranchUpdated - 250) return incoming;
  return incomingUpdated >= existingUpdated ? incoming : existing;
}

function cloudSyncMergeSession(existingSession, incomingSession, sid){
  const sessionId = String(sid || incomingSession?.id || existingSession?.id || '').trim();
  const incoming = incomingSession && typeof incomingSession === 'object' ? JSON.parse(JSON.stringify(incomingSession)) : {};
  incoming.id = String(incoming.id || sessionId).trim() || sessionId;
  cloudSyncEnsureConversationSyncFields(incoming, sessionId);
  if(!existingSession || typeof existingSession !== 'object' || isCloudSessionStub(existingSession)){
    incoming._cloudStub = false;
    incoming._cloudNeedsHydrate = false;
    incoming._cloudHydrated = true;
    cloudSyncHydrateRunRecoveryRuntimeFields(incoming);
    if(!sessionHasPendingAssistantSnapshot(incoming)) clearPendingAssistantFieldsFromSession(incoming);
    return incoming;
  }
  const existing = JSON.parse(JSON.stringify(existingSession));
  existing.id = String(existing.id || sessionId).trim() || sessionId;
  cloudSyncEnsureConversationSyncFields(existing, sessionId);
  const incomingUpdated = Number(incoming.updatedAt || incoming.updated_at || incoming.createdAt || incoming.created_at || 0) || 0;
  const existingUpdated = Number(existing.updatedAt || existing.updated_at || existing.createdAt || existing.created_at || 0) || 0;
  const merged = incomingUpdated >= existingUpdated ? { ...existing, ...incoming } : { ...incoming, ...existing };
  merged.id = sessionId;
  const existingHasBranchState = webaiBranchSessionHasState(existing);
  const incomingHasBranchState = webaiBranchSessionHasState(incoming);
  if(existingHasBranchState || incomingHasBranchState){
    const authoritative = cloudSyncChooseBranchAuthoritativeSession(existing, incoming, existingUpdated, incomingUpdated) || (incomingUpdated >= existingUpdated ? incoming : existing);
    merged.messages = webaiBranchCloneMessages(authoritative.messages || []);
    if(authoritative._webaiConversationBranches && typeof authoritative._webaiConversationBranches === 'object'){
      try{ merged._webaiConversationBranches = JSON.parse(JSON.stringify(authoritative._webaiConversationBranches)); }catch(_){ merged._webaiConversationBranches = authoritative._webaiConversationBranches; }
    }else{
      delete merged._webaiConversationBranches;
    }
    if(String(authoritative._webaiActiveConversationBranchId || '').trim()) merged._webaiActiveConversationBranchId = String(authoritative._webaiActiveConversationBranchId || '').trim();
    else delete merged._webaiActiveConversationBranchId;
    try{ webaiBranchNormalizeActiveViewInSession(merged, { skipIfLive:false }); }catch(_){ }
    try{ webaiBranchNormalizeVisibleAssistantRunsInSession(merged); }catch(_){ }
  }else{
    merged.messages = cloudSyncMergeMessageLists(existing.messages, incoming.messages);
  }
  if(incomingUpdated || existingUpdated) merged.updatedAt = Math.max(incomingUpdated, existingUpdated);
  preserveSessionReadStateFromSource(merged, existing);
  preserveSessionReadStateFromSource(merged, incoming);
  try{ preserveSessionUserAttachmentsFromSource(merged, existing); }catch(_){}
  try{ preserveSessionUserAttachmentsFromSource(merged, incoming); }catch(_){}
  normalizeSessionUnreadStateAfterMerge(merged);
  applyMergedComposerDraftFields(merged, existing, incoming, existingUpdated, incomingUpdated);
  applyMergedComposerAttachmentDraftFields(merged, existing, incoming, existingUpdated, incomingUpdated);
  try{ preserveConversationSyncRecoveryFields(merged, existing); }catch(_){ }
  try{ preserveConversationSyncRecoveryFields(merged, incoming); }catch(_){ }
  if(existing.composerQuoteDraft && typeof existing.composerQuoteDraft === 'object' && !incoming.composerQuoteDraft) merged.composerQuoteDraft = existing.composerQuoteDraft;
  try{
    if(typeof applyComposerAttachmentDraftRuntimeGuardToSession === 'function') applyComposerAttachmentDraftRuntimeGuardToSession(merged, sessionId);
  }catch(_){ }
  merged._cloudStub = false;
  merged._cloudNeedsHydrate = false;
  merged._cloudHydrated = true;
  if(!sessionHasPendingAssistantSnapshot(merged)) clearPendingAssistantFieldsFromSession(merged);
  return merged;
}
function cloudSyncSessionMetaPatch(prevSession, nextSession){
  const prev = prevSession && typeof prevSession === 'object' ? prevSession : {};
  const next = nextSession && typeof nextSession === 'object' ? nextSession : {};
  const keys = ['id','title','model','createdAt','updatedAt','webEnabled','imageGenerationEnabled','chatThinkingType','aiTitleDone','titleAutoLocked','archived','archivedAt','archived_at','pinned','pinnedAt','pinned_at','rtFinalMs','sidebarUnreadDone','sidebarUnreadDoneKey','sidebarUnreadDoneAt','sidebarReadDoneKey','sidebarReadDoneAt','composerDraft','composerDraftUpdatedAt','composerDraftClearedAt','composerDraftSentClearAt','composerDraftClearReason','composerAttachmentDraft','composerAttachmentDraftUpdatedAt','_webaiConversationBranches','_webaiActiveConversationBranchId','conversationMode','conversation_mode','api_endpoint_mode','endpoint_mode','localId','local_id','opId','op_id','syncStatus','sync_status','serverVersion','server_version','conversationRecovery','runRecovery','runRecoveryClearedAt','run_recovery_cleared_at'];
  const patch = {};
  for(const key of keys){
    if(key === 'id') continue;
    let prevValue = prev[key] ?? null;
    let nextValue = next[key] ?? null;
    if(key === 'composerAttachmentDraft'){
      prevValue = normalizeComposerAttachmentDraftForCloudApply(prevValue);
      nextValue = normalizeComposerAttachmentDraftForCloudApply(nextValue);
    }
    if(cloudSyncStableStringify(prevValue ?? null) !== cloudSyncStableStringify(nextValue ?? null)){
      patch[key] = key === 'composerAttachmentDraft' ? nextValue : next[key];
    }
  }
  return patch;
}
function cloudSyncMinimalSessionSeed(session, sid){
  const s = session && typeof session === 'object' ? session : {};
  const mode = sessionConversationMode(s, cloudSyncCurrentConversationMode());
  const endpointMode = cloudSyncCurrentApiEndpointModeForConversation(mode);
  const localId = String(s.localId || s.local_id || sid || '').trim() || cloudSyncRandomToken('local_conv');
  const opId = String(s.opId || s.op_id || '').trim() || makeCloudSyncOpId('conversation', localId || sid);
  return {
    id: String(s.id || sid || '').trim() || String(sid || '').trim(),
    localId,
    local_id: localId,
    opId,
    op_id: opId,
    conversationMode: mode,
    conversation_mode: mode,
    api_endpoint_mode: String(s.api_endpoint_mode || s.endpoint_mode || endpointMode).trim() || endpointMode,
    endpoint_mode: String(s.endpoint_mode || s.api_endpoint_mode || endpointMode).trim() || endpointMode,
    syncStatus: String(s.syncStatus || s.sync_status || 'pending').trim() || 'pending',
    sync_status: String(s.sync_status || s.syncStatus || 'pending').trim() || 'pending',
    serverVersion: Number(s.serverVersion || s.server_version || 0) || 0,
    server_version: Number(s.server_version || s.serverVersion || 0) || 0,
    conversationRecovery: {
      mode,
      local_id: localId,
      server_id: String(s.id || sid || '').trim() || String(sid || '').trim(),
      op_id: opId,
      server_version: Number(s.serverVersion || s.server_version || 0) || 0,
      status: String(s.syncStatus || s.sync_status || 'pending').trim() || 'pending',
      updated_at: Number(s.updatedAt || s.updated_at || Date.now()) || Date.now(),
    },
    title: String(s.title || '新会话').trim() || '新会话',
    model: String(s.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL,
    createdAt: Number(s.createdAt || Date.now()) || Date.now(),
    updatedAt: Number(s.updatedAt || s.createdAt || Date.now()) || Date.now(),
    webEnabled: !!s.webEnabled,
    imageGenerationEnabled: !!s.imageGenerationEnabled,
    chatThinkingType: normalizeThinkingType(s.chatThinkingType || ''),
    archived: isSessionArchived(s),
    archivedAt: getSessionArchivedAtMs(s),
    archived_at: getSessionArchivedAtMs(s),
    pinned: !!s.pinned,
    pinnedAt: Number(s.pinnedAt || s.pinned_at || 0) || 0,
    pinned_at: Number(s.pinned_at || s.pinnedAt || 0) || 0,
    messages: [],
  };
}

function cloudSyncBuildAppendMessageOps(sessionId, prevMessages, addedMessages, nextSession, metaPatch={}){
  const sid = String(sessionId || '').trim();
  const rawAdded = Array.isArray(addedMessages) ? addedMessages.map(cloudSyncSlimMessageForTransport).filter(Boolean) : [];
  if(!sid || !rawAdded.length) return [];
  const out = [];
  const base = Array.isArray(prevMessages) ? prevMessages.map(cloudSyncSlimMessageForTransport).filter(Boolean) : [];
  let cursorBase = base.slice();
  let chunk = [];
  const softChunkBytes = 48 * 1024;
  const maxChunkMessages = 24;
  let metaPatchApplied = false;
  const hasMetaPatch = !!Object.keys(metaPatch || {}).length;
  const makeAppendOp = (messages, includePatch=false) => ({
    op_id: makeCloudSyncOpId('append_messages', sid),
    op_type: 'append_messages',
    device_id: getCloudSyncDeviceId(),
    session_id: sid,
    payload: {
      ...cloudSyncMessageBaseGuard(cursorBase),
      messages,
      session_seed: cloudSyncMinimalSessionSeed(nextSession, sid),
      session_patch: includePatch ? (metaPatch || {}) : {},
    },
    created_at: Date.now(),
  });
  const flushChunk = (includePatch=false)=>{
    if(!chunk.length) return;
    const messages = chunk.slice();
    out.push(makeAppendOp(messages, includePatch));
    if(includePatch) metaPatchApplied = true;
    cursorBase = cursorBase.concat(messages);
    chunk = [];
  };
  for(let i = 0; i < rawAdded.length; i++){
    const prepared = cloudSyncPrepareChunkedMessageForTransport(rawAdded[i], sid, i);
    const msg = prepared.message;
    const bodyChunkOps = Array.isArray(prepared.chunkOps) ? prepared.chunkOps : [];
    if(bodyChunkOps.length){
      flushChunk(false);
      const includePatch = hasMetaPatch && i === rawAdded.length - 1;
      out.push(makeAppendOp([msg], includePatch));
      if(includePatch) metaPatchApplied = true;
      cursorBase = cursorBase.concat([msg]);
      for(const bodyOp of bodyChunkOps) out.push(bodyOp);
      continue;
    }
    const candidate = chunk.concat([msg]);
    const candidateOp = makeAppendOp(candidate, false);
    const candidateBytes = cloudSyncOpsPayloadBytes([candidateOp]);
    if(chunk.length && (candidate.length > maxChunkMessages || candidateBytes > softChunkBytes)){
      flushChunk(false);
    }
    chunk.push(msg);
  }
  flushChunk(hasMetaPatch && !metaPatchApplied);
  if(hasMetaPatch && !metaPatchApplied){
    out.push({
      op_id: makeCloudSyncOpId('update_session_meta', sid),
      op_type: 'update_session_meta',
      device_id: getCloudSyncDeviceId(),
      session_id: sid,
      payload: { patch: metaPatch || {} },
      created_at: Date.now(),
    });
  }
  if(out.length > 1 && hasMetaPatch){
    for(let i = 0; i < out.length - 1; i++){
      if(out[i]?.op_type === 'append_messages'){
        try{ out[i].payload.session_patch = {}; }catch(_){ }
      }
    }
  }
  return out;
}

function cloudSyncBuildMessageBodyUpdateOps(sessionId, prevMessages, nextMessages, metaPatch={}){
  const sid = String(sessionId || '').trim();
  const prev = Array.isArray(prevMessages) ? prevMessages : [];
  const next = Array.isArray(nextMessages) ? nextMessages : [];
  if(!sid || !prev.length || prev.length !== next.length) return [];
  const out = [];
  for(let i = 0; i < next.length; i += 1){
    const prevMsg = prev[i];
    const nextMsg = next[i];
    if(!prevMsg || !nextMsg || typeof prevMsg !== 'object' || typeof nextMsg !== 'object') return [];
    const prevId = cloudSyncMessageIdentityKey(prevMsg);
    const nextId = cloudSyncMessageIdentityKey(nextMsg);
    if(!prevId || !nextId || prevId !== nextId) return [];
    const prevContent = typeof prevMsg.content === 'string' ? String(prevMsg.content) : '';
    const nextContent = typeof nextMsg.content === 'string' ? String(nextMsg.content) : '';
    if(prevContent !== nextContent && nextContent){
      out.push(...cloudSyncBuildMessageBodyChunkOps(sid, nextMsg, i, 'content'));
    }
  }
  if(out.length && Object.keys(metaPatch || {}).length){
    out.push({
      op_id: makeCloudSyncOpId('update_session_meta', sid),
      op_type: 'update_session_meta',
      device_id: getCloudSyncDeviceId(),
      session_id: sid,
      payload: { patch: metaPatch || {} },
      created_at: Date.now(),
    });
  }
  return out;
}

function cloudSyncBuildSessionOps(prevSession, nextSession, sid){
  const sessionId = String(sid || nextSession?.id || prevSession?.id || '').trim();
  if(!sessionId || !nextSession || typeof nextSession !== 'object') return [];
  const prevForSync = cloudSyncSlimSessionForTransport(prevSession);
  const nextForSync = cloudSyncSlimSessionForTransport(nextSession);
  if(isCloudSessionStub(nextForSync)){
    const metaPatch = cloudSyncSessionMetaPatch(prevForSync, nextForSync);
    if(Object.keys(metaPatch).length){
      return [{
        op_id: makeCloudSyncOpId('update_session_meta', sessionId),
        op_type: 'update_session_meta',
        device_id: getCloudSyncDeviceId(),
        session_id: sessionId,
        payload: { patch: metaPatch },
        created_at: Date.now(),
      }];
    }
    return [];
  }
  if(!prevForSync || typeof prevForSync !== 'object' || isCloudSessionStub(prevForSync)){
    const nextMessages = Array.isArray(nextForSync.messages) ? nextForSync.messages : [];
    if(nextMessages.length){
      const metaPatch = cloudSyncSessionMetaPatch({}, nextForSync);
      return cloudSyncBuildAppendMessageOps(sessionId, [], nextMessages, nextForSync, metaPatch);
    }
    return [{
      op_id: makeCloudSyncOpId('upsert_session', sessionId),
      op_type: 'upsert_session',
      device_id: getCloudSyncDeviceId(),
      session_id: sessionId,
      payload: { session: nextForSync },
      created_at: Date.now(),
    }];
  }
  const prevMessages = Array.isArray(prevForSync.messages) ? prevForSync.messages : [];
  const nextMessages = Array.isArray(nextForSync.messages) ? nextForSync.messages : [];
  const metaPatch = cloudSyncSessionMetaPatch(prevForSync, nextForSync);
  const metaKeys = Object.keys(metaPatch);
  const bodyUpdateOps = cloudSyncBuildMessageBodyUpdateOps(sessionId, prevMessages, nextMessages, metaPatch);
  if(bodyUpdateOps.length) return bodyUpdateOps;
  if(cloudSyncMessageListHasSamePrefix(prevMessages, nextMessages)){
    const addedMessages = nextMessages.slice(prevMessages.length).map(cloudSyncSlimMessageForTransport).filter(Boolean);
    if(addedMessages.length){
      return cloudSyncBuildAppendMessageOps(sessionId, prevMessages, addedMessages, nextForSync, metaPatch);
    }
    if(metaKeys.length){
      return [{
        op_id: makeCloudSyncOpId('update_session_meta', sessionId),
        op_type: 'update_session_meta',
        device_id: getCloudSyncDeviceId(),
        session_id: sessionId,
        payload: { patch: metaPatch },
        created_at: Date.now(),
      }];
    }
    return [];
  }
  return [{
    op_id: makeCloudSyncOpId('upsert_session', sessionId),
    op_type: 'upsert_session',
    device_id: getCloudSyncDeviceId(),
    session_id: sessionId,
    payload: { ...cloudSyncMessageBaseGuard(prevMessages), session: nextForSync },
    created_at: Date.now(),
  }];
}


function buildCloudSyncOpsFromPayload(nextPayload, nextStoreObj=null){
  const nextStore = nextStoreObj && isValidStoreShape(nextStoreObj) ? nextStoreObj : parseCloudSyncPayload(nextPayload);
  if(!nextStore) return [];
  const prevStore = parseCloudSyncPayload(lastCloudSyncedPayload);
  const ops = [];
  const prevSessions = (prevStore?.sessions && typeof prevStore.sessions === 'object') ? prevStore.sessions : {};
  const nextSessions = (nextStore.sessions && typeof nextStore.sessions === 'object') ? nextStore.sessions : {};

  const pushChangedNonStubSessions = () => {
    for(const [sid, session] of Object.entries(nextSessions)){
      if(!sid || !session) continue;
      if(isSessionDeletedByTombstones(sid, currentAccountEmail)) continue;
      if(!prevSessions[sid] || cloudSyncSessionChanged(prevSessions[sid], session)){
        for(const op of cloudSyncBuildSessionOps(prevSessions[sid], session, sid)){
          if(op && typeof op === 'object') ops.push(op);
        }
      }
    }
  };

  const pushPersonalizationIfChanged = () => {
    const personalizationPrev = cloudSyncStableStringify(prevStore?.personalization || null);
    const personalizationNext = cloudSyncStableStringify(nextStore.personalization || null);
    if(personalizationPrev !== personalizationNext){
      ops.push({
        op_id: makeCloudSyncOpId('set_personalization'),
        op_type: 'set_personalization',
        device_id: getCloudSyncDeviceId(),
        payload: { personalization: nextStore.personalization || {} },
        created_at: Date.now(),
      });
    }
  };

  pushChangedNonStubSessions();
  pushPersonalizationIfChanged();

  // Important: local absence is not deletion. Only explicit user delete/clear actions
  // are allowed to create delete_session ops.
  for(const op of buildPendingCloudDeleteOps()) ops.push(op);

  // activeId is a device-local cursor. Account sync only carries sessions/messages.

  return ops;
}

function cloudSyncOpsPayloadBytes(ops){
  try{ return new Blob([JSON.stringify(ops || [])]).size; }catch(_){ }
  try{ return (new TextEncoder()).encode(JSON.stringify(ops || [])).length; }catch(_){ }
  try{ return JSON.stringify(ops || []).length * 2; }catch(_){ }
  return 0;
}

function limitCloudSyncOpsForPush(ops){
  const rows = Array.isArray(ops) ? ops.filter(op => op && typeof op === 'object') : [];
  const softLimit = Math.max(64 * 1024, Math.min(CLOUD_SYNC_OP_PAYLOAD_SOFT_LIMIT, Number(accountChatLimits?.maxStoreBytes || 0) || CLOUD_SYNC_OP_PAYLOAD_SOFT_LIMIT));
  const maxOps = 70;
  if(!rows.length) return { ops:[], partial:false, totalOps:0, sentOps:0, bytes:0, error:'' };
  const selected = [];
  let selectedBytes = 2;
  for(const op of rows){
    const candidate = selected.concat([op]);
    const candidateBytes = cloudSyncOpsPayloadBytes(candidate);
    if(selected.length > 0 && (selected.length >= maxOps || candidateBytes > softLimit)) break;
    if(selected.length === 0 && candidateBytes > softLimit){
      return { ops:[], partial:true, totalOps:rows.length, sentOps:0, bytes:candidateBytes, error:'single_op_too_large' };
    }
    selected.push(op);
    selectedBytes = candidateBytes;
  }
  return {
    ops:selected,
    partial:selected.length < rows.length,
    totalOps:rows.length,
    sentOps:selected.length,
    bytes:selectedBytes,
    error:'',
  };
}

function noteCloudSyncBuildProblem(reason='', payload=''){
  const msg = String(reason || 'cloud_sync_ops_build_failed').trim();
  if(!currentAccountEmail || !msg) return;
  const rawPayload = String(payload || cloudSyncQueuedPayload || getScopedCloudSyncPendingPayload(currentAccountEmail) || '').trim();
  if(!rawPayload) return;
  cloudSyncLastReason = msg;
  cloudSyncQueuedPayload = rawPayload;
  writeScopedCloudSyncPending(currentAccountEmail, rawPayload, {
    lastReason: msg,
    retryCount: cloudSyncRetryCount,
    localUpdatedAt: storeLatestUpdatedAtMs(store),
    buildFailed:true,
  });
  markScopedStoreDirty(currentAccountEmail, { localUpdatedAt: storeLatestUpdatedAtMs(store) });
}

function buildCloudSyncPushBodyFromPayload(payload, storeObj=null){
  const rawOps = buildCloudSyncOpsFromPayload(payload, storeObj);
  const limited = limitCloudSyncOpsForPush(rawOps);
  cloudSyncLastPushBuildMeta = {
    partial: !!limited.partial,
    totalOps: Number(limited.totalOps || 0) || 0,
    sentOps: Number(limited.sentOps || 0) || 0,
    error: String(limited.error || ''),
  };
  return {
    protocol: 'ops_v3_incremental',
    protocol_version: CLOUD_SYNC_PROTOCOL_VERSION,
    device_id: getCloudSyncDeviceId(),
    base_revision: Number(currentCloudStoreRevision || 0) || 0,
    client_store_updated_at: storeLatestUpdatedAtMs(store),
    ops: limited.ops,
    ops_total: Number(limited.totalOps || 0) || 0,
    ops_sent: Number(limited.sentOps || 0) || 0,
    ops_partial: !!limited.partial,
    ops_build_error: String(limited.error || ''),
  };
}
function restorePendingCloudSyncForScope(scopeEmail=currentAccountEmail, opts){
  const normalized = normalizeAccountScopeEmail(scopeEmail);
  if(!normalized || authKickRedirecting) return false;
  const o = opts || {};
  const pendingRec = readScopedCloudSyncPending(normalized);
  const persistedPayload = String(pendingRec?.payload || '').trim();
  const localDirty = !!readScopedStoreMeta(normalized)?.dirty;
  const allowDirtyFallback = o.allowDirtyFallback === true;
  const fallbackPayload = (allowDirtyFallback && localDirty) ? String(o.payload || getCloudSyncCurrentPayload() || '').trim() : '';
  const payload = String(persistedPayload || fallbackPayload || '').trim();
  if(!payload) return false;
  if(!o.allowStaleAfterCloudAuthority && cloudSyncPendingPredatesAuthoritativeCloud(normalized, pendingRec)){
    clearScopedCloudSyncPending(normalized);
    return false;
  }
  if(!currentCloudStoreRevision){
    const pendingStore = parseCloudSyncPayload(payload);
    if(!hasMeaningfulStoreHistory(pendingStore)) return false;
  }
  if(normalized !== currentAccountEmail) return true;
  if(payload === lastCloudSyncedPayload && currentCloudStoreUpdatedTs > 0){
    clearScopedCloudSyncPending(normalized);
    return false;
  }
  cloudSyncQueuedPayload = payload;
  cloudSyncRetryCount = Math.max(cloudSyncRetryCount, Number(pendingRec?.retryCount || 0) || 0);
  cloudSyncLastReason = String(o.reason || pendingRec?.lastReason || cloudSyncLastReason || '').trim();
  writeScopedCloudSyncPending(normalized, payload, {
    lastReason: cloudSyncLastReason,
    retryCount: cloudSyncRetryCount,
    localUpdatedAt: Number(o.localUpdatedAt || storeLatestUpdatedAtMs(store) || 0) || 0,
  });
  const delayMs = Number(o.delayMs);
  if(!cloudSyncInFlight && !cloudSyncTimer){
    scheduleCloudStoreSyncRetry(Number.isFinite(delayMs) ? delayMs : CLOUD_SYNC_DEBOUNCE_MS, cloudSyncLastReason);
  }
  return true;
}
function readScopedStoreMeta(scopeEmail=currentAccountEmail){
  const key = buildScopedStoreMetaKey(scopeEmail);
  try{
    const raw = localStorage.getItem(key);
    if(!raw) return {};
    const obj = JSON.parse(raw);
    return (obj && typeof obj === 'object') ? obj : {};
  }catch(_){
    return {};
  }
}
function writeScopedStoreMeta(scopeEmail=currentAccountEmail, patch=null){
  const normalizedEmail = normalizeAccountScopeEmail(scopeEmail);
  if(!normalizedEmail) return {};
  const key = buildScopedStoreMetaKey(normalizedEmail);
  const prev = readScopedStoreMeta(normalizedEmail);
  const next = { ...(prev && typeof prev === 'object' ? prev : {}) };
  if(patch && typeof patch === 'object'){
    for(const [k, v] of Object.entries(patch)){
      if(v === undefined) delete next[k];
      else next[k] = v;
    }
  }
  try{
    localStorage.setItem(key, JSON.stringify(next));
  }catch(_){ }
  return next;
}
function markScopedStoreDirty(scopeEmail=currentAccountEmail, info=null){
  const normalizedEmail = normalizeAccountScopeEmail(scopeEmail);
  if(!normalizedEmail) return {};
  const localUpdatedAt = Number(info?.localUpdatedAt || storeLatestUpdatedAtMs(store) || now()) || now();
  return writeScopedStoreMeta(normalizedEmail, {
    dirty: true,
    localUpdatedAt,
    localSavedAt: now(),
  });
}
function clearScopedStoreDirty(scopeEmail=currentAccountEmail, info=null){
  const normalizedEmail = normalizeAccountScopeEmail(scopeEmail);
  if(!normalizedEmail) return {};
  const cloudUpdatedTs = Number(info?.cloudUpdatedTs || currentCloudStoreUpdatedTs || 0) || 0;
  const localUpdatedAt = Number(info?.localUpdatedAt || storeLatestUpdatedAtMs(store) || 0) || 0;
  return writeScopedStoreMeta(normalizedEmail, {
    dirty: false,
    localUpdatedAt,
    localSavedAt: now(),
    lastSyncedAt: now(),
    cloudUpdatedTs,
    cloudAuthoritativeAt: info?.authoritative === false ? undefined : now(),
  });
}
function isValidStoreShape(candidate){
  if(!candidate || typeof candidate !== 'object') return false;
  if(!candidate.sessions || typeof candidate.sessions !== 'object' || Array.isArray(candidate.sessions)) return false;
  const active = candidate.activeId;
  return active === null || active === undefined || typeof active === 'string';
}
function normalizeStoreActiveIdInPlace(candidate){
  if(!isValidStoreShape(candidate)) return false;
  const sessions = candidate.sessions || {};
  const ids = Object.keys(sessions).filter(id => id && sessions[id]);
  const activeId = String(candidate.activeId || '').trim();
  if(activeId && sessions[activeId]) return false;
  candidate.activeId = ids[0] || null;
  return true;
}
function storeHasActiveSession(candidate){
  if(!isValidStoreShape(candidate)) return false;
  const activeId = String(candidate.activeId || '').trim();
  return !!(activeId && candidate.sessions?.[activeId]);
}
function cloneStoreDeep(candidate){
  try{ return JSON.parse(JSON.stringify(candidate)); }catch(_){ return null; }
}
function countStoreMessageEntries(candidate){
  if(!isValidStoreShape(candidate)) return 0;
  let total = 0;
  for(const session of Object.values(candidate.sessions || {})){
    total += Array.isArray(session?.messages) ? session.messages.length : 0;
  }
  return total;
}
function hasMeaningfulStoreHistory(candidate){
  return countStoreMessageEntries(candidate) > 1;
}
function sessionObjectLastVisibleMessageIsAssistant(session){
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  for(let i = rows.length - 1; i >= 0; i--){
    const msg = rows[i];
    if(!msg || String(msg.role || '').toLowerCase() === 'system') continue;
    return String(msg.role || '').toLowerCase() === 'assistant';
  }
  return false;
}
function sessionHasTerminalBackendErrorForPendingAssistant(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(String(s.pendingJobId || '').trim()) return false;
  try{ return !!normalizeSessionBackendErrorPayload(s.lastBackendError || null); }catch(_){ return !!s.lastBackendError; }
}

const PENDING_ASSISTANT_FIELD_NAMES = [
  'pendingAssistantDraft',
  'pendingAssistantStatus',
  'pendingAssistantProcess',
  'pendingAssistantStreaming',
  'pendingAssistantFiles',
  'pendingAssistantImageReplies',
  'pendingAssistantWeatherPayload',
  'pendingAssistantReasoning',
  'pendingAssistantReasoningMeta',
  'pendingAssistantSources',
  'pendingAssistantRtStartAt',
  'pendingAssistantRtFinalMs',
  'pendingAssistantUpdatedAt',
  'pendingAssistantTurnKey',
  'pendingAssistantUserCreatedAtMs',
];
function clearPendingAssistantFieldsFromSession(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  let changed = false;
  for(const key of PENDING_ASSISTANT_FIELD_NAMES){
    if(Object.prototype.hasOwnProperty.call(s, key)){
      delete s[key];
      changed = true;
    }
  }
  return changed;
}

function repairChatRuntimeStateInStore(candidate, reason=''){
  const storeObj = candidate && typeof candidate === 'object' ? candidate : null;
  if(!storeObj || !storeObj.sessions || typeof storeObj.sessions !== 'object') return false;
  let changed = false;
  const runtimeOnlyKeys = [
    'pendingJobId','pendingJobCursor','pendingJobTurnKey',
    'pendingAssistantDraft','pendingAssistantStatus','pendingAssistantProcess','pendingAssistantStreaming',
    'pendingAssistantFiles','pendingAssistantImageReplies','pendingAssistantWeatherPayload','pendingAssistantReasoning','pendingAssistantReasoningMeta',
    'pendingAssistantSources','pendingAssistantRtStartAt','pendingAssistantRtFinalMs','pendingAssistantUpdatedAt',
    'pendingAssistantTurnKey','pendingAssistantUserCreatedAtMs','_webaiActiveBranchGroupId','_webaiActiveBranchStart'
  ];
  const stripBrokenBranchMessageMeta = (msg)=>{
    if(!msg || typeof msg !== 'object') return false;
    let did = false;
    for(const key of [
      '_webai_branch_group_id','_webaiBranchGroupId','branch_group_id',
      '_webai_branch_active_index','_webaiBranchActiveIndex',
      '_webai_branch_total','_webaiBranchTotal','_webai_branch_pos','_webaiBranchPos'
    ]){
      if(Object.prototype.hasOwnProperty.call(msg, key)){
        delete msg[key];
        did = true;
      }
    }
    return did;
  };
  for(const session of Object.values(storeObj.sessions || {})){
    if(!session || typeof session !== 'object') continue;
    const messages = Array.isArray(session.messages) ? session.messages : [];
    for(const msg of messages){
      if(stripBrokenBranchMessageMeta(msg)) changed = true;
    }
    if(session._webaiBranchGroups && typeof session._webaiBranchGroups === 'object'){
      delete session._webaiBranchGroups;
      changed = true;
    }
    for(const key of runtimeOnlyKeys){
      if(Object.prototype.hasOwnProperty.call(session, key)){
        delete session[key];
        changed = true;
      }
    }
    if(session.rtStartAt || session.rtFinalMs){
      session.rtStartAt = 0;
      session.rtFinalMs = 0;
      changed = true;
    }
  }
  return changed;
}
function sessionHasPendingAssistantStateFields(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(String(s.pendingAssistantDraft || '').trim()) return true;
  if(String(s.pendingAssistantStatus || '').trim()) return true;
  if(String(s.pendingAssistantProcess || '').trim()) return true;
  if(!!s.pendingAssistantStreaming) return true;
  if(Array.isArray(s.pendingAssistantFiles) && s.pendingAssistantFiles.length) return true;
  if(Array.isArray(s.pendingAssistantImageReplies) && s.pendingAssistantImageReplies.length) return true;
  if(normalizeAssistantWeatherPayload(s.pendingAssistantWeatherPayload || null)) return true;
  if(Array.isArray(s.pendingAssistantReasoning) && s.pendingAssistantReasoning.length) return true;
  if(s.pendingAssistantReasoningMeta && typeof s.pendingAssistantReasoningMeta === 'object'){
    const meta = _normalizePendingAssistantReasoningMeta(s.pendingAssistantReasoningMeta);
    if(Object.keys(meta).length) return true;
  }
  if(Array.isArray(s.pendingAssistantSources) && s.pendingAssistantSources.length) return true;
  return false;
}
function pendingAssistantTimestampMs(value){
  const n = Number(value || 0);
  if(!Number.isFinite(n) || n <= 0) return 0;
  return n < 100000000000 ? n * 1000 : n;
}
function pendingAssistantBelongsToCurrentTurn(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(!sessionHasPendingAssistantStateFields(s)) return false;
  const latestUserMs = _rtLatestUserCreatedMs(s);
  const hasPendingJob = String(s.pendingJobId || '').trim();
  if(!latestUserMs) return !!hasPendingJob;
  if(hasPendingJob) return true;
  const explicitUserMs = pendingAssistantTimestampMs(s.pendingAssistantUserCreatedAtMs);
  if(explicitUserMs > 0) return Math.abs(explicitUserMs - latestUserMs) <= 3000;
  const startAt = pendingAssistantTimestampMs(s.pendingAssistantRtStartAt);
  if(startAt > 0) return startAt >= latestUserMs - 3000;
  const updatedAt = pendingAssistantTimestampMs(s.pendingAssistantUpdatedAt);
  if(updatedAt > 0) return updatedAt >= latestUserMs - 3000;
  return false;
}

function sessionHasPendingAssistantSnapshot(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(sessionObjectLastVisibleMessageIsAssistant(s)) return false;
  if(sessionHasTerminalBackendErrorForPendingAssistant(s)) return false;
  if(!sessionHasPendingAssistantStateFields(s)) return false;
  if(!pendingAssistantBelongsToCurrentTurn(s)) return false;
  return true;
}
function storeHasPendingAssistantSnapshot(candidate){
  if(!isValidStoreShape(candidate)) return false;
  return Object.values(candidate.sessions || {}).some(sessionHasPendingAssistantSnapshot);
}

function sessionHasLiveLocalRuntimeForCloud(sessionId, candidate=store){
  const sid = String(sessionId || '').trim();
  const src = isValidStoreShape(candidate) ? candidate : store;
  if(!sid || !isValidStoreShape(src)) return false;
  const session = src.sessions?.[sid];
  if(!session || typeof session !== 'object') return false;
  if(sessionObjectLastVisibleMessageIsAssistant(session)) return false;
  if(String(session.pendingJobId || '').trim()) return true;
  if(sessionHasPendingAssistantSnapshot(session)) return true;
  try{ if(typeof getSessionPendingJobId === 'function' && String(getSessionPendingJobId(sid) || '').trim()) return true; }catch(_){ }
  try{ if(typeof isSessionStreaming === 'function' && isSessionStreaming(sid)) return true; }catch(_){ }
  try{
    const rt = (sessionRuntime && typeof sessionRuntime === 'object') ? (sessionRuntime[sid] || {}) : {};
    if(rt.streaming) return true;
    if(String(rt.statusText || rt.draftText || rt.draftProcessText || '').trim()) return true;
    if(Array.isArray(rt.draftFiles) && rt.draftFiles.length) return true;
    if(Array.isArray(rt.draftImageReplies) && rt.draftImageReplies.length) return true;
    if(normalizeAssistantWeatherPayload(rt.draftWeatherPayload || null)) return true;
    if(Array.isArray(rt.reasoning) && rt.reasoning.length) return true;
    if(Array.isArray(rt.sources) && rt.sources.length) return true;
  }catch(_){ }
  return false;
}

function countCloudMergeVisibleMessages(session){
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  return rows.filter(msg => msg && String(msg.role || '').toLowerCase() !== 'system').length;
}

function sessionHasLocalMessagesMissingFromRemote(remoteSession, localSession){
  const local = localSession && typeof localSession === 'object' ? localSession : null;
  if(!local || !sessionHasMeaningfulConversation(local)) return false;
  const remote = remoteSession && typeof remoteSession === 'object' ? remoteSession : null;
  if(!remote || isCloudSessionStub(remote)) return true;
  const localMessages = Array.isArray(local.messages) ? local.messages : [];
  const remoteMessages = Array.isArray(remote.messages) ? remote.messages : [];
  const localVisible = countCloudMergeVisibleMessages(local);
  const remoteVisible = countCloudMergeVisibleMessages(remote);
  if(localVisible > 0 && remoteVisible < localVisible) return true;
  if(localMessages.length && remoteMessages.length){
    const localPrefixOfRemote = cloudSyncMessageListHasSamePrefix(localMessages, remoteMessages);
    const remotePrefixOfLocal = cloudSyncMessageListHasSamePrefix(remoteMessages, localMessages);
    if(!localPrefixOfRemote && !remotePrefixOfLocal){
      const localUpdated = Number(local.updatedAt || local.updated_at || local.createdAt || local.created_at || 0) || 0;
      const remoteUpdated = Number(remote.updatedAt || remote.updated_at || remote.createdAt || remote.created_at || 0) || 0;
      if(localUpdated > remoteUpdated + 1000) return true;
    }
  }
  return false;
}


function sessionLatestMessageProgressSignature(session){
  const s = session && typeof session === 'object' ? session : null;
  const rows = Array.isArray(s?.messages) ? s.messages.filter(msg => msg && String(msg.role || '').toLowerCase() !== 'system') : [];
  const last = rows.length ? rows[rows.length - 1] : null;
  let lastIdentity = '';
  try{ lastIdentity = messageStableClientIdentity(last) || ''; }catch(_){ lastIdentity = ''; }
  let lastCreated = 0;
  try{ lastCreated = messageCreatedAtComparableMs(last); }catch(_){ lastCreated = 0; }
  let lastLight = '';
  try{ lastLight = chatRenderLightFingerprint(last || null, 900); }catch(_){ lastLight = cloudSyncStableStringify(last || null).slice(0, 900); }
  return [String(rows.length), String(lastCreated || 0), String(lastIdentity || ''), String(lastLight || '')].join('|');
}

function sessionHasMessageProgressMissingFromSource(targetSession, sourceSession){
  const target = targetSession && typeof targetSession === 'object' ? targetSession : null;
  const source = sourceSession && typeof sourceSession === 'object' ? sourceSession : null;
  if(!target || !source || !sessionHasMeaningfulConversation(source)) return false;
  const sourceMessages = Array.isArray(source.messages) ? source.messages : [];
  if(!sourceMessages.length) return false;
  const targetVisible = countCloudMergeVisibleMessages(target);
  const sourceVisible = countCloudMergeVisibleMessages(source);
  // Only a strictly longer visible transcript is message progress.
  // Session updatedAt can change for composer typing/drafts and must not make an
  // older equal-length snapshot overwrite the currently displayed messages.
  return sourceVisible > targetVisible;
}

function preserveSessionMessageProgressFromSource(targetSession, sourceSession){
  const target = targetSession && typeof targetSession === 'object' ? targetSession : null;
  const source = sourceSession && typeof sourceSession === 'object' ? sourceSession : null;
  if(!target || !source || !Array.isArray(source.messages) || !source.messages.length) return false;
  let changed = false;
  if(sessionHasMessageProgressMissingFromSource(target, source)){
    const beforeMessages = cloudSyncStableStringify(target.messages || []);
    target.messages = cloudSyncMergeMessageLists(target.messages || [], source.messages || []);
    if(beforeMessages !== cloudSyncStableStringify(target.messages || [])) changed = true;
  }
  try{ if(preserveSessionUserAttachmentsFromSource(target, source)) changed = true; }catch(_){ }
  return changed;
}

function commitSessionToStoreWithoutRollback(candidateSession){
  const candidate = candidateSession && typeof candidateSession === 'object' ? candidateSession : null;
  const sid = String(candidate?.id || '').trim();
  if(!candidate || !sid) return candidateSession;
  if(isSessionDeletedByTombstones(sid, currentAccountEmail)) return store?.sessions?.[sid] || null;
  const latest = store?.sessions?.[sid];
  if(latest && latest !== candidate && typeof latest === 'object' && sessionHasMeaningfulConversation(latest)){
    const merged = cloudSyncMergeSession(latest, candidate, sid);
    try{ preserveSessionMessageProgressFromSource(merged, latest); }catch(_){ }
    store.sessions[sid] = merged;
    return merged;
  }
  store.sessions[sid] = candidate;
  return candidate;
}

function cloudSyncMergeStorePreservingLiveLocal(remoteStore, localStore=store, opts={}){
  if(!isValidStoreShape(remoteStore)) return remoteStore;
  const local = isValidStoreShape(localStore) ? localStore : store;
  if(!isValidStoreShape(local)) return remoteStore;
  const next = cloneStoreDeep(remoteStore) || JSON.parse(JSON.stringify(remoteStore));
  applySessionDeleteTombstonesToStore(next, currentAccountEmail);
  const localSessions = local.sessions || {};
  const preserveLocalProgress = opts?.preserveLocalProgress === true;
  for(const sid of Object.keys(localSessions)){
    if(isSessionDeletedByTombstones(sid, currentAccountEmail)) continue;
    const localSession = localSessions[sid];
    const remoteSession = next.sessions?.[sid];
    const liveLocal = sessionHasLiveLocalRuntimeForCloud(sid, local);
    const keepLocalBranch = cloudSyncShouldKeepLocalBranchSession(localSession, remoteSession, sid, opts);
    if(keepLocalBranch){
      next.sessions[sid] = cloudSyncCloneLocalBranchAuthoritativeSession(localSession, remoteSession, sid);
    }else if(liveLocal){
      next.sessions[sid] = cloudSyncMergeSession(remoteSession, localSession, sid);
    }else{
      if(remoteSession && localSession){
        if(preserveLocalProgress && sessionHasLocalMessagesMissingFromRemote(remoteSession, localSession)){
          next.sessions[sid] = cloudSyncMergeSession(remoteSession, localSession, sid);
          continue;
        }
        const mergedReadStateSession = cloneStoreDeep(remoteSession) || JSON.parse(JSON.stringify(remoteSession));
        const attachmentChanged = preserveSessionUserAttachmentsFromSource(mergedReadStateSession, localSession);
        const readStateChanged = preserveSessionReadStateFromSource(mergedReadStateSession, localSession) || normalizeSessionUnreadStateAfterMerge(mergedReadStateSession);
        const draftChanged = preserveNewerLocalComposerDraft(mergedReadStateSession, localSession);
        const composerAttachmentChanged = preserveNewerLocalComposerAttachmentDraft(mergedReadStateSession, localSession);
        if(attachmentChanged || readStateChanged || draftChanged || composerAttachmentChanged) next.sessions[sid] = mergedReadStateSession;
      }else if(preserveLocalProgress && localSession && sessionHasMeaningfulConversation(localSession) && !isTemporarySession(localSession)){
        next.sessions[sid] = cloneStoreDeep(localSession) || JSON.parse(JSON.stringify(localSession));
      }else if(localSession && !remoteSession && !isTemporarySession(localSession) && cloudSyncSessionHasProtectedLocalState(localSession)){
        const protectedLocal = cloneStoreDeep(localSession) || JSON.parse(JSON.stringify(localSession));
        cloudSyncEnsureConversationSyncFields(protectedLocal, sid);
        next.sessions[sid] = protectedLocal;
      }
      continue;
    }
    try{
      const pending = pendingAssistantSnapshotForSession(sid, local);
      if(pending){
        next.sessions[sid].pendingAssistantDraft = pending.draft;
        next.sessions[sid].pendingAssistantStatus = pending.status;
        next.sessions[sid].pendingAssistantProcess = pending.process;
        next.sessions[sid].pendingAssistantStreaming = pending.streaming;
        next.sessions[sid].pendingAssistantFiles = pending.files;
        next.sessions[sid].pendingAssistantImageReplies = pending.imageReplies;
        next.sessions[sid].pendingAssistantWeatherPayload = pending.weatherPayload;
        next.sessions[sid].pendingAssistantReasoning = pending.reasoning;
        next.sessions[sid].pendingAssistantReasoningMeta = pending.reasoningMeta;
        next.sessions[sid].pendingAssistantSources = pending.sources;
        next.sessions[sid].pendingAssistantRtStartAt = pending.rtStartAt;
        next.sessions[sid].pendingAssistantRtFinalMs = pending.rtFinalMs;
        next.sessions[sid].pendingAssistantUserCreatedAtMs = pending.userCreatedAtMs || _rtLatestUserCreatedMs(next.sessions[sid]);
        next.sessions[sid].pendingAssistantUpdatedAt = pending.updatedAt || Date.now();
      }
    }catch(_){ }
  }
  const preserveActiveId = String(opts?.preserveActiveId || local.activeId || '').trim();
  const preserveActiveSession = preserveActiveId ? local.sessions?.[preserveActiveId] : null;
  if(preserveActiveId && isTemporarySession(preserveActiveSession)){
    const clonedTemporary = cloneTemporarySessionForRuntime(preserveActiveSession);
    if(clonedTemporary){
      next.sessions[preserveActiveId] = clonedTemporary;
      next.activeId = preserveActiveId;
    }
    return next;
  }
  if(preserveActiveId && next.sessions?.[preserveActiveId] && (sessionHasLiveLocalRuntimeForCloud(preserveActiveId, local) || opts?.preserveActive === true || sessionHasLocalMessagesMissingFromRemote(next.sessions[preserveActiveId], preserveActiveSession))){
    next.activeId = preserveActiveId;
  }
  return next;
}

function normalizeComposerQuoteDraftForCloudApply(payload){
  const raw = payload && typeof payload === 'object' ? payload : null;
  if(!raw) return null;
  const text = normalizeAssistantQuoteText(raw.text || '');
  if(!text) return null;
  return {
    text,
    msgIndex: Number.isFinite(raw.msgIndex) ? Number(raw.msgIndex) : null,
    messageId: String(raw.messageId || '').trim().slice(0, 220),
    sourceOffset: Number.isInteger(Number(raw.sourceOffset)) && Number(raw.sourceOffset) >= 0 ? Number(raw.sourceOffset) : null,
  };
}

function normalizeComposerAttachmentDraftForCloudApply(payload){
  const raw = payload && typeof payload === 'object' ? payload : null;
  if(!raw) return { files:[], images:[] };
  const files = (Array.isArray(raw.files) ? raw.files : []).map(normalizeComposerAttachmentDraftFile).filter(isComposerLibraryFileAttachment);
  const images = (Array.isArray(raw.images) ? raw.images : []).map(normalizeComposerAttachmentDraftImage).filter(isComposerRestorableImageAttachment);
  return { files, images };
}

function composerAttachmentDraftHasItems(payload){
  return !!(payload && ((Array.isArray(payload.files) && payload.files.length) || (Array.isArray(payload.images) && payload.images.length)));
}

function captureComposerDraftForStoreApply(preferredSessionId=''){
  const activeId = String(store?.activeId || '').trim();
  const sid = String(preferredSessionId || activeId || '').trim();
  if(!sid || !store?.sessions?.[sid]) return null;
  const isActive = activeId === sid;
  const hasInput = typeof inputEl !== 'undefined' && !!inputEl;
  let inputOwner = '';
  try{ inputOwner = (typeof getComposerInputOwnerSessionId === 'function') ? String(getComposerInputOwnerSessionId() || '').trim() : ''; }catch(_){ inputOwner = ''; }
  const inputBelongsToSid = hasInput && ((inputOwner && inputOwner === sid) || (!inputOwner && isActive));
  const liveDraft = inputBelongsToSid ? String(inputEl.value ?? '') : String(store.sessions[sid]?.composerDraft ?? '');
  const storedDraft = String(store.sessions[sid]?.composerDraft ?? '');
  const liveQuote = (inputBelongsToSid && typeof composerQuoteState !== 'undefined') ? composerQuoteState : store.sessions[sid]?.composerQuoteDraft;
  const quoteDraft = normalizeComposerQuoteDraftForCloudApply(liveQuote);
  const liveAttachments = inputBelongsToSid ? getComposerAttachmentDraftPayload() : store.sessions[sid]?.composerAttachmentDraft;
  const attachmentDraft = normalizeComposerAttachmentDraftForCloudApply(liveAttachments);
  const sourceSession = store.sessions[sid] || {};
  const draftMeta = {};
  for(const key of ['composerDraftUpdatedAt','composerDraftClearedAt','composerDraftSentClearAt','composerDraftClearReason']){
    if(Object.prototype.hasOwnProperty.call(sourceSession, key) && sourceSession[key] !== undefined && sourceSession[key] !== null && sourceSession[key] !== ''){
      draftMeta[key] = sourceSession[key];
    }
  }
  return {
    sessionId: sid,
    draft: liveDraft,
    draftMeta,
    quoteDraft,
    attachmentDraft,
    preserveDraft: inputBelongsToSid || storedDraft.length > 0 || liveDraft.length > 0 || composerDraftMergeStamp(store.sessions[sid]) > 0,
    preserveQuote: !!quoteDraft,
    preserveAttachments: composerAttachmentDraftHasItems(attachmentDraft),
  };
}

function applyComposerDraftSnapshotToStore(snapshot, targetStore=store){
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : null;
  const sid = String(snap?.sessionId || '').trim();
  if(!sid || !targetStore?.sessions?.[sid]) return false;
  const session = targetStore.sessions[sid];
  let changed = false;
  if(snap.preserveDraft){
    const draftSource = { composerDraft: String(snap.draft ?? ''), ...(snap.draftMeta && typeof snap.draftMeta === 'object' ? snap.draftMeta : {}) };
    changed = copyComposerDraftFields(session, draftSource) || changed;
  }
  if(snap.preserveQuote){
    const prev = normalizeComposerQuoteDraftForCloudApply(session.composerQuoteDraft);
    if(cloudSyncStableStringify(prev || null) !== cloudSyncStableStringify(snap.quoteDraft || null)){
      session.composerQuoteDraft = snap.quoteDraft;
      changed = true;
    }
  }else if(snap.preserveDraft && session.composerQuoteDraft){
    delete session.composerQuoteDraft;
    changed = true;
  }
  if(snap.preserveAttachments){
    const nextAttach = normalizeComposerAttachmentDraftForCloudApply(snap.attachmentDraft);
    const prevAttach = normalizeComposerAttachmentDraftForCloudApply(session.composerAttachmentDraft);
    if(cloudSyncStableStringify(prevAttach) !== cloudSyncStableStringify(nextAttach)){
      session.composerAttachmentDraft = nextAttach;
      changed = true;
    }
  }else if(false && snap.preserveDraft && session.composerAttachmentDraft && composerAttachmentDraftHasItems(session.composerAttachmentDraft)){
    // 附件草稿只能由发送成功、用户删除或显式清空来移除。
    // 云端同步 / 重新渲染期间 live composer 可能短暂为空，不能据此清掉库中添加的文件或图片。
    session.composerAttachmentDraft = { files:[], images:[] };
    changed = true;
  }
  return changed;
}

function pendingAssistantSnapshotForSession(sessionId, candidate=store){
  if(!sessionId || !isValidStoreShape(candidate)) return null;
  const s = candidate.sessions?.[sessionId];
  if(sessionObjectLastVisibleMessageIsAssistant(s)) return null;
  if(sessionHasTerminalBackendErrorForPendingAssistant(s)) return null;
  if(!sessionHasPendingAssistantSnapshot(s)) return null;
  return {
    draft: String(s?.pendingAssistantDraft || ''),
    status: String(s?.pendingAssistantStatus || ''),
    process: String(s?.pendingAssistantProcess || ''),
    streaming: !!s?.pendingAssistantStreaming,
    files: _normalizePendingAssistantFiles(s?.pendingAssistantFiles),
    imageReplies: _normalizePendingAssistantImageReplies(s?.pendingAssistantImageReplies),
    weatherPayload: normalizeAssistantWeatherPayload(s?.pendingAssistantWeatherPayload || null),
    reasoning: _normalizePendingAssistantReasoning(s?.pendingAssistantReasoning),
    reasoningMeta: _normalizePendingAssistantReasoningMeta(s?.pendingAssistantReasoningMeta),
    sources: normalizeAssistantSourceItems(s?.pendingAssistantSources),
    rtStartAt: Math.max(0, Number(s?.pendingAssistantRtStartAt || s?.rtStartAt || 0) || 0),
    rtFinalMs: Math.max(0, Number(s?.pendingAssistantRtFinalMs || s?.rtFinalMs || 0) || 0),
    userCreatedAtMs: pendingAssistantTimestampMs(s?.pendingAssistantUserCreatedAtMs),
    updatedAt: Number(s?.pendingAssistantUpdatedAt || s?.updatedAt || 0) || 0,
  };
}
function hydrateSessionRuntimeFromPendingSnapshot(sessionId, opts){
  const o = opts || {};
  const sourceStore = o.store || store;
  const sid = String(sessionId || '').trim();
  const sourceSession = isValidStoreShape(sourceStore) && sid ? sourceStore.sessions?.[sid] : null;
  const rt = ensureSessionRuntime(sessionId);
  if(sessionObjectLastVisibleMessageIsAssistant(sourceSession || getSessionById(sid)) || sessionHasTerminalBackendErrorForPendingAssistant(sourceSession || getSessionById(sid))){
    rt.streaming = false;
    rt.rtStartAt = 0;
    rt.draftText = '';
    rt.statusText = '';
    rt.draftProcessText = '';
    rt.draftFiles = [];
    rt.draftImageReplies = [];
    rt.draftWeatherPayload = null;
    rt.reasoning = [];
    rt.reasoningMeta = {};
    rt.sources = [];
    rt.generationUsage = null;
    return rt;
  }
  const snapshot = pendingAssistantSnapshotForSession(sessionId, sourceStore);
  if(!snapshot) return rt;
  if(!String(rt.draftText || '').trim() && snapshot.draft) rt.draftText = snapshot.draft;
  if(!String(rt.statusText || '').trim() && snapshot.status) rt.statusText = snapshot.status;
  if(!String(rt.draftProcessText || '').trim() && snapshot.process) rt.draftProcessText = snapshot.process;
  if(snapshot.streaming && !rt.streaming) rt.streaming = true;
  if(snapshot.streaming && Number(snapshot.rtStartAt || 0) > 0) rt.rtStartAt = _rtNormalizeStartAtForSession(sessionId, Number(snapshot.rtStartAt || 0));
  if(Number(snapshot.rtFinalMs || 0) > 0) rt.rtFinalMs = _rtClampElapsedMsForSession(sessionId, Number(snapshot.rtFinalMs || 0));
  if(Array.isArray(snapshot.files) && snapshot.files.length){
    rt.draftFiles = _normalizePendingAssistantFiles([...(Array.isArray(rt.draftFiles) ? rt.draftFiles : []), ...snapshot.files]);
  }
  if(Array.isArray(snapshot.imageReplies) && snapshot.imageReplies.length){
    rt.draftImageReplies = _normalizePendingAssistantImageReplies([...(Array.isArray(rt.draftImageReplies) ? rt.draftImageReplies : []), ...snapshot.imageReplies]);
  }
  if(normalizeAssistantWeatherPayload(snapshot.weatherPayload || null)){
    rt.draftWeatherPayload = normalizeAssistantWeatherPayload(snapshot.weatherPayload);
  }
  if(Array.isArray(snapshot.reasoning) && snapshot.reasoning.length){
    rt.reasoning = _normalizePendingAssistantReasoning([...(Array.isArray(rt.reasoning) ? rt.reasoning : []), ...snapshot.reasoning]);
  }
  const reasoningMeta = _normalizePendingAssistantReasoningMeta(snapshot.reasoningMeta);
  if(Object.keys(reasoningMeta).length){
    rt.reasoningMeta = { ..._normalizePendingAssistantReasoningMeta(rt.reasoningMeta), ...reasoningMeta };
  }
  if(Array.isArray(snapshot.sources) && snapshot.sources.length){
    rt.sources = mergeAssistantSourceItems(Array.isArray(rt.sources) ? rt.sources : [], snapshot.sources);
  }
  return rt;
}
function storeLatestUpdatedAtMs(candidate){
  if(!isValidStoreShape(candidate)) return 0;
  let latest = 0;
  for(const session of Object.values(candidate.sessions || {})){
    const ts = sessionRealUpdatedAtMs(session);
    if(ts > latest) latest = ts;
  }
  return latest;
}
function updateAccountChatLimits(limits){
  const next = { ...ACCOUNT_CHAT_LIMITS_DEFAULTS };
  if(limits && typeof limits === 'object'){
    const maxSessions = Number(limits.max_sessions ?? limits.maxSessions);
    const maxMessages = Number(limits.max_messages_per_session ?? limits.maxMessagesPerSession);
    const maxChars = Number(limits.max_text_chars ?? limits.maxTextChars);
    const maxBytes = Number(limits.max_store_bytes ?? limits.maxStoreBytes);
    if(Number.isFinite(maxSessions) && maxSessions > 0) next.maxSessions = Math.max(1, Math.floor(maxSessions));
    if(Number.isFinite(maxMessages) && maxMessages > 0) next.maxMessagesPerSession = Math.max(1, Math.floor(maxMessages));
    if(Number.isFinite(maxChars) && maxChars > 0) next.maxTextChars = Math.max(200, Math.floor(maxChars));
    if(Number.isFinite(maxBytes) && maxBytes > 0) next.maxStoreBytes = Math.max(1024, Math.floor(maxBytes));
  }
  accountChatLimits = next;
  return accountChatLimits;
}
function getAccountSessionLimit(){
  const raw = Number(accountChatLimits?.maxSessions ?? ACCOUNT_CHAT_LIMITS_DEFAULTS.maxSessions);
  if(Number.isFinite(raw) && raw > 0) return Math.max(1, Math.floor(raw));
  return 0;
}
function sortStoreSessionIdsByRecency(candidate){
  if(!isValidStoreShape(candidate)) return [];
  return Object.values(candidate.sessions || {})
    .filter(session => session && typeof session === 'object' && session.id)
    .sort((a, b)=>{
      const aUpdated = sessionRealUpdatedAtMs(a);
      const bUpdated = sessionRealUpdatedAtMs(b);
      if(bUpdated !== aUpdated) return bUpdated - aUpdated;
      const aCreated = Number(a.createdAt || a.created_at || 0) || 0;
      const bCreated = Number(b.createdAt || b.created_at || 0) || 0;
      if(bCreated !== aCreated) return bCreated - aCreated;
      return String(a.id || '').localeCompare(String(b.id || ''));
    })
    .map(session => String(session.id || '').trim())
    .filter(Boolean);
}
function enforceAccountStoreLimitsInPlace(reason=''){
  if(!currentAccountEmail || !isValidStoreShape(store)) return false;
  const maxSessions = getAccountSessionLimit();
  if(!(maxSessions > 0)) return false;
  const orderedIds = sortStoreSessionIdsByRecency(store);
  if(orderedIds.length <= maxSessions) return false;
  const keep = new Set();
  const activeId = String(store.activeId || '').trim();
  if(activeId && store.sessions?.[activeId]) keep.add(activeId);
  for(const sid of orderedIds){
    if(keep.size >= maxSessions) break;
    if(store.sessions?.[sid]) keep.add(sid);
  }
  const removed = [];
  for(const sid of Object.keys(store.sessions || {})){
    if(!keep.has(sid)) removed.push(sid);
  }
  if(!removed.length) return false;
  for(const sid of removed){
    try{ delete sessionRuntime[sid]; }catch(_){ }
    try{ delete streamControllers[sid]; }catch(_){ }
    try{ delete streamPromises[sid]; }catch(_){ }
    try{ delete streamAbortReasons[sid]; }catch(_){ }
    delete store.sessions[sid];
  }
  if(!store.sessions?.[store.activeId]){
    store.activeId = orderedIds.find(sid => keep.has(sid)) || Object.keys(store.sessions || {})[0] || null;
  }
  const msg = `账号会话上限 ${maxSessions} 个，已自动清理最旧会话`;
  if(reason !== 'silent'){
    try{ toast(msg); }catch(_){ }
    try{ setStatus(msg); }catch(_){ }
  }
  return true;
}

/* Store persistence, IndexedDB, cloud hydration, and pending assistant snapshots. */
function loadStore(scopeEmail=currentAccountEmail){
  const key = buildScopedStoreKey(scopeEmail);
  try{
    const raw = localStorage.getItem(key);
    if(!raw) return null;
    const obj = JSON.parse(raw);
    if(!isValidStoreShape(obj)) return null;
    cleanLegacyDefaultSystemMessagesFromStore(obj);
    applySessionDeleteTombstonesToStore(obj, scopeEmail);
    normalizeStoreActiveIdInPlace(obj);
    try{ repairChatRuntimeStateInStore(obj, 'loadStore'); }catch(_){ }
    try{ webaiBranchNormalizeActiveViewsInStore(obj, { skipIfLive:false }); }catch(_){ }
    try{ for(const ss of Object.values(obj.sessions || {})) webaiOfficialNormalizeActiveSession(ss, { skipIfLive:false }); }catch(_){ }
    return obj;
  }catch{
    return null;
  }
}


// --- IndexedDB helpers (for large history, avoids localStorage quota) ---
const IDB_DB_NAME = "chat_ui_store";
const IDB_STORE_NAME = "kv";

function idbOpen(){
  return new Promise((resolve, reject)=>{
    if(!("indexedDB" in window)) return reject(new Error("indexedDB not supported"));
    const req = indexedDB.open(IDB_DB_NAME, 2);
    req.onupgradeneeded = ()=>{
      const db = req.result;
      if(!db.objectStoreNames.contains(IDB_STORE_NAME)) db.createObjectStore(IDB_STORE_NAME);
      // store blobs for local image persistence (A+B: keep history slim but previews open)
      if(!db.objectStoreNames.contains("img")) db.createObjectStore("img");
    };
    req.onsuccess = ()=> resolve(req.result);
    req.onerror = ()=> reject(req.error || new Error("idb open failed"));
  });
}
async function idbGet(key){
  const db = await idbOpen();
  return new Promise((resolve, reject)=>{
    const tx = db.transaction(IDB_STORE_NAME, "readonly");
    const os = tx.objectStore(IDB_STORE_NAME);
    const rq = os.get(key);
    rq.onsuccess = ()=> resolve(rq.result ?? null);
    rq.onerror = ()=> reject(rq.error || new Error("idb get failed"));
  });
}
async function idbSet(key, val){
  const db = await idbOpen();
  return new Promise((resolve, reject)=>{
    const tx = db.transaction(IDB_STORE_NAME, "readwrite");
    const os = tx.objectStore(IDB_STORE_NAME);
    const rq = os.put(val, key);
    rq.onsuccess = ()=> resolve(true);
    rq.onerror = ()=> reject(rq.error || new Error("idb put failed"));
  });
}


// --- IndexedDB image blob helpers (persistent original image, keeps chat history slim) ---
async function idbImgGet(id){
  const db = await idbOpen();
  return new Promise((resolve)=>{
    try{
      const tx = db.transaction("img", "readonly");
      const os = tx.objectStore("img");
      const rq = os.get(id);
      rq.onsuccess = ()=> resolve(rq.result ?? null);
      rq.onerror = ()=> resolve(null);
    }catch(e){
      resolve(null);
    }
  });
}
async function idbImgSet(id, blob){
  const db = await idbOpen();
  return new Promise((resolve)=>{
    try{
      const tx = db.transaction("img", "readwrite");
      const os = tx.objectStore("img");
      const rq = os.put(blob, id);
      rq.onsuccess = ()=> resolve(true);
      rq.onerror = ()=> resolve(false);
    }catch(e){
      resolve(false);
    }
  });
}

// Convert 'local://<id>' to a displayable blob URL. Caller should revoke when done.
async function localUrlToObjectUrl(localUrl){
  const id = String(localUrl || "").replace(/^local:\/\//, "");
  if(!id) return "";
  const blob = await idbImgGet(id);
  if(!blob) return "";
  return URL.createObjectURL(blob);
}


// Convert data URL (base64) to Blob
async function dataUrlToBlob(dataUrl){
  try{
    const res = await fetch(dataUrl);
    return await res.blob();
  }catch(e){
    return null;
  }
}

// Set <img> src from normal url or local:// scheme without triggering browser fetch
async function setImgSrcMaybeLocal(imgEl, url, opts={}){
  const u = String(url || "").trim();
  if(!u) return;
  const displayUrl = String(opts.displayUrl || u).trim();
  const rawUrl = String(opts.rawUrl || imgEl?.dataset?.rawSrc || displayUrl).trim();
  const fallbackProxyUrl = buildRemoteImageProxyUrl(displayUrl || rawUrl || u);
  const proxyUrl = String(opts.proxyUrl || imgEl?.dataset?.proxySrc || fallbackProxyUrl).trim();
  const preferDirect = !!(opts.preferDirect || String(imgEl?.dataset?.preferDirect || '').trim() === '1');
  const disableMirror = !!(opts.disableMirror || inlineImageMirrorDisabled(imgEl));
  const sourceType = String(imgEl?.dataset?.sourceType || imgEl?.dataset?.source_type || '').trim().toLowerCase();
  const operation = String(imgEl?.dataset?.operation || imgEl?.dataset?.intent || '').trim().toLowerCase();
  const isSearchImageInline = isImageSearchSourceType(sourceType) || operation === 'image_search' || operation === 'visual_image_search' || operation === 'web_image_search';
  const rawCandidateForDirect = rawUrl || displayUrl || u;
  const isGeneratedImageInline = !isSearchImageInline && (
    sourceType === 'generated' ||
    !!String(imgEl?.dataset?.providerSrc || '').trim() ||
    !!String(imgEl?.dataset?.sourceRole || '').trim()
  );
  const directFirst = isSearchImageInline
    ? !proxyUrl
    : ((preferDirect || disableMirror || (isGeneratedImageInline && /^https?:\/\//i.test(rawCandidateForDirect)))
      ? !!(rawUrl || displayUrl || u)
      : (!proxyUrl && shouldBypassRemoteImageProxy(displayUrl || rawUrl || u)));
  if(displayUrl.startsWith("local://")){
    imgEl.dataset.localId = u.slice("local://".length);
    const objUrl = await localUrlToObjectUrl(u);
    if(objUrl){
      imgEl.dataset.objUrl = objUrl;
      imgEl.src = objUrl;
    }else{
      imgEl.removeAttribute("src");
    }
    return;
  }
  const rawCandidate = rawUrl || displayUrl || u;
  const shouldUseQueuedProxy = !disableMirror && !directFirst && proxyUrl && isRemoteImageProxyUrl(proxyUrl) && /^https?:\/\//i.test(rawCandidate || '');
  if(imgEl){
    imgEl.dataset.rawSrc = rawCandidate;
    if(proxyUrl) imgEl.dataset.proxySrc = proxyUrl;
    if(shouldUseQueuedProxy) imgEl.dataset.providerSrc = rawCandidate;
    imgEl.dataset.srcStage = shouldUseQueuedProxy ? 'proxy-pending' : (directFirst ? 'direct' : 'proxy');
  }
  if(shouldUseQueuedProxy){
    imgEl.src = IMAGE_REMOTE_PLACEHOLDER_URL;
    markInlineImageMirrorPending(imgEl, '图片正在后台拉取中');
    scheduleImageMirrorPoll(imgEl, 'queued-proxy');
  }else{
    imgEl.src = directFirst ? rawCandidate : (proxyUrl || rawCandidate);
    armInlineImageSlowMirrorFallback(imgEl);
  }
}


function configureDeferredInlineImage(img){
  if(!img) return img;
  try{ img.loading = 'lazy'; }catch(_){ }
  try{ img.decoding = 'async'; }catch(_){ }
  try{ img.fetchPriority = 'low'; }catch(_){ }
  img.dataset.lazy = '1';
  img.classList.add('is-loading');
  if(img.dataset.boundLoadState !== '1') {
    img.dataset.boundLoadState = '1';
    const markLoaded = () => {
      img.classList.remove('is-loading');
      img.classList.add('is-loaded');
    };
    img.addEventListener('load', markLoaded, { once:true });
    img.addEventListener('error', () => {
      img.classList.remove('is-loading');
    }, { once:true });
  }
  return img;
}

async function hydrateStoreFromIdb(scopeEmail=currentAccountEmail){
  try{
    const raw = await idbGet(buildScopedStoreKey(scopeEmail));
    if(!raw) return null;
    const obj = JSON.parse(raw);
    if(!isValidStoreShape(obj)) return null;
    cleanLegacyDefaultSystemMessagesFromStore(obj);
    applySessionDeleteTombstonesToStore(obj, scopeEmail);
    normalizeStoreActiveIdInPlace(obj);
    return obj;
  }catch(e){
    console.warn("hydrate from IndexedDB failed:", e);
    return null;
  }
}

async function readPersistedStoreForScope(scopeEmail=currentAccountEmail){
  const fromIdb = await hydrateStoreFromIdb(scopeEmail);
  if(fromIdb) return fromIdb;
  return loadStore(scopeEmail);
}

function buildPersistableStorePayload(sourceStore=store){
  const slim = JSON.parse(JSON.stringify(sourceStore || { sessions:{}, activeId:null }));
  stripTemporarySessionsFromPersistableStore(slim);
  cleanLegacyDefaultSystemMessagesFromStore(slim);
  applySessionDeleteTombstonesToStore(slim, currentAccountEmail);
  for(const sid in (slim.sessions||{})){
    const ss = slim.sessions[sid];
    try{ webaiBranchNormalizeActiveViewInSession(ss, { skipIfLive:true }); }catch(_){ }
    try{ webaiBranchNormalizeVisibleAssistantRunsInSession(ss); }catch(_){ }
    if(!sessionHasPendingAssistantSnapshot(ss)) clearPendingAssistantFieldsFromSession(ss);
    for(const m of (ss.messages||[])){
      const c = m.content;
      if(c && typeof c === "object" && c._kind === "image"){
        if(c.data_url) delete c.data_url;
      }
      if(Array.isArray(c)){
        for(const it of c){
          if(!it || it.type !== "image_url") continue;
          ensureStructuredImagePartDurableUrl(it);
          if(!it.image_url || typeof it.image_url !== "object") it.image_url = { url:"" };
          const currentUrl = String(it.image_url.url || "").trim();
          const displayUrl = composerLibraryDisplayImageUrl(it);
          const durableUrl = composerLibraryDurableImageUrl(it);
          if(displayUrl && (!currentUrl || !composerLibraryBrowserImageSource(currentUrl))){
            it.image_url.url = displayUrl;
          }else if((currentUrl.startsWith("data:") || currentUrl.startsWith("blob:") || currentUrl.startsWith("local://")) && composerLibraryBrowserImageSource(durableUrl)){
            it.image_url.url = durableUrl;
          }else if(!currentUrl && composerLibraryBrowserImageSource(durableUrl)){
            it.image_url.url = durableUrl;
          }
          const finalUrl = String(it.image_url.url || "").trim();
          const finalDisplayUrl = composerLibraryBrowserImageSource(finalUrl) || displayUrl;
          if(finalDisplayUrl){
            if(!String(it.preview_url || "").trim()) it.preview_url = finalDisplayUrl;
            if(!String(it.view_url || "").trim()) it.view_url = finalDisplayUrl;
            if(!String(it.server_url || "").trim()) it.server_url = finalDisplayUrl;
          }
          if(durableUrl){
            if(!String(it.persisted_url || "").trim()) it.persisted_url = durableUrl;
            if(!String(it.model_storage_ref || "").trim()) it.model_storage_ref = durableUrl;
          }
          const previewUrl = String(it._preview_url || "").trim();
          if(previewUrl){
            if(!String(it.preview_url || "").trim() && composerLibraryBrowserImageSource(previewUrl)) it.preview_url = previewUrl;
            if(previewUrl.startsWith("data:") || previewUrl.startsWith("blob:") || finalDisplayUrl) delete it._preview_url;
          }
        }
      }
    }
  }
  return { slim, payload: JSON.stringify(slim) };
}

function storageTextBytes(text){
  const raw = String(text || '');
  try{ return (new TextEncoder()).encode(raw).length; }catch(_){ }
  try{ return new Blob([raw]).size; }catch(_){ }
  return raw.length * 2;
}

function buildTinyLocalStorageStorePayload(slim, opts={}){
  const tiny = JSON.parse(JSON.stringify(slim || { sessions:{}, activeId:null, personalization: normalizePersonalizationState() }));
  const MAX_FULL_SESSIONS_PERSIST = 3;
  const MAX_MSGS_PER_SESSION = 40;
  const MAX_CHARS_PER_MSG = 20000;
  const sessionsArr = Object.values(tiny.sessions || {});
  sessionsArr.sort((a,b)=> (b.updatedAt || 0) - (a.updatedAt || 0));
  const keepFull = new Set(sessionsArr.slice(0, MAX_FULL_SESSIONS_PERSIST).map(s => String(s?.id || '').trim()).filter(Boolean));
  const newSessions = {};
  for(const original of sessionsArr){
    const sid = String(original?.id || '').trim();
    const s = tiny.sessions?.[sid];
    if(!s) continue;
    if(keepFull.has(sid)){
      if(Array.isArray(s.messages) && s.messages.length > MAX_MSGS_PER_SESSION){
        s.messages = s.messages.slice(-MAX_MSGS_PER_SESSION);
      }
      for(const msg of (s.messages || [])){
        if(typeof msg.content === "string" && msg.content.length > MAX_CHARS_PER_MSG){
          msg.content = msg.content.slice(0, MAX_CHARS_PER_MSG) + "\n...(本地降级缓存预览已截断，完整正文仍从 IndexedDB/云端读取)";
        }
      }
      newSessions[sid] = s;
      continue;
    }
    const messages = Array.isArray(s.messages) ? s.messages : [];
    const last = messages.length ? messages[messages.length - 1] : null;
    const preview = typeof last?.content === "string" ? last.content.slice(0, 240) : "";
    newSessions[sid] = {
      id:sid,
      title:String(s.title || "新会话"),
      model:String(s.model || ""),
      createdAt:Number(s.createdAt || s.created_at || 0) || 0,
      updatedAt:Number(s.updatedAt || s.updated_at || 0) || 0,
      archived:!!(s.archived || s.isArchived),
      pinned:!!s.pinned,
      pinnedAt:Number(s.pinnedAt || s.pinned_at || 0) || 0,
      messages:[],
      _cloudStub:true,
      _cloudNeedsHydrate:true,
      _cloudMessageCount:messages.length,
      _cloudLastPreview:preview,
      syncStatus:"hydrate_required",
    };
  }
  tiny.sessions = newSessions;
  if(!tiny.sessions[tiny.activeId]) tiny.activeId = String(sessionsArr[0]?.id || '') || null;
  tiny._localStorageFallback = true;
  tiny._fullStoreInIndexedDB = opts?.fullStoreInIndexedDB !== false;
  if(!tiny._fullStoreInIndexedDB) tiny._indexedDBSaveFailed = true;
  tiny._fallbackSavedAt = Date.now();
  return JSON.stringify(tiny);
}

function persistStorePayloadLocallyFallback(scopedKey, slim, opts={}){
  try{
    const fullStoreInIndexedDB = opts?.fullStoreInIndexedDB !== false;
    localStorage.setItem(scopedKey, buildTinyLocalStorageStorePayload(slim, {
      fullStoreInIndexedDB,
    }));
    if(opts?.warn && typeof setStatus === "function"){
      setStatus(fullStoreInIndexedDB
        ? "⚠️ localStorage 空间不足：已保留全部会话索引，完整正文保存在 IndexedDB"
        : "⚠️ IndexedDB 保存失败：已保留全部会话索引和最近正文，完整历史将从云端恢复");
    }
    return true;
  }catch(e){
    console.warn("tiny localStorage save failed:", e);
    if(typeof setStatus === "function") setStatus("⚠️ 保存失败：本地存储空间不足");
    return false;
  }
}

function persistStorePayloadLocally(payload, slim, scopeEmail=currentAccountEmail){
  const scopedKey = buildScopedStoreKey(scopeEmail);
  const payloadBytes = storageTextBytes(payload);
  const largePayload = payloadBytes > LOCAL_STORAGE_FULL_STORE_SOFT_LIMIT;
  idbSet(scopedKey, payload).catch(e=>{
    console.warn("IndexedDB save failed:", e);
    if(largePayload){
      persistStorePayloadLocallyFallback(scopedKey, slim, { warn:true, fullStoreInIndexedDB:false });
    }
  });

  if(largePayload){
    persistStorePayloadLocallyFallback(scopedKey, slim, { warn:false, fullStoreInIndexedDB:true });
    return;
  }

  try{
    localStorage.setItem(scopedKey, payload);
    return;
  }catch(e){
    console.warn("localStorage save failed:", e);
  }

  persistStorePayloadLocallyFallback(scopedKey, slim, { warn:true });
}

function isLocalStorageFallbackStorePayload(value){
  return !!(value && typeof value === "object" && value._localStorageFallback === true);
}

async function fetchCloudStoreSnapshot(){
  if(!currentAccountEmail || authKickRedirecting) return null;
  const ctl = new AbortController();
  const timeoutId = setTimeout(()=>{
    try{ ctl.abort('cloud_store_snapshot_timeout'); }catch(_){ }
  }, computeWeakFetchTimeoutMs('cloud_get'));
  let res = null;
  let data = {};
  try{
    res = await fetch('/api3/chat-sync/store', { cache:'no-store', credentials:'same-origin', signal: ctl.signal });
    data = await res.json().catch(()=>({}));
  }catch(err){
    if(isFetchAbortLikeError(err)) return null;
    throw err;
  }finally{
    try{ clearTimeout(timeoutId); }catch(_){ }
  }
  if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')) return null;
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  updateAccountChatLimits(data?.limits);
  const rev = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
  if(rev > 0) currentCloudStoreRevision = rev;
  return data && typeof data === 'object' ? data : null;
}



function isCloudSessionStub(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(s._cloudHydrated === true) return false;
  return !!(s._cloudStub || s.cloud_stub || s._cloudNeedsHydrate || s.cloudNeedsHydrate) && !sessionHasMeaningfulConversation(s);
}

function sessionNeedsCloudHydrate(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(sessionHasMeaningfulConversation(s)) return false;
  if(isCloudSessionStub(s)) return true;
  if(s._cloudNeedsHydrate || s.cloudNeedsHydrate || s._cloudStub || s.cloud_stub) return true;
  if(Number(s._cloudMessageCount || s.message_count || s.messageCount || 0) > 0) return true;
  if(String(s._cloudLastPreview || s.last_preview || s.lastPreview || '').trim()) return true;
  return false;
}

const activeCloudSessionHydrateTimers = new Map();
function scheduleActiveCloudSessionHydrate(reason='', opts={}){
  const sid = String(store?.activeId || '').trim();
  if(!sid || !currentAccountEmail || authKickRedirecting) return false;
  const session = store?.sessions?.[sid];
  if(!sessionNeedsCloudHydrate(session)) return false;
  if(activeCloudSessionHydrateTimers.has(sid)) return true;
  const statusText = String(opts?.statusText || '已加载当前会话').trim();
  const delay = Math.max(0, Number(opts?.delayMs || 0) || 0);
  const timer = setTimeout(()=>{
    activeCloudSessionHydrateTimers.delete(sid);
    if(String(store?.activeId || '').trim() !== sid) return;
    if(!sessionNeedsCloudHydrate(store?.sessions?.[sid])) return;
    try{ hydrateActiveSessionAfterSwitch(sid, { force:!!opts?.force, statusText }).catch(()=>{}); }catch(_){ }
  }, delay);
  activeCloudSessionHydrateTimers.set(sid, timer);
  return true;
}

function clearActiveCloudSessionHydrateTimer(sessionId=''){
  const sid = String(sessionId || store?.activeId || '').trim();
  if(!sid) return;
  const timer = activeCloudSessionHydrateTimers.get(sid);
  if(timer){
    try{ clearTimeout(timer); }catch(_){ }
    activeCloudSessionHydrateTimers.delete(sid);
  }
}

function waitMs(ms){
  return new Promise(resolve => setTimeout(resolve, Math.max(0, Number(ms || 0) || 0)));
}

async function ensureActiveCloudSessionHydratedForReady(reason='', opts={}){
  const sid = String(opts?.sessionId || store?.activeId || '').trim();
  if(!sid || !currentAccountEmail || authKickRedirecting) return { ok:true, needed:false, sid };
  if(!store?.sessions?.[sid]) return { ok:false, needed:true, sid, reason:'missing_local_session' };
  if(!sessionNeedsCloudHydrate(store.sessions[sid])) return { ok:true, needed:false, sid };
  clearActiveCloudSessionHydrateTimer(sid);
  const attempts = Math.max(1, Math.min(3, Number(opts?.attempts || 2) || 2));
  const statusText = String(opts?.loadingText || '正在同步当前会话正文…').trim();
  if(statusText && typeof setStatus === 'function') setStatus(statusText);
  for(let i = 0; i < attempts; i++){
    let hydrated = false;
    try{
      if(typeof hydrateActiveSessionAfterSwitch === 'function'){
        hydrated = await hydrateActiveSessionAfterSwitch(sid, {
          force:true,
          statusText:'',
        });
      }else{
        hydrated = await ensureCloudSessionLoadedIntoStore(sid, { makeActive:true, force:true });
      }
    }catch(e){
      console.warn('[chat-sync] ready hydrate failed:', e);
    }
    if(hydrated || !sessionNeedsCloudHydrate(store?.sessions?.[sid])){
      return { ok:true, needed:true, sid };
    }
    if(i < attempts - 1) await waitMs(350 + i * 450);
  }
  scheduleActiveCloudSessionHydrate(reason || 'ready_gate_retry', {
    delayMs: stableBackoffMs(1, 1600, 12000),
    force:true,
    statusText:'已同步当前会话',
  });
  return { ok:false, needed:true, sid, reason:'hydrate_pending' };
}

function cloudSyncHasUnsettledLocalWork(scopeEmail=currentAccountEmail){
  const email = normalizeAccountScopeEmail(scopeEmail);
  if(!email) return false;
  if(cloudSyncInFlight || cloudSyncQueuedPayload) return true;
  try{ if(getScopedCloudSyncPendingPayload(email)) return true; }catch(_){ }
  try{ if(readScopedStoreMeta(email)?.dirty) return true; }catch(_){ }
  return false;
}

async function waitForCloudSyncSettledForReady(scopeEmail=currentAccountEmail, opts={}){
  const email = normalizeAccountScopeEmail(scopeEmail);
  if(!email || authKickRedirecting) return { ok:true, needed:false };
  if(!cloudSyncHasUnsettledLocalWork(email)) return { ok:true, needed:false };
  const deadline = Date.now() + Math.max(1200, Math.min(12000, Number(opts?.timeoutMs || 6500) || 6500));
  if(typeof setStatus === 'function') setStatus(String(opts?.loadingText || '正在确认账号会话已同步…').trim());
  if(cloudSyncTimer){
    try{ clearTimeout(cloudSyncTimer); }catch(_){ }
    cloudSyncTimer = null;
  }
  while(Date.now() < deadline){
    if(!cloudSyncInFlight){
      try{ await flushCloudStoreSync(); }catch(e){ console.warn('[chat-sync] ready flush failed:', e); }
    }
    if(!cloudSyncHasUnsettledLocalWork(email)) return { ok:true, needed:true };
    await waitMs(450);
  }
  return { ok:false, needed:true, reason:'cloud_sync_pending' };
}

function sessionShouldUseAddressRoute(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s || isTemporarySession(s)) return false;
  if(sessionHasMeaningfulConversation(s)) return true;
  if(isCloudSessionStub(s)) return true;
  if(s._cloudNeedsHydrate || s.cloudNeedsHydrate || s._cloudStub || s.cloud_stub) return true;
  if(Number(s._cloudMessageCount || s.message_count || s.messageCount || 0) > 0) return true;
  if(String(s._cloudLastPreview || s.last_preview || s.lastPreview || '').trim()) return true;
  return false;
}

function normalizeCloudSessionSummary(row){
  const src = row && typeof row === 'object' ? row : {};
  const id = String(src.id || src.session_id || src.sessionId || '').trim();
  if(!id) return null;
  const createdAt = Number((src.createdAt ?? src.created_at_ms ?? src.created_at ?? src.created_ts ?? src.created) || 0) || 0;
  const updatedAt = Number((src.updatedAt ?? src.updated_at_ms ?? src.updated_at ?? src.updated_ts ?? src.updated) || createdAt || Date.now()) || Date.now();
  const mode = normalizeConversationSyncMode(src.conversationMode || src.conversation_mode || src.syncMode || src.sync_mode || src.api_endpoint_mode || src.endpoint_mode || '');
  const endpointMode = String(src.api_endpoint_mode || src.endpoint_mode || cloudSyncCurrentApiEndpointModeForConversation(mode)).trim() || cloudSyncCurrentApiEndpointModeForConversation(mode);
  const localId = String(src.localId || src.local_id || id).trim() || id;
  const opId = String(src.opId || src.op_id || '').trim() || makeCloudSyncOpId('conversation', localId);
  const serverVersion = Number(src.serverVersion || src.server_version || src.revision || src.server_revision || src.cloudRevision || 0) || 0;
  const syncStatus = String(src.syncStatus || src.sync_status || (serverVersion > 0 ? 'active' : 'pending')).trim() || (serverVersion > 0 ? 'active' : 'pending');
  const summary = {
    id,
    localId,
    local_id: localId,
    opId,
    op_id: opId,
    conversationMode: mode,
    conversation_mode: mode,
    api_endpoint_mode: endpointMode,
    endpoint_mode: endpointMode,
    syncStatus,
    sync_status: syncStatus,
    serverVersion,
    server_version: serverVersion,
    conversationRecovery: {
      ...(src.conversationRecovery && typeof src.conversationRecovery === 'object' ? src.conversationRecovery : {}),
      mode,
      local_id: localId,
      server_id: id,
      op_id: opId,
      server_version: serverVersion,
      status: syncStatus,
      updated_at: updatedAt,
    },
    runRecovery: src.runRecovery && typeof src.runRecovery === 'object' ? src.runRecovery : undefined,
    runRecoveryClearedAt: Math.max(0, Number(src.runRecoveryClearedAt || src.run_recovery_cleared_at || 0) || 0),
    title: String(src.title || '').trim() || '新会话',
    model: String(src.model || '').trim() || DEFAULT_MODEL,
    createdAt,
    updatedAt,
    webEnabled: !!src.webEnabled,
    imageGenerationEnabled: !!src.imageGenerationEnabled,
    chatThinkingType: normalizeThinkingType(src.chatThinkingType || src.chat_thinking_type || ''),
    archived: !!src.archived || Number(src.archivedAt || src.archived_at || 0) > 0,
    archivedAt: Number(src.archivedAt || src.archived_at || 0) || 0,
    archived_at: Number(src.archived_at || src.archivedAt || 0) || 0,
    pinned: !!src.pinned,
    pinnedAt: Number(src.pinnedAt || src.pinned_at || 0) || 0,
    pinned_at: Number(src.pinned_at || src.pinnedAt || 0) || 0,
    _cloudStub: true,
    _cloudNeedsHydrate: true,
    _cloudHydrated: false,
    _cloudRevision: Number(src.revision || src.server_revision || src.cloudRevision || 0) || 0,
    _cloudMessageCount: Number(src.message_count || src.messageCount || 0) || 0,
    _cloudLastPreview: String(src.last_preview || src.lastPreview || src.preview || '').trim(),
    messages: [],
  };
  cloudSyncHydrateRunRecoveryRuntimeFields(summary);
  return summary;
}

function buildCloudManifestFromStoreData(data){
  const obj = data && typeof data === 'object' ? data : {};
  const remoteStore = (obj.store && isValidStoreShape(obj.store)) ? obj.store : null;
  if(!remoteStore) return null;
  try{ cloudSyncRehydrateStoreBodiesInPlace(remoteStore); }catch(_){ }
  const rows = Object.values(remoteStore.sessions || {}).map(session => {
    const s = session && typeof session === 'object' ? session : {};
    const messages = Array.isArray(s.messages) ? s.messages : [];
    let lastPreview = '';
    for(let i = messages.length - 1; i >= 0; i--){
      const msg = messages[i];
      if(!msg || msg.role === 'system') continue;
      if(typeof msg.content === 'string') lastPreview = msg.content;
      else if(Array.isArray(msg.content)) lastPreview = msg.content.map(x => String(x?.text || '')).filter(Boolean).join(' ');
      else if(msg.content && typeof msg.content === 'object') lastPreview = String(msg.content.text || msg.content.answer || msg.content.filename || msg.content._kind || '');
      lastPreview = String(lastPreview || '').replace(/\s+/g, ' ').trim().slice(0, 180);
      if(lastPreview) break;
    }
    return {
      id: String(s.id || '').trim(),
      localId: String(s.localId || s.local_id || s.id || '').trim(),
      local_id: String(s.local_id || s.localId || s.id || '').trim(),
      opId: String(s.opId || s.op_id || '').trim(),
      op_id: String(s.op_id || s.opId || '').trim(),
      conversationMode: sessionConversationMode(s),
      conversation_mode: sessionConversationMode(s),
      api_endpoint_mode: String(s.api_endpoint_mode || s.endpoint_mode || cloudSyncCurrentApiEndpointModeForConversation(sessionConversationMode(s))).trim(),
      endpoint_mode: String(s.endpoint_mode || s.api_endpoint_mode || cloudSyncCurrentApiEndpointModeForConversation(sessionConversationMode(s))).trim(),
      syncStatus: String(s.syncStatus || s.sync_status || '').trim(),
      sync_status: String(s.sync_status || s.syncStatus || '').trim(),
      serverVersion: Number(s.serverVersion || s.server_version || 0) || 0,
      server_version: Number(s.server_version || s.serverVersion || 0) || 0,
      conversationRecovery: s.conversationRecovery && typeof s.conversationRecovery === 'object' ? s.conversationRecovery : null,
      runRecovery: s.runRecovery && typeof s.runRecovery === 'object' ? s.runRecovery : null,
      runRecoveryClearedAt: Math.max(0, Number(s.runRecoveryClearedAt || s.run_recovery_cleared_at || 0) || 0),
      title: String(s.title || '').trim() || '新会话',
      model: String(s.model || '').trim() || DEFAULT_MODEL,
      createdAt: Number(s.createdAt || s.created_at || 0) || 0,
      updatedAt: Number(s.updatedAt || s.updated_at || 0) || 0,
      webEnabled: !!s.webEnabled,
      imageGenerationEnabled: !!s.imageGenerationEnabled,
      chatThinkingType: normalizeThinkingType(s.chatThinkingType || ''),
      archived: isSessionArchived(s),
      archivedAt: getSessionArchivedAtMs(s),
      archived_at: getSessionArchivedAtMs(s),
      pinned: !!s.pinned,
      pinnedAt: Number(s.pinnedAt || s.pinned_at || 0) || 0,
      pinned_at: Number(s.pinned_at || s.pinnedAt || 0) || 0,
      message_count: messages.filter(m => m && m.role !== 'system').length,
      last_preview: lastPreview,
    };
  }).filter(x => x.id);
  return {
    ok: true,
    email: obj.email || currentAccountEmail,
    active_id: String(remoteStore.activeId || '').trim(),
    activeId: String(remoteStore.activeId || '').trim(),
    personalization: remoteStore.personalization || {},
    sessions: rows,
    updated_ts: Number(obj.updated_ts || 0) || 0,
    revision: Number(obj.server_revision ?? obj.revision ?? 0) || 0,
    server_revision: Number(obj.server_revision ?? obj.revision ?? 0) || 0,
    sync_protocol: 'manifest_from_store_fallback',
    limits: obj.limits,
    _fullStore: remoteStore,
  };
}

async function fetchCloudManifestSnapshot(){
  if(!currentAccountEmail || authKickRedirecting) return null;
  const ctl = new AbortController();
  const timeoutId = setTimeout(()=>{
    try{ ctl.abort('cloud_manifest_timeout'); }catch(_){ }
  }, computeWeakFetchTimeoutMs('manifest_get'));
  let res = null;
  let data = {};
  try{
    res = await fetch('/api3/chat-sync/manifest?limit=300', { cache:'no-store', credentials:'same-origin', signal: ctl.signal });
    data = await res.json().catch(()=>({}));
  }catch(err){
    if(isFetchAbortLikeError(err)) return null;
    throw err;
  }finally{
    try{ clearTimeout(timeoutId); }catch(_){ }
  }
  if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')) return null;
  if(res.status === 404){
    const fullData = await fetchCloudStoreSnapshot();
    return buildCloudManifestFromStoreData(fullData);
  }
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  updateAccountChatLimits(data?.limits);
  const rev = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
  if(rev > 0) currentCloudStoreRevision = rev;
  return data && typeof data === 'object' ? data : null;
}

function mergeCloudManifestIntoLocalStore(localStore, manifestData, opts={}){
  const o = opts || {};
  const local = isValidStoreShape(localStore) ? JSON.parse(JSON.stringify(localStore)) : { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
  const cloudTombstones = receiveCloudSessionDeleteTombstones(manifestData, currentAccountEmail);
  applySessionDeleteTombstonesToStore(local, currentAccountEmail, cloudTombstones);
  const localSessions = (local.sessions && typeof local.sessions === 'object') ? local.sessions : {};
  const rows = Array.isArray(manifestData?.sessions) ? manifestData.sessions : [];
  const nextSessions = {};
  const manifestIds = new Set();
  for(const row of rows){
    const summary = normalizeCloudSessionSummary(row);
    if(!summary || isSessionDeletedByTombstones(summary.id, currentAccountEmail, cloudTombstones)) continue;
    manifestIds.add(summary.id);
    const existing = localSessions[summary.id] && typeof localSessions[summary.id] === 'object' ? localSessions[summary.id] : null;
    const useLocalHydratedContent = o.useLocalHydratedContent !== false;
    const existingUpdated = Number(existing?.updatedAt || existing?.updated_at || existing?.createdAt || existing?.created_at || 0) || 0;
    const summaryUpdated = Number(summary.updatedAt || summary.updated_at || summary.createdAt || summary.created_at || 0) || 0;
    const localHydratedStillCurrent = !!(existingUpdated > 0 && summaryUpdated > 0 && existingUpdated >= summaryUpdated);
    if(useLocalHydratedContent && existing && sessionHasMeaningfulConversation(existing) && (o.allowStaleHydratedContent === true || localHydratedStillCurrent)){
      nextSessions[summary.id] = {
        ...existing,
        localId: existing.localId || existing.local_id || summary.localId,
        local_id: existing.local_id || existing.localId || summary.local_id,
        opId: existing.opId || existing.op_id || summary.opId,
        op_id: existing.op_id || existing.opId || summary.op_id,
        conversationMode: sessionConversationMode(existing, summary.conversationMode),
        conversation_mode: sessionConversationMode(existing, summary.conversation_mode),
        api_endpoint_mode: existing.api_endpoint_mode || existing.endpoint_mode || summary.api_endpoint_mode,
        endpoint_mode: existing.endpoint_mode || existing.api_endpoint_mode || summary.endpoint_mode,
        syncStatus: cloudSyncSessionHasProtectedLocalState(existing) ? (existing.syncStatus || existing.sync_status || summary.syncStatus) : (summary.syncStatus || existing.syncStatus || existing.sync_status),
        sync_status: cloudSyncSessionHasProtectedLocalState(existing) ? (existing.sync_status || existing.syncStatus || summary.sync_status) : (summary.sync_status || existing.sync_status || existing.syncStatus),
        serverVersion: Math.max(Number(existing.serverVersion || existing.server_version || 0) || 0, Number(summary.serverVersion || summary.server_version || 0) || 0),
        server_version: Math.max(Number(existing.server_version || existing.serverVersion || 0) || 0, Number(summary.server_version || summary.serverVersion || 0) || 0),
        conversationRecovery: { ...(summary.conversationRecovery || {}), ...(existing.conversationRecovery || {}) },
        runRecovery: existing.runRecovery || summary.runRecovery || null,
        title: String(existing.title || summary.title || '新会话'),
        model: String(existing.model || summary.model || DEFAULT_MODEL),
        updatedAt: Math.max(Number(existing.updatedAt || 0) || 0, Number(summary.updatedAt || 0) || 0),
        createdAt: Number(existing.createdAt || summary.createdAt || Date.now()) || Date.now(),
        archived: !!(isSessionArchived(existing) || isSessionArchived(summary)),
        archivedAt: getSessionArchivedAtMs(existing) || getSessionArchivedAtMs(summary),
        archived_at: getSessionArchivedAtMs(existing) || getSessionArchivedAtMs(summary),
        _cloudStub: false,
        _cloudNeedsHydrate: false,
        _cloudHydrated: true,
        _cloudMessageCount: summary._cloudMessageCount,
        _cloudLastPreview: summary._cloudLastPreview,
      };
    }else{
      nextSessions[summary.id] = summary;
    }
  }
  if(o.preserveLocalExtra){
    for(const [sid, session] of Object.entries(localSessions)){
      if(!sid || manifestIds.has(sid) || !session || typeof session !== 'object') continue;
      if(isSessionDeletedByTombstones(sid, currentAccountEmail, cloudTombstones)) continue;
      nextSessions[sid] = session;
    }
  }else{
    for(const [sid, session] of Object.entries(localSessions)){
      if(!sid || manifestIds.has(sid) || !session || typeof session !== 'object') continue;
      if(isSessionDeletedByTombstones(sid, currentAccountEmail, cloudTombstones)) continue;
      if(cloudSyncSessionHasProtectedLocalState(session) || (sessionHasMeaningfulConversation(session) && Number(session.serverVersion || session.server_version || 0) <= 0)){
        const cloned = cloneStoreDeep(session) || JSON.parse(JSON.stringify(session));
        cloudSyncEnsureConversationSyncFields(cloned, sid);
        nextSessions[sid] = cloned;
      }
    }
  }
  let activeId = String(manifestData?.active_id || manifestData?.activeId || local.activeId || '').trim();
  if(!activeId || !nextSessions[activeId]) activeId = Object.keys(nextSessions)[0] || null;
  const nextStore = {
    ...local,
    sessions: nextSessions,
    activeId,
    personalization: (manifestData?.personalization && typeof manifestData.personalization === 'object') ? manifestData.personalization : (local.personalization || normalizePersonalizationState()),
  };
  normalizeStoreActiveIdInPlace(nextStore);
  return nextStore;
}

function buildCloudManifestBaselineStore(manifestData, personalizationFallback=null){
  const personalization = (manifestData?.personalization && typeof manifestData.personalization === 'object')
    ? manifestData.personalization
    : normalizePersonalizationState(personalizationFallback || {});
  return mergeCloudManifestIntoLocalStore(
    { sessions:{}, activeId:null, personalization },
    manifestData,
    { preserveLocalExtra:false, useLocalHydratedContent:false }
  );
}

async function fetchCloudSessionSnapshot(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid || !currentAccountEmail || authKickRedirecting) return null;
  const ctl = new AbortController();
  const timeoutId = setTimeout(()=>{
    try{ ctl.abort('cloud_session_timeout'); }catch(_){ }
  }, computeWeakFetchTimeoutMs('session_get'));
  let res = null;
  let data = {};
  try{
    const url = '/api3/chat-sync/session?id=' + encodeURIComponent(sid);
    res = await fetch(url, { cache:'no-store', credentials:'same-origin', signal: ctl.signal });
    data = await res.json().catch(()=>({}));
  }catch(err){
    if(isFetchAbortLikeError(err)) return null;
    throw err;
  }finally{
    try{ clearTimeout(timeoutId); }catch(_){ }
  }
  if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')) return null;
  if(res.status === 404){
    const fullData = await fetchCloudStoreSnapshot();
    const fullStore = (fullData?.store && isValidStoreShape(fullData.store)) ? fullData.store : null;
    if(fullStore?.sessions?.[sid]){
      return { ...fullData, session: fullStore.sessions[sid], session_id: sid, sync_protocol:'session_from_store_fallback' };
    }
    return null;
  }
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  updateAccountChatLimits(data?.limits);
  const rev = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
  if(rev > 0) currentCloudStoreRevision = rev;
  return data && typeof data === 'object' ? data : null;
}

function normalizeCloudSessionSnapshotForStore(data, sessionId){
  const sid = String(sessionId || data?.session_id || data?.sessionId || data?.session?.id || '').trim();
  const remoteSession = data?.session && typeof data.session === 'object' ? data.session : null;
  if(!sid || !remoteSession) return null;
  let nextSession = null;
  try{ nextSession = JSON.parse(JSON.stringify(remoteSession)); }catch(_){ nextSession = { ...remoteSession }; }
  if(!nextSession || typeof nextSession !== 'object') return null;
  nextSession.id = String(nextSession.id || sid).trim() || sid;
  nextSession._cloudStub = false;
  nextSession._cloudNeedsHydrate = false;
  nextSession._cloudHydrated = true;
  cloudSyncHydrateRunRecoveryRuntimeFields(nextSession);
  return {
    sid,
    session: nextSession,
    updatedTs: Number(data?.updated_ts || 0) || 0,
    revision: Number(data?.server_revision ?? data?.revision ?? 0) || 0,
  };
}

function cloudSyncApplyAuthoritativeRemoteSession(previousSession, remoteSession, sid){
  const sessionId = String(sid || remoteSession?.id || previousSession?.id || '').trim();
  const remote = remoteSession && typeof remoteSession === 'object' ? (cloneStoreDeep(remoteSession) || JSON.parse(JSON.stringify(remoteSession))) : null;
  if(!remote || !sessionId) return remoteSession;
  const previous = previousSession && typeof previousSession === 'object' ? previousSession : {};
  remote.id = String(remote.id || sessionId).trim() || sessionId;
  remote._cloudStub = false;
  remote._cloudNeedsHydrate = false;
  remote._cloudHydrated = true;
  if(cloudSyncShouldKeepLocalBranchSession(previous, remote, sessionId, { preserveActiveId: store?.activeId || sessionId })){
    const local = cloudSyncCloneLocalBranchAuthoritativeSession(previous, remote, sessionId);
    try{ preserveConversationSyncRecoveryFields(local, remote); }catch(_){ }
    const remoteVersion = Number(remote.serverVersion || remote.server_version || 0) || 0;
    if(remoteVersion > 0){
      local.serverVersion = Math.max(Number(local.serverVersion || local.server_version || 0) || 0, remoteVersion);
      local.server_version = local.serverVersion;
    }
    return local;
  }
  try{ preserveSessionMessageProgressFromSource(remote, previous); }catch(_){ }
  try{ preserveSessionUserAttachmentsFromSource(remote, previous); }catch(_){ }
  preserveSessionReadStateFromSource(remote, previous);
  preserveNewerLocalComposerDraft(remote, previous);
  preserveNewerLocalComposerAttachmentDraft(remote, previous);
  try{
    if(typeof applyComposerAttachmentDraftRuntimeGuardToSession === 'function') applyComposerAttachmentDraftRuntimeGuardToSession(remote, sessionId);
  }catch(_){ }
  normalizeSessionUnreadStateAfterMerge(remote);
  cloudSyncHydrateRunRecoveryRuntimeFields(remote);
  if(!sessionHasPendingAssistantSnapshot(remote)) clearPendingAssistantFieldsFromSession(remote);
  return remote;
}

function importCloudSessionSnapshotIntoStore(data, sessionId, opts={}){
  const normalized = normalizeCloudSessionSnapshotForStore(data, sessionId);
  if(!normalized) return false;
  if(!isValidStoreShape(store)){
    store = { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
  }
  if(!store.sessions || typeof store.sessions !== 'object') store.sessions = {};
  const sid = normalized.sid;
  if(isSessionDeletedByTombstones(sid, currentAccountEmail, extractCloudSessionDeleteTombstones(data))) return false;
  const previous = store.sessions?.[sid] && typeof store.sessions[sid] === 'object' ? store.sessions[sid] : {};
  if(sessionHasLiveLocalRuntimeForCloud(sid, store) && sessionHasMeaningfulConversation(previous)) return false;
  store.sessions[sid] = cloudSyncApplyAuthoritativeRemoteSession(previous, normalized.session, sid);
  if(opts.makeActive || !store.activeId || !store.sessions[store.activeId]) store.activeId = sid;
  if(normalized.updatedTs > 0) currentCloudStoreUpdatedTs = Math.max(Number(currentCloudStoreUpdatedTs || 0) || 0, normalized.updatedTs);
  if(normalized.revision > 0) currentCloudStoreRevision = normalized.revision;
  return true;
}

async function ensureCloudSessionLoadedIntoStore(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid || !currentAccountEmail || authKickRedirecting) return false;
  const existing = store?.sessions?.[sid];
  if(existing && !opts.force && !sessionNeedsCloudHydrate(existing)) return false;
  const data = await fetchCloudSessionSnapshot(sid);
  if(!data?.session) return false;
  return importCloudSessionSnapshotIntoStore(data, sid, opts);
}

function applyCloudSessionSnapshotToStore(data, sessionId, opts={}){
  const sid = String(sessionId || data?.session_id || data?.sessionId || data?.session?.id || '').trim();
  const remoteSession = data?.session && typeof data.session === 'object' ? data.session : null;
  if(!sid || !remoteSession) return false;
  if(isSessionDeletedByTombstones(sid, currentAccountEmail, extractCloudSessionDeleteTombstones(data))) return false;
  const activeBefore = String(store?.activeId || '').trim();
  const composerSnapshot = captureComposerDraftForStoreApply(sid);
  const previous = store.sessions?.[sid] && typeof store.sessions[sid] === 'object' ? store.sessions[sid] : {};
  const visualBefore = captureActiveChatVisualState();
  const localDirty = !!readScopedStoreMeta(currentAccountEmail)?.dirty;
  const hasPending = !!pendingAssistantSnapshotForSession(sid, store);
  if((sessionHasLiveLocalRuntimeForCloud(sid, store) || hasPending) && sessionHasMeaningfulConversation(previous)) return false;
  if(!opts.force && (shouldDeferCloudRefreshForLocalState() || localDirty || hasPending) && sessionHasMeaningfulConversation(previous)) return false;
  const nextSession = JSON.parse(JSON.stringify(remoteSession));
  try{ cloudSyncRehydrateSessionBodiesInPlace(nextSession); }catch(_){ }
  nextSession.id = String(nextSession.id || sid).trim() || sid;
  nextSession._cloudStub = false;
  nextSession._cloudNeedsHydrate = false;
  nextSession._cloudHydrated = true;
  store.sessions[sid] = cloudSyncApplyAuthoritativeRemoteSession(previous, nextSession, sid);
  applyComposerDraftSnapshotToStore(composerSnapshot, store);
  if(opts.preserveActive !== false && activeBefore && store.sessions[activeBefore]) store.activeId = activeBefore;
  else store.activeId = sid;
  const updatedTs = Number(data?.updated_ts || 0) || 0;
  const revision = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
  if(updatedTs > 0) currentCloudStoreUpdatedTs = Math.max(Number(currentCloudStoreUpdatedTs || 0) || 0, updatedTs);
  if(revision > 0) currentCloudStoreRevision = revision;
  const normalized = buildPersistableStorePayload(store);
  persistStorePayloadLocally(normalized.payload, normalized.slim, currentAccountEmail);
  lastCloudSyncedPayload = String(buildPersistableStorePayload(store).payload || lastCloudSyncedPayload || '');
  const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
  if(chatDomUpdated) restoreComposerDraft(store.activeId);
  if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
  const statusText = String(opts.statusText || '').trim();
  if(statusText) setStatus(statusText);
  return true;
}


async function fetchCloudOpsSnapshot(sinceRevision=currentCloudStoreRevision){
  if(!currentAccountEmail || authKickRedirecting) return null;
  const since = Math.max(0, Number(sinceRevision || 0) || 0);
  const ctl = new AbortController();
  const timeoutId = setTimeout(()=>{
    try{ ctl.abort('cloud_ops_pull_timeout'); }catch(_){ }
  }, computeWeakFetchTimeoutMs('ops_pull'));
  let res = null;
  let data = {};
  try{
    const url = '/api3/chat-sync/pull?since_revision=' + encodeURIComponent(String(since)) + '&mode=ops';
    res = await fetch(url, { cache:'no-store', credentials:'same-origin', signal: ctl.signal });
    data = await res.json().catch(()=>({}));
  }catch(err){
    if(isFetchAbortLikeError(err)) return null;
    throw err;
  }finally{
    try{ clearTimeout(timeoutId); }catch(_){ }
  }
  if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')) return null;
  if(res.status === 404) return null;
  if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
  updateAccountChatLimits(data?.limits);
  return data && typeof data === 'object' ? data : null;
}
function applyCloudSyncOpToLocalStore(baseStore, op){
  const next = isValidStoreShape(baseStore) ? JSON.parse(JSON.stringify(baseStore)) : { sessions:{}, activeId:null, personalization: normalizePersonalizationState() };
  const operation = op && typeof op === 'object' ? op : {};
  const opType = String(operation.op_type || operation.type || '').trim().toLowerCase();
  const payload = operation.payload && typeof operation.payload === 'object' ? operation.payload : {};
  const sid = String(operation.session_id || payload.session_id || payload.activeId || '').trim();
  if(!next.sessions || typeof next.sessions !== 'object') next.sessions = {};
  if(sid && opType !== 'delete_session' && isSessionDeletedByTombstones(sid, currentAccountEmail, extractCloudSessionDeleteTombstones({ ops:[operation] }))) return { store: next, changed:false };
  if(opType === 'upsert_session'){
    const session = payload.session && typeof payload.session === 'object' ? JSON.parse(JSON.stringify(payload.session)) : null;
    const sessionId = String(sid || session?.id || '').trim();
    if(!sessionId || !session) return { store: next, changed:false };
    cloudSyncEnsureConversationSyncFields(session, sessionId);
    const opRevision = Number(operation.revision ?? operation.server_revision ?? payload.revision ?? payload.server_revision ?? 0) || 0;
    if(opRevision > 0){
      session.serverVersion = Math.max(Number(session.serverVersion || session.server_version || 0) || 0, opRevision);
      session.server_version = session.serverVersion;
      const status = String(session.syncStatus || session.sync_status || '').trim().toLowerCase();
      if(!['generating','server_owned_inflight','auth_suspended','failed_retryable'].includes(status)){
        session.syncStatus = 'active';
        session.sync_status = 'active';
      }
    }
    const before = cloudSyncStableStringify(next.sessions[sessionId] || null);
    next.sessions[sessionId] = cloudSyncMergeSession(next.sessions[sessionId], session, sessionId);
    if(!next.activeId || !next.sessions[next.activeId]) next.activeId = sessionId;
    return { store: next, changed: before !== cloudSyncStableStringify(next.sessions[sessionId] || null) };
  }
  if(opType === 'append_messages'){
    const sessionId = sid;
    if(!sessionId) return { store: next, changed:false };
    const previousSession = next.sessions[sessionId] && typeof next.sessions[sessionId] === 'object' ? next.sessions[sessionId] : null;
    let session = previousSession;
    if(!session || typeof session !== 'object' || isCloudSessionStub(session)){
      const seed = payload.session_seed && typeof payload.session_seed === 'object' ? payload.session_seed : cloudSyncMinimalSessionSeed({}, sessionId);
      session = { ...seed, id: String(seed.id || sessionId).trim() || sessionId, messages: Array.isArray(seed.messages) ? seed.messages : [] };
    }else{
      session = JSON.parse(JSON.stringify(session));
    }
    cloudSyncEnsureConversationSyncFields(session, sessionId);
    const messages = Array.isArray(session.messages) ? session.messages : [];
    const added = Array.isArray(payload.messages) ? payload.messages : [];
    const previousHasBranchState = previousSession && webaiBranchSessionHasState(previousSession);
    const baseMatches = cloudSyncMessageBaseGuardMatchesSession(previousSession, payload, { strictLength: previousHasBranchState });
    if(added.length && previousHasBranchState && !baseMatches){
      const before = cloudSyncStableStringify(previousSession || null);
      const kept = cloudSyncCloneLocalBranchAuthoritativeSession(previousSession, session, sessionId);
      next.sessions[sessionId] = kept;
      if(!next.activeId || !next.sessions[next.activeId]) next.activeId = sessionId;
      return { store: next, changed: before !== cloudSyncStableStringify(kept || null) };
    }
    if(added.length) session.messages = cloudSyncMergeMessageLists(messages, added);
    const patch = payload.session_patch && typeof payload.session_patch === 'object' ? payload.session_patch : {};
    for(const [key, value] of Object.entries(patch)){
      if(key === 'id' || key === 'messages') continue;
      session[key] = value;
    }
    session._cloudStub = false;
    session._cloudNeedsHydrate = false;
    session._cloudHydrated = true;
    const opRevision = Number(operation.revision ?? operation.server_revision ?? payload.revision ?? payload.server_revision ?? 0) || 0;
    if(opRevision > 0){
      session.serverVersion = Math.max(Number(session.serverVersion || session.server_version || 0) || 0, opRevision);
      session.server_version = session.serverVersion;
      const status = String(session.syncStatus || session.sync_status || '').trim().toLowerCase();
      if(!['generating','server_owned_inflight','auth_suspended','failed_retryable'].includes(status)){
        session.syncStatus = 'active';
        session.sync_status = 'active';
      }
    }
    cloudSyncEnsureConversationSyncFields(session, sessionId);
    let finalSession = session;
    if((previousSession && webaiBranchSessionHasState(previousSession)) || webaiBranchSessionHasState(session)){
      finalSession = cloudSyncMergeSession(previousSession, session, sessionId);
    }
    next.sessions[sessionId] = finalSession;
    if(!next.activeId || !next.sessions[next.activeId]) next.activeId = sessionId;
    return { store: next, changed: added.length > 0 || Object.keys(patch).length > 0 };
  }
  if(opType === 'message_body_chunk'){
    const sessionId = sid;
    if(!sessionId || !next.sessions[sessionId]) return { store: next, changed:false };
    const session = JSON.parse(JSON.stringify(next.sessions[sessionId]));
    const changed = cloudSyncApplyBodyChunkToSession(session, payload);
    if(changed){
      session._cloudStub = false;
      session._cloudNeedsHydrate = false;
      session._cloudHydrated = true;
      next.sessions[sessionId] = session;
    }
    return { store: next, changed };
  }
  if(opType === 'update_session_meta'){
    const sessionId = sid;
    if(!sessionId || !next.sessions[sessionId]) return { store: next, changed:false };
    const previousSession = next.sessions[sessionId] && typeof next.sessions[sessionId] === 'object' ? next.sessions[sessionId] : null;
    const session = JSON.parse(JSON.stringify(next.sessions[sessionId]));
    const patch = payload.patch && typeof payload.patch === 'object' ? payload.patch : {};
    let changed = false;
    for(const [key, value] of Object.entries(patch)){
      if(key === 'id' || key === 'messages') continue;
      if(cloudSyncStableStringify(session[key] ?? null) !== cloudSyncStableStringify(value ?? null)){
        session[key] = value;
        changed = true;
      }
    }
    if(changed){
      next.sessions[sessionId] = ((previousSession && webaiBranchSessionHasState(previousSession)) || webaiBranchSessionHasState(session))
        ? cloudSyncMergeSession(previousSession, session, sessionId)
        : session;
    }
    return { store: next, changed };
  }
  if(opType === 'delete_session'){
    const sessionId = sid;
    if(sessionId) markLocalSessionDeleteTombstone(sessionId, {
      deleted_at: payload.deleted_at ?? payload.deletedAt ?? operation.created_at ?? operation.createdAt ?? Date.now(),
      server_revision: Number(operation.revision ?? operation.server_revision ?? payload.revision ?? payload.server_revision ?? 0) || 0,
      device_id: operation.device_id || payload.device_id || '',
    });
    if(sessionId && next.sessions[sessionId]){
      delete next.sessions[sessionId];
      if(String(next.activeId || '').trim() === sessionId) next.activeId = Object.keys(next.sessions)[0] || null;
      return { store: next, changed:true };
    }
    return { store: next, changed:false };
  }
  if(opType === 'set_active'){
    return { store: next, changed:false };
  }
  if(opType === 'set_personalization'){
    const personalization = payload.personalization && typeof payload.personalization === 'object' ? payload.personalization : {};
    if(cloudSyncStableStringify(next.personalization || {}) !== cloudSyncStableStringify(personalization)){
      next.personalization = personalization;
      return { store: next, changed:true };
    }
    return { store: next, changed:false };
  }
  return { store: next, changed:false };
}
function applyCloudOpsSnapshotToStore(data, opts={}){
  const serverData = data && typeof data === 'object' ? data : {};
  const serverRevision = Number(serverData?.server_revision ?? serverData?.revision ?? 0) || 0;
  const updatedTs = Number(serverData?.updated_ts || 0) || 0;
  try{ receiveCloudSessionDeleteTombstones(serverData, currentAccountEmail); }catch(_){ }
  if(serverRevision > 0 && serverRevision <= Number(currentCloudStoreRevision || 0) && !serverData?.snapshot_required) return false;
  const hasRuntimeLocalWork = (typeof hasLocalRuntimeActivityForCloudRefresh === 'function') ? hasLocalRuntimeActivityForCloudRefresh() : false;
  if(storeHasPendingAssistantSnapshot(store) || cloudSyncQueuedPayload || getScopedCloudSyncPendingPayload(currentAccountEmail) || hasRuntimeLocalWork) return false;

  const preserveActiveId = String(opts?.preserveActiveId || store?.activeId || '').trim();
  const visualBefore = captureActiveChatVisualState();
  if(serverData?.store && isValidStoreShape(serverData.store)){
    return applyFetchedCloudStoreSnapshot(serverData, {
      requireNewer: false,
      preserveActiveId,
      statusText: opts?.statusText || '已同步账号会话记录',
    });
  }
  if(serverData?.snapshot_required && Array.isArray(serverData?.sessions)){
    const cloudManifestBaselineStore = buildCloudManifestBaselineStore(serverData, store?.personalization || {});
    let cloudManifestBaselinePayload = '';
    try{ cloudManifestBaselinePayload = String(buildPersistableStorePayload(cloudManifestBaselineStore).payload || ''); }catch(_){ cloudManifestBaselinePayload = ''; }
    let nextStore = mergeCloudManifestIntoLocalStore(store, serverData, { preserveLocalExtra:false });
    if(isValidStoreShape(nextStore)){
      const composerSnapshot = captureComposerDraftForStoreApply(preserveActiveId);
      nextStore = cloudSyncMergeStorePreservingLiveLocal(nextStore, store, { preserveActiveId, preserveActive:true });
      applyComposerDraftSnapshotToStore(composerSnapshot, nextStore);
      store = nextStore;
      if(preserveActiveId && store.sessions?.[preserveActiveId]) store.activeId = preserveActiveId;
      if(updatedTs > 0) currentCloudStoreUpdatedTs = updatedTs;
      if(serverRevision > 0) currentCloudStoreRevision = serverRevision;
      const normalized = buildPersistableStorePayload(store);
      persistStorePayloadLocally(normalized.payload, normalized.slim, currentAccountEmail);
      lastCloudSyncedPayload = cloudManifestBaselinePayload || normalized.payload;
      clearScopedStoreDirty(currentAccountEmail, { cloudUpdatedTs: updatedTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
      const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
      if(chatDomUpdated) restoreComposerDraft(store.activeId);
      if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
      const statusText = String(opts?.statusText || '').trim();
      if(statusText) setStatus(statusText);
      return true;
    }
  }
  const ops = Array.isArray(serverData?.ops) ? serverData.ops : [];
  let nextStore = store;
  let changed = false;
  for(const op of ops){
    const applied = applyCloudSyncOpToLocalStore(nextStore, op);
    nextStore = applied.store;
    changed = changed || !!applied.changed;
  }
  if(serverRevision > 0) currentCloudStoreRevision = serverRevision;
  if(updatedTs > 0) currentCloudStoreUpdatedTs = Math.max(Number(currentCloudStoreUpdatedTs || 0) || 0, updatedTs);
  if(!changed){
    if(serverRevision > 0 || updatedTs > 0){
      const normalized = buildPersistableStorePayload(store);
      lastCloudSyncedPayload = normalized.payload;
      clearScopedStoreDirty(currentAccountEmail, { cloudUpdatedTs: updatedTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
    }
    return false;
  }
  const composerSnapshot = captureComposerDraftForStoreApply(preserveActiveId);
  nextStore = cloudSyncMergeStorePreservingLiveLocal(nextStore, store, { preserveActiveId, preserveActive:true });
  applyComposerDraftSnapshotToStore(composerSnapshot, nextStore);
  store = nextStore;
  if(preserveActiveId && store.sessions?.[preserveActiveId]) store.activeId = preserveActiveId;
  enforceAccountStoreLimitsInPlace('silent');
  const normalized = buildPersistableStorePayload(store);
  persistStorePayloadLocally(normalized.payload, normalized.slim, currentAccountEmail);
  clearScopedStoreDirty(currentAccountEmail, { cloudUpdatedTs: updatedTs, localUpdatedAt: storeLatestUpdatedAtMs(store) });
  lastCloudSyncedPayload = normalized.payload;
  const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
  if(chatDomUpdated) restoreComposerDraft(store.activeId);
  if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
  const statusText = String(opts?.statusText || '').trim();
  if(statusText) setStatus(statusText);
  return true;
}

let accountRealtimeSource = null;
let accountRealtimeEmail = "";
let accountRealtimeReconnectTimer = null;
let accountRealtimeGapPullTimer = null;
let accountRealtimeRetryCount = 0;
let accountRealtimePullInFlight = false;
let accountRealtimeHelloAt = 0;

function stopAccountRealtimeSync(reason='', opts={}){
  try{ if(accountRealtimeReconnectTimer) clearTimeout(accountRealtimeReconnectTimer); }catch(_){ }
  accountRealtimeReconnectTimer = null;
  try{ if(accountRealtimeGapPullTimer) clearTimeout(accountRealtimeGapPullTimer); }catch(_){ }
  accountRealtimeGapPullTimer = null;
  if(accountRealtimeSource){
    try{ accountRealtimeSource.close(); }catch(_){ }
  }
  accountRealtimeSource = null;
  accountRealtimeEmail = "";
  accountRealtimeHelloAt = 0;
  if(opts?.preserveRetry !== true) accountRealtimeRetryCount = 0;
  try{ if(reason) console.debug('[webai] account realtime stopped:', reason); }catch(_){ }
}

function isAccountRealtimeSyncHealthy(){
  const email = normalizeAccountScopeEmail(currentAccountEmail || '');
  return !!(
    email
    && accountRealtimeEmail === email
    && accountRealtimeSource
    && accountRealtimeSource.readyState === 1
    && accountRealtimeHelloAt > 0
  );
}

function shouldDeferAccountRealtimeApply(){
  if(!currentAccountEmail || authKickRedirecting) return true;
  if(cloudSyncInFlight || cloudSyncQueuedPayload || getScopedCloudSyncPendingPayload(currentAccountEmail)) return true;
  try{ if(typeof hasLocalRuntimeActivityForCloudRefresh === 'function' && hasLocalRuntimeActivityForCloudRefresh()) return true; }catch(_){ }
  try{ if(storeHasPendingAssistantSnapshot(store)) return true; }catch(_){ }
  return false;
}

async function pullAccountRealtimeGap(reason=''){
  if(accountRealtimePullInFlight || !currentAccountEmail || authKickRedirecting) return false;
  accountRealtimePullInFlight = true;
  try{
    if(shouldDeferAccountRealtimeApply()) return false;
    const data = await fetchCloudOpsSnapshot(currentCloudStoreRevision);
    if(!data) return false;
    const changed = applyCloudOpsSnapshotToStore(data, { statusText:'' });
    return !!changed;
  }catch(err){
    try{ console.warn('[webai] account realtime gap pull failed:', reason, err); }catch(_){ }
    return false;
  }finally{
    accountRealtimePullInFlight = false;
  }
}

function scheduleAccountRealtimeGapPull(reason='', delayMs=0){
  if(!currentAccountEmail || authKickRedirecting || isNavigatorOffline()) return false;
  try{ if(accountRealtimeGapPullTimer) clearTimeout(accountRealtimeGapPullTimer); }catch(_){ }
  const wait = Math.max(300, Math.min(15000, Number(delayMs || 0) || 700));
  accountRealtimeGapPullTimer = setTimeout(async ()=>{
    accountRealtimeGapPullTimer = null;
    if(!currentAccountEmail || authKickRedirecting || isNavigatorOffline()) return;
    if(shouldDeferAccountRealtimeApply()){
      scheduleAccountRealtimeGapPull(reason || 'deferred', Math.min(15000, Math.max(1200, wait * 2)));
      return;
    }
    await pullAccountRealtimeGap(reason || 'scheduled');
  }, wait);
  return true;
}

function scheduleAccountRealtimeReconnect(reason='', delayMs=0){
  if(!currentAccountEmail || authKickRedirecting) return;
  if(isNavigatorOffline() || document.visibilityState === 'hidden') return;
  try{ if(accountRealtimeReconnectTimer) clearTimeout(accountRealtimeReconnectTimer); }catch(_){ }
  const attempt = Math.max(1, Number(accountRealtimeRetryCount || 0) + 1);
  accountRealtimeRetryCount = attempt;
  const wait = Math.max(600, Math.min(45000, Number(delayMs || 0) || stableBackoffMs(attempt, 1200, 45000)));
  accountRealtimeReconnectTimer = setTimeout(()=>{
    accountRealtimeReconnectTimer = null;
    startAccountRealtimeSync({ reason: reason || 'reconnect', force:true });
  }, wait);
}

function handleAccountRealtimePayload(data, source='events'){
  const payload = data && typeof data === 'object' ? data : {};
  const email = normalizeAccountScopeEmail(payload.email || '');
  if(email && currentAccountEmail && email !== currentAccountEmail) return false;
  const serverRevision = Number(payload.server_revision ?? payload.revision ?? 0) || 0;
  if(serverRevision > 0 && serverRevision <= Number(currentCloudStoreRevision || 0) && !payload.snapshot_required) return false;
  if(shouldDeferAccountRealtimeApply()){
    scheduleAccountRealtimeGapPull(source + '_deferred', 1800);
    return false;
  }
  const changed = applyCloudOpsSnapshotToStore(payload, { statusText:'' });
  if(changed){
    accountRealtimeRetryCount = 0;
  }else if(serverRevision > Number(currentCloudStoreRevision || 0)){
    scheduleAccountRealtimeGapPull(source + '_retry_apply', 2200);
  }
  return !!changed;
}

function startAccountRealtimeSync(opts={}){
  const email = normalizeAccountScopeEmail(currentAccountEmail || '');
  if(!email || authKickRedirecting || typeof EventSource !== 'function'){
    stopAccountRealtimeSync(!email ? 'no_account' : 'eventsource_unavailable');
    return false;
  }
  if(document.visibilityState === 'hidden') return false;
  const o = opts || {};
  if(accountRealtimeSource && accountRealtimeEmail === email && o.force !== true) return true;
  stopAccountRealtimeSync('restart', { preserveRetry:true });
  accountRealtimeEmail = email;
  const since = Math.max(0, Number(currentCloudStoreRevision || 0) || 0);
  const url = '/api3/chat-sync/events?since_revision=' + encodeURIComponent(String(since));
  let source = null;
  try{
    source = new EventSource(url, { withCredentials:true });
  }catch(err){
    try{ console.warn('[webai] account realtime open failed:', err); }catch(_){ }
    scheduleAccountRealtimeReconnect('open_failed');
    return false;
  }
  accountRealtimeSource = source;
  source.addEventListener('hello', (event)=>{
    try{
      const data = JSON.parse(event?.data || '{}');
      updateAccountChatLimits(data?.limits);
      if(typeof applyAuthoritativeAccountProfile === 'function' && data?.profile){
        applyAuthoritativeAccountProfile(data, { renderSettings:true });
      }
      accountRealtimeHelloAt = Date.now();
      accountRealtimeRetryCount = 0;
      scheduleAccountRealtimeGapPull('hello', 300);
    }catch(_){ }
  });
  source.addEventListener('ops', (event)=>{
    try{
      const data = JSON.parse(event?.data || '{}');
      updateAccountChatLimits(data?.limits);
      handleAccountRealtimePayload(data, 'sse_ops');
    }catch(err){
      try{ console.warn('[webai] account realtime event parse failed:', err); }catch(_){ }
      scheduleAccountRealtimeGapPull('parse_failed', 700);
    }
  });
  source.addEventListener('profile', (event)=>{
    try{
      const data = JSON.parse(event?.data || '{}');
      if(typeof applyAuthoritativeAccountProfile === 'function'){
        applyAuthoritativeAccountProfile(data, { renderSettings:true });
      }
    }catch(err){
      try{ console.warn('[webai] account realtime profile parse failed:', err); }catch(_){ }
    }
  });
  source.addEventListener('heartbeat', (event)=>{
    try{
      const data = JSON.parse(event?.data || '{}');
      const serverRevision = Number(data?.server_revision ?? data?.revision ?? 0) || 0;
      if(serverRevision > Number(currentCloudStoreRevision || 0)) scheduleAccountRealtimeGapPull('heartbeat_gap', 500);
    }catch(_){ }
  });
  source.addEventListener('error', ()=>{
    if(accountRealtimeSource !== source) return;
    try{ source.close(); }catch(_){ }
    accountRealtimeSource = null;
    accountRealtimeHelloAt = 0;
    if(!authKickRedirecting && normalizeAccountScopeEmail(currentAccountEmail || '') === email){
      scheduleAccountRealtimeReconnect('sse_error');
    }
  });
  scheduleAccountRealtimeGapPull(String(o.reason || 'start'), 400);
  return true;
}

function ensureAccountRealtimeSync(reason=''){
  if(!currentAccountEmail || authKickRedirecting){
    stopAccountRealtimeSync('ensure_no_account');
    return false;
  }
  if(document.visibilityState === 'hidden'){
    stopAccountRealtimeSync('ensure_hidden', { preserveRetry:true });
    return false;
  }
  if(accountRealtimeSource && accountRealtimeEmail === normalizeAccountScopeEmail(currentAccountEmail)) return true;
  if(accountRealtimeReconnectTimer) return true;
  return startAccountRealtimeSync({ reason });
}

function getCloudSyncCurrentPayload(){
  try{
    return String(buildPersistableStorePayload(store).payload || '').trim();
  }catch(_){
    return '';
  }
}

function scheduleCloudStoreSyncRetry(delayMs, reason=''){
  if(!currentAccountEmail || authKickRedirecting) return;
  const payload = String(cloudSyncQueuedPayload || getScopedCloudSyncPendingPayload(currentAccountEmail) || '').trim();
  if(!payload) return;
  cloudSyncQueuedPayload = payload;
  cloudSyncLastReason = String(reason || cloudSyncLastReason || '').trim();
  writeScopedCloudSyncPending(currentAccountEmail, payload, {
    lastReason: cloudSyncLastReason,
    retryCount: cloudSyncRetryCount,
    localUpdatedAt: storeLatestUpdatedAtMs(store),
  });
  const requested = Number(delayMs || CLOUD_SYNC_DEBOUNCE_MS) || CLOUD_SYNC_DEBOUNCE_MS;
  let waitMs = getCloudSyncWeakDebounceMs(Math.max(600, Math.min(CLOUD_SYNC_RETRY_MAX_MS, requested)));
  if(isNavigatorOffline()) waitMs = Math.max(waitMs, 15000 + stableJitterMs(3000));
  if(document.visibilityState === 'hidden') waitMs = Math.max(waitMs, 10000 + stableJitterMs(2500));
  try{ if(cloudSyncTimer) clearTimeout(cloudSyncTimer); }catch(_){ }
  cloudSyncTimer = setTimeout(()=>{
    cloudSyncTimer = null;
    flushCloudStoreSync();
  }, Math.max(600, Math.min(CLOUD_SYNC_RETRY_MAX_MS, waitMs)));
}

function applyCloudStoreSyncSuccess(payload, data, opts){
  const rawPayload = String(payload || '').trim();
  const serverData = (data && typeof data === 'object') ? data : {};
  const ackTs = Number(serverData?.updated_ts || 0) || Number(currentCloudStoreUpdatedTs || 0) || 0;
  const ackRevision = Number(serverData?.server_revision ?? serverData?.revision ?? 0) || Number(currentCloudStoreRevision || 0) || 0;
  const queuedAfterAck = String(cloudSyncQueuedPayload || '').trim();
  const cloudConflict = !!(serverData?.conflict || (serverData?.ok === false && Array.isArray(serverData?.conflicts)));
  updateAccountChatLimits(serverData?.limits);
  if(ackTs > 0) currentCloudStoreUpdatedTs = ackTs;
  if(ackRevision > 0) currentCloudStoreRevision = ackRevision;
  const visualBefore = captureActiveChatVisualState();
  const activeBefore = String(store?.activeId || '').trim();
  const serverStore = (serverData?.store && isValidStoreShape(serverData.store)) ? serverData.store : null;
  let serverBaselinePayload = rawPayload;
  let localPayloadAfterApply = rawPayload;

  if(serverStore){
    try{ receiveCloudSessionDeleteTombstones(serverData, currentAccountEmail); }catch(_){ }
    try{ applySessionDeleteTombstonesToStore(serverStore, currentAccountEmail, extractCloudSessionDeleteTombstones(serverData)); }catch(_){ }
    try{ cloudSyncRehydrateStoreBodiesInPlace(serverStore); }catch(_){ }
    cleanLegacyDefaultSystemMessagesFromStore(serverStore);
    try{ serverBaselinePayload = String(buildPersistableStorePayload(serverStore).payload || rawPayload || ''); }catch(_){ serverBaselinePayload = rawPayload; }
    if(cloudConflict){
      const queuedLocalPayload = queuedAfterAck && queuedAfterAck !== rawPayload ? queuedAfterAck : rawPayload;
      const queuedLocalStore = parseCloudSyncPayload(queuedLocalPayload);
      const localRebaseStore = isValidStoreShape(queuedLocalStore) ? queuedLocalStore : store;
      store = cloudSyncMergeStorePreservingLiveLocal(serverStore, localRebaseStore, {
        preserveActiveId: activeBefore,
        preserveActive:true,
        preserveLocalProgress:true,
      });
      if(activeBefore && store.sessions?.[activeBefore]) store.activeId = activeBefore;
      const normalized = buildPersistableStorePayload(store);
      persistStorePayloadLocally(normalized.payload, normalized.slim, currentAccountEmail);
      lastLoadedStoreScopeKey = buildScopedStoreKey(currentAccountEmail);
      lastCloudSyncedPayload = String(serverBaselinePayload || normalized.payload || '').trim();
      const rebasedPayload = normalized.payload && normalized.payload !== lastCloudSyncedPayload ? normalized.payload : '';
      if(rebasedPayload){
        cloudSyncQueuedPayload = rebasedPayload;
        cloudSyncRetryCount = 0;
        cloudSyncLastReason = 'conflict_rebase_after_cloud_ack';
        markScopedStoreDirty(currentAccountEmail, { localUpdatedAt: storeLatestUpdatedAtMs(store) });
        writeScopedCloudSyncPending(currentAccountEmail, rebasedPayload, {
          lastReason: cloudSyncLastReason,
          retryCount: cloudSyncRetryCount,
          localUpdatedAt: storeLatestUpdatedAtMs(store),
          rebasedAfterConflict:true,
        });
        scheduleCloudStoreSyncRetry(getCloudSyncWeakDebounceMs(700), cloudSyncLastReason);
      }else{
        cloudSyncQueuedPayload = '';
        clearScopedStoreDirty(currentAccountEmail, {
          cloudUpdatedTs: ackTs,
          localUpdatedAt: storeLatestUpdatedAtMs(store),
        });
        clearScopedCloudSyncPending(currentAccountEmail);
        cloudSyncRetryCount = 0;
        cloudSyncLastReason = '';
      }
      const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
      if(chatDomUpdated) restoreComposerDraft(store.activeId);
      if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
      try{ toast(rebasedPayload
        ? (window.AperviaI18n?.t('sync.merged') || 'New cloud changes were merged with local pending updates.')
        : (serverData?.message || window.AperviaI18n?.t('sync.refreshed') || 'Cloud conversations updated and refreshed.')); }catch(_){ }
      if(!rebasedPayload) clearPendingCloudSessionDeletes();
      cloudSyncErrorShown = '';
      return;
    }
    const composerSnapshot = captureComposerDraftForStoreApply(activeBefore);
    const nextServerStore = cloudSyncMergeStorePreservingLiveLocal(serverStore, store, { preserveActiveId: activeBefore, preserveActive:true });
    applyComposerDraftSnapshotToStore(composerSnapshot, nextServerStore);
    store = nextServerStore;
    if(activeBefore && store.sessions?.[activeBefore]) store.activeId = activeBefore;
    const normalized = buildPersistableStorePayload(store);
    localPayloadAfterApply = normalized.payload;
    persistStorePayloadLocally(normalized.payload, normalized.slim, currentAccountEmail);
    lastLoadedStoreScopeKey = buildScopedStoreKey(currentAccountEmail);
    const chatDomUpdated = renderCloudSyncAppliedUi(visualBefore);
    if(chatDomUpdated) restoreComposerDraft(store.activeId);
    if(typeof refreshStatusForActiveSession === 'function') refreshStatusForActiveSession();
    if(serverData?.message) setStatus(String(serverData.message));
  }else{
    localPayloadAfterApply = rawPayload;
  }

  lastCloudSyncedPayload = String(serverBaselinePayload || rawPayload || '').trim();
  let followupPayload = '';
  if(queuedAfterAck && queuedAfterAck !== rawPayload){
    followupPayload = queuedAfterAck;
  }else if(opts?.partial){
    followupPayload = rawPayload;
  }else if(localPayloadAfterApply && localPayloadAfterApply !== lastCloudSyncedPayload){
    followupPayload = localPayloadAfterApply;
  }

  if(followupPayload){
    cloudSyncQueuedPayload = followupPayload;
    markScopedStoreDirty(currentAccountEmail, { localUpdatedAt: storeLatestUpdatedAtMs(store) });
    writeScopedCloudSyncPending(currentAccountEmail, followupPayload, {
      lastReason: 'followup_after_cloud_ack',
      retryCount: cloudSyncRetryCount,
      localUpdatedAt: storeLatestUpdatedAtMs(store),
    });
    scheduleCloudStoreSyncRetry(getCloudSyncWeakDebounceMs(700), 'followup_after_cloud_ack');
  }else{
    cloudSyncQueuedPayload = '';
    clearScopedStoreDirty(currentAccountEmail, {
      cloudUpdatedTs: ackTs,
      localUpdatedAt: storeLatestUpdatedAtMs(store),
    });
    clearScopedCloudSyncPending(currentAccountEmail);
    cloudSyncRetryCount = 0;
    cloudSyncLastReason = '';
  }

  clearPendingCloudSessionDeletes();
  cloudSyncErrorShown = '';
}

async function verifyCloudStoreSyncApplied(payload){
  const rawPayload = String(payload || '').trim();
  if(!rawPayload || !currentAccountEmail || authKickRedirecting) return false;
  try{
    const data = await fetchCloudStoreSnapshot();
    const remoteStore = (data?.store && isValidStoreShape(data.store)) ? data.store : null;
    if(!remoteStore) return false;
    const remotePayload = String(buildPersistableStorePayload(remoteStore).payload || '').trim();
    if(remotePayload && remotePayload === rawPayload){
      applyCloudStoreSyncSuccess(rawPayload, data, { verified:true });
      return true;
    }
  }catch(e){
    console.warn('verify cloud store sync failed:', e);
  }
  return false;
}

function queueCloudStoreSync(payload){
  if(!currentAccountEmail || authKickRedirecting) return;
  const nextPayload = String(payload || "").trim();
  if(!nextPayload) return;
  if(nextPayload === lastCloudSyncedPayload && currentCloudStoreUpdatedTs > 0 && !cloudSyncQueuedPayload) return;
  if(nextPayload !== cloudSyncQueuedPayload) cloudSyncRetryCount = 0;
  cloudSyncQueuedPayload = nextPayload;
  cloudSyncLastReason = '';
  writeScopedCloudSyncPending(currentAccountEmail, nextPayload, {
    lastReason: '',
    retryCount: 0,
    localUpdatedAt: storeLatestUpdatedAtMs(store),
  });
  try{ if(cloudSyncTimer) clearTimeout(cloudSyncTimer); }catch(_){ }
  const delayMs = getCloudSyncWeakDebounceMs(CLOUD_SYNC_DEBOUNCE_MS);
  cloudSyncTimer = setTimeout(()=>{
    cloudSyncTimer = null;
    flushCloudStoreSync();
  }, delayMs);
}

function requestCloudMessageRealtimeFlush(reason='', opts={}){
  if(!currentAccountEmail || authKickRedirecting) return false;
  const payload = String(cloudSyncQueuedPayload || getScopedCloudSyncPendingPayload(currentAccountEmail) || getCloudSyncCurrentPayload() || '').trim();
  if(!payload) return false;
  cloudSyncQueuedPayload = payload;
  try{ if(cloudSyncTimer) clearTimeout(cloudSyncTimer); }catch(_){ }
  const delayMs = Math.max(0, Number(opts?.delayMs ?? 0) || 0);
  cloudSyncTimer = setTimeout(()=>{
    cloudSyncTimer = null;
    flushCloudStoreSync();
  }, delayMs);
  try{ console.debug('[webai] message realtime cloud flush requested:', String(reason || 'message')); }catch(_){ }
  return true;
}


async function flushCloudStoreSync(){
  if(cloudSyncInFlight || !currentAccountEmail || authKickRedirecting) return;
  const payload = String(cloudSyncQueuedPayload || getScopedCloudSyncPendingPayload(currentAccountEmail) || "").trim();
  if(!payload) return;
  if(shouldPauseNonCriticalCloudSync()){
    cloudSyncQueuedPayload = payload;
    writeScopedCloudSyncPending(currentAccountEmail, payload, {
      lastReason: isNavigatorOffline() ? 'offline' : 'defer_non_critical_sync',
      retryCount: cloudSyncRetryCount,
      localUpdatedAt: storeLatestUpdatedAtMs(store),
    });
    scheduleCloudStoreSyncRetry(getCloudSyncWeakDebounceMs(CLOUD_SYNC_DEBOUNCE_MS), isNavigatorOffline() ? 'offline' : 'defer_non_critical_sync');
    return;
  }
  let storePayload = null;
  try{ storePayload = JSON.parse(payload); }catch(_){
    cloudSyncQueuedPayload = '';
    clearScopedCloudSyncPending(currentAccountEmail);
    return;
  }
  const pushBody = buildCloudSyncPushBodyFromPayload(payload, storePayload);
  if(!Array.isArray(pushBody.ops) || pushBody.ops.length <= 0){
    if(pushBody.ops_build_error){
      const reason = String(pushBody.ops_build_error || 'cloud_sync_ops_build_failed');
      cloudSyncRetryCount = Math.max(1, Number(cloudSyncRetryCount || 0) + 1);
      noteCloudSyncBuildProblem(reason, payload);
      scheduleCloudStoreSyncRetry(stableBackoffMs(Math.max(1, cloudSyncRetryCount + 1), 1800, CLOUD_SYNC_RETRY_MAX_MS), reason);
      try{ console.warn('cloud store sync pending retry:', reason); }catch(_){ }
      return;
    }
    applyCloudStoreSyncSuccess(payload, {
      ok:true,
      updated_ts: currentCloudStoreUpdatedTs,
      server_revision: currentCloudStoreRevision,
      sync_protocol:'ops_v2_noop',
      limits: accountChatLimits,
    });
    return;
  }
  cloudSyncInFlight = true;
  cloudSyncQueuedPayload = "";
  const attempt = cloudSyncRetryCount + 1;
  try{
    const ctl = new AbortController();
    const timeoutId = setTimeout(()=>{
      try{ ctl.abort('cloud_sync_timeout'); }catch(_){ }
    }, Math.max(CLOUD_SYNC_FETCH_TIMEOUT_MS, computeWeakFetchTimeoutMs('cloud_post')));
    let res = null;
    let data = {};
    try{
      res = await fetch('/api3/chat-sync/push', {
        method:'POST',
        headers:{ 'Content-Type':'application/json' },
        body: JSON.stringify(pushBody),
        cache:'no-store',
        credentials:'same-origin',
        signal: ctl.signal,
      });
      data = await res.json().catch(()=>({}));
    }finally{
      clearTimeout(timeoutId);
    }
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')) return;
    if(res.status === 404 || data?.sync_protocol === 'unsupported') throw new Error(data?.error || 'chat_sync_push_unavailable');
    if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
    applyCloudStoreSyncSuccess(payload, data, { partial: !!pushBody.ops_partial });
  }catch(e){
    console.warn('cloud store sync soft failed:', e);
    const msg = stableNetworkReason(e, 'cloud_sync_failed');
    const softNetwork = isSoftNetworkError(e);
    if(!softNetwork){
      const verified = await verifyCloudStoreSyncApplied(payload);
      if(verified) return;
    }
    cloudSyncQueuedPayload = payload;
    cloudSyncRetryCount = attempt;
    cloudSyncLastReason = msg;
    writeScopedCloudSyncPending(currentAccountEmail, payload, {
      lastReason: msg,
      retryCount: attempt,
      localUpdatedAt: storeLatestUpdatedAtMs(store),
      softNetwork,
    });
    if(!softNetwork && msg && msg !== cloudSyncErrorShown && (attempt === 1 || attempt % 5 === 0)){
      cloudSyncErrorShown = msg;
      try{ console.warn('cloud store sync will retry silently:', msg); }catch(_){ }
    }
    const retryMs = stableBackoffMs(attempt, softNetwork ? 2400 : 1400, CLOUD_SYNC_RETRY_MAX_MS);
    scheduleCloudStoreSyncRetry(retryMs, msg);
  }finally{
    cloudSyncInFlight = false;
    if(cloudSyncQueuedPayload && cloudSyncQueuedPayload !== lastCloudSyncedPayload && !authKickRedirecting && !cloudSyncTimer){
      scheduleCloudStoreSyncRetry(CLOUD_SYNC_DEBOUNCE_MS, cloudSyncLastReason);
    }
  }
}

function saveStore(){
  try{
    for(const ss of Object.values(store?.sessions || {})){
      try{ webaiOfficialNormalizeActiveSession(ss, { skipIfLive:true }); }catch(_){ }
    }
  }catch(_){ }
  const trimmed = enforceAccountStoreLimitsInPlace('save');
  const { slim, payload } = buildPersistableStorePayload();
  persistStorePayloadLocally(payload, slim);
  if(currentAccountEmail) markScopedStoreDirty(currentAccountEmail, { localUpdatedAt: storeLatestUpdatedAtMs(store) });
  queueCloudStoreSync(payload);
  if(trimmed) safeRenderAll();
}

// Throttled save to avoid frequent writes
let _saveStoreTimer = null;
function saveStoreThrottled(){
  try{ if(_saveStoreTimer) clearTimeout(_saveStoreTimer); }catch(e){}
  _saveStoreTimer = setTimeout(()=>{
    _saveStoreTimer = null;
    try{ saveStore(); }catch(e){}
  }, 120);
}

let _saveStoreLocalOnlyTimer = null;
function saveStoreLocalOnly(){
  try{
    const { slim, payload } = buildPersistableStorePayload(store);
    persistStorePayloadLocally(payload, slim, currentAccountEmail);
  }catch(e){
    console.warn('local-only store save failed:', e);
  }
}
function saveStoreLocalOnlyThrottled(){
  try{ if(_saveStoreLocalOnlyTimer) clearTimeout(_saveStoreLocalOnlyTimer); }catch(e){}
  _saveStoreLocalOnlyTimer = setTimeout(()=>{
    _saveStoreLocalOnlyTimer = null;
    saveStoreLocalOnly();
  }, 120);
}


function normalizeAssistantFileSourceRole(file){
  const f = file && typeof file === 'object' ? file : {};
  const raw = String(f.source_role || f.sourceRole || f.version_role || f.versionRole || '').trim().toLowerCase();
  if(raw === 'edited_output' || raw === 'assistant_edited' || raw === 'edited') return 'edited_output';
  if(raw === 'assistant_generated' || raw === 'latest_generated' || raw === 'generated' || raw === 'assistant_file' || raw === 'assistant') return 'assistant_generated';
  if(f.edit_audit || f.file_edit_audit || f.edit_details || f.edited_from) return 'edited_output';
  return 'assistant_generated';
}

function normalizeUserFileSourceRole(file){
  const f = file && typeof file === 'object' ? file : {};
  const raw = String(f.source_role || f.sourceRole || f.version_role || f.versionRole || '').trim().toLowerCase();
  if(raw === 'user_upload' || raw === 'upload' || raw === 'uploaded' || raw === 'user') return 'user_upload';
  return 'user_upload';
}

function assistantFileSourceRoleLabel(file){
  const role = normalizeAssistantFileSourceRole(file);
  return role === 'edited_output' ? '助手修改' : '助手生成';
}

function _normalizePendingAssistantFiles(files){
  const out = [];
  const seen = new Set();
  for(const f of (Array.isArray(files) ? files : [])){
    if(!f || typeof f !== 'object') continue;
    const filename = String(f.filename || '').trim();
    const href = String(getAssistantArtifactDownloadHref(f) || f.download_url || f.url || f.view_url || '').trim();
    if(!filename || !href) continue;
    const key = (filename + '|' + href).toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    const sourceRole = normalizeAssistantFileSourceRole(f);
    out.push({
      ...f,
      source_type: 'generated',
      sourceType: 'generated',
      source_role: sourceRole,
      sourceRole,
      generated_by_assistant: f.generated_by_assistant !== false,
      generatedByAssistant: f.generated_by_assistant !== false,
      download_url: f.download_url || href,
      downloadUrl: f.downloadUrl || f.download_url || href,
    });
  }
  return out;
}

function _normalizePendingAssistantImageReplies(items){
  const out = [];
  const seen = new Set();
  for(const item of (Array.isArray(items) ? items : [])){
    if(!item || typeof item !== 'object') continue;
    const createdAtMs = Number(item.created_at_ms || item.createdAtMs || Date.now()) || Date.now();
    const endpointMode = normalizeApiEndpointMode(item.endpoint_mode || item.api_endpoint_mode || item.apiEndpointMode || item.endpointMode || '');
    const normalized = {
      _kind: 'image_reply',
      ...(item || {}),
      source_role: String(item.source_role || 'assistant'),
      endpoint_mode: endpointMode,
      api_endpoint_mode: endpointMode,
      operation: String(item.operation || item.task_mode || 'generate'),
      created_at_ms: createdAtMs,
      createdAtMs: createdAtMs,
      image_seq: Number(item.image_seq || item.seq || 1) || 1,
      images: normalizeImageReplyImagesForPayload(item).map((img, index) => {
        const sourceImageIds = normalizeImageReplySourceIds(img, item);
        return {
          ...img,
          source_role: 'assistant',
          source_type: img.source_type || 'generated',
          endpoint_mode: normalizeApiEndpointMode(img.endpoint_mode || img.api_endpoint_mode || img.apiEndpointMode || endpointMode || ''),
          api_endpoint_mode: normalizeApiEndpointMode(img.api_endpoint_mode || img.endpoint_mode || img.apiEndpointMode || endpointMode || ''),
          image_id: String(img.image_id || img.imageId || img.attachment_id || img.id || '').trim(),
          operation: img.operation || item.operation || item.task_mode || 'generate',
          parent_image_id: String(img.parent_image_id || img.parentImageId || item.parent_image_id || item.parentImageId || '').trim(),
          source_image_ids: sourceImageIds,
          derived_from: sourceImageIds,
          created_at_ms: Number(img.created_at_ms || img.createdAtMs || createdAtMs) || createdAtMs,
          createdAtMs: Number(img.created_at_ms || img.createdAtMs || createdAtMs) || createdAtMs,
          image_seq: Number(img.image_seq || img.seq || index + 1) || (index + 1),
          seq: Number(img.image_seq || img.seq || index + 1) || (index + 1),
        };
      }),
      text: String(item.text || '').trim(),
    };
    if(!normalized.images.length && !normalized.text) continue;
    const sig = imageReplySignature(normalized);
    const key = ((sig || 'no-image') + '||' + normalized.text).toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    out.push(normalized);
  }
  return out;
}

function persistPendingAssistantSnapshot(id, patch, opts){
  const s = getSessionById(id);
  if(!s) return;
  const o = opts || {};
  const nextDraft = (patch && Object.prototype.hasOwnProperty.call(patch, 'draft')) ? String(patch.draft ?? '') : String(s.pendingAssistantDraft || '');
  const nextStatus = (patch && Object.prototype.hasOwnProperty.call(patch, 'status')) ? String(patch.status ?? '') : String(s.pendingAssistantStatus || '');
  const nextProcess = (patch && Object.prototype.hasOwnProperty.call(patch, 'process')) ? String(patch.process ?? '') : String(s.pendingAssistantProcess || '');
  const nextStreaming = (patch && Object.prototype.hasOwnProperty.call(patch, 'streaming')) ? !!patch.streaming : !!s.pendingAssistantStreaming;
  const nextFiles = (patch && Object.prototype.hasOwnProperty.call(patch, 'files')) ? _normalizePendingAssistantFiles(patch.files) : _normalizePendingAssistantFiles(s.pendingAssistantFiles);
  const nextImageReplies = (patch && Object.prototype.hasOwnProperty.call(patch, 'imageReplies')) ? _normalizePendingAssistantImageReplies(patch.imageReplies) : _normalizePendingAssistantImageReplies(s.pendingAssistantImageReplies);
  const nextWeatherPayload = (patch && Object.prototype.hasOwnProperty.call(patch, 'weatherPayload')) ? normalizeAssistantWeatherPayload(patch.weatherPayload) : normalizeAssistantWeatherPayload(s.pendingAssistantWeatherPayload || null);
  const nextReasoning = (patch && Object.prototype.hasOwnProperty.call(patch, 'reasoning')) ? _normalizePendingAssistantReasoning(patch.reasoning) : _normalizePendingAssistantReasoning(s.pendingAssistantReasoning);
  const nextReasoningMeta = (patch && Object.prototype.hasOwnProperty.call(patch, 'reasoningMeta')) ? _normalizePendingAssistantReasoningMeta(patch.reasoningMeta) : _normalizePendingAssistantReasoningMeta(s.pendingAssistantReasoningMeta);
  const nextSources = (patch && Object.prototype.hasOwnProperty.call(patch, 'sources')) ? normalizeAssistantSourceItems(patch.sources) : normalizeAssistantSourceItems(s.pendingAssistantSources);
  const nextRtStartAt = (patch && Object.prototype.hasOwnProperty.call(patch, 'rtStartAt')) ? Math.max(0, Number(patch.rtStartAt || 0) || 0) : Math.max(0, Number(s.pendingAssistantRtStartAt || 0) || 0);
  const nextRtFinalMs = (patch && Object.prototype.hasOwnProperty.call(patch, 'rtFinalMs')) ? _rtClampElapsedMsForSession(id, Math.max(0, Number(patch.rtFinalMs || 0) || 0)) : _rtClampElapsedMsForSession(id, Math.max(0, Number(s.pendingAssistantRtFinalMs || 0) || 0));
  const nextIsEmpty = !nextDraft && !nextStatus && !nextProcess && !nextStreaming && !nextFiles.length && !nextImageReplies.length && !nextWeatherPayload && !nextReasoning.length && !Object.keys(nextReasoningMeta).length && !nextSources.length;
  const prevSig = JSON.stringify({
    draft: String(s.pendingAssistantDraft || ''),
    status: String(s.pendingAssistantStatus || ''),
    process: String(s.pendingAssistantProcess || ''),
    streaming: !!s.pendingAssistantStreaming,
    files: _normalizePendingAssistantFiles(s.pendingAssistantFiles),
    imageReplies: _normalizePendingAssistantImageReplies(s.pendingAssistantImageReplies),
    weatherPayload: normalizeAssistantWeatherPayload(s.pendingAssistantWeatherPayload || null),
    reasoning: _normalizePendingAssistantReasoning(s.pendingAssistantReasoning),
    reasoningMeta: _normalizePendingAssistantReasoningMeta(s.pendingAssistantReasoningMeta),
    sources: normalizeAssistantSourceItems(s.pendingAssistantSources),
    rtStartAt: Math.max(0, Number(s.pendingAssistantRtStartAt || 0) || 0),
    rtFinalMs: Math.max(0, Number(s.pendingAssistantRtFinalMs || 0) || 0),
  });
  const nextSig = JSON.stringify({
    draft: nextDraft,
    status: nextStatus,
    process: nextProcess,
    streaming: nextStreaming,
    files: nextFiles,
    imageReplies: nextImageReplies,
    weatherPayload: nextWeatherPayload,
    reasoning: nextReasoning,
    reasoningMeta: nextReasoningMeta,
    sources: nextSources,
    rtStartAt: nextRtStartAt,
    rtFinalMs: nextRtFinalMs,
  });
  if(sessionObjectLastVisibleMessageIsAssistant(s) && !nextIsEmpty){
    if(!sessionHasPendingAssistantStateFields(s)) return;
    clearPendingAssistantFieldsFromSession(s);
    if(o.immediate) saveStore();
    else saveStoreThrottled();
    return;
  }
  if(!nextIsEmpty){
    const turnCandidate = {
      ...s,
      pendingAssistantDraft: nextDraft,
      pendingAssistantStatus: nextStatus,
      pendingAssistantProcess: nextProcess,
      pendingAssistantStreaming: nextStreaming,
      pendingAssistantFiles: nextFiles,
      pendingAssistantImageReplies: nextImageReplies,
      pendingAssistantWeatherPayload: nextWeatherPayload,
      pendingAssistantReasoning: nextReasoning,
      pendingAssistantReasoningMeta: nextReasoningMeta,
      pendingAssistantSources: nextSources,
      pendingAssistantRtStartAt: nextRtStartAt,
      pendingAssistantRtFinalMs: nextRtFinalMs,
      pendingAssistantUpdatedAt: Date.now(),
    };
    if(!pendingAssistantBelongsToCurrentTurn(turnCandidate)){
      if(clearPendingAssistantFieldsFromSession(s)){
        if(o.immediate) saveStore();
        else saveStoreThrottled();
      }
      return;
    }
  }
  if(prevSig === nextSig) return;
  if(nextIsEmpty){
    clearPendingAssistantFieldsFromSession(s);
  }else{
    s.pendingAssistantDraft = nextDraft;
    s.pendingAssistantStatus = nextStatus;
    s.pendingAssistantProcess = nextProcess;
    s.pendingAssistantStreaming = nextStreaming;
    s.pendingAssistantFiles = nextFiles;
    s.pendingAssistantImageReplies = nextImageReplies;
    s.pendingAssistantWeatherPayload = nextWeatherPayload;
    s.pendingAssistantReasoning = nextReasoning;
    s.pendingAssistantReasoningMeta = nextReasoningMeta;
    s.pendingAssistantSources = nextSources;
    s.pendingAssistantRtStartAt = nextRtStartAt;
    s.pendingAssistantRtFinalMs = nextRtFinalMs;
    s.pendingAssistantUserCreatedAtMs = _rtLatestUserCreatedMs(s) || 0;
    s.pendingAssistantUpdatedAt = now();
  }
  // pendingAssistant* 只是流式恢复快照，不能影响侧边栏聊天时间。
  if(o.immediate) saveStore();
  else saveStoreThrottled();
}

function clearPendingAssistantSnapshot(id, opts){
  persistPendingAssistantSnapshot(id, { draft:'', status:'', process:'', streaming:false, files:[], imageReplies:[], weatherPayload:null, reasoning:[], reasoningMeta:{}, sources:[], rtStartAt:0, rtFinalMs:0 }, opts);
}

function persistStreamingDraftsToStore(opts){
  const o = opts || {};
  let changed = false;
  for(const sid of Object.keys(sessionRuntime || {})){
    const rt = ensureSessionRuntime(sid);
    const draft = String(rt?.draftText || '');
    const status = String(rt?.statusText || '');
    const process = String(rt?.draftProcessText || '');
    const files = _normalizePendingAssistantFiles(rt?.draftFiles || []);
    const imageReplies = _normalizePendingAssistantImageReplies(rt?.draftImageReplies || []);
    const weatherPayload = normalizeAssistantWeatherPayload(rt?.draftWeatherPayload || null);
    const reasoning = _normalizePendingAssistantReasoning(rt?.reasoning || []);
    const reasoningMeta = _normalizePendingAssistantReasoningMeta(rt?.reasoningMeta || {});
    const sources = normalizeAssistantSourceItems(rt?.sources || []);
    const streaming = !!rt?.streaming;
    const s = getSessionById(sid);
    if(!s) continue;
    if(sessionObjectLastVisibleMessageIsAssistant(s)){
      if(clearPendingAssistantFieldsFromSession(s)) changed = true;
      continue;
    }
    const prevSig = JSON.stringify({
      draft: String(s.pendingAssistantDraft || ''),
      status: String(s.pendingAssistantStatus || ''),
      process: String(s.pendingAssistantProcess || ''),
      streaming: !!s.pendingAssistantStreaming,
      files: _normalizePendingAssistantFiles(s.pendingAssistantFiles),
      imageReplies: _normalizePendingAssistantImageReplies(s.pendingAssistantImageReplies),
      weatherPayload: normalizeAssistantWeatherPayload(s.pendingAssistantWeatherPayload || null),
      reasoning: _normalizePendingAssistantReasoning(s.pendingAssistantReasoning),
      reasoningMeta: _normalizePendingAssistantReasoningMeta(s.pendingAssistantReasoningMeta),
      sources: normalizeAssistantSourceItems(s.pendingAssistantSources),
      rtStartAt: Math.max(0, Number(s.pendingAssistantRtStartAt || 0) || 0),
      rtFinalMs: Math.max(0, Number(s.pendingAssistantRtFinalMs || 0) || 0),
    });
    const rtStartAt = Math.max(0, Number(rt?.rtStartAt || 0) || 0);
    const rtFinalMs = Math.max(0, Number(rt?.rtFinalMs || 0) || 0);
    const nextHasPending = !!(draft || status || process || streaming || files.length || imageReplies.length || weatherPayload || reasoning.length || Object.keys(reasoningMeta).length || sources.length);
    if(nextHasPending){
      const turnCandidate = {
        ...s,
        pendingAssistantDraft: draft,
        pendingAssistantStatus: status,
        pendingAssistantProcess: process,
        pendingAssistantStreaming: streaming,
        pendingAssistantFiles: files,
        pendingAssistantImageReplies: imageReplies,
        pendingAssistantWeatherPayload: weatherPayload,
        pendingAssistantReasoning: reasoning,
        pendingAssistantReasoningMeta: reasoningMeta,
        pendingAssistantSources: sources,
        pendingAssistantRtStartAt: rtStartAt,
        pendingAssistantRtFinalMs: rtFinalMs,
        pendingAssistantUpdatedAt: Date.now(),
      };
      if(!pendingAssistantBelongsToCurrentTurn(turnCandidate)){
        if(clearPendingAssistantFieldsFromSession(s)) changed = true;
        continue;
      }
    }
    const nextSig = JSON.stringify({ draft, status, process, streaming, files, imageReplies, weatherPayload, reasoning, reasoningMeta, sources, rtStartAt, rtFinalMs });
    if(prevSig !== nextSig){
      if(nextHasPending){
        s.pendingAssistantDraft = draft;
        s.pendingAssistantStatus = status;
        s.pendingAssistantProcess = process;
        s.pendingAssistantStreaming = streaming;
        s.pendingAssistantFiles = files;
        s.pendingAssistantImageReplies = imageReplies;
        s.pendingAssistantWeatherPayload = weatherPayload;
        s.pendingAssistantReasoning = reasoning;
        s.pendingAssistantReasoningMeta = reasoningMeta;
        s.pendingAssistantSources = sources;
        s.pendingAssistantRtStartAt = rtStartAt;
        s.pendingAssistantRtFinalMs = rtFinalMs;
        s.pendingAssistantUserCreatedAtMs = _rtLatestUserCreatedMs(s) || 0;
        s.rtStartAt = rtStartAt;
        s.rtFinalMs = rtFinalMs;
        s.pendingAssistantUpdatedAt = now();
      }else{
        clearPendingAssistantFieldsFromSession(s);
      }
      // 运行时快照落盘不代表真实聊天内容更新，不能刷新会话时间。
      changed = true;
    }
  }
  if(changed){
    if(o.immediate) saveStore();
    else saveStoreThrottled();
  }
  return changed;
}


function flushCloudStoreSyncNow(payload, opts){
  if(!currentAccountEmail || authKickRedirecting) return false;
  const o = opts || {};
  const rawPayload = String(payload || '').trim();
  if(!rawPayload) return false;
  const flushReason = String(o.reason || cloudSyncLastReason || '').trim();
  const allowExitKeepalive = o.keepalive !== false && /^(page_exit|page_exit_persisted|hidden_persist|visibility_hidden|beforeunload|pagehide|unload)/i.test(flushReason);
  if(!allowExitKeepalive && shouldPauseNonCriticalCloudSync()){
    cloudSyncQueuedPayload = rawPayload;
    writeScopedCloudSyncPending(currentAccountEmail, rawPayload, {
      lastReason: flushReason,
      retryCount: cloudSyncRetryCount,
      localUpdatedAt: storeLatestUpdatedAtMs(store),
    });
    scheduleCloudStoreSyncRetry(getCloudSyncWeakDebounceMs(CLOUD_SYNC_DEBOUNCE_MS), flushReason);
    return false;
  }
  let storeObj = null;
  try{ storeObj = JSON.parse(rawPayload); }catch(_){ return false; }
  const pushBody = buildCloudSyncPushBodyFromPayload(rawPayload, storeObj);
  if(!Array.isArray(pushBody.ops) || pushBody.ops.length <= 0){
    if(pushBody.ops_build_error){
      noteCloudSyncBuildProblem(String(pushBody.ops_build_error || 'cloud_sync_ops_build_failed'), rawPayload);
    }
    return false;
  }
  let body = JSON.stringify(pushBody);
  let endpoint = '/api3/chat-sync/push';
  cloudSyncQueuedPayload = rawPayload;
  writeScopedCloudSyncPending(currentAccountEmail, rawPayload, {
    lastReason: flushReason,
    retryCount: cloudSyncRetryCount,
    localUpdatedAt: storeLatestUpdatedAtMs(store),
  });
  let beaconSent = false;
  try{
    const bodyBytes = new Blob([body]).size;
    if((allowExitKeepalive || !shouldUseWeakNonCriticalMode()) && o.keepalive !== false && navigator.sendBeacon && bodyBytes <= 60 * 1024){
      const blob = new Blob([body], { type:'application/json' });
      beaconSent = !!navigator.sendBeacon(endpoint, blob);
    }
  }catch(_){ beaconSent = false; }
  if(!beaconSent){
    try{
      fetch(endpoint, {
        method:'POST',
        headers:{ 'Content-Type':'application/json' },
        body,
        keepalive:(allowExitKeepalive || !shouldUseWeakNonCriticalMode()) && o.keepalive !== false,
        cache:'no-store',
        credentials:'same-origin',
      }).then(async (res)=>{
        const data = await res.json().catch(()=>({}));
        if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || '当前登录已失效，请重新登录')) return;
        if(res.status === 404) throw new Error(data?.error || 'chat_sync_push_unavailable');
        if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
        applyCloudStoreSyncSuccess(rawPayload, data, { keepalive:true, partial: !!pushBody.ops_partial });
      }).catch(async (err)=>{
        console.warn('cloud store keepalive sync soft failed:', err);
        cloudSyncQueuedPayload = rawPayload;
        const reason = stableNetworkReason(err, 'keepalive_sync_failed');
        const verified = isSoftNetworkError(err) ? false : await verifyCloudStoreSyncApplied(rawPayload);
        if(!verified) scheduleCloudStoreSyncRetry(stableBackoffMs(Math.max(1, cloudSyncRetryCount + 1), 1800, CLOUD_SYNC_RETRY_MAX_MS), reason);
      });
    }catch(err){
      cloudSyncQueuedPayload = rawPayload;
      scheduleCloudStoreSyncRetry(stableBackoffMs(Math.max(1, cloudSyncRetryCount + 1), 1800, CLOUD_SYNC_RETRY_MAX_MS), stableNetworkReason(err, 'keepalive_sync_failed'));
    }
  }
  return beaconSent;
}

function flushPendingStoreWrites(opts){
  const o = opts || {};
  try{ if(_saveStoreTimer) clearTimeout(_saveStoreTimer); }catch(_){ }
  _saveStoreTimer = null;
  try{ persistStreamingDraftsToStore({ immediate:false }); }catch(_){ }
  const { slim, payload } = buildPersistableStorePayload();
  persistStorePayloadLocally(payload, slim);
  if(currentAccountEmail && !authKickRedirecting){
    writeScopedCloudSyncPending(currentAccountEmail, payload, {
      lastReason: String(o.reason || cloudSyncLastReason || '').trim(),
      retryCount: cloudSyncRetryCount,
      localUpdatedAt: storeLatestUpdatedAtMs(store),
    });
    if(o.cloud !== false){
      flushCloudStoreSyncNow(payload, { keepalive:o.keepalive !== false, reason:o.reason });
    }
  }
}

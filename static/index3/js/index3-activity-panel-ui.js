/* ChatGPT-like activity side panel: unified thinking + tool progress timeline. */
window.WEBAI_ACTIVITY_PANEL_ENABLED = true;
const WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT = 80;

let _activityPanelOpenSessionId = '';
let _activityPanelTargetMessage = null;
let _activityPanelTargetSnapshot = null;
let _activityPanelRunKey = '';
let _activityPanelLastSignature = '';
let _activityPanelLastStructureSignature = '';
let _activityPanelRefreshFrame = 0;
let _activityPanelRefreshTimer = 0;
let _activityPanelLastRefreshAt = 0;
let _activityPanelPendingRefreshOpts = null;
let _activityPanelLiveTimer = 0;
let _activityPanelLiveSessionId = '';
let _activityPanelVisualRunKey = '';
let _activityPanelSeenVisualKeys = new Set();
let _activityPanelEventStateByKey = new Map();
let _activitySourceIconObserver = null;

function _activityT(key, params=null, fallback=''){
  try{
    const value = window.AperviaI18n?.t(key, params || {});
    if(value && value !== key) return String(value);
  }catch(_){ }
  return String(fallback || '');
}

function _activityEventTitle(type, state, params={}){
  const phase = String(state || '').toLowerCase() === 'error'
    ? 'error'
    : (String(state || '').toLowerCase() === 'done' ? 'done' : 'active');
  const fallbacks = {
    mcp:{active:'Calling MCP tool',done:'MCP tool call completed',error:'MCP tool call failed'},
    image_analysis:{active:'Analyzing image',done:'Image analyzed',error:'Image analysis failed'},
    import_files:{active:'Importing files',done:'Files imported',error:'File import failed'},
    read_file:{active:'Reading file',done:'File read',error:'Unable to read file'},
    sandbox_run:{active:'Running sandbox check',done:'Sandbox check completed',error:'Sandbox check failed'},
    write_file:{active:'Writing file',done:'File written',error:'Unable to write file'},
    replace_text:{active:'Editing file',done:'File edited',error:'Unable to edit file'},
    publish_files:{active:'Preparing downloads',done:'Downloads ready',error:'Unable to prepare files'},
    office_file:{active:'Generating Office file',done:'Office file generated',error:'Office file generation failed'},
    knowledge_search:{active:'Searching knowledge base',done:'Knowledge base searched',error:'Knowledge-base search failed'},
    web_read:{active:'Reading web page',done:'Web page read',error:'Unable to read web page'},
    web_search:{active:'Searching the web',done:'Web search completed',error:'Web search failed'},
    image_search:{active:'Searching for images',done:'Image search completed',error:'Image search failed'},
    weather:{active:'Checking weather',done:'Weather checked',error:'Weather lookup failed'},
    image:{active:'Processing image',done:'Image processed',error:'Image processing failed'},
    answer:{active:'Generating answer',done:'Answer generated',error:'Answer generation failed'},
  };
  return _activityT(`activity.event.${type}.${phase}`, params, fallbacks[type]?.[phase] || 'Processing');
}

function _activitySandboxOperationTitle(operation, state){
  const key = String(operation || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  const fallbacks = {
    sandbox_run_skipped:{active:'Selecting a more suitable file tool',done:'Unnecessary code run skipped',error:'Unable to select a file tool'},
    sandbox_run_outputs:{active:'Generating sandbox files',done:'Sandbox files generated',error:'Unable to generate sandbox files'},
    sandbox_run_list_files:{active:'Listing sandbox files',done:'Sandbox files listed',error:'Unable to list sandbox files'},
    sandbox_run_find_files:{active:'Finding file paths',done:'File paths found',error:'Unable to find file paths'},
    sandbox_run_search_files:{active:'Searching file contents',done:'File contents searched',error:'Unable to search file contents'},
    sandbox_run_diff:{active:'Checking file differences',done:'File differences checked',error:'Unable to check file differences'},
    sandbox_run_tests:{active:'Running tests',done:'Tests completed',error:'Tests failed'},
    sandbox_run_python_capture:{active:'Running Python and capturing output',done:'Python output captured',error:'Python failed; output captured'},
    sandbox_run_script:{active:'Running script',done:'Script completed',error:'Script failed'},
    sandbox_run_check:{active:'Running sandbox check',done:'Sandbox check completed',error:'Sandbox check failed'},
  };
  if(!fallbacks[key]) return '';
  const normalizedState = String(state || '').trim().toLowerCase();
  const phase = normalizedState === 'error' ? 'error' : (['done','warn'].includes(normalizedState) ? 'done' : 'active');
  return _activityT(`activity.sandbox_operation.${key}.${phase}`, null, fallbacks[key][phase]);
}

function _activityPanelEnsureVisualRun(runKey){
  const key = String(runKey || '').trim();
  if(key === _activityPanelVisualRunKey) return;
  _activityPanelVisualRunKey = key;
  _activityPanelSeenVisualKeys = new Set();
  _activityPanelEventStateByKey = new Map();
}

function _activityPanelStableVisualKey(...parts){
  return parts.map(part => String(part ?? '').trim()).join('|').slice(0, 900);
}

function _activityPanelStableItemKey(item, itemIndex=0){
  const row = item && typeof item === 'object' ? item : {};
  const kind = row.kind || 'answer';
  return _activityPanelStableVisualKey('item', row.key || row.id || row.seq || row.ts || itemIndex, row.stage || row.kind || kind);
}

function _activityScheduleSourceIcon(img, src){
  if(!img || !src) return;
  img.dataset.src = String(src || '');
  const load = ()=>{
    const url = img.dataset.src || '';
    if(!url || img.src) return;
    img.src = url;
  };
  try{
    if(!('IntersectionObserver' in window)){
      load();
      return;
    }
    if(!_activitySourceIconObserver){
      _activitySourceIconObserver = new IntersectionObserver((entries)=>{
        for(const entry of entries || []){
          if(!entry || !entry.isIntersecting) continue;
          const target = entry.target;
          try{ _activitySourceIconObserver.unobserve(target); }catch(_){ }
          if(target && target.dataset) target.src = target.dataset.src || target.src || '';
        }
      }, { root:null, rootMargin:'160px 0px', threshold:0.01 });
    }
    _activitySourceIconObserver.observe(img);
  }catch(_){
    load();
  }
}

function _activityPanelMarkEnter(el, key, order=0, opts={}){
  if(!el || !key) return false;
  const fullKey = _activityPanelStableVisualKey(_activityPanelVisualRunKey, key);
  if(!fullKey || _activityPanelSeenVisualKeys.has(fullKey)) return false;
  _activityPanelSeenVisualKeys.add(fullKey);
  try{
    el.classList.add('activity-panel-enter');
    // 事件按实际到达顺序逐帧渲染，不再人为错峰延迟。
    el.style.setProperty('--activity-enter-delay', '0ms');
  }catch(_){ }
  return true;
}

function _activityPanelVisualStateForItem(item, context={}){
  const raw = String(item?.state || '').toLowerCase();
  if(raw === 'active') return 'active';
  if(raw === 'error' || raw === 'failed') return 'error';
  if(raw === 'warn' || raw === 'warning') return 'warn';
  if(context?.streaming && raw !== 'done' && raw !== 'complete' && raw !== 'completed') return 'active';
  return 'done';
}

function _activityPanelMarkEventState(el, key, nextState){
  if(!el || !key) return;
  const state = String(nextState || 'done').toLowerCase();
  const fullKey = _activityPanelStableVisualKey(_activityPanelVisualRunKey, key);
  if(!fullKey) return;
  const prev = _activityPanelEventStateByKey.get(fullKey) || '';
  _activityPanelEventStateByKey.set(fullKey, state);
  try{
    el.classList.toggle('activity-panel-event-active', state === 'active');
    el.classList.toggle('activity-panel-event-done', state === 'done');
    el.classList.toggle('activity-panel-event-error', state === 'error');
    if(prev === 'active' && state !== 'active') el.classList.add('activity-panel-event-settle');
  }catch(_){ }
}

function _activityPanelMarkTitleEventState(els, nextState){
  const head = els?.root ? els.root.querySelector('.activity-panel-head') : null;
  if(!head) return;
  const state = String(nextState || 'done').toLowerCase();
  const key = _activityPanelStableVisualKey(_activityPanelVisualRunKey, 'panel-title-event');
  const prev = _activityPanelEventStateByKey.get(key) || '';
  _activityPanelEventStateByKey.set(key, state);
  try{
    head.classList.toggle('activity-panel-title-event-active', state === 'active');
    head.classList.toggle('activity-panel-title-event-done', state === 'done');
    head.classList.toggle('activity-panel-title-event-error', state === 'error');
    if(prev === 'active' && state !== 'active') head.classList.add('activity-panel-title-event-settle');
    else head.classList.remove('activity-panel-title-event-settle');
  }catch(_){ }
}

function _activityPanelEls(){
  return {
    root: document.getElementById('activityPanel'),
    title: document.getElementById('activityPanelTitle'),
    elapsed: document.getElementById('activityPanelElapsed'),
    body: document.getElementById('activityPanelBody'),
    close: document.getElementById('activityPanelClose'),
  };
}

function _activityCurrentSessionId(sessionId){
  const visibleId = (typeof visibleChatSessionId !== 'undefined') ? visibleChatSessionId : '';
  const activeId = (typeof store !== 'undefined') ? (store?.activeId || '') : '';
  return String(sessionId || visibleId || activeId || '').trim();
}

function _activityPanelIsExplicitlyOpenForSession(sessionId){
  const sid = _activityCurrentSessionId(sessionId);
  return !!(sid && _activityPanelOpenSessionId === sid);
}

function _activityPanelHasOpenableRealActivity(sessionId, message, opts={}){
  const sid = _activityCurrentSessionId(sessionId);
  if(!sid) return false;
  const rt = (typeof ensureSessionRuntime === 'function') ? ensureSessionRuntime(sid) : null;
  const msg = (message && typeof message === 'object') ? message : null;
  let snapshot = null;
  try{
    snapshot = (opts?.reasoningSnapshot && typeof opts.reasoningSnapshot === 'object')
      ? opts.reasoningSnapshot
      : (msg ? _composeReasoningPanelSnapshot('', { message:msg }) : _composeReasoningPanelSnapshot(sid, {}));
  }catch(_){ snapshot = opts?.reasoningSnapshot || null; }
  const items = _activityNormalizeSnapshotItems(sid, snapshot || {}, {
    message: msg,
    finalSnapshot: !!(opts?.reasoningSnapshot && typeof opts.reasoningSnapshot === 'object'),
    // “正在思考中”等占位不属于真实活动；流式面板等待真实事件时改由骨架屏承载。
    allowRuntimeFallback:false,
  });
  return _activityHasRealPanelItems(items);
}

function openActivityPanelForMessage(sessionId, message, opts={}){
  const sid = _activityCurrentSessionId(sessionId);
  if(!sid) return;
  const rt = (typeof ensureSessionRuntime === 'function') ? ensureSessionRuntime(sid) : null;
  const msg = (message && typeof message === 'object') ? message : null;
  // 流式期间允许打开面板等待真实事件，但非流式空面板不应被打开。
  if(!_activityPanelHasOpenableRealActivity(sid, msg, opts || {}) && !rt?.streaming){
    if(_activityPanelIsExplicitlyOpenForSession(sid)) hideActivityPanelForVisibleSession();
    return;
  }
  _activityPanelOpenSessionId = sid;
  // 流式面板必须持续读取运行态，让首个真实事件能够替换骨架；历史消息才固定点击快照。
  _activityPanelTargetMessage = rt?.streaming ? null : msg;
  _activityPanelTargetSnapshot = rt?.streaming
    ? null
    : ((opts?.reasoningSnapshot && typeof opts.reasoningSnapshot === 'object') ? opts.reasoningSnapshot : null);
  refreshActivityPanelForVisibleSession(sid, { schedule:false, force:true });
}

function toggleActivityPanelForMessage(sessionId, message, opts={}){
  const sid = _activityCurrentSessionId(sessionId);
  if(!sid) return;
  const sameOpen = _activityPanelIsExplicitlyOpenForSession(sid);
  if(sameOpen) hideActivityPanelForVisibleSession();
  else openActivityPanelForMessage(sid, message, opts);
}

function _activityLastAssistantMessage(session){
  const msgs = Array.isArray(session?.messages) ? session.messages : [];
  for(let i = msgs.length - 1; i >= 0; i -= 1){
    const m = msgs[i];
    if(!m || String(m.role || '').toLowerCase() !== 'assistant') continue;
    if(m._image_context_only || m._pending_stream_image_reply) continue;
    return m;
  }
  return null;
}

function _activityElapsedLabel(sessionId, rt, message, snapshot){
  let ms = 0;
  try{
    const msgMs = (message && typeof _rtMessageElapsedMs === 'function') ? _rtMessageElapsedMs(message) : 0;
    const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
    const meta = snap.reasoningMeta && typeof snap.reasoningMeta === 'object' ? snap.reasoningMeta : {};
    const nativeStart = Math.max(
      Number(meta.nativeReasoningStartAt || meta.native_reasoning_start_at || 0) || 0,
      Number(snap.nativeReasoningStartAt || snap.native_reasoning_start_at || 0) || 0
    );
    const nativeEnd = Math.max(
      Number(meta.nativeReasoningEndAt || meta.native_reasoning_end_at || 0) || 0,
      Number(snap.nativeReasoningEndAt || snap.native_reasoning_end_at || 0) || 0
    );
    const turnMsgMs = message ? _activityMessageTurnElapsedMs(sessionId, message) : 0;
    if(message && msgMs > 0){
      ms = msgMs;
    }else if(message && turnMsgMs > 0){
      ms = turnMsgMs;
    }else if(nativeStart > 0 && (nativeEnd > 0 || rt?.streaming)){
      ms = Math.max(0, (nativeEnd || Date.now()) - nativeStart);
    }else if(rt?.streaming && Number(rt.rtStartAt || 0) > 0){
      ms = Date.now() - Number(rt.rtStartAt || 0);
    }else if(!message && Number(rt?.rtFinalMs || 0) > 0){
      ms = Number(rt.rtFinalMs || 0);
    }
  }catch(_){ ms = 0; }
  ms = Math.max(0, Number(ms || 0) || 0);
  if(ms <= 0) return '';
  if(typeof _formatReasoningElapsedShort === 'function') return _formatReasoningElapsedShort(ms);
  const sec = Math.max(0, Math.floor(ms / 1000));
  if(sec < 60) return _activityT('activity.elapsed_seconds', {count:sec}, `${sec}s`);
  const min = Math.floor(sec / 60);
  const rest = sec % 60;
  return rest
    ? _activityT('activity.elapsed_minutes_seconds', {minutes:min, seconds:rest}, `${min}m ${rest}s`)
    : _activityT('activity.elapsed_minutes', {count:min}, `${min}m`);
}


function _activityEventMs(value){
  const n = Number(value || 0) || 0;
  if(!(n > 0)) return 0;
  return n < 10000000000 ? n * 1000 : n;
}

function _activityNormalizeEventTs(value, fallback=0){
  let n = Number(value || 0) || 0;
  if(n > 0 && n < 10000000000) n *= 1000;
  return n > 0 ? n : fallback;
}

function _activityElapsedLabelFromActivityData(data){
  try{
    const items = Array.isArray(data?.items) ? data.items : [];
    let start = 0;
    let end = 0;
    let hasActive = !!data?.rt?.streaming;
    for(const item of items){
      if(!item || typeof item !== 'object') continue;
      const itemStart = _activityEventMs(item.startedAt || item.started_at || item.ts || item.createdAt || item.created_at);
      const itemUpdated = _activityEventMs(item.updatedAt || item.updated_at || item.doneAt || item.done_at || item.ts);
      const itemDone = _activityEventMs(item.doneAt || item.done_at || item.finishedAt || item.finished_at || item.completedAt || item.completed_at);
      if(itemStart > 0) start = start ? Math.min(start, itemStart) : itemStart;
      end = Math.max(end, itemDone || itemUpdated || itemStart || 0);
      if(String(item.state || '').toLowerCase() === 'active') hasActive = true;
    }
    if(start > 0){
      const stop = hasActive ? Date.now() : (end || Date.now());
      const ms = Math.max(0, stop - start);
      if(typeof _formatReasoningElapsedShort === 'function') return _formatReasoningElapsedShort(ms);
      const sec = Math.max(0, Math.floor(ms / 1000));
      if(sec < 60) return _activityT('activity.elapsed_seconds', {count:sec}, `${sec}s`);
      const min = Math.floor(sec / 60);
      const rest = sec % 60;
      return rest
        ? _activityT('activity.elapsed_minutes_seconds', {minutes:min, seconds:rest}, `${min}m ${rest}s`)
        : _activityT('activity.elapsed_minutes', {count:min}, `${min}m`);
    }
  }catch(_){ }
  return _activityElapsedLabel(data?.sid || '', data?.rt || null, data?.message || null, data?.snapshot || null);
}

function _activityPublicFileLabel(value){
  let raw = String(value == null ? '' : value).replace(/\\/g, '/').trim();
  if(!raw) return '';
  raw = raw.replace(/[?#].*$/g, '').replace(/\/+$/g, '');
  const parts = raw.split('/').filter(Boolean);
  let name = parts.length ? parts[parts.length - 1] : raw;
  name = String(name || '').trim();
  if(!name || name === '.' || name === '..') return _activityT('activity.workspace', null, 'Workspace');
  try{ name = decodeURIComponent(name); }catch(_){ }
  return name.slice(0, 120);
}

function _activityCleanSandboxPaths(text){
  // Keep sandbox command/output text byte-faithful: never rewrite /mnt/data paths.
  // Public filename labels are handled only by file-chip helpers, not by stdout/code renderers.
  return String(text == null ? '' : text);
}

function _activityCollectFileNames(value, limit=80){
  const out = [];
  const seen = new Set();
  const max = Math.max(1, Math.min(Number(limit || 80) || 80, 200));
  const add = (v)=>{
    if(v == null) return;
    if(Array.isArray(v)){ v.forEach(add); return; }
    if(typeof v === 'object'){
      add(v.display_name || v.displayName || v.filename || v.target_filename || v.targetFilename || v.name || v.path || v.url || v.href);
      add(v.fileNames || v.file_names || v.filenames || v.files_preview || v.file_preview || v.paths || v.files);
      return;
    }
    const name = _activityPublicFileLabel(v);
    if(!name || name === '文件' || name === _activityT('activity.file_generic', null, 'File')) return;
    const key = name.toLowerCase();
    if(seen.has(key)) return;
    seen.add(key);
    if(out.length < max) out.push(name);
  };
  add(value);
  return { names: out, total: seen.size };
}

function _activityNormalizeFileNames(value, limit=10){
  const collected = _activityCollectFileNames(value, Math.max(1, Math.min(Number(limit || 10) || 10, 24)));
  return collected.names.slice(0, Math.max(1, Math.min(Number(limit || 10) || 10, 24)));
}

function _activityMergeFileNames(...lists){
  return _activityNormalizeFileNames(lists.flatMap(x => Array.isArray(x) ? x : (x ? [x] : [])), 24);
}

function _activityCountFileNames(...lists){
  return _activityCollectFileNames(lists.flatMap(x => Array.isArray(x) ? x : (x ? [x] : [])), 1).total;
}

function _activityCleanText(text, maxLen=280){
  let s = _activityCleanSandboxPaths(text).replace(/\r\n?/g, '\n').trim();
  if(!s) return '';
  const sandboxEnvironment = _activityT('activity.sandbox_environment', null, 'Sandbox environment');
  const sandbox = _activityT('activity.sandbox', null, 'Sandbox');
  const fileNotFound = _activityT('activity.file_not_found', null, 'File not found');
  s = s
    .replace(/\bexec_id\s*[:=]\s*[\w\-]+/giu, '')
    .replace(/\btool_call_id\s*[:=]\s*[\w\-]+/giu, '')
    .replace(/\bapp3-sandbox:[\w.\-]+\b/giu, sandboxEnvironment)
    .replace(/Docker\s+sandbox/giu, sandbox)
    .replace(/docker\s+image/giu, sandboxEnvironment)
    .replace(/file_not_found/giu, fileNotFound)
    .replace(/sandbox_(?:import_files|read_file|write_file|write_files|replace_text|run|publish_files|create_office_file|list_files)/giu, '')
    .replace(/\s+/g, ' ')
    .trim();
  if(s.length > maxLen) s = s.slice(0, Math.max(1, maxLen - 1)).trimEnd() + '…';
  return s;
}

function _activityCleanLongText(text, maxLen=1600){
  let s = _activityCleanSandboxPaths(text).replace(/\r\n?/g, '\n').trim();
  if(!s) return '';
  const sandboxEnvironment = _activityT('activity.sandbox_environment', null, 'Sandbox environment');
  const sandbox = _activityT('activity.sandbox', null, 'Sandbox');
  const fileNotFound = _activityT('activity.file_not_found', null, 'File not found');
  s = s
    .replace(/\bexec_id\s*[:=]\s*[\w\-]+/giu, '')
    .replace(/\btool_call_id\s*[:=]\s*[\w\-]+/giu, '')
    .replace(/\bapp3-sandbox:[\w.\-]+\b/giu, sandboxEnvironment)
    .replace(/Docker\s+sandbox/giu, sandbox)
    .replace(/docker\s+image/giu, sandboxEnvironment)
    .replace(/file_not_found/giu, fileNotFound)
    .replace(/sandbox_(?:import_files|read_file|write_file|write_files|replace_text|run|publish_files|create_office_file|list_files)/giu, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if(s.length > maxLen) s = s.slice(0, Math.max(1, maxLen - 1)).trimEnd() + '…';
  return s;
}


function _activityRawText(text){
  return _sanitizeNativeReasoningDisplayText(text).trim();
}

function _activityIsGenericNativeReasoningTitle(title){
  const s = String(title || '').replace(/\s+/g, ' ').trim();
  return !s || /^(?:思考|思考中|已思考|推理|推理中|已完成|处理中|Thinking|Thinking\.\.\.|Reasoning|Reasoning\.\.\.)$/i.test(s);
}

function _activityPanelCancelScheduledRefresh(){
  try{ if(_activityPanelRefreshTimer) clearTimeout(_activityPanelRefreshTimer); }catch(_){ }
  _activityPanelRefreshTimer = 0;
  try{ if(_activityPanelRefreshFrame) cancelAnimationFrame(_activityPanelRefreshFrame); }catch(_){ }
  _activityPanelRefreshFrame = 0;
  _activityPanelPendingRefreshOpts = null;
}

function _activityPanelMergeRefreshOpts(prev, next){
  const a = (prev && typeof prev === 'object') ? prev : {};
  const b = (next && typeof next === 'object') ? next : {};
  const prevThrottle = Number(a.throttleMs || 0) || 0;
  const nextThrottle = Number(b.throttleMs || 0) || 0;
  const throttle = prevThrottle && nextThrottle ? Math.min(prevThrottle, nextThrottle) : (nextThrottle || prevThrottle || 0);
  return {
    ...a,
    ...b,
    ...(throttle ? { throttleMs:throttle } : {}),
    force:!!(a.force || b.force),
    immediate:!!(a.immediate || b.immediate),
  };
}

function _activityPanelCaptureScrollAnchor(body){
  if(!body) return null;
  const scrollHeight = Number(body.scrollHeight || 0) || 0;
  const clientHeight = Number(body.clientHeight || 0) || 0;
  const scrollTop = Number(body.scrollTop || 0) || 0;
  const maxTop = Math.max(0, scrollHeight - clientHeight);
  const nearBottom = maxTop - scrollTop <= 42;
  const rootRect = body.getBoundingClientRect ? body.getBoundingClientRect() : null;
  let key = '';
  let offset = 0;
  if(rootRect){
    const rows = body.querySelectorAll ? body.querySelectorAll('[data-activity-key]') : [];
    for(const row of rows){
      const rect = row.getBoundingClientRect ? row.getBoundingClientRect() : null;
      if(!rect) continue;
      if(rect.bottom >= rootRect.top + 8){
        key = String(row.getAttribute('data-activity-key') || '');
        offset = rect.top - rootRect.top;
        break;
      }
    }
  }
  return { scrollTop, scrollHeight, nearBottom, key, offset };
}

function _activityPanelRestoreScrollAnchor(body, anchor){
  if(!body || !anchor) return;
  try{
    if(anchor.nearBottom){
      body.scrollTop = Math.max(0, Number(body.scrollHeight || 0) || 0);
      return;
    }
    if(anchor.key && body.querySelector){
      const escaped = (typeof CSS !== 'undefined' && CSS.escape) ? CSS.escape(anchor.key) : anchor.key.replace(/["\\]/g, '\\$&');
      const row = body.querySelector(`[data-activity-key="${escaped}"]`);
      const rootRect = body.getBoundingClientRect ? body.getBoundingClientRect() : null;
      const rect = row && row.getBoundingClientRect ? row.getBoundingClientRect() : null;
      if(rootRect && rect){
        body.scrollTop += (rect.top - rootRect.top) - Number(anchor.offset || 0);
        return;
      }
    }
    body.scrollTop = Math.max(0, Number(anchor.scrollTop || 0) || 0);
  }catch(_){ }
}

function _activityIsNativeReasoningTransitionTitle(title){
  const s = String(title || '').replace(/\s+/g, ' ').trim();
  if(!s) return false;
  return /^(?:Now|Then|Next|Also|Finally|Overall|Meanwhile|Additionally|However|So|Ok|Okay)$/i.test(s);
}

function _activityNativeReasoningTitleShouldBreak(title){
  const s = String(title || '').replace(/\s+/g, ' ').trim();
  if(!s || _activityIsGenericNativeReasoningTitle(s) || _activityIsNativeReasoningTransitionTitle(s)) return false;
  if(s.length <= 6 && /^[A-Za-z]+$/.test(s)) return false;
  return true;
}

function _activityExtractNativeReasoningTitleAndBody(text){
  const raw = _activityRawText(text)
    .replace(/^\s+/, '')
    .replace(/\n{3,}/g, '\n\n');
  if(!raw) return { title:'', body:'' };
  // Native reasoning often sends its own short section title as a bold line:
  // **Checking for recent information**
  // Use that real model-provided title for the activity row instead of the
  // generic "思考", and remove it from the body to avoid duplicated titles.
  const bold = raw.match(/^\s*\*\*([^*\n][^*\n]{0,180}?)\*\*\s*(?:\n+)?/);
  if(bold){
    const title = _activityCleanText(bold[1], 96);
    const body = raw.slice(bold[0].length).replace(/^\s+/, '').replace(/\n{3,}/g, '\n\n').trim();
    if(title && _activityNativeReasoningTitleShouldBreak(title)) return { title, body };
  }
  return { title:'', body:raw.trim() };
}

function _activityJoinReasoningText(prevText, nextText){
  const left = String(prevText == null ? '' : prevText).replace(/\r\n?/g, '\n');
  const right = String(nextText == null ? '' : nextText).replace(/\r\n?/g, '\n');
  if(!left) return right;
  if(!right) return left;
  if(/\n\s*$/.test(left) || /^\s*\n/.test(right)) return left + right;
  const leftTrim = left.trimEnd();
  const rightTrim = right.trimStart();
  const rightLooksLikeBlock = /^(?:#{1,6}\s+|>\s*|[-*+]\s+|\d{1,9}[.)]\s+|```|~~~|\|)/.test(rightTrim)
    || /^(?:\*\*|__)[^\n*_#][\s\S]{1,140}(?:\*\*|__)(?:\s*$|\s*\n)/.test(rightTrim);
  if(rightLooksLikeBlock) return `${leftTrim}\n\n${rightTrim}`;
  if(/[A-Za-z0-9\u4e00-\u9fff][.!?。！？：:]$/.test(leftTrim) && /^[A-Za-z0-9\u4e00-\u9fff]/.test(rightTrim)){
    return `${leftTrim} ${rightTrim}`;
  }
  return left + right;
}

function _activityCodeText(text){
  return String(text == null ? '' : text).replace(/\r\n?/g, '\n').replace(/\s+$/g, '');
}

function _activityDisplayCodeText(text){
  return _activityCodeText(text);
}


function _activityReasoningMarkdownSource(text){
  let s = _activityRawText(text);
  if(!s) return '';
  // Some upstream/tool snapshots can carry escaped newlines as literal "\\n".
  // Keep this scoped to reasoning display so commands/stdout stay exact.
  if(s.includes('\\n') && !s.includes('\n')){
    s = s.replace(/\\n/g, '\n');
  }
  return s.trim();
}


function _activitySourceHost(url){
  try{
    const u = new URL(String(url || '').trim());
    return String(u.hostname || '').replace(/^www\./i, '').trim();
  }catch(_){ return ''; }
}

function _activityFallbackFaviconUrl(src){
  try{
    const rawHost = String(src?.host || '').trim().replace(/^www\./i, '');
    const host = rawHost || _activitySourceHost(src?.url || '');
    if(!host) return '';
    return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`;
  }catch(_){ return ''; }
}

function _activityNormalizeSourceItems(items, limit=WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const out = [];
  const seen = new Set();
  const configuredMax = Math.max(4, Number(window.WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT || WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT || 24) || 24);
  const requested = Number(limit || configuredMax) || configuredMax;
  const max = Math.max(1, Math.min(requested, configuredMax));
  for(const raw of source){
    if(!raw || typeof raw !== 'object') continue;
    const url = String(raw.url || raw.href || raw.link || raw.uri || raw.source_url || raw.sourceUrl || raw.page_url || raw.pageUrl || raw.canonical_url || raw.canonicalUrl || '').trim();
    const host = String(raw.host || raw.domain || _activitySourceHost(url) || '').trim().replace(/^www\./i, '');
    const title = _activityCleanText(raw.title || raw.label || raw.name || host || url, 90);
    let favicon = String(raw.favicon || raw.icon || raw.iconUrl || raw.icon_url || '').trim();
    if(!title && !host && !url) continue;
    if(!favicon) favicon = _activityFallbackFaviconUrl({ host, url });
    const key = String(host || url || title).toLowerCase();
    if(!key || seen.has(key)) continue;
    seen.add(key);
    out.push({
      title: title || host || url,
      url: url.slice(0, 800),
      host: host.slice(0, 120),
      favicon: favicon.slice(0, 1000),
    });
    if(out.length >= max) break;
  }
  return out;
}

function _activityNormalizeImageItems(items, limit=8){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const out = [];
  const seen = new Set();
  const max = Math.max(1, Math.min(Number(limit || 8) || 8, 12));
  for(const raw of source){
    const row = typeof raw === 'string' ? { image_id:raw } : (raw && typeof raw === 'object' ? raw : null);
    if(!row) continue;
    const imageId = String(row.image_id || row.imageId || row.stable_image_id || row.stableImageId || row.role_image_id || row.roleImageId || '').trim();
    const attachmentId = String(row.attachment_id || row.attachmentId || '').trim();
    const fileLibraryId = String(row.file_library_id || row.fileLibraryId || row.library_file_id || row.libraryFileId || row.file_registry?.file_id || '').trim();
    const storageRef = String(row.storage_ref || row.storageRef || '').trim();
    const modelStorageRef = String(row.model_storage_ref || row.modelStorageRef || '').trim();
    const previewUrl = String(row.preview_url || row.previewUrl || row._preview_url || '').trim();
    const viewUrl = String(row.view_url || row.viewUrl || '').trim();
    const imageUrl = row.image_url && typeof row.image_url === 'object' ? String(row.image_url.url || '').trim() : String(row.image_url || row.imageUrl || '').trim();
    const url = String(row.url || imageUrl || '').trim();
    const key = String(imageId || attachmentId || fileLibraryId || modelStorageRef || storageRef || viewUrl || previewUrl || url).toLowerCase();
    if(!key || seen.has(key)) continue;
    seen.add(key);
    out.push({
      ...row,
      image_id:imageId,
      attachment_id:attachmentId,
      file_library_id:fileLibraryId,
      storage_ref:storageRef,
      model_storage_ref:modelStorageRef,
      preview_url:previewUrl,
      view_url:viewUrl,
      url,
      filename:String(row.filename || row.name || row.title || '').trim(),
    });
    if(out.length >= max) break;
  }
  return out;
}

function _activityNormalizeDocumentVisualItems(items, limit=12){
  const source = Array.isArray(items) ? items : [];
  const out = [];
  const seen = new Set();
  const max = Math.max(1, Math.min(Number(limit || 12) || 12, 24));
  for(const raw of source){
    if(!raw || typeof raw !== 'object') continue;
    const previewUrl = String(raw.preview_url || raw.previewUrl || '').trim();
    if(!previewUrl.startsWith('/api3/sandbox-visual-preview/')) continue;
    const pageNumber = Math.max(0, Number(raw.page_number || raw.pageNumber || 0) || 0);
  const pageLabel = String(raw.page_label || raw.pageLabel || raw.label || (pageNumber
    ? _activityT('activity.document_page', {count:pageNumber}, `Page ${pageNumber}`)
    : _activityT('activity.document_pages', null, 'Document pages'))).trim();
    const key = `${pageNumber}|${previewUrl}`;
    if(seen.has(key)) continue;
    seen.add(key);
    out.push({
      previewUrl,
      pageNumber,
      pageLabel,
      documentName:String(raw.document_name || raw.documentName || '').trim(),
      totalPages:Math.max(0, Number(raw.total_pages || raw.totalPages || 0) || 0),
      visualExecId:String(raw.visual_exec_id || raw.visualExecId || '').trim(),
    });
    if(out.length >= max) break;
  }
  return out;
}

function _activityImageIdentitySet(item){
  const row = item && typeof item === 'object' ? item : {};
  return new Set([
    row.image_id, row.imageId, row.stable_image_id, row.stableImageId, row.role_image_id, row.roleImageId,
    row.attachment_id, row.attachmentId, row.file_library_id, row.fileLibraryId, row.library_file_id, row.libraryFileId,
    row.storage_ref, row.storageRef, row.model_storage_ref, row.modelStorageRef, row.file_registry?.file_id,
  ].map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
}

function _activitySessionImageCandidates(sessionId){
  const session = (typeof getSessionById === 'function') ? getSessionById(sessionId) : null;
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const rows = [];
  const add = (value)=>{
    if(!value) return;
    if(Array.isArray(value)){
      value.forEach(add);
      return;
    }
    if(typeof value !== 'object') return;
    if(Array.isArray(value.images)) value.images.forEach(add);
    if(value.image_url || value.imageUrl || value.image_id || value.imageId || value.attachment_id || value.attachmentId || value.model_storage_ref || value.storage_ref){
      rows.push(value);
    }
  };
  for(const message of messages){
    const content = message?.content;
    if(Array.isArray(content)) content.forEach(add);
    else if(content && typeof content === 'object') add(content);
    add(message?.images);
    add(message?.imageReplies);
    add(message?.image_replies);
  }
  return _activityNormalizeImageItems(rows, 80);
}

function _activityResolveImagePreviewItems(sessionId, items, limit=8){
  const requested = _activityNormalizeImageItems(items, limit);
  if(!requested.length) return [];
  const candidates = _activitySessionImageCandidates(sessionId);
  const resolved = [];
  for(const item of requested){
    const ids = _activityImageIdentitySet(item);
    const matched = ids.size ? candidates.find(candidate => {
      const candidateIds = _activityImageIdentitySet(candidate);
      return Array.from(ids).some(id => candidateIds.has(id));
    }) : null;
    const merged = matched ? { ...matched, ...item } : item;
    let display = '';
    let openUrl = '';
    try{ if(typeof imageItemDisplayUrl === 'function') display = imageItemDisplayUrl(merged); }catch(_){ }
    try{ if(typeof imageItemOpenUrl === 'function') openUrl = imageItemOpenUrl(merged); }catch(_){ }
    if(!display){
      try{ if(typeof composerLibraryDisplayImageUrl === 'function') display = composerLibraryDisplayImageUrl(merged); }catch(_){ }
    }
    display = String(display || merged.preview_url || merged.view_url || merged.url || '').trim();
    openUrl = String(openUrl || merged.view_url || merged.url || display).trim();
    if(!display) continue;
    resolved.push({
      ...merged,
      displayUrl:display,
      openUrl,
      alt:String(merged.filename || merged.alt || merged.title || _activityT('activity.analyzed_image', null, 'Analyzed image')).trim() || _activityT('activity.analyzed_image', null, 'Analyzed image'),
    });
    if(resolved.length >= limit) break;
  }
  return resolved;
}

function _activityCountSourceItems(items){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const seen = new Set();
  for(const raw of source){
    if(!raw || typeof raw !== 'object') continue;
    const url = String(raw.url || raw.href || raw.link || raw.uri || raw.source_url || raw.sourceUrl || raw.page_url || raw.pageUrl || raw.canonical_url || raw.canonicalUrl || '').trim();
    const host = String(raw.host || raw.domain || _activitySourceHost(url) || '').trim().replace(/^www\./i, '');
    const title = _activityCleanText(raw.title || raw.label || raw.name || host || url, 90);
    if(!title && !host && !url) continue;
    const key = String(host || url || title).toLowerCase();
    if(!key || seen.has(key)) continue;
    seen.add(key);
  }
  return seen.size;
}

function _activitySourcesFromSnapshot(snapshot){
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const meta = snap.reasoningMeta && typeof snap.reasoningMeta === 'object' ? snap.reasoningMeta : {};
  const pools = [];
  const addPool = (v)=>{ if(Array.isArray(v) && v.length) pools.push(v); };
  // Search result websites and opened/read page sources may arrive under
  // several legacy/new keys.  Keep them all here; _activityNormalizeSourceItems
  // dedupes by URL/host/title.
  // Only use websites returned by search here.  Do not mix in meta.sources /
  // citations / fetched pages: those are pages the assistant opened/read later,
  // while the activity search chips should represent the search result list.
  addPool(meta.searchResults || meta.search_results);
  addPool(meta.searchedResults || meta.searched_results);
  addPool(meta.search_results_raw || meta.searched_results_raw);
  addPool(meta.sourceItems || meta.source_items);
  addPool(snap.searchResults || snap.search_results);
  addPool(snap.searchedResults || snap.searched_results);
  addPool(snap.sourceItems || snap.source_items);
  const addGroupPools = (rows)=>{
    if(!Array.isArray(rows)) return;
    rows.forEach(row => {
      if(!row || typeof row !== 'object') return;
      addPool(row.sourceItems || row.source_items || row.searchResults || row.search_results || row.results || row.items);
    });
  };
  addGroupPools(meta.webQueryGroups || meta.web_query_groups);
  addGroupPools(snap.webQueryGroups || snap.web_query_groups);
  let merged = [];
  for(const pool of pools){
    try{
      if(typeof normalizeAssistantSourceItems === 'function'){
        const normalized = normalizeAssistantSourceItems(pool);
        if(Array.isArray(normalized) && normalized.length){
          merged = merged.concat(normalized);
          continue;
        }
      }
    }catch(_){ }
    merged = merged.concat(pool);
  }
  const normalized = _activityNormalizeSourceItems(merged, WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
  const total = _activityCountSourceItems(merged);
  try{
    Object.defineProperty(normalized, '_activityTotalCount', { value:total, enumerable:false });
  }catch(_){
    try{ normalized._activityTotalCount = total; }catch(__){ }
  }
  return normalized;
}

function _activitySearchTitleFromQueries(queries, fallback=''){
  const arr = Array.isArray(queries) ? queries.map(q => _activityCleanText(q, 72)).filter(Boolean) : [];
  if(!arr.length) return fallback || _activityEventTitle('web_search', 'done');
  const first = arr[0];
  return _activityT('activity.search_query', {query:first}, `Search: ${first}`);
}

function _activityKnowledgeTitle(title,state){
  const match=String(title||'').match(/命中\s*(\d+)/);
  return match
    ?_activityT('activity.knowledge_hits',{count:Number(match[1]||0)},`Knowledge base: ${match[1]} matches`)
    :_activityEventTitle('knowledge_search',state);
}

function _activitySearchSystemTitle(title,state){
  const raw=String(title||'').trim();
  const sourceMatch=raw.match(/检索到\s*(\d+)\s*个(引用|图片)?来源/);
  if(sourceMatch){
    const key=sourceMatch[2]==='图片'?'activity.image_sources_found':'activity.sources_found';
    return _activityT(key,{count:Number(sourceMatch[1]||0)},`${sourceMatch[1]} sources found`);
  }
  const roundMatch=raw.match(/第\s*(\d+)\s*次搜索/);
  if(roundMatch){
    const round=Number(roundMatch[1]||0);
    return _activityT(state==='done'?'activity.search_round_done':'activity.search_round_active',{round},state==='done'?`Search ${round}`:`Search ${round} in progress`);
  }
  return _activityEventTitle('web_search',state);
}

function _activityIsSyntheticSearchSummaryItem(item){
  if(!item || typeof item !== 'object') return false;
  const key = String(item.key || '').toLowerCase();
  const title = String(item.title || '').trim();
  return key.startsWith('activity_sources|')
    || key.startsWith('activity_global_sources|')
    || /^已搜索\s*\d+\s*个网站$/.test(title);
}

function _activityIsInternalToolInvocationItem(item){
  if(!item || typeof item !== 'object') return false;
  const tool = String(item.tool || '').trim().toLowerCase();
  if(['sandbox_run','sandbox_list_files'].includes(tool)) return false;
  const stage = String(item.stage || item.rawStage || item.raw_stage || item.panelStage || item.panel_stage || '').trim().toLowerCase();
  const source = String(item.source || '').trim().toLowerCase();
  const actionType = String(item.actionType || item.action_type || item.activityOp || item.activity_op || '').trim().toLowerCase();
  if(stage === 'tool_call' || source === 'tool_call_debug' || actionType === 'tool_call_debug') return true;
  const title = String(item.title || item.text || '').trim();
  const prefix = String.fromCharCode(24050, 35843, 29992, 24037, 20855);
  return title.startsWith(prefix);
}

function _activityDisplayTitleForItem(item, fallback=''){
  const title = String(fallback || item?.title || '').trim();
  return title;
}

function _activityAttachSnapshotSources(items, snapshot){
  const arr = Array.isArray(items) ? items.slice() : [];
  return arr.filter(item => !_activityIsSyntheticSearchSummaryItem(item));
}

function _activityMessageTurnElapsedMs(sessionId, message){
  try{
    if(!message || typeof message !== 'object' || typeof _rtMessageCreatedMs !== 'function') return 0;
    const assistantMs = _rtMessageCreatedMs(message);
    if(!(assistantMs > 0)) return 0;
    const sid = _activityCurrentSessionId(sessionId);
    const session = (sid && typeof getSessionById === 'function') ? getSessionById(sid) : null;
    const msgs = Array.isArray(session?.messages) ? session.messages : [];
    let msgIndex = -1;
    for(let i = 0; i < msgs.length; i += 1){
      if(msgs[i] === message){ msgIndex = i; break; }
    }
    if(msgIndex < 0){
      for(let i = 0; i < msgs.length; i += 1){
        const m = msgs[i];
        if(String(m?.role || '').toLowerCase() !== 'assistant') continue;
        if(_rtMessageCreatedMs(m) === assistantMs && String(m?.content || '') === String(message.content || '')){ msgIndex = i; break; }
      }
    }
    if(msgIndex <= 0) return 0;
    for(let j = msgIndex - 1; j >= 0; j -= 1){
      const prev = msgs[j];
      if(String(prev?.role || '').toLowerCase() !== 'user') continue;
      const userMs = _rtMessageCreatedMs(prev);
      if(userMs > 0 && assistantMs >= userMs) return Math.max(0, assistantMs - userMs);
      break;
    }
  }catch(_){ }
  return 0;
}

function _activityToolLabel(tool){
  const key = String(tool || '').trim().toLowerCase();
  const fallback = {
    sandbox_import_files:'Read uploaded files',
    sandbox_read_file:'Read file',
    sandbox_write_file:'Write file',
    sandbox_write_files:'Write files',
    sandbox_replace_text:'Edit file',
    sandbox_run:'Run check',
    sandbox_publish_files:'Prepare downloads',
    sandbox_create_office_file:'Generate Office file',
    sandbox_list_files:'List sandbox files',
    web_search:'Search the web',
    web_fetch:'Read web page',
    fetch_url:'Read web page',
    fetch_urls:'Read web pages',
    get_weather:'Check weather',
    image_generation:'Generate image',
    knowledge_search:'Search knowledge base',
  }[key] || '';
  return fallback ? _activityT(`activity.tool.${key}`, null, fallback) : '';
}

function _activityTitleByState(activeTitle, doneTitle, errorTitle, state){
  const s = String(state || '').toLowerCase();
  if(s === 'error') return errorTitle || activeTitle || doneTitle;
  if(s === 'done') return doneTitle || activeTitle;
  return activeTitle || doneTitle || errorTitle;
}

function _activityNormalizeItem(raw, index=0){
  const item = raw && typeof raw === 'object' ? raw : {};
  const stateRaw = String(item.state || '').trim().toLowerCase();
  const state = /^(active|done|warn|error)$/.test(stateRaw) ? stateRaw : 'done';
  const stage = String(item.stage || '').trim().toLowerCase();
  const rawStage = String(item.rawStage || item.raw_stage || '').trim().toLowerCase();
  const tool = String(item.tool || '').trim().toLowerCase();
  const actionType = String(item.action_type || item.actionType || item.activity_op || item.activityOp || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  const rawTitleText = String(item.title || (stage === 'think' ? '' : item.text) || '');
  const rawDetailText = String(item.detail || '');
  const titleRaw = _activityCleanText(rawTitleText, 180);
  const detectText = _activityCleanText(item.title || item.text || '', 180);
  const isNativeReasoningItem = String(item.key || '').trim() === 'native_reasoning' || stage === 'think' || /思考|推理/.test(`${detectText} ${rawStage}`);
  const nativeReasoningTextRaw = isNativeReasoningItem ? _activityRawText(rawDetailText || item.text || '') : '';
  const nativeReasoningTitleBody = isNativeReasoningItem ? _activityExtractNativeReasoningTitleAndBody(nativeReasoningTextRaw) : { title:'', body:'' };
  const detailRaw = isNativeReasoningItem ? (nativeReasoningTitleBody.body || nativeReasoningTextRaw) : _activityCleanText(rawDetailText, 320);
  const combined = `${titleRaw} ${detailRaw.slice(0, 320)} ${rawStage} ${tool}`.trim();
  const toolLabel = _activityToolLabel(tool);
  const sandboxOperationTitle = _activitySandboxOperationTitle(actionType, state);
  let title = titleRaw || toolLabel || _activityT('activity.processing', null, 'Processing');
  let detail = detailRaw;
  let kind = stage || 'answer';
  let renderMode = isNativeReasoningItem ? 'markdown' : 'auto';
  const toolInvokePrefix = String.fromCharCode(24050, 35843, 29992, 24037, 20855);
  if((String(title || '').trim().startsWith(toolInvokePrefix) || rawStage === 'tool_call') && !['sandbox_run','sandbox_list_files'].includes(tool)){
    title = '';
    detail = '';
    kind = 'internal';
  }

  if(isNativeReasoningItem){
    kind = 'think';
    // Native reasoning rows should keep the provider's real section title when
    // it exists. If the provider sends only reasoning text, do not invent a
    // generic "思考/思考中" title; rendering can show a title-less row.
    const nativeReasoningTitle = nativeReasoningTitleBody.title || (!_activityIsGenericNativeReasoningTitle(titleRaw) ? titleRaw : '');
    title = nativeReasoningTitle || '';
    if(!detail && /思考|推理/.test(titleRaw) && titleRaw !== title) detail = titleRaw;
  }else if(stage === 'mcp' || rawStage.startsWith('mcp_') || actionType.startsWith('mcp_') || String(item.source || '').toLowerCase() === 'mcp'){
    kind = 'mcp';
    title = titleRaw || _activityEventTitle('mcp', state);
  }else if(tool === 'analyze_existing_image' || actionType === 'image_analysis' || rawStage.includes('image_analysis')){
    kind = 'image';
    title = _activityEventTitle('image_analysis', state);
    detail = '';
  }else if(rawStage === 'sandbox_arguments_streaming'){
    kind = 'file';
    if(tool === 'sandbox_create_office_file') title = _activityT('activity.prepare_office_file', null, 'Preparing Office file generation');
    else if(tool === 'sandbox_write_file' || tool === 'sandbox_write_files' || tool === 'sandbox_replace_text') title = _activityT('activity.prepare_write_file', null, 'Preparing to write file');
    else if(tool === 'sandbox_publish_files') title = _activityT('activity.prepare_delivery', null, 'Preparing file delivery');
    else title = toolLabel
      ? _activityT('activity.prepare_named_tool', {tool:toolLabel}, `Preparing ${toolLabel}`)
      : _activityT('activity.prepare_file_action', null, 'Preparing file action');
    detail = '';
  }else if(tool === 'sandbox_import_files' || rawStage.includes('import')){
    kind = 'file';
    title = _activityEventTitle('import_files', state);
  }else if(tool === 'sandbox_read_file' || rawStage.includes('read_file')){
    kind = 'file';
    title = _activityEventTitle('read_file', state);
  }else if(tool === 'sandbox_list_files'){
    kind = 'sandbox';
    title = sandboxOperationTitle || _activityT('activity.list_sandbox_files', null, 'List sandbox files');
    detail = '';
  }else if(tool === 'sandbox_run' || /运行代码|代码运行|沙盒运行|沙盒命令/.test(combined)){
    kind = 'sandbox';
    const hasUsefulSandboxTitle = titleRaw && !/^(?:正在)?运行(?:代码|沙盒命令|沙盒检查)$|^(?:已)?运行(?:代码|沙盒命令|沙盒检查)$/.test(titleRaw);
    title = sandboxOperationTitle || (hasUsefulSandboxTitle ? titleRaw : _activityEventTitle('sandbox_run', state));
  }else if(tool === 'sandbox_write_file' || tool === 'sandbox_write_files' || tool === 'sandbox_replace_text' || (!tool && /写入文件|修改文件|保存文件/.test(combined))){
    kind = 'file';
    title = _activityEventTitle(tool === 'sandbox_replace_text' ? 'replace_text' : 'write_file', state);
  }else if(tool === 'sandbox_publish_files' || rawStage.includes('publish') || (!tool && /发布|下载文件|文件已发布|文件已就绪|准备下载/.test(combined))){
    kind = 'file';
    title = _activityEventTitle('publish_files', state);
  }else if(tool === 'sandbox_create_office_file' || (!tool && /office|docx|pptx|xlsx|生成.*文件/.test(combined))){
    kind = 'file';
    title = _activityEventTitle('office_file', state);
  }else if(/准备.*工具调用|工具参数/.test(combined)){
    kind = 'tool';
    title = toolLabel
      ? _activityT('activity.prepare_named_tool', {tool:toolLabel}, `Preparing ${toolLabel}`)
      : _activityT('activity.prepare_tool_call', null, 'Preparing tool call');
    detail = '';
  }else if(/知识库|文档片段|知识库片段/.test(combined)){
    kind = 'search';
    title = _activityKnowledgeTitle(titleRaw,state);
  }else if(tool === 'web_fetch' || tool === 'fetch_url' || tool === 'fetch_urls' || ['open_page','read_page','page_open'].includes(actionType) || rawStage.includes('open_page') || rawStage.includes('read_page')){
    kind = 'search';
    const genericReadTitle = /^(?:阅读网页|读取网页|抓取网页|正在阅读网页…?|正在读取网页…?|正在抓取网页…?|已阅读网页|已读取网页|已抓取网页|网页)$/i.test(titleRaw);
    title = (!genericReadTitle && titleRaw) ? titleRaw : _activityEventTitle('web_read', state);
  }else if(stage === 'web_query_group' || rawStage.includes('web_query_group')){
    kind = 'search';
    title = _activityEventTitle('web_search', state);
  }else if(/第\s*\d+\s*次搜索|搜索中|查询中|网页|网站|引用来源|联网|检索到/.test(combined)){
    kind = 'search';
    title = _activitySearchSystemTitle(titleRaw,state);
  }else if(/天气/.test(combined)){
    kind = 'tool';
    title = _activityEventTitle('weather', state);
  }else if(/图片|视觉|生图|生成图/.test(combined)){
    kind = 'tool';
    title = _activityEventTitle('image', state);
  }else if(/回答|生成回答|回复/.test(combined)){
    kind = 'answer';
    title = _activityEventTitle('answer', state);
  }

  if(!detail && toolLabel && !['sandbox_run','sandbox_list_files'].includes(tool) && !title.includes(toolLabel)) detail = toolLabel;
  const rawQueries = (Array.isArray(item.queries) ? item.queries : [])
    .map(q => _activityCleanText(q, 80))
    .filter(Boolean);
  const queries = _activitySanitizeQueriesForItem({
    ...item,
    kind,
    stage: kind,
    rawStage,
    raw_stage: rawStage,
    tool,
    title,
    actionType,
    action_type: actionType,
    source:String(item.source || '').trim(),
  }, rawQueries);
  const isImageSearchEvent = tool === 'image_search' || actionType === 'image_search' || rawStage.includes('image_search');
  if(isImageSearchEvent){
    kind = 'search';
    const q = queries[0] || _activityCleanText(item.query || item.search_query || item.searchQuery || item.querySummary || item.query_summary || '', 80);
    if(q){
      title = state === 'error'
        ? _activityT('activity.image_search_failed_query', {query:q}, `Image search failed: ${q}`)
        : _activityT('activity.search_query', {query:q}, `Search: ${q}`);
    }else{
      title = _activityEventTitle('image_search', state);
    }
    detail = '';
  }
  const rawSourceItems = item.sourceItems || item.source_items || item.sources || item.searchResults || item.search_results || [];
  const sourceItems = _activityNormalizeSourceItems(rawSourceItems, WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
  const sourceItemCount = _activityCountSourceItems(rawSourceItems);
  const imageItems = _activityNormalizeImageItems(item.imageItems || item.image_items || [], 8);
  const imageCount = Math.max(Number(item.imageCount || item.image_count || 0) || 0, imageItems.length);
  const documentVisualItems = _activityNormalizeDocumentVisualItems(item.documentVisualItems || item.document_visual_items || [], 12);
  const documentPageCount = Math.max(Number(item.documentPageCount || item.document_page_count || 0) || 0, documentVisualItems.length);
  const documentVisualDeferred = !!(item.documentVisualDeferred || item.document_visual_deferred);
  const fileNameInputs = [
    item.fileNames, item.file_names, item.filenames, item.files_preview, item.file_preview, item.filename, item.target_filename,
    item.targetFilename, item.current_file, item.currentFile, item.display_name, item.displayName, item.path, item.paths, item.files
  ];
  let fileNames = _activityMergeFileNames(...fileNameInputs);
  let fileNameTotal = Number(item.fileNameTotal || item.file_name_total || item.fileNameCount || item.file_name_count || item.fileCount || item.file_count || 0) || _activityCountFileNames(...fileNameInputs);
  if(!fileNames.length && /\b[\w一-鿿][\w.()\- 一-鿿]{0,120}\.(?:zip|txt|py|js|ts|html|css|json|md|csv|xlsx?|docx?|pptx?|pdf|png|jpe?g|webp|gif)\b/i.test(detailRaw)){
    const matches = detailRaw.match(/\b[\w一-鿿][\w.()\- 一-鿿]{0,120}\.(?:zip|txt|py|js|ts|html|css|json|md|csv|xlsx?|docx?|pptx?|pdf|png|jpe?g|webp|gif)\b/gi) || [];
    fileNames = _activityNormalizeFileNames(matches, 24);
    fileNameTotal = Math.max(fileNameTotal, _activityCountFileNames(matches));
  }
  fileNameTotal = Math.max(Number(fileNameTotal || 0) || 0, fileNames.length);
  if(fileNames.length){
    const firstFile = String(fileNames[0] || '').trim();
    const countLabel = Math.max(fileNameTotal, fileNames.length);
    if(tool === 'sandbox_read_file' || rawStage.includes('read_file')){
      title = _activityT(`activity.file_read_${state === 'error' ? 'error' : (state === 'active' ? 'active' : 'done')}`, {file:firstFile}, state === 'error' ? `Unable to read: ${firstFile}` : (state === 'active' ? `Reading: ${firstFile}` : `Read: ${firstFile}`));
    }else if(tool === 'sandbox_analyze_file_images'){
      const documentVisualFile = /\.(?:pdf|docx?|pptx?|xlsx?|xlsm)$/i.test(firstFile);
      if(documentVisualFile){
        if(state === 'error') title = _activityT('activity.document_pages_error', {file:firstFile}, `Unable to analyze document pages: ${firstFile}`);
        else if(state === 'active') title = _activityT('activity.document_pages_active', {file:firstFile}, `Rendering document pages: ${firstFile}`);
        else if(documentVisualDeferred) title = _activityT('activity.document_pages_prepared', {count:documentPageCount, file:firstFile}, documentPageCount > 0 ? `Prepared ${documentPageCount} document pages: ${firstFile}` : `Document pages prepared: ${firstFile}`);
        else title = _activityT('activity.document_pages_done', {count:documentPageCount, file:firstFile}, documentPageCount > 0 ? `Analyzed ${documentPageCount} document pages: ${firstFile}` : `Document pages analyzed: ${firstFile}`);
      }else{
        title = _activityT(`activity.visual_read_${state === 'error' ? 'error' : (state === 'active' ? 'active' : 'done')}`, {file:firstFile}, state === 'error' ? `Unable to inspect: ${firstFile}` : (state === 'active' ? `Inspecting: ${firstFile}` : `Inspected: ${firstFile}`));
      }
    }else if(tool === 'sandbox_import_files' || rawStage.includes('import')){
      if(countLabel > 1) title = _activityT(`activity.files_import_${state === 'error' ? 'error' : (state === 'active' ? 'active' : 'done')}`, {count:countLabel}, state === 'error' ? `Unable to import ${countLabel} files` : (state === 'active' ? `Importing ${countLabel} files` : `Imported ${countLabel} files`));
      else title = _activityT(`activity.file_import_${state === 'error' ? 'error' : (state === 'active' ? 'active' : 'done')}`, {file:firstFile}, state === 'error' ? `Unable to import: ${firstFile}` : (state === 'active' ? `Importing: ${firstFile}` : `Imported: ${firstFile}`));
    }else if(tool === 'sandbox_write_file' || tool === 'sandbox_replace_text'){
      title = _activityT(`activity.file_write_${state === 'error' ? 'error' : (state === 'active' ? 'active' : 'done')}`, {file:firstFile}, state === 'error' ? `Unable to write: ${firstFile}` : (state === 'active' ? `Writing: ${firstFile}` : `Written: ${firstFile}`));
    }
  }
  if(kind === 'search' && queries.length){
    const genericSearchTitle = /^(?:第\s*\d+\s*次搜索(?:中|完成)?|搜索网页|网页搜索|搜索中|查询中|原生搜索(?:已完成|执行中|调用中))$/i.test(String(title || '').trim());
    if(genericSearchTitle) title = _activitySearchTitleFromQueries(queries, title);
  }
  if(tool === 'sandbox_list_files'){
    detail = '';
  }
  const debugToolCanShow = ['sandbox_run','sandbox_list_files'].includes(tool);
  const showDebug = debugToolCanShow && !!(item.showDebug || item.show_debug || String(item.state || '').toLowerCase() === 'error' || state === 'error');
  let command = _activityCodeText(item.display_command || item.displayCommand || item.command || '');
  let stdout = _activityCodeText(item.stdout || '');
  let stderr = _activityCodeText(item.stderr || '');
  let exitCode = item.exitCode ?? item.exit_code;
  let commandLanguage = String(item.commandLanguage || item.command_language || item.language || '').trim().toLowerCase();
  if(!debugToolCanShow){
    command = '';
    stdout = '';
    stderr = '';
    exitCode = undefined;
  }
  if(!showDebug){
    command = '';
    stdout = '';
    stderr = '';
    exitCode = undefined;
  }
  if(kind === 'sandbox' && showDebug && (command || stdout || stderr)){
    detail = '';
  }
  const operationKey = String(item.operation_key || item.operationKey || '').trim();
  const isSandboxRunTool = kind === 'sandbox' && (tool === 'sandbox_run' || (!tool && command));
  const sandboxRunId = isSandboxRunTool
    ? _activitySandboxRunIdentity({ ...item, operationKey }, command)
    : '';
  const normalizedKey = sandboxRunId
    ? `sandbox_run|${sandboxRunId}`
    : String(item.key || ((kind === 'sandbox' && command)
      ? `sandbox_command|${tool || 'tool'}|${_activityCompactKeyHash(command)}`
      : `${kind}|${title}|${detail.slice(0, 160)}|${command.slice(0, 120)}|${index}`));
  return {
    key: String(normalizedKey).slice(0, 500),
    title,
    detail,
    queries,
    ...(sourceItems.length ? { sourceItems } : {}),
    kind,
    state,
    renderMode,
    showDebug,
    ...(commandLanguage ? { commandLanguage } : {}),
    ...(command ? { command } : {}),
    ...(stdout ? { stdout } : {}),
    ...(stderr ? { stderr } : {}),
    ...(exitCode !== undefined && exitCode !== null ? { exitCode } : {}),
    ...(operationKey ? { operationKey } : {}),
    ...(fileNames.length ? { fileNames } : {}),
    ...(fileNameTotal > 0 ? { fileNameTotal } : {}),
    ...(imageItems.length ? { imageItems } : {}),
    ...(imageCount > 0 ? { imageCount } : {}),
    ...(documentVisualItems.length ? { documentVisualItems } : {}),
    ...(documentPageCount > 0 ? { documentPageCount } : {}),
    ...(documentPageCount > 0 ? { documentVisualDeferred } : {}),
    resultCount:Math.max(Number(item.resultCount || item.result_count || 0) || 0, sourceItemCount, sourceItems.length),
    ts: Number(item.ts || 0) || Date.now() + index,
    startedAt: _activityEventMs(item.startedAt || item.started_at || item.ts || 0),
    updatedAt: _activityEventMs(item.updatedAt || item.updated_at || item.ts || 0),
    doneAt: _activityEventMs(item.doneAt || item.done_at || item.finishedAt || item.finished_at || item.completedAt || item.completed_at || 0),
    rawStage,
    tool,
    ...(actionType ? { actionType } : {}),
    source:String(item.source || '').trim(),
    ...(Number(item.percent || 0) > 0 ? { percent:Number(item.percent || 0) } : {}),
    ...(Number(item.seq || item.order || 0) > 0 ? { seq:Number(item.seq || item.order || 0) } : {}),
  };
}

function _activityCompactKeyHash(value){
  const s = String(value || '');
  let h = 2166136261;
  for(let i = 0; i < s.length; i += 1){
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16);
}

function _activitySandboxRunIdentity(item, commandText=''){
  if(!item || typeof item !== 'object') return '';
  const direct = String(item.operation_key || item.operationKey || '').trim();
  if(direct) return direct.slice(0, 180);
  const command = String(commandText || item.display_command || item.displayCommand || item.command || '').trim();
  if(command) return `cmd:${_activityCompactKeyHash(command)}`;
  const key = String(item.key || '').trim();
  let m = key.match(/^sandbox_run\|(.+)$/i);
  if(m && m[1] && !/^default$/i.test(m[1])) return m[1].slice(0, 180);
  m = key.match(/^sandbox\|sandbox_run\|([^|]+)/i);
  if(m && m[1] && !/^default$/i.test(m[1])) return m[1].slice(0, 180);
  return '';
}

function _activitySameSandboxRunDebug(oldItem, newItem){
  const oldCommand = String(oldItem?.command || '').trim();
  const newCommand = String(newItem?.command || '').trim();
  if(oldCommand && newCommand && oldCommand !== newCommand) return false;
  const oldId = _activitySandboxRunIdentity(oldItem, oldCommand);
  const newId = _activitySandboxRunIdentity(newItem, newCommand || oldCommand);
  if(oldId && newId) return oldId === newId;
  return !!(oldCommand && (!newCommand || oldCommand === newCommand));
}

function _activityMergeSandboxDebugFields(oldItem, newItem, base){
  const merged = { ...base };
  const sameRun = _activitySameSandboxRunDebug(oldItem, newItem);
  const hasOwn = (obj, key)=>Object.prototype.hasOwnProperty.call(obj || {}, key);
  merged.command = hasOwn(newItem, 'command') ? (newItem.command || '') : (sameRun ? (oldItem.command || '') : '');
  merged.stdout = hasOwn(newItem, 'stdout') ? (newItem.stdout || '') : (sameRun ? (oldItem.stdout || '') : '');
  merged.stderr = hasOwn(newItem, 'stderr') ? (newItem.stderr || '') : (sameRun ? (oldItem.stderr || '') : '');
  if(hasOwn(newItem, 'exitCode')) merged.exitCode = newItem.exitCode;
  else if(sameRun && hasOwn(oldItem, 'exitCode')) merged.exitCode = oldItem.exitCode;
  else delete merged.exitCode;
  return merged;
}

function _activityIsLowLevelSandboxPrepItem(item){
  if(!item || typeof item !== 'object') return false;
  const raw = String(item.rawStage || item.raw_stage || '').toLowerCase();
  const title = String(item.title || '').trim();
  const tool = String(item.tool || '').toLowerCase();
  return raw === 'sandbox_arguments_streaming'
    || /^准备(?:工具调用|文件工具|文件操作|文件交付|读取上传文件|读取文件|写入文件|修改文件|运行代码|准备下载文件|生成 Office 文件)/.test(title)
    || (tool && /^准备/.test(title));
}

function _activityIsSandboxLikeItem(item){
  if(!item || typeof item !== 'object') return false;
  const kind = String(item.kind || item.stage || '').toLowerCase();
  const raw = String(item.rawStage || item.raw_stage || '').toLowerCase();
  const tool = String(item.tool || '').toLowerCase();
  return kind === 'sandbox' || kind === 'file' || raw.startsWith('sandbox_') || tool.startsWith('sandbox_');
}

function _activitySandboxOperationKey(item){
  if(!_activityIsSandboxLikeItem(item)) return '';
  const tool = String(item.tool || '').toLowerCase();
  const key = String(item.key || '');
  const command = String(item.display_command || item.displayCommand || item.command || '').trim();
  const detail = String(item.detail || '').trim();
  const title = String(item.title || '').trim();
  const path = String(item.path || item.target_filename || item.current_file || '').trim();
  if(tool === 'sandbox_list_files') return `${tool}|${_activityCompactKeyHash(command || path || detail || key || title)}`;
  if(tool === 'sandbox_import_files' || tool === 'sandbox_publish_files' || tool === 'sandbox_create_office_file' || tool === 'sandbox_write_files' || tool === 'sandbox_analyze_file_images') return tool;
  if(tool === 'sandbox_run' || (!tool && command)){
    const runId = _activitySandboxRunIdentity(item, command);
    return `sandbox_run|${runId || `cmd:${_activityCompactKeyHash(command || title || detail || key)}`}`;
  }
  let normalizedKey = key
    .replace(/sandbox_(?:progress|result)\|(run|import|file|publish|create_office|write)_(?:active|done)(?:\|)?/i, 'sandbox_op|$1|')
    .replace(/\|(?:start|done|error)$/i, '');
  if(normalizedKey && !/\|active(?:\||$)|\|done(?:\||$)/i.test(normalizedKey)){
    return normalizedKey.slice(0, 240);
  }
  const basis = detail || command || title;
  return `${tool || String(item.kind || '').toLowerCase() || 'sandbox'}|${_activityCompactKeyHash(basis || key || title)}`;
}

function _activityStateRank(state){
  const s = String(state || '').toLowerCase();
  if(s === 'error') return 4;
  if(s === 'warn') return 3;
  if(s === 'done') return 2;
  if(s === 'active') return 1;
  return 0;
}

function _activityChooseBetterItem(oldItem, newItem){
  if(!oldItem) return newItem;
  if(!newItem) return oldItem;
  const oldRank = _activityStateRank(oldItem.state);
  const newRank = _activityStateRank(newItem.state);
  const preferNew = newRank > oldRank || (newRank === oldRank && (Number(newItem.ts || 0) || 0) >= (Number(oldItem.ts || 0) || 0));
  const base = preferNew ? { ...oldItem, ...newItem } : { ...newItem, ...oldItem };
  let merged = {
    ...base,
    ts: Math.min(Number(oldItem.ts || 0) || Number(newItem.ts || 0) || Date.now(), Number(newItem.ts || 0) || Number(oldItem.ts || 0) || Date.now()),
    showDebug: !!(newItem.showDebug || oldItem.showDebug),
    commandLanguage: newItem.commandLanguage || oldItem.commandLanguage || '',
    fileNames: _activityMergeFileNames(oldItem.fileNames, newItem.fileNames),
    fileNameTotal: Math.max(Number(oldItem.fileNameTotal || oldItem.fileNameCount || 0) || 0, Number(newItem.fileNameTotal || newItem.fileNameCount || 0) || 0, _activityCountFileNames(oldItem.fileNames, newItem.fileNames)),
    detail: newItem.detail || oldItem.detail || '',
    state: _activityStateRank(newItem.state) >= _activityStateRank(oldItem.state) ? newItem.state : oldItem.state,
  };
  const sandboxDebug = String(oldItem.tool || newItem.tool || '').toLowerCase() === 'sandbox_run'
    || !!(oldItem.command || newItem.command || oldItem.stdout || newItem.stdout || oldItem.stderr || newItem.stderr);
  if(sandboxDebug){
    merged = _activityMergeSandboxDebugFields(oldItem, newItem, merged);
  }else{
    merged.command = newItem.command || oldItem.command || '';
    merged.stdout = newItem.stdout || oldItem.stdout || '';
    merged.stderr = newItem.stderr || oldItem.stderr || '';
    merged.exitCode = newItem.exitCode ?? oldItem.exitCode;
  }
  return merged;
}

function _activityCompactFileGroupTitle(title, count){
  const base = String(title || _activityT('activity.process_files', null, 'Process files')).replace(/（\d+ 项）$/,'').trim() || _activityT('activity.process_files', null, 'Process files');
  return _activityT('activity.group_count', {label:base, count}, `${base} (${count})`);
}


function _activityIsFileIndexItem(item){
  if(!item || typeof item !== 'object') return false;
  const raw = `${item.key || ''} ${item.rawStage || item.raw_stage || ''} ${item.stage || item.kind || ''} ${item.title || ''} ${item.detail || ''} ${item.text || ''}`.toLowerCase();
  return raw.includes('upload_files_ready')
    || raw.includes('file_index_start')
    || raw.includes('file_index_file')
    || raw.includes('file_index_ready')
    || /准备沙盒文件清单|待导入文件|沙盒文件清单已就绪/.test(String(item.title || item.detail || item.text || ''));
}

function _activityFileIndexIsReady(item){
  const raw = `${item.key || ''} ${item.rawStage || item.raw_stage || ''} ${item.title || ''} ${item.detail || ''} ${item.text || ''}`.toLowerCase();
  return raw.includes('upload_files_ready') || raw.includes('file_index_ready') || /清单已就绪|已准备/.test(String(item.title || item.text || ''));
}

function _activityFileIndexIsStart(item){
  const raw = `${item.key || ''} ${item.rawStage || item.raw_stage || ''} ${item.title || ''} ${item.detail || ''} ${item.text || ''}`.toLowerCase();
  return raw.includes('file_index_start') || /正在准备/.test(String(item.title || item.text || ''));
}

function _activityExtractFileIndexNames(item){
  const names = _activityMergeFileNames(
    item?.fileNames, item?.file_names, item?.filenames, item?.files_preview, item?.file_preview, item?.filename, item?.target_filename,
    item?.targetFilename, item?.current_file, item?.currentFile, item?.display_name, item?.displayName, item?.path, item?.paths, item?.files
  );
  const text = String(`${item?.title || ''}\n${item?.detail || ''}\n${item?.text || ''}`).replace(/\r\n?/g, '\n');
  const candidates = [];
  const labeled = text.match(/(?:待导入文件|目标文件|target_filename|filename)\s*[：:]\s*([^\n|｜·]+)/giu) || [];
  for(const row of labeled){
    const value = row.replace(/^.*?[：:]/u, '').trim();
    if(value) candidates.push(value);
  }
  const fileMatches = text.match(/[\w\u4e00-\u9fff][\w.()\- \u4e00-\u9fff]{0,140}\.(?:zip|txt|py|js|ts|html|css|json|md|csv|xlsx?|docx?|pptx?|pdf|png|jpe?g|webp|gif)/giu) || [];
  candidates.push(...fileMatches);
  return _activityMergeFileNames(names, candidates);
}

function _activityCompactFileIndexItems(items){
  const arr = Array.isArray(items) ? items : [];
  const fileIndexItems = arr.filter(item => _activityIsFileIndexItem(item));
  if(!fileIndexItems.length) return arr;
  const collected = _activityCollectFileNames(fileIndexItems.map(item => _activityExtractFileIndexNames(item)), 80);
  const names = collected.names;
  const explicitFileRows = fileIndexItems.filter(item => String(item?.rawStage || item?.raw_stage || item?.stage || item?.key || '').toLowerCase().includes('file_index_file')).length;
  const explicitTotals = fileIndexItems.map(item => Number(item?.fileNameTotal || item?.file_name_total || item?.fileNameCount || item?.file_name_count || item?.fileCount || item?.file_count || item?.total_count || 0) || 0);
  const fileNameTotal = Math.max(collected.total, explicitFileRows, names.length, ...explicitTotals);
  const firstTs = Math.min(...fileIndexItems.map(item => Number(item?.ts || 0) || Date.now()));
  const hasError = fileIndexItems.some(item => String(item?.state || '').toLowerCase() === 'error' || /失败|出错|error|failed/i.test(`${item?.title || ''} ${item?.detail || ''}`));
  const hasReady = fileIndexItems.some(item => _activityFileIndexIsReady(item));
  const hasOnlyStart = fileIndexItems.some(item => _activityFileIndexIsStart(item)) && !hasReady && names.length === 0;
  const state = hasError ? 'error' : (hasOnlyStart ? 'active' : 'done');
  const compact = {
    key:`file_index_compact|${_activityCompactKeyHash(names.join('|') || fileIndexItems.map(item => item?.key || item?.title || '').join('|'))}`,
    title: _activityT(`activity.upload_files_${state === 'error' ? 'error' : (state === 'active' ? 'active' : 'done')}`, null, state === 'error' ? 'Unable to prepare uploaded files' : (state === 'active' ? 'Preparing uploaded files' : 'Uploaded files prepared')),
    detail: fileNameTotal > 0
      ? _activityT('activity.upload_files_ready_count', {count:fileNameTotal, note:fileNameTotal > 8 ? _activityT('activity.upload_files_preview_note', null, ' Only the first few are shown here.') : ''}, `${fileNameTotal} uploaded files identified. Content will be read when needed.${fileNameTotal > 8 ? ' Only the first few are shown here.' : ''}`)
      : _activityT('activity.upload_files_ready', null, 'Uploaded files are ready. Content will be read when needed.'),
    kind:'file',
    stage:'file',
    state,
    ts:Number.isFinite(firstTs) ? firstTs : Date.now(),
    source:'file_progress',
    ...(names.length ? { fileNames:names.slice(0, 8) } : {}),
    ...(fileNameTotal > 0 ? { fileNameTotal } : {}),
    ...((hasError || fileNameTotal > 8) ? { collapsedItems:fileIndexItems.map(item => ({
      title:String(item?.title || '').trim(),
      detail:String(item?.detail || '').trim(),
      state:String(item?.state || '').trim(),
      fileNames:_activityExtractFileIndexNames(item),
    })).filter(row => row.title || row.detail || (row.fileNames || []).length).slice(0, 12) } : {}),
  };
  const out = [];
  let inserted = false;
  for(const item of arr){
    if(_activityIsFileIndexItem(item)){
      if(!inserted){
        out.push(compact);
        inserted = true;
      }
      continue;
    }
    out.push(item);
  }
  if(!inserted) out.unshift(compact);
  return out;
}

function _activityFirstFileName(item){
  const names = _activityMergeFileNames(item?.fileNames, item?.file_names, item?.filenames, item?.files_preview, item?.filename, item?.target_filename, item?.current_file, item?.path, item?.files);
  return names[0] || '';
}

function _activityLastMatchingRow(rows, predicate){
  const arr = Array.isArray(rows) ? rows : [];
  for(let i = arr.length - 1; i >= 0; i -= 1){
    if(predicate(arr[i])) return arr[i];
  }
  return arr[arr.length - 1] || null;
}


function _activityCompactLowLevelSandboxPrepItems(items){
  const arr = Array.isArray(items) ? items : [];
  const prep = arr.filter(item => _activityIsLowLevelSandboxPrepItem(item));
  if(prep.length <= 1) return arr;
  const nonPrep = arr.filter(item => !_activityIsLowLevelSandboxPrepItem(item));
  const first = prep[0] || {};
  const preferred = [...prep].reverse().find(item => String(item.title || '').trim() && !/准备文件工具/.test(String(item.title || ''))) || first;
  const titles = prep.map(item => String(item.title || '').trim()).filter(Boolean);
  let title = String(preferred.title || '').trim() || _activityT('activity.prepare_file_action', null, 'Preparing file action');
  if(titles.some(x => /生成 Office/.test(x))) title = _activityT('activity.prepare_office_file', null, 'Preparing Office file generation');
  else if(titles.some(x => /写入文件/.test(x))) title = _activityT('activity.prepare_write_file', null, 'Preparing to write file');
  else if(titles.some(x => /文件交付|下载文件/.test(x))) title = _activityT('activity.prepare_delivery', null, 'Preparing file delivery');
  return _activitySortTimelineItems([
    {
      ...first,
      key:`sandbox_prep_compact|${_activityCompactKeyHash(prep.map(item => item.key || item.title || '').join('|'))}`,
      title,
      detail:'',
      kind:'file',
      state: prep.some(item => String(item.state || '').toLowerCase() === 'error') ? 'error' : 'active',
      ts:Math.min(...prep.map(item => Number(item.ts || 0) || Date.now())),
      command:'', stdout:'', stderr:'', exitCode:undefined,
    },
    ...nonPrep,
  ]);
}

function _activityGroupedFileOperationTitle(first, rows, state, count){
  const tool = String(first?.tool || '').toLowerCase();
  const active = _activityLastMatchingRow(rows, x => String(x?.state || '').toLowerCase() === 'active');
  const error = _activityLastMatchingRow(rows, x => String(x?.state || '').toLowerCase() === 'error');
  const current = active || error || _activityLastMatchingRow(rows, ()=>true) || first || {};
  const name = _activityFirstFileName(current);
  const n = Math.max(Number(count || 0) || 0, Array.isArray(rows) ? rows.length : 0);
  if(tool === 'sandbox_read_file'){
    if(active && name) return _activityT('activity.file_read_active', {file:name}, `Reading: ${name}`);
    if(state === 'error') return n > 1
      ? _activityT('activity.files_read_error', {count:n}, `Unable to read ${n} files`)
      : (name ? _activityT('activity.file_read_error', {file:name}, `Unable to read: ${name}`) : _activityEventTitle('read_file', 'error'));
    return n > 1
      ? _activityT('activity.files_read_done', {count:n}, `Read ${n} files`)
      : (name ? _activityT('activity.file_read_done', {file:name}, `Read: ${name}`) : _activityEventTitle('read_file', 'done'));
  }
  if(tool === 'sandbox_analyze_file_images'){
    if(active && name) return _activityT('activity.visual_read_active', {file:name}, `Inspecting: ${name}`);
    if(state === 'error') return n > 1
      ? _activityT('activity.files_visual_error', {count:n}, `Unable to inspect ${n} files`)
      : (name ? _activityT('activity.visual_read_error', {file:name}, `Unable to inspect: ${name}`) : _activityT('activity.visual_read_error_generic', null, 'Visual inspection failed'));
    return n > 1
      ? _activityT('activity.files_visual_done', {count:n}, `Inspected ${n} files`)
      : (name ? _activityT('activity.visual_read_done', {file:name}, `Inspected: ${name}`) : _activityT('activity.visual_read_done_generic', null, 'Files inspected'));
  }
  if(tool === 'sandbox_import_files'){
    if(active && n > 1) return _activityT('activity.files_import_active', {count:n}, `Importing ${n} files`);
    if(active && name) return _activityT('activity.file_import_active', {file:name}, `Importing: ${name}`);
    if(state === 'error') return n > 1
      ? _activityT('activity.files_import_error', {count:n}, `Unable to import ${n} files`)
      : (name ? _activityT('activity.file_import_error', {file:name}, `Unable to import: ${name}`) : _activityEventTitle('import_files', 'error'));
    return n > 1
      ? _activityT('activity.files_import_done', {count:n}, `Imported ${n} files`)
      : (name ? _activityT('activity.file_import_done', {file:name}, `Imported: ${name}`) : _activityEventTitle('import_files', 'done'));
  }
  if(tool === 'sandbox_list_files'){
    return _activityT('activity.list_sandbox_files', null, 'List sandbox files');
  }
  return _activityCompactFileGroupTitle(first?.title || _activityT('activity.process_files', null, 'Process files'), n || rows.length || 1);
}


function _activityCompactTimelineItems(items, context={}){
  let arr = _activitySortTimelineItems(Array.isArray(items) ? items : []);
  const hasRealSandboxWork = arr.some(item => _activityIsSandboxLikeItem(item) && !_activityIsLowLevelSandboxPrepItem(item));
  if(hasRealSandboxWork){
    arr = arr.filter(item => !_activityIsLowLevelSandboxPrepItem(item));
  }else{
    arr = _activityCompactLowLevelSandboxPrepItems(arr);
  }

  const merged = [];
  const opIndex = new Map();
  for(const item of arr){
    if(!_activityIsSandboxLikeItem(item)){
      merged.push(item);
      continue;
    }
    const opKey = _activitySandboxOperationKey(item);
    if(!opKey){
      merged.push(item);
      continue;
    }
    if(opIndex.has(opKey)){
      const idx = opIndex.get(opKey);
      merged[idx] = _activityChooseBetterItem(merged[idx], item);
    }else{
      opIndex.set(opKey, merged.length);
      merged.push(item);
    }
  }

  const grouped = [];
  const fileBuckets = new Map();
  const flushBucket = (bucket)=>{
    if(!bucket || !bucket.rows || !bucket.rows.length) return;
    const rows = bucket.rows;
    if(rows.length < 4){
      grouped.push(...rows);
      return;
    }
    const errors = rows.filter(x => String(x.state || '').toLowerCase() === 'error');
    const first = rows[0] || {};
    const collected = _activityCollectFileNames(rows.map(x => x.fileNames || []), 80);
    const mergedFileNames = collected.names;
    const fileNameTotal = Math.max(collected.total, ...rows.map(x => Number(x.fileNameTotal || x.fileNameCount || 0) || 0));
    const groupState = errors.length ? 'error' : (rows.some(x => String(x.state || '').toLowerCase() === 'active') ? 'active' : 'done');
    const groupTitle = _activityGroupedFileOperationTitle(first, rows, groupState, fileNameTotal || rows.length);
    grouped.push({
      ...first,
      key:`compact_files|${bucket.key}|${rows.length}|${_activityCompactKeyHash(rows.map(x => x.key || x.title || '').join('|'))}`,
      title:groupTitle,
      detail: errors.length
        ? _activityT('activity.group_errors', {count:rows.length, errors:errors.length}, `${errors.length} of ${rows.length} items failed.`)
        : (groupState === 'active'
          ? _activityT('activity.group_active', {count:rows.length}, `Processing a multi-file queue; ${rows.length} items are grouped.`)
          : _activityT('activity.group_done', {count:rows.length}, `${rows.length} items are grouped.`)),
      state: groupState,
      ts:Number(first.ts || 0) || Date.now(),
      command:'', stdout:'', stderr:'', exitCode:undefined,
      ...(mergedFileNames.length ? { fileNames:mergedFileNames.slice(0, 8) } : {}),
      ...(fileNameTotal > 0 ? { fileNameTotal } : {}),
      collapsedItems: rows.slice(0, 24).map(x => ({ title:x.title, detail:x.detail, state:x.state, fileNames:x.fileNames || [], fileNameTotal:x.fileNameTotal })),
    });
  };
  for(const item of _activitySortTimelineItems(merged)){
    const kind = String(item.kind || '').toLowerCase();
    const tool = String(item.tool || '').toLowerCase();
    const title = String(item.title || '').trim();
    const canGroupFile = kind === 'file' && !item.command && !item.stdout && !item.stderr && !/准备下载|生成 Office|生成文件/.test(title);
    if(canGroupFile){
      const groupableTool = ['sandbox_read_file','sandbox_analyze_file_images','sandbox_import_files','sandbox_list_files'].includes(tool);
      const bucketKey = groupableTool ? `${tool}|multi` : `${tool || kind}|${title}`;
      if(!fileBuckets.has(bucketKey)) fileBuckets.set(bucketKey, { key:bucketKey, rows:[] });
      fileBuckets.get(bucketKey).rows.push(item);
      continue;
    }
    for(const bucket of fileBuckets.values()) flushBucket(bucket);
    fileBuckets.clear();
    grouped.push(item);
  }
  for(const bucket of fileBuckets.values()) flushBucket(bucket);

  const deliveryCompacted = grouped;
  const maxItems = Math.max(8, Number(context.maxItems || 24) || 24);
  const sorted = _activitySortTimelineItems(deliveryCompacted);
  if(sorted.length <= maxItems) return sorted;
  // Keep compaction chronological. Do not pin the first think row at the top,
  // because that breaks the real timeline when reasoning resumes after search.
  const head = [];
  const tailBudget = Math.max(6, maxItems);
  const tail = sorted.slice(-tailBudget);
  const omitted = Math.max(0, sorted.length - tail.length);
  const out = [];
  if(omitted > 0){
    const anchor = tail[0] || sorted[0] || {};
    out.push({
      key:`activity_omitted|${omitted}|${Number(anchor.ts || Date.now())}`,
      title:_activityT('activity.intermediate_grouped', {count:omitted}, `${omitted} intermediate events grouped`),
      detail:_activityT('activity.intermediate_grouped_hint', null, 'Key steps and recent statuses are kept to keep the activity panel concise.'),
      kind:'tool',
      state:'done',
      ts:(Number(anchor.ts || 0) || Date.now()) - 1,
    });
  }
  out.push(...tail.filter(item => !head.some(h => h.key === item.key)));
  return _activitySortTimelineItems(out);
}

function _activityDedupeItems(items){
  const out = [];
  const seen = new Map();
  for(const raw of Array.isArray(items) ? items : []){
    const item = _activityNormalizeItem(raw, out.length);
    const isTitlelessThink = _activityLooksNativeReasoningItem(item) && String(item.detail || item.text || '').trim();
    if(!item.title && !isTitlelessThink) continue;
    if(_activityIsInternalToolInvocationItem(item)) continue;
    const sourceKey = Array.isArray(item.sourceItems) ? item.sourceItems.map(x => x.url || x.host || x.title || '').join('|').slice(0, 240) : '';
    const key = String(item.key || `${item.kind}|${item.title}|${String(item.detail || '').slice(0, 240)}|${item.queries.join('|')}|${sourceKey}|${String(item.command || '').slice(0, 160)}|${String(item.stdout || '').slice(0, 160)}|${String(item.stderr || '').slice(0, 160)}`);
    if(seen.has(key)){
      const old = out[seen.get(key)];
      out[seen.get(key)] = (_activityIsSandboxLikeItem(old) || _activityIsSandboxLikeItem(item))
        ? _activityChooseBetterItem(old, item)
        : { ...old, ...item, ts: old.ts || item.ts, seq: old.seq || item.seq };
      continue;
    }
    seen.set(key, out.length);
    out.push(item);
  }
  return out.slice(-80);
}


function _activityApplyReservePx(px){
  const value = `${Math.max(0, Math.ceil(Number(px) || 0))}px`;
  try{ document.body?.style?.setProperty('--active-activity-panel-reserve', value); }catch(_){ }
}

function _activitySyncReserve(visible){
  const els = _activityPanelEls();
  const active = typeof visible === 'boolean' ? visible : !!(els.root && !els.root.hidden);
  if(!active || !els.root){
    _activityApplyReservePx(0);
    return;
  }
  const measure = ()=>{
    try{
      const rect = els.root.getBoundingClientRect();
      const reserve = rect && rect.width > 0 ? Math.max(rect.width, window.innerWidth - rect.left) : 0;
      _activityApplyReservePx(reserve);
    }catch(_){
      _activityApplyReservePx(0);
    }
  };
  measure();
  try{ window.requestAnimationFrame(measure); }catch(_){ }
}


function _activityLooksNativeReasoningItem(item){
  if(!item || typeof item !== 'object') return false;
  const key = String(item.key || '').trim();
  const stage = String(item.stage || item.kind || '').trim().toLowerCase();
  const title = String(item.title || item.text || '').trim();
  return key === 'native_reasoning'
    || key.startsWith('native_reasoning_segment|')
    || stage === 'think'
    || /思考|推理/.test(title);
}


function _activityIsResponsesNativeReasoningSource(value){
  const s = String(value || '').trim().toLowerCase();
  if(!s) return false;
  return s === 'responses_reasoning'
    || s === 'responses_reasoning_snapshot'
    || s === 'response_reasoning'
    || s === 'response.reasoning'
    || s.startsWith('responses_reasoning_')
    || s.startsWith('response.reasoning.')
    || s.includes('responses_native_reasoning');
}

function _activityIsResponsesNativeReasoningItem(item){
  if(!item || typeof item !== 'object' || !_activityLooksNativeReasoningItem(item)) return false;
  if(item.responsesNativeReasoning || item.responses_native_reasoning) return true;
  return _activityIsResponsesNativeReasoningSource(item.source)
    || _activityIsResponsesNativeReasoningSource(item.nativeReasoningSource || item.native_reasoning_source)
    || _activityIsResponsesNativeReasoningSource(item.rawSource || item.raw_source);
}

function _activityJoinNativeReasoningSegmentText(left, right){
  const l = String(left == null ? '' : left).replace(/\r\n?/g, '\n');
  const r = String(right == null ? '' : right).replace(/\r\n?/g, '\n');
  if(!l) return r.trim();
  if(!r) return l;
  if(/\s$/.test(l) || /^\s/.test(r)) return l + r;
  const leftTrim = l.trimEnd();
  const rightTrim = r.trimStart();
  const rightLooksLikeBlock = /^(?:#{1,6}\s+|>\s*|[-*+]\s+|\d{1,9}[.)]\s+|```|~~~|\|)/.test(rightTrim)
    || /^(?:\*\*|__)[^\n*_#][\s\S]{1,140}(?:\*\*|__)(?:\s*$|\s*\n)/.test(rightTrim);
  if(rightLooksLikeBlock) return `${leftTrim}\n\n${rightTrim}`;
  // Space only between ASCII word/number fragments. Chinese fragments should
  // concatenate naturally instead of becoming "逐 字 分 开".
  if(/[A-Za-z0-9]$/.test(leftTrim) && /^[A-Za-z0-9]/.test(rightTrim)){
    return `${leftTrim} ${rightTrim}`;
  }
  if(/[.!?。！？：:]$/.test(leftTrim) && /^[A-Za-z0-9\u4e00-\u9fff]/.test(rightTrim)){
    return `${leftTrim} ${rightTrim}`;
  }
  return _activityJoinReasoningText(leftTrim, rightTrim);
}

function _activityNativeReasoningEventKey(row){
  if(!row || typeof row !== 'object') return '';
  return String(
    row.segmentKey || row.segment_key
    || row.reasoningEventKey || row.reasoning_event_key
    || row.nativeReasoningEventKey || row.native_reasoning_event_key
    || row.eventKey || row.event_key
    || row.itemId || row.item_id
    || ''
  ).trim().slice(0, 700);
}

function _activityShouldBreakNativeReasoningSegment(prev, cur){
  if(!prev || !cur) return true;
  const prevEventKey = _activityNativeReasoningEventKey(prev);
  const curEventKey = _activityNativeReasoningEventKey(cur);
  if(prevEventKey && curEventKey) return prevEventKey !== curEventKey;
  if(prevEventKey || curEventKey) return true;
  const prevText = String(prev.text || prev.detail || '').trim();
  const curText = String(cur.text || cur.detail || '').trim();
  const curTitle = String(cur.title || '').trim();
  if(!prevText && !String(prev.title || '').trim()) return false;
  // A provider-supplied bold/markdown title can be a real reasoning section, but
  // short transition words such as "Now" are still part of the same thought.
  if(curTitle && _activityNativeReasoningTitleShouldBreak(curTitle)) return true;
  const prevUpdated = Number(prev.updatedAt || prev.updated_at || prev.ts || 0) || 0;
  const curTs = Number(cur.ts || cur.startedAt || cur.started_at || 0) || 0;
  const gap = prevUpdated && curTs ? Math.max(0, curTs - prevUpdated) : 0;
  if(gap > 18000 && prevText.length > 240 && /(?:[.!?。！？]\s*|\n\s*)$/.test(prevText)) return true;
  if(prevText.length > 3600 && /(?:[.!?。！？]\s*|\n\s*)$/.test(prevText)) return true;
  return false;
}

function _activityNativeReasoningTransitionOnlyText(row){
  if(!row || typeof row !== 'object') return '';
  const title = String(row.title || '').replace(/\s+/g, ' ').trim();
  const body = String(row.text || row.detail || '')
    .replace(/\r\n?/g, '\n')
    .trim()
    .replace(/^\s*(?:\*\*|__)([\s\S]{1,40}?)(?:\*\*|__)\s*$/m, '$1')
    .replace(/\s+/g, ' ')
    .trim();
  if(title && _activityIsNativeReasoningTransitionTitle(title) && (!body || body === title)) return title;
  if(!title && body && body.length <= 24 && _activityIsNativeReasoningTransitionTitle(body)) return body;
  return '';
}

function _activityMergeNativeReasoningTransitionRows(rows){
  const source = Array.isArray(rows) ? rows : [];
  if(source.length <= 1) return source.slice();
  const out = [];
  let pending = null;
  for(const raw of source){
    const row = raw && typeof raw === 'object' ? raw : null;
    if(!row) continue;
    const transitionText = _activityNativeReasoningTransitionOnlyText(row);
    if(transitionText){
      if(pending){
        pending.text = _activityJoinNativeReasoningSegmentText(pending.text || pending.detail || '', transitionText);
        pending.detail = _activityRawText(pending.text || pending.detail || '');
        pending.updatedAt = Math.max(Number(pending.updatedAt || pending.updated_at || pending.ts || 0) || 0, Number(row.updatedAt || row.updated_at || row.ts || 0) || 0);
      }else{
        pending = { ...row, title:'', text:transitionText, detail:transitionText };
      }
      continue;
    }
    if(pending){
      const mergedText = _activityJoinNativeReasoningSegmentText(pending.text || pending.detail || '', row.text || row.detail || '');
      out.push({
        ...row,
        key:String(row.key || pending.key || '').includes('|') ? row.key : String(`${pending.key || 'native_transition'}|${row.key || out.length}`).slice(0, 700),
        text:mergedText,
        detail:_activityRawText(mergedText),
        title:String(row.title || '').trim(),
        ts:Number(pending.ts || row.ts || 0) || Number(row.ts || 0) || 0,
        updatedAt:Math.max(Number(pending.updatedAt || pending.updated_at || pending.ts || 0) || 0, Number(row.updatedAt || row.updated_at || row.ts || 0) || 0),
      });
      pending = null;
      continue;
    }
    out.push(row);
  }
  if(pending) out.push(pending);
  return out;
}

function _activityPlaybackTokenAround(text, index){
  const s = String(text || '');
  if(!s || index < 0 || index >= s.length) return { raw:'', token:'', start:index, end:index, rel:0 };
  let start = index;
  let end = index + 1;
  while(start > 0 && !/\s/.test(s[start - 1])) start -= 1;
  while(end < s.length && !/\s/.test(s[end])) end += 1;
  const raw = s.slice(start, end);
  const leftTrim = (raw.match(/^[<({[\"'“‘]+/) || [''])[0].length;
  const rightTrim = (raw.match(/[>)}\]\"'”’]+$/) || [''])[0].length;
  const tokenStart = start + leftTrim;
  const tokenEnd = end - rightTrim;
  const token = s.slice(tokenStart, tokenEnd);
  return { raw, token, start:tokenStart, end:tokenEnd, rel:index - tokenStart };
}

function _activityPlaybackTokenLooksProtected(token){
  const t = String(token || '').trim();
  if(!t) return false;
  if(/^(?:https?:\/\/|www\.)/i.test(t)) return true;
  if(/^(?:[a-z][a-z0-9+.-]*:\/\/)/i.test(t)) return true;
  if(/^(?:localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})(?::\d{2,5})?(?:[/?#]|$)/i.test(t)) return true;
  if(/^\d+(?:\.\d+)+(?::\d{2,5})?(?:[/?#]|$)/.test(t)) return true;
  if(/^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:[:/\\?#]|$)/.test(t)) return true;
  if(/^[\w.-]+\/[\w./~:%?#\[\]@!$&'()*+,;=-]*$/.test(t)) return true;
  return false;
}

function _activityPlaybackIndexInsideProtectedToken(text, index){
  const s = String(text || '');
  const info = _activityPlaybackTokenAround(s, index);
  if(!info.token || index < info.start || index >= info.end) return false;
  if(!_activityPlaybackTokenLooksProtected(info.token)) return false;
  const ch = s[index] || '';
  // Chinese sentence punctuation is never part of a URL/query/path token.
  if(/[。！？]/.test(ch)) return false;
  return true;
}

function _activityPlaybackDotIsSentenceBoundary(text, index, isCloser){
  const s = String(text || '');
  const prev = index > 0 ? s[index - 1] : '';
  const next = index + 1 < s.length ? s[index + 1] : '';
  if(_activityPlaybackIndexInsideProtectedToken(s, index)) return false;
  if(next === '.') return false;
  if(/[A-Za-z0-9]/.test(prev) && /[A-Za-z0-9]/.test(next)) return false;
  if(_activityInlineEnglishBoundaryLooksAbbrev(s.slice(Math.max(0, index - 48), index + 1))) return false;
  const closer = typeof isCloser === 'function' ? isCloser : (ch)=>/[\"')\]}]/.test(ch || '');
  let look = index + 1;
  while(look < s.length && closer(s[look])) look += 1;
  return look >= s.length || /\s/.test(s[look]);
}

function _activityPlaybackColonIsSentenceBoundary(text, index){
  const s = String(text || '');
  const prev = index > 0 ? s[index - 1] : '';
  const next = index + 1 < s.length ? s[index + 1] : '';
  const left = s.slice(Math.max(0, index - 12), index).toLowerCase();
  if(_activityPlaybackIndexInsideProtectedToken(s, index)) return false;
  if((left.endsWith('http') || left.endsWith('https')) && next === '/') return false;
  if(/\d/.test(prev) && /\d/.test(next)) return false;
  return true;
}

function _activityPlaybackPunctuationStaysInsideUrlToken(text, index){
  return _activityPlaybackIndexInsideProtectedToken(text, index);
}

function _activityChatThinkSoftChunks(text, opts={}){
  const raw = String(text == null ? '' : text).replace(/\r\n?/g, '\n').trim();
  if(!raw) return [];
  const active = !!opts.active;
  const maxLen = Math.max(96, Math.min(Number(opts.maxLen || 170) || 170, 260));
  const minHard = Math.max(56, Math.min(Number(opts.minHard || 86) || 86, 140));
  const maxChunks = Math.max(4, Math.min(Number(opts.maxChunks || 14) || 14, 24));
  const chunks = [];
  let buf = '';
  const push = (closed)=>{
    const s = buf.replace(/\s+$/g, '').trim();
    buf = '';
    if(s) chunks.push({ text:s, closed:!!closed });
  };
  for(let i = 0; i < raw.length; i += 1){
    const ch = raw[i];
    buf += ch;
    const next = raw[i + 1] || '';
    let atSentence = /[!?。！？；;：]/.test(ch);
    if(ch === '.') atSentence = _activityPlaybackDotIsSentenceBoundary(raw, i);
    else if(ch === ':') atSentence = _activityPlaybackColonIsSentenceBoundary(raw, i);
    else if((ch === '?' || ch === '!') && _activityPlaybackPunctuationStaysInsideUrlToken(raw, i)) atSentence = false;
    const atSoftBreak = /[，,、]/.test(ch) && buf.trim().length >= minHard;
    const atMarkdownLine = ch === '\n' && /^(?:\s*[-*+]\s+|\s*\d{1,3}[.)]\s+|\s{0,3}#{1,6}\s+)/.test(raw.slice(i + 1, i + 80));
    const tooLong = buf.trim().length >= maxLen && (/\s/.test(ch) || /[，,、]/.test(ch) || !next || buf.trim().length >= maxLen + 36);
    if(atSentence || atSoftBreak || atMarkdownLine || tooLong){
      push(true);
      while(raw[i + 1] === '\n' && raw[i + 2] === '\n') i += 1;
    }
  }
  if(buf.trim()){
    if(!active || chunks.length === 0 || buf.trim().length >= 34) push(!active);
  }
  if(chunks.length <= maxChunks) return chunks;
  const head = chunks.slice(0, 2);
  const tail = chunks.slice(-(maxChunks - head.length));
  return head.concat(tail);
}

function _activityExpandChatThinkSoftPanelRows(rows){
  const out = [];
  for(const raw of Array.isArray(rows) ? rows : []){
    const row = raw && typeof raw === 'object' ? raw : null;
    if(!row) continue;
    if(_activityIsResponsesNativeReasoningItem(row)){
      out.push(row);
      continue;
    }
    const stage = String(row.stage || row.kind || '').toLowerCase();
    if(stage !== 'think'){
      out.push(row);
      continue;
    }
    const source = String(row.source || row.nativeReasoningSource || row.native_reasoning_source || '').toLowerCase();
    if(source && _activityIsResponsesNativeReasoningSource(source)){
      out.push(row);
      continue;
    }
    const text = String(row.text || row.detail || '').replace(/\r\n?/g, '\n').trim();
    const active = String(row.state || '').toLowerCase() === 'active';
    const chunks = _activityChatThinkSoftChunks(text, { active });
    if(!chunks.length){
      out.push(row);
      continue;
    }
    const closedChunks = chunks.filter(chunk => chunk && chunk.closed);
    const displayChunks = closedChunks.length ? closedChunks : chunks.slice(0, 1);
    const displayText = displayChunks
      .map(chunk => chunk.text)
      .filter(Boolean)
      .join(' ')
      .replace(/[ \t]*\n+[ \t]*/g, ' ')
      .replace(/\s{2,}/g, ' ')
      .trim();
    const fallbackText = text.replace(/[ \t]*\n+[ \t]*/g, ' ').replace(/\s{2,}/g, ' ').trim();
    out.push({
      ...row,
      detail:displayText || fallbackText || text,
      text:displayText || fallbackText || text,
      chatThinkSoftFlow:true,
    });
  }
  return out;
}


function _activityResponsesReasoningHeadingLooksSection(title){
  const s = String(title || '').replace(/[`*_#>\[\](){}]/g, '').replace(/\s+/g, ' ').trim();
  if(!_activityNativeReasoningTitleShouldBreak(s)) return false;
  if(s.length < 8 || s.length > 92) return false;
  if(/[。！？!?]$/.test(s)) return false;
  if(/https?:\/\//i.test(s)) return false;
  if(/[,，;；]{2,}/.test(s)) return false;
  const words = s.split(/\s+/).filter(Boolean).length;
  if(words > 10) return false;
  const firstLatin = s.match(/[A-Za-z]/);
  if(firstLatin && firstLatin[0] !== firstLatin[0].toUpperCase()) return false;
  return true;
}

function _activityResponsesReasoningBoldHeadingAtBoundary(text, matchIndex, matchText){
  const raw = String(text || '');
  const before = raw.slice(Math.max(0, matchIndex - 12), matchIndex);
  const after = raw.slice(matchIndex + String(matchText || '').length);
  const beforeTrim = before.replace(/\s+$/g, '');
  if(beforeTrim && !/[\n.!?。！？:：]$/.test(beforeTrim)) return false;
  // Real Responses reasoning section titles are normally followed by a body. Do
  // not split bold emphasis buried in a sentence unless the boundary is clear.
  if(after && !/^\s*\n/.test(after)) return false;
  return true;
}

function _activitySplitResponsesReasoningTextBlocks(text, initialTitle){
  const raw = String(text || '').replace(/\r\n?/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  const firstTitle = String(initialTitle || '').replace(/\s+/g, ' ').trim();
  if(!raw && !firstTitle) return [];
  const blocks = [];
  let currentTitle = _activityResponsesReasoningHeadingLooksSection(firstTitle) ? firstTitle : '';
  let currentText = '';
  let cursor = 0;
  const push = ()=>{
    const body = String(currentText || '').replace(/^\s+|\s+$/g, '').replace(/\n{3,}/g, '\n\n');
    const title = String(currentTitle || '').trim();
    if(title || body) blocks.push({ title, body });
    currentTitle = '';
    currentText = '';
  };
  const re = /(?:\*\*|__)([^*_\n][^\n]{2,110}?)(?:\*\*|__)/g;
  let m;
  while((m = re.exec(raw))){
    const full = m[0] || '';
    const candidate = _activityCleanText(m[1] || '', 110);
    if(!_activityResponsesReasoningHeadingLooksSection(candidate)) continue;
    if(!_activityResponsesReasoningBoldHeadingAtBoundary(raw, m.index, full)) continue;
    const before = raw.slice(cursor, m.index);
    if(before.trim()) currentText = _activityJoinNativeReasoningSegmentText(currentText, before);
    push();
    currentTitle = candidate;
    cursor = m.index + full.length;
  }
  const rest = raw.slice(cursor);
  if(rest.trim()) currentText = _activityJoinNativeReasoningSegmentText(currentText, rest);
  push();
  if(!blocks.length && (raw || firstTitle)) blocks.push({ title:firstTitle, body:raw });
  return blocks.filter(block => String(block.title || block.body || '').trim());
}

function _activityResponsesReasoningSplitKey(baseKey, index, block){
  const seed = `${block?.title || ''}|${String(block?.body || '').slice(0, 80)}`;
  let hash = 0;
  for(let i = 0; i < seed.length; i += 1){
    hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
  }
  return String(`${baseKey || 'responses_reasoning'}|panel_part|${index}|${Math.abs(hash)}`).slice(0, 700);
}

function _activitySplitResponsesNativeReasoningPanelRows(rows){
  const sourceRows = Array.isArray(rows) ? rows : [];
  const out = [];
  for(const raw of sourceRows){
    const row = raw && typeof raw === 'object' ? raw : null;
    if(!row) continue;
    if(!_activityIsResponsesNativeReasoningItem(row)){
      out.push(row);
      continue;
    }
    const text = String(row.text || row.detail || '').replace(/\r\n?/g, '\n').trim();
    const blocks = _activitySplitResponsesReasoningTextBlocks(text, row.title || '');
    if(blocks.length <= 1){
      out.push({ ...row, responsesNativeReasoning:true, renderMode:row.renderMode || 'markdown' });
      continue;
    }
    const rowState = String(row.state || '').toLowerCase();
    const activeRow = rowState === 'active';
    const erroredRow = rowState === 'error';
    const baseTs = Number(row.ts || row.startedAt || row.started_at || 0) || 0;
    const baseUpdated = Number(row.updatedAt || row.updated_at || row.ts || 0) || baseTs || 0;
    blocks.forEach((block, index)=>{
      const isLast = index === blocks.length - 1;
      const state = erroredRow && isLast ? 'error' : (activeRow && isLast ? 'active' : 'done');
      const body = String(block.body || '').trim();
      const title = String(block.title || '').trim();
      out.push({
        ...row,
        key:_activityResponsesReasoningSplitKey(row.key || row.id || baseTs, index, block),
        title,
        text:body,
        detail:_activityRawText(body),
        state,
        ts:baseTs ? baseTs + index : baseTs,
        updatedAt:baseUpdated ? baseUpdated + index : baseUpdated,
        responsesNativeReasoning:true,
        responsesReasoningSplit:true,
        renderMode:row.renderMode || 'markdown',
      });
    });
  }
  return _activityMergeNativeReasoningTransitionRows(out);
}

function _activityNativeReasoningTextEndsClosed(text){
  const s = String(text || '').replace(/\s+$/g, '');
  if(!s) return false;
  return /(?:[.!?;:]|[。！？；：])(?:["')\]}>]|[”’）】》」』])*$/u.test(s);
}

function _activityNativeReasoningSegmentShouldFlush(row, text){
  const s = String(text || '').replace(/\s+/g, ' ').trim();
  if(!s) return false;
  // With a real provider event key, the event boundary itself is the unit.
  // Do not split it again just because a sentence ended.
  if(_activityNativeReasoningEventKey(row)) return false;
  if(_activityNativeReasoningTextEndsClosed(s)) return true;
  if(s.length >= 420) return true;
  const rowState = String(row?.state || '').toLowerCase();
  return rowState === 'done' && s.length >= 140;
}

function _activityCompactNativeReasoningPanelSegments(segments){
  const rows = Array.isArray(segments) ? segments.filter(Boolean) : [];
  const normalized = rows.map(raw => {
    const cur = { ...(raw || {}) };
    cur.text = String(cur.text || cur.detail || '').replace(/\r\n?/g, '\n');
    cur.detail = String(cur.detail || cur.text || '').replace(/\r\n?/g, '\n');
    cur.updatedAt = Number(cur.updatedAt || cur.updated_at || cur.ts || 0) || 0;
    if(_activityIsResponsesNativeReasoningItem(cur)) cur.responsesNativeReasoning = true;
    cur.renderMode = cur.renderMode || 'markdown';
    return cur;
  }).filter(cur => cur.text.trim() || String(cur.title || '').trim());
  const ordered = _activitySortTimelineItems(normalized);
  const out = [];
  let pending = null;
  const flush = ()=>{
    if(!pending) return;
    const text = String(pending.text || pending.detail || '').replace(/\r\n?/g, '\n').trim();
    const title = String(pending.title || '').trim();
    if(text || title){
      out.push({
        ...pending,
        text,
        detail:_activityRawText(text),
        title,
        renderMode:pending.renderMode || 'markdown',
      });
    }
    pending = null;
  };
  for(const row of ordered){
    const text = String(row.text || row.detail || '').replace(/\r\n?/g, '\n').trim();
    const title = String(row.title || '').trim();
    const pendingSeq = Number(pending?.seqEnd || pending?.seq_end || pending?.seq || 0) || 0;
    const rowSeq = Number(row.seq || 0) || 0;
    const keyedReasoningPair = !!(_activityNativeReasoningEventKey(pending) && _activityNativeReasoningEventKey(row));
    const shouldBreak = pending && (
      _activityShouldBreakNativeReasoningSegment(pending, row)
      || (!keyedReasoningPair && pendingSeq > 0 && rowSeq > 0 && rowSeq > pendingSeq + 1)
      || (!keyedReasoningPair && title && _activityNativeReasoningTitleShouldBreak(title))
    );
    if(shouldBreak) flush();
    if(!pending){
      pending = { ...row, text, detail:text };
    }else{
      const prevUpdated = Number(pending.updatedAt || pending.updated_at || pending.ts || 0) || 0;
      const rowUpdated = Number(row.updatedAt || row.updated_at || row.ts || 0) || 0;
      const joined = _activityJoinNativeReasoningSegmentText(pending.text || pending.detail || '', text);
      pending = {
        ...pending,
        state:String(row.state || '').toLowerCase() === 'active' ? 'active' : (pending.state || row.state || 'done'),
        updatedAt:Math.max(prevUpdated, rowUpdated),
        updated_at:Math.max(prevUpdated, rowUpdated),
        seq:Number(pending.seq || 0) || Number(row.seq || 0) || 0,
        seqEnd:Math.max(Number(pending.seqEnd || pending.seq_end || pending.seq || 0) || 0, Number(row.seqEnd || row.seq_end || row.seq || 0) || 0),
        text:joined,
        detail:joined,
        responsesNativeReasoning:!!(pending.responsesNativeReasoning || row.responsesNativeReasoning),
        ...(_activityNativeReasoningEventKey(pending) ? { segmentKey:_activityNativeReasoningEventKey(pending), reasoningEventKey:_activityNativeReasoningEventKey(pending) } : {}),
      };
    }
    if(_activityNativeReasoningSegmentShouldFlush(row, pending?.text || '')) flush();
  }
  flush();
  return _activitySplitResponsesNativeReasoningPanelRows(out);
}

function _activityNormalizeNativeReasoningSegments(meta, snapshot, rt, opts={}){
  const m = meta && typeof meta === 'object' ? meta : {};
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const rawSegments = Array.isArray(m.nativeReasoningSegments) ? m.nativeReasoningSegments : (Array.isArray(snap.nativeReasoningSegments) ? snap.nativeReasoningSegments : []);
  const nativeText = String(m.nativeReasoningText || snap.nativeReasoningText || '').trim();
  const nativeConnected = !!(m.nativeReasoningConnected || snap.nativeReasoningConnected || nativeText || rawSegments.length);
  if(!nativeConnected) return [];
  const explicitDone = !!(m.nativeReasoningDone || snap.nativeReasoningDone);
  const finalDone = explicitDone || !rt?.streaming || !!opts.message || !!opts.finalSnapshot;
  const nativeStartAt = Math.max(Number(m.nativeReasoningStartAt || m.native_reasoning_start_at || 0) || 0, Number(snap.nativeReasoningStartAt || snap.native_reasoning_start_at || 0) || 0);
  const nativeEndAt = Math.max(Number(m.nativeReasoningEndAt || m.native_reasoning_end_at || 0) || 0, Number(snap.nativeReasoningEndAt || snap.native_reasoning_end_at || 0) || 0);
  let source = String(m.nativeReasoningSource || snap.nativeReasoningSource || '').trim().slice(0, 40);
  let segments = [];
  const rawSegmentRows = Array.isArray(rawSegments) ? rawSegments : [];
  const rawSegmentsAreResponsesNative = _activityIsResponsesNativeReasoningSource(source)
    || rawSegmentRows.some(raw => raw && typeof raw === 'object' && (
      raw.responsesNativeReasoning
      || raw.responses_native_reasoning
      || _activityIsResponsesNativeReasoningSource(raw.source)
      || _activityIsResponsesNativeReasoningSource(raw.nativeReasoningSource || raw.native_reasoning_source)
    ));
  // Critical: when nativeReasoningText exists, do not throw away
  // nativeReasoningSegments.  The aggregate text has nativeStartAt and will pin
  // all before/after-search thoughts to the first row.  Segments are the only
  // source that can be interleaved with search/read ActivityEvents by seq/ts.
  const usableRawSegments = rawSegmentRows.length ? rawSegmentRows : [];
  usableRawSegments.forEach((raw, index)=>{
    if(!raw || typeof raw !== 'object') return;
    const text = String(raw.text || raw.delta || raw.content || raw.detail || '').replace(/\r\n?/g, '\n').trim();
    if(!text) return;
    const ts = _activityNormalizeEventTs(raw.ts || raw.startedAt || raw.started_at || raw.createdAt || raw.created_at || raw.updatedAt || raw.updated_at, nativeStartAt || Date.now() + index);
    const rawState = String(raw.state || '').trim().toLowerCase();
    const state = /^(active|done|warn|error)$/.test(rawState) ? rawState : (finalDone ? 'done' : 'active');
    source = source || String(raw.source || '').trim().slice(0, 40);
    const segmentSource = String(raw.source || source || '').trim().slice(0, 40);
    const isResponsesNativeReasoning = _activityIsResponsesNativeReasoningSource(segmentSource);
    const nativeTitleBody = _activityExtractNativeReasoningTitleAndBody(text);
    const nativeTitle = nativeTitleBody.title || '';
    const nativeBody = nativeTitleBody.title ? nativeTitleBody.body : text;
    const seq = Number(raw.seq || raw.order || raw._job_seq || 0) || 0;
    const seqEnd = Math.max(seq, Number(raw.seqEnd || raw.seq_end || raw.orderEnd || raw.order_end || raw._job_seq_end || 0) || 0);
    const eventKey = _activityNativeReasoningEventKey(raw);
    segments.push({
      key:String(raw.key || (eventKey ? `native_reasoning_segment|${eventKey}` : `native_reasoning_segment|${ts}|${index}`)).slice(0, 700),
      title:nativeTitle,
      detail:_activityRawText(nativeBody),
      stage:'think',
      state:finalDone && state !== 'error' ? 'done' : state,
      ts,
      ...(seq > 0 ? { seq } : {}),
      ...(seqEnd > 0 ? { seqEnd } : {}),
      ...(eventKey ? { segmentKey:eventKey, reasoningEventKey:eventKey } : {}),
      text:nativeBody,
      source:segmentSource || source,
      ...(isResponsesNativeReasoning ? { responsesNativeReasoning:true } : {}),
      renderMode:'markdown',
    });
  });
  if(!segments.length && nativeText){
    const isResponsesNativeReasoning = _activityIsResponsesNativeReasoningSource(source || m.nativeReasoningSource || snap.nativeReasoningSource);
    const nativeTitleBody = _activityExtractNativeReasoningTitleAndBody(nativeText);
    const nativeTitle = nativeTitleBody.title || '';
    const nativeBody = nativeTitleBody.title ? nativeTitleBody.body : nativeText;
    segments.push({
      key:'native_reasoning',
      title:nativeTitle,
      detail:_activityRawText(nativeBody),
      stage:'think',
      state:finalDone ? 'done' : 'active',
      ts:nativeStartAt || Date.now() - 10,
      text:nativeBody,
      source,
      ...(isResponsesNativeReasoning ? { responsesNativeReasoning:true } : {}),
      renderMode:'markdown',
    });
  }
  if(segments.length){
    segments = _activityCompactNativeReasoningPanelSegments(segments);
    let elapsed = '';
    if(nativeStartAt > 0 && typeof _formatReasoningElapsedShort === 'function'){
      elapsed = _formatReasoningElapsedShort(Math.max(0, (finalDone ? (nativeEndAt || Date.now()) : Date.now()) - nativeStartAt));
    }
    if(elapsed && segments.length) segments[segments.length - 1].nativeElapsed = elapsed;
  }
  return segments;
}

function _activitySearchRoundIndex(item){
  try{
    const direct = Number(item?.index || item?.round_index || item?.roundIndex || 0) || 0;
    if(direct > 0) return direct;
    const text = `${item?.title || ''} ${item?.key || ''} ${item?.rawStage || item?.raw_stage || ''}`;
    const m = String(text).match(/(?:第\s*)?(\d{1,3})\s*(?:次|轮)?\s*搜索|web_query_group\|(\d{1,3})/i);
    if(m) return Number(m[1] || m[2] || 0) || 0;
  }catch(_){ }
  return 0;
}


function _activityPushRealQueryValue(out, seen, value){
  const q = _activityCleanText(value, 160);
  if(!q) return;
  const key = q.toLowerCase();
  if(seen.has(key)) return;
  seen.add(key);
  out.push(q);
}

function _activityQueryLooksLikeReasoningFragment(value){
  const s = String(value || '').replace(/\s+/g, ' ').trim();
  if(!s) return true;
  // Native reasoning deltas can be accidentally copied into `queries` as
  // sentence fragments, for example: "m considering creating a .docx".
  // Search chips must only show real user/search-engine queries.
  if(s.length > 150) return true;
  if(/^[`'’]*m\b/i.test(s)) return true;
  if(/^(?:i|i['’]?m|i['’]?ll|i\s+will|we|we['’]?re|let['’]?s)\b/i.test(s)) return true;
  if(/\b(?:considering|ensure|ensuring|seems? important|the user|user requested|requested|asked|i could|i should|i need|i['’]?ll|i will|官方文档|我(?:在|会|需要|应该|可以)|用户(?:要求|请求|问)|确保|考虑|看来|似乎)\b/i.test(s)) return true;
  // A real search query is usually a compact phrase.  Long multi-sentence
  // English/Chinese text is almost always model thought or answer prose.
  const sentenceMarks = (s.match(/[.!?。！？]/g) || []).length;
  if(sentenceMarks >= 2) return true;
  if(sentenceMarks >= 1 && s.length > 90) return true;
  return false;
}

function _activityIsSearchQueryCarrier(item){
  if(!item || typeof item !== 'object') return false;
  const kind = String(item.kind || item.stage || '').trim().toLowerCase();
  const rawStage = String(item.rawStage || item.raw_stage || item.stage || item.panelStage || item.panel_stage || '').trim().toLowerCase();
  const tool = String(item.tool || '').trim().toLowerCase();
  const actionType = String(item.action_type || item.actionType || item.activity_op || item.activityOp || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  const title = String(item.title || item.text || '').trim();
  const key = String(item.key || item.id || '').trim().toLowerCase();
  if(['web_fetch','fetch_url','fetch_urls'].includes(tool)) return false;
  if(['open_page','read_page','page_open'].includes(actionType)) return false;
  if(/(?:^|[|:_-])(?:open_page|read_page|page_open|web_fetch|fetch_url|fetch_urls)(?:$|[|:_-])/.test(`${rawStage}|${key}`)) return false;
  if(typeof _activityIsWebReadTimelineItem === 'function' && _activityIsWebReadTimelineItem(item)) return false;
  if(tool === 'web_search') return true;
  if(tool === 'image_search') return true;
  if(kind === 'web_query_group') return true;
  if(['search','web_search','web_query_group','image_search'].includes(actionType)) return true;
  if(rawStage.includes('web_query_group') || key.includes('web_query_group')) return true;
  if(key.includes('native_query_group') || key.includes('|query_group|')) return true;
  // Plain `stage: search` is not enough. Some page-read/source rows are still
  // normalized as kind=search, and their `queries` can contain native reasoning
  // text. Require an actual search-like title for generic search-stage rows.
  if((rawStage.includes('search') || kind === 'search') && /搜索|查询|检索|联网|web search|search/i.test(title)) return true;
  return false;
}

function _activitySanitizeQueriesForItem(item, queries){
  const rows = Array.isArray(queries) ? queries : [];
  if(!rows.length) return [];
  if(!_activityIsSearchQueryCarrier(item)) return [];
  const out = [];
  const seen = new Set();
  for(const value of rows){
    const q = _activityCleanText(value, 120);
    if(!q || _activityQueryLooksLikeReasoningFragment(q)) continue;
    const key = q.toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    out.push(q);
    if(out.length >= 6) break;
  }
  return out;
}

function _activityShouldRenderQueryChips(item){
  return !!(Array.isArray(item?.queries) && item.queries.length && _activityIsSearchQueryCarrier(item));
}

function _activityExplicitWebQueries(meta, snapshot, progressEvents){
  const out = [];
  const seen = new Set();
  const push = (value)=>_activityPushRealQueryValue(out, seen, value);
  const pushList = (list)=>{
    if(!Array.isArray(list)) return;
    for(const row of list){
      if(typeof row === 'string') push(row);
      else if(row && typeof row === 'object') {
        const queryValue = row.query || row.search_query || row.searchQuery || row.q || '';
        if(queryValue) push(queryValue);
      }
    }
  };
  pushList(meta?.queriesUsed || meta?.queries_used || []);
  pushList(snapshot?.queriesUsed || snapshot?.queries_used || []);
  const groups = [];
  const collectGroupRows = (rows)=>{
    if(Array.isArray(rows)) groups.push(...rows);
  };
  collectGroupRows(meta?.webQueryGroups || meta?.web_query_groups || []);
  collectGroupRows(snapshot?.webQueryGroups || snapshot?.web_query_groups || []);
  collectGroupRows(meta?.nativeWebCalls || meta?.native_web_calls || []);
  collectGroupRows(snapshot?.nativeWebCalls || snapshot?.native_web_calls || []);
  for(const group of groups){
    if(!group || typeof group !== 'object') continue;
    pushList(group.queries || group.search_queries || []);
    push(group.query || group.search_query || group.searchQuery || '');
  }
  for(const item of (Array.isArray(progressEvents) ? progressEvents : [])){
    if(!item || typeof item !== 'object') continue;
    const stage = String(item.stage || item.rawStage || item.raw_stage || item.source || '').toLowerCase();
    const title = String(item.title || item.text || '').toLowerCase();
    if(!(stage.includes('web') || stage.includes('search') || title.includes('搜索') || title.includes('网页'))) continue;
    pushList(item.queries || []);
    push(item.query || item.search_query || item.searchQuery || '');
  }
  return out.slice(0, 12);
}

function _activitySourceItemsFromGroupRaw(raw){
  if(!raw || typeof raw !== 'object') return [];
  const pools = [];
  const add = (value)=>{ if(Array.isArray(value) && value.length) pools.push(value); };
  add(raw.sourceItems || raw.source_items);
  add(raw.sources || raw.searchResults || raw.search_results || raw.results || raw.items);
  let merged = [];
  for(const pool of pools) merged = merged.concat(pool);
  return _activityNormalizeSourceItems(merged, WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
}

function _activityBuildRealWebQueryGroups(meta, snapshot, progressEvents){
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const rawMeta = snap.reasoningMeta && typeof snap.reasoningMeta === 'object' ? snap.reasoningMeta : {};
  const rawGroups = [];
  const addGroups = (rows)=>{ if(Array.isArray(rows)) rawGroups.push(...rows); };
  // Keep the already-normalized meta rows, but also read the original
  // reasoningMeta rows.  The old reasoning panel stored real search sources in
  // raw web_query_groups/progress_events; the first activity-panel pass
  // normalized those rows and accidentally dropped source_items.
  addGroups(rawMeta.webQueryGroups || rawMeta.web_query_groups || []);
  addGroups(snap.webQueryGroups || snap.web_query_groups || []);
  addGroups(meta?.webQueryGroups || meta?.web_query_groups || []);
  addGroups(rawMeta.nativeWebCalls || rawMeta.native_web_calls || []);
  addGroups(snap.nativeWebCalls || snap.native_web_calls || []);
  addGroups(meta?.nativeWebCalls || meta?.native_web_calls || []);
  let groups = (typeof _normalizeReasoningWebQueryGroups === 'function')
    ? _normalizeReasoningWebQueryGroups(rawGroups)
    : [];
  groups = groups.filter(group => _activityQueriesFromGroup(group).length);
  if(groups.length){
    return groups.map((group, index)=>{
      const queries = _activityQueriesFromGroup(group);
      const candidates = rawGroups.filter(row => {
        if(!row || typeof row !== 'object') return false;
        const rawQueries = (Array.isArray(row.queries) ? row.queries : (row.query || row.search_query || row.searchQuery ? [row.query || row.search_query || row.searchQuery] : []))
          .map(q => String(q || '').trim()).filter(Boolean);
        const rawIndex = Number(row.index || index + 1) || (index + 1);
        const groupIndex = Number(group.index || index + 1) || (index + 1);
        return rawIndex === groupIndex || (rawQueries.length && rawQueries.join('\n') === queries.join('\n'));
      });
      const raw = candidates.find(row => _activitySourceItemsFromGroupRaw(row).length) || candidates[0] || rawGroups[index] || {};
      const sourceItems = _activityNormalizeSourceItems([
        ..._activitySourceItemsFromGroupRaw(group),
        ..._activitySourceItemsFromGroupRaw(raw),
      ], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
      return {
        ...group,
        ...(sourceItems.length ? { sourceItems } : {}),
        resultCount: Number(group.resultCount || group.result_count || raw.result_count || raw.resultCount || 0) || 0,
      };
    });
  }
  const queries = _activityExplicitWebQueries(meta, snapshot, progressEvents);
  if(!queries.length) return [];
  const nativeRows = [];
  const addNative = (rows)=>{ if(Array.isArray(rows)) nativeRows.push(...rows); };
  addNative(meta?.nativeWebCalls || meta?.native_web_calls || []);
  addNative(snapshot?.nativeWebCalls || snapshot?.native_web_calls || []);
  const firstNative = nativeRows.find(row => row && typeof row === 'object') || {};
  let ts = Number(firstNative.started_at || firstNative.startedAt || firstNative.updated_at || firstNative.updatedAt || 0) || 0;
  if(ts > 0 && ts < 10000000000) ts *= 1000;
  const stateRaw = String(firstNative.state || '').trim().toLowerCase();
  const statusRaw = String(firstNative.status || '').trim().toLowerCase();
  const state = /^(active|done|warn|error)$/.test(stateRaw) ? stateRaw : ({completed:'done', complete:'done', done:'done', success:'done', succeeded:'done', error:'error', failed:'error', searching:'active', in_progress:'active', running:'active', pending:'active', queued:'active'}[statusRaw] || 'active');
  const chunks = [];
  const chunkSize = 3;
  for(let i = 0; i < queries.length; i += chunkSize) chunks.push(queries.slice(i, i + chunkSize));
  return chunks.map((chunk, index)=>{
    const row = nativeRows[index] || (index === 0 ? firstNative : {}) || {};
    const sourceItems = _activitySourceItemsFromGroupRaw(row);
    return {
      index:index + 1,
      round:Number(row.round || firstNative.round || 0) || 0,
      status:String(row.status || statusRaw || (state === 'done' ? 'completed' : 'searching')).trim().toLowerCase(),
      state:String(row.state || state || 'active').trim().toLowerCase() || 'active',
      queries:chunk,
      queryCount:chunk.length,
      resultCount:Number(row.result_count || row.resultCount || firstNative.result_count || firstNative.resultCount || 0) || 0,
      key:`web_query_group|real_meta|${index + 1}|${chunk.join('|')}`,
      ts:(Number(row.started_at || row.startedAt || row.updated_at || row.updatedAt || 0) > 0 ? normalizeActivityTs(row.started_at || row.startedAt || row.updated_at || row.updatedAt) : (ts || Date.now())) + index,
      ...(sourceItems.length ? { sourceItems } : {}),
    };
  });
}

function normalizeActivityTs(value){
  let n = Number(value || 0) || 0;
  if(n > 0 && n < 10000000000) n *= 1000;
  return n > 0 ? n : Date.now();
}

function _activityQueriesFromGroup(group){
  return (Array.isArray(group?.queries) ? group.queries : [])
    .map(q => String(q || '').trim())
    .filter(Boolean)
    .slice(0, 8);
}

function _activityIsNativeWebCallItem(item){
  if(!item || typeof item !== 'object') return false;
  const source = String(item.source || item.provider || '').toLowerCase();
  const key = String(item.key || item.id || '').toLowerCase();
  const stage = String(item.stage || item.rawStage || item.raw_stage || item.panelStage || item.panel_stage || '').toLowerCase();
  return source === 'native_web_call'
    || source.includes('native_web_call')
    || key.includes('web|native_query_group')
    || key.includes('native_web_call')
    || stage === 'web_query_group';
}

function _activityIsWebReadTimelineItem(item){
  if(!item || typeof item !== 'object') return false;
  const tool = String(item.tool || '').trim().toLowerCase();
  const rawStage = String(item.rawStage || item.raw_stage || item.stage || item.panelStage || item.panel_stage || '').trim().toLowerCase();
  const actionType = String(item.action_type || item.actionType || item.activity_op || item.activityOp || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  const source = String(item.source || item.provider || '').trim().toLowerCase();
  const key = String(item.key || item.id || '').trim().toLowerCase();
  const text = `${item.title || ''} ${item.detail || ''} ${item.text || ''}`.trim();
  if(['web_fetch','fetch_url','fetch_urls'].includes(tool)) return true;
  if(['open_page','read_page','page_open'].includes(actionType)) return true;
  if(/(?:^|[|:_-])(?:open_page|read_page|page_open|web_fetch|fetch_url|fetch_urls)(?:$|[|:_-])/.test(`${rawStage}|${key}`)) return true;
  if(source.includes('native_web_call') && ['open_page','read_page','page_open'].includes(actionType)) return true;
  return /(?:阅读|读取|抓取)(?:网页|链接)|(?:正在|已)(?:阅读|读取|抓取)[:：]?[^。]*网页/.test(text);
}

function _activityNormalizeTimelinePreserveOrder(items){
  const out = [];
  for(const raw of Array.isArray(items) ? items : []){
    const item = _activityNormalizeItem(raw, out.length);
    const isTitlelessThink = _activityLooksNativeReasoningItem(item) && String(item.detail || item.text || '').trim();
    if(!item.title && !isTitlelessThink) continue;
    if(_activityIsInternalToolInvocationItem(item)) continue;
    if(_activityIsGenericCompletionItem(item)) continue;
    if(_activityIsSyntheticSearchSummaryItem(item)) continue;
    out.push(item);
  }
  return out.slice(-80);
}

function _activityEnrichSearchItemsWithQueryGroups(items, groups){
  const arr = Array.isArray(items) ? items.map(item => (item && typeof item === 'object') ? { ...item } : item) : [];
  const normalizedGroups = (Array.isArray(groups) ? groups : [])
    .map((group, index) => ({
      ...group,
      _activityIndex:Number(group?.index || index + 1) || (index + 1),
      _activityQueries:_activityQueriesFromGroup(group),
    }))
    .filter(group => group._activityQueries.length);
  if(!arr.length || !normalizedGroups.length) return arr;
  const used = new Set();
  const nextUnusedGroup = ()=>{
    for(const group of normalizedGroups){
      if(!used.has(group._activityIndex)) return group;
    }
    return null;
  };
  for(let i = 0; i < arr.length; i += 1){
    const item = arr[i];
    if(!item || typeof item !== 'object') continue;
    const stage = String(item.stage || item.kind || '').toLowerCase();
    const rawStage = String(item.rawStage || item.raw_stage || '').toLowerCase();
    const title = String(item.title || '').trim();
    const key = String(item.key || item.id || '').toLowerCase();
    const isSearch = stage === 'search' || stage === 'web_query_group' || rawStage.includes('search') || rawStage.includes('web_query_group') || key.includes('query_group') || /搜索|网页|web search|search/i.test(title);
    if(!isSearch) continue;
    const existing = (Array.isArray(item.queries) ? item.queries : []).map(q => String(q || '').trim()).filter(Boolean);
    const round = _activitySearchRoundIndex(item);
    if(existing.length){
      // Progress events often already contain the real query but not the
      // per-query website chips.  Match the corresponding web_query_group and
      // merge only its real search-result sourceItems.
      const existingKey = existing.join('\n').toLowerCase();
      let matchedGroup = null;
      if(round > 0) matchedGroup = normalizedGroups.find(g => g._activityIndex === round);
      if(!matchedGroup){
        matchedGroup = normalizedGroups.find(g => (g._activityQueries || []).join('\n').toLowerCase() === existingKey);
      }
      const groupSources = _activityNormalizeSourceItems(matchedGroup?.sourceItems || matchedGroup?.source_items || [], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
      if(groupSources.length){
        arr[i] = {
          ...item,
          sourceItems:_activityNormalizeSourceItems([...(Array.isArray(item.sourceItems) ? item.sourceItems : []), ...groupSources], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT),
          resultCount:Number(item.resultCount || item.result_count || matchedGroup?.resultCount || matchedGroup?.result_count || groupSources.length || 0) || 0,
          state: String(item.state || '').toLowerCase() === 'active' && String(matchedGroup?.state || '').toLowerCase() === 'done' ? 'done' : item.state,
        };
      }
      if(matchedGroup) used.add(matchedGroup._activityIndex);
      continue;
    }
    const genericTitle = /^(?:第\s*\d+\s*次搜索(?:中|完成)?|搜索网页|网页搜索|搜索中|查询中|正在联网搜索)$/i.test(title);
    const concreteSources = _activityNormalizeSourceItems(item.sourceItems || item.source_items || item.sources || item.searchResults || item.search_results || [], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
    const concreteCount = Number(item.resultCount || item.result_count || 0) || 0;
    // Do not invent a query for native Responses web rows. Native web search
    // already exposes real per-call action/query/source data; if this item has
    // no query, it is usually an open_page / page-read observation and must not
    // borrow a query from another search call.
    if(_activityIsNativeWebCallItem(item)) continue;
    if(!genericTitle || concreteSources.length || concreteCount > 0) continue;
    let group = round > 0 ? normalizedGroups.find(g => g._activityIndex === round && !used.has(g._activityIndex)) : null;
    if(!group) group = nextUnusedGroup();
    if(!group) continue;
    used.add(group._activityIndex);
    const queries = group._activityQueries;
    const groupSources = _activityNormalizeSourceItems(group.sourceItems || group.source_items || [], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
    arr[i] = {
      ...item,
      queries,
    title: genericTitle ? _activitySearchTitleFromQueries(queries, title || _activityEventTitle('web_search', 'done')) : item.title,
      state: String(item.state || '').toLowerCase() === 'active' && String(group.state || '').toLowerCase() === 'done' ? 'done' : item.state,
      ts: Number(item.ts || 0) || Number(group.ts || 0) || Date.now() + i,
      resultCount:Number(item.resultCount || item.result_count || group.resultCount || group.result_count || 0) || 0,
      ...(groupSources.length ? { sourceItems:_activityNormalizeSourceItems([...(Array.isArray(item.sourceItems) ? item.sourceItems : []), ...groupSources], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT) } : {}),
    };
  }
  return arr;
}

function _activitySortTimelineItems(items){
  const arr = (Array.isArray(items) ? items : []).filter(Boolean);
  arr.sort((a, b)=>{
    const as = Number(a.seq || 0) || 0;
    const bs = Number(b.seq || 0) || 0;
    // ActivityEvent.seq is the canonical stream order. Prefer it over timestamps
    // because several rows can be finalized with close or patched ts values.
    if(as > 0 && bs > 0 && as !== bs) return as - bs;
    const at = Number(a.ts || 0) || 0;
    const bt = Number(b.ts || 0) || 0;
    if(at > 0 && bt > 0 && at !== bt) return at - bt;
    // Do not automatically put every seq-bearing tool/search row before a
    // native reasoning row that lacks seq. Older snapshots may still miss seq;
    // in that case timestamps / original insertion order are safer than the
    // old "seq wins over no-seq" rule, which created fake timelines.
    if(at > 0 && bt <= 0) return -1;
    if(bt > 0 && at <= 0) return 1;
    // No timestamp/sequence fallback: keep the original insertion order. Do not
    // force native reasoning above tools/search, otherwise final snapshots can
    // visually push separated reasoning segments together.
    return 0;
  });
  return arr;
}

function _activityMergeAdjacentReasoningItems(items){
  // Preserve the real event order. Reasoning deltas are already merged into
  // nativeReasoningSegments by their segment key; this layer must not glue
  // separate reasoning parts together just because they are adjacent after
  // sorting.
  return _activitySortTimelineItems(Array.isArray(items) ? items : []);
}

function _activityIsLegacyGroupedReasoningItem(item, nativeConnected=false){
  if(!item || typeof item !== 'object') return false;
  const stage = String(item.stage || item.kind || item.panelStage || item.panel_stage || '').trim().toLowerCase();
  const rawStage = String(item.rawStage || item.raw_stage || item.type || '').trim().toLowerCase();
  const key = String(item.key || item.id || '').trim().toLowerCase();
  const source = String(item.source || item.provider || '').trim().toLowerCase();
  const title = String(item.title || item.text || '').replace(/\s+/g, ' ').trim();
  const looksThink = stage === 'think' || rawStage === 'think' || key === 'native_reasoning' || key.startsWith('reasoning|') || /思考|推理|thinking|reasoning/i.test(`${title} ${rawStage}`);
  if(!looksThink) return false;
  if(source && _activityIsResponsesNativeReasoningSource(source)) return true;
  if(key === 'native_reasoning') return true;
  if(key.startsWith('native_reasoning_segment|')) return true;
  // 这些是旧 reasoning panel 的概括行，不是真实 ActivityEvent。
  if(/^(?:思考|思考中|已思考|推理|推理中|已完成|处理中|Thinking|Reasoning)$/i.test(title)) return true;
  if(nativeConnected && (stage === 'think' || rawStage === 'think')) return true;
  if(nativeConnected && looksThink && !String(item.tool || '').trim() && !Array.isArray(item.sourceItems) && !Array.isArray(item.source_items)) return true;
  return false;
}

function _activityNormalizeSnapshotItems(sessionId, snapshot, opts={}){
  const sid = _activityCurrentSessionId(sessionId);
  const rt = (sid && typeof ensureSessionRuntime === 'function') ? ensureSessionRuntime(sid) : null;
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const meta = _normalizePendingAssistantReasoningMeta(snap.reasoningMeta || {});
  const nativeConnected = !!(meta.nativeReasoningConnected || snap.nativeReasoningConnected || String(meta.nativeReasoningText || snap.nativeReasoningText || '').trim() || (Array.isArray(meta.nativeReasoningSegments) && meta.nativeReasoningSegments.length) || (Array.isArray(snap.nativeReasoningSegments) && snap.nativeReasoningSegments.length));
  const timeline = [];
  const push = (item)=>{ if(item && typeof item === 'object') timeline.push(item); };

  // Native reasoning is the only reasoning source allowed in the Activity panel.
  // Old reasoning[]/progress grouped rows are filtered below, so these rows keep
  // their true timestamps instead of being re-grouped into an artificial section.
  for(const item of _activityNormalizeNativeReasoningSegments(meta, snap, rt, opts || {})){
    push(item);
  }

  // Tool/search/sandbox/file events are the other event source. This keeps the
  // activity panel as a real run timeline instead of rebuilding independent blocks.
  const rawMeta = snap.reasoningMeta && typeof snap.reasoningMeta === 'object' ? snap.reasoningMeta : {};
  const activitySource = meta.activityEvents || snap.activityEvents || snap.activity_events || rawMeta.activityEvents || rawMeta.activity_events || [];
  const scopedActivitySource = (typeof _reasoningEventBelongsToSession === 'function')
    ? (Array.isArray(activitySource) ? activitySource.filter(item => _reasoningEventBelongsToSession(item, sid)) : activitySource)
    : activitySource;
  const activityEvents = (typeof _normalizeReasoningProgressEvents === 'function')
    ? _normalizeReasoningProgressEvents(scopedActivitySource, 80)
    : (Array.isArray(scopedActivitySource) ? scopedActivitySource : []);
  const hasCanonicalActivity = activityEvents.length > 0;
  const progressSource = hasCanonicalActivity ? [] : (meta.progressEvents || snap.progressEvents || snap.progress_events || rawMeta.progressEvents || rawMeta.progress_events || []);
  const scopedProgressSource = (typeof _reasoningEventBelongsToSession === 'function')
    ? (Array.isArray(progressSource) ? progressSource.filter(item => _reasoningEventBelongsToSession(item, sid)) : progressSource)
    : progressSource;
  const progressEvents = hasCanonicalActivity ? activityEvents : ((typeof _normalizeReasoningProgressEvents === 'function')
    ? _normalizeReasoningProgressEvents(scopedProgressSource, 80)
    : (Array.isArray(scopedProgressSource) ? scopedProgressSource : []));
  const webGroups = _activityBuildRealWebQueryGroups(meta, snap, progressEvents);
  const progressTimelineItems = [];
  for(const item of progressEvents){
    if(_activityIsLegacyGroupedReasoningItem(item, nativeConnected)) continue;
    progressTimelineItems.push({
      key:String(item.key || `${item.stage || 'progress'}|${item.title || ''}|${item.detail || ''}`).slice(0, 700),
      title:String(item.title || '').trim(),
      detail:String(item.detail || '').trim(),
      queries:_activitySanitizeQueriesForItem(item, Array.isArray(item.queries) ? item.queries.map(q => String(q || '').trim()).filter(Boolean) : []),
      stage:String(item.stage || 'answer') || 'answer',
      state:String(item.state || 'done') || 'done',
      ts:_activityNormalizeEventTs(item.ts || item.startedAt || item.started_at || item.updatedAt || item.updated_at, Date.now()),
      ...(Number(item.seq || 0) > 0 ? { seq:Number(item.seq || 0) } : {}),
      rawStage:String(item.rawStage || item.raw_stage || '').trim(),
      tool:String(item.tool || '').trim(),
      source:String(item.source || '').trim(),
      text:String(item.text || item.title || '').trim(),
      ...(item.activity_op ? { activity_op:String(item.activity_op) } : {}),
      ...(item.activityOp ? { activityOp:String(item.activityOp) } : {}),
      ...(item.action_type ? { action_type:String(item.action_type) } : {}),
      ...(item.actionType ? { actionType:String(item.actionType) } : {}),
      ...(item.operation_key ? { operation_key:String(item.operation_key) } : {}),
      ...(item.operationKey ? { operationKey:String(item.operationKey) } : {}),
      ...(item.debug_available !== undefined ? { debug_available:!!item.debug_available } : {}),
      ...(item.debugAvailable !== undefined ? { debugAvailable:!!item.debugAvailable } : {}),
      ...(item.show_debug !== undefined ? { show_debug:!!item.show_debug } : {}),
      ...(item.showDebug !== undefined ? { showDebug:!!item.showDebug } : {}),
      ...(item.commandLanguage ? { commandLanguage:String(item.commandLanguage) } : {}),
      ...(item.command_language ? { command_language:String(item.command_language) } : {}),
      ...(item.command ? { command:String(item.command) } : {}),
      ...(item.stdout ? { stdout:String(item.stdout) } : {}),
      ...(item.stderr ? { stderr:String(item.stderr) } : {}),
      ...(item.exitCode !== undefined && item.exitCode !== null ? { exitCode:item.exitCode } : {}),
      ...(item.exit_code !== undefined && item.exit_code !== null ? { exit_code:item.exit_code } : {}),
      ...(item.fileNames || item.file_names || item.filenames || item.files_preview || item.file_preview ? { fileNames:item.fileNames || item.file_names || item.filenames || item.files_preview || item.file_preview } : {}),
      ...(item.fileNameTotal || item.file_name_total || item.fileNameCount || item.file_name_count || item.fileCount || item.file_count || item.total_count ? { fileNameTotal:item.fileNameTotal || item.file_name_total || item.fileNameCount || item.file_name_count || item.fileCount || item.file_count || item.total_count } : {}),
      ...(item.current_file ? { current_file:item.current_file } : {}),
      ...(item.currentFile ? { currentFile:item.currentFile } : {}),
      ...(item.files_preview ? { files_preview:item.files_preview } : {}),
      ...(item.target_filename ? { target_filename:item.target_filename } : {}),
      ...(item.filename ? { filename:item.filename } : {}),
      ...(item.path ? { path:item.path } : {}),
      ...(item.paths ? { paths:item.paths } : {}),
      ...(item.files ? { files:item.files } : {}),
      ...(item.imageItems || item.image_items ? { imageItems:item.imageItems || item.image_items } : {}),
      ...(item.imageCount || item.image_count ? { imageCount:item.imageCount || item.image_count } : {}),
      ...(item.documentVisualItems || item.document_visual_items ? { documentVisualItems:item.documentVisualItems || item.document_visual_items } : {}),
      ...(item.documentPageCount || item.document_page_count ? { documentPageCount:item.documentPageCount || item.document_page_count } : {}),
      ...(item.documentVisualDeferred !== undefined || item.document_visual_deferred !== undefined ? { documentVisualDeferred:!!(item.documentVisualDeferred || item.document_visual_deferred) } : {}),
      resultCount:Number(item.resultCount || item.result_count || 0) || 0,
      ...(_activityNormalizeSourceItems(item.sourceItems || item.source_items || item.sources || item.searchResults || item.search_results || [], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT).length ? { sourceItems:_activityNormalizeSourceItems(item.sourceItems || item.source_items || item.sources || item.searchResults || item.search_results || [], WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT) } : {}),
    });
  }
  let preserveWebReadOrder = progressTimelineItems.some(item => _activityIsWebReadTimelineItem(item));
  const searchTimelineItems = _activityEnrichSearchItemsWithQueryGroups(progressTimelineItems, webGroups);
  for(const item of searchTimelineItems){
    push(item);
  }

  const metaPageCount = Math.max(
    Number(meta.pageCount || meta.page_count || 0) || 0,
    Number(snap.pageCount || snap.page_count || snap.pages || 0) || 0
  );
  const metaSourceCount = Math.max(
    Number(meta.sourceCount || meta.source_count || 0) || 0,
    Number(snap.sourceCount || snap.source_count || 0) || 0
  );
  const routeMode = String(meta.routeMode || meta.route_mode || snap.routeMode || snap.route_mode || '').trim();
  const useWebResearch = !!(meta.useWebResearch || meta.use_web_research || snap.useWebResearch || snap.use_web_research || routeMode === 'web_research');
  // Removed: synthetic meta page-read row. Page/search/read steps must come from
  // real ActivityEvent/progressEvents so the panel follows actual seq/ts order.

  const hasProgressKind = (kind)=>timeline.some(item => {
    const stage = String(item.stage || item.kind || '').toLowerCase();
    const rawStage = String(item.rawStage || item.raw_stage || '').toLowerCase();
    const tool = String(item.tool || '').toLowerCase();
    return stage === kind || rawStage.includes(kind) || tool.includes(kind);
  });

  // File progress fallback only applies when no unified progress event exists.
  const hasFileOrSandbox = hasProgressKind('file') || hasProgressKind('sandbox');
  if(!hasFileOrSandbox && typeof _normalizeReasoningFileProgressItems === 'function' && typeof _progressEventFromFileProgress === 'function'){
    const fileProgressItems = _normalizeReasoningFileProgressItems(meta.fileProgressItems || snap.fileProgressItems || snap.file_progress_items || [], 80);
    fileProgressItems.forEach(item => push(_progressEventFromFileProgress(item)));
  }

  // Removed: legacy reasoning[] fallback. It was the old grouped reasoning panel
  // source and could duplicate native reasoning. Empty real timeline now stays empty.

  const snapshotIsFinal = !!(opts.message || opts.finalSnapshot || !rt?.streaming);
  let items = timeline.map(item => {
    if(!item || typeof item !== 'object') return item;
    const s = String(item.state || '').toLowerCase();
    return snapshotIsFinal && s === 'active' ? { ...item, state:'done' } : item;
  });

  const allowRuntimeFallback = !!opts.allowRuntimeFallback;
  if(allowRuntimeFallback && rt?.streaming && !items.length){
    // Do not surface internal route/status text such as "已进入 Responses..." in
    // the user-facing inline activity.  When there is no canonical activity event
    // yet, the honest state is simply that the model is still thinking.
    const thinkingText = _activityT('activity.thinking_active', null, 'Thinking…');
    items.push({ key:'activity|thinking_wait', title:thinkingText, stage:'think', state:'active', ts:Date.now(), text:thinkingText, transient:true });
  }
  if(allowRuntimeFallback && rt?.streaming && String(rt.draftText || '').trim()){
    const hasActive = items.some(item => String(item?.state || '').toLowerCase() === 'active');
    const hasAnswer = items.some(item => /回答|回复|生成回答/.test(String(item?.title || item?.text || '')));
    if(!hasActive && !hasAnswer){
    const answeringText = _activityEventTitle('answer', 'active');
    items.push({ key:'activity|answering', title:answeringText, stage:'answer', state:'active', ts:Date.now() + 20, text:answeringText, transient:true });
    }
  }

  if(preserveWebReadOrder){
    return _activityNormalizeTimelinePreserveOrder(_activitySortTimelineItems(items));
  }

  items = _activityDedupeItems(items);
  items = _activityCompactFileIndexItems(items);
  items = _activityMergeAdjacentReasoningItems(items);
  items = _activityAttachSnapshotSources(items, snap);
  items = _activityCompactTimelineItems(items, { maxItems:80, final:snapshotIsFinal });
  return _activitySortTimelineItems(items).slice(-80);
}

function _activityInlineCleanCueText(value, maxLen=180){
  let s = String(value || '').replace(/\r\n?/g, '\n').trim();
  if(!s) return '';
  s = s
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*\n]{1,180}?)\*\*/g, '$1')
    .replace(/__([^_\n]{1,180}?)__/g, '$1')
    .replace(/`([^`\n]{1,180}?)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
  const internal = /已进入\s*Responses|原生流式\s*Agent|按需调用工具|route|capability|responses_native/i;
  if(!s || internal.test(s)) return '';
  return s.length > maxLen ? `${s.slice(0, Math.max(1, maxLen - 1)).trimEnd()}…` : s;
}

// Inline正文行不再取“最新活动标题”。
// 下面的播放队列直接消费真实 timeline：标题、原生推理句子、搜索 query、读取/工具事件。

function _activitySummaryContextFromSnapshot(sessionId, snapshot, opts={}){
  const sid = _activityCurrentSessionId(sessionId);
  const rt = (sid && typeof ensureSessionRuntime === 'function') ? ensureSessionRuntime(sid) : null;
  const meta = _normalizePendingAssistantReasoningMeta(snapshot?.reasoningMeta || {});
  const scopedStreaming = !!(rt?.streaming && !opts.message);
  const elapsed = _activityElapsedLabel(sid, rt, opts.message || null, snapshot);
  const artifactFilenames = (Array.isArray(meta.artifactFilenames) ? meta.artifactFilenames : (Array.isArray(snapshot?.artifactFilenames) ? snapshot.artifactFilenames : []))
    .map(x => String(x || '').trim()).filter(Boolean);
  const fileProgressItems = _normalizeReasoningFileProgressItems(meta.fileProgressItems || snapshot?.fileProgressItems || [], 16);
  const activityEvents = (typeof _normalizeReasoningProgressEvents === 'function')
    ? _normalizeReasoningProgressEvents(meta.activityEvents || snapshot?.activityEvents || snapshot?.activity_events || [], 80)
    : [];
  const hasSandboxActivity = activityEvents.some(item => {
    const stage = String(item?.stage || item?.kind || '').toLowerCase();
    const tool = String(item?.tool || '').toLowerCase();
    const rawStage = String(item?.rawStage || item?.raw_stage || '').toLowerCase();
    return stage === 'sandbox' || tool === 'sandbox_run' || rawStage.includes('sandbox');
  });
  return {
    streaming:scopedStreaming,
    elapsed,
    sourceCount:Math.max(Number(meta.sourceCount || 0) || 0, Number(snapshot?.sourceCount || 0) || 0),
    resultCount:Math.max(Number(meta.resultCount || 0) || 0, Number(snapshot?.resultCount || 0) || 0),
    kbResultCount:Math.max(Number(meta.kbResultCount || 0) || 0, Number(snapshot?.kbResultCount || 0) || 0),
    artifactCount:artifactFilenames.length,
    sandbox:hasSandboxActivity || fileProgressItems.some(item => _isSandboxFileProgressItem(item)),
  };
}

function getActivityTriggerSummaryForSnapshot(sessionId, opts={}, snapshotArg=null){
  // Compatibility for older callers only. The inline正文行 no longer uses a
  // latest-headline model; it is driven by getActivityInlinePlaybackForSnapshot().
  const sid = _activityCurrentSessionId(sessionId);
  const snapshot = snapshotArg && typeof snapshotArg === 'object' ? snapshotArg : _composeReasoningPanelSnapshot(sid, opts || {});
  const items = _activityNormalizeSnapshotItems(sid, snapshot, { ...(opts || {}), allowRuntimeFallback:!!opts?.allowRuntimeFallback });
  const context = _activitySummaryContextFromSnapshot(sid, snapshot, opts || {});
  const active = !!context.streaming || items.some(item => String(item?.state || '').toLowerCase() === 'active');
  return { sid, snapshot, items, headline:{ title:active ? _activityT('activity.thinking_active', null, 'Thinking…') : _activityT('activity.completed', null, 'Completed'), state:active ? 'active' : 'done', bits:[], item:null }, context };
}


function _activityInlineUnitKeyText(text){
  return String(text || '').replace(/\s+/g, ' ').trim().slice(0, 90);
}

function _activityInlinePushUnit(out, basisKey, text, kind='activity', state='done', extra={}){
  if(!Array.isArray(out)) return;
  const clean = _activityInlineCleanCueText(text, Number(extra.maxLen || 180) || 180);
  if(!clean) return;
  const prev = out.length ? out[out.length - 1] : null;
  if(prev && prev.text === clean && prev.kind === kind) return;
  const base = String(basisKey || `unit|${out.length}`);
  out.push({
    key:_activityPanelStableVisualKey(base, kind, out.length, _activityInlineUnitKeyText(clean)),
    text:clean,
    kind:String(kind || 'activity'),
    state:String(state || 'done'),
    ts:Number(extra.ts || 0) || 0,
    holdMs:Number(extra.holdMs || 0) || 0,
    stickyActive:!!extra.stickyActive,
  });
}

function _activityInlineSearchHostsFromItem(item, limit=4){
  const max = Math.max(1, Math.min(Number(limit || 4) || 4, 6));
  const rawItems = item?.sourceItems || item?.source_items || item?.sources || item?.searchResults || item?.search_results || [];
  const normalized = _activityNormalizeSourceItems(rawItems, Math.max(max * 3, 12));
  const out = [];
  const seen = new Set();
  for(const src of normalized){
    const host = String(src?.host || _activitySourceHost(src?.url || '') || '').trim().replace(/^www\./i, '');
    const title = _activityInlineCleanCueText(src?.title || '', 90);
    const value = host || title;
    if(!value) continue;
    const key = String(host || value).toLowerCase();
    if(!key || seen.has(key)) continue;
    seen.add(key);
    out.push(value);
    if(out.length >= max) break;
  }
  return out;
}

function _activityInlineEnglishBoundaryLooksAbbrev(leftText){
  const left = String(leftText || '').trim();
  if(!left) return false;
  const tail = left.slice(-32);
  if(/(?:^|\s)(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|No|Nos|Fig|Figs|Eq|Eqs|Dept|Inc|Ltd|Co|Corp|vs|etc)\.$/i.test(tail)) return true;
  if(/(?:^|\s)(?:e\.g|i\.e|a\.m|p\.m)\.$/i.test(tail)) return true;
  if(/(?:^|\s)(?:[A-Z]\.){2,}$/i.test(tail)) return true;
  return false;
}

function _activityInlineSentenceParts(clean, opts={}){
  const text = String(clean || '').replace(/\s+/g, ' ').trim();
  if(!text) return [];
  const includeIncomplete = opts.includeIncomplete !== false;
  const out = [];
  let start = 0;
  const len = text.length;
  const isCloser = (ch)=>/[\"'”’）)】\]}>》」』]/.test(ch || '');
  for(let i = 0; i < len; i += 1){
    const ch = text[i];
    let boundary = false;
    if(/[。！？!?]/.test(ch)){
      boundary = (ch === '?' || ch === '!') ? !_activityPlaybackPunctuationStaysInsideUrlToken(text, i) : true;
    }else if(ch === '.'){
      boundary = _activityPlaybackDotIsSentenceBoundary(text, i, isCloser);
    }
    if(!boundary) continue;
    let end = i + 1;
    while(end < len && isCloser(text[end])) end += 1;
    const part = text.slice(start, end).replace(/\s+/g, ' ').trim();
    if(part) out.push(part);
    start = end;
    while(start < len && /\s/.test(text[start])) start += 1;
    i = Math.max(i, start - 1);
  }
  const tail = text.slice(start).replace(/\s+/g, ' ').trim();
  if(tail && includeIncomplete) out.push(tail);
  return out;
}

function _activityInlineSplitLongSentence(part, maxLen){
  let text = String(part || '').replace(/\s+/g, ' ').trim();
  if(!text) return [];
  if(text.length <= maxLen) return [text];
  const out = [];
  while(text.length > maxLen){
    const slice = text.slice(0, maxLen);
    const cut = Math.max(
      slice.lastIndexOf('，'), slice.lastIndexOf(','),
      slice.lastIndexOf(';'), slice.lastIndexOf('；'),
      slice.lastIndexOf(': '), slice.lastIndexOf(' ')
    );
    const n = cut > Math.min(80, Math.floor(maxLen * 0.55)) ? cut + 1 : maxLen;
    const head = text.slice(0, n).trim();
    if(head) out.push(head);
    text = text.slice(n).trim();
  }
  if(text) out.push(text);
  return out;
}

function _activityInlineSplitCueSentences(text, opts={}){
  const maxUnits = Math.max(1, Math.min(Number(opts.maxUnits || 12) || 12, 60));
  const maxLen = Math.max(40, Math.min(Number(opts.maxLen || 180) || 180, Number(opts.allowLong ? 680 : 320)));
  const splitLong = opts.splitLong !== false;
  let clean = _activityInlineCleanCueText(text, Math.max(1200, maxLen * maxUnits));
  if(!clean) return [];
  clean = clean
    .replace(/(^|\s)[-*+]\s+/g, ' ')
    .replace(/(^|\s)\d{1,3}[.)]\s+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const rawParts = _activityInlineSentenceParts(clean, { includeIncomplete: opts.includeIncomplete !== false });
  const out = [];
  rawParts.forEach((raw, partIndex)=>{
    let part = String(raw || '').replace(/\s+/g, ' ').trim();
    if(!part) return;
    // Responses native reasoning can arrive as arbitrary deltas. If a leftover
    // lower-case tail such as "task." leaks through as the first chunk, do not
    // play it as an independent sentence in the inline row. The full accumulated
    // native text path below supplies the complete sentence instead.
    if(opts.dropLeadingFragment && partIndex === 0 && /^[a-z][a-z'’’-]{0,24}[.!?。！？]?$/.test(part) && rawParts.length > 1){
      return;
    }
    const pieces = splitLong ? _activityInlineSplitLongSentence(part, maxLen) : [part];
    for(const piece of pieces){
      if(piece) out.push(piece);
      if(out.length >= maxUnits) break;
    }
  });
  return out.slice(0, maxUnits);
}

function _activityInlineNativeReasoningUnitsFromSnapshot(sessionId, snapshot, context){
  const sid = _activityCurrentSessionId(sessionId);
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const rawMeta = snap.reasoningMeta && typeof snap.reasoningMeta === 'object' ? snap.reasoningMeta : {};
  const meta = (typeof _normalizePendingAssistantReasoningMeta === 'function')
    ? _normalizePendingAssistantReasoningMeta(rawMeta)
    : rawMeta;
  const nativeText = String(
    meta.nativeReasoningText
    || rawMeta.nativeReasoningText
    || rawMeta.native_reasoning_text
    || snap.nativeReasoningText
    || snap.native_reasoning_text
    || ''
  ).replace(/\r\n?/g, '\n').trim();
  const nativeConnected = !!(
    meta.nativeReasoningConnected
    || rawMeta.nativeReasoningConnected
    || rawMeta.native_reasoning_connected
    || snap.nativeReasoningConnected
    || snap.native_reasoning_connected
    || nativeText
  );
  if(!nativeConnected || !nativeText) return [];

  const explicitDone = !!(
    meta.nativeReasoningDone
    || rawMeta.nativeReasoningDone
    || rawMeta.native_reasoning_done
    || snap.nativeReasoningDone
    || snap.native_reasoning_done
  );
  const finalDone = explicitDone || !context?.streaming;
  const startedAt = Number(
    meta.nativeReasoningStartAt
    || rawMeta.nativeReasoningStartAt
    || rawMeta.native_reasoning_start_at
    || snap.nativeReasoningStartAt
    || snap.native_reasoning_start_at
    || 0
  ) || 0;
  const source = String(
    meta.nativeReasoningSource
    || rawMeta.nativeReasoningSource
    || rawMeta.native_reasoning_source
    || snap.nativeReasoningSource
    || snap.native_reasoning_source
    || 'native_field'
  ).trim().slice(0, 40) || 'native_field';

  // 正文播放只消费“完整原生推理文本”的句子队列。
  // nativeReasoningSegments 仍给右侧活动面板做真实时间线；这里故意不再按 segment 播，
  // 避免一句话跨 segment 时被拆成半句。
  const parsed = _activityExtractNativeReasoningTitleAndBody(nativeText);
  const body = String(parsed.body || nativeText || '').trim();
  const sentences = _activityInlineSplitCueSentences(body, {
    maxUnits:48,
    maxLen:520,
    allowLong:true,
    splitLong:false,
    includeIncomplete:finalDone,
  });
  const out = [];
  const baseKey = _activityPanelStableVisualKey('native_inline_sentence', sid || 'session', startedAt || '', source);
  sentences.forEach((sentence, idx)=>{
    const clean = _activityInlineCleanCueText(sentence, 520);
    if(!clean || _activityInlinePlaybackUnitIsCompletionNoise(clean)) return;
    _activityInlinePushUnit(out, _activityPanelStableVisualKey(baseKey, 'sentence', idx), clean, 'think', finalDone ? 'done' : 'active', {
      ts: startedAt ? startedAt + idx : idx,
      maxLen:520,
      holdMs: Math.max(900, Math.min(3200, clean.length * 20)),
    });
  });
  return out;
}

function _activityInlineUnitsFromItem(item, itemIndex=0){
  const out = [];
  if(!item || typeof item !== 'object' || _activityIsGenericCompletionItem(item)) return out;
  const kind = String(item.kind || item.stage || 'activity').toLowerCase();
  const state = String(item.state || 'done').toLowerCase() || 'done';
  const baseKey = _activityPanelStableVisualKey('inline', item.key || item.id || item.seq || item.ts || itemIndex, kind);
  const ts = Number(item.ts || 0) || 0;

  if(kind === 'think'){
    const raw = _activityRawText(item.detail || item.text || '');
    const parsed = _activityExtractNativeReasoningTitleAndBody(raw);
    const itemTitle = _activityInlineCleanCueText(item.title || parsed.title || '', 140);
    const title = (_activityNativeReasoningTitleShouldBreak(itemTitle) ? itemTitle : '') || parsed.title;
    if(title) _activityInlinePushUnit(out, baseKey, title, 'think-title', state, { ts, maxLen:150, holdMs:1250 });
    const body = parsed.body || raw;
    const sentences = _activityInlineSplitCueSentences(body, { maxUnits:18, maxLen:190, includeIncomplete:state !== 'active' });
    sentences.forEach((sentence, idx)=>{
      if(title && _activityInlineCleanCueText(sentence, 190) === _activityInlineCleanCueText(title, 190)) return;
      _activityInlinePushUnit(out, _activityPanelStableVisualKey(baseKey, 'sentence', idx), sentence, 'think', state, { ts, maxLen:190 });
    });
    if(!out.length && title) _activityInlinePushUnit(out, baseKey, title, 'think-title', state, { ts });
    return out;
  }

  if(kind === 'search'){
    const queries = _activityShouldRenderQueryChips(item)
      ? item.queries.map(q => _activityInlineCleanCueText(q, 190)).filter(Boolean)
      : [];
    if(queries.length){
      queries.forEach((query, idx)=>{
        const text = _activityT('activity.search_query', {query}, `Search: ${query}`);
        _activityInlinePushUnit(out, _activityPanelStableVisualKey(baseKey, 'query', idx), text, 'search-query', state, { ts, maxLen:210, holdMs:1050 });
      });
    }else{
      const title = _activityInlineCleanCueText(_activityDisplayTitleForItem(item, item.title || item.text || _activityEventTitle('web_search', 'done')), 180);
      if(title) _activityInlinePushUnit(out, baseKey, title, 'search-query', state, { ts, maxLen:180, holdMs:1050 });
    }

    // Official-like inline playback also surfaces a few real search result sites.
    // Keep this small: the full result list still belongs in the activity panel.
    const hosts = _activityInlineSearchHostsFromItem(item, 4);
    hosts.forEach((host, idx)=>{
      _activityInlinePushUnit(
        out,
        _activityPanelStableVisualKey(baseKey, 'site', idx, host),
        _activityT('activity.searching_site', {site:host}, `Searching ${host}`),
        'search-site',
        state,
        { ts, maxLen:120, holdMs:820 }
      );
    });
    return out;
  }

  const isStreamRetry = (typeof _activityEventIsStreamRetry === 'function')
    ? _activityEventIsStreamRetry(item)
    : String(item.key || '').toLowerCase().startsWith('stream_retry|');
  const title = _activityInlineCleanCueText(_activityDisplayTitleForItem(item, item.title || item.text || ''), 180);
  if(title) _activityInlinePushUnit(out, baseKey, title, isStreamRetry ? 'stream-retry' : kind, state, { ts, maxLen:180, stickyActive:isStreamRetry });
  const detail = _activityInlineCleanCueText(item.detail || '', 900);
  if(detail && detail !== title){
    _activityInlineSplitCueSentences(detail, { maxUnits:4, maxLen:180 }).forEach((sentence, idx)=>{
      if(sentence && sentence !== title) _activityInlinePushUnit(out, _activityPanelStableVisualKey(baseKey, 'detail', idx), sentence, kind, state, { ts, maxLen:180 });
    });
  }
  return out;
}

function _activityInlinePlaybackUnitsFromItems(items, snapshot=null, context=null, sessionId=''){
  const rows = Array.isArray(items) ? items : [];
  const units = [];
  const nativeUnits = _activityInlineNativeReasoningUnitsFromSnapshot(sessionId, snapshot || {}, context || {});
  let nativeInserted = false;
  rows.forEach((item, index)=>{
    if(_activityLooksNativeReasoningItem(item)){
      if(!nativeInserted){
        nativeUnits.forEach(unit => units.push(unit));
        nativeInserted = true;
      }
      return;
    }
    _activityInlineUnitsFromItem(item, index).forEach(unit => units.push(unit));
  });
  if(nativeUnits.length && !nativeInserted){
    units.unshift(...nativeUnits);
  }
  return units;
}

function getActivityInlinePlaybackForSnapshot(sessionId, opts={}, snapshotArg=null){
  const sid = _activityCurrentSessionId(sessionId);
  const snapshot = snapshotArg && typeof snapshotArg === 'object' ? snapshotArg : _composeReasoningPanelSnapshot(sid, opts || {});
  const items = _activityNormalizeSnapshotItems(sid, snapshot, { ...(opts || {}), allowRuntimeFallback:!!opts?.allowRuntimeFallback });
  const context = _activitySummaryContextFromSnapshot(sid, snapshot, opts || {});
  const units = _activityInlinePlaybackUnitsFromItems(items, snapshot, context, sid);
  const active = !!context.streaming || items.some(item => String(item?.state || '').toLowerCase() === 'active');
  const hasRealActivity = _activityHasRealPanelItems(items);
  const meta = snapshot?.reasoningMeta && typeof snapshot.reasoningMeta === 'object' ? snapshot.reasoningMeta : {};
  const rt = (sid && typeof ensureSessionRuntime === 'function') ? ensureSessionRuntime(sid) : null;
  const runSeed = Number(meta.nativeReasoningStartAt || meta.native_reasoning_start_at || snapshot?.nativeReasoningStartAt || snapshot?.native_reasoning_start_at || rt?.rtStartAt || 0) || '';
  const runKey = _activityPanelStableVisualKey('inline_sentence_player', sid || 'session', runSeed || 'no_start');
  const doneText = context.elapsed
    ? (window.AperviaI18n?.t('activity.completed_elapsed', {elapsed:context.elapsed}) || `Completed · ${context.elapsed}`)
    : (window.AperviaI18n?.t('activity.completed') || 'Completed');
  return { sid, snapshot, items, context, units, active, doneText, runKey, hasRealActivity, finalStatic:!context.streaming };
}

function _activitySnapshotForSession(sessionId){
  const sid = _activityCurrentSessionId(sessionId);
  const session = (sid && typeof getSessionById === 'function') ? getSessionById(sid) : null;
  const rt = (sid && typeof ensureSessionRuntime === 'function') ? ensureSessionRuntime(sid) : null;
  const targetMessage = (_activityPanelOpenSessionId === sid && _activityPanelTargetMessage && typeof _activityPanelTargetMessage === 'object') ? _activityPanelTargetMessage : null;
  const targetSnapshot = (_activityPanelOpenSessionId === sid && _activityPanelTargetSnapshot && typeof _activityPanelTargetSnapshot === 'object') ? _activityPanelTargetSnapshot : null;
  const hasRuntimeDraft = (typeof sessionRuntimeHasVisibleDraftContent === 'function') ? sessionRuntimeHasVisibleDraftContent(rt) : false;
  const useRuntime = !!(rt && !targetMessage && !targetSnapshot && (rt.streaming || hasRuntimeDraft));
  const lastAssistant = targetMessage || _activityLastAssistantMessage(session);
  let snapshot = null;
  try{
    snapshot = targetSnapshot || (useRuntime
      ? _composeReasoningPanelSnapshot(sid, {})
      : _composeReasoningPanelSnapshot('', { message:lastAssistant }));
  }catch(_){ snapshot = targetSnapshot || null; }
  const items = _activityNormalizeSnapshotItems(sid, snapshot || {}, { message:useRuntime ? null : lastAssistant, finalSnapshot:!!targetSnapshot, allowRuntimeFallback:useRuntime });
  return { sid, session, rt, message:lastAssistant, snapshot, items };
}

function _activityKindSectionTitle(kind){
  const key = String(kind || '').trim().toLowerCase();
  const fallback = {think:'Thinking',search:'Search',file:'Files',sandbox:'Code execution',mcp:'MCP',tool:'Tools',answer:'Answer'}[key] || 'Activity';
  return _activityT(`activity.kind.${key || 'activity'}`, null, fallback);
}

function _activityRenderTextBlock(parent, text, mode='auto'){
  const raw = String(text || '').replace(/\r\n?/g, '\n').trim();
  if(!raw) return;
  const modeKey = String(mode || '').toLowerCase();
  if(modeKey === 'markdown' || modeKey === 'reasoning'){
    const markdownSource = _activityReasoningMarkdownSource(raw);
    const detail = document.createElement('div');
    detail.className = 'activity-panel-reasoning-markdown';
    if(typeof renderTextSectionHtml === 'function'){
      detail.innerHTML = renderTextSectionHtml(markdownSource, { inlineSourcePills:false });
    }else if(typeof renderInlineRich === 'function'){
      detail.innerHTML = renderInlineRich(markdownSource);
    }else{
      detail.textContent = markdownSource;
    }
    parent.appendChild(detail);
    try{
      if(typeof enhanceRenderedMarkdown === 'function') enhanceRenderedMarkdown(detail);
      else if(typeof enhanceAssistantMarkdown === 'function') enhanceAssistantMarkdown(detail);
      else if(typeof attachCodeBlockEnhancements === 'function') attachCodeBlockEnhancements(detail);
    }catch(_){ }
    return;
  }
  if(modeKey === 'plain'){
    const detail = document.createElement('div');
    detail.className = 'activity-panel-native-text';
    detail.textContent = raw;
    parent.appendChild(detail);
    return;
  }
  const lines = raw.split('\n').map(x => x.trim()).filter(Boolean).slice(0, 12);
  if(lines.length > 1){
    const ul = document.createElement('ul');
    ul.className = 'activity-panel-bullets';
    for(const line of lines){
      const li = document.createElement('li');
      li.textContent = line.replace(/^[-*•]\s*/, '');
      ul.appendChild(li);
    }
    parent.appendChild(ul);
  }else{
    const detail = document.createElement('div');
    detail.className = 'activity-panel-item-detail';
    detail.textContent = raw;
    parent.appendChild(detail);
  }
}


function _activityRenderSourceChips(parent, items, opts={}){
  const sources = _activityNormalizeSourceItems(items, WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT);
  if(!sources.length) return;
  const row = document.createElement('div');
  row.className = 'activity-panel-source-row';
  const baseKey = String(opts?.key || 'sources').slice(0, 520);
  const markEnter = typeof opts?.markEnter === 'function' ? opts.markEnter : null;
  const totalCount = Math.max(Number(opts?.totalCount || opts?.sourceTotal || 0) || 0, sources.length);
  const defaultLimit = Math.max(1, Math.min(Number(opts?.visibleLimit || 4) || 4, 4));
  const render = (expanded=false, renderOpts={})=>{
    const fromToggle = !!renderOpts?.fromToggle;
    const frag = document.createDocumentFragment();
    const visible = expanded ? sources : sources.slice(0, defaultLimit);
    for(const [sourceIndex, src] of visible.entries()){
      const chip = src.url ? document.createElement('a') : document.createElement('span');
      chip.className = 'activity-panel-source-chip';
      if(fromToggle && expanded && sourceIndex >= defaultLimit){
        chip.classList.add('activity-panel-source-expand-enter');
        chip.style.setProperty('--activity-source-expand-delay', `${Math.min(180, (sourceIndex - defaultLimit) * 34)}ms`);
      }
      if(src.url){
        chip.href = src.url;
        chip.target = '_blank';
        chip.rel = 'noopener noreferrer';
      }
      const favicon = src.favicon || _activityFallbackFaviconUrl(src);
      if(favicon){
        const img = document.createElement('img');
        img.className = 'activity-panel-source-icon';
        img.alt = '';
        img.loading = 'lazy';
        img.decoding = 'async';
        img.referrerPolicy = 'no-referrer';
        img.onerror = ()=>{ try{ img.remove(); }catch(_){ img.style.display = 'none'; } };
        _activityScheduleSourceIcon(img, favicon);
        chip.appendChild(img);
      }
      const label = document.createElement('span');
      label.className = 'activity-panel-source-label';
      label.textContent = src.host || src.title || src.url;
      chip.appendChild(label);
      if(markEnter){
        markEnter(chip, _activityPanelStableVisualKey(baseKey, 'source', sourceIndex, src.url || src.host || src.title || ''), { stepMs:45, maxDelayMs:280 });
      }
      frag.appendChild(chip);
    }
    if(sources.length > defaultLimit){
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'activity-panel-source-chip activity-panel-source-more';
      const remaining = Math.max(0, sources.length - visible.length);
      more.textContent = expanded
        ? _activityT('activity.show_less', null, 'Show less')
        : _activityT('activity.show_more_count', {count:remaining}, `Show ${remaining} more`);
      more.addEventListener('click', (ev)=>{
        ev.preventDefault();
        ev.stopPropagation();
        render(!expanded, { fromToggle:true });
      });
      frag.appendChild(more);
    }
    row.replaceChildren(frag);
  };
  render(false);
  parent.appendChild(row);
}

function _activityRenderFileChips(parent, names, totalCount){
  const collected = _activityCollectFileNames(names, 120);
  const files = collected.names;
  const total = Math.max(Number(totalCount || 0) || 0, collected.total, files.length);
  if(!files.length && total <= 0) return;
  const row = document.createElement('div');
  row.className = 'activity-panel-file-row';
  let expanded = false;
  const visibleLimit = total > 12 ? 6 : 3;

  const appendChip = (name, extraClass)=>{
    const chip = document.createElement('span');
    chip.className = `activity-panel-file-chip${extraClass ? ' ' + extraClass : ''}`;
    chip.textContent = name;
    chip.title = name;
    row.appendChild(chip);
  };

  const appendToggle = (label, title, nextExpanded)=>{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'activity-panel-file-chip activity-panel-file-more';
    btn.textContent = label;
    btn.title = title || '';
    btn.style.cursor = 'pointer';
    btn.style.font = 'inherit';
    btn.addEventListener('click', (ev)=>{
      ev.preventDefault();
      ev.stopPropagation();
      expanded = !!nextExpanded;
      render();
    });
    row.appendChild(btn);
  };

  const render = ()=>{
    row.textContent = '';
    const visible = expanded ? files : files.slice(0, visibleLimit);
    for(const name of visible){
      appendChip(name);
    }
    const hiddenNamedCount = Math.max(0, files.length - visible.length);
    const hiddenTotalCount = Math.max(0, total - visible.length);
    if(!expanded && hiddenTotalCount > 0){
      const canExpand = files.length > visible.length;
      if(canExpand){
        appendToggle(
          _activityT('activity.more_count', {count:hiddenTotalCount}, `${hiddenTotalCount} more`),
          _activityT('activity.expand_file_names', null, 'Show remaining file names'),
          true,
        );
      }else{
        appendChip(_activityT('activity.more_count', {count:hiddenTotalCount}, `${hiddenTotalCount} more`), 'activity-panel-file-more');
      }
      return;
    }
    if(expanded){
      const notListed = Math.max(0, total - files.length);
      if(notListed > 0){
        appendChip(_activityT('activity.unlisted_count', {count:notListed}, `${notListed} more not listed`), 'activity-panel-file-more');
      }
      if(files.length > visibleLimit || hiddenNamedCount > 0 || notListed > 0){
        appendToggle(_activityT('activity.collapse', null, 'Collapse'), _activityT('activity.collapse_file_list', null, 'Collapse file list'), false);
      }
    }
  };

  render();
  parent.appendChild(row);
}

function _activityRenderImagePreviews(parent, items, totalCount=0, sessionId=''){
  const images = _activityResolveImagePreviewItems(sessionId, items, 8);
  const total = Math.max(Number(totalCount || 0) || 0, images.length);
  if(!images.length) return;
  const grid = document.createElement('div');
  grid.className = `activity-panel-image-grid${images.length === 1 ? ' activity-panel-image-grid-single' : ''}`;
  images.forEach((item, index)=>{
    const preview = document.createElement('div');
    preview.className = 'activity-panel-image-preview';
    const img = document.createElement('img');
    img.src = item.displayUrl;
    img.alt = item.alt || _activityT('activity.analyzed_image', null, 'Analyzed image');
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', ()=>{
      preview.classList.add('activity-panel-image-preview-failed');
    }, { once:true });
    preview.appendChild(img);
    grid.appendChild(preview);
  });
  if(total > images.length){
    const more = document.createElement('span');
    more.className = 'activity-panel-image-more';
    more.textContent = _activityT('activity.more_images', {count:total - images.length}, `${total - images.length} more images`);
    grid.appendChild(more);
  }
  parent.appendChild(grid);
}

function _activityRenderDocumentVisualPreviews(parent, items, totalCount=0){
  const pages = _activityNormalizeDocumentVisualItems(items, 12);
  const total = Math.max(Number(totalCount || 0) || 0, pages.length);
  if(!pages.length) return;
  const grid = document.createElement('div');
  grid.className = `activity-panel-image-grid activity-panel-document-grid${pages.length === 1 ? ' activity-panel-image-grid-single' : ''}`;
  pages.forEach((item, index)=>{
    const pageNumber = Math.max(Number(item.pageNumber || 0) || 0, index + 1);
    const pageLabel = item.pageLabel || _activityT('activity.document_page', {count:pageNumber}, `Page ${pageNumber}`);
    const preview = document.createElement('div');
    preview.className = 'activity-panel-image-preview activity-panel-document-preview';
    const img = document.createElement('img');
    img.src = item.previewUrl;
    img.alt = pageLabel;
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'same-origin';
    img.addEventListener('error', ()=>{
      preview.classList.add('activity-panel-image-preview-failed');
    }, { once:true });
    const label = document.createElement('span');
    label.className = 'activity-panel-document-page-label';
    label.textContent = pageLabel;
    preview.appendChild(img);
    preview.appendChild(label);
    grid.appendChild(preview);
  });
  if(total > pages.length){
    const more = document.createElement('span');
    more.className = 'activity-panel-image-more';
    more.textContent = _activityT('activity.more_document_pages', {count:total - pages.length}, `${total - pages.length} more document pages`);
    grid.appendChild(more);
  }
  parent.appendChild(grid);
}

function _activityRenderCollapsedDetails(parent, rows){
  const list = Array.isArray(rows) ? rows.filter(Boolean) : [];
  if(!list.length) return;
  const details = document.createElement('details');
  details.className = 'activity-panel-mini-details';
  const summary = document.createElement('summary');
  summary.textContent = _activityT('activity.view_details_count', {count:list.length}, `View ${list.length} details`);
  details.appendChild(summary);
  const ul = document.createElement('ul');
  ul.className = 'activity-panel-mini-list';
  for(const row of list.slice(0, 20)){
    const li = document.createElement('li');
    const title = _activityCleanText(row.title || _activityT('activity.file_action', null, 'File action'), 80);
    const names = _activityNormalizeFileNames(row.fileNames || [], 4);
    const detail = _activityCleanText(row.detail || '', 120);
    const nameText = names.length ? `: ${names.join(', ')}` : '';
    li.textContent = detail ? `${title}${nameText} | ${detail}` : `${title}${nameText}`;
    ul.appendChild(li);
  }
  if(list.length > 20){
    const li = document.createElement('li');
    li.textContent = _activityT('activity.omitted_count', {count:list.length - 20}, `${list.length - 20} more omitted`);
    ul.appendChild(li);
  }
  details.appendChild(ul);
  parent.appendChild(details);
}

function _activityCopyText(text){
  const raw = String(text == null ? '' : text);
  if(!raw) return Promise.resolve(false);
  try{
    if(navigator.clipboard && window.isSecureContext){
      return navigator.clipboard.writeText(raw).then(()=>true).catch(()=>false);
    }
  }catch(_){ }
  return new Promise(resolve=>{
    try{
      const ta = document.createElement('textarea');
      ta.value = raw;
      ta.setAttribute('readonly', 'readonly');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      ta.style.top = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      resolve(!!ok);
    }catch(_){ resolve(false); }
  });
}

function _activityRenderCodeBlock(parent, label, text, language='', opts={}){
  const raw = _activityDisplayCodeText(text);
  if(!raw) return;
  const box = document.createElement('div');
  const extraClass = String(opts?.extraClass || '').trim();
  box.className = ['activity-panel-code-block', 'activity-panel-code-block-direct', extraClass].filter(Boolean).join(' ');
  const head = document.createElement('div');
  head.className = 'activity-panel-code-head';
  const title = document.createElement('span');
  title.className = 'activity-panel-code-title';
  if(extraClass && String(extraClass).includes('activity-panel-sandbox-command-card')){
    const icon = document.createElement('span');
    icon.className = 'activity-panel-inline-code-icon';
    icon.textContent = '‹›';
    title.appendChild(icon);
    const labelNode = document.createElement('span');
    labelNode.textContent = label || 'Python';
    title.appendChild(labelNode);
  }else{
    title.textContent = label || _activityT('activity.run_details', null, 'Run details');
  }
  head.appendChild(title);
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'icon-btn bubble-copy activity-panel-code-copy';
  copy.textContent = _activityT('activity.copy', null, 'Copy');
  if(typeof decorateBubbleActionButton === 'function'){
    decorateBubbleActionButton(copy, 'copy', _activityT('activity.copy', null, 'Copy'));
  }else{
    copy.setAttribute('aria-label', _activityT('activity.copy', null, 'Copy'));
    copy.title = _activityT('activity.copy', null, 'Copy');
  }
  copy.addEventListener('click', async (ev)=>{
    ev.preventDefault();
    ev.stopPropagation();
    const ok = (typeof copyText === 'function') ? (copyText(raw), true) : await _activityCopyText(raw);
    if(typeof flashButtonCopied === 'function'){
      flashButtonCopied(copy, ok ? _activityT('activity.copied', null, 'Copied') : _activityT('activity.copy_failed', null, 'Copy failed'));
    }else{
      const old = copy.textContent || _activityT('activity.copy', null, 'Copy');
      copy.textContent = ok ? _activityT('activity.copied', null, 'Copied') : _activityT('activity.copy_failed', null, 'Copy failed');
      try{ clearTimeout(copy._activityResetTimer); }catch(_){ }
      copy._activityResetTimer = setTimeout(()=>{ copy.textContent = old; }, 900);
    }
  });
  head.appendChild(copy);
  const scroll = document.createElement('div');
  scroll.className = 'activity-panel-code-scroll';
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  if(language) code.className = `language-${language}`;
  const shouldHighlight = extraClass.includes('activity-panel-sandbox-command-card')
    && typeof highlightCode === 'function';
  if(shouldHighlight){
    code.innerHTML = highlightCode(raw, language);
  }else{
    code.textContent = raw;
  }
  pre.appendChild(code);
  scroll.appendChild(pre);
  box.appendChild(head);
  box.appendChild(scroll);
  parent.appendChild(box);
}

function _activityIsGenericCompletionItem(item){
  if(!item || typeof item !== 'object') return false;
  const title = String(item.title || '').replace(/\s+/g, '').trim();
  const detail = String(item.detail || '').trim();
  const queries = Array.isArray(item.queries) ? item.queries.filter(Boolean) : [];
  return /^(?:完成|已完成|done|completed)$/i.test(title) && !detail && !queries.length;
}


function _activityIsRealPanelItem(item){
  if(!item || typeof item !== 'object') return false;
  if(item.transient || item.runtimeFallback || item.runtime_fallback) return false;
  if(_activityIsGenericCompletionItem(item)) return false;
  const title = String(item.title || item.text || '').replace(/\s+/g, '').trim();
  const detail = String(item.detail || '').replace(/\s+/g, '').trim();
  const queries = Array.isArray(item.queries) ? item.queries.map(q => String(q || '').trim()).filter(Boolean) : [];
  const sources = Array.isArray(item.sourceItems || item.source_items || item.sources || item.searchResults || item.search_results)
    ? (item.sourceItems || item.source_items || item.sources || item.searchResults || item.search_results)
    : [];
  const waitingText = /^(?:正在思考中|思考中|正在生成回答|正在回答|thinking…?|generatinganswer)$/i;
  // 某些链路归一化后会丢失 transient 标记，并把同一占位同时写入 title/detail。
  // 在面板分类器内按语义兜底，纯等待文案永远交给骨架屏，不作为真实活动。
  if(!queries.length && !sources.length && waitingText.test(title) && (!detail || waitingText.test(detail))) return false;
  if(queries.length || sources.length || detail) return true;
  if(!title) return false;
  // Pure waiting rows are runtime placeholders; they should not make the inline
  // reasoning text clickable because the side panel would have nothing real to show.
  if(waitingText.test(title)) return false;
  return true;
}

function _activityHasRealPanelItems(items){
  return (Array.isArray(items) ? items : []).some(item => _activityIsRealPanelItem(item));
}

function _activityPanelItemHasSettled(item){
  const state = String(item?.state || item?.status || '').trim().toLowerCase();
  return /^(done|complete|completed|finish|finished|success|succeeded|warn|warning|error|failed|stopped)$/.test(state);
}

function _activityPanelItemEndedByLaterEvent(item, rows, index){
  if(!_activityLooksNativeReasoningItem(item)) return false;
  for(let i = Math.max(0, Number(index || 0) + 1); i < rows.length; i += 1){
    const next = rows[i];
    if(!next || typeof next !== 'object') continue;
    if(next.transient || next.runtimeFallback || next.runtime_fallback) continue;
    if(_activityIsGenericCompletionItem(next)) continue;
    if(_activityIsRealPanelItem(next)) return true;
  }
  return false;
}

function _activityPanelVisibleItemsForRender(items, context={}){
  // 占位无论处于流式还是历史快照都不能成为活动条目；空流式面板由骨架屏显示。
  const rows = (Array.isArray(items) ? items : []).filter(item => _activityIsRealPanelItem(item));
  if(!context?.streaming) return rows;
  const out = [];
  for(const [index, item] of rows.entries()){
    if(_activityPanelItemHasSettled(item)){
      out.push(item);
      continue;
    }
    if(_activityPanelItemEndedByLaterEvent(item, rows, index)){
      out.push({ ...item, state:'done' });
      continue;
    }
    // 当前真实活动必须随事件流立即进入面板；仅 transient/runtimeFallback
    // 占位项继续由 _activityIsRealPanelItem() 拦截。
    if(_activityIsRealPanelItem(item)) out.push(item);
  }
  return out;
}

function _activityShouldRevealSearchQueries(item, context={}){
  if(!item || typeof item !== 'object') return false;
  const queries = Array.isArray(item.queries) ? item.queries.filter(Boolean) : [];
  if(!queries.length) return false;
  // Query reveal is only a live-search affordance.  Historical/final panels and
  // completed search rows should render normally, not re-enter on every refresh.
  if(!context?.streaming) return false;
  if(String(item.kind || '').toLowerCase() !== 'search') return false;
  if(String(item.state || '').toLowerCase() !== 'active') return false;
  return true;
}

function _activityPanelCompactTextSig(value){
  const s = String(value || '');
  if(!s) return '';
  if(s.length <= 180) return s;
  return `${s.length}:${s.slice(0, 70)}:${s.slice(-70)}`;
}

function _activityPanelCompactSourceSig(item){
  const raw = item?.sourcePreview || item?.source_preview || item?.sourceItems || item?.source_items || item?.sources || item?.searchResults || item?.search_results || [];
  const sources = _activityNormalizeSourceItems(raw, 8);
  const total = Math.max(Number(item?.sourceTotal || item?.source_total || item?.resultCount || item?.result_count || 0) || 0, sources.length);
  return [total, sources.map(x => String(x.url || x.host || x.title || '').slice(0, 160)).join('|')];
}


function _activityPanelMeasureStableRail(list){
  if(!list || !list.classList || !list.classList.contains('activity-panel-has-multiple')) return;
  const measure = ()=>{
    try{
      const rows = Array.from(list.children || []).filter(el => el && el.classList && el.classList.contains('activity-panel-item'));
      if(rows.length <= 1) return;
      const last = rows[rows.length - 1];
      const listRect = list.getBoundingClientRect ? list.getBoundingClientRect() : null;
      const lastRect = last && last.getBoundingClientRect ? last.getBoundingClientRect() : null;
      if(!listRect || !lastRect) return;
      const cs = window.getComputedStyle ? window.getComputedStyle(list) : null;
      const y = parseFloat(cs?.getPropertyValue('--activity-timeline-y') || '') || 10;
      const dot = parseFloat(cs?.getPropertyValue('--activity-dot-size') || '') || 6;
      const lastDotY = Math.max(0, (lastRect.top - listRect.top) + y);
      const bottom = Math.max(y + dot, Math.round(Number(listRect.height || 0) - lastDotY));
      list.style.setProperty('--activity-timeline-rail-bottom', `${bottom}px`);
    }catch(_){ }
  };
  measure();
  try{ window.requestAnimationFrame(measure); }catch(_){ }
}

function _activityRenderFinalComplete(parent, context={}, markEnter=null){
  if(!parent) return;
  const done = document.createElement('div');
  done.className = 'activity-panel-complete activity-panel-final-complete';
  try{ done.dataset.activityKey = 'final-complete'; }catch(_){ }
  const icon = document.createElement('span');
  icon.className = 'activity-panel-complete-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = '<svg viewBox="0 0 16 16" focusable="false"><circle cx="8" cy="8" r="6.25"></circle><path d="M5.2 8.15 7.05 10l3.85-4.25"></path></svg>';
  const main = document.createElement('span');
  main.className = 'activity-panel-complete-main';
  const elapsed = String(context?.elapsed || '').trim();
  if(elapsed){
    const summary = document.createElement('span');
    summary.className = 'activity-panel-complete-summary';
    summary.textContent = elapsed === (window.AperviaI18n?.t('activity.elapsed_few') || 'a few seconds')
      ? (window.AperviaI18n?.t('activity.thought_few') || 'Thought for a few seconds')
      : (window.AperviaI18n?.t('activity.thought_elapsed', {elapsed}) || `Thought for ${elapsed}`);
    main.appendChild(summary);
  }
  const label = document.createElement('span');
  label.className = 'activity-panel-complete-label';
  label.textContent = _activityT('activity.done', null, 'Done');
  main.appendChild(label);
  done.appendChild(icon);
  done.appendChild(main);
  if(typeof markEnter === 'function') markEnter(done, 'final-complete', { stepMs:46, maxDelayMs:120 });
  parent.appendChild(done);
}

function _activityPanelShouldShowFinalComplete(items, context={}){
  const allItems = Array.isArray(items) ? items : [];
  if(!allItems.length || context?.streaming) return false;
  const hasActive = allItems.some(item => String(item?.state || '').toLowerCase() === 'active');
  const hasError = allItems.some(item => {
    const state = String(item?.state || '').toLowerCase();
    return state === 'error' || state === 'failed';
  });
  return !hasActive && !hasError;
}

function _activityPanelSettleRenderedItems(body, items, context={}){
  if(!body) return false;
  const list = body.querySelector ? body.querySelector('.activity-panel-list.activity-panel-timeline') : null;
  if(!list) return false;
  const visibleItems = _activityPanelVisibleItemsForRender(items, context);
  if(!visibleItems.length) return false;
  for(const [itemIndex, item] of visibleItems.entries()){
    const key = _activityPanelStableItemKey(item, itemIndex);
    if(!key) continue;
    const escaped = (typeof CSS !== 'undefined' && CSS.escape) ? CSS.escape(key) : key.replace(/["\\]/g, '\\$&');
    const row = list.querySelector(`[data-activity-key="${escaped}"]`);
    if(!row) return false;
    const state = item.state || 'done';
    row.classList.remove('activity-state-active', 'activity-state-done', 'activity-state-warn', 'activity-state-error', 'activity-state-failed');
    row.classList.add(`activity-state-${state}`);
    _activityPanelMarkEventState(row, key, _activityPanelVisualStateForItem(item, context));
  }
  const shouldShowFinalComplete = _activityPanelShouldShowFinalComplete(items, context);
  const existingFinal = list.querySelector('.activity-panel-final-complete');
  if(shouldShowFinalComplete && !existingFinal){
    _activityRenderFinalComplete(list, context, null);
  }else if(existingFinal && !shouldShowFinalComplete){
    existingFinal.remove();
  }else if(existingFinal && shouldShowFinalComplete){
    const elapsed = String(context?.elapsed || '').trim();
    const summary = existingFinal.querySelector('.activity-panel-complete-summary');
    if(elapsed && summary) summary.textContent = elapsed === (window.AperviaI18n?.t('activity.elapsed_few') || 'a few seconds')
      ? (window.AperviaI18n?.t('activity.thought_few') || 'Thought for a few seconds')
      : (window.AperviaI18n?.t('activity.thought_elapsed', {elapsed}) || `Thought for ${elapsed}`);
  }
  _activityPanelMeasureStableRail(list);
  return true;
}

function _activityPanelAppendSectionHeading(body, beforeNode=null){
  if(!body) return null;
  const heading = document.createElement('h2');
  heading.className = 'activity-panel-section-heading';
  heading.textContent = _activityT('activity.thinking', null, 'Thinking');
  body.insertBefore(heading, beforeNode || null);
  return heading;
}

function _activityPanelRenderSkeleton(body, variant='activity', rows=3){
  if(!body) return null;
  if(typeof AppLoadingUi !== 'undefined' && typeof AppLoadingUi.render === 'function'){
    const skeleton = AppLoadingUi.render(body, { variant, rows, label:_activityT('activity.loading', null, 'Loading activity') });
    _activityPanelAppendSectionHeading(body, skeleton);
    return skeleton;
  }
  const fallback = document.createElement('div');
  fallback.className = 'activity-panel-empty';
  fallback.textContent = _activityT('activity.loading_ellipsis', null, 'Loading activity…');
  body.replaceChildren(fallback);
  _activityPanelAppendSectionHeading(body, fallback);
  body.setAttribute('aria-busy', 'true');
  return fallback;
}

function _activityRenderItems(body, items, context={}){
  body.textContent = '';
  if(typeof AppLoadingUi !== 'undefined' && typeof AppLoadingUi.ready === 'function') AppLoadingUi.ready(body);
  const allItems = Array.isArray(items) ? items : [];
  const visibleItems = _activityPanelVisibleItemsForRender(allItems, context);
  const showFinalComplete = _activityPanelShouldShowFinalComplete(allItems, context);
  // “完成”是整轮活动的收尾提示，不是每个阶段 done 后的阶段提示。
  // 流式过程中可能出现：当前几个活动都 done，但回答/工具链还在继续，
  // 这时不能提前显示“完成”，否则会像每个活动都结束了一次。
  items = visibleItems;
  const searchItemCount = items.filter(item => String(item?.kind || item?.stage || '').toLowerCase() === 'search').length;
  const defaultSourceVisibleLimit = searchItemCount >= 8 ? 2 : (searchItemCount >= 4 ? 3 : 4);
  if(!items.length){
    if(context?.streaming){
      _activityPanelRenderSkeleton(body, 'activity', 3);
      return;
    }
    const empty = document.createElement('div');
    empty.className = 'activity-panel-empty';
    empty.textContent = _activityT('activity.empty', null, 'No activity is available for this turn.');
    body.appendChild(empty);
    return;
  }
  _activityPanelAppendSectionHeading(body);
  const list = document.createElement('div');
  list.className = 'activity-panel-list activity-panel-list-flat activity-panel-timeline';
  if(items.length > 1) list.classList.add('activity-panel-has-multiple');
  let enterOrder = 0;
  const markEnter = (el, key, opts={})=>{
    const didEnter = _activityPanelMarkEnter(el, key, enterOrder, opts);
    if(didEnter) enterOrder += 1;
    return didEnter;
  };
  for(const [itemIndex, item] of items.entries()){
    const kind = item.kind || 'answer';
    const kindKey = String(kind || '').toLowerCase();
    const row = document.createElement('div');
    row.className = `activity-panel-item activity-kind-${kind} activity-state-${item.state || 'done'}`;
    const stableItemKey = _activityPanelStableItemKey(item, itemIndex);
    try{ row.dataset.activityKey = stableItemKey; }catch(_){ }
    markEnter(row, stableItemKey, { stepMs:46, maxDelayMs:240 });
    _activityPanelMarkEventState(row, stableItemKey, _activityPanelVisualStateForItem(item, context));
    if(kindKey === 'search'){
      const marker = document.createElement('span');
      marker.className = 'activity-panel-timeline-marker activity-panel-search-marker';
      marker.setAttribute('aria-hidden', 'true');
      marker.innerHTML = '<svg viewBox="0 0 18 18" focusable="false"><circle cx="9" cy="9" r="6.5"></circle><path d="M2.9 9h12.2M9 2.5c1.75 1.65 2.65 3.8 2.65 6.5S10.75 13.85 9 15.5M9 2.5C7.25 4.15 6.35 6.3 6.35 9s.9 4.85 2.65 6.5"></path></svg>';
      row.appendChild(marker);
    }

    const main = document.createElement('div');
    main.className = 'activity-panel-item-main';
    const title = document.createElement('div');
    title.className = 'activity-panel-item-title';
    const isThinkRow = String(item.kind || kind || '').toLowerCase() === 'think';
    const titleFallback = isThinkRow ? '' : (_activityKindSectionTitle(kind) || _activityT('activity.processing', null, 'Processing'));
    const titleText = _activityDisplayTitleForItem(item, item.title || titleFallback);
    if(titleText){
      if(String(item.kind || kind || '').toLowerCase() === 'sandbox' && (String(item.tool || '').toLowerCase() === 'sandbox_run' || item.command)){
        const icon = document.createElement('span');
        icon.className = 'activity-panel-inline-code-icon';
        icon.textContent = '‹›';
        title.appendChild(icon);
        const labelNode = document.createElement('span');
        labelNode.textContent = titleText;
        title.appendChild(labelNode);
      }else{
        title.textContent = titleText;
      }
      main.appendChild(title);
    }
    const elapsed = String(item.nativeElapsed || '').trim();
    if(elapsed){
      const meta = document.createElement('div');
      meta.className = 'activity-panel-item-meta';
      meta.textContent = _activityT('activity.duration', {elapsed}, `Duration ${elapsed}`);
      main.appendChild(meta);
    }
    const itemTool = String(item.tool || '').toLowerCase();
    const itemKind = String(item.kind || kind || '').toLowerCase();
    const canRenderDebugBlocks = ['sandbox_run','sandbox_list_files'].includes(itemTool);
    const showDebug = canRenderDebugBlocks && !!(item.showDebug || item.show_debug || item.debugAvailable || item.debug_available || String(item.state || '').toLowerCase() === 'error');
    const itemCommand = canRenderDebugBlocks ? String(item.command || '') : '';
    const itemStdout = canRenderDebugBlocks ? String(item.stdout || '') : '';
    const itemStderr = canRenderDebugBlocks ? String(item.stderr || '') : '';
    const itemExitCode = canRenderDebugBlocks ? (item.exitCode ?? item.exit_code) : undefined;
    // sandbox_run 的退出码已合并进“输出”块，面板顶部不再重复显示“退出码 1”。
    const isSandboxRunItem = itemKind === 'sandbox' && (itemTool === 'sandbox_run' || !!item.command || !!itemCommand || !!itemStdout || !!itemStderr);
    if(isSandboxRunItem) row.classList.add('activity-panel-command-item');
    if(showDebug && !isSandboxRunItem && itemExitCode !== undefined && itemExitCode !== null){
      const exit = document.createElement('div');
      exit.className = 'activity-panel-item-meta';
      exit.textContent = _activityT('activity.exit_code', {code:itemExitCode}, `Exit code ${itemExitCode}`);
      main.appendChild(exit);
    }
    // sandbox_run 的 data/path 只是执行目录标签，用户价值低；文件列表/读写/发布类事件仍保留文件 chips。
    if(!isSandboxRunItem && ((Array.isArray(item.fileNames) && item.fileNames.length) || Number(item.fileNameTotal || 0) > 0)) _activityRenderFileChips(main, item.fileNames || [], item.fileNameTotal || item.fileNameCount || item.file_count || 0);
    const hasStaticImageResults = Array.isArray(item.imageItems) && item.imageItems.length;
    if(hasStaticImageResults && !isSandboxRunItem) _activityRenderImagePreviews(main, item.imageItems, item.imageCount || 0, context?.sessionId || '');
    if(Array.isArray(item.documentVisualItems) && item.documentVisualItems.length) _activityRenderDocumentVisualPreviews(main, item.documentVisualItems, item.documentPageCount || 0);
    if(item.detail) _activityRenderTextBlock(main, item.detail, item.renderMode || 'auto');
    if(Array.isArray(item.collapsedItems) && item.collapsedItems.length) _activityRenderCollapsedDetails(main, item.collapsedItems);
    if(showDebug && itemCommand){
      const lang = String(item.commandLanguage || item.command_language || '').toLowerCase();
      const isJs = (lang === 'javascript' || lang === 'node');
      const isShell = (lang === 'shell' || lang === 'bash' || lang === 'sh');
      const invokesPython = /\b(?:python(?:3(?:\.\d+)?)?|py)\b/i.test(itemCommand);
      const label = isJs ? 'JavaScript' : (isShell && !invokesPython ? 'Shell' : 'Python');
      _activityRenderCodeBlock(main, label, itemCommand, isJs ? 'javascript' : (isShell ? 'shell' : 'python'), { extraClass:'activity-panel-sandbox-command-card' });
    }
    if(showDebug && itemStdout) _activityRenderCodeBlock(main, _activityT('activity.output', null, 'Output'), itemStdout, 'text', { extraClass:'activity-panel-sandbox-output-card' });
    if(showDebug && itemStderr) _activityRenderCodeBlock(main, _activityT('activity.error_output', null, 'Error output'), itemStderr, 'text', { extraClass:'activity-panel-sandbox-error-card' });
    if(hasStaticImageResults && isSandboxRunItem) _activityRenderImagePreviews(main, item.imageItems, item.imageCount || 0, context?.sessionId || '');
    if(_activityShouldRenderQueryChips(item)){
      const chips = document.createElement('div');
      chips.className = 'activity-panel-query-row';
      const revealQueries = _activityShouldRevealSearchQueries(item, context);
      for(const [queryIndex, q] of item.queries.entries()){
        const chip = document.createElement('span');
        chip.className = 'activity-panel-query-chip';
        chip.textContent = q;
        // Only reveal query chips while a real search row is actively running.
        // Completed/historical rows render stable, so reopening the panel or
        // receiving final snapshots does not make every query animate again.
        if(revealQueries){
          markEnter(chip, _activityPanelStableVisualKey(stableItemKey, 'query', queryIndex, q), { stepMs:42, maxDelayMs:220 });
        }
        chips.appendChild(chip);
      }
      main.appendChild(chips);
    }
    if(Array.isArray(item.sourceItems) && item.sourceItems.length){
      // Source chips are real event data too, but animating every source makes the
      // panel feel busy.  Keep reveal animation limited to search-query chips.
      _activityRenderSourceChips(main, item.sourceItems, { key:stableItemKey, totalCount:(item.sourceTotal || item.source_total || item.resultCount || item.result_count || 0), visibleLimit:defaultSourceVisibleLimit });
    }
    const itemState = String(item.state || '').toLowerCase();
    const hasPendingDetail = !!(
      item.detail || item.command || item.stdout || item.stderr ||
      (Array.isArray(item.queries) && item.queries.length) ||
      (Array.isArray(item.sourceItems) && item.sourceItems.length) ||
      (Array.isArray(item.fileNames) && item.fileNames.length) ||
      (Array.isArray(item.imageItems) && item.imageItems.length) ||
      (Array.isArray(item.documentVisualItems) && item.documentVisualItems.length)
    );
    if(context?.streaming && itemState === 'active' && !hasPendingDetail && typeof AppLoadingUi !== 'undefined'){
      const pending = AppLoadingUi.create?.({ variant:'activity-detail', rows:1, label:_activityT('activity.receiving_details', null, 'Receiving activity details') });
      if(pending) main.appendChild(pending);
    }
    row.appendChild(main);
    list.appendChild(row);
  }
  if(showFinalComplete){
    _activityRenderFinalComplete(list, context, markEnter);
  }
  body.appendChild(list);
  _activityPanelMeasureStableRail(list);
}

function _activityPanelNeedsLiveTick(data){
  return false;
}

function _activityPanelItemSignatureDetail(item, streaming){
  const kind = String(item?.kind || item?.stage || '').toLowerCase();
  const state = String(item?.state || '').toLowerCase();
  if(streaming && kind === 'think' && state === 'active' && item?.chatThinkSoftFlow){
    return _activityPanelCompactTextSig(item?.detail || item?.text || '');
  }
  if(streaming && kind === 'think' && state === 'active'){
    return '';
  }
  return _activityPanelCompactTextSig(item?.detail);
}

function _activityPanelScheduleLiveRefresh(sessionId, enabled){
  const sid = _activityCurrentSessionId(sessionId);
  if(!enabled || !sid || !_activityPanelIsExplicitlyOpenForSession(sid)){
    try{ if(_activityPanelLiveTimer) clearInterval(_activityPanelLiveTimer); }catch(_){ }
    _activityPanelLiveTimer = 0;
    _activityPanelLiveSessionId = '';
    return;
  }
  if(_activityPanelLiveTimer && _activityPanelLiveSessionId === sid) return;
  try{ if(_activityPanelLiveTimer) clearInterval(_activityPanelLiveTimer); }catch(_){ }
  _activityPanelLiveSessionId = sid;
  _activityPanelLiveTimer = setInterval(()=>{
    if(!_activityPanelIsExplicitlyOpenForSession(sid)){
      _activityPanelScheduleLiveRefresh(sid, false);
      return;
    }
    refreshActivityPanelForVisibleSession(sid, { schedule:false, liveTick:true });
  }, 1000);
}

function refreshActivityPanelForVisibleSession(sessionId, opts={}){
  const sidForOpen = _activityCurrentSessionId(sessionId);
  const force = !!opts?.force;
  const openForSession = _activityPanelIsExplicitlyOpenForSession(sidForOpen);
  const switchedOpenSession = !!(_activityPanelOpenSessionId && _activityPanelOpenSessionId !== sidForOpen);
  const schedule = opts && opts.schedule !== false;
  if(schedule){
    if(!force && !openForSession && !switchedOpenSession) return;
    if(switchedOpenSession){
      _activityPanelOpenSessionId = '';
      _activityPanelTargetMessage = null;
      _activityPanelTargetSnapshot = null;
      _activityPanelLastSignature = '';
      _activityPanelLastStructureSignature = '';
    }
    const weakMode = !!(typeof shouldUseWeakNonCriticalMode === 'function' && shouldUseWeakNonCriticalMode());
    const defaultThrottleMs = weakMode ? 520 : 260;
    let throttleMs = Math.max(0, Number(opts?.throttleMs || defaultThrottleMs) || defaultThrottleMs);
    if(openForSession && !force && throttleMs >= 700) throttleMs = weakMode ? 360 : 220;
    if(opts?.terminal || opts?.immediate) throttleMs = Math.min(throttleMs, 64);
    _activityPanelPendingRefreshOpts = _activityPanelMergeRefreshOpts(_activityPanelPendingRefreshOpts, opts);
    const run = ()=>{
      const pendingOpts = _activityPanelMergeRefreshOpts(_activityPanelPendingRefreshOpts, opts);
      try{ if(_activityPanelRefreshTimer) clearTimeout(_activityPanelRefreshTimer); }catch(_){ }
      _activityPanelRefreshTimer = 0;
      _activityPanelPendingRefreshOpts = null;
      try{ if(_activityPanelRefreshFrame) cancelAnimationFrame(_activityPanelRefreshFrame); }catch(_){ }
      _activityPanelRefreshFrame = requestAnimationFrame(()=>{
        _activityPanelRefreshFrame = 0;
        _activityPanelLastRefreshAt = Date.now();
        refreshActivityPanelForVisibleSession(sessionId, { ...pendingOpts, schedule:false });
      });
    };
    const elapsed = Date.now() - Number(_activityPanelLastRefreshAt || 0);
    if(opts?.immediate || force || elapsed >= throttleMs){
      run();
    }else{
      try{ if(_activityPanelRefreshTimer) clearTimeout(_activityPanelRefreshTimer); }catch(_){ }
      _activityPanelRefreshTimer = setTimeout(run, Math.max(16, throttleMs - elapsed));
    }
    return;
  }
  const els = _activityPanelEls();
  if(!els.root || !els.body) return;
  if(!force && !openForSession){
    if(_activityPanelOpenSessionId && _activityPanelOpenSessionId !== sidForOpen){
      _activityPanelOpenSessionId = '';
      _activityPanelTargetMessage = null;
      _activityPanelTargetSnapshot = null;
    }
    els.root.hidden = true;
    els.root.setAttribute('aria-hidden', 'true');
    document.body?.classList?.remove('activity-panel-open');
    try{ if(typeof mainEl !== 'undefined' && mainEl) mainEl.classList.remove('activity-panel-open'); }catch(_){ }
    _activitySyncReserve(false);
    _activityPanelLastSignature = '';
    _activityPanelLastStructureSignature = '';
    _activityPanelCancelScheduledRefresh();
    _activityPanelScheduleLiveRefresh(sidForOpen, false);
    return;
  }
  const data = _activitySnapshotForSession(sessionId);
  const sid = data.sid;
  const runKey = `${sid}|${Number(data.rt?.rtStartAt || 0) || 0}|${data.rt?.streaming ? 'streaming' : 'idle'}`;
  if(runKey !== _activityPanelRunKey){
    _activityPanelRunKey = runKey;
  }
  const visualSeed = Number(data.rt?.rtStartAt || 0) || Math.min(...data.items.map(x => Number(x?.ts || x?.updatedAt || x?.updated_at || 0) || Date.now()));
  _activityPanelEnsureVisualRun(`${sid}|${Number.isFinite(visualSeed) ? visualSeed : 0}`);
  const hasActivity = !!(sid && _activityHasRealPanelItems(data.items));
  const waitingForFirstActivity = !!(sid && data.rt?.streaming && _activityPanelIsExplicitlyOpenForSession(sid));
  const homeView = !!(typeof isHomeLandingView !== 'undefined' && isHomeLandingView);
  const shouldHide = (!hasActivity && !waitingForFirstActivity) || !_activityPanelIsExplicitlyOpenForSession(sid) || homeView;
  els.root.hidden = shouldHide;
  els.root.setAttribute('aria-hidden', shouldHide ? 'true' : 'false');
  document.body?.classList?.toggle('activity-panel-open', !shouldHide);
  try{ if(typeof mainEl !== 'undefined' && mainEl) mainEl.classList.toggle('activity-panel-open', !shouldHide); }catch(_){ }
  _activitySyncReserve(!shouldHide);
  if(shouldHide){
    if(!hasActivity && !data.rt?.streaming && _activityPanelIsExplicitlyOpenForSession(sid)){
      _activityPanelOpenSessionId = '';
      _activityPanelTargetMessage = null;
      _activityPanelTargetSnapshot = null;
    }
    _activityPanelLastSignature = '';
    _activityPanelLastStructureSignature = '';
    // Keep visual seen keys for the current run when the panel is temporarily
    // hidden.  The key resets naturally on a new run/session, but close/reopen
    // should not replay query reveal animations.
    _activityPanelCancelScheduledRefresh();
    _activityPanelScheduleLiveRefresh(sid, false);
    return;
  }

  _activityPanelScheduleLiveRefresh(sid, _activityPanelNeedsLiveTick(data));
  const elapsed = _activityElapsedLabelFromActivityData(data);
  if(els.title) els.title.textContent = _activityT('activity.title', null, 'Activity');
  if(els.elapsed) els.elapsed.textContent = elapsed ? `· ${elapsed}` : '';
  const hasActivePanelItem = data.items.some(item => String(item?.state || '').toLowerCase() === 'active');
  const hasErrorPanelItem = data.items.some(item => {
    const state = String(item?.state || '').toLowerCase();
    return state === 'error' || state === 'failed';
  });
  _activityPanelMarkTitleEventState(els, hasErrorPanelItem ? 'error' : ((data.rt?.streaming || hasActivePanelItem) ? 'active' : 'done'));
  const streaming = !!data.rt?.streaming;
  const panelRenderItems = _activityPanelVisibleItemsForRender(data.items, { streaming, elapsed, sessionId:sid });
  const itemSignatureRows = panelRenderItems.map((x, index) => [
    _activityPanelStableItemKey(x, index), x.key, x.title, _activityPanelCompactTextSig(x?.detail), x.state, _activityPanelItemSignatureDetail(x, streaming), x.seq, x.ts, x.queries, _activityPanelCompactSourceSig(x),
    x.renderMode, x.showDebug, x.commandLanguage, _activityPanelCompactTextSig(x.command),
    _activityPanelCompactTextSig(x.stdout), _activityPanelCompactTextSig(x.stderr), x.exitCode,
    x.fileNames, x.fileNameTotal, Array.isArray(x.collapsedItems) ? x.collapsedItems.length : 0,
    x.imageCount, _activityNormalizeImageItems(x.imageItems || [], 8).map(item => String(item.image_id || item.attachment_id || item.file_library_id || item.model_storage_ref || item.storage_ref || item.view_url || item.preview_url || item.url || '')).join('|'),
    x.documentPageCount, !!x.documentVisualDeferred, _activityNormalizeDocumentVisualItems(x.documentVisualItems || [], 12).map(item => `${item.visualExecId || ''}:${item.pageNumber || ''}:${item.previewUrl || ''}`).join('|')
  ]);
  const structureSignature = JSON.stringify({ sid, items:itemSignatureRows.map(row => row.filter((_, index) => index !== 4 && index !== 5)) });
  const signature = JSON.stringify({ sid, streaming, items:itemSignatureRows });
  if(signature === _activityPanelLastSignature) return;
  const canSettleInPlace = !streaming && _activityPanelLastStructureSignature === structureSignature && _activityPanelLastSignature;
  if(canSettleInPlace && _activityPanelSettleRenderedItems(els.body, data.items, { streaming, elapsed, sessionId:sid })){
    _activityPanelLastSignature = signature;
    _activityPanelLastStructureSignature = structureSignature;
    return;
  }
  _activityPanelLastSignature = signature;
  _activityPanelLastStructureSignature = structureSignature;
  const scrollAnchor = _activityPanelCaptureScrollAnchor(els.body);
  _activityRenderItems(els.body, data.items, { streaming, elapsed, sessionId:sid });
  _activityPanelRestoreScrollAnchor(els.body, scrollAnchor);
}

function hideActivityPanelForVisibleSession(){
  const sid = _activityCurrentSessionId();
  _activityPanelOpenSessionId = '';
  _activityPanelTargetMessage = null;
  _activityPanelTargetSnapshot = null;
  refreshActivityPanelForVisibleSession(sid, { schedule:false });
}

function initActivityPanelUi(){
  const els = _activityPanelEls();
  if(els.close && !els.close.dataset.activityBound){
    els.close.dataset.activityBound = '1';
    els.close.addEventListener('click', hideActivityPanelForVisibleSession);
  }
  refreshActivityPanelForVisibleSession('', { schedule:false });
}

try{ window.addEventListener('resize', ()=>_activitySyncReserve(), { passive:true }); }catch(_){ }
try{ initActivityPanelUi(); }catch(_){ }

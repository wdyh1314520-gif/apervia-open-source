/* Product frontend module.
 * Purpose: Browser location, clock, URL extraction, and webpage context helpers.
 * Loaded before index3.js; classic-script globals preserve the existing single runtime.
 */

function isSettingTruthyValue(value){
  if(value === true) return true;
  if(value === false || value === null || value === undefined) return false;
  if(typeof value === "number") return value !== 0;
  const raw = String(value || "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on" || raw === "enabled" || raw === "开启";
}

function isBrowserGeoOneShotActive(){
  return Number(_browserGeoOneShotUntil || 0) > Date.now();
}

function isBrowserGeoPersistentlyEnabled(){
  try{
    const ws = (typeof getWebSettings === "function") ? getWebSettings() : {};
    return isSettingTruthyValue(ws.BROWSER_GEO_ENABLE);
  }catch(_){
    return false;
  }
}

function isBrowserGeoSettingEnabled(){
  return isBrowserGeoPersistentlyEnabled() || isBrowserGeoOneShotActive();
}

function clearUserGeoCache(){
  _geoCache = null;
  _geoCacheAt = 0;
  try{ localStorage.removeItem(USER_GEO_CACHE_KEY); }catch(_){ }
}

function normalizeUserGeoPayload(value){
  if(!value || typeof value !== "object") return null;
  const lat = Number(value.lat);
  const lon = Number(value.lon);
  if(!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const out = { lat, lon };
  const accuracy = Number(value.accuracy);
  if(Number.isFinite(accuracy)) out.accuracy = accuracy;
  const acquiredAt = Number(value.acquired_at || value.acquiredAt || Date.now());
  out.acquired_at = Number.isFinite(acquiredAt) ? acquiredAt : Date.now();
  const source = String(value.source || "browser").trim();
  if(source) out.source = source;
  return out;
}

function loadPersistedUserGeo(){
  try{
    const raw = localStorage.getItem(USER_GEO_CACHE_KEY);
    if(!raw) return null;
    const geo = normalizeUserGeoPayload(JSON.parse(raw));
    if(!geo) return null;
    const age = Date.now() - Number(geo.acquired_at || 0);
    if(age > USER_GEO_PERSIST_TTL_MS){
      localStorage.removeItem(USER_GEO_CACHE_KEY);
      return null;
    }
    return geo;
  }catch(_){
    return null;
  }
}

function persistUserGeo(geo){
  try{ localStorage.setItem(USER_GEO_CACHE_KEY, JSON.stringify(geo)); }catch(_){ }
}

function rememberUserGeo(geo){
  const normalized = normalizeUserGeoPayload(geo);
  if(!normalized) return null;
  _geoCache = normalized;
  _geoCacheAt = Date.now();
  persistUserGeo(normalized);
  return normalized;
}

function buildGeoErrorMeta(err, extra={}){
  const code = Number(err?.code);
  const reasonMap = {
    1: 'permission_denied',
    2: 'position_unavailable',
    3: 'timeout',
  };
  const out = {
    code: Number.isFinite(code) ? code : null,
    reason: reasonMap[code] || String(err?.name || extra.reason || 'unknown').trim().toLowerCase() || 'unknown',
    name: String(err?.name || '').trim(),
    message: String(err?.message || extra.message || '').trim().slice(0, 160),
    secure_context: !!window.isSecureContext,
    protocol: String(location.protocol || '').trim(),
    has_geolocation_api: !!navigator.geolocation,
    ts: Date.now(),
  };
  if(extra && typeof extra === 'object'){
    if(extra.step) out.step = String(extra.step).trim();
    if(extra.timeout_ms != null) out.timeout_ms = Number(extra.timeout_ms) || 0;
    if(extra.maximum_age_ms != null) out.maximum_age_ms = Number(extra.maximum_age_ms) || 0;
    if(extra.enable_high_accuracy != null) out.enable_high_accuracy = !!extra.enable_high_accuracy;
  }
  return out;
}

function getGeoRuntimeDebugMeta(){
  return {
    has_geolocation_api: !!navigator.geolocation,
    is_secure_context: !!window.isSecureContext,
    protocol: String(location.protocol || '').trim(),
    browser_geo_enabled: isBrowserGeoSettingEnabled(),
    last_geo_error: (_lastGeoErrorMeta && typeof _lastGeoErrorMeta === 'object') ? { ..._lastGeoErrorMeta } : null,
  };
}

async function queryBrowserGeoPermissionStateSafe(){
  try{
    if(!navigator.permissions || typeof navigator.permissions.query !== 'function') return '';
    const status = await navigator.permissions.query({ name: 'geolocation' });
    return String(status && status.state || '').trim();
  }catch(_){
    return '';
  }
}

function buildRuntimeLocationStatePayload({ userGeo = null, geoAttachMode = '', permissionState = '' } = {}){
  const nowDate = new Date();
  let timezone = '';
  try{ timezone = String(Intl.DateTimeFormat().resolvedOptions().timeZone || '').trim(); }catch(_){ timezone = ''; }
  const settingEnabled = isBrowserGeoSettingEnabled();
  // 长期开关只控制自动附带位置；一次性精确定位能否申请，仅取决于页面和浏览器能力。
  const canRequestPrecise = !!(navigator.geolocation && canUseBrowserGeoNow());
  const precise = normalizeUserGeoPayload(userGeo);
  const lastError = (_lastGeoErrorMeta && typeof _lastGeoErrorMeta === 'object') ? { ..._lastGeoErrorMeta } : null;
  const out = {
    source: 'frontend_runtime',
    precise_location: {
      enabled: !!settingEnabled,
      available: !!precise,
      permission_state: String(permissionState || '').trim(),
      can_request: canRequestPrecise,
      attach_mode: String(geoAttachMode || '').trim(),
      last_error: lastError,
    },
    approximate_location: {
      available: false,
      source: 'not_available',
    },
    time_environment: {
      available: !!timezone,
      timezone,
      offset_minutes: -nowDate.getTimezoneOffset(),
      locale: String(navigator.language || '').trim(),
      source: 'browser_clock',
    },
    visibility: precise ? 'precise_location_available' : (timezone ? 'timezone_only' : 'no_location_context'),
    ts: Date.now(),
  };
  if(precise){
    out.precise_location.lat = precise.lat;
    out.precise_location.lon = precise.lon;
    if(precise.accuracy != null) out.precise_location.accuracy = precise.accuracy;
    if(precise.acquired_at != null) out.precise_location.acquired_at = precise.acquired_at;
    if(precise.source) out.precise_location.source = precise.source;
  }
  return out;
}

function geoUiText(key, fallback){
  return window.AperviaI18n?.t(key, null, fallback) || fallback;
}

function buildGeoUserHint(meta){
  if(!meta || typeof meta !== 'object') return '';
  const reason = String(meta.reason || '').trim().toLowerCase();
  if(reason === 'disabled_by_setting') return geoUiText('location.disabled', 'Location is off. Enable device location under Settings → Data controls.');
  if(reason === 'timeout') return geoUiText('location.timeout', 'Location timed out. Try again later.');
  if(reason === 'permission_denied') return geoUiText('location.permission_denied', 'Location failed: you denied location access for this site. Allow location in your browser and try again.');
  if(reason === 'position_unavailable') return geoUiText('location.position_unavailable', 'Location failed: your position is temporarily unavailable. Check system location, GPS, or your network and try again.');
  if(reason === 'api_unavailable') return geoUiText('location.api_unavailable', 'Location failed: this browser does not support location services.');
  if(reason === 'insecure_context') return geoUiText('location.insecure_context', 'Location failed: this page is not using HTTPS or localhost, so the browser will not provide a location.');
  return geoUiText('location.failed', 'Location failed: your current position is temporarily unavailable. Try again later.');
}

function notifyGeoUserHint(meta){
  const msg = buildGeoUserHint(meta);
  if(!msg) return;
  const reason = String(meta?.reason || '').trim().toLowerCase() || 'unknown';
  const step = String(meta?.step || '').trim().toLowerCase() || '-';
  const key = `${reason}|${step}|${msg}`;
  const now = Date.now();
  if(_lastGeoNoticeKey === key && (now - _lastGeoNoticeAt) < 4000) return;
  _lastGeoNoticeKey = key;
  _lastGeoNoticeAt = now;
  try{ setStatus(msg); }catch(_){ }
  try{ toast(msg, 2600); }catch(_){ }
}

function locationPermissionPromptText(payload, key, fallback, resourceKey = ''){
  const localized = resourceKey ? String(geoUiText(resourceKey, '') || '').trim() : '';
  if(localized) return localized;
  const data = payload && typeof payload === 'object' ? payload : {};
  const value = data[key] ?? data[key.replace(/_([a-z])/g, (_, ch)=>ch.toUpperCase())];
  const text = String(value || fallback || '').trim();
  return text || String(fallback || '').trim();
}

async function submitLocationPermissionResponse(payload = {}, patch = {}){
  const jobId = String(payload?.job_id || payload?._job_id || patch?.job_id || patch?._job_id || '').trim();
  if(!jobId) return false;
  const body = {
    job_id: jobId,
    request_id: String(payload?.request_id || patch?.request_id || '').trim(),
    ok: !!patch.ok,
    cancelled: !!patch.cancelled,
    reason: String(patch.reason || '').trim(),
    error: String(patch.error || '').trim(),
  };
  if(patch.user_geo && typeof patch.user_geo === 'object') body.user_geo = patch.user_geo;
  if(patch.location_state && typeof patch.location_state === 'object') body.location_state = patch.location_state;
  try{
    await fetch('/api3/chat_async/location', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify(body),
      cache:'no-store',
    });
    return true;
  }catch(_){
    return false;
  }
}

async function handleLocationPermissionRequest(payload = {}){
  if(_locationPermissionPromptPending){
    await submitLocationPermissionResponse(payload, { ok:false, cancelled:true, reason:'prompt_already_pending' });
    return false;
  }
  _locationPermissionPromptPending = true;
  _lastLocationPermissionPromptAt = Date.now();
  const title = locationPermissionPromptText(payload, 'title', 'Use your location for this request?', 'location.permission_prompt_title');
  const desc = locationPermissionPromptText(payload, 'message', 'Your precise location will be used only for this conversation request.', 'location.permission_prompt_desc');
  const confirmText = locationPermissionPromptText(payload, 'confirm_text', 'Confirm', 'common.confirm');
  const cancelText = locationPermissionPromptText(payload, 'cancel_text', 'Cancel', 'common.cancel');
  let resolvedGeo = null;
  let resolvedLocationState = null;
  const requestOnce = async ()=>{
    _browserGeoOneShotUntil = Date.now() + 10 * 60 * 1000;
    const geo = await getUserGeoCached({ preferFresh:true, allowStored:false });
    if(!geo){
      _browserGeoOneShotUntil = 0;
      const hint = buildGeoUserHint(_lastGeoErrorMeta) || geoUiText('location.unavailable', 'Location is temporarily unavailable.');
      throw new Error(hint);
    }
    resolvedGeo = geo;
    const permissionState = await queryBrowserGeoPermissionStateSafe();
    resolvedLocationState = buildRuntimeLocationStatePayload({
      userGeo: geo,
      geoAttachMode: 'one_shot_permission_modal',
      permissionState,
    });
    try{ toast(geoUiText('location.acquired', 'Location acquired')); }catch(_){ }
    try{ setStatus(geoUiText('location.continuing', 'Location acquired. Continuing the response…')); }catch(_){ }
    return true;
  };
  try{
    let confirmed = false;
    if(typeof askKbDangerAction === 'function'){
      confirmed = await askKbDangerAction({
        title,
        desc,
        confirmText,
        cancelText,
        busyText:geoUiText('location.requesting', 'Getting your location…'),
        errorPrefix:'',
      }, requestOnce);
    }else if(confirm(`${title}\n\n${desc}`.trim())){
      await requestOnce();
      confirmed = true;
    }
    if(confirmed && resolvedGeo){
      await submitLocationPermissionResponse(payload, {
        ok:true,
        cancelled:false,
        reason:'granted',
        user_geo: resolvedGeo,
        location_state: resolvedLocationState || buildRuntimeLocationStatePayload({ userGeo: resolvedGeo, geoAttachMode:'one_shot_permission_modal' }),
      });
    }else{
      const permissionState = await queryBrowserGeoPermissionStateSafe();
      await submitLocationPermissionResponse(payload, {
        ok:false,
        cancelled:true,
        reason:'cancelled',
        location_state: buildRuntimeLocationStatePayload({ geoAttachMode:'one_shot_permission_modal_cancelled', permissionState }),
      });
    }
  }catch(err){
    const message = String(err?.message || err || '').trim();
    try{ notifyGeoUserHint(_lastGeoErrorMeta || buildGeoErrorMeta(err, { reason:'unknown', message })); }catch(_){ }
    const permissionState = await queryBrowserGeoPermissionStateSafe();
    await submitLocationPermissionResponse(payload, {
      ok:false,
      cancelled:true,
      reason:String(_lastGeoErrorMeta?.reason || 'error'),
      error:message,
      location_state: buildRuntimeLocationStatePayload({ geoAttachMode:'one_shot_permission_modal_error', permissionState }),
    });
  }finally{
    _locationPermissionPromptPending = false;
  }
  return true;
}

function canUseBrowserGeoNow(){
  try{
    if(window.isSecureContext) return true;
    const host = String(location.hostname || '').trim().toLowerCase();
    return host === 'localhost' || host === '127.0.0.1' || host === '::1';
  }catch(_){
    return false;
  }
}

function requestBrowserGeoOnce(options){
  return new Promise((resolve, reject)=>{
    if(!navigator.geolocation) return reject({ name:'GeolocationUnavailable', message:'navigator.geolocation 不可用' });
    navigator.geolocation.getCurrentPosition(resolve, reject, options || {});
  });
}

async function getUserGeoCached(opts){
  const options = (opts && typeof opts === "object") ? opts : {};
  const preferFresh = !!options.preferFresh;
  const allowStored = options.allowStored !== false;
  const nowTs = Date.now();
  if(!isBrowserGeoSettingEnabled()){
    _lastGeoErrorMeta = buildGeoErrorMeta(null, { reason:'disabled_by_setting', message:'应用定位开关未开启' });
    return null;
  }
  if(_geoCache && (nowTs - _geoCacheAt) < USER_GEO_MEMORY_TTL_MS) return _geoCache;

  const storedGeo = allowStored ? loadPersistedUserGeo() : null;
  if(storedGeo){
    _geoCache = storedGeo;
    _geoCacheAt = Number(storedGeo.acquired_at || nowTs);
    if(!preferFresh) return storedGeo;
  }

  if(!navigator.geolocation){
    _lastGeoErrorMeta = buildGeoErrorMeta(null, { reason:'api_unavailable', message:'当前浏览器不支持 geolocation' });
    return storedGeo || null;
  }
  if(!canUseBrowserGeoNow()){
    _lastGeoErrorMeta = buildGeoErrorMeta(null, { reason:'insecure_context', message:'当前页面不是 HTTPS/localhost，浏览器不会返回定位' });
    console.warn('定位失败：当前页面不是 HTTPS/localhost，浏览器不会返回定位');
    return storedGeo || null;
  }

  const quick = !!options.quick || !!options.forChatRequest;
  const attempts = quick
    ? [{ enableHighAccuracy:false, timeout:2800, maximumAge:300000, step:'chat_request_quick' }]
    : [
        { enableHighAccuracy:true, timeout:8000, maximumAge:60000, step:'high_accuracy' },
        { enableHighAccuracy:false, timeout:12000, maximumAge:300000, step:'coarse_retry' },
      ];

  for(const attempt of attempts){
    try{
      const pos = await requestBrowserGeoOnce({
        enableHighAccuracy: !!attempt.enableHighAccuracy,
        timeout: Number(attempt.timeout) || 8000,
        maximumAge: Number(attempt.maximumAge) || 0,
      });
      const geo = rememberUserGeo({
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        acquired_at: Date.now(),
        source: attempt.step === 'coarse_retry' ? 'browser_live_retry' : 'browser_live',
      });
      _lastGeoErrorMeta = null;
      if(geo) return geo;
    }catch(err){
      _lastGeoErrorMeta = buildGeoErrorMeta(err, {
        step: attempt.step,
        timeout_ms: attempt.timeout,
        maximum_age_ms: attempt.maximumAge,
        enable_high_accuracy: attempt.enableHighAccuracy,
      });
      console.log('定位失败:', _lastGeoErrorMeta);
    }
  }

  return storedGeo || null;
}

function buildRuntimeTimePayload(){
  try{
    const nowDate = new Date();
    const tz = (()=>{
      try{ return String(Intl.DateTimeFormat().resolvedOptions().timeZone || '').trim(); }catch(_){ return ''; }
    })();
    return {
      epoch_ms: nowDate.getTime(),
      iso_utc: nowDate.toISOString(),
      timezone: tz,
      offset_minutes: -nowDate.getTimezoneOffset(),
      locale: String(navigator.language || '').trim(),
      source: 'browser_clock'
    };
  }catch(_){
    return null;
  }
}

function extractUrls(str){
  if(!str) return [];
  // 注意：先匹配出可能的 URL，再做清洗截断
  const re = /https?:\/\/[^\s)）\]】'"<>]+/ig;
  const m = str.match(re) || [];
  // 去重 + 限制数量
  const seen = new Set();
  const out = [];
  for(const u of m){
    const uu = trimUrl(u);
    if(!uu) continue;
    if(!seen.has(uu)){
      seen.add(uu);
      out.push(uu);
    }
    if(out.length>=3) break;
  }
  return out;
}


function formatWebpagesForSystem(pages){
  const blocks = [];
  for(const p of (pages||[])){
    if(p && p.error){
      blocks.push(`- URL: ${p.url}\n  抓取失败：${p.error}`);
      continue;
    }
    if(!p) continue;
    const title = (p.title||"").trim();
    const head = `- URL: ${p.final_url || p.url}${title?`\n  标题：${title}`:""}${p.content_type?`\n  类型：${p.content_type}`:""}${p.warning?`\n  备注：${p.warning}`:""}`;
    const body = (p.text||"").trim();
    blocks.push(head + (body?`\n  摘录：\n${body}`:""));
  }
  return blocks.join("\n\n");
}

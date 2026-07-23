# Split from app3_parts/auth/platform_auth_login_pages_part.py.
# Purpose: rate-limit admin page HTML renderer.
# Loaded by platform_auth_login_pages_part.py via _exec_split_file(...), sharing app3.py globals.

def _rate_limit_admin_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>限流</title>
  <style>
    body{margin:0;background:#0f1115;color:#eef2f6;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .wrap{max-width:1180px;margin:0 auto;padding:22px 14px 40px}
    h1{margin:0 0 8px;font-size:28px}
    .sub{color:#9da7b2;margin-bottom:18px;line-height:1.7}
    .toolbar,.card{background:#171a21;border:1px solid rgba(255,255,255,.08);border-radius:18px}
    .toolbar{padding:16px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
    .left,.right{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .pill{display:inline-flex;align-items:center;gap:8px;background:#0d1016;border:1px solid rgba(255,255,255,.08);border-radius:999px;padding:8px 12px;font-size:13px}
    .metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-top:14px}
    .metric{background:#171a21;border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:14px 16px}
    .metric .k{font-size:12px;color:#8fa0b3}.metric .v{font-size:22px;font-weight:800;margin-top:8px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:14px}
    .card{padding:16px}
    .card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}
    .title{font-size:16px;font-weight:800}.code{font-size:12px;color:#8fa0b3;margin-top:4px}
    .switch{display:flex;align-items:center;gap:8px;font-size:13px;color:#cdd7e2}
    .switch input{width:16px;height:16px}
    .kv{display:grid;grid-template-columns:56px 1fr 18px 1fr 28px;gap:8px;align-items:center;margin-top:10px}
    .kv label{font-size:12px;color:#8fa0b3}
    .kv input,.kv select,.row input,.row select{width:100%;border:1px solid rgba(255,255,255,.14);background:#0d1016;color:#fff;border-radius:12px;padding:10px 10px;font-size:14px;outline:none;box-sizing:border-box}
    .kv input:focus,.kv select:focus,.row input:focus,.row select:focus{border-color:#4f8cff;box-shadow:0 0 0 3px rgba(79,140,255,.18)}
    .slash,.unit{color:#8fa0b3;font-size:12px;text-align:center}
    .hint{margin-top:12px;font-size:12px;color:#8fa0b3;line-height:1.6}
    .stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px;font-size:12px;color:#aab4be}
    .stats div{background:#10141b;border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:10px 12px}
    .two{display:grid;grid-template-columns:1.15fr .85fr;gap:12px;margin-top:14px}
    table{width:100%;border-collapse:collapse;font-size:13px} th,td{padding:10px 8px;border-top:1px solid rgba(255,255,255,.06);text-align:left;vertical-align:top} th{color:#8fa0b3;font-weight:600} tr:first-child th,tr:first-child td{border-top:none}
    .list{display:flex;flex-direction:column;gap:10px}
    .event{padding:12px;border:1px solid rgba(255,255,255,.06);border-radius:14px;background:#10141b}
    .event .top{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:13px;font-weight:700}
    .event .meta{margin-top:6px;font-size:12px;color:#9da7b2;line-height:1.7}
    .manual-form{display:grid;grid-template-columns:120px minmax(0,1fr) 130px minmax(0,1fr) 108px;gap:10px;margin-top:12px}
    .row{display:flex;flex-direction:column;gap:6px}
    .row label{font-size:12px;color:#8fa0b3}
    .manual-actions{display:flex;align-items:flex-end}
    .manual-actions button{width:100%}
    .stack{display:flex;flex-direction:column;gap:12px}
    button{border:none;border-radius:12px;padding:10px 14px;font-size:14px;cursor:pointer}
    .ok{background:#238636;color:#fff}.warn{background:#b45309;color:#fff}.ghost{background:#30363d;color:#fff}.danger{background:#8b1e2d;color:#fff}
    .status{margin-top:12px;min-height:20px;color:#cfd6dd;font-size:13px}
    .empty{color:#94a3b8;font-size:13px;padding:4px 0}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
    .subtle{font-size:12px;color:#8fa0b3}
    .chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 8px;font-size:12px;border:1px solid rgba(255,255,255,.08);background:#0d1016;color:#cdd7e2}
    .rateTabs{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:#171a21;border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:8px;margin-top:14px}
    .rateTab{background:transparent;color:#b9c3d1;font-weight:700;padding:10px 16px;border:1px solid transparent}
    .rateTab:hover{background:rgba(255,255,255,.05);color:#fff}.rateTab.is-active{background:rgba(35,134,54,.22);border-color:rgba(46,160,67,.55);color:#d9ffe7}
    .ratePanel{display:none;margin-top:14px}.ratePanel.is-active{display:block}.ratePanel .grid{margin-top:0}
    @media (max-width:1100px){.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.manual-form{grid-template-columns:repeat(2,minmax(0,1fr))}.manual-actions{grid-column:1/-1}}
    @media (max-width:900px){.two{grid-template-columns:1fr}.toolbar{align-items:flex-start}}
    @media (max-width:720px){.metrics,.grid,.manual-form{grid-template-columns:1fr}.kv{grid-template-columns:48px 1fr 18px 1fr 28px}}
    /* formal admin route skin */
    body{background:#0f1114;color:#f2f4f7}
    .wrap{max-width:none;min-height:100vh;padding:16px 18px 22px 252px;background:#0f1114}
.wrap::before{content:"Apervia";white-space:pre-line;position:fixed;left:12px;top:14px;width:212px;padding:14px 12px 16px;border:1px solid #2b3038;border-radius:8px;background:#15171c;color:#f2f4f7;font-weight:760;line-height:1.45;box-sizing:border-box}
    .topbar{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;border-bottom:1px solid #2b3038;padding-bottom:12px;margin-bottom:12px}
    .topActions{position:fixed;left:12px;top:108px;width:212px;display:flex;flex-direction:column;gap:6px;z-index:10}
    .topActions a,.topActions button{width:100%;box-sizing:border-box;text-align:left}
    h1{font-size:24px}
    .sub{color:#a7afb9;max-width:900px}
    .toolbar,.card,.metric,.rateTabs{border-radius:8px;border-color:#2b3038;background:#181a1f}
    .event,.stats div,.pill{border-color:#2a2f37;background:#14161a;border-radius:8px}
    .pill,.chip{border-radius:4px}
    button,.kv input,.kv select,.row input,.row select{border-radius:6px;border-color:#343a44;background:#111318;color:#f3f5f7}
    button.ok{background:#173d2d;border-color:#2b7a55}
    button.warn{background:#402f13;border-color:#9a6917}
    button.ghost{background:#171a20;border-color:#3a414b}
    button.danger{background:#442023;border-color:#a44349}
    .rateTabs{padding:4px;gap:4px}
    .rateTab{border-radius:6px}
    .rateTab.is-active{background:#e8edf5;border-color:#e8edf5;color:#111318}
    @media(max-width:1180px){.wrap{padding:14px}.wrap::before{display:none}.topbar{display:block}.topActions{position:static;width:auto;flex-direction:row;flex-wrap:wrap;margin-top:12px}.topActions a,.topActions button{width:auto}}
    @media(max-width:720px){.topActions a,.topActions button{width:100%}.topActions{width:100%}}
  </style>
</head>
<body>
<div class="wrap">
  <div class="topbar"><div><h1 data-i18n="admin.rate.title">限流</h1>
  <div class="sub" data-i18n="admin.rate.subtitle">管理聊天、上传和登录相关接口的请求频率，可直接调整阈值并查看自动拦截和手动封禁。</div></div><div class="topActions"><a href="/blacklist-admin"><button class="ghost" type="button" data-i18n="admin.blacklist">黑名单</button></a><a href="/platform-admin"><button class="ok" type="button" data-i18n="admin.unified">统一后台</button></a></div></div>
  <div class="toolbar">
    <div class="left">
      <label class="pill"><input id="globalEnabled" type="checkbox"><span data-i18n="admin.rate.auto_enable">启用自动限流</span></label>
      <span class="pill"><span data-i18n="admin.rate.keep_prefix">最近记录保留</span> <input id="eventsKeep" type="number" min="20" max="400" step="10" style="width:72px;border:none;background:transparent;color:#fff;outline:none"> <span data-i18n="admin.rate.keep_suffix">条</span></span>
    </div>
    <div class="right">
      <button id="saveBtn" class="ok" type="button" data-i18n="admin.rate.save">保存设置</button>
      <button id="clearBlocksBtn" class="warn" type="button" data-i18n="admin.rate.clear_auto">清空自动封禁</button>
      <button id="clearStatsBtn" class="ghost" type="button" data-i18n="admin.rate.clear_stats">清空统计</button>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="k" data-i18n="admin.rate.endpoint_count">接口数量</div><div class="v" id="metricEndpoints">-</div></div>
    <div class="metric"><div class="k" data-i18n="admin.rate.allowed">已放行</div><div class="v" id="metricAllowed">-</div></div>
    <div class="metric"><div class="k" data-i18n="admin.rate.blocked">已拦截</div><div class="v" id="metricBlocked">-</div></div>
    <div class="metric"><div class="k" data-i18n="admin.rate.auto_blocks">自动封禁</div><div class="v" id="metricAutoActive">-</div></div>
    <div class="metric"><div class="k" data-i18n="admin.rate.manual_blocks">手动封禁</div><div class="v" id="metricManualActive">-</div></div>
  </div>
  <div class="rateTabs" role="tablist" aria-label="限流设置分页" data-i18n-aria-label="admin.rate.tabs">
    <button class="rateTab is-active" type="button" role="tab" aria-selected="true" data-rate-tab-button="rules" data-i18n="admin.rate.rules">接口限流</button>
    <button class="rateTab" type="button" role="tab" aria-selected="false" data-rate-tab-button="summary" data-i18n="admin.rate.summary">接口情况</button>
    <button class="rateTab" type="button" role="tab" aria-selected="false" data-rate-tab-button="manual" data-i18n="admin.rate.manual">手动封禁</button>
    <button class="rateTab" type="button" role="tab" aria-selected="false" data-rate-tab-button="events" data-i18n="admin.rate.events">拦截记录</button>
  </div>
  <section class="ratePanel is-active" data-rate-tab-panel="rules">
    <div id="endpointGrid" class="grid"></div>
  </section>
  <section class="ratePanel" data-rate-tab-panel="summary">
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px"><h2 style="margin:0;font-size:18px" data-i18n="admin.rate.summary">接口情况</h2><div id="updatedAt" class="code">-</div></div>
      <div style="margin-top:10px;overflow:auto">
        <table>
          <thead><tr><th data-i18n="admin.rate.endpoint">接口</th><th data-i18n="admin.rate.allowed">已放行</th><th data-i18n="admin.rate.blocked">已拦截</th><th data-i18n="admin.rate.active_blocks">当前封禁</th><th data-i18n="admin.rate.last_blocked">最近拦截</th></tr></thead>
          <tbody id="summaryTable"></tbody>
        </table>
      </div>
    </div>
  </section>
  <section class="ratePanel" data-rate-tab-panel="manual">
    <div class="card">
      <h2 style="margin:0 0 10px;font-size:18px" data-i18n="admin.rate.manual">手动封禁</h2>
      <div class="subtle" data-i18n="admin.rate.manual_help">这里是主机本地手动拦截，只拦 IP 或账号，不改主机网络层配置，也不影响其他账号。</div>
      <div class="manual-form">
        <div class="row"><label data-i18n="admin.rate.scope">对象类型</label><select id="manualScope"><option value="ip" data-i18n="admin.rate.ip">IP</option><option value="account" data-i18n="admin.rate.account">账号</option></select></div>
        <div class="row"><label data-i18n="admin.rate.target">对象值</label><input id="manualValue" type="text" placeholder="IP 或邮箱" data-i18n-placeholder="admin.rate.target_placeholder"></div>
        <div class="row"><label data-i18n="admin.rate.duration">持续秒数</label><input id="manualDuration" type="number" min="60" max="2592000" step="60" value="3600"></div>
        <div class="row"><label data-i18n="admin.rate.reason">原因</label><input id="manualReason" type="text" maxlength="120" placeholder="例如：疑似批量抓取" data-i18n-placeholder="admin.rate.reason_placeholder"></div>
        <div class="manual-actions"><button id="manualBlockBtn" class="danger" type="button" data-i18n="admin.rate.add">添加封禁</button></div>
      </div>
      <div class="hint" data-i18n="admin.rate.account_hint">账号填写完整登录邮箱。默认拦全部受保护接口。</div>
      <div id="manualList" class="list" style="margin-top:12px"></div>
    </div>
  </section>
  <section class="ratePanel" data-rate-tab-panel="events">
    <div class="card">
      <h2 style="margin:0 0 10px;font-size:18px" data-i18n="admin.rate.recent">最近拦截 / 自动封禁</h2>
      <div id="eventsList" class="list"></div>
    </div>
  </section>
  <div id="msg" class="status"></div>
</div>
<script src="/static/shared/i18n.js"></script><script src="/static/i18n/en.js"></script><script src="/static/i18n/zh-CN.js"></script><script src="/static/i18n/en-phrases.js"></script><script>window.AperviaI18n?.start({syncAccount:true});</script>
<script>
const rateT=(key,params=null,fallback='')=>window.AperviaI18n?.t(key,params,fallback)||fallback;
const ratePhrase=(value)=>window.AperviaI18n?.phrase(String(value??''))||String(value??'');
function setRateTab(name){
  const panels = Array.from(document.querySelectorAll('[data-rate-tab-panel]'));
  const active = panels.some((panel) => panel.getAttribute('data-rate-tab-panel') === name) ? name : 'rules';
  panels.forEach((panel) => panel.classList.toggle('is-active', panel.getAttribute('data-rate-tab-panel') === active));
  document.querySelectorAll('[data-rate-tab-button]').forEach((button) => {
    const selected = button.getAttribute('data-rate-tab-button') === active;
    button.classList.toggle('is-active', selected);
    button.setAttribute('aria-selected', selected ? 'true' : 'false');
  });
}
document.querySelectorAll('[data-rate-tab-button]').forEach((button) => {
  button.addEventListener('click', () => setRateTab(button.getAttribute('data-rate-tab-button') || 'rules'));
});
setRateTab('rules');
function esc(v){return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s] || s));}
function authHeaders(extra){ return Object.assign({}, extra || {}); }
function redirectToAdminGate(){ location.replace('/login?next=' + encodeURIComponent(location.pathname)); }
async function requestJson(url, options={}){
  const opts = Object.assign({cache:'no-store'}, options || {});
  opts.headers = authHeaders(opts.headers || {});
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.message || data.error || rateT('common.request_failed', null, '请求失败'));
    err.code = data.error || '';
    if (res.status === 401) {
      redirectToAdminGate();
    }
    throw err;
  }
  return data || {};
}
async function postJson(url, body){
  return requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})});
}
function renderEndpointCards(endpoints){
  const wrap = document.getElementById('endpointGrid');
  if(!Array.isArray(endpoints) || !endpoints.length){ wrap.innerHTML = `<div class="card empty">${esc(rateT('admin.rate.no_config'))}</div>`; return; }
  wrap.innerHTML = endpoints.map(ep => `
    <div class="card" data-endpoint="${esc(ep.name)}">
      <div class="card-head">
        <div><div class="title">${esc(ratePhrase(ep.label || ep.name))}</div><div class="code mono">${esc(ep.name)}</div></div>
        <label class="switch"><input type="checkbox" data-field="enabled" ${ep.enabled ? 'checked' : ''}>${esc(rateT('admin.rate.enabled'))}</label>
      </div>
      <div class="kv"><label>${esc(rateT('admin.rate.ip'))}</label><input type="number" min="0" max="500" data-field="ip_limit" value="${esc(ep.ip_limit)}"><div class="slash">/</div><input type="number" min="0" max="86400" data-field="ip_window_s" value="${esc(ep.ip_window_s)}"><div class="unit">${esc(rateT('admin.rate.seconds'))}</div></div>
      <div class="kv"><label>${esc(rateT('admin.rate.session'))}</label><input type="number" min="0" max="500" data-field="session_limit" value="${esc(ep.session_limit)}"><div class="slash">/</div><input type="number" min="0" max="86400" data-field="session_window_s" value="${esc(ep.session_window_s)}"><div class="unit">${esc(rateT('admin.rate.seconds'))}</div></div>
      <div class="kv"><label>${esc(rateT('admin.rate.account'))}</label><input type="number" min="0" max="500" data-field="account_limit" value="${esc(ep.account_limit)}"><div class="slash">/</div><input type="number" min="0" max="86400" data-field="account_window_s" value="${esc(ep.account_window_s)}"><div class="unit">${esc(rateT('admin.rate.seconds'))}</div></div>
      <div class="kv"><label>${esc(rateT('admin.rate.block_duration'))}</label><input type="number" min="0" max="86400" data-field="block_s" value="${esc(ep.block_s)}"><div class="slash"></div><input type="text" value="${esc(rateT('admin.rate.cooldown'))}" disabled><div class="unit">${esc(rateT('admin.rate.seconds'))}</div></div>
      <div class="hint">${esc(rateT('admin.rate.zero_hint'))}</div>
      <div class="stats">
        <div>${esc(rateT('admin.rate.allowed'))}: <strong>${esc(ep.allowed)}</strong><br>${esc(rateT('admin.rate.last_allowed'))}: ${esc(ep.last_allowed_at || '-')}</div>
        <div>${esc(rateT('admin.rate.blocked'))}: <strong>${esc(ep.blocked)}</strong><br>${esc(rateT('admin.rate.last_blocked'))}: ${esc(ep.last_blocked_at || '-')}</div>
        <div>${esc(rateT('admin.rate.current_blocks'))}: <strong>${esc(ep.active_blocks)}</strong><br>${esc(ep.last_reason || rateT('admin.rate.none'))}</div>
      </div>
    </div>`).join('');
}
function renderSummary(endpoints){
  const body = document.getElementById('summaryTable');
  if(!Array.isArray(endpoints) || !endpoints.length){ body.innerHTML = `<tr><td colspan="5" class="empty">${esc(rateT('admin.rate.no_data'))}</td></tr>`; return; }
  body.innerHTML = endpoints.map(ep => `<tr>
    <td>${esc(ratePhrase(ep.label || ep.name))}<br><span class="code">${esc(ep.enabled ? rateT('admin.rate.enabled') : rateT('admin.rate.disabled', null, 'Disabled'))}</span></td>
    <td>${esc(ep.allowed)}</td>
    <td>${esc(ep.blocked)}</td>
    <td>${esc(ep.active_blocks)}</td>
    <td>${esc(ep.last_blocked_at || '-')}</td>
  </tr>`).join('');
}
function renderManualBlocks(items){
  const el = document.getElementById('manualList');
  if(!Array.isArray(items) || !items.length){ el.innerHTML = `<div class="empty">${esc(rateT('admin.rate.no_manual'))}</div>`; return; }
  el.innerHTML = items.map(item => `
    <div class="event">
      <div class="top"><div>${esc(item.scope_label || item.scope || '-')} · ${esc(item.key_display || '-')}</div><div class="chip">${esc(rateT('admin.rate.remaining',{seconds:item.remaining_s}))}</div></div>
      <div class="meta">${esc(rateT('admin.rate.reason'))}: ${esc(item.reason || rateT('admin.rate.manual'))}<br>${esc(rateT('admin.rate.expires'))}: ${esc(item.until_text || '-')}<br>${esc(rateT('admin.rate.created'))}: ${esc(item.created_text || '-')}</div>
      <div style="margin-top:10px;display:flex;justify-content:flex-end"><button class="ghost" type="button" data-unblock-id="${esc(item.id || '')}">${esc(rateT('admin.rate.unblock'))}</button></div>
    </div>
  `).join('');
  el.querySelectorAll('[data-unblock-id]').forEach(btn => {
    btn.addEventListener('click', () => removeManualBlock(btn.getAttribute('data-unblock-id')));
  });
}
function renderEvents(events, autoActiveBlocks){
  const el = document.getElementById('eventsList');
  const rows = [];
  (autoActiveBlocks || []).slice(0, 8).forEach(item => rows.push({type:'active', ...item}));
  (events || []).slice(0, 12).forEach(item => rows.push({type:'event', ...item}));
  if(!rows.length){ el.innerHTML = `<div class="empty">${esc(rateT('admin.rate.no_events'))}</div>`; return; }
  el.innerHTML = rows.map(item => {
    const topRight = item.type === 'active' ? `剩余 ${esc(item.remaining_s)} 秒` : esc(item.ts_text || '-');
    const reason = item.reason || (item.type === 'active' ? '封禁中' : '触发限流');
    return `<div class="event">
      <div class="top"><div>${esc(item.endpoint_label || item.endpoint || '-')} · ${esc(item.scope_label || item.scope || '-')}</div><div>${topRight}</div></div>
      <div class="meta">对象：${esc(item.key_display || '-')}<br>原因：${esc(reason)}${item.window_s ? `<br>阈值：${esc(item.limit)} / ${esc(item.window_s)} 秒` : ''}</div>
    </div>`;
  }).join('');
}
function collectConfig(){
  const endpoints = {};
  document.querySelectorAll('[data-endpoint]').forEach(card => {
    const name = card.getAttribute('data-endpoint');
    const obj = {};
    card.querySelectorAll('[data-field]').forEach(input => {
      const field = input.getAttribute('data-field');
      obj[field] = input.type === 'checkbox' ? !!input.checked : Number(input.value || 0);
    });
    endpoints[name] = obj;
  });
  return {
    global_enabled: !!document.getElementById('globalEnabled').checked,
    events_keep: Number(document.getElementById('eventsKeep').value || 120),
    endpoints,
  };
}
function setMsg(text){ document.getElementById('msg').textContent = text || ''; }
async function refreshState(){
  const data = await requestJson('/api3/rate-limit/state');
  document.getElementById('globalEnabled').checked = !!data.global_enabled;
  document.getElementById('eventsKeep').value = Number(data.events_keep || 120);
  document.getElementById('metricEndpoints').textContent = String(data.summary?.endpoint_count || 0);
  document.getElementById('metricAllowed').textContent = String(data.summary?.total_allowed || 0);
  document.getElementById('metricBlocked').textContent = String(data.summary?.total_blocked || 0);
  document.getElementById('metricAutoActive').textContent = String(data.summary?.auto_active_blocks || 0);
  document.getElementById('metricManualActive').textContent = String(data.summary?.manual_blocks || 0);
  document.getElementById('updatedAt').textContent = rateT('admin.rate.updated', {time:data.updated_at || '-'});
  renderEndpointCards(data.endpoints || []);
  renderSummary(data.endpoints || []);
  renderManualBlocks(data.manual_blocks || []);
  renderEvents(data.recent_events || [], data.auto_active_blocks || []);
}
async function saveConfig(){
  setMsg('正在保存…');
  try{
    await postJson('/api3/rate-limit/config', collectConfig());
    setMsg('保存成功');
    await refreshState();
  }catch(err){
    setMsg(String(err.message || '保存失败'));
  }
}
async function resetState(body, okText){
  try{
    await postJson('/api3/rate-limit/reset', body);
    setMsg(okText);
    await refreshState();
  }catch(err){
    setMsg(String(err.message || '操作失败'));
  }
}
async function addManualBlock(){
  const scope = document.getElementById('manualScope').value;
  const key = document.getElementById('manualValue').value.trim();
  const duration_s = Number(document.getElementById('manualDuration').value || 3600);
  const reason = document.getElementById('manualReason').value.trim();
  if(!key){ setMsg('请先填写对象值'); return; }
  setMsg('正在添加手动封禁…');
  try{
    await postJson('/api3/rate-limit/manual-block', {scope, key, duration_s, reason});
    document.getElementById('manualValue').value = '';
    document.getElementById('manualReason').value = '';
    setMsg('已添加手动封禁');
    await refreshState();
  }catch(err){
    setMsg(String(err.message || '添加失败'));
  }
}
async function removeManualBlock(id){
  try{
    await postJson('/api3/rate-limit/manual-unblock', {id});
    setMsg('已解除手动封禁');
    await refreshState();
  }catch(err){
    setMsg(String(err.message || '解除失败'));
  }
}
document.getElementById('saveBtn').addEventListener('click', saveConfig);
document.getElementById('clearBlocksBtn').addEventListener('click', () => resetState({clear_blocks:true, clear_events:false, clear_stats:false}, '已清空自动封禁'));
document.getElementById('clearStatsBtn').addEventListener('click', () => resetState({clear_blocks:false, clear_events:true, clear_stats:true}, '已清空统计和记录'));
document.getElementById('manualBlockBtn').addEventListener('click', addManualBlock);
document.addEventListener('apervia:languagechange', () => refreshState().catch(() => {}));
setInterval(refreshState, 4000);
refreshState();
</script>
</body>
</html>"""

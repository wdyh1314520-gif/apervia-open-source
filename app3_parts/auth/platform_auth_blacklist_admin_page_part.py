# Split from app3_parts/auth/platform_auth_login_pages_part.py.
# Purpose: blacklist admin page HTML renderer.
# Loaded by platform_auth_login_pages_part.py via _exec_split_file(...), sharing app3.py globals.

def _blacklist_admin_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>黑名单面板</title>
  <style>
    body{margin:0;background:#0f1115;color:#eef2f6;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .wrap{max-width:1120px;margin:0 auto;padding:22px 14px 40px}
    .topbar{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap;margin-bottom:18px}
    h1{margin:0 0 8px;font-size:28px}
    .sub{color:#9da7b2;line-height:1.7;max-width:820px}
    .actions{display:flex;gap:10px;flex-wrap:wrap}
    button{border-radius:12px;border:1px solid #2a3340;background:#121722;color:#eef2f6;padding:10px 12px;font-size:14px;cursor:pointer}
    .card{background:#151b27;border:1px solid #273142;border-radius:18px;padding:18px}
    .summary{margin-bottom:16px;color:#d7dfeb;line-height:1.8}
    .list{display:flex;flex-direction:column;gap:12px}
    .row{border:1px solid #273142;border-radius:16px;padding:14px;background:#101620;display:flex;justify-content:space-between;gap:14px;align-items:flex-start}
    .meta{font-size:13px;color:#c8d0dc;line-height:1.7}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
    .pill{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;border:1px solid #304055;background:#182131;font-size:12px;margin-right:8px;margin-bottom:8px}
    .tmp{border-color:#8a3a20;color:#ffbe9c}
    .perm{border-color:#913c45;color:#ffb3bb}
    .empty{color:#9da7b2}
    @media (max-width:860px){.row{flex-direction:column}}
    /* formal admin route skin */
    body{background:#0f1114;color:#f2f4f7}
    .wrap{max-width:none;min-height:100vh;padding:16px 18px 22px 252px;background:#0f1114}
.wrap::before{content:"Apervia";white-space:pre-line;position:fixed;left:12px;top:14px;width:212px;padding:14px 12px 16px;border:1px solid #2b3038;border-radius:8px;background:#15171c;color:#f2f4f7;font-weight:760;line-height:1.45;box-sizing:border-box}
    .topbar>.actions{position:fixed;left:12px;top:108px;width:212px;display:flex;flex-direction:column;gap:6px;z-index:10}
    .topbar>.actions a,.topbar>.actions button{width:100%;box-sizing:border-box;text-align:left}
    .topbar{border-bottom:1px solid #2b3038;padding-bottom:12px;margin-bottom:12px}
    .topbar h1{font-size:24px}
    .sub{color:#a7afb9}
    .card{border-radius:8px;border-color:#2b3038;background:#181a1f}
    .row{border-radius:8px;border-color:#2a2f37;background:#14161a}
    button{border-radius:6px;border-color:#3a414b;background:#20242b}
    .pill{border-radius:4px;background:#20242c}
    .summary{border:1px solid #2b3038;border-radius:8px;background:#14161a;padding:12px}
    @media(max-width:1180px){.wrap{padding:14px}.wrap::before{display:none}.topbar>.actions{position:static;width:auto;flex-direction:row;flex-wrap:wrap}.topbar>.actions a,.topbar>.actions button{width:auto}}
  </style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <h1 data-i18n="admin.blacklist.title">黑名单</h1>
      <div class="sub" data-i18n="admin.blacklist.subtitle">查看被临时拉黑或永久封禁的账号。临时拉黑到期后会自动转为永久封禁，管理员可在这里解封。</div>
    </div>
    <div class="actions">
      <a href="/rate-admin"><button type="button" data-i18n="admin.rate_limit">限流</button></a>
        <a href="/platform-admin"><button type="button" data-i18n="admin.unified">统一后台</button></a>
    </div>
  </div>
  <div class="card">
    <div id="summary" class="summary" data-i18n="common.loading">载入中…</div>
    <div id="blacklistList" class="list" data-i18n="common.loading">载入中…</div>
  </div>
</div>
<script src="/static/shared/i18n.js"></script><script src="/static/i18n/en.js"></script><script src="/static/i18n/zh-CN.js"></script><script src="/static/i18n/en-phrases.js"></script><script>window.AperviaI18n?.start({syncAccount:true});</script>
<script>
const blacklistT=(key,params=null,fallback='')=>window.AperviaI18n?.t(key,params,fallback)||fallback;
function esc(v){return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s] || s));}
function authHeaders(extra){ return Object.assign({}, extra || {}); }
function redirectToAdminGate(){ location.replace('/login?next=' + encodeURIComponent(location.pathname)); }
async function requestJson(url, options={}){ const opts = Object.assign({cache:'no-store'}, options || {}); opts.headers = authHeaders(opts.headers || {}); const res = await fetch(url, opts); const data = await res.json().catch(() => ({})); if(!res.ok){ const err = new Error(data.message || data.error || blacklistT('common.request_failed',null,'请求失败')); err.code = data.error || ''; if(res.status === 401) redirectToAdminGate(); throw err; } return data || {}; }
async function postJson(url, body){ return requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})}); }
function renderUsers(users){ const el = document.getElementById('blacklistList'); const summary = document.getElementById('summary'); const total = Array.isArray(users) ? users.length : 0; const permanent = (users || []).filter((item) => item.blacklist_permanent).length; const temporary = total - permanent; summary.textContent = blacklistT('admin.blacklist.summary',{total,temporary,permanent}); if(!users || !users.length){ el.innerHTML = `<div class="empty">${esc(blacklistT('admin.blacklist.empty'))}</div>`; return; } el.innerHTML = users.map((user) => { const pill = user.blacklist_permanent ? `<span class="pill perm">${esc(blacklistT('admin.blacklist.permanent'))}</span>` : `<span class="pill tmp">${esc(blacklistT('admin.blacklist.temporary',{days:Number(user.blacklist_remaining_days || 0)}))}</span>`; const lines = []; if(user.blacklist_reason) lines.push(esc(blacklistT('admin.blacklist.reason')) + ': ' + esc(user.blacklist_reason)); if(user.blacklisted_at) lines.push(esc(blacklistT('admin.blacklist.blocked_at')) + ': ' + esc(user.blacklisted_at)); if(user.blacklist_deadline_at && !user.blacklist_permanent) lines.push(esc(blacklistT('admin.blacklist.permanent_at')) + ': ' + esc(user.blacklist_deadline_at)); if(user.blacklist_permanent_at) lines.push(esc(blacklistT('admin.blacklist.permanent')) + ': ' + esc(user.blacklist_permanent_at)); if(user.last_login_at) lines.push(esc(blacklistT('admin.blacklist.last_login')) + ': ' + esc(user.last_login_at)); if(user.last_login_ip) lines.push(esc(blacklistT('admin.blacklist.last_ip')) + ': ' + esc(user.last_login_ip)); if(user.last_active_at) lines.push(esc(blacklistT('admin.blacklist.last_active')) + ': ' + esc(user.last_active_at)); return `<div class="row"><div><div>${pill}<span class="mono">${esc(user.email || user.email_masked || '-')}</span></div><div class="meta">${lines.join('<br>') || '-'}</div></div><div><button type="button" data-unblacklist-email="${esc(user.email || '')}">${esc(blacklistT('admin.blacklist.unblock'))}</button></div></div>`; }).join(''); }
async function refreshList(){ const data = await requestJson('/api3/auth/blacklist'); renderUsers(data.users || []); }
document.addEventListener('click', async (e) => { const btn = e.target.closest('button[data-unblacklist-email]'); if(!btn) return; const email = btn.getAttribute('data-unblacklist-email') || ''; if(!confirm(blacklistT('admin.blacklist.confirm'))) return; try{ await postJson('/api3/auth/user-blacklist', { email, blocked:false }); await refreshList(); }catch(err){ alert(err.message || blacklistT('common.request_failed')); } });
refreshList().catch((err) => { document.getElementById('summary').textContent = err.message || blacklistT('admin.blacklist.load_failed'); document.getElementById('blacklistList').innerHTML = `<div class="empty">${esc(blacklistT('admin.blacklist.load_failed'))}</div>`; });
document.addEventListener('apervia:languagechange', () => refreshList().catch(()=>{}));
window.addEventListener('focus', () => { refreshList().catch(()=>{}); });
document.addEventListener('visibilitychange', () => { if(document.visibilityState === 'visible') refreshList().catch(()=>{}); });
setInterval(() => { if(document.visibilityState === 'visible') refreshList().catch(()=>{}); }, 10000);
</script>
</body>
</html>"""

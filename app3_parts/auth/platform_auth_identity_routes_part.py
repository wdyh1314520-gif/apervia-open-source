# 统一身份页面与管理员入口。


def _auth_identity_safe_next(value: str = '') -> str:
    target = str(value or '/').strip() or '/'
    if not target.startswith('/') or target.startswith('//') or target.startswith('/login'):
        return '/'
    return target


def _auth_identity_register_http(data: dict | None = None):
    payload = data if isinstance(data, dict) else {}
    limit_resp = _apply_rate_limit('auth_register', email=str(payload.get('email') or ''))
    if limit_resp is not None:
        return limit_resp
    try:
        user = _auth_identity_register(
            str(payload.get('email') or ''),
            str(payload.get('password') or ''),
            str(payload.get('name') or payload.get('display_name') or ''),
        )
    except ValueError as exc:
        return _json_no_store({'error': 'registration_failed', 'message': str(exc)}, 400)
    if user.get('status') == 'pending' or user.get('role') == 'pending':
        return _json_no_store({'ok': True, 'pending': True, 'user': user}, 201)
    token, signed_in_user = _auth_identity_create_session(str(user.get('id') or ''))
    resp = _json_no_store({'ok': True, 'pending': False, 'user': signed_in_user, 'admin_url': '/admin' if signed_in_user.get('role') == 'admin' else ''}, 201)
    return _auth_identity_set_session_cookie(resp, token)


def _auth_identity_password_login_http(data: dict | None = None):
    payload = data if isinstance(data, dict) else {}
    limit_resp = _apply_rate_limit('auth_password_login', email=str(payload.get('email') or ''))
    if limit_resp is not None:
        return limit_resp
    try:
        token, user = _auth_identity_sign_in(str(payload.get('email') or ''), str(payload.get('password') or ''))
    except PermissionError as exc:
        return _json_no_store({'error': 'account_not_active', 'message': str(exc)}, 403)
    except ValueError as exc:
        return _json_no_store({'error': 'invalid_credentials', 'message': str(exc)}, 401)
    resp = _json_no_store({'ok': True, 'pending': False, 'user': user, 'admin_url': '/admin' if user.get('role') == 'admin' else ''})
    return _auth_identity_set_session_cookie(resp, token)


def _auth_identity_login_html() -> str:
    return r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sign in to Apervia</title>
  <style>
    *{box-sizing:border-box}html,body{min-height:100%}body{margin:0;background:#f7f7f8;color:#171717;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
    .page{min-height:100vh;display:grid;grid-template-columns:minmax(320px,1fr) minmax(420px,560px)}
    .intro{padding:clamp(38px,7vw,96px);display:flex;flex-direction:column;justify-content:space-between;background:linear-gradient(145deg,#111827,#172033 58%,#24324b);color:#fff}
    .brand{font-size:19px;font-weight:760;letter-spacing:.01em}.introMain{max-width:620px}.intro h1{font-size:clamp(40px,5vw,72px);line-height:1.04;margin:0 0 22px;letter-spacing:-.045em}.intro p{max-width:570px;color:#c7d2e2;font-size:17px;line-height:1.75;margin:0}
    .introFoot{color:#8fa0b8;font-size:13px}.auth{display:flex;align-items:center;justify-content:center;padding:32px;background:#fff}.card{width:min(390px,100%)}
    .eyebrow{font-size:13px;color:#6b7280;margin-bottom:12px}.card h2{font-size:30px;letter-spacing:-.025em;margin:0 0 9px}.hint{font-size:14px;color:#6b7280;line-height:1.65;margin-bottom:28px}
    .tabs{display:grid;grid-template-columns:1fr 1fr;background:#f1f2f4;border-radius:12px;padding:4px;margin-bottom:22px}.tab{border:0;background:transparent;border-radius:9px;padding:10px;color:#616773;cursor:pointer;font-weight:650}.tab.active{background:#fff;color:#111827;box-shadow:0 1px 5px rgba(0,0,0,.09)}
    .field{margin-bottom:14px}.field label{display:block;font-size:13px;font-weight:650;margin-bottom:7px}.field input{width:100%;border:1px solid #d6d8dc;border-radius:11px;padding:12px 13px;font-size:15px;outline:none;background:#fff}.field input:focus{border-color:#111827;box-shadow:0 0 0 3px rgba(17,24,39,.08)}
    .submit{width:100%;border:0;border-radius:11px;padding:12px 15px;background:#111827;color:#fff;font-size:15px;font-weight:700;cursor:pointer;margin-top:7px}.submit:disabled{opacity:.55;cursor:wait}.msg{min-height:23px;margin-top:15px;font-size:13px;line-height:1.6;color:#64748b}.msg.error{color:#b42318}.msg.ok{color:#087443}.hidden{display:none!important}
    .pending{margin-top:18px;border:1px solid #f2d59b;background:#fff9e9;color:#775a16;border-radius:12px;padding:12px 13px;font-size:13px;line-height:1.65}.adminNote{margin-top:18px;color:#8a9099;font-size:12px;line-height:1.6}.languageRow{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:0 0 20px;font-size:13px;color:#6b7280}.languageRow select{border:1px solid #d6d8dc;border-radius:9px;background:#fff;padding:7px 28px 7px 10px;color:#20242c;font:inherit}
    @media(max-width:860px){.page{display:block}.intro{min-height:260px;padding:34px 28px}.intro h1{font-size:40px;margin-top:45px}.introFoot{display:none}.auth{min-height:calc(100vh - 260px);padding:38px 24px}}
  </style>
</head>
<body>
<main class="page">
  <section class="intro">
    <div class="brand">Apervia</div>
    <div class="introMain"><h1 data-i18n="login.intro_title">Continue your intelligent workspace here.</h1><p data-i18n="login.intro_desc">Continue conversations, organize knowledge and files, and connect the models and tools you use. Everything stays organized and ready when you return.</p></div>
    <div class="introFoot" data-i18n="login.intro_footer">Your workspace · Knowledge that grows · Create whenever you are ready</div>
  </section>
  <section class="auth">
    <div class="card">
      <div class="eyebrow" data-i18n="login.eyebrow">Apervia account</div>
      <h2 id="title">Welcome back</h2>
      <div id="hint" class="hint">Sign in to continue to your workspace.</div>
      <label class="languageRow"><span data-i18n="login.language">Language</span><select id="language" aria-label="Language" data-i18n-aria-label="login.language"><option value="en">English</option><option value="zh-CN">简体中文</option></select></label>
      <div class="tabs"><button id="signinTab" class="tab active" type="button" data-i18n="login.sign_in">Sign in</button><button id="signupTab" class="tab" type="button" data-i18n="login.register">Register</button></div>
      <form id="form">
        <div id="nameField" class="field hidden"><label for="name" data-i18n="login.display_name">Display name</label><input id="name" maxlength="80" autocomplete="name" placeholder="Your name" data-i18n-placeholder="login.name_placeholder"></div>
        <div class="field"><label for="email" data-i18n="login.email">Email</label><input id="email" type="email" autocomplete="email" required placeholder="name@example.com"></div>
        <div class="field"><label for="password" data-i18n="login.password">Password</label><input id="password" type="password" autocomplete="current-password" required placeholder="At least 6 characters with uppercase, lowercase, and a number" data-i18n-placeholder="login.password_placeholder"></div>
        <button id="submit" class="submit" type="submit" data-i18n="login.sign_in">Sign in</button>
      </form>
      <div id="pending" class="pending hidden" data-i18n="login.pending_notice">Account created and awaiting administrator approval. You can sign in after approval.</div>
      <div id="msg" class="msg"></div>
      <div class="adminNote" data-i18n="login.first_user_notice">On a new deployment, the first registered account becomes the administrator. Later accounts require administrator approval.</div>
    </div>
  </section>
</main>
<script src="/static/shared/i18n.js"></script><script src="/static/i18n/en.js"></script><script src="/static/i18n/zh-CN.js"></script><script src="/static/i18n/en-phrases.js"></script>
<script>
let mode='signin';let signupEnabled=true;
const $=id=>document.getElementById(id);const t=(key,params=null,fallback='')=>window.AperviaI18n?.t(key,params,fallback)||fallback;const msg=(text,type='')=>{$('msg').textContent=String(text||'');$('msg').className='msg '+type};
function nextPath(){const p=new URLSearchParams(location.search).get('next')||'/';return p.startsWith('/')&&!p.startsWith('//')&&!p.startsWith('/login')?p:'/'}
function applyMode(next){mode=next==='signup'?'signup':'signin';const signup=mode==='signup';$('signinTab').classList.toggle('active',!signup);$('signupTab').classList.toggle('active',signup);$('nameField').classList.toggle('hidden',!signup);$('title').textContent=signup?t('login.create_account',null,'Create account'):t('login.welcome',null,'Welcome back');$('hint').textContent=signup?t('login.create_hint',null,'Create your Apervia account and start building your workspace.'):t('login.welcome_hint',null,'Sign in to continue to your workspace.');$('submit').textContent=signup?t('login.create_account',null,'Create account'):t('login.sign_in',null,'Sign in');$('password').autocomplete=signup?'new-password':'current-password';$('pending').classList.add('hidden');msg('')}
function authError(data,status){const code=String(data?.error||'');if(code==='invalid_credentials')return t('login.invalid_credentials',null,'Incorrect email address or password');if(code==='account_not_active')return t('login.account_not_active',null,'This account is not active yet');if(code==='registration_failed')return data?.message||t('login.registration_failed',null,'Unable to create the account');return data?.message||code||t('common.request_failed',null,'Request failed')}
async function requestJson(url,body){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{}),cache:'no-store'});const data=await res.json().catch(()=>({}));if(!res.ok){const err=new Error(authError(data,res.status));err.status=res.status;err.code=data.error||'';throw err}return data}
async function load(){try{const me=await fetch('/api3/auth/me',{cache:'no-store'}).then(r=>r.json());if(me?.logged_in){location.replace(nextPath());return}const state=await fetch('/api3/auth/status',{cache:'no-store'}).then(r=>r.json());signupEnabled=state?.signup_enabled!==false||state?.first_user===true;$('signupTab').disabled=!signupEnabled;if(state?.first_user===true)applyMode('signup')}catch(_){}}
$('signinTab').onclick=()=>applyMode('signin');$('signupTab').onclick=()=>{if(signupEnabled)applyMode('signup')};
$('form').addEventListener('submit',async e=>{e.preventDefault();const button=$('submit');button.disabled=true;msg(mode==='signup'?t('login.creating',null,'Creating account…'):t('login.signing_in',null,'Signing in…'));try{const body={email:$('email').value,password:$('password').value,name:$('name').value};const data=await requestJson(mode==='signup'?'/api3/auth/register':'/api3/auth/password-login',body);if(data.pending){$('pending').classList.remove('hidden');msg(t('login.registered_pending',null,'Registration complete. Awaiting administrator approval.'),'ok');return}msg(t('login.success',null,'Signed in. Opening your workspace…'),'ok');location.replace(nextPath())}catch(err){msg(err.message||t('common.operation_failed',null,'Operation failed'),'error')}finally{button.disabled=false}});
$('language').value=window.AperviaI18n?.language||'en';$('language').onchange=()=>window.AperviaI18n?.setLanguage($('language').value).then(()=>applyMode(mode));document.addEventListener('apervia:languagechange',()=>{document.title=t('login.page_title',null,'Sign in to Apervia');$('language').value=window.AperviaI18n?.language||'en';applyMode(mode)});window.AperviaI18n?.start();document.title=t('login.page_title',null,'Sign in to Apervia');applyMode('signin');load();
</script>
</body></html>'''


def _auth_identity_admin_html() -> str:
    return r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Apervia 管理后台</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f7;color:#1c1d1f;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}.shell{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{background:#111827;color:#fff;padding:24px 16px;position:sticky;top:0;height:100vh}.brand{font-size:18px;font-weight:760;padding:0 10px 26px}.navLabel{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#77849a;padding:12px 10px 7px}.nav a{display:block;color:#c6cfdb;text-decoration:none;padding:10px;border-radius:9px;font-size:14px;margin:2px 0}.nav a:hover,.nav a.active{background:#253047;color:#fff}.main{padding:34px clamp(22px,4vw,58px)}.top{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:28px}.top h1{font-size:30px;letter-spacing:-.025em;margin:0 0 7px}.sub{color:#6b7280;font-size:14px}.logout{border:1px solid #d5d8dc;background:#fff;border-radius:9px;padding:9px 13px;cursor:pointer}.metrics{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:12px;margin-bottom:20px}.metric,.card{background:#fff;border:1px solid #e1e3e6;border-radius:14px}.metric{padding:16px}.metric span{display:block;color:#737985;font-size:12px;margin-bottom:8px}.metric b{font-size:25px}.card{overflow:hidden}.cardHead{padding:17px 18px;border-bottom:1px solid #eceef0;display:flex;justify-content:space-between;align-items:center}.cardHead h2{font-size:16px;margin:0}.tableWrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:820px}th,td{text-align:left;padding:13px 16px;border-bottom:1px solid #f0f1f2;font-size:13px}th{color:#6f7681;font-weight:650;background:#fafbfb}.identity b{display:block;font-size:14px;margin-bottom:3px}.identity span{color:#747b86}.pill{display:inline-flex;border-radius:999px;padding:4px 8px;background:#eef1f4;color:#4b5563;font-size:12px}.pill.admin{background:#e7edff;color:#2448a3}.pill.pending{background:#fff3d6;color:#8b5d00}.pill.disabled{background:#fee9e7;color:#a12b24}select,input{border:1px solid #d6d9dd;background:#fff;border-radius:8px;padding:7px 8px;font-size:13px}.save{border:0;background:#111827;color:#fff;border-radius:8px;padding:8px 10px;cursor:pointer}.msg{min-height:22px;color:#68707c;font-size:13px;margin-top:14px}.msg.error{color:#b42318}@media(max-width:920px){.shell{display:block}.side{position:static;height:auto}.nav{display:flex;overflow:auto}.navLabel{display:none}.nav a{white-space:nowrap}.main{padding:24px 16px}.metrics{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div class="shell"><aside class="side"><div class="brand">Apervia Admin</div><div class="navLabel" data-i18n="admin.identity.section">身份与访问</div><nav class="nav"><a class="active" href="/admin" data-i18n="admin.identity.user_management">用户管理</a><a href="/platform-admin" data-i18n="admin.identity.platform_data">平台与数据</a><a href="/storage-admin" data-i18n="admin.identity.storage">存储管理</a><a href="/rate-admin" data-i18n="admin.identity.security">安全与限流</a><a href="/blacklist-admin" data-i18n="admin.identity.blacklist_legacy">黑名单记录</a><a href="/" data-i18n="admin.back_to_app">返回应用</a></nav></aside><main class="main"><div class="top"><div><h1 data-i18n="admin.identity.title">用户与权限</h1><div class="sub" data-i18n="admin.identity.subtitle">统一管理账号状态、系统角色和会话访问。</div></div><button id="logout" class="logout" data-i18n="admin.sign_out">退出登录</button></div><section id="metrics" class="metrics"></section><section class="card"><div class="cardHead"><h2 data-i18n="admin.identity.all_users">全部用户</h2><button id="refresh" class="logout" data-i18n="admin.identity.refresh">刷新</button></div><div class="tableWrap"><table><thead><tr><th data-i18n="admin.identity.user">用户</th><th data-i18n="admin.identity.role">角色</th><th data-i18n="admin.identity.status">状态</th><th data-i18n="admin.identity.last_login">最近登录</th><th data-i18n="admin.identity.created">创建时间</th><th data-i18n="admin.identity.actions">操作</th></tr></thead><tbody id="users"></tbody></table></div></section><div id="msg" class="msg"></div></main></div>
<script src="/static/shared/i18n.js"></script><script src="/static/i18n/en.js"></script><script src="/static/i18n/zh-CN.js"></script><script src="/static/i18n/en-phrases.js"></script><script>window.AperviaI18n?.start({syncAccount:true});</script>
<script>
const t=(key,fallback='')=>window.AperviaI18n?.t(key,null,fallback)||fallback;const esc=v=>String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));const msg=(text,e=false)=>{const el=document.getElementById('msg');el.textContent=String(text||'');el.className='msg '+(e?'error':'')};
async function api(url,opt={}){const res=await fetch(url,Object.assign({cache:'no-store'},opt));const data=await res.json().catch(()=>({}));if(res.status===401){location.replace('/login?next=/admin');throw new Error(t('admin.login_required','请先登录'))}if(!res.ok)throw new Error(data.message||data.error||t('common.request_failed','请求失败'));return data}
function renderMetrics(s){const items=[['admin.identity.total_users',s.total],['admin.identity.admins',s.admin],['admin.identity.members',s.user],['admin.identity.pending',s.pending],['admin.identity.sessions',s.active_sessions]];document.getElementById('metrics').innerHTML=items.map(x=>`<div class="metric"><span>${esc(t(x[0]))}</span><b>${Number(x[1]||0)}</b></div>`).join('')}
function renderUsers(rows){document.getElementById('users').innerHTML=(rows||[]).map(u=>`<tr><td class="identity"><b>${esc(u.name||'-')}</b><span>${esc(u.email||'')}</span></td><td><select data-role="${esc(u.id)}"><option value="admin" ${u.role==='admin'?'selected':''}>${esc(t('admin.identity.role_admin'))}</option><option value="user" ${u.role==='user'?'selected':''}>${esc(t('admin.identity.role_user'))}</option><option value="pending" ${u.role==='pending'?'selected':''}>${esc(t('admin.identity.pending'))}</option></select></td><td><select data-status="${esc(u.id)}"><option value="active" ${u.status==='active'?'selected':''}>${esc(t('admin.identity.status_active'))}</option><option value="pending" ${u.status==='pending'?'selected':''}>${esc(t('admin.identity.pending'))}</option><option value="disabled" ${u.status==='disabled'?'selected':''}>${esc(t('admin.identity.status_disabled'))}</option></select></td><td>${esc(u.last_login_at||'-')}</td><td>${esc(u.created_at||'-')}</td><td><button class="save" data-save="${esc(u.id)}">${esc(t('common.save'))}</button></td></tr>`).join('')}
async function load(){msg(t('admin.identity.reading','正在读取…'));const [summary,users]=await Promise.all([api('/api3/admin/summary'),api('/api3/admin/users')]);renderMetrics(summary.summary||{});renderUsers(users.users||[]);msg('')}
document.addEventListener('click',async e=>{const btn=e.target.closest('[data-save]');if(!btn)return;const id=btn.dataset.save;btn.disabled=true;try{await api('/api3/admin/users/'+encodeURIComponent(id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:document.querySelector(`[data-role="${CSS.escape(id)}"]`).value,status:document.querySelector(`[data-status="${CSS.escape(id)}"]`).value})});msg(t('admin.identity.updated'));await load()}catch(err){msg(err.message,true)}finally{btn.disabled=false}});document.getElementById('refresh').onclick=()=>load().catch(e=>msg(e.message,true));document.getElementById('logout').onclick=async()=>{await api('/api3/auth/logout',{method:'POST'}).catch(()=>{});location.replace('/login')};document.addEventListener('apervia:languagechange',()=>load().catch(()=>{}));load().catch(e=>msg(e.message,true));
</script></body></html>'''


@app.get('/admin')
def auth_identity_admin_page():
    user = _auth_identity_current_user()
    if not user:
        return redirect('/login?next=/admin', code=302)
    if str(user.get('role') or '') != 'admin':
        return Response('需要管理员权限', status=403, mimetype='text/plain; charset=utf-8')
    return _local_admin_html_response(_auth_identity_admin_html())


@app.get('/api3/admin/summary')
def auth_identity_admin_summary_route():
    guard = _auth_identity_admin_guard()
    if guard is not None:
        return guard
    return _json_no_store({'ok': True, 'summary': _auth_identity_admin_summary()})


@app.get('/api3/admin/users')
def auth_identity_admin_users_route():
    guard = _auth_identity_admin_guard()
    if guard is not None:
        return guard
    return _json_no_store({'ok': True, 'users': _auth_identity_admin_users()})


@app.patch('/api3/admin/users/<user_id>')
def auth_identity_admin_user_update_route(user_id):
    guard = _auth_identity_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        user = _auth_identity_admin_update_user(
            str(user_id or ''),
            role=data.get('role') if 'role' in data else None,
            status=data.get('status') if 'status' in data else None,
            name=data.get('name') if 'name' in data else None,
        )
    except ValueError as exc:
        return _json_no_store({'error': 'invalid_user_update', 'message': str(exc)}, 400)
    return _json_no_store({'ok': True, 'user': user})

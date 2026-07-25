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
    except _AuthIdentityAccessError as exc:
        return _json_no_store({'error': exc.code, 'reason_code': exc.code, 'message': str(exc)}, 403)
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
  <title>Apervia Admin</title>
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
function authError(data,status){const code=String(data?.error||'');if(code==='invalid_credentials')return t('login.invalid_credentials',null,'Incorrect email address or password');if(code==='account_pending'||code==='account_not_active')return t('login.account_not_active',null,'This account is not active yet');if(code==='account_blacklisted')return t('login.account_blacklisted',null,'This account has been blacklisted. Contact an administrator to restore access.');if(code==='account_disabled')return t('login.account_disabled',null,'This account has been disabled. Contact an administrator.');if(code==='account_deleted')return t('login.account_deleted',null,'This account has been deleted and cannot sign in.');if(code==='account_delete_pending')return t('login.account_delete_pending',null,'This account is pending deletion. Restore it before signing in.');if(code==='registration_failed')return data?.message||t('login.registration_failed',null,'Unable to create the account');return data?.message||code||t('common.request_failed',null,'Request failed')}
async function requestJson(url,body){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{}),cache:'no-store'});const data=await res.json().catch(()=>({}));if(!res.ok){const err=new Error(authError(data,res.status));err.status=res.status;err.code=data.error||'';throw err}return data}
async function load(){try{const me=await fetch('/api3/auth/me',{cache:'no-store'}).then(r=>r.json());if(me?.logged_in){location.replace(nextPath());return}const state=await fetch('/api3/auth/status',{cache:'no-store'}).then(r=>r.json());signupEnabled=state?.signup_enabled!==false||state?.first_user===true;$('signupTab').disabled=!signupEnabled;if(state?.first_user===true)applyMode('signup')}catch(_){}}
$('signinTab').onclick=()=>applyMode('signin');$('signupTab').onclick=()=>{if(signupEnabled)applyMode('signup')};
$('form').addEventListener('submit',async e=>{e.preventDefault();const button=$('submit');button.disabled=true;msg(mode==='signup'?t('login.creating',null,'Creating account…'):t('login.signing_in',null,'Signing in…'));try{const body={email:$('email').value,password:$('password').value,name:$('name').value};const data=await requestJson(mode==='signup'?'/api3/auth/register':'/api3/auth/password-login',body);if(data.pending){$('pending').classList.remove('hidden');msg(t('login.registered_pending',null,'Registration complete. Awaiting administrator approval.'),'ok');return}msg(t('login.success',null,'Signed in. Opening your workspace…'),'ok');location.replace(nextPath())}catch(err){msg(err.message||t('common.operation_failed',null,'Operation failed'),'error')}finally{button.disabled=false}});
$('language').value=window.AperviaI18n?.language||'en';$('language').onchange=()=>window.AperviaI18n?.setLanguage($('language').value).then(()=>applyMode(mode));document.addEventListener('apervia:languagechange',()=>{document.title=t('login.page_title',null,'Sign in to Apervia');$('language').value=window.AperviaI18n?.language||'en';applyMode(mode)});window.AperviaI18n?.start();document.title=t('login.page_title',null,'Sign in to Apervia');applyMode('signin');load();
</script>
</body></html>'''


@app.get('/admin')
def auth_identity_admin_page():
    user = _auth_identity_current_user()
    if not user:
        return redirect('/login?next=/admin', code=302)
    if str(user.get('role') or '') != 'admin':
        return Response('需要管理员权限', status=403, mimetype='text/plain; charset=utf-8')
    return _admin_html_response(_platform_admin_html())


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


@app.get('/api3/admin/rate-limit/state')
def auth_identity_admin_rate_limit_state_route():
    guard = _auth_identity_admin_guard()
    if guard is not None:
        return guard
    return _json_no_store(_rate_limit_public_state())


@app.post('/api3/admin/rate-limit/config')
def auth_identity_admin_rate_limit_config_route():
    guard = _auth_identity_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        state = _rate_limit_update_config(data)
    except ValueError as exc:
        return _json_no_store({'error': 'invalid_rate_limit_config', 'message': str(exc)}, 400)
    return _json_no_store(state)

@app.post('/api3/admin/rate-limit/reset')
def auth_identity_admin_rate_limit_reset_route():
    guard = _auth_identity_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    state = _rate_limit_reset(
        clear_blocks=bool(data.get('clear_blocks', True)),
        clear_events=bool(data.get('clear_events', True)),
        clear_stats=bool(data.get('clear_stats', False)),
    )
    return _json_no_store(state)

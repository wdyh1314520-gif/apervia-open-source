/* Apervia MCP server directory, permissions, and chat approval integration. */

const MCP_DEVELOPER_MODE_KEY = "webai_mcp_developer_mode_v1";
let mcpServersCache = [];
let mcpActiveServerId = "";
let mcpEditorMode = "edit";
let mcpOauthPending = null;
let mcpOauthPollTimer = 0;
let mcpOauthPollDeadline = 0;
let mcpActiveView = "list";

function mcpUiT(key, params=null, fallback=""){
  return window.AperviaI18n?.t(key, params, fallback) || String(fallback || key || "");
}

function purgeLegacyMcpBrowserStorage(){
  const prefix="webai_mcp_servers_v1";
  try{
    const keys=[];
    for(let index=0;index<localStorage.length;index+=1){
      const key=String(localStorage.key(index) || "");
      if(key === prefix || key.startsWith(`${prefix}::acct::`)) keys.push(key);
    }
    keys.forEach(key=>localStorage.removeItem(key));
  }catch(_){ }
}

const MCP_PERMISSION_META = {
  always_ask:{labelKey:"settings.mcp.permission.always_ask", fallback:"Always ask"},
  allow_read:{labelKey:"settings.mcp.permission.allow_read", fallback:"Allow reads"},
  allow_low_risk:{labelKey:"settings.mcp.permission.allow_low_risk", fallback:"Allow low-risk actions"},
  allow_all:{labelKey:"settings.mcp.permission.allow_all", fallback:"Allow all actions", risk:"high"},
};

function mcpPermissionLabel(mode){
  const meta=MCP_PERMISSION_META[mode] || MCP_PERMISSION_META.allow_low_risk;
  return mcpUiT(meta.labelKey, null, meta.fallback);
}

function mcpServerIconSvg(){
  return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.1 17.3H7a3.8 3.8 0 0 1-.45-7.57A5 5 0 0 1 16.2 8a4 4 0 0 1 .8 7.92h-1.1"/><path d="M9.2 13.2h5.6m-4.6-2v2m3.6-2v2M10 13.2v1.5a2 2 0 0 0 4 0v-1.5M12 16.7v2"/></svg>';
}

function isMcpDeveloperModeEnabled(){
  return String(readAccountScopedSettingItem(MCP_DEVELOPER_MODE_KEY) || "") === "1";
}

function setMcpDeveloperModeEnabled(enabled){
  writeAccountScopedSettingItem(MCP_DEVELOPER_MODE_KEY, enabled ? "1" : "0");
  syncMcpDeveloperModeUi();
}

function syncMcpDeveloperModeUi(){
  const enabled=isMcpDeveloperModeEnabled();
  const toggle=document.getElementById("accountDeveloperModeToggle");
  const addButton=document.getElementById("mcpNewBtn");
  if(toggle) toggle.checked=enabled;
  if(addButton){
    addButton.classList.toggle("locked", !enabled);
    addButton.setAttribute("aria-label", globalThis.AperviaI18n?.t(enabled ? 'settings.mcp.add_server' : 'settings.mcp.enable_developer_to_add') || (enabled ? "Add MCP server" : "Enable developer mode to add an MCP server"));
    addButton.title=enabled ? "" : (globalThis.AperviaI18n?.t('settings.mcp.developer_required') || "Enable developer mode before adding an MCP server");
  }
  return enabled;
}

async function openMcpDeveloperModeSettings(){
  try{
    if(typeof requestActivateSettingsTab === "function") await requestActivateSettingsTab("account");
    else if(typeof activateSettingsTab === "function") activateSettingsTab("account");
  }catch(_){ }
  const row=document.getElementById("accountDeveloperModeRow");
  try{ row?.scrollIntoView?.({block:"center", behavior:"smooth"}); }catch(_){ }
  document.getElementById("accountDeveloperModeToggle")?.focus();
  try{ toast(window.AperviaI18n?.t('settings.mcp.developer_required') || "Enable developer mode before adding an MCP server"); }catch(_){ }
}

function mcpStableId(value=""){
  const clean = String(value || "").trim().replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return clean || `server_${Date.now().toString(36)}`;
}

function normalizeMcpTool(raw){
  const item = raw && typeof raw === "object" ? raw : {};
  const annotations = item.annotations && typeof item.annotations === "object" ? item.annotations : {};
  const inputSchema = item.inputSchema && typeof item.inputSchema === "object"
    ? item.inputSchema
    : (item.input_schema && typeof item.input_schema === "object" ? item.input_schema : {type:"object", properties:{}});
  const readOnly = (annotations.readOnlyHint === true || item.read_only === true) && annotations.destructiveHint !== true;
  let risk = String(item.risk || "").toLowerCase();
  if(!["read","low","high"].includes(risk)) risk = readOnly ? "read" : ((annotations.destructiveHint === true || annotations.openWorldHint === true) ? "high" : "low");
  return {
    name:String(item.name || "").trim().slice(0, 200),
    title:String(item.title || item.name || "").trim().slice(0, 200),
    description:String(item.description || "").trim().slice(0, 4000),
    inputSchema,
    annotations,
    enabled:item.enabled !== false,
    read_only:readOnly,
    risk,
  };
}

function normalizeMcpServer(raw){
  const item = raw && typeof raw === "object" ? raw : {};
  const authType = ["none","bearer","oauth"].includes(String(item.auth_type || "").toLowerCase()) ? String(item.auth_type).toLowerCase() : "oauth";
  const transport = ["auto","streamable_http","sse"].includes(String(item.transport || "").toLowerCase()) ? String(item.transport).toLowerCase() : "auto";
  const permissionMode = ["always_ask","allow_read","allow_low_risk","allow_all"].includes(String(item.permission_mode || "").toLowerCase())
    ? String(item.permission_mode).toLowerCase() : "allow_low_risk";
  return {
    id:mcpStableId(item.id || item.server_id || item.name),
    name:String(item.name || item.id || "MCP Server").trim().slice(0, 120),
    url:String(item.url || item.server_url || "").trim().slice(0, 2000),
    enabled:item.enabled !== false,
    auth_type:authType,
    credential_configured:item.credential_configured === true,
    connected:item.connected === true,
    token_expires_at:Math.max(0, Number(item.token_expires_at || 0) || 0),
    oauth_client_id:String(item.oauth_client_id || "apervia").trim().slice(0, 500) || "apervia",
    oauth:item.oauth && typeof item.oauth === "object" ? item.oauth : {},
    transport,
    permission_mode:permissionMode,
    allow_insecure_local:false,
    tools:(Array.isArray(item.tools) ? item.tools : []).map(normalizeMcpTool).filter(tool=>tool.name).slice(0, 50),
    scanned_at:Number(item.scanned_at || 0) || 0,
  };
}

function getMcpServers(){
  return (Array.isArray(mcpServersCache) ? mcpServersCache : []).map(normalizeMcpServer).slice(0, 6);
}

function saveMcpServers(rows){
  const normalized = (Array.isArray(rows) ? rows : []).map(normalizeMcpServer).slice(0, 6);
  mcpServersCache = normalized;
  return normalized;
}

async function fetchMcpServers(){
  const response=await fetch("/api3/mcp/servers", {credentials:"same-origin", cache:"no-store"});
  const data=await response.json().catch(()=>({}));
  if(!response.ok || !data.ok){
    const code=String(data.error || '').trim();
    const message=code === 'login_required'
      ? (window.AperviaI18n?.t('common.login_required') || 'Please sign in first')
      : (data.message || data.error || `HTTP ${response.status}`);
    const error=new Error(message);
    error.code=code;
    throw error;
  }
  return saveMcpServers(Array.isArray(data.servers) ? data.servers : []);
}

async function persistMcpServer(server){
  const payload={...server};
  const response=await fetch("/api3/mcp/servers", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({server:payload})});
  const data=await response.json().catch(()=>({}));
  if(!response.ok || !data.ok || !data.server) throw new Error(data.message || data.error || `HTTP ${response.status}`);
  return replaceSavedMcpServer(normalizeMcpServer(data.server)).find(item=>item.id === data.server.id) || normalizeMcpServer(data.server);
}

function mcpTokenValid(server){
  if(server.auth_type !== "oauth" && server.auth_type !== "bearer") return true;
  if(!server.credential_configured) return false;
  return !server.token_expires_at || server.token_expires_at > (Math.floor(Date.now()/1000) + 30);
}

function currentMcpServer(){
  const rows = getMcpServers();
  return rows.find(server=>server.id === mcpActiveServerId) || rows[0] || null;
}

function mcpServerConnected(server){
  if(!server) return false;
  return server.connected === true || (server.enabled && mcpTokenValid(server));
}

function closeMcpMoreMenu(){
  const menu=document.getElementById("mcpMoreMenu");
  const button=document.getElementById("mcpMoreBtn");
  if(menu) menu.hidden=true;
  if(button) button.setAttribute("aria-expanded", "false");
}

function showMcpView(view="list"){
  const target=["list","detail","permission","connection"].includes(view) ? view : "list";
  mcpActiveView=target;
  document.querySelectorAll('[data-mcp-view]').forEach(panel=>{
    const active=panel.getAttribute("data-mcp-view") === target;
    panel.hidden=!active;
    panel.classList.toggle("active", active);
  });
  const connectionBack=document.querySelector('[data-mcp-view="connection"] [data-mcp-back]');
  if(connectionBack) connectionBack.dataset.mcpBack=mcpEditorMode === "new" ? "list" : "detail";
  closeMcpMoreMenu();
  const panel=document.querySelector('[data-settings-panel="mcp"]');
  if(panel) panel.scrollTop=0;
}

function syncMcpPermissionUi(server=currentMcpServer()){
  const mode=server?.permission_mode || document.getElementById("mcpPermissionMode")?.value || "allow_low_risk";
  const meta=MCP_PERMISSION_META[mode] || MCP_PERMISSION_META.allow_low_risk;
  const hidden=document.getElementById("mcpPermissionMode");
  if(hidden) hidden.value=mode;
  const summary=document.getElementById("mcpPermissionSummary");
  if(summary){
    summary.textContent=mcpPermissionLabel(mode);
    summary.classList.toggle("danger", meta.risk === "high");
  }
  document.querySelectorAll('[data-mcp-permission-mode]').forEach(button=>{
    const selected=button.dataset.mcpPermissionMode === mode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-checked", selected ? "true" : "false");
  });
}

function renderMcpDetail(server=currentMcpServer()){
  if(!server) return;
  const connected=mcpServerConnected(server);
  const name=document.getElementById("mcpDetailName");
  const permissionName=document.getElementById("mcpPermissionServerName");
  const status=document.getElementById("mcpCurrentStatus");
  const connection=document.getElementById("mcpConnectionSummary");
  if(name) name.textContent=server.name;
  if(permissionName) permissionName.textContent=server.name;
  if(status){
    status.textContent=connected
      ? mcpUiT('settings.mcp.connected_to', {name:server.name}, `Connected to ${server.name}`)
      : mcpUiT(server.enabled ? 'settings.mcp.needs_connection' : 'settings.mcp.disabled', null, server.enabled ? 'Needs connection' : 'Disabled');
    status.dataset.kind=connected ? "ok" : "";
  }
  if(connection) connection.textContent=server.url || mcpUiT('settings.mcp.address_missing', null, 'No server address');
  const disconnectAction=document.querySelector('[data-mcp-action="disconnect"]');
  if(disconnectAction) disconnectAction.hidden=!server.credential_configured;
  syncMcpPermissionUi(server);
  renderMcpToolList(server);
}

function readMcpServerForm(){
  const name = String(document.getElementById("mcpServerName")?.value || "").trim() || "MCP Server";
  const existing = mcpEditorMode === "edit" ? currentMcpServer() : null;
  const normalized=normalizeMcpServer({
    ...(existing || {}),
    id:existing?.id || mcpStableId(name),
    name,
    url:String(document.getElementById("mcpServerUrl")?.value || "").trim(),
    transport:document.getElementById("mcpTransport")?.value || "auto",
    auth_type:document.getElementById("mcpAuthType")?.value || "oauth",
    oauth_client_id:"apervia",
    enabled:!!document.getElementById("mcpServerEnabled")?.checked,
    permission_mode:document.getElementById("mcpPermissionMode")?.value || "allow_low_risk",
    allow_insecure_local:false,
  });
  const bearerToken=document.getElementById("mcpAuthType")?.value === "bearer"
    ? String(document.getElementById("mcpBearerToken")?.value || "").trim() : "";
  return bearerToken ? {...normalized, bearer_token:bearerToken} : normalized;
}

function setMcpSettingsHint(text="", kind=""){
  const el = document.getElementById("mcpSettingsHint");
  if(!el) return;
  el.textContent = String(text || "");
  el.dataset.kind = String(kind || "");
}

function syncMcpAuthUi(){
  const type = document.getElementById("mcpAuthType")?.value || "oauth";
  const bearer = document.getElementById("mcpBearerField");
  const oauth = document.getElementById("mcpOauthFields");
  if(bearer){ bearer.hidden = type !== "bearer"; bearer.style.display = type === "bearer" ? "" : "none"; }
  if(oauth){ oauth.hidden = type !== "oauth"; oauth.style.display = type === "oauth" ? "" : "none"; }
  const connect = document.getElementById("mcpConnectBtn");
  if(connect) connect.hidden = type !== "oauth";
}

function mcpRiskLabel(tool){
  if(tool.risk === "read") return mcpUiT('settings.mcp.risk.read', null, 'Read');
  if(tool.risk === "low") return mcpUiT('settings.mcp.risk.low_action', null, 'Low-risk action');
  return mcpUiT('settings.mcp.risk.high', null, 'High risk');
}

function replaceSavedMcpServer(next){
  const rows = getMcpServers();
  const index = rows.findIndex(item=>item.id === next.id);
  if(index >= 0) rows[index] = normalizeMcpServer(next); else rows.push(normalizeMcpServer(next));
  return saveMcpServers(rows);
}

function renderMcpToolList(server=currentMcpServer()){
  const wrap = document.getElementById("mcpToolList");
  if(!wrap) return;
  const tools = Array.isArray(server?.tools) ? server.tools : [];
  wrap.innerHTML = "";
  if(!tools.length){
    const empty=document.createElement('div');
    empty.className='settings-empty';
    empty.textContent=mcpUiT('settings.mcp.tools_empty', null, 'No tools scanned yet.');
    wrap.appendChild(empty);
    return;
  }
  for(const tool of tools){
    const row = document.createElement("details");
    row.className = "mcp-tool-row" + (tool.enabled ? "" : " blocked");
    const summary = document.createElement("summary");
    const copy = document.createElement("span");
    copy.className = "mcp-tool-copy";
    const title = document.createElement("strong");
    title.textContent = tool.title || tool.name;
    const desc = document.createElement("small");
    desc.textContent = tool.description || tool.name;
    copy.append(title, desc);
    const controls = document.createElement("span");
    controls.className = "mcp-tool-controls";
    const badge = document.createElement("span");
    badge.className = `settings-badge mcp-risk-${tool.risk}`;
    badge.textContent = mcpRiskLabel(tool);
    const toggle = document.createElement("label");
    toggle.className = "ui-switch";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = tool.enabled;
    input.setAttribute("aria-label", mcpUiT('settings.mcp.enable_tool', {name:tool.title || tool.name}, `Enable ${tool.title || tool.name}`));
    const track = document.createElement("span");
    track.setAttribute("aria-hidden", "true");
    toggle.append(input, track);
    controls.append(badge, toggle);
    summary.append(copy, controls);
    const body=document.createElement("div");
    body.className="mcp-tool-body";
    const schemaHead=document.createElement("div");
    schemaHead.className="mcp-tool-schema-head";
    const schemaTitle=document.createElement("strong");
    schemaTitle.textContent=mcpUiT('settings.mcp.input_schema', null, 'Input schema');
    const copyButton=document.createElement("button");
    copyButton.type="button";
    copyButton.textContent=mcpUiT('settings.mcp.copy', null, 'Copy');
    copyButton.addEventListener("click", async event=>{
      event.preventDefault();
      event.stopPropagation();
      try{
        await navigator.clipboard.writeText(JSON.stringify(tool.inputSchema || {}, null, 2));
        toast(window.AperviaI18n?.t('settings.mcp.schema_copied') || "Input schema copied");
      }catch(_){ try{ toast(window.AperviaI18n?.t('settings.mcp.copy_failed') || "Copy failed"); }catch(__){ } }
    });
    schemaHead.append(schemaTitle, copyButton);
    const schema=document.createElement("pre");
    schema.textContent=JSON.stringify(tool.inputSchema || {}, null, 2);
    body.append(schemaHead, schema);
    row.append(summary, body);
    input.addEventListener("change", async ()=>{
      const current = currentMcpServer();
      if(!current) return;
      current.tools = current.tools.map(item=>item.name === tool.name ? {...item, enabled:input.checked} : item);
      replaceSavedMcpServer(current);
      renderMcpSavedList();
      row.classList.toggle("blocked", !input.checked);
      try{ await persistMcpServer(current); }
      catch(err){ input.checked=!input.checked; await fetchMcpServers().catch(()=>{}); renderMcpSavedList(); renderMcpDetail(currentMcpServer()); setMcpSettingsHint(mcpUiT('settings.mcp.tool_state_save_failed', {error:String(err?.message || err)}, `Unable to save tool state: ${String(err?.message || err)}`), "error"); }
    });
    toggle.addEventListener("click", event=>event.stopPropagation());
    input.addEventListener("click", event=>event.stopPropagation());
    wrap.appendChild(row);
  }
}

function fillMcpForm(server=currentMcpServer()){
  const row = server || normalizeMcpServer({name:"", enabled:true, auth_type:"oauth"});
  const assign = (id, value)=>{ const el=document.getElementById(id); if(el) el.value=value; };
  assign("mcpServerName", row.name || "");
  assign("mcpServerUrl", row.url || "");
  assign("mcpTransport", row.transport || "auto");
  assign("mcpAuthType", row.auth_type || "oauth");
  assign("mcpBearerToken", "");
  const bearerInput=document.getElementById("mcpBearerToken");
  if(bearerInput) bearerInput.placeholder=row.auth_type === "bearer" && row.credential_configured
    ? mcpUiT('settings.mcp.bearer_saved', null, 'Encrypted on the server; leave blank to keep it')
    : mcpUiT('settings.mcp.bearer_store', null, 'Encrypted on the server after saving');
  assign("mcpPermissionMode", row.permission_mode || "allow_low_risk");
  const checks = {mcpServerEnabled:row.enabled !== false};
  for(const [id,value] of Object.entries(checks)){ const el=document.getElementById(id); if(el) el.checked=!!value; }
  const title=document.getElementById("mcpConnectionTitle");
  if(title) title.textContent=window.AperviaI18n?.t(mcpEditorMode === "new" ? 'settings.mcp.add_server' : 'settings.mcp.connection_settings') || (mcpEditorMode === "new" ? "Add MCP server" : "Connection settings");
  const connect = document.getElementById("mcpConnectBtn");
  if(connect) connect.textContent = mcpUiT(row.credential_configured ? 'settings.mcp.reconnect' : 'settings.mcp.connect', null, row.credential_configured ? 'Reconnect' : 'Connect');
  const disconnect = document.getElementById("mcpDisconnectBtn");
  if(disconnect) disconnect.hidden = !row.credential_configured;
  const deleteButton=document.getElementById("mcpDeleteBtn");
  if(deleteButton) deleteButton.hidden=mcpEditorMode === "new";
  syncMcpAuthUi();
  syncMcpPermissionUi(row);
  if(mcpEditorMode !== "new") renderMcpDetail(row);
  setMcpSettingsHint(row.scanned_at ? mcpUiT('settings.mcp.last_scan', {time:new Date(row.scanned_at).toLocaleString()}, `Last scan: ${new Date(row.scanned_at).toLocaleString()}`) : "", "");
}

function renderMcpSavedList(){
  const wrap = document.getElementById("mcpSavedList");
  if(!wrap) return;
  const rows = getMcpServers();
  const count = document.getElementById("mcpServerCount");
  if(count) count.textContent = window.AperviaI18n?.t('settings.mcp.server_count', {count:rows.length}) || `${rows.length} servers`;
  wrap.innerHTML = "";
  if(!rows.length){
    const empty=document.createElement('div');
    empty.className='settings-empty';
    empty.textContent=mcpUiT('settings.mcp.servers_empty', null, 'No MCP servers saved yet.');
    wrap.appendChild(empty);
    return;
  }
  for(const server of rows){
    const btn=document.createElement("button");
    btn.type="button";
    btn.className="mcp-server-list-item";
    const available=server.tools.filter(tool=>tool.enabled).length;
    const icon=document.createElement("span");
    icon.className="mcp-server-list-icon";
    icon.innerHTML=mcpServerIconSvg();
    const main=document.createElement("span");
    main.className="mcp-server-list-copy";
    const title=document.createElement("strong"); title.textContent=server.name;
    const stateKey = mcpServerConnected(server) ? 'settings.mcp.connected' : (server.enabled ? 'settings.mcp.needs_connection' : 'settings.mcp.disabled');
    const stateLabel = window.AperviaI18n?.t(stateKey) || (mcpServerConnected(server) ? "Connected" : (server.enabled ? "Needs connection" : "Disabled"));
    const toolLabel = window.AperviaI18n?.t('settings.mcp.tool_count', {available, total:server.tools.length}) || `${available}/${server.tools.length} tools`;
    const meta=document.createElement("small"); meta.textContent=`${stateLabel} · ${toolLabel}`;
    main.append(title, meta);
    const permission=document.createElement("span");
    permission.className="mcp-server-list-permission";
    permission.textContent=mcpPermissionLabel(server.permission_mode);
    const chevron=document.createElement("span");
    chevron.className="mcp-server-list-chevron";
    chevron.textContent="›";
    btn.append(icon, main, permission, chevron);
    btn.addEventListener("click", ()=>{
      mcpActiveServerId=server.id;
      mcpEditorMode="edit";
      fillMcpForm(server);
      renderMcpDetail(server);
      showMcpView("detail");
    });
    wrap.appendChild(btn);
  }
}

async function hydrateMcpSettingsUi(){
  setMcpSettingsHint(window.AperviaI18n?.t('settings.mcp.directory_loading') || "Loading the MCP directory…", "loading");
  try{
    const rows=await fetchMcpServers();
    if(!rows.some(server=>server.id === mcpActiveServerId)) mcpActiveServerId=rows[0]?.id || "";
    syncMcpDeveloperModeUi();
    renderMcpSavedList();
    fillMcpForm(currentMcpServer());
    showMcpView("list");
    setMcpSettingsHint("", "");
  }catch(err){
    saveMcpServers([]);
    renderMcpSavedList();
    setMcpSettingsHint(window.AperviaI18n?.t('settings.mcp.directory_load_failed', {error:String(err?.message || err)}) || `Unable to load the MCP directory: ${String(err?.message || err)}`, "error");
  }
}

async function scanMcpServer(server=readMcpServerForm()){
  if(!server.url){ setMcpSettingsHint(window.AperviaI18n?.t('settings.mcp.url_required') || "Enter the MCP Server URL first.", "error"); return null; }
  const btn=document.getElementById("mcpScanBtn");
  if(btn) btn.disabled=true;
  setMcpSettingsHint(mcpUiT('settings.mcp.scan_connecting', null, 'Connecting and reading tools/list…'), "loading");
  try{
    const saved=await persistMcpServer(server);
    if(["oauth","bearer"].includes(saved.auth_type) && !saved.credential_configured){
      throw new Error(saved.auth_type === "oauth"
        ? mcpUiT('settings.mcp.oauth_required', null, 'Connect and complete MCP authorization first.')
        : mcpUiT('settings.mcp.bearer_required', null, 'Enter and save a Bearer Token first.'));
    }
    const res=await fetch("/api3/mcp/scan", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({server_id:saved.id})});
    const data=await res.json().catch(()=>({}));
    if(!res.ok || !data.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
    const next=normalizeMcpServer(data.server || {});
    mcpActiveServerId=next.id;
    mcpEditorMode="edit";
    replaceSavedMcpServer(next);
    renderMcpSavedList();
    fillMcpForm(next);
    renderMcpDetail(next);
    showMcpView("detail");
    setMcpSettingsHint(mcpUiT('settings.mcp.scan_succeeded', {count:next.tools.length}, `Connected. ${next.tools.length} tools found.`), "ok");
    try{ toast(window.AperviaI18n?.t('settings.mcp.connect_success', {count:next.tools.length}) || `MCP connected: ${next.tools.length} tools`); }catch(_){ }
    return next;
  }catch(err){
    setMcpSettingsHint(mcpUiT('settings.mcp.connect_failed', {error:String(err?.message || err)}, `Connection failed: ${String(err?.message || err)}`), "error");
    return null;
  }finally{ if(btn) btn.disabled=false; }
}

async function startMcpOauthConnect(){
  if(mcpEditorMode === "new" && !isMcpDeveloperModeEnabled()){
    await openMcpDeveloperModeSettings();
    return;
  }
  const server=readMcpServerForm();
  if(!server.url){ setMcpSettingsHint(window.AperviaI18n?.t('settings.mcp.url_required') || "Enter the MCP Server URL first.", "error"); return; }
  const popup=window.open("about:blank", "apervia_mcp_oauth", "popup=yes,width=720,height=760");
  if(!popup){ setMcpSettingsHint(mcpUiT('settings.mcp.popup_blocked', null, 'The authorization window was blocked. Allow pop-ups and try again.'), "error"); return; }
  popup.document.write(`<!doctype html><meta charset="utf-8"><title>${mcpUiT('settings.mcp.oauth_title', null, 'MCP authorization')}</title><p style="font-family:system-ui;padding:32px">${mcpUiT('settings.mcp.oauth_preparing', null, 'Preparing MCP authorization…')}</p>`);
  const btn=document.getElementById("mcpConnectBtn");
  if(btn) btn.disabled=true;
  setMcpSettingsHint(mcpUiT('settings.mcp.oauth_discovering', null, 'Discovering MCP OAuth configuration…'), "loading");
  try{
    const saved=await persistMcpServer({...server, auth_type:"oauth"});
    const response=await fetch("/api3/mcp/oauth/start", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({server_id:saved.id})});
    const data=await response.json().catch(()=>({}));
    if(!response.ok || !data.ok || !data.authorization_url) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    mcpOauthPending={state:String(data.state || ""), server:saved, popup};
    mcpOauthPollDeadline=Date.now() + 10 * 60 * 1000;
    scheduleMcpOauthResultPoll(700);
    popup.location.replace(data.authorization_url);
    setMcpSettingsHint(mcpUiT('settings.mcp.oauth_continue', null, 'Continue in the MCP authorization window. Your password is never shared with Apervia.'), "loading");
  }catch(err){
    stopMcpOauthResultPoll();
    mcpOauthPending=null;
    try{ popup.close(); }catch(_){ }
    setMcpSettingsHint(mcpUiT('settings.mcp.oauth_start_failed', {error:String(err?.message || err)}, `Unable to start authorization: ${String(err?.message || err)}`), "error");
  }finally{ if(btn) btn.disabled=false; }
}

function stopMcpOauthResultPoll(){
  if(mcpOauthPollTimer) clearTimeout(mcpOauthPollTimer);
  mcpOauthPollTimer=0;
  mcpOauthPollDeadline=0;
}

function scheduleMcpOauthResultPoll(delay=900){
  if(mcpOauthPollTimer) clearTimeout(mcpOauthPollTimer);
  if(!mcpOauthPending) return;
  mcpOauthPollTimer=setTimeout(()=>{ pollMcpOauthResult().catch(()=>{}); },Math.max(250,Number(delay || 0)));
}

async function applyMcpOauthResult(data={}){
  if(!mcpOauthPending) return false;
  if(String(data.type || "") !== "apervia:mcp-oauth") return false;
  if(String(data.state || "") !== String(mcpOauthPending.state || "")) return false;
  const pending=mcpOauthPending;
  mcpOauthPending=null;
  stopMcpOauthResultPoll();
  if(!data.ok){ setMcpSettingsHint(mcpUiT('settings.mcp.oauth_failed', {error:String(data.message || mcpUiT('settings.mcp.oauth_denied', null, 'Authorization was denied by the server'))}, `Authorization failed: ${String(data.message || 'Authorization was denied by the server')}`), "error"); return; }
  const next=normalizeMcpServer(data.server || pending.server);
  mcpActiveServerId=next.id;
  mcpEditorMode="edit";
  replaceSavedMcpServer(next);
  fillMcpForm(next);
  renderMcpSavedList();
  setMcpSettingsHint(mcpUiT('settings.mcp.oauth_success', null, 'Authorization succeeded. Scanning tools…'), "ok");
  await scanMcpServer(next);
  return true;
}

async function pollMcpOauthResult(){
  mcpOauthPollTimer=0;
  const pending=mcpOauthPending;
  if(!pending) return;
  if(mcpOauthPollDeadline && Date.now() >= mcpOauthPollDeadline){
    mcpOauthPending=null;
    stopMcpOauthResultPoll();
    setMcpSettingsHint(mcpUiT('settings.mcp.oauth_timeout', null, 'MCP authorization timed out. Reconnect and try again.'), "error");
    return;
  }
  try{
    const response=await fetch(`/api3/mcp/oauth/result?state=${encodeURIComponent(String(pending.state || ""))}`, {credentials:"same-origin", cache:"no-store"});
    const data=await response.json().catch(()=>({}));
    if(response.status === 404 || data.pending){ scheduleMcpOauthResultPoll(900); return; }
    if(!response.ok || !data.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    if(await applyMcpOauthResult(data.result || {})) return;
  }catch(_){ }
  if(mcpOauthPending) scheduleMcpOauthResultPoll(1100);
}

async function handleMcpOauthMessage(event){
  if(event.origin !== location.origin) return;
  const data=event.data && typeof event.data === "object" ? event.data : {};
  await applyMcpOauthResult(data);
}

async function disconnectMcpServer(){
  const current=currentMcpServer();
  if(!current) return;
  try{
    const response=await fetch(`/api3/mcp/servers/${encodeURIComponent(current.id)}/disconnect`, {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:"{}"});
    const data=await response.json().catch(()=>({}));
    if(!response.ok || !data.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    const next=normalizeMcpServer(data.server || {...current, credential_configured:false, connected:false, token_expires_at:0});
    replaceSavedMcpServer(next);
    fillMcpForm(next);
    renderMcpSavedList();
    renderMcpDetail(next);
    setMcpSettingsHint(mcpUiT('settings.mcp.disconnected', null, 'Disconnected. Encrypted server credentials were cleared.'), "ok");
  }catch(err){ setMcpSettingsHint(mcpUiT('settings.mcp.disconnect_failed', {error:String(err?.message || err)}, `Unable to disconnect: ${String(err?.message || err)}`), "error"); }
}

async function setMcpPermissionMode(mode){
  const nextMode=MCP_PERMISSION_META[mode] ? mode : "allow_low_risk";
  const current=currentMcpServer();
  if(!current) return;
  const next=normalizeMcpServer({...current, permission_mode:nextMode});
  replaceSavedMcpServer(next);
  syncMcpPermissionUi(next);
  renderMcpSavedList();
  setMcpSettingsHint(mcpUiT('settings.mcp.permission_updated', {mode:mcpPermissionLabel(nextMode)}, `Permission updated to “${mcpPermissionLabel(nextMode)}”.`), "ok");
  try{ await persistMcpServer(next); }
  catch(err){ await fetchMcpServers().catch(()=>{}); renderMcpSavedList(); renderMcpDetail(currentMcpServer()); setMcpSettingsHint(mcpUiT('settings.mcp.permission_save_failed', {error:String(err?.message || err)}, `Unable to save permission: ${String(err?.message || err)}`), "error"); }
}

async function deleteCurrentMcpServer(returnFocusEl=document.getElementById("mcpDeleteBtn")){
  const current=currentMcpServer();
  if(!current || mcpEditorMode === "new") return false;
  const ok=await askKbDangerConfirm({title:window.AperviaI18n?.t('settings.mcp.delete_title') || "Delete MCP server?",desc:window.AperviaI18n?.t('settings.mcp.delete_desc', {name:current.name}) || `This deletes the address, token, and tool cache for “${current.name}”.`,confirmText:window.AperviaI18n?.t('common.delete') || "Delete",cancelText:window.AperviaI18n?.t('common.cancel') || "Cancel"},returnFocusEl);
  if(!ok) return false;
  const response=await fetch(`/api3/mcp/servers/${encodeURIComponent(current.id)}`, {method:"DELETE", credentials:"same-origin"});
  const data=await response.json().catch(()=>({}));
  if(!response.ok || !data.ok){ const error=String(data.message || data.error || `HTTP ${response.status}`); setMcpSettingsHint(mcpUiT('settings.mcp.delete_failed', {error}, `Unable to delete the MCP server: ${error}`), "error"); return false; }
  const rows=saveMcpServers(getMcpServers().filter(item=>item.id !== current.id));
  mcpActiveServerId=rows[0]?.id || "";
  mcpEditorMode="edit";
  renderMcpSavedList();
  fillMcpForm(currentMcpServer());
  showMcpView("list");
  setMcpSettingsHint(mcpUiT('settings.mcp.deleted', null, 'MCP server deleted.'), "ok");
  return true;
}

const mcpInlineRequestDrafts = new Map();
const mcpInlineExpandedState = new Map();

function mcpInlineCardKey(type, requestId){
  return `${type === "approval" ? "mcp_approval" : "mcp_call"}|${String(requestId || "").trim()}`;
}

function mcpInlineStateLabel(card){
  const state=String(card?.state || "").toLowerCase();
  if(state === "pending") return mcpUiT('settings.mcp.state.pending', null, 'Awaiting authorization');
  if(state === "submitting") return mcpUiT('settings.mcp.state.submitting', null, 'Submitting');
  if(state === "allowed") return mcpUiT('settings.mcp.state.allowed', null, 'Allowed');
  if(state === "denied") return mcpUiT('settings.mcp.state.denied', null, 'Denied');
  if(state === "revision") return mcpUiT('settings.mcp.state.revision', null, 'Revision requested');
  if(state === "running") return mcpUiT('settings.mcp.state.running', null, 'Running');
  if(state === "done") return mcpUiT('settings.mcp.state.done', null, 'Completed');
  if(state === "error") return mcpUiT('settings.mcp.state.error', null, 'Failed');
  return "MCP";
}

function mcpInlineActivityEvent(card){
  const row=card && typeof card === "object" ? card : {};
  const approval=row.type === "approval";
  const state=String(row.state || "").toLowerCase();
  const label=String(row.toolTitle || row.toolName || mcpUiT('settings.mcp.tool_fallback', null, 'MCP tool'));
  let title=approval
    ? mcpUiT('settings.mcp.activity.awaiting', {name:label}, `Awaiting authorization: ${label}`)
    : mcpUiT('settings.mcp.activity.running', {name:label}, `Running: ${label}`);
  let activityState="active";
  if(state === "allowed"){ title=mcpUiT('settings.mcp.activity.allowed', {name:label}, `Authorized: ${label}`); activityState="done"; }
  else if(state === "denied"){ title=mcpUiT('settings.mcp.activity.denied', {name:label}, `Denied: ${label}`); activityState="warn"; }
  else if(state === "revision"){ title=mcpUiT('settings.mcp.activity.revision', {name:label}, `Revision requested: ${label}`); activityState="warn"; }
  else if(state === "done"){ title=mcpUiT('settings.mcp.activity.done', {name:label}, `Completed: ${label}`); activityState="done"; }
  else if(state === "error"){ title=mcpUiT('settings.mcp.activity.error', {name:label}, `Failed: ${label}`); activityState="error"; }
  return {
    key:`mcp_activity|${row.key || row.requestId || row.activityId || label}`,
    title,
    detail:`${String(row.serverName || "MCP Server")} · ${label}`,
    stage:"mcp",
    rawStage:approval ? "mcp_approval" : "mcp_call",
    source:"mcp",
    state:activityState,
    tool:String(row.toolName || ""),
    actionType:approval ? "mcp_approval" : "mcp_call",
    activityEvent:true,
    ts:Number(row.ts || Date.now()) || Date.now(),
    updatedAt:Number(row.updatedAt || Date.now()) || Date.now(),
  };
}

function upsertMcpInlineCard(sessionId, patch){
  const sid=String(sessionId || store?.activeId || "").trim();
  if(!sid || !patch) return null;
  const rt=ensureSessionRuntime(sid);
  const meta=_normalizePendingAssistantReasoningMeta(rt.reasoningMeta || {});
  const previous=_normalizeMcpInlineCards(meta.mcpCards || [], 30);
  const key=String(patch.key || mcpInlineCardKey(patch.type, patch.requestId || patch.activityId)).trim();
  const existing=previous.find(item=>item.key === key) || {};
  const nextCard=_normalizeMcpInlineCards([{...existing,...patch,key,updatedAt:Date.now()}], 1)[0];
  if(!nextCard) return null;
  const nextCards=_normalizeMcpInlineCards([...previous.filter(item=>item.key !== key),nextCard],30);
  setSessionRuntimeReasoningMeta(sid,{mcpCards:nextCards,activityEvents:[mcpInlineActivityEvent(nextCard)]});
  try{ if(typeof syncVisibleDraftBubble === "function") syncVisibleDraftBubble(sid); }catch(_){ }
  return nextCard;
}

async function submitMcpApproval(payload, decision, userRequest=""){
  const response=await fetch("/api3/chat_async/mcp_approval", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
    job_id:String(payload.jobId || payload.job_id || payload._job_id || ""),
    request_id:String(payload.requestId || payload.request_id || ""),
    decision,
    user_request:String(userRequest || "").trim(),
  })});
  const data=await response.json().catch(()=>({}));
  if(!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function decideMcpInlineApproval(card, decision, userRequest="", sessionId=""){
  const sid=String(sessionId || store?.activeId || "").trim();
  const note=String(userRequest || "").trim();
  if(decision === "revise" && !note){
    try{ toast(window.AperviaI18n?.t('settings.mcp.revision_required') || "Describe how you want the model to revise this tool call first."); }catch(_){ }
    return false;
  }
  upsertMcpInlineCard(sid,{...card,state:"submitting",userRequest:decision === "revise" ? note : ""});
  try{
    if(decision === "always_allow"){
      const rows=getMcpServers();
      const index=rows.findIndex(server=>server.id === String(card.serverId || ""));
      if(index >= 0){ rows[index].permission_mode="allow_all"; saveMcpServers(rows); await persistMcpServer(rows[index]); }
    }
    await submitMcpApproval(card,decision,decision === "revise" ? note : "");
    const state=decision === "deny" ? "denied" : (decision === "revise" ? "revision" : "allowed");
    mcpInlineExpandedState.set(String(card.key || mcpInlineCardKey("approval",card.requestId)),false);
    upsertMcpInlineCard(sid,{...card,state,expanded:false,userRequest:decision === "revise" ? note : ""});
    mcpInlineRequestDrafts.delete(String(card.requestId || card.key || ""));
    return true;
  }catch(err){
    upsertMcpInlineCard(sid,{...card,state:"pending",error:String(err?.message || err)});
    try{ toast(window.AperviaI18n?.t('settings.mcp.approval_submit_failed', {error:String(err?.message || err)}) || `Unable to submit MCP authorization: ${String(err?.message || err)}`); }catch(_){ }
    return false;
  }
}

async function handleMcpApprovalRequest(payload={},opts={}){
  const requestId=String(payload.request_id || payload.requestId || "").trim();
  if(!requestId) return null;
  return upsertMcpInlineCard(opts.sessionId,{
    key:mcpInlineCardKey("approval",requestId),
    type:"approval",
    jobId:String(payload.job_id || payload._job_id || ""),
    requestId,
    activityId:requestId,
    serverId:String(payload.server_id || ""),
    serverName:String(payload.server_name || "MCP Server"),
    toolName:String(payload.tool_name || ""),
    toolTitle:String(payload.tool_title || payload.tool_name || mcpUiT('settings.mcp.tool_fallback', null, 'MCP tool')),
    description:String(payload.tool_description || mcpUiT('settings.mcp.approval_default_description', null, 'This tool will access or modify data on the MCP server.')),
    risk:String(payload.risk || "high"),
    arguments:payload.arguments || {},
    state:"pending",
    expanded:true,
    ts:Date.now(),
  });
}

function handleMcpApprovalResult(payload={},opts={}){
  const requestId=String(payload.request_id || payload.requestId || "").trim();
  if(!requestId) return null;
  const decision=String(payload.decision || "deny").toLowerCase();
  const state=decision === "deny" ? "denied" : (decision === "revise" ? "revision" : "allowed");
  const cardKey=mcpInlineCardKey("approval",requestId);
  mcpInlineExpandedState.set(cardKey,false);
  return upsertMcpInlineCard(opts.sessionId,{
    key:cardKey,
    type:"approval",
    jobId:String(payload.job_id || payload._job_id || ""),
    requestId,
    activityId:requestId,
    serverId:String(payload.server_id || ""),
    serverName:String(payload.server_name || "MCP Server"),
    toolName:String(payload.tool_name || ""),
    toolTitle:String(payload.tool_title || payload.tool_name || mcpUiT('settings.mcp.tool_fallback', null, 'MCP tool')),
    description:String(payload.tool_description || ""),
    risk:String(payload.risk || "high"),
    ...(payload.arguments && typeof payload.arguments === "object" ? {arguments:payload.arguments} : {}),
    state,
    userRequest:String(payload.user_request || payload.userRequest || ""),
    expanded:false,
  });
}

function handleMcpToolAudit(payload={},opts={}){
  const action=String(payload.action || "").toLowerCase();
  const activityId=String(payload.activity_id || payload.activityId || payload.request_id || payload.requestId || "").trim();
  if(!activityId) return null;
  if(action === "approval_decision") return handleMcpApprovalResult(payload,opts);
  if(!["call_started","call_completed","call_failed"].includes(action)) return null;
  const state=action === "call_started" ? "running" : ((action === "call_failed" || payload.ok === false) ? "error" : "done");
  const patch={
    key:mcpInlineCardKey("call",activityId),
    type:"call",
    requestId:activityId,
    activityId,
    serverId:String(payload.server_id || ""),
    serverName:String(payload.server_name || "MCP Server"),
    toolName:String(payload.tool_name || ""),
    toolTitle:String(payload.tool_title || payload.tool_name || mcpUiT('settings.mcp.tool_fallback', null, 'MCP tool')),
    description:String(payload.tool_description || ""),
    risk:String(payload.risk || "high"),
    error:state === "error" ? String(payload.message || payload.error_type || payload.result_preview?.message || mcpUiT('settings.mcp.state.error', null, 'Failed')) : "",
    state,
    expanded:false,
  };
  if(action === "call_started") patch.ts=Date.now();
  if(payload.arguments && typeof payload.arguments === "object") patch.arguments=payload.arguments;
  if(Object.prototype.hasOwnProperty.call(payload,"result_preview")) patch.resultPreview=payload.result_preview;
  return upsertMcpInlineCard(opts.sessionId,patch);
}

function mcpInlineRiskLabel(risk){
  if(risk === "read") return mcpUiT('settings.mcp.risk.read', null, 'Read');
  if(risk === "low") return mcpUiT('settings.mcp.risk.low', null, 'Low risk');
  return mcpUiT('settings.mcp.risk.high', null, 'High risk');
}

function buildMcpInlineCardsNode(sessionId,cards){
  const rows=_normalizeMcpInlineCards(cards || [],30);
  if(!rows.length) return null;
  const stack=document.createElement("div");
  stack.className="mcp-chat-stack";
  stack.dataset.mcpSignature=JSON.stringify(rows.map(card=>[card.key,card.state,card.userRequest,card.error,card.resultPreview,card.updatedAt]));
  for(const card of rows){
    const details=document.createElement("details");
    details.className=`mcp-chat-card mcp-chat-${card.type} state-${card.state}`;
    const remembered=mcpInlineExpandedState.get(card.key);
    const awaitingApproval=card.type === "approval" && ["pending","submitting"].includes(card.state);
    details.open=remembered !== undefined ? !!remembered : awaitingApproval;
    details.addEventListener("toggle",()=>mcpInlineExpandedState.set(card.key,details.open));
    const summary=document.createElement("summary");
    const icon=document.createElement("span");
    icon.className="mcp-chat-icon";
    icon.innerHTML=mcpServerIconSvg();
    const summaryCopy=document.createElement("span");
    summaryCopy.className="mcp-chat-summary-copy";
    const eyebrow=document.createElement("span");
    eyebrow.className="mcp-chat-eyebrow";
    eyebrow.textContent=card.type === "approval"
      ? mcpUiT('settings.mcp.approval_request', null, 'MCP authorization request')
      : mcpUiT('settings.mcp.tool_execution', null, 'MCP tool execution');
    const title=document.createElement("span");
    title.className="mcp-chat-title";
    title.textContent=card.toolTitle;
    const summaryMeta=document.createElement("span");
    summaryMeta.className="mcp-chat-summary-meta";
    summaryMeta.textContent=`${card.serverName} · ${mcpInlineRiskLabel(card.risk)}`;
    summaryCopy.append(eyebrow,title,summaryMeta);
    const status=document.createElement("span");
    status.className="mcp-chat-status";
    status.textContent=mcpInlineStateLabel(card);
    summary.append(icon,summaryCopy,status);
    const body=document.createElement("div");
    body.className="mcp-chat-body";
    const meta=document.createElement("div");
    meta.className="mcp-chat-meta";
    const metaDot=document.createElement("span");
    metaDot.className="mcp-chat-meta-dot";
    const metaText=document.createElement("span");
    metaText.textContent=`${card.serverName} · ${mcpUiT('settings.mcp.permission', {risk:mcpInlineRiskLabel(card.risk)}, `${mcpInlineRiskLabel(card.risk)} permission`)}`;
    meta.append(metaDot,metaText);
    body.appendChild(meta);
    if(card.description){
      const desc=document.createElement("p");
      desc.textContent=card.description;
      body.appendChild(desc);
    }
    const argsText=JSON.stringify(card.arguments || {},null,2);
    const argsPanel=document.createElement("details");
    argsPanel.className="mcp-chat-data-panel mcp-chat-arguments-panel";
    argsPanel.open=argsText.length <= 360;
    const argsSummary=document.createElement("summary");
    const argsLabel=document.createElement("span");
    argsLabel.textContent=mcpUiT('settings.mcp.arguments', null, 'Arguments');
    const argsSize=document.createElement("span");
    argsSize.className="mcp-chat-data-size";
    argsSize.textContent=mcpUiT('settings.mcp.character_count', {count:argsText.length > 1000 ? `${Math.ceil(argsText.length / 1000)}k` : argsText.length}, `${argsText.length} characters`);
    argsSummary.append(argsLabel,argsSize);
    const args=document.createElement("pre");
    args.className="mcp-chat-arguments";
    args.textContent=argsText;
    argsPanel.append(argsSummary,args);
    body.appendChild(argsPanel);
    if(card.type === "call" && card.resultPreview !== null && card.resultPreview !== undefined){
      const resultText=JSON.stringify(card.resultPreview,null,2);
      const resultPanel=document.createElement("details");
      resultPanel.className="mcp-chat-data-panel mcp-chat-result-panel";
      const resultSummary=document.createElement("summary");
      const resultLabel=document.createElement("span");
      resultLabel.textContent=mcpUiT('settings.mcp.result', null, 'Result');
      const resultSize=document.createElement("span");
      resultSize.className="mcp-chat-data-size";
      resultSize.textContent=mcpUiT('settings.mcp.character_count', {count:resultText.length > 1000 ? `${Math.ceil(resultText.length / 1000)}k` : resultText.length}, `${resultText.length} characters`);
      resultSummary.append(resultLabel,resultSize);
      const result=document.createElement("pre");
      result.className="mcp-chat-result";
      result.textContent=resultText;
      resultPanel.append(resultSummary,result);
      body.appendChild(resultPanel);
    }
    if(card.userRequest){
      const request=document.createElement("div");
      request.className="mcp-chat-user-request";
      request.textContent=mcpUiT('settings.mcp.extra_request_value', {request:card.userRequest}, `Additional request: ${card.userRequest}`);
      body.appendChild(request);
    }
    if(card.error){
      const error=document.createElement("div");
      error.className="mcp-chat-error";
      error.textContent=card.error;
      body.appendChild(error);
    }
    if(card.type === "approval" && ["pending","submitting"].includes(card.state)){
      const requestField=document.createElement("div");
      requestField.className="mcp-chat-request-field";
      const requestLabel=document.createElement("label");
      requestLabel.textContent=mcpUiT('settings.mcp.extra_request', null, 'Additional request');
      const requestOptional=document.createElement("span");
      requestOptional.textContent=mcpUiT('settings.mcp.extra_request_hint', null, 'Optional · fill this in, then select Revise and retry');
      requestLabel.appendChild(requestOptional);
      const textarea=document.createElement("textarea");
      textarea.className="mcp-chat-request-input";
      textarea.rows=2;
      textarea.placeholder=mcpUiT('settings.mcp.extra_request_placeholder', null, 'For example: Keep the original file and create a copy instead.');
      textarea.value=mcpInlineRequestDrafts.get(card.requestId) || "";
      textarea.addEventListener("input",()=>mcpInlineRequestDrafts.set(card.requestId,textarea.value));
      requestField.append(requestLabel,textarea);
      body.appendChild(requestField);
      const actions=document.createElement("div");
      actions.className="mcp-chat-actions";
      const addAction=(decision,label,className="")=>{
        const button=document.createElement("button");
        button.type="button";
        button.textContent=label;
        button.className=className;
        button.disabled=card.state === "submitting";
        button.addEventListener("click",event=>{
          event.preventDefault();
          event.stopPropagation();
          decideMcpInlineApproval(card,decision,textarea.value,sessionId);
        });
        actions.appendChild(button);
      };
      addAction("deny",mcpUiT('settings.mcp.deny', null, 'Deny'),"danger");
      addAction("revise",mcpUiT('settings.mcp.revise', null, 'Revise and retry'),"revise");
      addAction("allow_once",mcpUiT('settings.mcp.allow_once', null, 'Allow once'),"primary");
      addAction("always_allow",mcpUiT('settings.mcp.always_allow', null, 'Always allow'));
      body.appendChild(actions);
    }
    details.append(summary,body);
    stack.appendChild(details);
  }
  return stack;
}

function syncMcpInlineCardsInBody(body,sessionId,cards){
  if(!body?.querySelector) return null;
  const rows=_normalizeMcpInlineCards(cards || [],30);
  const existing=body.querySelector(":scope > .mcp-chat-stack");
  if(!rows.length){ if(existing) existing.remove(); return null; }
  const signature=JSON.stringify(rows.map(card=>[card.key,card.state,card.userRequest,card.error,card.resultPreview,card.updatedAt]));
  if(existing && existing.dataset.mcpSignature === signature) return existing;
  const next=buildMcpInlineCardsNode(sessionId,rows);
  if(!next) return null;
  if(existing){ existing.replaceWith(next); return next; }
  const reasoning=body.querySelector(":scope > .activity-inline-trigger-wrap, :scope > .reasoning-panels, :scope > .reasoning-panel");
  if(reasoning) body.insertBefore(next,reasoning.nextSibling || null);
  else body.insertBefore(next,body.firstChild || null);
  return next;
}

function bindMcpSettingsUi(){
  purgeLegacyMcpBrowserStorage();
  window.addEventListener("message", event=>{ handleMcpOauthMessage(event).catch(()=>{}); });
  syncMcpDeveloperModeUi();
  document.getElementById("accountDeveloperModeToggle")?.addEventListener("change", event=>{
    const enabled=!!event.target.checked;
    setMcpDeveloperModeEnabled(enabled);
    try{ toast(window.AperviaI18n?.t(enabled ? 'settings.mcp.developer_enabled' : 'settings.mcp.developer_disabled') || (enabled ? "Developer mode enabled" : "Developer mode disabled")); }catch(_){ }
  });
  document.getElementById("mcpAuthType")?.addEventListener("change", syncMcpAuthUi);
  document.getElementById("mcpConnectBtn")?.addEventListener("click", ()=>startMcpOauthConnect());
  document.getElementById("mcpDisconnectBtn")?.addEventListener("click", ()=>disconnectMcpServer());
  document.getElementById("mcpScanBtn")?.addEventListener("click", ()=>scanMcpServer());
  document.getElementById("mcpPermissionOpenBtn")?.addEventListener("click", ()=>{
    const current=currentMcpServer();
    if(!current) return;
    syncMcpPermissionUi(current);
    showMcpView("permission");
  });
  document.getElementById("mcpConnectionOpenBtn")?.addEventListener("click", ()=>{
    const current=currentMcpServer();
    if(!current) return;
    mcpEditorMode="edit";
    fillMcpForm(current);
    showMcpView("connection");
  });
  document.querySelectorAll('[data-mcp-back]').forEach(button=>button.addEventListener("click", ()=>{
    const target=button.dataset.mcpBack || "list";
    if(target === "detail") renderMcpDetail(currentMcpServer());
    if(target === "list") renderMcpSavedList();
    showMcpView(target);
  }));
  document.querySelectorAll('[data-mcp-permission-mode]').forEach(button=>button.addEventListener("click", ()=>setMcpPermissionMode(button.dataset.mcpPermissionMode || "allow_low_risk")));
  document.getElementById("mcpPermissionResetBtn")?.addEventListener("click", ()=>setMcpPermissionMode("allow_low_risk"));
  document.getElementById("mcpMoreBtn")?.addEventListener("click", event=>{
    event.stopPropagation();
    const menu=document.getElementById("mcpMoreMenu");
    const button=document.getElementById("mcpMoreBtn");
    if(!menu || !button) return;
    menu.hidden=!menu.hidden;
    button.setAttribute("aria-expanded", menu.hidden ? "false" : "true");
  });
  document.getElementById("mcpMoreMenu")?.addEventListener("click", async event=>{
    const button=event.target.closest('[data-mcp-action]');
    if(!button) return;
    const action=button.dataset.mcpAction;
    closeMcpMoreMenu();
    if(action === "edit"){
      mcpEditorMode="edit";
      fillMcpForm(currentMcpServer());
      showMcpView("connection");
    }else if(action === "scan"){
      await scanMcpServer(currentMcpServer());
    }else if(action === "disconnect"){
      disconnectMcpServer();
    }else if(action === "delete"){
      await deleteCurrentMcpServer(button);
    }
  });
  document.addEventListener("click", event=>{
    if(!event.target.closest(".mcp-more-wrap")) closeMcpMoreMenu();
  });
  document.addEventListener("keydown", event=>{
    if(event.key === "Escape" && !document.getElementById("mcpMoreMenu")?.hidden){ closeMcpMoreMenu(); event.stopPropagation(); }
  });
  document.getElementById("mcpSaveBtn")?.addEventListener("click", async ()=>{
    if(mcpEditorMode === "new" && !isMcpDeveloperModeEnabled()){
      openMcpDeveloperModeSettings();
      return;
    }
    const next=readMcpServerForm();
    if(!next.url){ setMcpSettingsHint(window.AperviaI18n?.t('settings.mcp.url_required') || "Enter the MCP Server URL first.", "error"); return; }
    try{
      const saved=await persistMcpServer(next);
      mcpActiveServerId=saved.id;
      mcpEditorMode="edit";
      renderMcpSavedList(); fillMcpForm(saved); renderMcpDetail(saved); showMcpView("detail");
      try{ toast(window.AperviaI18n?.t('settings.mcp.saved') || "MCP server saved"); }catch(_){ }
    }catch(err){ setMcpSettingsHint(mcpUiT('settings.mcp.save_failed', {error:String(err?.message || err)}, `Unable to save the MCP server: ${String(err?.message || err)}`), "error"); }
  });
  document.getElementById("mcpNewBtn")?.addEventListener("click", ()=>{
    if(!isMcpDeveloperModeEnabled()){
      openMcpDeveloperModeSettings();
      return;
    }
    mcpEditorMode="new"; mcpActiveServerId=""; setMcpSettingsHint("", ""); fillMcpForm(normalizeMcpServer({name:"",enabled:true,auth_type:"oauth"})); showMcpView("connection");
    document.getElementById("mcpServerName")?.focus();
  });
  document.getElementById("mcpDeleteBtn")?.addEventListener("click", ()=>deleteCurrentMcpServer(document.getElementById("mcpDeleteBtn")));
}

let mcpAdminLoaded = false;

function mcpAdminAuthLabel(value) {
  return { none: adminT('admin.platform.mcp_none_auth', '无认证'), bearer: 'Bearer', oauth: 'OAuth' }[String(value || '')] || adminT('admin.platform.mcp_unknown_auth', '未知认证');
}

function renderMcpAdmin(data = {}) {
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const list = document.getElementById('mcpAdminList');
  const storage = document.getElementById('mcpAdminStorage');
  if (storage) storage.textContent = adminT(data.key_source === 'environment' ? 'admin.platform.mcp_env_encryption' : 'admin.platform.mcp_volume_encryption', data.key_source === 'environment' ? '环境密钥加密' : '数据卷密钥加密');
  if (!list) return;
  list.innerHTML = rows.map(row => {
    const connected = row.connected === true;
    const enabled = row.enabled !== false;
    const tools = `${Number(row.enabled_tool_count || 0)}/${Number(row.tool_count || 0)}`;
    const accountTools = adminTP('admin.platform.mcp_account_tools', {account:row.owner || '-', tools});
    return `<div class="row"><div class="rowTop"><div><div class="rowTitle">${esc(row.name || row.id || 'MCP Server')}</div><span class="pill ${connected ? 'ok' : 'warn'}">${esc(adminT(connected ? 'admin.platform.mcp_connected' : 'admin.platform.mcp_disconnected', connected ? '已连接' : '未连接'))}</span><span class="pill ${enabled ? 'ok' : 'warn'}">${esc(adminT(enabled ? 'admin.platform.mcp_enabled' : 'admin.platform.mcp_disabled', enabled ? '已启用' : '已停用'))}</span><span class="pill">${esc(mcpAdminAuthLabel(row.auth_type))}</span></div><div class="rowActions"><button type="button" data-mcp-admin-action="${enabled ? 'disable' : 'enable'}" data-owner="${esc(row.owner || '')}" data-server-id="${esc(row.id || '')}">${esc(adminT(enabled ? 'admin.platform.mcp_disable' : 'admin.platform.mcp_enable', enabled ? '停用' : '启用'))}</button><button type="button" class="warn" data-mcp-admin-action="disconnect" data-owner="${esc(row.owner || '')}" data-server-id="${esc(row.id || '')}" ${row.credential_configured ? '' : 'disabled'}>${esc(adminT('admin.platform.mcp_disconnect', '断开'))}</button><button type="button" class="bad" data-mcp-admin-action="delete" data-owner="${esc(row.owner || '')}" data-server-id="${esc(row.id || '')}">${esc(adminT('admin.platform.mcp_delete', '删除'))}</button></div></div><div class="rowMeta">${esc(accountTools)}<br>${esc(row.url || '-')}</div></div>`;
  }).join('') || emptyState(
    adminT('admin.platform.mcp_empty', 'No MCP servers'),
    adminT('admin.platform.mcp_empty_hint', 'No matching records are available in the server-side directory.'),
  );
}

async function refreshMcpAdmin() {
  setAdminListLoading(['mcpAdminList'], { rows: 4, label: adminT('admin.platform.mcp_loading', 'Loading the MCP directory') });
  const query = String(document.getElementById('mcpAdminQuery')?.value || '').trim();
  const data = await requestJson('/api3/platform-admin/mcp?' + qs({ q: query }));
  clearAdminListLoading(['mcpAdminList']);
  renderMcpAdmin(data);
  mcpAdminLoaded = true;
  setMsg(adminTP('admin.platform.mcp_loaded', {count:Number(data.total || 0)}));
  return data;
}

async function runMcpAdminAction(button) {
  const action = String(button?.dataset?.mcpAdminAction || '');
  const owner = String(button?.dataset?.owner || '');
  const serverId = String(button?.dataset?.serverId || '');
  if (!action || !owner || !serverId) return;
  const label = {
    enable: adminT('admin.platform.mcp_enable', 'Enable'),
    disable: adminT('admin.platform.mcp_disable', 'Disable'),
    disconnect: adminT('admin.platform.mcp_disconnect_clear', 'Disconnect and clear credentials'),
    delete: adminT('admin.platform.mcp_delete_permanently', 'Delete permanently'),
  }[action] || action;
  if (['disconnect', 'delete'].includes(action) && !confirm(adminTP('admin.platform.mcp_action_confirm', { action: label, owner, server: serverId }))) return;
  button.disabled = true;
  try {
    const data = await postJson('/api3/platform-admin/mcp/action', { owner, server_id: serverId, action });
    renderMcpAdmin({ rows: data.rows || [], total: (data.rows || []).length, credential_storage: 'encrypted' });
    setMsg(adminTP('admin.platform.mcp_action_succeeded', { action: label }));
  } finally {
    button.disabled = false;
  }
}

document.querySelector('[data-tab="mcp"]')?.addEventListener('click', () => {
  if (!mcpAdminLoaded) refreshMcpAdmin().catch(error => setMsg(error.message || adminT('admin.platform.mcp_load_failed', 'Unable to load the MCP directory'), true));
});
document.getElementById('reloadMcpAdminBtn')?.addEventListener('click', () => refreshMcpAdmin().catch(error => setMsg(error.message || adminT('admin.platform.mcp_load_failed', 'Unable to load the MCP directory'), true)));
document.getElementById('mcpAdminList')?.addEventListener('click', event => {
  const button = event.target.closest('[data-mcp-admin-action]');
  if (button) runMcpAdminAction(button).catch(error => setMsg(error.message || adminT('admin.platform.mcp_action_failed', 'MCP action failed'), true));
});

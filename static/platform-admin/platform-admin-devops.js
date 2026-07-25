const ADMIN_PREFS_KEY = 'app3_platform_admin_prefs_v2';
const ADMIN_PREF_DEFAULTS = { pageSize: 20, accountDetailPageSize: 12, refreshInterval: 30, density: 'comfortable' };
let adminPrefs = loadAdminPrefs();
let adminRefreshTimer = 0;
let devopsLoaded = false;
let logPollingEnabled = true;
let logPollTimer = 0;
let logRows = [];
let logLatestSeq = 0;
let storagePolicyCache = null;
const accountDetailState = { owner: '', section: 'sessions', page: 1, account: null, totals: {} };

function loadAdminPrefs() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ADMIN_PREFS_KEY) || '{}');
    const merged = Object.assign({}, ADMIN_PREF_DEFAULTS, parsed && typeof parsed === 'object' ? parsed : {});
    if (![20, 40, 80].includes(Number(merged.pageSize))) merged.pageSize = ADMIN_PREF_DEFAULTS.pageSize;
    if (![10, 12, 20].includes(Number(merged.accountDetailPageSize))) merged.accountDetailPageSize = ADMIN_PREF_DEFAULTS.accountDetailPageSize;
    if (![0, 15, 30, 60].includes(Number(merged.refreshInterval))) merged.refreshInterval = ADMIN_PREF_DEFAULTS.refreshInterval;
    if (!['comfortable', 'compact'].includes(String(merged.density))) merged.density = ADMIN_PREF_DEFAULTS.density;
    return merged;
  } catch (_) {
    return Object.assign({}, ADMIN_PREF_DEFAULTS);
  }
}

function adminListPageSize() {
  const size = Number(adminPrefs.pageSize || ADMIN_PREF_DEFAULTS.pageSize);
  return [20, 40, 80].includes(size) ? size : ADMIN_PREF_DEFAULTS.pageSize;
}

function applyAdminPrefs() {
  document.body.classList.toggle('compact', adminPrefs.density === 'compact');
  const values = {
    adminPageSize: String(adminListPageSize()),
    accountDetailPageSize: String(Number(adminPrefs.accountDetailPageSize || 12)),
    adminRefreshInterval: String(Number(adminPrefs.refreshInterval || 0)),
    adminDensity: String(adminPrefs.density || 'comfortable'),
  };
  Object.entries(values).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (el) el.value = value;
  });
  if (adminRefreshTimer) window.clearInterval(adminRefreshTimer);
  adminRefreshTimer = 0;
  const seconds = Number(adminPrefs.refreshInterval || 0);
  if (seconds > 0) {
    adminRefreshTimer = window.setInterval(() => {
      if (!document.hidden) refreshState().catch(() => {});
    }, seconds * 1000);
  }
}

function saveAdminPrefs() {
  adminPrefs = {
    pageSize: Number(document.getElementById('adminPageSize')?.value || 40),
    accountDetailPageSize: Number(document.getElementById('accountDetailPageSize')?.value || 12),
    refreshInterval: Number(document.getElementById('adminRefreshInterval')?.value || 0),
    density: String(document.getElementById('adminDensity')?.value || 'comfortable'),
  };
  localStorage.setItem(ADMIN_PREFS_KEY, JSON.stringify(adminPrefs));
  applyAdminPrefs();
  setMsg(adminT('admin.platform.prefs_saved', '控制台体验设置已保存'));
}

function resetAdminPrefs() {
  adminPrefs = Object.assign({}, ADMIN_PREF_DEFAULTS);
  localStorage.removeItem(ADMIN_PREFS_KEY);
  applyAdminPrefs();
  setMsg(adminT('admin.platform.prefs_reset', '控制台体验设置已恢复默认'));
}

function accountSectionLabel(section) {
  const keys = { sessions: 'sessions', files: 'files', kb: 'kb', audit: 'audit' };
  const key = keys[section];
  return key ? adminT(`admin.platform.account_section_${key}`, { sessions: '会话', files: '文件', kb: '知识库', audit: '审计' }[section]) : section;
}

function accountSectionPage(payload) {
  return payload?.page || {};
}

function renderAccountSectionRows(section, payload, owner) {
  if (section === 'sessions') {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    return rows.map(item => `<div class="row"><div class="rowTop"><div><div class="rowTitle">${esc(item.title || adminT('admin.platform.new_chat', '新会话'))}</div><div class="rowMeta">${esc(adminTP('admin.platform.session_meta', { messages: Number(item.message_count || 0), model: item.model || '-', status: adminT(item.deleted ? 'admin.platform.status_deleted' : 'admin.platform.status_normal', item.deleted ? '已删除' : '正常') }))}<br>${esc(adminTP('admin.platform.updated_at', { time: item.updated_at || '-' }))}</div></div><button type="button" data-chat-owner="${esc(owner)}" data-chat-session="${esc(item.id || '')}">${esc(adminT('admin.platform.view_content', '查看正文'))}</button></div></div>`).join('') || `<div class="muted">${esc(adminT('admin.platform.no_sessions', '暂无会话'))}</div>`;
  }
  if (section === 'files') {
    return renderFileRows(Array.isArray(payload?.files) ? payload.files : []);
  }
  if (section === 'kb') {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    return rows.map(item => `<div class="row"><div class="rowTitle">${esc(item.filename || '-')}</div><div class="rowMeta">${esc(adminTP('admin.platform.kb_row_meta', { size: item.size_text || '0B', chunks: Number(item.chunk_count || 0), time: item.updated_at || '-' }))}</div></div>`).join('') || `<div class="muted">${esc(adminT('admin.platform.no_kb_content', '暂无知识库内容'))}</div>`;
  }
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  return rows.map(item => `<div class="row"><span class="pill ${item.ok ? 'ok' : 'bad'}">${esc(adminT(item.ok ? 'admin.platform.status_success' : 'admin.platform.status_failed', item.ok ? '成功' : '失败'))}</span>${esc(adminPhrase(item.action || '-'))}<div class="rowMeta">${esc(item.time || '-')}<br>${esc(item.target || '-')}</div></div>`).join('') || `<div class="muted">${esc(adminT('admin.platform.no_audit_records', '暂无审计记录'))}</div>`;
}

renderAccountDetail = function renderPagedAccountDetail(data) {
  const el = document.getElementById('accountDetail');
  if (!el) return;
  const section = String(data.section || accountDetailState.section || 'sessions');
  const account = data.account || accountDetailState.account || {};
  const sectionPayload = data[section] || {};
  accountDetailState.owner = String(data.owner || accountDetailState.owner || '');
  accountDetailState.section = section;
  accountDetailState.account = account;
  accountDetailState.page = Number(sectionPayload?.page?.page || 1);
  accountDetailState.totals[section] = Number(sectionPayload?.total ?? sectionPayload?.page?.total ?? 0);
  const tabs = ['sessions', 'files', 'kb', 'audit'].map(key => `<button type="button" class="${key === section ? 'active' : ''}" data-account-section="${key}">${accountSectionLabel(key)}${accountDetailState.totals[key] !== undefined ? ` ${accountDetailState.totals[key]}` : ''}</button>`).join('');
  el.innerHTML = `<div class="row accountDetailHeader"><div class="rowTop"><div><span class="pill ${esc(account.status_kind || '')}">${esc(adminPhrase(account.status || '-'))}</span><span class="mono">${esc(accountDetailState.owner || '-')}</span></div><button type="button" data-account-detail-close="1">${esc(adminT('common.close', '关闭'))}</button></div><div class="rowMeta">${esc(adminTP('admin.platform.account_detail_usage', { used: account.used_text || '0B', limit: account.limit_text || '-', files: account.tracked_files_text || '0B', kb: account.knowledge_base_text || '0B' }))}</div></div><div class="accountSectionTabs">${tabs}</div><div class="sectionTitle"><h3>${accountSectionLabel(section)}</h3><span class="muted small">${esc(adminT('admin.platform.account_detail_loading_hint', '每次只加载当前模块，避免长列表连续翻动'))}</span></div><div class="accountDetailBody list">${renderAccountSectionRows(section, sectionPayload, accountDetailState.owner)}</div><div id="accountDetailPager" class="pager"></div>`;
  renderPager('accountDetailPager', accountSectionPage(sectionPayload),
    () => loadAccountDetailSection(section, Math.max(1, accountDetailState.page - 1)),
    () => loadAccountDetailSection(section, accountDetailState.page + 1));
};

async function loadAccountDetailSection(section, page = 1) {
  if (!accountDetailState.owner) return;
  setMsg(adminTP('admin.platform.account_section_loading', { section: accountSectionLabel(section) }));
  const data = await requestJson('/api3/platform-admin/account-detail?' + qs({
    owner: accountDetailState.owner,
    section,
    page,
    page_size: Number(adminPrefs.accountDetailPageSize || 12),
  }));
  renderAccountDetail(data);
  setMsg(adminTP('admin.platform.account_section_loaded', { section: accountSectionLabel(section) }));
}

openAccountDetail = async function openPagedAccountDetail(owner) {
  document.querySelectorAll('[data-account-row]').forEach(row => row.classList.toggle('selected', row.getAttribute('data-account-row') === owner));
  accountDetailState.owner = String(owner || '');
  accountDetailState.section = 'sessions';
  accountDetailState.page = 1;
  accountDetailState.account = null;
  accountDetailState.totals = {};
  await loadAccountDetailSection('sessions', 1);
};

function renderEffectiveSettings(data) {
  const target = document.getElementById('effectiveSettings');
  if (!target) return;
  const groups = Array.isArray(data?.groups) ? data.groups : [];
  target.innerHTML = groups.map(group => `<div class="configCard"><div class="rowTitle">${esc(adminPhrase(group.name || '-'))}</div><div class="configRows">${(group.items || []).map(item => `<div><span>${esc(adminPhrase(item.label || item.key))}</span><b class="mono">${esc(String(item.value))}</b></div>`).join('')}</div></div>`).join('') || emptyState(adminT('admin.platform.no_effective_settings', '暂无有效配置'), adminT('admin.platform.no_effective_settings_hint', '服务没有返回可展示的运行设置。'));
}

async function loadEffectiveSettings() {
  const data = await requestJson('/api3/platform-admin/settings');
  renderEffectiveSettings(data);
  return data;
}

function ensureStoragePolicyCard() {
  let card = document.querySelector('.storagePolicyCard');
  if (card) return card;
  const template = document.getElementById('storagePolicyCardTemplate');
  const panel = document.querySelector('#panel-devops .panelShell');
  if (!template || !panel) return null;
  const fragment = template.content.cloneNode(true);
  const firstSection = panel.querySelector('.sectionGap');
  panel.insertBefore(fragment, firstSection || null);
  return panel.querySelector('.storagePolicyCard');
}

function storagePolicyMb(bytes) {
  const value = Number(bytes || 0) / 1048576;
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
}

function renderStoragePolicy(data) {
  ensureStoragePolicyCard();
  storagePolicyCache = data || {};
  const groups = Array.isArray(storagePolicyCache.groups) ? storagePolicyCache.groups : [];
  const target = document.getElementById('storagePolicyGroups');
  const meta = document.getElementById('storagePolicyMeta');
  if (meta) meta.textContent = adminTP('admin.platform.storage_custom_count', { count: Number(storagePolicyCache.custom_count || 0) });
  if (!target) return;
  target.innerHTML = groups.map(group => `<section class="storagePolicyGroup"><div class="storagePolicyGroupTitle">${esc(adminPhrase(group.name || adminT('admin.platform.other', '其他')))}</div><div class="storagePolicyItems">${(group.items || []).map(item => `<div class="storagePolicyItem ${item.custom ? 'custom' : ''}"><div class="storagePolicyInfo"><div><strong>${esc(adminPhrase(item.label || item.key))}</strong><span class="pill ${item.custom ? 'ok' : ''}">${esc(adminT(item.custom ? 'admin.platform.custom' : 'admin.platform.default', item.custom ? '自定义' : '默认'))}</span></div><code>${esc(item.key || '')}</code>${item.note ? `<p>${esc(adminPhrase(item.note))}</p>` : ''}<small>${esc(adminTP('admin.platform.current_default', { value: item.value_text || '-', default: item.default_text || '-' }))}</small></div><div class="storagePolicyEdit"><input type="number" min="${storagePolicyMb(item.minimum_bytes)}" max="${storagePolicyMb(item.maximum_bytes)}" step="1" value="${storagePolicyMb(item.value_bytes)}" data-storage-policy-input="${esc(item.key || '')}" aria-label="${esc(adminTP('admin.platform.unit_mb_label', { label: adminPhrase(item.label || item.key) }))}"><span>MB</span><button type="button" data-storage-policy-reset="${esc(item.key || '')}" ${item.custom ? '' : 'disabled'}>${esc(adminT('admin.platform.restore_default', '恢复默认'))}</button></div></div>`).join('')}</div></section>`).join('') || emptyState(adminT('admin.platform.no_storage_policy', '暂无存储额度策略'), adminT('admin.platform.no_storage_policy_hint', '服务没有返回可调整的存储额度项。'));
}

async function loadStoragePolicy() {
  ensureStoragePolicyCard();
  const data = await requestJson('/api3/storage-admin/policy');
  renderStoragePolicy(data);
  return data;
}

function applyStoragePolicyResponse(data) {
  renderStoragePolicy(data?.policy || data || {});
  if (data?.state && typeof renderState === 'function') renderState(data.state);
}

async function saveStoragePolicy() {
  const items = Array.isArray(storagePolicyCache?.items) ? storagePolicyCache.items : [];
  const current = new Map(items.map(item => [String(item.key || ''), item]));
  const limits = {};
  document.querySelectorAll('[data-storage-policy-input]').forEach(input => {
    const key = String(input.getAttribute('data-storage-policy-input') || '');
    const item = current.get(key);
    const valueMb = Number(input.value);
    if (!item || !Number.isFinite(valueMb) || valueMb <= 0) throw new Error(adminTP('admin.platform.storage_invalid_mb', { label: adminPhrase(item?.label || key) }));
    const valueBytes = Math.round(valueMb * 1048576);
    if (valueBytes !== Number(item.value_bytes || 0)) limits[key] = valueBytes;
  });
  if (!Object.keys(limits).length) {
    setMsg(adminT('admin.platform.storage_no_changes', '存储额度没有改动'));
    return;
  }
  const button = document.getElementById('saveStoragePolicyBtn');
  if (button) button.disabled = true;
  setMsg(adminT('admin.platform.storage_saving', '正在保存存储额度策略…'));
  try {
    const data = await postJson('/api3/storage-admin/policy', { limits });
    applyStoragePolicyResponse(data);
    setMsg(adminTP('admin.platform.storage_saved_count', { count: Object.keys(limits).length }));
  } finally {
    if (button) button.disabled = false;
  }
}

async function resetStoragePolicyKey(key) {
  const data = await postJson('/api3/storage-admin/policy', { reset_keys: [String(key || '')] });
  applyStoragePolicyResponse(data);
  setMsg(adminT('admin.platform.storage_key_reset', '该存储额度已恢复默认'));
}

async function resetAllStoragePolicy() {
  if (!confirm(adminT('admin.platform.storage_reset_confirm', '确认将所有存储额度恢复为程序默认值？'))) return;
  const data = await postJson('/api3/storage-admin/policy', { reset_all: true });
  applyStoragePolicyResponse(data);
  setMsg(adminT('admin.platform.storage_all_reset', '所有存储额度已恢复默认'));
}

function pythonPackageSourceText(item) {
  if (item?.source === 'extension') return adminT('admin.platform.python_source_extension', '持久化扩展');
  if (item?.source === 'image') return adminT('admin.platform.python_source_image', '镜像内置');
  return adminPhrase(item?.source_text || adminT('admin.platform.sandbox_visible', 'Visible in sandbox'));
}

function pythonPackageSummary(item) {
  const summary = String(item?.summary || '').trim();
  if (summary) return adminPhrase(summary);
  if (item?.source === 'extension') return adminT('admin.platform.python_summary_extension', '后台安装的持久化扩展包');
  if (item?.source === 'image') return adminT('admin.platform.python_summary_image', '沙盒镜像内置包');
  return '';
}

function renderPythonPackages(data) {
  const status = document.getElementById('pythonPackageStatus');
  const install = document.getElementById('installPythonPackageBtn');
  const docker = data?.docker || {};
  const imageReady = Boolean(data?.image);
  const inventoryAvailable = Boolean(data?.inventory_available);
  if (status) {
    status.classList.toggle('error', !docker.available || !imageReady || !inventoryAvailable);
    if (!docker.available) {
      status.textContent = adminTP('admin.platform.python_docker_unavailable', { message: adminPhrase(docker.message || 'Docker 未启动或无法连接') });
      status.title = adminErrorText(docker.error || '');
    } else if (!imageReady) {
      status.textContent = adminT('admin.platform.python_image_missing', '沙盒 Docker 镜像未配置，无法读取 Python 包');
      status.title = '';
    } else if (!inventoryAvailable) {
      status.textContent = adminTP('admin.platform.python_inventory_failed', { message: adminPhrase(data.inventory_message || '沙盒 Python 包识别失败') });
      status.title = String(data.inventory_error || '');
    } else {
      status.textContent = adminTP('admin.platform.python_inventory', { total: Number(data.total || 0), image: Number(data.image_total || 0), extension: Number(data.extension_total || 0) });
      status.title = adminTP('admin.platform.python_docker_title', { version: docker.version || adminT('admin.platform.available', '可用'), image: data.image || '-' });
    }
  }
  if (install) install.disabled = !docker.available || !imageReady;
  const target = document.getElementById('pythonPackageList');
  if (target) {
    const rows = Array.isArray(data?.rows) ? data.rows : [];
    const emptyTitle = inventoryAvailable ? adminT('admin.platform.python_none', '沙盒中未识别到 Python 包') : adminT('admin.platform.python_unavailable', '暂时无法读取沙盒 Python 包');
    const emptyHint = inventoryAvailable ? adminT('admin.platform.python_none_hint', '请检查沙盒镜像中的 Python 环境。') : adminT('admin.platform.python_unavailable_hint', '启动 Docker 并确认沙盒镜像可用后，点击“检查环境”。');
  target.innerHTML = rows.map(item => `<div class="packageItem"><div class="rowTitle">${esc(item.name || '-')} <span class="pill">${esc(item.version || '-')}</span> <span class="pill ${item.source === 'extension' ? 'ok' : ''}">${esc(pythonPackageSourceText(item))}</span></div><div class="muted small">${esc(pythonPackageSummary(item))}</div></div>`).join('') || emptyState(emptyTitle, emptyHint);
  }
}

async function loadPythonPackages(force = false) {
  const data = await requestJson('/api3/platform-admin/python-packages?' + qs({ force: force ? 1 : 0 }));
  renderPythonPackages(data);
  return data;
}

async function installPythonPackage() {
  const input = document.getElementById('pythonPackageSpec');
  const spec = String(input?.value || '').trim();
  if (!spec) throw new Error(adminT('admin.platform.python_spec_required', '请输入 PyPI 包名或“包名==版本”'));
  if (!confirm(adminTP('admin.platform.python_install_confirm', { spec }))) return;
  const button = document.getElementById('installPythonPackageBtn');
  if (button) button.disabled = true;
  setMsg(adminTP('admin.platform.python_installing', { spec }));
  try {
    const data = await postJson('/api3/platform-admin/python-packages/install', { spec });
    renderPythonPackages(data);
    if (input) input.value = '';
    setMsg(adminTP('admin.platform.python_installed', { spec }));
  } finally {
    if (button) button.disabled = false;
  }
}

function renderLogs(data, reset = false) {
  if (reset) logRows = [];
  const incoming = Array.isArray(data?.rows) ? data.rows : [];
  const known = new Set(logRows.map(item => Number(item.seq || 0)));
  incoming.forEach(item => { if (!known.has(Number(item.seq || 0))) logRows.push(item); });
  if (logRows.length > 400) logRows = logRows.slice(-400);
  logLatestSeq = Math.max(logLatestSeq, Number(data?.latest_seq || 0));
  const viewer = document.getElementById('appLogViewer');
  if (viewer) {
    const nearBottom = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 80;
    viewer.innerHTML = logRows.map(item => `<div class="logLine" data-level="${esc(item.level || '')}"><span>${esc(item.time || '-')}</span><span class="level">${esc(item.level || '-')}</span><span class="logger">${esc(item.logger || '-')}</span><span class="message">${esc(item.message || '')}</span></div>`).join('') || `<div class="muted">${esc(adminT('admin.platform.no_logs', '暂无日志'))}</div>`;
    if (nearBottom || reset) viewer.scrollTop = viewer.scrollHeight;
  }
  const meta = document.getElementById('logMeta');
  if (meta) meta.textContent = adminTP('admin.platform.log_meta', { count: logRows.length, size: Number(data?.buffer_size || 0), limit: Number(data?.buffer_limit || 0), time: data?.updated_at_text || '-' });
}

async function loadLogs(reset = false) {
  const level = String(document.getElementById('logLevelFilter')?.value || '').trim();
  const q = String(document.getElementById('logQueryFilter')?.value || '').trim();
  if (reset) {
    logRows = [];
    logLatestSeq = 0;
  }
  const data = await requestJson('/api3/platform-admin/app-logs?' + qs({ after: reset ? 0 : logLatestSeq, limit: 300, level, q }));
  renderLogs(data, reset);
  return data;
}

function startLogPolling() {
  if (logPollTimer) window.clearInterval(logPollTimer);
  logPollTimer = window.setInterval(() => {
    if (!logPollingEnabled || document.hidden || !document.getElementById('panel-devops')?.classList.contains('active')) return;
    loadLogs(false).catch(() => {});
  }, 2000);
}

function toggleLogPolling() {
  logPollingEnabled = !logPollingEnabled;
  const button = document.getElementById('toggleLogPollingBtn');
  if (button) {
    button.textContent = adminTP('admin.platform.live_updates', { state: adminT(logPollingEnabled ? 'common.on' : 'common.off', logPollingEnabled ? '开' : '关') });
    button.classList.toggle('ok', logPollingEnabled);
  }
  if (logPollingEnabled) loadLogs(false).catch(() => {});
}

async function loadDevops() {
  applyAdminPrefs();
  const results = await Promise.allSettled([
    loadEffectiveSettings(),
    loadStoragePolicy(),
    loadPythonPackages(false),
    loadLogs(true),
  ]);
  devopsLoaded = true;
  const failed = results.filter(item => item.status === 'rejected');
  if (failed.length) throw new Error(adminTP('admin.platform.devops_failed', { count: failed.length, error: failed[0].reason?.message || adminT('common.request_failed', '请求失败') }));
  setMsg(adminT('admin.platform.devops_refreshed', '设置与开发运维状态已刷新'));
}

document.querySelector('[data-tab="devops"]')?.addEventListener('click', () => {
  if (!devopsLoaded) loadDevops().catch(error => setMsg(error.message || adminT('admin.platform.devops_load_failed', 'Unable to load Settings and DevOps status'), true));
});
document.getElementById('reloadDevopsBtn')?.addEventListener('click', () => loadDevops().catch(error => setMsg(error.message || adminT('admin.platform.devops_refresh_failed', 'Refresh failed'), true)));
document.getElementById('saveAdminPrefsBtn')?.addEventListener('click', saveAdminPrefs);
document.getElementById('resetAdminPrefsBtn')?.addEventListener('click', resetAdminPrefs);
document.getElementById('reloadPythonPackagesBtn')?.addEventListener('click', () => loadPythonPackages(true).catch(error => setMsg(error.message || adminT('admin.platform.python_check_failed', 'Unable to check the Python environment'), true)));
document.getElementById('installPythonPackageBtn')?.addEventListener('click', () => installPythonPackage().catch(error => setMsg(error.message || adminT('admin.platform.python_install_failed', 'Installation failed'), true)));
document.getElementById('reloadLogsBtn')?.addEventListener('click', () => loadLogs(true).catch(error => setMsg(error.message || adminT('admin.platform.logs_load_failed', 'Unable to load logs'), true)));
document.getElementById('toggleLogPollingBtn')?.addEventListener('click', toggleLogPolling);
document.getElementById('clearLogViewBtn')?.addEventListener('click', () => {
  logRows = [];
  const viewer = document.getElementById('appLogViewer');
  if (viewer) viewer.innerHTML = `<div class="muted">${esc(adminT('admin.platform.log_view_cleared', '日志视图已清空，新日志仍会继续进入。'))}</div>`;
});
document.getElementById('logLevelFilter')?.addEventListener('change', () => loadLogs(true).catch(error => setMsg(error.message || adminT('admin.platform.logs_filter_failed', 'Unable to filter logs'), true)));
document.getElementById('logQueryFilter')?.addEventListener('keydown', event => {
  if (event.key === 'Enter') loadLogs(true).catch(error => setMsg(error.message || adminT('admin.platform.logs_filter_failed', 'Unable to filter logs'), true));
});
document.addEventListener('click', event => {
  if (event.target.closest('#saveStoragePolicyBtn')) saveStoragePolicy().catch(error => setMsg(error.message || adminT('admin.platform.storage_save_failed', 'Unable to save storage limits'), true));
  if (event.target.closest('#resetAllStoragePolicyBtn')) resetAllStoragePolicy().catch(error => setMsg(error.message || adminT('admin.platform.storage_reset_failed', 'Unable to restore defaults'), true));
  const resetPolicy = event.target.closest('[data-storage-policy-reset]');
  if (resetPolicy) resetStoragePolicyKey(resetPolicy.getAttribute('data-storage-policy-reset')).catch(error => setMsg(error.message || adminT('admin.platform.storage_reset_failed', 'Unable to restore defaults'), true));
  const section = event.target.closest('[data-account-section]');
  if (section) loadAccountDetailSection(section.getAttribute('data-account-section'), 1).catch(error => setMsg(error.message || adminT('admin.platform.account_detail_failed', 'Unable to load account details'), true));
  const openTab = event.target.closest('[data-open-admin-tab]');
  if (openTab) activateAdminTab(openTab.getAttribute('data-open-admin-tab'));
  if (event.target.closest('[data-account-detail-close]')) {
    accountDetailState.owner = '';
    accountDetailState.account = null;
  }
});

applyAdminPrefs();
startLogPolling();

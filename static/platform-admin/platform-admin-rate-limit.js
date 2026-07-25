(() => {
  const apiBase = '/api3/admin/rate-limit';
  let state = null;
  let pending = null;

  const t = (key, fallback = '') => adminT(key, fallback);
  const tp = (key, params = null, fallback = '') => adminTP(key, params, fallback);
  const endpointLabel = endpoint => t(`admin.rate.endpoint_${String(endpoint?.name || endpoint || '')}`, String(endpoint?.label || endpoint || '-'));
  const scopeLabel = scope => t(`admin.rate.${String(scope || '')}`, String(scope || '-'));
  const numberValue = value => Number.isFinite(Number(value)) ? Number(value) : 0;

  function setView(name) {
    const active = ['rules', 'summary', 'events'].includes(name) ? name : 'rules';
    document.querySelectorAll('[data-rate-view]').forEach(button => button.classList.toggle('active', button.dataset.rateView === active));
    document.querySelectorAll('[data-rate-panel]').forEach(panel => panel.classList.toggle('active', panel.dataset.ratePanel === active));
  }

  function renderMetrics(data) {
    const summary = data?.summary || {};
    document.getElementById('rateMetricEndpoints').textContent = String(summary.endpoint_count ?? 0);
    document.getElementById('rateMetricAllowed').textContent = String(summary.total_allowed ?? 0);
    document.getElementById('rateMetricBlocked').textContent = String(summary.total_blocked ?? 0);
    document.getElementById('rateMetricBlocks').textContent = String(summary.active_blocks ?? 0);
  }

  function ruleRow(labelKey, limitField, windowField, endpoint) {
    return `<div class="rateRuleRow"><label>${esc(t(labelKey))}</label><input type="number" min="0" max="500" data-rate-field="${esc(limitField)}" value="${esc(endpoint[limitField])}"><span>/</span><input type="number" min="0" max="86400" data-rate-field="${esc(windowField)}" value="${esc(endpoint[windowField])}"><span>${esc(t('admin.rate.seconds', 'sec'))}</span></div>`;
  }

  function renderRules(endpoints) {
    const root = document.getElementById('rateEndpointGrid');
    if (!Array.isArray(endpoints) || !endpoints.length) {
      root.innerHTML = `<div class="muted">${esc(t('admin.rate.no_config', 'No configuration'))}</div>`;
      return;
    }
    root.innerHTML = endpoints.map(endpoint => `<article class="rateEndpointCard" data-rate-endpoint="${esc(endpoint.name)}"><div class="rateEndpointHead"><div><strong>${esc(endpointLabel(endpoint))}</strong><div class="rateEndpointName">${esc(endpoint.name)}</div></div><label class="rateCheck"><input type="checkbox" data-rate-field="enabled" ${endpoint.enabled ? 'checked' : ''}> ${esc(t('admin.rate.enabled', 'Enabled'))}</label></div><div class="rateEndpointRows">${ruleRow('admin.rate.ip', 'ip_limit', 'ip_window_s', endpoint)}${ruleRow('admin.rate.session', 'session_limit', 'session_window_s', endpoint)}${ruleRow('admin.rate.account', 'account_limit', 'account_window_s', endpoint)}<div class="rateRuleRow"><label>${esc(t('admin.rate.block_duration', 'Cooldown'))}</label><input type="number" min="0" max="86400" data-rate-field="block_s" value="${esc(endpoint.block_s)}"><span></span><span>${esc(t('admin.rate.cooldown', 'Cooldown after a limit is reached'))}</span><span>${esc(t('admin.rate.seconds', 'sec'))}</span></div></div><div class="rateEndpointStats"><div>${esc(t('admin.rate.allowed', 'Allowed'))}: <strong>${esc(endpoint.allowed)}</strong><br>${esc(t('admin.rate.last_allowed', 'Last allowed'))}: ${esc(endpoint.last_allowed_at || '-')}</div><div>${esc(t('admin.rate.blocked', 'Limited'))}: <strong>${esc(endpoint.blocked)}</strong><br>${esc(t('admin.rate.last_blocked', 'Last limited'))}: ${esc(endpoint.last_blocked_at || '-')}</div><div>${esc(t('admin.rate.current_blocks', 'Active cooldowns'))}: <strong>${esc(endpoint.active_blocks)}</strong><br>${esc(endpoint.active_blocks ? t('admin.rate.block_active', 'Cooling down') : t('admin.rate.none', 'None'))}</div></div></article>`).join('');
  }

  function renderSummary(endpoints) {
    const body = document.getElementById('rateSummaryBody');
    if (!Array.isArray(endpoints) || !endpoints.length) {
      body.innerHTML = `<tr><td colspan="5" class="muted">${esc(t('admin.rate.no_data', 'No data'))}</td></tr>`;
      return;
    }
    body.innerHTML = endpoints.map(endpoint => `<tr><td>${esc(endpointLabel(endpoint))}<br><span class="muted small">${esc(endpoint.name)}</span></td><td>${esc(endpoint.allowed)}</td><td>${esc(endpoint.blocked)}</td><td>${esc(endpoint.active_blocks)}</td><td>${esc(endpoint.last_blocked_at || '-')}</td></tr>`).join('');
  }

  function renderEvents(items) {
    const root = document.getElementById('rateEventsList');
    if (!Array.isArray(items) || !items.length) {
      root.innerHTML = `<div class="muted">${esc(t('admin.rate.no_events', 'No cooldown records'))}</div>`;
      return;
    }
    root.innerHTML = items.map(item => `<article class="rateEvent"><div class="rateEventTop"><strong>${esc(endpointLabel(item.endpoint))} · ${esc(scopeLabel(item.scope))}</strong><span class="pill warn">${esc(item.ts_text || '-')}</span></div><div class="rateEventMeta">${esc(item.key_display || '-')} · ${esc(t('admin.rate.threshold', 'Threshold'))}: ${esc(item.limit)}/${esc(item.window_s)} ${esc(t('admin.rate.seconds', 'sec'))} · ${esc(t('admin.rate.cooldown', 'Cooldown'))}: ${esc(item.block_s)} ${esc(t('admin.rate.seconds', 'sec'))}</div></article>`).join('');
  }

  function render(data) {
    state = data || {};
    document.getElementById('rateGlobalEnabled').checked = state.global_enabled !== false;
    document.getElementById('rateEventsKeep').value = String(state.events_keep || 120);
    renderMetrics(state);
    renderRules(state.endpoints || []);
    renderSummary(state.endpoints || []);
    renderEvents(state.recent_events || []);
    document.getElementById('rateUpdatedAt').textContent = state.updated_at ? tp('admin.rate.updated', {time: state.updated_at}, `Last updated: ${state.updated_at}`) : '';
  }

  async function refresh(force = false) {
    if (pending) return pending;
    if (state && !force) {
      render(state);
      return state;
    }
    pending = requestJson(`${apiBase}/state`).then(data => {
      render(data);
      return data;
    }).finally(() => {
      pending = null;
    });
    return pending;
  }

  function readConfig() {
    const endpoints = {};
    document.querySelectorAll('[data-rate-endpoint]').forEach(card => {
      const item = {};
      card.querySelectorAll('[data-rate-field]').forEach(input => {
        item[input.dataset.rateField] = input.type === 'checkbox' ? input.checked : numberValue(input.value);
      });
      endpoints[card.dataset.rateEndpoint] = item;
    });
    return {
      global_enabled: document.getElementById('rateGlobalEnabled').checked,
      events_keep: numberValue(document.getElementById('rateEventsKeep').value),
      endpoints,
    };
  }

  async function saveConfig() {
    setMsg(t('admin.rate.saving', 'Saving…'));
    render(await postJson(`${apiBase}/config`, readConfig()));
    setMsg(t('admin.rate.saved', 'Saved'));
  }

  async function reset(payload, successKey, fallback) {
    render(await postJson(`${apiBase}/reset`, payload));
    setMsg(t(successKey, fallback));
  }

  document.querySelectorAll('[data-rate-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.rateView)));
  document.getElementById('reloadRateLimitBtn')?.addEventListener('click', () => refresh(true).catch(error => setMsg(error.message || t('admin.platform.load_failed', 'Unable to load data'), true)));
  document.getElementById('saveRateLimitBtn')?.addEventListener('click', () => saveConfig().catch(error => setMsg(error.message || t('common.save_failed', 'Save failed'), true)));
  document.getElementById('clearRateBlocksBtn')?.addEventListener('click', () => reset({clear_blocks: true, clear_events: false, clear_stats: false}, 'admin.rate.auto_cleared', 'Automatic cooldowns cleared').catch(error => setMsg(error.message || t('common.operation_failed', 'Operation failed'), true)));
  document.getElementById('clearRateStatsBtn')?.addEventListener('click', () => reset({clear_blocks: false, clear_events: true, clear_stats: true}, 'admin.rate.stats_cleared', 'Statistics and records cleared').catch(error => setMsg(error.message || t('common.operation_failed', 'Operation failed'), true)));
  document.addEventListener('apervia:languagechange', () => {
    if (state) render(state);
  });

  setView('rules');
  window.AperviaRateAdmin = {activate: () => refresh(false), refresh};
})();

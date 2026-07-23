/* Independent workspace for image jobs that continue after the chat view times out. */
(function initImagePullbackUi(){
  if(window.__imagePullbackUiBooted) return;
  window.__imagePullbackUiBooted = true;

  const runtime = { jobs: [], opened: false, pollTimer: null, refreshing: false };
  const POLL_MS = 6000;
  const qs = (id) => document.getElementById(id);
  const getMask = () => qs('imagePullbackWorkspace');
  const getSidebarBtn = () => qs('openImagePullbackSidebar');
  const ensureArray = (value) => Array.isArray(value) ? value : [];
  const esc = (value) => typeof escapeHtml === 'function'
    ? escapeHtml(String(value ?? ''))
    : String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
      }[char]));
  const pullbackT = (key, params, fallback='') => window.AperviaI18n?.t(key, params, fallback) || fallback || key;
  const currentLocale = () => window.AperviaI18n?.language === 'zh-CN' ? 'zh-CN' : 'en';

  function formatTimeText(input){
    const raw = Number(input || 0);
    if(!raw) return '';
    const value = raw > 1e12 ? raw : raw * 1000;
    try{
      return new Intl.DateTimeFormat(currentLocale(), {
        month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'
      }).format(new Date(value));
    }catch(_){
      return '';
    }
  }

  function api(path, { method='GET', body=null } = {}){
    const init = { method, cache:'no-store', headers:{} };
    if(body != null){
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(path, init).then(async (res) => {
      let data = {};
      try{ data = await res.json(); }catch(_){ }
      if(!res.ok) throw new Error(data?.error || data?.message || ('HTTP ' + res.status));
      return data || {};
    });
  }

  function normalizeStatus(status){
    const key = String(status || '').trim().toLowerCase();
    if(key === 'done') return { key:'done', label:pullbackT('pullback.status_done', null, 'Completed') };
    if(key === 'error') return { key:'error', label:pullbackT('pullback.status_error', null, 'Failed') };
    if(key === 'expired') return { key:'expired', label:pullbackT('pullback.status_expired', null, 'Expired') };
    return { key:'running', label:pullbackT('pullback.status_running', null, 'Generating') };
  }

  function isFrontendTimeoutPullbackJob(job){
    const reason = String(job?.reason || job?.pullback_reason || '').trim().toLowerCase();
    return ['frontend_soft_timeout', 'frontend_timeout', 'soft_timeout'].includes(reason);
  }

  function normalizeJobs(rows){
    return ensureArray(rows).filter(isFrontendTimeoutPullbackJob);
  }

  function getLastSeenTs(){
    try{ return Number(localStorage.getItem('image_pullback_last_seen_ts') || 0) || 0; }
    catch(_){ return 0; }
  }

  function markSeen(){
    try{ localStorage.setItem('image_pullback_last_seen_ts', String(Date.now())); }
    catch(_){ }
  }

  function updateBadge(){
    const badge = qs('imagePullbackBadge');
    if(!badge) return;
    const lastSeen = getLastSeenTs();
    const unread = runtime.opened ? 0 : runtime.jobs.filter((job) => {
      const raw = Number(job?.updated_ts || 0);
      const updatedMs = raw > 1e12 ? raw : raw * 1000;
      return String(job?.status || '').trim().toLowerCase() === 'done' && updatedMs > lastSeen;
    }).length;
    const hasUnreadDone = unread > 0;
    badge.hidden = !hasUnreadDone;
    badge.textContent = '';
    const unreadLabel = hasUnreadDone ? pullbackT('pullback.unread', null, 'New retrieved image results') : '';
    badge.setAttribute('aria-label', unreadLabel);
    badge.title = unreadLabel;
  }

  function renderStats(){
    const el = qs('imagePullbackStats');
    if(!el) return;
    const jobs = runtime.jobs;
    const running = jobs.filter((job) => !['done', 'error', 'expired'].includes(String(job?.status || '').toLowerCase())).length;
    const done = jobs.filter((job) => String(job?.status || '').toLowerCase() === 'done').length;
    const failed = jobs.filter((job) => ['error', 'expired'].includes(String(job?.status || '').toLowerCase())).length;
    const images = jobs.reduce((sum, job) => sum + ensureArray(job?.images).length, 0);
    const stats = [
      [pullbackT('pullback.stat_all', null, 'All jobs'), jobs.length],
      [pullbackT('pullback.stat_running', null, 'Generating'), running],
      [pullbackT('pullback.stat_done', null, 'Completed'), done],
      [pullbackT('pullback.stat_images', null, 'Result images'), images]
    ];
    el.innerHTML = stats.map(([label, value]) => `
      <div class="pullback-stat-item">
        <div class="pullback-stat-value">${value}</div>
        <div class="pullback-stat-label">${label}</div>
      </div>
    `).join('') + (failed ? `<div class="pullback-stat-alert">${esc(pullbackT('pullback.unfinished', {count:failed}, `${failed} jobs unfinished`))}</div>` : '');
  }

  function renderUpdatedAt(text=''){
    const el = qs('imagePullbackUpdatedAt');
    if(!el) return;
    const time = new Date().toLocaleTimeString(currentLocale(), { hour:'2-digit', minute:'2-digit' });
    el.textContent = text || pullbackT('pullback.synced', {time}, `Synced automatically · ${time}`);
  }

  function setRefreshState(refreshing){
    runtime.refreshing = !!refreshing;
    const btn = qs('imagePullbackRefreshBtn');
    if(btn){
      btn.disabled = runtime.refreshing;
      btn.classList.toggle('is-loading', runtime.refreshing);
      btn.setAttribute('aria-busy', runtime.refreshing ? 'true' : 'false');
    }
    if(runtime.refreshing) renderUpdatedAt(pullbackT('pullback.syncing', null, 'Syncing…'));
  }

  function imageDownloadIcon(){
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path></svg>';
  }

  function deleteIcon(){
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path></svg>';
  }

  function emptyImageIcon(){
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="8.5" cy="9" r="1.5"></circle><path d="m5 17 4.5-4.5 3.2 3.2 2.1-2.1L19 17"></path></svg>';
  }

  function renderImages(images, jobId){
    const list = ensureArray(images);
    if(!list.length) return '';
    return `<div class="pullback-image-grid">${list.map((img, idx) => {
      const preview = esc(img?.preview_url || img?.view_url || img?.download_url || '');
      const download = esc(img?.download_url || img?.view_url || img?.preview_url || '');
      const filename = esc(img?.filename || ('image_' + (idx + 1) + '.png'));
      const caption = esc(img?.caption || img?.filename || pullbackT('pullback.result_image', {index:idx + 1}, `Result image ${idx + 1}`));
      const previewLabel = esc(pullbackT('pullback.preview_file', {filename}, `Preview ${filename}`));
      const downloadLabel = esc(pullbackT('pullback.download_file', {filename}, `Download ${filename}`));
      return `<figure class="pullback-image-card">
        <button class="pullback-image-preview" type="button" data-pullback-job="${esc(jobId)}" data-pullback-index="${idx}" aria-label="${previewLabel}">
          <img class="pullback-image-thumb" src="${preview}" alt="${filename}" loading="lazy" decoding="async">
          <span class="pullback-image-preview-label">${esc(pullbackT('pullback.preview', null, 'Preview'))}</span>
        </button>
        <figcaption class="pullback-image-caption">
          <span title="${caption}">${caption}</span>
          <a class="pullback-image-download" href="${download}" target="_blank" rel="noopener noreferrer" title="${downloadLabel}" aria-label="${downloadLabel}">${imageDownloadIcon()}</a>
        </figcaption>
      </figure>`;
    }).join('')}</div>`;
  }

  function renderJobBody(job, state){
    const images = ensureArray(job?.images);
    if(images.length) return renderImages(images, job?.id || '');
    if(state.key === 'running'){
      return `<div class="pullback-job-waiting"><span class="pullback-waiting-spinner" aria-hidden="true"></span><span>${esc(pullbackT('pullback.job_running', null, 'The job is still generating in the background. Results will appear here automatically.'))}</span></div>`;
    }
    if(state.key === 'done'){
      return `<div class="pullback-job-waiting">${esc(pullbackT('pullback.job_done_empty', null, 'The job completed without returning a usable image.'))}</div>`;
    }
    return '';
  }

  function renderList(){
    renderStats();
    const el = qs('imagePullbackList');
    const clearBtn = qs('imagePullbackClearBtn');
    if(clearBtn) clearBtn.disabled = runtime.jobs.length === 0;
    if(!el) return;
    const jobs = runtime.jobs;
    if(!jobs.length){
      el.innerHTML = `<div class="pullback-empty">
        <div class="pullback-empty-icon">${emptyImageIcon()}</div>
        <strong>${esc(pullbackT('pullback.empty_title', null, 'No retrieval jobs'))}</strong>
        <p>${esc(pullbackT('pullback.empty_desc', null, 'Image jobs that time out in a conversation will continue here automatically.'))}</p>
      </div>`;
      return;
    }

    el.innerHTML = jobs.map((job, idx) => {
      const state = normalizeStatus(job?.status);
      const rawTitle = String(job?.prompt || pullbackT('pullback.job_title', {index:idx + 1}, `Image job ${idx + 1}`)).trim();
      const title = esc(rawTitle);
      const meta = [
        job?.session_title ? `<span>${esc(job.session_title)}</span>` : '',
        formatTimeText(job?.updated_ts) ? `<span>${esc(formatTimeText(job.updated_ts))}</span>` : '',
        ensureArray(job?.images).length ? `<span>${esc(pullbackT('pullback.image_count', {count:ensureArray(job.images).length}, `${ensureArray(job.images).length} images`))}</span>` : ''
      ].filter(Boolean).join('');
      const errorText = esc(job?.error || '');
      return `<article class="pullback-job-card" data-pullback-id="${esc(job?.id || '')}">
        <div class="pullback-job-top">
          <div class="pullback-job-heading">
            <div class="pullback-job-title" title="${title}">${title}</div>
            ${meta ? `<div class="pullback-job-meta">${meta}</div>` : ''}
          </div>
          <div class="pullback-job-actions">
            <span class="pullback-status-pill status-${state.key}"><span class="pullback-status-dot" aria-hidden="true"></span>${state.label}</span>
            <button class="pullback-job-delete" type="button" title="${esc(pullbackT('pullback.delete_record', null, 'Delete record'))}" aria-label="${esc(pullbackT('pullback.delete_record', null, 'Delete record'))}" data-pullback-delete="${esc(job?.id || '')}">${deleteIcon()}</button>
          </div>
        </div>
        ${errorText ? `<div class="pullback-job-error">${errorText}</div>` : ''}
        ${renderJobBody(job, state)}
      </article>`;
    }).join('');

    el.querySelectorAll('[data-pullback-delete]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = String(btn.getAttribute('data-pullback-delete') || '').trim();
        if(!id) return;
        const ok = await askKbDangerConfirm({
          title:pullbackT('pullback.delete_title', null, 'Delete this retrieval record?'),
          desc:pullbackT('pullback.delete_desc', null, 'This cannot be undone.'),
          confirmText:pullbackT('common.confirm', null, 'Confirm'),
          cancelText:pullbackT('common.cancel', null, 'Cancel')
        }, btn);
        if(!ok) return;
        try{
          await api('/api3/image-pullback/delete', { method:'POST', body:{ id } });
          runtime.jobs = runtime.jobs.filter((job) => String(job?.id || '').trim() !== id);
          renderList();
          updateBadge();
          if(typeof toast === 'function') toast(pullbackT('pullback.deleted', null, 'Deleted'));
        }catch(err){
          if(typeof reportAppError === 'function') reportAppError(err?.message || pullbackT('pullback.delete_failed', null, 'Delete failed'));
        }
      });
    });

    el.querySelectorAll('.pullback-image-preview').forEach((node) => {
      node.addEventListener('click', async () => {
        const jobId = String(node.getAttribute('data-pullback-job') || '').trim();
        const startIndex = Math.max(0, Number(node.getAttribute('data-pullback-index') || 0));
        const job = runtime.jobs.find((item) => String(item?.id || '').trim() === jobId);
        const items = ensureArray(job?.images).map((img) => ({
          src:String(img?.view_url || img?.preview_url || img?.download_url || '').trim(),
          alt:String(img?.filename || '').trim()
        }));
        if(!items.length) return;
        if(typeof openImageLightbox === 'function'){
          await openImageLightbox(items, startIndex);
        }else{
          const target = items[startIndex]?.src || items[0]?.src || '';
          if(target) window.open(target, '_blank', 'noopener');
        }
      });
    });
  }

  async function refreshImagePullbackJobs({ silent=false } = {}){
    if(runtime.refreshing) return runtime.jobs;
    if(silent) runtime.refreshing = true;
    else setRefreshState(true);
    try{
      const data = await api('/api3/image-pullback/list');
      runtime.jobs = normalizeJobs(data?.jobs);
      renderList();
      renderUpdatedAt();
      if(runtime.opened) markSeen();
      updateBadge();
      return runtime.jobs;
    }catch(err){
      renderUpdatedAt(pullbackT('pullback.sync_failed', null, 'Sync failed. Apervia will retry automatically.'));
      if(!silent && typeof reportAppError === 'function') reportAppError(err?.message || pullbackT('pullback.list_failed', null, 'Unable to load retrieval jobs'));
      return runtime.jobs;
    }finally{
      if(silent) runtime.refreshing = false;
      else setRefreshState(false);
    }
  }

  async function clearImagePullbackJobs(){
    if(!runtime.jobs.length){
      renderList();
      return;
    }
    const ok = await askKbDangerConfirm({
      title:pullbackT('pullback.clear_title', null, 'Clear all retrieval records?'),
      desc:pullbackT('pullback.clear_desc', {count:runtime.jobs.length}, `This will delete ${runtime.jobs.length} retrieval records.`),
      confirmText:pullbackT('common.confirm', null, 'Confirm'),
      cancelText:pullbackT('common.cancel', null, 'Cancel')
    }, qs('imagePullbackClearBtn'));
    if(!ok) return;
    try{
      await api('/api3/image-pullback/clear', { method:'POST', body:{ reason:'frontend_soft_timeout' } });
      runtime.jobs = [];
      renderList();
      updateBadge();
      renderUpdatedAt();
      if(typeof toast === 'function') toast(pullbackT('pullback.cleared', null, 'Cleared'));
    }catch(err){
      if(typeof reportAppError === 'function') reportAppError(err?.message || pullbackT('pullback.clear_failed', null, 'Clear failed'));
    }
  }

  function setOpen(open){
    const visible = !!open;
    runtime.opened = visible;
    const mask = getMask();
    const btn = getSidebarBtn();
    const main = qs('main');
    try{ document.body?.classList.toggle('pullback-open', visible); }catch(_){ }
    main?.classList.toggle('pullback-page-open', visible);
    document.querySelectorAll('#workspace > :not(#imagePullbackWorkspace), #main > .topbar, #main > .composer').forEach((el) => {
      if(visible){
        if(!el.hasAttribute('data-pullback-prev-inert')) el.setAttribute('data-pullback-prev-inert', el.inert ? '1' : '0');
        el.inert = true;
      }else{
        const previous = el.getAttribute('data-pullback-prev-inert');
        if(previous != null){
          el.inert = previous === '1';
          el.removeAttribute('data-pullback-prev-inert');
        }
      }
    });
    if(mask){
      mask.classList.toggle('open', visible);
      mask.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }
    if(btn) btn.classList.toggle('is-active', visible);
    if(visible){
      markSeen();
      updateBadge();
      refreshImagePullbackJobs({ silent:true });
    }
  }

  async function trackImagePullbackFromAsyncJob(payload = {}){
    const sourceJobId = String(payload?.sourceJobId || payload?.source_job_id || '').trim();
    if(!sourceJobId) throw new Error(pullbackT('pullback.missing_source_job', null, 'Missing source_job_id'));
    const data = await api('/api3/image-pullback/track', {
      method:'POST',
      body:{
        source_job_id:sourceJobId,
        session_id:String(payload?.sessionId || payload?.session_id || '').trim(),
        session_title:String(payload?.sessionTitle || payload?.session_title || '').trim(),
        prompt:String(payload?.prompt || '').trim(),
        reason:String(payload?.reason || 'frontend_soft_timeout').trim() || 'frontend_soft_timeout'
      }
    });
    await refreshImagePullbackJobs({ silent:true });
    return data || { ok:true };
  }

  function boot(){
    qs('openImagePullbackSidebar')?.addEventListener('click', () => {
      if(typeof openImagePullbackRoute === 'function') openImagePullbackRoute();
      else setOpen(true);
    });
    qs('imagePullbackSidebarToggleBtn')?.addEventListener('click', () => {
      if(typeof applySidebarCollapsed === 'function') applySidebarCollapsed(false);
    });
    qs('imagePullbackRefreshBtn')?.addEventListener('click', () => refreshImagePullbackJobs());
    qs('imagePullbackClearBtn')?.addEventListener('click', () => clearImagePullbackJobs());
    document.addEventListener('apervia:languagechange', () => {
      renderList();
      renderUpdatedAt();
      updateBadge();
    });
    renderList();
    if(typeof isImagePullbackRoute === 'function' && isImagePullbackRoute()) setOpen(true);
    refreshImagePullbackJobs({ silent:true });
    const loop = async () => {
      try{ await refreshImagePullbackJobs({ silent:true }); }catch(_){ }
      runtime.pollTimer = setTimeout(loop, POLL_MS);
    };
    runtime.pollTimer = setTimeout(loop, POLL_MS);
  }

  window.refreshImagePullbackJobs = refreshImagePullbackJobs;
  window.trackImagePullbackFromAsyncJob = trackImagePullbackFromAsyncJob;
  window.openImagePullbackWorkspace = (opts={}) => {
    if(opts?.syncRoute !== false && typeof openImagePullbackRoute === 'function') return openImagePullbackRoute(opts);
    return setOpen(true);
  };
  window.closeImagePullbackWorkspace = (opts={}) => {
    if(opts?.syncRoute !== false && typeof closeImagePullbackRoute === 'function') return closeImagePullbackRoute(opts);
    return setOpen(false);
  };
  boot();
})();

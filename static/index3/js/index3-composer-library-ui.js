const COMPOSER_FILE_LIBRARY_PICKER_PAGE_SIZE = 30;
const COMPOSER_FILE_LIBRARY_RECENT_MENU_LIMIT = 3;
const composerFileLibraryPickerState = { files:[], type:'all', filter:'', hasMore:false, nextOffset:0, loading:false };
let composerFileLibraryRecentCache = { ts:0, files:[] };
let composerFileLibraryRecentLoading = null;
let composerFileLibraryFilterTimer = null;

function composerLibraryT(key, params, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

function normalizeComposerFileLibraryId(item){
  return String(item?.file_id || item?.id || item?.registry_file_id || '').trim();
}

function composerFileLibraryItemIsImage(item){
  return String(item?.category || '').trim().toLowerCase() === 'image';
}

function fileLibrarySourceKind(item){
  const source = String(item?.source || '').trim().toLowerCase();
  const namespace = String(item?.namespace || '').trim().toLowerCase();
  if(source === 'generated' || namespace === 'generated') return 'generated';
  if(source === 'pullback') return 'retrieved';
  return 'uploaded';
}

function fileLibrarySourceLabel(item){
  const kind = fileLibrarySourceKind(item);
  const labels = {
    generated:['library.source.generated', 'Generated file'],
    retrieved:['library.source.retrieved', 'Retrieved image'],
    uploaded:['library.source.uploaded', 'Uploaded file'],
  };
  const [key, fallback] = labels[kind] || labels.uploaded;
  return composerLibraryT(key, null, fallback);
}

function composerFileLibrarySourceType(item){
  return fileLibrarySourceKind(item) === 'generated' ? 'generated' : 'upload';
}

function composerFileLibraryItemIsGenerated(item){
  return composerFileLibrarySourceType(item) === 'generated';
}

function composerFileLibraryImageOriginalUrl(item){
  return String(item?.model_storage_ref || item?.storage_ref || item?.view_url || item?.download_url || item?.url || '').trim();
}

function composerFileLibraryImagePreviewUrl(item){
  return String(item?.preview_url || item?.preview_download_url || item?.view_url || item?.download_url || item?.url || item?.model_storage_ref || item?.storage_ref || '').trim();
}

function composerFileLibraryImageModelUrl(item){
  const backendRef = composerLibraryStableModelSource(item?.model_storage_ref) || composerLibraryStableModelSource(item?.storage_ref);
  const preview = composerFileLibraryImagePreviewUrl(item);
  const original = composerFileLibraryImageOriginalUrl(item);
  return backendRef || (composerFileLibraryItemIsGenerated(item) ? (preview || original) : (original || preview));
}

function composerFileLibraryExtLabel(item){
  const raw = String(item?.ext || '').replace(/^\./, '').trim().toUpperCase();
  if(raw) return raw;
  return composerFileLibraryItemIsImage(item) ? 'IMG' : 'FILE';
}

function composerFileLibraryMetaText(item){
  return [
    fileLibrarySourceLabel(item),
    composerFileLibraryExtLabel(item),
    fmtBytes(Number(item?.size || 0) || 0),
  ].filter(Boolean).join(' · ');
}

function composerFileLibraryRegistryPayload(item){
  const fileId = normalizeComposerFileLibraryId(item);
  const sourceType = composerFileLibrarySourceType(item);
  return {
    ...(item && typeof item === 'object' ? item : {}),
    file_id: fileId,
    source: String(item?.source || sourceType || 'upload').trim() || sourceType || 'upload',
    namespace: String(item?.namespace || (sourceType === 'generated' ? 'generated' : 'uploads')).trim() || (sourceType === 'generated' ? 'generated' : 'uploads'),
    filename: String(item?.filename || item?.saved_filename || composerLibraryT('composer.library.unnamed', null, 'Untitled file')).trim(),
    saved_filename: String(item?.saved_filename || item?.filename || '').trim(),
    ext: String(item?.ext || '').trim(),
    url: String(item?.url || item?.download_url || item?.view_url || '').trim(),
    view_url: String(item?.view_url || item?.url || '').trim(),
    download_url: String(item?.download_url || item?.url || item?.view_url || '').trim(),
    preview_url: String(item?.preview_url || '').trim(),
    storage_ref: String(item?.storage_ref || '').trim(),
    model_storage_ref: String(item?.model_storage_ref || item?.storage_ref || '').trim(),
    full_text_available: !!item?.full_text_available,
    summary: String(item?.summary || '').trim(),
    size: Number(item?.size || 0) || 0,
  };
}

function composerFileLibraryIsAlreadyAttached(item){
  const fileId = normalizeComposerFileLibraryId(item);
  const original = composerFileLibraryImageOriginalUrl(item);
  const preview = composerFileLibraryImagePreviewUrl(item);
  if(composerFileLibraryItemIsImage(item)){
    return (pastedImages || []).some((img)=>{
      const reg = img?.file_registry && typeof img.file_registry === 'object' ? img.file_registry : {};
      return !!(
        (fileId && (String(img?.file_library_id || '').trim() === fileId || String(reg.file_id || '').trim() === fileId || String(img?.model_storage_ref || '').trim() === fileId || String(img?.storage_ref || '').trim() === fileId))
        || (original && (String(img?._source_url || '').trim() === original || String(img?.image_url?.url || '').trim() === original || String(img?.persisted_url || '').trim() === original))
        || (preview && (String(img?._preview_url || '').trim() === preview || String(img?.image_url?.url || '').trim() === preview))
      );
    });
  }
  return (pendingFiles || []).some((file)=>{
    const reg = file?.file_registry && typeof file.file_registry === 'object' ? file.file_registry : {};
    return !!(
      (fileId && (String(file?.id || '').trim() === fileId || String(file?.file_library_id || '').trim() === fileId || String(reg.file_id || '').trim() === fileId))
      || (!fileId && String(file?.download_url || file?.url || '').trim() && String(file.download_url || file.url || '').trim() === String(item?.download_url || item?.url || '').trim())
    );
  });
}

function addComposerAttachmentFromFileLibraryItem(item, opts={}){
  const row = item && typeof item === 'object' ? item : {};
  const fileId = normalizeComposerFileLibraryId(row);
  const filename = String(row.filename || row.saved_filename || composerLibraryT('composer.library.unnamed', null, 'Untitled file')).trim() || composerLibraryT('composer.library.unnamed', null, 'Untitled file');
  if(composerFileLibraryIsAlreadyAttached(row)){
    if(opts.toast !== false && typeof toast === 'function') toast(window.AperviaI18n?.t('composer.library.in_composer') || 'Already added to the composer');
    return false;
  }
  if(composerFileLibraryItemIsImage(row)){
    assertComposerCanAcceptAttachment('image');
    const modelUrl = composerFileLibraryImageModelUrl(row);
    const previewUrl = composerFileLibraryImagePreviewUrl(row) || modelUrl;
    const originalUrl = composerFileLibraryImageOriginalUrl(row) || modelUrl;
    if(!modelUrl && !fileId) throw new Error('这个图片没有可用链接');
    const composerId = 'libimg_' + Math.random().toString(16).slice(2) + '_' + Date.now().toString(16);
    const registryPayload = composerFileLibraryRegistryPayload(row);
    const modelSource = composerLibraryStableModelSource(modelUrl) || composerLibraryStableModelSource(row.model_storage_ref) || composerLibraryStableModelSource(row.storage_ref) || composerLibraryStableModelSource(registryPayload.model_storage_ref) || composerLibraryStableModelSource(registryPayload.storage_ref);
    const displayUrl = previewUrl || originalUrl || modelSource || '';
    const imgItem = ensureComposerImageAttachmentMeta({
      type:'image_url',
      attachment_id: fileId || ('lib_' + composerId),
      image_id: fileId || ('lib_' + composerId),
      storage_ref: modelSource || '',
      model_storage_ref: modelSource || '',
      file_library_id: fileId,
      library_file_id: fileId,
      file_registry: registryPayload,
      image_url:{ url: displayUrl },
      preview_url: displayUrl,
      view_url: String(row.view_url || registryPayload.view_url || displayUrl || '').trim(),
      download_url: String(row.download_url || registryPayload.download_url || row.view_url || registryPayload.view_url || displayUrl || '').trim(),
      persisted_url: modelSource || originalUrl || '',
      server_url: displayUrl || originalUrl || modelSource || '',
      _preview_url: displayUrl,
      _source_url: originalUrl || modelSource || '',
      filename,
      _ocr_text: String(row.summary || '').trim(),
      source_role:'user',
      source_type:'file_library',
      operation:'library_reuse',
      _composerId: composerId,
      _sessionId: getComposerAttachmentOwnerSessionId(),
    }, { prefix:'libimg', sourceRole:'user', operation:'library_reuse', endpointMode:getActiveApiEndpointMode() });
    pastedImages.push(imgItem);
    addImageThumb(imgItem);
    persistComposerAttachmentDraft(getComposerAttachmentOwnerSessionId(), { immediate:true });
    updateComposerActionState();
    updateComposerPlaceholder();
    setStatus(composerFileLibraryItemIsGenerated(row) && previewUrl && previewUrl === modelUrl ? '已从库中添加图片预览图（待发送）' : '已从库中添加图片（待发送）');
    return true;
  }

  assertComposerCanAcceptAttachment('file');
  const sourceType = composerFileLibrarySourceType(row);
  const url = String(row.download_url || row.url || row.view_url || '').trim();
  const att = {
    id: fileId || newAttId(),
    file_library_id: fileId,
    kind:'file',
    source_type: sourceType,
    source_role: sourceType === 'generated' ? 'assistant_generated' : 'user_upload',
    filename,
    ext: composerFileLibraryExtLabel(row),
    text:'',
    text_is_preview:false,
    full_text_available: !!row.full_text_available,
    parsed_chars: Number(row.full_text_chars || row.parsed_chars || 0) || 0,
    parsed_lines: Number(row.full_text_lines || row.parsed_lines || 0) || 0,
    url,
    view_url: String(row.view_url || row.url || '').trim(),
    download_url: url,
    size: Number(row.size || 0) || 0,
    note:'从上传文件库添加',
    file_registry: composerFileLibraryRegistryPayload(row),
    code_summary: String(row.summary || '').trim(),
    symbols: Array.isArray(row.symbols) ? row.symbols : [],
    kb_imported: !!row.joined_kb || Number(row.kb_doc_count || 0) > 0,
  };
  pendingFiles.push(att);
  addPendingFileCard(att);
  persistComposerAttachmentDraft(getComposerAttachmentOwnerSessionId(), { immediate:true });
  updateComposerActionState();
  updateComposerPlaceholder();
  setStatus('已从库中添加文件（待发送）');
  return true;
}

function ensureComposerFileLibraryStyle(){
  if(document.getElementById('composerFileLibraryStyle')) return;
  const style = document.createElement('style');
  style.id = 'composerFileLibraryStyle';
  style.textContent = `
    .composer-library-mask{position:fixed;inset:0;z-index:1350;display:none;align-items:center;justify-content:center;padding:22px;background:rgba(8,10,14,.42);backdrop-filter:blur(12px);}
    .composer-library-mask.open{display:flex;}
    .composer-library-card{width:min(760px,94vw);height:min(760px,88vh);display:flex;flex-direction:column;overflow:hidden;border-radius:24px;border:1px solid color-mix(in srgb,var(--border) 78%, transparent);background:color-mix(in srgb,var(--panel) 98%, var(--bg));box-shadow:0 24px 90px rgba(0,0,0,.26);color:var(--fg);}
    .composer-library-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px;border-bottom:1px solid color-mix(in srgb,var(--border) 72%, transparent);}
    .composer-library-title{display:grid;gap:4px;min-width:0;}
    .composer-library-title strong{font-size:20px;line-height:1.25;}
    .composer-library-title span{font-size:12px;color:var(--muted);}
    .composer-library-close{width:36px;height:36px;border:0;border-radius:12px;background:transparent;color:var(--fg);font-size:24px;line-height:1;cursor:pointer;}
    .composer-library-close:hover{background:color-mix(in srgb,var(--fg) 7%, transparent);}
    .composer-library-tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid color-mix(in srgb,var(--border) 64%, transparent);}
    .composer-library-search{flex:1 1 260px;min-width:180px;height:42px;border-radius:14px;border:1px solid color-mix(in srgb,var(--border) 78%, transparent);background:color-mix(in srgb,var(--panel) 94%, var(--bg));color:var(--fg);padding:0 13px;font-size:14px;}
    .composer-library-tabs{display:inline-flex;gap:4px;padding:4px;border-radius:14px;background:color-mix(in srgb,var(--fg) 5%, transparent);}
    .composer-library-tab{height:34px;padding:0 12px;border:0;border-radius:11px;background:transparent;color:var(--muted);font-size:12px;font-weight:750;cursor:pointer;}
    .composer-library-tab.active{background:color-mix(in srgb,var(--panel) 98%, var(--bg));color:var(--fg);}
    .composer-library-list{flex:1;min-height:0;overflow:auto;padding:12px;display:grid;gap:8px;align-content:start;}
    .composer-library-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center;padding:12px;border-radius:16px;border:1px solid color-mix(in srgb,var(--border) 74%, transparent);background:color-mix(in srgb,var(--panel) 94%, var(--bg));}
    .composer-library-thumb{width:42px;height:42px;border-radius:12px;border:1px solid color-mix(in srgb,var(--border) 70%, transparent);display:grid;place-items:center;overflow:hidden;background:color-mix(in srgb,var(--fg) 5%, transparent);color:var(--muted);font-size:17px;}
    .composer-library-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
    .composer-library-main{min-width:0;display:grid;gap:4px;}
    .composer-library-name{font-size:14px;font-weight:800;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .composer-library-meta{font-size:12px;color:var(--muted);line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .composer-library-add,.composer-library-loadmore{height:34px;padding:0 12px;border-radius:12px;border:1px solid color-mix(in srgb,var(--border) 76%, transparent);background:color-mix(in srgb,var(--fg) 6%, transparent);color:var(--fg);font-size:12px;font-weight:800;cursor:pointer;}
    .composer-library-add:hover,.composer-library-loadmore:hover{background:color-mix(in srgb,var(--fg) 10%, transparent);}
    .composer-library-add:disabled{opacity:.55;cursor:default;}
    .composer-library-empty{padding:34px 14px;text-align:center;color:var(--muted);font-size:14px;}
    .composer-library-foot{padding:10px 16px;border-top:1px solid color-mix(in srgb,var(--border) 64%, transparent);display:flex;justify-content:center;}
    #composerAddLibrarySubmenu{width:min(360px,calc(100vw - 28px));max-width:calc(100vw - 28px);max-height:none;overflow:visible;box-sizing:border-box;}
    #composerAddLibrarySubmenu .composer-add-submenu-item{min-height:52px;box-sizing:border-box;max-width:100%;overflow:hidden;display:grid;grid-template-columns:26px minmax(0,1fr) 18px;align-items:center;column-gap:12px;justify-content:initial;}
    #composerAddLibrarySubmenu .composer-add-submenu-item[data-composer-library-open]{grid-template-columns:26px minmax(0,1fr) 18px;}
    #composerAddLibrarySubmenu .composer-add-item-main{min-width:0;overflow:hidden;}
    #composerAddLibrarySubmenu .composer-add-item-title,#composerAddLibrarySubmenu .composer-add-item-sub{display:block;max-width:100%;min-width:0;}
    #composerAddLibrarySubmenu .composer-add-check{justify-self:end;}
    .composer-add-recent-header{height:28px;padding:0 10px;display:flex;align-items:center;color:var(--muted);font-size:12px;font-weight:750;}
    .composer-add-library-icon{width:22px;min-width:22px;height:26px;display:inline-flex;align-items:center;justify-content:center;overflow:visible;background:transparent;color:var(--fg);opacity:.9;flex:0 0 auto;}
    .composer-add-recent-thumb{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;overflow:hidden;background:color-mix(in srgb,var(--fg) 7%, transparent);color:var(--fg);flex:0 0 auto;}
    .composer-add-library-icon svg{width:21px;height:21px;display:block;}
    .composer-add-recent-thumb svg{width:18px;height:18px;display:block;}
    .composer-add-submenu-item .composer-add-recent-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
    .composer-add-menu-icon svg{width:21px;height:21px;display:block;}
  `;
  document.head.appendChild(style);
}

function ensureComposerFileLibraryPicker(){
  ensureComposerFileLibraryStyle();
  let mask = document.getElementById('composerFileLibraryMask');
  if(mask) return mask;
  mask = document.createElement('div');
  mask.id = 'composerFileLibraryMask';
  mask.className = 'composer-library-mask';
  mask.setAttribute('aria-hidden', 'true');
  mask.innerHTML = `
    <div class="composer-library-card" role="dialog" aria-modal="true" aria-label="从库中添加" data-i18n-aria-label="composer.library.add_from">
      <div class="composer-library-head">
        <div class="composer-library-title"><strong data-i18n="composer.library.add_from">从库中添加</strong><span data-i18n="composer.library.add_from_desc">复用上传文件库里的文件和图片，不重复上传。</span></div>
        <button id="composerLibraryCloseBtn" class="composer-library-close" type="button" aria-label="关闭" data-i18n-aria-label="common.close">×</button>
      </div>
      <div class="composer-library-tools">
        <input id="composerLibrarySearchInput" class="composer-library-search" type="search" placeholder="搜索库" data-i18n-placeholder="composer.library.search">
        <div class="composer-library-tabs" role="tablist" aria-label="文件类型">
          <button class="composer-library-tab active" type="button" data-composer-library-type="all" data-i18n="composer.library.all">全部</button>
          <button class="composer-library-tab" type="button" data-composer-library-type="image" data-i18n="composer.library.images">图片</button>
          <button class="composer-library-tab" type="button" data-composer-library-type="file" data-i18n="composer.library.files">文件</button>
        </div>
      </div>
      <div id="composerLibraryList" class="composer-library-list"></div>
      <div class="composer-library-foot"><button id="composerLibraryLoadMoreBtn" class="composer-library-loadmore" type="button" hidden data-i18n="composer.library.load_more">加载更多</button></div>
    </div>`;
  document.body.appendChild(mask);
  const close = ()=> closeComposerFileLibraryPicker();
  mask.addEventListener('click', (event)=>{ if(event.target === mask) close(); });
  mask.querySelector('#composerLibraryCloseBtn')?.addEventListener('click', close);
  mask.querySelector('#composerLibrarySearchInput')?.addEventListener('input', (event)=>{
    composerFileLibraryPickerState.filter = String(event.target?.value || '').trim();
    clearTimeout(composerFileLibraryFilterTimer);
    composerFileLibraryFilterTimer = setTimeout(()=> composerFileLibraryLoadPage({ reset:true }), 220);
  });
  mask.querySelectorAll('[data-composer-library-type]').forEach((btn)=>{
    btn.addEventListener('click', ()=>{
      composerFileLibraryPickerState.type = String(btn.getAttribute('data-composer-library-type') || 'all');
      mask.querySelectorAll('[data-composer-library-type]').forEach(x=>x.classList.toggle('active', x === btn));
      composerFileLibraryLoadPage({ reset:true });
    });
  });
  mask.querySelector('#composerLibraryLoadMoreBtn')?.addEventListener('click', ()=> composerFileLibraryLoadPage({ reset:false }));
  mask.querySelector('#composerLibraryList')?.addEventListener('click', (event)=>{
    const btn = event.target?.closest?.('[data-composer-library-add]');
    if(!btn) return;
    const fileId = String(btn.getAttribute('data-composer-library-add') || '').trim();
    const item = composerFileLibraryPickerState.files.find(x => normalizeComposerFileLibraryId(x) === fileId);
    if(!item) return;
    try{
      const added = addComposerAttachmentFromFileLibraryItem(item);
      if(added){
        btn.textContent = composerLibraryT('composer.library.added', null, 'Added');
        btn.disabled = true;
      }
    }catch(err){
      if(typeof reportAppError === 'function') reportAppError(`添加失败：${err.message || err}`);
    }
  });
  document.addEventListener('keydown', (event)=>{
    if(event.key === 'Escape' && mask.classList.contains('open')){
      event.preventDefault();
      close();
    }
  });
  return mask;
}

function closeComposerFileLibraryPicker(){
  const mask = document.getElementById('composerFileLibraryMask');
  if(!mask) return;
  mask.classList.remove('open');
  mask.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
}

function composerFileLibraryStateUrl({ offset=0, limit=COMPOSER_FILE_LIBRARY_PICKER_PAGE_SIZE, type='all', filter='' } = {}){
  const params = new URLSearchParams();
  params.set('offset', String(Math.max(0, Number(offset || 0) || 0)));
  params.set('limit', String(Math.max(1, Math.min(100, Number(limit || COMPOSER_FILE_LIBRARY_PICKER_PAGE_SIZE) || COMPOSER_FILE_LIBRARY_PICKER_PAGE_SIZE))));
  params.set('type', ['all','image','file'].includes(String(type || '').trim()) ? String(type || 'all').trim() : 'all');
  params.set('sort', 'updated_desc');
  const q = String(filter || '').trim();
  if(q) params.set('filter', q);
  return '/api3/file-library/state?' + params.toString();
}

async function composerFileLibraryApi(path, { method='GET', body=null } = {}){
  const init = { method, headers:{} };
  if(body != null){
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let data = {};
  try{ data = await res.json(); }catch(_){ }
  if(!res.ok) throw new Error(data?.error || data?.message || ('HTTP ' + res.status));
  return data || {};
}

function renderComposerFileLibraryPicker(){
  const mask = ensureComposerFileLibraryPicker();
  const list = mask.querySelector('#composerLibraryList');
  const loadMore = mask.querySelector('#composerLibraryLoadMoreBtn');
  const files = composerFileLibraryPickerState.files || [];
  if(!list) return;
  if(composerFileLibraryPickerState.loading && !files.length){
    if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.render(list, { variant:'compact-list', rows:5, label:composerLibraryT('composer.library.loading', null, 'Loading library') });
    else list.innerHTML = `<div class="composer-library-empty">${escapeHtml(composerLibraryT('composer.library.loading_short', null, 'Loading…'))}</div>`;
  }else if(!files.length){
    if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(list);
    list.innerHTML = `<div class="composer-library-empty">${escapeHtml(composerLibraryT('composer.library.no_files', null, 'No files found'))}</div>`;
  }else{
    if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(list);
    list.innerHTML = files.map((item)=>{
      const idRaw = normalizeComposerFileLibraryId(item);
      const id = escapeHtml(idRaw);
      const name = escapeHtml(String(item?.filename || item?.saved_filename || composerLibraryT('composer.library.unnamed', null, 'Untitled file')));
      const isImage = composerFileLibraryItemIsImage(item);
      const thumbUrl = isImage ? composerFileLibraryImagePreviewUrl(item) : '';
      const thumb = isImage && thumbUrl ? `<img src="${escapeHtml(thumbUrl)}" alt="${name}" loading="lazy" decoding="async">` : (isImage ? '🖼' : '📄');
      const added = composerFileLibraryIsAlreadyAttached(item);
      const meta = escapeHtml(composerFileLibraryMetaText(item));
      return `<article class="composer-library-row" data-composer-library-id="${id}">
        <div class="composer-library-thumb">${thumb}</div>
        <div class="composer-library-main"><div class="composer-library-name" title="${name}">${name}</div><div class="composer-library-meta">${meta}</div></div>
        <button class="composer-library-add" type="button" data-composer-library-add="${id}" ${added ? 'disabled' : ''}>${escapeHtml(composerLibraryT(added ? 'composer.library.added' : 'composer.library.add', null, added ? 'Added' : 'Add'))}</button>
      </article>`;
    }).join('');
  }
  if(loadMore){
    loadMore.hidden = !composerFileLibraryPickerState.hasMore;
    loadMore.disabled = !!composerFileLibraryPickerState.loading;
    loadMore.textContent = composerLibraryT(composerFileLibraryPickerState.loading ? 'common.loading' : 'composer.library.load_more', null, composerFileLibraryPickerState.loading ? 'Loading…' : 'Load more');
  }
}

async function composerFileLibraryLoadPage({ reset=false } = {}){
  const state = composerFileLibraryPickerState;
  if(state.loading) return;
  state.loading = true;
  if(reset){
    state.files = [];
    state.nextOffset = 0;
    state.hasMore = false;
  }
  renderComposerFileLibraryPicker();
  try{
    const data = await composerFileLibraryApi(composerFileLibraryStateUrl({ offset:state.nextOffset, type:state.type, filter:state.filter }));
    const next = Array.isArray(data.files) ? data.files : [];
    const seen = new Set((state.files || []).map(normalizeComposerFileLibraryId).filter(Boolean));
    const merged = reset ? [] : (state.files || []).slice();
    for(const item of next){
      const id = normalizeComposerFileLibraryId(item);
      if(id && seen.has(id)) continue;
      if(id) seen.add(id);
      merged.push(item);
    }
    state.files = merged;
    state.hasMore = !!data?.page?.has_more;
    state.nextOffset = Number(data?.page?.next_offset ?? merged.length) || merged.length;
  }catch(err){
    if(typeof reportAppError === 'function') reportAppError(`载入文件库失败：${err.message || err}`);
  }finally{
    state.loading = false;
    renderComposerFileLibraryPicker();
  }
}

function openComposerFileLibraryPicker(){
  closeComposerAddMenu();
  const mask = ensureComposerFileLibraryPicker();
  mask.classList.add('open');
  mask.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  const input = mask.querySelector('#composerLibrarySearchInput');
  if(input) input.value = composerFileLibraryPickerState.filter || '';
  setTimeout(()=>{ try{ input?.focus?.(); }catch(_){ } }, 0);
  composerFileLibraryLoadPage({ reset:true });
}

function composerFileLibraryIconSvg(kind='file'){
  const k = String(kind || '').trim().toLowerCase();
  if(k === 'library'){
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="3.8" y="5" width="4.4" height="14" rx="1.45"></rect><rect x="8.6" y="5" width="4.4" height="14" rx="1.45"></rect><path d="M15.25 5.1c.86-.17 1.7.39 1.87 1.25l2.18 10.92c.17.86-.39 1.7-1.25 1.87l-1.08.22c-.86.17-1.7-.39-1.87-1.25L12.92 7.19c-.17-.86.39-1.7 1.25-1.87l1.08-.22Z"></path></svg>';
  }
  if(k === 'recent'){
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="5" y="4" width="14" height="16" rx="3"></rect><path d="M9 8h6"></path><path d="M9 12h6"></path><path d="M9 16h4"></path></svg>';
  }
  if(k === 'image'){
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="4" y="5" width="16" height="14" rx="3"></rect><circle cx="9" cy="10" r="1.3"></circle><path d="m7 17 4.2-4.2a1.8 1.8 0 0 1 2.6 0L17 16"></path></svg>';
  }
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M8 4h5l4 4v12H8a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"></path><path d="M13 4v5h5"></path><path d="m10 13-2 2 2 2"></path><path d="m14 13 2 2-2 2"></path></svg>';
}

function ensureComposerLibraryMenuShell(){
  ensureComposerFileLibraryStyle();
  const menu = document.getElementById('composerAddMenu');
  const uploadBtn = document.getElementById('composerAddUploadBtn');
  if(!menu || !uploadBtn) return null;
  let wrap = document.getElementById('composerAddLibraryWrap');
  if(wrap) return wrap;
  wrap = document.createElement('div');
  wrap.id = 'composerAddLibraryWrap';
  wrap.className = 'composer-add-submenu-wrap';
  wrap.innerHTML = `
    <button id="composerAddLibraryBtn" class="composer-add-menu-item" type="button" role="menuitem" aria-haspopup="menu" aria-expanded="false">
      <span class="composer-add-menu-icon" aria-hidden="true">${composerFileLibraryIconSvg('recent')}</span>
      <span class="composer-add-menu-label" data-i18n="composer.library.recent">近期文件</span>
      <span class="composer-add-menu-caret" aria-hidden="true">›</span>
    </button>
    <div id="composerAddLibrarySubmenu" class="composer-add-submenu" role="menu" aria-label="近期文件" data-i18n-aria-label="composer.library.recent"></div>`;
  uploadBtn.insertAdjacentElement('afterend', wrap);
  const submenu = wrap.querySelector('#composerAddLibrarySubmenu');
  submenu?.addEventListener('click', (event)=>{
    const openBtn = event.target?.closest?.('[data-composer-library-open]');
    if(openBtn){
      event.preventDefault();
      event.stopPropagation();
      openComposerFileLibraryPicker();
      return;
    }
    const addBtn = event.target?.closest?.('[data-composer-library-recent-add]');
    if(addBtn){
      event.preventDefault();
      event.stopPropagation();
      const id = String(addBtn.getAttribute('data-composer-library-recent-add') || '').trim();
      const item = (composerFileLibraryRecentCache.files || []).find(x => normalizeComposerFileLibraryId(x) === id);
      if(!item) return;
      try{
        if(addComposerAttachmentFromFileLibraryItem(item)){
          addBtn.classList.add('active');
          const check = addBtn.querySelector('.composer-add-check');
          if(check) check.style.opacity = '1';
        }
        closeComposerAddMenu();
      }catch(err){
        if(typeof reportAppError === 'function') reportAppError(`添加失败：${err.message || err}`);
      }
    }
  });
  return wrap;
}

function renderComposerLibraryRecentMenu(files=[], loading=false){
  const wrap = ensureComposerLibraryMenuShell();
  const submenu = wrap?.querySelector?.('#composerAddLibrarySubmenu');
  if(!submenu) return;
  const rows = Array.isArray(files) ? files.slice(0, COMPOSER_FILE_LIBRARY_RECENT_MENU_LIMIT) : [];
  const openRow = `<button class="composer-add-submenu-item" type="button" data-composer-library-open="1" role="menuitem"><span class="composer-add-library-icon" aria-hidden="true">${composerFileLibraryIconSvg('library')}</span><span class="composer-add-item-main"><span class="composer-add-item-title">${escapeHtml(composerLibraryT('composer.library.add_from', null, 'Add from library'))}</span><span class="composer-add-item-sub">${escapeHtml(composerLibraryT('composer.library.search_uploads', null, 'Search uploaded files'))}</span></span><span class="composer-add-check" aria-hidden="true"></span></button>`;
  if(loading && !rows.length){
    const skeleton = typeof AppLoadingUi !== 'undefined'
      ? AppLoadingUi.html({ variant:'compact-list', rows:3, label:composerLibraryT('composer.library.loading_recent', null, 'Loading recent files') })
      : `<button class="composer-add-submenu-item disabled" type="button" disabled><span class="composer-add-item-main"><span class="composer-add-item-title">${escapeHtml(composerLibraryT('composer.library.loading_recent_short', null, 'Loading recent files…'))}</span></span></button>`;
    submenu.innerHTML = `${openRow}<div class="composer-add-menu-sep" aria-hidden="true"></div>${skeleton}`;
    submenu.setAttribute('aria-busy', 'true');
    return;
  }
  submenu.removeAttribute('aria-busy');
  if(!rows.length){
    submenu.innerHTML = `${openRow}<div class="composer-add-menu-sep" aria-hidden="true"></div><button class="composer-add-submenu-item disabled" type="button" disabled><span class="composer-add-item-main"><span class="composer-add-item-title">${escapeHtml(composerLibraryT('composer.library.no_recent', null, 'No recent files'))}</span><span class="composer-add-item-sub">${escapeHtml(composerLibraryT('composer.library.no_recent_desc', null, 'Uploaded files will appear here.'))}</span></span></button>`;
    return;
  }
  const recentHtml = rows.map((item)=>{
    const id = escapeHtml(normalizeComposerFileLibraryId(item));
    const name = escapeHtml(String(item?.filename || item?.saved_filename || composerLibraryT('composer.library.unnamed', null, 'Untitled file')));
    const isImage = composerFileLibraryItemIsImage(item);
    const thumbUrl = isImage ? composerFileLibraryImagePreviewUrl(item) : '';
    const thumb = isImage && thumbUrl ? `<img src="${escapeHtml(thumbUrl)}" alt="">` : composerFileLibraryIconSvg(isImage ? 'image' : 'file');
    const meta = escapeHtml(composerFileLibraryMetaText(item));
    const added = composerFileLibraryIsAlreadyAttached(item);
    return `<button class="composer-add-submenu-item${added ? ' active' : ''}" type="button" data-composer-library-recent-add="${id}" role="menuitem">
      <span class="composer-add-recent-thumb" aria-hidden="true">${thumb}</span>
      <span class="composer-add-item-main"><span class="composer-add-item-title">${name}</span><span class="composer-add-item-sub">${meta}</span></span>
      <span class="composer-add-check">✓</span>
    </button>`;
  }).join('');
  submenu.innerHTML = `${openRow}<div class="composer-add-menu-sep" aria-hidden="true"></div><div class="composer-add-recent-header">${escapeHtml(composerLibraryT('composer.library.recent_heading', null, 'Recent'))}</div>${recentHtml}`;
}

async function loadComposerLibraryRecentFiles(force=false){
  const nowTs = Date.now();
  if(!force && (nowTs - Number(composerFileLibraryRecentCache.ts || 0)) < 20000 && Array.isArray(composerFileLibraryRecentCache.files)){
    renderComposerLibraryRecentMenu(composerFileLibraryRecentCache.files, false);
    return composerFileLibraryRecentCache.files;
  }
  if(composerFileLibraryRecentLoading) return composerFileLibraryRecentLoading;
  renderComposerLibraryRecentMenu(composerFileLibraryRecentCache.files || [], true);
  composerFileLibraryRecentLoading = (async()=>{
    try{
      const data = await composerFileLibraryApi(composerFileLibraryStateUrl({ offset:0, limit:COMPOSER_FILE_LIBRARY_RECENT_MENU_LIMIT, type:'all', filter:'' }));
      const files = Array.isArray(data.files) ? data.files : [];
      composerFileLibraryRecentCache = { ts:Date.now(), files };
      renderComposerLibraryRecentMenu(files, false);
      return files;
    }catch(_){
      renderComposerLibraryRecentMenu(composerFileLibraryRecentCache.files || [], false);
      return composerFileLibraryRecentCache.files || [];
    }finally{
      composerFileLibraryRecentLoading = null;
    }
  })();
  return composerFileLibraryRecentLoading;
}

function syncComposerLibraryRecentMenu(){
  ensureComposerLibraryMenuShell();
  loadComposerLibraryRecentFiles(false);
}

function renderComposerAddApiMenu(){
  const submenu = document.getElementById("composerAddApiSubmenu");
  const current = document.getElementById("composerAddApiCurrent");
  if(!submenu) return;
  const mode = (typeof getActiveApiEndpointMode === "function") ? getActiveApiEndpointMode() : API_ENDPOINT_MODE_CHAT;
  if(typeof ensureApiProfileForMode === "function") ensureApiProfileForMode(mode);
  const profiles = (typeof getApiProfiles === "function") ? getApiProfiles() : {};
  const active = (typeof getActiveApiName === "function") ? getActiveApiName(mode) : "";
  if(current) current.textContent = `${apiEndpointModeLabel(mode)} · ${apiProfileDisplayName(active || DEFAULT_API_PROFILE_NAME)}`;
  submenu.innerHTML = "";
  const names = Object.keys(profiles || {}).filter(name => apiProfileMatchesMode(profiles[name], mode));
  if(!names.length){
    const empty = document.createElement("button");
    empty.type = "button";
    empty.className = "composer-add-submenu-item disabled";
    empty.disabled = true;
    empty.innerHTML = '<span class="composer-add-item-main"><span class="composer-add-item-title">暂无可切换 API</span><span class="composer-add-item-sub">请先到设置里保存 Key</span></span>';
    submenu.appendChild(empty);
    return;
  }
  names.forEach((name)=>{
    const profile = profiles[name] || {};
    const item = document.createElement("button");
    item.type = "button";
    item.className = "composer-add-submenu-item" + (name === active ? " active" : "");
    item.setAttribute("role", "menuitemradio");
    item.setAttribute("aria-checked", name === active ? "true" : "false");
    const main = document.createElement("span");
    main.className = "composer-add-item-main";
    const title = document.createElement("span");
    title.className = "composer-add-item-title";
    title.textContent = apiProfileDisplayName(name);
    const sub = document.createElement("span");
    sub.className = "composer-add-item-sub";
    const base = String(profile.api_base || API_DEFAULT_BASE || "").trim();
    const baseText = (typeof shortApiBase === "function") ? shortApiBase(base) : base;
    const endpointText = apiEndpointModeLabel(profile.api_endpoint_mode);
    sub.textContent = [baseText, endpointText].filter(Boolean).join(" · ");
    main.appendChild(title);
    if(sub.textContent) main.appendChild(sub);
    const check = document.createElement("span");
    check.className = "composer-add-check";
    check.textContent = "✓";
    item.appendChild(main);
    item.appendChild(check);
    item.addEventListener("click", (event)=>{
      event.preventDefault();
      event.stopPropagation();
      if(typeof setActiveApiName === "function") setActiveApiName(name);
      syncComposerAddMenuUi();
      closeComposerAddMenu();
    });
    submenu.appendChild(item);
  });
}

function syncComposerAddModeMenu(){
  const endpointMode = getActiveApiEndpointMode();
  const current = document.getElementById("composerAddModeCurrent");
  if(current) current.textContent = apiEndpointModeLabel(endpointMode);
  document.querySelectorAll(".composer-add-endpoint-option").forEach((btn)=>{
    const active = normalizeApiEndpointMode(btn.dataset.endpointMode || "") === endpointMode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-checked", active ? "true" : "false");
  });
  document.querySelectorAll(".composer-add-toggle-option").forEach((btn)=>{
    const id = String(btn.dataset.toggleId || "");
    const source = document.getElementById(id);
    const on = !!source?.checked;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-checked", on ? "true" : "false");
    const state = btn.querySelector(".composer-add-toggle-state");
    if(state){
      state.textContent = on ? "开启" : "关闭";
      state.classList.toggle("on", on);
    }
  });
}

function syncComposerAddMenuUi(){
  renderComposerAddApiMenu();
  syncComposerAddModeMenu();
  syncComposerLibraryRecentMenu();
}

function closeComposerAddSubmenus(exceptWrap=null){
  document.querySelectorAll(".composer-add-submenu-wrap.submenu-open").forEach((wrap)=>{
    if(exceptWrap && wrap === exceptWrap) return;
    wrap.classList.remove("submenu-open");
    wrap.querySelector(":scope > .composer-add-menu-item")?.setAttribute("aria-expanded", "false");
  });
}

function closeComposerAddMenu(){
  const shell = document.getElementById("composerInputShell");
  const menu = document.getElementById("composerAddMenu");
  if(shell) shell.classList.remove("add-menu-open");
  document.body?.classList.remove("composer-add-menu-open");
  if(menu) menu.setAttribute("aria-hidden", "true");
  if(addFileBtn) addFileBtn.setAttribute("aria-expanded", "false");
  closeComposerAddSubmenus();
}

function openComposerAddMenu(){
  const shell = document.getElementById("composerInputShell");
  const menu = document.getElementById("composerAddMenu");
  if(!shell || !menu || !addFileBtn || addFileBtn.disabled) return;
  syncComposerAddMenuUi();
  shell.classList.add("add-menu-open");
  document.body?.classList.add("composer-add-menu-open");
  menu.setAttribute("aria-hidden", "false");
  addFileBtn.setAttribute("aria-expanded", "true");
}

function toggleComposerAddMenu(){
  const shell = document.getElementById("composerInputShell");
  if(shell?.classList.contains("add-menu-open")) closeComposerAddMenu();
  else openComposerAddMenu();
}

function initComposerAddMenuUI(){
  const shell = document.getElementById("composerInputShell");
  const menu = document.getElementById("composerAddMenu");
  const uploadBtn = document.getElementById("composerAddUploadBtn");
  if(!shell || !menu || !addFileBtn) return;
  ensureComposerLibraryMenuShell();

  addFileBtn.addEventListener("click", (event)=>{
    event.preventDefault();
    event.stopPropagation();
    toggleComposerAddMenu();
  });

  uploadBtn?.addEventListener("click", (event)=>{
    event.preventDefault();
    event.stopPropagation();
    closeComposerAddMenu();
    fileEl.value = "";
    fileEl.click();
  });

  document.querySelectorAll(".composer-add-submenu-wrap > .composer-add-menu-item").forEach((btn)=>{
    btn.addEventListener("click", (event)=>{
      event.preventDefault();
      event.stopPropagation();
      const wrap = btn.closest(".composer-add-submenu-wrap");
      if(!wrap) return;
      const opening = !wrap.classList.contains("submenu-open");
      closeComposerAddSubmenus(wrap);
      wrap.classList.toggle("submenu-open", opening);
      btn.setAttribute("aria-expanded", opening ? "true" : "false");
    });
  });

  document.querySelectorAll(".composer-add-endpoint-option").forEach((btn)=>{
    btn.addEventListener("click", (event)=>{
      event.preventDefault();
      event.stopPropagation();
      setCurrentApiEndpointMode(btn.dataset.endpointMode || API_ENDPOINT_MODE_CHAT);
      syncComposerAddMenuUi();
    });
  });

  document.querySelectorAll(".composer-add-toggle-option").forEach((btn)=>{
    btn.addEventListener("click", (event)=>{
      event.preventDefault();
      event.stopPropagation();
      const source = document.getElementById(String(btn.dataset.toggleId || ""));
      if(!source) return;
      source.checked = !source.checked;
      source.dispatchEvent(new Event("change", { bubbles:true }));
      syncComposerAddMenuUi();
    });
  });

  menu.addEventListener("click", (event)=>event.stopPropagation());
  document.addEventListener("pointerdown", (event)=>{
    const target = event.target;
    if(addFileBtn.contains(target) || menu.contains(target)) return;
    closeComposerAddMenu();
  }, true);
  document.addEventListener("keydown", (event)=>{
    if(event.key === "Escape") closeComposerAddMenu();
  });
  window.addEventListener("resize", ()=>closeComposerAddMenu(), { passive:true });
  syncComposerAddMenuUi();
}

document.addEventListener('apervia:languagechange', ()=>{
  if(document.getElementById('composerFileLibraryMask')) renderComposerFileLibraryPicker();
  if(document.getElementById('composerAddLibrarySubmenu')){
    renderComposerLibraryRecentMenu(composerFileLibraryRecentCache.files || [], !!composerFileLibraryRecentLoading);
  }
  syncComposerAddModeMenu();
});

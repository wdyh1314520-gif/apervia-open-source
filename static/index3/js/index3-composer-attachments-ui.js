function fmtBytes(n){
  const b = Number(n||0);
  if(!b) return "0B";
  const units = ["B","KB","MB","GB"];
  let v=b, i=0;
  while(v>=1024 && i<units.length-1){ v/=1024; i++; }
  return (v>=10 || i===0 ? v.toFixed(0) : v.toFixed(1)) + units[i];
}

function composerAttachmentT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

const uploadPreviewMap = new Map();
const composerUploadTaskMap = new Map();

function createUploadCanceledError(message=composerAttachmentT('composer.attachment.upload_canceled', null, 'Upload canceled')){
  const err = new Error(message);
  err.name = "AbortError";
  err.code = "upload_canceled";
  return err;
}

function isUploadCanceledError(err){
  return !!err && (err.code === "upload_canceled" || (err.name === "AbortError" && /取消|cancell?ed|abort/i.test(String(err.message || ""))));
}

class ComposerUploadTask {
  constructor(id="", kind="file"){
    this.id = String(id || "");
    this.kind = String(kind || "file");
    this.aborted = false;
    this.abortReason = "";
    this.uploadId = "";
    this.controllers = new Set();
    this.xhrs = new Set();
  }
  throwIfAborted(){
    if(this.aborted) throw createUploadCanceledError();
  }
  trackController(controller){
    if(!controller) return controller;
    this.controllers.add(controller);
    if(this.aborted){
      try{ controller.abort("upload_canceled"); }catch(_){ }
    }
    return controller;
  }
  untrackController(controller){
    try{ this.controllers.delete(controller); }catch(_){ }
  }
  trackXhr(xhr){
    if(!xhr) return xhr;
    this.xhrs.add(xhr);
    if(this.aborted){
      try{ xhr.abort(); }catch(_){ }
    }
    return xhr;
  }
  untrackXhr(xhr){
    try{ this.xhrs.delete(xhr); }catch(_){ }
  }
  setUploadId(uploadId){
    this.uploadId = String(uploadId || "").trim();
    if(this.aborted && this.uploadId) this.cancelRemoteChunkUpload();
  }
  cancelRemoteChunkUpload(){
    const uploadId = String(this.uploadId || "").trim();
    if(!uploadId || typeof fetch !== "function") return;
    try{
      fetch("/api3/upload_chunk/cancel", {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body:JSON.stringify({ upload_id:uploadId }),
        cache:"no-store",
        keepalive:true
      }).catch(()=>{});
    }catch(_){ }
  }
  abort(reason="upload_canceled"){
    if(this.aborted) return;
    this.aborted = true;
    this.abortReason = String(reason || "upload_canceled");
    for(const ctl of Array.from(this.controllers)){
      try{ ctl.abort("upload_canceled"); }catch(_){ }
    }
    for(const xhr of Array.from(this.xhrs)){
      try{ xhr.abort(); }catch(_){ }
    }
    this.cancelRemoteChunkUpload();
  }
}

function createComposerUploadTask(id="", kind="file"){
  const task = new ComposerUploadTask(id, kind);
  if(id) composerUploadTaskMap.set(String(id), task);
  return task;
}

function getComposerUploadTask(id){
  return composerUploadTaskMap.get(String(id || "")) || null;
}

function deleteComposerUploadTask(id){
  composerUploadTaskMap.delete(String(id || ""));
}

function hasBlockingComposerAttachmentUploads(){
  try{
    for(const rec of uploadPreviewMap.values()){
      if(rec && rec.phase !== "done") return true;
    }
  }catch(_){ }
  if(Array.isArray(pastedImages)){
    return pastedImages.some(img => !!img?._upload_pending || !!img?._ocr_pending || !!String(img?._upload_error || "").trim());
  }
  return false;
}

function createStatusNode(text, state="loading") {
  const wrap = document.createElement("span");
  wrap.className = "file-status" + (state === "ready" ? " ready" : state === "error" ? " error" : "");
  if(state === "loading") {
    const sp = document.createElement("span");
    sp.className = "thinking-spinner";
    wrap.appendChild(sp);
  }
  const tx = document.createElement("span");
  tx.textContent = text;
  wrap.appendChild(tx);
  return wrap;
}

function createProgressRing(size="small"){
  const wrap = document.createElement("span");
  wrap.className = "upload-progress-ring indeterminate";
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 36 36");
  const bg = document.createElementNS(svgNS, "circle");
  bg.setAttribute("class", "ring-bg");
  bg.setAttribute("cx", "18"); bg.setAttribute("cy", "18"); bg.setAttribute("r", "15");
  const fg = document.createElementNS(svgNS, "circle");
  fg.setAttribute("class", "ring-fg");
  fg.setAttribute("cx", "18"); fg.setAttribute("cy", "18"); fg.setAttribute("r", "15");
  const c = 2 * Math.PI * 15;
  fg.style.strokeDasharray = `0 ${c}`;
  fg.style.strokeDashoffset = '0';
  svg.appendChild(bg);
  svg.appendChild(fg);
  wrap.appendChild(svg);
  wrap._fg = fg;
  wrap._bg = bg;
  wrap._circumference = c;
  wrap._size = size === "thumb" ? "thumb" : "small";
  setRingProgress(wrap, 0);
  return wrap;
}

function setRingProgress(ringEl, percent, indeterminate=false){
  if(!ringEl || !ringEl._fg) return;
  const c = Number(ringEl._circumference || 0);
  if(!(c > 0)) return;
  const p = Math.max(0, Math.min(100, Number(percent || 0)));
  ringEl.classList.toggle("indeterminate", !!indeterminate);
  const arc = indeterminate
    ? Math.max(c * 0.22, 18)
    : Math.max(0, Math.min(c, c * (p / 100)));
  ringEl._fg.style.strokeDasharray = `${arc} ${c}`;
  ringEl._fg.style.strokeDashoffset = '0';
}

function previewHandle(file){
  return addLocalUploadingPreview(file);
}

function addLocalUploadingPreview(file){
  const tempId = "upload_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
  const isImage = !!(file && file.type && file.type.startsWith("image/"));
  const task = createComposerUploadTask(tempId, isImage ? "image" : "file");

  if(isImage){
    const wrap = document.createElement("div");
    wrap.className = "thumb pending-upload";
    wrap.dataset.attId = tempId;

    const img = document.createElement("img");
    const localUrl = URL.createObjectURL(file);
    img.src = localUrl;
    wrap.appendChild(img);
    attachPreviewableImage(img, localUrl);

    const progressWrap = document.createElement("div");
    progressWrap.className = "thumb-progress";
    const ring = createProgressRing("thumb");
    progressWrap.appendChild(ring);
    wrap.appendChild(progressWrap);

    const status = document.createElement("div");
    status.className = "thumb-status";
    const tx = document.createElement("span");
    tx.textContent = "";
    status.appendChild(tx);
    status.classList.add("hidden");
    wrap.appendChild(status);

    const x = document.createElement("button");
    x.className = "x";
    x.type = "button";
    x.textContent = "×";
    x.title = composerAttachmentT('composer.attachment.cancel_upload', null, 'Cancel upload');
    x.setAttribute("aria-label", x.title);
    x.onclick = ()=> cancelLocalUploadingPreview(tempId);
    wrap.appendChild(x);

    imagePreviewEl.appendChild(wrap);
    refreshComposerLayoutSoon();
    uploadPreviewMap.set(tempId, { type:"image", el:wrap, statusEl:status, progressWrap, ringEl:ring, localUrl, phase:"uploading", task });
    updateComposerActionState();
    return tempId;
  }

  let card = document.createElement("div");
  card.className = "file-card pending-upload";
  card.dataset.attId = tempId;

  const icon = document.createElement("div");
  icon.className = "file-icon";
  icon.textContent = "📎";

  const main = document.createElement("div");
  main.className = "file-main";
  const name = document.createElement("div");
  name.className = "file-name";
  name.textContent = file?.name || composerAttachmentT('composer.attachment.unnamed_file', null, 'Untitled file');
  const meta = document.createElement("div");
  meta.className = "file-meta";
  const progressWrap = document.createElement("span");
  progressWrap.className = "upload-progress-wrap";
  const ring = createProgressRing();
  const label = document.createElement("span");
  label.className = "upload-progress-text";
  label.textContent = "0%";
  progressWrap.appendChild(ring);
  progressWrap.appendChild(label);
  meta.appendChild(progressWrap);
  if(file?.size){
    const size = document.createElement("span");
    size.textContent = fmtBytes(file.size);
    meta.appendChild(size);
  }
  if(typeof buildUnifiedFileCardNode === 'function'){
    card = buildUnifiedFileCardNode({
      filename:file?.name || composerAttachmentT('composer.attachment.unnamed_file', null, 'Untitled file'),
      metaNode:meta,
      className:'composer-file-card pending-upload',
      onRemove:()=>cancelLocalUploadingPreview(tempId),
      removeTitle:composerAttachmentT('composer.attachment.cancel_upload', null, 'Cancel upload'),
    });
  }else{
    main.appendChild(name);
    main.appendChild(meta);
    card.appendChild(icon);
    card.appendChild(main);
    const x = document.createElement("button");
    x.className = "file-x";
    x.type = "button";
    x.textContent = "×";
    x.title = composerAttachmentT('composer.attachment.cancel_upload', null, 'Cancel upload');
    x.setAttribute("aria-label", x.title);
    x.onclick = ()=> cancelLocalUploadingPreview(tempId);
    card.appendChild(x);
  }
  card.dataset.attId = tempId;
  imagePreviewEl.appendChild(card);
  refreshComposerLayoutSoon();
  uploadPreviewMap.set(tempId, { type:"file", el:card, metaEl:meta, progressWrap, ringEl:ring, labelEl:label, phase:"uploading", task });
  updateComposerActionState();
  return tempId;
}

function getLocalUploadingPreviewTask(tempId){
  const rec = uploadPreviewMap.get(tempId);
  return rec?.task || getComposerUploadTask(tempId);
}

function updateLocalUploadingPreviewProgress(tempId, percent, phase="uploading"){
  const rec = uploadPreviewMap.get(tempId);
  if(!rec) return;
  const p = Math.max(0, Math.min(100, Number(percent || 0)));
  rec.phase = phase || rec.phase || "uploading";
  const uploading = rec.phase === "uploading";
  setRingProgress(rec.ringEl, p, !uploading);
  if(rec.type === "image"){
    const tx = rec.statusEl?.querySelector("span:last-child") || rec.statusEl?.querySelector("span");
    if(rec.statusEl) rec.statusEl.classList.add("hidden");
    if(tx) tx.textContent = "";
    return;
  }
  if(rec.labelEl){
    rec.labelEl.textContent = uploading ? `${Math.round(p)}%` : (rec.phase === "parsing" ? composerAttachmentT('composer.attachment.parsing', null, 'Parsing…') : `${Math.round(p)}%`);
  }
}

function markLocalUploadingPreviewParsing(tempId){
  const rec = uploadPreviewMap.get(tempId);
  if(!rec) return;
  rec.phase = "parsing";
  setRingProgress(rec.ringEl, 100, true);
  if(rec.type === "image"){
    const tx = rec.statusEl?.querySelector("span:last-child") || rec.statusEl?.querySelector("span");
    if(rec.statusEl) rec.statusEl.classList.add("hidden");
    if(tx) tx.textContent = "";
  }else if(rec.labelEl){
    rec.labelEl.textContent = composerAttachmentT('composer.attachment.parsing', null, 'Parsing…');
  }
}

function markLocalUploadingPreviewReady(tempId){
  const rec = uploadPreviewMap.get(tempId);
  if(!rec) return;
  rec.phase = "done";
  setRingProgress(rec.ringEl, 100, false);
  rec.ringEl?.classList.remove("indeterminate");
  rec.ringEl?.classList.add("ready");
  if(rec.type === "image") {
    if(rec.progressWrap) rec.progressWrap.classList.add("done");
    const statusText = rec.statusEl?.querySelector("span:last-child") || rec.statusEl?.querySelector("span");
    if(rec.statusEl) rec.statusEl.classList.add("hidden");
    if(statusText) statusText.textContent = "";
    rec.el.classList.remove('pending-upload');
    updateComposerActionState();
    return;
  }
  if(rec.metaEl){
    rec.metaEl.innerHTML = "";
    rec.metaEl.appendChild(createStatusNode(composerAttachmentT('composer.attachment.parsed_ready', null, 'Parsed · ready to send'), "ready"));
  }
  rec.el.classList.remove("pending-upload");
  updateComposerActionState();
}

function markLocalUploadingPreviewError(tempId, msg){
  const rec = uploadPreviewMap.get(tempId);
  if(!rec) return;
  setRingProgress(rec.ringEl, 100, false);
  rec.ringEl?.classList.remove("indeterminate");
  rec.ringEl?.classList.add("error");
  const label = msg || composerAttachmentT('composer.attachment.parse_failed', null, 'Parsing failed');
  if(rec.type === "image") {
    if(rec.progressWrap) rec.progressWrap.classList.add("done");
    const statusText = rec.statusEl?.querySelector("span:last-child") || rec.statusEl?.querySelector("span");
    if(rec.statusEl) rec.statusEl.classList.remove("hidden");
    if(statusText) statusText.textContent = label;
  }else if(rec.metaEl){
    rec.metaEl.innerHTML = "";
    rec.metaEl.appendChild(createStatusNode(label, "error"));
  }
  try{ clearTimeout(rec.errorClearTimer); }catch(_){}
  rec.errorClearTimer = setTimeout(()=>{
    clearLocalUploadingPreview(tempId);
    try{ refreshComposerLayoutSoon(); }catch(_){}
  }, 1600);
}

function clearLocalUploadingPreview(tempId, opts={}){
  const rec = uploadPreviewMap.get(tempId);
  if(!rec) return;
  if(opts?.abort){
    try{ rec.task?.abort("upload_canceled"); }catch(_){ }
  }
  try{ if(rec.localUrl) URL.revokeObjectURL(rec.localUrl); }catch(_){}
  try{ rec.el?.remove(); }catch(_){}
  uploadPreviewMap.delete(tempId);
  deleteComposerUploadTask(tempId);
  refreshComposerLayoutSoon();
  updateComposerActionState();
}

function cancelLocalUploadingPreview(tempId){
  const rec = uploadPreviewMap.get(tempId);
  if(!rec) return;
  try{ rec.task?.abort("upload_canceled"); }catch(_){ }
  clearLocalUploadingPreview(tempId);
  try{ setStatus(composerAttachmentT('composer.attachment.upload_canceled', null, 'Upload canceled')); }catch(_){ }
  updateComposerActionState();
}

function addPendingFileCard(att){
  if(typeof buildUnifiedFileCardNode === 'function'){
    let unifiedCard = null;
    unifiedCard = buildUnifiedFileCardNode({
      filename:att.filename || '',
      metaText:att.kb_imported
        ? composerAttachmentT('composer.attachment.file_indexed', null, 'File · indexed')
        : composerAttachmentT('composer.attachment.file', null, 'File'),
      className:'composer-file-card',
      onRemove:()=>{
        pendingFiles = pendingFiles.filter(it => it.id !== att.id);
        unifiedCard?.remove();
        persistComposerAttachmentDraft(getComposerAttachmentOwnerSessionId(), { immediate:true });
        updateComposerActionState();
        refreshComposerLayoutSoon();
      },
      removeTitle:composerAttachmentT('composer.attachment.remove', null, 'Remove attachment'),
    });
    unifiedCard.dataset.attId = att.id;
    const detailParts = [String(att.ext || '').trim(), att.size ? fmtBytes(att.size) : ''].filter(Boolean);
    if(detailParts.length) unifiedCard.title = detailParts.join(' · ');
    imagePreviewEl.appendChild(unifiedCard);
    refreshComposerLayoutSoon();
    return unifiedCard;
  }
  const card = document.createElement("div");
  card.className = "file-card";
  card.dataset.attId = att.id;

  const icon = document.createElement("div");
  icon.className = "file-icon";
  icon.textContent = att.kind === "image" ? "🖼" : "📎";

  const main = document.createElement("div");
  main.className = "file-main";

  const name = document.createElement("div");
  name.className = "file-name";
  name.textContent = att.filename || "";
  const meta = document.createElement("div");
  meta.className = "file-meta";
  const imageLabel = composerAttachmentT('composer.attachment.image', null, 'Image');
  const typeLabel = composerAttachmentT('composer.attachment.type', {type:att.ext || ''}, `Type: ${att.ext || ''}`);
  const indexedLabel = composerAttachmentT('composer.attachment.indexed', null, 'Indexed');
  meta.textContent = att.kind === "image"
    ? [imageLabel, att.size ? fmtBytes(att.size) : ''].filter(Boolean).join(' · ')
    : [typeLabel, att.size ? fmtBytes(att.size) : '', att.kb_imported ? indexedLabel : ''].filter(Boolean).join(' · ');

  main.appendChild(name);
  main.appendChild(meta);

  const x = document.createElement("button");
  x.className = "file-x";
  x.type = "button";
  x.textContent = "×";
  x.title = composerAttachmentT('composer.attachment.remove', null, 'Remove attachment');
  x.onclick = ()=>{
    pendingFiles = pendingFiles.filter(it => it.id !== att.id);
    card.remove();
    persistComposerAttachmentDraft(getComposerAttachmentOwnerSessionId(), { immediate:true });
    updateComposerActionState();
    refreshComposerLayoutSoon();
  };

  card.appendChild(icon);
  card.appendChild(main);
  card.appendChild(x);

  // 放到预览区（和图片缩略图同一行）
  imagePreviewEl.appendChild(card);
  refreshComposerLayoutSoon();
}

function ensureComposerImageKey(imageItem){
  if(!imageItem || typeof imageItem !== "object") return "";
  if(!imageItem._composerId) imageItem._composerId = "cmpimg_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
  return imageItem._composerId;
}

function getComposerImagePreviewUrl(imageItem){
  const item = imageItem && typeof imageItem === 'object' ? imageItem : {};
  const composerId = ensureComposerImageKey(item);
  const cache = composerId ? getComposerImageLocalCache(composerId) : null;
  const cachedPreview = composerLibraryBrowserImageSource(cache?.previewUrl) || composerLibraryBrowserImageSource(cache?.dataUrl);
  if(cachedPreview) return cachedPreview;
  return composerLibraryBrowserImageSource(item._preview_url)
    || composerLibraryBrowserImageSource(item.preview_url)
    || composerLibraryBrowserImageSource(item.image_url?.url)
    || composerLibraryBrowserImageSource(item.view_url)
    || composerLibraryBrowserImageSource(item.download_url)
    || composerLibraryBrowserImageSource(item.url)
    || composerLibraryBrowserImageSource(item.persisted_url)
    || composerLibraryBrowserImageSource(item.server_url)
    || composerLibraryBrowserImageSource(item._source_url)
    || composerLibraryBrowserImageSource(item.model_storage_ref)
    || composerLibraryBrowserImageSource(item.storage_ref)
    || '';
}

function findComposerImageByKey(composerId){
  const key = String(composerId || '').trim();
  if(!key) return null;
  return pastedImages.find(it => ensureComposerImageKey(it) === key) || null;
}

function getComposerImageThumbNodes(imageItemOrKey){
  const key = typeof imageItemOrKey === "string"
    ? String(imageItemOrKey || '').trim()
    : ensureComposerImageKey(imageItemOrKey);
  if(!key) return {};
  const wrap = imagePreviewEl?.querySelector(`.thumb[data-composer-id="${key}"]`);
  if(!wrap) return {};
  const progressWrap = wrap.querySelector('.thumb-progress');
  const ringEl = progressWrap?.querySelector('.upload-progress-ring') || null;
  const statusEl = wrap.querySelector('.thumb-status');
  const statusTextEl = statusEl?.querySelector('span:last-child') || statusEl?.querySelector('span') || null;
  return { key, wrap, progressWrap, ringEl, statusEl, statusTextEl };
}

function ensureComposerImageThumbOverlay(imageItemOrKey){
  const refs = getComposerImageThumbNodes(imageItemOrKey);
  const wrap = refs?.wrap;
  if(!wrap) return refs || {};
  let progressWrap = refs.progressWrap;
  let ringEl = refs.ringEl;
  let statusEl = refs.statusEl;
  let statusTextEl = refs.statusTextEl;
  if(!progressWrap){
    progressWrap = document.createElement('div');
    progressWrap.className = 'thumb-progress';
    ringEl = createProgressRing('thumb');
    progressWrap.appendChild(ringEl);
    wrap.appendChild(progressWrap);
  }
  if(!statusEl){
    statusEl = document.createElement('div');
    statusEl.className = 'thumb-status';
    statusTextEl = document.createElement('span');
    statusEl.appendChild(statusTextEl);
    wrap.appendChild(statusEl);
  }else if(!statusTextEl){
    statusTextEl = document.createElement('span');
    statusEl.appendChild(statusTextEl);
  }
  return { ...(refs || {}), wrap, progressWrap, ringEl, statusEl, statusTextEl };
}

function patchComposerImageLocalState(composerId, patch){
  const key = String(composerId || '').trim();
  if(!key || !patch || typeof patch !== 'object') return;
  const item = findComposerImageByKey(key);
  if(!item) return;
  Object.assign(item, JSON.parse(JSON.stringify(patch)));
  syncComposerImageThumbUi(item);
  updateComposerActionState();
}

function syncComposerImageThumbUi(imageItem){
  const key = ensureComposerImageKey(imageItem);
  if(!key) return;
  const refs = ensureComposerImageThumbOverlay(key);
  const wrap = refs?.wrap;
  if(!wrap) return;
  const img = wrap.querySelector('img');
  const previewUrl = getComposerImagePreviewUrl(imageItem);
  if(img && previewUrl){
    img.dataset.previewSrc = previewUrl;
    if(img.src !== previewUrl) img.src = previewUrl;
    attachPreviewableImage(img, previewUrl);
  }

  const hasError = !!String(imageItem?._upload_error || '').trim();
  const pending = !!imageItem?._upload_pending || !!imageItem?._ocr_pending;
  const phase = String(imageItem?._upload_phase || '').trim().toLowerCase();
  const progressRaw = Number(imageItem?._upload_progress);
  const progress = Number.isFinite(progressRaw) ? Math.max(0, Math.min(100, progressRaw)) : 0;

  wrap.classList.toggle('pending-upload', pending);
  wrap.classList.toggle('thumb-error', hasError);

  if(refs.progressWrap) refs.progressWrap.classList.remove('done');
  refs.ringEl?.classList.remove('ready', 'error', 'indeterminate');

  if(hasError){
    setRingProgress(refs.ringEl, 100, false);
    refs.ringEl?.classList.add('error');
    if(refs.progressWrap) refs.progressWrap.classList.add('done');
    if(refs.statusEl) refs.statusEl.classList.remove('hidden');
    if(refs.statusTextEl) refs.statusTextEl.textContent = String(imageItem?._upload_error || composerAttachmentT('composer.attachment.upload_failed', null, 'Upload failed'));
    return;
  }

  if(pending){
    if(phase === 'parsing' || phase === 'processing'){
      setRingProgress(refs.ringEl, 100, true);
      if(refs.statusEl) refs.statusEl.classList.add('hidden');
      if(refs.statusTextEl) refs.statusTextEl.textContent = '';
      return;
    }
    if(progress > 0 && progress < 100){
      setRingProgress(refs.ringEl, progress, false);
      if(refs.statusEl) refs.statusEl.classList.add('hidden');
      if(refs.statusTextEl) refs.statusTextEl.textContent = '';
      return;
    }
    setRingProgress(refs.ringEl, 18, true);
    if(refs.statusEl) refs.statusEl.classList.add('hidden');
    if(refs.statusTextEl) refs.statusTextEl.textContent = '';
    return;
  }

  setRingProgress(refs.ringEl, 100, false);
  refs.ringEl?.classList.add('ready');
  if(refs.progressWrap) refs.progressWrap.classList.add('done');
  if(refs.statusEl) refs.statusEl.classList.add('hidden');
  if(refs.statusTextEl) refs.statusTextEl.textContent = '';
}

async function patchSessionImageByComposerId(sessionId, composerId, patch){
  const sid = String(sessionId || '').trim();
  const key = String(composerId || '').trim();
  if(!sid || !key || !patch || typeof patch !== 'object') return;
  try{
    await updateSessionById(sid, s=>{
      const msgs = Array.isArray(s?.messages) ? s.messages : [];
      for(let i = msgs.length - 1; i >= 0; i--){
        const msg = msgs[i];
        if(!msg || !Array.isArray(msg.content)) continue;
        let changed = false;
        for(const part of msg.content){
          if(!part || part.type !== 'image_url') continue;
          if(ensureComposerImageKey(part) !== key) continue;
          Object.assign(part, JSON.parse(JSON.stringify(patch)));
          changed = true;
        }
        if(changed) break;
      }
    }, { skipCompress: true });
  }catch(_){ }
}

async function applyComposerImagePatch(composerId, patch, opts={}){
  const key = String(composerId || '').trim();
  if(!key || !patch || typeof patch !== 'object') return;
  const clonedPatch = JSON.parse(JSON.stringify(patch));
  const composerItem = findComposerImageByKey(key);
  const targetSessionId = String(clonedPatch._sessionId || composerItem?._sessionId || opts.sessionId || '').trim();
  const patchImageUrl = String(clonedPatch?.image_url?.url || '').trim();
  const patchPreviewUrl = String(clonedPatch?._preview_url || '').trim();
  if(patchImageUrl.startsWith('data:image/') || patchPreviewUrl.startsWith('data:image/')){
    setComposerImageLocalCache(key, {
      dataUrl: patchImageUrl.startsWith('data:image/') ? patchImageUrl : patchPreviewUrl,
      previewUrl: patchPreviewUrl || patchImageUrl,
    });
  }else if(patchPreviewUrl.startsWith('blob:')){
    setComposerImageLocalCache(key, { previewUrl: patchPreviewUrl });
  }
  if(composerItem){
    Object.assign(composerItem, clonedPatch);
    syncComposerImageThumbUi(composerItem);
  }
  if(targetSessionId){
    await patchSessionImageByComposerId(targetSessionId, key, clonedPatch);
    try{ persistComposerAttachmentDraft(targetSessionId); }catch(_){ }
  }else{
    try{ persistComposerAttachmentDraft(getComposerAttachmentOwnerSessionId()); }catch(_){ }
  }
  updateComposerActionState();
}

function addImageThumb(imageItem){
  const wrap = document.createElement("div");
  wrap.className = "thumb";
  const removeKey = ensureComposerImageKey(imageItem);
  wrap.dataset.composerId = removeKey;

  const img = document.createElement("img");
  img.src = getComposerImagePreviewUrl(imageItem);

  const progressWrap = document.createElement("div");
  progressWrap.className = "thumb-progress";
  const ring = createProgressRing("thumb");
  progressWrap.appendChild(ring);

  const status = document.createElement("div");
  status.className = "thumb-status";
  const statusText = document.createElement("span");
  statusText.textContent = "";
  status.appendChild(statusText);
  status.classList.add("hidden");

  const x = document.createElement("button");
  x.className = "x";
  x.type = "button";
  x.textContent = "×";
  x.onclick = ()=>{
    const removed = pastedImages.find(it => ensureComposerImageKey(it) === removeKey);
    cancelComposerImageUpload(removeKey, { silent:true });
    pastedImages = pastedImages.filter(it => ensureComposerImageKey(it) !== removeKey);
    clearComposerImageLocalCache(removeKey, { revokePreview:true });
    revokeComposerImagePreviewUrl(String(removed?._preview_url || '').trim());
    wrap.remove();
    persistComposerAttachmentDraft(getComposerAttachmentOwnerSessionId(), { immediate:true });
    updateComposerActionState();
    updateComposerPlaceholder();
    refreshComposerLayoutSoon();
  };

  wrap.appendChild(img);
  if(img.src) attachPreviewableImage(img, img.src);
  wrap.appendChild(progressWrap);
  wrap.appendChild(status);
  wrap.appendChild(x);
  imagePreviewEl.appendChild(wrap);
  refreshComposerLayoutSoon();
  syncComposerImageThumbUi(imageItem);
}

function cancelComposerImageUpload(composerId, opts={}){
  const key = String(composerId || "").trim();
  if(!key) return false;
  const task = getComposerUploadTask(key);
  if(task) task.abort("upload_canceled");
  deleteComposerUploadTask(key);
  if(!opts?.silent){
    try{ setStatus(composerAttachmentT('composer.attachment.upload_canceled', null, 'Upload canceled')); }catch(_){ }
  }
  updateComposerActionState();
  return !!task;
}


function getLocalFileExt(file){
  const name = String(file?.name || '');
  const idx = name.lastIndexOf('.');
  return idx >= 0 ? name.slice(idx).toLowerCase() : '';
}

function isAppleHighEfficiencyImageFile(file){
  const ext = getLocalFileExt(file);
  const type = String(file?.type || '').split(';', 1)[0].trim().toLowerCase();
  return ext === '.heic' || ext === '.heif' || type === 'image/heic' || type === 'image/heif' || type === 'image/heic-sequence' || type === 'image/heif-sequence';
}

function isLikelyLocalImageFile(file){
  const type = String(file?.type || '').split(';', 1)[0].trim().toLowerCase();
  if(type.startsWith('image/')) return true;
  const ext = getLocalFileExt(file);
  return ['.png','.jpg','.jpeg','.jpe','.jfif','.webp','.gif','.bmp','.tif','.tiff','.ico','.heic','.heif'].includes(ext);
}

function canvasToBlobByMime(canvas, mime='image/jpeg', quality=0.92){
  return new Promise((resolve)=>{
    try{
      canvas.toBlob(blob=>resolve(blob || null), mime, quality);
    }catch(_){
      resolve(null);
    }
  });
}

function canvasToJpegBlob(canvas, quality=0.92){
  return canvasToBlobByMime(canvas, 'image/jpeg', quality);
}

function currentComposerAttachmentCounts(){
  return {
    images: Array.isArray(pastedImages) ? pastedImages.length : 0,
    files: Array.isArray(pendingFiles) ? pendingFiles.length : 0,
  };
}

function composerAttachmentLimitMessage(kind='attachment'){
  const c = currentComposerAttachmentCounts();
  if(kind === 'image' && c.images >= COMPOSER_MAX_IMAGES) return composerAttachmentT('composer.attachment.limit_images', {count:COMPOSER_MAX_IMAGES}, `You can upload up to ${COMPOSER_MAX_IMAGES} images`);
  if(kind === 'file' && c.files >= COMPOSER_MAX_FILES) return composerAttachmentT('composer.attachment.limit_files', {count:COMPOSER_MAX_FILES}, `You can add up to ${COMPOSER_MAX_FILES} files`);
  if((c.images + c.files) >= COMPOSER_MAX_ATTACHMENTS) return composerAttachmentT('composer.attachment.limit_total', {count:COMPOSER_MAX_ATTACHMENTS}, `You can add up to ${COMPOSER_MAX_ATTACHMENTS} images and files combined`);
  return '';
}

function assertComposerCanAcceptAttachment(kind='attachment'){
  const message = composerAttachmentLimitMessage(kind);
  if(message) throw new Error(message);
  return true;
}

function isGifImageFile(file){
  const ext = getLocalFileExt(file);
  const type = String(file?.type || '').split(';', 1)[0].trim().toLowerCase();
  return ext === '.gif' || type === 'image/gif';
}

function imageFileLooksLikeTextOrScreenshot(file){
  const name = String(file?.name || '').toLowerCase();
  const type = String(file?.type || '').split(';', 1)[0].trim().toLowerCase();
  const ext = getLocalFileExt(file);
  if(type === 'image/png' || ext === '.png') return true;
  return /(screenshot|screen.?shot|capture|code|ui|doc|document|text|截图|截屏|屏幕|代码|文档|文字|界面)/iu.test(name);
}

function imageCompressionOutputMime(file, textLike=false){
  const type = String(file?.type || '').split(';', 1)[0].trim().toLowerCase();
  const ext = getLocalFileExt(file);
  if(textLike && (type === 'image/png' || ext === '.png')) return 'image/png';
  if(type === 'image/webp') return 'image/webp';
  return 'image/jpeg';
}

function imageCompressionFilename(file, mime){
  const original = String(file?.name || 'image').trim() || 'image';
  const base = original.replace(/\.[^.]*$/, '') || 'image';
  if(mime === 'image/webp') return `${base}.webp`;
  if(mime === 'image/png') return `${base}.png`;
  return `${base}.jpg`;
}

async function loadImageForCanvas(file){
  if(typeof createImageBitmap === 'function'){
    try{
      const bitmap = await createImageBitmap(file);
      if(bitmap) return { image:bitmap, width:bitmap.width || 1, height:bitmap.height || 1, close:()=>{ try{ bitmap.close?.(); }catch(_){ } } };
    }catch(_){ }
  }
  const objectUrl = URL.createObjectURL(file);
  try{
    const img = await new Promise((resolve, reject)=>{
      const el = new Image();
      el.onload = ()=> resolve(el);
      el.onerror = ()=> reject(new Error(composerAttachmentT('composer.attachment.image_read_failed', null, 'Unable to read image')));
      el.src = objectUrl;
    });
    return { image:img, width:img.naturalWidth || img.width || 1, height:img.naturalHeight || img.height || 1, close:()=>{} };
  }finally{
    try{ URL.revokeObjectURL(objectUrl); }catch(_){ }
  }
}

async function compressImageForVisionUpload(file){
  if(!file || !isLikelyLocalImageFile(file)) return { file, compressed:false, dataUrl:'', originalSize:Number(file?.size || 0) || 0, finalSize:Number(file?.size || 0) || 0 };
  const originalSize = Number(file?.size || 0) || 0;
  if(isGifImageFile(file)){
    if(originalSize > IMAGE_UPLOAD_MAX_BYTES) throw new Error(composerAttachmentT('composer.attachment.gif_too_large', {size:fmtBytes(IMAGE_UPLOAD_MAX_BYTES)}, `GIF is too large; maximum size is ${fmtBytes(IMAGE_UPLOAD_MAX_BYTES)}`));
    return { file, compressed:false, dataUrl:'', originalSize, finalSize:originalSize };
  }
  if(originalSize > 0 && originalSize <= IMAGE_COMPRESS_TRIGGER_BYTES){
    return { file, compressed:false, dataUrl:'', originalSize, finalSize:originalSize };
  }
  const textLike = imageFileLooksLikeTextOrScreenshot(file);
  const maxEdge = textLike ? IMAGE_COMPRESS_MAX_EDGE_TEXT : IMAGE_COMPRESS_MAX_EDGE_PHOTO;
  const quality = textLike ? IMAGE_COMPRESS_QUALITY_TEXT : IMAGE_COMPRESS_QUALITY_PHOTO;
  const loaded = await loadImageForCanvas(file);
  try{
    const srcW = Math.max(1, Number(loaded.width || 1) || 1);
    const srcH = Math.max(1, Number(loaded.height || 1) || 1);
    const ratio = Math.min(1, maxEdge / Math.max(srcW, srcH));
    const dstW = Math.max(1, Math.round(srcW * ratio));
    const dstH = Math.max(1, Math.round(srcH * ratio));
    if(ratio >= 1 && originalSize <= IMAGE_UPLOAD_MAX_BYTES){
      return { file, compressed:false, dataUrl:'', originalSize, finalSize:originalSize };
    }
    const canvas = document.createElement('canvas');
    canvas.width = dstW;
    canvas.height = dstH;
    const ctx = canvas.getContext('2d', { alpha:true });
    if(!ctx) throw new Error(composerAttachmentT('composer.attachment.image_compress_failed', null, 'Unable to compress image'));
    ctx.drawImage(loaded.image, 0, 0, dstW, dstH);
    const mime = imageCompressionOutputMime(file, textLike);
    let blob = await canvasToBlobByMime(canvas, mime, quality);
    if((!blob || blob.size <= 0) && mime !== 'image/jpeg'){
      blob = await canvasToJpegBlob(canvas, quality);
    }
    if(!blob || blob.size <= 0) throw new Error(composerAttachmentT('composer.attachment.image_compress_failed', null, 'Unable to compress image'));
    if(blob.size > IMAGE_UPLOAD_MAX_BYTES){
      const webpBlob = await canvasToBlobByMime(canvas, 'image/webp', Math.max(0.84, Math.min(quality, 0.9)));
      if(webpBlob && webpBlob.size > 0 && webpBlob.size < blob.size) blob = webpBlob;
    }
    if(blob.size > IMAGE_UPLOAD_MAX_BYTES){
      const fallbackBlob = await canvasToJpegBlob(canvas, Math.max(0.82, Math.min(quality, 0.88)));
      if(fallbackBlob && fallbackBlob.size > 0 && fallbackBlob.size < blob.size) blob = fallbackBlob;
    }
    if(blob.size > IMAGE_UPLOAD_MAX_BYTES){
      throw new Error(composerAttachmentT('composer.attachment.image_too_large_after_compress', {size:fmtBytes(IMAGE_UPLOAD_MAX_BYTES)}, `Image is still larger than ${fmtBytes(IMAGE_UPLOAD_MAX_BYTES)} after compression`));
    }
    if(blob.size >= originalSize && originalSize <= IMAGE_UPLOAD_MAX_BYTES){
      return { file, compressed:false, dataUrl:'', originalSize, finalSize:originalSize };
    }
    const outMime = blob.type || mime || 'image/jpeg';
    const outFile = new File([blob], imageCompressionFilename(file, outMime), { type:outMime, lastModified:file?.lastModified || Date.now() });
    let dataUrl = '';
    try{ dataUrl = canvas.toDataURL(outMime, quality); }catch(_){ dataUrl = ''; }
    return { file:outFile, compressed:true, dataUrl, originalSize, finalSize:blob.size };
  }finally{
    try{ loaded.close?.(); }catch(_){ }
  }
}

async function prepareImageFileForComposerUpload(file){
  const normalized = await convertAppleImageFileForUpload(file);
  const normalizedFile = normalized?.file || file;
  const compressed = await compressImageForVisionUpload(normalizedFile);
  return {
    file: compressed?.file || normalizedFile,
    dataUrl: compressed?.dataUrl || normalized?.dataUrl || '',
    converted: !!normalized?.converted,
    compressed: !!compressed?.compressed,
    originalSize: Number(compressed?.originalSize || file?.size || 0) || 0,
    finalSize: Number(compressed?.finalSize || compressed?.file?.size || normalizedFile?.size || 0) || 0,
  };
}

async function convertAppleImageFileForUpload(file){
  if(!isAppleHighEfficiencyImageFile(file)) return { file, converted:false, dataUrl:'' };
  let bitmap = null;
  try{
    if(typeof createImageBitmap === 'function'){
      bitmap = await createImageBitmap(file);
    }
  }catch(_){
    bitmap = null;
  }
  if(bitmap){
    try{
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width || 1;
      canvas.height = bitmap.height || 1;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(bitmap, 0, 0);
      try{ bitmap.close?.(); }catch(_){ }
      const blob = await canvasToJpegBlob(canvas, 0.92);
      if(blob && blob.size > 0){
        const base = String(file?.name || 'image').replace(/\.[^.]*$/, '') || 'image';
        const jpegFile = new File([blob], `${base}.jpg`, { type:'image/jpeg', lastModified:file?.lastModified || Date.now() });
        let dataUrl = '';
        try{ dataUrl = canvas.toDataURL('image/jpeg', 0.92); }catch(_){ dataUrl = ''; }
        return { file:jpegFile, converted:true, dataUrl };
      }
    }catch(_){ }
  }
  const objectUrl = URL.createObjectURL(file);
  try{
    const img = await new Promise((resolve, reject)=>{
      const el = new Image();
      el.onload = ()=> resolve(el);
      el.onerror = ()=> reject(new Error('heif_preview_decode_failed'));
      el.src = objectUrl;
    });
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth || img.width || 1;
    canvas.height = img.naturalHeight || img.height || 1;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const blob = await canvasToJpegBlob(canvas, 0.92);
    if(blob && blob.size > 0){
      const base = String(file?.name || 'image').replace(/\.[^.]*$/, '') || 'image';
      const jpegFile = new File([blob], `${base}.jpg`, { type:'image/jpeg', lastModified:file?.lastModified || Date.now() });
      let dataUrl = '';
      try{ dataUrl = canvas.toDataURL('image/jpeg', 0.92); }catch(_){ dataUrl = ''; }
      return { file:jpegFile, converted:true, dataUrl };
    }
  }catch(_){
  }finally{
    try{ URL.revokeObjectURL(objectUrl); }catch(_){ }
  }
  return { file, converted:false, dataUrl:'' };
}

function fileToDataUrl(file){
  return new Promise((resolve, reject)=>{
    const reader = new FileReader();
    reader.onload = ()=> resolve(String(reader.result || ''));
    reader.onerror = ()=> reject(new Error('图片读取失败'));
    reader.readAsDataURL(file);
  });
}

function waitForComposerUploadReconcile(ms){
  return new Promise(resolve=>setTimeout(resolve, Math.max(0, Number(ms || 0) || 0)));
}

function composerUploadLibraryMatch(item, meta={}){
  const row = item && typeof item === 'object' ? item : {};
  const expectedName = String(meta.filename || '').trim().toLowerCase();
  const actualName = String(row.filename || row.saved_filename || '').trim().toLowerCase();
  if(!expectedName || actualName !== expectedName) return false;
  const expectedSize = Number(meta.size || 0) || 0;
  const actualSize = Number(row.size || 0) || 0;
  if(expectedSize > 0 && actualSize > 0 && expectedSize !== actualSize) return false;
  const updatedMs = Math.round((Number(row.updated_ts || 0) || 0) * 1000);
  const startedAtMs = Number(meta.startedAtMs || 0) || 0;
  if(startedAtMs > 0 && updatedMs > 0 && updatedMs < startedAtMs - 10000) return false;
  if(startedAtMs <= 0 && updatedMs > 0 && updatedMs < Date.now() - 30 * 60 * 1000) return false;
  return String(row.category || '').trim().toLowerCase() === 'image';
}

async function completePendingComposerImageFromLibrary(key, current, matched, task=null){
  const fileId = String(matched?.file_id || '').trim();
  const storageRef = String(matched?.storage_ref || matched?.model_storage_ref || '').trim();
  const modelStorageRef = String(matched?.model_storage_ref || matched?.storage_ref || '').trim();
  const viewUrl = String(matched?.preview_url || matched?.view_url || matched?.url || matched?.download_url || '').trim();
  const downloadUrl = String(matched?.download_url || matched?.url || matched?.view_url || '').trim();
  if(!fileId || (!storageRef && !modelStorageRef && !viewUrl)) return false;
  if(task) task.libraryReconciled = true;
  await applyComposerImagePatch(key, ensureComposerImageAttachmentMeta({
    attachment_id: String(current?.attachment_id || fileId).trim(),
    image_id: String(current?.image_id || current?.attachment_id || fileId).trim(),
    file_library_id:fileId,
    library_file_id:fileId,
    file_registry:{
      file_id:fileId,
      filename:String(matched?.filename || current?.filename || '').trim(),
      saved_filename:String(matched?.saved_filename || '').trim(),
      storage_ref:storageRef,
      view_url:viewUrl,
      download_url:downloadUrl,
      size:Number(matched?.size || current?._upload_match_size || 0) || 0,
    },
    storage_ref:storageRef || modelStorageRef,
    model_storage_ref:modelStorageRef || storageRef,
    image_url:{ url:modelStorageRef || storageRef || viewUrl },
    persisted_url:viewUrl,
    server_url:viewUrl,
    preview_url:viewUrl,
    view_url:viewUrl,
    download_url:downloadUrl,
    _preview_url:viewUrl || getComposerImagePreviewUrl(current),
    filename:String(matched?.filename || current?.filename || '').trim(),
    source_role:'user',
    source_type:'upload',
    operation:'upload',
    _upload_pending:false,
    _ocr_pending:false,
    _upload_error:'',
    _upload_phase:'done',
    _upload_progress:100,
    _sessionId:String(current?._sessionId || '').trim(),
  }), { sessionId:String(current?._sessionId || '').trim() });
  return true;
}

async function reconcilePendingComposerImageFromLibrary(composerId, uploadFile, startedAtMs, task=null){
  const key = String(composerId || '').trim();
  const filename = String(uploadFile?.name || '').trim();
  const size = Number(uploadFile?.size || 0) || 0;
  if(!key || !filename) return false;

  for(let attempt = 0; attempt < 12; attempt++){
    await waitForComposerUploadReconcile(attempt === 0 ? 1600 : 1200);
    if(task?.aborted) return false;
    const current = findComposerImageByKey(key);
    if(!current || (!current._upload_pending && !current._ocr_pending)) return false;
    try{
      const params = new URLSearchParams({ offset:'0', limit:'50', type:'image', sort:'updated_desc' });
      const response = await fetch('/api3/file-library/state?' + params.toString(), { cache:'no-store' });
      if(!response.ok) continue;
      const payload = await response.json();
      const files = Array.isArray(payload?.files) ? payload.files : [];
      const matched = files
        .filter(item=>composerUploadLibraryMatch(item, { filename, size, startedAtMs }))
        .sort((a,b)=>(Number(b?.updated_ts || 0) || 0) - (Number(a?.updated_ts || 0) || 0))[0];
      if(!matched) continue;

      if(!(await completePendingComposerImageFromLibrary(key, current, matched, task))) continue;
      try{ setStatus(composerAttachmentT('composer.attachment.image_uploaded_pending', null, 'Image uploaded · ready to send')); }catch(_){ }
      return true;
    }catch(_){ }
  }
  return false;
}

async function reconcileRestoredPendingComposerImagesFromLibrary(images=[]){
  const pending = (Array.isArray(images) ? images : []).filter(item=>item && (item._upload_pending || item._ocr_pending));
  if(!pending.length) return 0;
  try{
    const params = new URLSearchParams({ offset:'0', limit:'100', type:'image', sort:'updated_desc' });
    const response = await fetch('/api3/file-library/state?' + params.toString(), { cache:'no-store' });
    if(!response.ok) return 0;
    const payload = await response.json();
    const files = Array.isArray(payload?.files) ? payload.files : [];
    let completed = 0;
    for(const item of pending){
      const key = ensureComposerImageKey(item);
      const filename = String(item._upload_match_filename || item.filename || '').trim();
      const size = Number(item._upload_match_size || item.file_registry?.size || 0) || 0;
      const startedAtMs = Number(item._upload_started_at_ms || 0) || 0;
      const matched = files
        .filter(row=>composerUploadLibraryMatch(row, { filename, size, startedAtMs }))
        .sort((a,b)=>(Number(b?.updated_ts || 0) || 0) - (Number(a?.updated_ts || 0) || 0))[0];
      if(!matched) continue;
      const current = findComposerImageByKey(key) || item;
      if(await completePendingComposerImageFromLibrary(key, current, matched)) completed++;
    }
    if(completed){
      try{ setStatus(completed > 1
        ? composerAttachmentT('composer.attachment.images_uploaded_pending', {count:completed}, `${completed} images uploaded · ready to send`)
        : composerAttachmentT('composer.attachment.image_uploaded_pending', null, 'Image uploaded · ready to send')); }catch(_){ }
    }
    return completed;
  }catch(_){
    return 0;
  }
}

async function startLocalImageResolution(file, imageItem, uploadTask=null){
  const composerId = ensureComposerImageKey(imageItem);
  const sessionId = String(imageItem?._sessionId || store.activeId || '').trim();
  const task = uploadTask || getComposerUploadTask(composerId) || createComposerUploadTask(composerId, "image");
  patchComposerImageLocalState(composerId, {
    _upload_pending: true,
    _ocr_pending: true,
    _upload_error: '',
    _upload_phase: 'uploading',
    _upload_progress: 0,
  });
  let uploadFile = file;
  try{
    task?.throwIfAborted?.();
    const prepared = await prepareImageFileForComposerUpload(file);
    task?.throwIfAborted?.();
    uploadFile = prepared?.file || file;
    const localDataUrl = prepared?.dataUrl || await fileToDataUrl(uploadFile);
    task?.throwIfAborted?.();
    if(prepared?.compressed){
      setStatus(composerAttachmentT('composer.attachment.image_compressed_upload', {
        original:fmtBytes(prepared.originalSize),
        final:fmtBytes(prepared.finalSize),
      }, `Large image compressed for upload (${fmtBytes(prepared.originalSize)} → ${fmtBytes(prepared.finalSize)})`));
    }
    if(localDataUrl){
      setComposerImageLocalCache(composerId, {
        file: uploadFile,
        dataUrl: localDataUrl,
        previewUrl: localDataUrl,
      });
      await applyComposerImagePatch(composerId, {
        image_url: { url: localDataUrl },
        _preview_url: localDataUrl,
        filename: uploadFile?.name || imageItem?.filename || file?.name || '',
        _sessionId: sessionId,
      }, { sessionId });
    }
  }catch(err){
    if(isUploadCanceledError(err) || task?.aborted){
      deleteComposerUploadTask(composerId);
      return;
    }
    setComposerImageLocalCache(composerId, { file: uploadFile || file, dataUrl:'', previewUrl:String(imageItem?._preview_url || '').trim() });
    await applyComposerImagePatch(composerId, {
      _upload_pending: false,
      _ocr_pending: false,
      _upload_error: String(err?.message || composerAttachmentT('composer.attachment.image_read_failed', null, 'Unable to read image')),
      _sessionId: sessionId,
    }, { sessionId });
    reportAppError(composerAttachmentT('composer.attachment.image_preprocess_failed', {
      name:file?.name || composerAttachmentT('composer.attachment.unnamed_image', null, 'Untitled image'),
      error:err.message || err,
    }, `Unable to prepare ${file?.name || 'untitled image'}: ${err.message || err}`));
    deleteComposerUploadTask(composerId);
    return;
  }

  try{
    const uploadStartedAtMs = Date.now();
    patchComposerImageLocalState(composerId, {
      _upload_match_filename:String(uploadFile?.name || file?.name || '').trim(),
      _upload_match_size:Number(uploadFile?.size || file?.size || 0) || 0,
      _upload_started_at_ms:uploadStartedAtMs,
    });
    try{ persistComposerAttachmentDraft(sessionId); }catch(_){ }
    reconcilePendingComposerImageFromLibrary(composerId, uploadFile, uploadStartedAtMs, task).catch(()=>{});
    const data = await uploadOneFileRequest(uploadFile, null, {
      task,
      onProgress(percent, phase){
        if(task?.libraryReconciled) return;
        patchComposerImageLocalState(composerId, {
          _upload_pending: true,
          _ocr_pending: true,
          _upload_error: '',
          _upload_phase: String(phase || 'uploading'),
          _upload_progress: Number.isFinite(Number(percent)) ? Number(percent) : 0,
        });
      }
    });
    task?.throwIfAborted?.();
    if(!data || data.kind !== 'image') throw new Error(data?.error || composerAttachmentT('composer.attachment.image_upload_failed', null, 'Image upload failed'));
    const persistedUrl = String(data?.preview_url || data?.view_url || data?.url || data?.download_url || '').trim();
    const dataUrl = String(data?.data_url || '').trim();
    const previewUrl = dataUrl || persistedUrl || getComposerImagePreviewUrl(imageItem);
    const imageUrl = persistedUrl || dataUrl || String(imageItem?.image_url?.url || '').trim();
    await applyComposerImagePatch(composerId, ensureComposerImageAttachmentMeta({
      attachment_id: String(data?.attachment_id || imageItem?.attachment_id || '').trim(),
      image_id: String(data?.image_id || data?.attachment_id || imageItem?.image_id || imageItem?.attachment_id || '').trim(),
      storage_ref: String(data?.storage_ref || '').trim(),
      model_storage_ref: String(data?.model_storage_ref || data?.storage_ref || '').trim(),
      file_library_id: String(data?.file_library_id || data?.library_file_id || data?.file_registry?.file_id || '').trim(),
      library_file_id: String(data?.library_file_id || data?.file_library_id || data?.file_registry?.file_id || '').trim(),
      file_registry: data?.file_registry || null,
      source_role: String(data?.source_role || 'user').trim() || 'user',
      source_type: String(data?.source_type || 'upload').trim() || 'upload',
      operation: String(data?.operation || 'upload').trim() || 'upload',
      image_url: { url: imageUrl },
      persisted_url: persistedUrl,
      server_url: persistedUrl,
      view_url: String(data?.view_url || persistedUrl || '').trim(),
      download_url: String(data?.download_url || data?.url || persistedUrl || '').trim(),
      _preview_url: previewUrl,
      filename: data.filename || imageItem?.filename || file?.name || '',
      _ocr_text: String(data?.text || '').trim(),
      _upload_pending: false,
      _ocr_pending: false,
      _upload_error: '',
      _upload_phase: 'done',
      _upload_progress: 100,
      _sessionId: sessionId,
    }), { sessionId });
  }catch(err){
    if(isUploadCanceledError(err) || task?.aborted) return;
    if(task?.libraryReconciled) return;
    await applyComposerImagePatch(composerId, {
      _upload_pending: false,
      _ocr_pending: false,
      _upload_error: String(err?.message || composerAttachmentT('composer.attachment.image_upload_failed', null, 'Image upload failed')),
      _upload_phase: 'error',
      _upload_progress: 100,
      _sessionId: sessionId,
    }, { sessionId });
    console.warn('本地图片后台处理失败', file?.name, err);
  }finally{
    deleteComposerUploadTask(composerId);
  }
}

async function addImageFileToPreview(file){
  assertComposerCanAcceptAttachment('image');
  const sessionId = getComposerAttachmentOwnerSessionId();
  const composerId = "cmpimg_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
  const uploadTask = createComposerUploadTask(composerId, "image");
  const localPreviewUrl = URL.createObjectURL(file);
  setComposerImageLocalCache(composerId, { file, dataUrl:'', previewUrl:localPreviewUrl });
  const imgItem = ensureComposerImageAttachmentMeta({
    type:'image_url',
    image_url:{ url:'' },
    persisted_url:'',
    server_url:'',
    _preview_url:localPreviewUrl,
    filename:file?.name || '',
    _composerId: composerId,
    _sessionId: sessionId,
    _upload_pending: true,
    _ocr_pending: true,
    _ocr_text: '',
    _upload_error: '',
    _upload_phase: 'uploading',
    _upload_progress: 0
  }, { prefix:'upl' });
  pastedImages.push(imgItem);
  addImageThumb(imgItem);
  persistComposerAttachmentDraft(sessionId);
  updateComposerActionState();
  updateComposerPlaceholder();
  setStatus(composerAttachmentT('composer.attachment.image_added_processing', null, 'Image added · processing before send'));
  startLocalImageResolution(file, imgItem, uploadTask);
}

function extractImageUrlsFromHtml(html){
  const out = [];
  try{
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
    doc.querySelectorAll('img[src]').forEach(img=>{
      const src = String(img.getAttribute('src') || '').trim();
      if(/^https?:\/\//i.test(src)) out.push(src);
    });
  }catch(_){ }
  return out;
}

function clipboardHtmlContainsImages(html){
  try{
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
    return !!doc.querySelector('img[src]');
  }catch(_){
    return false;
  }
}

function isLikelyDirectImageUrl(url){
  const s = String(url || '').trim();
  if(!/^https?:\/\//i.test(s)) return false;
  try{
    const u = new URL(s);
    const path = String(u.pathname || '').toLowerCase();
    if(/\.(png|jpe?g|webp|gif|bmp|svg|avif|heic|heif)$/.test(path)) return true;
    const format = String(u.searchParams.get('format') || '').toLowerCase();
    if(['png','jpg','jpeg','webp','gif','bmp','svg','avif','heic','heif'].includes(format)) return true;
  }catch(_){ }
  return false;
}

function extractImageUrlsFromText(text){
  const out = [];
  const s = String(text || '');
  const re = /https?:\/\/[^\s<>"']+/ig;
  for(const m of s.matchAll(re)){
    const url = String(m[0] || '').trim().replace(/[),.;!?]+$/,'');
    if(url) out.push(url);
  }
  return out;
}

function pickRemoteImageUrlsFromClipboardLikeData({ html='', text='', uriList='' } = {}){
  const urls = [];
  const seen = new Set();
  const push = (u)=>{
    const s = String(u || '').trim();
    if(!/^https?:\/\//i.test(s)) return;
    if(seen.has(s)) return;
    seen.add(s);
    urls.push(s);
  };
  const htmlHasImages = clipboardHtmlContainsImages(html);
  const uriCandidates = String(uriList || '').split(/\r?\n/).map(v=>v.trim()).filter(v=>v && !v.startsWith('#'));
  if(htmlHasImages){
    extractImageUrlsFromHtml(html).forEach(push);
    extractImageUrlsFromText(text).filter(isLikelyDirectImageUrl).forEach(push);
  }
  uriCandidates.filter(isLikelyDirectImageUrl).forEach(push);
  return urls.slice(0, 6);
}

async function importRemoteImageUrl(url){
  assertComposerCanAcceptAttachment('image');
  const rawUrl = String(url || '').trim();
  if(!rawUrl) throw new Error(composerAttachmentT('composer.attachment.image_url_empty', null, 'Image URL is empty'));
  const sessionId = getComposerAttachmentOwnerSessionId();
  const composerId = "cmpimg_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
  const imgItem = ensureComposerImageAttachmentMeta({
    type:'image_url',
    image_url:{ url: rawUrl },
    persisted_url:'',
    server_url:'',
    _preview_url: rawUrl,
    _source_url: rawUrl,
    filename:'',
    _composerId: composerId,
    _sessionId: sessionId,
    _upload_pending: true,
    _ocr_pending: true,
    _ocr_text: '',
    _upload_error: '',
    _upload_phase: 'processing',
    _upload_progress: 0
  }, { prefix:'imp' });
  pastedImages.push(imgItem);
  addImageThumb(imgItem);
  persistComposerAttachmentDraft(sessionId);
  updateComposerActionState();

  fetch('/api3/import-image-url', {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body: JSON.stringify({ url: rawUrl })
  }).then(async resp => {
    let data = {};
    try{ data = await resp.json(); }catch(_){ }
    if(!resp.ok) throw new Error(data?.error || ('HTTP ' + resp.status));
    const persistedUrl = String(data?.preview_url || data?.view_url || data?.url || data?.download_url || '').trim();
    const dataUrl = String(data?.data_url || '').trim();
    const previewUrl = dataUrl || persistedUrl || rawUrl;
    if(!data || data.kind !== 'image' || !previewUrl) throw new Error(composerAttachmentT('composer.attachment.image_url_import_failed', null, 'Unable to import image URL'));
    const imageUrl = persistedUrl || dataUrl || rawUrl;
    await applyComposerImagePatch(composerId, ensureComposerImageAttachmentMeta({
      attachment_id: String(data?.attachment_id || imgItem?.attachment_id || '').trim(),
      image_id: String(data?.image_id || data?.attachment_id || imgItem?.image_id || imgItem?.attachment_id || '').trim(),
      storage_ref: String(data?.storage_ref || '').trim(),
      model_storage_ref: String(data?.model_storage_ref || data?.storage_ref || '').trim(),
      file_library_id: String(data?.file_library_id || data?.library_file_id || data?.file_registry?.file_id || '').trim(),
      library_file_id: String(data?.library_file_id || data?.file_library_id || data?.file_registry?.file_id || '').trim(),
      file_registry: data?.file_registry || null,
      source_role: String(data?.source_role || 'user').trim() || 'user',
      source_type: String(data?.source_type || 'upload').trim() || 'upload',
      operation: String(data?.operation || 'upload').trim() || 'upload',
      image_url:{ url:imageUrl },
      persisted_url:persistedUrl,
      server_url:persistedUrl,
      view_url: String(data?.view_url || persistedUrl || '').trim(),
      download_url: String(data?.download_url || data?.url || persistedUrl || '').trim(),
      _preview_url:previewUrl,
      filename:data.filename || '',
      _ocr_text: String(data?.text || '').trim(),
      _upload_pending:false,
      _ocr_pending:false,
      _upload_error:'',
      _upload_phase:'done',
      _upload_progress:100,
      _sessionId: sessionId,
    }), { sessionId });
  }).catch(async err => {
    await applyComposerImagePatch(composerId, {
      _upload_pending:false,
      _ocr_pending:false,
      _upload_error:String(err?.message || composerAttachmentT('composer.attachment.image_url_import_failed', null, 'Unable to import image URL')),
      _upload_phase:'error',
      _upload_progress:100,
      _sessionId: sessionId,
    }, { sessionId });
    console.warn('远程图片后台导入失败', rawUrl, err);
  });

  return imgItem;
}

async function importRemoteImageUrls(urls, sourceLabel=composerAttachmentT('composer.attachment.image_url', null, 'Image URL')){
  const uniqueList = Array.from(new Set((urls || []).map(v=>String(v || '').trim()).filter(Boolean)));
  const c = currentComposerAttachmentCounts();
  const available = Math.max(0, Math.min(COMPOSER_MAX_IMAGES - c.images, COMPOSER_MAX_ATTACHMENTS - c.images - c.files));
  if(available <= 0){
    reportAppError(composerAttachmentLimitMessage('image') || composerAttachmentT('composer.attachment.limit_images', {count:COMPOSER_MAX_IMAGES}, `You can upload up to ${COMPOSER_MAX_IMAGES} images`));
    return false;
  }
  const list = uniqueList.slice(0, available);
  if(uniqueList.length > list.length) setStatus(composerAttachmentT('composer.attachment.images_trimmed_to_limit', {count:list.length}, `Only ${list.length} images were added to stay within the limit`));
  if(!list.length) return false;
  let accepted = 0;
  for(const url of list){
    try{
      await importRemoteImageUrl(url);
      accepted += 1;
    }catch(err){
      console.warn(`${sourceLabel}导入失败`, url, err);
    }
  }
  if(accepted > 0){
    setStatus(composerAttachmentT('composer.attachment.images_added_processing', {count:accepted}, `${accepted} images added · processing in the background`));
    updateComposerPlaceholder();
    return true;
  }
  return false;
}

function clearPastedImages(opts={}){
  const preserveLocalCache = !!opts?.preserveLocalCache;
  const preservePreviewUrls = !!opts?.preservePreviewUrls || preserveLocalCache;
  const prevImages = Array.isArray(pastedImages) ? pastedImages.slice() : [];
  for(const it of prevImages){
    const composerId = ensureComposerImageKey(it);
    if(composerId) cancelComposerImageUpload(composerId, { silent:true });
    if(composerId && !preserveLocalCache) clearComposerImageLocalCache(composerId, { revokePreview:true });
    if(!preservePreviewUrls) revokeComposerImagePreviewUrl(String(it?._preview_url || '').trim());
  }
  pastedImages = [];
  pendingFiles = [];
  updateComposerActionState();
  Array.from(uploadPreviewMap.keys()).forEach(tempId => clearLocalUploadingPreview(tempId, { abort:true }));
  imagePreviewEl.innerHTML = "";
  refreshComposerLayoutSoon();
  updateComposerPlaceholder();
}

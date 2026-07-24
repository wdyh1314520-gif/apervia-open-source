/* Upload and drag/drop UI.*/

/* ✅ 上传：记录附件消息（带 id），system 绑定 _link，方便 × 一起删 */
function uploadRequestFormFields(){
  const out = {};
  try{
    const kbOverride = window.__kbUploadImportOverride && typeof window.__kbUploadImportOverride === 'object' ? window.__kbUploadImportOverride : null;
    if(kbOverride?.enabled){
      out.kb_import = '1';
      if(kbOverride.spaceId) out.kb_space_id = String(kbOverride.spaceId || '').trim();
      return out;
    }
    if(getActiveTemporarySession()) return out;
    // 普通上传只进入上传文件库；只有知识库界面上传时才通过 __kbUploadImportOverride 入库。
  }catch(_){ }
  return out;
}

function shouldUseChunkedUploadForFile(file){
  const size = Number(file?.size || 0) || 0;
  if(!file || !size || typeof fetch !== 'function') return false;
  const minSize = shouldUseWeakNonCriticalMode() ? 512 * 1024 : 1024 * 1024;
  return size >= minSize;
}

function preferredUploadChunkSizeBytes(file){
  const size = Number(file?.size || 0) || 0;
  if(shouldUseWeakNonCriticalMode()) return size >= 8 * 1024 * 1024 ? 512 * 1024 : 256 * 1024;
  return size >= 16 * 1024 * 1024 ? 1024 * 1024 : 512 * 1024;
}

async function parseUploadJsonResponse(res){
  const text = await res.text().catch(()=>'');
  if(!text) return {};
  try{ return JSON.parse(text); }catch(_){ return { error:text }; }
}

function uploadResponseError(data,status=0){
  const payload=data&&typeof data==='object'?data:{error:String(data||'')};
  const localized=typeof normalizeCompactErrorText==='function'?normalizeCompactErrorText(payload):'';
  const err=new Error(localized||payload.error||payload.message||('HTTP '+status));
  err.code=String(payload.code||payload.error_code||'');
  err.params=payload.params&&typeof payload.params==='object'?payload.params:{};
  return err;
}

async function uploadFetchJson(url, options={}, timeoutMs=45000, task=null){
  task?.throwIfAborted?.();
  const ctl = new AbortController();
  task?.trackController?.(ctl);
  const timeoutId = setTimeout(()=>{
    try{ ctl.abort('upload_timeout'); }catch(_){ }
  }, Math.max(8000, Number(timeoutMs || 45000) || 45000));
  try{
    const res = await fetch(url, { cache:'no-store', ...options, signal:ctl.signal });
    const data = await parseUploadJsonResponse(res);
    if(!res.ok) throw uploadResponseError(data,res.status);
    return data;
  }catch(err){
    if(task?.aborted) throw createUploadCanceledError();
    if(err?.name === 'AbortError' && String(ctl.signal?.reason || '') === 'upload_timeout') throw new Error('上传超时');
    throw err;
  }finally{
    try{ clearTimeout(timeoutId); }catch(_){ }
    task?.untrackController?.(ctl);
  }
}

async function uploadRawChunkWithRetry(uploadId, index, blob, attemptLimit=3, task=null){
  const maxAttempts = Math.max(1, Number(attemptLimit || 3) || 3);
  let lastErr = null;
  for(let attempt = 1; attempt <= maxAttempts; attempt++){
    task?.throwIfAborted?.();
    try{
      return await uploadFetchJson(
        `/api3/upload_chunk/raw_part?upload_id=${encodeURIComponent(uploadId)}&index=${encodeURIComponent(index)}`,
        {
          method:'POST',
          headers:{ 'Content-Type':'application/octet-stream' },
          body:blob,
        },
        shouldUseWeakNonCriticalMode() ? 60000 : 42000,
        task
      );
    }catch(err){
      lastErr = err;
      if(isUploadCanceledError(err) || task?.aborted) throw createUploadCanceledError();
      if(attempt >= maxAttempts) break;
      await sleep(Math.min(2200, 350 * attempt + stableJitterMs(260)));
    }
  }
  throw lastErr || new Error('分片上传失败');
}

async function uploadOneFileRequestChunked(file, previewId=null, hooks=null){
  const onProgress = typeof hooks?.onProgress === 'function' ? hooks.onProgress : null;
  const task = hooks?.task || getLocalUploadingPreviewTask(previewId);
  const formFields = uploadRequestFormFields();
  const requestedChunkSize = preferredUploadChunkSizeBytes(file);
  task?.throwIfAborted?.();
  updateLocalUploadingPreviewProgress(previewId, 0, 'uploading');
  try{ onProgress?.(0, 'uploading', null, null); }catch(_){ }

  const initData = await uploadFetchJson('/api3/upload_chunk/init', {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body:JSON.stringify({
      filename:String(file?.name || 'upload.bin'),
      size:Number(file?.size || 0) || 0,
      mime:String(file?.type || ''),
      chunk_size:requestedChunkSize,
      ...formFields,
    }),
  }, shouldUseWeakNonCriticalMode() ? 45000 : 30000, task);

  const uploadId = String(initData?.upload_id || '').trim();
  task?.setUploadId?.(uploadId);
  if(!uploadId) throw new Error(initData?.error || '分片上传初始化失败');
  const chunkSize = Math.max(32 * 1024, Number(initData?.chunk_size || requestedChunkSize) || requestedChunkSize);
  const totalSize = Number(file?.size || 0) || 0;
  const totalChunks = Math.max(1, Math.ceil(totalSize / chunkSize));

  for(let index = 0; index < totalChunks; index++){
    task?.throwIfAborted?.();
    const start = index * chunkSize;
    const end = Math.min(totalSize, start + chunkSize);
    const blob = file.slice(start, end);
    await uploadRawChunkWithRetry(uploadId, index, blob, shouldUseWeakNonCriticalMode() ? 4 : 3, task);
    const percent = Math.max(1, Math.min(96, Math.round(((index + 1) / totalChunks) * 96)));
    updateLocalUploadingPreviewProgress(previewId, percent, 'uploading');
    try{ onProgress?.(percent, 'uploading', { loaded:end, total:totalSize, lengthComputable:true }, null); }catch(_){ }
  }

  markLocalUploadingPreviewParsing(previewId);
  try{ onProgress?.(100, 'parsing', null, null); }catch(_){ }
  task?.throwIfAborted?.();
  return await uploadFetchJson('/api3/upload_chunk/finish', {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body:JSON.stringify({ upload_id:uploadId }),
  }, shouldUseWeakNonCriticalMode() ? 180000 : 120000, task);
}

function uploadOneFileRequestPlain(file, previewId=null, hooks=null){
  return new Promise((resolve, reject)=>{
    const onProgress = typeof hooks?.onProgress === 'function' ? hooks.onProgress : null;
    const task = hooks?.task || getLocalUploadingPreviewTask(previewId);
    try{ task?.throwIfAborted?.(); }catch(err){ reject(err); return; }
    const fd = new FormData();
    fd.append("file", file);
    const formFields = uploadRequestFormFields();
    for(const [key, value] of Object.entries(formFields)){
      if(String(value || '').trim()) fd.append(key, String(value || '').trim());
    }
    const xhr = new XMLHttpRequest();
    task?.trackXhr?.(xhr);
    xhr.open("POST", "/api3/upload", true);
    xhr.responseType = "text";
    xhr.upload.onprogress = (evt)=>{
      if(evt.lengthComputable){
        const percent = Math.round((evt.loaded / evt.total) * 100);
        updateLocalUploadingPreviewProgress(previewId, percent, "uploading");
        try{ onProgress?.(percent, 'uploading', evt, xhr); }catch(_){ }
      }
    };
    xhr.onloadstart = ()=>{
      updateLocalUploadingPreviewProgress(previewId, 0, "uploading");
      try{ onProgress?.(0, 'uploading', null, xhr); }catch(_){ }
    };
    xhr.onreadystatechange = ()=>{
      if(xhr.readyState === 2){
        markLocalUploadingPreviewParsing(previewId);
        try{ onProgress?.(100, 'parsing', null, xhr); }catch(_){ }
      }
    };
    xhr.onerror = ()=> reject(new Error("网络错误"));
    xhr.onabort = ()=> reject(new Error("上传已取消"));
    xhr.onerror = ()=>{ task?.untrackXhr?.(xhr); reject(new Error("网络错误")); };
    xhr.onabort = ()=>{ task?.untrackXhr?.(xhr); reject(createUploadCanceledError()); };
    xhr.onload = ()=>{
      task?.untrackXhr?.(xhr);
      if(task?.aborted) return reject(createUploadCanceledError());
      let data;
      try{ data = JSON.parse(xhr.responseText || "{}"); }catch{ data = { error: xhr.responseText || "返回格式错误" }; }
      if(xhr.status < 200 || xhr.status >= 300) return reject(uploadResponseError(data,xhr.status));
      resolve(data);
    };
    xhr.send(fd);
  });
}

function uploadClientMaxBytesForFile(file){
  if(isLikelyLocalImageFile(file)) return IMAGE_UPLOAD_MAX_BYTES;
  const formFields = uploadRequestFormFields();
  if(String(formFields.kb_import || '').trim()) return 0;
  return FILE_UPLOAD_MAX_BYTES;
}

function assertUploadClientFileSize(file){
  const maxBytes = uploadClientMaxBytesForFile(file);
  const size = Number(file?.size || 0) || 0;
  if(maxBytes > 0 && size > maxBytes){
    const label = isLikelyLocalImageFile(file) ? '图片' : '文件';
    throw new Error(`${label}过大，最大支持 ${fmtBytes(maxBytes)}`);
  }
}

async function uploadOneFileRequest(file, previewId=null, hooks=null){
  assertUploadClientFileSize(file);
  const task = hooks?.task || getLocalUploadingPreviewTask(previewId);
  if(shouldUseChunkedUploadForFile(file)){
    try{
      return await uploadOneFileRequestChunked(file, previewId, { ...(hooks || {}), task });
    }catch(err){
      if(isUploadCanceledError(err) || task?.aborted) throw createUploadCanceledError();
      console.warn('chunked upload failed, fallback to normal upload:', err);
      updateLocalUploadingPreviewProgress(previewId, 0, 'uploading');
      return await uploadOneFileRequestPlain(file, previewId, { ...(hooks || {}), task });
    }
  }
  try{
    return await uploadOneFileRequestPlain(file, previewId, { ...(hooks || {}), task });
  }catch(err){
    if(isUploadCanceledError(err) || task?.aborted) throw createUploadCanceledError();
    throw err;
  }
}

function commitUploadedFileAttachment(att, ownerSessionId=''){
  const ownerSid = String(ownerSessionId || '').trim();
  const currentOwnerSid = String(getComposerAttachmentOwnerSessionId() || '').trim();
  if(!ownerSid || ownerSid === currentOwnerSid || !store?.sessions?.[ownerSid]){
    pendingFiles.push(att);
    addPendingFileCard(att);
    persistComposerAttachmentDraft(currentOwnerSid || ownerSid, { immediate:true });
    return true;
  }

  const session = store.sessions[ownerSid];
  const previous = session.composerAttachmentDraft && typeof session.composerAttachmentDraft === 'object'
    ? session.composerAttachmentDraft
    : { files:[], images:[] };
  const files = (Array.isArray(previous.files) ? previous.files : []).map(normalizeComposerAttachmentDraftFile);
  const normalized = normalizeComposerAttachmentDraftFile(att);
  const identity = String(normalized.file_library_id || normalized.library_file_id || normalized.id || normalized.filename || '').trim().toLowerCase();
  if(!files.some(item => String(item.file_library_id || item.library_file_id || item.id || item.filename || '').trim().toLowerCase() === identity)){
    files.push(normalized);
  }
  const payload = {
    files,
    images: Array.isArray(previous.images) ? previous.images : [],
  };
  const changedAt = Date.now();
  session.composerAttachmentDraft = payload;
  session.composerAttachmentDraftUpdatedAt = changedAt;
  session.updatedAt = now();
  try{ rememberComposerAttachmentDraftRuntimeGuard(ownerSid, payload, changedAt); }catch(_){ }
  saveStore();
  return false;
}

async function uploadOneFile(file, previewId=null){
  const uploadOwnerSessionId = String(getComposerAttachmentOwnerSessionId() || '').trim();
  if(isLikelyLocalImageFile(file)) assertComposerCanAcceptAttachment('image');
  else assertComposerCanAcceptAttachment('file');
  const task = getLocalUploadingPreviewTask(previewId);
  let data = null;
  try{
    data = await uploadOneFileRequest(file, previewId);
  }catch(err){
    if(isUploadCanceledError(err) || task?.aborted){
      if(previewId) clearLocalUploadingPreview(previewId);
      return null;
    }
    throw err;
  }
  if(task?.aborted){
    if(previewId) clearLocalUploadingPreview(previewId);
    return null;
  }
  if(!data) return null;

  if(data.kind === "text"){
    const attId = newAttId();
    const ext = (String(data.filename).split(".").pop() || "").toUpperCase();
    const url = data.download_url || data.url || data.view_url || "";

    // ✅ 先进入“待发送”（可删）；真正写入会话在 send() 里完成
    const fileId = String(data.file_library_id || data.library_file_id || data.file_registry?.file_id || '').trim();
    const storageRef = String(data.storage_ref || data.model_storage_ref || data.file_registry?.storage_ref || '').trim();
    const att = { id: attId, kind:"file", file_library_id:fileId, library_file_id:fileId, storage_ref:storageRef, model_storage_ref:String(data.model_storage_ref || storageRef || '').trim(), source_type: String(data.source_type || 'upload').trim() || 'upload', filename: data.filename, ext, text: data.text || "", text_is_preview: !!data.text_is_preview, full_text_available: !!data.full_text_available, parsed_chars: Number(data.parsed_chars || 0) || 0, parsed_lines: Number(data.parsed_lines || 0) || 0, url, view_url: data.view_url || "", download_url: data.download_url || data.url || "", size: data.size || file?.size || 0, file_registry: data.file_registry || null, code_summary: data.code_summary || "", symbols: Array.isArray(data.symbols) ? data.symbols : [], kb_imported: !!data.kb_imported };
    assertComposerCanAcceptAttachment('file');
    assertComposerCanAcceptAttachment('file');
    if(previewId) clearLocalUploadingPreview(previewId);
    commitUploadedFileAttachment(att, uploadOwnerSessionId);
    updateComposerActionState();
    setStatus("已添加附件（待发送）");

  }else if(data.kind === "file"){
    const attId = newAttId();
    const ext = (String(data.filename).split(".").pop() || "").toUpperCase();
    const url = data.download_url || data.url || data.view_url || "";

    const fileId = String(data.file_library_id || data.library_file_id || data.file_registry?.file_id || '').trim();
    const storageRef = String(data.storage_ref || data.model_storage_ref || data.file_registry?.storage_ref || '').trim();
    const att = { id: attId, kind:"file", file_library_id:fileId, library_file_id:fileId, storage_ref:storageRef, model_storage_ref:String(data.model_storage_ref || storageRef || '').trim(), source_type: String(data.source_type || 'upload').trim() || 'upload', filename: data.filename, ext, text: "", url, view_url: data.view_url || "", download_url: data.download_url || data.url || "", size: data.size || file?.size || 0, note: data.note || "", file_registry: data.file_registry || null, code_summary: data.code_summary || "", symbols: Array.isArray(data.symbols) ? data.symbols : [], kb_imported: !!data.kb_imported };
    if(previewId) clearLocalUploadingPreview(previewId);
    commitUploadedFileAttachment(att, uploadOwnerSessionId);
    updateComposerActionState();
    setStatus("已添加附件（待发送）");

  }else if(data.kind === "image"){
    const dataUrl = String(data.data_url || "").trim();
    const persistedUrl = String(data.preview_url || data.view_url || data.url || data.download_url || "").trim();
    const previewUrl = dataUrl || persistedUrl;
    const imageUrl = persistedUrl || dataUrl;
    if(previewUrl && imageUrl){
      assertComposerCanAcceptAttachment('image');
      if(previewId) clearLocalUploadingPreview(previewId);
      const activeEndpointMode = getActiveApiEndpointMode();
      const imgItem = ensureComposerImageAttachmentMeta({ type:"image_url", attachment_id:String(data?.attachment_id || '').trim(), image_id:String(data?.image_id || data?.attachment_id || '').trim(), storage_ref:String(data?.storage_ref || '').trim(), model_storage_ref:String(data?.model_storage_ref || data?.storage_ref || '').trim(), file_library_id:String(data?.file_library_id || data?.library_file_id || data?.file_registry?.file_id || '').trim(), library_file_id:String(data?.library_file_id || data?.file_library_id || data?.file_registry?.file_id || '').trim(), file_registry:data?.file_registry || null, image_url:{ url:imageUrl }, persisted_url:persistedUrl, server_url:persistedUrl, view_url:String(data?.view_url || persistedUrl || '').trim(), download_url:String(data?.download_url || data?.url || persistedUrl || '').trim(), _preview_url:previewUrl, filename:data.filename || (file?.name || ""), _ocr_text: String(data?.text || '').trim(), source_role:String(data?.source_role || 'user'), source_type:String(data?.source_type || 'upload'), operation:String(data?.operation || 'upload'), endpoint_mode:activeEndpointMode, api_endpoint_mode:activeEndpointMode, created_at_ms:Number(data?.created_at_ms || Date.now()) || Date.now(), image_seq:Number(data?.image_seq || 1) || 1, _composerId:"cmpimg_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16) }, { endpointMode:activeEndpointMode });
      pastedImages.push(imgItem);
      addImageThumb(imgItem);
      updateComposerActionState();
      setStatus("已添加图片（待发送）");
    }else{
      throw new Error("图片返回为空");
    }
  }else{
    throw new Error(data?.error || "未知返回");
  }
}


fileEl.addEventListener("change", async ()=>{
  const files = Array.from(fileEl.files || []);
  if(!files.length) return;

  addFileBtn.disabled = true;
  try{
    setStatus("处理附件…");
    for(const f of files){
      const isImage = isLikelyLocalImageFile(f);
      if(isImage){
        await addImageFileToPreview(f);
        continue;
      }
      const previewId = addLocalUploadingPreview(f);
      try{
        await uploadOneFile(f, previewId);
      }catch(err){
        if(isUploadCanceledError(err)) continue;
        markLocalUploadingPreviewError(previewId, composerAttachmentT('composer.attachment.add_failed', null, 'Failed to add'));
        throw err;
      }
    }
  }catch(e){
    reportAppError("添加附件失败：" + e.message);
  }finally{
    addFileBtn.disabled = false;
    setStatus("就绪");
  }
});


/* ✅ 拖拽文件/图片 */
let dragDepth = 0;

function isFileDrag(e){
  const types = e.dataTransfer?.types;
  if(!types) return false;
  return Array.from(types).includes("Files");
}

function setDropActive(on){
  if(on) mainEl.classList.add("drop-active");
  else mainEl.classList.remove("drop-active");
  if(on) dropOverlayEl?.classList.add("show");
  else dropOverlayEl?.classList.remove("show");
}


// ✅ 只要拖到“输入框”上就可直接添加附件（符合你说的“拖到发送框内”）
inputEl.addEventListener("dragover", (e)=>{
  if(!isFileDrag(e)) return;
  e.preventDefault();
  inputEl.classList.add("drop-input-active");
});
inputEl.addEventListener("dragleave", (e)=>{
  if(!isFileDrag(e)) return;
  inputEl.classList.remove("drop-input-active");
});
inputEl.addEventListener("drop", async (e)=>{
  if(!isFileDrag(e)) return;
  e.preventDefault();
  inputEl.classList.remove("drop-input-active");

  const files = Array.from(e.dataTransfer.files || []);
  if(files.length){
    setStatus("处理拖拽附件…");
    for(const f of files){
      const isImage = isLikelyLocalImageFile(f);
      if(isImage){
        await addImageFileToPreview(f);
        continue;
      }
      const previewId = addLocalUploadingPreview(f);
      try{
        await uploadOneFile(f, previewId);
      }catch(err){
        markLocalUploadingPreviewError(previewId, composerAttachmentT('composer.attachment.add_failed', null, 'Failed to add'));
        reportAppError(`拖拽处理失败：${f.name}：${err.message}`);
      }
    }
    setStatus("就绪");
    return;
  }

  const remoteUrls = pickRemoteImageUrlsFromClipboardLikeData({
    html: String(e.dataTransfer?.getData?.('text/html') || ''),
    text: String(e.dataTransfer?.getData?.('text/plain') || ''),
    uriList: String(e.dataTransfer?.getData?.('text/uri-list') || '')
  });
  if(remoteUrls.length){
    setStatus('导入拖拽图片链接…');
    await importRemoteImageUrls(remoteUrls, '拖拽的图片链接');
    setStatus('就绪');
  }
});
window.addEventListener("dragenter", (e)=>{
  if(!isFileDrag(e)) return;
  dragDepth++;
  setDropActive(true);
});

window.addEventListener("dragleave", (e)=>{
  if(!isFileDrag(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if(dragDepth === 0) setDropActive(false);
});

window.addEventListener("dragover", (e)=>{
  if(!isFileDrag(e)) return;
  e.preventDefault();
});

window.addEventListener("drop", async (e)=>{
  if(!isFileDrag(e)) return;
  // 输入框的 drop 已单独处理
  if(e.target === inputEl) return;
  e.preventDefault();
  dragDepth = 0;
  setDropActive(false);

  const files = Array.from(e.dataTransfer.files || []);
  if(files.length){
    setStatus("处理拖拽文件…");
    for(const f of files){
      const isImage = isLikelyLocalImageFile(f);
      if(isImage){
        await addImageFileToPreview(f);
        continue;
      }
      const previewId = addLocalUploadingPreview(f);
      try{
        await uploadOneFile(f, previewId);
      }catch(err){
        markLocalUploadingPreviewError(previewId, composerAttachmentT('composer.attachment.add_failed', null, 'Failed to add'));
        reportAppError(`拖拽处理失败：${f.name}：${err.message}`);
      }
    }
    setStatus("就绪");
    return;
  }

  const remoteUrls = pickRemoteImageUrlsFromClipboardLikeData({
    html: String(e.dataTransfer?.getData?.('text/html') || ''),
    text: String(e.dataTransfer?.getData?.('text/plain') || ''),
    uriList: String(e.dataTransfer?.getData?.('text/uri-list') || '')
  });
  if(remoteUrls.length){
    setStatus('导入拖拽图片链接…');
    await importRemoteImageUrls(remoteUrls, '拖拽的图片链接');
    setStatus('就绪');
  }
});

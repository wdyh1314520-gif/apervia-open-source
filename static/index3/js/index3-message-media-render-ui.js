/* Message media/content rendering.*/

function messageMediaT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params || {}, fallback) || String(fallback || key || '');
}

function normalizeImageGenerationForcedTimeoutMessage(raw){
  const text = String(raw || '').trim();
  if(!text) return '';
  if(text.includes('上游异常超时') || text.includes('ImageGenerationTimeoutError')){
    return messageMediaT('stream.image_timeout', null, 'Upstream image generation timed out and was stopped.');
  }
  return '';
}

function legacyImageReplyToText(payload){
  const data = payload && typeof payload === "object" ? payload : {};
  const text = String(data.text || "").trim();
  if(text) return text;
  const count = normalizeImageItems(data.images).length;
  return count > 0 ? messageMediaT('message.image_reply_count', {count}, `Image response: ${count} images`) : "";
}

function normalizeImageReplySourceIds(item, data){
  const rows = [];
  const push = (value)=>{
    if(value === undefined || value === null) return;
    if(Array.isArray(value)){
      value.forEach(push);
      return;
    }
    const text = String(value || '').trim();
    if(text && !rows.includes(text)) rows.push(text);
  };
  push(item?.source_image_ids);
  push(item?.sourceImageIds);
  push(item?.derived_from);
  push(item?.derivedFrom);
  push(data?.source_image_ids);
  push(data?.sourceImageIds);
  push(data?.derived_from);
  push(data?.derivedFrom);
  return rows.slice(0, 8);
}

function normalizeImageReplyForModelRequest(payload){
  const data = payload && typeof payload === "object" ? payload : {};
  const images = normalizeImageItems(data.images);
  const payloadEndpointMode = normalizeApiEndpointMode(data.endpoint_mode || data.api_endpoint_mode || data.apiEndpointMode || data.endpointMode || '');
  const cleanImages = images.map((item, idx)=>{
    const itemEndpointMode = normalizeApiEndpointMode(item.endpoint_mode || item.api_endpoint_mode || item.apiEndpointMode || payloadEndpointMode || '');
    const rawUrl = String(item.rawUrl || item.raw_url || item.viewUrl || item.view_url || item.downloadUrl || item.download_url || item.url || item.src || "").trim();
    const viewUrl = String(item.viewUrl || item.view_url || item.rawUrl || item.raw_url || item.url || "").trim();
    const downloadUrl = String(item.downloadUrl || item.download_url || "").trim();
    const previewUrl = String(item.previewUrl || item.preview_url || "").trim();
    const sourceImageIds = normalizeImageReplySourceIds(item, data);
    return {
      url: previewUrl || viewUrl || downloadUrl || rawUrl || String(item.url || "").trim(),
      raw_url: rawUrl || viewUrl || downloadUrl || previewUrl,
      view_url: viewUrl || rawUrl || previewUrl,
      download_url: downloadUrl,
      preview_url: previewUrl,
      storage_ref: String(item.storage_ref || item.model_storage_ref || item.file_registry?.storage_ref || item.file_registry?.model_storage_ref || '').trim(),
      model_storage_ref: String(item.model_storage_ref || item.storage_ref || item.file_registry?.model_storage_ref || item.file_registry?.storage_ref || '').trim(),
      file_library_id: String(item.file_library_id || item.library_file_id || item.file_registry?.file_id || '').trim(),
      library_file_id: String(item.library_file_id || item.file_library_id || item.file_registry?.file_id || '').trim(),
      file_registry: item.file_registry && typeof item.file_registry === 'object' ? item.file_registry : null,
      persisted_url: String(item.persisted_url || item.persistedUrl || '').trim(),
      server_url: String(item.server_url || item.serverUrl || '').trim(),
      _source_url: String(item._source_url || item.source_url || item.sourceUrl || '').trim(),
      _preview_url: String(item._preview_url || item.preview_url || item.previewUrl || '').trim(),
      provider_url: String(item.providerUrl || item.provider_url || '').trim(),
      image_url: item.image_url && typeof item.image_url === 'object' ? { ...item.image_url } : (item.image_url ? { url:String(item.image_url || '').trim() } : undefined),
      filename: String(item.filename || item.name || `generated_image_${idx + 1}.png`).trim(),
      alt: String(item.alt || item.caption || data.subject || "生成图片").trim(),
      caption: String(item.caption || item.alt || data.subject || "生成图片").trim(),
      image_id: String(item.image_id || item.imageId || item.attachment_id || item.id || '').trim(),
      attachment_id: String(item.attachment_id || item.id || item.image_id || '').trim(),
      endpoint_mode: itemEndpointMode,
      api_endpoint_mode: itemEndpointMode,
      source_type: String(item.source_type || item.sourceType || data.source_type || data.source || 'assistant_generated').trim(),
      source_role: String(item.source_role || item.sourceRole || data.source_role || 'assistant').trim(),
      operation: String(item.operation || item.task_mode || data.operation || data.task_mode || '').trim(),
      task_mode: String(item.task_mode || item.operation || data.task_mode || data.operation || '').trim(),
      parent_image_id: String(item.parent_image_id || item.parentImageId || data.parent_image_id || data.parentImageId || '').trim(),
      source_image_ids: sourceImageIds,
      derived_from: sourceImageIds,
      created_at_ms: Number(item.created_at_ms || item.createdAtMs || data.created_at_ms || data.createdAtMs || 0) || undefined,
      image_seq: Number(item.image_seq || item.seq || idx + 1) || (idx + 1),
      ocr_text_hint: String(item.ocr_text_hint || item.ocrTextHint || item._ocr_text || item.text || '').trim(),
    };
  }).filter(item => item.url || item.raw_url || item.view_url || item.download_url || item.model_storage_ref || item.storage_ref || item.file_library_id || item.library_file_id);
  return {
    _kind: 'image_reply',
    source: String(data.source || 'image_generation'),
    subject: String(data.subject || '').trim(),
    text: String(data.text || '').trim(),
    endpoint_mode: payloadEndpointMode,
    api_endpoint_mode: payloadEndpointMode,
    images: cleanImages,
  };
}


function isImageGenerationStatusText(raw){
  const text = String(raw || '').trim();
  if(!text) return false;
  return /(正在生成图片|正在生成图像|正在生成图|正在出图|正在生图|生成图片|图片生成|图片任务|拉回生图|正在参考图片生成|参考图片生成|正在编辑图片|正在改图|编辑图片|图片编辑|图片交付链路)/.test(text);
}

function ensureBubbleImageStageShell(bubble, opts={}){
  const body = bubble?.querySelector?.('.bubble-body');
  if(!body) return null;
  let shell = body.querySelector('.image-generation-stage');
  if(!shell){
    shell = document.createElement('div');
    shell.className = 'image-generation-stage is-loading';
    shell.innerHTML = '<div class="image-generation-stage-slot"><div class="image-generation-stage-skeleton"></div></div><div class="image-generation-stage-status"></div>';
    const reasoningNode = body.querySelector('.reasoning-panels, .reasoning-panel');
    if(reasoningNode && reasoningNode.parentNode === body) body.insertBefore(shell, reasoningNode.nextSibling || null);
    else body.appendChild(shell);
  }
  bubble.classList.add('bubble-image-stage');
  const slot = shell.querySelector('.image-generation-stage-slot');
  const statusEl = shell.querySelector('.image-generation-stage-status');
  const imageGeneratingText = messageMediaT('stream.generating_image', null, 'Generating image…');
  const statusText = String(opts.statusText || imageGeneratingText).trim() || imageGeneratingText;
  if(statusEl){
    statusEl.textContent = statusText;
    statusEl.style.display = '';
  }
  return { shell, slot, statusEl };
}

function clearBubbleImageStageShell(bubble, opts={}){
  const remove = !!opts.remove;
  const body = bubble?.querySelector?.('.bubble-body');
  if(!body) return;
  const shell = body.querySelector('.image-generation-stage');
  if(shell && remove) shell.remove();
  if(remove){
    bubble.classList.remove('bubble-image-stage');
    delete bubble.dataset.imageStageReady;
  }
}

function markImageGenerationStageReady(shell, payload){
  if(!shell) return;
  shell.classList.remove('is-loading');
  shell.classList.add('is-ready');
  shell.querySelector('.image-generation-stage-skeleton')?.remove();
  const bubble = shell.closest('.bubble');
  if(bubble){
    bubble.dataset.imageStageReady = '1';
    delete bubble.dataset.imageStagePendingFinal;
  }
  const statusEl = shell.querySelector('.image-generation-stage-status');
  const statusText = String(payload?.text || '').trim();
  if(statusEl){
    statusEl.textContent = statusText;
    statusEl.style.display = statusText ? '' : 'none';
  }
}

function keepImageGenerationStageLoading(shell, text=messageMediaT('message.image_loading', null, 'Image received. Loading…')){
  if(!shell) return;
  shell.classList.add('is-loading');
  shell.classList.remove('is-ready');
  let slot = shell.querySelector('.image-generation-stage-slot');
  if(slot && !slot.querySelector('.image-generation-stage-skeleton')){
    const skeleton = document.createElement('div');
    skeleton.className = 'image-generation-stage-skeleton';
    slot.insertBefore(skeleton, slot.firstChild || null);
  }
  const statusEl = shell.querySelector('.image-generation-stage-status');
  if(statusEl){
    statusEl.textContent = text;
    statusEl.style.display = '';
  }
}

function inlineImageHasVisibleRealPixels(img){
  if(!img) return false;
  const loadedSrc = String(img.getAttribute?.('src') || img.currentSrc || img.src || '').trim();
  if(!loadedSrc || loadedSrc === IMAGE_REMOTE_PLACEHOLDER_URL) return false;
  if(String(img.dataset?.srcStage || '').trim() === 'proxy-pending') return false;
  return !!(img.complete && (img.naturalWidth || 0) > 0 && (img.naturalHeight || 0) > 0);
}

function watchImageGenerationStageLoad(shell, payload){
  const imgs = Array.from(shell?.querySelectorAll?.('img.inline-img') || []);
  if(!imgs.length) return false;
  const loaded = imgs.find(img => inlineImageHasVisibleRealPixels(img));
  if(loaded){
    markImageGenerationStageReady(shell, payload);
    return true;
  }
  let settled = false;
  const cleanup = () => {
    imgs.forEach(img => {
      try{ img.removeEventListener('load', onLoad, true); }catch(_){ }
      try{ img.removeEventListener('error', onError, true); }catch(_){ }
    });
  };
  const onLoad = (event) => {
    const img = event?.target;
    if(settled) return;
    if(inlineImageHasVisibleRealPixels(img)){
      settled = true;
      cleanup();
      markImageGenerationStageReady(shell, payload);
      return;
    }
    keepImageGenerationStageLoading(shell);
  };
  const onError = () => {
    if(settled) return;
    const anyLoaded = imgs.some(img => inlineImageHasVisibleRealPixels(img));
    if(anyLoaded){
      settled = true;
      cleanup();
      markImageGenerationStageReady(shell, payload);
      return;
    }
    keepImageGenerationStageLoading(shell);
  };
  imgs.forEach(img => {
    img.addEventListener('load', onLoad, true);
    img.addEventListener('error', onError, true);
  });
  keepImageGenerationStageLoading(shell);
  return false;
}

async function renderImageReplyIntoStageShell(shell, payload){
  if(!shell) return null;
  const slot = shell.querySelector('.image-generation-stage-slot');
  if(!slot) return null;
  slot.innerHTML = '<div class="image-generation-stage-skeleton"></div>';
  const images = normalizeImageReplyImagesForPayload(payload);
  let rendered = null;
  if(images.length){
    rendered = await appendImageGroup(slot, images);
  }
  if(!rendered){
    slot.innerHTML = '';
    const empty = document.createElement('div');
    empty.className = 'image-generation-stage-empty';
    empty.textContent = messageMediaT('message.image_loading', null, 'Image received. Loading…');
    slot.appendChild(empty);
    keepImageGenerationStageLoading(shell, messageMediaT('message.image_loading', null, 'Image received. Loading…'));
    return null;
  }
  watchImageGenerationStageLoad(shell, payload);
  return rendered;
}

function clearImageOnlyBubbleProcessUi(bubble){
  if(!bubble?.querySelector) return bubble;
  const body = bubble.querySelector('.bubble-body');
  if(!body) return bubble;
  body.querySelectorAll(':scope > .reasoning-answer-wrap, :scope > .thinking-wrap, :scope > .reasoning-panels, :scope > .reasoning-panel').forEach(node => {
    try{ node.remove(); }catch(_){ }
  });
  setBubbleProcessText(bubble, '');
  return bubble;
}

function clearSessionImageOnlyReasoningRuntime(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  const rt = ensureSessionRuntime(sid);
  rt.reasoning = [];
  rt.reasoningMeta = {};
  rt.draftProcessText = '';
}

function isGeneratedImageReplyPayload(payload){
  return !!(payload && typeof payload === 'object' && !isImageSearchReplyPayload(payload));
}

function isGeneratedImageReplyMessage(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').toLowerCase() !== 'assistant') return false;
  const content = m.content;
  if(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply' && isGeneratedImageReplyPayload(content)) return true;
  const replies = _normalizePendingAssistantImageReplies([
    ...(Array.isArray(m.imageReplies) ? m.imageReplies : []),
    ...(Array.isArray(m.image_replies) ? m.image_replies : []),
  ]);
  return replies.some(isGeneratedImageReplyPayload);
}

function isGeneratedImageOnlyOrphanReasoningMessage(msg, previousMessage){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').toLowerCase() !== 'assistant') return false;
  if(!isGeneratedImageReplyMessage(previousMessage)) return false;
  const content = m.content;
  if(typeof content === 'string' && content.trim()) return false;
  if(Array.isArray(content) && content.some(part => {
    if(!part) return false;
    if(part.type === 'text') return String(part.text || '').trim();
    if(part.type === 'image_url') return true;
    return true;
  })) return false;
  if(content && typeof content === 'object' && !Array.isArray(content) && Object.keys(content).length) return false;
  if(_normalizePendingAssistantImageReplies([
    ...(Array.isArray(m.imageReplies) ? m.imageReplies : []),
    ...(Array.isArray(m.image_replies) ? m.image_replies : []),
  ]).length) return false;
  if(normalizeAssistantWeatherPayload(m.weather || m.weather_payload || null)) return false;
  if(_normalizePendingAssistantFiles(m.generatedFiles || m.generated_files || []).length) return false;
  if(String(m.fileProcessText || m.file_process_text || '').trim()) return false;
  return !!_messageReasoningSnapshot(m);
}

async function patchDraftBubbleWithImageReply(bubble, payload){
  if(!bubble?.querySelector) return bubble;
  const body = bubble.querySelector('.bubble-body');
  if(!body) return bubble;
  if(isGeneratedImageReplyPayload(payload)) clearImageOnlyBubbleProcessUi(bubble);
  else {
    body.querySelector('.reasoning-answer-wrap')?.remove();
    body.querySelector('.thinking-wrap')?.remove();
  }
  const stage = ensureBubbleImageStageShell(bubble, { statusText:messageMediaT('message.image_loading', null, 'Image received. Loading…') });
  if(!stage?.shell) return bubble;
  await renderImageReplyIntoStageShell(stage.shell, payload);
  setBubbleProcessText(bubble, '');
  bindBubbleEnhancements(bubble);
  dedupeAdjacentAssistantImageBubbles();
  return bubble;
}

function finalizeVisibleImageDraftBubble(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  const bubble = getVisibleDraftBubble(sid);
  if(!bubble) return null;
  bubble.classList.remove('bubble-streaming');
  bubble.removeAttribute('data-session-draft');
  const caret = bubble.querySelector('.bubble-streaming-caret');
  if(caret) caret.remove();
  clearImageOnlyBubbleProcessUi(bubble);
  delete liveDraftBubbleEls[sid];
  return bubble;
}

function finalizeVisiblePendingImageStageBubble(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  const bubble = getVisibleDraftBubble(sid);
  if(!bubble) return null;
  bubble.classList.remove('bubble-streaming');
  const caret = bubble.querySelector('.bubble-streaming-caret');
  if(caret) caret.remove();
  setBubbleProcessText(bubble, '');
  bubble.dataset.imageStagePendingFinal = '1';
  const imageGeneratingText = messageMediaT('stream.generating_image', null, 'Generating image…');
  const statusText = String(opts.statusText || bubble.dataset.draftStatusText || imageGeneratingText).trim() || imageGeneratingText;
  const stage = ensureBubbleImageStageShell(bubble, { statusText });
  if(stage?.shell){
    stage.shell.classList.remove('is-ready');
    stage.shell.classList.add('is-loading');
    if(stage.statusEl){
      stage.statusEl.textContent = statusText;
      stage.statusEl.style.display = '';
    }
  }
  return bubble;
}

async function renderImageReplyIntoBubble(bubble, payload){
  if(!bubble) return bubble;
  const body = bubble.querySelector('.bubble-body');
  if(!body) return bubble;
  body.innerHTML = '';

  const data = payload && typeof payload === 'object' ? payload : {};
  const images = normalizeImageReplyImagesForPayload(data);
  const text = String(data.text || '').trim();

  let hasRendered = false;
  if(images.length){
    const stageWrap = document.createElement('div');
    stageWrap.className = 'image-generation-stage is-loading';
    stageWrap.innerHTML = '<div class="image-generation-stage-slot"><div class="image-generation-stage-skeleton"></div></div><div class="image-generation-stage-status"></div>';
    const stageStatus = stageWrap.querySelector('.image-generation-stage-status');
    if(stageStatus) stageStatus.textContent = messageMediaT('message.image_loading', null, 'Image received. Loading…');
    body.appendChild(stageWrap);
    bubble.classList.add('bubble-image-stage');
    const group = await renderImageReplyIntoStageShell(stageWrap, data);
    if(group) hasRendered = true;
    const actions = buildImageReplyActions(images);
    if(actions){
      body.appendChild(actions);
      hasRendered = true;
    }
  }
  if(text){
    const block = document.createElement('div');
    block.className = 'structured-text-block';
    block.innerHTML = renderRichTextHtml(text);
    body.appendChild(block);
    hasRendered = true;
  }
  if(!hasRendered){
    const fallback = document.createElement('div');
    fallback.className = 'structured-text-block';
    fallback.innerHTML = renderRichTextHtml(messageMediaT('message.image_loading', null, 'Image received. Loading…'));
    body.appendChild(fallback);
  }
  return bubble;
}

function addImageReplyBubble(payload, opts={}){
  const message = opts.message && typeof opts.message === 'object'
    ? opts.message
    : { role:'assistant', content: payload };
  const bubble = buildBubbleNode('assistant', '', {
    message,
    messageIndex: opts.messageIndex,
    sessionId: opts.sessionId || store?.activeId || '',
    disableCopy: true,
  });
  chatEl.appendChild(bubble);
  Promise.resolve(renderImageReplyIntoBubble(bubble, payload)).finally(()=>{
    bindBubbleEnhancements(bubble);
    dedupeAdjacentAssistantImageBubbles();
  });
  return bubble;
}

function imageUrlLooksLikeSignedProviderObject(url){
  const u = String(url || '').trim();
  if(!u || !/^https?:\/\//i.test(u)) return false;
  try{
    const parsed = new URL(u);
    const host = String(parsed.hostname || '').toLowerCase();
    const query = String(parsed.search || '').toLowerCase();
    const signed = /(x-tos-|x-amz-|x-goog-|x-oss-|signature=|x-tos-signature=|x-amz-signature=|x-goog-signature=|x-oss-signature=|expires=|x-tos-expires=|x-amz-expires=)/i.test(query);
    if(!signed) return false;
    return /(^|\.)(volces\.com|tos-[^.]+\.volces\.com|amazonaws\.com|googleapis\.com|aliyuncs\.com|myqcloud\.com)$/i.test(host)
      || host.includes('.volces.com')
      || host.includes('.amazonaws.com')
      || host.includes('.googleapis.com')
      || host.includes('.aliyuncs.com')
      || host.includes('.myqcloud.com');
  }catch(_){
    return /(x-tos-|x-amz-|x-goog-|x-oss-|signature=|expires=)/i.test(u);
  }
}

function shouldBypassRemoteImageProxy(url){
  const u = String(url || '').trim();
  if(!u || !/^https?:\/\//i.test(u)) return false;
  // 生成图上游返回的对象存储签名 URL 可以先让浏览器直连加载；
  // 服务端代理仍作为失败回退，不再让首屏显示被 /api3/remote-image 的二次下载拖慢。
  return imageUrlLooksLikeSignedProviderObject(u);
}

function buildRemoteImageProxyUrl(url, opts={}){
  const u = String(url || '').trim();
  if(!u || !/^https?:\/\//i.test(u)) return '';
  const preview = opts && Object.prototype.hasOwnProperty.call(opts, 'preview') ? !!opts.preview : true;
  const prefix = preview ? '/api3/remote-image?preview=1&url=' : '/api3/remote-image?url=';
  return `${prefix}${encodeURIComponent(u)}`;
}


const IMAGE_MIRROR_POLL_MAX_ATTEMPTS = 90;
const IMAGE_MIRROR_POLL_BASE_DELAY_MS = 1200;
const IMAGE_REMOTE_PLACEHOLDER_URL = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="transparent"/></svg>');

function imageMirrorStatusUrl(providerUrl){
  const u = String(providerUrl || '').trim();
  if(!u || !/^https?:\/\//i.test(u)) return '';
  return '/api3/image-generation/mirror-status?url=' + encodeURIComponent(u);
}

function remoteImageProxyStatusUrl(providerUrl){
  const u = String(providerUrl || '').trim();
  if(!u || !/^https?:\/\//i.test(u)) return '';
  return '/api3/remote-image/status?url=' + encodeURIComponent(u);
}

function isRemoteImageProxyUrl(url){
  const u = String(url || '').trim();
  return /^\/api3\/(?:remote-image|image_proxy)(?:\?|$)/i.test(u) || /^https?:\/\/[^/]+\/api3\/(?:remote-image|image_proxy)(?:\?|$)/i.test(u);
}

function inlineImageMirrorDisabled(imgEl){
  if(!imgEl) return false;
  if(String(imgEl.dataset.disableMirror || '').trim() === '1') return true;
  const sourceType = String(imgEl.dataset.sourceType || imgEl.dataset.source_type || '').trim().toLowerCase();
  if(isImageSearchSourceType(sourceType)) return true;
  const operation = String(imgEl.dataset.operation || imgEl.dataset.intent || '').trim().toLowerCase();
  return operation === 'image_search' || operation === 'visual_image_search' || operation === 'web_image_search';
}

function imageMirrorCandidateUrlFromImg(imgEl){
  if(!imgEl) return '';
  if(inlineImageMirrorDisabled(imgEl)) return '';
  const provider = String(imgEl.dataset.providerSrc || '').trim();
  if(provider && /^https?:\/\//i.test(provider)) return provider;
  const raw = String(imgEl.dataset.rawSrc || imgEl.dataset.originSrc || '').trim();
  if(raw && /^https?:\/\//i.test(raw)){
    try{
      const meta = parseSameAppUrlMeta(raw);
      if(meta?.isSameApp && /^\/api3\//i.test(meta.path || '')) return '';
    }catch(_){ }
    return raw;
  }
  return '';
}

function inlineImageHasRenderableMirrorImage(imgEl){
  if(!imgEl) return false;
  const src = String(imgEl.getAttribute('src') || imgEl.currentSrc || imgEl.src || '').trim();
  if(!src) return false;
  if(src === IMAGE_REMOTE_PLACEHOLDER_URL) return false;
  if(src.startsWith('data:image/svg+xml') && src.includes('transparent')) return false;
  return !!(imgEl.complete && (imgEl.naturalWidth || 0) > 0 && (imgEl.naturalHeight || 0) > 0);
}

function markInlineImageMirrorVisible(imgEl){
  if(!imgEl) return false;
  const cell = imgEl.closest('.inline-image-cell') || imgEl.closest('.inline-img-standalone');
  if(!cell) return false;
  if(!inlineImageHasRenderableMirrorImage(imgEl)) return false;
  cell.classList.add('mirror-visible');
  cell.classList.remove('mirror-pending');
  if(!cell.classList.contains('load-failed')) cell.querySelector('.inline-image-fallback')?.remove();
  return true;
}

function markInlineImageMirrorPending(imgEl, text='图片正在拉取中'){
  if(!imgEl) return;
  if(imgEl.dataset.mirrorReady === '1' || markInlineImageMirrorVisible(imgEl)) return;
  const cell = imgEl.closest('.inline-image-cell') || imgEl.closest('.inline-img-standalone');
  if(!cell) return;
  cell.classList.remove('mirror-visible');
  cell.classList.add('mirror-pending');
  cell.classList.remove('load-failed');
  let fallback = cell.querySelector('.inline-image-fallback');
  if(!fallback){
    fallback = document.createElement('div');
    fallback.className = 'inline-image-fallback';
    fallback.innerHTML = '<div class="icon">🖼️</div><div></div>';
    cell.appendChild(fallback);
  }
  const label = fallback.querySelector('div:last-child');
  if(label) label.textContent = text;
}

function clearInlineImageMirrorPending(imgEl){
  if(!imgEl) return;
  const cell = imgEl.closest('.inline-image-cell') || imgEl.closest('.inline-img-standalone');
  if(!cell) return;
  cell.classList.remove('mirror-pending');
  if(inlineImageHasRenderableMirrorImage(imgEl)) cell.classList.add('mirror-visible');
  if(!cell.classList.contains('load-failed')) cell.querySelector('.inline-image-fallback')?.remove();
}

function applyMirroredArtifactToInlineImage(imgEl, artifact){
  if(!imgEl || !artifact || typeof artifact !== 'object') return false;
  const providerUrlForPersist = imageMirrorCandidateUrlFromImg(imgEl) || String(imgEl.dataset.providerSrc || imgEl.dataset.rawSrc || imgEl.dataset.originSrc || '').trim();
  const preview = String(artifact.preview_url || artifact.previewUrl || artifact.view_url || artifact.viewUrl || artifact.url || '').trim();
  const view = String(artifact.view_url || artifact.viewUrl || artifact.raw_url || artifact.rawUrl || artifact.download_url || artifact.downloadUrl || preview).trim();
  const download = String(artifact.download_url || artifact.downloadUrl || view || preview).trim();
  if(!preview && !view) return false;
  const nextSrc = preview || view;
  imgEl.dataset.srcStage = 'mirrored';
  imgEl.dataset.rawSrc = view || nextSrc;
  imgEl.dataset.originSrc = view || nextSrc;
  imgEl.dataset.proxySrc = '';
  imgEl.dataset.mirrorReady = '1';
  imgEl.dataset.mirrorPollActive = '';
  imgEl.dataset.downloadSrc = download || '';
  clearInlineImageMirrorPending(imgEl);
  clearInlineImageFailedState(imgEl);
  if(imgEl.getAttribute('src') !== nextSrc) imgEl.src = nextSrc;
  try{ persistMirroredImageArtifactForCurrentStore(providerUrlForPersist, artifact); }catch(_){ }
  try{ syncInlineImageGroupState(imgEl.closest('.inline-image-group')); }catch(_){ }
  return true;
}

async function fetchImageMirrorStatus(providerUrl){
  const u = String(providerUrl || '').trim();
  if(!u || isNavigatorOffline()) return null;
  const endpoints = [imageMirrorStatusUrl(u), remoteImageProxyStatusUrl(u)].filter(Boolean);
  let best = null;
  for(const endpoint of endpoints){
    const ctl = new AbortController();
    const timeoutId = setTimeout(()=>{ try{ ctl.abort('image_mirror_status_timeout'); }catch(_){ } }, computeWeakFetchTimeoutMs('image_probe'));
    try{
      const resp = await fetch(endpoint, { method:'GET', credentials:'same-origin', cache:'no-store', signal: ctl.signal });
      if(!resp.ok) continue;
      const data = await resp.json();
      if(data?.ready || data?.artifact || String(data?.status?.status || '').toLowerCase() === 'ready') return data;
      const state = String(data?.status?.status || '').toLowerCase();
      if(!best || (state && state !== 'unknown')) best = data;
    }catch(_){
      // Keep trying the secondary status source. Generated-image mirror status and
      // generic remote-image warm status are intentionally independent.
    }finally{
      try{ clearTimeout(timeoutId); }catch(_){ }
    }
  }
  return best;
}

function normalizeRemoteImageJobState(data){
  const root = data && typeof data === 'object' ? data : {};
  const status = root.status && typeof root.status === 'object' ? root.status : {};
  const raw = String(root.state || status.state || status.status || '').trim().toLowerCase();
  const aliases = {
    running: 'fetching',
    downloading: 'fetching',
    checking_cache: 'fetching',
    failed: 'failed_retryable',
    error: 'failed_retryable',
    done: 'ready',
    completed: 'ready'
  };
  const state = aliases[raw] || raw || (root.ready || status.ready ? 'ready' : 'queued');
  const retryAfterMs = Number(root.retry_after_ms || status.retry_after_ms || 0) || 0;
  const attempts = Number(status.attempts || root.attempts || 0) || 0;
  const maxAttempts = Number(status.max_attempts || root.max_attempts || 0) || 0;
  const phase = String(status.phase || root.phase || '').trim().toLowerCase();
  return {
    state,
    phase,
    retryAfterMs,
    attempts,
    maxAttempts,
    retryable: !!(root.retryable || status.retryable || ['queued','fetching','failed_retryable'].includes(state)),
    terminal: !!(root.terminal || status.terminal || ['ready','failed_final'].includes(state)),
    error: String(root.error || status.error || '').trim()
  };
}

function remoteImageJobStatusLabel(info){
  const state = String(info?.state || '').toLowerCase();
  const phase = String(info?.phase || '').toLowerCase();
  if(state === 'queued') return messageMediaT('message.image_queue', null, 'Image queued for background retrieval');
  if(state === 'fetching'){
  if(phase === 'checking_cache') return messageMediaT('message.image_checking_cache', null, 'Checking the image cache');
  if(phase === 'downloading') return messageMediaT('message.image_downloading', null, 'Retrieving the image in the background');
  return messageMediaT('message.image_processing', null, 'Processing the image in the background');
  }
  if(state === 'failed_retryable') return messageMediaT('message.image_retry_later', null, 'Image retrieval failed. Apervia will retry automatically.');
  if(state === 'failed_final') return messageMediaT('message.image_retry_manual', null, 'The image cannot be retrieved right now. You can retry later.');
  return messageMediaT('message.image_retrieving', null, 'Retrieving image');
}

function scheduleImageMirrorPoll(imgEl, reason=''){
  const providerUrl = imageMirrorCandidateUrlFromImg(imgEl);
  if(!providerUrl || !imgEl || imgEl.dataset.mirrorReady === '1') return false;
  const currentAttempt = Number(imgEl.dataset.mirrorPollAttempt || 0) || 0;
  if(currentAttempt >= IMAGE_MIRROR_POLL_MAX_ATTEMPTS){
    markInlineImageMirrorPending(imgEl, '图片仍在后台队列中，可稍后回来查看');
    imgEl.dataset.mirrorPollActive = '';
    return true;
  }
  if(imgEl.dataset.mirrorPollActive === '1') return true;
  imgEl.dataset.mirrorPollActive = '1';
  markInlineImageMirrorPending(imgEl, currentAttempt > 2
    ? messageMediaT('message.image_background_retrieving', null, 'Retrieving image in the background')
    : messageMediaT('message.image_queue', null, 'Image queued for background retrieval'));
  const run = async ()=>{
    if(!imgEl.isConnected || imgEl.dataset.mirrorReady === '1'){
      imgEl.dataset.mirrorPollActive = '';
      return;
    }
    const alreadyVisible = markInlineImageMirrorVisible(imgEl);
    const attempt = Number(imgEl.dataset.mirrorPollAttempt || 0) || 0;
    imgEl.dataset.mirrorPollAttempt = String(attempt + 1);
    let serverRetryAfterMs = 0;
    try{
      const data = await fetchImageMirrorStatus(providerUrl);
      const status = data?.status || {};
      const stateInfo = normalizeRemoteImageJobState(data);
      serverRetryAfterMs = Number(stateInfo.retryAfterMs || 0) || 0;
      const artifact = data && (data.ready || stateInfo.state === 'ready') ? (data.artifact || status.artifact || {}) : {};
      if(artifact && Object.keys(artifact).length && applyMirroredArtifactToInlineImage(imgEl, artifact)){
        imgEl.dataset.mirrorPollActive = '';
        return;
      }
      if(data?.ready || status.ready || stateInfo.state === 'ready'){
        imgEl.dataset.mirrorReady = '1';
        imgEl.dataset.mirrorPollActive = '';
        clearInlineImageMirrorPending(imgEl);
        return;
      }
      if(stateInfo.state === 'failed_final'){
        imgEl.dataset.mirrorPollActive = '';
        imgEl.dataset.mirrorFinalFailed = '1';
        markInlineImageMirrorPending(imgEl, remoteImageJobStatusLabel(stateInfo));
        return;
      }
      if(stateInfo.state === 'failed_retryable'){
        markInlineImageMirrorPending(imgEl, remoteImageJobStatusLabel(stateInfo));
      }else if(['queued','fetching'].includes(stateInfo.state)){
        markInlineImageMirrorPending(imgEl, remoteImageJobStatusLabel(stateInfo));
      }
      const bytes = Number(status.bytes_downloaded || 0) || 0;
      const total = Number(status.content_length || 0) || 0;
      if(!alreadyVisible && bytes > 0 && total > 0){
        markInlineImageMirrorPending(imgEl, `图片拉取中 ${Math.min(99, Math.round(bytes * 100 / total))}%`);
      }
    }catch(_){ }
    const nextAttempt = Number(imgEl.dataset.mirrorPollAttempt || 0) || 0;
    if(nextAttempt >= IMAGE_MIRROR_POLL_MAX_ATTEMPTS || imgEl.dataset.mirrorReady === '1'){
      imgEl.dataset.mirrorPollActive = '';
      if(imgEl.dataset.mirrorReady !== '1') markInlineImageMirrorPending(imgEl, '图片仍在后台队列中，可稍后回来查看');
      return;
    }
    const fallbackDelay = Math.min(9000, IMAGE_MIRROR_POLL_BASE_DELAY_MS + nextAttempt * 650);
    const delay = serverRetryAfterMs > 0 ? Math.max(1400, Math.min(15000, serverRetryAfterMs)) : fallbackDelay;
    setTimeout(run, delay);
  };
  const delay0 = reason === 'slow' ? 0 : 350;
  setTimeout(run, delay0);
  return true;
}

function armInlineImageSlowMirrorFallback(imgEl){
  if(!imgEl || imgEl.dataset.slowMirrorFallbackArmed === '1') return;
  if(!imageMirrorCandidateUrlFromImg(imgEl)) return;
  imgEl.dataset.slowMirrorFallbackArmed = '1';
  setTimeout(()=>{
    if(!imgEl.isConnected || imgEl.dataset.mirrorReady === '1') return;
    if(imgEl.complete && (imgEl.naturalWidth || 0) > 0 && (imgEl.naturalHeight || 0) > 0) return;
    scheduleImageMirrorPoll(imgEl, 'slow');
  }, 4200);
}

function armInlineImageVisibleMirrorPersist(imgEl){
  if(!imgEl || imgEl.dataset.visibleMirrorPersistArmed === '1') return;
  if(!imageMirrorCandidateUrlFromImg(imgEl)) return;
  imgEl.dataset.visibleMirrorPersistArmed = '1';
  const run = () => {
    if(!imgEl.isConnected || imgEl.dataset.mirrorReady === '1') return;
    scheduleImageMirrorPoll(imgEl, 'visible');
  };
  if(inlineImageHasRenderableMirrorImage(imgEl)){
    setTimeout(run, 0);
  }else{
    imgEl.addEventListener('load', () => setTimeout(run, 0), { once:true });
  }
}

function imageReplySignature(payload){
  const items = normalizeImageItems(payload?.images);
  if(!items.length) return '';
  return items
    .map(item => String(item.model_storage_ref || item.storage_ref || item.file_library_id || item.library_file_id || item.rawUrl || item.raw_url || item.viewUrl || item.view_url || item.downloadUrl || item.download_url || item.previewUrl || item.preview_url || item.url || item.proxyUrl || item.image_id || item.attachment_id || '').trim())
    .filter(Boolean)
    .join('||');
}

function imageDomDedupeKey(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  try{
    const u = new URL(raw, window.location.origin);
    let path = String(u.pathname || '').replace(/\/+/g, '/');
    path = path.replace('/api3/generated-download/', '/api3/generated-files/');
    path = path.replace(/__preview(?=\.[a-z0-9]+$)/i, '');
    u.pathname = path;
    u.searchParams.delete('scope');
    u.searchParams.delete('__webai_img_retry');
    u.hash = '';
    return u.origin === window.location.origin ? (u.pathname + u.search) : u.toString();
  }catch(_){
    return raw.replace('/api3/generated-download/', '/api3/generated-files/').replace(/__preview(?=\.[a-z0-9]+($|\?))/i, '');
  }
}

function getBubbleImageSignature(root){
  if(!root) return '';
  const urls = Array.from(root.querySelectorAll('.inline-image-group img.inline-img, .inline-img-standalone img.inline-img, img.inline-img.inline-img-standalone')).map(img => {
    const src = String(img.dataset.rawSrc || img.dataset.originSrc || img.getAttribute('src') || img.src || '').trim();
    return imageDomDedupeKey(src);
  }).filter(Boolean);
  if(!urls.length) return '';
  return urls.join('||');
}

function removeDuplicateImageContainersInsideBubble(body){
  if(!body) return;
  const containers = Array.from(body.querySelectorAll(':scope > .image-generation-stage, :scope > .inline-image-group, :scope > .inline-img-standalone, :scope > .assistant-image-replies'));
  if(containers.length < 2) return;
  const seen = new Map();
  for(const node of containers){
    const sig = getBubbleImageSignature(node);
    if(!sig) continue;
    const prev = seen.get(sig);
    if(!prev){
      seen.set(sig, node);
      continue;
    }
    const prevIsStage = prev.classList?.contains('image-generation-stage');
    const curIsStage = node.classList?.contains('image-generation-stage');
    const removeNode = prevIsStage && !curIsStage ? prev : node;
    const keepNode = removeNode === prev ? node : prev;
    try{ removeNode.remove(); }catch(_){ }
    seen.set(sig, keepNode);
  }
}

function dedupeAdjacentAssistantImageBubbles(){
  const bubbles = Array.from(chatEl?.querySelectorAll('.bubble.a') || []);
  if(!bubbles.length) return;
  for(const bubble of bubbles){
    removeDuplicateImageContainersInsideBubble(bubble.querySelector('.bubble-body'));
  }
  for(let i = 1; i < bubbles.length; i++){
    const prev = bubbles[i - 1];
    const cur = bubbles[i];
    if(!prev || !cur || !prev.isConnected || !cur.isConnected) continue;
    const prevBody = prev.querySelector('.bubble-body');
    const curBody = cur.querySelector('.bubble-body');
    if(!prevBody || !curBody) continue;
    const prevSig = getBubbleImageSignature(prevBody);
    const curImageNodes = Array.from(curBody.querySelectorAll(':scope > .image-generation-stage, :scope > .inline-image-group, :scope > .inline-img-standalone, :scope > .assistant-image-replies'));
    if(!prevSig || !curImageNodes.length) continue;
    const firstImageSig = getBubbleImageSignature(curImageNodes[0]);
    if(!firstImageSig || firstImageSig !== prevSig) continue;
    curImageNodes[0].remove();
    const emptyParas = Array.from(curBody.querySelectorAll(':scope > p')).filter(p => !String(p.textContent || '').trim() && !p.querySelector('img,video,iframe,table,pre,blockquote,ul,ol'));
    emptyParas.forEach(p => p.remove());
    const hasMeaningful = Array.from(curBody.childNodes || []).some(node => {
      if(node.nodeType === Node.TEXT_NODE) return !!String(node.textContent || '').trim();
      if(node.nodeType !== Node.ELEMENT_NODE) return false;
      if(node.classList?.contains('inline-image-group')) return true;
      return !!String(node.textContent || '').trim() || !!node.querySelector?.('img,video,iframe,table,pre,blockquote,ul,ol');
    });
    if(!hasMeaningful){
      cur.remove();
      i--;
    }
  }
}


const IMAGE_MIRROR_ARTIFACT_CACHE_KEY = "webai_image_mirror_artifact_cache_v1";
const IMAGE_MIRROR_ARTIFACT_CACHE_MAX = 160;
const IMAGE_MIRROR_ARTIFACT_CACHE_TTL_MS = 30 * 24 * 3600 * 1000;
let _imageMirrorArtifactCacheMem = null;

function normalizeImageMirrorUrlKey(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  const nested = extractRemoteImageProxyOriginalUrl(raw);
  const u = nested || raw;
  try{
    const parsed = new URL(u, window.location.origin);
    if(parsed.origin === window.location.origin){
      return (parsed.pathname + parsed.search + parsed.hash).trim();
    }
    parsed.hash = '';
    return parsed.toString();
  }catch(_){
    return u;
  }
}

function extractRemoteImageProxyOriginalUrl(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  try{
    const parsed = new URL(raw, window.location.origin);
    const pathname = String(parsed.pathname || '').replace(/\/+$/g, '');
    if(/^\/api3\/(?:remote-image|image_proxy)$/i.test(pathname)){
      return String(parsed.searchParams.get('url') || '').trim();
    }
  }catch(_){ }
  return '';
}

function collectImageMirrorUrlKeysFromValue(value, out){
  const target = out || new Set();
  const primary = normalizeImageMirrorUrlKey(value);
  if(primary) target.add(primary);
  const nested = extractRemoteImageProxyOriginalUrl(value);
  const nestedKey = normalizeImageMirrorUrlKey(nested);
  if(nestedKey) target.add(nestedKey);
  return target;
}

function imageMirrorUrlKeysFromItem(item){
  const keys = new Set();
  if(!item || typeof item !== 'object') return keys;
  const fields = [
    item.provider_url, item.providerUrl,
    item.raw_url, item.rawUrl,
    item.view_url, item.viewUrl,
    item.download_url, item.downloadUrl,
    item.preview_url, item.previewUrl,
    item.proxy_url, item.proxyUrl,
    item.preview_proxy_url, item.previewProxyUrl,
    item.url, item.src,
    item.file_url, item.fileUrl,
    item.image_url && item.image_url.url,
    item.imageUrl && item.imageUrl.url,
  ];
  for(const v of fields) collectImageMirrorUrlKeysFromValue(v, keys);
  return keys;
}

function readImageMirrorArtifactCache(){
  if(_imageMirrorArtifactCacheMem && typeof _imageMirrorArtifactCacheMem === 'object') return _imageMirrorArtifactCacheMem;
  let cache = { items:{}, updated_at:0 };
  try{
    const raw = localStorage.getItem(IMAGE_MIRROR_ARTIFACT_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if(parsed && typeof parsed === 'object' && parsed.items && typeof parsed.items === 'object') cache = parsed;
  }catch(_){ }
  const nowTs = Date.now();
  const clean = {};
  for(const [key, rec] of Object.entries(cache.items || {})){
    if(!key || !rec || typeof rec !== 'object') continue;
    const ts = Number(rec.ts || rec.updated_at || 0) || 0;
    if(ts > 0 && nowTs - ts > IMAGE_MIRROR_ARTIFACT_CACHE_TTL_MS) continue;
    clean[key] = rec;
  }
  _imageMirrorArtifactCacheMem = { items: clean, updated_at: Number(cache.updated_at || 0) || 0 };
  return _imageMirrorArtifactCacheMem;
}

function writeImageMirrorArtifactCache(cache){
  const row = cache && typeof cache === 'object' ? cache : { items:{} };
  const items = row.items && typeof row.items === 'object' ? row.items : {};
  const entries = Object.entries(items)
    .filter(([, rec]) => rec && typeof rec === 'object')
    .sort((a, b) => (Number(b[1].ts || b[1].updated_at || 0) || 0) - (Number(a[1].ts || a[1].updated_at || 0) || 0))
    .slice(0, IMAGE_MIRROR_ARTIFACT_CACHE_MAX);
  const next = { items:Object.fromEntries(entries), updated_at:Date.now() };
  _imageMirrorArtifactCacheMem = next;
  try{ localStorage.setItem(IMAGE_MIRROR_ARTIFACT_CACHE_KEY, JSON.stringify(next)); }catch(_){ }
  return next;
}

function buildMirroredImagePersistPatch(artifact, providerUrl){
  const data = artifact && typeof artifact === 'object' ? artifact : {};
  const provider = String(providerUrl || data.provider_url || data.providerUrl || data.raw_url || data.rawUrl || '').trim();
  const preview = String(data.preview_url || data.previewUrl || data.view_url || data.viewUrl || data.url || '').trim();
  const view = String(data.view_url || data.viewUrl || data.raw_url || data.rawUrl || data.download_url || data.downloadUrl || preview).trim();
  const download = String(data.download_url || data.downloadUrl || view || preview).trim();
  const stableUrl = preview || view || download;
  if(!stableUrl) return null;
  const patch = {
    url: stableUrl,
    raw_url: view || download || stableUrl,
    rawUrl: view || download || stableUrl,
    view_url: view || stableUrl,
    viewUrl: view || stableUrl,
    download_url: download || view || stableUrl,
    downloadUrl: download || view || stableUrl,
    preview_url: preview || stableUrl,
    previewUrl: preview || stableUrl,
    proxy_url: '',
    proxyUrl: '',
    preview_proxy_url: '',
    previewProxyUrl: '',
    provider_url: provider,
    providerUrl: provider,
    mirror_status: 'ready',
    mirrorStatus: 'ready',
    delivery_mode: String(data.delivery_mode || data.deliveryMode || 'mirrored_local').trim() || 'mirrored_local',
    deliveryMode: String(data.delivery_mode || data.deliveryMode || 'mirrored_local').trim() || 'mirrored_local',
    is_temporary_remote: false,
    isTemporaryRemote: false,
    source_type: String(data.source_type || data.sourceType || 'generated').trim() || 'generated',
    sourceType: String(data.source_type || data.sourceType || 'generated').trim() || 'generated',
    generated_by_assistant: data.generated_by_assistant !== false,
    generatedByAssistant: data.generated_by_assistant !== false,
  };
  for(const key of ['filename','mime','size','attachment_id','attachmentId','image_seq','imageSeq','seq','parent_image_id','parentImageId','created_at_ms','createdAtMs','operation']){
    const value = data[key];
    if(value !== undefined && value !== null && String(value).trim() !== '') patch[key] = value;
  }
  const patchSourceImageIds = normalizeImageReplySourceIds(data, {});
  if(patchSourceImageIds.length){
    patch.source_image_ids = patchSourceImageIds;
    patch.sourceImageIds = patchSourceImageIds;
    patch.derived_from = patchSourceImageIds;
    patch.derivedFrom = patchSourceImageIds;
  }
  if(String(data.storage_backend || data.storageBackend || '').trim()){
    patch.storage_backend = String(data.storage_backend || data.storageBackend || '').trim();
    patch.storageBackend = patch.storage_backend;
  }else{
    patch.storage_backend = 'generated_local';
    patch.storageBackend = 'generated_local';
  }
  return patch;
}

function rememberMirroredImageArtifact(providerUrl, artifact){
  const provider = String(providerUrl || '').trim();
  const patch = buildMirroredImagePersistPatch(artifact, provider);
  if(!patch || !provider) return null;
  const keys = new Set();
  collectImageMirrorUrlKeysFromValue(provider, keys);
  for(const k of imageMirrorUrlKeysFromItem(patch)) keys.add(k);
  if(!keys.size) return patch;
  const cache = readImageMirrorArtifactCache();
  const rec = { ts:Date.now(), provider_url:provider, artifact:patch };
  for(const key of keys){
    if(key) cache.items[key] = rec;
  }
  writeImageMirrorArtifactCache(cache);
  return patch;
}

function findCachedMirroredArtifactForImageItem(item){
  const cache = readImageMirrorArtifactCache();
  const keys = imageMirrorUrlKeysFromItem(item);
  for(const key of keys){
    const rec = cache.items?.[key];
    const artifact = rec && typeof rec === 'object' ? rec.artifact : null;
    if(artifact && typeof artifact === 'object') return artifact;
  }
  return null;
}

function applyImagePersistPatchToItem(item, patch){
  if(!item || typeof item !== 'object' || !patch || typeof patch !== 'object') return false;
  let changed = false;
  const setValue = (key, value, allowEmpty=false)=>{
    if(value === undefined || value === null) return;
    if(!allowEmpty && typeof value === 'string' && !value.trim()) return;
    if(item[key] !== value){ item[key] = value; changed = true; }
  };
  for(const [key, value] of Object.entries(patch)){
    const allowEmpty = ['proxy_url','proxyUrl','preview_proxy_url','previewProxyUrl'].includes(key);
    setValue(key, value, allowEmpty);
  }
  return changed;
}

function applyMirroredImageCacheToImageItem(item){
  if(!item || typeof item !== 'object') return item;
  const cached = findCachedMirroredArtifactForImageItem(item);
  if(!cached) return item;
  const cloned = { ...item };
  applyImagePersistPatchToItem(cloned, cached);
  return cloned;
}

function applyMirroredImageCacheToImageReplyPayload(payload){
  if(!payload || typeof payload !== 'object') return payload;
  let changed = false;
  const cloned = { ...payload };
  if(Array.isArray(cloned.images)){
    cloned.images = cloned.images.map(item => {
      if(!item || typeof item !== 'object') return item;
      const next = applyMirroredImageCacheToImageItem(item);
      if(next !== item) changed = true;
      return next;
    });
  }
  const rootNext = applyMirroredImageCacheToImageItem(cloned);
  if(rootNext !== cloned) changed = true;
  return changed ? rootNext : payload;
}

function itemMatchesImageMirrorKeys(item, keys){
  if(!item || typeof item !== 'object' || !keys || !keys.size) return false;
  for(const key of imageMirrorUrlKeysFromItem(item)){
    if(keys.has(key)) return true;
  }
  return false;
}

function patchMirroredImageObjectTree(root, keys, patch, seen){
  if(!root || typeof root !== 'object') return false;
  const visited = seen || new WeakSet();
  if(visited.has(root)) return false;
  visited.add(root);
  let changed = false;
  if(itemMatchesImageMirrorKeys(root, keys)){
    changed = applyImagePersistPatchToItem(root, patch) || changed;
  }
  if(Array.isArray(root)){
    for(const item of root){
      if(item && typeof item === 'object') changed = patchMirroredImageObjectTree(item, keys, patch, visited) || changed;
    }
    return changed;
  }
  for(const value of Object.values(root)){
    if(value && typeof value === 'object') changed = patchMirroredImageObjectTree(value, keys, patch, visited) || changed;
  }
  return changed;
}

function persistMirroredImageArtifactForCurrentStore(providerUrl, artifact){
  const provider = String(providerUrl || '').trim();
  const patch = rememberMirroredImageArtifact(provider, artifact);
  if(!patch) return false;
  const keys = new Set();
  collectImageMirrorUrlKeysFromValue(provider, keys);
  for(const key of imageMirrorUrlKeysFromItem(patch)) keys.add(key);
  if(!keys.size) return false;
  let changed = false;
  try{
    for(const s of Object.values(store?.sessions || {})){
      if(!s || typeof s !== 'object') continue;
      if(patchMirroredImageObjectTree(s.messages || [], keys, patch)) changed = true;
      if(patchMirroredImageObjectTree(s.imageReplies || [], keys, patch)) changed = true;
      if(patchMirroredImageObjectTree(s.image_replies || [], keys, patch)) changed = true;
    }
  }catch(_){ }
  try{
    for(const [sid, rt] of Object.entries(sessionRuntime || {})){
      if(!rt || typeof rt !== 'object') continue;
      if(patchMirroredImageObjectTree(rt.draftImageReplies || [], keys, patch)){
        changed = true;
        try{ _scheduleSessionRuntimePendingSnapshot(sid, { immediate:true }); }catch(_){ }
      }
    }
  }catch(_){ }
  if(changed){
    try{ saveStoreThrottled(); }catch(_){ }
  }
  return changed;
}

function normalizeImageItems(images){
  return (Array.isArray(images) ? images : [])
    .map((item, index) => {
      if(typeof item === "string"){
        const url = item.trim();
        const displayUrl = composerLibraryBrowserImageSource(url) || url;
        const proxyUrl = buildRemoteImageProxyUrl(displayUrl);
        const createdAtMs = Date.now();
        return { url: proxyUrl || displayUrl, rawUrl:displayUrl, proxyUrl, viewUrl:displayUrl, previewUrl:proxyUrl || displayUrl, downloadUrl:composerLibraryBrowserFileSource(url, 'download') || displayUrl, filename:"", alt:"", caption:"", created_at_ms:createdAtMs, createdAtMs, image_seq:index + 1, seq:index + 1, source_role:'assistant', source_type:'generated', operation:'generate' };
      }
      if(item && typeof item === "object"){
        const initialSourceType = String(item.source_type || item.sourceType || 'generated').trim() || 'generated';
        const initialOperationRaw = String(item.operation || item.intent || item.visual_intent || item.visualIntent || item.task_mode || '').trim().toLowerCase();
        const initialSearchImage = isImageSearchSourceType(initialSourceType) || initialOperationRaw === 'image_search' || initialOperationRaw === 'visual_image_search' || initialOperationRaw === 'web_image_search';
        const sourceItem = initialSearchImage ? item : applyMirroredImageCacheToImageItem(item);
        const sourceType = String(sourceItem.source_type || sourceItem.sourceType || 'generated').trim() || 'generated';
        const operationRaw = String(sourceItem.operation || sourceItem.intent || sourceItem.visual_intent || sourceItem.visualIntent || sourceItem.task_mode || '').trim().toLowerCase();
        const searchImage = isImageSearchSourceType(sourceType) || operationRaw === 'image_search' || operationRaw === 'visual_image_search' || operationRaw === 'web_image_search';
        const providerUrl = String(sourceItem.provider_url || sourceItem.providerUrl || '').trim();
        const temporaryRemote = !!sourceItem.is_temporary_remote || String(sourceItem.delivery_mode || sourceItem.deliveryMode || '').trim() === 'provider_url_first';
        const previewUrl = String(sourceItem.preview_url || sourceItem.previewUrl || '').trim();
        const imageObjectUrl = (sourceItem.image_url && typeof sourceItem.image_url === 'object') ? String(sourceItem.image_url.url || '').trim() : String(sourceItem.image_url || sourceItem.imageUrl || '').trim();
        const stableDisplayUrl = composerLibraryDisplayImageUrl(sourceItem);
        const idDownloadUrl = composerLibraryIdBrowserSource(sourceItem, 'download');
        const rawUrl = String(sourceItem.raw_url || sourceItem.rawUrl || imageObjectUrl || sourceItem.view_url || sourceItem.viewUrl || sourceItem.download_url || sourceItem.downloadUrl || sourceItem.url || sourceItem.src || sourceItem.model_storage_ref || sourceItem.storage_ref || providerUrl || "").trim();
        const explicitProxyUrl = String(sourceItem.proxy_url || sourceItem.proxyUrl || sourceItem.preview_proxy_url || sourceItem.previewProxyUrl || "").trim();
        const proxyBase = rawUrl || previewUrl || providerUrl;
        const generatedRemote = !searchImage && sourceType === 'generated' && /^https?:\/\//i.test(proxyBase) && (temporaryRemote || providerUrl || String(sourceItem.storage_backend || '').trim() === 'provider_url');
        const proxyUrl = explicitProxyUrl || (searchImage ? '' : (generatedRemote ? buildRemoteImageProxyUrl(proxyBase) : (shouldBypassRemoteImageProxy(previewUrl || rawUrl) ? '' : buildRemoteImageProxyUrl(previewUrl || rawUrl))));
        const useMirrorPlaceholder = !searchImage && generatedRemote && temporaryRemote && /^https?:\/\//i.test(providerUrl || rawUrl || proxyBase);
        const previewCandidateUrl = composerLibraryBrowserImageSource(previewUrl);
        const rawCandidateUrl = composerLibraryBrowserImageSource(rawUrl);
        const previewIsEphemeral = composerLibraryIsEphemeralImageSource(previewCandidateUrl || previewUrl);
        const rawIsEphemeral = composerLibraryIsEphemeralImageSource(rawCandidateUrl || rawUrl);
        const storageDisplayUrl = composerLibraryBrowserImageSource(sourceItem.model_storage_ref) || composerLibraryBrowserImageSource(sourceItem.storage_ref) || composerLibraryBrowserImageSource(sourceItem.file_registry?.model_storage_ref) || composerLibraryBrowserImageSource(sourceItem.file_registry?.storage_ref);
        const previewDisplayUrl = stableDisplayUrl || (!previewIsEphemeral ? previewCandidateUrl : '') || (!rawIsEphemeral ? rawCandidateUrl : '') || storageDisplayUrl || previewCandidateUrl || rawCandidateUrl;
        const rawDisplayUrl = (!rawIsEphemeral ? rawCandidateUrl : '') || stableDisplayUrl || storageDisplayUrl || previewDisplayUrl || rawCandidateUrl;
        const url = searchImage ? (rawDisplayUrl || previewDisplayUrl || proxyUrl || String(sourceItem.url || sourceItem.src || "").trim()) : (useMirrorPlaceholder ? IMAGE_REMOTE_PLACEHOLDER_URL : (previewDisplayUrl || proxyUrl || rawDisplayUrl || String(sourceItem.url || sourceItem.src || "").trim()));
        const createdAtMs = Number(sourceItem.created_at_ms || sourceItem.createdAtMs || sourceItem._created_at_ms || sourceItem.created_at || sourceItem.createdAt || 0) || Date.now();
        const imageSeq = Number(sourceItem.image_seq || sourceItem.seq || sourceItem.order_seq || index + 1) || (index + 1);
        const sourceImageIds = normalizeImageReplySourceIds(sourceItem, item);
        return {
          url,
          rawUrl: rawDisplayUrl || rawUrl || providerUrl || url,
          proxyUrl,
          previewUrl: previewDisplayUrl || previewUrl || proxyUrl,
          viewUrl: composerLibraryBrowserImageSource(sourceItem.view_url || sourceItem.viewUrl) || previewDisplayUrl || rawDisplayUrl || '',
          downloadUrl: composerLibraryBrowserFileSource(sourceItem.download_url || sourceItem.downloadUrl || idDownloadUrl || sourceItem.view_url || sourceItem.viewUrl || sourceItem.model_storage_ref || sourceItem.storage_ref || rawUrl, 'download') || idDownloadUrl || rawDisplayUrl || previewDisplayUrl || '',
          raw_url: rawDisplayUrl || rawUrl || providerUrl || url,
          preview_url: previewDisplayUrl || previewUrl || proxyUrl,
          view_url: composerLibraryBrowserImageSource(sourceItem.view_url || sourceItem.viewUrl) || previewDisplayUrl || rawDisplayUrl || '',
          download_url: composerLibraryBrowserFileSource(sourceItem.download_url || sourceItem.downloadUrl || idDownloadUrl || sourceItem.view_url || sourceItem.viewUrl || sourceItem.model_storage_ref || sourceItem.storage_ref || rawUrl, 'download') || idDownloadUrl || rawDisplayUrl || previewDisplayUrl || '',
          storage_ref: String(sourceItem.storage_ref || sourceItem.model_storage_ref || sourceItem.file_registry?.storage_ref || sourceItem.file_registry?.model_storage_ref || '').trim(),
          model_storage_ref: String(sourceItem.model_storage_ref || sourceItem.storage_ref || sourceItem.file_registry?.model_storage_ref || sourceItem.file_registry?.storage_ref || '').trim(),
          file_library_id: String(sourceItem.file_library_id || sourceItem.library_file_id || sourceItem.file_registry?.file_id || '').trim(),
          library_file_id: String(sourceItem.library_file_id || sourceItem.file_library_id || sourceItem.file_registry?.file_id || '').trim(),
          file_registry: sourceItem.file_registry && typeof sourceItem.file_registry === 'object' ? sourceItem.file_registry : null,
          persisted_url: String(sourceItem.persisted_url || sourceItem.persistedUrl || '').trim(),
          server_url: String(sourceItem.server_url || sourceItem.serverUrl || '').trim(),
          _source_url: String(sourceItem._source_url || sourceItem.source_url || sourceItem.sourceUrl || '').trim(),
          _preview_url: String(sourceItem._preview_url || sourceItem.preview_url || sourceItem.previewUrl || '').trim(),
          image_url: sourceItem.image_url && typeof sourceItem.image_url === 'object' ? { ...sourceItem.image_url } : (sourceItem.image_url ? { url:String(sourceItem.image_url || '').trim() } : undefined),
          providerUrl,
          storage_backend: String(sourceItem.storage_backend || sourceItem.storageBackend || '').trim(),
          delivery_mode: String(sourceItem.delivery_mode || sourceItem.deliveryMode || '').trim(),
          mirror_status: String(sourceItem.mirror_status || sourceItem.mirrorStatus || '').trim(),
          mirrorStatus: String(sourceItem.mirror_status || sourceItem.mirrorStatus || '').trim(),
          content_length: Number(sourceItem.content_length || sourceItem.contentLength || 0) || 0,
          first_byte_ms: Number(sourceItem.first_byte_ms || sourceItem.firstByteMs || 0) || 0,
          download_ms: Number(sourceItem.download_ms || sourceItem.downloadMs || sourceItem.elapsed_ms || sourceItem.elapsedMs || 0) || 0,
          bytes_per_sec: Number(sourceItem.bytes_per_sec || sourceItem.bytesPerSec || 0) || 0,
          is_temporary_remote: temporaryRemote,
          mirror_placeholder: useMirrorPlaceholder,
          filename: String(sourceItem.filename || sourceItem.name || '').trim(),
          alt: String(sourceItem.alt || sourceItem.title || sourceItem.caption || "").trim(),
          caption: String(sourceItem.caption || sourceItem.title || sourceItem.alt || "").trim(),
          attachment_id: String(sourceItem.attachment_id || sourceItem.id || sourceItem.image_id || '').trim(),
          image_id: String(sourceItem.image_id || sourceItem.imageId || sourceItem.attachment_id || sourceItem.id || '').trim(),
          endpoint_mode: normalizeApiEndpointMode(sourceItem.endpoint_mode || sourceItem.api_endpoint_mode || sourceItem.apiEndpointMode || sourceItem.endpointMode || ''),
          api_endpoint_mode: normalizeApiEndpointMode(sourceItem.api_endpoint_mode || sourceItem.endpoint_mode || sourceItem.apiEndpointMode || sourceItem.endpointMode || ''),
          source_role: String(sourceItem.source_role || sourceItem.role || 'assistant').trim() || 'assistant',
          source_type: searchImage ? 'image_search' : sourceType,
          operation: searchImage ? 'image_search' : (String(sourceItem.operation || sourceItem.task_mode || 'generate').trim() || 'generate'),
          disable_mirror: searchImage,
          created_at_ms: createdAtMs,
          createdAtMs: createdAtMs,
          image_seq: imageSeq,
          seq: imageSeq,
          parent_image_id: String(sourceItem.parent_image_id || sourceItem.parentImageId || '').trim(),
          source_image_ids: sourceImageIds,
          sourceImageIds: sourceImageIds,
          derived_from: sourceImageIds,
          derivedFrom: sourceImageIds,
          ocr_text_hint: String(sourceItem.ocr_text_hint || sourceItem.ocrTextHint || sourceItem._ocr_text || sourceItem.text || '').trim(),
          ocr_source: String(sourceItem.ocr_source || sourceItem.ocrSource || '').trim(),
        };
      }
      return { url:"", rawUrl:"", proxyUrl:"", previewUrl:"", viewUrl:"", downloadUrl:"", filename:"", alt:"", caption:"" };
    })
    .filter(item => item.url);
}

function imageItemDisplayUrl(item){
  if(!item || typeof item !== 'object') return '';
  const stable = composerLibraryDisplayImageUrl(item);
  if(stable) return stable;
  const candidates = [item.previewUrl, item.preview_url, item.url, item.src, item.viewUrl, item.view_url, item.rawUrl, item.raw_url, item.model_storage_ref, item.storage_ref];
  for(const value of candidates){
    const display = composerLibraryBrowserImageSource(value);
    if(display) return display;
  }
  return String(candidates.find(v => String(v || '').trim()) || '').trim();
}

function imageItemOpenUrl(item){
  if(!item || typeof item !== 'object') return '';
  const stable = composerLibraryDisplayImageUrl(item);
  if(stable) return stable;
  const candidates = [item.rawUrl, item.raw_url, item.viewUrl, item.view_url, item.downloadUrl, item.download_url, item.url, item.src, item.model_storage_ref, item.storage_ref];
  for(const value of candidates){
    const display = composerLibraryBrowserImageSource(value);
    if(display) return display;
  }
  return String(candidates.find(v => String(v || '').trim()) || '').trim();
}

function resolveImageReplyDownloadUrl(item){
  if(!item || typeof item !== 'object') return '';
  const explicit = composerLibraryBrowserFileSource(item.downloadUrl || item.download_url, 'download') || String(item.downloadUrl || item.download_url || '').trim();
  if(explicit) return explicit;
  const candidate = composerLibraryBrowserFileSource(item.viewUrl || item.view_url || item.rawUrl || item.raw_url || item.url || item.src || item.model_storage_ref || item.storage_ref, 'download') || String(item.viewUrl || item.view_url || item.rawUrl || item.raw_url || item.url || item.src || '').trim();
  if(!candidate) return '';
  const replacePathOnly = (value)=>{
    const v = String(value || '').trim();
    if(!v) return '';
    if(/^\/api3\/generated-files\//i.test(v)) return v.replace(/^\/api3\/generated-files\//i, '/api3/generated-download/');
    if(/^\/api3\/uploads\//i.test(v)) return v.replace(/^\/api3\/uploads\//i, '/api3/download/');
    return v;
  };
  try{
    const parsed = new URL(candidate, window.location.origin);
    if(parsed.origin === window.location.origin){
      parsed.pathname = replacePathOnly(parsed.pathname);
      return parsed.pathname + parsed.search + parsed.hash;
    }
    return candidate;
  }catch(_){ }
  return replacePathOnly(candidate);
}

function buildImageReplyActions(images){
  return null;
}

function isImageSearchReplyPayload(payload){
  const data = payload && typeof payload === 'object' ? payload : {};
  const source = String(data.source || data.kind || data.intent || data.visual_intent || '').trim().toLowerCase();
  if(source === 'image_search' || source === 'visual_image_search' || source === 'web_image_search') return true;
  const images = Array.isArray(data.images) ? data.images : [];
  return images.some(item => {
    if(!item || typeof item !== 'object') return false;
    const t = String(item.source_type || item.sourceType || item.type || '').trim().toLowerCase();
    return t === 'image_search' || t === 'web_image' || t === 'visual_image_search';
  });
}

function normalizeImageReplyImagesForPayload(payload){
  const data = payload && typeof payload === 'object' ? payload : {};
  const images = Array.isArray(data.images) ? data.images : [];
  const isSearch = isImageSearchReplyPayload(data);
  const prepared = isSearch
    ? images.map(item => {
        if(item && typeof item === 'object'){
          return {
            ...item,
            source_type: 'image_search',
            sourceType: 'image_search',
            operation: 'image_search',
            intent: item.intent || 'image_search',
          };
        }
        return item;
      })
    : images;
  return normalizeImageItems(prepared).map(item => isSearch ? {
    ...item,
    source_type: 'image_search',
    sourceType: 'image_search',
    operation: 'image_search',
  } : item);
}

function getAssistantMessageImageReplies(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  const rows = [];
  if(Array.isArray(m.imageReplies)) rows.push(...m.imageReplies);
  if(Array.isArray(m.image_replies)) rows.push(...m.image_replies);
  const content = m.content;
  if(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply'){
    rows.push(content);
  }
  // 不只渲染搜图结果。生成图/改图结果也可能在恢复会话、后台任务完成、
  // 或旧快照里以 message.imageReplies 的形式保存；过滤掉它们会造成空白助手气泡。
  return _normalizePendingAssistantImageReplies(rows);
}

function buildAssistantImageRepliesNode(payloads){
  const replies = _normalizePendingAssistantImageReplies(payloads || []);
  const images = [];
  for(const reply of replies){
    const isSearchReply = isImageSearchReplyPayload(reply);
    for(const item of normalizeImageReplyImagesForPayload(reply)){
      images.push(isSearchReply ? { ...item, source_type: 'image_search', sourceType: 'image_search', operation:'image_search' } : item);
    }
  }
  if(!images.length) return null;
  const wrap = document.createElement('div');
  wrap.className = 'assistant-image-replies';
  wrap.dataset.imageReplySignature = replies.map(item => imageReplySignature(item)).filter(Boolean).join('||');
  if(images.length === 1){
    appendImageGroup(wrap, images);
  }else{
    const group = buildInlineImageGroup(images);
    if(group) wrap.appendChild(group);
  }
  return wrap.childElementCount ? wrap : null;
}

function syncAssistantImageRepliesInBody(body, payloads){
  if(!body) return null;
  const existing = body.querySelector(':scope > .assistant-image-replies');
  const node = buildAssistantImageRepliesNode(payloads);
  if(!node){
    if(existing) existing.remove();
    return null;
  }
  if(existing && existing.dataset.imageReplySignature === node.dataset.imageReplySignature){
    return existing;
  }
  if(existing){
    existing.replaceWith(node);
  }else{
    const reasoningNode = body.querySelector(':scope > .reasoning-panels, :scope > .reasoning-panel');
    const answerNode = body.querySelector(':scope > .reasoning-answer-wrap');
    if(reasoningNode && reasoningNode.parentNode === body) body.insertBefore(node, reasoningNode.nextSibling || null);
    else if(answerNode && answerNode.parentNode === body) body.insertBefore(node, answerNode);
    else body.insertBefore(node, body.firstChild || null);
  }
  bindBubbleEnhancements(body.closest('.bubble') || body);
  return node;
}

function markInlineImageFailed(imgEl){
  if(!imgEl) return;
  if(imageMirrorCandidateUrlFromImg(imgEl)){
    markInlineImageMirrorPending(imgEl, '图片暂时没加载出来，正在尝试拉回');
    return;
  }
  const cell = imgEl.closest('.inline-image-cell') || imgEl.closest('.inline-img-standalone');
  if(!cell) return;
  cell.classList.remove('mirror-pending');
  cell.classList.add('load-failed');
  let fallback = cell.querySelector('.inline-image-fallback');
  if(!fallback){
    fallback = document.createElement('div');
    fallback.className = 'inline-image-fallback';
    fallback.innerHTML = `<div class="icon">🖼️</div><div>${escapeHtml(messageMediaT('message.image_unavailable_retry', null, 'The image is temporarily unavailable. Apervia will retry automatically.'))}</div>`;
    cell.appendChild(fallback);
  }
}

function clearInlineImageFailedState(imgEl){
  if(!imgEl) return;
  const cell = imgEl.closest('.inline-image-cell') || imgEl.closest('.inline-img-standalone');
  if(!cell) return;
  cell.classList.remove('load-failed');
  cell.classList.remove('mirror-pending');
  cell.querySelector('.inline-image-fallback')?.remove();
}

function imageItemPrimaryUrl(item){
  if(!item || typeof item !== 'object') return '';
  return imageItemDisplayUrl(item);
}

function imageItemProxyUrl(item){
  if(!item || typeof item !== 'object') return '';
  const explicitProxyUrl = String(item.proxyUrl || item.proxy_url || item.previewProxyUrl || item.preview_proxy_url || '').trim();
  if(explicitProxyUrl) return explicitProxyUrl;
  const rawUrl = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
  if(!rawUrl || !/^https?:\/\//i.test(rawUrl)) return '';
  if(preferInlineDirectImageSource(item)) return explicitProxyUrl || '';
  const generatedRemote = String(item.source_type || item.sourceType || '').trim() === 'generated' || String(item.providerUrl || item.provider_url || '').trim();
  if(generatedRemote) return buildRemoteImageProxyUrl(rawUrl);
  return shouldBypassRemoteImageProxy(rawUrl) ? '' : buildRemoteImageProxyUrl(rawUrl);
}

function isImageSearchSourceType(value){
  const t = String(value || '').trim().toLowerCase();
  return t === 'image_search' || t === 'web_image' || t === 'visual_image_search';
}

function preferInlineDirectImageSource(item){
  if(!item || typeof item !== 'object') return false;
  if(isImageSearchSourceType(item.source_type || item.sourceType || item.type || '')) return true;
  const operation = String(item.operation || item.intent || item.visual_intent || '').trim().toLowerCase();
  return operation === 'image_search' || operation === 'visual_image_search' || operation === 'web_image_search';
}

function normalizeGalleryItemsForDataset(images){
  return normalizeImageItems(images).map(item => ({
    src: imageItemOpenUrl(item) || imageItemDisplayUrl(item),
    rawUrl: imageItemOpenUrl(item) || imageItemDisplayUrl(item),
    proxyUrl: imageItemProxyUrl(item),
    alt: String(item.alt || '').trim(),
    caption: String(item.caption || '').trim(),
  })).filter(item => item.src);
}

function syncInlineImageGroupState(group){
  if(!group) return;
  const imgs = Array.from(group.querySelectorAll('img.inline-img'));
  const galleryItems = imgs.map((img, idx) => {
    img.dataset.galleryIndex = String(idx);
    return {
      src: String(img.dataset.rawSrc || img.dataset.originSrc || img.getAttribute('src') || img.src || '').trim(),
      rawUrl: String(img.dataset.rawSrc || img.dataset.originSrc || img.getAttribute('src') || img.src || '').trim(),
      proxyUrl: String(img.dataset.proxySrc || '').trim(),
      alt: String(img.getAttribute('alt') || '').trim(),
      caption: String(img.dataset.caption || '').trim(),
    };
  }).filter(item => item.src);
  group.dataset.galleryItems = JSON.stringify(galleryItems);
  group.dataset.imageCount = String(galleryItems.length);
  group.dataset.totalCount = String(galleryItems.length);
  group.querySelectorAll('.inline-image-cell').forEach(cell => cell.classList.remove('has-more'));
  group.querySelectorAll('.inline-image-more').forEach(node => node.remove());
  if(!galleryItems.length){
    group.remove();
    return;
  }
  const cols = galleryItems.length <= 1 ? 1 : galleryItems.length === 2 ? 2 : 3;
  group.className = `inline-image-group cols-${cols}`;
}

function removeBrokenInlineImage(imgEl){
  if(!imgEl) return;
  markInlineImageFailed(imgEl);
  const cell = imgEl.closest('.inline-image-cell');
  if(cell) cell.dataset.loadState = 'failed';
}

function addImageRetryCacheBuster(src, attempt){
  const raw = String(src || '').trim();
  if(!raw || raw.startsWith('data:') || raw.startsWith('blob:')) return raw;
  try{
    const u = new URL(raw, window.location.origin);
    u.searchParams.set('__webai_img_retry', String(attempt || Date.now()));
    if(u.origin === window.location.origin) return u.pathname + u.search + u.hash;
    return u.href;
  }catch(_){
    const sep = raw.includes('?') ? '&' : '?';
    return raw + sep + '__webai_img_retry=' + encodeURIComponent(String(attempt || Date.now()));
  }
}

function retryInlineImageSoft(imgEl, reason=''){
  if(!imgEl || isNavigatorOffline()) return false;
  const attempt = Number(imgEl.dataset.loadRetryAttempt || 0) || 0;
  if(attempt >= 4) return false;
  const proxySrc = String(imgEl.dataset.proxySrc || '').trim();
  const rawSrc = String(imgEl.dataset.rawSrc || imgEl.dataset.originSrc || '').trim();
  const currentSrc = String(imgEl.getAttribute('src') || imgEl.src || '').trim();
  const candidates = [];
  for(const u of [proxySrc, rawSrc, currentSrc]){
    const v = String(u || '').trim();
    if(v && v !== IMAGE_REMOTE_PLACEHOLDER_URL && !candidates.includes(v)) candidates.push(v);
  }
  if(!candidates.length) return false;
  const next = candidates[Math.min(attempt, candidates.length - 1)] || candidates[0];
  imgEl.dataset.loadRetryAttempt = String(attempt + 1);
  markInlineImageMirrorPending(imgEl, inlineImageMirrorDisabled(imgEl) ? (attempt <= 1 ? '图片加载较慢，正在重试' : '图片仍在加载，继续重试') : (attempt <= 1 ? '图片加载较慢，正在重试' : '图片仍在加载，后台继续重试'));
  setTimeout(()=>{
    if(!imgEl.isConnected || imgEl.dataset.mirrorReady === '1') return;
    try{
      imgEl.dataset.srcStage = proxySrc && next === proxySrc ? 'proxy-retry' : 'retry';
      imgEl.src = addImageRetryCacheBuster(next, attempt + 1);
    }catch(_){ }
  }, Math.min(6000, 700 + attempt * 900 + stableJitterMs(500)));
  return true;
}

function retryPendingInlineImages(reason=''){
  try{
    const imgs = Array.from(document.querySelectorAll('img.inline-img'));
    for(const img of imgs){
      if(!img || !img.isConnected) continue;
      if(img.dataset.mirrorReady === '1') continue;
      const cell = img.closest('.inline-image-cell') || img.closest('.inline-img-standalone');
      const needsRetry = cell?.classList?.contains('load-failed') || cell?.classList?.contains('mirror-pending') || !(img.complete && (img.naturalWidth || 0) > 0 && (img.naturalHeight || 0) > 0);
      if(!needsRetry) continue;
      if(scheduleImageMirrorPoll(img, reason || 'foreground')) continue;
      retryInlineImageSoft(img, reason || 'foreground');
    }
  }catch(_){ }
}

function probeImageCandidate(item){
  const rawSrc = imageItemPrimaryUrl(item);
  const proxySrc = imageItemProxyUrl(item);
  const tryLoad = (src) => new Promise(resolve => {
    const u = String(src || '').trim();
    if(!u) return resolve(false);
    const probe = new Image();
    let done = false;
    const finish = (ok)=>{
      if(done) return;
      done = true;
      probe.onload = null;
      probe.onerror = null;
      resolve(ok);
    };
    const timer = setTimeout(()=>finish(false), computeWeakFetchTimeoutMs('image_probe'));
    probe.onload = ()=>{
      clearTimeout(timer);
      finish((probe.naturalWidth || 0) > 0 && (probe.naturalHeight || 0) > 0);
    };
    probe.onerror = ()=>{
      clearTimeout(timer);
      finish(false);
    };
    probe.decoding = 'async';
    probe.referrerPolicy = 'no-referrer';
    probe.src = u;
  });
  return (async ()=>{
    if(proxySrc) return await tryLoad(proxySrc);
    if(rawSrc) return await tryLoad(rawSrc);
    return false;
  })();
}

async function filterLoadableImageItems(images){
  const normalized = normalizeImageItems(images);
  if(!normalized.length) return [];
  const checks = await Promise.all(normalized.map(async item => ({ item, ok: await probeImageCandidate(item) })));
  return checks.filter(entry => entry.ok).map(entry => entry.item);
}

function attachInlineImageErrorHandler(imgEl){
  if(!imgEl || imgEl.dataset.boundImgError === '1') return;
  imgEl.dataset.boundImgError = '1';
  imgEl.addEventListener('error', async (ev)=>{
    try{ ev?.stopImmediatePropagation?.(); }catch(_){ }
    const proxySrc = String(imgEl.dataset.proxySrc || '').trim();
    const currentSrc = String(imgEl.getAttribute('src') || imgEl.src || '').trim();
    if(imgEl.dataset.srcStage === 'direct' && proxySrc && currentSrc !== proxySrc){
      if(inlineImageMirrorDisabled(imgEl)){
        imgEl.dataset.srcStage = 'proxy-retry';
        clearInlineImageMirrorPending(imgEl);
        imgEl.src = proxySrc;
        return;
      }
      imgEl.dataset.srcStage = 'proxy-pending';
      const rawSrc = String(imgEl.dataset.rawSrc || imgEl.dataset.originSrc || '').trim();
      if(rawSrc && /^https?:\/\//i.test(rawSrc)) imgEl.dataset.providerSrc = rawSrc;
      markInlineImageMirrorPending(imgEl, '图片加载较慢，后台正在拉回');
      if(scheduleImageMirrorPoll(imgEl, 'direct-error')) return;
      imgEl.src = proxySrc;
      armInlineImageSlowMirrorFallback(imgEl);
      return;
    }
    if(scheduleImageMirrorPoll(imgEl, 'error')) return;
    if(retryInlineImageSoft(imgEl, 'error')) return;
    removeBrokenInlineImage(imgEl);
  });
  imgEl.addEventListener('load', ()=>{
    const loadedSrc = String(imgEl.getAttribute('src') || imgEl.currentSrc || imgEl.src || '').trim();
    if(loadedSrc === IMAGE_REMOTE_PLACEHOLDER_URL || imgEl.dataset.srcStage === 'proxy-pending'){
      markInlineImageMirrorPending(imgEl, '图片正在后台拉取中');
      scheduleImageMirrorPoll(imgEl, 'placeholder-load');
      return;
    }
    if((imgEl.naturalWidth || 0) > 0 && (imgEl.naturalHeight || 0) > 0){
      markInlineImageMirrorVisible(imgEl);
      clearInlineImageMirrorPending(imgEl);
      clearInlineImageFailedState(imgEl);
      imgEl.dataset.srcStage = imgEl.dataset.srcStage || 'loaded';
      return;
    }
    const proxySrc = String(imgEl.dataset.proxySrc || '').trim();
    const currentSrc = String(imgEl.getAttribute('src') || imgEl.src || '').trim();
    if(imgEl.dataset.srcStage === 'direct' && proxySrc && currentSrc !== proxySrc){
      if(inlineImageMirrorDisabled(imgEl)){
        imgEl.dataset.srcStage = 'proxy-retry';
        clearInlineImageMirrorPending(imgEl);
        imgEl.src = proxySrc;
        return;
      }
      imgEl.dataset.srcStage = 'proxy-pending';
      const rawSrc = String(imgEl.dataset.rawSrc || imgEl.dataset.originSrc || '').trim();
      if(rawSrc && /^https?:\/\//i.test(rawSrc)) imgEl.dataset.providerSrc = rawSrc;
      markInlineImageMirrorPending(imgEl, '图片加载较慢，后台正在拉回');
      if(scheduleImageMirrorPoll(imgEl, 'direct-error')) return;
      imgEl.src = proxySrc;
      armInlineImageSlowMirrorFallback(imgEl);
      return;
    }
    if(scheduleImageMirrorPoll(imgEl, 'empty-load')) return;
    if(retryInlineImageSoft(imgEl, 'empty-load')) return;
    removeBrokenInlineImage(imgEl);
  });
}

function buildInlineImageGroup(images, opts={}){
  const normalized = normalizeImageItems(images);
  if(!normalized.length) return null;

  const total = normalized.length;
  const cols = total <= 1 ? 1 : total === 2 ? 2 : 3;
  const visibleCount = cols === 3 ? Math.min(total, 3) : total;
  const visible = normalized.slice(0, visibleCount);
  const showBadge = total > visibleCount;

  const group = document.createElement('div');
  group.className = `inline-image-group cols-${cols}`;
  group.dataset.imageCount = String(total);
  group.dataset.totalCount = String(total);
  group.dataset.galleryItems = JSON.stringify(normalizeGalleryItemsForDataset(normalized));

  visible.forEach((item, idx) => {
    const cell = document.createElement('div');
    cell.className = 'inline-image-cell';

    const im = document.createElement('img');
    configureDeferredInlineImage(im);
    im.className = 'inline-img';
    im.alt = item.alt || `图片${idx + 1}`;
    im.dataset.caption = String(item.caption || '').trim();
    attachInlineImageErrorHandler(im);
    im.dataset.galleryIndex = String(idx);
    im.dataset.sourceType = String(item.source_type || item.sourceType || '').trim();
    im.dataset.operation = String(item.operation || item.intent || '').trim();
    if(preferInlineDirectImageSource(item)) im.dataset.disableMirror = '1';
    im.dataset.originSrc = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
    im.dataset.rawSrc = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
    if(item.providerUrl) im.dataset.providerSrc = item.providerUrl;
    else if(item.is_temporary_remote && /^https?:\/\//i.test(imageItemOpenUrl(item) || imageItemPrimaryUrl(item))) im.dataset.providerSrc = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
    if(imageItemProxyUrl(item)) im.dataset.proxySrc = imageItemProxyUrl(item);
    if(preferInlineDirectImageSource(item)) im.dataset.preferDirect = '1';
    setImgSrcMaybeLocal(im, imageItemPrimaryUrl(item), { displayUrl:imageItemPrimaryUrl(item), rawUrl:imageItemOpenUrl(item) || imageItemPrimaryUrl(item), proxyUrl:imageItemProxyUrl(item), preferDirect: preferInlineDirectImageSource(item), disableMirror: preferInlineDirectImageSource(item) });
    if(im.dataset.providerSrc && item.mirror_placeholder) scheduleImageMirrorPoll(im, 'slow');
    armInlineImageVisibleMirrorPersist(im);
    attachPreviewableImage(im, imageItemOpenUrl(item) || imageItemPrimaryUrl(item));
    cell.appendChild(im);

    if(showBadge && idx === visible.length - 1){
      cell.classList.add('has-more');
      const badge = document.createElement('div');
      badge.className = 'inline-image-more';
      badge.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="3"></rect><circle cx="9" cy="10" r="1.7"></circle><path d="M6.5 16l4.2-4.2a1 1 0 0 1 1.4 0L17.5 17"></path></svg><span>' + total + '</span>';
      cell.appendChild(badge);
    }

    group.appendChild(cell);
  });
  return group;
}

async function appendImageGroup(container, images, opts={}){
  if(!container) return null;
  const normalized = normalizeImageItems(images);
  if(!normalized.length) return null;

  if(normalized.length === 1){
    const item = normalized[0];
    const wrapper = document.createElement('div');
    wrapper.className = 'inline-img-standalone';

    const im = document.createElement('img');
    configureDeferredInlineImage(im);
    im.className = 'inline-img';
    im.alt = item.alt || '图片1';
    im.dataset.caption = String(item.caption || '').trim();
    im.dataset.galleryIndex = '0';
    im.dataset.sourceType = String(item.source_type || item.sourceType || '').trim();
    im.dataset.operation = String(item.operation || item.intent || '').trim();
    if(preferInlineDirectImageSource(item)) im.dataset.disableMirror = '1';
    im.dataset.originSrc = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
    im.dataset.rawSrc = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
    if(item.providerUrl) im.dataset.providerSrc = item.providerUrl;
    else if(item.is_temporary_remote && /^https?:\/\//i.test(imageItemOpenUrl(item) || imageItemPrimaryUrl(item))) im.dataset.providerSrc = imageItemOpenUrl(item) || imageItemPrimaryUrl(item);
    if(imageItemProxyUrl(item)) im.dataset.proxySrc = imageItemProxyUrl(item);
    if(preferInlineDirectImageSource(item)) im.dataset.preferDirect = '1';
    attachInlineImageErrorHandler(im);
    setImgSrcMaybeLocal(im, imageItemPrimaryUrl(item), { displayUrl:imageItemPrimaryUrl(item), rawUrl:imageItemOpenUrl(item) || imageItemPrimaryUrl(item), proxyUrl:imageItemProxyUrl(item), preferDirect: preferInlineDirectImageSource(item), disableMirror: preferInlineDirectImageSource(item) });
    if(im.dataset.providerSrc && item.mirror_placeholder) scheduleImageMirrorPoll(im, 'slow');
    armInlineImageVisibleMirrorPersist(im);
    attachPreviewableImage(im, imageItemOpenUrl(item) || imageItemPrimaryUrl(item));

    wrapper.appendChild(im);
    container.appendChild(wrapper);
    return wrapper;
  }

  const group = buildInlineImageGroup(normalized, opts);
  if(group) container.appendChild(group);
  return group;
}

async function renderStructuredMessageContent(container, content){
  if(!container || !Array.isArray(content)) return false;
  const parts = content.filter(Boolean);
  if(!parts.length) return false;
  container.innerHTML = "";

  let hasAny = false;
  let pendingImages = [];

  const flushImages = async ()=>{
    if(!pendingImages.length) return;
    const group = await appendImageGroup(container, pendingImages);
    pendingImages = [];
    if(group) hasAny = true;
  };

  for(const part of parts){
    if(part?.type === "text"){
      const txt = String(part.text || "");
      if(!txt.trim()) continue;
      await flushImages();
      const block = document.createElement("div");
      block.className = "structured-text-block";
      const role = container.closest('.bubble')?.classList.contains('u') ? 'user' : 'assistant';
      block.innerHTML = renderMessageHtml(role, txt);
      container.appendChild(block);
      hasAny = true;
      continue;
    }
    if(isStructuredImagePartLike(part)){
      const imagePart = normalizeStructuredImagePartForRender(part);
      ensureStructuredImagePartDurableUrl(imagePart);
      const reg = imagePart?.file_registry && typeof imagePart.file_registry === 'object' ? imagePart.file_registry : {};
      const imageUrl = structuredImagePartDisplayUrl(imagePart);
      const durableUrl = composerLibraryDurableImageUrl(imagePart);
      const idDownloadUrl = composerLibraryIdBrowserSource(imagePart, 'download');
      if(imageUrl){
        pendingImages.push({
          url: imageUrl,
          rawUrl: composerLibraryBrowserImageSource(imagePart.raw_url || imagePart.rawUrl || imagePart._source_url || durableUrl) || imageUrl,
          viewUrl: composerLibraryBrowserImageSource(imagePart.view_url || imagePart.viewUrl || reg.view_url || durableUrl) || imageUrl,
          downloadUrl: composerLibraryBrowserFileSource(imagePart.download_url || imagePart.downloadUrl || reg.download_url || idDownloadUrl || imagePart.view_url || imagePart.viewUrl || durableUrl || imageUrl, 'download') || idDownloadUrl || imageUrl,
          previewUrl: composerLibraryBrowserImageSource(imagePart.preview_url || imagePart.previewUrl || imagePart._preview_url || durableUrl) || imageUrl,
          providerUrl: String(imagePart.provider_url || imagePart.providerUrl || '').trim(),
          alt: String(imagePart.alt || imagePart.filename || reg.filename || "").trim(),
          caption: String(imagePart.caption || "").trim(),
          source_type: String(imagePart.source_type || imagePart.sourceType || '').trim(),
          operation: String(imagePart.operation || '').trim(),
          file_library_id: String(imagePart.file_library_id || imagePart.library_file_id || reg.file_id || '').trim(),
          library_file_id: String(imagePart.library_file_id || imagePart.file_library_id || reg.file_id || '').trim(),
          storage_ref: String(imagePart.storage_ref || '').trim(),
          model_storage_ref: String(imagePart.model_storage_ref || '').trim(),
        });
      }
    }
  }

  await flushImages();
  return hasAny;
}

function structuredImagePartLooksImageFile(part){
  const row = part && typeof part === 'object' ? part : {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  const mime = String(row.mime || row.content_type || row.contentType || reg.mime || reg.content_type || '').trim().toLowerCase();
  if(mime.startsWith('image/')) return true;
  const ext = String(row.ext || reg.ext || '').trim().toLowerCase().replace(/^\./, '');
  if(['png','jpg','jpeg','webp','gif','bmp','svg','avif','heic','heif'].includes(ext)) return true;
  const name = String(row.filename || row.saved_filename || reg.filename || reg.saved_filename || '').trim().toLowerCase();
  return /\.(png|jpe?g|webp|gif|bmp|svg|avif|heic|heif)(?:$|[?#])/.test(name);
}

function isStructuredImagePartLike(part){
  if(!part || typeof part !== 'object') return false;
  if(part.type === 'image_url') return true;
  const reg = part.file_registry && typeof part.file_registry === 'object' ? part.file_registry : {};
  const hasImageIdentity = !!(
    String(part.file_library_id || part.library_file_id || reg.file_id || '').trim()
    || String(part.image_id || part.attachment_id || '').trim()
    || part.image_url
  );
  return hasImageIdentity && structuredImagePartLooksImageFile(part) && !!composerLibraryDisplayImageUrl(part);
}

function normalizeStructuredImagePartForRender(part){
  const row = part && typeof part === 'object' ? { ...part } : {};
  row.type = 'image_url';
  if(!row.image_url || typeof row.image_url !== 'object') row.image_url = { url:'' };
  const display = composerLibraryDisplayImageUrl(row);
  if(display && !String(row.image_url.url || '').trim()) row.image_url.url = display;
  return row;
}

function splitMixedUserStructuredContent(content){
  const parts = Array.isArray(content) ? content.filter(Boolean) : [];
  const textParts = [];
  const imageParts = [];
  const otherParts = [];
  for(const part of parts){
    if(part?.type === 'text'){
      if(String(part.text || '').trim()) textParts.push(part);
      continue;
    }
    if(isStructuredImagePartLike(part)){
      imageParts.push(normalizeStructuredImagePartForRender(part));
      continue;
    }
    otherParts.push(part);
  }
  return {
    hasMixed: textParts.length > 0 && imageParts.length > 0,
    textParts,
    imageParts,
    otherParts,
  };
}

function assistantModelNameForBubble(message, sessionId){
  const msg = message && typeof message === 'object' ? message : {};
  const sid = String(sessionId || '').trim();
  const session = sid ? getSessionById(sid) : getActive();
  const selectedModel = String(session?.model || '').trim();
  const sessionRuntimeModel = String(session?.runtimeModel || session?.runtime_model || '').trim();
  const runtimeSourceModel = String(session?.runtimeModelSourceModel || session?.runtime_model_source_model || '').trim();
  const currentSessionRuntimeModel = sessionRuntimeModel && (!runtimeSourceModel || runtimeSourceModel === selectedModel)
    ? sessionRuntimeModel
    : '';
  return String(
    msg.runtimeModel
    || msg.runtime_model
    || msg.model
    || msg.modelName
    || msg.model_name
    || currentSessionRuntimeModel
    || selectedModel
    || 'AI'
  ).trim() || 'AI';
}

function assistantGeneratedFilesForFallbackCards(files, answerRoot){
  const list = Array.isArray(files) ? files : [];
  if(!list.length || !answerRoot) return list;
  try{
    if(answerRoot.querySelector?.('a[data-webai-managed-download="1"]')) return [];
  }catch(_){ }
  return list;
}

function buildBubbleNode(role, text, opts={}){
  const div = document.createElement("div");
  div.className = "bubble " + (role === "user" ? "u" : "a");
  if(opts.messageIndex != null) div.dataset.msgIndex = String(opts.messageIndex);
  const msg = opts.message || null;
  const backendErrorPayloadForBubble = role !== "user" ? getAssistantBackendErrorPayload(msg || null) : null;
  if(backendErrorPayloadForBubble) div.classList.add('bubble-backend-error');
  const splitGroupId = String(msg?._split_group_id || opts.splitGroupId || '').trim();
  const splitPart = String(msg?._split_part || opts.splitPart || '').trim().toLowerCase();
  if(splitGroupId){
    div.dataset.splitGroupId = splitGroupId;
    div.classList.add('bubble-user-split');
  }
  if(splitPart){
    div.dataset.splitPart = splitPart;
    div.classList.add(`bubble-user-split-${splitPart}`);
  }
  const hideHeader = !!opts.hideHeader;
  const suppressQuote = !!opts.suppressQuote;
  const isUser = role === "user";
  const header = hideHeader ? null : document.createElement("div");
  if(header) header.className = "bubble-head" + (isUser ? " bubble-head-user" : " bubble-head-assistant");

  const roleWrap = (!hideHeader && !isUser) ? document.createElement("div") : null;
  if(roleWrap){
    roleWrap.className = "bubble-role-wrap";
    const labels = document.createElement("span");
    labels.className = "bubble-role-labels";
    const roleEl = document.createElement("span");
    roleEl.className = "bubble-role";
    roleEl.textContent = assistantModelNameForBubble(msg, opts?.sessionId || store?.activeId || '');
    labels.appendChild(roleEl);
    roleWrap.appendChild(labels);
    header.appendChild(roleWrap);
  }

  const actions = hideHeader ? null : document.createElement("div");
  if(actions) actions.className = "bubble-actions" + (isUser ? " bubble-actions-user" : " bubble-actions-assistant");
  const processText = !isUser ? String(
    opts?.processText
    || msg?.fileProcessText
    || msg?.file_process_text
    || msg?.draftProcessText
    || msg?.draft_process_text
    || ''
  ) : String(opts?.processText || "");
  if(actions){
    buildBubbleMessageActions(actions, {
      role,
      text,
      message: msg,
      messageIndex: opts.messageIndex,
      disableCopy: opts.disableCopy,
      sessionId: opts?.sessionId || store?.activeId || '',
      backendText: backendErrorPayloadForBubble?.text || '',
    });
  }

  if(header){
    if(!isUser || roleWrap) div.appendChild(header);
  }

  const body = document.createElement("div");
  body.className = "bubble-body";
  const sessionIdForFiles = opts?.sessionId || store?.activeId || '';
  const content = String(text ?? "");
  const draftStatusText = String(opts?.statusText || "");
  const isStreamingDraftBubble = !isUser && !!opts?.streamingDraft;
  const reasoningSnapshot = !isUser ? ((opts?.reasoningSnapshot && typeof opts.reasoningSnapshot === 'object') ? opts.reasoningSnapshot : _messageReasoningSnapshot(opts?.message || null)) : null;
  const reasoningNode = !isUser ? buildReasoningPanel(String(opts?.sessionId || ''), { statusText: draftStatusText, reasoningSnapshot, message: opts?.message || null }) : null;
  if(reasoningNode) body.appendChild(reasoningNode);
  const mcpCardsNode = !isUser && typeof syncMcpInlineCardsInBody === 'function'
    ? syncMcpInlineCardsInBody(body, String(opts?.sessionId || ''), reasoningSnapshot?.reasoningMeta?.mcpCards || opts?.message?.reasoningMeta?.mcpCards || [])
    : null;
  const assistantWeatherNode = !isUser ? syncAssistantWeatherCardInBody(body, getAssistantMessageWeatherPayload(opts?.message || null)) : null;
  const assistantGeneratedFiles = !isUser ? getAssistantMessageGeneratedFiles(opts?.message || null, sessionIdForFiles) : [];
  const messageImageRepliesNode = !isUser
    ? syncAssistantImageRepliesInBody(body, getAssistantMessageImageReplies(opts?.message || null))
    : null;
  if(backendErrorPayloadForBubble){
    const errorCard = buildBackendErrorCardNode(backendErrorPayloadForBubble);
    if(errorCard) body.appendChild(errorCard);
  }else if(content.trim()){
    const contentWrap = document.createElement('div');
    contentWrap.className = 'reasoning-answer-wrap';
    if(isStreamingDraftBubble){
      const draftTextNode = document.createElement('div');
      draftTextNode.className = 'streaming-draft-text';
      draftTextNode.style.cssText = 'white-space:pre-wrap;word-break:break-word;line-height:1.75;';
      draftTextNode.textContent = content;
      contentWrap.appendChild(draftTextNode);
    }else{
      const renderContent = (!isUser && assistantGeneratedFiles.length)
        ? appendAssistantGeneratedFileLinks(content, assistantGeneratedFiles)
        : content;
      contentWrap.innerHTML = renderMessageHtml(role, renderContent);
    }
    body.appendChild(contentWrap);
    if(!isUser && !isStreamingDraftBubble) linkifyAssistantGeneratedFileMentions(body, sessionIdForFiles);
  }
  const fallbackGeneratedFiles = !isUser
    ? assistantGeneratedFilesForFallbackCards(assistantGeneratedFiles, body.querySelector(':scope > .reasoning-answer-wrap'))
    : [];
  const assistantGeneratedFilesNode = !isUser ? syncAssistantGeneratedFilesInBody(body, fallbackGeneratedFiles) : null;
  if(!backendErrorPayloadForBubble && !content.trim() && !reasoningNode && !mcpCardsNode && !messageImageRepliesNode && !assistantWeatherNode && !assistantGeneratedFilesNode && !processText.trim()){
    body.appendChild(createThinkingNode(draftStatusText || messageMediaT('stream.thinking', null, 'Thinking…')));
  }
  div.appendChild(body);
  if(!isUser) setBubbleProcessText(div, processText);
  if(isUser && msg && !suppressQuote) injectMessageQuoteIntoBubble(div, msg);
  if(!isUser && msg) injectAssistantSourcesIntoBubble(div, msg);
  if(!isUser) injectAssistantUsageIntoBubble(div, msg || null);

  if(actions && actions.childElementCount){
    div.appendChild(actions);
  }

  return div;
}

function addBubble(role, text){
  const div = buildBubbleNode(role, text);
  chatEl.appendChild(div);
  bindBubbleEnhancements(div);
  dedupeAdjacentAssistantImageBubbles();
  maybeAutoScroll();
  return div;
}


function syncStreamingCaretForBubble(bubble){
  if(!bubble) return;
  const sid = bubble?.dataset?.sessionDraft || "";
  const body = bubble.querySelector('.bubble-body');
  if(!body) return;
  const shouldShow = !!sid && typeof isSessionStreaming === 'function' && isSessionStreaming(sid) && !!body.textContent.trim();
  bubble.classList.toggle('bubble-streaming', shouldShow);
  // Inline blinking caret looked like an extra marker under “正在思考中”.
  // Keep the existing streaming state logic, but do not render that caret.
  body.querySelectorAll('.bubble-streaming-caret').forEach(node => node.remove());
}

function inferThinkingStage(text){
  const s = String(text || "");
  if(/搜索|资料|联网|搜图|天气/.test(s)) return "search";
  if(/网页|链接|读取|补充网页|搜索网页/.test(s)) return "web";
  if(/生成|回答|回复/.test(s)) return "answer";
  return "think";
}

function createThinkingNode(text, spinnerOnly=false){
  const wrap = document.createElement("span");
  wrap.className = "thinking-wrap";
  wrap.classList.add('status-' + inferThinkingStage(text));
  const tx = document.createElement("span");
  tx.className = "thinking-text";
  tx.textContent = text || "Thinking…";
  wrap.appendChild(tx);
  return wrap;
}

function setBubbleProcessText(bubble, text){
  if(!bubble) return;
  const raw = String(text || '').trim();
  const existing = bubble.querySelector('.draft-process-wrap');
  if(!raw){
    if(existing) existing.remove();
    return;
  }
  const liveProcess = !!String(bubble?.dataset?.sessionDraft || '').trim();
  const looksRawEdit = /原始文件修改代码|===== 修改|replacement（模型正在生成的新代码）|exact_old（将被替换的原始代码片段）/i.test(raw);
  let wrap = existing;
  if(!wrap){
    wrap = document.createElement('div');
    // 正在写时默认展开；写完后的持久化面板默认收起，避免完成后占用过多聊天空间。
    wrap.className = 'draft-process-wrap';
    if(!liveProcess) wrap.classList.add('is-collapsed');
    wrap.innerHTML = `<button type="button" class="draft-process-label" aria-expanded="true"><span class="draft-process-title">${escapeHtml(messageMediaT('message.ai_writing_file', null, 'AI is writing a file'))}</span><span class="draft-process-caret" aria-hidden="true">⌄</span></button><pre class="draft-process-pre"></pre>`;
    const body = bubble.querySelector('.bubble-body');
    if(body) bubble.insertBefore(wrap, body);
    else bubble.appendChild(wrap);
  }else if(!wrap.dataset.userToggled){
    wrap.classList.toggle('is-collapsed', !liveProcess);
  }
  const labelBtn = wrap.querySelector('.draft-process-label');
  const titleEl = wrap.querySelector('.draft-process-title');
  if(titleEl){
    titleEl.textContent = looksRawEdit
      ? messageMediaT(liveProcess ? 'message.raw_edit_active' : 'message.raw_edit', null, liveProcess ? 'Original edit code · generating' : 'Original edit code')
      : messageMediaT('message.ai_writing_file', null, 'AI is writing a file');
  }
  if(labelBtn && labelBtn.tagName === 'BUTTON' && !labelBtn.dataset.bound){
    labelBtn.dataset.bound = '1';
    labelBtn.addEventListener('click', ()=>{
      wrap.dataset.userToggled = '1';
      const collapsed = wrap.classList.toggle('is-collapsed');
      labelBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      labelBtn.setAttribute('title', messageMediaT(collapsed ? 'message.expand_raw_edit' : 'message.collapse_raw_edit', null, collapsed ? 'Expand original edit code' : 'Collapse original edit code'));
    });
  }
  if(labelBtn){
    const collapsedNow = wrap.classList.contains('is-collapsed');
    labelBtn.setAttribute('aria-expanded', collapsedNow ? 'false' : 'true');
    labelBtn.setAttribute('title', messageMediaT(collapsedNow ? 'message.expand_raw_edit' : 'message.collapse_raw_edit', null, collapsedNow ? 'Expand original edit code' : 'Collapse original edit code'));
  }
  const pre = wrap.querySelector('.draft-process-pre');
  if(!pre) return;
  const previousText = String(pre.dataset.processText || '');
  const shouldStickBottom = !previousText || ((pre.scrollHeight - pre.clientHeight - pre.scrollTop) <= 48);
  if(previousText !== raw){
    pre.textContent = raw;
    pre.dataset.processText = raw;
  }
  if(shouldStickBottom){
    requestAnimationFrame(()=>{
      pre.scrollTop = Math.max(0, pre.scrollHeight - pre.clientHeight);
    });
  }
}

function injectAssistantUsageIntoBubble(bubble, message){
  if(!bubble) return;
  const existing = bubble.querySelector('.assistant-usage-inline');
  const shouldShow = (typeof getGenerationSettings === 'function' && typeof normalizeApiTriState === 'function')
    ? normalizeApiTriState(getGenerationSettings()?.generation_include_usage) === 'enabled'
    : false;
  if(!shouldShow){
    if(existing) existing.remove();
    const emptyFooter = bubble.querySelector('.bubble-footer:empty');
    if(emptyFooter) emptyFooter.remove();
    return;
  }
  const usage = getAssistantMessageGenerationUsage(message || null);
  const label = assistantUsageText(usage);
  if(!label){
    if(existing) existing.remove();
    const emptyFooter = bubble.querySelector('.bubble-footer:empty');
    if(emptyFooter) emptyFooter.remove();
    return;
  }
  let footer = bubble.querySelector('.bubble-footer');
  if(!footer){
    footer = document.createElement('div');
    footer.className = 'bubble-footer';
    const actions = bubble.querySelector(':scope > .bubble-actions');
    if(actions) bubble.insertBefore(footer, actions);
    else bubble.appendChild(footer);
  }
  let node = existing;
  if(!node){
    node = document.createElement('div');
    node.className = 'assistant-usage-inline';
    footer.appendChild(node);
  }else if(node.parentElement !== footer){
    footer.appendChild(node);
  }
  node.setAttribute('aria-label', window.AperviaI18n?.t('chat.usage.aria_label', null, 'Token usage') || 'Token usage');
  node.textContent = label;
  node.title = label;
}

function setDraftBubbleContent(bubble, text){
  if(!bubble) return;
  const role = bubble.classList.contains("u") ? "user" : "assistant";
  const draftSessionId = String(bubble.dataset.sessionDraft || "").trim();
  if(role !== 'user' && draftSessionId){
    const rt = ensureSessionRuntime(draftSessionId);
    patchStreamingDraftBubble(bubble, {
      sessionId: draftSessionId,
      visibleText: String(text ?? ""),
      statusText: String(rt?.statusText || ''),
      processText: String(rt?.draftProcessText || ''),
    });
    liveDraftBubbleEls[draftSessionId] = bubble;
    return;
  }

  const sessionIdForFiles = draftSessionId || store?.activeId || '';
  const processText = draftSessionId ? String(ensureSessionRuntime(draftSessionId)?.draftProcessText || '') : '';
  const content = String(text ?? "");
  const body = bubble.querySelector('.bubble-body');

  if(!body){
    const fresh = buildBubbleNode(role === "user" ? "user" : "assistant", text, { sessionId: sessionIdForFiles, processText });
    if(draftSessionId) fresh.dataset.sessionDraft = draftSessionId;
    bubble.replaceWith(fresh);
    bindBubbleEnhancements(fresh);
    syncStreamingCaretForBubble(fresh);
    if(fresh.dataset.sessionDraft) liveDraftBubbleEls[fresh.dataset.sessionDraft] = fresh;
    return;
  }

  const statusText = draftSessionId ? String(ensureSessionRuntime(draftSessionId)?.statusText || '') : '';
  body.innerHTML = '';
  const reasoningNode = role !== 'user' ? buildReasoningPanel(draftSessionId, { statusText, message: null }) : null;
  if(reasoningNode) body.appendChild(reasoningNode);
  const mcpCardsNode = role !== 'user' && typeof syncMcpInlineCardsInBody === 'function'
    ? syncMcpInlineCardsInBody(body, draftSessionId, ensureSessionRuntime(draftSessionId)?.reasoningMeta?.mcpCards || [])
    : null;
  if(content.trim()){
    const contentWrap = document.createElement('div');
    contentWrap.className = 'reasoning-answer-wrap';
    contentWrap.innerHTML = renderMessageHtml(role, content, { streamingDraft: !!draftSessionId });
    body.appendChild(contentWrap);
    if(role !== 'user') linkifyAssistantGeneratedFileMentions(body, sessionIdForFiles);
  }else if(!reasoningNode && !mcpCardsNode && !processText.trim()){
    body.appendChild(createThinkingNode(statusText || messageMediaT('stream.thinking', null, 'Thinking…')));
  }

  if(role !== 'user') setBubbleProcessText(bubble, processText);
  bindBubbleEnhancements(bubble);
  syncStreamingCaretForBubble(bubble);
  if(draftSessionId) liveDraftBubbleEls[draftSessionId] = bubble;
}

function quickAction(text){
  try{
    inputEl.value = text || "";
    inputEl.focus();

inputEl.dispatchEvent(new Event("input"));
  }catch(e){}
}


// 天气 / 定位是否调用工具，统一交给后端 orchestrator/tool planner 判断。
// 前端只负责展示天气卡片与携带已授权的缓存定位，不再用正则预判用户意图。

function weatherDisplayText(value, fallback="--"){
  if(value === null || value === undefined || value === "") return fallback;
  const n = Number(value);
  if(Number.isFinite(n)) return String(Math.round(n));
  return String(value);
}

function weatherMetricText(value, suffix="", fallback="--", digits=0){
  if(value === null || value === undefined || value === "") return fallback;
  const n = Number(value);
  const out = Number.isFinite(n) ? (digits > 0 ? n.toFixed(digits) : String(Math.round(n))) : String(value);
  return `${out}${suffix}`;
}

function formatWeatherClock(value){
  const s = String(value || "").trim();
  const m = s.match(/(\d{2}):(\d{2})/);
  if(m) return `${m[1]}:${m[2]}`;
  return s;
}

function formatWeatherDayLabel(value, idx){
  const s = String(value || "").trim();
  if(!s) return idx === 0
    ? messageMediaT('weather.today', null, 'Today')
    : messageMediaT('weather.day_index', {count:idx+1}, `Day ${idx+1}`);
  if(/[周星期天一二三四五六日]|今天|明天|后天/.test(s)) return s;
  const d = new Date(s);
  if(Number.isNaN(d.getTime())) return s;
  const week = ["周日","周一","周二","周三","周四","周五","周六"];
  if(idx === 0) return messageMediaT('weather.today', null, 'Today');
  if(idx === 1) return messageMediaT('weather.tomorrow', null, 'Tomorrow');
  if(window.AperviaI18n?.language !== 'zh-CN') return new Intl.DateTimeFormat('en', {weekday:'short'}).format(d);
  return week[d.getDay()];
}

function normalizeWeatherPayload(data){
  if(!data || typeof data !== "object") return data;
  const cur = data.current || {};
  const location = data.location || {};
  const hourly = Array.isArray(data.hourly) ? data.hourly : [];
  const daily = Array.isArray(data.daily) ? data.daily : [];
  return {
    ...data,
    location: {
      ...location,
      name: location.name || location.display_name || messageMediaT('weather.current_location', null, 'Current location')
    },
    current: {
      ...cur,
      weather: cur.weather || cur.desc || "",
      emoji: cur.emoji || cur.icon || "🌈",
      feels_like: cur.feels_like ?? cur.apparent_temperature ?? null,
      temperature_unit: cur.temperature_unit || "°C",
      wind_speed_unit: cur.wind_speed_unit || "km/h",
      time: formatWeatherClock(cur.time || data.updated_at || "")
    },
    hourly: hourly.map((h, idx) => ({
      ...h,
      weather: h.weather || h.desc || "",
      emoji: h.emoji || h.icon || "🌈",
      precip: h.precip ?? h.precip_probability ?? h.precipitation ?? "--",
      time: formatWeatherClock(h.time || h.label || ""),
      _idx: idx
    })),
    daily: daily.map((d, idx) => ({
      ...d,
      weather: d.weather || d.desc || "",
      emoji: d.emoji || d.icon || "🌈",
      precip: d.precip ?? d.precip_probability ?? d.precipitation_sum ?? "--",
      label: formatWeatherDayLabel(d.label || d.date || "", idx),
      _idx: idx
    }))
  };
}

function weatherSystemText(key, fallback){
  return window.AperviaI18n?.t(key, null, fallback) || fallback;
}

function weatherSystemMessage(data){
  const row = data && typeof data === 'object' ? data : {};
  if(row.need_location){
    return weatherSystemText('weather.location_required', 'Tell Apervia which location to use.');
  }
  const key = String(row.message_key || '').trim();
  if(key) return weatherSystemText(key, String(row.message || 'Weather data is temporarily unavailable.'));
  return String(row.message || weatherSystemText('weather.service_unavailable', 'Weather data is temporarily unavailable.'));
}

function weatherSystemTips(data){
  const row = data && typeof data === 'object' ? data : {};
  if(row.need_location){
    return [weatherSystemText('weather.location_required_action', 'Enter a city, or allow location access for this request.')];
  }
  if(String(row.error_code || '').trim() === 'service_unavailable' || String(row.message_key || '').trim() === 'weather.service_unavailable'){
    return [weatherSystemText('weather.service_unavailable_action', 'Try again later or search the web for this location.')];
  }
  const keys = Array.isArray(row.tip_keys) ? row.tip_keys : [];
  if(keys.length){
    return keys.map((key, index)=> weatherSystemText(String(key || ''), String(row.tips?.[index] || ''))).filter(Boolean);
  }
  return Array.isArray(row.tips) ? row.tips.map((item)=> String(item || '').trim()).filter(Boolean) : [];
}

function weatherCardToText(data){
  const x = normalizeWeatherPayload(data);
  if(!x) return "";
  if(x.need_location || x.ok === false) return [weatherSystemMessage(x), ...weatherSystemTips(x)].filter(Boolean).join('\n');
  if(x.summary) return String(x.summary);
  const place = x.location?.name || messageMediaT('weather.current_location', null, 'Current location');
  const cur = x.current || {};
  return `${place} ${cur.emoji || ""} ${cur.weather || ""} ${cur.temperature ?? "--"}${cur.temperature_unit || "°C"}`.trim();
}

function buildWeatherCardNode(data){
  data = normalizeWeatherPayload(data);
  const wrap = document.createElement("div");
  wrap.className = "weather-card";

  if(!data || data.ok === false || data.need_location){
    const empty = document.createElement("div");
    empty.className = "weather-empty";
    empty.textContent = [weatherSystemMessage(data), ...weatherSystemTips(data)].filter(Boolean).join("\n");
    wrap.appendChild(empty);
    return wrap;
  }

  const cur = data.current || {};
  if(data.summary){
    const summary = document.createElement("div");
    summary.className = "weather-summary";
    summary.textContent = String(data.summary);
    wrap.appendChild(summary);
  }
  const top = document.createElement("div");
  top.className = "weather-top";
  const temperatureUnit = String(cur.temperature_unit || "°C");
  const updatedAt = messageMediaT('weather.updated_at', {time:String(cur.time || '')}, `Updated ${String(cur.time || '')}`);
  const feelsLike = messageMediaT('weather.feels_like', {temperature:weatherDisplayText(cur.feels_like), unit:temperatureUnit}, `Feels like ${weatherDisplayText(cur.feels_like)}${temperatureUnit}`);
  top.innerHTML = `<div><div class="weather-place">📍 ${escapeHtml(String(data.location?.name || messageMediaT('weather.current_location', null, 'Current location')))}</div><div class="weather-time">${escapeHtml(updatedAt)}</div></div><div class="weather-main"><div class="weather-emoji">${escapeHtml(String(cur.emoji || "🌈"))}</div><div><div class="weather-temp">${escapeHtml(weatherDisplayText(cur.temperature))}${escapeHtml(temperatureUnit)}</div><div class="weather-desc">${escapeHtml(String(cur.weather || ""))} · ${escapeHtml(feelsLike)}</div></div></div>`;
  wrap.appendChild(top);

  const metrics = [
    [messageMediaT('weather.humidity', null, 'Humidity'), weatherMetricText(cur.humidity, "%")],
    [messageMediaT('weather.wind_speed', null, 'Wind'), weatherMetricText(cur.wind_speed, ` ${cur.wind_speed_unit || "km/h"}`, "--", 1)],
    [messageMediaT('weather.pressure', null, 'Pressure'), weatherMetricText(cur.pressure, " hPa")],
    [messageMediaT('weather.precipitation_metric', null, 'Precipitation'), weatherMetricText(cur.precipitation, " mm", "--", 1)],
  ];
  const metricsEl = document.createElement("div");
  metricsEl.className = "weather-metrics";
  for(const [k,v] of metrics){
    const item = document.createElement("div");
    item.className = "weather-metric";
    item.innerHTML = `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(String(v))}</div>`;
    metricsEl.appendChild(item);
  }
  wrap.appendChild(metricsEl);

  if(Array.isArray(data.hourly) && data.hourly.length){
    const title = document.createElement("div");
    title.className = "weather-section-title";
    title.textContent = messageMediaT('weather.next_12_hours', null, 'Next 12 hours');
    wrap.appendChild(title);
    const hourly = document.createElement("div");
    hourly.className = "weather-hourly";
    for(const h of data.hourly){
      const item = document.createElement("div");
      item.className = "weather-hour";
      item.innerHTML = `<div class="t1">${escapeHtml(String(h.time || ""))}</div><div class="t2">${escapeHtml(String(h.emoji || "🌈"))}</div><div class="t3">${escapeHtml(weatherDisplayText(h.temp))}°</div><div class="t4">${escapeHtml(String(h.weather || ""))} · ${escapeHtml(messageMediaT('weather.precipitation', {value:weatherDisplayText(h.precip)}, `Precipitation ${weatherDisplayText(h.precip)}%`))}</div>`;
      hourly.appendChild(item);
    }
    wrap.appendChild(hourly);
  }

  if(Array.isArray(data.daily) && data.daily.length){
    const title = document.createElement("div");
    title.className = "weather-section-title";
    title.textContent = messageMediaT('weather.next_7_days', null, 'Next 7 days');
    wrap.appendChild(title);
    const daily = document.createElement("div");
    daily.className = "weather-daily";
    for(const d of data.daily){
      const item = document.createElement("div");
      item.className = "weather-day";
      item.innerHTML = `<div class="t1">${escapeHtml(String(d.label || d.date || ""))}</div><div class="t2">${escapeHtml(String(d.emoji || "🌈"))}</div><div class="t3">${escapeHtml(weatherDisplayText(d.temp_max))}° / ${escapeHtml(weatherDisplayText(d.temp_min))}°</div><div class="t4">${escapeHtml(String(d.weather || ""))} · ${escapeHtml(messageMediaT('weather.precipitation', {value:weatherDisplayText(d.precip)}, `Precipitation ${weatherDisplayText(d.precip)}%`))}</div>`;
      daily.appendChild(item);
    }
    wrap.appendChild(daily);
  }

  return wrap;
}


function normalizeMemoryEventPayload(payload){
  const row = (payload && typeof payload === 'object') ? payload : {};
  const title = String(row.title || '').trim() || messageMediaT(String(row.action || '').toLowerCase() === 'delete' ? 'memory.deleted' : 'memory.updated', null, String(row.action || '').toLowerCase() === 'delete' ? 'Deleted' : 'Memory updated');
  const text = String(row.text || row.memory || '').replace(/\s+/g, ' ').trim();
  const action = String(row.action || row.op || '').trim().toLowerCase() || 'update';
  const id = String(row.memory_id || row.id || '').trim();
  return { _kind:'memory_event', title, text, action, memory_id:id, id };
}

function buildMemoryEventNode(payload){
  const ev = normalizeMemoryEventPayload(payload);
  const wrap = document.createElement('div');
  wrap.className = 'memory-event-bubble';
  wrap.setAttribute('role', 'button');
  wrap.tabIndex = 0;
  wrap.title = messageMediaT('memory.open_saved', null, 'Open saved memories');
  const icon = document.createElement('div');
  icon.className = 'memory-event-icon';
  icon.textContent = '✓';
  const body = document.createElement('div');
  body.className = 'memory-event-main';
  const title = document.createElement('div');
  title.className = 'memory-event-title';
  title.textContent = ev.title;
  body.appendChild(title);
  if(ev.text){
    const text = document.createElement('div');
    text.className = 'memory-event-text';
    text.textContent = ev.text;
    body.appendChild(text);
  }
  wrap.appendChild(icon);
  wrap.appendChild(body);
  const open = ()=>{
    try{ openSettingsModal('personalization'); setPersonalizationMemoryModalOpen(true); }catch(_){ }
  };
  wrap.addEventListener('click', open);
  wrap.addEventListener('keydown', (e)=>{ if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); open(); } });
  return wrap;
}

function addMemoryEventBubble(payload){
  const node = buildMemoryEventNode(payload);
  chatEl.appendChild(node);
  maybeAutoScroll();
  return node;
}

function normalizeAssistantWeatherPayload(payload){
  const row = payload && typeof payload === 'object' ? payload : null;
  if(!row) return null;
  const kind = String(row._kind || '').trim();
  const hasWeatherShape = !!(kind === 'weather' || row.location || row.current || row.summary || row.need_location || row.ok === false || row.weather_payload || row.weatherPayload);
  if(!hasWeatherShape) return null;
  const source = (row.weather_payload && typeof row.weather_payload === 'object') ? row.weather_payload : ((row.weatherPayload && typeof row.weatherPayload === 'object') ? row.weatherPayload : row);
  return { _kind:'weather', ...source };
}

function getAssistantMessageWeatherPayload(message){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg) return null;
  return normalizeAssistantWeatherPayload(msg.weather || msg.weatherPayload || msg.weather_payload || msg.content || null);
}

function syncAssistantWeatherCardInBody(body, payload){
  if(!body?.querySelector) return null;
  const normalized = normalizeAssistantWeatherPayload(payload);
  const existing = body.querySelector(':scope > .weather-card');
  if(!normalized){
    if(existing) existing.remove();
    return null;
  }
  const node = buildWeatherCardNode(normalized);
  if(existing){
    existing.replaceWith(node);
    return node;
  }
  const anchor = body.querySelector(':scope > .reasoning-answer-wrap, :scope > .thinking-wrap, :scope > .image-generation-stage, :scope > .generated-files-card, :scope > .draft-process-wrap');
  if(anchor) body.insertBefore(node, anchor);
  else body.appendChild(node);
  return node;
}

function addWeatherBubble(data){
  const div = buildBubbleNode("assistant", weatherCardToText(data), { disableCopy:true, hideHeader:true });
  div.classList.add("weather-bubble");
  const body = div.querySelector(".bubble-body");
  if(body){
    body.innerHTML = "";
    body.appendChild(buildWeatherCardNode(data));
  }
  chatEl.appendChild(div);
  maybeAutoScroll();
  return div;
}


function buildFilesBubbleHtml(files){
  return "";
}

function addFilesBubble(files){
  return null;
}

/* ✅ 删除附件：同时删“附件消息”和“对应 system 上下文” */
async function removeAttachmentById(attId){
  await updateSessionById(sessionId, s=>{
    s.messages = s.messages.filter(m=>{
      const c = m.content;
      const isAtt = c && typeof c === "object" && (c._kind === "file" || c._kind === "image") && c.id === attId;
      const isLinkedSystem = m.role === "system" && m._link === attId;
      return !(isAtt || isLinkedSystem);
    });
  });
}

function attachmentMetaLabel(contentObj){
  const filename = String(contentObj?.filename || '').trim();
  const rawExt = String(contentObj?.ext || '').trim().replace(/^\./, '').toLowerCase();
  const nameExt = filename.includes('.') ? String(filename.split('.').pop() || '').trim().replace(/^\./, '').toLowerCase() : '';
  const ext = rawExt || nameExt;
  const labelMap = {
    py: 'Python',
    html: 'HTML',
    htm: 'HTML',
    js: 'JavaScript',
    mjs: 'JavaScript',
    cjs: 'JavaScript',
    ts: 'TypeScript',
    jsx: 'React JSX',
    tsx: 'React TSX',
    css: 'CSS',
    scss: 'SCSS',
    less: 'Less',
    json: 'JSON',
    md: 'Markdown',
    txt: 'Text',
    pdf: 'PDF',
    doc: 'Word',
    docx: 'Word',
    xls: 'Excel',
    xlsx: 'Excel',
    csv: 'CSV',
    ppt: 'PowerPoint',
    pptx: 'PowerPoint',
    zip: 'ZIP',
    rar: 'RAR',
    '7z': '7Z',
    jpg: 'JPG',
    jpeg: 'JPG',
    png: 'PNG',
    gif: 'GIF',
    webp: 'WebP',
    heic: 'HEIC',
    heif: 'HEIF',
  };
  if(contentObj?._kind === 'image') return messageMediaT('message.image', null, 'Image');
  if(ext && labelMap[ext]) return labelMap[ext];
  if(ext) return String(ext).toUpperCase();
  return messageMediaT('message.file', null, 'File');
}

function attachmentDisplayMetaLabel(contentObj, role=''){
  const base = attachmentMetaLabel(contentObj);
  const r = String(role || '').trim().toLowerCase();
  const kind = String(contentObj?._kind || '').trim();
  if(r === 'user' && kind === 'file') return messageMediaT('message.user_file', {type:base}, `User file · ${base}`);
  if(r === 'assistant' && kind === 'file') return `${assistantFileSourceRoleLabel(contentObj)} · ${base}`;
  return base;
}

function attachmentIconSvg(isImg){
  return isImg
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="3"></rect><circle cx="9" cy="10" r="1.5"></circle><path d="M6.5 17l4.2-4.2a1.2 1.2 0 0 1 1.7 0l2.2 2.2"></path><path d="M13.8 15.1l1.3-1.3a1.2 1.2 0 0 1 1.7 0l1.7 1.7"></path></svg>'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3.5h6.3l4.2 4.2V18a2.5 2.5 0 0 1-2.5 2.5H8A2.5 2.5 0 0 1 5.5 18V6A2.5 2.5 0 0 1 8 3.5z"></path><path d="M14 3.8V8h4.2"></path><path d="M8.8 12.2h6.4"></path><path d="M8.8 15.2h4.8"></path></svg>';
}

/* ✅ 渲染附件小卡片（不再用聊天气泡包裹） */
function buildUnifiedFileCardNode(opts={}){
  const card = document.createElement('div');
  card.className = ['file-card', 'file-card-chat', 'unified-file-card', String(opts.className || '').trim()].filter(Boolean).join(' ');
  const icon = document.createElement('div');
  icon.className = 'file-icon';
  icon.innerHTML = attachmentIconSvg(!!opts.isImage);
  card.appendChild(icon);

  if(opts.thumbUrl){
    const thumb = document.createElement('div');
    thumb.className = 'file-thumb';
    const img = document.createElement('img');
    img.src = String(opts.thumbUrl || '');
    thumb.appendChild(img);
    try{ attachPreviewableImage(img, img.src); }catch(_){ }
    card.appendChild(thumb);
  }

  const main = document.createElement('div');
  main.className = 'file-main';
  const name = document.createElement('div');
  name.className = 'file-name';
  name.textContent = String(opts.filename || '');
  main.appendChild(name);
  const meta = opts.metaNode instanceof HTMLElement ? opts.metaNode : document.createElement('div');
  meta.classList.add('file-meta');
  if(!(opts.metaNode instanceof HTMLElement)) meta.textContent = String(opts.metaText || messageMediaT('message.file', null, 'File'));
  main.appendChild(meta);

  if(opts.downloadHref){
    const download = document.createElement('a');
    download.className = 'file-download';
    download.href = String(opts.downloadHref || '');
    download.textContent = String(opts.downloadText || messageMediaT('message.download', null, 'Download'));
    download.target = '_blank';
    download.rel = 'noopener noreferrer';
    download.dataset.webaiManagedDownload = '1';
    main.appendChild(download);
  }
  card.appendChild(main);

  if(typeof opts.onRemove === 'function'){
    const remove = document.createElement('button');
    remove.className = 'file-x';
    remove.type = 'button';
    remove.textContent = '×';
    remove.title = String(opts.removeTitle || messageMediaT('message.remove_attachment', null, 'Remove attachment'));
    remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', event=>{
      event.stopPropagation();
      opts.onRemove(event, card);
    });
    card.appendChild(remove);
  }
  return card;
}

function addAttachmentBubble(role, contentObj, allowRemove=false, opts={}){
  const row = document.createElement("div");
  const isUser = role === "user";
  row.className = "attachment-row " + (isUser ? "attachment-row-user" : "attachment-row-assistant");

  const isImg = contentObj._kind === "image";
  const metaText = attachmentDisplayMetaLabel(contentObj, role);

  if(typeof buildUnifiedFileCardNode === 'function'){
    const unifiedCard = buildUnifiedFileCardNode({
      filename:contentObj.filename || '',
      metaText,
      isImage:isImg,
      className:isUser ? 'file-card-user' : 'file-card-assistant',
      thumbUrl:isImg && String(contentObj.data_url || '').startsWith('data:') ? contentObj.data_url : '',
      downloadHref:!isImg && contentObj.url ? normalizeAssistantDownloadHref(contentObj.download_url || contentObj.url || contentObj.view_url || contentObj.url) : '',
      onRemove:allowRemove ? ()=>removeAttachmentById(contentObj.id) : null,
      removeTitle:messageMediaT('message.remove_attachment', null, 'Remove attachment'),
    });
    if(contentObj?._kind === 'file'){
      unifiedCard.dataset.sourceRole = isUser ? normalizeUserFileSourceRole(contentObj) : normalizeAssistantFileSourceRole(contentObj);
      unifiedCard.dataset.sourceType = isUser ? 'upload' : 'generated';
    }
    row.appendChild(unifiedCard);
    const target = opts.container instanceof HTMLElement ? opts.container : chatEl;
    target.appendChild(row);
    if(target === chatEl) maybeAutoScroll();
    return;
  }

  const card = document.createElement("div");
  card.className = "file-card file-card-chat " + (isUser ? "file-card-user" : "file-card-assistant");
  if(contentObj?._kind === 'file'){
    card.dataset.sourceRole = isUser ? normalizeUserFileSourceRole(contentObj) : normalizeAssistantFileSourceRole(contentObj);
    card.dataset.sourceType = isUser ? 'upload' : 'generated';
  }

  const icon = document.createElement("div");
  icon.className = "file-icon";
  icon.innerHTML = attachmentIconSvg(isImg);
  card.appendChild(icon);

  // 可选小缩略图（只接受 data: 开头的本地预览）
  if(isImg && contentObj.data_url && String(contentObj.data_url).startsWith("data:")){
    const thumb = document.createElement("div");
    thumb.className = "file-thumb";
    const img = document.createElement("img");
    img.src = contentObj.data_url;
    thumb.appendChild(img);
    attachPreviewableImage(img, contentObj.data_url);
    card.appendChild(thumb);
  }

  const main = document.createElement("div");
  main.className = "file-main";

  const name = document.createElement("div");
  name.className = "file-name";
  name.textContent = contentObj.filename || "";
  main.appendChild(name);

  const meta = document.createElement("div");
  meta.className = "file-meta";
  meta.textContent = metaText;
  main.appendChild(meta);

  if(!isImg && contentObj.url){
    const dl = document.createElement("a");
    dl.className = "file-download";
    dl.href = normalizeAssistantDownloadHref(contentObj.download_url || contentObj.url || contentObj.view_url || contentObj.url);
    dl.textContent = messageMediaT('message.download', null, 'Download');
    dl.target = "_blank";
    dl.rel = "noopener noreferrer";
    dl.dataset.webaiManagedDownload = '1';
    main.appendChild(dl);
  }

  card.appendChild(main);
  if(allowRemove){
    const x = document.createElement("button");
    x.className = "file-x";
    x.title = messageMediaT('common.remove', null, 'Remove');
    x.type = "button";
    x.textContent = "×";
    x.addEventListener("click",(e)=>{
      e.stopPropagation();
      removeAttachmentById(contentObj.id);
    });
    card.appendChild(x);
  }

  row.appendChild(card);
  const target = opts.container instanceof HTMLElement ? opts.container : chatEl;
  target.appendChild(row);
  if(target === chatEl) maybeAutoScroll();
}

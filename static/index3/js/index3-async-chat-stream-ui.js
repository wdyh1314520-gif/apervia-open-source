/* Async chat streaming/send pipeline.*/

function asyncStreamT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params || {}, fallback) || String(fallback || key || '');
}

/* Streaming */
let _pendingRenderAll = false;
function safeRenderAll(){
  if(isSettingsModalOpen()){
    renderPassiveUiForModal();
    return;
  }
  if(!isHomeLandingView && isSessionStreaming(store.activeId) && visibleChatSessionId === store.activeId){
    _pendingRenderAll = true;
    renderList();
    refreshStatusForActiveSession();
    return;
  }
  renderAll();
}
function flushPendingRenderAll(){
  if(_pendingRenderAll){
    _pendingRenderAll = false;
    if(isSettingsModalOpen()){
      renderPassiveUiForModal();
      return;
    }
    renderAll();
  }
}

window.addEventListener('webai:katex-ready', ()=>{
  try{ invalidateChatRenderCache(); }catch(_){ }
  try{ safeRenderAll(); }catch(_){ }
});

window.addEventListener('webai:mermaid-ready', ()=>{
  try{ renderMermaidBlocks(document); }catch(_){ }
});

    function isHistorySummaryMessage(message){
      if(!message || typeof message !== "object") return false;
      if(String(message._kind || "") === "history_summary") return true;
      if(String(message.role || "") !== "system") return false;
      const content = String(message.content || "").trim();
      return content.startsWith("【历史摘要】") || content.startsWith("[历史摘要]");
    }

    function estimateRequestTokens(value){
      let text = "";
      try{ text = typeof value === "string" ? value : JSON.stringify(value || ""); }catch(_){ text = String(value || ""); }
      const raw = String(text || "");
      let ascii = 0;
      let cjk = 0;
      let other = 0;
      for(const ch of raw){
        const code = ch.codePointAt(0) || 0;
        if(code <= 0x7f) ascii += 1;
        else if((code >= 0x3400 && code <= 0x9fff) || (code >= 0xf900 && code <= 0xfaff)) cjk += 1;
        else other += 1;
      }
      return Math.max(1, Math.ceil(ascii / 4 + cjk * 0.85 + other / 2));
    }

    function upstreamModelMetadataForRequest(model){
      try{
        if(typeof modelMetadataForProfileModel === "function" && typeof getCurrentApiProfile === "function"){
          return modelMetadataForProfileModel(getCurrentApiProfile(), model) || {};
        }
      }catch(_){ }
      return {};
    }

    function contextWindowTokensForRequest(session){
      let configured = "";
      try{ configured = String(generationSettingsForRequest()?.generation_context_window_tokens || "").trim(); }catch(_){ configured = ""; }
      const n = Math.floor(Number(configured));
      if(Number.isFinite(n) && n > 0) return Math.max(4096, Math.min(2000000, n));
      const upstream = Number(upstreamModelMetadataForRequest(session?.model || DEFAULT_MODEL)?.context_window_tokens || 0);
      if(Number.isFinite(upstream) && upstream > 0) return Math.max(4096, Math.min(10000000, Math.floor(upstream)));
      return 0;
    }

    function sanitizeMessageForModelRequest(message){
      if(!message || typeof message !== "object") return null;
      const clean = {};
      const role = typeof message.role === "string" ? message.role : "";
      if(!role) return null;
      clean.role = role;
      if(Object.prototype.hasOwnProperty.call(message, 'content')) clean.content = message.content;
      if(String(role || '').toLowerCase() === 'user'){
        const fileMeta = getUserMessageInlineFileAttachments(message);
        if(fileMeta.length){
          clean.file_attachments = fileMeta.map(buildOutgoingUserFileAttachmentMeta).filter(Boolean);
          clean.attachments = clean.file_attachments;
          clean._composer_file_attachments = clean.file_attachments;
        }
      }
      const rawQuote = typeof message._quote === 'string'
        ? message._quote
        : (typeof message.quoteText === 'string'
          ? message.quoteText
          : (typeof message.quote === 'string' ? message.quote : ''));
      if(String(rawQuote || '').trim()) clean._quote = String(rawQuote);
      if(typeof message.name === 'string' && message.name) clean.name = message.name;
      if(typeof message.tool_call_id === 'string' && message.tool_call_id) clean.tool_call_id = message.tool_call_id;
      if(Array.isArray(message.tool_calls) && message.tool_calls.length) clean.tool_calls = message.tool_calls;
      if(message.function_call && typeof message.function_call === 'object') clean.function_call = message.function_call;
      return clean;
    }

    function requestMessageTextIdentity(message){
      const msg = message && typeof message === "object" ? message : null;
      if(!msg || String(msg.role || "").toLowerCase() !== "user") return "";
      const content = msg.content;
      let text = "";
      if(typeof content === "string"){
        text = content;
      }else if(Array.isArray(content)){
        text = content
          .filter(item => item && typeof item === "object" && String(item.type || "") === "text")
          .map(item => String(item.text || ""))
          .join("\n");
      }
      return String(text || "").replace(/\s+/g, " ").trim().slice(0, 1200);
    }

    function requestMessageStableIdentity(message){
      const msg = message && typeof message === "object" ? message : null;
      if(!msg || String(msg.role || "").toLowerCase() !== "user") return [];
      const keys = [];
      const push = (prefix, value)=>{
        const val = String(value || "").trim();
        if(val) keys.push(prefix + ":" + val);
      };
      push("send", msg._send_id || msg.client_send_id || msg.clientSendId || msg.send_id);
      push("created", msg.created_at_ms || msg.createdAtMs || msg.created_at || msg.createdAt);
      push("id", msg.id || msg.message_id || msg.messageId || msg._id);
      push("source_index", msg._request_source_index);
      const textKey = requestMessageTextIdentity(msg);
      if(textKey) push("text", textKey);
      return keys;
    }

    function requestMessageRawFileAttachments(message){
      const msg = message && typeof message === "object" ? message : null;
      if(!msg || String(msg.role || "").toLowerCase() !== "user") return [];
      const rows = [];
      for(const key of ["file_attachments", "attachments", "_composer_file_attachments", "files"]){
        const value = msg[key];
        if(Array.isArray(value)) rows.push(...value.filter(item => item && typeof item === "object"));
      }
      const content = msg.content;
      if(content && typeof content === "object" && !Array.isArray(content) && content._kind === "file"){
        rows.push(content);
      }
      return rows;
    }

    function preserveHistoricalFileAttachmentsForRequest(requestMessages, sourceMessages){
      const out = Array.isArray(requestMessages) ? requestMessages : [];
      const source = Array.isArray(sourceMessages) ? sourceMessages : [];
      if(!out.length || !source.length) return out;
      const byIdentity = new Map();
      const byText = new Map();
      const attachmentSources = [];
      source.forEach((msg, sourceIndex)=>{
        const rows = requestMessageRawFileAttachments(msg);
        if(!rows.length) return;
        const cleanRows = rows.map(buildOutgoingUserFileAttachmentMeta).filter(Boolean);
        if(!cleanRows.length) return;
        const sourceRow = { msg, rows: cleanRows };
        attachmentSources.push(sourceRow);
        for(const key of ["idx:" + sourceIndex, ...requestMessageStableIdentity(msg)]){
          if(!byIdentity.has(key)) byIdentity.set(key, []);
          byIdentity.get(key).push(sourceRow);
        }
        const textKey = requestMessageTextIdentity(msg);
        if(textKey){
          if(!byText.has(textKey)) byText.set(textKey, []);
          byText.get(textKey).push(sourceRow);
        }
      });
      if(!attachmentSources.length) return out;
      let restored = 0;
      for(const msg of out){
        if(!msg || typeof msg !== "object" || String(msg.role || "").toLowerCase() !== "user") continue;
        if(requestMessageRawFileAttachments(msg).length) continue;
        let matched = null;
        for(const key of requestMessageStableIdentity(msg)){
          const rows = byIdentity.get(key);
          if(rows && rows.length){ matched = rows[rows.length - 1]; break; }
        }
        if(!matched){
          const key = requestMessageTextIdentity(msg);
          const rows = key ? byText.get(key) : null;
          if(rows && rows.length === 1) matched = rows[0];
        }
        const cleanRows = matched?.rows || [];
        if(!cleanRows.length) continue;
        msg.file_attachments = cleanRows.map(row => ({ ...row }));
        msg.attachments = cleanRows.map(row => ({ ...row }));
        msg._composer_file_attachments = cleanRows.map(row => ({ ...row }));
        restored += cleanRows.length;
      }
      try{
        if(restored){
          console.log('[PROMPT_CACHE_HISTORY_ATTACHMENTS_RESTORED]', {
            requestMessages: out.length,
            sourceMessages: source.length,
            attachmentMessages: attachmentSources.length,
            restored
          });
        }
      }catch(_){ }
      return out;
    }

    function stripPromptCacheRequestOnlyMessageMeta(messages){
      for(const msg of (Array.isArray(messages) ? messages : [])){
        if(msg && typeof msg === "object"){
          delete msg._request_source_index;
        }
      }
      return messages;
    }

    function buildMessagesForRequest(session, opts={}){
      const msgs = Array.isArray(session?.messages) ? session.messages : [];
      const maxMessageIndexRaw = Number(opts?.maxMessageIndex);
      const hasMaxMessageIndex = Number.isInteger(maxMessageIndexRaw) && maxMessageIndexRaw >= 0;
      const currentSystemPrompt = String(buildDefaultSystemPrompt() || "").trim();
      const currentSystemMsg = currentSystemPrompt ? { role:"system", content: currentSystemPrompt } : null;
      const useBackendPersonalization = isBackendPersonalizationActive();
      const memorySystemPrompt = useBackendPersonalization ? "" : buildPersonalizationMemorySystemPrompt(getPersonalizationState());
      const memorySystemMsg = memorySystemPrompt ? { role:"system", content: memorySystemPrompt } : null;
      const fixedHead = [currentSystemMsg, memorySystemMsg].filter(Boolean);

      if(!msgs.length){
        return fixedHead;
      }

      const body = msgs.map((m, idx)=> ({ m, idx })).filter(({m, idx})=> {
        if(hasMaxMessageIndex && idx > maxMessageIndexRaw) return false;
        if(!m) return false;
        if(m._image_context_only || m._pending_stream_image_reply || m._image_asset_context_only) return false;
        if(String(m.role || '').trim().toLowerCase() === 'assistant'){
          const content = m.content;
          if(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply') return false;
        }
        if(idx === 0 && m.role === "system") return false;
        if(isLegacyDefaultSystemMessage(m)) return false;
        if(isLegacyAssistantQuoteContextSystemMessage(m)) return false;
        if(isHistorySummaryMessage(m)) return false;
        return true;
      });

      const contextWindowTokens = contextWindowTokensForRequest(session);
      if(!(contextWindowTokens > 0)){
        return [...fixedHead, ...body.map(({m})=>sanitizeMessageForModelRequest(m)).filter(Boolean)].filter(Boolean);
      }
      let outputReserve = 4096;
      try{
        const configuredOutput = Number(generationSettingsForRequest()?.generation_max_tokens || 0);
        if(Number.isFinite(configuredOutput) && configuredOutput > 0) outputReserve = Math.max(1024, configuredOutput);
        else{
          const upstreamOutput = Number(upstreamModelMetadataForRequest(session?.model || DEFAULT_MODEL)?.max_output_tokens || 0);
          if(Number.isFinite(upstreamOutput) && upstreamOutput > 0) outputReserve = Math.max(1024, upstreamOutput);
        }
      }catch(_){ }
      const fixedOverhead = 2048;
      const fixedTokens = fixedHead.reduce((sum, item)=> sum + estimateRequestTokens(item), 0);
      const historyBudget = Math.max(2048, contextWindowTokens - outputReserve - fixedOverhead - fixedTokens);
      const selected = [];
      let used = 0;
      for(let i = body.length - 1; i >= 0; i--){
        const clean = sanitizeMessageForModelRequest(body[i].m);
        if(!clean) continue;
        clean._request_source_index = body[i].idx;
        const itemTokens = estimateRequestTokens(clean);
        if(selected.length && used + itemTokens > historyBudget) break;
        selected.push(clean);
        used += itemTokens;
      }
      const tail = selected.reverse();

      return [...fixedHead, ...tail].filter(Boolean);
    }

    function normalizeFileAttachmentSourceRole(content, sourceType){
      const c = content && typeof content === 'object' ? content : {};
      const raw = String(c.source_role || c.sourceRole || c.version_role || c.versionRole || '').trim().toLowerCase();
      const st = String(sourceType || c.source_type || c.sourceType || c.file_registry?.source || '').trim().toLowerCase();
      if(st === 'generated' || st === 'assistant_generated' || st === 'edited_output'){
        return normalizeAssistantFileSourceRole(c);
      }
      if(raw === 'assistant_generated' || raw === 'latest_generated' || raw === 'generated' || raw === 'edited_output') return normalizeAssistantFileSourceRole(c);
      return normalizeUserFileSourceRole(c);
    }

    function normalizeFileAttachmentForRequest(content){
      if(!content || typeof content !== 'object' || Array.isArray(content) || content._kind !== 'file') return null;
      const filename = String(content.filename || content.file_registry?.filename || content.file_registry?.saved_filename || '').trim();
      if(!filename) return null;
      const sourceTypeRaw = String(content.source_type || content.sourceType || content.file_registry?.source || content.file_registry?.namespace || 'upload').trim().toLowerCase();
      const sourceType = sourceTypeRaw === 'generated' ? 'generated' : (sourceTypeRaw === 'file_library' ? 'file_library' : 'upload');
      const sourceRole = normalizeFileAttachmentSourceRole(content, sourceType);
      const libraryFileId = String(content.file_library_id || content.library_file_id || content.file_id || content.file_registry?.file_id || '').trim();
      return {
        id: String(content.id || libraryFileId || content.file_registry?.file_id || '').trim(),
        registry_file_id: String(content.registry_file_id || content.registryFileId || content.file_id || content.file_registry?.file_id || libraryFileId || '').trim(),
        file_id: String(content.file_id || content.registry_file_id || content.file_registry?.file_id || libraryFileId || '').trim(),
        file_library_id: libraryFileId,
        library_file_id: String(content.library_file_id || content.file_library_id || libraryFileId || '').trim(),
        artifact_id: String(content.artifact_id || content.id || '').trim(),
        source_type: sourceType,
        source_role: sourceRole,
        filename,
        ext: String(content.ext || content.file_registry?.ext || '').trim().toLowerCase(),
        url: String(content.url || content.download_url || content.view_url || content.file_registry?.url || content.file_registry?.download_url || uploadStorageRefToBrowserUrl(content.storage_ref || content.model_storage_ref || content.file_registry?.storage_ref || content.file_registry?.model_storage_ref, 'download') || '').trim(),
        view_url: String(content.view_url || content.url || content.file_registry?.view_url || uploadStorageRefToBrowserUrl(content.storage_ref || content.model_storage_ref || content.file_registry?.storage_ref || content.file_registry?.model_storage_ref, 'view') || '').trim(),
        download_url: String(content.download_url || content.url || content.view_url || content.file_registry?.download_url || content.file_registry?.url || uploadStorageRefToBrowserUrl(content.storage_ref || content.model_storage_ref || content.file_registry?.storage_ref || content.file_registry?.model_storage_ref, 'download') || '').trim(),
        storage_ref: String(content.storage_ref || content.model_storage_ref || content.file_registry?.storage_ref || content.file_registry?.model_storage_ref || '').trim(),
        model_storage_ref: String(content.model_storage_ref || content.storage_ref || content.file_registry?.model_storage_ref || content.file_registry?.storage_ref || '').trim(),
        full_text_ref: String(content.full_text_ref || content.file_registry?.full_text_ref || '').trim(),
        size: Number(content.size || content.file_registry?.size || 0) || 0,
        note: String(content.note || '').trim(),
        text_is_preview: !!content.text_is_preview,
        full_text_available: !!content.full_text_available || !!content.file_registry?.full_text_available,
        parsed_chars: Number(content.parsed_chars || content.file_registry?.full_text_chars || 0) || 0,
        parsed_lines: Number(content.parsed_lines || content.file_registry?.full_text_lines || 0) || 0,
        file_registry: content.file_registry || null,
        code_summary: String(content.code_summary || content.file_registry?.summary || '').trim(),
        symbols: Array.isArray(content.symbols) ? content.symbols : (Array.isArray(content.file_registry?.symbols) ? content.file_registry.symbols : []),
        edited_from: (content.edited_from && typeof content.edited_from === 'object') ? content.edited_from : null,
        edit_audit: (content.edit_audit && typeof content.edit_audit === 'object') ? content.edit_audit : null,
        edit_details: (content.edit_details && typeof content.edit_details === 'object') ? content.edit_details : null,
      };
    }

    function collectFileAttachmentsForRequest(session, maxItems=24, opts={}){
      // Only send files that the user attached/selected for this turn.
      // Historical generated/uploaded files remain in messages for explicit lookup,
      // but they must not be re-sent as active payload candidates on every turn;
      // otherwise vague prompts like “这个怎么样” can bind to an old file.
      const out = [];
      const seen = new Set();
      const markCurrentTurn = (item, source)=>({
        _kind:'file',
        ...item,
        _current_turn_attachment:true,
        current_turn:true,
        turn_scope:'current_turn',
        request_scope:'current_turn',
        selection_source: source || item?.selection_source || item?.operation || 'composer',
      });
      const pushOne = (item, source)=>{
        const normalized = normalizeFileAttachmentForRequest(markCurrentTurn(item || {}, source));
        if(!normalized) return;
        normalized._current_turn_attachment = true;
        normalized.current_turn = true;
        normalized.turn_scope = 'current_turn';
        normalized.request_scope = 'current_turn';
        normalized.selection_source = String(source || normalized.selection_source || 'composer').trim() || 'composer';
        const key = [normalized.id, normalized.file_registry?.file_id, normalized.storage_ref, normalized.model_storage_ref, normalized.download_url, normalized.url, normalized.filename].map(x=>String(x||'').trim()).find(Boolean) || normalized.filename;
        const k = String(key || '').toLowerCase();
        if(!k || seen.has(k)) return;
        seen.add(k);
        out.push(normalized);
      };
      for(const item of (Array.isArray(opts?.currentUserFileAttachments) ? opts.currentUserFileAttachments : [])){
        pushOne(item, 'current_user_message');
      }
      try{
        const draftPayload = getComposerAttachmentDraft(opts?.sessionId || session?.id || store?.activeId);
        for(const file of (Array.isArray(draftPayload.files) ? draftPayload.files : [])){
          pushOne(normalizeComposerAttachmentDraftFile(file), 'composer_draft');
        }
      }catch(_){ }
      return out.slice(-Math.max(1, Number(maxItems || 24) || 24));
    }




function collectConversationImageAssetsForRequest(sessionId, session, opts={}){
  const sid = String(sessionId || session?.id || '').trim();
  const s = session && typeof session === 'object' ? session : {};
  const localImgMap = opts?.localImgMap instanceof Map ? opts.localImgMap : new Map();
  const maxItems = Math.max(1, Math.min(Number(opts?.maxItems || 16) || 16, 24));
  const out = [];
  const seen = new Set();
  const pushReply = (raw, source='')=>{
    if(!raw || typeof raw !== 'object') return;
    if(isImageSearchReplyPayload(raw)) return;
    let normalized = null;
    try{ normalized = normalizeImageReplyForModelRequest(raw); }catch(_){ normalized = null; }
    if(!normalized || !Array.isArray(normalized.images) || !normalized.images.length) return;
    const cleanImages = [];
    for(const image of normalized.images){
      if(!image || typeof image !== 'object') continue;
      const img = { ...image };
      let url = String(img.url || img.raw_url || img.view_url || img.download_url || img.preview_url || '').trim();
      if(url.startsWith('local://')){
        const id = url.slice('local://'.length);
        const dataUrl = localImgMap.get(id);
        if(dataUrl) url = dataUrl;
      }
      if(url) img.url = url;
      const modelKey = String(img.model_storage_ref || img.storage_ref || img.raw_url || img.view_url || img.download_url || img.preview_url || img.url || img.image_id || img.attachment_id || '').trim();
      if(!modelKey) continue;
      cleanImages.push(img);
    }
    if(!cleanImages.length) return;
    normalized.images = cleanImages;
    normalized._kind = 'image_reply';
    normalized.source = String(normalized.source || raw.source || 'image_generation').trim() || 'image_generation';
    normalized.source_role = 'assistant';
    normalized._asset_source = String(source || '').trim();
    const sig = imageReplySignature(normalized) || cleanImages.map(img => String(img.model_storage_ref || img.storage_ref || img.raw_url || img.view_url || img.download_url || img.preview_url || img.url || img.image_id || '').trim()).filter(Boolean).join('|');
    if(!sig || seen.has(sig)) return;
    seen.add(sig);
    out.push(normalized);
  };

  const msgs = Array.isArray(s.messages) ? s.messages : [];
  for(const msg of msgs){
    if(!msg || String(msg.role || '').trim().toLowerCase() !== 'assistant') continue;
    const content = msg.content;
    if(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply') pushReply(content, 'message.content');
    const imageReplies = [
      ...(Array.isArray(msg.imageReplies) ? msg.imageReplies : []),
      ...(Array.isArray(msg.image_replies) ? msg.image_replies : []),
    ];
    for(const item of imageReplies) pushReply(item, 'message.imageReplies');
  }

  try{
    const rt = ensureSessionRuntime(sid);
    for(const item of (Array.isArray(rt?.draftImageReplies) ? rt.draftImageReplies : [])) pushReply(item, 'runtime.draftImageReplies');
  }catch(_){ }
  for(const item of (Array.isArray(s.pendingAssistantImageReplies) ? s.pendingAssistantImageReplies : [])) pushReply(item, 'session.pendingAssistantImageReplies');
  try{
    const snap = pendingAssistantSnapshotForSession(sid, store);
    for(const item of (Array.isArray(snap?.imageReplies) ? snap.imageReplies : [])) pushReply(item, 'pendingSnapshot.imageReplies');
  }catch(_){ }

  return out.slice(-maxItems);
}

async function buildAsyncChatRequestBodyForSession(sessionId, opts){
  const o = opts || {};
  const text = String(o.text || '');
  const localImgMap = o.localImgMap instanceof Map ? o.localImgMap : new Map();
  const currentUserImageUploadsForSandbox = Array.isArray(o.currentUserImageUploadsForSandbox) ? o.currentUserImageUploadsForSandbox : [];
  const s = getSessionById(sessionId);
  if(!s) throw new Error("会话不存在或已被删除");

  const geoSettingEnabled = isBrowserGeoSettingEnabled();
  let userGeo = null;
  let geoSourceForDebug = "none";
  let geoAttachMode = geoSettingEnabled ? "no_cached_geo" : "setting_disabled";

  if(geoSettingEnabled && _geoCache && (Date.now() - _geoCacheAt) < USER_GEO_MEMORY_TTL_MS){
    userGeo = _geoCache;
    geoAttachMode = "memory_cache";
  }else if(geoSettingEnabled){
    const storedGeoForContext = loadPersistedUserGeo();
    if(storedGeoForContext){
      userGeo = storedGeoForContext;
      _geoCache = storedGeoForContext;
      _geoCacheAt = Number(storedGeoForContext.acquired_at || Date.now());
      geoAttachMode = "stored_context";
    }
  }
  if(userGeo) geoSourceForDebug = String(userGeo.source || geoAttachMode || "cached_context");

  const geoPermissionState = await queryBrowserGeoPermissionStateSafe();
  if(!userGeo && geoSettingEnabled && canUseBrowserGeoNow() && geoPermissionState !== 'denied'){
    try{
      const freshGeo = await getUserGeoCached({ preferFresh:true, allowStored:true, quick:true, forChatRequest:true });
      if(freshGeo){
        userGeo = freshGeo;
        geoAttachMode = 'browser_request';
        geoSourceForDebug = String(freshGeo.source || geoAttachMode || 'browser_request');
      }else if(_lastGeoErrorMeta && typeof _lastGeoErrorMeta === 'object'){
        const reason = String(_lastGeoErrorMeta.reason || '').trim();
        geoAttachMode = reason ? ('request_failed:' + reason) : 'request_failed';
      }
    }catch(_){
      if(_lastGeoErrorMeta && typeof _lastGeoErrorMeta === 'object'){
        const reason = String(_lastGeoErrorMeta.reason || '').trim();
        geoAttachMode = reason ? ('request_failed:' + reason) : 'request_failed';
      }
    }
  }

  const locationState = buildRuntimeLocationStatePayload({
    userGeo,
    geoAttachMode,
    permissionState: geoPermissionState,
  });
  if(userGeo && isBrowserGeoOneShotActive() && !isBrowserGeoPersistentlyEnabled()){
    _browserGeoOneShotUntil = 0;
  }

  console.log("[DEBUG_GEO_SEND]", {
    text,
    webEnabled: !!s.webEnabled,
    geoSettingEnabled,
    semanticGeoPrefetchDisabled: true,
    geoAttachMode,
    finalUserGeo: userGeo,
    geoSourceForDebug,
    locationState,
  });

  try{ webaiOfficialNormalizeActiveSession(s, { skipIfLive:true }); }catch(_){ }
  const messages2 = JSON.parse(JSON.stringify(buildMessagesForRequest(s, { maxMessageIndex: o.maxMessageIndex })));
  preserveHistoricalFileAttachmentsForRequest(messages2, s.messages);
  stripPromptCacheRequestOnlyMessageMeta(messages2);
  if(Array.isArray(o.extraRequestMessages) && o.extraRequestMessages.length){
    for(const item of o.extraRequestMessages){
      const clean = sanitizeMessageForModelRequest(item);
      if(clean) messages2.push(clean);
    }
  }

  const blobToDataUrlForRequest = (blob)=> new Promise((resolve)=>{
    try{
      if(!blob) return resolve('');
      const reader = new FileReader();
      reader.onload = ()=> resolve(String(reader.result || ''));
      reader.onerror = ()=> resolve('');
      reader.readAsDataURL(blob);
    }catch(_){
      resolve('');
    }
  });

  const hydrateRequestImagePartForBackend = async (part)=>{
    if(!part || typeof part !== 'object' || part.type !== 'image_url') return false;
    let raw = '';
    if(part.image_url && typeof part.image_url === 'object') raw = String(part.image_url.url || '').trim();
    else raw = String(part.image_url || part.url || '').trim();
    if(!raw) return false;
    let resolved = raw;
    if(raw.startsWith('local://')){
      const localId = raw.slice('local://'.length);
      resolved = String(localImgMap.get(localId) || '').trim();
      if(!resolved && typeof idbImgGet === 'function'){
        try{
          const blob = await idbImgGet(localId);
          resolved = await blobToDataUrlForRequest(blob);
        }catch(_){
          resolved = '';
        }
      }
    }else if(raw.startsWith('blob:')){
      const preview = String(part._preview_url || part.preview_url || part.persisted_url || part.server_url || part._source_url || '').trim();
      if(preview && !preview.startsWith('blob:') && !preview.startsWith('local://')) resolved = preview;
    }
    if(!resolved || resolved.startsWith('local://') || resolved.startsWith('blob:')) return false;
    if(!part.image_url || typeof part.image_url !== 'object') part.image_url = { url: resolved };
    else part.image_url.url = resolved;
    if(!String(part.url || '').trim()) part.url = resolved;
    if(!String(part._source_url || '').trim()) part._source_url = raw;
    return true;
  };

  const hydrateRequestMessageImagesForBackend = async (msgs, maxImages=8)=>{
    let remaining = Math.max(1, Math.min(Number(maxImages || 8) || 8, 16));
    const list = Array.isArray(msgs) ? msgs : [];
    for(let mi = list.length - 1; mi >= 0 && remaining > 0; mi--){
      const msg = list[mi];
      if(!msg || !Array.isArray(msg.content)) continue;
      for(let pi = msg.content.length - 1; pi >= 0 && remaining > 0; pi--){
        const part = msg.content[pi];
        if(!part || part.type !== 'image_url') continue;
        const ok = await hydrateRequestImagePartForBackend(part);
        if(ok) remaining -= 1;
      }
    }
  };

  await hydrateRequestMessageImagesForBackend(messages2, 8);

  const requestImageAssets = collectConversationImageAssetsForRequest(sessionId, s, { localImgMap, maxItems: 16 });
  try{
    if(requestImageAssets.length){
      console.log('[DEBUG_IMAGE_ASSETS_CONTEXT_SEND]', {
        sessionId,
        count: requestImageAssets.length,
        labels: requestImageAssets.map(item => String(item?.subject || item?.text || item?.images?.[0]?.filename || '').trim()).filter(Boolean).slice(0, 8),
        images: requestImageAssets.flatMap((item, replyIdx) => (Array.isArray(item?.images) ? item.images : []).map((img, imgIdx) => ({
          reply_index: replyIdx + 1,
          image_index: imgIdx + 1,
          image_id: String(img?.image_id || img?.attachment_id || '').trim(),
          source_role: String(img?.source_role || item?.source_role || '').trim(),
          source_type: String(img?.source_type || item?.source_type || '').trim(),
          operation: String(img?.operation || img?.task_mode || item?.operation || item?.task_mode || '').trim(),
          model_storage_ref: String(img?.model_storage_ref || '').trim(),
          storage_ref: String(img?.storage_ref || '').trim(),
          file_library_id: String(img?.file_library_id || img?.library_file_id || '').trim(),
          url_kind: String(img?.url || '').startsWith('data:image/') ? 'data_url' : (String(img?.url || '').startsWith('local://') ? 'local' : (String(img?.url || '').startsWith('upload://') ? 'storage_ref' : (String(img?.url || '').startsWith('http') ? 'http' : (String(img?.url || '') ? 'other' : '')))),
          raw_kind: String(img?.raw_url || '').startsWith('data:image/') ? 'data_url' : (String(img?.raw_url || '').startsWith('upload://') ? 'storage_ref' : (String(img?.raw_url || '').startsWith('http') ? 'http' : (String(img?.raw_url || '') ? 'other' : ''))),
        }))).slice(0, 16),
      });
    }
  }catch(_){ }

  for(const m of messages2){
    const c = m?.content;
    if(c && typeof c === "object" && !Array.isArray(c)){
      if(c._kind === "genfiles" || c._kind === "file"){
        // 保留结构化文件对象给后端，后端会统一建立“上传/生成文件”轻量索引和按需回看片段。
      }else if(c._kind === "image_reply"){
        // Keep generated assistant images as a structured image-reply record so
        // the backend can index them on the next turn. Do not collapse them to
        // plain text here, otherwise follow-ups like “这个图怎么样 / 继续改这张”
        // cannot reliably bind to the generated image.
        m.content = normalizeImageReplyForModelRequest(c);
      }else if(c._kind && c._kind !== "image"){
        try{ m.content = JSON.stringify(c); }catch(e){ m.content = String(c._kind); }
      }
    }
    if(c && typeof c === "object" && !Array.isArray(c) && c._kind === "image"){
      const tag = "[图片附件]";
      const name = c.filename ? ` ${c.filename}` : "";
      m.content = `${tag}${name}`;
    }
    if(Array.isArray(c)){
      m.content = c.filter(p => {
        if(!(p && p.type === "image_url")) return true;
        const raw = String((p.image_url && typeof p.image_url === 'object' ? p.image_url.url : p.image_url) || p.url || '').trim();
        return !!raw && !raw.startsWith('local://') && !raw.startsWith('blob:');
      });
    }
  }

  const kbUi = typeof getKnowledgeBaseUiSettings === 'function' ? getKnowledgeBaseUiSettings() : { chatUseKnowledgeBase:true, activeSpaceId:'', activeDocId:'' };

  const requestMessages = messages2;
  const requestFileAttachments = collectFileAttachmentsForRequest(s, 24, { sessionId, currentUserFileAttachments: o.currentUserFileAttachments || [] });
  const isSandboxImportableImageSource = (value)=>{
    const raw = String(value || '').trim();
    if(!raw) return false;
    const low = raw.toLowerCase();
    if(low.startsWith('data:') || low.startsWith('blob:') || low.startsWith('local://')) return false;
    if(low.startsWith('upload://')) return true;
    if(/^\/api3\/(?:uploads|download)\//i.test(raw)) return true;
    try{
      const u = new URL(raw, window.location.origin);
      return u.origin === window.location.origin && /^\/api3\/(?:uploads|download)\//i.test(u.pathname || '');
    }catch(_){
      return false;
    }
  };
  const pushCurrentUserImageAsSandboxFile = (img, index)=>{
    if(!img || typeof img !== 'object') return;
    const reg = img.file_registry && typeof img.file_registry === 'object' ? img.file_registry : {};
    const filename = String(img.filename || reg.filename || reg.saved_filename || `user_upload_image_${index}.png`).trim();
    const storageRef = String(img.model_storage_ref || img.storage_ref || reg.model_storage_ref || reg.storage_ref || '').trim();
    const registryFileId = String(img.file_library_id || img.library_file_id || reg.file_id || '').trim();
    const viewCandidates = [
      uploadStorageRefToBrowserUrl(storageRef, 'view'),
      img.view_url, img.server_url, img.persisted_url, reg.view_url, reg.url,
      img.image_url?.url,
    ];
    const downloadCandidates = [
      uploadStorageRefToBrowserUrl(storageRef, 'download'),
      img.download_url, reg.download_url, reg.url,
      img.server_url, img.persisted_url, img.view_url,
    ];
    const viewUrl = String(viewCandidates.find(isSandboxImportableImageSource) || '').trim();
    const downloadUrl = String(downloadCandidates.find(isSandboxImportableImageSource) || viewUrl || '').trim();
    const hasImportableIdentity = !!(storageRef.toLowerCase().startsWith('upload://') || registryFileId || viewUrl || downloadUrl);
    if(!hasImportableIdentity){
      try{
        console.warn('[DEBUG_SANDBOX_USER_UPLOAD_IMAGE_FILE_SKIPPED]', {
          filename,
          reason:'no_importable_identity',
          has_storage_ref: !!storageRef,
          has_registry_file_id: !!registryFileId,
          note:'skip local-only attachment_id/image_id; sandbox needs real storage_ref/file id/url',
          raw_url_kind: String(img.image_url?.url || img.view_url || img.server_url || img.persisted_url || '').startsWith('blob:') ? 'blob' : (String(img.image_url?.url || img.view_url || img.server_url || img.persisted_url || '').startsWith('local://') ? 'local' : (String(img.image_url?.url || img.view_url || img.server_url || img.persisted_url || '').startsWith('data:') ? 'data' : 'other'))
        });
      }catch(_){ }
      return;
    }
    const ext = String(img.ext || reg.ext || (filename.includes('.') ? filename.split('.').pop() : '') || '').replace(/^\./, '').toLowerCase();
    const normalizedFileMsg = normalizeFileAttachmentForRequest({
      _kind:'file',
      id: registryFileId,
      file_library_id: String(img.file_library_id || img.library_file_id || reg.file_id || '').trim(),
      library_file_id: String(img.library_file_id || img.file_library_id || reg.file_id || '').trim(),
      registry_file_id: String(reg.file_id || img.file_library_id || img.library_file_id || '').trim(),
      source_type:'upload',
      source_role:'user_upload',
      filename,
      ext,
      url: downloadUrl || viewUrl,
      view_url: viewUrl,
      download_url: downloadUrl || viewUrl,
      storage_ref: storageRef,
      model_storage_ref: storageRef,
      size: Number(img.size || reg.size || 0) || 0,
      note:'sandbox_current_turn_user_upload_image',
      file_registry: reg && Object.keys(reg).length ? reg : null,
      code_summary: String(img._ocr_text || reg.summary || '').trim(),
      _current_turn_attachment:true,
      current_turn:true,
      turn_scope:'current_turn',
      request_scope:'current_turn',
      selection_source:'current_user_image',
    });
    if(!normalizedFileMsg) return;
    const key = [normalizedFileMsg.id, normalizedFileMsg.file_registry?.file_id, normalizedFileMsg.storage_ref, normalizedFileMsg.download_url, normalizedFileMsg.url, normalizedFileMsg.filename].map(x=>String(x||'').trim()).find(Boolean) || normalizedFileMsg.filename;
    const exists = requestFileAttachments.some(x => {
      const xkey = [x.id, x.file_registry?.file_id, x.storage_ref, x.download_url, x.url, x.filename].map(v=>String(v||'').trim()).find(Boolean) || x.filename;
      return String(xkey || '').toLowerCase() === String(key || '').toLowerCase();
    });
    if(!exists) requestFileAttachments.push(normalizedFileMsg);
  };
  currentUserImageUploadsForSandbox.forEach((img, idx) => pushCurrentUserImageAsSandboxFile(img, idx + 1));
  try{
    const draftPayload = getComposerAttachmentDraft(sessionId);
    for(const file of (Array.isArray(draftPayload.files) ? draftPayload.files : [])){
      const normalizedFileMsg = normalizeFileAttachmentForRequest({ _kind:'file', ...normalizeComposerAttachmentDraftFile(file), _current_turn_attachment:true, current_turn:true, turn_scope:'current_turn', request_scope:'current_turn', selection_source:'composer_draft' });
      if(!normalizedFileMsg) continue;
      const key = [normalizedFileMsg.id, normalizedFileMsg.file_registry?.file_id, normalizedFileMsg.download_url, normalizedFileMsg.url, normalizedFileMsg.filename].map(x=>String(x||'').trim()).find(Boolean) || normalizedFileMsg.filename;
      const exists = requestFileAttachments.some(x => {
        const xkey = [x.id, x.file_registry?.file_id, x.download_url, x.url, x.filename].map(v=>String(v||'').trim()).find(Boolean) || x.filename;
        return String(xkey || '').toLowerCase() === String(key || '').toLowerCase();
      });
      if(!exists) requestFileAttachments.push(normalizedFileMsg);
    }
  }catch(_){ }
  try{
    console.log('[DEBUG_FILE_ATTACHMENTS_SEND]', {
      sessionId,
      messages: requestMessages.length,
      fileCount: requestFileAttachments.length,
      files: requestFileAttachments.map(f=>({
        filename: f.filename,
        id: f.id || f.file_registry?.file_id || '',
        source_role: f.source_role || '',
        source_type: f.source_type || '',
        ext: f.ext,
        full_text_available: !!f.full_text_available || !!f.file_registry?.full_text_available,
        parsed_chars: f.parsed_chars || f.file_registry?.full_text_chars || 0,
        symbols: Array.isArray(f.symbols) ? f.symbols.length : (Array.isArray(f.file_registry?.symbols) ? f.file_registry.symbols.length : 0),
        symbol_sample: (Array.isArray(f.symbols) ? f.symbols : (Array.isArray(f.file_registry?.symbols) ? f.file_registry.symbols : [])).slice(0, 12).map(x=>x && (x.name || x.kind || x.line) ? `${x.kind || ''}:${x.name || ''}@${x.line || ''}` : String(x || ''))
      }))
    });
  }catch(_e){}

  const temporaryChat = isTemporarySession(s);
  return {
    model:s.model,
    messages:requestMessages,
    file_attachments: requestFileAttachments,
    image_assets: requestImageAssets,
    show_steps:true,
    temporary_chat: temporaryChat,
    temporaryChat: temporaryChat,
    user_geo:userGeo,
    location_state: locationState,
    user_time:buildRuntimeTimePayload(),
    kb_enabled: kbUi.chatUseKnowledgeBase !== false,
    kb_space_id: String(kbUi.activeSpaceId || '').trim(),
    kb_doc_id: String(kbUi.activeDocId || '').trim(),
    debug_geo_meta:{
      text,
      web_enabled: !!s.webEnabled,
      image_generation_enabled: !!s.imageGenerationEnabled,
      is_weather_query: null,
      is_location_query: null,
      is_weather_followup: null,
      browser_geo_enabled: geoSettingEnabled,
      need_fresh_geo: false,
      geo_source: geoSourceForDebug,
      geo_attach_mode: geoAttachMode,
      semantic_geo_prefetch_disabled: true,
      recent_weather_geo: null,
      browser_geo: getGeoRuntimeDebugMeta(),
      location_state: locationState
    },
    web_enabled: !!s.webEnabled,
    image_generation_enabled:!!s.imageGenerationEnabled,
    client_session_id: String(sessionId || ''),
    client_session_title: String(s.title || ''),
    client_turn_id: (typeof stableAsyncChatTurnIdForSession === 'function' ? stableAsyncChatTurnIdForSession(sessionId, s) : ''),
    runtime_model: String((String(s.runtimeModelSourceModel || s.runtime_model_source_model || '').trim() === String(s.model || '').trim()) ? (s.runtimeModel || s.runtime_model || '') : '').trim(),
    ...getRequestSettings(s.model)
  };
}

function normalizeAssistantContinuationTarget(value){
  const raw = value && typeof value === 'object' ? value : null;
  if(!raw) return null;
  const messageIndex = Number(raw.messageIndex);
  const baseText = String(raw.baseText || '').trim();
  const messageId = String(raw.messageId || raw.localId || raw.local_id || '').trim();
  if((!Number.isInteger(messageIndex) || messageIndex < 0) && !messageId) return null;
  if(!baseText) return null;
  return { messageIndex: Number.isInteger(messageIndex) && messageIndex >= 0 ? messageIndex : null, messageId, baseText };
}

function setAsyncSessionStatus(sessionId, txt, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  const raw = String(txt ?? '');
  const fileStage = !!opts.fileStage || _isFileGenerationStatusText(raw);
  if(!opts.skipReasoning && !fileStage) pushSessionRuntimeReasoningStatus(sid, raw);
  if(fileStage) finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
  const nice = normalizeStreamStatusText(raw);
  setSessionRuntimeStatus(sid, nice);
  if(opts.present !== false){
    if(isSessionVisibleInMainView(sid)){
      const otherCount = getOtherStreamingSessionIds(sid).length;
      setStatus(otherCount>0?(window.AperviaI18n?.t('stream.other_sessions',{status:nice,count:otherCount})||`${nice} (${otherCount} other conversations in progress)`):nice);
      if(opts.syncDraft !== false) syncVisibleDraftBubble(sid);
    }else{
      refreshStatusForActiveSession();
    }
  }
  return { sid, raw, nice, fileStage };
}

async function attachSessionToAsyncJob(sessionId, opts){
  const o = opts || {};
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  const existingPromise = getSessionPromise(sid);
  if(existingPromise) return existingPromise;
  const continuationTarget = normalizeAssistantContinuationTarget(o.assistantContinuationTarget || o.continuationTarget || null);

  const isViewingStreamSession = ()=> isSessionVisibleInMainView(sid);
  const isActiveSession = ()=> String(store?.activeId || '').trim() === sid;
  const composeAssistantContinuationText = (baseText, addText)=>{
    const base = String(baseText || '');
    const add = String(addText || '');
    if(!add) return base;
    if(base && add.startsWith(base)) return add;
    const trimmedAdd = add.replace(/^\s+/, '');
    if(!base) return trimmedAdd || add;
    const spacer = /\n\s*$/.test(base) ? '' : '\n\n';
    return base + spacer + (trimmedAdd || add);
  };
  const findAssistantContinuationMessage = (session)=>{
    const rows = Array.isArray(session?.messages) ? session.messages : [];
    const identity = String(continuationTarget?.messageId || '').trim();
    if(identity){
      const found = rows.findIndex(m => {
        if(!m || String(m.role || '').toLowerCase() !== 'assistant') return false;
        const mid = String((typeof messageStableClientIdentity === 'function' ? messageStableClientIdentity(m) : '') || m.localId || m.local_id || m.messageLocalId || m.message_local_id || '').trim();
        return mid && mid === identity;
      });
      if(found >= 0) return { msg: rows[found], index: found };
    }
    const idx = Number(continuationTarget?.messageIndex);
    if(Number.isInteger(idx) && idx >= 0 && rows[idx] && String(rows[idx].role || '').toLowerCase() === 'assistant'){
      return { msg: rows[idx], index: idx };
    }
    return null;
  };
  const patchAssistantContinuationTargetDraft = (draftText, opts={})=>{
    if(!continuationTarget || !isViewingStreamSession()) return null;
    const session = getSessionById(sid);
    const target = findAssistantContinuationMessage(session);
    if(!target || !target.msg) return null;
    const finalText = composeAssistantContinuationText(continuationTarget.baseText, draftText);
    const idx = target.index;
    let bubble = null;
    try{
      bubble = chatEl?.querySelector?.(`.bubble[data-msg-index="${idx}"]`) || null;
    }catch(_){ bubble = null; }
    if(!bubble) return null;
    const nextMsg = {
      ...(target.msg || {}),
      content: finalText,
      sources: opts.sources || target.msg.sources,
      imageReplies: opts.imageReplies || target.msg.imageReplies,
      weather: opts.weatherPayload || target.msg.weather,
      generationUsage: opts.generationUsage || target.msg.generationUsage || target.msg.generation_usage,
    };
    const fresh = buildBubbleNode('assistant', finalText, {
      sessionId: sid,
      message: nextMsg,
      messageIndex: idx,
      processText: String(opts.processText || ''),
    });
    try{
      fresh.classList.add('bubble-continuation-draft');
      if(opts.done) fresh.classList.remove('bubble-continuation-draft');
      bubble.replaceWith(fresh);
      bindBubbleEnhancements(fresh);
      return fresh;
    }catch(_){
      return null;
    }
  };
  let edgeStreamImageReplyVisible = false;
  const removeEmptyVisibleDraftBubbleAfterEdgeImageReply = ()=>{
    const bubble = getVisibleDraftBubble(sid);
    if(!bubble?.querySelector) return false;
    const rtNow = ensureSessionRuntime(sid);
    if(String(rtNow?.draftText || '').trim()) return false;
    if(String(rtNow?.draftProcessText || '').trim()) return false;
    const body = bubble.querySelector('.bubble-body');
    if(!body) return false;
    const hasContentNode = !!body.querySelector(':scope > .reasoning-answer-wrap, :scope > .mcp-chat-stack, :scope > .assistant-image-replies, :scope > .image-generation-stage, :scope > .structured-text-block, :scope > .generated-files-card, :scope > .weather-card');
    const hasReasoningNode = !!body.querySelector(':scope > .activity-inline-trigger-wrap, :scope > .reasoning-panels, :scope > .reasoning-panel');
    if(hasContentNode || hasReasoningNode) return false;
    bubble.remove();
    if(liveDraftBubbleEls[sid] === bubble) delete liveDraftBubbleEls[sid];
    return true;
  };
  const shouldSuppressEmptyDraftForEdgeImageReply = (opts={})=>{
    if(!edgeStreamImageReplyVisible) return false;
    if(opts.fileStage) return false;
    const rtNow = ensureSessionRuntime(sid);
    if(String(rtNow?.draftText || '').trim()) return false;
    if(String(rtNow?.draftProcessText || '').trim()) return false;
    return _normalizePendingAssistantImageReplies(rtNow?.draftImageReplies || []).length > 0;
  };
  const inferEdgeImageReplySource = (payload)=>{
    const data = payload && typeof payload === 'object' ? payload : {};
    const explicit = String(data.source || data.kind || data.intent || data.visual_intent || data.source_type || '').trim();
    if(explicit) return explicit;
    const images = Array.isArray(data.images) ? data.images : [];
    const hasSearchDeliveryMeta = images.some(item => item && typeof item === 'object' && String(item.source_url || item.sourceUrl || item.page_url || item.pageUrl || '').trim());
    const hasGeneratedDeliveryMeta = images.some(item => item && typeof item === 'object' && String(item.view_url || item.viewUrl || item.download_url || item.downloadUrl || item.preview_url || item.previewUrl || item.attachment_id || item.attachmentId || item.provider_url || item.providerUrl || '').trim());
    return hasSearchDeliveryMeta && !hasGeneratedDeliveryMeta ? 'image_search' : '';
  };
  const setStatusForSession = (txt, opts={})=>{
    const statusState = setAsyncSessionStatus(sid, txt, { ...opts, present:false });
    if(!statusState) return;
    const { nice, fileStage } = statusState;
    if(isViewingStreamSession()){
      const otherCount = getOtherStreamingSessionIds(sid).length;
      setStatus(otherCount>0?(window.AperviaI18n?.t('stream.other_sessions',{status:nice,count:otherCount})||`${nice} (${otherCount} other conversations in progress)`):nice);
      if(continuationTarget){
        patchAssistantContinuationTargetDraft(current);
        return;
      }
      const terminalFinalAlreadyVisible = !!terminalSeen && !!finalizedVisibleDraft;
      const rtNow = ensureSessionRuntime(sid);
      const shouldSkipTerminalEmptyDraft = !!opts.terminalStatus && !sessionRuntimeHasVisibleDraftContent(rtNow);
      const shouldSkipSavedAssistantEmptyDraft = sessionLastVisibleMessageIsAssistant(sid) && !sessionRuntimeHasVisibleDraftContent(rtNow);
      if(shouldSkipTerminalEmptyDraft || shouldSkipSavedAssistantEmptyDraft){
        removeVisibleDraftBubbleForSession(sid);
        return;
      }
      if(!terminalFinalAlreadyVisible && !String(rtNow?.draftText || "").trim()){
        if(shouldSuppressEmptyDraftForEdgeImageReply({ ...opts, fileStage })){
          removeEmptyVisibleDraftBubbleAfterEdgeImageReply();
        }else{
          syncVisibleDraftBubble(sid);
        }
      }
    }else refreshStatusForActiveSession();
  };
  const refreshStreamDraftForSession = ()=>{
    try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(sid); }catch(_){ }
    if(isViewingStreamSession()){
      if(continuationTarget) patchAssistantContinuationTargetDraft(current);
      else syncVisibleDraftBubble(sid);
    }
  };

  const _isResumeSession = !!String(o.resumeJobId || '').trim() || !!o.isResume;
  let current = _isResumeSession ? String(ensureSessionRuntime(sid)?.draftText || getSessionById(sid)?.pendingAssistantDraft || "") : "";
  let renderBuffer = "";
  let renderTimer = null;
  let renderFrameId = 0;
  let _firstTokenAt = current.trim() ? Date.now() : 0;
  let _receivedAssistantTextThisRun = false;
  const shouldKeepCurrentDraftOnTerminalError = ()=> !!String(current || '').trim() && (_isResumeSession || _receivedAssistantTextThisRun || !!_firstTokenAt);
  let _weatherPayload = null;
  let _assistantSources = _isResumeSession
    ? normalizeAssistantSourceItems(ensureSessionRuntime(sid)?.sources || getSessionById(sid)?.pendingAssistantSources || [])
    : [];
  ensureSessionRuntime(sid).sources = _assistantSources;
  let _generationUsage = _isResumeSession
    ? normalizeAssistantUsagePayload(ensureSessionRuntime(sid)?.generationUsage || null)
    : null;
  ensureSessionRuntime(sid).generationUsage = _generationUsage;
  let _imageReplyPayloads = _normalizePendingAssistantImageReplies(ensureSessionRuntime(sid)?.draftImageReplies || getSessionById(sid)?.pendingAssistantImageReplies || []);
  let _imageReplySignatureSet = new Set(_imageReplyPayloads.map(item => imageReplySignature(item)).filter(Boolean));
  let _genFiles = Array.isArray(ensureSessionRuntime(sid)?.draftFiles) ? [...ensureSessionRuntime(sid).draftFiles] : [];
  let _latestVisibleFileProcessText = '';
  let _memoryEvents = [];
  let _runtimeModel = String(getSessionById(sid)?.runtimeModel || getSessionById(sid)?.runtime_model || '').trim();
  let _savedFilesMsg = false;
  let savedAssistant = false;
  let terminalSeen = false;
  let finalizedVisibleDraft = false;
  let placeholder = null;
  let imagePullbackSoftTimedOut = false;
  let imagePullbackStopPolling = false;
  let imagePullbackTimer = null;
  let imagePullbackSoftTimeoutMs = 180000;
  let imagePullbackSourceJobId = String(o.resumeJobId || '').trim();
  let activeEventJobId = String(o.resumeJobId || '').trim();
  let imagePullbackContinuationRequest = null;
  let imagePullbackContinueAfterHandoff = false;
  let suppressTextForGeneratedImageReply = false;
  let activeStartController = null;
  let activePollController = null;

  const clearImagePullbackSoftTimer = ()=>{
    if(imagePullbackTimer){
      clearTimeout(imagePullbackTimer);
      imagePullbackTimer = null;
    }
  };
  const resetSessionRuntimeAfterPullback = ()=>{
    const rt = ensureSessionRuntime(sid);
    rt.draftText = "";
    rt.statusText = "";
    rt.draftProcessText = "";
    rt.draftFiles = [];
    rt.draftImageReplies = [];
    rt.draftWeatherPayload = null;
    rt.reasoning = [];
    rt.reasoningMeta = {};
    rt.sources = [];
    rt.streaming = false;
  };
  const imagePullbackPromptFromRequest = ()=>{
    const rb = (o.requestBody && typeof o.requestBody === 'object') ? o.requestBody : {};
    const msgs = Array.isArray(rb.messages) ? rb.messages : [];
    for(let i = msgs.length - 1; i >= 0; i--){
      const msg = msgs[i] || {};
      if(String(msg.role || '').toLowerCase() !== 'user') continue;
      const c = msg.content;
      if(typeof c === 'string' && c.trim()) return c.trim().slice(0, 1000);
      if(Array.isArray(c)){
        const parts = c.map(part => part && part.type === 'text' ? String(part.text || '').trim() : '').filter(Boolean);
        if(parts.length) return parts.join('\\n').trim().slice(0, 1000);
      }
    }
    return String(getSessionById(sid)?.title || '').trim().slice(0, 1000);
  };
  const buildImagePullbackContinuationRequest = ()=>{
    const rb = (o.requestBody && typeof o.requestBody === 'object') ? o.requestBody : null;
    if(!rb) return null;
    let nextBody = null;
    try{ nextBody = JSON.parse(JSON.stringify(rb)); }catch(_){ nextBody = null; }
    if(!nextBody || typeof nextBody !== 'object') return null;
    const nextMessages = Array.isArray(nextBody.messages) ? nextBody.messages.filter(msg => msg && typeof msg === 'object') : [];
    nextMessages.push({
      role:'system',
      content:'系统通知：前端等待生图时发生软超时截断，但图片任务仍在后台继续处理，前端已将它转入「拉回生图」，用户稍后可在那里查看结果。现在不要再次调用生图或编辑图工具。请基于当前上下文继续正常回答用户：可以先用一句话提醒图片仍在后台生成，然后继续给出有帮助的说明、建议、分析或下一步内容。不要重复整段提示词，也不要只回复“已转入拉回生图”。'
    });
    nextBody.messages = nextMessages;
    nextBody.image_generation_enabled = false;
    nextBody.disable_visual_prefetch = true;
    nextBody.client_session_id = String(sid || '');
    nextBody.client_session_title = String(getSessionById(sid)?.title || nextBody.client_session_title || '').trim();
    return nextBody;
  };
  const finishIntoImagePullback = async (reason='soft_timeout')=>{
    if(imagePullbackSoftTimedOut || terminalSeen || imagePullbackStopPolling) return false;
    const continuationRequest = buildImagePullbackContinuationRequest();
    imagePullbackSoftTimedOut = true;
    imagePullbackStopPolling = true;
    imagePullbackContinuationRequest = continuationRequest;
    imagePullbackContinueAfterHandoff = !!continuationRequest;
    clearImagePullbackSoftTimer();
    try{
      const sourceJobId = String(imagePullbackSourceJobId || getSessionPendingJobId(sid) || '').trim();
      if(sourceJobId && typeof window.trackImagePullbackFromAsyncJob === 'function'){
        await window.trackImagePullbackFromAsyncJob({
          sourceJobId,
          sessionId: sid,
          sessionTitle: String(getSessionById(sid)?.title || '').trim(),
          prompt: imagePullbackPromptFromRequest(),
          reason: 'frontend_soft_timeout',
        });
      }
    }catch(err){
      try{ console.warn('[image_pullback] track failed', err); }catch(_){ }
    }
    try{ activePollController?.abort('image_pullback_handoff'); }catch(_){ }
    try{ activeStartController?.abort('image_pullback_handoff'); }catch(_){ }
    flushRenderBuffer(true);
    finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
    setSessionRuntimeProcessText(sid, '');
    current = '';
    renderBuffer = '';
    setStatusForSession('已转入拉回生图');
    setSessionRuntimeDraftText(sid, '');
    refreshStreamDraftForSession();
    if(!isSessionVisibleInMainView(sid)){
      showCrossSessionCompletionNotice(sid, { state:'done', previewText: '', message:'图片已转入拉回生图' });
    }
    clearPendingAssistantSnapshot(sid, { immediate:true });
    clearSessionPendingJob(sid, { immediate:true });
    resetSessionRuntimeAfterPullback();
    if(isViewingStreamSession()) rtStop(sid, true);
    try{ if(typeof window.refreshImagePullbackJobs === 'function') window.refreshImagePullbackJobs({ silent:true }); }catch(_){ }
    if(typeof toast === 'function') toast(window.AperviaI18n?.t('pullback.moved_notice') || 'The image job moved to Generated images in the sidebar.');
    return true;
  };
  const scheduleImagePullbackSoftTimeout = (timeoutMs)=>{
    clearImagePullbackSoftTimer();
    const nextMs = Math.max(15000, Number(timeoutMs || imagePullbackSoftTimeoutMs || 180000));
    imagePullbackSoftTimeoutMs = nextMs;
    if(imagePullbackSoftTimedOut || terminalSeen || imagePullbackStopPolling) return;
    imagePullbackTimer = setTimeout(()=>{ finishIntoImagePullback('soft_timeout'); }, nextMs);
  };

  const flushRenderBuffer = (force=false)=>{
    if(renderTimer){ clearTimeout(renderTimer); renderTimer = null; }
    if(renderFrameId){ try{ cancelAnimationFrame(renderFrameId); }catch(_){ } renderFrameId = 0; }
    if(!renderBuffer && !force) return;
    if(renderBuffer || force){
      const draftText = getArtifactDraftPreviewText(current) || current;
      setSessionRuntimeDraftText(sid, draftText);
      refreshStreamDraftForSession();
      renderBuffer = "";
    }
  };
  const scheduleRenderFlush = ()=>{
    if(renderFrameId || renderTimer) return;
    const flushSoon = ()=>{
      if(renderFrameId){ try{ cancelAnimationFrame(renderFrameId); }catch(_){ } renderFrameId = 0; }
      if(renderTimer){ clearTimeout(renderTimer); renderTimer = null; }
      flushRenderBuffer(true);
    };
    try{
      renderFrameId = requestAnimationFrame(()=>{
        renderFrameId = 0;
        if(renderTimer){ clearTimeout(renderTimer); renderTimer = null; }
        flushRenderBuffer(true);
      });
    }catch(_){ }
    renderTimer = setTimeout(flushSoon, document.hidden ? 24 : 6);
  };

  const patchSavedAssistantWithGeneratedFiles = async (incomingFiles)=>{
    const mergedIncoming = mergeGeneratedFiles([], incomingFiles);
    if(!mergedIncoming.length) return;
    await updateSessionById(sid, s2 => {
      s2.generatedFiles = mergeGeneratedFiles(s2.generatedFiles || s2.generated_files || [], mergedIncoming).slice(-20);
      s2.generated_files = s2.generatedFiles;
      const msgs = Array.isArray(s2.messages) ? s2.messages : [];
      for(let i = msgs.length - 1; i >= 0; i--){
        if(msgs[i]?.role !== 'assistant') continue;
        msgs[i].generatedFiles = mergeGeneratedFiles(msgs[i].generatedFiles || msgs[i].generated_files || [], mergedIncoming).slice(-12);
        msgs[i].generated_files = msgs[i].generatedFiles;
        break;
      }
    }, { skipCompress: true, skipRender: true });
  };

  const imageReplyPayloadSigForContext = (payload)=>{
    try{
      const normalized = normalizeImageReplyForModelRequest(payload || {});
      if(!normalized || !Array.isArray(normalized.images) || !normalized.images.length) return '';
      return imageReplySignature(normalized);
    }catch(_){
      try{ return imageReplySignature(payload || {}); }catch(__){ return ''; }
    }
  };

  const persistAssistantImageReplyContextImmediately = async (payload)=>{
    const normalizedPayload = normalizeImageReplyForModelRequest(payload || {});
    if(!normalizedPayload || !Array.isArray(normalizedPayload.images) || !normalizedPayload.images.length) return false;
    const sig = imageReplyPayloadSigForContext(normalizedPayload);
    if(!sig) return false;
    const createdAtMs = Number(normalizedPayload.created_at_ms || normalizedPayload.createdAtMs || payload?.created_at_ms || payload?.createdAtMs || Date.now()) || Date.now();
    let inserted = false;
    await updateSessionById(sid, s2 => {
      const msgs = Array.isArray(s2.messages) ? s2.messages : (s2.messages = []);
      for(const msg of msgs){
        if(!msg || msg.role !== 'assistant') continue;
        const content = msg.content;
        if(!(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply')) continue;
        if(imageReplyPayloadSigForContext(content) === sig){
          if(msg._image_context_only || msg._pending_stream_image_reply){
            msg.content = normalizedPayload;
            msg.created_at_ms = Number(msg.created_at_ms || msg.createdAtMs || createdAtMs) || createdAtMs;
            msg.createdAtMs = Number(msg.createdAtMs || msg.created_at_ms || createdAtMs) || createdAtMs;
          }
          inserted = false;
          return;
        }
      }
      const imageContextMsg = decorateOutgoingAssistantMessage({
        role:'assistant',
        created_at_ms: createdAtMs,
        createdAtMs: createdAtMs,
        content: normalizedPayload,
        _image_context_only: true,
        _pending_stream_image_reply: true,
      }, sid, createdAtMs, activeEventJobId || getSessionPendingJobId(sid) || '', 'image_context');
      msgs.push(imageContextMsg);
      inserted = true;
    }, { skipCompress: true, skipRender: true });
    try{
      console.log('[DEBUG_ASSISTANT_IMAGE_CONTEXT_PERSISTED]', {
        sessionId: sid,
        inserted,
        sig,
        imageCount: Array.isArray(normalizedPayload.images) ? normalizedPayload.images.length : 0,
        subject: String(normalizedPayload.subject || '').trim(),
      });
    }catch(_){ }
    return true;
  };

  const finalizePersistedAssistantImageReplyContext = (messages, payload, createdAtMs)=>{
    const normalizedPayload = normalizeImageReplyForModelRequest(payload || {});
    if(!normalizedPayload || !Array.isArray(normalizedPayload.images) || !normalizedPayload.images.length) return false;
    const sig = imageReplyPayloadSigForContext(normalizedPayload);
    if(!sig) return false;
    const msgs = Array.isArray(messages) ? messages : [];
    for(const msg of msgs){
      if(!msg || msg.role !== 'assistant') continue;
      const content = msg.content;
      if(!(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply')) continue;
      if(imageReplyPayloadSigForContext(content) !== sig) continue;
      msg.content = normalizedPayload;
      msg.created_at_ms = Number(msg.created_at_ms || msg.createdAtMs || createdAtMs || Date.now()) || Date.now();
      msg.createdAtMs = Number(msg.createdAtMs || msg.created_at_ms || createdAtMs || Date.now()) || Date.now();
      delete msg._image_context_only;
      delete msg._pending_stream_image_reply;
      return true;
    }
    return false;
  };

  let _saveAssistantPromise = Promise.resolve();
  let preservedBranchContextForAssistantSave = null;

  const clearTerminalSessionUiState = ()=>{
    resetSessionTerminalRuntimeState(sid, { finalizeTimer:true, preserveReasoning:true });
  };

  const cloneBranchContextForAssistantSave = (ctx)=>{
    const data = ctx && typeof ctx === 'object' ? ctx : null;
    const groupId = String(data?.groupId || '').trim();
    if(!groupId) return null;
    const out = { ...data, groupId };
    out.versionIndex = Math.max(0, Number(data.versionIndex ?? 0) || 0);
    const startIndex = Number(data.startIndex);
    if(Number.isInteger(startIndex) && startIndex >= 0) out.startIndex = startIndex;
    out.kind = String(data.kind || '').trim() || 'user_edit';
    return out;
  };

  const inferActiveAssistantBranchContextForSave = (session)=>{
    const s = session && typeof session === 'object' ? session : null;
    if(!s) return null;
    let ctx = null;
    try{
      if(typeof webaiBranchCurrentContextForSession === 'function'){
        ctx = cloneBranchContextForAssistantSave(webaiBranchCurrentContextForSession(s));
      }
    }catch(_){ }
    try{
      const gid = String(ctx?.groupId || s._webaiActiveConversationBranchId || '').trim();
      const group = gid && typeof webaiBranchGroup === 'function' ? webaiBranchGroup(s, gid) : null;
      const active = Math.max(0, Number(group?.active ?? ctx?.versionIndex ?? 0) || 0);
      const activeVersionTail = Array.isArray(group?.versions?.[active]?.messages) ? group.versions[active].messages : [];
      const startIndex = Number(ctx?.startIndex ?? group?.startIndex);
      const rows = Array.isArray(s.messages) ? s.messages : [];
      const tailSinceStart = Number.isInteger(startIndex) && startIndex >= 0 ? rows.slice(Math.min(startIndex, rows.length)) : [];
      const hasUserAfterStart = tailSinceStart.some(msg => msg && String(msg.role || '').trim().toLowerCase() === 'user');
      if(group && String(group.kind || ctx?.kind || '') === 'assistant_regen' && (!activeVersionTail.length || !hasUserAfterStart)){
        return cloneBranchContextForAssistantSave({
          ...(ctx || {}),
          groupId: gid,
          versionIndex: active,
          startIndex,
          kind: 'assistant_regen',
        });
      }
    }catch(_){ }
    return null;
  };

  const resolveBranchContextForAssistantSave = (session)=>{
    const s = session && typeof session === 'object' ? session : null;
    const direct = cloneBranchContextForAssistantSave(preservedBranchContextForAssistantSave)
      || cloneBranchContextForAssistantSave(ensureSessionRuntime(sid)?.pendingBranchSave)
      || cloneBranchContextForAssistantSave(s?._webaiPendingConversationBranch)
      || inferActiveAssistantBranchContextForSave(s);
    return direct || null;
  };

  const preserveBranchContextForAssistantSave = ()=>{
    const ctx = resolveBranchContextForAssistantSave(getSessionById(sid));
    if(ctx){
      preservedBranchContextForAssistantSave = ctx;
      try{ ensureSessionRuntime(sid).pendingBranchSave = ctx; }catch(_){ }
    }
    return ctx;
  };

  const shouldRenderBranchAfterAssistantSave = ()=>{
    try{
      return !!resolveBranchContextForAssistantSave(getSessionById(sid));
    }catch(_){
      return false;
    }
  };

  const renderBranchAfterAssistantSave = ()=>{
    try{ invalidateChatRenderCache(); }catch(_){ }
    try{ renderList(); }catch(_){ }
    try{ if(isViewingStreamSession()) renderChat(); }catch(_){ }
  };

  const saveAssistantOnce = async ()=>{
    if(savedAssistant) return _saveAssistantPromise;
    const runtimeBeforePersist = ensureSessionRuntime(sid);
    const hasPersistableReasoning = !!(_normalizePendingAssistantReasoning(runtimeBeforePersist?.reasoning || []).length || _reasoningMetaHasVisibleContent(runtimeBeforePersist?.reasoningMeta || {}));
    if(!current.trim() && !(_genFiles && _genFiles.length) && !_weatherPayload && !(_imageReplyPayloads && _imageReplyPayloads.length) && !(_memoryEvents && _memoryEvents.length) && !hasPersistableReasoning) return _saveAssistantPromise;
    savedAssistant = true;

    const parsed = tryParseArtifactJson(current);
    const finalText = parsed ? (parsed.answer || "") : current;
    const persistedFileProcessText = String(_latestVisibleFileProcessText || ensureSessionRuntime(sid)?.draftProcessText || '').trim();
    const persistedGenerationUsage = normalizeAssistantUsagePayload(_generationUsage || ensureSessionRuntime(sid)?.generationUsage || null);

    _saveAssistantPromise = updateSessionById(sid, s2 => {
      const assistantCreatedAtMs = Date.now();
      const pendingBranchForSave = resolveBranchContextForAssistantSave(s2);
      if(pendingBranchForSave && pendingBranchForSave.groupId){
        try{ ensureSessionRuntime(sid).pendingBranchSave = pendingBranchForSave; }catch(_){ }
        try{ webaiBranchPreparePendingTailForSave(s2, pendingBranchForSave); }catch(_){ }
      }
      const applyPendingAssistantBranchMeta = (assistantMsg)=>{
        const pendingBranchForAssistant = pendingBranchForSave || resolveBranchContextForAssistantSave(s2);
        if(assistantMsg && pendingBranchForAssistant && pendingBranchForAssistant.groupId && String(pendingBranchForAssistant.kind || '') === 'assistant_regen'){
          assistantMsg._webai_conv_branch_id = String(pendingBranchForAssistant.groupId || '');
          assistantMsg._webai_conv_branch_version = Number(pendingBranchForAssistant.versionIndex || 0) || 0;
          assistantMsg._webai_conv_branch_kind = 'assistant_regen';
          assistantMsg._webai_conv_branch_control = true;
        }
        return assistantMsg;
      };
      const saveAssistantMessageForCurrentTurn = (assistantMsg)=>{
        if(!assistantMsg || typeof assistantMsg !== 'object') return;
        const duplicateAssistantIndex = findDuplicateAssistantMessageIndexInCurrentTurn(s2.messages, assistantMsg);
        if(duplicateAssistantIndex >= 0){
          mergeAssistantMessageMetadata(s2.messages[duplicateAssistantIndex], assistantMsg);
        }else{
          s2.messages.push(assistantMsg);
        }
      };
      const currentJobKeyForSave = String(activeEventJobId || imagePullbackSourceJobId || getSessionPendingJobId(sid) || '').trim();
      if(Array.isArray(_memoryEvents) && _memoryEvents.length){
        let memoryIndex = 0;
        for(const ev of _memoryEvents.slice(0, 4)){
          memoryIndex += 1;
          saveAssistantMessageForCurrentTurn(applyPendingAssistantBranchMeta(decorateOutgoingAssistantMessage({ role:'assistant', created_at_ms: assistantCreatedAtMs, createdAtMs: assistantCreatedAtMs, content: normalizeMemoryEventPayload(ev) }, sid, assistantCreatedAtMs, currentJobKeyForSave, 'memory_' + memoryIndex)));
        }
      }
      const persistedWeatherPayload = normalizeAssistantWeatherPayload(_weatherPayload || null);
      if(persistedWeatherPayload && !String(finalText || '').trim()){
        saveAssistantMessageForCurrentTurn(applyPendingAssistantBranchMeta(decorateOutgoingAssistantMessage({ role:"assistant", created_at_ms: assistantCreatedAtMs, createdAtMs: assistantCreatedAtMs, content: persistedWeatherPayload }, sid, assistantCreatedAtMs, currentJobKeyForSave, 'weather')));
      }
      const imageSearchReplyPayloads = Array.isArray(_imageReplyPayloads) ? _imageReplyPayloads.filter(isImageSearchReplyPayload) : [];
      const persistedGeneratedFilesForSession = _normalizePendingAssistantFiles(_genFiles || []);
      if(persistedGeneratedFilesForSession.length){
        s2.generatedFiles = mergeGeneratedFiles(s2.generatedFiles || s2.generated_files || [], persistedGeneratedFilesForSession).slice(-20);
        s2.generated_files = s2.generatedFiles;
      }
      const finalTextHasContent = !!String(finalText || '').trim();
      const standaloneImageReplyPayloads = Array.isArray(_imageReplyPayloads)
        ? _imageReplyPayloads.filter(item => {
            if(!item) return false;
            const itemJob = String(item._stream_job_id || item.job_id || item._job_id || '').trim();
            if(currentJobKeyForSave && itemJob && itemJob !== currentJobKeyForSave) return false;
            if(finalTextHasContent && !isImageSearchReplyPayload(item)) return false;
            return !isImageSearchReplyPayload(item) || !finalTextHasContent;
          })
        : [];
      if(standaloneImageReplyPayloads.length){
        for(const item of standaloneImageReplyPayloads){
          if(!item) continue;
          // The top-level assistant image-reply message is part of the current
          // assistant turn, so its message timestamp must be the assistant turn
          // timestamp, not a provider/image artifact timestamp carried inside the
          // payload. Otherwise later sync/render passes can place the generated
          // image above the user prompt that triggered it.
          const imageReplyCreatedAtMs = assistantCreatedAtMs;
          const persistedReplyEndpointMode = normalizeApiEndpointMode(item?.endpoint_mode || item?.api_endpoint_mode || item?.apiEndpointMode || getActiveApiEndpointMode());
          const persistedImageReply = applyMirroredImageCacheToImageReplyPayload({ _kind:'image_reply', ...item, source_role:'assistant', endpoint_mode:persistedReplyEndpointMode, api_endpoint_mode:persistedReplyEndpointMode, created_at_ms:imageReplyCreatedAtMs, createdAtMs:imageReplyCreatedAtMs });
          saveAssistantMessageForCurrentTurn(applyPendingAssistantBranchMeta(decorateOutgoingAssistantMessage({ role:'assistant', created_at_ms: imageReplyCreatedAtMs, createdAtMs: imageReplyCreatedAtMs, content: persistedImageReply }, sid, imageReplyCreatedAtMs, currentJobKeyForSave, 'image_reply')));
        }
      }
      const generatedImageStandaloneOnly = !!(standaloneImageReplyPayloads.some(isGeneratedImageReplyPayload) && !finalTextHasContent && !persistedWeatherPayload && !persistedGeneratedFilesForSession.length && !persistedFileProcessText);
      const persistedAssistantText = generatedImageStandaloneOnly ? '' : String(finalText || '').trim();
      if(persistedAssistantText.trim()){
        const runtimeForPersist = ensureSessionRuntime(sid);
        const persistedReasoningMeta = _normalizePendingAssistantReasoningMeta(runtimeForPersist?.reasoningMeta || {});
        const persistedReasoning = _mergeNativeReasoningEntry(runtimeForPersist?.reasoning || [], persistedReasoningMeta);
        const webHit = !!(
          persistedReasoningMeta?.webHit
          || (Number(persistedReasoningMeta?.resultCount || 0) || 0) > 0
          || (Number(persistedReasoningMeta?.pageCount || 0) || 0) > 0
          || (Number(persistedReasoningMeta?.sourceCount || 0) || 0) > 0
          || _assistantSources.length
        );
        const persistedSources = mergeAssistantSourceItems(normalizeAssistantSourceItems(_assistantSources), deriveAssistantCitationSources(sid, persistedAssistantText));
        const assistantMsg = decorateOutgoingAssistantMessage({ role:"assistant", created_at_ms: assistantCreatedAtMs, createdAtMs: assistantCreatedAtMs, content: persistedAssistantText, webHit, sourceBound: !!persistedSources.length || webHit }, sid, assistantCreatedAtMs, currentJobKeyForSave, 'answer');
        applyPendingAssistantBranchMeta(assistantMsg);
        const assistantElapsedMs = _rtClampElapsedMsForSession(sid, Math.max(0, Number(runtimeForPersist?.rtFinalMs || getSessionById(sid)?.rtFinalMs || 0) || 0));
        if(assistantElapsedMs > 0){
          assistantMsg.rtFinalMs = assistantElapsedMs;
          assistantMsg.elapsedMs = assistantElapsedMs;
          assistantMsg.elapsed_ms = assistantElapsedMs;
        }
        if(persistedGenerationUsage){
          assistantMsg.generationUsage = persistedGenerationUsage;
          assistantMsg.generation_usage = persistedGenerationUsage;
        }
        if(imageSearchReplyPayloads.length) assistantMsg.imageReplies = imageSearchReplyPayloads;
        if(persistedWeatherPayload) assistantMsg.weather = persistedWeatherPayload;
        if(persistedGeneratedFilesForSession.length) assistantMsg.generatedFiles = persistedGeneratedFilesForSession;
        if(persistedFileProcessText){
          assistantMsg.fileProcessText = persistedFileProcessText;
          assistantMsg.file_process_text = persistedFileProcessText;
        }
        if(persistedSources.length) assistantMsg.sources = persistedSources;
        if(_runtimeModel) assistantMsg.runtimeModel = _runtimeModel;
        if(persistedReasoning.length) assistantMsg.reasoning = persistedReasoning;
        if(Object.keys(persistedReasoningMeta).length) assistantMsg.reasoningMeta = persistedReasoningMeta;
        let assistantContinuationSaved = false;
        if(continuationTarget){
          const target = findAssistantContinuationMessage(s2);
          if(target && target.msg){
            const updatedAtMs = Date.now();
            target.msg.content = composeAssistantContinuationText(continuationTarget.baseText, persistedAssistantText);
            target.msg.updatedAt = updatedAtMs;
            target.msg.updated_at = updatedAtMs;
            target.msg.updated_at_ms = updatedAtMs;
            target.msg.syncStatus = 'pending';
            target.msg.sync_status = 'pending';
            if(target.msg.messageRecovery && typeof target.msg.messageRecovery === 'object'){
              target.msg.messageRecovery = { ...target.msg.messageRecovery, status:'pending', updated_at: updatedAtMs };
            }
            mergeAssistantMessageMetadata(target.msg, assistantMsg);
            try{ cloudSyncEnsureMessageSyncFields(target.msg, sid, target.msg.conversationMode || target.msg.conversation_mode || ''); }catch(_){ }
            s2.updatedAt = updatedAtMs;
            s2.conversationRecovery = {
              ...(s2.conversationRecovery && typeof s2.conversationRecovery === 'object' ? s2.conversationRecovery : {}),
              updated_at: updatedAtMs,
              status: String(s2.syncStatus || s2.sync_status || 'pending').trim() || 'pending',
            };
            assistantContinuationSaved = true;
          }
        }
        if(!assistantContinuationSaved){
          saveAssistantMessageForCurrentTurn(assistantMsg);
        }
      }else if((persistedGeneratedFilesForSession.length || persistedFileProcessText) && !persistedWeatherPayload){
        const runtimeForPersist = ensureSessionRuntime(sid);
        const persistedReasoningMeta = _normalizePendingAssistantReasoningMeta(runtimeForPersist?.reasoningMeta || {});
        const persistedReasoning = _mergeNativeReasoningEntry(runtimeForPersist?.reasoning || [], persistedReasoningMeta);
        const assistantMsg = decorateOutgoingAssistantMessage({ role:"assistant", created_at_ms: assistantCreatedAtMs, createdAtMs: assistantCreatedAtMs, content: '' }, sid, assistantCreatedAtMs, currentJobKeyForSave, 'file_generation');
        if(persistedGeneratedFilesForSession.length){
          assistantMsg.generatedFiles = persistedGeneratedFilesForSession;
          assistantMsg.generated_files = persistedGeneratedFilesForSession;
        }
        if(persistedFileProcessText){
          assistantMsg.fileProcessText = persistedFileProcessText;
          assistantMsg.file_process_text = persistedFileProcessText;
        }
        const assistantElapsedMs = _rtClampElapsedMsForSession(sid, Math.max(0, Number(runtimeForPersist?.rtFinalMs || getSessionById(sid)?.rtFinalMs || 0) || 0));
        if(assistantElapsedMs > 0){
          assistantMsg.rtFinalMs = assistantElapsedMs;
          assistantMsg.elapsedMs = assistantElapsedMs;
          assistantMsg.elapsed_ms = assistantElapsedMs;
        }
        if(persistedGenerationUsage){
          assistantMsg.generationUsage = persistedGenerationUsage;
          assistantMsg.generation_usage = persistedGenerationUsage;
        }
        if(_runtimeModel) assistantMsg.runtimeModel = _runtimeModel;
        if(persistedReasoning.length) assistantMsg.reasoning = persistedReasoning;
        if(Object.keys(persistedReasoningMeta).length) assistantMsg.reasoningMeta = persistedReasoningMeta;
        saveAssistantMessageForCurrentTurn(applyPendingAssistantBranchMeta(assistantMsg));
      }else{
        if(generatedImageStandaloneOnly){
          const runtimeForPersist = ensureSessionRuntime(sid);
          runtimeForPersist.reasoning = [];
          runtimeForPersist.reasoningMeta = {};
          runtimeForPersist.draftProcessText = '';
        }else{
          const runtimeForPersist = ensureSessionRuntime(sid);
          const persistedReasoningMeta = _normalizePendingAssistantReasoningMeta(runtimeForPersist?.reasoningMeta || {});
          const persistedReasoning = _mergeNativeReasoningEntry(runtimeForPersist?.reasoning || [], persistedReasoningMeta);
          if(persistedReasoning.length || Object.keys(persistedReasoningMeta).length){
            const assistantMsg = decorateOutgoingAssistantMessage({ role:'assistant', created_at_ms: assistantCreatedAtMs, createdAtMs: assistantCreatedAtMs, content: '' }, sid, assistantCreatedAtMs, currentJobKeyForSave, 'reasoning');
            if(_runtimeModel) assistantMsg.runtimeModel = _runtimeModel;
            if(persistedReasoning.length) assistantMsg.reasoning = persistedReasoning;
            if(Object.keys(persistedReasoningMeta).length) assistantMsg.reasoningMeta = persistedReasoningMeta;
            const assistantElapsedMs = _rtClampElapsedMsForSession(sid, Math.max(0, Number(runtimeForPersist?.rtFinalMs || getSessionById(sid)?.rtFinalMs || 0) || 0));
            if(assistantElapsedMs > 0){
              assistantMsg.rtFinalMs = assistantElapsedMs;
              assistantMsg.elapsedMs = assistantElapsedMs;
              assistantMsg.elapsed_ms = assistantElapsedMs;
            }
            if(persistedGenerationUsage){
              assistantMsg.generationUsage = persistedGenerationUsage;
              assistantMsg.generation_usage = persistedGenerationUsage;
            }
            saveAssistantMessageForCurrentTurn(applyPendingAssistantBranchMeta(assistantMsg));
          }
        }
      }
      try{
        const pendingBranchForCommit = pendingBranchForSave || resolveBranchContextForAssistantSave(s2);
        if(pendingBranchForCommit && pendingBranchForCommit.groupId){
          webaiBranchCommitActiveVersion(s2, pendingBranchForCommit);
          try{ delete ensureSessionRuntime(sid).pendingBranchSave; }catch(_){ }
          preservedBranchContextForAssistantSave = null;
        }else{
          // Ordinary turns after an edited/regenerated branch continue that active
          // branch. Commit after saving assistant too, so refresh/cloud sync cannot
          // roll the visible path back to the pre-send user message.
          webaiBranchCommitActiveVersion(s2, null);
        }
      }catch(_){ }
      try{ webaiOfficialPersistActivePath(s2); }catch(_){ }
      clearPendingAssistantFieldsFromSession(s2);
    }, { skipCompress: true, skipRender: true });
    return _saveAssistantPromise;
  };

  const processAsyncJobEvent = async (event, payload)=>{
    const payloadJobId = String(payload?.job_id || payload?._job_id || '').trim();
    if(payloadJobId && activeEventJobId && payloadJobId !== activeEventJobId) return;
    if(payload && Number.isFinite(Number(payload._job_seq))){
      setSessionPendingJobCursor(sid, Number(payload._job_seq));
    }

    if(event === "location_permission_request"){
      handleLocationPermissionRequest(payload || {}).catch(()=>{});
      return;
    }
    if(event === "mcp_approval_request"){
      handleMcpApprovalRequest(payload || {}, { sessionId:sid }).catch(()=>{});
      return;
    }
    if(event === "mcp_approval_result"){
      try{ handleMcpApprovalResult(payload || {}, { sessionId:sid }); }catch(_){ }
      return;
    }
    if(event === "mcp_tool_audit"){
      try{ handleMcpToolAudit(payload || {}, { sessionId:sid }); }catch(_){ }
      return;
    }
    if(event === "status"){
      const statusText = String(payload?.text || "");
      const hasFileProgress = !!(payload?.file_progress && typeof payload.file_progress === 'object');
      if(hasFileProgress){
        pushSessionRuntimeFileProgress(sid, payload.file_progress);
        refreshStreamDraftForSession();
      }
      const forcedImageTimeoutMsg = normalizeImageGenerationForcedTimeoutMessage(statusText);
      if(forcedImageTimeoutMsg){
        setSessionBackendError(sid, forcedImageTimeoutMsg);
      }
      setStatusForSession(statusText, { fileStage: _isFileGenerationStatusText(statusText) || hasFileProgress });
      return;
    }
    if(event === "reasoning"){
      const reasoningEventKey = String(payload?.segment_key || payload?.segmentKey || payload?.reasoning_event_key || payload?.reasoningEventKey || payload?.native_reasoning_event_key || payload?.nativeReasoningEventKey || payload?.event_key || payload?.eventKey || '').trim();
      pushSessionRuntimeNativeReasoningDelta(
        sid,
        String(payload?.text || ''),
        String(payload?.source || 'native_field'),
        Number(payload?.seq || payload?.order || payload?._job_seq || 0) || 0,
        reasoningEventKey
      );
      if(isViewingStreamSession()) refreshStreamDraftForSession();
      return;
    }
    if(event === "reasoning_meta"){
      const metaText = String(payload?.native_reasoning_text || payload?.nativeReasoningText || payload?.text || payload?.full_text || '').trim();
      // reasoning is the only append-only event. reasoning_meta is an
      // authoritative aggregate snapshot used for recovery/finalization; never
      // reinterpret it as a delta, even when reconnect state is temporarily
      // behind.  finalizeSessionRuntimeNativeReasoning still creates one
      // aggregate fallback row when a provider emits snapshots without deltas.
      const patch = {
        nativeReasoningConnected: !!(payload?.connected || payload?.native_reasoning_connected || payload?.nativeReasoningConnected || metaText),
        nativeReasoningDone: !!(payload?.done || payload?.native_reasoning_done || payload?.nativeReasoningDone || String(payload?.status || '').toLowerCase() === 'done'),
        nativeReasoningSource: String(payload?.source || payload?.native_reasoning_source || payload?.nativeReasoningSource || ''),
        nativeReasoningText: metaText,
      };
      setSessionRuntimeReasoningMeta(sid, patch);
      if(patch.nativeReasoningConnected || String(ensureSessionRuntime(sid)?.reasoningMeta?.nativeReasoningText || '').trim()) finalizeSessionRuntimeNativeReasoning(sid, patch);
      if(isViewingStreamSession()) refreshStreamDraftForSession();
      return;
    }
    if(event === "delta"){
      const piece = String(payload?.text || "");
      if(!piece) return;
      if(suppressTextForGeneratedImageReply) return;
      const hadFirstToken = !!_firstTokenAt;
      if(!hadFirstToken){
        _firstTokenAt = Date.now();
        setStatusForSession("正在生成回答…");
      }
      _receivedAssistantTextThisRun = true;
      current += piece;
      renderBuffer += piece;
      if(!hadFirstToken || shouldFlushStreamBuffer(renderBuffer)) flushRenderBuffer(true);
      else scheduleRenderFlush();
      return;
    }
    if(event === "file_progress"){
      pushSessionRuntimeFileProgress(sid, payload || {});
      const progressMessage = String(payload?.message || payload?.text || '正在处理文件…');
      setStatusForSession(progressMessage, { skipReasoning:true, fileStage:true });
      refreshStreamDraftForSession();
      return;
    }
    if(event === "file_process"){
      const processText = String(payload?.text || "");
      const processMode = String(payload?.mode || payload?.file_mode || '').trim();
      if(processText.trim()){
        _latestVisibleFileProcessText = processText;
      }
      setSessionRuntimeProcessText(sid, processText);
      if(payload?.status) setStatusForSession(String(payload.status || ""), { skipReasoning:true, fileStage:true });
      refreshStreamDraftForSession();
      return;
    }
    if(event === "files"){
      const files = payload.files || payload;
      if(Array.isArray(files)){
        pushSessionRuntimeDraftFiles(sid, files);
        _genFiles = mergeGeneratedFiles(_genFiles, files);
        // 保留可见文件正文面板，最终回答持久化后继续显示。
        refreshStreamDraftForSession();
        setStatusForSession("文件已生成，正在整理回复…", { skipReasoning:true, fileStage:true });
        if(savedAssistant){
          await patchSavedAssistantWithGeneratedFiles(files);
        }
      }
      return;
    }
    if(event === "activity"){
      const activityEvents = (typeof _activityEventsFromPayload === 'function') ? _activityEventsFromPayload(payload) : (
        Array.isArray(payload?.activity_events) ? payload.activity_events : (
          Array.isArray(payload?.activityEvents) ? payload.activityEvents : (payload?.activity_event ? [payload.activity_event] : [])
        )
      );
      if(activityEvents.length){
        const shouldRefreshInlineActivity = activityEvents.some(item => (
          typeof _activityEventIsStreamRetry === 'function'
            ? _activityEventIsStreamRetry(item)
            : String(item?.key || '').trim().toLowerCase().startsWith('stream_retry|')
        ));
        // Activity events only need to update the side panel/runtime store.
        // Re-syncing the whole draft bubble here makes search progress feel
        // like it is stuttering, especially when source chips arrive in bursts.
        setSessionRuntimeReasoningMeta(sid, { activityEvents });
        if(shouldRefreshInlineActivity && isViewingStreamSession()){
          syncVisibleDraftBubble(sid);
        }
      }
      return;
    }
    if(event === "usage"){
      const usage = normalizeAssistantUsagePayload(payload || null);
      if(usage){
        _generationUsage = usage;
        ensureSessionRuntime(sid).generationUsage = usage;
      }
      return;
    }
    if(event === "meta"){
      const runtimeModel = String(payload?.runtime_model || payload?.runtimeModel || '').trim();
      if(runtimeModel){
        _runtimeModel = runtimeModel;
        await updateSessionById(sid, s2 => {
          s2.runtimeModel = runtimeModel;
          s2.runtime_model = runtimeModel;
          s2.runtimeModelSourceModel = String(s2.model || '').trim();
          s2.runtime_model_source_model = String(s2.model || '').trim();
        }, { skipCompress:true, skipRender:true });
      }
      const files = payload?.artifacts || [];
      const sources = normalizeAssistantSourceItems(payload?.sources || []);
      const sourceCount = Math.max(
        Number(payload?.source_count || 0) || 0,
        Array.isArray(sources) ? sources.length : 0
      );
      const metaVisualIntent = String(payload?.visual_intent || payload?.visualIntent || '').trim().toLowerCase();
      const metaImageStage = String(payload?.image_stage || payload?.imageStage || '').trim().toLowerCase();
      const metaImageResultCount = Number(payload?.image_result_count || payload?.imageResultCount || 0) || 0;
      const suppressGeneratedImageProcessMeta = !!(
        metaVisualIntent === 'image_generation'
        || metaVisualIntent === 'image_generate'
        || metaVisualIntent === 'image_edit'
        || metaVisualIntent === 'image_variation'
        || (metaImageStage === 'generated' && metaImageResultCount > 0)
      );
      if(suppressGeneratedImageProcessMeta) clearSessionImageOnlyReasoningRuntime(sid);
      setSessionRuntimeReasoningMeta(sid, {
        sourceCount,
        resultCount: Number(payload?.result_count || payload?.results || 0) || 0,
        pageCount: Number(payload?.page_count || payload?.pages || 0) || 0,
        searchRounds: Number(payload?.search_rounds || 0) || 0,
        routeMode: String(payload?.route_mode || ''),
        useWebResearch: !!(payload?.use_web_research || payload?.useWebResearch),
        webHit: !!(payload?.web_hit || payload?.webHit),
        answerStrategy: String(payload?.answer_strategy || ''),
        queryStrategy: String(payload?.query_strategy || ''),
        searchStage: String(payload?.search_stage || ''),
        statusText: String(payload?.status_text || ''),
        queriesUsed: Array.isArray(payload?.queries_used) ? payload.queries_used : [],
        webQueryGroups: Array.isArray(payload?.web_query_groups) ? payload.web_query_groups : (Array.isArray(payload?.webQueryGroups) ? payload.webQueryGroups : []),
        activityEvents: (typeof _activityEventsFromPayload === 'function') ? _activityEventsFromPayload(payload) : (Array.isArray(payload?.activity_events) ? payload.activity_events : (Array.isArray(payload?.activityEvents) ? payload.activityEvents : [])),
        progressEvents: (typeof _progressEventsFromPayload === 'function') ? _progressEventsFromPayload(payload) : (Array.isArray(payload?.progress_events) ? payload.progress_events : (Array.isArray(payload?.progressEvents) ? payload.progressEvents : [])),
        plannedFocuses: Array.isArray(payload?.planned_focuses) ? payload.planned_focuses : [],
        searchResults: payload?.search_results || payload?.searched_results || [],
        nativeWebCallCount: Number(payload?.native_web_call_count || payload?.nativeWebCallCount || 0) || 0,
        nativeWebCalls: Array.isArray(payload?.native_web_calls) ? payload.native_web_calls : (Array.isArray(payload?.nativeWebCalls) ? payload.nativeWebCalls : []),
        useKnowledgeBase: !!(payload?.use_knowledge_base || payload?.useKnowledgeBase || payload?.knowledge_hit || payload?.knowledgeHit),
        kbResultCount: Number(payload?.kb_result_count || payload?.kbResultCount || payload?.knowledge_result_count || payload?.knowledgeResultCount || 0) || 0,
        kbDocCount: Number(payload?.kb_doc_count || payload?.kbDocCount || payload?.knowledge_doc_count || payload?.knowledgeDocCount || 0) || 0,
        kbChunkCount: Number(payload?.kb_chunk_count || payload?.kbChunkCount || payload?.knowledge_chunk_count || payload?.knowledgeChunkCount || 0) || 0,
        kbQueriesUsed: Array.isArray(payload?.kb_queries_used) ? payload.kb_queries_used : (Array.isArray(payload?.kbQueriesUsed) ? payload.kbQueriesUsed : []),
        kbSearchResults: Array.isArray(payload?.kb_search_results) ? payload.kb_search_results : (Array.isArray(payload?.kbSearchResults) ? payload.kbSearchResults : []),
        useVisual: suppressGeneratedImageProcessMeta ? false : !!(payload?.use_visual || payload?.useVisual),
        visualIntent: suppressGeneratedImageProcessMeta ? '' : String(payload?.visual_intent || payload?.visualIntent || ''),
        imageStage: suppressGeneratedImageProcessMeta ? '' : String(payload?.image_stage || payload?.imageStage || ''),
        imageResultCount: suppressGeneratedImageProcessMeta ? 0 : (Number(payload?.image_result_count || payload?.imageResultCount || 0) || 0),
        imageQueriesUsed: suppressGeneratedImageProcessMeta ? [] : (Array.isArray(payload?.image_queries_used) ? payload.image_queries_used : (Array.isArray(payload?.imageQueriesUsed) ? payload.imageQueriesUsed : [])),
        fileToolUsed: !!(payload?.file_tool_used || payload?.fileToolUsed),
        fileToolRounds: Number(payload?.file_tool_rounds || payload?.fileToolRounds || 0) || 0,
        fileProgressItems: Array.isArray(payload?.file_progress_items) ? payload.file_progress_items : (Array.isArray(payload?.fileProgressItems) ? payload.fileProgressItems : []),
        fileEditAudits: Array.isArray(payload?.file_edit_audits) ? payload.file_edit_audits : (Array.isArray(payload?.fileEditAudits) ? payload.fileEditAudits : []),
        artifactCount: Number(payload?.artifact_count || payload?.artifactCount || 0) || 0,
        artifactFilenames: Array.isArray(payload?.artifact_filenames) ? payload.artifact_filenames : (Array.isArray(payload?.artifactFilenames) ? payload.artifactFilenames : []),
        nativeReasoningConnected: !!(payload?.native_reasoning_connected || payload?.nativeReasoningConnected || payload?.native_reasoning_text || payload?.nativeReasoningText),
        nativeReasoningDone: !!(payload?.native_reasoning_done || payload?.nativeReasoningDone),
        nativeReasoningSource: String(payload?.native_reasoning_source || payload?.nativeReasoningSource || ''),
        nativeReasoningText: String(payload?.native_reasoning_text || payload?.nativeReasoningText || ''),
      });
      if(isViewingStreamSession() && !String(current || '').trim()) refreshStreamDraftForSession();
      if(sourceCount > 0) pushSessionRuntimeReasoningSources(sid, sourceCount);
      if(sources.length){
        _assistantSources = mergeAssistantSourceItems(_assistantSources, sources);
        pushSessionRuntimeSourceItems(sid, sources);
      }
      if(Array.isArray(files) && files.length){
        pushSessionRuntimeDraftFiles(sid, files);
        _genFiles = mergeGeneratedFiles(_genFiles, files);
        // 保留可见文件正文面板，最终回答持久化后继续显示。
        refreshStreamDraftForSession();
        if(savedAssistant){
          await patchSavedAssistantWithGeneratedFiles(files);
        }
      }
      return;
    }
    if(event === "memory_event"){
      const ev = normalizeMemoryEventPayload(payload || {});
      if(ev.text || ev.title){
        _memoryEvents.push(ev);
        if(isViewingStreamSession()) addMemoryEventBubble(ev);
        setStatusForSession(ev.title || "已更新记忆", { skipReasoning:true });
        try{ fetchBackendPersonalizationState({ render:false, persist:false }); }catch(_){ }
      }
      return;
    }
    if(event === "image_pullback_hint"){
      const ms = Number(payload?.soft_timeout_ms || 180000) || 180000;
      imagePullbackSoftTimeoutMs = Math.max(15000, ms);
      scheduleImagePullbackSoftTimeout(imagePullbackSoftTimeoutMs);
      try{ if(typeof window.refreshImagePullbackJobs === 'function') window.refreshImagePullbackJobs({ silent:true }); }catch(_){ }
      if(payload?.status_text) setStatusForSession(String(payload.status_text || '图片任务已进入后台拉回保护。'));
      return;
    }
    if(event === "weather"){
      flushRenderBuffer(true);
      _weatherPayload = { _kind:"weather", ...(payload || {}) };
      setSessionRuntimeWeatherPayload(sid, _weatherPayload);
      setStatusForSession("天气已更新");
      if(isViewingStreamSession()) refreshStreamDraftForSession();
      return;
    }
    if(event === "image_reply"){
      const sig = imageReplySignature(payload);
      if(sig && _imageReplySignatureSet.has(sig)) return;
      if(sig) _imageReplySignatureSet.add(sig);
      const inferredImageReplySource = inferEdgeImageReplySource(payload);
      const replyEndpointMode = normalizeApiEndpointMode(
        payload?.endpoint_mode || payload?.api_endpoint_mode || payload?.apiEndpointMode ||
        o?.requestBody?.api_endpoint_mode || o?.requestBody?.apiEndpointMode ||
        o?.requestBody?.api_settings?.api_endpoint_mode || getActiveApiEndpointMode()
      );
      const imageReplyEventCreatedAtMs = Date.now();
      const normalizedPayload = {
        _kind: 'image_reply',
        ...(payload || {}),
        created_at_ms: imageReplyEventCreatedAtMs,
        createdAtMs: imageReplyEventCreatedAtMs,
        _stream_job_id: activeEventJobId || payloadJobId || '',
        ...(inferredImageReplySource && !String(payload?.source || '').trim() ? { source: inferredImageReplySource } : {}),
        ...(inferredImageReplySource === 'image_search' && !String(payload?.operation || payload?.task_mode || '').trim() ? { operation: 'image_search' } : {}),
        endpoint_mode: replyEndpointMode,
        api_endpoint_mode: replyEndpointMode,
        images: normalizeImageReplyImagesForPayload({
          ...(payload || {}),
          ...(inferredImageReplySource && !String(payload?.source || '').trim() ? { source: inferredImageReplySource } : {}),
          ...(inferredImageReplySource === 'image_search' && !String(payload?.operation || payload?.task_mode || '').trim() ? { operation: 'image_search' } : {}),
          endpoint_mode: replyEndpointMode,
          api_endpoint_mode: replyEndpointMode,
        }).map((img)=>{
          const sourceImageIds = normalizeImageReplySourceIds(img, payload || {});
          return {
            ...img,
            endpoint_mode: normalizeApiEndpointMode(img.endpoint_mode || img.api_endpoint_mode || img.apiEndpointMode || replyEndpointMode),
            api_endpoint_mode: normalizeApiEndpointMode(img.api_endpoint_mode || img.endpoint_mode || img.apiEndpointMode || replyEndpointMode),
            parent_image_id: String(img.parent_image_id || img.parentImageId || payload?.parent_image_id || payload?.parentImageId || '').trim(),
            source_image_ids: sourceImageIds,
            derived_from: sourceImageIds,
            _stream_job_id: activeEventJobId || payloadJobId || '',
          };
        }),
      };
      _imageReplyPayloads = _normalizePendingAssistantImageReplies([
        ...(Array.isArray(_imageReplyPayloads) ? _imageReplyPayloads : []),
        normalizedPayload,
      ]);
      pushSessionRuntimeImageReplies(sid, [normalizedPayload]);
      if(isGeneratedImageReplyPayload(normalizedPayload)){
        suppressTextForGeneratedImageReply = true;
        current = '';
        renderBuffer = '';
        setSessionRuntimeDraftText(sid, '');
        clearSessionImageOnlyReasoningRuntime(sid);
      }
      clearImagePullbackSoftTimer();
      edgeStreamImageReplyVisible = true;
      if(isViewingStreamSession()){
        if(isImageSearchReplyPayload(normalizedPayload)){
          refreshStreamDraftForSession();
        }else{
          let draftBubble = getVisibleDraftBubble(sid);
          if(draftBubble && !visibleDraftBubbleIsAfterLatestUserTurn(draftBubble)){
            try{ draftBubble.remove(); }catch(_){ }
            try{ if(liveDraftBubbleEls) delete liveDraftBubbleEls[sid]; }catch(_){ }
            draftBubble = null;
          }
          const shouldPatchDraftBubble = !!draftBubble && (
            !String(current || '').trim()
            || draftBubble.classList.contains('bubble-image-stage')
            || draftBubble.dataset.imageStagePendingFinal === '1'
            || isImageGenerationStatusText(draftBubble.dataset.draftStatusText || '')
          );
          if(shouldPatchDraftBubble){
            delete draftBubble.dataset.imageStagePendingFinal;
            await patchDraftBubbleWithImageReply(draftBubble, normalizedPayload);
          } else {
            addImageReplyBubble(normalizedPayload, { sessionId:sid });
          }
        }
        removeEmptyVisibleDraftBubbleAfterEdgeImageReply();
      }
      setStatusForSession("内容已更新");
      return;
    }
    if(event === "done"){
      terminalSeen = true;
      clearImagePullbackSoftTimer();
      const hasGeneratedImageReplyForTurn = Array.isArray(_imageReplyPayloads) && _imageReplyPayloads.some(isGeneratedImageReplyPayload);
      if(hasGeneratedImageReplyForTurn){
        suppressTextForGeneratedImageReply = true;
        current = '';
        renderBuffer = '';
        setSessionRuntimeDraftText(sid, '');
        clearSessionImageOnlyReasoningRuntime(sid);
      }else{
        finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
      }
      const finalFileProcessText = hasGeneratedImageReplyForTurn ? '' : String(_latestVisibleFileProcessText || ensureSessionRuntime(sid)?.draftProcessText || '').trim();
      flushRenderBuffer(true);
      const parsed = tryParseArtifactJson(current);
      if(parsed){
        current = parsed.answer || "";
        setSessionRuntimeDraftText(sid, (parsed?.answer || ""));
        refreshStreamDraftForSession();
      }
      const imageOnlyCompleted = Array.isArray(_imageReplyPayloads) && _imageReplyPayloads.length && !String(current || '').trim() && !_genFiles.length && !_weatherPayload;
      const imageOnlyScrollState = imageOnlyCompleted && isViewingStreamSession()
        ? { top: Number(chatEl?.scrollTop || 0) || 0 }
        : null;
      const visibleDraftBubble = getVisibleDraftBubble(sid);
      const waitingImageOnly = !imageOnlyCompleted
        && !String(current || '').trim()
        && !_genFiles.length
        && !_weatherPayload
        && !!visibleDraftBubble
        && (visibleDraftBubble.classList.contains('bubble-image-stage') || isImageGenerationStatusText(visibleDraftBubble.dataset.draftStatusText || ''));
      const finalPreviewText = getArtifactDraftPreviewText(current) || current || "";
      const finalizedBubble = imageOnlyCompleted
        ? finalizeVisibleImageDraftBubble(sid)
        : (continuationTarget
            ? patchAssistantContinuationTargetDraft(finalPreviewText, {
                done: true,
                sources: _assistantSources,
                imageReplies: (Array.isArray(_imageReplyPayloads) ? _imageReplyPayloads.filter(isImageSearchReplyPayload) : []),
                weatherPayload: _weatherPayload,
                processText: finalFileProcessText,
                generationUsage: _generationUsage || normalizeAssistantUsagePayload(ensureSessionRuntime(sid)?.generationUsage || null),
              })
            : (waitingImageOnly
            ? finalizeVisiblePendingImageStageBubble(sid, { statusText: String(visibleDraftBubble?.dataset?.draftStatusText || asyncStreamT('stream.generating_image', null, 'Generating image…')) })
            : finalizeVisibleDraftBubble(sid, {
                finalText: finalPreviewText,
                statusText: asyncStreamT('stream.done', null, 'Completed'),
                sources: _assistantSources,
                webHit: !!_assistantSources.length,
                imageReplies: (Array.isArray(_imageReplyPayloads) ? _imageReplyPayloads.filter(isImageSearchReplyPayload) : []),
                weatherPayload: _weatherPayload,
                processText: finalFileProcessText,
                generationUsage: _generationUsage || normalizeAssistantUsagePayload(ensureSessionRuntime(sid)?.generationUsage || null),
              })));
      finalizedVisibleDraft = !!finalizedBubble;
      if(finalizedVisibleDraft && isViewingStreamSession()) scrollChatToBottom(false);
      setStatusForSession("完成", { terminalStatus:true });
      preserveBranchContextForAssistantSave();
      settleSessionStreamingTerminalState(sid, "完成");
      const branchRenderAfterSave = shouldRenderBranchAfterAssistantSave();
      clearTerminalSessionUiState();
      await saveAssistantOnce();
      try{ requestCloudMessageRealtimeFlush('assistant_done'); }catch(_){ }
      let renderedAssistantAfterSave = false;
      if(continuationTarget){
        try{ invalidateChatRenderCache(); }catch(_){ }
        try{ renderList(); }catch(_){ }
        try{ if(isViewingStreamSession()) renderChat(); }catch(_){ }
        renderedAssistantAfterSave = true;
      }
      if(imageOnlyCompleted && finalizedBubble?.isConnected && isViewingStreamSession()){
        try{ finalizedBubble.remove(); }catch(_){ }
        try{ if(liveDraftBubbleEls[sid] === finalizedBubble) delete liveDraftBubbleEls[sid]; }catch(_){ }
        try{ invalidateChatRenderCache(); }catch(_){ }
        renderAll();
        renderedAssistantAfterSave = true;
        if(imageOnlyScrollState){
          requestAnimationFrame(()=>{
            try{
              if(!isViewingStreamSession()) return;
              const maxTop = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
              chatEl.scrollTop = Math.max(0, Math.min(Number(imageOnlyScrollState.top || 0) || 0, maxTop));
              scrollChatToBottom(false);
              saveCurrentChatScrollState(sid);
            }catch(_){ }
          });
        }
      }
      if(branchRenderAfterSave && !renderedAssistantAfterSave){
        renderBranchAfterAssistantSave();
      }
      try{
        const finalMsForMessage = _rtClampElapsedMsForSession(sid, Math.max(0, Number(ensureSessionRuntime(sid)?.rtFinalMs || getSessionById(sid)?.rtFinalMs || 0) || 0));
        _rtPersistFinalMsToLastAssistant(sid, finalMsForMessage);
      }catch(_){ }
      queueAiTitleAfterReply(sid);
      if(!isSessionVisibleInMainView(sid)) showCrossSessionCompletionNotice(sid, { state:'done', previewText: finalPreviewText, message:'回答已完成，点击查看' });
      clearPendingAssistantSnapshot(sid, { immediate:true });
      {
        const rt = ensureSessionRuntime(sid);
        rt.draftText = "";
        rt.statusText = "";
        rt.draftProcessText = "";
        rt.draftFiles = [];
        rt.draftImageReplies = [];
        rt.draftWeatherPayload = null;
        // Do not clear reasoning/reasoningMeta here: saveAssistantOnce() has just
        // persisted them and the final render may still read the runtime snapshot.
        // They will be cleared when the next turn starts or when terminal state is reset.
        rt.sources = [];
        rt.generationUsage = null;
        delete rt.assistantContinuationTarget;
        rt.streaming = false;
      }
      clearSessionPendingJob(sid, { immediate:true });
      if(isViewingStreamSession()) rtStop(sid, true);
      return;
    }
    if(event === "error"){
      clearImagePullbackSoftTimer();
      const rawErr = String(payload?.error || "unknown error");
      preserveBranchContextForAssistantSave();
      if(rawErr === '__async_chat_job_stopped__'){
        terminalSeen = true;
        finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
        flushRenderBuffer(true);
        setStatusForSession("已停止");
        setSessionRuntimeDraftText(sid, `（已停止）\n${current}`);
        refreshStreamDraftForSession();
        preserveBranchContextForAssistantSave();
        settleSessionStreamingTerminalState(sid, "已停止");
        clearTerminalSessionUiState();
        await saveAssistantOnce();
        try{ requestCloudMessageRealtimeFlush('assistant_stopped'); }catch(_){ }
        if(!isSessionVisibleInMainView(sid)) showCrossSessionCompletionNotice(sid, { state:'stopped', previewText: current, message:'已停止生成，点击查看' });
        clearPendingAssistantSnapshot(sid, { immediate:true });
        {
          const rt = ensureSessionRuntime(sid);
          rt.draftText = "";
          rt.statusText = "";
          rt.draftFiles = [];
          // Keep reasoning/reasoningMeta until terminal cleanup has persisted/rendered it.
          rt.sources = [];
          rt.streaming = false;
        }
        clearSessionPendingJob(sid, { immediate:true });
        if(isViewingStreamSession()) rtStop(sid, true);
        return;
      }
      if(rawErr === '__async_chat_job_upstream_interrupted__'){
        terminalSeen = true;
        finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
        flushRenderBuffer(true);
        const msg = String(payload?.message || '连接中断，已保留已生成内容');
        setSessionBackendError(sid, msg);
        setStatusForSession('连接中断');
        if(shouldKeepCurrentDraftOnTerminalError()){
          setSessionRuntimeDraftText(sid, current);
        }else if(Array.isArray(_genFiles) && _genFiles.length){
          setSessionRuntimeDraftText(sid, '');
        }else{
          setSessionRuntimeDraftText(sid, msg);
        }
        refreshStreamDraftForSession();
        preserveBranchContextForAssistantSave();
        settleSessionStreamingTerminalState(sid, "连接中断");
        clearTerminalSessionUiState();
        await saveAssistantOnce();
        try{ requestCloudMessageRealtimeFlush('assistant_interrupted'); }catch(_){ }
        if(!isSessionVisibleInMainView(sid)) showCrossSessionCompletionNotice(sid, { state:'interrupted', previewText: current || msg, message:'连接中断，点击查看' });
        clearPendingAssistantSnapshot(sid, { immediate:true });
        {
          const rt = ensureSessionRuntime(sid);
          rt.draftText = "";
          rt.statusText = "";
          rt.draftFiles = [];
          rt.draftImageReplies = [];
          rt.draftWeatherPayload = null;
          // Keep reasoning/reasoningMeta until terminal cleanup has persisted/rendered it.
          rt.sources = [];
          rt.streaming = false;
        }
        clearSessionPendingJob(sid, { immediate:true });
        if(isViewingStreamSession()) rtStop(sid, true);
        return;
      }
      const forcedImageTimeoutMsg = normalizeImageGenerationForcedTimeoutMessage(rawErr);
      if(forcedImageTimeoutMsg){
        terminalSeen = true;
        finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
        flushRenderBuffer(true);
        current = String(current || '').trim() || forcedImageTimeoutMsg;
        setSessionBackendError(sid, forcedImageTimeoutMsg);
        setStatusForSession("出错");
        setSessionRuntimeProcessText(sid, "");
        setSessionRuntimeDraftText(sid, current);
        refreshStreamDraftForSession();
        preserveBranchContextForAssistantSave();
        settleSessionStreamingTerminalState(sid, "出错");
        clearTerminalSessionUiState();
        await saveAssistantOnce();
        try{ requestCloudMessageRealtimeFlush('assistant_forced_timeout'); }catch(_){ }
        if(!isSessionVisibleInMainView(sid)) showCrossSessionCompletionNotice(sid, { state:'error', previewText: current, message: forcedImageTimeoutMsg });
        clearSessionPendingJob(sid, { immediate:true });
        if(isViewingStreamSession()) rtStop(sid, true);
        return;
      }
      terminalSeen = true;
      finalizeSessionRuntimeNativeReasoning(sid, { nativeReasoningDone:true });
      flushRenderBuffer(true);
      setStatusForSession("出错");
      setSessionBackendError(sid, rawErr);
      setSessionRuntimeProcessText(sid, "");
      const friendlyErr = explainSearchProviderStreamError(rawErr);
      if(shouldKeepCurrentDraftOnTerminalError()){
        setSessionRuntimeDraftText(sid, current);
      }else if(Array.isArray(_genFiles) && _genFiles.length){
        setSessionRuntimeDraftText(sid, '');
      }else{
        setSessionRuntimeDraftText(sid, '这次请求失败了，当前会话已保留，可稍后自动续连或重新发送。');
      }
      if(friendlyErr !== rawErr){
        const hintText = friendlyErr.split("\n提示：")[1] || "";
        if(hintText) setWebSettingsHint(hintText, "warn");
      }
      refreshStreamDraftForSession();
      preserveBranchContextForAssistantSave();
      settleSessionStreamingTerminalState(sid, "出错");
      clearTerminalSessionUiState();
      if(!isSessionVisibleInMainView(sid)) showCrossSessionCompletionNotice(sid, { state:'error', previewText: current, message:'生成出错，点击查看' });
      clearSessionPendingJob(sid, { immediate:true });
      if(isViewingStreamSession()) rtStop(sid, true);
      return;
    }
  };

  const streamPromise = (async ()=>{
    let jobId = String(o.resumeJobId || '').trim();
    let localStopOnly = false;
    activeStartController = null;
    activePollController = null;
    try{
      const s = getSessionById(sid);
      if(!s) throw new Error("会话不存在或已被删除");

      if(!_isResumeSession){
        clearPendingAssistantSnapshot(sid, { immediate:true });
        clearSessionPendingJob(sid, { immediate:true });
        const rtBoot = ensureSessionRuntime(sid);
        rtBoot.draftText = "";
        rtBoot.statusText = "";
        rtBoot.draftProcessText = "";
        rtBoot.draftFiles = [];
        rtBoot.draftImageReplies = [];
        rtBoot.reasoning = [];
        rtBoot.reasoningMeta = {};
        rtBoot.sources = [];
        if(continuationTarget) rtBoot.assistantContinuationTarget = continuationTarget;
        else delete rtBoot.assistantContinuationTarget;
        rtBoot.streaming = false;
        rtBoot.rtStartAt = 0;
        rtBoot.rtFinalMs = 0;
        current = "";
        renderBuffer = "";
        _firstTokenAt = 0;
        _receivedAssistantTextThisRun = false;
        _assistantSources = [];
        _imageReplyPayloads = [];
        _imageReplySignatureSet = new Set();
        _genFiles = [];
        persistPendingAssistantSnapshot(sid, {
          draft: "",
          process: "",
          files: [],
          imageReplies: [],
          status: "",
          streaming: false,
          reasoning: [],
          reasoningMeta: {},
          sources: [],
          rtStartAt: 0,
          rtFinalMs: 0,
        }, { immediate:true });
      }

      if(isViewingStreamSession() && !continuationTarget){
        placeholder = syncVisibleDraftBubble(sid);
        syncStreamingCaretForBubble(placeholder);
      }

      setSessionAbortReason(sid, "");
      if(isViewingStreamSession()) setSendButtonMode("streaming");
      streamControllers[sid] = {
        abort(){
          localStopOnly = true;
          try{ flushRenderBuffer(true); }catch(_){ }
          try{ persistStreamingDraftsToStore({ immediate:true }); }catch(_){ }
          try{ flushPendingStoreWrites({ cloud:false, keepalive:false, reason:'manual_stop_preserve_draft' }); }catch(_){ }
          try{ activeStartController?.abort('manual_stop'); }catch(_){ }
          try{ activePollController?.abort('manual_stop'); }catch(_){ }
        }
      };
      markSessionStreaming(sid, true, ensureSessionRuntime(sid).statusText || asyncStreamT('stream.thinking', null, 'Thinking…'), { forceNewTimer: !jobId });
      refreshStatusForActiveSession();
      _statusMetaText = "";
      if(isViewingStreamSession()) rtSyncActiveDisplay();

      if(!jobId){
        const requestBody = o.requestBody || null;
        if(!requestBody || typeof requestBody !== 'object'){
          throw new Error("缺少请求体，无法启动后台任务");
        }
        let startRes = null;
        let startData = {};
        const maxStartAttempts = shouldPreferStableAsyncPollTransport() ? 4 : 2;
        for(let startAttempt = 0; startAttempt < maxStartAttempts; startAttempt++){
          activeStartController = new AbortController();
          try{
            startRes = await fetch('/api3/chat_async/start', {
              method:'POST',
              headers:{ 'Content-Type':'application/json' },
              body: JSON.stringify(requestBody),
              cache:'no-store',
              signal: activeStartController.signal,
            });
          }finally{
            activeStartController = null;
          }
          startData = await startRes.json().catch(()=>({}));
          const retryableBusy = !startRes.ok && (startRes.status === 429 || startRes.status === 503) && /^(server_busy_retryable|chat_async_busy)$/i.test(String(startData?.code || ''));
          if(!retryableBusy || startAttempt >= maxStartAttempts - 1) break;
          const retryAfterMs = Math.max(800, Math.min(Number(startData?.retry_after_ms || 0) || 0, 8000)) || (1200 + startAttempt * 900);
          setStatusForSession('服务器正在处理较多任务，正在自动排队重试…');
          refreshStreamDraftForSession();
          await sleep(retryAfterMs);
        }
        if(!startRes || !startRes.ok){
          if(handleForcedLogin(startData, startData?.message || startData?.error || ('HTTP ' + (startRes ? startRes.status : 0)))) return;
          if(startRes?.status === 409 && String(startData?.code || '').trim() === 'conversation_run_active' && typeof o.onConversationRunConflict === 'function'){
            const handled = await o.onConversationRunConflict(startData || {});
            if(handled) return;
          }
          throw new Error(startData?.message || startData?.error || ('HTTP ' + (startRes ? startRes.status : 0)));
        }
        jobId = String(startData?.job_id || '').trim();
        imagePullbackSourceJobId = jobId;
        activeEventJobId = jobId;
        if(!jobId) throw new Error("后台任务未返回 job_id");
        setSessionPendingJob(sid, jobId, 0, String(startData?.turn_id || requestBody?.client_turn_id || ''));
      }else{
        imagePullbackSourceJobId = jobId;
        activeEventJobId = jobId;
        setSessionPendingJob(sid, jobId, getSessionPendingJobCursor(sid) || Number(o.resumeCursor || 0) || 0, String(o.resumeTurnId || getSessionById(sid)?.pendingJobTurnKey || ''));
      }

      const hintTimer = setTimeout(()=>{
        if(isSessionStreaming(sid) && !_firstTokenAt){
          setStatusForSession(normalizeStreamStatusText("等待响应中…（如果一直卡住，检查后端 /api3/chat_async/poll 是否可访问）"));
        }
      }, 12000);

      try{
        let streamHandled = false;
        const preferPollTransport = shouldPreferStableAsyncPollTransport();
        const skipStreamTransport = preferPollTransport && shouldSkipAsyncStreamTransportForNow();
        const canTryStreamTransport = canUseAsyncChatJobStreamTransport() && !skipStreamTransport;
        if(preferPollTransport && canTryStreamTransport){
          setStatusForSession('正在建立公网流式通道，连接不稳会自动续传…');
          refreshStreamDraftForSession();
        }else if(preferPollTransport){
          setStatusForSession('当前连接使用稳定续传模式…');
          refreshStreamDraftForSession();
        }
        if(canTryStreamTransport){
          try{
            const streamCursor = getSessionPendingJobCursor(sid);
            const streamCtl = new AbortController();
            activePollController = streamCtl;
            const streamResult = await consumeAsyncChatJobEventStream(
              `/api3/chat_async/stream?job_id=${encodeURIComponent(jobId)}&cursor=${encodeURIComponent(streamCursor)}&_=${Date.now()}`,
              {
                controller: streamCtl,
                firstByteTimeoutMs: asyncStreamFirstByteTimeoutMs(),
                shouldStop: ()=> !!localStopOnly,
                onEvent: async (eventName, payload)=>{
                  await processAsyncJobEvent(String(eventName || ''), payload || {});
                }
              }
            );
            activePollController = null;
            if(imagePullbackStopPolling){
              streamHandled = true;
            }else if(localStopOnly){
              await processAsyncJobEvent('error', { error:'__async_chat_job_stopped__' });
              streamHandled = true;
            }else if(streamResult?.ok && (terminalSeen || streamResult?.aborted)){
              recordAsyncStreamTransportHealth(Number(streamResult?.eventCount || 0) > 0 || terminalSeen, 'stream_done');
              streamHandled = true;
            }else if(streamResult?.ok === false){
              const streamData = streamResult?.data || {};
              const streamStatus = Number(streamResult?.httpStatus || 0);
              if(streamStatus === 404){
                clearSessionPendingJob(sid, { immediate:true });
                await processAsyncJobEvent('error', { error: String(streamData?.message || streamData?.error || '任务不存在或已过期') });
                streamHandled = true;
              }else if(handleForcedLogin(streamData, streamData?.message || streamData?.error || ('HTTP ' + streamStatus))) return;
              else if(getSessionPendingJobId(sid)){
                recordAsyncStreamTransportHealth(false, streamData?.error || ('HTTP ' + streamStatus));
                setStatusForSession('流式通道不可用，改用轮询续传…');
                refreshStreamDraftForSession();
              }
            }else if(streamResult?.ok && Number(streamResult?.eventCount || 0) > 0){
              recordAsyncStreamTransportHealth(false, 'stream_interrupted');
              setStatusForSession('流式通道短暂中断，正在自动续传…');
              refreshStreamDraftForSession();
            }
          }catch(err){
            activePollController = null;
            if(imagePullbackStopPolling){
              streamHandled = true;
            }else if(localStopOnly){
              await processAsyncJobEvent('error', { error:'__async_chat_job_stopped__' });
              streamHandled = true;
            }else if(getSessionPendingJobId(sid)){
              recordAsyncStreamTransportHealth(false, stableNetworkReason(err, 'stream_failed'));
              setStatusForSession('流式通道续连失败，改用轮询续传…');
              refreshStreamDraftForSession();
            }
          }
        }

        if(!streamHandled){
          let consecutivePollFailures = 0;
          const maxConsecutivePollFailures = shouldPreferStableAsyncPollTransport() ? 60 : 24;
          while(true){
            if(imagePullbackStopPolling) break;
            if(localStopOnly && !getSessionPendingJobId(sid)) break;

            const cursor = getSessionPendingJobCursor(sid);
            let pollRes = null;
            let pollData = {};
            try{
              const ctl = new AbortController();
              activePollController = ctl;
              const timeoutId = setTimeout(()=>{
                try{ ctl.abort('poll_timeout'); }catch(_){ }
              }, shouldPreferStableAsyncPollTransport() ? 30000 : 18000);
              try{
                pollRes = await fetch(`/api3/chat_async/poll?job_id=${encodeURIComponent(jobId)}&cursor=${encodeURIComponent(cursor)}&timeout_ms=8000`, {
                  cache:'no-store',
                  signal: ctl.signal,
                });
              }finally{
                activePollController = null;
                clearTimeout(timeoutId);
              }
              pollData = await pollRes.json().catch(()=>({}));
            }catch(err){
              activePollController = null;
              if(imagePullbackStopPolling){
                break;
              }
              if(localStopOnly){
                await processAsyncJobEvent('error', { error:'__async_chat_job_stopped__' });
                break;
              }
              consecutivePollFailures += 1;
              if(getSessionPendingJobId(sid) && consecutivePollFailures <= maxConsecutivePollFailures){
                const retryMs = Math.max(300, Math.min(6500, 350 * consecutivePollFailures));
                const retryLabel = consecutivePollFailures <= 2 ? '网络抖动，正在续连…' : `连接不稳，正在第 ${consecutivePollFailures} 次续连…`;
                setStatusForSession(retryLabel);
                refreshStreamDraftForSession();
                await new Promise(resolve => setTimeout(resolve, retryMs));
                continue;
              }
              throw err;
            }

            if(!pollRes || !pollRes.ok){
              if(imagePullbackStopPolling){
                break;
              }
              if(localStopOnly){
                await processAsyncJobEvent('error', { error:'__async_chat_job_stopped__' });
                break;
              }
              const pollStatus = Number(pollRes?.status || 0);
              if(pollStatus === 404){
                clearSessionPendingJob(sid, { immediate:true });
                await processAsyncJobEvent('error', { error: String(pollData?.message || pollData?.error || '任务不存在或已过期') });
                break;
              }
              if(handleForcedLogin(pollData, pollData?.message || pollData?.error || ('HTTP ' + pollStatus))) return;
              const fatalHttp = [400, 403].includes(pollStatus);
              const pollErr = new Error(pollData?.message || pollData?.error || ('HTTP ' + pollStatus));
              consecutivePollFailures += 1;
              if(!fatalHttp && getSessionPendingJobId(sid) && consecutivePollFailures <= maxConsecutivePollFailures){
                const retryMs = Math.max(300, Math.min(6500, 350 * consecutivePollFailures));
                const retryLabel = consecutivePollFailures <= 2 ? '网络抖动，正在续连…' : `连接不稳，正在第 ${consecutivePollFailures} 次续连…`;
                setStatusForSession(retryLabel);
                refreshStreamDraftForSession();
                await new Promise(resolve => setTimeout(resolve, retryMs));
                continue;
              }
              throw pollErr;
            }

            consecutivePollFailures = 0;
            const events = Array.isArray(pollData?.events) ? pollData.events : [];
            for(const item of events){
              await processAsyncJobEvent(String(item?.event || ''), item?.payload || {});
            }

            const status = String(pollData?.status || '').trim().toLowerCase();
            const done = !!pollData?.done || ['done', 'error', 'stopped'].includes(status);

            if(done){
              if(!terminalSeen){
                const doneFullText = typeof pollData?.full_text === 'string' ? pollData.full_text : '';
                if(doneFullText){
                  _receivedAssistantTextThisRun = true;
                  if(!current){
                    current = doneFullText;
                    renderBuffer = doneFullText;
                    flushRenderBuffer(true);
                  }else if(doneFullText.startsWith(current)){
                    const tail = doneFullText.slice(current.length);
                    current = doneFullText;
                    if(tail){
                      renderBuffer += tail;
                      flushRenderBuffer(true);
                    }
                  }else if(doneFullText.length >= current.length){
                    current = doneFullText;
                    renderBuffer = doneFullText;
                    flushRenderBuffer(true);
                  }
                }

                const doneArtifacts = Array.isArray(pollData?.artifacts) ? pollData.artifacts : [];
                const doneMeta = (pollData?.meta && typeof pollData.meta === 'object') ? { ...pollData.meta } : null;
                if((doneMeta && Object.keys(doneMeta).length) || doneArtifacts.length){
                  await processAsyncJobEvent('meta', { ...(doneMeta || {}), artifacts: doneArtifacts });
                }

                if(status === 'stopped'){
                  await processAsyncJobEvent('error', { error:'__async_chat_job_stopped__' });
                }else if(status === 'error'){
                  await processAsyncJobEvent('error', { error: String(pollData?.error || 'unknown error') });
                }else{
                  await processAsyncJobEvent('done', {});
                }
              }
              break;
            }

            const waitMs = Math.max(8, Math.min(90, Number(pollData?.poll_after_ms || 16) || 16));
            if(waitMs > 0){
              await new Promise(resolve => setTimeout(resolve, waitMs));
            }
          }
        }
      }finally{
        try{ clearTimeout(hintTimer); }catch(_){ }
      }
    }catch(e){
      if(imagePullbackStopPolling){
        // 已转入拉回生图，本轮前端轮询自然结束。
      }else if(localStopOnly && !terminalSeen){
        await processAsyncJobEvent('error', { error:'__async_chat_job_stopped__' });
      }else{
        flushRenderBuffer(true);
        if(getSessionPendingJobId(sid)){
          setStatusForSession("连接中断，正在重连…");
        }else{
          setStatusForSession("出错");
        }
        const message = String(e?.message || e || '');
        setSessionBackendError(sid, message);
        if(!getSessionPendingJobId(sid)){
          const friendlyErr = explainSearchProviderStreamError(message);
          setSessionRuntimeProcessText(sid, '');
          resetSessionRuntimeDraftState(sid);
          clearPendingAssistantSnapshot(sid, { immediate:true });
          removeVisibleDraftBubbleForSession(sid);
          if(friendlyErr !== message){
            const hintText = friendlyErr.split("\n提示：")[1] || "";
            if(hintText) setWebSettingsHint(hintText, 'warn');
          }
        }
        refreshStreamDraftForSession();
        if(isViewingStreamSession()) rtStop(sid, true);
      }
    }finally{
      clearImagePullbackSoftTimer();
      try{
        if(!terminalSeen && !imagePullbackStopPolling) flushRenderBuffer(true);
      }catch(_){ }
      if(terminalSeen){
        resetSessionTerminalRuntimeState(sid, { finalizeTimer:true, preserveReasoning:true });
      }else{
        if(isViewingStreamSession()) rtStop(sid, false);
        markSessionStreaming(sid, false, "");
      }
      if(terminalSeen && isViewingStreamSession()){
        removeVisibleDraftBubbleForSession(sid);
      }
      flushPendingRenderAll();
      const finalDraftBubble = liveDraftBubbleEls[sid];
      if(finalDraftBubble) syncStreamingCaretForBubble(finalDraftBubble);
      delete liveDraftBubbleEls[sid];
      clearSessionStreamState(sid);
      if(isViewingStreamSession()){
        setSendButtonMode(isSessionStreaming(sid) ? "streaming" : "idle");
        inputEl.focus();
      }
      try{ await _saveAssistantPromise; }catch(_){ }
      refreshStatusForActiveSession();
      if(isSettingsModalOpen()) renderPassiveUiForModal();
      else if(finalizedVisibleDraft && terminalSeen && isViewingStreamSession()){
        renderList();
        refreshComposerEditBar();
        refreshStatusForActiveSession();
      }else{
        renderAll();
      }
      if(terminalSeen && isViewingStreamSession()){
        removeVisibleDraftBubbleForSession(sid);
      }

      const abortReason = getSessionAbortReason(sid);
      const shouldAutoResume = !terminalSeen
        && getSessionPendingJobId(sid)
        && document.visibilityState === 'visible'
        && !['manual_stop', 'clear_all'].includes(String(abortReason || '').trim());
      if(shouldAutoResume){
        setTimeout(()=>{ maybeResumeSessionJob(sid, { force:true }); }, 800);
      }
      const shouldContinueAfterPullback = !terminalSeen && imagePullbackContinueAfterHandoff && imagePullbackContinuationRequest && !getSessionPendingJobId(sid);
      if(shouldContinueAfterPullback){
        const continuationBody = imagePullbackContinuationRequest;
        imagePullbackContinueAfterHandoff = false;
        imagePullbackContinuationRequest = null;
        setTimeout(()=>{
          attachSessionToAsyncJob(sid, { requestBody: continuationBody, imagePullbackContinuation:true }).catch(err => {
            try{ console.warn('[image_pullback_continue] failed', err); }catch(_){ }
          });
        }, 0);
      }
    }
  })();

  streamPromises[sid] = streamPromise;
  return streamPromise;
}

const _sessionRunDiscoveryPromises = Object.create(null);

async function discoverSessionAsyncRun(sessionId, opts={}){
  const sid = String(sessionId || store?.activeId || '').trim();
  if(!sid || !getSessionById(sid)) return null;
  if(_sessionRunDiscoveryPromises[sid]) return _sessionRunDiscoveryPromises[sid];
  const activeOnly = opts?.activeOnly === true;
  const requestedTurnId = Object.prototype.hasOwnProperty.call(opts || {}, 'turnId')
    ? String(opts.turnId || '').trim()
    : (typeof stableAsyncChatTurnIdForSession === 'function' ? stableAsyncChatTurnIdForSession(sid, getSessionById(sid)) : '');
  const task = (async ()=>{
    const params = new URLSearchParams({ conversation_id:sid });
    if(requestedTurnId) params.set('turn_id', requestedTurnId);
    if(activeOnly) params.set('active_only', '1');
    let res = null;
    let data = {};
    try{
      res = await fetch('/api3/chat_async/active?' + params.toString(), { cache:'no-store', credentials:'same-origin' });
      data = await res.json().catch(()=>({}));
    }catch(_){
      return null;
    }
    if((res.status === 401 || res.status === 403) && handleForcedLogin(data, data?.message || data?.error || '当前登录已失效')) return null;
    if(!res.ok || !data?.ok) return null;
    if(data?.found === false) return null;
    const jobId = String(data.job_id || '').trim();
    if(!jobId) return null;
    const runTurnId = String(data.turn_id || '').trim();
    const localTurnId = typeof stableAsyncChatTurnIdForSession === 'function' ? stableAsyncChatTurnIdForSession(sid, getSessionById(sid)) : '';
    if(runTurnId && localTurnId && runTurnId !== localTurnId && !activeOnly) return null;
    return {
      jobId,
      turnId: runTurnId,
      cursor: 0,
      status: String(data.status || '').trim(),
      statusText: String(data.status_text || '').trim(),
      done: !!data.done,
      currentSeq: Math.max(0, Number(data.current_seq || 0) || 0),
    };
  })();
  _sessionRunDiscoveryPromises[sid] = task;
  try{ return await task; }
  finally{ if(_sessionRunDiscoveryPromises[sid] === task) delete _sessionRunDiscoveryPromises[sid]; }
}

async function rollbackOutgoingTurnForConversationConflict(sessionId, outgoingSendId, snapshot, activeRun){
  const sid = String(sessionId || '').trim();
  const sendId = String(outgoingSendId || '').trim();
  const run = activeRun && typeof activeRun === 'object' ? activeRun : {};
  if(!sid || !sendId || !String(run.job_id || '').trim()) return false;
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const stamp = Date.now();
  try{
    await updateSessionById(sid, session=>{
      session.messages = (Array.isArray(session.messages) ? session.messages : []).filter(message => {
        return String(message?._client_send_id || message?.client_send_id || '').trim() !== sendId;
      });
      session.composerDraft = String(snap.text || '');
      session.composerDraftUpdatedAt = stamp;
      session.composerAttachmentDraft = {
        files: (Array.isArray(snap.files) ? snap.files : []).map(item => {
          try{ return normalizeComposerAttachmentDraftFile(item); }catch(_){ return item; }
        }).filter(Boolean),
        images: (Array.isArray(snap.images) ? snap.images : []).map(item => {
          try{ return normalizeComposerAttachmentDraftImage(item); }catch(_){ return item; }
        }).filter(Boolean),
      };
      session.composerAttachmentDraftUpdatedAt = stamp;
      try{ webaiOfficialPersistActivePath(session); }catch(_){ }
    }, { skipCompress:true });
    clearPendingAssistantSnapshot(sid, { immediate:true });
    clearSessionPendingJob(sid, { immediate:true });
    setSessionPendingJob(sid, String(run.job_id || ''), 0, String(run.turn_id || ''));
    if(String(store?.activeId || '').trim() === sid){
      if(!String(inputEl?.value || '').trim()){
        inputEl.value = String(snap.text || '');
        resizeComposer();
      }
      try{ restoreComposerAttachmentDraft(sid, { replace:true }); }catch(_){ }
      updateComposerActionState();
    }
    try{ requestCloudMessageRealtimeFlush('conversation_run_conflict_rollback'); }catch(_){ }
    setAsyncSessionStatus(sid, String(run.status_text || '').trim() || '另一设备已先开始此会话，当前输入已恢复为草稿，正在接回已有回答…');
    return true;
  }catch(_){
    return false;
  }
}

async function maybeResumeSessionJob(sessionId, opts){
  const sid = String(sessionId || store?.activeId || '').trim();
  if(!sid) return null;
  const session = getSessionById(sid);
  if(!session){
    clearSessionPendingJob(sid, { immediate:true });
    return null;
  }
  const pendingSnapshot = pendingAssistantSnapshotForSession(sid, store);
  const rt = ensureSessionRuntime(sid);
  const last = lastVisibleMessageFromSession(session);
  const lastIsAssistant = String(last?.role || '').toLowerCase() === 'assistant';
  if(lastIsAssistant){
    resetSessionTerminalRuntimeState(sid, { finalizeTimer:true });
    return null;
  }
  if(getSessionPromise(sid)) return getSessionPromise(sid);
  if(isSessionStreaming(sid) && !(opts && opts.force)) return null;
  let jobId = getSessionPendingJobId(sid);
  let turnId = String(session.pendingJobTurnKey || session.runRecovery?.turn_key || '').trim();
  let cursor = getSessionPendingJobCursor(sid);
  if(!jobId){
    const run = await discoverSessionAsyncRun(sid, { activeOnly:false });
    if(!run) return null;
    jobId = run.jobId;
    turnId = run.turnId || turnId;
    // 游标属于设备，不继承其他设备已经消费到的位置。
    cursor = 0;
    setSessionPendingJob(sid, jobId, cursor, turnId);
    if(run.statusText) setAsyncSessionStatus(sid, run.statusText);
    else setAsyncSessionStatus(sid, run.done ? '正在恢复已完成回答…' : '正在接回云端生成任务…');
  }
  return attachSessionToAsyncJob(sid, {
    resumeJobId: jobId,
    resumeCursor: cursor,
    resumeTurnId: turnId,
    isResume: true
  });
}

function currentTurnImageHasSandboxIndex(imageItem){
  const img = imageItem && typeof imageItem === 'object' ? imageItem : {};
  const reg = img.file_registry && typeof img.file_registry === 'object' ? img.file_registry : {};
  const storageRef = String(img.model_storage_ref || img.storage_ref || reg.model_storage_ref || reg.storage_ref || '').trim();
  if(storageRef.toLowerCase().startsWith('upload://')) return true;
  if(String(img.file_library_id || img.library_file_id || img.registry_file_id || img.file_id || reg.file_id || '').trim()) return true;
  const candidates = [
    img.download_url, img.view_url, img.url, img.persisted_url, img.server_url,
    img.image_url?.url,
    reg.download_url, reg.view_url, reg.url,
  ];
  for(const value of candidates){
    const raw = String(value || '').trim();
    if(!raw) continue;
    if(/^\/api3\/(?:uploads|download)\//i.test(raw)) return true;
    try{
      const u = new URL(raw, window.location.origin);
      if(u.origin === window.location.origin && /^\/api3\/(?:uploads|download)\//i.test(u.pathname || '')) return true;
    }catch(_){ }
  }
  return false;
}

async function waitForCurrentTurnImageSandboxIndexes(sessionId, opts={}){
  const timeoutMs = Math.max(1000, Math.min(Number(opts.timeoutMs || 12000) || 12000, 30000));
  const started = Date.now();
  const sleep = (ms)=> new Promise(resolve => setTimeout(resolve, ms));
  const capturedRows = Array.isArray(opts.imageRows) ? opts.imageRows : null;
  const rows = ()=> capturedRows || (Array.isArray(pastedImages) ? pastedImages : []);
  let announced = false;
  while(Date.now() - started < timeoutMs){
    const images = rows();
    const failed = images.find(img => String(img?._upload_error || '').trim());
    if(failed){
      return { ok:false, reason:'upload_failed', message:String(failed._upload_error || '图片上传失败') };
    }
    const pending = images.filter(img => !!img?._upload_pending || !!img?._ocr_pending);
    const missingIndex = images.filter(img => !currentTurnImageHasSandboxIndex(img));
    if(!pending.length && !missingIndex.length){
      return { ok:true, waited_ms: Date.now() - started };
    }
    if(!announced && images.length){
      announced = true;
      try{ setStatus('正在等待图片上传完成，准备沙盒文件索引…'); }catch(_){ }
    }
    await sleep(180);
  }
  const missing = rows().filter(img => !currentTurnImageHasSandboxIndex(img));
  return {
    ok:false,
    reason:'image_index_timeout',
    missing_count: missing.length,
    message: missing.length ? '图片还没有完成上传登记，暂时不能发送；请稍后重试。' : '图片上传状态未完成，请稍后重试。',
  };
}

const _sendStartLocks = new Set();

async function send(){

  const selectedModel = isHomeLandingView
    ? String(currentHomeLandingModel() || '').trim()
    : String(getActive()?.model || '').trim();
  if(!selectedModel){
    try{ setStatus('请先选择模型'); }catch(_){ }
    try{ toast(window.AperviaI18n?.t('composer.select_model') || 'Select a model first'); }catch(_){ }
    try{ openModelPicker(); }catch(_){ }
    return;
  }

  let sessionId = store.activeId;
  if(isHomeLandingView || !sessionId || !store?.sessions?.[sessionId]){
    const session = createSessionFromHomeLanding();
    sessionId = session.id;
    saveStore();
    syncSessionRoute({ sessionId });
    renderList();
  }
  if(!sessionId) return;
  if((typeof hasBlockingComposerAttachmentUploads === 'function') && hasBlockingComposerAttachmentUploads()){
    try{ setStatus('附件上传完成后再发送'); }catch(_){ }
    updateComposerActionState();
    return;
  }
  const activeBeforePromotion = store?.sessions?.[sessionId];
  if(typeof isSharedChatPreviewSession === 'function' && isSharedChatPreviewSession(activeBeforePromotion)){
    const hasSharedSendIntent = !!(
      String(inputEl?.value || '').trim()
      || String(composerQuoteState?.text || '').trim()
      || (Array.isArray(pendingFiles) && pendingFiles.length)
      || (Array.isArray(pastedImages) && pastedImages.length)
    );
    if(!hasSharedSendIntent){
      updateComposerActionState();
      return;
    }
    const stableSessionId = typeof promoteSharedChatPreviewForSend === 'function'
      ? await promoteSharedChatPreviewForSend(sessionId)
      : '';
    if(!stableSessionId){
      updateComposerActionState();
      return;
    }
    sessionId = stableSessionId;
  }
  if(_sendStartLocks.has(sessionId)){
    updateComposerActionState();
    return getSessionPromise(sessionId) || null;
  }
  _sendStartLocks.add(sessionId);
  try{
  if(isSessionArchived(getSessionById(sessionId))){
    refreshArchivedComposerState();
    try{ toast(window.AperviaI18n?.t('composer.archived') || 'This conversation is archived. Unarchive it before continuing.'); }catch(_){ }
    return;
  }
  if(isCloudSessionStub(getSessionById(sessionId))){
    setStatus('正在加载当前对话，加载完成后再发送…');
    const hydrated = await hydrateActiveSessionAfterSwitch(sessionId, { force:true, statusText:'已加载当前会话' });
    if(!hydrated && isCloudSessionStub(getSessionById(sessionId))){
      try{ toast(window.AperviaI18n?.t('composer.loading_retry') || 'This conversation is still loading. Apervia will retry automatically.'); }catch(_){ }
      return;
    }
  }
  clearSessionBackendError(sessionId, { render:false });
  dismissCrossSessionCompletionNotice(sessionId);
  clearGlobalAppError();
  prepareSessionForCleanAssistantTurn(sessionId, { immediate:true });
  try{ webaiOfficialCleanupStaleRuntimeBeforeSend(sessionId); }catch(_){ }
  const streamCheck = canStartStreamingForSession(sessionId);
  if(!streamCheck.ok){
    const blockText = describeParallelStreamBlock(streamCheck);
    if(blockText) setStatus(blockText);
    if(streamCheck.reason === 'same_session_streaming') return getSessionPromise(sessionId) || null;
    return;
  }

  // 发送前先查询账号级会话运行态，避免另一设备已经开始生成时本机再追加一个并发回合。
  const existingCloudRun = await discoverSessionAsyncRun(sessionId, { activeOnly:true, turnId:'' });
  if(existingCloudRun && !existingCloudRun.done){
    setSessionPendingJob(sessionId, existingCloudRun.jobId, 0, existingCloudRun.turnId);
    setStatus(existingCloudRun.statusText || '此会话正在另一设备生成，正在同步进度…');
    try{ if(typeof refreshCloudStoreIfChanged === 'function') await refreshCloudStoreIfChanged(); }catch(_){ }
    setTimeout(()=>{ maybeResumeSessionJob(sessionId, { force:true }); }, 0);
    return getSessionPromise(sessionId) || null;
  }

  try{
    const ownerAtSendStart = (typeof getComposerInputOwnerSessionId === 'function') ? String(getComposerInputOwnerSessionId() || '').trim() : '';
    if(ownerAtSendStart && ownerAtSendStart !== sessionId && store?.sessions?.[ownerAtSendStart]) sessionId = ownerAtSendStart;
  }catch(_){ }
  const activeSession = getSessionById(sessionId);
  const text = inputEl.value.trim();
  const quoteText = normalizeAssistantQuoteText(composerQuoteState?.text || '');
  const quoteMsgIndexRaw = Number(composerQuoteState?.msgIndex);
  const quoteMsgIndex = Number.isInteger(quoteMsgIndexRaw) && quoteMsgIndexRaw >= 0 ? quoteMsgIndexRaw : null;
  const quoteMsgId = String(composerQuoteState?.messageId || '').trim().slice(0, 220);
  const quoteSourceOffsetRaw = Number(composerQuoteState?.sourceOffset);
  const quoteSourceOffset = Number.isInteger(quoteSourceOffsetRaw) && quoteSourceOffsetRaw >= 0 ? quoteSourceOffsetRaw : null;
  const applyComposerQuoteMetaToUserMessage = message=>{
    const target = message && typeof message === 'object' ? message : null;
    if(!target) return target;
    if(quoteText){
      target._quote = quoteText;
      if(quoteMsgIndex !== null) target._quote_msg_index = quoteMsgIndex;
      else delete target._quote_msg_index;
      if(quoteMsgId) target._quote_msg_id = quoteMsgId;
      else delete target._quote_msg_id;
      if(quoteSourceOffset !== null) target._quote_source_offset = quoteSourceOffset;
      else delete target._quote_source_offset;
    }else{
      delete target._quote;
      delete target._quote_msg_index;
      delete target._quote_msg_id;
      delete target._quote_source_offset;
    }
    return target;
  };
  const messageCreatedAtMs = Date.now();
  const imageEndpointMode = getActiveApiEndpointMode();
  const outgoingSendId = createOutgoingUserClientSendId(sessionId, messageCreatedAtMs);
  const pendingFilesSource = Array.isArray(pendingFiles) ? pendingFiles.map(pf => ({ ...pf })) : [];
  const pastedImagesSource = Array.isArray(pastedImages) ? [...pastedImages] : [];
  if(pastedImagesSource.length > 0){
    const imageIndexReady = await waitForCurrentTurnImageSandboxIndexes(sessionId, { timeoutMs: 12000, imageRows: pastedImagesSource });
    if(!imageIndexReady?.ok){
      const msg = String(imageIndexReady?.message || '图片还没有完成上传登记，暂时不能发送；请稍后重试。');
      try{ reportAppError(msg); }catch(_){ }
      try{ setStatus(msg); }catch(_){ }
      updateComposerActionState();
      return;
    }
  }
  const pendingFilesSnapshot = pendingFilesSource.map(pf => ({ ...pf }));
  const outgoingUserFileAttachments = pendingFilesSnapshot.map(buildOutgoingUserFileAttachmentMeta).filter(Boolean);
  const pastedImagesSnapshot = pastedImagesSource.map((it, index) => {
    let cloned;
    try{ cloned = JSON.parse(JSON.stringify(it)); }catch(_){ cloned = it; }
    ensureStructuredImagePartDurableUrl(cloned);
    const isLibraryImage = isComposerLibraryImageAttachment(cloned);
    const operation = String(cloned?.operation || (isLibraryImage ? 'library_reuse' : 'upload')).trim() || 'upload';
    const normalized = ensureComposerImageAttachmentMeta(cloned, { sourceRole:'user', operation, createdAtMs: messageCreatedAtMs, imageSeq: index + 1, forceCreatedAt:true, endpointMode:imageEndpointMode });
    return isLibraryImage ? normalizeComposerAttachmentDraftImage(normalized) : normalized;
  });
  const effectiveText = text || (quoteText ? '请基于引用继续回答。' : '');
  if(pastedImagesSnapshot.length > COMPOSER_MAX_IMAGES){
    reportAppError(`最多上传 ${COMPOSER_MAX_IMAGES} 张图片`);
    updateComposerActionState();
    return;
  }
  if(pendingFilesSnapshot.length > COMPOSER_MAX_FILES){
    reportAppError(`最多添加 ${COMPOSER_MAX_FILES} 个文件`);
    updateComposerActionState();
    return;
  }
  if((pastedImagesSnapshot.length + pendingFilesSnapshot.length) > COMPOSER_MAX_ATTACHMENTS){
    reportAppError(`图片和文件合计最多 ${COMPOSER_MAX_ATTACHMENTS} 个`);
    updateComposerActionState();
    return;
  }
  if(!effectiveText && pastedImagesSnapshot.length === 0 && pendingFilesSnapshot.length === 0){
    updateComposerActionState();
    return;
  }

  const composerStillOwnsSendSession = (()=>{
    try{ return typeof composerInputBelongsToSession === 'function' ? composerInputBelongsToSession(sessionId) : (String(store?.activeId || '').trim() === String(sessionId || '').trim()); }catch(_){ return false; }
  })();

  if((pastedImagesSnapshot.length > 0 || pendingFilesSnapshot.length > 0) && composerStillOwnsSendSession){
    clearComposerPreviewDomForSend();
  }

  // 先清发送会话的草稿，但只在输入框仍属于该会话时改动可见 DOM。
  // 这样图片上传等待、云同步、切换会话交错时，不会把 A 会话已发送的文字恢复到 B 会话。
  persistComposerDraft(sessionId, "", { reason:'send_clear', stamp: messageCreatedAtMs, forceMeta:true, immediateLocal:true });
  if(composerStillOwnsSendSession){
    inputEl.value = "";
    clearComposerQuoteState({ silent:true });
    resizeComposer();
    updateComposerActionState();
  }else{
    try{ persistComposerQuoteDraft(sessionId, null); }catch(_){ }
  }

  const rewritePlan = buildRewritePlan(activeSession, effectiveText);
  let sendBranchContext = null;

  // 先把用户消息立刻写到会话里，别等图片落盘/历史压缩
  await updateSessionById(sessionId, s=>{
    const rewriteBranchTail = [];
    const rewriteBranchEnabled = !!(rewritePlan && Number.isInteger(rewritePlan.cutFrom) && rewritePlan.cutFrom >= 0);
    if(!rewriteBranchEnabled){
      try{ webaiOfficialPrepareOrdinarySend(s, sessionId); }catch(_){ }
    }

    if(pendingFilesSnapshot.length > 0 && !effectiveText && pastedImagesSnapshot.length === 0){
      for(const pf of pendingFilesSnapshot){
        const fileMsg = {
          role:"user",
          created_at_ms: messageCreatedAtMs,
          createdAtMs: messageCreatedAtMs,
          content:{ _kind:"file", id: pf.id, file_library_id: pf.file_library_id || pf.file_registry?.file_id || '', library_file_id: pf.library_file_id || pf.file_library_id || pf.file_registry?.file_id || '', source_type: pf.source_type || 'upload', source_role: pf.source_role || 'user_upload', filename: pf.filename, ext: pf.ext, url: pf.url || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'download') || "", view_url: pf.view_url || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'view') || "", download_url: pf.download_url || pf.url || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'download') || "", storage_ref: pf.storage_ref || pf.model_storage_ref || '', model_storage_ref: pf.model_storage_ref || pf.storage_ref || '', full_text_ref: pf.full_text_ref || pf.file_registry?.full_text_ref || '', size: pf.size || 0, note: pf.note || "", text_is_preview: !!pf.text_is_preview, full_text_available: !!pf.full_text_available, parsed_chars: Number(pf.parsed_chars || 0) || 0, parsed_lines: Number(pf.parsed_lines || 0) || 0, file_registry: pf.file_registry || null, code_summary: pf.code_summary || "", symbols: Array.isArray(pf.symbols) ? pf.symbols : [] }
        };
        pushOutgoingUserMessageOnce(rewriteBranchEnabled ? rewriteBranchTail : s.messages, decorateOutgoingUserMessage(fileMsg, outgoingSendId, `file_${String(pf.id || pf.filename || '').slice(0, 48)}`));

        // 文件正文/符号清单不再通过前端 system 预览塞给模型。
        // 每次请求会额外携带结构化 file_attachments，后端基于 file_registry/full_text 重新读取。
      }
    }

    if(rewritePlan?.newUserMessage){
      const cloned = JSON.parse(JSON.stringify(rewritePlan.newUserMessage));
      const useComposerStructuredContent = !!composerEditState?.useComposerStructuredContent;
      if(pastedImagesSnapshot.length > 0 || useComposerStructuredContent){
        const content = [];
        if(effectiveText) content.push({ type:"text", text: effectiveText });
        for(const img of pastedImagesSnapshot) content.push(img);
        cloned.content = content;
        attachOutgoingUserFileAttachmentsMeta(cloned, outgoingUserFileAttachments);
      }else{
        cloned.content = buildEditedUserContent(cloned.content, effectiveText);
        attachOutgoingUserFileAttachmentsMeta(cloned, outgoingUserFileAttachments);
      }
      cloned.created_at_ms = messageCreatedAtMs;
      cloned.createdAtMs = messageCreatedAtMs;
      applyComposerQuoteMetaToUserMessage(cloned);
      pushOutgoingUserMessageOnce(rewriteBranchEnabled ? rewriteBranchTail : s.messages, decorateOutgoingUserMessage(cloned, outgoingSendId, 'content'));
    }else if(!rewritePlan?.skipNewUserMessage && pastedImagesSnapshot.length > 0){
      const content = [];
      if(effectiveText) content.push({ type:"text", text: effectiveText });
      for(const img of pastedImagesSnapshot) content.push(img);
      const userMsg = attachOutgoingUserFileAttachmentsMeta({ role:"user", created_at_ms: messageCreatedAtMs, createdAtMs: messageCreatedAtMs, content }, outgoingUserFileAttachments);
      applyComposerQuoteMetaToUserMessage(userMsg);
      pushOutgoingUserMessageOnce(rewriteBranchEnabled ? rewriteBranchTail : s.messages, decorateOutgoingUserMessage(userMsg, outgoingSendId, 'content'));
    } else if(!rewritePlan?.skipNewUserMessage && effectiveText){
      const userMsg = attachOutgoingUserFileAttachmentsMeta({ role:"user", created_at_ms: messageCreatedAtMs, createdAtMs: messageCreatedAtMs, content:effectiveText }, outgoingUserFileAttachments);
      applyComposerQuoteMetaToUserMessage(userMsg);
      pushOutgoingUserMessageOnce(rewriteBranchEnabled ? rewriteBranchTail : s.messages, decorateOutgoingUserMessage(userMsg, outgoingSendId, 'content'));
    }

    if(rewriteBranchEnabled){
      sendBranchContext = webaiBranchReplaceTailForNewVersion(s, rewritePlan.cutFrom, rewriteBranchTail, rewritePlan.branchKind || 'user_edit');
    }else{
      // Continue from the currently active GPT/OpenWebUI-style branch.
      // After a user edit/regenerate, later ordinary sends must extend the active
      // branch version; otherwise later render/sync normalization can restore the
      // older branch tail and the just-sent user message appears to vanish while
      // the backend is already running.
      try{
        if(webaiBranchSessionHasState(s)){
          webaiBranchCommitActiveVersion(s, null);
        }
      }catch(_){ }
    }
    try{ webaiOfficialPersistActivePath(s); }catch(_){ }

    try{
      const isDefaultTitle = isDefaultSessionTitle(s.title);
      if(isDefaultTitle && !s.titleAutoLocked){
        const titleSeedText = maybeSeedSessionHeuristicTitle(s);
        if(titleSeedText){
          s.aiTitleDone = false;
        }
      }
    }catch(e){}

  }, { skipCompress: true });

  if(sendBranchContext){
    try{ ensureSessionRuntime(sessionId).pendingBranchSave = sendBranchContext; }catch(_){ }
  }

  if(String(store?.activeId || '').trim() === String(sessionId || '').trim()){
    syncSessionRoute({ sessionId });
  }

  persistPendingAssistantSnapshot(sessionId, {
    draft: '',
    status: '等待响应中…',
    streaming: true,
    files: [],
    imageReplies: [],
    rtStartAt: messageCreatedAtMs,
    rtFinalMs: 0,
  }, { immediate:true });
  try{ requestCloudMessageRealtimeFlush('user_message_sent'); }catch(_){ }

  // Make the new turn visible immediately after edit/regenerate follow-ups.
  // Some branch/sync paths can leave the render signature unchanged for one tick;
  // force the active conversation DOM to adopt the just-appended user turn and
  // its empty assistant draft before the async job starts streaming.
  try{
    if(String(store?.activeId || '').trim() === String(sessionId || '').trim()){
      invalidateChatRenderCache();
      renderChat();
      scrollChatToBottom(false);
    }
  }catch(_){ }

  // 图片原始数据异步落到 IndexedDB，避免阻塞消息首屏显示
  const localImgMap = new Map(); // localId -> dataUrl
  const persistedImages = [];
  if(pastedImagesSnapshot.length > 0){
    try{
      for(const it of pastedImagesSnapshot){
          const composerId = ensureComposerImageKey(it);
          const cacheRec = composerId ? getComposerImageLocalCache(composerId) : null;
          let dataUrl = String(it?.image_url?.url || '').trim();
          const persistedUrl = String(it?.persisted_url || it?.server_url || "").trim();
          if((!dataUrl || !dataUrl.startsWith("data:image/")) && typeof it?._preview_url === 'string' && String(it._preview_url || '').trim().startsWith('data:image/')){
            dataUrl = String(it._preview_url || '').trim();
          }
          if((!dataUrl || !dataUrl.startsWith("data:image/")) && cacheRec?.dataUrl){
            dataUrl = String(cacheRec.dataUrl || '').trim();
          }
          if((!dataUrl || !dataUrl.startsWith("data:image/")) && cacheRec?.file instanceof File){
            try{
              const rebuiltDataUrl = await fileToDataUrl(cacheRec.file);
              if(rebuiltDataUrl){
                dataUrl = rebuiltDataUrl;
                setComposerImageLocalCache(composerId, { dataUrl: rebuiltDataUrl, previewUrl: rebuiltDataUrl });
              }
            }catch(_){ }
          }
          if(!dataUrl || !String(dataUrl).startsWith("data:image/")){
            const durableUrl = composerLibraryDurableImageUrl(it);
            const stable = durableUrl || persistedUrl || structuredImagePartDisplayUrl(it);
            const display = composerLibraryDisplayImageUrl(it) || composerLibraryBrowserImageSource(stable) || String(it?._preview_url || '').trim();
            persistedImages.push(ensureComposerImageAttachmentMeta({ ...it, image_url:{ url: display || stable || String(it?.image_url?.url || '').trim() }, preview_url:String(it?.preview_url || display || '').trim(), view_url:String(it?.view_url || display || '').trim(), download_url:String(it?.download_url || it?.view_url || display || '').trim(), persisted_url:String(it?.persisted_url || stable || display || '').trim(), server_url:String(it?.server_url || display || stable || '').trim(), _preview_url:String(it?._preview_url || display || stable || '').trim(), _source_url:String(it?._source_url || stable || display || '').trim(), _composerId: composerId }, { sourceRole:'user', operation:String(it?.operation || (isComposerLibraryImageAttachment(it) ? 'library_reuse' : 'upload')).trim() || 'upload', endpointMode: normalizeApiEndpointMode(it?.endpoint_mode || it?.api_endpoint_mode || it?.apiEndpointMode || imageEndpointMode) }));
            continue;
          }
          const localId = "img_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
          const blob = await dataUrlToBlob(dataUrl);
          if(blob){
            await idbImgSet(localId, blob);
            localImgMap.set(localId, dataUrl);
          }
          const display = composerLibraryDisplayImageUrl(it) || composerLibraryBrowserImageSource(persistedUrl) || (blob ? ("local://" + localId) : dataUrl);
          persistedImages.push(ensureComposerImageAttachmentMeta({ type:"image_url", attachment_id: String(it?.attachment_id || '').trim(), image_id: String(it?.image_id || it?.attachment_id || '').trim(), storage_ref: String(it?.storage_ref || '').trim(), model_storage_ref: String(it?.model_storage_ref || it?.storage_ref || '').trim(), file_library_id: String(it?.file_library_id || it?.library_file_id || it?.file_registry?.file_id || '').trim(), library_file_id: String(it?.library_file_id || it?.file_library_id || it?.file_registry?.file_id || '').trim(), file_registry: it?.file_registry || null, image_url:{ url: display || persistedUrl || (blob ? ("local://" + localId) : dataUrl) }, preview_url:String(it?.preview_url || display || '').trim(), view_url:String(it?.view_url || display || '').trim(), download_url:String(it?.download_url || it?.view_url || display || '').trim(), persisted_url:persistedUrl || display, server_url:display || persistedUrl, filename: it?.filename || "", _preview_url: String(it?._preview_url || display || persistedUrl || dataUrl || '').trim(), _source_url: String(it?._source_url || persistedUrl || '').trim(), _ocr_text: String(it?._ocr_text || '').trim(), endpoint_mode: normalizeApiEndpointMode(it?.endpoint_mode || it?.api_endpoint_mode || it?.apiEndpointMode || imageEndpointMode), api_endpoint_mode: normalizeApiEndpointMode(it?.api_endpoint_mode || it?.endpoint_mode || it?.apiEndpointMode || imageEndpointMode), _composerId: composerId }, { sourceRole:'user', operation:String(it?.operation || (isComposerLibraryImageAttachment(it) ? 'library_reuse' : 'upload')).trim() || 'upload', endpointMode: normalizeApiEndpointMode(it?.endpoint_mode || it?.api_endpoint_mode || it?.apiEndpointMode || imageEndpointMode) }));
        }

      if(persistedImages.length){
        await updateSessionById(sessionId, s=>{
          let replaced = false;
          const targetSendId = String(outgoingSendId || '').trim();
          for(let i = (s.messages?.length || 0) - 1; i >= 0; i--){
            const msg = s.messages[i];
            if(!msg || msg.role !== "user" || !Array.isArray(msg.content)) continue;
            if(targetSendId && String(msg._client_send_id || '').trim() !== targetSendId) continue;
            const hasMatchingText = text
              ? msg.content.some(part => part && part.type === "text" && part.text === text)
              : true;
            const imageCount = msg.content.filter(part => part && part.type === "image_url").length;
            if(hasMatchingText && imageCount === pastedImagesSnapshot.length){
              const nextContent = [];
              if(text) nextContent.push({ type:"text", text });
              for(const img of persistedImages) nextContent.push(img);
              msg.content = nextContent;
              replaced = true;
              break;
            }
          }
          if(!replaced && !targetSendId){
            return;
          }
          if(!replaced){
            for(let i = (s.messages?.length || 0) - 1; i >= 0; i--){
              const msg = s.messages[i];
              if(!msg || msg.role !== "user" || !Array.isArray(msg.content)) continue;
              if(String(msg._client_send_id || '').trim() !== targetSendId) continue;
              const textParts = msg.content.filter(part => part && part.type === "text");
              const nextContent = [];
              if(textParts.length){
                for(const part of textParts) nextContent.push(part);
              }else if(text){
                nextContent.push({ type:"text", text });
              }
              for(const img of persistedImages) nextContent.push(img);
              msg.content = nextContent;
              break;
            }
          }
        }, { skipCompress: true });
      }
    }catch(_){ }
  }



  if(composerStillOwnsSendSession){
    clearPastedImages();
    clearComposerEditState();
  }

  const requestBody = await buildAsyncChatRequestBodyForSession(sessionId, { text, localImgMap, currentUserImageUploadsForSandbox: persistedImages, currentUserFileAttachments: outgoingUserFileAttachments });
  clearComposerAttachmentDraft(sessionId);
  const streamPromise = attachSessionToAsyncJob(sessionId, {
    requestBody,
    onConversationRunConflict: activeRun => rollbackOutgoingTurnForConversationConflict(
      sessionId,
      outgoingSendId,
      { text, files:pendingFilesSnapshot, images:pastedImagesSnapshot },
      activeRun,
    ),
  });
  return streamPromise;
  }finally{
    _sendStartLocks.delete(sessionId);
  }
}

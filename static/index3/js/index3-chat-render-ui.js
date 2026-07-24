/* Chat render/edit/branch UI.*/
function chatRenderT(key,params=null,fallback=''){
  return window.AperviaI18n?.t(key,params,fallback)||fallback||key;
}

/* 标题 */

function normalizeUserMessageInlineFileAttachment(raw){
  const row = raw && typeof raw === 'object' ? raw : null;
  if(!row) return null;
  const file = row._kind === 'file' ? { ...row } : buildOutgoingUserFileAttachmentMeta(row);
  if(!file) return null;
  file._kind = 'file';
  file.filename = String(file.filename || file.saved_filename || file.file_registry?.filename || file.file_registry?.saved_filename || '').trim() || '未命名文件';
  file.ext = String(file.ext || file.file_registry?.ext || '').trim();
  file.storage_ref = String(file.storage_ref || file.model_storage_ref || file.file_registry?.storage_ref || file.file_registry?.model_storage_ref || '').trim();
  file.model_storage_ref = String(file.model_storage_ref || file.storage_ref || file.file_registry?.model_storage_ref || file.file_registry?.storage_ref || '').trim();
  const fileViewFromStorage = uploadStorageRefToBrowserUrl(file.storage_ref || file.model_storage_ref, 'view');
  const fileDownloadFromStorage = uploadStorageRefToBrowserUrl(file.storage_ref || file.model_storage_ref, 'download');
  file.url = String(file.url || file.download_url || file.view_url || file.file_registry?.download_url || file.file_registry?.url || fileDownloadFromStorage || fileViewFromStorage || '').trim();
  file.view_url = String(file.view_url || file.url || file.file_registry?.view_url || file.file_registry?.url || fileViewFromStorage || '').trim();
  file.download_url = String(file.download_url || file.url || file.view_url || file.file_registry?.download_url || file.file_registry?.url || fileDownloadFromStorage || '').trim();
  return file;
}

function getUserMessageInlineFileAttachments(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').toLowerCase() !== 'user') return [];
  const sources = [];
  for(const key of ['file_attachments','attachments','_composer_file_attachments','files']){
    const value = m[key];
    if(Array.isArray(value)) sources.push(...value);
  }
  const content = m.content;
  if(content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'file') sources.push(content);
  const out = [];
  const seen = new Set();
  for(const item of sources){
    const file = normalizeUserMessageInlineFileAttachment(item);
    if(!file) continue;
    const key = [file.id, file.file_library_id, file.library_file_id, file.file_registry?.file_id, file.download_url, file.view_url, file.url, file.filename].map(x=>String(x||'').trim()).find(Boolean) || '';
    const dedupe = String(key || '').toLowerCase();
    if(dedupe && seen.has(dedupe)) continue;
    if(dedupe) seen.add(dedupe);
    out.push(file);
  }
  return out;
}

function renderUserMessageSeparateFileAttachments(msg, messageIndex=null){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').toLowerCase() !== 'user') return 0;
  const content = m.content;
  if(content && typeof content === 'object' && !Array.isArray(content) && (content._kind === 'file' || content._kind === 'image')) return 0;
  const files = getUserMessageInlineFileAttachments(m);
  if(!files.length) return 0;
  for(const file of files){
    addAttachmentBubble('user', file, false, { messageIndex, message:m });
  }
  return files.length;
}

function renderUserMessageAttachmentGroup(container, msg, imageParts=[], messageIndex=null){
  const target = container instanceof HTMLElement ? container : null;
  if(!target) return null;
  const images = Array.isArray(imageParts) ? imageParts.filter(Boolean) : [];
  const files = getUserMessageInlineFileAttachments(msg);
  if(!images.length && !files.length) return null;

  const group = document.createElement('div');
  group.className = 'user-sent-attachment-group';
  target.appendChild(group);

  // Keep image and file order stable inside their own sections; images always lead.
  if(images.length){
    const imageSection = document.createElement('div');
    imageSection.className = 'user-sent-attachment-images';
    group.appendChild(imageSection);
    Promise.resolve(renderStructuredMessageContent(imageSection, images)).then(rendered=>{
      if(!rendered) imageSection.remove();
      if(!group.childElementCount) group.remove();
    }).catch(()=>{
      imageSection.remove();
      if(!group.childElementCount) group.remove();
    });
  }
  if(files.length){
    const fileSection = document.createElement('div');
    fileSection.className = 'user-sent-attachment-files';
    group.appendChild(fileSection);
    for(const file of files){
      addAttachmentBubble('user', file, false, { messageIndex, message:msg, container:fileSection });
    }
  }
  return group;
}

function buildTitleContextForSession(s){
  const items = [];
  for(const m of s.messages){
    if(m.role === "system") continue;

    if(typeof m.content === "object" && m.content && m.content._kind === "file"){
      items.push(`${m.role}: [文件] ${m.content.filename}`);
    }else if(typeof m.content === "object" && m.content && m.content._kind === "image"){
      items.push(`${m.role}: [图片] ${m.content.filename}`);
    }else if(Array.isArray(m.content)){
      const textParts = m.content.filter(x => x?.type === "text" && x?.text).map(x=>x.text);
      if(textParts.length) items.push(`${m.role}: ${textParts.join(" ")}`);
      const imgCount = m.content.filter(x => x?.type === "image_url").length;
      if(imgCount) items.push(`${m.role}: [图片x${imgCount}]`);
    }else{
      const t = String(m.content || "").trim();
      if(t) items.push(`${m.role}: ${t}`);
    }

    if(items.length >= 6) break;
  }
  return items.join("\n").slice(0, 2500);
}


let visibleChatSessionId = null;
const liveDraftBubbleEls = Object.create(null);
const chatScrollMemory = Object.create(null);
let composerEditState = null;
let inlineMessageEditState = null;
let chatImageOrderSeq = 0;

function nextChatImageOrderSeq(){
  chatImageOrderSeq += 1;
  return chatImageOrderSeq;
}

function ensureComposerImageAttachmentMeta(imageItem, opts={}){
  const item = imageItem && typeof imageItem === "object" ? imageItem : null;
  if(!item) return item;
  const prefix = String(opts.prefix || 'img').trim() || 'img';
  if(!item.attachment_id){
    item.attachment_id = `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now().toString(16)}`;
  }
  const forcedCreatedAt = Number(opts.createdAtMs || opts.created_at_ms || 0) || 0;
  const existingCreatedAt = Number(item.created_at_ms || item.createdAtMs || item._created_at_ms || item.created_at || item.createdAt || 0) || 0;
  const createdAtMs = (opts.forceCreatedAt && forcedCreatedAt) ? forcedCreatedAt : (existingCreatedAt || forcedCreatedAt || Date.now());
  item.created_at_ms = createdAtMs;
  item.createdAtMs = createdAtMs;
  item._created_at_ms = createdAtMs;
  const seq = Number(opts.imageSeq || opts.image_seq || item.image_seq || item.seq || 0) || nextChatImageOrderSeq();
  item.image_seq = seq;
  item.seq = seq;
  if(opts.sourceRole || opts.source_role){
    item.source_role = String(opts.sourceRole || opts.source_role || '').trim();
  }else if(!item.source_role){
    item.source_role = 'user';
  }
  if(opts.operation){
    item.operation = String(opts.operation || '').trim();
  }else if(!item.operation){
    item.operation = item.source_role === 'assistant' ? 'generate' : 'upload';
  }
  const endpointModeRaw = opts.endpointMode || opts.endpoint_mode || opts.apiEndpointMode || opts.api_endpoint_mode || item.endpoint_mode || item.api_endpoint_mode || item.apiEndpointMode || '';
  const endpointMode = endpointModeRaw ? normalizeApiEndpointMode(endpointModeRaw) : '';
  if(endpointMode){
    item.endpoint_mode = endpointMode;
    item.api_endpoint_mode = endpointMode;
    item.apiEndpointMode = endpointMode;
  }
  if(!item.image_id){
    item.image_id = String(item.attachment_id || `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now().toString(16)}`).trim();
  }
  if(!item.model_storage_ref && item.storage_ref) item.model_storage_ref = item.storage_ref;
  if(!item.storage_ref && item.model_storage_ref) item.storage_ref = item.model_storage_ref;
  return item;
}

function imageItemHasStableModelSource(imageItem){
  const item = imageItem || {};
  const reg = item?.file_registry && typeof item.file_registry === 'object' ? item.file_registry : {};
  return !!(
    String(item?.model_storage_ref || '').trim()
    || String(item?.storage_ref || '').trim()
    || String(item?.file_library_id || item?.library_file_id || reg.file_id || '').trim()
    || String(item?.persisted_url || item?.server_url || '').trim()
    || String(item?.image_url?.url || '').trim()
    || String(item?._preview_url || '').trim()
    || String(item?.url || item?.view_url || item?.download_url || item?._source_url || '').trim()
    || String(reg.preview_url || reg.view_url || reg.download_url || reg.url || '').trim()
    || composerLibraryDurableImageUrl(item)
  );
}

function bubbleMessageImagePartsForComposer(msg){
  if(!msg || !Array.isArray(msg.content)) return [];
  return msg.content.filter(part => part && part.type === "image_url" && imageItemHasStableModelSource(part));
}

function bubbleMessageImageCountForComposer(msg){
  return bubbleMessageImagePartsForComposer(msg).length;
}

function messageHasEditableComposerContent(msg){
  return !!bubbleMessageTextForComposer(msg) || bubbleMessageImageCountForComposer(msg) > 0 || getUserMessageInlineFileAttachments(msg).length > 0;
}

function cloneComposerImageItem(imageItem){
  let cloned;
  try{ cloned = JSON.parse(JSON.stringify(imageItem || {})); }catch(_){ cloned = { ...(imageItem || {}) }; }
  if(!cloned || typeof cloned !== "object") cloned = {};
  cloned.type = "image_url";
  if(!cloned.image_url || typeof cloned.image_url !== "object") cloned.image_url = { url:"" };
  ensureComposerImageAttachmentMeta(cloned);
  const preferredUrl = String(cloned?._preview_url || cloned?.image_url?.url || cloned?.persisted_url || cloned?.server_url || "").trim();
  if(preferredUrl && !cloned.image_url.url) cloned.image_url.url = preferredUrl;
  if(preferredUrl && !cloned._preview_url) cloned._preview_url = preferredUrl;
  if(!cloned._composerId) cloned._composerId = "cmpimg_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
  return cloned;
}

function hydrateComposerAttachmentsFromMessage(msg){
  for(const part of bubbleMessageImagePartsForComposer(msg)){
    const cloned = cloneComposerImageItem(part);
    pastedImages.push(cloned);
    addImageThumb(cloned);
  }
}

function getMessageDisplaySnippet(msg){
  const txt = bubbleMessageTextForComposer(msg || {});
  if(txt) return txt.replace(/\s+/g, " ").trim().slice(0, 120);
  const imageCount = bubbleMessageImageCountForComposer(msg);
  if(imageCount>0) return chatRenderT('chat.attachment_summary_images',{count:imageCount},`${imageCount} images`);
  const fileCount = getUserMessageInlineFileAttachments(msg).length;
  if(fileCount>0) return chatRenderT('chat.attachment_summary_files',{count:fileCount},`${fileCount} files`);
  return "";
}

function refreshComposerEditBar(){
  if(!composerEditBarEl || !composerEditTitleEl || !composerEditDescEl) return;
  if(!composerEditState){
    composerEditBarEl.classList.remove("show");
    composerEditTitleEl.textContent = "";
    composerEditDescEl.textContent = "";
    return;
  }
  const mode=chatRenderT(composerEditState.mode==='regenerate'?'chat.edit.regenerate_title':'chat.edit.rewrite_title',null,composerEditState.mode==='regenerate'?'Regenerate response':'Edit and rewrite following messages');
  const snippet = String(composerEditState.preview || "").trim();
  composerEditTitleEl.textContent = mode;
  composerEditDescEl.textContent=snippet||chatRenderT('chat.edit.rewrite_desc',null,'After sending, later responses will be rewritten from here.');
  composerEditBarEl.classList.add("show");
}

function clearComposerEditState(){
  composerEditState = null;
  refreshComposerEditBar();
}

function setComposerEditState(next){
  if(next) clearComposerQuoteState({ silent:true });
  composerEditState = next ? { ...next } : null;
  refreshComposerEditBar();
}

function findPrevUserMessageIndex(messages, fromIndex){
  const msgs = Array.isArray(messages) ? messages : [];
  for(let i = Math.min((fromIndex ?? msgs.length) - 1, msgs.length - 1); i >= 0; i--){
    const m = msgs[i];
    if(m && m.role === "user") return i;
  }
  return -1;
}

function buildEditedUserContent(originalContent, nextText, removedAttachmentKeys=null){
  const text = String(nextText || "");
  const removed = removedAttachmentKeys instanceof Set ? removedAttachmentKeys : new Set();
  if(Array.isArray(originalContent)){
    const kept = originalContent.filter(part => {
      if(!(part && part.type === "text")){
        return !inlineEditAttachmentMatchesRemovedKeys(removed, part);
      }
      return false;
    });
    return text ? [{ type:"text", text }, ...kept] : kept;
  }
  if(originalContent && typeof originalContent === "object" && !Array.isArray(originalContent)){
    if(inlineEditAttachmentMatchesRemovedKeys(removed, originalContent)){
      return text;
    }
  }
  return text;
}

function cloneMessageForEdit(value){
  try{ return JSON.parse(JSON.stringify(value || {})); }catch(_){ return { ...(value || {}) }; }
}


// GPT/OpenWebUI-like lightweight branch layer.
// The flat s.messages array remains the runtime/source-of-truth for backend calls.
// Branch metadata only records replaceable tails so edit/regenerate can switch versions
// without appending old answers to the end or swallowing normal assistant replies.
function webaiBranchNewGroupId(sessionId=''){
  const sid = String(sessionId || store?.activeId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 40);
  return ['br', sid, Date.now().toString(36), Math.random().toString(16).slice(2, 10)].filter(Boolean).join('_');
}
function webaiBranchCloneMessages(messages){
  try{ return JSON.parse(JSON.stringify(Array.isArray(messages) ? messages : [])); }
  catch(_){ return (Array.isArray(messages) ? messages : []).map(m => ({ ...(m || {}) })); }
}
function webaiBranchStore(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return null;
  if(!s._webaiConversationBranches || typeof s._webaiConversationBranches !== 'object'){
    s._webaiConversationBranches = { version:1, groups:{} };
  }
  if(!s._webaiConversationBranches.groups || typeof s._webaiConversationBranches.groups !== 'object'){
    s._webaiConversationBranches.groups = {};
  }
  return s._webaiConversationBranches;
}
function webaiBranchGroup(session, groupId){
  const storeObj = webaiBranchStore(session);
  const gid = String(groupId || '').trim();
  if(!storeObj || !gid) return null;
  return storeObj.groups[gid] || null;
}
function webaiBranchVisibleGroup(session, message){
  const gid = String(message?._webai_conv_branch_id || '').trim();
  if(!gid) return null;
  return webaiBranchGroup(session, gid);
}
function webaiBranchStoredStartIndex(session, groupId){
  const gid = String(groupId || '').trim();
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  if(!gid) return -1;
  try{
    const group = webaiBranchGroup(session, gid);
    const idx = Number(group?.startIndex);
    if(Number.isInteger(idx) && idx >= 0 && idx <= rows.length) return idx;
  }catch(_){ }
  return -1;
}
function webaiBranchAdjustAssistantRegenerateStartIndex(session, group, startIndex){
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  const branchKind = String(group?.kind || '').trim();
  let idx = Number(startIndex);
  if(branchKind !== 'assistant_regen' || !Number.isInteger(idx) || idx <= 0) return startIndex;
  idx = Math.min(idx, rows.length);
  const current = rows[idx];
  const prev = rows[idx - 1];
  if(!prev || String(prev.role || '').trim().toLowerCase() !== 'assistant') return startIndex;
  if(current && String(current.role || '').trim().toLowerCase() !== 'assistant') return startIndex;
  let first = idx;
  while(first > 0){
    const before = rows[first - 1];
    if(!before || String(before.role || '').trim().toLowerCase() !== 'assistant') break;
    first -= 1;
  }
  return first;
}
function webaiBranchFindStartIndex(session, groupId){
  const gid = String(groupId || '').trim();
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  if(!gid) return -1;
  const group = webaiBranchGroup(session, gid);
  for(let i = 0; i < rows.length; i++){
    const m = rows[i];
    if(m && String(m._webai_conv_branch_id || '').trim() === gid && m._webai_conv_branch_anchor === true) return webaiBranchAdjustAssistantRegenerateStartIndex(session, group, i);
  }
  const storedStart = webaiBranchStoredStartIndex(session, gid);
  const preferStoredStart = String(group?.kind || '').trim() === 'assistant_regen';
  if(preferStoredStart && Number.isInteger(storedStart) && storedStart >= 0) return webaiBranchAdjustAssistantRegenerateStartIndex(session, group, storedStart);
  for(let i = 0; i < rows.length; i++){
    const m = rows[i];
    if(m && String(m._webai_conv_branch_id || '').trim() === gid) return webaiBranchAdjustAssistantRegenerateStartIndex(session, group, i);
  }
  if(Number.isInteger(storedStart) && storedStart >= 0) return webaiBranchAdjustAssistantRegenerateStartIndex(session, group, storedStart);
  return -1;
}
function webaiBranchControlRoleForKind(kind){
  return String(kind || '') === 'assistant_regen' ? 'assistant' : 'user';
}
function webaiBranchClearGroupMetaOnMessage(msg, groupId){
  if(!msg || typeof msg !== 'object') return false;
  const gid = String(groupId || '').trim();
  if(!gid || String(msg._webai_conv_branch_id || '').trim() !== gid) return false;
  delete msg._webai_conv_branch_id;
  delete msg._webai_conv_branch_version;
  delete msg._webai_conv_branch_kind;
  delete msg._webai_conv_branch_anchor;
  delete msg._webai_conv_branch_control;
  return true;
}
function webaiBranchSetGroupMetaOnMessage(msg, groupId, versionIndex, kind, flags={}){
  if(!msg || typeof msg !== 'object') return false;
  const gid = String(groupId || '').trim();
  if(!gid) return false;
  msg._webai_conv_branch_id = gid;
  msg._webai_conv_branch_version = Math.max(0, Number(versionIndex || 0) || 0);
  msg._webai_conv_branch_kind = String(kind || 'user_edit').trim() || 'user_edit';
  if(flags.anchor) msg._webai_conv_branch_anchor = true;
  else delete msg._webai_conv_branch_anchor;
  if(flags.control) msg._webai_conv_branch_control = true;
  else delete msg._webai_conv_branch_control;
  return true;
}
function webaiBranchDecorateTail(messages, groupId, versionIndex, kind, opts={}){
  const rows = Array.isArray(messages) ? messages : [];
  const gid = String(groupId || '').trim();
  const idx = Math.max(0, Number(versionIndex || 0) || 0);
  const branchKind = String(kind || 'user_edit').trim() || 'user_edit';
  const controlRole = String(opts.controlRole || webaiBranchControlRoleForKind(branchKind)).trim();
  if(!gid) return rows;

  // Do not stamp the whole tail with one branch id.  Later edits/regenerations can
  // live inside an already edited branch; if every descendant message inherits the
  // ancestor id, a new control click is later normalized back to the first branch.
  // Keep branch metadata only on this group's own anchor/control message and
  // preserve nested child-group controls inside the tail.
  for(const msg of rows){
    if(!msg || typeof msg !== 'object') continue;
    webaiBranchClearGroupMetaOnMessage(msg, gid);
  }

  let anchorIndex = -1;
  for(let i = 0; i < rows.length; i++){
    const msg = rows[i];
    if(!msg || typeof msg !== 'object' || String(msg.role || '').toLowerCase() === 'system') continue;
    anchorIndex = i;
    break;
  }
  if(anchorIndex < 0) return rows;

  let controlIndex = -1;
  for(let i = anchorIndex; i < rows.length; i++){
    const msg = rows[i];
    if(!msg || typeof msg !== 'object') continue;
    if(String(msg.role || '').toLowerCase() === controlRole){
      controlIndex = i;
      break;
    }
  }
  if(controlIndex < 0) controlIndex = anchorIndex;
  if(anchorIndex === controlIndex){
    webaiBranchSetGroupMetaOnMessage(rows[anchorIndex], gid, idx, branchKind, { anchor:true, control:true });
  }else{
    webaiBranchSetGroupMetaOnMessage(rows[anchorIndex], gid, idx, branchKind, { anchor:true, control:false });
    webaiBranchSetGroupMetaOnMessage(rows[controlIndex], gid, idx, branchKind, { anchor:false, control:true });
  }
  return rows;
}
function webaiBranchStripVolatileMeta(messages){
  const rows = webaiBranchCloneMessages(messages);
  for(const msg of rows){
    if(!msg || typeof msg !== 'object') continue;
    delete msg._webai_conv_branch_id;
    delete msg._webai_conv_branch_version;
    delete msg._webai_conv_branch_kind;
    delete msg._webai_conv_branch_anchor;
    delete msg._webai_conv_branch_control;
  }
  return rows;
}

// OpenWebUI/GPT-like active-path shadow history.
// `session.messages` stays the runtime active path for the existing backend, while
// this tree records that the active view is authoritative after edit/regenerate.
// It prevents stale flat snapshots from being treated as the source of truth.
function webaiOfficialMsgId(sessionId='', index=0){
  const sid = String(sessionId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 40) || 's';
  return ['owmsg', sid, Date.now().toString(36), index, Math.random().toString(16).slice(2, 8)].join('_');
}
function webaiOfficialActivePathFromMessages(session){
  const s = session && typeof session === 'object' ? session : null;
  const rows = Array.isArray(s?.messages) ? s.messages : [];
  const messages = {};
  let parentId = null;
  let currentId = '';
  rows.forEach((raw, index)=>{
    if(!raw || typeof raw !== 'object') return;
    const msg = webaiBranchCloneMessages([raw])[0] || {};
    const id = String(msg._webai_history_id || msg.id || '').trim() || webaiOfficialMsgId(s?.id || '', index);
    msg._webai_history_id = id;
    msg.id = String(msg.id || id);
    msg.parentId = parentId;
    msg.childrenIds = [];
    messages[id] = msg;
    if(parentId && messages[parentId]){
      const arr = Array.isArray(messages[parentId].childrenIds) ? messages[parentId].childrenIds : [];
      if(!arr.includes(id)) arr.push(id);
      messages[parentId].childrenIds = arr;
    }
    parentId = id;
    currentId = id;
  });
  return { currentId, messages };
}
function webaiOfficialPersistActivePath(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s || !Array.isArray(s.messages)) return false;
  const active = webaiOfficialActivePathFromMessages(s);
  s.history = { ...(s.history && typeof s.history === 'object' ? s.history : {}), currentId: active.currentId, messages: active.messages };
  s._webaiHistoryCurrentId = active.currentId;
  return true;
}
function webaiOfficialNormalizeActiveSession(session, opts={}){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  let changed = false;
  try{ if(webaiBranchNormalizeActiveViewInSession(s, { skipIfLive: opts.skipIfLive !== false })) changed = true; }catch(_){ }
  try{ if(webaiBranchNormalizeVisibleAssistantRunsInSession(s)) changed = true; }catch(_){ }
  try{ webaiOfficialPersistActivePath(s); }catch(_){ }
  return changed;
}
function webaiOfficialPrepareOrdinarySend(session, sessionId=''){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  let changed = false;
  try{ if(webaiBranchCommitActiveVersion(s, null)) changed = true; }catch(_){ }
  try{ if(webaiBranchNormalizeActiveViewInSession(s, { skipIfLive:false })) changed = true; }catch(_){ }
  try{ if(webaiBranchNormalizeVisibleAssistantRunsInSession(s)) changed = true; }catch(_){ }
  try{ delete s._webaiPendingConversationBranch; }catch(_){ }
  try{
    const rt = ensureSessionRuntime(String(sessionId || s.id || '').trim());
    if(rt && Object.prototype.hasOwnProperty.call(rt, 'pendingBranchSave')) delete rt.pendingBranchSave;
  }catch(_){ }
  try{ webaiOfficialPersistActivePath(s); }catch(_){ }
  return changed;
}
function webaiOfficialCleanupStaleRuntimeBeforeSend(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  let changed = false;
  try{
    const rt = ensureSessionRuntime(sid);
    const hasPromise = !!getSessionPromise(sid);
    const hasJob = !!getSessionPendingJobId(sid);
    const lastIsAssistant = sessionLastVisibleMessageIsAssistant(sid);
    if(!hasPromise && (rt?.streaming || hasJob) && lastIsAssistant){
      resetSessionTerminalRuntimeState(sid, { finalizeTimer:true, preserveReasoning:true });
      changed = true;
    }
  }catch(_){ }
  return changed;
}


function webaiBranchSessionHasState(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  if(s._webaiConversationBranches && typeof s._webaiConversationBranches === 'object') return true;
  if(String(s._webaiActiveConversationBranchId || '').trim()) return true;
  const rows = Array.isArray(s.messages) ? s.messages : [];
  return rows.some(m => m && typeof m === 'object' && String(m._webai_conv_branch_id || '').trim());
}

function webaiBranchVisibleGroupIds(session){
  const s = session && typeof session === 'object' ? session : null;
  const out = [];
  const seen = new Set();
  const rows = Array.isArray(s?.messages) ? s.messages : [];
  for(const msg of rows){
    const gid = String(msg?._webai_conv_branch_id || '').trim();
    if(!gid || seen.has(gid)) continue;
    if(msg?._webai_conv_branch_anchor === true || msg?._webai_conv_branch_control === true){
      seen.add(gid);
      out.push(gid);
    }
  }
  return out;
}
function webaiBranchPruneTailWideMessageMeta(session){
  const s = session && typeof session === 'object' ? session : null;
  const rows = Array.isArray(s?.messages) ? s.messages : [];
  let changed = false;
  for(const msg of rows){
    if(!msg || typeof msg !== 'object') continue;
    const gid = String(msg._webai_conv_branch_id || '').trim();
    if(!gid) continue;
    if(msg._webai_conv_branch_anchor === true || msg._webai_conv_branch_control === true) continue;
    webaiBranchClearGroupMetaOnMessage(msg, gid);
    changed = true;
  }
  return changed;
}
function webaiBranchPersistVisibleGroupVersions(session, opts={}){
  const s = session && typeof session === 'object' ? session : null;
  const storeObj = s?._webaiConversationBranches && typeof s._webaiConversationBranches === 'object' ? s._webaiConversationBranches : null;
  const groups = storeObj?.groups && typeof storeObj.groups === 'object' ? storeObj.groups : null;
  if(!s || !Array.isArray(s.messages) || !groups) return false;
  webaiBranchPruneTailWideMessageMeta(s);
  const ids = webaiBranchVisibleGroupIds(s);
  if(!ids.length) return false;
  const entries = [];
  for(const gid of ids){
    const group = groups[gid];
    if(!group || typeof group !== 'object') continue;
    const startIndex = webaiBranchFindStartIndex(s, gid);
    if(!Number.isInteger(startIndex) || startIndex < 0) continue;
    entries.push({ gid, group, startIndex });
  }
  entries.sort((a,b)=> a.startIndex - b.startIndex);
  let changed = false;
  const stamp = Date.now();
  for(const item of entries){
    const group = item.group;
    const active = Math.max(0, Number(group.active || 0) || 0);
    if(!Array.isArray(group.versions)) group.versions = [];
    if(!group.versions[active]) group.versions[active] = { id:`${item.gid}_v${active}`, createdAt:stamp, messages:[] };
    const kind = String(group.kind || group.versions[active]?.kind || 'user_edit').trim() || 'user_edit';
    const tail = webaiBranchDecorateTail(webaiBranchCloneMessages(s.messages.slice(item.startIndex)), item.gid, active, kind, { controlRole:webaiBranchControlRoleForKind(kind) });
    group.startIndex = item.startIndex;
    group.versions[active].messages = tail;
    group.versions[active].updatedAt = stamp;
    group.active = active;
    group.kind = kind;
    group.updatedAt = stamp;
    changed = true;
  }
  return changed;
}

function webaiBranchMaxUpdatedAt(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return 0;
  const sessionStamp = Math.max(0, Number(s.updatedAt || s.updated_at || s.createdAt || s.created_at || 0) || 0);
  let best = 0;
  const storeObj = s._webaiConversationBranches && typeof s._webaiConversationBranches === 'object' ? s._webaiConversationBranches : null;
  const groups = storeObj && storeObj.groups && typeof storeObj.groups === 'object' ? storeObj.groups : null;
  for(const group of Object.values(groups || {})){
    if(!group || typeof group !== 'object') continue;
    best = Math.max(best, Number(group.updatedAt || group.createdAt || 0) || 0);
    for(const version of (Array.isArray(group.versions) ? group.versions : [])){
      if(!version || typeof version !== 'object') continue;
      best = Math.max(best, Number(version.updatedAt || version.createdAt || 0) || 0);
    }
  }
  return best || sessionStamp;
}

function cloudSyncCloneLocalBranchAuthoritativeSession(localSession, remoteSession, sid){
  const sessionId = String(sid || localSession?.id || remoteSession?.id || '').trim();
  const local = cloneStoreDeep(localSession) || JSON.parse(JSON.stringify(localSession || {}));
  local.id = String(local.id || sessionId).trim() || sessionId;
  try{ webaiBranchNormalizeActiveViewInSession(local, { skipIfLive:false }); }catch(_){ }
  try{ webaiBranchNormalizeVisibleAssistantRunsInSession(local); }catch(_){ }
  try{ preserveSessionReadStateFromSource(local, remoteSession); }catch(_){ }
  try{ normalizeSessionUnreadStateAfterMerge(local); }catch(_){ }
  local._cloudStub = false;
  local._cloudNeedsHydrate = false;
  local._cloudHydrated = true;
  return local;
}

function cloudSyncShouldKeepLocalBranchSession(localSession, remoteSession, sid, opts={}){
  const local = localSession && typeof localSession === 'object' ? localSession : null;
  if(!local || !webaiBranchSessionHasState(local)) return false;
  const sessionId = String(sid || local.id || '').trim();
  const preserveActiveId = String(opts?.preserveActiveId || store?.activeId || '').trim();
  if(sessionHasPendingAssistantSnapshot(local)) return true;
  if(String(local.pendingJobId || '').trim()) return true;
  try{ if(sessionId && sessionHasLiveLocalRuntimeForCloud(sessionId, { sessions:{ [sessionId]:local }, activeId:preserveActiveId || sessionId })) return true; }catch(_){ }
  const remote = remoteSession && typeof remoteSession === 'object' ? remoteSession : null;
  if(!remote || isCloudSessionStub(remote)) return true;
  const localBranchStamp = webaiBranchMaxUpdatedAt(local);
  const remoteBranchStamp = webaiBranchMaxUpdatedAt(remote);
  const localVisible = (Array.isArray(local.messages) ? local.messages : []).filter(msg => msg && String(msg.role || '').toLowerCase() !== 'system').length;
  const remoteVisible = (Array.isArray(remote.messages) ? remote.messages : []).filter(msg => msg && String(msg.role || '').toLowerCase() !== 'system').length;
  if(localVisible < remoteVisible) return false;
  if(localBranchStamp > remoteBranchStamp + 250) return true;
  return false;
}

function webaiBranchNormalizeActiveViewInSession(session, opts={}){
  const s = session && typeof session === 'object' ? session : null;
  if(!s || !webaiBranchSessionHasState(s)) return false;
  try{ webaiBranchPruneTailWideMessageMeta(s); }catch(_){ }
  const o = opts && typeof opts === 'object' ? opts : {};
  if(o.skipIfLive !== false){
    try{
      if(String(s.pendingJobId || '').trim()) return false;
      if(typeof sessionHasPendingAssistantSnapshot === 'function' && sessionHasPendingAssistantSnapshot(s)) return false;
    }catch(_){ }
  }
  const storeObj = s._webaiConversationBranches && typeof s._webaiConversationBranches === 'object' ? s._webaiConversationBranches : null;
  const groups = storeObj && storeObj.groups && typeof storeObj.groups === 'object' ? storeObj.groups : null;
  let gid = String(s._webaiActiveConversationBranchId || '').trim();
  if(!gid && groups){
    const candidates = Object.values(groups).filter(g => g && typeof g === 'object');
    candidates.sort((a,b)=> Number(b.updatedAt || b.createdAt || 0) - Number(a.updatedAt || a.createdAt || 0));
    gid = String(candidates[0]?.id || '').trim();
  }
  if(!gid || !groups || !groups[gid]) return false;
  const group = groups[gid];
  if(!Array.isArray(group.versions) || !group.versions.length) return false;
  const active = Math.max(0, Math.min(group.versions.length - 1, Number(group.active || 0) || 0));
  const version = group.versions[active];
  const versionTail = Array.isArray(version?.messages) ? version.messages : [];
  if(!versionTail.length) return false;
  let startIndex = webaiBranchFindStartIndex(s, gid);
  if(!Number.isInteger(startIndex) || startIndex < 0){
    const savedStart = Number(group.startIndex);
    if(Number.isInteger(savedStart) && savedStart >= 0) startIndex = Math.min(savedStart, Array.isArray(s.messages) ? s.messages.length : savedStart);
  }
  if(!Number.isInteger(startIndex) || startIndex < 0) return false;
  const kind = String(group.kind || version.kind || 'user_edit').trim() || 'user_edit';
  const activeTail = kind === 'assistant_regen'
    ? webaiBranchNormalizeAssistantRegenerateTail(versionTail, gid, active)
    : webaiBranchCloneMessages(versionTail);
  const decoratedTail = webaiBranchDecorateTail(activeTail, gid, active, kind, { controlRole:webaiBranchControlRoleForKind(kind) });
  const prefix = Array.isArray(s.messages) ? s.messages.slice(0, startIndex) : [];
  s.messages = prefix.concat(webaiBranchCloneMessages(decoratedTail));
  try{ webaiBranchPruneTailWideMessageMeta(s); }catch(_){ }
  group.active = active;
  group.kind = kind;
  group.startIndex = startIndex;
  group.updatedAt = Number(group.updatedAt || Date.now()) || Date.now();
  group.versions[active].messages = webaiBranchCloneMessages(decoratedTail);
  group.versions[active].updatedAt = Number(group.versions[active].updatedAt || group.updatedAt || Date.now()) || Date.now();
  s._webaiActiveConversationBranchId = gid;
  delete s._webaiPendingConversationBranch;
  try{ webaiBranchPersistVisibleGroupVersions(s, { reason:'normalize' }); }catch(_){ }
  return true;
}

function webaiBranchNormalizeActiveViewsInStore(storeObj, opts={}){
  const root = storeObj && typeof storeObj === 'object' ? storeObj : null;
  if(!root || !root.sessions || typeof root.sessions !== 'object') return false;
  let changed = false;
  for(const session of Object.values(root.sessions || {})){
    try{ if(webaiBranchNormalizeActiveViewInSession(session, opts)) changed = true; }catch(_){ }
  }
  return changed;
}

function webaiBranchAssistantMessageIsSquashable(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m || String(m.role || '').trim().toLowerCase() !== 'assistant') return false;
  const content = m.content;
  if(content && typeof content === 'object' && !Array.isArray(content)){
    const kind = String(content._kind || '').trim();
    if(kind === 'memory_event' || kind === 'weather' || kind === 'genfiles' || kind === 'image_reply' || kind === 'file' || kind === 'image') return false;
  }
  return true;
}

function webaiBranchSquashConsecutiveAssistantRuns(messages){
  const rows = webaiBranchCloneMessages(messages);
  const out = [];
  let lastVisibleAssistantOutIndex = -1;
  let lastVisibleWasSquashableAssistant = false;
  for(const msg of rows){
    if(!msg || typeof msg !== 'object') continue;
    const role = String(msg.role || '').trim().toLowerCase();
    if(role === 'system'){
      out.push(msg);
      continue;
    }
    const squashableAssistant = webaiBranchAssistantMessageIsSquashable(msg);
    if(squashableAssistant && lastVisibleWasSquashableAssistant && lastVisibleAssistantOutIndex >= 0){
      // GPT/OpenWebUI style: regenerated assistant siblings must not both appear in
      // the active flat view. Keep the newest visible text assistant in this run;
      // structured assistant cards such as memory/tool cards are independent UI.
      out[lastVisibleAssistantOutIndex] = msg;
      continue;
    }
    out.push(msg);
    lastVisibleWasSquashableAssistant = squashableAssistant;
    lastVisibleAssistantOutIndex = squashableAssistant ? out.length - 1 : -1;
  }
  return out;
}
function webaiBranchNormalizeAssistantRegenerateTail(messages, groupId, versionIndex){
  const rows = webaiBranchCloneMessages(messages);
  const gid = String(groupId || '').trim();
  const active = Math.max(0, Number(versionIndex || 0) || 0);
  let firstVisible = -1;
  for(let i = 0; i < rows.length; i += 1){
    if(String(rows[i]?.role || '').trim().toLowerCase() === 'system') continue;
    firstVisible = i;
    break;
  }
  if(firstVisible < 0 || String(rows[firstVisible]?.role || '').trim().toLowerCase() !== 'assistant') return rows;
  let runEnd = firstVisible;
  while(runEnd < rows.length){
    const role = String(rows[runEnd]?.role || '').trim().toLowerCase();
    if(role !== 'assistant' && role !== 'system') break;
    runEnd += 1;
  }
  let markerIndex = -1;
  let lastAssistantIndex = -1;
  for(let i = firstVisible; i < runEnd; i += 1){
    const msg = rows[i];
    if(!msg || String(msg.role || '').trim().toLowerCase() !== 'assistant') continue;
    lastAssistantIndex = i;
    const msgGroup = String(msg._webai_conv_branch_id || '').trim();
    const msgVersion = Math.max(0, Number(msg._webai_conv_branch_version || 0) || 0);
    if(gid && msgGroup === gid && msgVersion === active){
      markerIndex = i;
      break;
    }
  }
  const keepFrom = markerIndex >= 0 ? markerIndex : (lastAssistantIndex > firstVisible ? lastAssistantIndex : -1);
  if(keepFrom <= firstVisible) return rows;
  return rows.slice(0, firstVisible).concat(rows.slice(keepFrom));
}

function webaiMessageCreatedAtMs(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return 0;
  const candidates = [m.created_at_ms, m.createdAtMs, m.created_at, m.createdAt, m.timestamp, m.ts];
  for(const value of candidates){
    const n = Number(value || 0) || 0;
    if(n > 0) return n;
  }
  return 0;
}
function webaiAssistantImageReplyShouldFollowUser(assistantMsg, userMsg){
  const a = assistantMsg && typeof assistantMsg === 'object' ? assistantMsg : null;
  const u = userMsg && typeof userMsg === 'object' ? userMsg : null;
  if(!a || !u) return false;
  if(String(a.role || '').trim().toLowerCase() !== 'assistant') return false;
  if(String(u.role || '').trim().toLowerCase() !== 'user') return false;
  if(!isGeneratedImageReplyMessage(a)) return false;
  const aTs = webaiMessageCreatedAtMs(a);
  const uTs = webaiMessageCreatedAtMs(u);
  if(!aTs || !uTs) return false;
  // Generated-image replies belong after the user turn that triggered them.
  // If a stale branch/sync snapshot places an assistant image before a user
  // message while its assistant timestamp is not older than that user turn,
  // render/save it after the user instead of letting the image jump above the
  // prompt. Older assistant images followed by a later user follow-up are left
  // untouched.
  return aTs >= uTs;
}
function webaiNormalizeAssistantImageReplyTurnOrder(messages){
  const rows = Array.isArray(messages) ? messages.slice() : [];
  let changed = false;
  for(let i = 0; i < rows.length - 1; i += 1){
    if(webaiAssistantImageReplyShouldFollowUser(rows[i], rows[i + 1])){
      const assistantMsg = rows[i];
      rows[i] = rows[i + 1];
      rows[i + 1] = assistantMsg;
      changed = true;
    }
  }
  return changed ? rows : messages;
}

function webaiBranchNormalizeVisibleAssistantRunsInSession(session){
  const s = session && typeof session === 'object' ? session : null;
  if(!s || !Array.isArray(s.messages) || s.messages.length < 2) return false;
  let changed = false;
  const before = s.messages.length;
  let normalized = webaiBranchSquashConsecutiveAssistantRuns(s.messages);
  if(normalized.length !== before) changed = true;
  const orderNormalized = webaiNormalizeAssistantImageReplyTurnOrder(normalized);
  if(orderNormalized !== normalized){
    normalized = orderNormalized;
    changed = true;
  }
  if(!changed) return false;
  s.messages = normalized;
  try{ s.updatedAt = s.updatedAt || now(); }catch(_){ }
  return true;
}

function webaiBranchTailBeforeAssistantSave(messages){
  const rows = webaiBranchCloneMessages(messages);
  return rows.filter(msg => String(msg?.role || '').toLowerCase() !== 'assistant');
}
function webaiBranchPreparePendingTailForSave(session, ctx){
  const s = session && typeof session === 'object' ? session : null;
  const data = ctx && typeof ctx === 'object' ? ctx : null;
  if(!s || !data || !data.groupId) return false;
  const gid = String(data.groupId || '').trim();
  if(!gid) return false;
  const group = webaiBranchGroup(s, gid);
  if(!group || !Array.isArray(group.versions)) return false;
  const versionIndex = Math.max(0, Number(data.versionIndex ?? group.active ?? 0) || 0);
  const version = group.versions[versionIndex];
  if(!version) return false;
  let startIndex = Number(data.startIndex);
  if(!Number.isInteger(startIndex) || startIndex < 0) startIndex = webaiBranchFindStartIndex(s, gid);
  if(!Number.isInteger(startIndex) || startIndex < 0) return false;
  const rows = Array.isArray(s.messages) ? s.messages : [];
  const kind = String(group.kind || data.kind || 'user_edit').trim() || 'user_edit';
  const baseTail = webaiBranchTailBeforeAssistantSave(version.messages || []);
  const decorated = webaiBranchDecorateTail(baseTail, gid, versionIndex, kind, { controlRole:webaiBranchControlRoleForKind(kind) });
  s.messages = rows.slice(0, startIndex).concat(decorated);
  group.versions[versionIndex].messages = webaiBranchCloneMessages(decorated);
  group.versions[versionIndex].updatedAt = Date.now();
  group.startIndex = startIndex;
  group.active = versionIndex;
  group.updatedAt = Date.now();
  s._webaiActiveConversationBranchId = gid;
  s._webaiPendingConversationBranch = { ...data, groupId:gid, versionIndex, startIndex, kind };
  try{ webaiBranchPersistVisibleGroupVersions(s, { reason:'prepare_pending' }); }catch(_){ }
  return true;
}
function webaiBranchEnsureGroupForReplacement(session, startIndex, kind){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return null;
  const rows = Array.isArray(s.messages) ? s.messages : [];
  const requestedStart = Math.max(0, Number(startIndex || 0) || 0);
  const currentAtStart = rows[requestedStart] || null;
  let groupId = String(currentAtStart?._webai_conv_branch_id || '').trim();
  let group = groupId ? webaiBranchGroup(s, groupId) : null;
  const requestedKind = String(kind || group?.kind || 'user_edit').trim() || 'user_edit';
  // Branch metadata is written across the whole active tail.  A later user edit or
  // assistant regeneration inside that tail must not inherit the ancestor group's
  // start index; otherwise every new edit/regenerate jumps back to the first edited
  // turn.  Only reuse a group when the clicked control message is exactly that
  // group's own control/anchor turn.
  if(group){
    const groupKind = String(group.kind || '').trim();
    const groupStart = webaiBranchFindStartIndex(s, groupId);
    const controlRole = webaiBranchControlRoleForKind(requestedKind);
    const roleAtStart = String(currentAtStart?.role || '').trim().toLowerCase();
    const isOwnControl = currentAtStart?._webai_conv_branch_control === true
      && roleAtStart === controlRole
      && Number.isInteger(groupStart)
      && groupStart === requestedStart;
    if((groupKind && groupKind !== requestedKind) || !isOwnControl){
      groupId = '';
      group = null;
    }
  }
  let actualStart = group ? webaiBranchFindStartIndex(s, groupId) : requestedStart;
  if(actualStart < 0) actualStart = requestedStart;
  const storeObj = webaiBranchStore(s);
  if(!storeObj) return null;
  const branchKind = requestedKind;
  if(!group){
    groupId = webaiBranchNewGroupId(s.id);
    const baseTail = rows.slice(actualStart);
    const baseVersion = webaiBranchDecorateTail(webaiBranchCloneMessages(baseTail), groupId, 0, branchKind, { controlRole:webaiBranchControlRoleForKind(branchKind) });
    group = {
      id: groupId,
      kind: branchKind,
      active: 0,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      startIndex: actualStart,
      versions: [{ id:`${groupId}_v0`, createdAt:Date.now(), messages:baseVersion }],
    };
    storeObj.groups[groupId] = group;
  }else{
    group.kind = branchKind;
    group.startIndex = actualStart;
    if(!Array.isArray(group.versions)) group.versions = [];
    const active = Math.max(0, Number(group.active || 0) || 0);
    if(!group.versions[active]) group.versions[active] = { id:`${groupId}_v${active}`, createdAt:Date.now(), messages:[] };
    group.versions[active].messages = webaiBranchDecorateTail(webaiBranchCloneMessages(rows.slice(actualStart)), groupId, active, branchKind, { controlRole:webaiBranchControlRoleForKind(branchKind) });
    group.versions[active].updatedAt = Date.now();
  }
  const newIndex = Array.isArray(group.versions) ? group.versions.length : 0;
  group.active = newIndex;
  group.updatedAt = Date.now();
  group.versions.push({ id:`${groupId}_v${newIndex}`, createdAt:Date.now(), updatedAt:Date.now(), messages:[] });
  return { groupId, versionIndex:newIndex, startIndex:actualStart, kind:branchKind };
}
function webaiBranchReplaceTailForNewVersion(session, startIndex, newTailMessages, kind){
  const ctx = webaiBranchEnsureGroupForReplacement(session, startIndex, kind);
  if(!ctx) return null;
  const rows = Array.isArray(session.messages) ? session.messages : [];
  const decorated = webaiBranchDecorateTail(webaiBranchCloneMessages(newTailMessages), ctx.groupId, ctx.versionIndex, ctx.kind, { controlRole:webaiBranchControlRoleForKind(ctx.kind) });
  const group = webaiBranchGroup(session, ctx.groupId);
  if(group && group.versions && group.versions[ctx.versionIndex]){
    group.versions[ctx.versionIndex].messages = webaiBranchCloneMessages(decorated);
    group.versions[ctx.versionIndex].updatedAt = Date.now();
    group.startIndex = ctx.startIndex;
  }
  session.messages = rows.slice(0, ctx.startIndex).concat(decorated);
  try{ webaiBranchPruneTailWideMessageMeta(session); }catch(_){ }
  session._webaiActiveConversationBranchId = ctx.groupId;
  session._webaiPendingConversationBranch = { ...ctx };
  try{ webaiBranchPersistVisibleGroupVersions(session, { reason:'replace_tail' }); }catch(_){ }
  return ctx;
}
function webaiBranchCurrentContextForSession(session){
  const pending = session?._webaiPendingConversationBranch;
  if(pending && pending.groupId) return { ...pending };
  const activeId = String(session?._webaiActiveConversationBranchId || '').trim();
  const group = activeId ? webaiBranchGroup(session, activeId) : null;
  if(!group) return null;
  const startIndex = webaiBranchFindStartIndex(session, activeId);
  if(startIndex < 0) return null;
  return { groupId:activeId, versionIndex:Number(group.active || 0) || 0, startIndex, kind:String(group.kind || 'user_edit') };
}
function webaiBranchCommitActiveVersion(session, explicitContext=null){
  const s = session && typeof session === 'object' ? session : null;
  if(!s) return false;
  const ctx = explicitContext || webaiBranchCurrentContextForSession(s);
  if(!ctx || !ctx.groupId) return false;
  const group = webaiBranchGroup(s, ctx.groupId);
  if(!group) return false;
  const rows = Array.isArray(s.messages) ? s.messages : [];
  let startIndex = Number(explicitContext?.startIndex);
  if(!Number.isInteger(startIndex) || startIndex < 0 || startIndex > rows.length) startIndex = webaiBranchFindStartIndex(s, ctx.groupId);
  else startIndex = webaiBranchAdjustAssistantRegenerateStartIndex(s, group, startIndex);
  if(startIndex < 0) return false;
  group.startIndex = startIndex;
  const activeSeed = explicitContext ? (ctx.versionIndex ?? group.active ?? 0) : (group.active ?? ctx.versionIndex ?? 0);
  const active = Math.max(0, Number(activeSeed) || 0);
  if(!Array.isArray(group.versions)) group.versions = [];
  if(!group.versions[active]) group.versions[active] = { id:`${ctx.groupId}_v${active}`, createdAt:Date.now(), messages:[] };
  const branchKind = String(group.kind || ctx.kind || 'user_edit').trim() || 'user_edit';
  let activeTail = rows.slice(startIndex);
  if(branchKind === 'assistant_regen') activeTail = webaiBranchNormalizeAssistantRegenerateTail(activeTail, ctx.groupId, active);
  const cleanActiveTail = webaiBranchSquashConsecutiveAssistantRuns(activeTail);
  const decoratedActiveTail = webaiBranchDecorateTail(webaiBranchCloneMessages(cleanActiveTail), ctx.groupId, active, branchKind, { controlRole:webaiBranchControlRoleForKind(branchKind) });
  s.messages = (s.messages || []).slice(0, startIndex).concat(webaiBranchCloneMessages(decoratedActiveTail));
  try{ webaiBranchPruneTailWideMessageMeta(s); }catch(_){ }
  group.versions[active].messages = decoratedActiveTail;
  group.versions[active].updatedAt = Date.now();
  group.active = active;
  group.updatedAt = Date.now();
  delete s._webaiPendingConversationBranch;
  try{ webaiBranchPersistVisibleGroupVersions(s, { reason:'commit' }); }catch(_){ }
  return true;
}
async function webaiBranchSwitchVersion(sessionId, groupId, nextIndex){
  const sid = String(sessionId || store?.activeId || '').trim();
  const gid = String(groupId || '').trim();
  if(!sid || !gid) return;
  await updateSessionById(sid, s=>{
    const group = webaiBranchGroup(s, gid);
    if(!group || !Array.isArray(group.versions) || !group.versions.length) return;
    const total = group.versions.length;
    const requested = Math.max(0, Math.min(total - 1, Number(nextIndex || 0) || 0));
    const startIndex = webaiBranchFindStartIndex(s, gid);
    if(startIndex < 0) return;
    group.startIndex = startIndex;
    webaiBranchCommitActiveVersion(s, { groupId:gid, versionIndex:Number(group.active || 0) || 0, kind:group.kind || 'user_edit' });
    const version = group.versions[requested];
    const tail = webaiBranchDecorateTail(webaiBranchCloneMessages(version?.messages || []), gid, requested, group.kind || 'user_edit', { controlRole:webaiBranchControlRoleForKind(group.kind) });
    s.messages = (s.messages || []).slice(0, startIndex).concat(tail);
    try{ webaiBranchPruneTailWideMessageMeta(s); }catch(_){ }
    group.active = requested;
    group.updatedAt = Date.now();
    s._webaiActiveConversationBranchId = gid;
    delete s._webaiPendingConversationBranch;
    try{ webaiBranchPersistVisibleGroupVersions(s, { reason:'switch' }); }catch(_){ }
    try{ clearPendingAssistantFieldsFromSession(s); }catch(_){ }
    try{ webaiOfficialPersistActivePath(s); }catch(_){ }
  }, { skipCompress:true });
  renderChat();
}
function isInlineAttachmentMessage(msg){
  const c = msg?.content;
  return !!(msg && msg.role === "user" && c && typeof c === "object" && !Array.isArray(c) && (c._kind === "file" || c._kind === "image"));
}

function isInlineEditableUserMessage(msg){
  return !!(msg && msg.role === "user" && (messageHasEditableComposerContent(msg) || isInlineAttachmentMessage(msg)));
}

function collectInlineAttachmentRun(messages, startIndex){
  const msgs = Array.isArray(messages) ? messages : [];
  const out = [];
  for(let i = Math.max(0, Number(startIndex) || 0); i < msgs.length; i++){
    if(isInlineAttachmentMessage(msgs[i])) out.push(i);
    else if(msgs[i]?.role === "system") continue;
    else break;
  }
  return out;
}

function collectInlineLeadingAttachments(messages, targetIndex){
  const msgs = Array.isArray(messages) ? messages : [];
  const out = [];
  for(let i = Math.min((Number(targetIndex) || 0) - 1, msgs.length - 1); i >= 0; i--){
    const m = msgs[i];
    if(m?.role === "system") continue;
    if(isInlineAttachmentMessage(m)){ out.unshift(i); continue; }
    break;
  }
  return out;
}

function resolveInlineEditTarget(session, messageIndex){
  const msgs = Array.isArray(session?.messages) ? session.messages : [];
  const idx = Number(messageIndex);
  if(!Number.isInteger(idx) || idx < 0 || idx >= msgs.length) return null;
  const msg = msgs[idx];
  if(!isInlineEditableUserMessage(msg)) return null;
  if(isInlineAttachmentMessage(msg)){
    const leadingAttachmentIndexes = collectInlineLeadingAttachments(msgs, idx);
    const firstAttachmentIndex = leadingAttachmentIndexes.length ? leadingAttachmentIndexes[0] : idx;
    const attachmentIndexes = collectInlineAttachmentRun(msgs, firstAttachmentIndex);
    let nextIndex = firstAttachmentIndex + 1;
    while(nextIndex < msgs.length && (isInlineAttachmentMessage(msgs[nextIndex]) || msgs[nextIndex]?.role === "system")) nextIndex++;
    if(nextIndex < msgs.length && msgs[nextIndex]?.role === "user" && messageHasEditableComposerContent(msgs[nextIndex])){
      return {
        sessionId: session.id,
        targetIndex: nextIndex,
        cutFrom: firstAttachmentIndex,
        attachmentIndexes,
        skipIndexes: attachmentIndexes.filter(i => i !== nextIndex),
      };
    }
    return {
      sessionId: session.id,
      targetIndex: idx,
      cutFrom: firstAttachmentIndex,
      attachmentIndexes,
      skipIndexes: attachmentIndexes.filter(i => i !== idx),
    };
  }
  const attachmentIndexes = collectInlineLeadingAttachments(msgs, idx);
  const cutFrom = attachmentIndexes.length ? attachmentIndexes[0] : idx;
  return {
    sessionId: session.id,
    targetIndex: idx,
    cutFrom,
    attachmentIndexes,
    skipIndexes: attachmentIndexes.filter(i => i !== idx),
  };
}

function clearInlineMessageEditState(opts={}){
  const shouldRender = opts.render !== false;
  inlineMessageEditState = null;
  if(shouldRender) renderChat();
}

function getActiveInlineEditState(session){
  if(!inlineMessageEditState || !session) return null;
  if(String(inlineMessageEditState.sessionId || "") !== String(session.id || "")) return null;
  const msgs = Array.isArray(session.messages) ? session.messages : [];
  const targetIndex = Number(inlineMessageEditState.targetIndex);
  if(!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex >= msgs.length) return null;
  if(!isInlineEditableUserMessage(msgs[targetIndex])) return null;
  return inlineMessageEditState;
}

function beginInlineMessageEdit(btn, messageIndex){
  const s = getActive();
  if(!s || isSessionStreaming(s.id)) return;
  const resolved = resolveInlineEditTarget(s, messageIndex);
  if(!resolved) return;
  clearComposerEditState();
  clearComposerQuoteState({ silent:true });
  const targetMessage = (s.messages || [])[resolved.targetIndex];
  inlineMessageEditState = {
    ...resolved,
    draft: bubbleMessageTextForComposer(targetMessage || {}),
    preview: getMessageDisplaySnippet(targetMessage),
  };
  renderChat();
  requestAnimationFrame(()=>{
    const editor = chatEl?.querySelector?.(`.inline-message-edit-bubble[data-msg-index="${resolved.targetIndex}"]`);
    const textarea = editor?.querySelector?.('.inline-message-edit-input');
    if(textarea){
      textarea.focus();
      try{ textarea.selectionStart = textarea.selectionEnd = textarea.value.length; }catch(_){ }
    }
    try{ editor?.scrollIntoView?.({ block:'center', behavior:'smooth' }); }catch(_){ }
  });
  try{ btn?.closest('.bubble,.attachment-row')?.classList.add('bubble-editing'); setTimeout(()=>btn?.closest('.bubble,.attachment-row')?.classList.remove('bubble-editing'), 800); }catch(_){ }
}

function inlineEditAttachmentDedupeKeys(contentObj){
  const item = contentObj && typeof contentObj === "object" ? contentObj : {};
  const reg = item.file_registry && typeof item.file_registry === "object" ? item.file_registry : {};
  return [
    item.id,
    item.file_library_id,
    item.library_file_id,
    item.image_id,
    item.attachment_id,
    reg.file_id,
    item.storage_ref,
    item.model_storage_ref,
    item.download_url,
    item.view_url,
    item.url,
    item.filename,
  ].map(v => String(v || '').trim().toLowerCase()).filter(Boolean);
}

function inlineEditAttachmentDedupeKey(contentObj){
  return inlineEditAttachmentDedupeKeys(contentObj)[0] || '';
}

function getInlineEditRemovedAttachmentKeys(state){
  const out = new Set();
  for(const key of (Array.isArray(state?.removedAttachmentKeys) ? state.removedAttachmentKeys : [])){
    const text = String(key || '').trim().toLowerCase();
    if(text) out.add(text);
  }
  return out;
}

function inlineEditAttachmentMatchesRemovedKeys(removedKeys, contentObj){
  const removed = removedKeys instanceof Set ? removedKeys : new Set();
  if(!removed.size) return false;
  return inlineEditAttachmentDedupeKeys(contentObj).some(key => removed.has(key));
}

function inlineEditAttachmentMatchesRemoved(state, contentObj){
  return inlineEditAttachmentMatchesRemovedKeys(getInlineEditRemovedAttachmentKeys(state), contentObj);
}

function markInlineEditAttachmentRemoved(state, contentObj){
  if(!state) return;
  const keys = inlineEditAttachmentDedupeKeys(contentObj);
  if(!keys.length) return;
  const current = new Set(Array.isArray(state.removedAttachmentKeys) ? state.removedAttachmentKeys.map(k => String(k || '').trim().toLowerCase()).filter(Boolean) : []);
  keys.forEach(key => current.add(key));
  state.removedAttachmentKeys = Array.from(current);
}

function filterInlineEditMessageAttachmentArrays(message, removedKeys){
  const m = message && typeof message === "object" ? message : null;
  if(!m || !(removedKeys instanceof Set) || !removedKeys.size) return;
  for(const key of ['file_attachments','attachments','_composer_file_attachments','files']){
    if(Array.isArray(m[key])){
      m[key] = m[key].filter(item => !inlineEditAttachmentMatchesRemovedKeys(removedKeys, item));
    }
  }
}

function buildInlineAttachmentCard(contentObj, opts={}){
  const item = contentObj && typeof contentObj === "object" ? contentObj : {};
  const card = document.createElement("div");
  card.className = "inline-message-edit-attachment";
  card.style.position = 'relative';
  card.style.paddingRight = opts.allowRemove ? '42px' : '';
  const isImg = item._kind === "image";
  const icon = document.createElement("div");
  icon.className = "file-icon";
  icon.innerHTML = attachmentIconSvg(isImg);
  card.appendChild(icon);
  const main = document.createElement("div");
  main.className = "file-main";
  const name = document.createElement("div");
  name.className = "file-name";
  name.textContent=item.filename||chatRenderT('common.attachment',null,'Attachment');
  main.appendChild(name);
  const meta = document.createElement("div");
  meta.className = "file-meta";
  meta.textContent = attachmentMetaLabel(item);
  main.appendChild(meta);
  card.appendChild(main);
  if(opts.allowRemove){
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "file-x";
    removeBtn.title=chatRenderT('common.remove',null,'Remove');
    removeBtn.setAttribute('aria-label',chatRenderT('chat.edit.remove_attachment',null,'Remove attachment'));
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", (e)=>{
      e.preventDefault();
      e.stopPropagation();
      if(typeof opts.onRemove === "function") opts.onRemove(item, card);
    });
    card.appendChild(removeBtn);
  }
  return card;
}

function buildInlineUserEditNode(session, state){
  const msgs = Array.isArray(session?.messages) ? session.messages : [];
  const targetIndex = Number(state?.targetIndex);
  const msg = msgs[targetIndex];
  const div = document.createElement("div");
  div.className = "bubble u inline-message-edit-bubble";
  div.dataset.msgIndex = String(targetIndex);
  div.dataset.inlineEdit = "1";

  const body = document.createElement("div");
  body.className = "bubble-body";
  const wrap = document.createElement("div");
  wrap.className = "inline-message-edit-wrap";

  const attachmentIndexes = Array.isArray(state?.attachmentIndexes) ? state.attachmentIndexes : [];
  const attachmentWrap = document.createElement("div");
  attachmentWrap.className = "inline-message-edit-attachments";
  const seenEditAttachments = new Set();
  const appendEditAttachment = (content)=>{
    if(!content || typeof content !== "object" || Array.isArray(content)) return;
    if(inlineEditAttachmentMatchesRemoved(state, content)) return;
    const key = inlineEditAttachmentDedupeKey(content);
    if(key && seenEditAttachments.has(key)) return;
    if(key) seenEditAttachments.add(key);
    attachmentWrap.appendChild(buildInlineAttachmentCard(content, {
      allowRemove:true,
      onRemove: (_item, card)=>{
        markInlineEditAttachmentRemoved(inlineMessageEditState, content);
        try{ card?.remove?.(); }catch(_){ }
        if(!attachmentWrap.childElementCount){
          try{ attachmentWrap.remove(); }catch(_){ }
        }
      }
    }));
  };
  for(const idx of attachmentIndexes){
    appendEditAttachment(msgs[idx]?.content);
  }
  for(const file of getUserMessageInlineFileAttachments(msg || {})){
    appendEditAttachment(file);
  }
  if(attachmentWrap.childElementCount) wrap.appendChild(attachmentWrap);

  const imageParts = bubbleMessageImagePartsForComposer(msg || {});
  if(imageParts.length){
    const imageWrap = document.createElement("div");
    imageWrap.className = "inline-message-edit-image-preview";
    wrap.appendChild(imageWrap);
    Promise.resolve(renderStructuredMessageContent(imageWrap, imageParts.map(part => cloneComposerImageItem(part)))).catch(()=>{});
  }

  const textarea = document.createElement("textarea");
  textarea.className = "inline-message-edit-input";
  const hasDraft = state && Object.prototype.hasOwnProperty.call(state, 'draft');
  textarea.value = hasDraft ? String(state.draft || '') : bubbleMessageTextForComposer(msg || {});
  textarea.placeholder=(attachmentIndexes.length||imageParts.length)
    ?chatRenderT('chat.edit.attachment_placeholder',null,'Add a note for this message…')
    :chatRenderT('chat.edit.message_placeholder',null,'Edit message');
  textarea.rows = Math.max(2, Math.min(10, textarea.value.split(/\n/).length || 2));
  textarea.addEventListener("input", ()=>{
    if(inlineMessageEditState && String(inlineMessageEditState.sessionId || '') === String(session?.id || '') && Number(inlineMessageEditState.targetIndex) === targetIndex){
      inlineMessageEditState.draft = textarea.value;
    }
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, Math.max(140, Math.round((window.innerHeight || 720) * 0.34))) + "px";
  });
  wrap.appendChild(textarea);

  const actions = document.createElement("div");
  actions.className = "inline-message-edit-actions";
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "inline-message-edit-cancel";
  cancelBtn.textContent=chatRenderT('common.cancel',null,'Cancel');
  cancelBtn.addEventListener("click", (e)=>{
    e.preventDefault();
    clearInlineMessageEditState();
    inputEl?.focus?.();
  });
  const submitBtn = document.createElement("button");
  submitBtn.type = "button";
  submitBtn.className = "inline-message-edit-submit";
  submitBtn.textContent=chatRenderT('composer.send',null,'Send');
  submitBtn.addEventListener("click", async (e)=>{
    e.preventDefault();
    await submitInlineMessageEdit(textarea.value);
  });
  textarea.addEventListener("keydown", async (e)=>{
    if(e.key === "Escape"){
      e.preventDefault();
      clearInlineMessageEditState();
      inputEl?.focus?.();
      return;
    }
    if(e.key === "Enter" && !e.shiftKey && !e.isComposing){
      e.preventDefault();
      await submitInlineMessageEdit(textarea.value);
    }
  });
  actions.appendChild(cancelBtn);
  actions.appendChild(submitBtn);
  wrap.appendChild(actions);
  body.appendChild(wrap);
  div.appendChild(body);
  requestAnimationFrame(()=> textarea.dispatchEvent(new Event("input")));
  return div;
}

function buildInlineEditedMessages(session, state, nextText){
  const msgs = Array.isArray(session?.messages) ? session.messages : [];
  const targetIndex = Number(state?.targetIndex);
  const target = msgs[targetIndex];
  if(!target) return [];
  const createdAtMs = Date.now();
  const attachmentIndexes = Array.isArray(state?.attachmentIndexes) ? state.attachmentIndexes : [];
  const removedKeys = getInlineEditRemovedAttachmentKeys(state);
  const attachmentMessages = [];
  const seenAttachmentIndexes = new Set();
  for(const idx of attachmentIndexes){
    if(seenAttachmentIndexes.has(idx)) continue;
    const m = msgs[idx];
    if(isInlineAttachmentMessage(m) && !inlineEditAttachmentMatchesRemovedKeys(removedKeys, m.content)){
      seenAttachmentIndexes.add(idx);
      const clonedAttachment = cloneMessageForEdit(m);
      clonedAttachment.created_at_ms = clonedAttachment.created_at_ms || createdAtMs;
      clonedAttachment.createdAtMs = clonedAttachment.createdAtMs || clonedAttachment.created_at_ms || createdAtMs;
      attachmentMessages.push(clonedAttachment);
    }
  }

  const text = String(nextText || "").trim();
  if(isInlineAttachmentMessage(target)){
    const targetRemoved = inlineEditAttachmentMatchesRemovedKeys(removedKeys, target.content);
    const out = attachmentMessages.length ? attachmentMessages : (targetRemoved ? [] : [cloneMessageForEdit(target)]);
    if(text){
      out.push({ role:"user", created_at_ms: createdAtMs, createdAtMs, content:text });
    }
    return out;
  }

  const cloned = cloneMessageForEdit(target);
  cloned.content = buildEditedUserContent(target.content, text, removedKeys);
  filterInlineEditMessageAttachmentArrays(cloned, removedKeys);
  cloned.created_at_ms = createdAtMs;
  cloned.createdAtMs = createdAtMs;
  return [...attachmentMessages, cloned];
}

async function submitInlineMessageEdit(nextText){
  const state = inlineMessageEditState ? { ...inlineMessageEditState } : null;
  if(!state) return;
  const sessionId = String(state.sessionId || store?.activeId || "").trim();
  if(!sessionId) return;
  const streamCheck = canStartStreamingForSession(sessionId);
  if(!streamCheck.ok){
    const blockText = describeParallelStreamBlock(streamCheck);
    if(blockText) setStatus(blockText);
    return;
  }
  const session = getSessionById(sessionId);
  if(!session) return;
  if(isSessionArchived(session)){
    try{ toast(window.AperviaI18n?.t('composer.archived') || 'This conversation is archived. Unarchive it before continuing.'); }catch(_){ }
    return;
  }
  const target = (session.messages || [])[Number(state.targetIndex)];
  const removedKeys = getInlineEditRemovedAttachmentKeys(state);
  const attachmentIndexes = Array.isArray(state.attachmentIndexes) ? state.attachmentIndexes : [];
  const attachmentCount = attachmentIndexes.filter(idx => {
    const m = (session.messages || [])[idx];
    return isInlineAttachmentMessage(m) && !inlineEditAttachmentMatchesRemovedKeys(removedKeys, m.content);
  }).length + getUserMessageInlineFileAttachments(target || {}).filter(file => !inlineEditAttachmentMatchesRemovedKeys(removedKeys, file)).length;
  const imageCount = bubbleMessageImageCountForComposer(target || {});
  const text = String(nextText || "").trim();
  if(!text && !attachmentCount && !imageCount){
    setStatus("内容不能为空");
    return;
  }
  const editedMessages = buildInlineEditedMessages(session, state, text);
  if(!editedMessages.length) return;
  const cutFrom = Math.max(0, Number.isInteger(Number(state.cutFrom)) ? Number(state.cutFrom) : Number(state.targetIndex));
  let inlineBranchContext = null;
  prepareSessionForCleanAssistantTurn(sessionId, { immediate:true });
  await updateSessionById(sessionId, s=>{
    inlineBranchContext = webaiBranchReplaceTailForNewVersion(s, cutFrom, editedMessages, 'user_edit');
    try{ webaiOfficialPersistActivePath(s); }catch(_){ }
    try{
      const isDefaultTitle = isDefaultSessionTitle(s.title);
      if(isDefaultTitle && !s.titleAutoLocked){
        const titleSeedText = maybeSeedSessionHeuristicTitle(s);
        if(titleSeedText) s.aiTitleDone = false;
      }
    }catch(_){ }
  }, { skipCompress:true });
  if(inlineBranchContext){
    try{ ensureSessionRuntime(sessionId).pendingBranchSave = inlineBranchContext; }catch(_){ }
  }
  inlineMessageEditState = null;
  syncSessionRoute({ sessionId });
  const inlineTurnStartAt = editedMessages.map(m => _rtMessageCreatedMs(m)).filter(Boolean).pop() || Date.now();
  persistPendingAssistantSnapshot(sessionId, {
    draft: '',
    status: '等待响应中…',
    streaming: true,
    files: [],
    imageReplies: [],
    rtStartAt: inlineTurnStartAt,
    rtFinalMs: 0,
  }, { immediate:true });
  renderChat();
  const requestBody = await buildAsyncChatRequestBodyForSession(sessionId, { text, localImgMap:new Map() });
  return attachSessionToAsyncJob(sessionId, { requestBody });
}

function buildRewritePlan(session, overrideText){
  const state = composerEditState;
  if(!state || !session) return null;
  const msgs = Array.isArray(session.messages) ? session.messages : [];
  if(state.mode === "edit_user"){
    const idx = Number(state.targetIndex);
    if(!(idx >= 0) || !msgs[idx] || msgs[idx].role !== "user") return null;
    return {
      cutFrom: idx,
      branchKind: "user_edit",
      newUserMessage: {
        ...msgs[idx],
        content: buildEditedUserContent(msgs[idx].content, overrideText)
      }
    };
  }
  if(state.mode === "regenerate"){
    const assistantIdx = resolveRegenerateAssistantIndex(msgs, state);
    const userIdx = resolveRegenerateUserIndex(msgs, state, assistantIdx);
    if(!(userIdx >= 0) || !msgs[userIdx] || msgs[userIdx].role !== "user") return null;
    if(!(assistantIdx >= 0) || !msgs[assistantIdx] || msgs[assistantIdx].role !== "assistant") return null;
    return {
      cutFrom: assistantIdx,
      branchKind: "assistant_regen",
      skipNewUserMessage: true
    };
  }
  return null;
}

function regenerateAssistantMatchesState(msg, state){
  if(!msg || String(msg.role || '').toLowerCase() !== 'assistant') return false;
  const targetId = String(state?.assistantClientId || '').trim();
  if(targetId && messageStableClientIdentity(msg) === targetId) return true;
  const targetImage = String(state?.assistantImageSig || '').trim();
  if(targetImage && assistantImageReplyComparableSignature(msg) === targetImage) return true;
  const targetText = String(state?.assistantTextSig || '').trim();
  const currentText = assistantMessageComparableText(msg);
  const targetKind = String(state?.assistantContentKind || '').trim();
  const currentKind = assistantMessageContentKind(msg);
  const targetMs = Number(state?.assistantCreatedAtMs || 0) || 0;
  const currentMs = messageCreatedAtComparableMs(msg);
  if(targetMs > 0 && currentMs > 0 && Math.abs(targetMs - currentMs) <= 1500 && (!targetKind || targetKind === currentKind)) return true;
  return !!(targetText && currentText && targetText === currentText && (!targetKind || targetKind === currentKind));
}

function resolveRegenerateAssistantIndex(messages, state){
  const rows = Array.isArray(messages) ? messages : [];
  const raw = Number(state?.assistantIndex);
  if(Number.isInteger(raw) && raw >= 0 && rows[raw] && String(rows[raw].role || '').toLowerCase() === 'assistant' && regenerateAssistantMatchesState(rows[raw], state)) return raw;
  for(let i = 0; i < rows.length; i++){
    if(regenerateAssistantMatchesState(rows[i], state)) return i;
  }
  if(Number.isInteger(raw) && raw >= 0 && rows[raw] && String(rows[raw].role || '').toLowerCase() === 'assistant') return raw;
  return -1;
}

function regenerateUserMatchesState(msg, state){
  if(!msg || String(msg.role || '').toLowerCase() !== 'user') return false;
  const targetId = String(state?.userClientId || '').trim();
  if(targetId && messageStableClientIdentity(msg) === targetId) return true;
  const targetText = String(state?.userTextSig || '').trim();
  const currentText = userMessageComparableText(msg);
  const targetMs = Number(state?.userCreatedAtMs || 0) || 0;
  const currentMs = messageCreatedAtComparableMs(msg);
  if(targetMs > 0 && currentMs > 0 && Math.abs(targetMs - currentMs) <= 1500) return true;
  return !!(targetText && currentText && targetText === currentText);
}

function resolveRegenerateUserIndex(messages, state, assistantIdx){
  const rows = Array.isArray(messages) ? messages : [];
  const upper = Number.isInteger(Number(assistantIdx)) && Number(assistantIdx) >= 0 ? Number(assistantIdx) : rows.length;
  const raw = Number(state?.userIndex);
  if(Number.isInteger(raw) && raw >= 0 && raw < upper && rows[raw] && String(rows[raw].role || '').toLowerCase() === 'user' && regenerateUserMatchesState(rows[raw], state)) return raw;
  for(let i = Math.min(upper - 1, rows.length - 1); i >= 0; i--){
    if(regenerateUserMatchesState(rows[i], state)) return i;
  }
  return findPrevUserMessageIndex(rows, upper);
}

function saveCurrentChatScrollState(sessionId){
  const sid = sessionId || visibleChatSessionId || store?.activeId;
  if(!sid || !chatEl) return null;
  const state = captureChatScrollState();
  chatScrollMemory[sid] = state;
  return state;
}

function getVisibleDraftBubble(sessionId){
  if(!sessionId) return null;
  const cached = liveDraftBubbleEls[sessionId];
  if(cached && cached.isConnected) return cached;
  const found = chatEl.querySelector(`.bubble[data-session-draft="${sessionId}"]`);
  if(found) liveDraftBubbleEls[sessionId] = found;
  return found;
}

function visibleDraftBubbleIsAfterLatestUserTurn(bubble){
  if(!bubble || !chatEl?.children) return true;
  const children = Array.from(chatEl.children || []);
  const draftIndex = children.indexOf(bubble);
  if(draftIndex < 0) return true;
  let lastUserIndex = -1;
  for(let i = 0; i < children.length; i += 1){
    const node = children[i];
    if(!node || !node.querySelectorAll) continue;
    const isUserBubble = node.classList?.contains('bubble') && node.classList?.contains('u');
    const hasUserBubble = isUserBubble || !!node.querySelector?.('.bubble.u');
    if(hasUserBubble) lastUserIndex = i;
  }
  return lastUserIndex < 0 || draftIndex > lastUserIndex;
}

function sessionLastVisibleMessageIsAssistant(sessionId){
  const sid = String(sessionId || '').trim();
  const session = sid ? getSessionById(sid) : getActive();
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  for(let i = rows.length - 1; i >= 0; i--){
    const msg = rows[i];
    if(!msg || String(msg.role || '').toLowerCase() === 'system') continue;
    return String(msg.role || '').toLowerCase() === 'assistant';
  }
  return false;
}

function sessionRuntimeHasVisibleDraftContent(rt){
  const data = rt && typeof rt === 'object' ? rt : {};
  if(String(data.draftText || '').trim()) return true;
  if(String(data.draftProcessText || '').trim()) return true;
  if(Array.isArray(data.draftFiles) && data.draftFiles.length) return true;
  if(_normalizePendingAssistantImageReplies(data.draftImageReplies || []).length) return true;
  if(normalizeAssistantWeatherPayload(data.draftWeatherPayload || null)) return true;
  if(_normalizePendingAssistantReasoning(data.reasoning || []).length) return true;
  if(_reasoningMetaHasVisibleContent(data.reasoningMeta || {})) return true;
  if(normalizeAssistantSourceItems(data.sources || []).length) return true;
  return false;
}

function sessionRuntimeHasAssistantContinuationTarget(rt){
  const data = rt && typeof rt === 'object' ? rt : {};
  const target = data.assistantContinuationTarget && typeof data.assistantContinuationTarget === 'object' ? data.assistantContinuationTarget : null;
  if(!target) return false;
  const idx = Number(target.messageIndex);
  const id = String(target.messageId || '').trim();
  return (Number.isInteger(idx) && idx >= 0) || !!id;
}

function normalizeAssistantDedupText(raw){
  return String(raw ?? '')
    .replace(/\u00a0/g, ' ')
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s+/g, ' ')
    .trim();
}

function assistantMessageComparableText(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  if(String(m.role || '').toLowerCase() !== 'assistant') return '';
  const content = m.content;
  if(typeof content === 'string') return normalizeAssistantDedupText(content);
  if(Array.isArray(content)){
    return normalizeAssistantDedupText(content.map(part => {
      if(!part || typeof part !== 'object') return '';
      if(part.type === 'text') return part.text || '';
      if(typeof part.text === 'string') return part.text;
      return '';
    }).filter(Boolean).join('\n'));
  }
  if(content && typeof content === 'object'){
    const kind = String(content._kind || '').trim();
    if(kind === 'weather' || kind === 'genfiles' || kind === 'file' || kind === 'image') return '';
    if(kind === 'image_reply') return normalizeAssistantDedupText(content.text || content.answer || '');
    if(kind === 'memory_event') return normalizeAssistantDedupText(content.text || content.title || '');
    return normalizeAssistantDedupText(content.text || content.answer || content.content || '');
  }
  return '';
}
function assistantMessageContentKind(msg){
  const content = msg && typeof msg === 'object' ? msg.content : null;
  if(Array.isArray(content)) return 'array';
  if(content && typeof content === 'object') return String(content._kind || 'object').trim() || 'object';
  return typeof content === 'string' ? 'text' : '';
}
function assistantImageReplyComparableSignature(msg){
  const content = msg && typeof msg === 'object' ? msg.content : null;
  const payload = content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'image_reply' ? content : null;
  if(!payload) return '';
  const parts = [String(payload.source || ''), String(payload.subject || ''), String(payload.text || '')].map(v => v.trim()).filter(Boolean);
  const images = Array.isArray(payload.images) ? payload.images : [];
  for(const image of images){
    if(!image || typeof image !== 'object') continue;
    const one = [
      image.storage_ref, image.model_storage_ref, image.file_library_id, image.library_file_id,
      image.image_id, image.attachment_id, image.id, image.raw_url, image.rawUrl,
      image.view_url, image.viewUrl, image.download_url, image.downloadUrl,
      image.provider_url, image.providerUrl, image.preview_url, image.previewUrl,
      image.persisted_url, image.persistedUrl, image.server_url, image.serverUrl,
      image.url, image.src
    ].map(v => String(v || '').trim()).filter(Boolean);
    if(image.image_url && typeof image.image_url === 'object'){
      const u = String(image.image_url.url || '').trim();
      if(u) one.push(u);
    }
    if(one.length) parts.push(one.join('|'));
  }
  return normalizeAssistantDedupText(parts.join('\n')).slice(0, 2000);
}
function assistantMessagesHaveSameVisibleText(a, b){
  const left = assistantMessageComparableText(a);
  const right = assistantMessageComparableText(b);
  if(left && right && left === right) return true;
  const leftImage = assistantImageReplyComparableSignature(a);
  const rightImage = assistantImageReplyComparableSignature(b);
  return !!(leftImage && rightImage && leftImage === rightImage);
}

function userMessageComparableText(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  if(String(m.role || '').toLowerCase() !== 'user') return '';
  const content = m.content;
  if(typeof content === 'string') return normalizeAssistantDedupText(content);
  if(Array.isArray(content)){
    return normalizeAssistantDedupText(content.map(part => {
      if(!part || typeof part !== 'object') return '';
      if(part.type === 'text') return part.text || '';
      if(typeof part.text === 'string') return part.text;
      return '';
    }).filter(Boolean).join('\n'));
  }
  return '';
}

function messageCreatedAtComparableMs(msg){
  const m = msg && typeof msg === 'object' ? msg : {};
  const raw = Number(m.created_at_ms || m.createdAtMs || m.created_at || m.createdAt || m.timestamp || m.ts || 0) || 0;
  if(!raw) return 0;
  return raw < 100000000000 ? raw * 1000 : raw;
}

function userMessagesHaveSameVisibleText(a, b, maxGapMs=3500){
  const left = userMessageComparableText(a);
  const right = userMessageComparableText(b);
  if(!left || !right || left !== right) return false;
  const leftQuote = normalizeAssistantQuoteText(a?._quote || '');
  const rightQuote = normalizeAssistantQuoteText(b?._quote || '');
  if(leftQuote !== rightQuote) return false;
  const leftQuoteSourceId = getMessageQuoteSourceId(a);
  const rightQuoteSourceId = getMessageQuoteSourceId(b);
  if(leftQuoteSourceId !== rightQuoteSourceId) return false;
  const leftQuoteOffset = getMessageQuoteSourceOffset(a);
  const rightQuoteOffset = getMessageQuoteSourceOffset(b);
  if(leftQuoteOffset !== rightQuoteOffset) return false;
  const at = messageCreatedAtComparableMs(a);
  const bt = messageCreatedAtComparableMs(b);
  if(at > 0 && bt > 0) return Math.abs(at - bt) <= Math.max(80, Number(maxGapMs || 3500) || 3500);
  return false;
}

function messageStableClientIdentity(msg){
  const m = msg && typeof msg === 'object' ? msg : null;
  if(!m) return '';
  for(const key of ['_client_msg_id', 'client_msg_id', 'clientMessageId']){
    const value = String(m[key] || '').trim();
    if(value) return value.slice(0, 220);
  }
  return '';
}

function userMessagesHaveSameClientIdentity(a, b){
  const leftMsg = a && typeof a === 'object' ? a : null;
  const rightMsg = b && typeof b === 'object' ? b : null;
  if(!leftMsg || !rightMsg) return false;
  if(String(leftMsg.role || '').toLowerCase() !== 'user' || String(rightMsg.role || '').toLowerCase() !== 'user') return false;
  const leftId = messageStableClientIdentity(leftMsg);
  const rightId = messageStableClientIdentity(rightMsg);
  if(leftId && rightId) return leftId === rightId;
  return userMessagesHaveSameVisibleText(leftMsg, rightMsg, 180);
}

function visibleMessagesAreDuplicateNeighbors(prev, current){
  if(assistantMessagesHaveSameVisibleText(prev, current)) return true;
  if(userMessagesHaveSameClientIdentity(prev, current)) return true;
  return false;
}

function createOutgoingUserClientSendId(sessionId, createdAtMs){
  const sid = String(sessionId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 48);
  const ts = Number(createdAtMs || Date.now()) || Date.now();
  const randomPart = Math.random().toString(16).slice(2, 10);
  return ['send', sid, ts.toString(36), randomPart].filter(Boolean).join('_').slice(0, 180);
}

function decorateOutgoingUserMessage(message, sendId, partKey='content'){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg || String(msg.role || '').toLowerCase() !== 'user') return msg;
  const sid = String(sendId || '').trim();
  if(!sid) return msg;
  const part = String(partKey || 'content').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 64) || 'content';
  msg._client_send_id = sid;
  msg._client_msg_id = `${sid}:${part}`.slice(0, 260);
  const mode = (typeof cloudSyncCurrentConversationMode === 'function') ? cloudSyncCurrentConversationMode() : 'chat';
  const localId = String(msg.localId || msg.local_id || msg._client_msg_id || '').trim();
  msg.localId = localId;
  msg.local_id = localId;
  msg.messageLocalId = localId;
  msg.message_local_id = localId;
  msg.opId = String(msg.opId || msg.op_id || (typeof makeCloudSyncOpId === 'function' ? makeCloudSyncOpId('append_message', localId || sid) : ('append_message:' + (localId || sid)))).trim();
  msg.op_id = msg.opId;
  msg.messageOpId = msg.opId;
  msg.message_op_id = msg.opId;
  msg.conversationMode = mode;
  msg.conversation_mode = mode;
  msg.syncStatus = String(msg.syncStatus || msg.sync_status || 'sending').trim() || 'sending';
  msg.sync_status = msg.syncStatus;
  msg.messageRecovery = {
    ...(msg.messageRecovery && typeof msg.messageRecovery === 'object' ? msg.messageRecovery : {}),
    mode,
    local_id: localId,
    op_id: msg.opId,
    status: msg.syncStatus,
    created_at: Number(msg.created_at_ms || msg.createdAtMs || Date.now()) || Date.now(),
  };
  return msg;
}


function createAssistantClientMessageId(sessionId, createdAtMs, jobKey='', partKey='answer'){
  const sid = String(sessionId || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 48);
  const ts = Number(createdAtMs || Date.now()) || Date.now();
  const job = String(jobKey || '').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 64);
  const part = String(partKey || 'answer').replace(/[^0-9A-Za-z_.:-]/g, '_').slice(0, 48) || 'answer';
  return ['assistant', sid, ts.toString(36), job, part].filter(Boolean).join('_').slice(0, 220);
}

function decorateOutgoingAssistantMessage(message, sessionId, createdAtMs, jobKey='', partKey='answer'){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg || String(msg.role || '').toLowerCase() !== 'assistant') return msg;
  const session = getSessionById(sessionId);
  const selectedModel = String(session?.model || '').trim();
  const runtimeModel = String(msg.runtimeModel || msg.runtime_model || '').trim();
  if(!String(msg.model || msg.modelName || msg.model_name || '').trim() && (runtimeModel || selectedModel)){
    msg.model = runtimeModel || selectedModel;
  }
  if(!messageStableClientIdentity(msg)) msg._client_msg_id = createAssistantClientMessageId(sessionId, createdAtMs, jobKey, partKey);
  const mode = (typeof cloudSyncCurrentConversationMode === 'function') ? cloudSyncCurrentConversationMode() : 'chat';
  const localId = String(msg.localId || msg.local_id || msg._client_msg_id || '').trim();
  msg.localId = localId;
  msg.local_id = localId;
  msg.messageLocalId = localId;
  msg.message_local_id = localId;
  msg.opId = String(msg.opId || msg.op_id || (typeof makeCloudSyncOpId === 'function' ? makeCloudSyncOpId('append_assistant_message', localId || sessionId) : ('append_assistant_message:' + (localId || sessionId)))).trim();
  msg.op_id = msg.opId;
  msg.messageOpId = msg.opId;
  msg.message_op_id = msg.opId;
  msg.conversationMode = mode;
  msg.conversation_mode = mode;
  msg.syncStatus = String(msg.syncStatus || msg.sync_status || 'pending').trim() || 'pending';
  msg.sync_status = msg.syncStatus;
  msg.messageRecovery = {
    ...(msg.messageRecovery && typeof msg.messageRecovery === 'object' ? msg.messageRecovery : {}),
    mode,
    local_id: localId,
    op_id: msg.opId,
    server_run_id: String(jobKey || msg.messageRecovery?.server_run_id || '').trim(),
    status: msg.syncStatus,
    created_at: Number(msg.created_at_ms || msg.createdAtMs || createdAtMs || Date.now()) || Date.now(),
  };
  return msg;
}

function pushOutgoingUserMessageOnce(messages, userMsg){
  const rows = Array.isArray(messages) ? messages : [];
  const candidate = userMsg && typeof userMsg === 'object' ? userMsg : null;
  if(!candidate || String(candidate.role || '').toLowerCase() !== 'user') return false;
  for(let i = rows.length - 1; i >= 0; i--){
    const msg = rows[i];
    if(!msg || String(msg.role || '').toLowerCase() === 'system') continue;
    if(userMessagesHaveSameClientIdentity(msg, candidate)) return false;
    if(String(msg.role || '').toLowerCase() !== 'user') break;
  }
  rows.push(candidate);
  return true;
}

function lastVisibleMessageFromSession(session){
  const rows = Array.isArray(session?.messages) ? session.messages : [];
  for(let i = rows.length - 1; i >= 0; i--){
    const msg = rows[i];
    if(!msg || String(msg.role || '').toLowerCase() === 'system') continue;
    return msg;
  }
  return null;
}

function findDuplicateAssistantMessageIndexInCurrentTurn(messages, candidate){
  const rows = Array.isArray(messages) ? messages : [];
  for(let i = rows.length - 1; i >= 0; i--){
    const msg = rows[i];
    if(!msg || String(msg.role || '').toLowerCase() === 'system') continue;
    if(String(msg.role || '').toLowerCase() === 'user') break;
    if(assistantMessagesHaveSameVisibleText(msg, candidate)) return i;
  }
  return -1;
}

function mergeGeneratedFiles(baseFiles, incomingFiles){
  const merged = [];
  const seen = new Set();
  const pushOne = (f)=>{
    if(!f || typeof f !== 'object') return;
    let href = '';
    try{ href = String(getAssistantArtifactDownloadHref(f) || '').trim(); }catch(_){ href = ''; }
    const filename = String(f.filename || '').trim();
    let key = (href || filename || '').toLowerCase();
    if(!key){
      try{ key = JSON.stringify(f).toLowerCase(); }catch(_){ key = ''; }
    }
    if(!key || seen.has(key)) return;
    seen.add(key);
    merged.push(f);
  };
  (Array.isArray(baseFiles) ? baseFiles : []).forEach(pushOne);
  (Array.isArray(incomingFiles) ? incomingFiles : []).forEach(pushOne);
  return merged;
}

function mergeAssistantMessageMetadata(target, incoming){
  const dst = target && typeof target === 'object' ? target : null;
  const src = incoming && typeof incoming === 'object' ? incoming : null;
  if(!dst || !src) return dst;
  if(src.webHit) dst.webHit = true;
  if(src.sourceBound) dst.sourceBound = true;
  const mergedSources = mergeAssistantSourceItems(normalizeAssistantSourceItems(dst.sources || []), normalizeAssistantSourceItems(src.sources || []));
  if(mergedSources.length) dst.sources = mergedSources;
  const mergedFiles = mergeGeneratedFiles(dst.generatedFiles || dst.generated_files || [], src.generatedFiles || src.generated_files || []);
  if(mergedFiles.length){
    dst.generatedFiles = mergedFiles.slice(-12);
    dst.generated_files = dst.generatedFiles;
  }
  const incomingWeather = normalizeAssistantWeatherPayload(src.weather || src.weatherPayload || src.weather_payload || null);
  if(incomingWeather) dst.weather = incomingWeather;
  const mergedImageReplies = _normalizePendingAssistantImageReplies([...(Array.isArray(dst.imageReplies) ? dst.imageReplies : []), ...(Array.isArray(src.imageReplies) ? src.imageReplies : [])]);
  if(mergedImageReplies.length) dst.imageReplies = mergedImageReplies;
  const mergedReasoning = _normalizePendingAssistantReasoning([...(Array.isArray(dst.reasoning) ? dst.reasoning : []), ...(Array.isArray(src.reasoning) ? src.reasoning : [])]);
  if(mergedReasoning.length) dst.reasoning = mergedReasoning;
  const mergedReasoningMeta = { ..._normalizePendingAssistantReasoningMeta(dst.reasoningMeta || {}), ..._normalizePendingAssistantReasoningMeta(src.reasoningMeta || {}) };
  if(Object.keys(mergedReasoningMeta).length) dst.reasoningMeta = mergedReasoningMeta;
  const incomingUsage = normalizeAssistantUsagePayload(src.generationUsage || src.generation_usage || src.usage || null);
  if(incomingUsage){
    dst.generationUsage = incomingUsage;
    dst.generation_usage = incomingUsage;
  }
  for(const key of ['_webai_conv_branch_id', '_webai_conv_branch_version', '_webai_conv_branch_kind', '_webai_conv_branch_anchor', '_webai_conv_branch_control']){
    if(Object.prototype.hasOwnProperty.call(src, key)) dst[key] = src[key];
  }
  if(src.runtimeModel && !dst.runtimeModel) dst.runtimeModel = src.runtimeModel;
  return dst;
}

function pendingAssistantDuplicatesLastAssistant(sessionId, snapshot=null, rt=null){
  const sid = String(sessionId || '').trim();
  const session = sid ? getSessionById(sid) : getActive();
  const last = lastVisibleMessageFromSession(session);
  if(!last || String(last.role || '').toLowerCase() !== 'assistant') return false;
  const lastText = assistantMessageComparableText(last);
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : null;
  const runtime = rt && typeof rt === 'object' ? rt : null;
  const draftText = normalizeAssistantDedupText(runtime?.draftText || snap?.draft || '');
  if(draftText && lastText && draftText === lastText) return true;
  const processText = String(runtime?.draftProcessText || snap?.process || '').trim();
  const statusText = String(runtime?.statusText || snap?.status || '').trim();
  const files = _normalizePendingAssistantFiles(runtime?.draftFiles || snap?.files || []);
  const imageReplies = _normalizePendingAssistantImageReplies(runtime?.draftImageReplies || snap?.imageReplies || []);
  const reasoningMeta = _normalizePendingAssistantReasoningMeta(runtime?.reasoningMeta || snap?.reasoningMeta || {});
  const reasoning = _mergeNativeReasoningEntry(_normalizePendingAssistantReasoning(runtime?.reasoning || snap?.reasoning || []), reasoningMeta);
  const streaming = !!(runtime?.streaming || snap?.streaming);
  const hasOnlyStatusLikeDraft = !draftText && !processText && !files.length && !imageReplies.length && !reasoning.length && !_reasoningMetaHasVisibleContent(reasoningMeta) && statusText;
  return !!(hasOnlyStatusLikeDraft && (!streaming || /完成|已完成|等待响应|连接模型|生成回答|思考中/.test(statusText)));
}

function resetSessionRuntimeDraftState(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  const rt = ensureSessionRuntime(sid);
  rt.draftText = '';
  rt.statusText = '';
  rt.draftProcessText = '';
  rt.draftFiles = [];
  rt.draftImageReplies = [];
  rt.draftWeatherPayload = null;
  rt.reasoning = [];
  rt.reasoningMeta = {};
  rt.sources = [];
  rt.streaming = false;
}

function sessionRuntimeDraftBelongsToCurrentTurn(sessionId, runtime){
  const sid = String(sessionId || '').trim();
  if(!sid) return false;
  const s = getSessionById(sid);
  if(!s) return false;
  const rt = runtime && typeof runtime === 'object' ? runtime : ensureSessionRuntime(sid);
  if(sessionRuntimeHasAssistantContinuationTarget(rt)) return true;
  if(sessionObjectLastVisibleMessageIsAssistant(s)) return false;
  if(sessionHasTerminalBackendErrorForPendingAssistant(s)) return false;
  if(String(getSessionPendingJobId(sid) || '').trim()) return true;
  if(!rt.streaming && !sessionRuntimeHasVisibleDraftContent(rt)) return true;
  const latestUserMs = _rtLatestUserCreatedMs(s);
  if(!latestUserMs) return false;
  const startAt = pendingAssistantTimestampMs(rt.rtStartAt);
  if(startAt > 0) return startAt >= latestUserMs - 3000;
  return false;
}

function discardStaleSessionRuntimeDraft(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  resetSessionRuntimeDraftState(sid);
  try{
    const rt = ensureSessionRuntime(sid);
    rt.rtStartAt = 0;
    if(opts?.clearFinalMs) rt.rtFinalMs = 0;
  }catch(_){ }
  try{ clearPendingAssistantSnapshot(sid, { immediate: opts?.immediate !== false }); }catch(_){ }
  try{ removeVisibleDraftBubbleForSession(sid); }catch(_){ }
}

function discardDuplicatePendingAssistantState(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  try{
    const timer = _streamPendingSnapshotTimers[sid];
    if(timer){ clearTimeout(timer); delete _streamPendingSnapshotTimers[sid]; }
  }catch(_){ }
  resetSessionRuntimeDraftState(sid);
  clearPendingAssistantSnapshot(sid, { immediate: opts?.immediate !== false });
  removeVisibleDraftBubbleForSession(sid);
}

function prepareSessionForCleanAssistantTurn(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return;
  try{
    const timer = _streamPendingSnapshotTimers[sid];
    if(timer){ clearTimeout(timer); delete _streamPendingSnapshotTimers[sid]; }
  }catch(_){ }
  try{ resetSessionRuntimeDraftState(sid); }catch(_){ }
  try{ clearPendingAssistantSnapshot(sid, { immediate: opts?.immediate !== false }); }catch(_){ }
  try{ clearSessionPendingJob(sid, { immediate: opts?.immediate !== false }); }catch(_){ }
  try{ removeVisibleDraftBubbleForSession(sid); }catch(_){ }
  try{ delete liveDraftBubbleEls[sid]; }catch(_){ }
}

function removeVisibleDraftBubbleForSession(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid || !chatEl?.querySelectorAll) return false;
  let removed = false;
  const nodes = new Set();
  const cached = liveDraftBubbleEls[sid];
  if(cached && cached.isConnected) nodes.add(cached);
  chatEl.querySelectorAll('.bubble[data-session-draft]').forEach(node => {
    if(String(node?.dataset?.sessionDraft || '').trim() === sid) nodes.add(node);
  });
  nodes.forEach(node => {
    try{ node.remove(); removed = true; }catch(_){ }
  });
  delete liveDraftBubbleEls[sid];
  return removed;
}


function _streamingFenceInfoFromText(text){
  const src = String(text || '').replace(/\r\n/g, '\n');
  if(!src) return { src, open:false, lang:'', code:'', openFenceStart:-1 };
  const lines = src.split('\n');
  let pos = 0;
  let fenceOpen = false;
  let openFenceStart = -1;
  let openFenceLang = '';
  let openFenceContentStart = -1;
  for(let i = 0; i < lines.length; i += 1){
    const line = String(lines[i] || '');
    const lineStart = pos;
    const lineEnd = lineStart + line.length;
    const hasNextLine = i < lines.length - 1;
    if(/^\s*```/.test(line)){
      if(!fenceOpen){
        fenceOpen = true;
        openFenceStart = lineStart;
        openFenceLang = line.replace(/^\s*```+/, '').trim().split(/\s+/, 1)[0] || '';
        openFenceContentStart = hasNextLine ? (lineEnd + 1) : lineEnd;
      }else{
        fenceOpen = false;
        openFenceStart = -1;
        openFenceLang = '';
        openFenceContentStart = -1;
      }
    }
    pos = lineEnd + 1;
  }
  if(!fenceOpen || openFenceStart < 0) return { src, open:false, lang:'', code:'', openFenceStart:-1 };
  return {
    src,
    open:true,
    lang: openFenceLang,
    code: src.slice(Math.max(0, openFenceContentStart)),
    openFenceStart,
  };
}

function computeStreamingDraftRenderPlan(text){
  const src = String(text || '').replace(/\r\n/g, '\n');
  if(!src) return { rendered:'', tail:'', liveCode:null };
  const fence = _streamingFenceInfoFromText(src);
  if(fence.open){
    return {
      rendered: src.slice(0, Math.max(0, fence.openFenceStart)),
      tail: '',
      liveCode: {
        rawLang: String(fence.lang || '').trim(),
        code: String(fence.code || ''),
      },
    };
  }
  const lastNewline = src.lastIndexOf('\n');
  if(lastNewline < 0){
    return { rendered:'', tail: src, liveCode:null };
  }
  return {
    rendered: src.slice(0, lastNewline + 1),
    tail: src.slice(lastNewline + 1),
    liveCode: null,
  };
}

function buildStreamingLiveCodeBlockHtml(rawCode, rawLang=''){
  const codeText = normalizeRunnableCodeSource(String(rawCode || ''));
  const inferredLang = String(rawLang || '').trim() || inferCodeFenceLangFromBlock(codeText.split('\n')) || 'code';
  const displayLang = escapeHtml(getCodeLangDisplayName(inferredLang || 'code'));
  const langClass = escapeHtml(getCodeLangClassName(inferredLang || 'code'));
  const normalizedCode = codeText.replace(/\n$/, '');
  const lineCount = Math.max(1, normalizedCode ? normalizedCode.split('\n').length : 1);
  const codeHtml = highlightCode(codeText, inferredLang || 'code');
  const rawCodeAttr = escapeHtml(encodeURIComponent(codeText));
  const rawLangAttr = escapeHtml(inferredLang || 'code');
  return `<div class="code-block streaming-live-code" data-streaming-live="1" data-code-lines="${lineCount}" data-code-raw-lang="${rawLangAttr}"><div class="code-toolbar"><div class="code-toolbar-left"><span class="code-lang">${displayLang}</span><span class="code-lines">${escapeHtml(chatRenderT('code.lines',{count:lineCount},`${lineCount} lines`))}</span><span class="code-streaming-state">${escapeHtml(chatRenderT('chat.streaming.generating',null,'Generating'))}</span></div><div class="code-toolbar-right"><button class="icon-btn code-copy" type="button" data-copy-code="streaming_live">${escapeHtml(chatRenderT('code.copy',null,'Copy code'))}</button></div></div><pre><code class="language-${langClass}" data-raw-code="${rawCodeAttr}">${codeHtml}</code></pre></div>`;
}

function syncStreamingLiveCodeViewport(contentWrap){
  const pre = contentWrap?.querySelector?.('.streaming-live-code pre');
  if(!pre) return;
  const maxScrollTop = Math.max(0, pre.scrollHeight - pre.clientHeight);
  pre.scrollTop = maxScrollTop;
}

function renderStreamingDraftContent(contentWrap, visibleText, sessionId=''){
  if(!contentWrap) return false;
  const plan = computeStreamingDraftRenderPlan(String(visibleText || ''));
  let changed = false;

  let renderedWrap = contentWrap.querySelector('.streaming-rendered-html');
  if(!renderedWrap){
    renderedWrap = document.createElement('div');
    renderedWrap.className = 'streaming-rendered-html';
    contentWrap.appendChild(renderedWrap);
  }
  const renderedText = String(plan.rendered || '');
  if(renderedWrap.dataset.renderedText !== renderedText){
    renderedWrap.dataset.renderedText = renderedText;
    renderedWrap.innerHTML = renderedText ? renderMessageHtml('assistant', renderedText, { streamingDraft:true }) : '';
    if(renderedText) linkifyAssistantGeneratedFileMentions(renderedWrap, sessionId || store?.activeId || '');
    changed = true;
  }
  renderedWrap.style.display = renderedText ? '' : 'none';

  let liveCodeWrap = contentWrap.querySelector('.streaming-live-code-wrap');
  if(plan.liveCode && String(plan.liveCode.code || '').length){
    if(!liveCodeWrap){
      liveCodeWrap = document.createElement('div');
      liveCodeWrap.className = 'streaming-live-code-wrap';
      contentWrap.appendChild(liveCodeWrap);
    }
    const signature = JSON.stringify([String(plan.liveCode.rawLang || ''), String(plan.liveCode.code || '')]);
    if(liveCodeWrap.dataset.liveCodeSignature !== signature){
      liveCodeWrap.dataset.liveCodeSignature = signature;
      liveCodeWrap.innerHTML = buildStreamingLiveCodeBlockHtml(plan.liveCode.code, plan.liveCode.rawLang);
      changed = true;
    }
    liveCodeWrap.style.display = '';
    syncStreamingLiveCodeViewport(contentWrap);
  }else if(liveCodeWrap){
    liveCodeWrap.remove();
    changed = true;
  }

  let tailNode = contentWrap.querySelector('.streaming-draft-tail');
  const tailText = String(plan.tail || '');
  if(tailText){
    if(!tailNode){
      tailNode = document.createElement('div');
      tailNode.className = 'streaming-draft-tail';
      tailNode.style.cssText = 'white-space:pre-wrap;word-break:break-word;line-height:1.75;';
      contentWrap.appendChild(tailNode);
    }
    if(tailNode.textContent !== tailText){
      tailNode.textContent = tailText;
      changed = true;
    }
  }else if(tailNode){
    tailNode.remove();
    changed = true;
  }

  return changed;
}

function patchStreamingDraftBubble(bubble, opts={}){
  if(!bubble?.querySelector) return bubble;
  const sessionId = String(opts.sessionId || bubble.dataset.sessionDraft || '').trim();
  const body = bubble.querySelector('.bubble-body');
  if(!body) return bubble;
  const draftRuntime = sessionId ? ensureSessionRuntime(sessionId) : null;

  const visibleText = String(opts.visibleText || '');
  const statusText = String(opts.statusText || '').trim();
  const processText = String(opts.processText || '').trim();
  const nextReasoningNode = buildReasoningPanel(sessionId, { statusText });
  const prevReasoningNodes = Array.from(body.querySelectorAll(':scope > .activity-inline-trigger-wrap, :scope > .reasoning-panels, :scope > .reasoning-panel'));
  const prevReasoningNode = prevReasoningNodes[0] || null;
  if(nextReasoningNode){
    if(prevReasoningNode) prevReasoningNode.replaceWith(nextReasoningNode);
    else body.insertBefore(nextReasoningNode, body.firstChild || null);
    prevReasoningNodes.slice(1).forEach(node => { try{ node.remove(); }catch(_){ } });
  }else if(prevReasoningNodes.length){
    prevReasoningNodes.forEach(node => { try{ node.remove(); }catch(_){ } });
  }
  if(typeof syncMcpInlineCardsInBody === 'function'){
    syncMcpInlineCardsInBody(body,sessionId,draftRuntime?.reasoningMeta?.mcpCards || []);
  }

  const draftImageReplies = _normalizePendingAssistantImageReplies(draftRuntime?.draftImageReplies || []);
  const draftFiles = _normalizePendingAssistantFiles(draftRuntime?.draftFiles || []);
  const draftWeatherPayload = normalizeAssistantWeatherPayload(draftRuntime?.draftWeatherPayload || null);
  const hasDraftImageReplies = draftImageReplies.length > 0;
  const hasDraftFiles = draftFiles.length > 0;
  const hasDraftWeather = !!draftWeatherPayload;

  let contentWrap = body.querySelector('.reasoning-answer-wrap');
  let thinkingNode = body.querySelector('.thinking-wrap');
  const hasText = !!String(visibleText || '').trim();
  // Text streaming turns must stay text-owned.  Late image_reply / mirror
  // callbacks from a previous image generation can leave draftImageReplies in
  // runtime; do not let those images replace or sit above the current answer.
  syncAssistantImageRepliesInBody(body, hasText ? [] : draftImageReplies);
  syncAssistantWeatherCardInBody(body, draftWeatherPayload);
  const existingImageStage = body.querySelector('.image-generation-stage');
  const statusLooksImageStage = isImageGenerationStatusText(statusText);
  const shouldShowImageStage = !hasText && (statusLooksImageStage || bubble.dataset.imageStageReady === '1' || !!existingImageStage);
  let enhancementChanged = false;

  if(hasText){
    clearBubbleImageStageShell(bubble, { remove:true });
    if(!contentWrap){
      contentWrap = document.createElement('div');
      contentWrap.className = 'reasoning-answer-wrap';
      if(thinkingNode){
        thinkingNode.replaceWith(contentWrap);
        thinkingNode = null;
      }else if(nextReasoningNode && nextReasoningNode.parentNode === body){
        body.insertBefore(contentWrap, nextReasoningNode.nextSibling || null);
      }else{
        body.appendChild(contentWrap);
      }
    }
    enhancementChanged = renderStreamingDraftContent(contentWrap, visibleText, sessionId) || enhancementChanged;
    if(thinkingNode) thinkingNode.remove();
  }else if(shouldShowImageStage){
    if(contentWrap) contentWrap.remove();
    if(thinkingNode) thinkingNode.remove();
    const previousImageStageStatus = String(existingImageStage?.querySelector?.('.image-generation-stage-status')?.textContent || '').trim();
    const imageGeneratingText = chatRenderT('stream.generating_image', null, 'Generating image…');
    const imageStageStatusText = statusLooksImageStage ? (statusText || imageGeneratingText) : (previousImageStageStatus || imageGeneratingText);
    const stage = ensureBubbleImageStageShell(bubble, { statusText: imageStageStatusText });
    if(stage?.shell){
      if(bubble.dataset.imageStageReady === '1'){
        stage.shell.classList.remove('is-loading');
        stage.shell.classList.add('is-ready');
      }else{
        stage.shell.classList.remove('is-ready');
        stage.shell.classList.add('is-loading');
      }
    }
  }else{
    clearBubbleImageStageShell(bubble, { remove:true });
    if(contentWrap) contentWrap.remove();
    if(hasDraftImageReplies || hasDraftFiles || hasDraftWeather){
      if(thinkingNode) thinkingNode.remove();
    }else if(processText){
      if(thinkingNode) thinkingNode.remove();
    }else if(!nextReasoningNode){
      if(!thinkingNode){
        thinkingNode = createThinkingNode(statusText || chatRenderT('stream.thinking', null, 'Thinking…'));
        body.appendChild(thinkingNode);
      }else{
        const txt = thinkingNode.querySelector('.thinking-text');
        if(txt) txt.textContent = statusText || chatRenderT('stream.thinking', null, 'Thinking…');
      }
    }else if(thinkingNode){
      thinkingNode.remove();
    }
  }

  const generatedFilesNode = syncAssistantGeneratedFilesInBody(body, _normalizePendingAssistantFiles(ensureSessionRuntime(sessionId)?.draftFiles || []));
  if(generatedFilesNode && thinkingNode) thinkingNode.remove();

  setBubbleProcessText(bubble, processText);
  bubble.dataset.draftStatusText = statusText;
  bubble.dataset.draftProcessText = processText;
  bubble.dataset.draftTextLength = String(visibleText.length || 0);
  if(enhancementChanged) bindBubbleEnhancements(bubble);
  syncStreamingCaretForBubble(bubble);
  return bubble;
}

function syncVisibleDraftBubble(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  if(isHomeLandingView) return null;
  if(String(store?.activeId || '').trim() !== sid) return null;
  if(String(visibleChatSessionId || '').trim() !== sid) return null;
  const rt = hydrateSessionRuntimeFromPendingSnapshot(sid);
  if(!sessionRuntimeDraftBelongsToCurrentTurn(sid, rt)){
    discardStaleSessionRuntimeDraft(sid, { immediate:true });
    return null;
  }
  if(sessionLastVisibleMessageIsAssistant(sid) && (pendingAssistantSnapshotForSession(sid, store) || String(getSessionPendingJobId(sid) || '').trim() || rt?.streaming || sessionRuntimeHasVisibleDraftContent(rt))){
    resetSessionTerminalRuntimeState(sid, { finalizeTimer:true });
    return null;
  }
  const shouldStickBottom = isNearBottom(140);
  const visibleText = String(rt.draftText || "").trim() ? rt.draftText : "";
  const statusText = String(rt.statusText || "").trim();
  const processText = String(rt.draftProcessText || "").trim();
  const draftImageReplies = _normalizePendingAssistantImageReplies(rt?.draftImageReplies || []);
  const draftFiles = _normalizePendingAssistantFiles(rt?.draftFiles || []);
  if(sessionLastVisibleMessageIsAssistant(sid) && !sessionRuntimeHasVisibleDraftContent(rt)){
    removeVisibleDraftBubbleForSession(sid);
    return null;
  }
  const draftMessage = draftImageReplies.length ? { role:'assistant', content:'', imageReplies:draftImageReplies, _useRuntimeDraftFiles:true } : null;
  let bubble = getVisibleDraftBubble(sid);
  if(!bubble){
    bubble = buildBubbleNode("assistant", visibleText, { statusText, sessionId: sid, processText, disableCopy:true, message:draftMessage, streamingDraft:true });
    chatEl.appendChild(bubble);
    bindBubbleEnhancements(bubble);
    dedupeAdjacentAssistantImageBubbles();
    bubble.dataset.sessionDraft = sid;
    liveDraftBubbleEls[sid] = bubble;
  }
  patchStreamingDraftBubble(bubble, { sessionId: sid, visibleText, statusText, processText });
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(sid); }catch(_){ }
  if(!bubble) return null;
  if(shouldStickBottom) chatEl.scrollTop = chatEl.scrollHeight;
  scrollChatToBottom(false);
  saveCurrentChatScrollState(sid);
  return bubble;
}

function finalizeVisibleDraftBubble(sessionId, opts={}){
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  const existing = getVisibleDraftBubble(sid);
  if(!existing) return null;

  const finalTextRaw = String(opts.finalText ?? '');
  const finalStatusText = String(opts.statusText || '').trim();
  const sources = mergeAssistantSourceItems(opts.sources || [], deriveAssistantCitationSources(sid, finalTextRaw));
  const webHit = !!opts.webHit;
  const fakeMessage = {
    role: 'assistant',
    content: finalTextRaw,
    webHit,
    sourceBound: !!sources.length || webHit,
  };
  const finalImageReplies = _normalizePendingAssistantImageReplies(opts.imageReplies || []);
  const finalGeneratedFiles = _normalizePendingAssistantFiles(opts.files || opts.generatedFiles || ensureSessionRuntime(sid)?.draftFiles || []);
  const finalWeatherPayload = normalizeAssistantWeatherPayload(opts.weatherPayload || opts.weather || ensureSessionRuntime(sid)?.draftWeatherPayload || null);
  if(finalImageReplies.length) fakeMessage.imageReplies = finalImageReplies;
  if(finalWeatherPayload) fakeMessage.weather = finalWeatherPayload;
  if(finalGeneratedFiles.length) fakeMessage.generatedFiles = finalGeneratedFiles;
  if(sources.length) fakeMessage.sources = sources;
  const finalGenerationUsage = normalizeAssistantUsagePayload(opts.generationUsage || opts.generation_usage || ensureSessionRuntime(sid)?.generationUsage || null);
  if(finalGenerationUsage){
    fakeMessage.generationUsage = finalGenerationUsage;
    fakeMessage.generation_usage = finalGenerationUsage;
  }
  try{
    const rtNow = ensureSessionRuntime(sid);
    const finalReasoning = _normalizePendingAssistantReasoning(rtNow?.reasoning || []);
    const finalReasoningMeta = _normalizePendingAssistantReasoningMeta(rtNow?.reasoningMeta || {});
    if(finalReasoning.length) fakeMessage.reasoning = finalReasoning;
    if(Object.keys(finalReasoningMeta).length) fakeMessage.reasoningMeta = finalReasoningMeta;
  }catch(_){ }

  const finalProcessText = String(opts.processText ?? ensureSessionRuntime(sid)?.draftProcessText ?? '').trim();
  if(finalProcessText){
    fakeMessage.fileProcessText = finalProcessText;
    fakeMessage.file_process_text = finalProcessText;
  }

  const replacement = buildBubbleNode('assistant', finalTextRaw, {
    sessionId: sid,
    message: fakeMessage,
    statusText: finalStatusText,
    processText: finalProcessText,
  });

  if(existing.dataset?.pendingAssistantRecovered) replacement.dataset.pendingAssistantRecovered = '1';
  existing.replaceWith(replacement);
  bindBubbleEnhancements(replacement);
  dedupeAdjacentAssistantImageBubbles();
  replacement.classList.remove('bubble-streaming');
  replacement.removeAttribute('data-session-draft');
  const caret = replacement.querySelector('.bubble-streaming-caret');
  if(caret) caret.remove();
  delete liveDraftBubbleEls[sid];
  return replacement;
}


function buildEmptyStateNode(){
  const wrap = document.createElement("div");
  wrap.className = "empty-state";

  const title = document.createElement("div");
  title.className = "empty-title no-mark";
  const temporarySession = getActiveTemporarySession();
  if(temporarySession){
    const tempStatus = document.createElement("button");
    tempStatus.type = "button";
    tempStatus.className = "empty-temporary-status";
    const temporaryLabel = window.AperviaI18n?.t('temporary.status_label') || 'Temporary conversation';
    const temporaryDesc = window.AperviaI18n?.t('temporary.status_desc') || 'This conversation will not appear in your history, and your messages will not be saved.';
    tempStatus.setAttribute("aria-label", `${temporaryLabel}: ${temporaryDesc}`);
    tempStatus.setAttribute("data-tooltip", temporaryDesc);
    tempStatus.innerHTML = `<span class="empty-temporary-status-icon" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"></path><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"></path><path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"></path><path d="M2 2l20 20"></path></svg></span><span>${escapeHtml(temporaryLabel)}</span>`;
    title.appendChild(tempStatus);
  }
  const model = document.createElement("div");
  model.className = "empty-logo-model";
  model.textContent = currentHomeLandingModel() || window.AperviaI18n?.t('home.no_model') || "未选择模型";
  title.appendChild(model);

  const suggestLabel = document.createElement("div");
  suggestLabel.className = "empty-suggest-label";
  suggestLabel.innerHTML = `<span class="empty-suggest-title"><span aria-hidden="true">⚡</span> ${escapeHtml(window.AperviaI18n?.t('home.suggestions') || '建议')}</span>`;

  const suggestionKinds = ['writing','code','file','learning','analysis','plan','image','data','translation','research','meeting','ideas'];
  const suggestions = suggestionKinds.map((kind) => [
    window.AperviaI18n?.t(`home.suggestion.${kind}.category`) || kind,
    window.AperviaI18n?.t(`home.suggestion.${kind}.prompt`) || '',
  ]);

  const carousel = document.createElement("div");
  carousel.className = "empty-suggest-carousel";
  const viewport = document.createElement("div");
  viewport.className = "empty-suggest-viewport";
  viewport.setAttribute("role", "region");
  viewport.setAttribute("aria-label", window.AperviaI18n?.t('home.suggestions_label') || "建议，可上下滑动切换");
  const track = document.createElement("div");
  track.className = "empty-suggest-track";

  const visibleCount = 3;
  const loopItems = [
    ...suggestions.slice(-visibleCount),
    ...suggestions,
    ...suggestions.slice(0, visibleCount),
  ];
  loopItems.forEach(([category, prompt]) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "empty-card empty-suggest-item";
    card.innerHTML = `<div class="k">${escapeHtml(category)}</div><div class="v">${escapeHtml(prompt)}</div>`;
    card.addEventListener("click", () => {
      quickAction(prompt);
      inputEl.focus();
    });
    track.appendChild(card);
  });
  viewport.appendChild(track);
  carousel.appendChild(viewport);

  const itemStep = 66;
  const firstRealIndex = visibleCount;
  const loopResetIndex = suggestions.length + visibleCount;
  let activeIndex = firstRealIndex;
  let autoTimer = null;
  let transitionTimer = null;
  let pointerId = null;
  let pointerStartY = 0;
  let pointerDeltaY = 0;
  let dragging = false;
  let transitioning = false;
  let suppressClick = false;
  let pointerInside = false;
  let focusInside = false;
  let wheelDelta = 0;
  let wheelResetTimer = null;
  const reduceMotion = !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  function scheduleSuggestionRotation(){
    if(autoTimer) clearTimeout(autoTimer);
    autoTimer = null;
    if(reduceMotion || pointerInside || focusInside || dragging) return;
    autoTimer = setTimeout(() => {
      if(!wrap.isConnected) return;
      moveSuggestions(1);
    }, 4800);
  }

  function updateSuggestionAccessibility(){
    Array.from(track.children).forEach((card, index) => {
      const visible = index >= activeIndex && index < activeIndex + visibleCount;
      card.setAttribute("aria-hidden", visible ? "false" : "true");
      card.tabIndex = visible ? 0 : -1;
    });
  }

  function applySuggestionPosition({ animate=true } = {}){
    if(transitionTimer) clearTimeout(transitionTimer);
    transitionTimer = null;
    track.classList.toggle("without-transition", !animate);
    track.classList.remove("is-dragging");
    track.style.transform = `translate3d(0,${-activeIndex * itemStep}px,0)`;
    transitioning = animate && !reduceMotion;
    updateSuggestionAccessibility();
    if(transitioning){
      transitionTimer = setTimeout(() => normalizeSuggestionLoop(), 420);
    }
    if(!animate){
      requestAnimationFrame(() => track.classList.remove("without-transition"));
    }
  }

  function normalizeSuggestionLoop(){
    if(transitionTimer) clearTimeout(transitionTimer);
    transitionTimer = null;
    if(activeIndex >= loopResetIndex){
      activeIndex = firstRealIndex;
      applySuggestionPosition({ animate:false });
    }else if(activeIndex <= 0){
      activeIndex = suggestions.length;
      applySuggestionPosition({ animate:false });
    }
    transitioning = false;
  }

  function moveSuggestions(direction){
    if(transitioning) return;
    activeIndex += direction < 0 ? -1 : 1;
    applySuggestionPosition({ animate:!reduceMotion });
    if(reduceMotion) normalizeSuggestionLoop();
    scheduleSuggestionRotation();
  }

  track.addEventListener("transitionend", (event) => {
    if(event.propertyName !== "transform") return;
    normalizeSuggestionLoop();
  });
  carousel.addEventListener("mouseenter", () => {
    pointerInside = true;
    if(autoTimer) clearTimeout(autoTimer);
  });
  carousel.addEventListener("mouseleave", () => {
    pointerInside = false;
    scheduleSuggestionRotation();
  });
  carousel.addEventListener("focusin", () => {
    focusInside = true;
    if(autoTimer) clearTimeout(autoTimer);
  });
  carousel.addEventListener("focusout", (event) => {
    if(carousel.contains(event.relatedTarget)) return;
    focusInside = false;
    scheduleSuggestionRotation();
  });

  viewport.addEventListener("pointerdown", (event) => {
    if(transitioning || (event.pointerType === "mouse" && event.button !== 0)) return;
    pointerId = event.pointerId;
    pointerStartY = event.clientY;
    pointerDeltaY = 0;
    dragging = true;
    suppressClick = false;
    track.classList.add("is-dragging");
    viewport.classList.add("is-dragging");
    viewport.setPointerCapture?.(pointerId);
    if(autoTimer) clearTimeout(autoTimer);
  }, true);
  viewport.addEventListener("pointermove", (event) => {
    if(!dragging || event.pointerId !== pointerId) return;
    pointerDeltaY = event.clientY - pointerStartY;
    if(Math.abs(pointerDeltaY) > 7){
      suppressClick = true;
      event.preventDefault();
    }
    const limitedDelta = Math.max(-itemStep * 1.15, Math.min(itemStep * 1.15, pointerDeltaY));
    track.style.transform = `translate3d(0,${(-activeIndex * itemStep) + limitedDelta}px,0)`;
  }, true);
  const finishSuggestionDrag = (event) => {
    if(!dragging || (event?.pointerId != null && event.pointerId !== pointerId)) return;
    const threshold = 24;
    dragging = false;
    viewport.classList.remove("is-dragging");
    try{ viewport.releasePointerCapture?.(pointerId); }catch(_){ }
    pointerId = null;
    if(pointerDeltaY <= -threshold) moveSuggestions(1);
    else if(pointerDeltaY >= threshold) moveSuggestions(-1);
    else{
      applySuggestionPosition({ animate:!reduceMotion });
      if(reduceMotion) transitioning = false;
      scheduleSuggestionRotation();
    }
    pointerDeltaY = 0;
    if(suppressClick) setTimeout(() => { suppressClick = false; }, 0);
  };
  viewport.addEventListener("pointerup", finishSuggestionDrag, true);
  viewport.addEventListener("pointercancel", finishSuggestionDrag, true);
  viewport.addEventListener("dragstart", (event) => event.preventDefault());
  viewport.addEventListener("wheel", (event) => {
    if(Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
    event.preventDefault();
    if(wheelResetTimer) clearTimeout(wheelResetTimer);
    wheelDelta += event.deltaY;
    wheelResetTimer = setTimeout(() => { wheelDelta = 0; }, 140);
    if(transitioning || Math.abs(wheelDelta) < 18) return;
    const direction = wheelDelta > 0 ? 1 : -1;
    wheelDelta = 0;
    moveSuggestions(direction);
  }, { passive:false });
  carousel.addEventListener("keydown", (event) => {
    if(event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    moveSuggestions(event.key === "ArrowDown" ? 1 : -1);
  });
  viewport.addEventListener("click", (event) => {
    if(!suppressClick) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  applySuggestionPosition({ animate:false });
  scheduleSuggestionRotation();

  wrap.appendChild(title);
  wrap.appendChild(suggestLabel);
  wrap.appendChild(carousel);
  return wrap;
}

function buildChatCenterLoadingNode(){
  const wrap = document.createElement("div");
  wrap.className = "chat-center-loading";
  wrap.dataset.centerLoading = "1";
  wrap.setAttribute("aria-busy", "true");
  wrap.setAttribute("aria-live", "polite");
  const loadingLabel=chatRenderT('chat.loading_conversation',null,'Loading conversation');
  wrap.setAttribute('aria-label',loadingLabel);
  const skeleton = (typeof AppLoadingUi !== 'undefined' && typeof AppLoadingUi.create === 'function')
    ? AppLoadingUi.create({variant:'chat',rows:3,label:loadingLabel})
    : null;
  if(skeleton){
    wrap.appendChild(skeleton);
    return wrap;
  }
  const spinner = document.createElement("span");
  spinner.className = "chat-center-spinner";
  spinner.setAttribute("aria-hidden", "true");
  wrap.appendChild(spinner);
  return wrap;
}

function chatHasVisibleContentForCenterLoading(){
  try{
    return Array.from(chatEl?.children || []).some(node => {
      if(!node || node.dataset?.centerLoading === "1") return false;
      return true;
    });
  }catch(_){
    return false;
  }
}

function shouldShowChatCenterLoadingForSession(session){
  const s = session && typeof session === "object" ? session : getActive();
  const sid = String(s?.id || store?.activeId || '').trim();
  if(!sid || isHomeLandingView || !store?.sessions?.[sid]) return false;
  const currentSession = store.sessions[sid];
  if(chatCenterLoadingForceCount > 0) return true;
  try{ if(isCloudSessionStub(currentSession)) return true; }catch(_){}
  try{ if(sessionNeedsCloudHydrate(currentSession) && !sessionHasMeaningfulConversation(currentSession)) return true; }catch(_){}
  return false;
}

function syncChatCenterLoading(){
  if(!chatEl) return;
  const existing = chatEl.querySelector(':scope > .chat-center-loading');
  if(chatHasVisibleContentForCenterLoading()){
    if(existing) existing.remove();
    return;
  }
  if(shouldShowChatCenterLoadingForSession(getActive())){
    if(!existing) chatEl.appendChild(buildChatCenterLoadingNode());
  }else if(existing){
    existing.remove();
  }
}

function setChatCenterLoadingForced(enabled){
  chatCenterLoadingForceCount = Math.max(0, chatCenterLoadingForceCount + (enabled ? 1 : -1));
  syncChatCenterLoading();
}

function scrollChatToBottom(force=false){
  if(force) chatEl.scrollTop = chatEl.scrollHeight;
  const delta = chatEl.scrollHeight - chatEl.clientHeight - chatEl.scrollTop;
  scrollBottomBtn?.classList.toggle("show", delta > 180);
}

function captureChatScrollState(){
  return {
    nearBottom: isNearBottom(140),
    deltaFromBottom: chatEl.scrollHeight - chatEl.clientHeight - chatEl.scrollTop,
    top: chatEl.scrollTop,
  };
}

function restoreChatScrollState(state){
  if(!state) return;
  if(state.nearBottom){
    chatEl.scrollTop = chatEl.scrollHeight;
    return;
  }
  const maxTop = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
  chatEl.scrollTop = Math.max(0, Math.min(state.top, maxTop));
}

let homeEmptyComposerOriginalParent = null;
let homeEmptyComposerOriginalNextSibling = null;

function mountComposerIntoHomeEmpty(){
  try{
    const composerEl = document.querySelector(".composer");
    const emptyStateEl = chatEl?.querySelector(".empty-state");
    if(!composerEl || !emptyStateEl) return;
    if(!homeEmptyComposerOriginalParent){
      homeEmptyComposerOriginalParent = composerEl.parentNode || null;
      homeEmptyComposerOriginalNextSibling = composerEl.nextSibling || null;
    }
    const suggestLabelEl = emptyStateEl.querySelector(".empty-suggest-label");
    if(composerEl.parentNode === emptyStateEl && suggestLabelEl && composerEl.nextSibling === suggestLabelEl) return;
    emptyStateEl.insertBefore(composerEl, suggestLabelEl || null);
  }catch(_err){}
}

function restoreComposerFromHomeEmpty(){
  try{
    const composerEl = document.querySelector(".composer");
    if(!composerEl || !homeEmptyComposerOriginalParent) return;
    if(composerEl.parentNode === homeEmptyComposerOriginalParent) return;
    homeEmptyComposerOriginalParent.insertBefore(composerEl, homeEmptyComposerOriginalNextSibling || null);
  }catch(_err){}
}

function updateHomeEmptyComposerLayout(){
  try{
    const root = document.documentElement;
    const isHomeEmpty = document.body.classList.contains("home-empty") && mainEl?.classList.contains("home-empty");
    root.style.removeProperty("--home-empty-composer-top");
    root.style.removeProperty("--home-empty-suggest-gap");
    if(!isHomeEmpty){
      restoreComposerFromHomeEmpty();
      updateComposerBottomSpace();
      return;
    }
    mountComposerIntoHomeEmpty();
    updateComposerBottomSpace();
  }catch(_err){}
}

let _lastChatRenderSignature = "";
function chatRenderLightFingerprint(value, limit = 900){
  const maxLen = Math.max(120, Number(limit || 900) || 900);
  if(value == null) return '';
  if(typeof value === 'string'){
    const s = value;
    if(s.length <= maxLen) return `str:${s.length}:${s}`;
    return `str:${s.length}:${s.slice(0, Math.floor(maxLen / 2))}:${s.slice(-Math.floor(maxLen / 2))}`;
  }
  if(typeof value === 'number' || typeof value === 'boolean') return String(value);
  if(Array.isArray(value)){
    return value.slice(0, 48).map((item)=>chatRenderLightFingerprint(item, Math.max(80, Math.floor(maxLen / 8)))).join('|');
  }
  if(value && typeof value === 'object'){
    const kind = String(value._kind || value.kind || value.type || '').trim();
    if(kind === 'image_reply'){
      const imgs = Array.isArray(value.images) ? value.images : [];
      return JSON.stringify({
        kind,
        text: chatRenderLightFingerprint(value.text || value.answer || '', 260),
        operation: String(value.operation || value.task_mode || ''),
        count: imgs.length,
        images: imgs.slice(0, 12).map((img)=>([
          String(img?.url || img?.view_url || img?.preview_url || img?.raw_url || '').slice(0, 260),
          String(img?.filename || '').slice(0, 120),
          String(img?.source_type || img?.operation || '').slice(0, 80),
        ].join('~'))),
      });
    }
    if(kind === 'file' || kind === 'image'){
      return JSON.stringify({
        kind,
        id: String(value.id || value.file_id || '').slice(0, 120),
        filename: String(value.filename || value.name || '').slice(0, 160),
        url: String(value.url || value.view_url || value.download_url || '').slice(0, 260),
        status: String(value.status || '').slice(0, 80),
      });
    }
    if(kind === 'weather' || (value.location && value.current)){
      return JSON.stringify({
        kind: kind || 'weather',
        location: value.location || '',
        current: value.current || null,
        updated_at: value.updated_at || value.created_at || '',
      }).slice(0, maxLen);
    }
    const compact = {};
    for(const key of ['_kind','type','role','text','answer','title','status','error','id','filename','url','view_url','download_url','created_at_ms','createdAtMs','updatedAt']){
      if(Object.prototype.hasOwnProperty.call(value, key)) compact[key] = value[key];
    }
    try{
      const raw = JSON.stringify(Object.keys(compact).length ? compact : value);
      if(raw.length <= maxLen) return raw;
      return `${raw.length}:${raw.slice(0, Math.floor(maxLen / 2))}:${raw.slice(-Math.floor(maxLen / 2))}`;
    }catch(_){
      return String(kind || Object.prototype.toString.call(value));
    }
  }
  return String(value);
}

function buildChatRenderSignature(session, homeView, sessionId){
  try{
    const sid = String(sessionId || '').trim();
    if(homeView){
      return JSON.stringify({
        home: true,
        sid,
        model: String(currentHomeLandingModel() || ''),
        // Do not include live composer text in the home render signature.
        // Background account/cloud refresh may call renderAll while the user is typing;
        // if the draft text is part of this signature, the home screen is torn down
        // and rebuilt mid-input, causing visible flashing and focus/input jank.
        quote: chatRenderLightFingerprint(homeQuoteDraft || null, 360),
        temporary: !!getActiveTemporarySession(),
        katex: !!window.__webaiKatexReady,
      });
    }
    const s = session && typeof session === 'object' ? session : null;
    if(!s) return JSON.stringify({ home:false, sid, empty:true });
    const msgs = (Array.isArray(s.messages) ? s.messages : [])
      .filter(m => m && m.role !== 'system')
      .map((m, idx)=>([
        idx,
        String(m.role || ''),
        String(m._kind || ''),
        chatRenderLightFingerprint(m.content, 900),
        chatRenderLightFingerprint({ file_attachments:m.file_attachments || [], attachments:m.attachments || [], composer_file_attachments:m._composer_file_attachments || [] }, 700),
        chatRenderLightFingerprint({ imageReplies:m.imageReplies || [], image_replies:m.image_replies || [] }, 900),
        String(m.id || m.message_id || '').slice(0, 120),
        chatRenderLightFingerprint({ reasoning:m.reasoning || [], reasoningMeta:m.reasoningMeta || {} }, 900),
        chatRenderLightFingerprint({ generationUsage:m.generationUsage || m.generation_usage || m.usage || null }, 500),
        String(m.runtimeModel || m.runtime_model || m.model || m.modelName || m.model_name || '').slice(0, 160),
      ].join('\u001e')));
    const rt = ensureSessionRuntime(s.id);
    const activeInlineEdit = getActiveInlineEditState(s);
    const pending = pendingAssistantSnapshotForSession(s.id, store);
    const backendErrorPayload = getSessionBackendErrorPayload(s);
    return JSON.stringify({
      home: false,
      sid: String(s.id || sid),
      title: String(s.title || ''),
      model: String(s.model || ''),
      temporary: isTemporarySession(s),
      archived: isSessionArchived(s),
      messageCount: msgs.length,
      messages: msgs,
      streaming: !!rt.streaming,
      pending: chatRenderLightFingerprint(pending || null, 1200),
      backendError: chatRenderLightFingerprint(backendErrorPayload || null, 700),
      inlineEdit: activeInlineEdit ? chatRenderLightFingerprint({
        targetIndex: activeInlineEdit.targetIndex,
        cutFrom: activeInlineEdit.cutFrom,
        attachmentIndexes: activeInlineEdit.attachmentIndexes || [],
        skipIndexes: activeInlineEdit.skipIndexes || [],
      }, 700) : '',
      katex: !!window.__webaiKatexReady,
    });
  }catch(_){
    return '';
  }
}

function invalidateChatRenderCache(){
  _lastChatRenderSignature = "";
}

function captureActiveChatVisualState(){
  try{
    const homeView = !!isHomeLandingView;
    const session = homeView ? null : getActive();
    const sid = homeView ? HOME_LANDING_VIRTUAL_ID : String(session?.id || store?.activeId || '').trim();
    return {
      homeView,
      sid,
      visibleSid: String(visibleChatSessionId || '').trim(),
      signature: buildChatRenderSignature(session, homeView, sid),
      hasVisibleContent: chatHasVisibleContentForCenterLoading(),
      scroll: sid ? saveCurrentChatScrollState(sid) : null,
    };
  }catch(_){
    return null;
  }
}

function activeChatVisualStillSame(snapshot){
  try{
    if(!snapshot || !snapshot.signature) return false;
    const homeView = !!isHomeLandingView;
    const session = homeView ? null : getActive();
    const sid = homeView ? HOME_LANDING_VIRTUAL_ID : String(session?.id || store?.activeId || '').trim();
    if(String(snapshot.sid || '').trim() !== String(sid || '').trim()) return false;
    if(String(visibleChatSessionId || '').trim() !== String(snapshot.visibleSid || snapshot.sid || '').trim()) return false;
    const nextSignature = buildChatRenderSignature(session, homeView, sid);
    return !!nextSignature && nextSignature === snapshot.signature && chatHasVisibleContentForCenterLoading();
  }catch(_){
    return false;
  }
}

function renderCloudSyncAppliedUi(snapshot=null, opts={}){
  const o = opts || {};
  if(activeChatVisualStillSame(snapshot)){
    // Cloud/account sync may update sidebar metadata while the open chat content is
    // byte-for-byte the same.  Do not touch the chat DOM in that case: keeping the
    // existing message nodes prevents the public site from visually flashing.
    try{ renderList({ preserveScroll:true }); }catch(_){ renderList(); }
    refreshComposerEditBar();
    refreshArchivedComposerState();
    refreshStatusForActiveSession();
    if(o.restoreComposer !== false) restoreComposerDraft(store.activeId);
    if(snapshot?.scroll){
      requestAnimationFrame(()=>{
        try{
          const sid = String(snapshot.sid || '').trim();
          if(sid && String(store?.activeId || '').trim() === sid) restoreChatScrollState(snapshot.scroll);
        }catch(_){ }
      });
    }
    return false;
  }
  safeRenderAll();
  return true;
}

function captureInlineMessageEditFocusSnapshot(session){
  try{
    const activeState = getActiveInlineEditState(session);
    if(!activeState) return null;
    const el = document.activeElement;
    if(!el || !el.classList || !el.classList.contains('inline-message-edit-input')) return null;
    const bubble = el.closest?.('.inline-message-edit-bubble');
    const targetIndex = Number(bubble?.dataset?.msgIndex || activeState.targetIndex);
    return {
      targetIndex,
      selectionStart: Number.isFinite(el.selectionStart) ? el.selectionStart : null,
      selectionEnd: Number.isFinite(el.selectionEnd) ? el.selectionEnd : null,
      scrollTop: Number(el.scrollTop || 0) || 0,
    };
  }catch(_){
    return null;
  }
}

function restoreInlineMessageEditFocusSnapshot(snapshot){
  if(!snapshot) return;
  requestAnimationFrame(()=>{
    try{
      const targetIndex = Number(snapshot.targetIndex);
      if(!Number.isInteger(targetIndex)) return;
      const editor = chatEl?.querySelector?.(`.inline-message-edit-bubble[data-msg-index="${targetIndex}"]`);
      const textarea = editor?.querySelector?.('.inline-message-edit-input');
      if(!textarea) return;
      textarea.focus({ preventScroll:true });
      const valueLen = String(textarea.value || '').length;
      const start = Number.isFinite(snapshot.selectionStart) ? Math.max(0, Math.min(Number(snapshot.selectionStart), valueLen)) : valueLen;
      const end = Number.isFinite(snapshot.selectionEnd) ? Math.max(0, Math.min(Number(snapshot.selectionEnd), valueLen)) : start;
      try{ textarea.selectionStart = start; textarea.selectionEnd = end; }catch(_){ }
      try{ textarea.scrollTop = Number(snapshot.scrollTop || 0) || 0; }catch(_){ }
    }catch(_){ }
  });
}

function renderChat(){
  const s = getActive();
  try{
    if(s && webaiOfficialNormalizeActiveSession(s, { skipIfLive:true })){
      store.sessions[s.id] = s;
      saveStoreLocalOnlyThrottled();
    }
  }catch(_){ }
  const homeView = !!isHomeLandingView;
  const nextSessionId = homeView ? HOME_LANDING_VIRTUAL_ID : (s?.id || null);
  const nextChatSignature = buildChatRenderSignature(s, homeView, nextSessionId);
  if(nextChatSignature && nextChatSignature === _lastChatRenderSignature && visibleChatSessionId === nextSessionId && chatHasVisibleContentForCenterLoading()){
    const showingEmptyState = !!chatEl.querySelector(':scope > .empty-state');
    if(homeView || showingEmptyState){
      document.body.classList.add("home-empty");
      mainEl.classList.add("home-empty");
      requestAnimationFrame(updateHomeEmptyComposerLayout);
    }else{
      document.body.classList.remove("home-empty");
      mainEl.classList.remove("home-empty");
      updateHomeEmptyComposerLayout();
    }
    refreshArchivedComposerState();
    refreshRegenerateActionsForVisibleSession(nextSessionId);
    try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(nextSessionId); }catch(_){ }
    scrollChatToBottom(false);
    acknowledgeVisibleSessionUnread(nextSessionId, { render:true });
    return;
  }
  _lastChatRenderSignature = nextChatSignature || "";
  const sameSession = visibleChatSessionId === nextSessionId;
  const prevScroll = sameSession ? saveCurrentChatScrollState(nextSessionId) : null;
  const inlineEditFocusSnapshot = sameSession ? captureInlineMessageEditFocusSnapshot(s) : null;

  if(!homeView && sameSession && isCloudSessionStub(s) && chatHasVisibleContentForCenterLoading()){
    document.body.classList.remove("home-empty");
    mainEl.classList.remove("home-empty");
    updateHomeEmptyComposerLayout();
    setStatus(chatRenderT('chat.updating_conversation',null,'Updating current conversation…'));
    hydrateActiveSessionAfterSwitch(s.id,{force:true,statusText:chatRenderT('chat.conversation_loaded',null,'Current conversation loaded')}).catch(()=>{});
    refreshArchivedComposerState();
    return;
  }

  visibleChatSessionId = nextSessionId;
  restoreComposerFromHomeEmpty();
  chatEl.innerHTML = "";
  Object.keys(liveDraftBubbleEls).forEach(k=>{ if(!liveDraftBubbleEls[k]?.isConnected) delete liveDraftBubbleEls[k]; });

  if(!homeView && isCloudSessionStub(s)){
    document.body.classList.remove("home-empty");
    mainEl.classList.remove("home-empty");
    updateHomeEmptyComposerLayout();
    chatEl.appendChild(buildChatCenterLoadingNode());
    setStatus(chatRenderT('chat.loading_current_conversation',null,'Loading current conversation…'));
    hydrateActiveSessionAfterSwitch(s.id,{force:true,statusText:chatRenderT('chat.conversation_loaded',null,'Current conversation loaded')}).catch(()=>{});
    refreshArchivedComposerState();
    return;
  }

  const visibleMsgs = (s.messages || []).filter(m => m && m.role !== "system");
  const hasPendingSnapshot = homeView ? false : !!pendingAssistantSnapshotForSession(s.id, store);
  const backendErrorPayload = homeView ? null : getSessionBackendErrorPayload(s);
  const hasBackendError = !!(backendErrorPayload && backendErrorPayload.text);
  if(homeView || (!visibleMsgs.length && !ensureSessionRuntime(s.id).streaming && !hasPendingSnapshot && !hasBackendError)){
    document.body.classList.add("home-empty");
    mainEl.classList.add("home-empty");
    chatEl.appendChild(buildEmptyStateNode());
    requestAnimationFrame(updateHomeEmptyComposerLayout);
    if(prevScroll) restoreChatScrollState(prevScroll);
    else chatEl.scrollTop = chatEl.scrollHeight;
    refreshArchivedComposerState();
    scrollChatToBottom(false);
    return;
  }

  document.body.classList.remove("home-empty");
  mainEl.classList.remove("home-empty");
  updateHomeEmptyComposerLayout();
  if(homeView) return;

  const rawVisibleEntries = (s.messages || []).map((m, idx)=>({ m, idx })).filter(x => x.m && x.m.role !== "system");
  const visibleEntries = [];
  let prevRenderedMessage = null;
  for(const entry of rawVisibleEntries){
    const lastVisibleMessage = visibleEntries.length ? visibleEntries[visibleEntries.length - 1].m : prevRenderedMessage;
    if(isGeneratedImageOnlyOrphanReasoningMessage(entry.m, lastVisibleMessage)){
      continue;
    }
    if(visibleMessagesAreDuplicateNeighbors(prevRenderedMessage, entry.m)){
      const lastEntry = visibleEntries[visibleEntries.length - 1];
      if(lastEntry && assistantMessagesHaveSameVisibleText(lastEntry.m, entry.m)){
        const mergedMessage = cloneStoreDeep(lastEntry.m || {}) || { ...(lastEntry.m || {}) };
        mergeAssistantMessageMetadata(mergedMessage, entry.m);
        lastEntry.m = mergedMessage;
        prevRenderedMessage = mergedMessage;
      }
      continue;
    }
    visibleEntries.push(entry);
    prevRenderedMessage = entry.m;
  }
  const activeInlineEdit = getActiveInlineEditState(s);
  const inlineSkipIndexes = new Set(Array.isArray(activeInlineEdit?.skipIndexes) ? activeInlineEdit.skipIndexes : []);
  for(const entry of visibleEntries){
    const m = entry.m;
    const originalIndex = entry.idx;
    if(m.role === "system") continue;
    if(m && (m._image_context_only || m._pending_stream_image_reply)) continue;
    if(inlineSkipIndexes.has(originalIndex)) continue;
    if(activeInlineEdit && Number(activeInlineEdit.targetIndex) === originalIndex){
      chatEl.appendChild(buildInlineUserEditNode(s, activeInlineEdit));
      continue;
    }

    if(typeof m.content === "object" && m.content && (m.content._kind === "file" || m.content._kind === "image")){
      addAttachmentBubble(m.role, m.content, false, { messageIndex: originalIndex, message:m });
      continue;
    }

    if(typeof m.content === "object" && m.content && m.content._kind === "genfiles"){
      const bubble = buildBubbleNode('assistant', '', { sessionId:s.id, message:m, messageIndex:originalIndex, disableCopy:true });
      chatEl.appendChild(bubble);
      bindBubbleEnhancements(bubble);
      continue;
    }

    if(typeof m.content === "object" && m.content && m.content._kind === "memory_event"){
      addMemoryEventBubble(m.content);
      continue;
    }

    if(typeof m.content === "object" && m.content && m.content._kind === "image_reply"){
      addImageReplyBubble(m.content, { messageIndex: originalIndex, message:m, sessionId:s.id });
      continue;
    }

    if(typeof m.content === "object" && m.content && (m.content._kind === "weather" || (m.content.location && m.content.current && (Array.isArray(m.content.hourly) || Array.isArray(m.content.daily))))){
      addWeatherBubble(m.content);
      continue;
    }

    const userFiles = m.role === 'user' ? getUserMessageInlineFileAttachments(m) : [];
    if(m.role === 'user' && !Array.isArray(m.content) && userFiles.length){
      renderUserMessageAttachmentGroup(chatEl, m, [], originalIndex);
    }
    if(m.role === 'user' && userFiles.length > 0 && !bubbleMessageTextForComposer(m) && bubbleMessageImageCountForComposer(m) <= 0 && !Array.isArray(m.content) && !(m.content && typeof m.content === 'object')){
      continue;
    }

    if(Array.isArray(m.content)){
      const userSplit = m.role === 'user' ? splitMixedUserStructuredContent(m.content) : { hasMixed:false, textParts:[], imageParts:[], otherParts:[] };
      if(m.role === 'user' && userSplit.imageParts.length > 0 && !userSplit.textParts.length && !userSplit.otherParts.length){
        const imageBubble = buildBubbleNode(m.role, "", { sessionId:s.id, message:m, messageIndex:originalIndex, disableCopy:true, hideHeader:true, suppressQuote:true, splitPart:'image' });
        imageBubble.classList.add('bubble-image-only');
        const imageBody = imageBubble.querySelector(".bubble-body");
        chatEl.appendChild(imageBubble);

        const renderedPromise = userFiles.length
          ? Promise.resolve(!!renderUserMessageAttachmentGroup(imageBody, m, userSplit.imageParts, originalIndex))
          : Promise.resolve(renderStructuredMessageContent(imageBody, userSplit.imageParts));
        renderedPromise.then((rendered)=>{
          if(!rendered){
            imageBubble.remove();
            return;
          }
          bindBubbleEnhancements(imageBubble);
          dedupeAdjacentAssistantImageBubbles();
        }).catch(()=>{
          imageBubble.remove();
        });
        continue;
      }

      if(m.role === 'user' && userSplit.hasMixed && !userSplit.otherParts.length){
        const splitGroupId = `mixed_${originalIndex}`;
        const turnGroup = document.createElement('div');
        turnGroup.className = 'user-mixed-turn-group';
        turnGroup.dataset.splitGroupId = splitGroupId;

        const textValue = userSplit.textParts.map(part => String(part?.text || '')).filter(Boolean).join('\n').trim();
        const imageBubble = buildBubbleNode(m.role, "", { sessionId:s.id, message:m, messageIndex:originalIndex, disableCopy:true, hideHeader:true, suppressQuote:true, splitGroupId, splitPart:'image' });
        imageBubble.classList.add('bubble-image-only');
        const imageBody = imageBubble.querySelector(".bubble-body");
        turnGroup.appendChild(imageBubble);

        if(textValue){
          const textBubble = buildBubbleNode(m.role, textValue, { sessionId:s.id, message:m, messageIndex:originalIndex, splitGroupId, splitPart:'text' });
          turnGroup.appendChild(textBubble);
          bindBubbleEnhancements(textBubble);
        }

        chatEl.appendChild(turnGroup);

        const renderedPromise = userFiles.length
          ? Promise.resolve(!!renderUserMessageAttachmentGroup(imageBody, m, userSplit.imageParts, originalIndex))
          : Promise.resolve(renderStructuredMessageContent(imageBody, userSplit.imageParts));
        renderedPromise.then((rendered)=>{
          if(!rendered){
            imageBubble.remove();
            if(!turnGroup.childElementCount) turnGroup.remove();
            return;
          }
          bindBubbleEnhancements(imageBubble);
          dedupeAdjacentAssistantImageBubbles();
        }).catch(()=>{
          imageBubble.remove();
          if(!turnGroup.childElementCount) turnGroup.remove();
        });
        continue;
      }

      if(m.role === 'user' && userFiles.length){
        renderUserMessageAttachmentGroup(chatEl, m, userSplit.imageParts, originalIndex);
      }
      const bubble = buildBubbleNode(m.role, "", { sessionId:s.id, message:m, messageIndex:originalIndex, disableCopy:true });
      const body = bubble.querySelector(".bubble-body");
      chatEl.appendChild(bubble);
      const contentForBubble = m.role === 'user' && userFiles.length
        ? m.content.filter(part => !isStructuredImagePartLike(part))
        : m.content;
      Promise.resolve(renderStructuredMessageContent(body, contentForBubble)).then((rendered)=>{
        if(!rendered){
          bubble.remove();
          return;
        }
        if(m.role === 'user') injectMessageQuoteIntoBubble(bubble, m);
        bindBubbleEnhancements(bubble);
        dedupeAdjacentAssistantImageBubbles();
      }).catch(()=>{
        bubble.remove();
      });
      continue;
    }

    chatEl.appendChild(buildBubbleNode(m.role, String(m.content ?? ""), { sessionId:s.id, message:m, messageIndex:originalIndex }));
    bindBubbleEnhancements(chatEl.lastChild);
    dedupeAdjacentAssistantImageBubbles();
  }

  dedupeAdjacentAssistantImageBubbles();

  let rt = hydrateSessionRuntimeFromPendingSnapshot(s.id, { store });
  let pendingSnapshot = pendingAssistantSnapshotForSession(s.id, store);
  const hasAssistantContinuationTarget = sessionRuntimeHasAssistantContinuationTarget(rt);
  if(!sessionRuntimeDraftBelongsToCurrentTurn(s.id, rt)){
    discardStaleSessionRuntimeDraft(s.id, { immediate:true });
    rt = ensureSessionRuntime(s.id);
    pendingSnapshot = null;
  }
  const hasStalePendingAfterAssistant = !hasAssistantContinuationTarget && sessionLastVisibleMessageIsAssistant(s.id) && !!(
    pendingSnapshot
    || String(getSessionPendingJobId(s.id) || '').trim()
    || rt?.streaming
    || sessionRuntimeHasVisibleDraftContent(rt)
  );
  let suppressDuplicatePendingAssistant = hasStalePendingAfterAssistant || (!hasAssistantContinuationTarget && pendingAssistantDuplicatesLastAssistant(s.id, pendingSnapshot, rt));
  if(suppressDuplicatePendingAssistant){
    resetSessionTerminalRuntimeState(s.id, { finalizeTimer:true });
    rt = ensureSessionRuntime(s.id);
    pendingSnapshot = null;
  }
  const pendingImageReplies = suppressDuplicatePendingAssistant ? [] : _normalizePendingAssistantImageReplies([
    ...(Array.isArray(rt?.draftImageReplies) ? rt.draftImageReplies : []),
    ...(Array.isArray(pendingSnapshot?.imageReplies) ? pendingSnapshot.imageReplies : []),
  ]);
  const pendingStandaloneImageReplies = pendingImageReplies.filter(item => !isImageSearchReplyPayload(item));
  if(pendingStandaloneImageReplies.length){
    for(const item of pendingStandaloneImageReplies){
      addImageReplyBubble(item, { sessionId:s.id });
    }
    dedupeAdjacentAssistantImageBubbles();
  }
  if(rt.streaming && !hasAssistantContinuationTarget){
    const streamingDraftText = String(rt.draftText || '');
    const streamingStatusText = String(rt.statusText || pendingSnapshot?.status || '');
    const streamingProcessText = String(rt.draftProcessText || pendingSnapshot?.process || '');
    const streamingImageReplies = pendingImageReplies.filter(isImageSearchReplyPayload);
    const streamingStandaloneImageReplies = pendingImageReplies.filter(item => !isImageSearchReplyPayload(item));
    const streamingFiles = Array.isArray(rt?.draftFiles) ? rt.draftFiles : (Array.isArray(pendingSnapshot?.files) ? pendingSnapshot.files : []);
    const streamingWeatherPayload = normalizeAssistantWeatherPayload(rt?.draftWeatherPayload || pendingSnapshot?.weatherPayload || null);
    const streamingReasoning = _normalizePendingAssistantReasoning([
      ...(Array.isArray(rt?.reasoning) ? rt.reasoning : []),
      ...(Array.isArray(pendingSnapshot?.reasoning) ? pendingSnapshot.reasoning : []),
    ]);
    const hasStreamingVisibleDraftContent = !!(
      streamingDraftText.trim()
      || streamingProcessText.trim()
      || streamingImageReplies.length
      || normalizeAssistantWeatherPayload(rt?.draftWeatherPayload || pendingSnapshot?.weatherPayload || null)
      || streamingFiles.length
      || streamingReasoning.length
    );
    const shouldRenderStreamingDraftBubble = !!(
      hasStreamingVisibleDraftContent
      || (!streamingStandaloneImageReplies.length && !sessionLastVisibleMessageIsAssistant(s.id))
    );
    if(shouldRenderStreamingDraftBubble){
      const draftMessage = (streamingImageReplies.length || streamingWeatherPayload) ? { role:'assistant', content:'', imageReplies:streamingImageReplies, weather:streamingWeatherPayload, _useRuntimeDraftFiles:true } : null;
      const draftBubble = buildBubbleNode('assistant', streamingDraftText, {
        sessionId: s.id,
        statusText: streamingStatusText,
        processText: streamingProcessText,
        disableCopy: true,
        message: draftMessage,
        streamingDraft: true,
      });
      chatEl.appendChild(draftBubble);
      bindBubbleEnhancements(draftBubble);
      dedupeAdjacentAssistantImageBubbles();
      draftBubble.dataset.sessionDraft = s.id;
      if(pendingSnapshot?.streaming) draftBubble.dataset.pendingAssistantRecovered = '1';
      liveDraftBubbleEls[s.id] = draftBubble;
      patchStreamingDraftBubble(draftBubble, {
        sessionId: s.id,
        visibleText: streamingDraftText,
        statusText: streamingStatusText,
        processText: streamingProcessText,
      });
      const headMeta = draftBubble.querySelector('.bubble-head .hint');
      if(headMeta && pendingSnapshot?.streaming && !streamingDraftText.trim()){
        headMeta.textContent=String(streamingStatusText||pendingSnapshot.status||chatRenderT('chat.waiting_response',null,'Waiting for a response…'));
      }
    }
  }else if(pendingSnapshot){
    try{ clearPendingAssistantSnapshot(s.id, { immediate:true }); }catch(_){ }
  }

  if(!chatEl.childElementCount && shouldShowChatCenterLoadingForSession(s)){
    chatEl.appendChild(buildChatCenterLoadingNode());
  }

  restorePinnedQuoteHighlightForActiveSession();
  if(prevScroll) restoreChatScrollState(prevScroll);
  else chatEl.scrollTop = chatEl.scrollHeight;
  restoreInlineMessageEditFocusSnapshot(inlineEditFocusSnapshot);
  refreshArchivedComposerState();
  refreshRegenerateActionsForVisibleSession(s.id);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(s.id); }catch(_){ }
  scrollChatToBottom(false);
  acknowledgeVisibleSessionUnread(s.id, { render:true });
}

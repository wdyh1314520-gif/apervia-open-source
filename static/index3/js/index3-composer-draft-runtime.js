/* Product frontend module.
 * Purpose: Composer attachment draft persistence and durable attachment-source normalization.
 * Loaded before index3.js; classic-script globals preserve the existing single runtime.
 */

let pastedImages = [];
const composerLocalImageFileMap = new Map();
function _normalizeComposerImageLocalCacheRecord(value){
  if(value instanceof File) return { file:value, dataUrl:'', previewUrl:'' };
  if(value && typeof value === 'object'){
    return {
      file: value.file instanceof File ? value.file : null,
      dataUrl: typeof value.dataUrl === 'string' ? value.dataUrl : '',
      previewUrl: typeof value.previewUrl === 'string' ? value.previewUrl : '',
    };
  }
  return { file:null, dataUrl:'', previewUrl:'' };
}
function getComposerImageLocalCache(composerId){
  const key = String(composerId || '').trim();
  if(!key || !composerLocalImageFileMap.has(key)) return null;
  return _normalizeComposerImageLocalCacheRecord(composerLocalImageFileMap.get(key));
}
function setComposerImageLocalCache(composerId, patch={}){
  const key = String(composerId || '').trim();
  if(!key) return null;
  const prev = getComposerImageLocalCache(key) || { file:null, dataUrl:'', previewUrl:'' };
  const next = {
    file: Object.prototype.hasOwnProperty.call(patch, 'file') ? (patch.file instanceof File ? patch.file : null) : prev.file,
    dataUrl: Object.prototype.hasOwnProperty.call(patch, 'dataUrl') ? String(patch.dataUrl || '') : prev.dataUrl,
    previewUrl: Object.prototype.hasOwnProperty.call(patch, 'previewUrl') ? String(patch.previewUrl || '') : prev.previewUrl,
  };
  if(!next.file && !next.dataUrl && !next.previewUrl){
    composerLocalImageFileMap.delete(key);
    return null;
  }
  composerLocalImageFileMap.set(key, next);
  return next;
}
function revokeComposerImagePreviewUrl(url){
  const raw = String(url || '').trim();
  if(!raw || !raw.startsWith('blob:')) return;
  try{ URL.revokeObjectURL(raw); }catch(_){ }
}
function clearComposerImageLocalCache(composerId, opts={}){
  const key = String(composerId || '').trim();
  if(!key || !composerLocalImageFileMap.has(key)) return;
  const rec = getComposerImageLocalCache(key);
  composerLocalImageFileMap.delete(key);
  if(opts && opts.revokePreview){
    revokeComposerImagePreviewUrl(rec?.previewUrl || '');
  }
}
let pendingFiles = []; // {id, kind:'file'|'image', filename, ext, text?, data_url?}
let homeComposerAttachmentDraft = { files:[], images:[] };
const composerAttachmentDraftRuntimeGuards = new Map();
const COMPOSER_ATTACHMENT_DRAFT_BACKUP_KEY = 'webai_composer_attachment_draft_backup_v1';

function composerAttachmentDraftClone(value){
  try{ return JSON.parse(JSON.stringify(value)); }catch(_){ return value && typeof value === 'object' ? { ...value } : value; }
}

function composerAttachmentDraftBackupScopeKey(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return '';
  let scope = 'local';
  try{ scope = String(typeof currentAccountEmail !== 'undefined' ? currentAccountEmail || 'local' : 'local').trim().toLowerCase() || 'local'; }catch(_){ }
  return scope + '::' + sid;
}

function readComposerAttachmentDraftBackup(sessionId){
  const key = composerAttachmentDraftBackupScopeKey(sessionId);
  if(!key) return null;
  try{
    const all = JSON.parse(localStorage.getItem(COMPOSER_ATTACHMENT_DRAFT_BACKUP_KEY) || '{}');
    const row = all && typeof all === 'object' ? all[key] : null;
    if(!row || typeof row !== 'object') return null;
    return {
      payload: composerAttachmentDraftClone(row.payload) || { files:[], images:[] },
      updatedAt: Math.max(0, Number(row.updatedAt || 0) || 0),
    };
  }catch(_){ return null; }
}

function compactComposerAttachmentDraftBackupPayload(payload){
  const source = payload && typeof payload === 'object' ? payload : {};
  const files = (Array.isArray(source.files) ? source.files : []).map(item=>{
    const row = composerAttachmentDraftClone(item) || {};
    for(const key of ['text','full_text','content','symbols']) delete row[key];
    if(row.file_registry && typeof row.file_registry === 'object'){
      for(const key of ['text','full_text','content','symbols']) delete row.file_registry[key];
    }
    return row;
  });
  const images = (Array.isArray(source.images) ? source.images : []).map(item=>{
    const row = composerAttachmentDraftClone(item) || {};
    for(const key of ['data_url','_ocr_text','text','content']) delete row[key];
    const clearTransient = value => /^(?:blob:|data:|local:)/i.test(String(value || '').trim()) ? '' : value;
    row._preview_url = clearTransient(row._preview_url);
    if(row.image_url && typeof row.image_url === 'object') row.image_url.url = clearTransient(row.image_url.url);
    return row;
  });
  return { files, images };
}

function writeComposerAttachmentDraftBackup(sessionId, payload, updatedAt=Date.now()){
  const key = composerAttachmentDraftBackupScopeKey(sessionId);
  if(!key) return;
  try{
    const parsed = JSON.parse(localStorage.getItem(COMPOSER_ATTACHMENT_DRAFT_BACKUP_KEY) || '{}');
    const all = parsed && typeof parsed === 'object' ? parsed : {};
    all[key] = {
      payload: compactComposerAttachmentDraftBackupPayload(payload),
      updatedAt: Math.max(1, Number(updatedAt || Date.now()) || Date.now()),
    };
    const compact = Object.fromEntries(
      Object.entries(all)
        .sort((a, b)=>Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0))
        .slice(0, 80)
    );
    localStorage.setItem(COMPOSER_ATTACHMENT_DRAFT_BACKUP_KEY, JSON.stringify(compact));
  }catch(_){ }
}

function rememberComposerAttachmentDraftRuntimeGuard(sessionId, payload, updatedAt=Date.now()){
  const sid = String(sessionId || '').trim();
  if(!sid) return null;
  const normalized = payload && typeof payload === 'object' ? payload : { files:[], images:[] };
  const guard = {
    payload: composerAttachmentDraftClone({
      files: Array.isArray(normalized.files) ? normalized.files : [],
      images: Array.isArray(normalized.images) ? normalized.images : [],
    }),
    updatedAt: Math.max(1, Number(updatedAt || Date.now()) || Date.now()),
  };
  composerAttachmentDraftRuntimeGuards.set(sid, guard);
  writeComposerAttachmentDraftBackup(sid, guard.payload, guard.updatedAt);
  return guard;
}

function applyComposerAttachmentDraftRuntimeGuardToSession(session, sessionId=''){
  const target = session && typeof session === 'object' ? session : null;
  const sid = String(sessionId || target?.id || '').trim();
  const guard = sid ? composerAttachmentDraftRuntimeGuards.get(sid) : null;
  if(!target || !guard) return false;
  target.composerAttachmentDraft = composerAttachmentDraftClone(guard.payload) || { files:[], images:[] };
  target.composerAttachmentDraftUpdatedAt = Math.max(
    Number(target.composerAttachmentDraftUpdatedAt || 0) || 0,
    Number(guard.updatedAt || 0) || 0
  );
  return true;
}

function isUploadStorageRef(value){
  return String(value || '').trim().toLowerCase().startsWith('upload://');
}

function uploadStorageRefToBrowserUrl(value, mode='view'){
  const raw = String(value || '').trim();
  if(!raw.toLowerCase().startsWith('upload://')) return '';
  const body = raw.slice('upload://'.length);
  const slash = body.indexOf('/');
  if(slash <= 0 || slash >= body.length - 1) return '';
  const scopeRaw = body.slice(0, slash).trim().toLowerCase();
  const scope = (scopeRaw === 'public' || scopeRaw === 'local') ? scopeRaw : '';
  if(!scope) return '';
  const encodedName = body.slice(slash + 1).replace(/^\/+/, '');
  let filename = '';
  try{ filename = decodeURIComponent(encodedName); }catch(_){ filename = encodedName; }
  filename = String(filename || '').replace(/^\/+/, '').trim();
  if(!filename || filename.includes('..') || /[\r\n]/.test(filename)) return '';
  const endpoint = String(mode || '').toLowerCase() === 'download' ? '/api3/download/' : '/api3/uploads/';
  return endpoint + encodeURIComponent(filename) + '?scope=' + encodeURIComponent(scope);
}

function composerLibraryBrowserFileSource(value, mode='download'){
  const raw = String(value || '').trim();
  if(!raw) return '';
  if(isUploadStorageRef(raw)) return uploadStorageRefToBrowserUrl(raw, mode);
  return composerLibraryBrowserImageSource(raw);
}

function composerLibraryStableModelSource(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  const low = raw.toLowerCase();
  if(low.startsWith('data:image/') || low.startsWith('upload://') || low.startsWith('http://') || low.startsWith('https://')) return raw;
  if(raw.startsWith('/api3/') || raw.startsWith('/static/') || raw.startsWith('/uploads/') || raw.startsWith('/generated/')) return raw;
  return '';
}

function composerLibraryBrowserImageSource(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  const low = raw.toLowerCase();
  if(low.startsWith('upload://')) return uploadStorageRefToBrowserUrl(raw, 'view');
  if(low.startsWith('data:image/') || low.startsWith('blob:') || low.startsWith('local://') || low.startsWith('http://') || low.startsWith('https://')) return raw;
  if(raw.startsWith('/api3/') || raw.startsWith('/static/') || raw.startsWith('/uploads/') || raw.startsWith('/generated/')) return raw;
  return '';
}

function composerLibraryIsEphemeralImageSource(value){
  const raw = String(value || '').trim().toLowerCase();
  return !!raw && (raw.startsWith('blob:') || raw.startsWith('local://') || raw.startsWith('data:image/'));
}

function composerLibraryFirstBrowserImageSource(candidates, opts={}){
  const allowEphemeral = opts?.allowEphemeral !== false;
  for(const value of (Array.isArray(candidates) ? candidates : [])){
    const display = composerLibraryBrowserImageSource(value);
    if(!display) continue;
    if(!allowEphemeral && composerLibraryIsEphemeralImageSource(display)) continue;
    return display;
  }
  return '';
}

function composerLibraryIdBrowserSource(imageItem, mode='view'){
  const row = imageItem && typeof imageItem === 'object' ? imageItem : {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  const fileId = composerLibraryStableFileId(row);
  if(!fileId) return '';
  const sourceType = String(row.source_type || row.sourceType || reg.source_type || reg.source || row.operation || '').trim().toLowerCase();
  const namespace = String(row.namespace || reg.namespace || '').trim().toLowerCase();
  const generated = !!row.generated_by_assistant || namespace === 'generated' || sourceType === 'generated' || sourceType === 'assistant_generated';
  const encoded = encodeURIComponent(fileId);
  if(String(mode || '').toLowerCase() === 'download'){
    return generated ? ('/api3/generated-download-id/' + encoded) : ('/api3/download-id/' + encoded);
  }
  return generated ? ('/api3/generated-files-id/' + encoded) : ('/api3/uploads-id/' + encoded);
}

function composerLibraryDisplayImageUrl(imageItem){
  const row = imageItem && typeof imageItem === 'object' ? imageItem : {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  const idViewUrl = composerLibraryIdBrowserSource(row, 'view');
  const durableCandidates = [
    row.view_url, row.viewUrl, row.download_url, row.downloadUrl, row.url,
    row.persisted_url, row.server_url, row._source_url, row.image_url?.url,
    row.model_storage_ref, row.storage_ref, reg.model_storage_ref, reg.storage_ref,
    reg.preview_url, reg.previewUrl, reg.view_url, reg.viewUrl, reg.download_url, reg.downloadUrl, reg.url,
    idViewUrl,
  ];
  const durable = composerLibraryFirstBrowserImageSource(durableCandidates, { allowEphemeral:false });
  if(durable) return durable;
  return composerLibraryFirstBrowserImageSource([
    row.preview_url, row.previewUrl, row._preview_url,
    row.image_url?.url, row.view_url, row.viewUrl, row.download_url, row.downloadUrl, row.url,
    row.persisted_url, row.server_url, row._source_url,
    row.model_storage_ref, row.storage_ref, reg.preview_url, reg.previewUrl, reg.view_url, reg.viewUrl,
    reg.download_url, reg.downloadUrl, reg.url, reg.model_storage_ref, reg.storage_ref,
    idViewUrl,
  ]);
}

function composerLibraryDurableImageUrl(imageItem){
  const row = imageItem && typeof imageItem === 'object' ? imageItem : {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  const candidates = [
    row.model_storage_ref, row.storage_ref, reg.model_storage_ref, reg.storage_ref,
    row.persisted_url, row.server_url, row.image_url?.url, row.url, row.view_url, row.download_url,
    row.preview_url, row._preview_url, row._source_url,
    reg.preview_url, reg.view_url, reg.download_url, reg.url,
  ];
  for(const value of candidates){
    const raw = String(value || '').trim();
    if(!raw) continue;
    const low = raw.toLowerCase();
    if(low.startsWith('data:image/') || low.startsWith('blob:') || low.startsWith('local://')) continue;
    const stable = composerLibraryStableModelSource(raw);
    if(stable) return stable;
  }
  return '';
}

function structuredImagePartDisplayUrl(part){
  const row = part && typeof part === 'object' ? part : {};
  const display = composerLibraryDisplayImageUrl(row);
  if(display) return display;
  const durable = composerLibraryDurableImageUrl(row);
  return composerLibraryBrowserImageSource(durable) || '';
}

function ensureStructuredImagePartDurableUrl(part){
  const row = part && typeof part === 'object' ? part : null;
  if(!row || row.type !== 'image_url') return row;
  if(!row.image_url || typeof row.image_url !== 'object') row.image_url = { url:'' };
  const current = String(row.image_url.url || '').trim();
  const display = composerLibraryDisplayImageUrl(row);
  const durable = composerLibraryDurableImageUrl(row);
  if(display && (!current || !composerLibraryBrowserImageSource(current))){
    row.image_url.url = display;
  }else if(!display && composerLibraryBrowserImageSource(durable) && (!current || current.startsWith('data:') || current.startsWith('blob:') || current.startsWith('local://'))){
    row.image_url.url = durable;
  }
  const finalDisplay = composerLibraryBrowserImageSource(row.image_url?.url) || display;
  if(finalDisplay){
    if(!String(row.preview_url || '').trim()) row.preview_url = finalDisplay;
    if(!String(row.view_url || '').trim()) row.view_url = finalDisplay;
  }
  if(durable){
    if(!String(row.persisted_url || '').trim()) row.persisted_url = durable;
    if(!String(row.server_url || '').trim()) row.server_url = finalDisplay || durable;
    if(!String(row._source_url || '').trim()) row._source_url = durable;
    if(!String(row.model_storage_ref || '').trim()) row.model_storage_ref = durable;
    if(!String(row.storage_ref || '').trim() && String(durable || '').trim().toLowerCase().startsWith('upload://')) row.storage_ref = durable;
  }
  return row;
}

function composerLibraryStableFileId(item){
  const row = item && typeof item === 'object' ? item : {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  return String(row.file_library_id || row.library_file_id || row.file_id || row.id || row.registry_file_id || reg.file_id || '').trim();
}

function isComposerLibraryFileAttachment(file){
  const row = file && typeof file === 'object' ? file : null;
  if(!row) return false;
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  return !!(
    String(row.file_library_id || '').trim()
    || String(reg.file_id || '').trim()
    || String(row.source_type || '').trim() === 'file_library'
  );
}

function isComposerLibraryImageAttachment(img){
  const row = img && typeof img === 'object' ? img : null;
  if(!row) return false;
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  return !!(
    String(row.file_library_id || '').trim()
    || String(reg.file_id || '').trim()
    || String(row.source_type || '').trim() === 'file_library'
    || String(row.operation || '').trim() === 'library_reuse'
  );
}

function isComposerRestorableImageAttachment(img){
  const row = img && typeof img === 'object' ? img : null;
  if(!row) return false;
  if(isComposerLibraryImageAttachment(row)) return true;
  const composerId = String(row._composerId || '').trim();
  const cache = composerId ? getComposerImageLocalCache(composerId) : null;
  const stableSource = composerLibraryFirstBrowserImageSource([
    row.persisted_url, row.server_url, row.view_url, row.download_url, row.url,
    row.storage_ref, row.model_storage_ref, row.image_url?.url, row._source_url
  ], { allowEphemeral:false });
  return !!(
    composerId
    && (
      stableSource
      || cache?.file
      || cache?.previewUrl
      || cache?.dataUrl
      || row._upload_pending
      || row._ocr_pending
      || String(row.source_type || '').trim() === 'upload'
      || String(row.operation || '').trim() === 'upload'
    )
  );
}

function normalizeComposerAttachmentDraftFile(file){
  const row = composerAttachmentDraftClone(file) || {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  const fileId = composerLibraryStableFileId(row) || String(row.id || '').trim();
  row.id = String(row.id || fileId || '').trim() || newAttId();
  row.kind = 'file';
  row.file_library_id = String(row.file_library_id || fileId || reg.file_id || row.id || '').trim();
  row.library_file_id = String(row.library_file_id || row.file_library_id || '').trim();
  row.source_type = String(row.source_type || 'file_library').trim() || 'file_library';
  row.source_role = String(row.source_role || (row.source_type === 'generated' ? 'assistant_generated' : 'user_upload')).trim() || 'user_upload';
  row.filename = String(row.filename || row.saved_filename || reg.filename || reg.saved_filename || '未命名文件').trim() || '未命名文件';
  row.ext = String(row.ext || reg.ext || '').trim();
  row.storage_ref = String(row.storage_ref || row.model_storage_ref || reg.storage_ref || reg.model_storage_ref || '').trim();
  row.model_storage_ref = String(row.model_storage_ref || row.storage_ref || reg.model_storage_ref || reg.storage_ref || '').trim();
  const fileViewFromStorage = uploadStorageRefToBrowserUrl(row.storage_ref || row.model_storage_ref, 'view');
  const fileDownloadFromStorage = uploadStorageRefToBrowserUrl(row.storage_ref || row.model_storage_ref, 'download');
  row.url = String(row.url || row.download_url || row.view_url || reg.download_url || reg.url || reg.view_url || fileDownloadFromStorage || fileViewFromStorage || '').trim();
  row.view_url = String(row.view_url || row.url || reg.view_url || reg.url || fileViewFromStorage || '').trim();
  row.download_url = String(row.download_url || row.url || row.view_url || reg.download_url || reg.url || reg.view_url || fileDownloadFromStorage || '').trim();
  row.note = String(row.note || '从上传文件库添加').trim();
  row.file_registry = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : reg;
  row.symbols = Array.isArray(row.symbols) ? row.symbols : [];
  return row;
}


function buildOutgoingUserFileAttachmentMeta(file){
  const pf = normalizeComposerAttachmentDraftFile(file || {});
  if(!pf || typeof pf !== 'object') return null;
  return {
    _kind:'file',
    id: String(pf.id || pf.file_library_id || pf.file_registry?.file_id || '').trim(),
    file_library_id: String(pf.file_library_id || pf.file_registry?.file_id || '').trim(),
    library_file_id: String(pf.library_file_id || pf.file_library_id || pf.file_registry?.file_id || '').trim(),
    source_type: String(pf.source_type || 'file_library').trim() || 'file_library',
    source_role: String(pf.source_role || 'user_upload').trim() || 'user_upload',
    filename: String(pf.filename || '未命名文件').trim() || '未命名文件',
    ext: String(pf.ext || '').trim(),
    url: String(pf.url || pf.download_url || pf.view_url || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'download') || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'view') || '').trim(),
    view_url: String(pf.view_url || pf.url || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'view') || '').trim(),
    download_url: String(pf.download_url || pf.url || pf.view_url || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'download') || uploadStorageRefToBrowserUrl(pf.storage_ref || pf.model_storage_ref, 'view') || '').trim(),
    storage_ref: String(pf.storage_ref || pf.model_storage_ref || pf.file_registry?.storage_ref || pf.file_registry?.model_storage_ref || '').trim(),
    model_storage_ref: String(pf.model_storage_ref || pf.storage_ref || pf.file_registry?.model_storage_ref || pf.file_registry?.storage_ref || '').trim(),
    full_text_ref: String(pf.full_text_ref || pf.file_registry?.full_text_ref || '').trim(),
    size: Number(pf.size || 0) || 0,
    note: String(pf.note || '').trim(),
    text_is_preview: !!pf.text_is_preview,
    full_text_available: !!pf.full_text_available || !!pf.file_registry?.full_text_available,
    parsed_chars: Number(pf.parsed_chars || pf.file_registry?.full_text_chars || 0) || 0,
    parsed_lines: Number(pf.parsed_lines || pf.file_registry?.full_text_lines || 0) || 0,
    file_registry: pf.file_registry || null,
    code_summary: String(pf.code_summary || pf.file_registry?.summary || '').trim(),
    symbols: Array.isArray(pf.symbols) ? pf.symbols : (Array.isArray(pf.file_registry?.symbols) ? pf.file_registry.symbols : []),
  };
}

function attachOutgoingUserFileAttachmentsMeta(message, files){
  const msg = message && typeof message === 'object' ? message : null;
  if(!msg || String(msg.role || '').toLowerCase() !== 'user') return msg;
  const rows = (Array.isArray(files) ? files : []).map(buildOutgoingUserFileAttachmentMeta).filter(Boolean);
  if(!rows.length) return msg;
  const cloned = rows.map(row => ({ ...row }));
  msg.file_attachments = cloned;
  msg.attachments = cloned;
  msg._composer_file_attachments = cloned;
  return msg;
}

function normalizeComposerAttachmentDraftImage(img){
  const row = composerAttachmentDraftClone(img) || {};
  const reg = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : {};
  const isLibraryImage = isComposerLibraryImageAttachment(row);
  const composerId = String(row._composerId || '').trim();
  const localCache = composerId ? getComposerImageLocalCache(composerId) : null;
  const fileId = composerLibraryStableFileId(row) || String(row.image_id || row.attachment_id || '').trim();
  const modelSource = composerLibraryStableModelSource(row.model_storage_ref)
    || composerLibraryStableModelSource(row.storage_ref)
    || composerLibraryStableModelSource(reg.model_storage_ref)
    || composerLibraryStableModelSource(reg.storage_ref)
    || composerLibraryStableModelSource(row.image_url?.url)
    || composerLibraryStableModelSource(row.persisted_url)
    || composerLibraryStableModelSource(row.server_url)
    || composerLibraryStableModelSource(row.url)
    || composerLibraryStableModelSource(row.view_url)
    || composerLibraryStableModelSource(row.download_url)
    || composerLibraryStableModelSource(row.preview_url)
    || composerLibraryStableModelSource(row._preview_url)
    || composerLibraryStableModelSource(row._source_url)
    || composerLibraryStableModelSource(reg.preview_url)
    || composerLibraryStableModelSource(reg.view_url)
    || composerLibraryStableModelSource(reg.download_url)
    || composerLibraryStableModelSource(reg.url);
  const previewUrl = composerLibraryBrowserImageSource(row._preview_url)
    || composerLibraryBrowserImageSource(row.preview_url)
    || composerLibraryBrowserImageSource(row.image_url?.url)
    || composerLibraryBrowserImageSource(row.view_url)
    || composerLibraryBrowserImageSource(row.download_url)
    || composerLibraryBrowserImageSource(row.url)
    || composerLibraryBrowserImageSource(reg.preview_url)
    || composerLibraryBrowserImageSource(reg.view_url)
    || composerLibraryBrowserImageSource(reg.download_url)
    || composerLibraryBrowserImageSource(reg.url)
    || composerLibraryBrowserImageSource(modelSource);
  const modelUrl = String(modelSource || composerLibraryStableModelSource(row.persisted_url) || composerLibraryStableModelSource(row.server_url) || previewUrl || '').trim();
  const displayUrl = previewUrl || composerLibraryBrowserImageSource(modelUrl) || '';
  const stableDisplayUrl = composerLibraryFirstBrowserImageSource([
    row.persisted_url, row.server_url, row.view_url, row.download_url, row.url,
    row.storage_ref, row.model_storage_ref, row._source_url, modelSource
  ], { allowEphemeral:false });
  const draftDisplayUrl = (!isLibraryImage && localCache && composerLibraryIsEphemeralImageSource(displayUrl))
    ? stableDisplayUrl
    : (displayUrl || stableDisplayUrl || modelUrl);
  row.type = 'image_url';
  row.attachment_id = String(row.attachment_id || fileId || row.image_id || '').trim() || ('libimg_' + Math.random().toString(16).slice(2));
  row.image_id = String(row.image_id || fileId || row.attachment_id || '').trim();
  row.file_library_id = String(row.file_library_id || (isLibraryImage ? fileId : '') || '').trim();
  row.library_file_id = String(row.library_file_id || row.file_library_id || '').trim();
  row.storage_ref = modelSource || composerLibraryStableModelSource(row.storage_ref) || '';
  row.model_storage_ref = modelSource || composerLibraryStableModelSource(row.model_storage_ref) || '';
  row.file_registry = row.file_registry && typeof row.file_registry === 'object' ? row.file_registry : reg;
  row.image_url = { url: draftDisplayUrl || '' };
  row.preview_url = String(row.preview_url || draftDisplayUrl || '').trim();
  row.view_url = String(row.view_url || draftDisplayUrl || '').trim();
  row.download_url = String(row.download_url || row.view_url || draftDisplayUrl || '').trim();
  row.persisted_url = String(row.persisted_url || stableDisplayUrl || modelUrl || '').trim();
  row.server_url = String(row.server_url || stableDisplayUrl || modelUrl || '').trim();
  row._preview_url = draftDisplayUrl || '';
  row._source_url = String(row._source_url || modelUrl || reg.url || reg.view_url || reg.download_url || stableDisplayUrl || '').trim();
  row.filename = String(row.filename || reg.filename || reg.saved_filename || '图片').trim() || '图片';
  row.source_role = String(row.source_role || 'user').trim() || 'user';
  row.source_type = String(row.source_type || (isLibraryImage ? 'file_library' : 'upload')).trim() || (isLibraryImage ? 'file_library' : 'upload');
  row.operation = String(row.operation || (isLibraryImage ? 'library_reuse' : 'upload')).trim() || (isLibraryImage ? 'library_reuse' : 'upload');
  const hasDurableUploadResult = !!(
    isLibraryImage
    || String(reg.file_id || '').trim()
    || String(row.file_library_id || row.library_file_id || '').trim()
    || isUploadStorageRef(row.storage_ref)
    || isUploadStorageRef(row.model_storage_ref)
    || stableDisplayUrl
  );
  if(hasDurableUploadResult){
    row._upload_pending = false;
    row._ocr_pending = false;
    row._upload_error = '';
    row._upload_phase = 'done';
    row._upload_progress = 100;
  }else{
    row._upload_pending = !!row._upload_pending;
    row._ocr_pending = !!row._ocr_pending;
  }
  if(!String(row._composerId || '').trim()) row._composerId = (isLibraryImage ? 'libimg_' : 'cmpimg_') + Math.random().toString(16).slice(2) + '_' + Date.now().toString(16);
  return ensureComposerImageAttachmentMeta(row, { prefix:isLibraryImage ? 'libimg' : 'upl', sourceRole:'user', operation:row.operation, endpointMode:getActiveApiEndpointMode() });
}

function getComposerAttachmentDraftPayload(){
  const files = (pendingFiles || []).filter(isComposerLibraryFileAttachment).map(normalizeComposerAttachmentDraftFile);
  const images = (pastedImages || []).filter(isComposerRestorableImageAttachment).map(normalizeComposerAttachmentDraftImage);
  return { files, images };
}

function persistComposerAttachmentDraft(sessionId, opts={}){
  const payload = getComposerAttachmentDraftPayload();
  const immediate = !!opts?.immediate;
  if(isHomeLandingView && (!sessionId || sessionId === store?.activeId)){
    homeComposerAttachmentDraft = payload;
    if(immediate) saveStore();
    return;
  }
  const sid = sessionId || getComposerAttachmentOwnerSessionId();
  if(!sid || !store?.sessions?.[sid]) return;
  const changedAt = Date.now();
  rememberComposerAttachmentDraftRuntimeGuard(sid, payload, changedAt);
  const prev = store.sessions[sid].composerAttachmentDraft || { files:[], images:[] };
  if(JSON.stringify(prev) === JSON.stringify(payload)) return;
  store.sessions[sid].composerAttachmentDraft = payload;
  store.sessions[sid].composerAttachmentDraftUpdatedAt = changedAt;
  store.sessions[sid].updatedAt = now();
  if(immediate) saveStore();
  else saveStoreThrottled();
}

function getComposerAttachmentOwnerSessionId(fallbackSessionId=''){
  try{
    const ownerId = (typeof getComposerInputOwnerSessionId === 'function') ? String(getComposerInputOwnerSessionId() || '').trim() : '';
    if(ownerId) return ownerId;
  }catch(_){ }
  return String(fallbackSessionId || store?.activeId || '').trim();
}

function clearComposerAttachmentDraft(sessionId){
  const empty = { files:[], images:[] };
  if(isHomeLandingView && (!sessionId || sessionId === store?.activeId)){
    homeComposerAttachmentDraft = empty;
    return;
  }
  const sid = sessionId || getComposerAttachmentOwnerSessionId();
  if(!sid || !store?.sessions?.[sid]) return;
  const changedAt = Date.now();
  rememberComposerAttachmentDraftRuntimeGuard(sid, empty, changedAt);
  store.sessions[sid].composerAttachmentDraft = empty;
  store.sessions[sid].composerAttachmentDraftUpdatedAt = changedAt;
  store.sessions[sid].updatedAt = now();
  saveStoreThrottled();
}

function getComposerAttachmentDraft(sessionId){
  if(isHomeLandingView && (!sessionId || sessionId === store?.activeId)) return homeComposerAttachmentDraft || { files:[], images:[] };
  const sid = sessionId || getComposerAttachmentOwnerSessionId();
  const payload = sid && store?.sessions?.[sid]?.composerAttachmentDraft;
  if(!payload || typeof payload !== 'object') return { files:[], images:[] };
  return {
    files: Array.isArray(payload.files) ? payload.files : [],
    images: Array.isArray(payload.images) ? payload.images : [],
  };
}

function restoreComposerAttachmentDraft(sessionId, opts={}){
  const sid = isHomeLandingView ? '' : String(sessionId || getComposerAttachmentOwnerSessionId() || '').trim();
  if(sid && store?.sessions?.[sid]){
    const backup = readComposerAttachmentDraftBackup(sid);
    const storedStamp = Number(store.sessions[sid].composerAttachmentDraftUpdatedAt || 0) || 0;
    if(backup && Number(backup.updatedAt || 0) >= storedStamp){
      store.sessions[sid].composerAttachmentDraft = composerAttachmentDraftClone(backup.payload) || { files:[], images:[] };
      store.sessions[sid].composerAttachmentDraftUpdatedAt = Number(backup.updatedAt || 0) || storedStamp;
    }
  }
  const payload = getComposerAttachmentDraft(sessionId);
  if(sid && !composerAttachmentDraftRuntimeGuards.has(sid)){
    const storedStamp = Number(store?.sessions?.[sid]?.composerAttachmentDraftUpdatedAt || 0) || Date.now();
    rememberComposerAttachmentDraftRuntimeGuard(sid, payload, storedStamp);
  }
  const preserveLiveUploads = opts?.preserveLiveUploads !== false
    && typeof hasBlockingComposerAttachmentUploads === 'function'
    && hasBlockingComposerAttachmentUploads();
  if(opts?.replace !== false && !preserveLiveUploads){
    if(typeof clearPastedImages === 'function') clearPastedImages({ preserveLocalCache:true, preservePreviewUrls:true });
    pendingFiles = [];
    imagePreviewEl?.querySelectorAll('.file-card').forEach(el=>el.remove());
  }
  const files = (Array.isArray(payload.files) ? payload.files : []).map(normalizeComposerAttachmentDraftFile).filter(isComposerLibraryFileAttachment);
  const images = (Array.isArray(payload.images) ? payload.images : []).map(normalizeComposerAttachmentDraftImage).filter(isComposerRestorableImageAttachment);
  for(const file of files){
    if((pendingFiles || []).some(x => String(x.id || '') === String(file.id || ''))) continue;
    pendingFiles.push(file);
    addPendingFileCard(file);
  }
  for(const img of images){
    const key = String(img.file_library_id || img.model_storage_ref || img.storage_ref || img.image_id || img.attachment_id || img._source_url || img.persisted_url || img.image_url?.url || '').trim();
    if(key && (pastedImages || []).some(x => String(x.file_library_id || x.model_storage_ref || x.storage_ref || x.image_id || x.attachment_id || x._source_url || x.persisted_url || x.image_url?.url || '').trim() === key)) continue;
    pastedImages.push(img);
    addImageThumb(img);
  }
  if(images.some(img=>!!img?._upload_pending || !!img?._ocr_pending)){
    try{ reconcileRestoredPendingComposerImagesFromLibrary(images).catch(()=>{}); }catch(_){ }
  }
  updateComposerActionState();
  updateComposerPlaceholder();
  refreshComposerLayoutSoon();
}

const COMPOSER_MAX_IMAGES = 4;
const COMPOSER_MAX_FILES = 5;
const COMPOSER_MAX_ATTACHMENTS = 8;
const IMAGE_COMPRESS_TRIGGER_BYTES = 3 * 1024 * 1024;
const IMAGE_UPLOAD_MAX_BYTES = 8 * 1024 * 1024;
const FILE_UPLOAD_MAX_BYTES = 30 * 1024 * 1024;
const IMAGE_COMPRESS_MAX_EDGE_PHOTO = 2048;
const IMAGE_COMPRESS_MAX_EDGE_TEXT = 2560;
const IMAGE_COMPRESS_QUALITY_PHOTO = 0.88;
const IMAGE_COMPRESS_QUALITY_TEXT = 0.92;
const AUTO_MESSAGE_TO_TXT_TRIGGER_CHARS = 4000;
const AUTO_MESSAGE_TO_TXT_TRIGGER_LINES = 120;

function buildAutoMessageTxtFilename(){
  const d = new Date();
  const pad2 = (n)=> String(n).padStart(2, "0");
  return `user_message_${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}_${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}.txt`;
}

function maybeAutoConvertLongMessageToTxt(rawText){
  const text = String(rawText || "");
  const normalized = text.replace(/\r\n?/g, "\n");
  const lineCount = normalized ? normalized.split("\n").length : 0;
  const shouldConvert = !!text.trim() && (
    text.length >= AUTO_MESSAGE_TO_TXT_TRIGGER_CHARS ||
    lineCount >= AUTO_MESSAGE_TO_TXT_TRIGGER_LINES
  );
  if(!shouldConvert){
    return { converted:false, text };
  }
  const body = normalized.endsWith("\n") ? normalized : (normalized + "\n");
  const file = new File([body], buildAutoMessageTxtFilename(), { type:"text/plain;charset=utf-8" });
  return {
    converted:true,
    text,
    filename:file.name,
    file,
    originalText:text,
    originalLength:text.length,
    lineCount,
  };
}

async function uploadPreparedFileForImmediateSend(file, previewId=null){
  const data = await uploadOneFileRequest(file, previewId);
  const attId = newAttId();
  const ext = (String(data.filename).split(".").pop() || "").toUpperCase();
  const url = data.download_url || data.url || data.view_url || "";

  if(data.kind === "text"){
    return { id: attId, kind:"file", source_type: String(data.source_type || 'upload').trim() || 'upload', filename: data.filename, ext, text: data.text || "", text_is_preview: !!data.text_is_preview, full_text_available: !!data.full_text_available, parsed_chars: Number(data.parsed_chars || 0) || 0, parsed_lines: Number(data.parsed_lines || 0) || 0, url, view_url: data.view_url || "", download_url: data.download_url || data.url || "", size: data.size || file?.size || 0, file_registry: data.file_registry || null, code_summary: data.code_summary || "", symbols: Array.isArray(data.symbols) ? data.symbols : [], kb_imported: !!data.kb_imported };
  }
  if(data.kind === "file"){
    return { id: attId, kind:"file", source_type: String(data.source_type || 'upload').trim() || 'upload', filename: data.filename, ext, text: "", url, view_url: data.view_url || "", download_url: data.download_url || data.url || "", size: data.size || file?.size || 0, note: data.note || "", file_registry: data.file_registry || null, code_summary: data.code_summary || "", symbols: Array.isArray(data.symbols) ? data.symbols : [], kb_imported: !!data.kb_imported };
  }
  throw new Error("自动转 txt 失败：上传返回了不支持的类型");
}

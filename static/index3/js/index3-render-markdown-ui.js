/* Assistant sources, citations, rich Markdown rendering, code block runner and assistant quote UI.*/
function markdownUiT(key,params=null,fallback=''){
  return window.AperviaI18n?.t(key,params,fallback)||fallback||key;
}

function trimUrl(u){
  let s = String(u || '').replace(/[.,;!?]+$/g, '');
  const m = s.match(/[一-鿿]/);
  if(m && m.index > 0){
    s = s.slice(0, m.index);
  }
  s = s.replace(/[.,;!?]+$/g, '');
  return s;
}

function getAssistantSourceHost(url){
  const raw = trimUrl(url);
  if(!raw) return '';
  try{
    return (new URL(raw, window.location.origin).hostname || '').replace(/^www\./i, '').toLowerCase();
  }catch(_){
    return '';
  }
}

function normalizeAssistantSourceTitle(title, url, host){
  const rawUrl = trimUrl(url);
  const normalizedHost = String(host || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase();
  let text = String(title || '').replace(/\s+/g, ' ').trim();
  if(!text) return normalizedHost;
  const lowered = text.toLowerCase().replace(/^https?:\/\//i, '').replace(/\/$/, '');
  const urlCompact = rawUrl.toLowerCase().replace(/^https?:\/\//i, '').replace(/\/$/, '');
  const hostVariants = new Set([
    normalizedHost,
    normalizedHost ? `www.${normalizedHost}` : '',
    urlCompact,
  ].filter(Boolean));
  if(hostVariants.has(lowered)) return normalizedHost;
  if(normalizedHost && (lowered === `${normalizedHost}/` || lowered.startsWith(`${normalizedHost}/`) || lowered.startsWith(`www.${normalizedHost}/`))){
    return normalizedHost;
  }
  return text;
}

function getAssistantSourceFallbackFaviconUrl(item){
  try{
    const rawUrl = trimUrl(item?.url || item?.href || '');
    const rawHost = String(item?.host || item?.domain || getAssistantSourceHost(rawUrl) || '').trim().replace(/^www\./i, '');
    if(!rawHost) return '';
    return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(rawHost)}&sz=32`;
  }catch(_){
    return '';
  }
}

function getAssistantSourceFaviconCandidates(item){
  const rawUrl = trimUrl(item?.url || item?.href || '');
  const host = String(item?.host || item?.domain || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
  const candidates = [];
  const seen = new Set();
  const push = (value)=>{
    const url = String(value || '').trim();
    if(!url || seen.has(url)) return;
    seen.add(url);
    candidates.push(url);
  };
  push(item?.favicon || item?.icon || item?.iconUrl || item?.icon_url || '');
  push(getAssistantSourceFallbackFaviconUrl({ ...item, url:rawUrl, host }));
  push(assistantInlineSourceFaviconUrlForHost(host));
  return candidates;
}

function getAssistantSourceFaviconUrl(item){
  return getAssistantSourceFaviconCandidates(item)[0] || '';
}

function bindAssistantSourceFavicon(icon, item){
  if(!icon) return false;
  const rawUrl = trimUrl(item?.url || item?.href || '');
  const host = String(item?.host || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
  if(host) icon.dataset.sourceHost = host;

  const favicon = getAssistantSourceFaviconUrl({ ...item, url:rawUrl, host });
  icon.replaceChildren();
  icon.classList.remove('has-image');
  if(!favicon) return false;

  const iconImg = document.createElement('img');
  iconImg.className = 'bubble-source-icon-img';
  iconImg.alt = '';
  iconImg.loading = 'lazy';
  iconImg.decoding = 'async';
  iconImg.referrerPolicy = 'no-referrer';
  icon.classList.add('has-image');
  iconImg.onload = ()=>icon.classList.add('has-image');
  iconImg.onerror = ()=>{
    icon.classList.remove('has-image');
    try{ iconImg.remove(); }catch(_){ iconImg.style.display = 'none'; }
  };
  if(typeof _activityScheduleSourceIcon === 'function') _activityScheduleSourceIcon(iconImg, favicon);
  else iconImg.src = favicon;
  icon.appendChild(iconImg);
  return true;
}

function getAssistantSourceIconFallback(item){
  return '↗';
}

function shouldShowAssistantSourceHost(item){
  const title = String(item?.title || '').trim().toLowerCase();
  const host = String(item?.host || '').trim().toLowerCase();
  if(!host) return false;
  if(!title) return true;
  return title !== host && title !== `www.${host}`;
}

function isAssistantVisibleCitationUrl(url){
  const rawUrl = trimUrl(url || '');
  if(!/^https?:\/\//i.test(rawUrl)) return false;
  try{
    const parsed = new URL(rawUrl, window.location.origin);
    const host = String(parsed.hostname || '').trim().toLowerCase();
    const path = String(parsed.pathname || '').trim().toLowerCase();
    if(!host) return false;
    if(host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0' || host === '::1') return false;
    if(host.endsWith('.local') || host.endsWith('.lan')) return false;
    if(path.startsWith('/api3/download/') || path.startsWith('/api3/uploads/') || path.startsWith('/api3/source-favicon')) return false;
    if(/^\d+\.\d+\.\d+\.\d+$/.test(host)){
      const parts = host.split('.').map(v => Number(v));
      if(parts.length === 4 && parts.every(v => Number.isFinite(v) && v >= 0 && v <= 255)){
        const [a, b] = parts;
        if(a === 10 || a === 127 || a === 0) return false;
        if(a === 172 && b >= 16 && b <= 31) return false;
        if(a === 192 && b === 168) return false;
        if(a === 169 && b === 254) return false;
      }
    }
    return true;
  }catch(_){
    return false;
  }
}

function normalizeAssistantCitationLabel(value){
  return String(value || '').replace(/\s+/g, ' ').trim();
}
function normalizeAssistantCitationLookupKeys(value){
  const raw = normalizeAssistantCitationLabel(value);
  if(!raw) return [];
  const compact = raw.replace(/\s+/g, '').toLowerCase();
  const normalized = compact.replace(/[《》]/g, '');
  const out = [compact];
  if(normalized && normalized !== compact) out.push(normalized);
  const matched = normalized.match(/^(.+?)#片段(\d+)$/);
  if(matched){
    out.push(`《${matched[1]}》#片段${Number(matched[2])}`.toLowerCase());
    out.push(`${matched[1]}#片段${Number(matched[2])}`.toLowerCase());
  }
  return Array.from(new Set(out.filter(Boolean)));
}

const assistantCitationSourceItemsByBubble = new WeakMap();
const knowledgeBaseCitationPreviewFetchCache = new Map();

function parseKnowledgeBaseCitationLabel(label){
  const raw = normalizeAssistantCitationLabel(label);
  const compact = raw.replace(/\s+/g, '');
  const m = compact.match(/^《?(.+?)》?#片段(\d+)$/);
  if(m){
    return { raw, filename:String(m[1] || '').trim(), chunk:Number(m[2] || 0) || 0 };
  }
  const parts = raw.split('#片段');
  if(parts.length >= 2){
    return { raw, filename:String(parts[0] || '').replace(/[《》]/g, '').trim(), chunk:Number(parts[1] || 0) || 0 };
  }
  return { raw, filename:raw.replace(/[《》]/g, '').trim(), chunk:0 };
}

function buildKnowledgeBaseCitationChipHtml(label){
  const parsed = parseKnowledgeBaseCitationLabel(label);
  const raw = normalizeAssistantCitationLabel(parsed.raw || label);
  if(!raw) return '';
  const filename = parsed.filename || markdownUiT('citation.kb_document', null, 'Knowledge-base document');
  const chunkText = parsed.chunk > 0
    ? markdownUiT('citation.chunk', {chunk:parsed.chunk}, 'Chunk {chunk}')
    : markdownUiT('citation.kb_reference', null, 'Knowledge-base citation');
  const title = markdownUiT('citation.open', {citation:raw}, 'View knowledge-base citation: {citation}');
  return `<button type="button" class="kb-citation-chip" data-kb-citation-label="${escapeHtml(raw)}" title="${escapeHtml(title)}"><span class="kb-citation-chip-icon" aria-hidden="true">▣</span><span class="kb-citation-chip-title">${escapeHtml(filename)}</span><span class="kb-citation-chip-meta">${escapeHtml(chunkText)}</span></button>`;
}

function ensureKnowledgeBaseCitationUiStyle(){
  if(document.getElementById('webai-kb-citation-ui-style')) return;
  const style = document.createElement('style');
  style.id = 'webai-kb-citation-ui-style';
  style.textContent = `
.kb-citation-chip{display:inline-flex;align-items:center;gap:4px;max-width:min(220px,100%);margin:0 2px;padding:1px 6px;border:1px solid color-mix(in srgb,var(--outline) 12%,var(--border));border-radius:999px;background:color-mix(in srgb,var(--panel) 82%,var(--card));color:var(--fg);font:inherit;font-size:.76em;line-height:1.32;vertical-align:baseline;cursor:pointer;box-shadow:none;transition:background .16s ease,border-color .16s ease,box-shadow .16s ease,transform .16s ease;}
.kb-citation-chip:hover,.kb-citation-chip.is-active{background:color-mix(in srgb,var(--card) 94%,var(--panel));border-color:color-mix(in srgb,var(--outline) 34%,var(--border));box-shadow:0 5px 15px rgba(0,0,0,.06);transform:translateY(-1px);}
.kb-citation-chip:active{transform:translateY(0) scale(.99);}
.kb-citation-chip:focus-visible{outline:2px solid color-mix(in srgb,var(--outline) 72%,transparent);outline-offset:2px;}
.kb-citation-chip-icon{font-size:.72em;opacity:.58;line-height:1;}
.kb-citation-chip-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:650;}
.kb-citation-chip-meta{flex:0 0 auto;color:var(--muted);font-size:.82em;}
.kb-citation-popover{position:fixed;z-index:1800;width:min(360px,calc(100vw - 28px));max-height:min(360px,calc(100vh - 28px));padding:14px;border-radius:20px;border:1px solid color-mix(in srgb,var(--outline) 14%,var(--border));background:color-mix(in srgb,var(--card) 98%,var(--panel));box-shadow:0 18px 50px rgba(0,0,0,.16);animation:kbCitationPopoverIn .14s ease both;overflow:hidden;}
.kb-citation-popover-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px;}
.kb-citation-popover-title{min-width:0;font-size:15px;line-height:1.28;font-weight:800;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.kb-citation-popover-meta{margin-top:4px;font-size:12px;line-height:1.35;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.kb-citation-popover-close{flex:0 0 auto;width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;border:none;border-radius:999px;background:transparent;color:var(--muted);font-size:19px;line-height:1;cursor:pointer;}
.kb-citation-popover-close:hover{background:color-mix(in srgb,var(--fg) 7%,transparent);color:var(--fg);}
.kb-citation-popover-label{font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px;}
.kb-citation-popover-text{max-height:220px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.58;color:var(--fg);padding:10px 11px;border-radius:14px;background:color-mix(in srgb,var(--panel) 62%,transparent);}
.kb-citation-popover-empty{color:var(--muted);}
.bubble-source-detail-row.has-preview{cursor:pointer;}
button.bubble-source-detail-row{width:100%;border:0;background:transparent;color:inherit;font:inherit;text-align:left;}
.bubble-source-detail-row.has-preview:hover,.bubble-source-detail-row.has-preview.is-active{background:color-mix(in srgb,var(--fg) 6%,transparent);}
@keyframes kbCitationPopoverIn{from{opacity:0;transform:translateY(4px) scale(.985);}to{opacity:1;transform:translateY(0) scale(1);}}
[data-theme="dark"] .kb-citation-chip{background:color-mix(in srgb,var(--panel) 78%,var(--card));}
[data-theme="dark"] .kb-citation-popover{box-shadow:0 20px 54px rgba(0,0,0,.34);}
`;
  document.head.appendChild(style);
}

function findKnowledgeBaseCitationSourceForBubble(bubble, label){
  const refs = normalizeAssistantCitationLookupKeys(label);
  const items = assistantCitationSourceItemsByBubble.get(bubble) || [];
  for(const item of (Array.isArray(items) ? items : [])){
    if(String(item?.sourceType || '').trim().toLowerCase() !== 'kb') continue;
    const itemLabel = normalizeAssistantCitationLabel(item?.citationLabel || '');
    if(!itemLabel) continue;
    const itemKeys = normalizeAssistantCitationLookupKeys(itemLabel);
    if(refs.some(key => itemKeys.includes(key))) return item;
  }
  return null;
}

let activeKnowledgeBaseCitationPopover = null;
let activeKnowledgeBaseCitationAnchor = null;

function closeKnowledgeBaseCitationPopover(){
  try{ activeKnowledgeBaseCitationPopover?.remove?.(); }catch(_){ }
  activeKnowledgeBaseCitationPopover = null;
  try{ activeKnowledgeBaseCitationAnchor?.classList?.remove?.('is-active'); }catch(_){ }
  activeKnowledgeBaseCitationAnchor = null;
  try{ document.querySelectorAll('.kb-citation-chip.is-active,.bubble-source-detail-row.is-active').forEach(x => x.classList.remove('is-active')); }catch(_){ }
}

function citationPreviewLabelForSource(item){
  const src = item && typeof item === 'object' ? item : {};
  const citation = normalizeAssistantCitationLabel(src.citationLabel || src.citation_label || '');
  if(citation) return citation;
  const title = String(src.title || src.filename || '').trim();
  return title || markdownUiT('citation.source', null, 'Source');
}

function citationPreviewSourceIsLocal(item){
  const src = item && typeof item === 'object' ? item : {};
  const t = String(src.sourceType || src.source_type || src.kind || '').trim().toLowerCase();
  return ['kb','file','upload','local_file','generated'].includes(t) || !!normalizeAssistantCitationLabel(src.citationLabel || src.citation_label || '');
}


function kbCitationPreviewCacheKey(label, source){
  const src = source && typeof source === 'object' ? source : {};
  const parsed = parseKnowledgeBaseCitationLabel(label || src.citationLabel || src.citation_label || '');
  return normalizeAssistantCitationLookupKeys(parsed.raw || label || src.citationLabel || src.citation_label || '').join('|')
    || `${String(src.docId || src.doc_id || src.document_id || '')}|${parsed.filename}|${parsed.chunk}`.toLowerCase();
}

function normalizeKnowledgeBaseDocumentReadPreview(data, parsed){
  const rows = Array.isArray(data?.results) ? data.results : [];
  if(!rows.length) return '';
  const targetChunk = Number(parsed?.chunk || 0) > 0 ? Number(parsed.chunk) - 1 : null;
  let best = null;
  for(const row of rows){
    if(!row || typeof row !== 'object') continue;
    const order = Number(row.chunk_order ?? row.chunk ?? row.chunkIndex ?? row.chunk_index ?? -1);
    if(targetChunk !== null && Number.isFinite(order) && order === targetChunk){
      best = row;
      break;
    }
    if(!best) best = row;
  }
  return String(best?.text || best?.snippet || best?.content || '').trim();
}

async function fetchKnowledgeBaseCitationPreview(label, source){
  const src = source && typeof source === 'object' ? source : {};
  const parsed = parseKnowledgeBaseCitationLabel(label || src.citationLabel || src.citation_label || '');
  const cacheKey = kbCitationPreviewCacheKey(label, source);
  if(cacheKey && knowledgeBaseCitationPreviewFetchCache.has(cacheKey)) return knowledgeBaseCitationPreviewFetchCache.get(cacheKey);
  const filename = String(src.filename || src.title || parsed.filename || '').trim();
  const docId = String(src.docId || src.doc_id || src.document_id || '').trim();
  if(!filename && !docId) return '';
  const center = parsed.chunk > 0 ? Math.max(0, parsed.chunk - 1) : Math.max(0, Number(src.chunk_order ?? src.chunkOrder ?? 0) || 0);
  const body = {
    filename,
    doc_id: docId,
    mode: parsed.chunk > 0 ? 'range' : 'around',
    start_chunk: center,
    end_chunk: center,
    around_chunk: center,
    window_chunks: 1,
    max_chars: 9000,
  };
  let text = '';
  try{
    const res = await fetch('/api3/kb/document-read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = {};
    try{ data = await res.json(); }catch(_){ data = {}; }
    if(res.ok && data && data.ok !== false){
      text = normalizeKnowledgeBaseDocumentReadPreview(data, parsed);
    }
  }catch(_){
    text = '';
  }
  if(text && source && typeof source === 'object'){
    try{ source.snippet = text; }catch(_){ }
  }
  if(cacheKey) knowledgeBaseCitationPreviewFetchCache.set(cacheKey, text || '');
  return text || '';
}

function setKnowledgeBaseCitationPopoverPreviewText(popover, text, emptyText=''){
  if(!popover) return;
  const el = popover.querySelector?.('.kb-citation-popover-text');
  if(!el) return;
  const value = String(text || '').trim();
  el.textContent = value || String(emptyText || markdownUiT('citation.empty_preview', null, 'This response cites the source, but a chunk preview is not currently available.'));
  el.classList.toggle('kb-citation-popover-empty', !value);
}

async function hydrateKnowledgeBaseCitationPopover(popover, label, source){
  const current = String(source?.snippet || source?.text || source?.preview || '').trim();
  if(current) return;
  setKnowledgeBaseCitationPopoverPreviewText(popover, markdownUiT('citation.loading_preview', null, 'Loading knowledge-base chunk…'));
  const fetched = await fetchKnowledgeBaseCitationPreview(label, source);
  if(activeKnowledgeBaseCitationPopover !== popover) return;
  setKnowledgeBaseCitationPopoverPreviewText(popover, fetched, markdownUiT('citation.no_preview', null, 'No preview is available for this chunk.'));
  if(activeKnowledgeBaseCitationAnchor && activeKnowledgeBaseCitationPopover) positionKnowledgeBaseCitationPopover(activeKnowledgeBaseCitationAnchor, activeKnowledgeBaseCitationPopover);
}

function createKnowledgeBaseCitationPopover(label, source){
  const parsed = parseKnowledgeBaseCitationLabel(label);
  const src = source && typeof source === 'object' ? source : {};
  const type = String(src.sourceType || src.source_type || '').trim().toLowerCase();
  const isKb = type === 'kb' || (!!parsed.chunk && !type);
  const filename = String(src.title || parsed.filename || (isKb
    ? markdownUiT('citation.kb_document', null, 'Knowledge-base document')
    : markdownUiT('citation.source', null, 'Source'))).trim() || (isKb
      ? markdownUiT('citation.kb_document', null, 'Knowledge-base document')
      : markdownUiT('citation.source', null, 'Source'));
  const citation = normalizeAssistantCitationLabel(src.citationLabel || src.citation_label || label);
  const snippet = String(src.snippet || src.text || src.preview || '').trim();
  const popover = document.createElement('div');
  popover.className = 'kb-citation-popover';
  popover.dataset.kbCitationLabel = citation;

  const head = document.createElement('div');
  head.className = 'kb-citation-popover-head';
  const titleWrap = document.createElement('div');
  titleWrap.style.minWidth = '0';
  const title = document.createElement('div');
  title.className = 'kb-citation-popover-title';
  title.textContent = filename;
  titleWrap.appendChild(title);
  const meta = document.createElement('div');
  meta.className = 'kb-citation-popover-meta';
  const metaBits = [];
  if(isKb) metaBits.push(markdownUiT('citation.kb_reference', null, 'Knowledge-base citation'));
  else metaBits.push(assistantSourceTypeLabel(src) || markdownUiT('citation.reference_source', null, 'Citation source'));
  if(parsed.chunk > 0) metaBits.push(markdownUiT('citation.chunk', {chunk:parsed.chunk}, 'Chunk {chunk}'));
  if(citation && citation !== filename) metaBits.push(citation);
  meta.textContent = metaBits.join(' · ');
  titleWrap.appendChild(meta);
  head.appendChild(titleWrap);

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'kb-citation-popover-close';
  close.setAttribute('aria-label', markdownUiT('citation.close_preview', null, 'Close citation preview'));
  close.textContent = '×';
  head.appendChild(close);
  popover.appendChild(head);

  const labelEl = document.createElement('div');
  labelEl.className = 'kb-citation-popover-label';
  labelEl.textContent = markdownUiT('citation.content', null, 'Content');
  popover.appendChild(labelEl);
  const text = document.createElement('div');
  text.className = 'kb-citation-popover-text' + (snippet ? '' : ' kb-citation-popover-empty');
  text.textContent = snippet || markdownUiT('citation.preparing_preview', null, 'Preparing knowledge-base chunk preview…');
  popover.appendChild(text);

  close.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    closeKnowledgeBaseCitationPopover();
  });
  popover.addEventListener('click', (e)=>e.stopPropagation());
  return popover;
}

function positionKnowledgeBaseCitationPopover(anchor, popover){
  if(!anchor || !popover) return;
  const gap = 8;
  const rect = anchor.getBoundingClientRect();
  const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
  const pr = popover.getBoundingClientRect();
  let left = rect.left;
  let top = rect.bottom + gap;
  if(left + pr.width > vw - 12) left = vw - pr.width - 12;
  if(left < 12) left = 12;
  if(top + pr.height > vh - 12){
    top = rect.top - pr.height - gap;
  }
  if(top < 12) top = 12;
  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

function showKnowledgeBaseCitationPreview(anchor, label, source){
  if(!anchor) return;
  ensureKnowledgeBaseCitationUiStyle();
  if(activeKnowledgeBaseCitationAnchor === anchor && activeKnowledgeBaseCitationPopover){
    closeKnowledgeBaseCitationPopover();
    return;
  }
  closeKnowledgeBaseCitationPopover();
  const popover = createKnowledgeBaseCitationPopover(label, source);
  document.body.appendChild(popover);
  activeKnowledgeBaseCitationPopover = popover;
  activeKnowledgeBaseCitationAnchor = anchor;
  try{ anchor.classList.add('is-active'); }catch(_){ }
  positionKnowledgeBaseCitationPopover(anchor, popover);
  hydrateKnowledgeBaseCitationPopover(popover, label, source);
  setTimeout(()=>positionKnowledgeBaseCitationPopover(anchor, popover), 0);
}

function clearKnowledgeBaseCitationCardsInBubble(bubble){
  if(!bubble?.querySelectorAll) return;
  closeKnowledgeBaseCitationPopover();
  bubble.querySelectorAll('.kb-citation-card').forEach(x => x.remove());
}

function installKnowledgeBaseCitationChipHandlers(){
  if(window.__webaiKnowledgeBaseCitationChipHandlersInstalled) return;
  window.__webaiKnowledgeBaseCitationChipHandlersInstalled = true;
  ensureKnowledgeBaseCitationUiStyle();
  document.addEventListener('click', (e)=>{
    const btn = e.target?.closest?.('.kb-citation-chip');
    if(!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const bubble = btn.closest('.bubble.a');
    const label = normalizeAssistantCitationLabel(btn.dataset.kbCitationLabel || btn.textContent || '');
    const source = bubble ? findKnowledgeBaseCitationSourceForBubble(bubble, label) : null;
    showKnowledgeBaseCitationPreview(btn, label, source);
  }, true);
  document.addEventListener('click', ()=>closeKnowledgeBaseCitationPopover());
  document.addEventListener('keydown', (e)=>{
    if(e.key === 'Escape' && activeKnowledgeBaseCitationPopover) closeKnowledgeBaseCitationPopover();
  });
  window.addEventListener('resize', ()=>{
    if(activeKnowledgeBaseCitationAnchor && activeKnowledgeBaseCitationPopover) positionKnowledgeBaseCitationPopover(activeKnowledgeBaseCitationAnchor, activeKnowledgeBaseCitationPopover);
  });
  window.addEventListener('scroll', ()=>{
    if(activeKnowledgeBaseCitationAnchor && activeKnowledgeBaseCitationPopover) positionKnowledgeBaseCitationPopover(activeKnowledgeBaseCitationAnchor, activeKnowledgeBaseCitationPopover);
  }, true);
}

installKnowledgeBaseCitationChipHandlers();
function isAssistantLocalSourceUrl(url){
  const raw = trimUrl(url || '');
  if(!raw) return false;
  try{
    const parsed = new URL(raw, window.location.origin);
    const path = String(parsed.pathname || '').trim().toLowerCase();
    if(parsed.origin !== window.location.origin) return false;
    return path.startsWith('/api3/download/')
      || path.startsWith('/api3/uploads/')
      || path.startsWith('/api3/generated-download/')
      || path.startsWith('/api3/generated-files/')
      || path.startsWith('/api3/generated-download-id/')
      || path.startsWith('/api3/generated-files-id/');
  }catch(_){
    return false;
  }
}
function normalizeAssistantSourceItems(items){
  const out = [];
  const seen = new Set();
  const pushOne = (item)=>{
    if(!item || typeof item !== 'object') return;
    const rawUrl = trimUrl(item.url || item.href || '');
    const explicitType = String(item.source_type || item.sourceType || item.kind || '').trim().toLowerCase();
    const citationLabel = normalizeAssistantCitationLabel(item.citation_label || item.citationLabel || item.label || '');
    const snippet = String(item.snippet || item.text || item.preview || '').trim();
    let localSourceType = explicitType;
    if(rawUrl){
      const meta = _assistantResolvedUrlMeta(rawUrl);
      if(meta.sourceType) localSourceType = meta.sourceType;
    }
    if(!localSourceType && citationLabel) localSourceType = 'file';
    const localLike = !!citationLabel || isAssistantLocalSourceUrl(rawUrl) || ['file','upload','generated','kb','local_file'].includes(localSourceType);
    if(localLike){
      const titleSeed = String(item.title || item.filename || '').trim();
      const fallbackTitle = citationLabel ? citationLabel.split('#片段')[0].replace(/[《》]/g, '').trim() : '';
      const title = String(titleSeed || fallbackTitle || rawUrl || markdownUiT('citation.local_source', null, 'Local source')).trim().slice(0, 160);
      const normalizedType = localSourceType || 'file';
      const key = `local:${normalizedType}|${citationLabel.toLowerCase()}|${rawUrl.toLowerCase()}|${title.toLowerCase()}`;
      if(seen.has(key)) return;
      seen.add(key);
      out.push({
        sourceType: normalizedType,
        title,
        url: rawUrl.slice(0, 500),
        host: '',
        favicon: '',
        citationLabel: citationLabel.slice(0, 200),
        snippet: snippet.slice(0, 600),
      });
      return;
    }
    if(!isAssistantVisibleCitationUrl(rawUrl)) return;
    const host = String(item.host || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase();
    const title = normalizeAssistantSourceTitle(item.title || item.label || '', rawUrl, host);
    const favicon = String(item.favicon || item.icon || item.iconUrl || item.icon_url || '').trim();
    const genericTitle = !title || title.toLowerCase() === host;
    const key = (genericTitle && host)
      ? `host:${host}`
      : `url:${rawUrl.toLowerCase()}||title:${String(title || '').toLowerCase()}`;
    if(seen.has(key)) return;
    seen.add(key);
    out.push({
      sourceType: 'web',
      title: String(title || host || rawUrl).slice(0, 160),
      url: rawUrl.slice(0, 500),
      host: host.slice(0, 120),
      favicon: favicon.slice(0, 1000),
      citationLabel: citationLabel.slice(0, 200),
      snippet: snippet.slice(0, 600),
    });
  };
  (Array.isArray(items) ? items : []).forEach(pushOne);
  return out.slice(0, 8);
}
function mergeAssistantSourceItems(baseItems, incomingItems){
  const combined = [
    ...(Array.isArray(baseItems) ? baseItems : []),
    ...(Array.isArray(incomingItems) ? incomingItems : []),
  ];
  const faviconByKey = new Map();
  for(const item of combined){
    if(!item || typeof item !== 'object') continue;
    const favicon = String(item.favicon || item.icon || item.iconUrl || item.icon_url || '').trim();
    if(!favicon) continue;
    const rawUrl = trimUrl(item.url || item.href || '');
    const host = String(item.host || item.domain || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
    if(rawUrl) faviconByKey.set(`url:${rawUrl.toLowerCase()}`, favicon);
    if(host) faviconByKey.set(`host:${host}`, favicon);
  }
  return normalizeAssistantSourceItems(combined).map(item=>{
    const rawUrl = trimUrl(item.url || item.href || '');
    const host = String(item.host || item.domain || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
    const favicon = (rawUrl ? faviconByKey.get(`url:${rawUrl.toLowerCase()}`) : '')
      || (host ? faviconByKey.get(`host:${host}`) : '')
      || String(item.favicon || '').trim();
    return favicon && favicon !== item.favicon ? { ...item, favicon:favicon.slice(0, 1000) } : item;
  });
}
function extractAssistantSourceItemsFromText(text, limit=8){
  const raw = String(text || '');
  if(!raw) return [];
  const out = [];
  const seen = new Set();
  const pushOne = (url, title='')=>{
    const rawUrl = trimUrl(url || '');
    if(!isAssistantVisibleCitationUrl(rawUrl)) return;
    const host = String(getAssistantSourceHost(rawUrl) || '').trim().toLowerCase();
    const normalizedTitle = normalizeAssistantSourceTitle(title || '', rawUrl, host);
    const key = `${rawUrl.toLowerCase()}|${String(normalizedTitle || '').toLowerCase()}`;
    if(seen.has(key)) return;
    seen.add(key);
    out.push({ title: normalizedTitle || host || rawUrl, url: rawUrl, host });
  };
  const mdRe = /\[([^\]]{1,160})\]\((https?:\/\/[^\s)]+)\)/g;
  let m;
  while((m = mdRe.exec(raw))){
    pushOne(m[2], m[1]);
    if(out.length >= limit) return normalizeAssistantSourceItems(out.slice(0, limit));
  }
  const plainRe = /https?:\/\/[^\s<>")\]]+/g;
  while((m = plainRe.exec(raw))){
    pushOne(m[0], '');
    if(out.length >= limit) break;
  }
  return normalizeAssistantSourceItems(out.slice(0, limit));
}
function hydrateAssistantSourceFavicons(items, faviconItems){
  const normalized = normalizeAssistantSourceItems(items);
  const faviconByKey = new Map();
  for(const item of (Array.isArray(faviconItems) ? faviconItems : [])){
    if(!item || typeof item !== 'object') continue;
    const favicon = String(item.favicon || item.icon || item.iconUrl || item.icon_url || '').trim();
    if(!favicon) continue;
    const rawUrl = trimUrl(item.url || item.href || '');
    const host = String(item.host || item.domain || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
    if(rawUrl) faviconByKey.set(`url:${rawUrl.toLowerCase()}`, favicon);
    if(host) faviconByKey.set(`host:${host}`, favicon);
  }
  return normalized.map(item=>{
    const rawUrl = trimUrl(item.url || item.href || '');
    const host = String(item.host || item.domain || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
    const favicon = (rawUrl ? faviconByKey.get(`url:${rawUrl.toLowerCase()}`) : '')
      || (host ? faviconByKey.get(`host:${host}`) : '')
      || String(item.favicon || '').trim();
    return favicon && favicon !== item.favicon ? { ...item, favicon:favicon.slice(0, 1000) } : item;
  });
}
function getAssistantMessageSourceItems(msg){
  const raw = (msg && typeof msg === 'object') ? msg : {};
  if(Object.prototype.hasOwnProperty.call(raw, 'sourceBound') && !raw.sourceBound) return [];
  const content = typeof raw.content === 'string' ? raw.content : '';
  const kbFromMessage = collectKnowledgeBaseCitationSourcesFromMessage(raw);
  const direct = normalizeAssistantSourceItems(raw.sources || raw.references || raw.citations || []);
  const sid = String(raw.session_id || raw.sessionId || visibleChatSessionId || store?.activeId || '').trim();
  const derived = deriveAssistantCitationSources(sid, content, kbFromMessage);
  const sourceItems = mergeAssistantSourceItems([...kbFromMessage, ...direct], derived);
  let activitySourceItems = [];
  try{
    if(typeof _activitySourcesFromSnapshot === 'function') activitySourceItems = _activitySourcesFromSnapshot(raw);
  }catch(_){ activitySourceItems = []; }
  return hydrateAssistantSourceFavicons(sourceItems, activitySourceItems);
}

const FILE_CITATION_CONTEXT_EXTS = new Set([
  'txt','md','json','jsonl','csv','tsv','log','cfg','py','c','cc','cpp','cxx','h','hpp',
  'js','mjs','cjs','ts','tsx','jsx','mts','cts','java','go','rs','php','rb','swift','kt','cs',
  'sql','yaml','yml','xml','toml','ini','sh','bat','ps1','proto','properties','conf','gradle','plist','ipynb',
  'html','htm','css','scss','less','svg','vue','svelte','astro'
]);
function shouldUseCitationFileContext(pf){
  const ext = String(pf?.ext || '').trim().toLowerCase().replace(/^\./, '');
  return !!String(pf?.text || '').trim() && FILE_CITATION_CONTEXT_EXTS.has(ext);
}
function splitTextForCitationContext(text, targetChars=1200, overlap=140){
  const raw = String(text || '').replace(/\r\n?/g, '\n').trim();
  if(!raw) return [];
  let paras = raw.split(/\n{2,}/).map(s => String(s || '').trim()).filter(Boolean);
  if(!paras.length) paras = [raw];
  const chunks = [];
  let buf = '';
  const maxChars = Math.max(600, Number(targetChars || 1200) || 1200);
  const keepOverlap = Math.max(0, Number(overlap || 140) || 140);
  for(const para of paras){
    if(!buf){
      buf = para;
      continue;
    }
    if((buf.length + 2 + para.length) <= maxChars){
      buf += '\n\n' + para;
    }else{
      chunks.push(buf.trim());
      const prefix = keepOverlap > 0 && buf.length > keepOverlap ? buf.slice(-keepOverlap).trim() : '';
      buf = prefix ? `${prefix}\n\n${para}`.trim() : para;
    }
  }
  if(buf.trim()) chunks.push(buf.trim());
  if(chunks.length <= 1 && raw.length > maxChars){
    const fallback = [];
    const step = Math.max(500, maxChars - keepOverlap);
    const size = Math.max(700, maxChars);
    for(let start = 0; start < raw.length; start += step){
      const piece = raw.slice(start, start + size).trim();
      if(piece) fallback.push(piece);
      if(fallback.length >= 64) break;
    }
    return fallback;
  }
  return chunks.slice(0, 64);
}

function buildUploadedFileCitationSystemNote(pf){
  const filename = String(pf?.filename || '未命名文件').trim() || '未命名文件';
  // 前端这里只提供文件读取状态和可引用预览；完整符号清单由后端基于
  // file_registry/full_text 重新扫描注入，避免前端预览符号不完整时误导模型。
  const chunks = splitTextForCitationContext(String(pf?.text || ''), 1200, 140);
  const parsedChars = Number(pf?.parsed_chars || pf?.file_registry?.full_text_chars || 0) || 0;
  const previewChars = String(pf?.text || '').length;
  const previewOnly = !!pf?.text_is_preview || (parsedChars > 0 && previewChars > 0 && previewChars < parsedChars);
  const fullTextKnown = !!pf?.full_text_available || !!pf?.file_registry?.full_text_available;
  const fileReadStatus = fullTextKnown
    ? `文件读取状态：服务端已保存原始文件和完整可解析文本${parsedChars ? `，完整解析约 ${parsedChars} 字符` : ''}；当前前端随消息只附带${previewOnly ? '预览/索引片段' : '可引用正文'}，后端会在回答前按需重新抽取完整文件上下文。`
    : '';
  const fileIndexText = [fileReadStatus, fullTextKnown ? '完整函数/类/脚本符号清单由后端在回答前从完整文件重新扫描注入；不要只依据前端预览判断文件结构。' : ''].filter(Boolean).join('\n');
  if(!chunks.length){
    return `以下是用户上传文件《${filename}》的内容，请在后续对话中参考：${fileIndexText ? '\n\n' + fileIndexText : ''}

${String(pf?.text || '')}`;
  }
  const lines = [
    `以下是用户上传文件《${filename}》的可引用片段，请在后续对话中优先基于这些片段回答。`,
    fileIndexText,
    `如果使用了文件里的事实，请在对应句末附上 [文件引用: ${filename}#片段N]。`,
    fullTextKnown ? '不要因为这里是片段就说无法读取文件；服务端会继续从完整文件中补充上下文。只有当前分段确实不足以覆盖用户要求时，才说明缺口。' : '如果现有片段不足以支撑结论，就明确说“文件证据不足”，不要编造。',
  ].filter(Boolean);
  chunks.forEach((piece, idx)=>{
    const citation = `${filename}#片段${idx + 1}`;
    lines.push(`### 文件片段 ${idx + 1}`);
    lines.push(`引用标记：[文件引用: ${citation}]`);
    lines.push(piece);
  });
  return lines.join('\n\n');
}
function parseUploadedFileCitationSystemNote(content){
  const text = String(content || '').trim();
  if(!text) return null;
  const matched = text.match(new RegExp('^以下是用户上传文件《(.+?)》的(?:可引用片段|内容)[^\\n：:]*[：:]?\\s*([\\s\\S]*)$'));
  if(!matched) return null;
  const filename = String(matched[1] || '').trim();
  const body = String(matched[2] || '').trim();
  const chunks = [];
  const re = new RegExp('###\\s*文件片段\\s*(\\d+)\\s*\\n+引用标记：\\[文件引用:\\s*([^\\]]+)\\]\\s*\\n([\\s\\S]*?)(?=\\n###\\s*文件片段\\s*\\d+\\s*\\n+引用标记：\\[文件引用:|$)', 'g');
  let mm;
  while((mm = re.exec(body))){
    const citation = normalizeAssistantCitationLabel(mm[2]);
    const piece = String(mm[3] || '').trim();
    if(!piece) continue;
    chunks.push({
      chunkOrder: Math.max(0, Number(mm[1] || chunks.length + 1) - 1),
      citationLabel: citation || `${filename}#片段${chunks.length + 1}`,
      text: piece,
    });
  }
  if(!chunks.length && body){
    splitTextForCitationContext(body, 1200, 140).forEach((piece, idx)=>{
      chunks.push({ chunkOrder: idx, citationLabel: `${filename}#片段${idx + 1}`, text: piece });
    });
  }
  return { filename, chunks };
}

function collectSessionFileCitationSourceMap(sessionId){
  const sid = String(sessionId || store?.activeId || '').trim();
  const s = sid ? getSessionById(sid) : null;
  const msgs = Array.isArray(s?.messages) ? s.messages : [];
  const uploadById = new Map();
  const uploadByName = new Map();
  const pushByName = (item)=>{
    const nameKey = String(item?.filename || '').trim().toLowerCase();
    if(nameKey && !uploadByName.has(nameKey)) uploadByName.set(nameKey, item);
  };
  for(const msg of msgs){
    const content = msg?.content;
    if(msg?.role === 'user' && content && typeof content === 'object' && !Array.isArray(content) && content._kind === 'file'){
      const rec = {
        filename: String(content.filename || '').trim(),
        url: String(content.url || content.download_url || content.view_url || '').trim(),
        view_url: String(content.view_url || '').trim(),
      };
      const id = String(content.id || '').trim();
      if(id) uploadById.set(id, rec);
      pushByName(rec);
    }
  }
  const out = new Map();
  const addOne = (source)=>{
    const label = normalizeAssistantCitationLabel(source?.citation_label || source?.citationLabel || '');
    if(!label) return;
    for(const key of normalizeAssistantCitationLookupKeys(label)){
      if(!out.has(key)) out.set(key, source);
    }
  };
  for(const msg of msgs){
    if(msg?.role !== 'system') continue;
    const parsed = parseUploadedFileCitationSystemNote(msg?.content);
    if(!parsed) continue;
    const linked = uploadById.get(String(msg?._link || '').trim()) || uploadByName.get(String(parsed.filename || '').trim().toLowerCase()) || null;
    const fileUrl = String(linked?.url || linked?.view_url || '').trim();
    for(const chunk of (Array.isArray(parsed.chunks) ? parsed.chunks : [])){
      addOne({
        source_type: 'file',
        title: parsed.filename,
        filename: parsed.filename,
        url: fileUrl,
        citation_label: String(chunk?.citationLabel || `${parsed.filename}#片段${Number(chunk?.chunkOrder || 0) + 1}`),
        snippet: String(chunk?.text || '').trim(),
      });
    }
  }
  return out;
}
function normalizeKnowledgeBaseCitationSourceItems(items, limit=24){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const out = [];
  const seen = new Set();
  const maxItems = Math.max(1, Math.min(Number(limit || 24) || 24, 60));
  for(const raw of source){
    if(!raw || typeof raw !== 'object') continue;
    const kbDocumentFallback = markdownUiT('citation.kb_document', null, 'Knowledge-base document');
    const filename = String(raw.filename || raw.document_name || raw.doc_name || raw.title || kbDocumentFallback).trim() || kbDocumentFallback;
    const chunkRaw = Number(raw.chunk_order ?? raw.chunk ?? raw.chunkIndex ?? raw.chunk_index ?? 0);
    const chunk = Number.isFinite(chunkRaw) ? Math.max(0, Math.floor(chunkRaw)) : 0;
    const labelSeed = String(raw.citation_label || raw.citationLabel || raw.citation || raw.ref || '').trim();
    const citation = normalizeAssistantCitationLabel(labelSeed || (chunk > 0 ? `《${filename}》#片段${chunk}` : ''));
    const snippet = String(raw.text || raw.snippet || raw.content || raw.preview || raw.chunk_text || raw.chunkText || '').trim();
    const url = String(raw.view_url || raw.viewUrl || raw.download_url || raw.downloadUrl || raw.url || raw.href || '').trim();
    if(!citation && !filename && !snippet) continue;
    const key = `${citation}|${filename}|${url}|${snippet.slice(0, 120)}`.toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    out.push({
      source_type: 'kb',
      title: filename.slice(0, 180),
      filename: filename.slice(0, 220),
      doc_id: String(raw.doc_id || raw.document_id || raw.kb_doc_id || '').trim().slice(0, 160),
      chunk_order: chunk,
      url: url.slice(0, 500),
      citation_label: citation.slice(0, 220),
      snippet: snippet.slice(0, 1600),
    });
    if(out.length >= maxItems) break;
  }
  return out;
}

function collectKnowledgeBaseCitationSourceMap(extraItems){
  const search = (typeof kbRuntime !== 'undefined' && kbRuntime && typeof kbRuntime === 'object') ? (kbRuntime.search || {}) : {};
  const runtimeSearchItems = Array.isArray(search?.results) ? search.results : [];
  const normalizedItems = normalizeKnowledgeBaseCitationSourceItems([
    ...(Array.isArray(extraItems) ? extraItems : []),
    ...runtimeSearchItems,
  ], 60);
  const out = new Map();
  const addOne = (source)=>{
    const label = normalizeAssistantCitationLabel(source?.citation_label || source?.citationLabel || '');
    if(!label) return;
    for(const key of normalizeAssistantCitationLookupKeys(label)){
      if(!out.has(key) || (!String(out.get(key)?.snippet || '').trim() && String(source?.snippet || '').trim())) out.set(key, source);
    }
  };
  for(const item of normalizedItems) addOne(item);
  return out;
}

function collectKnowledgeBaseCitationSourcesFromMessage(msg){
  const raw = (msg && typeof msg === 'object') ? msg : {};
  const meta = (raw.reasoningMeta && typeof raw.reasoningMeta === 'object') ? raw.reasoningMeta
    : ((raw.reasoning_meta && typeof raw.reasoning_meta === 'object') ? raw.reasoning_meta : {});
  const candidates = [];
  const pushList = (value)=>{
    if(Array.isArray(value)) candidates.push(...value);
  };
  pushList(meta.kbSearchResults || meta.kb_search_results || meta.knowledge_results || meta.knowledgeResults);
  pushList(raw.kbSearchResults || raw.kb_search_results || raw.knowledge_results || raw.knowledgeResults);
  pushList(meta.kb_results || meta.kbResults);
  return normalizeKnowledgeBaseCitationSourceItems(candidates, 40);
}
function extractAssistantCitationRefsFromText(text){
  const raw = String(text || '');
  if(!raw) return [];
  const out = [];
  const seen = new Set();
  const re = /\[(文件引用|知识库引用)\s*:\s*([^\]]+)\]/g;
  let m;
  while((m = re.exec(raw))){
    const refType = String(m[1] || '').trim() === '知识库引用' ? 'kb' : 'file';
    const label = normalizeAssistantCitationLabel(m[2]);
    const key = `${refType}|${label.toLowerCase()}`;
    if(!label || seen.has(key)) continue;
    seen.add(key);
    out.push({ type: refType, label });
  }
  return out;
}
function deriveAssistantCitationSources(sessionId, text, extraKbItems=[]){
  const refs = extractAssistantCitationRefsFromText(text);
  if(!refs.length) return [];
  const fileMap = collectSessionFileCitationSourceMap(sessionId);
  const kbMap = collectKnowledgeBaseCitationSourceMap(extraKbItems);
  const out = [];
  for(const ref of refs){
    let found = null;
    const keys = normalizeAssistantCitationLookupKeys(ref.label);
    if(ref.type === 'file'){
      for(const key of keys){ if(fileMap.has(key)){ found = fileMap.get(key); break; } }
      if(found){ out.push(found); continue; }
      const title = ref.label.split('#片段')[0].replace(/[《》]/g, '').trim() || markdownUiT('citation.local_file', null, 'Local file');
      out.push({ source_type:'file', title, citation_label: ref.label, url:'' });
      continue;
    }
    for(const key of keys){ if(kbMap.has(key)){ found = kbMap.get(key); break; } }
    if(found){ out.push(found); continue; }
    const title = ref.label.split('#片段')[0].replace(/[《》]/g, '').trim() || markdownUiT('citation.kb_document', null, 'Knowledge-base document');
    out.push({ source_type:'kb', title, citation_label: ref.label, url:'' });
  }
  return normalizeAssistantSourceItems(out);
}

function assistantSourceTypeLabel(item){
  const t = String(item?.sourceType || '').trim().toLowerCase();
  if(t === 'generated') return markdownUiT('citation.generated_file', null, 'Generated file');
  if(t === 'kb') return markdownUiT('citation.kb_document', null, 'Knowledge-base document');
  if(t === 'upload' || t === 'file' || t === 'local_file') return markdownUiT('citation.uploaded_file', null, 'Uploaded file');
  return '';
}

function buildAssistantSourcesNode(items){
  const list = normalizeAssistantSourceItems(items);
  if(!list.length) return null;
  const wrap = document.createElement('div');
  wrap.className = 'bubble-sources bubble-sources-collapsible';

  const sourceGlyph = (item)=>{
    const t = String(item?.sourceType || '').trim().toLowerCase();
    if(t === 'generated') return '🧾';
    if(t === 'kb') return '🗂';
    if(t === 'upload' || t === 'file' || t === 'local_file') return '📎';
    return getAssistantSourceIconFallback(item);
  };
  const subLabelForItem = (item)=>{
    const citation = normalizeAssistantCitationLabel(item?.citationLabel || '');
    if(citation) return citation;
    const typeLabel = assistantSourceTypeLabel(item);
    if(typeLabel) return typeLabel;
    return shouldShowAssistantSourceHost(item) ? String(item?.host || '').trim() : '';
  };
  const appendSourceIcon = (target, item, extraClass='')=>{
    if(!target) return null;
    const icon = document.createElement('span');
    icon.className = ('bubble-source-icon' + (extraClass ? ' ' + extraClass : '')).trim();
    const isWeb = String(item?.sourceType || '').trim().toLowerCase() === 'web';
    if(isWeb){
      const ok = bindAssistantSourceFavicon(icon, item);
      if(!ok) return null;
    }else{
      const iconFallback = document.createElement('span');
      iconFallback.className = 'bubble-source-icon-fallback';
      iconFallback.textContent = sourceGlyph(item);
      icon.appendChild(iconFallback);
    }
    target.appendChild(icon);
    return icon;
  };

  if(!buildAssistantSourcesNode._seq) buildAssistantSourcesNode._seq = 1;
  const panelId = `assistantSourcePanel-${buildAssistantSourcesNode._seq++}`;

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'bubble-sources-pill';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', panelId);
  toggle.title = markdownUiT('citation.source_count', {count:list.length}, '{count} sources');

  const iconStack = document.createElement('span');
  iconStack.className = 'bubble-source-icon-stack';
  list.slice(0, 3).forEach(item => appendSourceIcon(iconStack, item, 'bubble-source-icon-stack-item'));
  if(list.length > 3){
    const more = document.createElement('span');
    more.className = 'bubble-source-icon-more';
    more.textContent = `+${list.length - 3}`;
    iconStack.appendChild(more);
  }
  toggle.appendChild(iconStack);

  const pillText = document.createElement('span');
  pillText.className = 'bubble-sources-pill-text';
  pillText.textContent = markdownUiT('citation.sources', null, 'Sources');
  toggle.appendChild(pillText);

  const caret = document.createElement('span');
  caret.className = 'bubble-sources-pill-caret';
  caret.textContent = '⌄';
  toggle.appendChild(caret);
  wrap.appendChild(toggle);

  const detail = document.createElement('div');
  detail.id = panelId;
  detail.className = 'bubble-sources-detail';
  detail.hidden = true;

  const head = document.createElement('div');
  head.className = 'bubble-sources-detail-head';
  head.textContent = markdownUiT('citation.source_count', {count:list.length}, '{count} sources');
  detail.appendChild(head);

  const rows = document.createElement('div');
  rows.className = 'bubble-source-detail-list';

  list.forEach((item, idx)=>{
    const href = trimUrl(item.url || '');
    const previewable = citationPreviewSourceIsLocal(item);
    const canLink = !!href && !previewable;
    const row = previewable ? document.createElement('button') : (canLink ? document.createElement('a') : document.createElement('span'));
    if(previewable) row.type = 'button';
    row.className = 'bubble-source-detail-row' + (previewable ? ' has-preview' : '');
    row.dataset.sourceType = String(item?.sourceType || '').trim().toLowerCase() || 'file';
    if(canLink){
      row.href = href;
      row.target = '_blank';
      row.rel = 'noopener noreferrer';
    }
    const tooltipParts = [item.title || item.host || item.url, subLabelForItem(item), String(item.snippet || '').trim()].filter(Boolean);
    if(tooltipParts.length) row.title = tooltipParts.join('\n');

    const number = document.createElement('span');
    number.className = 'bubble-source-detail-number';
    number.textContent = String(idx + 1);
    row.appendChild(number);

    const urlText = document.createElement('span');
    urlText.className = 'bubble-source-detail-url';
    const sourceFallback = markdownUiT('citation.source', null, 'Source');
    urlText.textContent = previewable ? (subLabelForItem(item) || item.title || href || sourceFallback) : (href || subLabelForItem(item) || item.title || item.host || sourceFallback);
    row.appendChild(urlText);

    if(previewable){
      row.addEventListener('click', (e)=>{
        e.preventDefault();
        e.stopPropagation();
        const label = citationPreviewLabelForSource(item);
        showKnowledgeBaseCitationPreview(row, label, item);
      });
    }

    rows.appendChild(row);
  });

  detail.appendChild(rows);
  wrap.appendChild(detail);

  toggle.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    const opening = detail.hidden;
    detail.hidden = !opening;
    wrap.classList.toggle('is-open', opening);
    toggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
  });

  return wrap;
}

function injectAssistantSourcesIntoBubble(bubble, msg){
  if(!bubble || !msg || typeof msg !== 'object') return;
  const isAssistant = bubble.classList.contains('a');
  if(!isAssistant) return;
  const body = bubble.querySelector('.bubble-body');
  if(!body) return;
  const existing = bubble.querySelector(':scope > .bubble-sources');
  if(existing) existing.remove();
  const sourceItems = getAssistantMessageSourceItems(msg);
  try{ assistantCitationSourceItemsByBubble.set(bubble, sourceItems); }catch(_){ }
  syncAssistantInlineSourceIcons(bubble);
  const node = buildAssistantSourcesNode(sourceItems);
  if(!node) return;
  body.insertAdjacentElement('afterend', node);
}

/* 📍 Geolocation (optional): used to disambiguate same-name places (pick nearest). */
const USER_GEO_CACHE_KEY = "webai_user_geo_v2";
const USER_GEO_MEMORY_TTL_MS = 60 * 1000;
const USER_GEO_PERSIST_TTL_MS = 12 * 60 * 60 * 1000;
let _geoCache = null;
let _geoCacheAt = 0;
let _lastGeoErrorMeta = null;
let _lastGeoNoticeKey = '';
let _lastGeoNoticeAt = 0;
let _browserGeoOneShotUntil = 0;
let _locationPermissionPromptPending = false;
let _lastLocationPermissionPromptAt = 0;

function setBubbleActionButtonIcon(btn, kind, label){
  if(!btn) return btn;
  const safeKind = String(kind || btn.dataset.actionKind || 'copy').trim() || 'copy';
  const safeLabel = String(label || btn.dataset.actionLabel || btn.dataset.restoreLabel || '').trim();
  btn.textContent = '';
  btn.appendChild(makeBubbleActionIcon(safeKind));
  if(safeLabel){
    btn.dataset.restoreLabel = safeLabel;
    btn.setAttribute('aria-label', safeLabel);
    btn.title = safeLabel;
  }
  return btn;
}

function flashButtonCopied(btn, text=markdownUiT('code.copied',null,'Copied')){
  if(!btn) return;
  const isBubbleAction = !!(btn.classList?.contains('bubble-copy') || btn.querySelector?.('.bubble-action-icon'));
  if(isBubbleAction){
    const restoreKind = String(btn.dataset.actionKind || 'copy').trim() || 'copy';
    const restoreLabel = String(btn.dataset.actionLabel || btn.dataset.restoreLabel || btn.getAttribute('aria-label') || btn.title || '').trim();
    const feedbackLabel=String(text||markdownUiT('code.copied',null,'Copied')).trim()||markdownUiT('code.copied',null,'Copied');
    btn.classList.add('copied');
    setBubbleActionButtonIcon(btn, 'check', feedbackLabel);
    clearTimeout(btn._copiedTimer);
    btn._copiedTimer = setTimeout(()=>{
      btn.classList.remove('copied');
      setBubbleActionButtonIcon(btn, restoreKind, restoreLabel || markdownUiT('message.copy', null, 'Copy'));
    }, 1200);
    return;
  }
  const old = btn.dataset.restoreLabel || btn.textContent;
  btn.textContent = text;
  btn.classList.add('copied');
  clearTimeout(btn._copiedTimer);
  btn._copiedTimer = setTimeout(()=>{
    btn.textContent=old||markdownUiT('code.copy',null,'Copy code');
    btn.classList.remove('copied');
  }, 1200);
}

function makeBubbleActionIcon(kind){
  const span = document.createElement('span');
  span.className = 'bubble-action-icon';
  const map = {
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="10" height="10" rx="2"></rect><path d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.2 4.2L19 7"></path></svg>',
    edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l4.2-1 9.3-9.3a1.8 1.8 0 0 0 0-2.5l-.7-.7a1.8 1.8 0 0 0-2.5 0L5 15.8 4 20z"></path><path d="M13.5 7.5l3 3"></path></svg>',
    like: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 21H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h4v11z"></path><path d="M10 10l3.3-6a1.6 1.6 0 0 1 3 1v3h2.6a2.1 2.1 0 0 1 2.1 2.5l-1.1 6a2.1 2.1 0 0 1-2.1 1.7H10"></path></svg>',
    dislike: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h4a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-4V3z"></path><path d="M14 14l-3.3 6a1.6 1.6 0 0 1-3-1v-3H5.1A2.1 2.1 0 0 1 3 13.5l1.1-6a2.1 2.1 0 0 1 2.1-1.7H14"></path></svg>',
    continue: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4l10 8-10 8V4z"></path><path d="M19 5v14"></path></svg>',
    regenerate: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10a8 8 0 0 1 13.7-3.7L20 9"></path><path d="M20 4v5h-5"></path><path d="M20 14a8 8 0 0 1-13.7 3.7L4 15"></path><path d="M4 20v-5h5"></path></svg>',
    readaloud: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z"></path><path d="M16.5 8.5a5 5 0 0 1 0 7"></path><path d="M19 6a8 8 0 0 1 0 12"></path></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>',
    share: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4"></path><path d="m7.5 8.5 4.5-4.5 4.5 4.5"></path><path d="M5 13v6h14v-6"></path></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M6 7l1 14h10l1-14"></path><path d="M9 7V4h6v3"></path></svg>'
  };
  span.innerHTML = map[kind] || map.copy;
  return span;
}

function decorateBubbleActionButton(btn, kind, label){
  if(!btn) return btn;
  const safeKind = String(kind || 'copy').trim() || 'copy';
  const safeLabel = String(label || btn.textContent || '').trim();
  btn.dataset.actionKind = safeKind;
  btn.dataset.actionLabel = safeLabel;
  btn.dataset.restoreLabel = safeLabel;
  return setBubbleActionButtonIcon(btn, safeKind, safeLabel);
}


let mermaidRuntimePromise = null;
let mermaidConfigured = false;
let mermaidRenderSeq = 0;

function ensureMermaidDiagramStyles(){
  if(document.getElementById('webai-mermaid-diagram-style')) return;
  const style = document.createElement('style');
  style.id = 'webai-mermaid-diagram-style';
  style.textContent = `
.mermaid-block{overflow:hidden;}
.mermaid-block .mermaid-render{margin:0;padding:18px 18px 20px;border-top:1px solid color-mix(in srgb,var(--border) 92%,transparent);background:color-mix(in srgb,var(--card) 94%,var(--panel));overflow:auto;min-height:112px;max-height:min(72vh,760px);box-sizing:border-box;color:var(--fg);scrollbar-gutter:stable;}
.mermaid-block .mermaid-render svg{display:block;max-width:none;width:auto;height:auto;margin:0 auto;color:var(--fg);}
.mermaid-block .mermaid-source{display:none;}
.mermaid-block.is-source-visible .mermaid-render{display:none;}
.mermaid-block.is-source-visible .mermaid-source{display:block;}
.mermaid-block.is-mermaid-error .mermaid-render{min-height:auto;padding:12px 14px;background:color-mix(in srgb,var(--panel) 82%,transparent);}
.mermaid-block.is-mermaid-error .mermaid-source{display:block;}
.mermaid-error-note{font-size:13px;line-height:1.45;color:var(--muted);}
.table-wrap{position:relative;max-width:100%;margin:8px 0 14px;border:0;border-radius:0;background:transparent;overflow:visible;}
.table-scroll{max-width:100%;overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch;scrollbar-gutter:stable;}
.table-copy{position:absolute;top:2px;right:0;z-index:3;opacity:.42;transition:opacity .15s ease,background .15s ease,color .15s ease;}
.table-wrap:hover .table-copy,.table-wrap:focus-within .table-copy{opacity:1;}
.bubble-body .table-wrap table{width:max-content!important;min-width:100%!important;table-layout:auto!important;margin:0;border:0!important;border-radius:0!important;background:transparent!important;border-collapse:collapse!important;border-spacing:0!important;}
.bubble-body .table-wrap th,.bubble-body .table-wrap td{padding:12px 18px;border:0!important;border-bottom:1px solid color-mix(in srgb,var(--border) 72%,transparent)!important;text-align:left;vertical-align:top;font-size:14px;line-height:1.72;white-space:nowrap;word-break:normal!important;overflow-wrap:normal!important;background:transparent!important;}
.bubble-body .table-wrap th{font-weight:800;color:var(--fg);}
.bubble-body .table-wrap td{max-width:460px;white-space:normal;color:var(--fg);}
.bubble-body .table-wrap th:first-child,.bubble-body .table-wrap td:first-child{padding-left:0;}
.bubble-body .table-wrap th:last-child,.bubble-body .table-wrap td:last-child{padding-right:46px;}
.bubble-body .table-wrap tbody tr:last-child td{border-bottom:1px solid color-mix(in srgb,var(--border) 46%,transparent)!important;}
.math-display{display:block;max-width:100%;overflow-x:auto;overflow-y:hidden;padding:2px 0;margin:8px 0 12px;}
.math-display .katex-display{margin:.35em 0;}
.math-inline{max-width:100%;}
.math-fallback{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:color-mix(in srgb,var(--panel) 70%,transparent);border:1px solid color-mix(in srgb,var(--border) 86%,transparent);border-radius:8px;padding:1px 5px;}
.math-display.math-fallback{padding:9px 11px;white-space:pre-wrap;}
.mermaid-preview-modal{position:fixed;inset:0;z-index:260;display:none;align-items:center;justify-content:center;padding:28px;background:rgba(0,0,0,.58);box-sizing:border-box;}
.mermaid-preview-modal.open{display:flex;}
.mermaid-preview-card{width:min(1180px,96vw);height:min(860px,92vh);display:flex;flex-direction:column;overflow:hidden;border-radius:22px;border:1px solid color-mix(in srgb,var(--outline) 16%,var(--border));background:var(--card);box-shadow:0 24px 80px rgba(0,0,0,.34);}
.mermaid-preview-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--panel) 70%,var(--card));}
.mermaid-preview-title{min-width:0;font-size:14px;font-weight:800;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.mermaid-preview-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto;}
.mermaid-preview-body{flex:1;min-height:0;overflow:auto;padding:20px;background:color-mix(in srgb,var(--bg) 92%,var(--panel));}
.mermaid-preview-body svg{display:block;max-width:none;width:auto;height:auto;margin:0 auto;color:var(--fg);}
.mermaid-preview-source{white-space:pre;min-width:max-content;margin:0;padding:14px;border-radius:14px;border:1px solid var(--border);background:color-mix(in srgb,var(--panel) 82%,transparent);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;line-height:1.55;color:var(--fg);}
@media (max-width:720px){.mermaid-preview-modal{padding:12px}.mermaid-preview-card{width:100%;height:92vh;border-radius:18px}.table-copy{opacity:.7}.bubble-body .table-wrap table{width:max-content!important;min-width:100%!important;table-layout:auto!important}.bubble-body .table-wrap th,.bubble-body .table-wrap td{padding:10px 14px;font-size:13px}.bubble-body .table-wrap th:first-child,.bubble-body .table-wrap td:first-child{padding-left:0}.bubble-body .table-wrap th:last-child,.bubble-body .table-wrap td:last-child{padding-right:42px}.bubble-body .table-wrap td{max-width:260px}}
`;
  document.head.appendChild(style);
}

function getCurrentMermaidTheme(){
  try{
    const theme = String(document.documentElement.getAttribute('data-theme') || '').toLowerCase();
    return theme === 'dark' ? 'dark' : 'default';
  }catch(_){
    return 'default';
  }
}

function configureMermaidRuntime(force=false){
  const mermaid = window.mermaid;
  if(!mermaid) return mermaid;
  const theme = getCurrentMermaidTheme();
  if(!force && mermaidConfigured && configureMermaidRuntime._theme === theme) return mermaid;
  try{
    mermaid.initialize({
      startOnLoad:false,
      securityLevel:'strict',
      theme,
      flowchart:{ useMaxWidth:false, htmlLabels:false },
      sequence:{ useMaxWidth:false },
      gantt:{ useMaxWidth:false }
    });
    mermaidConfigured = true;
    configureMermaidRuntime._theme = theme;
  }catch(_){ }
  return mermaid;
}

function ensureMermaidRuntime(){
  if(window.mermaid) return Promise.resolve(configureMermaidRuntime());
  if(mermaidRuntimePromise) return mermaidRuntimePromise;
  mermaidRuntimePromise = new Promise((resolve, reject)=>{
    const existing = document.querySelector('script[data-webai-mermaid-runtime="1"]');
    if(existing){
      existing.addEventListener('load', ()=> resolve(configureMermaidRuntime()), { once:true });
      existing.addEventListener('error', ()=> reject(new Error('mermaid_load_failed')), { once:true });
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    script.async = true;
    script.defer = true;
    script.dataset.webaiMermaidRuntime = '1';
    script.onload = ()=> resolve(configureMermaidRuntime());
    script.onerror = ()=> reject(new Error('mermaid_load_failed'));
    document.head.appendChild(script);
  });
  return mermaidRuntimePromise;
}

function getMermaidBlockSource(block){
  const attr = String(block?.dataset?.mermaidSource || '').trim();
  if(attr){
    try{ return normalizeRunnableCodeSource(decodeURIComponent(attr)); }catch(_){ }
  }
  return getCodeBlockRawSource(block);
}

async function renderMermaidBlock(block, force=false){
  if(!block || (!force && (block.dataset.mermaidRendered === '1' || block.dataset.mermaidRendered === 'pending'))) return;
  const target = block.querySelector('[data-mermaid-render-target]');
  if(!target) return;
  const source = getMermaidBlockSource(block).trim();
  if(!source) return;
  block.dataset.mermaidRendered = 'pending';
  block.classList.remove('is-mermaid-error');
  target.innerHTML = escapeHtml(markdownUiT('code.rendering_diagram', null, 'Rendering diagram…'));
  try{
    const mermaid = await ensureMermaidRuntime();
    if(!block.isConnected) return;
    configureMermaidRuntime(force);
    if(!mermaid || typeof mermaid.render !== 'function') throw new Error('mermaid_unavailable');
    const id = `webai_mermaid_${Date.now()}_${++mermaidRenderSeq}`;
    let rendered = mermaid.render(id, source);
    if(rendered && typeof rendered.then === 'function') rendered = await rendered;
    const svg = typeof rendered === 'string' ? rendered : String(rendered?.svg || '');
    if(!svg.trim()) throw new Error('mermaid_empty_svg');
    target.innerHTML = svg;
    if(rendered && typeof rendered.bindFunctions === 'function'){
      try{ rendered.bindFunctions(target); }catch(_){ }
    }
    block.classList.add('is-mermaid-rendered');
    block.dataset.mermaidRendered = '1';
  }catch(err){
    if(!block.isConnected) return;
      target.innerHTML = `<div class="mermaid-error-note">${escapeHtml(markdownUiT('citation.mermaid_failed', null, 'Mermaid rendering failed. The source code is shown instead.'))}</div>`;
    block.classList.add('is-mermaid-error');
    block.dataset.mermaidRendered = 'error';
    try{ console.warn('Mermaid render failed:', err); }catch(_){ }
  }
}

function renderMermaidBlocks(root){
  if(!root) return;
  ensureMermaidDiagramStyles();
  root.querySelectorAll('.mermaid-block').forEach(block=>{
    if(block.dataset.mermaidRendered === '1' || block.dataset.mermaidRendered === 'pending') return;
    renderMermaidBlock(block);
  });
}

function rerenderMermaidBlocks(root=document){
  if(!root) return;
  try{ configureMermaidRuntime(true); }catch(_){ }
  root.querySelectorAll?.('.mermaid-block.is-mermaid-rendered').forEach(block=>{
    block.dataset.mermaidRendered = '';
    renderMermaidBlock(block, true);
  });
}

function ensureMermaidPreviewModal(){
  let modal = document.getElementById('mermaidPreviewModal');
  if(modal) return modal;
  modal = document.createElement('div');
  modal.id = 'mermaidPreviewModal';
  modal.className = 'mermaid-preview-modal';
  modal.setAttribute('aria-hidden', 'true');
  const previewTitle=markdownUiT('code.diagram_preview',null,'Diagram preview');
  modal.innerHTML=`<div class="mermaid-preview-card" role="dialog" aria-modal="true" aria-label="${escapeHtml(previewTitle)}"><div class="mermaid-preview-head"><div class="mermaid-preview-title">${escapeHtml(previewTitle)}</div><div class="mermaid-preview-actions"><button class="icon-btn" type="button" data-mermaid-modal-copy="1">${escapeHtml(markdownUiT('code.copy',null,'Copy code'))}</button><button class="icon-btn" type="button" data-mermaid-modal-close="1">${escapeHtml(markdownUiT('common.close',null,'Close'))}</button></div></div><div class="mermaid-preview-body" data-mermaid-modal-body="1"></div></div>`;
  modal.addEventListener('click', (e)=>{
    if(e.target === modal || e.target?.dataset?.mermaidModalClose === '1') closeMermaidPreviewModal();
    if(e.target?.dataset?.mermaidModalCopy === '1'){
      copyText(String(modal.dataset.mermaidSource || ''));
      flashButtonCopied(e.target,markdownUiT('code.copied',null,'Copied'));
    }
  });
  document.body.appendChild(modal);
  if(!ensureMermaidPreviewModal._keydownBound){
    ensureMermaidPreviewModal._keydownBound = true;
    document.addEventListener('keydown', (e)=>{
      if(e.key === 'Escape' && document.getElementById('mermaidPreviewModal')?.classList.contains('open')){
        e.preventDefault();
        closeMermaidPreviewModal();
      }
    });
  }
  return modal;
}

function closeMermaidPreviewModal(){
  const modal = document.getElementById('mermaidPreviewModal');
  if(!modal) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  modal.dataset.mermaidSource = '';
  const body = modal.querySelector('[data-mermaid-modal-body]');
  if(body) body.innerHTML = '';
  document.body.classList.remove('modal-open');
  if(closeMermaidPreviewModal._locked){
    document.body.style.overflow = closeMermaidPreviewModal._previousOverflow || '';
    closeMermaidPreviewModal._locked = false;
  }
}

async function openMermaidDiagramModal(block){
  if(!block) return;
  ensureMermaidDiagramStyles();
  await renderMermaidBlock(block);
  const modal = ensureMermaidPreviewModal();
  const body = modal.querySelector('[data-mermaid-modal-body]');
  if(!body) return;
  const source = getMermaidBlockSource(block);
  modal.dataset.mermaidSource = source || '';
  body.innerHTML = '';
  const svg = block.querySelector('[data-mermaid-render-target] svg');
  if(svg){
    body.appendChild(svg.cloneNode(true));
  }else{
    const pre = document.createElement('pre');
    pre.className = 'mermaid-preview-source';
    pre.textContent = source || '';
    body.appendChild(pre);
  }
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
  closeMermaidPreviewModal._previousOverflow = document.body.style.overflow || '';
  closeMermaidPreviewModal._locked = true;
  document.body.classList.add('modal-open');
  document.body.style.overflow = 'hidden';
}

function decodeDataAttributeText(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  try{ return decodeURIComponent(raw); }catch(_){ return raw; }
}

function getMarkdownTableText(wrap){
  const encoded = String(wrap?.dataset?.tableSource || '').trim();
  if(encoded) return decodeDataAttributeText(encoded);
  const table = wrap?.querySelector?.('table');
  if(!table) return '';
  const rows = Array.from(table.querySelectorAll('tr'));
  return rows.map(row => Array.from(row.children || []).map(cell => String(cell.textContent || '').trim()).join('\t')).join('\n');
}

function bindDisplayTableEnhancements(root){
  if(!root) return;
  root.querySelectorAll('[data-table-copy]').forEach(btn=>{
    if(btn.dataset.boundTableCopy === '1') return;
    btn.dataset.boundTableCopy = '1';
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      const wrap = btn.closest('.table-wrap');
      copyText(getMarkdownTableText(wrap));
      flashButtonCopied(btn,markdownUiT('code.copied',null,'Copied'));
    });
  });
}

function normalizeInlineImageLayouts(root){
  if(!root) return;

  root.querySelectorAll('.inline-img-grid').forEach(el=>{
    if(!el.classList.contains('inline-image-group')){
      el.classList.add('inline-image-group');
    }
  });

  root.querySelectorAll('.bubble-body p').forEach(p=>{
    if(p.querySelector('.inline-image-group')) return;
    const imgs = Array.from(p.querySelectorAll(':scope > img.inline-img'));
    if(!imgs.length) return;
    const meaningfulText = Array.from(p.childNodes || []).some(node=>{
      if(node.nodeType === Node.TEXT_NODE) return !!String(node.textContent || '').trim();
      if(node.nodeType === Node.ELEMENT_NODE){
        const tag = node.tagName;
        if(tag === 'IMG' && node.classList.contains('inline-img')) return false;
        if(tag === 'BR') return false;
        return !!String(node.textContent || '').trim();
      }
      return false;
    });
    if(meaningfulText) return;
    if(imgs.length === 1) return;
    const group = buildInlineImageGroup(imgs.map(img => ({
      url: img.getAttribute('src') || img.dataset.src || '',
      alt: img.getAttribute('alt') || '',
      caption: ''
    })));
    if(group) p.replaceWith(group);
  });

  root.querySelectorAll('.bubble-body img.inline-img').forEach(img=>{
    const standaloneWrap = img.closest('.inline-img-standalone');
    if(img.closest('.inline-image-group')){
      if(standaloneWrap) standaloneWrap.classList.remove('inline-img-standalone');
      img.classList.remove('inline-img-standalone');
      return;
    }
    if(img.parentElement && !img.parentElement.classList.contains('inline-img-standalone')){
      const wrapper = document.createElement('div');
      wrapper.className = 'inline-img-standalone';
      img.replaceWith(wrapper);
      wrapper.appendChild(img);
    }
  });

  const bubbleBody = root.classList?.contains('bubble-body') ? root : root.querySelector('.bubble-body') || root;
  const nodes = Array.from(bubbleBody.children || []);
  let run = [];

  const getSingleImagePayloadFromNode = (node)=>{
    if(!node || node.nodeType !== 1) return null;

    if(node.classList?.contains('inline-image-group')){
      const imgs = node.querySelectorAll(':scope .inline-image-cell img.inline-img');
      if(imgs.length !== 1) return null;
      const img = imgs[0];
      return {
        url: img.getAttribute('src') || img.dataset.src || '',
        alt: img.getAttribute('alt') || '',
        caption: ''
      };
    }

    const imgs = node.querySelectorAll('img.inline-img');
    if(imgs.length !== 1) return null;

    const text = String(node.textContent || '').trim();
    const imgAlt = String(imgs[0].getAttribute('alt') || '').trim();
    if(text && text !== imgAlt) return null;

    const img = imgs[0];
    return {
      url: img.getAttribute('src') || img.dataset.src || '',
      alt: img.getAttribute('alt') || '',
      caption: ''
    };
  };

  const flushRun = ()=>{
    if(run.length <= 1){
      run = [];
      return;
    }

    const images = run
      .map(node => getSingleImagePayloadFromNode(node))
      .filter(item => item && item.url);

    if(images.length <= 1){
      run = [];
      return;
    }

    const group = buildInlineImageGroup(images);
    if(group){
      run[0].before(group);
      run.forEach(node => node.remove());
    }
    run = [];
  };

  const isStandaloneImageBlock = (node)=>{
    return !!getSingleImagePayloadFromNode(node);
  };

  nodes.forEach(node=>{
    if(isStandaloneImageBlock(node)){
      run.push(node);
    }else{
      flushRun();
    }
  });
  flushRun();
}

function ensureInlineImageLoadVisibility(img){
  if(!img) return;
  const reveal = () => {
    img.classList.remove('is-loading');
    img.classList.add('is-loaded');
    try{ clearInlineImageFailedState(img); }catch(_){ }
    try{ markInlineImageMirrorVisible(img); }catch(_){ }
  };
  const hasRenderablePixels = () => !!(img.complete && (img.naturalWidth || 0) > 0 && (img.naturalHeight || 0) > 0);
  if(hasRenderablePixels()){
    reveal();
  }
  if(img.dataset.boundInlineLoadVisible !== '1'){
    img.dataset.boundInlineLoadVisible = '1';
    img.addEventListener('load', () => {
      if((img.naturalWidth || 0) > 0 && (img.naturalHeight || 0) > 0) reveal();
    });
    img.addEventListener('error', () => {
      img.classList.remove('is-loading');
    });
  }
  if(img.dataset.inlineLoadWatchdog !== '1'){
    img.dataset.inlineLoadWatchdog = '1';
    setTimeout(() => {
      if(!img.isConnected || !img.classList.contains('is-loading')) return;
      if(hasRenderablePixels()){
        reveal();
        return;
      }
      // Avoid keeping a large blank transparent box forever. If the browser has
      // not fired load/error, let the element become visible or fall back normally.
      img.classList.remove('is-loading');
    }, 1800);
  }
}

function bindBubbleEnhancements(root){
  if(!root) return;
  syncCodeRunAvailability(root);
  renderMermaidBlocks(root);
  bindDisplayTableEnhancements(root);
  normalizeInlineImageLayouts(root);
  scheduleUserMessageCollapse(root);
  root.querySelectorAll('[data-copy-code]').forEach(btn=>{
    if(btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      const code = getCodeBlockRawSource(btn.closest('.code-block'));
      copyText(code);
      flashButtonCopied(btn);
    });
  });
  root.querySelectorAll('[data-code-run]').forEach(btn=>{
    if(btn.dataset.boundRun === '1') return;
    btn.dataset.boundRun = '1';
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      const block = btn.closest('.code-block');
      if(!block) return;
      runCodeBlock(block, btn);
    });
  });
  root.querySelectorAll('[data-mermaid-toggle]').forEach(btn=>{
    if(btn.dataset.boundMermaidToggle === '1') return;
    btn.dataset.boundMermaidToggle = '1';
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      const block = btn.closest('.mermaid-block');
      if(!block) return;
      const showSource = !block.classList.contains('is-source-visible');
      block.classList.toggle('is-source-visible', showSource);
      btn.textContent=markdownUiT(showSource?'code.show_diagram':'code.show_code',null,showSource?'Show diagram':'Show code');
      if(!showSource) renderMermaidBlock(block);
    });
  });
  root.querySelectorAll('[data-mermaid-zoom]').forEach(btn=>{
    if(btn.dataset.boundMermaidZoom === '1') return;
    btn.dataset.boundMermaidZoom = '1';
    btn.addEventListener('click', async (e)=>{
      e.stopPropagation();
      const block = btn.closest('.mermaid-block');
      if(!block) return;
      await openMermaidDiagramModal(block);
    });
  });
  root.querySelectorAll('[data-code-collapse]').forEach(btn=>{
    if(btn.dataset.boundCollapse === '1') return;
    btn.dataset.boundCollapse = '1';
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      const block = btn.closest('.code-block');
      if(!block) return;
      const collapsed = block.classList.toggle('is-collapsed');
      const lines = Number(block.dataset.codeLines || 0);
      btn.textContent=collapsed?markdownUiT('code.expand_lines',{count:lines},`Expand ${lines} lines`):markdownUiT('code.collapse',null,'Collapse');
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
  });
  root.querySelectorAll('.code-block.collapsible').forEach(block=>{
    const btn = block.querySelector('[data-code-collapse]');
    if(btn && !btn.dataset.initLabel){
      btn.dataset.initLabel = '1';
      const lines = Number(block.dataset.codeLines || 0);
      btn.textContent=block.classList.contains('is-collapsed')?markdownUiT('code.expand_lines',{count:lines},`Expand ${lines} lines`):markdownUiT('code.collapse',null,'Collapse');
    }
  });
  root.querySelectorAll('img.inline-img').forEach(img=>{
    ensureInlineImageLoadVisibility(img);
    if(img.dataset.boundFallback !== '1' && img.dataset.boundImgError !== '1'){
      img.dataset.boundFallback = '1';
      img.addEventListener('error', ()=>{
        if(scheduleImageMirrorPoll(img, 'fallback-error')) return;
        const fallbackHtml = img.getAttribute('data-fallback-html') || '';
        const wrapper = document.createElement('span');
        wrapper.className = 'inline-img-fallback';
      wrapper.innerHTML = fallbackHtml || buildImageFallbackHtml(img.getAttribute('src') || img.src || '', img.getAttribute('alt') || `🔗 ${markdownUiT('citation.view_image', null, 'View image')}`);
        img.replaceWith(wrapper);
      }, { once:true });
    }
    if(img.dataset.boundPreview === '1') return;
    img.dataset.boundPreview = '1';
    attachPreviewableImage(img, img.getAttribute('src') || img.src || '');
  });
}

function normalizeLightboxItems(items){
  return (Array.isArray(items) ? items : [items]).map(item => {
    if(typeof item === 'string') return { src: item.trim(), alt: '' };
    if(item && typeof item === 'object') return { src: String(item.src || item.url || '').trim(), alt: String(item.alt || '').trim() };
    return { src: '', alt: '' };
  }).filter(item => item.src);
}

async function renderLightboxIndex(index){
  if(!imageLightboxEl || !imageLightboxImgEl || !lightboxItems.length) return;
  if(index < 0) index = lightboxItems.length - 1;
  if(index >= lightboxItems.length) index = 0;
  lightboxIndex = index;
  let u = String(lightboxItems[lightboxIndex]?.src || '').trim();
  if(!u) return;
  if(u.startsWith("local://")){
    const objUrl = await localUrlToObjectUrl(u);
    if(!objUrl) return;
    u = objUrl;
  }
  imageLightboxImgEl.dataset.rawSrc = u;
  imageLightboxImgEl.dataset.proxySrc = buildRemoteImageProxyUrl(u);
  imageLightboxImgEl.dataset.srcStage = 'proxy';
  imageLightboxImgEl.onerror = ()=>{
    const rawSrc = String(imageLightboxImgEl.dataset.rawSrc || '').trim();
    const proxySrc = String(imageLightboxImgEl.dataset.proxySrc || '').trim();
    const stage = String(imageLightboxImgEl.dataset.srcStage || 'proxy');
    if(stage === 'proxy' && rawSrc && rawSrc !== proxySrc){
      imageLightboxImgEl.dataset.srcStage = 'raw';
      imageLightboxImgEl.src = rawSrc;
      return;
    }
    imageLightboxImgEl.onerror = null;
    const hasGallery = lightboxItems.length > 1;
    if(hasGallery){
      const failedIndex = lightboxIndex;
      lightboxItems.splice(failedIndex, 1);
      if(!lightboxItems.length){
        closeImageLightbox();
        return;
      }
      if(lightboxIndex >= lightboxItems.length){
        lightboxIndex = 0;
      }
      renderLightboxIndex(lightboxIndex);
      return;
    }
    closeImageLightbox();
  };
  imageLightboxImgEl.onload = ()=>{
    if((imageLightboxImgEl.naturalWidth || 0) > 0 && (imageLightboxImgEl.naturalHeight || 0) > 0){
      return;
    }
    imageLightboxImgEl.onerror && imageLightboxImgEl.onerror();
  };
  imageLightboxImgEl.src = imageLightboxImgEl.dataset.proxySrc || u;
  imageLightboxImgEl.alt = lightboxItems[lightboxIndex]?.alt || markdownUiT('citation.image_alt', {index:lightboxIndex + 1}, 'Image {index}');
  const hasGallery = lightboxItems.length > 1;
  imageLightboxEl.classList.toggle('has-gallery', hasGallery);
  if(imageLightboxCounterEl){
    imageLightboxCounterEl.textContent = hasGallery ? `${lightboxIndex + 1} / ${lightboxItems.length}` : '';
  }
}

async function openImageLightbox(items, startIndex=0){
  if(!imageLightboxEl || !imageLightboxImgEl) return;
  lightboxItems = normalizeLightboxItems(items);
  if(!lightboxItems.length) return;
  imageLightboxEl.classList.add("open");
  imageLightboxEl.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  await renderLightboxIndex(startIndex);
}
function closeImageLightbox(){
  if(!imageLightboxEl || !imageLightboxImgEl) return;
  imageLightboxEl.classList.remove("open");
  imageLightboxEl.setAttribute("aria-hidden", "true");
  imageLightboxEl.classList.remove('has-gallery');
  imageLightboxImgEl.removeAttribute("src");
  imageLightboxImgEl.removeAttribute('alt');
  if(imageLightboxCounterEl) imageLightboxCounterEl.textContent = '';
  lightboxItems = [];
  lightboxIndex = 0;
  document.body.style.overflow = "";
}
async function stepImageLightbox(delta){
  if(!imageLightboxEl?.classList.contains('open') || lightboxItems.length <= 1) return;
  await renderLightboxIndex(lightboxIndex + delta);
}

async function attachPreviewableImageOpen(imgEl, src=''){
  if(!imgEl) return;
  const group = imgEl.closest('.inline-image-group');
  if(group){
    let items = [];
    try{
      items = JSON.parse(group.dataset.galleryItems || '[]');
    }catch(_){ items = []; }
    const startIndex = Math.max(0, parseInt(imgEl.dataset.galleryIndex || '0', 10) || 0);
    if(items.length){
      await openImageLightbox(items, startIndex);
      return;
    }
    const imgs = Array.from(group.querySelectorAll('img.inline-img')).map(node => ({
      src: (node.dataset.rawSrc || node.dataset.originSrc || node.dataset.src || node.getAttribute('src') || node.src || '').trim(),
      rawUrl: (node.dataset.rawSrc || node.dataset.originSrc || '').trim(),
      proxyUrl: (node.dataset.proxySrc || '').trim(),
      alt: node.getAttribute('alt') || ''
    })).filter(item => item.src);
    if(imgs.length){
      await openImageLightbox(imgs, startIndex);
      return;
    }
  }
  let singleSrc = String(src || imgEl.dataset.originSrc || imgEl.currentSrc || imgEl.src || '').trim();
  const localId = imgEl.dataset.localId || '';
  if((!singleSrc || singleSrc.startsWith('local://')) && localId){
    singleSrc = `local://${localId}`;
  }
  if(singleSrc){
    await openImageLightbox([{ src: singleSrc, alt: imgEl.getAttribute('alt') || '' }], 0);
  }
}

function attachPreviewableImage(imgEl, src){
  if(!imgEl) return;
  const previewSrc = String(src || imgEl.dataset.previewSrc || imgEl.getAttribute('src') || '').trim();
  if(previewSrc) imgEl.dataset.previewSrc = previewSrc;
  if(imgEl.dataset.boundPreviewClick === '1') return;
  imgEl.dataset.boundPreviewClick = '1';
  imgEl.addEventListener("click", async (e)=>{
    e.preventDefault();
    e.stopPropagation();
    const dynamicSrc = String(imgEl.dataset.previewSrc || imgEl.currentSrc || imgEl.getAttribute('src') || previewSrc || '').trim();
    await attachPreviewableImageOpen(imgEl, dynamicSrc);
  }, true);
}
function highlightCode(code, lang){
  const codeText = normalizeRunnableCodeSource(code).replace(/\n$/, '');
  let html = escapeHtml(codeText);
  const L = normalizeCodeFenceLang(lang);
  if(["javascript","typescript","python","java","c","cpp","go","rust","php","sql","bash","json","html","xml","css","yaml"].includes(L)){
    const placeholders = [];
    const alphaIndex = (n)=>{
      let value = Number(n) || 0;
      let out = '';
      do{
        out = String.fromCharCode(65 + (value % 26)) + out;
        value = Math.floor(value / 26) - 1;
      }while(value >= 0);
      return out;
    };
    const stash = (value)=>{
      const token = `__CODETOKEN${alphaIndex(placeholders.length)}__`;
      placeholders.push([token, String(value ?? "")]);
      return token;
    };
    const restore = (value)=>{
      let out = String(value ?? "");
      for(const [token, htmlValue] of placeholders){
        out = out.split(token).join(htmlValue);
      }
      return out;
    };

    html = html.replace(/(&quot;(?:\\.|[^&]|&(?!quot;))*?&quot;|&#0*39;(?:\\.|[^&]|&(?!#0*39;))*?&#0*39;|&#x0*27;(?:\\.|[^&]|&(?!#x0*27;))*?&#x0*27;|&apos;(?:\\.|[^&]|&(?!apos;))*?&apos;|`(?:\\.|[^`])*?`)/gi, (m)=> stash(`<span class="md-s">${m}</span>`));

    if(L === 'python' || L === 'bash' || L === 'yaml'){
      html = html.replace(/(^|\n)(\s*#.*)(?=$|\n)/g, (m, lead, body)=> `${lead}${stash(`<span class="md-c">${body}</span>`)}`);
    }
    if(['javascript','typescript','java','c','cpp','go','rust','php','css','sql'].includes(L)){
      html = html.replace(/\/\*[\s\S]*?\*\//g, (m)=> stash(`<span class="md-c">${m}</span>`));
      html = html.replace(/(^|\n)(\s*\/\/.*)(?=$|\n)/g, (m, lead, body)=> `${lead}${stash(`<span class="md-c">${body}</span>`)}`);
      if(L === 'sql'){
        html = html.replace(/(^|\n)(\s*--.*)(?=$|\n)/g, (m, lead, body)=> `${lead}${stash(`<span class="md-c">${body}</span>`)}`);
      }
    }
    if(L === 'html' || L === 'xml'){
      html = html.replace(/&lt;!--[\s\S]*?--&gt;/g, (m)=> stash(`<span class="md-c">${m}</span>`));
    }

    const keywordPatterns = {
      javascript: /\b(function|return|const|let|var|if|else|for|while|break|continue|class|new|try|catch|finally|throw|async|await|import|from|export|default|extends|super|switch|case|yield|typeof|instanceof|in|of|null|true|false)\b/g,
      typescript: /\b(function|return|const|let|var|if|else|for|while|break|continue|class|new|try|catch|finally|throw|async|await|import|from|export|default|extends|super|switch|case|yield|typeof|instanceof|in|of|null|true|false|interface|type|implements|enum|public|private|protected|readonly|declare|as)\b/g,
      python: /\b(def|class|return|if|elif|else|for|while|break|continue|try|except|finally|raise|import|from|as|pass|lambda|with|yield|async|await|True|False|None|and|or|not|in|is|global|nonlocal|assert)\b/g,
      java: /\b(class|public|private|protected|static|final|void|int|long|double|float|boolean|char|new|return|if|else|for|while|switch|case|break|continue|try|catch|finally|throw|throws|extends|implements|null|true|false|package|import)\b/g,
      c: /\b(return|if|else|for|while|switch|case|break|continue|struct|typedef|enum|static|const|void|int|long|double|float|char|sizeof|include)\b/g,
      cpp: /\b(return|if|else|for|while|switch|case|break|continue|class|struct|template|typename|using|namespace|public|private|protected|virtual|override|const|static|void|int|long|double|float|char|bool|new|delete|nullptr|include)\b/g,
      go: /\b(func|return|if|else|for|range|break|continue|switch|case|fallthrough|type|struct|interface|map|chan|go|defer|package|import|var|const|nil|true|false)\b/g,
      rust: /\b(fn|let|mut|pub|impl|trait|struct|enum|match|if|else|for|while|loop|break|continue|return|mod|use|crate|self|Self|super|async|await|move|const|static|mut|ref|where|dyn|true|false|None|Some|Result|Ok|Err)\b/g,
      php: /\b(function|return|if|else|elseif|for|foreach|while|break|continue|class|new|public|private|protected|static|const|namespace|use|try|catch|finally|throw|null|true|false)\b/g,
      sql: /\b(SELECT|FROM|WHERE|ORDER|BY|GROUP|HAVING|LIMIT|OFFSET|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|ALTER|DROP|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|AND|OR|NOT|NULL|DISTINCT|WITH|UNION|ALL|CASE|WHEN|THEN|END)\b/gi,
      bash: /\b(if|then|else|fi|for|in|do|done|case|esac|while|function|export|local|readonly|return|exit|sudo)\b/g,
      json: /\b(true|false|null)\b/g,
      html: /\b(html|head|body|div|span|script|style|link|meta|title|section|main|article|button)\b/g,
      css: /\b(display|position|color|background|border|padding|margin|flex|grid|font|width|height|transform|transition|absolute|relative|fixed|sticky)\b/g,
      yaml: /\b(true|false|null|yes|no|on|off)\b/gi,
    };
    const keywordPattern = keywordPatterns[L];
    if(keywordPattern){
      html = html.replace(keywordPattern, (m)=> stash(`<span class="md-k">${m}</span>`));
    }

    if(L === 'json' || L === 'yaml'){
      html = html.replace(/(^|\n)(\s*&quot;[^\n]*?&quot;\s*:)/g, (m, lead, body)=> `${lead}${stash(`<span class="md-k">${body}</span>`)}`);
    }
    html = html.replace(/\b(\d+(?:\.\d+)?)\b/g, (m)=> stash(`<span class="md-n">${m}</span>`));
    html = restore(html);
  }
  return html;
}

function normalizeMarkdownTableRow(line){
  return String(line ?? "")
    .trim()
    .replace(/｜/g, "|")
    .replace(/^\|\s*/, "")
    .replace(/\s*\|$/, "");
}

function parseMarkdownTableRow(line){
  return normalizeMarkdownTableRow(line).split("|").map(cell => cell.trim());
}

function isMarkdownTableSeparatorCell(cell){
  const raw = String(cell ?? '').trim();
  if(!raw) return false;
  const compact = raw.replace(/\s+/g, '').replace(/[‐‑‒–—―]/g, '-');
  return /^:?-{2,}:?$/.test(compact);
}

function isMarkdownTableSeparator(line){
  const cells = parseMarkdownTableRow(line);
  return !!cells.length && cells.every(isMarkdownTableSeparatorCell);
}

function isMarkdownTableRow(line){
  const raw = String(line ?? "").trim();
  const normalized = normalizeMarkdownTableRow(raw);
  if(!raw || normalized.indexOf('|') < 0) return false;
  if(isMarkdownTableSeparator(raw)) return true;
  const cells = parseMarkdownTableRow(raw);
  return cells.length >= 2;
}

function renderMarkdownTable(lines){
  const normalized = (Array.isArray(lines) ? lines : [])
    .map(line => String(line ?? '').trim())
    .filter(Boolean);
  if(normalized.length < 2) return "";
  const rows = normalized.map(parseMarkdownTableRow);
  if(rows.length < 2 || !isMarkdownTableSeparator(normalized[1])) return "";
  const head = rows[0];
  if(!head.length || head.length < 2) return "";
  const bodyRows = rows.slice(2).map(row => {
    if(row.length < head.length){
      return [...row, ...Array(head.length - row.length).fill('')];
    }
    return row.slice(0, head.length);
  });
  const sourceAttr = escapeHtml(encodeURIComponent(normalized.join('\n')));
  const copyIcon = '<span class="bubble-action-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="10" height="10" rx="2"></rect><path d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path></svg></span>';
  const copyTableLabel = escapeHtml(markdownUiT('citation.table_copy', null, 'Copy table'));
  return `<div class="table-wrap" data-table-source="${sourceAttr}"><button class="icon-btn bubble-copy table-copy" type="button" data-table-copy="1" data-action-kind="copy" data-action-label="${copyTableLabel}" data-restore-label="${copyTableLabel}" aria-label="${copyTableLabel}" title="${copyTableLabel}">${copyIcon}</button><div class="table-scroll"><table><thead><tr>` + head.map(cell=>`<th>${renderInlineRich(cell)}</th>`).join("") + '</tr></thead><tbody>' +
    bodyRows.map(row=>'<tr>' + head.map((_,i)=>`<td>${renderInlineRich(row[i] || "")}</td>`).join("") + '</tr>').join("") + '</tbody></table></div></div>';
}

function parseCodeFenceLine(line){
  const m = String(line ?? '').match(/^[ \t]{0,3}(`{3,}|~{3,})([^\n]*)$/);
  if(!m) return null;
  const fence = m[1] || '';
  const marker = fence[0] || '`';
  const info = String(m[2] || '').trim();
  if(marker === '`' && info.includes('`')) return null;
  const lang = (info.split(/\s+/).find(Boolean) || '').trim();
  return { marker, len:fence.length, info, lang };
}

function isCodeFenceCloseLine(line, fence){
  if(!fence) return false;
  const m = String(line ?? '').match(/^[ \t]{0,3}(`{3,}|~{3,})[ \t]*$/);
  if(!m) return false;
  const close = m[1] || '';
  return close[0] === fence.marker && close.length >= fence.len;
}

function isMarkdownFenceCodeLang(rawLang){
  const lang = normalizeCodeFenceLang(rawLang);
  return lang === 'markdown' || lang === 'md' || lang === 'mdx';
}

function splitRichTextBlocks(text){
  const src = String(text ?? "").replace(/\r\n/g, "\n");
  const blocks = [];
  const lines = src.split("\n");
  const textLines = [];
  const pushText = ()=>{
    if(!textLines.length) return;
    blocks.push({type:"text", text:textLines.join("\n")});
    textLines.length = 0;
  };
  let i = 0;
  while(i < lines.length){
    const opening = parseCodeFenceLine(lines[i]);
    if(!opening){
      textLines.push(lines[i]);
      i += 1;
      continue;
    }

    pushText();
    i += 1;
    const codeLines = [];
    const markdownLike = isMarkdownFenceCodeLang(opening.lang);
    let nestedFence = null;
    while(i < lines.length){
      const line = lines[i];
      if(markdownLike && nestedFence){
        codeLines.push(line);
        if(isCodeFenceCloseLine(line, nestedFence)) nestedFence = null;
        i += 1;
        continue;
      }
      if(isCodeFenceCloseLine(line, opening)){
        i += 1;
        break;
      }
      if(markdownLike){
        const innerOpening = parseCodeFenceLine(line);
        if(innerOpening && innerOpening.info){
          nestedFence = innerOpening;
        }
      }
      codeLines.push(line);
      i += 1;
    }
    blocks.push({type:"code", lang:opening.lang, code:codeLines.join("\n")});
  }
  pushText();
  return blocks;
}

function sanitizeEmbeddableImageUrl(url){
  let u = String(url || '').trim();
  if(!u) return '';
  if((u.startsWith('<') && u.endsWith('>')) || (u.startsWith('(') && u.endsWith(')'))){
    u = u.slice(1, -1).trim();
  }
  u = u.replace(/&amp;/gi, '&');
  if(/^sandbox:/i.test(u)){
    u = u.replace(/^sandbox:/i, '').trim();
    if(u && !u.startsWith('/') && !/^https?:\/\//i.test(u) && !/^data:image\//i.test(u)){
      u = '/' + u.replace(/^\/+/, '');
    }
  }
  if(/^data:image\//i.test(u)){
    u = u.replace(/\s+/g, '');
  }
  return trimUrl(u);
}

function normalizeInlineLinkUrl(url){
  let u = String(url || '').trim();
  if(!u) return '';
  for(let i = 0; i < 3; i++){
    const before = u;
    u = u
      .replace(/^(?:&(?:amp;)?lt;?|&#0*60;?|&#x0*3c;?)+/ig, '')
      .replace(/^[<＜]+/g, '')
      .replace(/[>＞]+$/g, '')
      .replace(/(?:&(?:amp;)?gt;?|&#0*62;?|&#x0*3e;?)+$/ig, '')
      .trim();
    u = decodeHtmlEntities(u).trim();
    if(u === before) break;
  }
  if(/^(?:\.\/)?api3\/(?:uploads|download|generated-files|generated-download|generated-files-id|generated-download-id)\//i.test(u)){
    u = '/' + u.replace(/^\.\//, '');
  }
  return sanitizeEmbeddableImageUrl(u);
}

function assistantFileNameFromLinkLabel(label = ''){
  let text = decodeHtmlEntities(String(label || '')).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  if(!text) return '';
  text = text.replace(/[：:]\s*/g, ' ').replace(/[，,。；;]+$/g, '').trim();
  const tokens = text.split(/[\s"'“”‘’「」『』【】\[\]（）()<>《》，,。；;:：!?！？]+/).map(token => {
    return String(token || '')
      .replace(/^[^\w\u4e00-\u9fff.-]+/g, '')
      .replace(/[^\w\u4e00-\u9fff.-]+$/g, '')
      .trim();
  }).filter(Boolean);
  for(let i = tokens.length - 1; i >= 0; i--){
    const token = tokens[i];
    if(!token || /[\/\\]/.test(token)) continue;
    if(/^[^\s\/\\]+\.[A-Za-z0-9][A-Za-z0-9._-]{0,15}$/.test(token)) return token;
  }
  if(/^[^\/\\\s]+\.[A-Za-z0-9][A-Za-z0-9._-]{0,15}$/.test(text)) return text;
  return '';
}

function isEmptyAssistantLocalFileRoute(url){
  const meta = _assistantResolvedUrlMeta(url);
  const path = String(meta.path || '').replace(/\/+$/g, '').toLowerCase();
  return !!(meta.isSameApp && /^\/api3\/(?:uploads|download|generated-files|generated-download|generated-files-id|generated-download-id)$/.test(path));
}

function assistantHrefFromEmptyRouteLabel(url, label = ''){
  if(!isEmptyAssistantLocalFileRoute(url)) return '';
  const filename = assistantFileNameFromLinkLabel(label);
  if(!filename) return '';
  try{
    const parsed = new URL(normalizeAssistantHref(url) || url, window.location.origin);
    const path = String(parsed.pathname || '').toLowerCase();
    const base = path.includes('/generated-') ? '/api3/generated-download/' : '/api3/download/';
    return normalizeAssistantDownloadHref(base + encodeURIComponent(filename) + (parsed.search || '') + (parsed.hash || ''));
  }catch(_){
    const lower = String(url || '').toLowerCase();
    const base = lower.includes('generated-') ? '/api3/generated-download/' : '/api3/download/';
    return normalizeAssistantDownloadHref(base + encodeURIComponent(filename));
  }
}

function assistantHrefFromRelativeFileUrl(url, label = ''){
  const raw = normalizeInlineLinkUrl(url);
  if(!raw || /^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith('/') || raw.startsWith('#') || raw.includes('\\')) return '';
  const filename = assistantGeneratedFileNameKey(raw) || assistantFileNameFromLinkLabel(label);
  if(!filename) return '';
  return normalizeAssistantDownloadHref('/api3/generated-download/' + encodeURIComponent(filename));
}

function assistantGeneratedDownloadHrefFromFilename(filename = ''){
  const safe = assistantGeneratedFileNameKey(filename) || assistantFileNameFromLinkLabel(filename);
  if(!safe) return '';
  return normalizeAssistantDownloadHref('/api3/generated-download/' + encodeURIComponent(safe));
}

function assistantHrefFromSandboxOrPathUrl(url, label = ''){
  const original = String(url || '').trim();
  const raw = normalizeInlineLinkUrl(original);
  const filenameFromUrl = assistantGeneratedFileNameKey(raw || original);
  const filenameFromLabel = assistantFileNameFromLinkLabel(label);
  if(!filenameFromUrl && !filenameFromLabel) return '';
  const lowRaw = String(raw || original || '').toLowerCase();
  const looksSandboxPath = /^sandbox:/i.test(original)
    || /^\/?mnt\/data\//i.test(lowRaw)
    || /^\/?tmp\//i.test(lowRaw)
    || /(?:^|\/)mnt\/data\//i.test(lowRaw);
  const looksPlainFile = !!filenameFromUrl && !/^(?:https?:|data:image\/|\/api3\/)/i.test(raw || original);
  if(!looksSandboxPath && !looksPlainFile) return '';
  const resolved = resolveAssistantGeneratedFileHrefForUrl(raw || original);
  if(resolved) return resolved;
  const filename = filenameFromUrl || filenameFromLabel;
  try{
    const currentFiles = _assistantGeneratedFilesForSession(typeof store !== 'undefined' ? store?.activeId : '');
    const key = String(filename || '').trim().toLowerCase();
    const matched = currentFiles.find(f => String(f.filename || '').trim().toLowerCase() === key);
    if(matched && matched.href) return String(matched.href || '').trim();
  }catch(_){ }
  // 兜底修复旧消息：旧正文只有 sandbox:/mnt/data/xxx 或 /mnt/data/xxx，
  // 但没有 generated_files 元数据时，仍按文件名走后端 generated-download。
  // 后端会做登录/会话 scope 校验；文件已清理时返回过期提示。
  return assistantGeneratedDownloadHrefFromFilename(filename);
}

function buildInlineLinkHtml(url, label = ''){
  const clean = normalizeInlineLinkUrl(url);
  if(!clean) return escapeHtml(label || url || '');
  if(isLikelyEmbeddableImageUrl(clean)) return buildInlineImageHtml(clean, label || markdownUiT('citation.related_image', null, 'Related image'));
  const artifactHref = resolveAssistantGeneratedFileHrefForUrl(clean)
    || assistantHrefFromEmptyRouteLabel(clean, label)
    || assistantHrefFromSandboxOrPathUrl(url, label)
    || assistantHrefFromRelativeFileUrl(clean, label);
  const linkTarget = artifactHref || clean;
  const managedDownload = !!artifactHref || isAssistantDownloadableFileUrl(linkTarget);
  const finalHref = managedDownload ? normalizeAssistantDownloadHref(linkTarget) : normalizeAssistantHref(linkTarget);
  const safeUrl = escapeHtml(finalHref || clean);
  const safeLabel = escapeHtml(label || clean);
  const extraAttrs = managedDownload ? ' data-webai-managed-download="1"' : '';
  return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer"${extraAttrs}>${safeLabel}</a>`;
}

function assistantInlineSourceHost(url){
  const clean = normalizeInlineLinkUrl(url);
  if(!clean || !isAssistantVisibleCitationUrl(clean)) return '';
  return getAssistantSourceHost(clean);
}

function assistantInlineSourceLabelLooksLikeHost(label, host, url){
  const h = String(host || '').trim().toLowerCase().replace(/^www\./i, '');
  if(!h) return false;
  const raw = stripInlineHtmlForLinkLabel(label || '').toLowerCase();
  if(!raw) return true;
  const compact = raw
    .replace(/^https?:\/\//i, '')
    .replace(/^www\./i, '')
    .replace(/[\/?#].*$/g, '')
    .replace(/[()（）\[\]【】<>《》"'“”‘’]/g, '')
    .replace(/\s+/g, '')
    .replace(/[.,;，。；]+$/g, '');
  if(!compact || compact.length > 80) return false;
  if(compact === h) return true;
  const normalizedUrl = String(url || '').toLowerCase().replace(/^https?:\/\//i, '').replace(/^www\./i, '').replace(/[\/?#].*$/g, '');
  return !!normalizedUrl && compact === normalizedUrl;
}

function assistantInlineSourceRawUrlLooksLikeCitation(url){
  const clean = normalizeInlineLinkUrl(url);
  if(!clean || !isAssistantVisibleCitationUrl(clean)) return false;
  try{
    const parsed = new URL(clean, window.location.origin);
    const path = String(parsed.pathname || '/').replace(/\/+$/g, '') || '/';
    return path === '/' && !parsed.search && !parsed.hash;
  }catch(_){
    return false;
  }
}

function assistantInlineSourceFaviconUrlForHost(host){
  const cleanHost = String(host || '').trim().toLowerCase().replace(/^www\./i, '');
  if(!cleanHost) return '';
  return `/api3/source-favicon?host=${encodeURIComponent(cleanHost)}`;
}

function assistantInlineSourceDisplayHost(host){
  return String(host || '').trim().toLowerCase().replace(/^www\./i, '');
}

function assistantInlineSourceLooksLikeBareHost(value){
  const raw = String(value || '').trim()
    .replace(/[()（）\[\]【】<>《》"'“”‘’]/g, '')
    .replace(/[.,;，。；]+$/g, '')
    .replace(/^https?:\/\//i, '')
    .replace(/^www\./i, '')
    .replace(/\/.*$/g, '');
  if(!raw || raw.length > 120) return false;
  if(/\s/.test(raw)) return false;
  if(/^localhost$/i.test(raw) || /^\d+\.\d+\.\d+\.\d+$/.test(raw)) return false;
  return /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(raw);
}

function assistantInlineSourceUrlFromBareHost(value){
  const raw = String(value || '').trim()
    .replace(/[()（）\[\]【】<>《》"'“”‘’]/g, '')
    .replace(/[.,;，。；]+$/g, '')
    .replace(/^https?:\/\//i, '')
    .replace(/^www\./i, '');
  const hostPart = raw.replace(/[/?#].*$/g, '');
  if(!assistantInlineSourceLooksLikeBareHost(hostPart)) return '';
  return `https://${raw}`;
}

let assistantInlineSourcePillsEnabled = true;
function withAssistantInlineSourcePillsEnabled(enabled, fn){
  const previous = assistantInlineSourcePillsEnabled;
  assistantInlineSourcePillsEnabled = enabled !== false;
  try{
    return typeof fn === 'function' ? fn() : '';
  }finally{
    assistantInlineSourcePillsEnabled = previous;
  }
}

function buildInlineSourceCitationHtml(url, label = ''){
  const clean = normalizeInlineLinkUrl(url);
  const host = assistantInlineSourceHost(clean);
  if(!host || !assistantInlineSourceLabelLooksLikeHost(label, host, clean)) return '';
  const finalHref = normalizeAssistantHref(clean) || clean;
  const displayHost = assistantInlineSourceDisplayHost(host);
  const safeUrl = escapeHtml(finalHref);
  const safeHost = escapeHtml(displayHost);
  const safeFullHost = escapeHtml(host);
  const fallback = escapeHtml(getAssistantSourceIconFallback({ host, url:finalHref }));
  const sourceAria = escapeHtml(markdownUiT('citation.source_label', {source:host}, 'Source: {source}'));
  return `<a class="assistant-inline-source assistant-inline-source-pill" href="${safeUrl}" target="_blank" rel="noopener noreferrer" title="${safeHost}" aria-label="${sourceAria}" data-source-host="${safeFullHost}" data-source-url="${safeUrl}"><span class="assistant-inline-source-icon" aria-hidden="true"><span class="bubble-source-icon-fallback">${fallback}</span></span><span class="assistant-inline-source-host">${safeHost}</span></a>`;
}

function buildInlineSourceCitationFromBareHostHtml(hostLabel = ''){
  const href = assistantInlineSourceUrlFromBareHost(hostLabel);
  if(!href) return '';
  const host = assistantInlineSourceHost(href);
  if(!host) return '';
  return buildInlineSourceCitationHtml(href, host);
}

function maybeBuildInlineSourceCitationHtml(url, label = ''){
  return buildInlineSourceCitationHtml(url, label) || buildInlineLinkHtml(url, label);
}

function getAssistantInlineSourceItemsForAnchor(anchor){
  try{
    const bubble = anchor?.closest?.('.bubble.a');
    if(!bubble) return [];
    return Array.isArray(assistantCitationSourceItemsByBubble.get(bubble)) ? assistantCitationSourceItemsByBubble.get(bubble) : [];
  }catch(_){
    return [];
  }
}

function findAssistantInlineSourceItemForAnchor(anchor){
  const rawHref = trimUrl(anchor?.dataset?.sourceUrl || anchor?.getAttribute?.('href') || '');
  const host = String(anchor?.dataset?.sourceHost || getAssistantSourceHost(rawHref) || '').trim().toLowerCase().replace(/^www\./i, '');
  const hrefKey = rawHref.toLowerCase().replace(/#.*$/g, '').replace(/\/$/g, '');
  const items = getAssistantInlineSourceItemsForAnchor(anchor);
  let hostMatch = null;
  for(const item of items){
    const itemUrl = trimUrl(item?.url || item?.href || '');
    const itemHost = String(item?.host || item?.domain || getAssistantSourceHost(itemUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
    const itemKey = itemUrl.toLowerCase().replace(/#.*$/g, '').replace(/\/$/g, '');
    if(hrefKey && itemKey && itemKey === hrefKey) return item;
    if(host && itemHost && itemHost === host && !hostMatch) hostMatch = item;
  }
  if(hostMatch) return hostMatch;
  return {
    sourceType:'web',
    title: host || rawHref || markdownUiT('citation.source', null, 'Source'),
    url: rawHref,
    host,
    favicon:'',
    snippet:'',
  };
}

function syncAssistantInlineSourceIcons(bubble){
  if(!bubble) return;
  const anchors = bubble.querySelectorAll('a.assistant-inline-source-pill, a.assistant-inline-source-citation, a.assistant-inline-source-textlink');
  for(const anchor of anchors){
    const icon = anchor.querySelector('.assistant-inline-source-icon');
    if(!icon) continue;
    bindAssistantSourceFavicon(icon, findAssistantInlineSourceItemForAnchor(anchor));
  }
}

let activeAssistantInlineSourcePopover = null;
let activeAssistantInlineSourceAnchor = null;
let assistantInlineSourceHoverTimer = null;
let assistantInlineSourceCloseTimer = null;

function closeAssistantInlineSourcePopover(){
  clearTimeout(assistantInlineSourceHoverTimer);
  clearTimeout(assistantInlineSourceCloseTimer);
  assistantInlineSourceHoverTimer = null;
  assistantInlineSourceCloseTimer = null;
  try{ activeAssistantInlineSourcePopover?.remove?.(); }catch(_){ }
  try{ activeAssistantInlineSourceAnchor?.classList?.remove?.('is-active'); }catch(_){ }
  activeAssistantInlineSourcePopover = null;
  activeAssistantInlineSourceAnchor = null;
}

function createAssistantInlineSourceIconNode(item, extraClass=''){
  const span = document.createElement('span');
  span.className = ('assistant-inline-source-icon' + (extraClass ? ' ' + extraClass : '')).trim();
  bindAssistantSourceFavicon(span, item);
  return span;
}

function createAssistantInlineSourcePopover(anchor){
  const item = findAssistantInlineSourceItemForAnchor(anchor);
  const href = trimUrl(item?.url || item?.href || anchor?.dataset?.sourceUrl || anchor?.getAttribute?.('href') || '');
  const host = String(item?.host || item?.domain || getAssistantSourceHost(href) || anchor?.dataset?.sourceHost || '').trim().toLowerCase().replace(/^www\./i, '');
  const title = normalizeAssistantSourceTitle(item?.title || item?.label || host || href || markdownUiT('citation.source', null, 'Source'), href, host);
  const snippet = String(item?.snippet || item?.text || item?.preview || '').replace(/\s+/g, ' ').trim();

  const popover = document.createElement('div');
  popover.className = 'assistant-inline-source-popover';
  popover.addEventListener('click', (e)=>e.stopPropagation());
  popover.addEventListener('mouseenter', ()=>clearTimeout(assistantInlineSourceCloseTimer));
  popover.addEventListener('mouseleave', ()=>scheduleCloseAssistantInlineSourcePopover(220));

  const card = href ? document.createElement('a') : document.createElement('div');
  card.className = 'assistant-inline-source-popover-card';
  if(href){
    card.href = href;
    card.target = '_blank';
    card.rel = 'noopener noreferrer';
  }

  const site = document.createElement('div');
  site.className = 'assistant-inline-source-popover-site';
  site.appendChild(createAssistantInlineSourceIconNode({ ...item, url: href, host }, 'assistant-inline-source-popover-site-icon'));
  const siteName = document.createElement('span');
  siteName.className = 'assistant-inline-source-popover-site-name';
  siteName.textContent = host || href || markdownUiT('citation.source', null, 'Source');
  site.appendChild(siteName);
  card.appendChild(site);

  const titleEl = document.createElement('div');
  titleEl.className = 'assistant-inline-source-popover-title';
  titleEl.textContent = title || host || href || markdownUiT('citation.source', null, 'Source');
  card.appendChild(titleEl);

  const preview = document.createElement('div');
  preview.className = 'assistant-inline-source-popover-preview';
  preview.textContent = snippet || href || host || '';
  card.appendChild(preview);

  popover.appendChild(card);
  return popover;
}

function positionAssistantInlineSourcePopover(anchor, popover){
  if(!anchor || !popover) return;
  const rect = anchor.getBoundingClientRect();
  const vw = window.innerWidth || document.documentElement.clientWidth || 1024;
  const vh = window.innerHeight || document.documentElement.clientHeight || 768;
  const margin = 12;
  const pr = popover.getBoundingClientRect();
  const width = pr.width || 380;
  const height = pr.height || 180;
  let left = rect.left;
  if(left + width + margin > vw) left = vw - width - margin;
  left = Math.max(margin, left);
  let top = rect.bottom + 8;
  if(top + height + margin > vh) top = rect.top - height - 8;
  top = Math.max(margin, Math.min(top, vh - height - margin));
  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

function showAssistantInlineSourcePopover(anchor){
  if(!anchor) return;
  if(activeAssistantInlineSourceAnchor === anchor && activeAssistantInlineSourcePopover){
    positionAssistantInlineSourcePopover(anchor, activeAssistantInlineSourcePopover);
    return;
  }
  closeAssistantInlineSourcePopover();
  const popover = createAssistantInlineSourcePopover(anchor);
  document.body.appendChild(popover);
  activeAssistantInlineSourceAnchor = anchor;
  activeAssistantInlineSourcePopover = popover;
  anchor.classList.add('is-active');
  positionAssistantInlineSourcePopover(anchor, popover);
  setTimeout(()=>positionAssistantInlineSourcePopover(anchor, popover), 0);
}

function scheduleCloseAssistantInlineSourcePopover(delay=220){
  clearTimeout(assistantInlineSourceCloseTimer);
  assistantInlineSourceCloseTimer = setTimeout(()=>closeAssistantInlineSourcePopover(), Math.max(0, Number(delay || 0)));
}

function installAssistantInlineSourcePopoverHandlers(){
  if(window.__webaiAssistantInlineSourcePopoverHandlersInstalled) return;
  window.__webaiAssistantInlineSourcePopoverHandlersInstalled = true;
  const sourceSelector = 'a.assistant-inline-source-pill, a.assistant-inline-source-citation';

  document.addEventListener('mouseover', (e)=>{
    const anchor = e.target?.closest?.(sourceSelector);
    if(!anchor) return;
    if(!anchor.closest?.('.bubble.a .bubble-body')) return;
    clearTimeout(assistantInlineSourceCloseTimer);
    clearTimeout(assistantInlineSourceHoverTimer);
    assistantInlineSourceHoverTimer = setTimeout(()=>showAssistantInlineSourcePopover(anchor), 140);
  });

  document.addEventListener('mouseout', (e)=>{
    const anchor = e.target?.closest?.(sourceSelector);
    if(!anchor) return;
    const related = e.relatedTarget;
    if(related && (anchor.contains(related) || activeAssistantInlineSourcePopover?.contains?.(related))) return;
    clearTimeout(assistantInlineSourceHoverTimer);
    scheduleCloseAssistantInlineSourcePopover(220);
  });

  document.addEventListener('click', (e)=>{
    const anchor = e.target?.closest?.(sourceSelector);
    if(!anchor || !anchor.closest?.('.bubble.a .bubble-body')) return;
    e.preventDefault();
    e.stopPropagation();
    try{ e.stopImmediatePropagation(); }catch(_){}
    if(activeAssistantInlineSourceAnchor === anchor && activeAssistantInlineSourcePopover){
      closeAssistantInlineSourcePopover();
    }else{
      showAssistantInlineSourcePopover(anchor);
    }
  });

  document.addEventListener('click', (e)=>{
    if(e.target?.closest?.(sourceSelector)) return;
    if(activeAssistantInlineSourcePopover?.contains?.(e.target)) return;
    closeAssistantInlineSourcePopover();
  });
  document.addEventListener('keydown', (e)=>{
    if(e.key === 'Escape' && activeAssistantInlineSourcePopover) closeAssistantInlineSourcePopover();
  });
  window.addEventListener('resize', ()=>{
    if(activeAssistantInlineSourceAnchor && activeAssistantInlineSourcePopover) positionAssistantInlineSourcePopover(activeAssistantInlineSourceAnchor, activeAssistantInlineSourcePopover);
  });
  window.addEventListener('scroll', ()=>{
    if(activeAssistantInlineSourceAnchor && activeAssistantInlineSourcePopover) positionAssistantInlineSourcePopover(activeAssistantInlineSourceAnchor, activeAssistantInlineSourcePopover);
  }, true);
}

installAssistantInlineSourcePopoverHandlers();

function stripInlineHtmlForLinkLabel(value = ''){
  return decodeHtmlEntities(String(value || ''))
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function buildSafeRawAnchorHtml(href = '', label = ''){
  const cleanLabel = stripInlineHtmlForLinkLabel(label);
  return buildInlineLinkHtml(href, cleanLabel || href);
}

function isAssistantSameAppApiPath(path){
  const p = String(path || '').trim();
  return /^\/api3\/(?:uploads|download|generated-files|generated-download|generated-files-id|generated-download-id)\//i.test(p) || /^\/api3\/(?:remote-image|image_proxy)(?:\?|$)/i.test(p);
}

function isAssistantLocalFileApiPath(path){
  const p = String(path || '').trim();
  return /^\/api3\/(?:uploads|download|generated-files|generated-download|generated-files-id|generated-download-id)\//i.test(p);
}

function assistantLocalFileSourceTypeFromPath(path){
  const p = String(path || '').trim().toLowerCase();
  if(/^\/api3\/(?:generated-files|generated-download|generated-files-id|generated-download-id)\//i.test(p)) return 'generated';
  if(/^\/api3\/(?:uploads|download)\//i.test(p)) return 'upload';
  return '';
}

function _assistantResolvedUrlMeta(url){
  const raw = sanitizeEmbeddableImageUrl(url);
  if(!raw) return { raw:'', href:'', path:'', isSameApp:false, isLocalFile:false };
  if(/^data:image\//i.test(raw)){
    return { raw, href: raw, path:'', isSameApp:false, isLocalFile:false };
  }
  try{
    if(isAssistantSameAppApiPath(raw)){
      const full = new URL(raw, window.location.origin);
      const path = String(full.pathname || '');
      const sourceType = assistantLocalFileSourceTypeFromPath(path);
      return {
        raw,
        href: full.toString(),
        path,
        isSameApp: true,
        isLocalFile: isAssistantLocalFileApiPath(path),
        sourceType,
      };
    }
    const parsed = new URL(raw, window.location.href);
    if(isAssistantSameAppApiPath(parsed.pathname || '')){
      const rel = (parsed.pathname || '') + (parsed.search || '') + (parsed.hash || '');
      const full = new URL(rel, window.location.origin);
      const path = String(full.pathname || '');
      const sourceType = assistantLocalFileSourceTypeFromPath(path);
      return {
        raw,
        href: full.toString(),
        path,
        isSameApp: true,
        isLocalFile: isAssistantLocalFileApiPath(path),
        sourceType,
      };
    }
    return {
      raw,
      href: parsed.toString(),
      path: String(parsed.pathname || ''),
      isSameApp: false,
      isLocalFile: false,
      sourceType: '',
    };
  }catch(_){
    return { raw, href: raw, path:'', isSameApp:false, isLocalFile:false, sourceType:'' };
  }
}

function normalizeAssistantHref(url){
  return _assistantResolvedUrlMeta(url).href || '';
}

function normalizeAssistantDownloadHref(url){
  const meta = _assistantResolvedUrlMeta(url);
  if(!meta.href) return '';
  if(!meta.isLocalFile) return meta.href;
  try{
    const parsed = new URL(meta.href, window.location.origin);
    let nextPath = String(parsed.pathname || '');
    nextPath = nextPath.replace(/^\/api3\/uploads\//i, '/api3/download/');
    nextPath = nextPath.replace(/^\/api3\/generated-files\//i, '/api3/generated-download/');
    nextPath = nextPath.replace(/^\/api3\/generated-files-id\//i, '/api3/generated-download-id/');
    return new URL(nextPath + (parsed.search || '') + (parsed.hash || ''), window.location.origin).toString();
  }catch(_){
    return meta.href;
  }
}

function isAssistantDownloadableFileUrl(url){
  return !!_assistantResolvedUrlMeta(url).isLocalFile;
}

function isWebAiManagedDownloadHref(url){
  const meta = _assistantResolvedUrlMeta(url);
  return !!(meta.isSameApp && /^\/api3\/(?:download|generated-download|generated-download-id)\//i.test(meta.path || ''));
}

function openWebAiManagedDownloadTab(url, emptyMessage=''){
  const href = String(normalizeAssistantDownloadHref(url) || url || '').trim();
  if(!href){
    if(typeof reportAppError === 'function') reportAppError(emptyMessage || markdownUiT('library.preview.no_download_link', null, 'This file has no download link.'));
    return false;
  }
  try{
    const f = document.createElement('iframe');
    f.setAttribute('aria-hidden', 'true');
    f.tabIndex = -1;
    f.style.position = 'fixed';
    f.style.left = '-9999px';
    f.style.top = '-9999px';
    f.style.width = '1px';
    f.style.height = '1px';
    f.style.opacity = '0';
    f.style.pointerEvents = 'none';
    f.style.border = '0';
    document.body.appendChild(f);
    setTimeout(()=>{
      try{ f.src = href; }catch(_){ }
    }, 0);
    setTimeout(()=>{ try{ f.remove(); }catch(_){} }, 60000);
    return true;
  }catch(_){
    try{
      const a = document.createElement('a');
      a.href = href;
      a.rel = 'noopener noreferrer';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      a.remove();
      return true;
    }catch(__){
      if(typeof reportAppError === 'function') reportAppError(markdownUiT('library.preview.open_failed', null, 'Unable to open the link in the browser.'));
      return false;
    }
  }
}

function installWebAiManagedDownloadClickHandler(){
  if(installWebAiManagedDownloadClickHandler._ready) return;
  installWebAiManagedDownloadClickHandler._ready = true;
  document.addEventListener('click', (event)=>{
    const rawTarget = event.target;
    const startEl = rawTarget && rawTarget.nodeType === 1 ? rawTarget : (rawTarget && rawTarget.parentElement ? rawTarget.parentElement : null);
    const anchor = startEl && startEl.closest ? startEl.closest('a') : null;
    if(!anchor) return;
    let href = String(anchor.getAttribute('href') || anchor.href || '').trim();
    const label = anchor.textContent || anchor.getAttribute('aria-label') || anchor.getAttribute('title') || '';
    if(isEmptyAssistantLocalFileRoute(href)){
      const rebuilt = assistantHrefFromEmptyRouteLabel(href, label);
      if(rebuilt){
        href = rebuilt;
        try{ anchor.setAttribute('href', href); }catch(_){}
      }
    }
    if(!isWebAiManagedDownloadHref(href)){
      const lazyHref = resolveAssistantGeneratedFileHrefForUrl(href)
        || assistantHrefFromSandboxOrPathUrl(href, label)
        || assistantHrefFromRelativeFileUrl(href, label)
        || assistantHrefFromEmptyRouteLabel(href, label);
      if(lazyHref){
        href = lazyHref;
        try{
          anchor.setAttribute('href', href);
          anchor.dataset.webaiManagedDownload = '1';
        }catch(_){}
      }
    }
    if(!isWebAiManagedDownloadHref(href)) return;
    event.preventDefault();
    event.stopPropagation();
    openWebAiManagedDownloadTab(href);
  }, true);
}
installWebAiManagedDownloadClickHandler();

function getAssistantArtifactSourceType(file){
  if(!file || typeof file !== 'object') return '';
  const explicit = String(file.source_type || file.sourceType || file.kind || '').trim().toLowerCase();
  if(explicit === 'generated' || explicit === 'upload' || explicit === 'file' || explicit === 'local_file' || explicit === 'kb') return explicit;
  if(file.generated_by_assistant === true) return 'generated';
  const direct = String(file.download_url || file.url || file.view_url || '').trim();
  const meta = _assistantResolvedUrlMeta(direct);
  if(meta.sourceType) return meta.sourceType;
  return '';
}

function assistantArtifactRegistryFileId(file){
  const f = file && typeof file === 'object' ? file : {};
  const reg = f.file_registry && typeof f.file_registry === 'object' ? f.file_registry : {};
  const candidates = [
    f.registry_file_id,
    f.registryFileId,
    f.file_registry_id,
    f.fileRegistryId,
    reg.file_id,
    reg.fileId,
  ];
  const generated = getAssistantArtifactSourceType(f) === 'generated' || f.generated_by_assistant === true;
  const top = String(f.file_id || f.fileId || '').trim();
  if(generated && top && !/^file-/i.test(top) && !/^container[_-]/i.test(top)) candidates.push(top);
  for(const raw of candidates){
    const fid = String(raw || '').trim();
    if(fid && !/[\/\s]/.test(fid) && fid.length <= 240) return fid;
  }
  return '';
}

function assistantGeneratedDownloadHrefFromFileId(fileId=''){
  const fid = String(fileId || '').trim();
  if(!fid) return '';
  return normalizeAssistantDownloadHref('/api3/generated-download-id/' + encodeURIComponent(fid));
}

function getAssistantArtifactDownloadHref(file){
  if(!file || typeof file !== 'object') return '';
  const directById = String(file.download_url_by_id || file.downloadUrlById || '').trim();
  if(directById) return normalizeAssistantDownloadHref(directById);
  const sourceType = getAssistantArtifactSourceType(file);
  if(sourceType === 'generated'){
    const fid = assistantArtifactRegistryFileId(file);
    const byId = assistantGeneratedDownloadHrefFromFileId(fid);
    if(byId) return byId;
  }
  const direct = String(file.download_url || file.url || file.view_url || '').trim();
  const filename = String(file.filename || '').trim();
  if(direct){
    const normalized = normalizeAssistantDownloadHref(direct);
    if(normalized){
      try{
        const meta = _assistantResolvedUrlMeta(normalized);
        if(!meta.isLocalFile && filename && (sourceType === 'generated' || sourceType === 'upload' || sourceType === 'file')) throw new Error('prefer_local_artifact_download');
        const parsed = new URL(normalized, window.location.origin);
        const path = String(parsed.pathname || '').replace(/\/+$/g, '');
        if(!/^\/api3\/(?:download|generated-download|generated-download-id)$/i.test(path)) return normalized;
      }catch(err){
        if(err && String(err.message || '') === 'prefer_local_artifact_download'){
          // 生成/上传产物元数据里混入存储后端链接时，优先走应用自己的下载路由。
        }else{
          if(filename) {
            // 应用路由缺少文件名时，用 filename 重建下载地址。
          }else{
            return normalized;
          }
        }
      }
    }
  }
  if(!filename) return '';
  const base = sourceType === 'generated' ? '/api3/generated-download/' : '/api3/download/';
  return normalizeAssistantDownloadHref(base + encodeURIComponent(filename));
}

function assistantGeneratedFileUrlCandidates(file){
  const f = file && typeof file === 'object' ? file : {};
  const out = [];
  const push = (value)=>{
    const raw = String(value || '').trim();
    if(!raw) return;
    const normalized = normalizeInlineLinkUrl(raw) || raw;
    if(normalized && !out.includes(normalized)) out.push(normalized);
    if(raw && raw !== normalized && !out.includes(raw)) out.push(raw);
  };
  for(const key of ['download_url','downloadUrl','download_url_by_id','downloadUrlById','legacy_download_url','legacyDownloadUrl','view_url','viewUrl','view_url_by_id','viewUrlById','legacy_view_url','legacyViewUrl','url','raw_url','rawUrl','object_url','objectUrl','preview_url','previewUrl','preview_download_url','previewDownloadUrl','sandbox_url','sandboxUrl','sandbox_path','sandboxPath']){
    push(f[key]);
  }
  const reg = f.file_registry && typeof f.file_registry === 'object' ? f.file_registry : {};
  for(const key of ['download_url','view_url','url','object_url','preview_url','preview_download_url']){
    push(reg[key]);
  }
  const annList = [];
  if(Array.isArray(f.annotations)) annList.push(...f.annotations);
  if(f.file_path_annotation && typeof f.file_path_annotation === 'object') annList.push(f.file_path_annotation);
  for(const ann of annList){
    if(!ann || typeof ann !== 'object') continue;
    push(ann.text);
    const fp = ann.file_path && typeof ann.file_path === 'object' ? ann.file_path : {};
    push(fp.path || fp.filename || fp.download_url || fp.url);
  }
  const filename = String(f.relative_path || f.display_filename || f.filename || '').trim();
  if(filename){
    push('sandbox:/mnt/data/' + filename.replace(/^\/+/, ''));
    push('/mnt/data/' + filename.replace(/^\/+/, ''));
  }
  return out;
}

function assistantGeneratedFileUrlKey(url){
  const raw = normalizeInlineLinkUrl(url);
  if(!raw) return '';
  try{
    const parsed = new URL(raw, window.location.href);
    parsed.hash = '';
    return parsed.toString().replace(/&amp;/gi, '&').toLowerCase();
  }catch(_){
    return raw.replace(/&amp;/gi, '&').toLowerCase();
  }
}

function assistantDecodeFileSegment(value=''){
  let raw = String(value || '').trim();
  for(let i = 0; i < 4; i++){
    const before = raw;
    try{ raw = decodeURIComponent(raw); }catch(_){ break; }
    if(raw === before) break;
  }
  return raw;
}

function assistantGeneratedFileNameKey(value){
  let raw = normalizeInlineLinkUrl(value);
  if(!raw) return '';
  try{
    const parsed = new URL(raw, window.location.href);
    raw = String(parsed.pathname || '').split('/').filter(Boolean).pop() || raw;
    raw = assistantDecodeFileSegment(raw);
  }catch(_){
    raw = raw.split(/[?#]/, 1)[0];
    raw = assistantDecodeFileSegment(raw);
  }
  raw = decodeHtmlEntities(String(raw || '')).replace(/^\.\/+/, '').trim();
  if(/[\/\\]/.test(raw)) raw = raw.split(/[\/\\]+/).filter(Boolean).pop() || '';
  if(!/^[^\s\/\\]+\.[A-Za-z0-9][A-Za-z0-9._-]{0,15}$/.test(raw)) return '';
  return raw.toLowerCase();
}

function resolveAssistantGeneratedFileHrefForUrl(url, sessionId=''){
  const key = assistantGeneratedFileUrlKey(url);
  const requestedNameKey = assistantGeneratedFileNameKey(url);
  if(!key && !requestedNameKey) return '';
  const sid = String(sessionId || store?.activeId || '').trim();
  const files = [];
  const pushFile = (f)=>{ if(f && typeof f === 'object') files.push(f); };
  try{
    const s = sid ? getSessionById(sid) : null;
    for(const f of (Array.isArray(s?.generatedFiles) ? s.generatedFiles : [])) pushFile(f);
    for(const f of (Array.isArray(s?.generated_files) ? s.generated_files : [])) pushFile(f);
    const msgs = Array.isArray(s?.messages) ? s.messages : [];
    for(const m of msgs){
      for(const f of (Array.isArray(m?.generatedFiles) ? m.generatedFiles : [])) pushFile(f);
      for(const f of (Array.isArray(m?.generated_files) ? m.generated_files : [])) pushFile(f);
      const c = m?.content;
      if(c && typeof c === 'object' && !Array.isArray(c) && c._kind === 'genfiles'){
        for(const f of (Array.isArray(c.files) ? c.files : [])) pushFile(f);
      }
    }
  }catch(_){ }
  try{
    const rt = sid ? ensureSessionRuntime(sid) : null;
    for(const f of (Array.isArray(rt?.draftFiles) ? rt.draftFiles : [])) pushFile(f);
  }catch(_){ }
  const seen = new Set();
  for(const file of files){
    const href = String(getAssistantArtifactDownloadHref(file) || '').trim();
    if(!href) continue;
    const filenameKey = assistantGeneratedFileNameKey(file.filename || file.display_filename || '');
    if(requestedNameKey && filenameKey && requestedNameKey === filenameKey) return href;
    for(const candidate of assistantGeneratedFileUrlCandidates(file)){
      const ckey = assistantGeneratedFileUrlKey(candidate);
      if(!ckey || seen.has(ckey)) continue;
      seen.add(ckey);
      if(ckey === key) return href;
    }
  }
  return '';
}

function buildAssistantGeneratedFileLinksText(files){
  const list = Array.isArray(files) ? files : [];
  const lines = [];
  const seen = new Set();
  for(const item of list){
    const filename = String(item?.filename || '').trim();
    const href = String(getAssistantArtifactDownloadHref(item) || '').trim();
    const key = `${filename}|${href}`.toLowerCase();
    if(!filename || !href || seen.has(key)) continue;
    seen.add(key);
    lines.push(`- [${filename}](${href})`);
  }
  if(!lines.length) return '';
  return `已生成文件：\n${lines.join('\n')}`;
}

function appendAssistantGeneratedFileLinks(text, files){
  // 不替助手补固定文件话术或链接；如果助手没在正文里发链接，下一轮让助手自己补发。
  // 已发出的生成文件链接仍会在 markdown 渲染时按元数据修正为可用下载地址。
  return String(text || '').trim();
}

function stripAssistantGeneratedFileDeliveryText(text, files){
  const raw = String(text || '');
  if(!raw) return raw;
  const list = Array.isArray(files) ? files : [];
  const names = list.map(f => String(f?.filename || '').trim().toLowerCase()).filter(Boolean);
  if(!names.length) return raw;
  const matchesGeneratedFile = (line)=>{
    const lower = String(line || '').toLowerCase();
    return names.some(name => lower.includes(name));
  };
  const cleaned = [];
  for(const line of raw.split(/\r?\n/)){
    const trimmed = String(line || '').trim();
    const compact = trimmed.replace(/\s+/g, '');
    if(!trimmed){
      cleaned.push(line);
      continue;
    }
    if((compact.startsWith('下载链接：') || compact.startsWith('下载链接:') || compact.startsWith('文件下载链接：') || compact.startsWith('文件下载链接:') || compact.startsWith('文件链接：') || compact.startsWith('文件链接:')) && matchesGeneratedFile(trimmed)){
      continue;
    }
    if((compact === '已生成文件：' || compact === '已生成文件:' || compact === '生成文件：' || compact === '生成文件:') && names.length){
      continue;
    }
    if(/^[-*•]?\s*\[[^\]]+\]\([^\)]+\)\s*$/u.test(trimmed) && matchesGeneratedFile(trimmed)){
      continue;
    }
    if(['文件下载链接见上。','文件下载链接见上','文件下载链接见下。','文件下载链接见下','下载链接见上。','下载链接见上','下载链接见下。','下载链接见下','见下方附件。','见上方附件。'].includes(compact)){
      continue;
    }
    cleaned.push(line);
  }
  return cleaned.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

function _assistantGeneratedFilesForSession(sessionId){
  const sid = String(sessionId || store?.activeId || '').trim();
  const out = [];
  const seen = new Set();
  const add = (f)=>{
    if(!f) return;
    const filename = String(f.filename || '').trim();
    const href = getAssistantArtifactDownloadHref(f);
    if(!filename || !href) return;
    const key = filename.toLowerCase() + '|' + href;
    if(seen.has(key)) return;
    seen.add(key);
    out.push({ filename, href });
  };
  try{
    const s = sid ? getSessionById(sid) : null;
    const msgs = Array.isArray(s?.messages) ? s.messages : [];
    for(const m of msgs){
      const c = m?.content;
      if(c && typeof c === 'object' && !Array.isArray(c) && c._kind === 'genfiles'){
        for(const f of (Array.isArray(c.files) ? c.files : [])) add(f);
      }
    }
  }catch(_){ }
  try{
    const rt = sid ? ensureSessionRuntime(sid) : null;
    for(const f of (Array.isArray(rt?.draftFiles) ? rt.draftFiles : [])) add(f);
  }catch(_){ }
  out.sort((a,b)=> String(b.filename || '').length - String(a.filename || '').length);
  return out;
}

function getAssistantMessageGeneratedFiles(msg, sessionId=''){
  const out = [];
  const seen = new Set();
  const pushOne = (file)=>{
    if(!file || typeof file !== 'object') return;
    const filename = String(file.filename || '').trim();
    const href = String(getAssistantArtifactDownloadHref(file) || file.download_url || file.url || file.view_url || '').trim();
    if(!filename || !href) return;
    const key = `${filename}|${href}`.toLowerCase();
    if(seen.has(key)) return;
    seen.add(key);
    out.push({ ...file });
  };
  const pushList = (list)=>{
    if(Array.isArray(list)) list.forEach(pushOne);
  };
  const m = msg && typeof msg === 'object' ? msg : null;
  if(m){
    pushList(m.generatedFiles);
    pushList(m.generated_files);
    pushList(m.files);
    const c = m.content;
    if(c && typeof c === 'object' && !Array.isArray(c) && c._kind === 'genfiles') pushList(c.files);
  }
  if(!out.length && sessionId && m?._useRuntimeDraftFiles){
    try{ pushList(ensureSessionRuntime(sessionId)?.draftFiles || []); }catch(_){ }
  }
  return _normalizePendingAssistantFiles(out);
}

function generatedFilesSignature(files){
  return _normalizePendingAssistantFiles(files || []).map(f => {
    const filename = String(f.filename || '').trim();
    const href = String(getAssistantArtifactDownloadHref(f) || f.download_url || f.url || f.view_url || '').trim();
    return `${filename}|${href}`;
  }).filter(Boolean).join('||');
}

function generatedFileMetaLabel(file){
  const f = file && typeof file === 'object' ? file : {};
  const prefix = assistantFileSourceRoleLabel(f);
  try{
    const ext = String(f.ext || (String(f.filename || '').includes('.') ? String(f.filename || '').split('.').pop() : '') || '').trim().toLowerCase();
    const label = attachmentMetaLabel({ _kind:'file', source_type:'generated', source_role:normalizeAssistantFileSourceRole(f), filename:f.filename || '', ext, size:f.size || 0 });
    if(label) return `${prefix} · ${label}`;
  }catch(_){ }
  return `${prefix} · ${markdownUiT('composer.attachment.file', null, 'File')}`;
}

function buildAssistantGeneratedFilesNode(files){
  const list = _normalizePendingAssistantFiles(files || []);
  if(!list.length) return null;
  const wrap = document.createElement('div');
  wrap.className = 'generated-files-card bubble-attachment';
  wrap.dataset.generatedFilesSignature = generatedFilesSignature(list);
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:8px;margin:10px 0 0 0;';
  for(const file of list){
    const filename = String(file.filename || '').trim();
    const href = String(getAssistantArtifactDownloadHref(file) || '').trim();
    if(!filename || !href) continue;
    if(typeof buildUnifiedFileCardNode === 'function'){
      const unifiedCard = buildUnifiedFileCardNode({
        filename,
        metaText:generatedFileMetaLabel(file),
        className:'file-card-assistant',
        downloadHref:href,
      });
      unifiedCard.dataset.sourceRole = normalizeAssistantFileSourceRole(file);
      unifiedCard.dataset.sourceType = 'generated';
      wrap.appendChild(unifiedCard);
      continue;
    }
    const card = document.createElement('div');
    card.className = 'file-card file-card-chat file-card-assistant';
    card.dataset.sourceRole = normalizeAssistantFileSourceRole(file);
    card.dataset.sourceType = 'generated';

    const icon = document.createElement('div');
    icon.className = 'file-icon';
    icon.innerHTML = attachmentIconSvg(false);
    card.appendChild(icon);

    const main = document.createElement('div');
    main.className = 'file-main';

    const name = document.createElement('div');
    name.className = 'file-name';
    name.textContent = filename;
    main.appendChild(name);

    const meta = document.createElement('div');
    meta.className = 'file-meta';
    meta.textContent = generatedFileMetaLabel(file);
    main.appendChild(meta);

    const download = document.createElement('a');
    download.className = 'file-download';
    download.href = href;
    download.textContent = markdownUiT('library.download', null, 'Download');
    download.target = '_blank';
    download.rel = 'noopener noreferrer';
    download.dataset.webaiManagedDownload = '1';
    main.appendChild(download);

    card.appendChild(main);
    wrap.appendChild(card);
  }
  return wrap.childElementCount ? wrap : null;
}

function syncAssistantGeneratedFilesInBody(body, files){
  if(!body) return null;
  const list = _normalizePendingAssistantFiles(files || []);
  const existing = body.querySelector(':scope > .generated-files-card');
  if(!list.length){
    if(existing) existing.remove();
    return null;
  }
  const sig = generatedFilesSignature(list);
  if(existing && existing.dataset.generatedFilesSignature === sig) return existing;
  const node = buildAssistantGeneratedFilesNode(list);
  if(!node){
    if(existing) existing.remove();
    return null;
  }
  if(existing) existing.replaceWith(node);
  else body.appendChild(node);
  return node;
}


function linkifyAssistantGeneratedFileMentions(root, sessionId){
  // 不再把正文里“普通提及的文件名”自动替换成链接。
  // 真实可下载文件仍走显式 markdown 链接 / 文件卡片，避免像 xxx.docx、report.pdf 这类普通文本被误渲染成链接。
  return;
}

function isLikelyEmbeddableImageUrl(url){
  const u = sanitizeEmbeddableImageUrl(url);
  if(!u) return false;
  if(/^data:image\/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=:+-]+)*,/.test(u)) return true;
  if(/^\/api3\/remote-image\?url=/i.test(u)) return true;
  if(!/^https?:\/\//i.test(u)) return false;
  if (/\.(png|jpe?g|webp|gif|bmp|svg)(?:[?#].*)?$/i.test(u)) return true;
  try{
    const parsed = new URL(u);
    const host = (parsed.hostname || '').toLowerCase();
    return [
      'images.unsplash.com',
      'images.pexels.com',
      'upload.wikimedia.org',
      'i.imgur.com',
      'imgur.com',
      'live.staticflickr.com',
      'wx1.sinaimg.cn',
      'pbs.twimg.com',
      'images.ctfassets.net',
      'cdn.pixabay.com'
    ].some(domain => host === domain || host.endsWith('.' + domain));
  }catch(_){
    return false;
  }
}

function normalizeInlineEmbeddableImageMarkdown(text){
  let src = String(text ?? '');
  if(!src) return src;

  src = src.replace(/!\[([^\]]*)\]\s*\n+\s*\(/g, '![$1](');

  src = src.replace(/^\s*\((data:image\/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=:+-]+)*,[^\n]+)\)\s*$/gim, (m, url)=>{
    const clean = sanitizeEmbeddableImageUrl(url);
    return isLikelyEmbeddableImageUrl(clean) ? `![](${clean})` : m;
  });

  src = src.replace(/^\s*(data:image\/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=:+-]+)*,[^\n]+)\s*$/gim, (m, url)=>{
    const clean = sanitizeEmbeddableImageUrl(url);
    return isLikelyEmbeddableImageUrl(clean) ? `![](${clean})` : m;
  });

  src = src.replace(/^\s*\((https?:\/\/[^\s)]+)\)\s*$/gim, (m, url)=>{
    const clean = sanitizeEmbeddableImageUrl(url);
    return isLikelyEmbeddableImageUrl(clean) ? `![](${clean})` : m;
  });

  src = src.replace(/^\s*(https?:\/\/[^\s]+\.(?:png|jpe?g|webp|gif|bmp|svg)(?:[?#][^\s]*)?)\s*$/gim, (m, url)=>{
    const clean = sanitizeEmbeddableImageUrl(url);
    return isLikelyEmbeddableImageUrl(clean) ? `![](${clean})` : m;
  });

  return src;
}

function buildImageFallbackHtml(url, label){
  const safeUrl = escapeHtml(sanitizeEmbeddableImageUrl(url));
  const text = escapeHtml(label || `🔗 ${markdownUiT('citation.view_image', null, 'View image')}`);
  return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${text}</a>`;
}

function buildInlineImageHtml(url, alt){
  const normalizedUrl = sanitizeEmbeddableImageUrl(url);
  const safeUrl = escapeHtml(normalizedUrl);
  const safeAlt = escapeHtml(alt || markdownUiT('citation.related_image', null, 'Related image'));
  const fallback = escapeHtml(buildImageFallbackHtml(normalizedUrl, alt || `🔗 ${markdownUiT('citation.view_image', null, 'View image')}`));
  return `<img class="inline-img is-loading" loading="lazy" decoding="async" fetchpriority="low" data-lazy="1" src="${safeUrl}" alt="${safeAlt}" data-fallback-html="${fallback}">`;
}

const LATEX_SYMBOL_REPLACERS = [
  [/\\cdots\b/g, '⋯'],
  [/\\ldots\b/g, '…'],
  [/\\times\b/g, '×'],
  [/\\div\b/g, '÷'],
  [/\\pm\b/g, '±'],
  [/\\mp\b/g, '∓'],
  [/\\neq\b|\\ne\b/g, '≠'],
  [/\\leq\b|\\le\b/g, '≤'],
  [/\\geq\b|\\ge\b/g, '≥'],
  [/\\approx\b/g, '≈'],
  [/\\equiv\b/g, '≡'],
  [/\\propto\b/g, '∝'],
  [/\\infty\b/g, '∞'],
  [/\\partial\b/g, '∂'],
  [/\\nabla\b/g, '∇'],
  [/\\forall\b/g, '∀'],
  [/\\exists\b/g, '∃'],
  [/\\nexists\b/g, '∄'],
  [/\\in\b/g, '∈'],
  [/\\notin\b/g, '∉'],
  [/\\ni\b/g, '∋'],
  [/\\subseteq\b/g, '⊆'],
  [/\\subset\b/g, '⊂'],
  [/\\supseteq\b/g, '⊇'],
  [/\\supset\b/g, '⊃'],
  [/\\cup\b/g, '∪'],
  [/\\cap\b/g, '∩'],
  [/\\emptyset\b/g, '∅'],
  [/\\setminus\b/g, '∖'],
  [/\\wedge\b/g, '∧'],
  [/\\vee\b/g, '∨'],
  [/\\neg\b|\\lnot\b/g, '¬'],
  [/\\oplus\b/g, '⊕'],
  [/\\otimes\b/g, '⊗'],
  [/\\to\b|\\rightarrow\b/g, '→'],
  [/\\leftarrow\b/g, '←'],
  [/\\leftrightarrow\b/g, '↔'],
  [/\\Rightarrow\b/g, '⇒'],
  [/\\Leftarrow\b/g, '⇐'],
  [/\\Leftrightarrow\b|\\iff\b/g, '⇔'],
  [/\\mapsto\b/g, '↦'],
  [/\\sin\b/g, 'sin'],
  [/\\cos\b/g, 'cos'],
  [/\\tan\b/g, 'tan'],
  [/\\log\b/g, 'log'],
  [/\\ln\b/g, 'ln'],
  [/\\alpha\b/g, 'α'],
  [/\\beta\b/g, 'β'],
  [/\\gamma\b/g, 'γ'],
  [/\\delta\b/g, 'δ'],
  [/\\epsilon\b|\\varepsilon\b/g, 'ε'],
  [/\\theta\b|\\vartheta\b/g, 'θ'],
  [/\\lambda\b/g, 'λ'],
  [/\\mu\b/g, 'μ'],
  [/\\pi\b|\\varpi\b/g, 'π'],
  [/\\rho\b|\\varrho\b/g, 'ρ'],
  [/\\sigma\b|\\varsigma\b/g, 'σ'],
  [/\\tau\b/g, 'τ'],
  [/\\phi\b|\\varphi\b/g, 'φ'],
  [/\\omega\b/g, 'ω'],
  [/\\Gamma\b/g, 'Γ'],
  [/\\Delta\b/g, 'Δ'],
  [/\\Theta\b/g, 'Θ'],
  [/\\Lambda\b/g, 'Λ'],
  [/\\Pi\b/g, 'Π'],
  [/\\Sigma\b/g, 'Σ'],
  [/\\Phi\b/g, 'Φ'],
  [/\\Omega\b/g, 'Ω'],
];

function normalizeMathSource(tex){
  return String(tex ?? '').replace(/\r\n/g, '\n').trim();
}

function latexToPlainMathText(tex){
  let out = normalizeMathSource(tex);
  if(!out) return out;
  out = out.replace(/\\begin\{[^{}]+\}|\\end\{[^{}]+\}/g, '');
  out = out.replace(/\\\\/g, '\n');
  out = out.replace(/\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle)\b/g, '');
  out = out.replace(/\\left\b|\\right\b/g, '');
  out = out.replace(/\\,/g, ' ');
  out = out.replace(/\\;/g, ' ');
  out = out.replace(/\\:/g, ' ');
  out = out.replace(/\\!/g, '');
  out = out.replace(/\\quad\b/g, '  ');
  out = out.replace(/\\qquad\b/g, '    ');
  for(let i = 0; i < 4; i++){
    out = out.replace(/\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g, '($1)/($2)');
    out = out.replace(/\\sqrt(?:\[[^\]]+\])?\s*\{([^{}]+)\}/g, '√($1)');
    out = out.replace(/\\(?:text|mathrm|operatorname)\s*\{([^{}]+)\}/g, '$1');
  }
  LATEX_SYMBOL_REPLACERS.forEach(([pattern, replacement]) => {
    out = out.replace(pattern, replacement);
  });
  out = out.replace(/\\[a-zA-Z]+\b/g, (m)=>m.slice(1));
  out = out.replace(/[{}]/g, '');
  out = out.replace(/\s+/g, ' ').trim();
  return out;
}

function buildMathFallbackHtml(tex, displayMode=false){
  const plain = latexToPlainMathText(tex);
  const escaped = escapeHtml(plain)
    .replace(/\^\{([^{}]+)\}/g, '<sup>$1</sup>')
    .replace(/_\{([^{}]+)\}/g, '<sub>$1</sub>')
    .replace(/\^([^\s<>{}]+)/g, '<sup>$1</sup>')
    .replace(/_([^\s<>{}]+)/g, '<sub>$1</sub>');
  const cls = displayMode ? 'math-display' : 'math-inline';
  return `<span class="${cls} math-fallback" data-math-mode="${displayMode ? 'display' : 'inline'}">${escaped || escapeHtml(normalizeMathSource(tex))}</span>`;
}

function renderMathHtml(tex, displayMode=false){
  const raw = normalizeMathSource(tex);
  if(!raw) return '';
  try{
    if(window.katex && typeof window.katex.renderToString === 'function'){
      const rendered = window.katex.renderToString(raw, {
        throwOnError:false,
        displayMode:!!displayMode,
        strict:'ignore',
        output:'html',
      });
      return `<span class="${displayMode ? 'math-display' : 'math-inline'}">${rendered}</span>`;
    }
  }catch(_){ }
  return buildMathFallbackHtml(raw, displayMode);
}

function tokenizeMathSegments(text, stash){
  let out = String(text ?? '');
  if(!out) return out;
  out = out.replace(/\\\[([\s\S]*?)\\\]/g, (_, tex)=>`\n${stash(renderMathHtml(tex, true))}\n`);
  out = out.replace(/\$\$([\s\S]*?)\$\$/g, (_, tex)=>`\n${stash(renderMathHtml(tex, true))}\n`);
  out = out.replace(/\\\(([\s\S]*?)\\\)/g, (_, tex)=>stash(renderMathHtml(tex, false)));
  return out;
}

function renderInlineRich(text){
  const tokenMap = new Map();
  let tokenSeed = 0;
  const stash = (html) => {
    const key = `__HTML_TOKEN_${tokenSeed++}__`;
    tokenMap.set(key, html);
    return key;
  };

  let src = tokenizeMathSegments(normalizeInlineEmbeddableImageMarkdown(text), stash);
  src = src.replace(/<a\b[^>]*\bhref\s*=\s*(["'])([^"']{1,2000})\1[^>]*>([\s\S]*?)<\/a>/gi, (_, _quote, href, label)=>{
    return stash(buildSafeRawAnchorHtml(href, label));
  });
  src = src.replace(/&lt;a\b[\s\S]{0,1600}?\bhref\s*=\s*(?:&quot;|&#34;|")([^"&]{1,2000})(?:&quot;|&#34;|")[\s\S]{0,1600}?&gt;([\s\S]*?)&lt;\/a&gt;/gi, (_, href, label)=>{
    return stash(buildSafeRawAnchorHtml(href, label));
  });
  src = src.replace(/(?:<|&lt;)\s*((?:https?:\/\/|(?:\.\/)?\/?api3\/(?:remote-image\?url=|uploads\/|download\/|generated-files\/|generated-download\/|generated-files-id\/|generated-download-id\/)|sandbox:|data:image\/)[^\s<]+?)\s*(?:>|&gt;?)/gi, (_, url)=>stash(buildInlineLinkHtml(url)));
  src = src.replace(/\[知识库引用\s*[:：]\s*([^\]]+?)\]/g, (_, label)=>stash(buildKnowledgeBaseCitationChipHtml(label)));
  let html = escapeHtml(src);

  html = html.replace(/!\[([^\]]*)\]\(((?:https?:\/\/[^\s)]+)|(?:(?:\.\/)?\/?api3\/(?:remote-image\?url=[^\s)]+|uploads\/[^\s)]+|download\/[^\s)]+|generated-files\/[^\s)]+|generated-download\/[^\s)]+|generated-files-id\/[^\s)]+|generated-download-id\/[^\s)]+))|(?:data:image\/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=:+-]+)*,[^\s)]+))\)/gi, (_, alt, url)=>{
  if(!isLikelyEmbeddableImageUrl(url)) return stash(buildImageFallbackHtml(url, alt || `🔗 ${markdownUiT('citation.view_image', null, 'View image')}`));
    return stash(buildInlineImageHtml(url, alt));
  });

  if(assistantInlineSourcePillsEnabled){
    html = html.replace(/\u3010\s*\[([^\]]{1,90})\]\(((?:https?:\/\/[^\s)\u3011]+))\)\s*\u3011/gi, (m, label, url)=>{
      const citation = buildInlineSourceCitationHtml(url, label);
      return citation ? stash(citation) : m;
    });

    html = html.replace(/\u3010\s*((?:https?:\/\/[^\s<>"'\u3011]+))\s*\u3011/gi, (m, url)=>{
      const host = assistantInlineSourceHost(url);
      const citation = host ? buildInlineSourceCitationHtml(url, host) : '';
      return citation ? stash(citation) : m;
    });

    html = html.replace(/\u3010\s*(([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?:\/[^\s<>'"\u3010\u3011()]*)?)\s*\u3011/gi, (m, hostLabel)=>{
      const citation = buildInlineSourceCitationFromBareHostHtml(hostLabel);
      return citation ? stash(citation) : m;
    });

    html = html.replace(/[（(]\s*\[([^\]]{1,90})\]\(((?:https?:\/\/[^\s)）]+))\)\s*[）)]/gi, (m, label, url)=>{
      const citation = buildInlineSourceCitationHtml(url, label);
      return citation ? stash(citation) : m;
    });

    html = html.replace(/[（(]\s*((?:https?:\/\/[^\s<>"'）\]\)]+))\s*[）)]/gi, (m, url)=>{
      const host = assistantInlineSourceHost(url);
      const citation = host ? buildInlineSourceCitationHtml(url, host) : '';
      return citation ? stash(citation) : m;
    });

    html = html.replace(/[（(]\s*(([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?:\/[^\s<>'"（）()，。；;]*)?)\s*[）)]/gi, (m, hostLabel)=>{
      const citation = buildInlineSourceCitationFromBareHostHtml(hostLabel);
      return citation ? stash(citation) : m;
    });
  }

  html = html.replace(/(?<!!)\[([^\]]+)\]\(((?:https?:\/\/[^\s)]+)|(?:(?:\.\/)?\/?api3\/(?:remote-image\?url=[^\s)]+|uploads\/[^\s)]+|download\/[^\s)]+|generated-files\/[^\s)]+|generated-download\/[^\s)]+|generated-files-id\/[^\s)]+|generated-download-id\/[^\s)]+))|(?:sandbox:[^\s)]+)|(?:data:image\/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=:+-]+)*,[^\s)]+)|(?:\.?\/?[^\/\\\s)]+\.[A-Za-z0-9][A-Za-z0-9._-]{0,15}(?:\?[^\s)]*)?))\)/gi, (_, label, url)=>{
    return stash(buildInlineLinkHtml(url, label));
  });

  html = html.replace(/\*\*([^*]+(?:\n[^*]+)*)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(^|[^*])\*([^*]+(?:\n[^*]+)*)\*(?!\*)/g, '$1<em>$2</em>');
  html = html.replace(/~~([^~]+(?:\n[^~]+)*)~~/g, '<del>$1</del>');
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  const urlRe = /((?:https?:\/\/[^\s<>"'）\]\)】一-鿿]+)|(?:(?:\.\/)?\/?api3\/(?:remote-image\?url=[^\s<>"'）\]\)】]+|uploads\/[^\s<>"'）\]\)】]+|download\/[^\s<>"'）\]\)】]+|generated-files\/[^\s<>"'）\]\)】]+|generated-download\/[^\s<>"'）\]\)】]+|generated-files-id\/[^\s<>"'）\]\)】]+|generated-download-id\/[^\s<>"'）\]\)】]+))|(?:sandbox:[^\s<>"'）\]\)】]+)|(?:data:image\/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=:+-]+)*,[A-Za-z0-9+/=_-]+))([.,;!?]+)?/g;
  html = html.replace(urlRe, (m, url, tail) => {
    const cleanUrl = normalizeInlineLinkUrl(url);
    const t = tail ? escapeHtml(tail) : "";
    return stash(buildInlineLinkHtml(cleanUrl) + t);
  });

  html = html.replace(/\n/g, "<br>");
  for(const [token, snippet] of tokenMap.entries()){
    html = html.split(token).join(snippet);
  }
  return html;
}
function markdownIndentUnits(rawIndent){
  let units = 0;
  for(const ch of String(rawIndent || '')){
    if(ch === '\t'){ const offset = units % 4; units += offset ? 4 - offset : 4; }
    else units += 1;
  }
  return units;
}

function parseMarkdownListMarker(line){
  const raw = String(line ?? '');
  const m = raw.match(/^([ \t]*)([-*+]|\d{1,9}[.)])(\s+)([\s\S]+)$/);
  if(!m) return null;
  const marker = String(m[2] || '');
  const ordered = /^\d{1,9}[.)]$/.test(marker);
  const indent = markdownIndentUnits(m[1] || '');
  const spacing = String(m[3] || ' ');
  return {
    indent,
    type: ordered ? 'ol' : 'ul',
    start: ordered ? Math.max(1, parseInt(marker, 10) || 1) : 1,
    marker,
    markerIndentRaw: String(m[1] || ''),
    markerWidth: marker.length + markdownIndentUnits(spacing),
    contentIndent: indent + marker.length + markdownIndentUnits(spacing),
    text: String(m[4] || ''),
  };
}
function parseMarkdownTaskListText(text){
  const m = String(text ?? '').match(/^\[([ xX])\]\s+([\s\S]*)$/);
  if(!m) return null;
  return { checked: String(m[1] || '').toLowerCase() === 'x', text: String(m[2] || '') };
}

function renderMarkdownListItemContent(text){
  const task = parseMarkdownTaskListText(text);
  if(task){
    const stateClass = task.checked ? ' is-checked' : '';
    const mark = task.checked ? '✓' : '';
    return `<span class="task-list-checkbox${stateClass}" aria-hidden="true">${mark}</span><span class="task-list-content">${renderInlineRich(task.text)}</span>`;
  }
  return renderInlineRich(text);
}

function normalizeMarkdownLineIndent(line, removeUnits){
  const raw = String(line ?? '');
  let remaining = Math.max(0, Number(removeUnits || 0));
  let outIdx = 0;
  for(let i = 0; i < raw.length && remaining > 0; i += 1){
    const ch = raw[i];
    if(ch === ' '){ remaining -= 1; outIdx = i + 1; continue; }
    if(ch === '\t'){
      const tabUnits = 4;
      remaining -= tabUnits;
      outIdx = i + 1;
      continue;
    }
    break;
  }
  return raw.slice(outIdx);
}

function stripOuterParagraphHtml(html){
  const src = String(html || '').trim();
  if(!src) return '';
  const m = src.match(/^<p>([\s\S]*)<\/p>$/);
  if(!m) return src;
  const inner = m[1];
  if(/<\/p>\s*<p>/i.test(inner)) return src;
  return inner;
}

function isMarkdownTableStart(lines, index){
  const cur = String(lines?.[index] ?? '').trim();
  const next = String(lines?.[index + 1] ?? '').trim();
  return !!(cur && next && isMarkdownTableRow(cur) && isMarkdownTableSeparator(next));
}

function isMarkdownBlockStarter(lines, index){
  const line = String(lines?.[index] ?? '');
  const trimmed = line.trim();
  if(!trimmed) return true;
  if(trimmed === '\\[' || trimmed === '$$') return true;
  if(/^\\begin\{(equation\*?|align\*?|aligned|gather\*?|multline\*?)\}$/.test(trimmed)) return true;
  if(/^(#{1,4})\s+/.test(trimmed)) return true;
  if(parseCodeFenceLine(line)) return true;
  if(/^>\s?/.test(trimmed)) return true;
  if(/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) return true;
  if(isMarkdownTableStart(lines, index)) return true;
  const item = parseMarkdownListMarker(line);
  return !!(item && !/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed));
}

function renderMarkdownListBlock(lines, startIndex, baseIndent){
  const first = parseMarkdownListMarker(lines[startIndex]);
  if(!first) return { html:'', nextIndex:startIndex + 1 };
  const listIndent = first.indent;
  const listType = first.type;
  const startAttr = listType === 'ol' && first.start > 1 ? ` start="${first.start}"` : '';
  const items = [];
  let hasTask = false;
  let i = startIndex;

  while(i < lines.length){
    const marker = parseMarkdownListMarker(lines[i]);
    const trimmed = String(lines[i] ?? '').trim();
    if(!marker || marker.indent !== listIndent || marker.type !== listType || /^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) break;

    let itemLines = [marker.text];
    const task = parseMarkdownTaskListText(marker.text);
    if(task){
      hasTask = true;
      itemLines[0] = task.text;
    }
    i += 1;

    while(i < lines.length){
      const raw = String(lines[i] ?? '');
      const lineTrimmed = raw.trim();
      const nextMarker = parseMarkdownListMarker(raw);
      if(nextMarker && nextMarker.indent <= listIndent) break;
      if(lineTrimmed === ''){
        itemLines.push('');
        i += 1;
        continue;
      }
      const lineIndent = markdownIndentUnits((raw.match(/^[ \t]*/) || [''])[0]);
      if(lineIndent <= listIndent && isMarkdownBlockStarter(lines, i)) break;
      const removeIndent = Math.min(marker.contentIndent || (listIndent + 2), lineIndent);
      itemLines.push(normalizeMarkdownLineIndent(raw, removeIndent));
      i += 1;
    }

    let itemHtml = renderMarkdownBlocksHtml(itemLines);
    itemHtml = stripOuterParagraphHtml(itemHtml);
    if(task){
      const stateClass = task.checked ? ' is-checked' : '';
      const mark = task.checked ? '✓' : '';
      itemHtml = `<span class="task-list-checkbox${stateClass}" aria-hidden="true">${mark}</span><span class="task-list-content">${itemHtml}</span>`;
    }
    items.push(`<li${task ? ' class="task-list-item"' : ''}>${itemHtml}</li>`);
  }

  const cls = hasTask && listType === 'ul' ? ' class="contains-task-list"' : '';
  return { html:`<${listType}${startAttr}${cls}>${items.join('')}</${listType}>`, nextIndex:i };
}

function renderMarkdownBlocksHtml(inputLines){
  const lines = Array.isArray(inputLines) ? inputLines.map(line => String(line ?? '')) : String(inputLines ?? '').replace(/\r?\n/g, '\n').split('\n');
  const parts = [];
  let i = 0;

  const pushParagraph = (paragraphLines)=>{
    const content = (Array.isArray(paragraphLines) ? paragraphLines : []).join('\n').trim();
    if(content) parts.push('<p>' + renderInlineRich(content) + '</p>');
  };

  while(i < lines.length){
    const line = lines[i];
    const trimmed = line.trim();

    if(!trimmed){
      i += 1;
      continue;
    }

    if(trimmed === '\\[' || trimmed === '$$'){
      const endMark = trimmed === '\\[' ? '\\]' : '$$';
      const mathLines = [];
      let j = i + 1;
      let foundEnd = false;
      for(; j < lines.length; j += 1){
        const mathLine = lines[j];
        if(mathLine.trim() === endMark){
          foundEnd = true;
          break;
        }
        mathLines.push(mathLine);
      }
      if(foundEnd){
        parts.push(renderMathHtml(mathLines.join('\n'), true));
        i = j + 1;
        continue;
      }
    }

    const beginMatch = trimmed.match(/^\\begin\{(equation\*?|align\*?|aligned|gather\*?|multline\*?)\}$/);
    if(beginMatch){
      const env = beginMatch[1];
      const mathLines = [trimmed];
      let j = i + 1;
      let foundEnd = false;
      for(; j < lines.length; j += 1){
        const mathLine = lines[j];
        mathLines.push(mathLine);
        if(mathLine.trim() === `\\end{${env}}`){
          foundEnd = true;
          break;
        }
      }
      if(foundEnd){
        parts.push(renderMathHtml(mathLines.join('\n'), true));
        i = j + 1;
        continue;
      }
    }

    const openingFence = parseCodeFenceLine(line) || (trimmed !== line ? parseCodeFenceLine(trimmed) : null);
    if(openingFence){
      const originalIndent = markdownIndentUnits((String(line ?? '').match(/^[ \t]*/) || [''])[0]);
      const stripFenceIndent = parseCodeFenceLine(line) ? 0 : originalIndent;
      const codeLines = [];
      let j = i + 1;
      for(; j < lines.length; j += 1){
        const candidate = stripFenceIndent ? normalizeMarkdownLineIndent(lines[j], stripFenceIndent) : lines[j];
        if(isCodeFenceCloseLine(candidate, openingFence)){
          break;
        }
        codeLines.push(candidate);
      }
      parts.push(renderCodeBlockHtml(codeLines.join('\n'), openingFence.lang, `nested_${i}`, false));
      i = j < lines.length ? j + 1 : j;
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if(heading){
      const level = Math.min(4, heading[1].length);
      parts.push(`<h${level}>${renderInlineRich(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    if(/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)){
      parts.push('<hr>');
      i += 1;
      continue;
    }

    if(/^>\s?/.test(trimmed)){
      const quoteLines = [];
      while(i < lines.length){
        const quoteMatch = String(lines[i] ?? '').trim().match(/^>\s?(.*)$/);
        if(!quoteMatch) break;
        quoteLines.push(quoteMatch[1] || '');
        i += 1;
      }
      parts.push(`<blockquote>${renderMarkdownBlocksHtml(quoteLines)}</blockquote>`);
      continue;
    }

    if(isMarkdownTableStart(lines, i)){
      const tableLines = [];
      while(i < lines.length && isMarkdownTableRow(String(lines[i] ?? '').trim())){
        tableLines.push(String(lines[i] ?? '').trim());
        i += 1;
      }
      const tableHtml = renderMarkdownTable(tableLines);
      if(tableHtml){
        parts.push(tableHtml);
      }else{
        pushParagraph(tableLines);
      }
      continue;
    }

    const listItem = parseMarkdownListMarker(line);
    if(listItem && !/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)){
      const result = renderMarkdownListBlock(lines, i, 0);
      if(result.html) parts.push(result.html);
      i = Math.max(result.nextIndex, i + 1);
      continue;
    }

    const paragraph = [line];
    i += 1;
    while(i < lines.length){
      if(!String(lines[i] ?? '').trim()) break;
      if(isMarkdownBlockStarter(lines, i)) break;
      paragraph.push(lines[i]);
      i += 1;
    }
    pushParagraph(paragraph);
  }

  return parts.join('') || '<p></p>';
}

function renderTextSectionHtml(text, options=null){
  const render = () => renderMarkdownBlocksHtml(String(text ?? '').replace(/\r?\n/g, '\n').split('\n'));
  if(options && typeof options === 'object' && options.inlineSourcePills === false){
    return withAssistantInlineSourcePillsEnabled(false, render);
  }
  return render();
}
function isLikelyShellCommandLine(line){
  const raw = String(line || "");
  const l = raw.trim();
  if(!l) return false;
  if(/^\$\s+/.test(l) || /^\.\//.test(l)) return true;
  if(/[\u4e00-\u9fff]/.test(l)) return false;
  return /^(docker|docker-compose|compose|kubectl|helm|git|npm|pnpm|yarn|bun|pip|pip3|python|python3|node|npx|curl|wget|bash|sh|cd|ls|pwd|mkdir|rm|cp|mv|cat|echo|chmod|chown|sudo|apt|apt-get|yum|dnf|apk|brew|systemctl|service)\b/.test(l);
}

function isYamlStarter(line, nextLine){
  const cur = String(line || '');
  const next = String(nextLine || '');
  if(!cur.trim()) return false;
  if(/^\s*(version|services|image|ports|environment|volumes|command)\s*:/i.test(cur)) return true;
  if(/^\s*[A-Za-z0-9_-]+\s*:\s*$/.test(cur) && /^\s{2,}([A-Za-z0-9_-]+\s*:|-\s+)/.test(next)) return true;
  return false;
}

function isYamlContinuation(line){
  const cur = String(line || '');
  if(!cur.trim()) return false;
  if(/^\s*#/.test(cur)) return true;
  if(/^\s{2,}[A-Za-z0-9_-]+\s*:/.test(cur)) return true;
  if(/^\s{2,}-\s+/.test(cur)) return true;
  if(/^\s{0,2}[A-Za-z0-9_-]+\s*:\s*.*$/.test(cur)) return true;
  return false;
}

function isHtmlStarter(line, nextLine){
  const cur = String(line || '').trim();
  const next = String(nextLine || '').trim();
  if(!cur) return false;
  if(/^<!doctype\s+html\b/i.test(cur)) return true;
  if(/^<(html|head|body)\b/i.test(cur)) return true;
  if(/^<(meta|link|title|style|script)\b/i.test(cur)) return true;
  if(/^<[a-z][\w:-]*(\s[^>]*)?>$/i.test(cur) && /^<\/?[a-z][\w:-]*/i.test(next)) return true;
  return false;
}

function normalizeCodeFenceLang(rawLang){
  let lang = String(rawLang || '').trim().toLowerCase();
  if(lang.startsWith('language-')) lang = lang.slice(9).trim();
  const aliasMap = {
    js:'javascript', mjs:'javascript', cjs:'javascript', jsx:'javascript',
    ts:'typescript', tsx:'typescript',
    py:'python', python3:'python',
    sh:'bash', shell:'bash', zsh:'bash', console:'bash', terminal:'bash',
    yml:'yaml',
    htm:'html',
    md:'markdown', mdown:'markdown', mkdn:'markdown', mdx:'markdown',
    mmd:'mermaid',
    'c++':'cpp',
    psql:'sql', postgres:'sql', mysql:'sql', sqlite:'sql',
  };
  return aliasMap[lang] || lang;
}

function getCodeLangDisplayName(rawLang){
  const lang = normalizeCodeFenceLang(rawLang) || 'code';
  const labelMap = {
    javascript:'JavaScript', typescript:'TypeScript', python:'Python', bash:'Shell',
    yaml:'YAML', json:'JSON', html:'HTML', css:'CSS', sql:'SQL', mermaid:'Mermaid', markdown:'Markdown',
    cpp:'C++', c:'C', go:'Go', rust:'Rust', java:'Java', php:'PHP', xml:'XML', svg:'SVG', code:'code'
  };
  return labelMap[lang] || (lang ? lang.toUpperCase() : 'code');
}

function getCodeLangClassName(rawLang){
  return normalizeCodeFenceLang(rawLang) || 'code';
}

function isMermaidCodeLang(rawLang){
  return normalizeCodeFenceLang(rawLang) === 'mermaid';
}

function isJsonStarter(line, nextLine){
  const cur = String(line || '').trim();
  const next = String(nextLine || '').trim();
  if(!cur) return false;
  if(cur === '{' || cur === '[') return true;
  if((cur.startsWith('{') || cur.startsWith('[')) && /[}\]]\s*[,;]?$/.test(cur)) return true;
  if((cur.startsWith('{') || cur.startsWith('[')) && (/^&quot;[^\n]+&quot;\s*:/.test(next) || /^"[^\n]+"\s*:/.test(next) || /^[\[{]/.test(next) || /^[}\]]/.test(next))) return true;
  return false;
}

function isJsonContinuation(line){
  const cur = String(line || '').trim();
  if(!cur) return false;
  if(/^[\[\]{}]/.test(cur) || /[\[\]{}],?$/.test(cur)) return true;
  if(/^"[^\n]+"\s*:/.test(cur) || /^&quot;[^\n]+&quot;\s*:/.test(cur)) return true;
  if(/^(true|false|null|-?\d+(?:\.\d+)?)(\s*,)?$/i.test(cur)) return true;
  return false;
}

function isPythonStarter(line, nextLine){
  const cur = String(line || '').trim();
  const next = String(nextLine || '');
  if(!cur) return false;
  if(/^(@[A-Za-z_][\w.]*)$/.test(cur)) return true;
  if(/^(from\s+\S+\s+import\s+.+|import\s+\S.+)$/.test(cur)) return true;
  if(/^(def|class)\s+[A-Za-z_][\w]*\s*[(:]/.test(cur)) return true;
  if(/^(if\s+__name__\s*==\s*["']__main__["']\s*:|if\s+.+:|elif\s+.+:|else:|for\s+.+\s+in\s+.+:|while\s+.+:|with\s+.+:|try:|except\b.*:|finally:)$/.test(cur)) return true;
  if(/:\s*$/.test(cur) && /^\s{2,}\S/.test(next)) return true;
  return false;
}

function isPythonContinuation(line){
  const raw = String(line || '');
  const cur = raw.trim();
  if(!cur) return false;
  if(/^\s{2,}\S/.test(raw)) return true;
  if(/^(@[A-Za-z_][\w.]*)$/.test(cur)) return true;
  if(/^(return|raise|yield|pass|break|continue|global|nonlocal|assert|from\s+\S+\s+import\s+.+|import\s+\S.+)\b/.test(cur)) return true;
  if(/^(if|elif|else|for|while|with|try|except|finally|def|class)\b.*:\s*$/.test(cur)) return true;
  if(/^[A-Za-z_][\w]*\s*=\s*.+/.test(cur)) return true;
  return false;
}

function isJavascriptStarter(line, nextLine){
  const cur = String(line || '').trim();
  const next = String(nextLine || '').trim();
  if(!cur) return false;
  if(/^(import\s+.+\s+from\s+.+|export\s+(default\s+)?|const\s+|let\s+|var\s+|function\s+|async\s+function\s+|class\s+|interface\s+|type\s+|enum\s+)/.test(cur)) return true;
  if(/=>\s*[{(]?/.test(cur)) return true;
  if(/[{};]$/.test(cur) && /^(const|let|var|if|for|while|switch|try|catch|class|function|async|return|document\.|window\.|fetch\()/.test(cur)) return true;
  if(/^[A-Za-z_$][\w$]*\s*=\s*[{\[]/.test(cur) && /^\s+/.test(next)) return true;
  return false;
}

function isJavascriptContinuation(line){
  const raw = String(line || '');
  const cur = raw.trim();
  if(!cur) return false;
  if(/^[{}()[\];,]+$/.test(cur)) return true;
  if(/^\s{2,}\S/.test(raw)) return true;
  if(/^(const|let|var|return|if|else|for|while|switch|case|break|continue|function|async|await|class|try|catch|finally|throw|import|export)\b/.test(cur)) return true;
  if(/[;{}]$/.test(cur)) return true;
  if(/=>/.test(cur)) return true;
  return false;
}

function isSqlStarter(line){
  const cur = String(line || '').trim();
  if(!cur) return false;
  return /^(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|WITH\s+)/i.test(cur);
}

function isSqlContinuation(line){
  const cur = String(line || '').trim();
  if(!cur) return false;
  return /^(SELECT|FROM|WHERE|ORDER\s+BY|GROUP\s+BY|HAVING|LIMIT|OFFSET|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|ALTER|DROP|TABLE|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|JOIN|ON|AND|OR|UNION|WITH|CASE|WHEN|THEN|END|,|\(|\))/i.test(cur) || /;\s*$/.test(cur);
}

function inferCodeFenceLangFromBlock(lines){
  const joined = (Array.isArray(lines) ? lines : []).join('\n').trim();
  if(!joined) return '';
  if(/^<!doctype\s+html\b/i.test(joined) || /^<html[\s>]/i.test(joined)) return 'html';
  if(/^<svg[\s>]/i.test(joined)) return 'svg';
  if(/^(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|WITH\s+)/i.test(joined)) return 'sql';
  if(/^(from\s+\S+\s+import\s+.+|import\s+\S.+|def\s+\w+\s*\(|class\s+\w+\s*[:(]|if\s+__name__\s*==\s*["']__main__["'])/m.test(joined)) return 'python';
  if(/^(import\s+.+\s+from\s+.+|export\s+(default\s+)?|const\s+|let\s+|var\s+|function\s+|async\s+function\s+|class\s+)/m.test(joined) || /=>/.test(joined)) return 'javascript';
  if(/^[\[{]/.test(joined) && /(?:^|\n)\s*(?:"[^\n]+"\s*:|[}\]])/m.test(joined)) return 'json';
  if(/^(version|services|image|ports|environment|volumes|command)\s*:/im.test(joined)) return 'yaml';
  if(/^(docker|docker-compose|compose|kubectl|helm|git|npm|pnpm|yarn|bun|pip|pip3|python|python3|node|npx|curl|wget|bash|sh|cd|ls|pwd|mkdir|rm|cp|mv|cat|echo|chmod|chown|sudo|apt|apt-get|yum|dnf|apk|brew|systemctl|service)\b/im.test(joined)) return 'bash';
  return '';
}

function shouldCollapseCodeBlock(codeRaw, rawLang){
  const lang = normalizeCodeFenceLang(rawLang);
  const text = normalizeRunnableCodeSource(codeRaw).replace(/\n$/, '');
  const lineCount = Math.max(1, text.split('\n').length);
  if(lineCount >= 36 || text.length >= 3200) return true;
  if(['html','svg','xml','json','yaml'].includes(lang)) return lineCount >= 16 || text.length >= 1800;
  if(['javascript','typescript','python','sql','bash'].includes(lang)) return lineCount >= 22 || text.length >= 2400;
  return lineCount > 18 || text.length > 2200;
}

function autoWrapLikelyCodeFences(text){
  const src = String(text ?? '').replace(/\r\n/g, '\n');
  if(!src.trim()) return src;

  const lines = src.split('\n');
  const out = [];
  let i = 0;

  while(i < lines.length){
    const line = lines[i];

    if(/^```/.test(String(line || '').trim())){
      out.push(line);
      i += 1;
      while(i < lines.length){
        out.push(lines[i]);
        if(/^```/.test(String(lines[i] || '').trim())){
          i += 1;
          break;
        }
        i += 1;
      }
      continue;
    }

    if(isHtmlStarter(line, lines[i + 1])){
      const block = [line];
      let sawClose = /<\/html\s*>/i.test(String(line || ''));
      i += 1;
      while(i < lines.length){
        block.push(lines[i]);
        if(/<\/html\s*>/i.test(String(lines[i] || ''))){
          sawClose = true;
          i += 1;
          break;
        }
        i += 1;
      }
      if(block.length >= 3 || sawClose){
        out.push('```html');
        out.push(...block);
        out.push('```');
      }else{
        out.push(...block);
      }
      continue;
    }

    if(isLikelyShellCommandLine(line)){
      const block = [line];
      i += 1;
      while(i < lines.length && isLikelyShellCommandLine(lines[i])){
        block.push(lines[i]);
        i += 1;
      }
      out.push('```bash');
      out.push(...block);
      out.push('```');
      continue;
    }

    if(isYamlStarter(line, lines[i + 1])){
      const block = [line];
      i += 1;
      while(i < lines.length && isYamlContinuation(lines[i])){
        block.push(lines[i]);
        i += 1;
      }
      const yamlLikeCount = block.filter(l => /^\s*[A-Za-z0-9_-]+\s*:/.test(String(l || '')) || /^\s{2,}-\s+/.test(String(l || ''))).length;
      if(block.length >= 4 && yamlLikeCount >= 4){
        out.push('```yaml');
        out.push(...block);
        out.push('```');
      }else{
        out.push(...block);
      }
      continue;
    }

    if(isJsonStarter(line, lines[i + 1])){
      const block = [line];
      i += 1;
      while(i < lines.length && isJsonContinuation(lines[i])){
        block.push(lines[i]);
        i += 1;
      }
      if(block.length >= 3){
        out.push('```json');
        out.push(...block);
        out.push('```');
      }else{
        out.push(...block);
      }
      continue;
    }

    if(isPythonStarter(line, lines[i + 1])){
      const block = [line];
      i += 1;
      while(i < lines.length && isPythonContinuation(lines[i])){
        block.push(lines[i]);
        i += 1;
      }
      if(block.length >= 2){
        out.push('```python');
        out.push(...block);
        out.push('```');
      }else{
        out.push(...block);
      }
      continue;
    }

    if(isJavascriptStarter(line, lines[i + 1])){
      const block = [line];
      i += 1;
      while(i < lines.length && isJavascriptContinuation(lines[i])){
        block.push(lines[i]);
        i += 1;
      }
      if(block.length >= 2){
        out.push('```javascript');
        out.push(...block);
        out.push('```');
      }else{
        out.push(...block);
      }
      continue;
    }

    if(isSqlStarter(line)){
      const block = [line];
      i += 1;
      while(i < lines.length && isSqlContinuation(lines[i])){
        block.push(lines[i]);
        i += 1;
      }
      if(block.length >= 2){
        out.push('```sql');
        out.push(...block);
        out.push('```');
      }else{
        out.push(...block);
      }
      continue;
    }

    out.push(line);
    i += 1;
  }

  return out.join('\n');
}

function normalizeRichTextSource(text, opts={}){
  const normalized = String(text ?? '').replace(/\r\n/g, '\n');
  const allowImplicitCodeFences = !!(opts && opts.allowImplicitCodeFences === true);
  return allowImplicitCodeFences ? autoWrapLikelyCodeFences(normalized) : normalized;
}

function normalizeAssistantMarkdownBlockBoundaries(text){
  let src = String(text ?? '').replace(/\r\n/g, '\n');
  if(!src) return src;

  // Streaming/final answers sometimes arrive with block Markdown markers squeezed
  // into the previous sentence, e.g. “说明。 ## 标题” or “结论。 --- ## 下一节”.
  // Keep this as a rendering-only normalization, and apply it only to non-code
  // text blocks so code fences and commands are not rewritten.
  const sentenceEnd = '([。！？!?；;：:）\\)\\]】》」』])';
  for(let i = 0; i < 2; i += 1){
    src = src.replace(new RegExp(sentenceEnd + '[ \\t]*(#{1,4}[ \\t]+(?=\\S))', 'g'), '$1\n\n$2');
    src = src.replace(new RegExp(sentenceEnd + '[ \\t]*(-{3,}|\\*{3,}|_{3,})(?=[ \\t]+|$)', 'g'), '$1\n\n$2');
    src = src.replace(new RegExp(sentenceEnd + '[ \\t]*((?:\\d{1,3}[.)]|[-*+])\\s+(?=\\S))', 'g'), '$1\n\n$2');
    src = src.replace(/(^|\n)([ \t]*[-*_]{3,})[ \t]+(#{1,4}[ \t]+(?=\S))/g, '$1$2\n\n$3');
    src = src.replace(/(^|\n)([ \t]*[-*_]{3,})[ \t]+([-*_]{3,})(?=[ \t]+|$)/g, '$1$2\n\n$3');
  }
  return src;
}

function renderRichTextHtml(text, opts={}){
  const isStreamingDraft = !!(opts && opts.streamingDraft);
  const normalized = normalizeRichTextSource(text, opts);
  return splitRichTextBlocks(normalized).map((block, idx)=>{
    if(block.type === "code"){
      return renderCodeBlockHtml(block.code || "", block.lang || '', idx, isStreamingDraft);
    }
    return renderTextSectionHtml(normalizeAssistantMarkdownBlockBoundaries(block.text));
  }).join("");
}

function renderCodeBlockHtml(code, rawLangInput='', copyId='code', isStreamingDraft=false){
  const codeRaw = normalizeRunnableCodeSource(code || "");
  const rawLang = normalizeCodeFenceLang(rawLangInput || '') || inferCodeFenceLangFromBlock(codeRaw.split('\n'));
  const langText = escapeHtml(getCodeLangDisplayName(rawLang || 'code'));
  const langClass = escapeHtml(getCodeLangClassName(rawLang || 'code'));
  const codeHtml = highlightCode(codeRaw, rawLang);
  const lineCount = Math.max(1, codeRaw.replace(/\n$/, "").split("\n").length);
  const rawCodeAttr = escapeHtml(encodeURIComponent(codeRaw));
  const rawLangAttr = escapeHtml(rawLang);
  const copyAttr = escapeHtml(String(copyId ?? 'code'));
  if(!isStreamingDraft && isMermaidCodeLang(rawLang)){
    return `<div class="code-block mermaid-block" data-code-lines="${lineCount}" data-code-raw-lang="${rawLangAttr}" data-mermaid-source="${rawCodeAttr}"><div class="code-toolbar"><div class="code-toolbar-left"><span class="code-lang">${langText}</span><span class="code-lines">${escapeHtml(markdownUiT('code.lines',{count:lineCount},`${lineCount} lines`))}</span></div><div class="code-toolbar-right"><button class="icon-btn code-mermaid-zoom" type="button" data-mermaid-zoom="1">${escapeHtml(markdownUiT('code.zoom',null,'Zoom'))}</button><button class="icon-btn code-mermaid-toggle" type="button" data-mermaid-toggle="1">${escapeHtml(markdownUiT('code.show_code',null,'Show code'))}</button><button class="icon-btn code-copy" type="button" data-copy-code="${copyAttr}">${escapeHtml(markdownUiT('code.copy',null,'Copy code'))}</button></div></div><div class="mermaid-render" data-mermaid-render-target="1">${escapeHtml(markdownUiT('code.rendering_diagram',null,'Rendering diagram…'))}</div><pre class="mermaid-source"><code class="language-${langClass}" data-raw-code="${rawCodeAttr}">${codeHtml}</code></pre></div>`;
  }
  const needCollapse = !isStreamingDraft && shouldCollapseCodeBlock(codeRaw, rawLang);
  const runMeta = getRunnableCodeMeta(rawLang, codeRaw);
  const runAttrs = runMeta ? ` data-run-enabled="1" data-run-mode="${escapeHtml(runMeta.mode)}" data-run-lang="${escapeHtml(runMeta.lang)}" data-run-label="${escapeHtml(runMeta.label)}"` : ``;
  const runBtnHtml=runMeta?`<button class="icon-btn code-run" type="button" data-code-run="1">${escapeHtml(markdownUiT(runMeta.mode==='preview'?'code.preview':'code.run',null,runMeta.mode==='preview'?'Preview':'Run'))}</button>`:``;
  const collapseBtnHtml=needCollapse?`<button class="icon-btn code-collapse" type="button" data-code-collapse="1" aria-expanded="true">${escapeHtml(markdownUiT('code.collapse',null,'Collapse'))}</button>`:``;
  const collapseFadeHtml = needCollapse ? `<div class="code-fade"></div>` : ``;
  return `<div class="code-block ${needCollapse ? 'collapsible' : ''}" data-code-lines="${lineCount}" data-code-raw-lang="${rawLangAttr}"${runAttrs}><div class="code-toolbar"><div class="code-toolbar-left"><span class="code-lang">${langText}</span><span class="code-lines">${escapeHtml(markdownUiT('code.lines',{count:lineCount},`${lineCount} lines`))}</span></div><div class="code-toolbar-right">${collapseBtnHtml}${runBtnHtml}<button class="icon-btn code-copy" type="button" data-copy-code="${copyAttr}">${escapeHtml(markdownUiT('code.copy',null,'Copy code'))}</button></div></div><pre><code class="language-${langClass}" data-raw-code="${rawCodeAttr}">${codeHtml}</code>${collapseFadeHtml}</pre></div>`;
}

function copyText(text){
  const value = String(text ?? "");
  if(!value) return;
  if(navigator.clipboard?.writeText){
    navigator.clipboard.writeText(value).then(()=>{try{setStatus(markdownUiT('code.copied',null,'Copied'));}catch(_){}}).catch(()=>{});
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = value;
  document.body.appendChild(ta);
  ta.select();
  try{ document.execCommand("copy"); }catch(_){}
  ta.remove();
  try{setStatus(markdownUiT('code.copied',null,'Copied'));}catch(_){}
}


const CODE_RUN_PREVIEW_LANGS = new Set(['html', 'htm', 'xhtml', 'css', 'svg']);
const CODE_RUN_SERVER_LANG_MAP = {
  py: 'python', python: 'python', python3: 'python',
  js: 'javascript', javascript: 'javascript', node: 'javascript', nodejs: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', typescript: 'typescript',
  bash: 'bash', shell: 'bash', sh: 'bash', zsh: 'bash',
  pwsh: 'powershell', powershell: 'powershell', ps1: 'powershell',
  c: 'c', cc: 'cpp', cpp: 'cpp', cxx: 'cpp', 'c++': 'cpp',
  go: 'go', golang: 'go', rs: 'rust', rust: 'rust', java: 'java',
  php: 'php', rb: 'ruby', ruby: 'ruby', pl: 'perl', perl: 'perl',
  lua: 'lua', r: 'r', swift: 'swift', dart: 'dart'
};
const CODE_RUN_LANG_LABELS = {
  html: 'HTML', css: 'CSS', svg: 'SVG', javascript: 'JavaScript', typescript: 'TypeScript',
  python: 'Python', bash: 'Shell', powershell: 'PowerShell', c: 'C', cpp: 'C++', go: 'Go',
  rust: 'Rust', java: 'Java', php: 'PHP', ruby: 'Ruby', perl: 'Perl', lua: 'Lua', r: 'R', swift: 'Swift', dart: 'Dart'
};
const codeRunnerStates = new Map();
const codeRunRuntimeMatrix = { loaded:false, loading:null, languages:{} };
const codeRunMainEl = document.getElementById('main');
const codeRunDockEl = document.getElementById('codeRunDock');
const codeRunDockBodyEl = document.getElementById('codeRunDockBody');
const codeRunDockTitleEl = document.getElementById('codeRunDockTitle');
const codeRunDockKindEl = document.getElementById('codeRunDockKind');
const codeRunDockCloseEl = document.getElementById('codeRunDockClose');
let codeRunnerSeq = 0;
let codeRunnerEventsBound = false;
let activeCodeRunnerState = null;

codeRunDockCloseEl?.addEventListener('click', ()=>{
  if(activeCodeRunnerState) destroyCodeRunner(activeCodeRunnerState);
  else hideCodeRunDock();
});

function isCodeRunServerLangAvailable(lang){
  const normalized = CODE_RUN_SERVER_LANG_MAP[normalizeCodeRunLang(lang)] || normalizeCodeRunLang(lang);
  if(!normalized) return null;
  if(!codeRunRuntimeMatrix.loaded) return null;
  return !!codeRunRuntimeMatrix.languages?.[normalized]?.available;
}

function syncCodeRunBlockAvailability(block){
  if(!block?.querySelector) return;
  const rawLang = String(block.dataset?.codeRawLang || '').trim();
  const code = getCodeBlockRawSource(block);
  const meta = getRunnableCodeMeta(rawLang, code);
  const toolbar = block.querySelector('.code-toolbar-right');
  const existingBtn = block.querySelector('[data-code-run]');

  if(meta){
    block.dataset.runEnabled = '1';
    block.dataset.runMode = meta.mode;
    block.dataset.runLang = meta.lang;
    block.dataset.runLabel = meta.label || meta.lang || '';
  }else{
    delete block.dataset.runEnabled;
    delete block.dataset.runMode;
    delete block.dataset.runLang;
    delete block.dataset.runLabel;
  }

  if(!toolbar) return;

  if(!meta){
    if(existingBtn) existingBtn.remove();
    if(block._codeRunnerState) destroyCodeRunner(block._codeRunnerState);
    return;
  }

  const nextText=markdownUiT(meta.mode==='preview'?'code.preview':'code.run',null,meta.mode==='preview'?'Preview':'Run');
  if(existingBtn){
    existingBtn.textContent = nextText;
    return;
  }

  const copyBtn = toolbar.querySelector('[data-copy-code]');
  const btn = document.createElement('button');
  btn.className = 'icon-btn code-run';
  btn.type = 'button';
  btn.dataset.codeRun = '1';
  btn.textContent = nextText;
  if(copyBtn) toolbar.insertBefore(btn, copyBtn);
  else toolbar.appendChild(btn);
}

function syncCodeRunAvailability(root=document){
  const scope = root && typeof root.querySelectorAll === 'function' ? root : document;
  scope.querySelectorAll('.code-block').forEach(syncCodeRunBlockAvailability);
}

async function ensureCodeRunRuntimeMatrix(force=false){
  if(codeRunRuntimeMatrix.loaded && !force) return codeRunRuntimeMatrix.languages;
  if(codeRunRuntimeMatrix.loading && !force) return codeRunRuntimeMatrix.loading;
  codeRunRuntimeMatrix.loading = fetch('/api3/code/runtimes', { cache:'no-store' })
    .then(async (resp)=>{
      const data = await resp.json().catch(()=>({ ok:false, languages:{} }));
      if(!resp.ok || !data?.ok || typeof data?.languages !== 'object'){
        throw new Error(String(data?.error || `runtime_probe_failed:${resp.status}`));
      }
      codeRunRuntimeMatrix.languages = data.languages || {};
      codeRunRuntimeMatrix.loaded = true;
      syncCodeRunAvailability(document);
      return codeRunRuntimeMatrix.languages;
    })
    .catch((err)=>{
      console.warn('[code-run] runtime probe failed', err);
      return codeRunRuntimeMatrix.languages;
    })
    .finally(()=>{
      codeRunRuntimeMatrix.loading = null;
    });
  return codeRunRuntimeMatrix.loading;
}

void ensureCodeRunRuntimeMatrix();

function getCodeRunDockKindText(meta, statusText=''){
  const label = String(meta?.label || meta?.lang || '').trim();
  const status = String(statusText || '').trim();
  if(label && status) return `${label} · ${status}`;
  return label || status;
}

function setCodeRunDockHeader(meta, statusText=''){
  if(codeRunDockTitleEl) codeRunDockTitleEl.textContent = meta?.mode === 'preview'
    ? markdownUiT('code.runner.preview_title', null, 'Code preview')
    : markdownUiT('code.runner.title', null, 'Code runner');
  if(codeRunDockKindEl) codeRunDockKindEl.textContent = getCodeRunDockKindText(meta, statusText);
}

function syncCodeRunDockHeaderForState(state, statusText=''){
  if(!state || activeCodeRunnerState !== state) return;
  setCodeRunDockHeader(state.meta, statusText);
}

function applyCodeRunDockReservePx(px){
  const value = `${Math.max(0, Math.ceil(Number(px) || 0))}px`;
  try{ document.body?.style?.setProperty('--active-code-run-dock-reserve', value); }catch(_){ }
}

function syncCodeRunDockReserve(visible){
  const active = typeof visible === 'boolean' ? visible : !!(codeRunDockEl && !codeRunDockEl.hidden);
  if(!active || !codeRunDockEl){
    applyCodeRunDockReservePx(0);
    return;
  }
  const measure = ()=>{
    try{
      const rect = codeRunDockEl.getBoundingClientRect();
      const reserve = rect && rect.width > 0 ? Math.max(rect.width, window.innerWidth - rect.left) : 0;
      applyCodeRunDockReservePx(reserve);
    }catch(_){
      applyCodeRunDockReservePx(0);
    }
  };
  measure();
  try{ window.requestAnimationFrame(measure); }catch(_){ }
}

function setCodeRunDockVisible(visible){
  if(!codeRunDockEl) return;
  codeRunDockEl.hidden = !visible;
  codeRunDockEl.setAttribute('aria-hidden', visible ? 'false' : 'true');
  document.body.classList.toggle('has-code-run-dock', !!visible);
  if(codeRunMainEl) codeRunMainEl.classList.toggle('has-code-run-dock', !!visible);
  syncCodeRunDockReserve(!!visible);
}

try{
  window.addEventListener('resize', ()=>syncCodeRunDockReserve(), { passive:true });
}catch(_){ }

function resetCodeRunDockEmpty(){
  if(!codeRunDockBodyEl) return;
  codeRunDockBodyEl.innerHTML = `<div class="code-run-dock-empty">${escapeHtml(markdownUiT('code.runner.empty', null, 'Run or preview code to see the result here.'))}</div>`;
}

function showCodeRunDockForState(state){
  if(!state) return;
  if(activeCodeRunnerState && activeCodeRunnerState !== state){
    try{ if(activeCodeRunnerState.previewId) codeRunnerStates.delete(String(activeCodeRunnerState.previewId)); }catch(_){ }
    try{ if(activeCodeRunnerState.frame) activeCodeRunnerState.frame.srcdoc = '<!doctype html><html><body></body></html>'; }catch(_){ }
    try{ activeCodeRunnerState.panel?.remove(); }catch(_){ }
    try{ if(activeCodeRunnerState.block?._codeRunnerState === activeCodeRunnerState) activeCodeRunnerState.block._codeRunnerState = null; }catch(_){ }
    activeCodeRunnerState.previewId = '';
    activeCodeRunnerState.isRunning = false;
    updateCodeRunnerToolbarState(activeCodeRunnerState, 'idle');
  }
  activeCodeRunnerState = state;
  if(codeRunDockBodyEl && state.panel){
    const onlyChildIsPanel = codeRunDockBodyEl.childElementCount === 1 && codeRunDockBodyEl.firstElementChild === state.panel;
    if(!onlyChildIsPanel){
      codeRunDockBodyEl.innerHTML = '';
      codeRunDockBodyEl.appendChild(state.panel);
    }
  }
  setCodeRunDockHeader(state.meta, state?.metaEl?.textContent || '');
  setCodeRunDockVisible(true);
}

function hideCodeRunDock(){
  activeCodeRunnerState = null;
  setCodeRunDockHeader(null);
  resetCodeRunDockEmpty();
  setCodeRunDockVisible(false);
}

function normalizeCodeRunLang(rawLang){
  let lang = String(rawLang || '').trim().toLowerCase();
  if(lang.startsWith('language-')) lang = lang.slice(9).trim();
  return lang;
}

function looksLikeBrowserJavascript(code){
  const src = String(code || '');
  if(!src) return false;
  return /(document\.|window\.|localStorage|sessionStorage|requestAnimationFrame\(|cancelAnimationFrame\(|canvas|getContext\(|addEventListener\(|querySelector\()/i.test(src);
}

function detectImplicitRunnableCode(code){
  const src = String(code || '').trim();
  if(!src) return null;
  if(/^<!doctype html/i.test(src) || /^<html[\s>]/i.test(src)) return { mode:'preview', lang:'html', label:'HTML' };
  if(/^<svg[\s>]/i.test(src)) return { mode:'preview', lang:'svg', label:'SVG' };
  return null;
}

function getCodeBlockRawSource(block){
  const codeEl = block?.querySelector?.('code');
  const attr = String(codeEl?.dataset?.rawCode || '').trim();
  if(attr){
    try{
      return normalizeRunnableCodeSource(decodeURIComponent(attr));
    }catch(_){ }
  }
  const text = codeEl?.textContent || codeEl?.innerText || '';
  return normalizeRunnableCodeSource(text);
}

function getRunnableCodeMeta(rawLang, code){
  const lang = normalizeCodeRunLang(rawLang);
  if(CODE_RUN_PREVIEW_LANGS.has(lang)) return { mode:'preview', lang, label: CODE_RUN_LANG_LABELS[lang] || lang.toUpperCase() };
  if(lang === 'javascript' || lang === 'js' || lang === 'mjs' || lang === 'cjs'){
    if(looksLikeBrowserJavascript(code)) return { mode:'preview', lang:'javascript', label:'JavaScript' };
    if(codeRunRuntimeMatrix.loaded && !isCodeRunServerLangAvailable('javascript')) return null;
    return { mode:'server', lang:'javascript', label:'JavaScript' };
  }
  const mapped = CODE_RUN_SERVER_LANG_MAP[lang];
  if(mapped){
    if(codeRunRuntimeMatrix.loaded && !isCodeRunServerLangAvailable(mapped)) return null;
    return { mode:'server', lang:mapped, label: CODE_RUN_LANG_LABELS[mapped] || mapped };
  }
  return detectImplicitRunnableCode(code);
}

function ensureCodeRunnerGlobalEvents(){
  if(codeRunnerEventsBound) return;
  codeRunnerEventsBound = true;
  window.addEventListener('message', (event)=>{
    const data = event?.data;
    if(!data || data.__codeRunner !== true) return;
    const previewId = String(data.previewId || '');
    const state = codeRunnerStates.get(previewId);
    if(!state) return;
    if(data.type === 'ready'){
      state.isRunning = false;
      updateCodeRunnerToolbarState(state, 'idle');
      syncCodeRunDockHeaderForState(state, '');
      return;
    }
    if(data.type === 'console'){
      const payload = data.payload && typeof data.payload === 'object' ? data.payload : {};
      const level = String(payload.level || 'log').toUpperCase();
      const text = String(payload.text || '').trim();
      if(!text) return;
      state.body.hidden = false;
      state.body.classList.remove('is-error');
      state.output.innerHTML += `<div class="code-run-section"><div class="code-run-section-label">${escapeHtml(level)}</div><pre>${escapeHtml(text)}</pre></div>`;
      return;
    }
  });
}

function updateCodeRunnerToolbarState(state, mode){
  if(!state?.runBtn) return;
  const kind = state?.meta?.mode === 'preview'
    ? markdownUiT('code.runner.preview', null, 'Preview')
    : markdownUiT('code.runner.run', null, 'Run');
  if(mode === 'running'){
    state.runBtn.textContent = state?.meta?.mode === 'preview'
      ? markdownUiT('code.runner.previewing', null, 'Previewing…')
      : markdownUiT('code.runner.running', null, 'Running…');
    state.runBtn.disabled = true;
    state.runBtn.classList.add('is-running');
    return;
  }
  state.runBtn.disabled = false;
  state.runBtn.classList.remove('is-running');
  state.runBtn.textContent = kind;
}

function createCodeRunnerPanel(block, runBtn, meta){
  const panel = document.createElement('div');
  panel.className = 'code-run-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="code-run-panel-head">
      <div class="code-run-panel-title">
        <strong>${escapeHtml(meta.mode === 'preview' ? markdownUiT('code.runner.live_preview', null, 'Live preview') : markdownUiT('code.runner.result', null, 'Run result'))}</strong>
        <span class="code-run-panel-kind">${escapeHtml(meta.label || meta.lang || '')}</span>
        <span class="code-run-panel-meta"></span>
      </div>
      <button class="icon-btn code-run-panel-close" type="button">${escapeHtml(markdownUiT('code.runner.close', null, 'Close'))}</button>
    </div>
    <div class="code-run-panel-main">
      <iframe class="code-run-panel-frame" hidden sandbox="allow-scripts"></iframe>
      <pre class="code-run-panel-source" hidden></pre>
    </div>
    <div class="code-run-panel-body" hidden></div>
  `;
  if(codeRunDockBodyEl) codeRunDockBodyEl.appendChild(panel);
  else block.appendChild(panel);
  const state = {
    block,
    panel,
    runBtn,
    meta,
    main: panel.querySelector('.code-run-panel-main'),
    frame: panel.querySelector('.code-run-panel-frame'),
    body: panel.querySelector('.code-run-panel-body'),
    output: panel.querySelector('.code-run-panel-body'),
    source: panel.querySelector('.code-run-panel-source'),
    metaEl: panel.querySelector('.code-run-panel-meta'),
    previewId: '',
    isRunning: false,
    sourceCode: '',
  };
  panel.querySelector('.code-run-panel-close')?.addEventListener('click', (e)=>{
    e.stopPropagation();
    destroyCodeRunner(state);
  });
  return state;
}

function destroyCodeRunner(state){
  if(!state) return;
  try{ if(state.previewId) codeRunnerStates.delete(String(state.previewId)); }catch(_){ }
  try{ if(state.frame) state.frame.srcdoc = '<!doctype html><html><body></body></html>'; }catch(_){ }
  try{ state.panel?.remove(); }catch(_){ }
  state.previewId = '';
  state.isRunning = false;
  updateCodeRunnerToolbarState(state, 'idle');
  try{ if(state.block?._codeRunnerState === state) state.block._codeRunnerState = null; }catch(_){ }
  if(activeCodeRunnerState === state){
    hideCodeRunDock();
  }
}

function refreshCodeRunnerLanguage(state){
  if(!state) return;
  const panelTitle = state.panel?.querySelector?.('.code-run-panel-title strong');
  if(panelTitle) panelTitle.textContent = state?.meta?.mode === 'preview'
    ? markdownUiT('code.runner.live_preview', null, 'Live preview')
    : markdownUiT('code.runner.result', null, 'Run result');
  const close = state.panel?.querySelector?.('.code-run-panel-close');
  if(close) close.textContent = markdownUiT('code.runner.close', null, 'Close');
  updateCodeRunnerToolbarState(state, state.isRunning ? 'running' : 'idle');
  if(state.outputSnapshot){
    const snapshot = state.outputSnapshot;
    setCodeRunnerOutput(state, snapshot.sections, snapshot.metaText, snapshot.isError);
  }else if(state?.meta?.mode === 'preview' && state.previewId && state.frame && !state.frame.hidden){
    try{ state.frame.srcdoc = buildPreviewDocument(state.meta, state.sourceCode, state.previewId); }catch(_){ }
  }
  if(activeCodeRunnerState === state){
    setCodeRunDockHeader(state.meta, state?.metaEl?.textContent || '');
  }
}

document.addEventListener('apervia:languagechange', ()=>{
  try{
    const seen = new Set();
    for(const state of codeRunnerStates.values()){
      if(!state || seen.has(state)) continue;
      seen.add(state);
      refreshCodeRunnerLanguage(state);
    }
    if(activeCodeRunnerState && !seen.has(activeCodeRunnerState)) refreshCodeRunnerLanguage(activeCodeRunnerState);
    if(!activeCodeRunnerState) resetCodeRunDockEmpty();
  }catch(_){ }
});

function buildPreviewRunnerBridge(previewId){
  const safeId = JSON.stringify(String(previewId || ''));
  return `
<script>
(function(){
  const previewId = ${safeId};
  const send = (type, payload)=>{
    try{ parent.postMessage({ __codeRunner:true, previewId, type, payload }, '*'); }catch(_){ }
  };
  const fmt = (value)=>{
    if(typeof value === 'string') return value;
    try{ return JSON.stringify(value, null, 2); }catch(_){ return String(value); }
  };
  ['log','info','warn','error'].forEach((level)=>{
    const orig = console[level];
    console[level] = function(){
      const text = Array.from(arguments || []).map(fmt).join(' ');
      send('console', { level, text });
      try{ if(orig) orig.apply(console, arguments); }catch(_){ }
    };
  });
  window.addEventListener('error', (event)=>{
    send('console', { level:'error', text: String(event?.message || 'Script error') });
  });
  window.addEventListener('unhandledrejection', (event)=>{
    let text = 'Unhandled promise rejection';
    try{ text += ': ' + fmt(event?.reason); }catch(_){ }
    send('console', { level:'error', text });
  });
  window.addEventListener('DOMContentLoaded', ()=> send('ready', {}), { once:true });
})();
<\/script>`;
}

function codePreviewCspMeta(){
  return `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob: http: https:; media-src data: blob: http: https:; font-src data: http: https:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none';">`;
}

function injectPreviewSecurityMeta(html){
  const src = String(html || '');
  const meta = `<meta charset="utf-8">${codePreviewCspMeta()}`;
  if(/<head\b[^>]*>/i.test(src)){
    return src.replace(/<head\b([^>]*)>/i, `<head$1>${meta}`);
  }
  if(/<html\b[^>]*>/i.test(src)){
    return src.replace(/<html\b([^>]*)>/i, `<html$1><head>${meta}</head>`);
  }
  return `<!doctype html><html><head>${meta}</head><body>${src}</body></html>`;
}

function buildPreviewDocument(meta, code, previewId){
  const lang = String(meta?.lang || '').trim();
  const source = String(code || '');
  const bridge = buildPreviewRunnerBridge(previewId);
  if(lang === 'html' || lang === 'htm' || lang === 'xhtml'){
    const safeSource = injectPreviewSecurityMeta(source);
    return safeSource.includes('</body>') ? safeSource.replace(/<\/body>/i, `${bridge}</body>`) : `${safeSource}${bridge}`;
  }
  if(lang === 'svg'){
    return `<!doctype html><html><head><meta charset="utf-8">${codePreviewCspMeta()}${bridge}<style>html,body{margin:0;padding:0;background:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;}svg{max-width:100%;max-height:100vh;}</style></head><body>${source}</body></html>`;
  }
  if(lang === 'css'){
    const title = escapeHtml(markdownUiT('code.runner.css_title', null, 'CSS preview'));
    const desc = escapeHtml(markdownUiT('code.runner.css_desc', null, 'This default preview container shows the applied styles.'));
    const button = escapeHtml(markdownUiT('code.runner.css_button', null, 'Example button'));
    return `<!doctype html><html><head><meta charset="utf-8">${codePreviewCspMeta()}<style>${source}</style>${bridge}</head><body><main class="preview-demo"><h1>${title}</h1><p>${desc}</p><button type="button">${button}</button></main></body></html>`;
  }
  const safeJs = source.replace(/<\/script/gi, '<\/script');
  return `<!doctype html><html><head><meta charset="utf-8">${codePreviewCspMeta()}${bridge}<style>html,body{margin:0;padding:16px;font-family:system-ui;background:#fff;color:#111;}button{cursor:pointer;}

/* ===== Mobile assistant bubble anti-offset fix ===== */
@media (max-width: 900px){
  body.sidebar-collapsed .bubble.a,
  body.is-mobile.sidebar-collapsed .bubble.a,
  .bubble.a{
    transform:none !important;
  }

  .bubble.a,
  .bubble.a .bubble-head,
  .bubble.a .bubble-body,
  .bubble-actions-assistant{
    margin-left:0 !important;
    margin-right:0 !important;
  }

  .bubble.a{
    width:100% !important;
    max-width:100% !important;
    padding-left:0 !important;
    padding-right:0 !important;
    overflow:visible !important;
  }

  .bubble.a .bubble-body{
    width:100% !important;
    max-width:100% !important;
    overflow-wrap:anywhere !important;
    word-break:break-word !important;
    box-sizing:border-box !important;
  }

  .bubble.a .bubble-body > *{
    max-width:100% !important;
    box-sizing:border-box !important;
  }

  .bubble-actions-assistant{
    justify-content:flex-start !important;
  }
}


/* ===== compact user mixed text+image turn ===== */
.user-mixed-turn-group{
  width:fit-content;
  max-width:min(360px,68vw);
  margin:6px max(18px,calc((100% - min(var(--gpt-content-max),calc(100% - 24px)))/2)) 8px auto;
  display:flex;
  flex-direction:column;
  align-items:flex-end;
  gap:6px;
}
.user-mixed-turn-group .bubble{
  width:auto !important;
  max-width:100% !important;
  margin:0 !important;
}
.user-mixed-turn-group .bubble.u{
  margin-right:0 !important;
}
.bubble-image-only{
  padding:0 !important;
  background:transparent !important;
  border:none !important;
  box-shadow:none !important;
  gap:0 !important;
}
.bubble-image-only .bubble-body{
  margin:0 !important;
  padding:0 !important;
  line-height:0 !important;
  background:transparent !important;
  border:none !important;
}
.bubble-image-only .inline-img-standalone{
  display:block !important;
  width:min(360px,68vw) !important;
  min-width:0 !important;
  max-width:min(360px,68vw) !important;
  height:auto !important;
  max-height:none !important;
  margin:0 !important;
  border-radius:18px !important;
  overflow:hidden !important;
  background:transparent !important;
}
.bubble-image-only .inline-img-standalone .inline-img,
.bubble-image-only img.inline-img.inline-img-standalone{
  display:block !important;
  width:100% !important;
  min-width:0 !important;
  max-width:100% !important;
  height:auto !important;
  min-height:0 !important;
  max-height:min(56vh,520px) !important;
  object-fit:contain !important;
  border-radius:18px !important;
  background:transparent !important;
}
.bubble-image-only .inline-image-group{
  margin:0 !important;
}
.bubble-image-only .inline-image-cell{
  border-radius:18px !important;
}
.user-mixed-turn-group .structured-text-block{
  margin:0 !important;
}


/* ===== compact file card readability tweak ===== */
.bubble-attachment .file-card .file-icon{
  color:color-mix(in srgb, var(--fg) 68%, transparent) !important;
  background:color-mix(in srgb, var(--fg) 10%, transparent) !important;
}
.bubble-attachment .file-card .file-icon svg{
  stroke-width:2.1 !important;
}
.bubble-attachment .file-card .file-name{
  font-size:16px !important;
  line-height:1.18 !important;
  font-weight:800 !important;
  color:color-mix(in srgb, var(--fg) 96%, transparent) !important;
}
.bubble-attachment .file-card .file-meta{
  font-size:14px !important;
  line-height:1.2 !important;
  color:color-mix(in srgb, var(--fg) 66%, transparent) !important;
}
.bubble-attachment .file-card .file-download{
  font-size:14px !important;
  line-height:1.2 !important;
}


/* ===== Composer minimal final override: keep only input content + disclaimer, remove surrounding frames ===== */
.composer{
  background:transparent !important;
  border-top:none !important;
  box-shadow:none !important;
  backdrop-filter:none !important;
  -webkit-backdrop-filter:none !important;
}
.composer::before,
.composer::after,
.composer-bar::before,
.composer-bar::after,
.composer-input-shell::before,
.composer-input-shell::after{
  content:none !important;
  display:none !important;
}
.composer-bar{
  background:transparent !important;
  border:none !important;
  box-shadow:none !important;
}
.composer-input-shell,
[data-theme="dark"] .composer-input-shell,
.composer-input-shell:focus-within,
[data-theme="dark"] .composer-input-shell:focus-within{
  background:transparent !important;
  border:none !important;
  box-shadow:none !important;
  border-radius:0 !important;
  outline:none !important;
}
#input,
[data-theme="dark"] #input,
#input:focus,
[data-theme="dark"] #input:focus{
  background:transparent !important;
  border:none !important;
  box-shadow:none !important;
  outline:none !important;
  border-radius:0 !important;
}
.composer-disclaimer{
  background:transparent !important;
  border:none !important;
  box-shadow:none !important;
}


</style></head><body><div id="app"></div><script>${safeJs}<\/script></body></html>`;
}

function setCodeRunnerSource(state, code){
  if(!state?.source) return;
  const src = String(code || '').replace(/\r\n?/g, '\n');
  state.sourceCode = src;
  if(!src.trim()){
    state.source.hidden = true;
    state.source.textContent = '';
    return;
  }
  state.source.hidden = false;
  state.source.textContent = src;
}

function setCodeRunnerPanelDisplayMode(state, mode){
  if(!state?.panel) return;
  const normalized = String(mode || '').trim() === 'preview' ? 'preview' : 'server';
  const isPreview = normalized === 'preview';
  state.panel.classList.toggle('is-preview-mode', isPreview);
  state.panel.classList.toggle('is-server-mode', !isPreview);
  if(state.main) state.main.hidden = !isPreview;
}

function resolveCodeRunnerLocalizedValue(value, fallback=''){
  if(value && typeof value === 'object' && !Array.isArray(value)){
    const key = String(value.key || '').trim();
    const textFallback = String(value.fallback || fallback || '').trim();
    if(key) return markdownUiT(key, value.params || null, textFallback);
  }
  return String(value ?? fallback ?? '');
}

function resolveCodeRunnerMetaText(metaText){
  if(Array.isArray(metaText)){
    return metaText.map(item=>resolveCodeRunnerLocalizedValue(item)).filter(Boolean).join(' · ');
  }
  return resolveCodeRunnerLocalizedValue(metaText);
}

function setCodeRunnerOutput(state, sections, metaText, isError=false){
  if(!state) return;
  state.frame.hidden = true;
  const sourceText = String(state.sourceCode || '').replace(/\r\n?/g, '\n').trim();
  const normalizedSections = Array.isArray(sections) ? sections.filter(Boolean) : [];
  const mergedSections = [];
  if(sourceText){
    mergedSections.push({ title:{ key:'code.runner.source', fallback:'Code' }, body: sourceText, kind:'source' });
  }
  mergedSections.push(...normalizedSections);
  state.outputSnapshot = {
    sections: normalizedSections.map(section=>({ ...section })),
    metaText: Array.isArray(metaText) ? metaText.map(item=>(item && typeof item === 'object' ? { ...item } : item)) : metaText,
    isError: !!isError,
  };
  state.body.hidden = false;
  state.body.classList.toggle('is-error', !!isError);
  const resolvedMetaText = resolveCodeRunnerMetaText(metaText);
  state.metaEl.textContent = resolvedMetaText;
  syncCodeRunDockHeaderForState(state, resolvedMetaText);
  state.output.innerHTML = mergedSections.map(section=>{
    const title = escapeHtml(resolveCodeRunnerLocalizedValue(section?.title).trim());
    const body = escapeHtml(resolveCodeRunnerLocalizedValue(section?.body).trim());
    const kindClass = String(section?.kind || '').trim() === 'source' ? ' code-run-section-source' : '';
    if(!title || !body) return '';
    return `<div class="code-run-section${kindClass}"><div class="code-run-section-label">${title}</div><pre>${body}</pre></div>`;
  }).join('') || `<div class="code-run-section"><div class="code-run-section-label">${escapeHtml(markdownUiT('code.runner.output', null, 'Output'))}</div><pre>${escapeHtml(markdownUiT('code.runner.no_output', null, 'No output'))}</pre></div>`;
}


function getCodeRunPublicStopReason(stderr, exitCode, timedOut){
  const text = String(stderr || '').trim();
  const code = Number(exitCode);
  if(timedOut) return 'timeout';
  if(/^killed$/i.test(text)) return 'resource';
  if(Number.isFinite(code) && (code === 137 || code === 143 || code === -9 || code === -15)) return 'resource';
  return '';
}

function isCodeRunInternalStopText(stderr){
  return /^\s*(killed|terminated)\s*$/i.test(String(stderr || ''));
}

function getCodeRunPublicRequestFailureMessage(data){
  const code = String(data?.code || '').trim();
  const params = data?.params && typeof data.params === 'object' ? data.params : {};
  if(code === 'code_language_required') return markdownUiT('code.runner.language_required', null, 'Select a language before running the code.');
  if(code === 'code_language_unsupported') return markdownUiT('code.runner.language_unsupported', params, '{language} is not supported. Available runtimes: {supported}.');
  if(code === 'code_empty') return markdownUiT('code.runner.code_empty', null, 'The code is empty.');
  if(code === 'code_too_large') return markdownUiT('code.runner.code_too_large', null, 'The code exceeds the current run limit.');
  if(code === 'code_invalid_request') return markdownUiT('code.runner.invalid_request', null, 'The run request is invalid.');
  if(code === 'code_runtime_missing') return markdownUiT('code.runner.runtime_missing', params, 'The {runtime} runtime is not available on the server.');
  return markdownUiT('code.runner.request_failed', null, 'The run could not be started. Please try again later.');
}

function runCodeBlockPreview(block, runBtn, meta, code){
  if(!block || !runBtn || !meta) return;
  ensureCodeRunnerGlobalEvents();
  let state = block._codeRunnerState || null;
  if(!state || !state.panel || !document.body.contains(state.panel)){
    state = createCodeRunnerPanel(block, runBtn, meta);
    block._codeRunnerState = state;
  }
  if(state.previewId){
    try{ codeRunnerStates.delete(String(state.previewId)); }catch(_){ }
  }
  state.meta = meta;
  showCodeRunDockForState(state);
  setCodeRunnerPanelDisplayMode(state, 'preview');
  state.previewId = `runner_${Date.now()}_${++codeRunnerSeq}`;
  state.panel.hidden = false;
  state.sourceCode = String(code || '');
  if(state.source){
    state.source.hidden = true;
    state.source.textContent = '';
  }
  state.body.hidden = true;
  state.body.innerHTML = '';
  state.metaEl.textContent = '';
  syncCodeRunDockHeaderForState(state, markdownUiT('code.runner.previewing', null, 'Previewing…'));
  state.frame.hidden = false;
  state.isRunning = true;
  updateCodeRunnerToolbarState(state, 'running');
  codeRunnerStates.set(state.previewId, state);
  try{
    state.frame.srcdoc = buildPreviewDocument(meta, code, state.previewId);
  }catch(err){
    state.isRunning = false;
    updateCodeRunnerToolbarState(state, 'idle');
    setCodeRunnerOutput(state, [{
      title:{ key:'code.runner.error', fallback:'Error' },
      body:err?.message || String(err || markdownUiT('code.runner.preview_failed', null, 'Preview failed')),
    }], '', true);
  }
}

async function runCodeBlockServer(block, runBtn, meta, code){
  if(!block || !runBtn || !meta) return;
  if(codeRunRuntimeMatrix.loaded && meta.mode === 'server' && !isCodeRunServerLangAvailable(meta.lang)){
    setStatus(markdownUiT('code.runner.runtime_unavailable', {language:meta.label || meta.lang}, 'The {language} runtime is currently unavailable.'));
    syncCodeRunBlockAvailability(block);
    return;
  }
  let state = block._codeRunnerState || null;
  if(!state || !state.panel || !document.body.contains(state.panel)){
    state = createCodeRunnerPanel(block, runBtn, meta);
    block._codeRunnerState = state;
  }
  state.meta = meta;
  showCodeRunDockForState(state);
  setCodeRunnerPanelDisplayMode(state, 'server');
  state.panel.hidden = false;
  state.sourceCode = String(code || '');
  state.frame.hidden = true;
  if(state.source){
    state.source.hidden = true;
    state.source.textContent = '';
  }
  state.body.hidden = false;
  state.body.classList.remove('is-error');
  state.body.innerHTML = `<div class="code-run-section"><div class="code-run-section-label">${escapeHtml(markdownUiT('code.runner.status', null, 'Status'))}</div><pre>${escapeHtml(markdownUiT('code.runner.running', null, 'Running…'))}</pre></div>`;
  state.metaEl.textContent = '';
  syncCodeRunDockHeaderForState(state, markdownUiT('code.runner.running', null, 'Running…'));
  state.isRunning = true;
  updateCodeRunnerToolbarState(state, 'running');
  try{
    const resp = await fetch('/api3/code/run', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ language: meta.lang, code: String(code || '') }),
    });
    const data = await resp.json().catch(()=>({ ok:false, code:'code_invalid_json' }));
    const ok = !!data?.ok && resp.ok;
    const sections = [];
    const compileStdout = String(data?.compile_stdout || '').trim();
    const compileStderr = String(data?.compile_stderr || '').trim();
    const stdout = String(data?.stdout || '').trim();
    const stderr = String(data?.stderr || '').trim();
    const elapsed = Number(data?.elapsed_ms || 0);
    const exitCode = Number.isFinite(Number(data?.exit_code)) ? Number(data?.exit_code) : 0;
    const timedOut = !!data?.timed_out;
    const stopReason = getCodeRunPublicStopReason(stderr, exitCode, timedOut);
    const stopped = !!stopReason;
    const success = ok && !stopped && exitCode === 0 && data?.success !== false;
    if(compileStdout) sections.push({ title:{key:'code.runner.compile_output', fallback:'Compiler output'}, body: compileStdout });
    if(compileStderr) sections.push({ title:{key:'code.runner.compile_error', fallback:'Compiler error'}, body: compileStderr });
    if(stdout) sections.push({ title:{key:'code.runner.output', fallback:'Output'}, body: stdout });
    if(stderr && !isCodeRunInternalStopText(stderr)) sections.push({ title:{key:'code.runner.stderr', fallback:'Error output'}, body: stderr });
    if(stopReason === 'timeout'){
      sections.unshift({ title:{key:'code.runner.stopped', fallback:'Stopped'}, body:{key:'code.runner.stopped_timeout', fallback:'The program ran for too long and was stopped automatically.'} });
    }else if(stopReason === 'resource'){
      sections.unshift({ title:{key:'code.runner.stopped', fallback:'Stopped'}, body:{key:'code.runner.stopped_resource', fallback:'The program used too many resources and was stopped automatically.'} });
    }else if(ok && exitCode !== 0 && !stdout && !stderr && !compileStdout && !compileStderr){
      sections.push({ title:{key:'code.runner.incomplete', fallback:'Run incomplete'}, body:{key:'code.runner.incomplete_empty', fallback:'The program did not complete successfully and produced no output.'} });
    }else if(!sections.length && success){
      sections.push({ title:{key:'code.runner.complete', fallback:'Run complete'}, body:{key:'code.runner.complete_empty', fallback:'The program completed without output.'} });
    }
    if(!ok){
      const failureBody = String(data?.code || '') === 'code_invalid_json'
        ? {key:'code.runner.invalid_json', fallback:'The runner returned an invalid response.'}
        : getCodeRunPublicRequestFailureMessage(data);
      sections.unshift({ title:{key:'code.runner.not_started', fallback:'Run not started'}, body:failureBody });
    }
    const metaBits = [];
    if(elapsed > 0) metaBits.push(`${elapsed} ms`);
    if(ok) metaBits.push(stopped
      ? {key:'code.runner.stopped', fallback:'Stopped'}
      : (success ? {key:'code.runner.complete', fallback:'Run complete'} : {key:'code.runner.incomplete', fallback:'Run incomplete'}));
    else if(resp?.status) metaBits.push({key:'code.runner.failed', fallback:'Run failed'});
    setCodeRunnerOutput(state, sections, metaBits, !success);
  }catch(err){
    setCodeRunnerOutput(state, [{
      title:{key:'code.runner.failed', fallback:'Run failed'},
      body:{key:'code.runner.request_failed', fallback:'The run could not be started. Please try again later.'},
    }], [{key:'code.runner.failed', fallback:'Run failed'}], true);
  }finally{
    state.isRunning = false;
    updateCodeRunnerToolbarState(state, 'idle');
  }
}

function runCodeBlock(block, runBtn){
  const code = getCodeBlockRawSource(block);
  const meta = getRunnableCodeMeta(block?.dataset?.runLang || '', code);
  if(!meta || !code.trim()) return;
  if(meta.mode === 'preview'){
    runCodeBlockPreview(block, runBtn, meta, code);
    return;
  }
  runCodeBlockServer(block, runBtn, meta, code);
}

function bubbleMessageTextForComposer(msg){
  if(!msg) return "";
  if(typeof msg.content === "string") return String(msg.content || "");
  if(Array.isArray(msg.content)) return msg.content.filter(x => x?.type === "text" && x?.text).map(x => x.text).join("\n");
  return "";
}

function loadMessageTextIntoComposerFromBubble(btn, text){
  inputEl.value = String(text || "");
  autoResizeInput();
  updateComposerActionState();
  try{
    if(typeof persistActiveComposerDraft === 'function') persistActiveComposerDraft(inputEl.value);
    else persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value);
  }catch(_){ persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value); }
  inputEl.focus();
  try{ btn?.closest('.bubble')?.classList.add('bubble-editing'); setTimeout(()=>btn?.closest('.bubble')?.classList.remove('bubble-editing'), 1200); }catch(_){ }
  try{ scrollComposerIntoView(); }catch(_){ }
}

function loadMessageIntoComposerFromBubble(btn, msg){
  clearPastedImages();
  const quoteText = getMessageQuoteText(msg);
  if(quoteText) setComposerQuoteState({
    text: quoteText,
    msgIndex: getMessageQuoteSourceIndex(msg),
    messageId: getMessageQuoteSourceId(msg),
    sourceOffset: getMessageQuoteSourceOffset(msg),
  }, { persist:true });
  else clearComposerQuoteState({ silent:true });
  inputEl.value = bubbleMessageTextForComposer(msg);
  autoResizeInput();
  hydrateComposerAttachmentsFromMessage(msg);
  updateComposerActionState();
  try{
    if(typeof persistActiveComposerDraft === 'function') persistActiveComposerDraft(inputEl.value);
    else persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value);
  }catch(_){ persistComposerDraft((typeof getComposerInputOwnerSessionId === 'function' ? getComposerInputOwnerSessionId() : store.activeId), inputEl.value); }
  inputEl.focus();
  try{ btn?.closest('.bubble')?.classList.add('bubble-editing'); setTimeout(()=>btn?.closest('.bubble')?.classList.remove('bubble-editing'), 1200); }catch(_){ }
  try{ scrollComposerIntoView(); }catch(_){ }
}

let aiQuoteSelectionState = { text:"", x:0, y:0, msgIndex:null, messageId:'', sourceOffset:null };
let aiQuotePopoverFrame = 0;
let aiQuoteSelectionFinishTimer = 0;
let aiQuotePointerSelecting = false;
let aiQuotePointerStartedInAssistantAnswer = false;

function normalizeAssistantQuoteText(raw){
  const text = String(raw || "").replace(/\u00a0/g, ' ').replace(/\r\n?/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  if(!text) return "";
  return text.length > 1800 ? (text.slice(0, 1800).trimEnd() + '…') : text;
}

function getAssistantBubbleBodyFromNode(node){
  const base = node && node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  const body = base?.closest?.('.bubble.a .bubble-body') || null;
  if(!body) return null;
  if(body.closest('.bubble-actions') || body.closest('.composer') || body.closest('.settings-mask')) return null;
  return body;
}

function getAssistantQuoteAnswerWrapFromNode(node){
  const base = node && node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  const answerWrap = base?.closest?.('.bubble.a .bubble-body .reasoning-answer-wrap') || null;
  if(!answerWrap) return null;
  if(answerWrap.closest('.reasoning-panels,.reasoning-panel,.thinking-wrap,.draft-process-wrap,.bubble-sources,.bubble-quote-ref,.bubble-actions,.composer,.settings-mask')) return null;
  return answerWrap;
}

function getAssistantQuoteNormalizedSourceOffset(answerWrap, range){
  if(!answerWrap || !range) return null;
  const startContainer = range.startContainer;
  const startOffset = Number(range.startOffset || 0) || 0;
  const parts = [];
  for(const row of collectTextNodes(answerWrap)){
    const node = row?.node;
    if(!node) continue;
    const value = String(node.nodeValue || '');
    if(node === startContainer){
      parts.push(value.slice(0, Math.max(0, Math.min(startOffset, value.length))));
      break;
    }
    try{
      const relation = node.compareDocumentPosition(startContainer);
      if(relation & Node.DOCUMENT_POSITION_FOLLOWING){
        parts.push(value);
        continue;
      }
    }catch(_){ }
    try{
      const probe = document.createRange();
      probe.selectNodeContents(node);
      if(probe.compareBoundaryPoints(Range.END_TO_START, range) <= 0) parts.push(value);
    }catch(_){ }
  }
  return quoteMatchNormalizeWithMap(parts.join('')).text.length;
}

function captureAssistantSelectionPayload(){
  const sel = window.getSelection?.();
  if(!sel || sel.rangeCount < 1 || sel.isCollapsed) return null;
  const text = normalizeAssistantQuoteText(sel.toString());
  if(!text) return null;
  const anchorBody = getAssistantBubbleBodyFromNode(sel.anchorNode);
  const focusBody = getAssistantBubbleBodyFromNode(sel.focusNode);
  if(!anchorBody || !focusBody || anchorBody !== focusBody) return null;
  const anchorAnswerWrap = getAssistantQuoteAnswerWrapFromNode(sel.anchorNode);
  const focusAnswerWrap = getAssistantQuoteAnswerWrapFromNode(sel.focusNode);
  if(!anchorAnswerWrap || !focusAnswerWrap || anchorAnswerWrap !== focusAnswerWrap) return null;
  let range = null;
  let rect = null;
  try{
    range = sel.getRangeAt(0);
    rect = range.getBoundingClientRect();
  }catch(_){ }
  if(range && typeof range.intersectsNode === 'function'){
    try{
      if(!range.intersectsNode(anchorAnswerWrap)) return null;
    }catch(_){ }
  }
  if(!rect || (!rect.width && !rect.height)){
    try{ rect = anchorAnswerWrap.getBoundingClientRect(); }catch(_){ rect = null; }
  }
  if(!rect) return null;
  const msgIndex = Number(anchorBody.closest('.bubble')?.dataset?.msgIndex || -1);
  const activeMessages = Array.isArray(getActive()?.messages) ? getActive().messages : [];
  const sourceMessage = Number.isInteger(msgIndex) && msgIndex >= 0 ? activeMessages[msgIndex] : null;
  const sourceOffset = getAssistantQuoteNormalizedSourceOffset(anchorAnswerWrap, range);
  return {
    text,
    body: anchorBody,
    rect,
    msgIndex,
    messageId: assistantQuoteMessageIdentity(sourceMessage),
    sourceOffset: Number.isInteger(sourceOffset) && sourceOffset >= 0 ? sourceOffset : null,
  };
}

function hideAssistantQuotePopover(){
  if(aiQuotePopoverFrame){
    cancelAnimationFrame(aiQuotePopoverFrame);
    aiQuotePopoverFrame = 0;
  }
  if(aiQuotePopoverEl){
    aiQuotePopoverEl.classList.remove('show');
    aiQuotePopoverEl.setAttribute('aria-hidden', 'true');
  }
  aiQuoteSelectionState = { text:"", x:0, y:0, msgIndex:null, messageId:'', sourceOffset:null };
}

function showAssistantQuotePopover(payload){
  if(!aiQuotePopoverEl || !payload?.rect) return;
  const pad = 14;
  const vw = window.innerWidth || document.documentElement.clientWidth || 0;
  const left = Math.min(Math.max(payload.rect.left + payload.rect.width / 2, pad), Math.max(pad, vw - pad));
  const top = Math.max(pad + 10, payload.rect.top - 10);
  aiQuoteSelectionState = {
    text:String(payload.text || ''),
    x:left,
    y:top,
    msgIndex:payload.msgIndex,
    messageId:String(payload.messageId || '').trim().slice(0, 220),
    sourceOffset:Number.isInteger(Number(payload.sourceOffset)) && Number(payload.sourceOffset) >= 0 ? Number(payload.sourceOffset) : null,
  };
  aiQuotePopoverEl.style.left = left + 'px';
  aiQuotePopoverEl.style.top = top + 'px';
  aiQuotePopoverEl.classList.add('show');
  aiQuotePopoverEl.setAttribute('aria-hidden', 'false');
}

function refreshAssistantQuotePopover(){
  aiQuotePopoverFrame = 0;
  const payload = captureAssistantSelectionPayload();
  if(!payload){
    hideAssistantQuotePopover();
    return;
  }
  showAssistantQuotePopover(payload);
}

function clearAssistantQuoteSelectionFinishTimer(){
  if(aiQuoteSelectionFinishTimer){
    clearTimeout(aiQuoteSelectionFinishTimer);
    aiQuoteSelectionFinishTimer = 0;
  }
}

function queueAssistantQuotePopoverRefresh(){
  if(aiQuotePopoverFrame) cancelAnimationFrame(aiQuotePopoverFrame);
  aiQuotePopoverFrame = requestAnimationFrame(refreshAssistantQuotePopover);
}

function queueAssistantQuotePopoverAfterSelectionDone(delay){
  clearAssistantQuoteSelectionFinishTimer();
  aiQuoteSelectionFinishTimer = setTimeout(()=>{
    aiQuoteSelectionFinishTimer = 0;
    aiQuotePointerSelecting = false;
    queueAssistantQuotePopoverRefresh();
  }, Math.max(0, Number(delay) || 0));
}

function handleAssistantQuoteSelectionChanging(){
  if(aiQuotePopoverEl?.classList?.contains('show')) hideAssistantQuotePopover();
  if(aiQuotePointerSelecting || aiQuotePointerStartedInAssistantAnswer) return;
  queueAssistantQuotePopoverAfterSelectionDone(220);
}

function markAssistantQuotePointerSelectionStart(target){
  clearAssistantQuoteSelectionFinishTimer();
  aiQuotePointerStartedInAssistantAnswer = !!getAssistantQuoteAnswerWrapFromNode(target);
  aiQuotePointerSelecting = aiQuotePointerStartedInAssistantAnswer;
  hideAssistantQuotePopover();
}

function markAssistantQuotePointerSelectionEnd(){
  if(!aiQuotePointerSelecting && !aiQuotePointerStartedInAssistantAnswer) return;
  aiQuotePointerSelecting = false;
  aiQuotePointerStartedInAssistantAnswer = false;
  queueAssistantQuotePopoverAfterSelectionDone(40);
}

function quoteSelectedAssistantTextIntoComposer(){
  const selectedText = normalizeAssistantQuoteText(aiQuoteSelectionState?.text || window.getSelection?.()?.toString?.() || '');
  if(!selectedText) return;
  setComposerQuoteState({
    text: selectedText,
    msgIndex: Number.isFinite(aiQuoteSelectionState?.msgIndex) ? Number(aiQuoteSelectionState.msgIndex) : null,
    messageId: String(aiQuoteSelectionState?.messageId || '').trim().slice(0, 220),
    sourceOffset: Number.isInteger(Number(aiQuoteSelectionState?.sourceOffset)) && Number(aiQuoteSelectionState.sourceOffset) >= 0 ? Number(aiQuoteSelectionState.sourceOffset) : null,
  });
  inputEl?.focus();
  try{ setStatus(markdownUiT('composer.quote_placed', null, 'Quote added above the composer')); }catch(_){ }
  try{ toast(window.AperviaI18n?.t('composer.quote_placed') || 'Quote added above the composer'); }catch(_){ }
  try{ window.getSelection?.()?.removeAllRanges?.(); }catch(_){ }
  hideAssistantQuotePopover();
}

function initAssistantSelectionQuoteUi(){
  if(!aiQuotePopoverEl || !aiQuoteAskBtnEl || aiQuotePopoverEl.dataset.bound === '1') return;
  aiQuotePopoverEl.dataset.bound = '1';
  composerQuoteClearEl?.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    clearComposerQuoteState();
    inputEl?.focus();
  });
  aiQuoteAskBtnEl.addEventListener('mousedown', (e)=>{
    e.preventDefault();
  });
  aiQuoteAskBtnEl.addEventListener('click', (e)=>{
    e.preventDefault();
    e.stopPropagation();
    quoteSelectedAssistantTextIntoComposer();
  });
  document.addEventListener('selectionchange', handleAssistantQuoteSelectionChanging, true);
  document.addEventListener('pointerdown', (e)=>{
    if(aiQuotePopoverEl.contains(e.target)) return;
    markAssistantQuotePointerSelectionStart(e.target);
  }, true);
  document.addEventListener('pointerup', markAssistantQuotePointerSelectionEnd, true);
  document.addEventListener('pointercancel', markAssistantQuotePointerSelectionEnd, true);
  document.addEventListener('mouseup', markAssistantQuotePointerSelectionEnd, true);
  document.addEventListener('touchend', markAssistantQuotePointerSelectionEnd, true);
  document.addEventListener('keyup', (e)=>{
    const key = String(e?.key || '');
    if(key.startsWith('Arrow') || key === 'Shift' || key === 'Meta' || key === 'Control'){
      queueAssistantQuotePopoverAfterSelectionDone(40);
    }
  }, true);
  document.addEventListener('mousedown', (e)=>{
    if(aiQuotePopoverEl.contains(e.target)) return;
    const insideAssistantBubble = !!e.target?.closest?.('.bubble.a .bubble-body');
    if(!insideAssistantBubble) hideAssistantQuotePopover();
  }, true);
  document.addEventListener('scroll', ()=>{ hideAssistantQuotePopover(); }, true);
  window.addEventListener('resize', hideAssistantQuotePopover);
}

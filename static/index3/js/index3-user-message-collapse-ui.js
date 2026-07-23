/* User message collapse UI helpers split from index3.js. */
const USER_MESSAGE_COLLAPSE_MIN_HEIGHT = 320;
const USER_MESSAGE_COLLAPSE_MAX_HEIGHT = 420;
const USER_MESSAGE_COLLAPSE_TRIGGER_EXTRA = 28;
const USER_MESSAGE_COLLAPSE_TEXT_FALLBACK_CHARS = 900;
const USER_MESSAGE_COLLAPSE_TEXT_FALLBACK_LINES = 18;

function userMessageCollapsedHeight(){
  const viewport = Number(window?.innerHeight || 0) || 0;
  if(!viewport) return USER_MESSAGE_COLLAPSE_MAX_HEIGHT;
  return Math.max(USER_MESSAGE_COLLAPSE_MIN_HEIGHT, Math.min(USER_MESSAGE_COLLAPSE_MAX_HEIGHT, Math.round(viewport * 0.42)));
}

function cleanupUserMessageCollapse(body){
  if(!body) return;
  body.classList.remove('user-message-collapsible', 'user-message-collapsed', 'user-message-expanded');
  body.style.removeProperty('--user-message-collapsed-max');
  body.querySelector(':scope > .user-message-expand-toggle')?.remove();
  delete body.dataset.userCollapseReady;
}

function userMessageCollapseNeedsToggle(body, collapsedHeight){
  if(!body) return false;
  const limit = collapsedHeight + USER_MESSAGE_COLLAPSE_TRIGGER_EXTRA;
  const scrollHeight = Number(body.scrollHeight || 0) || 0;
  const rectHeight = Number(body.getBoundingClientRect?.().height || 0) || 0;
  if(scrollHeight > limit || rectHeight > limit) return true;
  const text = String(body.innerText || body.textContent || '');
  if(!text.trim()) return false;
  const normalized = text.replace(/\r\n?/g, '\n');
  const lineCount = normalized.split('\n').length;
  return normalized.length >= USER_MESSAGE_COLLAPSE_TEXT_FALLBACK_CHARS || lineCount >= USER_MESSAGE_COLLAPSE_TEXT_FALLBACK_LINES;
}

function applyUserMessageCollapse(root){
  if(!root?.querySelectorAll && !root?.classList) return;
  const bubbles = root.classList?.contains('bubble')
    ? [root]
    : Array.from(root.querySelectorAll?.('.bubble.u') || []);
  for(const bubble of bubbles){
    if(!bubble?.classList?.contains('u')) continue;
    if(bubble.classList.contains('bubble-user-split-image') || bubble.classList.contains('bubble-attachment')) continue;
    const body = bubble.querySelector(':scope > .bubble-body');
    if(!body) continue;
    if(body.querySelector(':scope > .inline-img-standalone, :scope > .inline-image-group, :scope > .file-card, :scope > .bubble-attachment')){
      cleanupUserMessageCollapse(body);
      continue;
    }

    const existingToggle = body.querySelector(':scope > .user-message-expand-toggle');
    const keepExpanded = body.classList.contains('user-message-expanded') || existingToggle?.getAttribute('aria-expanded') === 'true';
    if(existingToggle) existingToggle.remove();
    body.classList.remove('user-message-collapsible', 'user-message-collapsed', 'user-message-expanded');
    body.style.removeProperty('--user-message-collapsed-max');

    const collapsedHeight = userMessageCollapsedHeight();
    if(!userMessageCollapseNeedsToggle(body, collapsedHeight)){
      cleanupUserMessageCollapse(body);
      continue;
    }

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'user-message-expand-toggle';
    const setExpanded = (expanded)=>{
      body.classList.toggle('user-message-expanded', expanded);
      body.classList.toggle('user-message-collapsed', !expanded);
      toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      toggle.textContent = expanded ? '收起⌃' : '展开⌄';
    };
    toggle.addEventListener('click', (e)=>{
      e.preventDefault();
      e.stopPropagation();
      setExpanded(!body.classList.contains('user-message-expanded'));
      try{ maybeAutoScroll(); }catch(_){ }
    });
    body.style.setProperty('--user-message-collapsed-max', `${collapsedHeight}px`);
    body.classList.add('user-message-collapsible');
    body.appendChild(toggle);
    setExpanded(!!keepExpanded);
    body.dataset.userCollapseReady = '1';
  }
}

function scheduleUserMessageCollapse(root){
  if(!root) return;
  applyUserMessageCollapse(root);
  const rerun = () => { try{ applyUserMessageCollapse(root); }catch(_){ } };
  try{ requestAnimationFrame(() => requestAnimationFrame(rerun)); }catch(_){ setTimeout(rerun, 40); }
  setTimeout(rerun, 160);
  setTimeout(rerun, 520);
}

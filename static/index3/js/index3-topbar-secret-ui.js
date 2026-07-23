/* Topbar secondary menu and secret input toggle UI. Extracted from index3.js. */

function initTopbarSecondaryUI(){
  const wrap = document.getElementById('topbarSecondaryWrap');
  const btn = document.getElementById('topbarSecondaryBtn');
  const panel = document.getElementById('topbarSecondaryPanel');
  if(!wrap || !btn || !panel) return;
  const closePanel = ()=>{
    wrap.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
  };
  btn.addEventListener('click', (e)=>{
    e.stopPropagation();
    const opening = !wrap.classList.contains('open');
    wrap.classList.toggle('open', opening);
    btn.setAttribute('aria-expanded', opening ? 'true' : 'false');
  });
  document.addEventListener('click', (e)=>{
    if(!wrap.contains(e.target)) closePanel();
  });
  document.addEventListener('keydown', (e)=>{
    if(e.key === 'Escape') closePanel();
  });
}


function initSecretInputToggles(root = document){
  const scope = root && (root.querySelectorAll || root.matches) ? root : document;

  const icon = (visible) => visible
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3 3l18 18"></path><path d="M10.58 10.58a2 2 0 0 0 2.83 2.83"></path><path d="M9.88 4.24A10.94 10.94 0 0 1 12 4c5 0 9 4.5 10 8-0.36 1.26-1.18 2.68-2.34 3.94"></path><path d="M6.1 6.1C4.1 7.5 2.7 9.7 2 12c1 3.5 5 8 10 8 1.55 0 3-.43 4.25-1.13"></path></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"></path><circle cx="12" cy="12" r="3"></circle></svg>';

  const labelTextForInput = (input) => {
    const parts = [
      input.id,
      input.name,
      input.placeholder,
      input.getAttribute('aria-label'),
      input.getAttribute('autocomplete'),
    ];
    try{
      if(input.id){
        const label = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
        if(label) parts.push(label.textContent || '');
      }
    }catch(_){ }
    try{
      const field = input.closest('.field, .settings-field, .login-field, .form-field');
      const label = field ? field.querySelector('label') : null;
      if(label) parts.push(label.textContent || '');
    }catch(_){ }
    return parts.filter(Boolean).join(' ').trim();
  };

  const shouldAttachToggle = (input) => {
    if(!input || String(input.tagName || '').toLowerCase() !== 'input') return false;
    if(String(input.dataset?.secretToggle || '').trim() === '0') return false;
    const type = String(input.getAttribute('type') || input.type || 'text').trim().toLowerCase();
    if(['hidden','checkbox','radio','file','submit','button','reset','range','color','date','datetime-local','month','week','time','number','search'].includes(type)) return false;
    if(input.dataset?.secretToggle || input.classList?.contains('secret-toggle-input') || type === 'password') return true;
    const hay = labelTextForInput(input).toLowerCase();
    return /(api\s*key|api[_-]?key|apikey|access[_\s-]?key|secret[_\s-]?key|密钥|秘钥|授权码|secret|token|bearer|sk-)/i.test(hay);
  };

  const inputs = [];
  try{
    if(scope.matches && scope.matches('input')) inputs.push(scope);
  }catch(_){ }
  try{
    if(scope.querySelectorAll) inputs.push(...Array.from(scope.querySelectorAll('input')));
  }catch(_){ }

  inputs.filter(shouldAttachToggle).forEach((input)=>{
    if(!input) return;
    const currentParent = input.parentElement;
    let wrap = currentParent && currentParent.classList && currentParent.classList.contains('secret-input-wrap') ? currentParent : null;
    if(input.dataset.secretToggleReady === '1' && wrap && wrap.querySelector('.secret-toggle-btn')) return;
    if(input.dataset.secretToggleReady === '1' && !wrap) input.dataset.secretToggleReady = '';
    input.dataset.secretToggleReady = '1';
    input.dataset.secretToggle = input.dataset.secretToggle || '1';
    input.classList.add('secret-toggle-input');
    try{ input.type = 'password'; }catch(_){ }
    try{ input.setAttribute('autocomplete', 'off'); }catch(_){ }
    try{ input.setAttribute('spellcheck', 'false'); }catch(_){ }
    const parent = input.parentElement;
    if(!parent) return;
    if(!wrap){
      wrap = document.createElement('div');
      wrap.className = 'secret-input-wrap';
      parent.insertBefore(wrap, input);
      wrap.appendChild(input);
    }
    const oldBtn = wrap.querySelector('.secret-toggle-btn');
    if(oldBtn) oldBtn.remove();
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'secret-toggle-btn';
    btn.setAttribute('aria-label', '显示内容');
    btn.title = '显示内容';
    btn.innerHTML = icon(false);
    btn.addEventListener('click', ()=>{
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      btn.setAttribute('aria-label', visible ? '显示内容' : '隐藏内容');
      btn.title = visible ? '显示内容' : '隐藏内容';
      btn.innerHTML = icon(!visible);
      try{ input.focus({ preventScroll:true }); }catch(_){ input.focus?.(); }
    });
    wrap.appendChild(btn);
  });

  if(!initSecretInputToggles._observerReady){
    initSecretInputToggles._observerReady = true;
    const rerun = (()=>{
      let timer = 0;
      return (node)=>{
        clearTimeout(timer);
        timer = setTimeout(()=>initSecretInputToggles(node && node.querySelectorAll ? node : document), 30);
      };
    })();
    try{
      document.addEventListener('DOMContentLoaded', ()=>initSecretInputToggles(document), { once:true });
    }catch(_){ }
    try{
      window.addEventListener('load', ()=>initSecretInputToggles(document), { once:true });
    }catch(_){ }
    try{
      if(window.MutationObserver){
        const observer = new MutationObserver((mutations)=>{
          for(const m of mutations || []){
            for(const node of Array.from(m.addedNodes || [])){
              if(node && node.nodeType === 1){
                rerun(node);
                return;
              }
            }
          }
        });
        observer.observe(document.documentElement || document.body, { childList:true, subtree:true });
      }
    }catch(_){ }
  }
}

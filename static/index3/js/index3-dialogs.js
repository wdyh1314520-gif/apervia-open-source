/* WebAI dialog/confirm modal UI helpers. Split from index3.js without changing behavior. */
const deleteSessionModalEl = document.getElementById("deleteSessionModal");
const deleteSessionModalDescEl = document.getElementById("deleteSessionModalDesc");
const deleteSessionCancelBtn = document.getElementById("deleteSessionCancelBtn");
const deleteSessionConfirmBtn = document.getElementById("deleteSessionConfirmBtn");
let deleteSessionModalState = null;

const deleteApiKeyModalEl = document.getElementById("deleteApiKeyModal");
const deleteApiKeyModalDescEl = document.getElementById("deleteApiKeyModalDesc");
const deleteApiKeyCancelBtn = document.getElementById("deleteApiKeyCancelBtn");
const deleteApiKeyConfirmBtn = document.getElementById("deleteApiKeyConfirmBtn");
let deleteApiKeyModalState = null;


const kbDangerModalEl = document.getElementById("kbDangerModal");
const kbDangerModalTitleEl = document.getElementById("kbDangerModalTitle");
const kbDangerModalDescEl = document.getElementById("kbDangerModalDesc");
const kbDangerModalErrorEl = document.getElementById("kbDangerModalError");
const kbDangerCancelBtn = document.getElementById("kbDangerCancelBtn");
const kbDangerConfirmBtn = document.getElementById("kbDangerConfirmBtn");
let kbDangerModalState = null;

const settingsUnsavedExitModalEl = document.getElementById("settingsUnsavedExitModal");
const settingsUnsavedReturnBtn = document.getElementById("settingsUnsavedReturnBtn");
const settingsUnsavedExitBtn = document.getElementById("settingsUnsavedExitBtn");
let settingsUnsavedExitState = null;

const temporaryChatIntroModalEl = document.getElementById("temporaryChatIntroModal");
const temporaryChatIntroCancelBtn = document.getElementById("temporaryChatIntroCancelBtn");
const temporaryChatIntroContinueBtn = document.getElementById("temporaryChatIntroContinueBtn");
const TEMPORARY_CHAT_INTRO_SEEN_KEY = "webai_temporary_chat_intro_seen_v3";
let temporaryChatIntroModalState = null;

function dialogUiT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || String(fallback || key || '');
}

function closeDeleteApiKeyModal(confirmed = false){
  const state = deleteApiKeyModalState;
  if(!state || !deleteApiKeyModalEl) return;
  deleteApiKeyModalState = null;
  deleteApiKeyModalEl.classList.remove('open');
  deleteApiKeyModalEl.hidden = true;
  deleteApiKeyModalEl.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  try{ state.resolve(!!confirmed); }catch(_){ }
  try{ state.returnFocusEl?.focus?.(); }catch(_){ }
}

function askDeleteApiKeyConfirm(keyName, returnFocusEl = null){
  const keyLabel = String(keyName || '').trim() || dialogUiT('dialog.current_key', null, '当前 Key');
  const fallbackText = dialogUiT('dialog.delete_key_prompt', {key:keyLabel}, `确定删除当前 Key：${keyLabel}？`);
  if(!deleteApiKeyModalEl || !deleteApiKeyModalDescEl || !deleteApiKeyCancelBtn || !deleteApiKeyConfirmBtn){
    return Promise.resolve(confirm(fallbackText));
  }
  if(deleteApiKeyModalState){
    try{ deleteApiKeyModalState.resolve(false); }catch(_){ }
    deleteApiKeyModalState = null;
  }
  deleteApiKeyModalDescEl.textContent = dialogUiT('dialog.delete_key_desc', {key:keyLabel}, `这将删除当前 Key：${keyLabel}。`);
  deleteApiKeyModalEl.hidden = false;
  deleteApiKeyModalEl.classList.add('open');
  deleteApiKeyModalEl.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  return new Promise((resolve)=>{
    deleteApiKeyModalState = { resolve, returnFocusEl: returnFocusEl || null };
    setTimeout(()=>{ try{ deleteApiKeyConfirmBtn.focus(); }catch(_){ } }, 0);
  });
}

if(deleteApiKeyCancelBtn){
  deleteApiKeyCancelBtn.addEventListener('click', ()=>closeDeleteApiKeyModal(false));
}
if(deleteApiKeyConfirmBtn){
  deleteApiKeyConfirmBtn.addEventListener('click', ()=>closeDeleteApiKeyModal(true));
}
if(deleteApiKeyModalEl){
  deleteApiKeyModalEl.addEventListener('click', (e)=>{
    if(e.target === deleteApiKeyModalEl) closeDeleteApiKeyModal(false);
  });
}

function setKbDangerModalError(message = ''){
  const text = String(message || '').trim();
  if(!kbDangerModalErrorEl) return;
  kbDangerModalErrorEl.hidden = !text;
  kbDangerModalErrorEl.textContent = text;
}

function setKbDangerModalBusy(busy = false, busyText = ''){
  const state = kbDangerModalState || {};
  const isBusy = !!busy;
  if(kbDangerCancelBtn) kbDangerCancelBtn.disabled = isBusy;
  if(kbDangerConfirmBtn){
    kbDangerConfirmBtn.disabled = isBusy;
    kbDangerConfirmBtn.classList.toggle('is-loading', isBusy);
    kbDangerConfirmBtn.textContent = isBusy
      ? (String(busyText || state.busyText || dialogUiT('common.processing', null, '处理中…')).trim() || dialogUiT('common.processing', null, '处理中…'))
      : (String(state.confirmText || dialogUiT('common.confirm', null, '确认')).trim() || dialogUiT('common.confirm', null, '确认'));
  }
  if(state) state.busy = isBusy;
}

function closeKbDangerModal(confirmed = false, options = {}){
  const state = kbDangerModalState;
  if(!state || !kbDangerModalEl) return;
  if(state.busy && !options.force) return;
  kbDangerModalState = null;
  kbDangerModalEl.classList.remove('open', 'is-danger');
  kbDangerModalEl.hidden = true;
  kbDangerModalEl.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  setKbDangerModalError('');
  if(kbDangerCancelBtn) kbDangerCancelBtn.disabled = false;
  if(kbDangerConfirmBtn){
    kbDangerConfirmBtn.disabled = false;
    kbDangerConfirmBtn.classList.remove('danger', 'is-loading');
  }
  try{ state.resolve(!!confirmed); }catch(_){ }
  try{ state.returnFocusEl?.focus?.(); }catch(_){ }
}

function openKbDangerModal({ title = '', desc = '', confirmText = '', cancelText = '', variant = '', busyText = '', errorPrefix = '', onConfirm = null } = {}, returnFocusEl = null){
  const safeTitle = String(title || '').trim() || dialogUiT('dialog.confirm_action', null, '确认操作');
  const safeDesc = String(desc || '').trim();
  const safeConfirm = String(confirmText || dialogUiT('common.confirm', null, '确认')).trim() || dialogUiT('common.confirm', null, '确认');
  const safeCancel = String(cancelText || dialogUiT('common.cancel', null, '取消')).trim() || dialogUiT('common.cancel', null, '取消');
  const isDanger = String(variant || '').trim().toLowerCase() === 'danger';
  if(!kbDangerModalEl || !kbDangerModalTitleEl || !kbDangerModalDescEl || !kbDangerCancelBtn || !kbDangerConfirmBtn){
    return Promise.resolve(confirm(`${safeTitle}
${safeDesc}`.trim()));
  }
  if(kbDangerModalState){
    try{ kbDangerModalState.resolve(false); }catch(_){ }
    kbDangerModalState = null;
  }
  kbDangerModalTitleEl.textContent = safeTitle;
  kbDangerModalDescEl.textContent = safeDesc;
  setKbDangerModalError('');
  kbDangerCancelBtn.disabled = false;
  kbDangerCancelBtn.textContent = safeCancel;
  kbDangerConfirmBtn.disabled = false;
  kbDangerConfirmBtn.classList.remove('danger', 'is-loading');
  kbDangerConfirmBtn.classList.toggle('danger', isDanger);
  kbDangerConfirmBtn.textContent = safeConfirm;
  kbDangerModalEl.classList.toggle('is-danger', isDanger);
  kbDangerModalEl.hidden = false;
  kbDangerModalEl.classList.add('open');
  kbDangerModalEl.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  return new Promise((resolve)=>{
    kbDangerModalState = {
      resolve,
      returnFocusEl: returnFocusEl || null,
      confirmText: safeConfirm,
      cancelText: safeCancel,
      busyText: String(busyText || dialogUiT('common.processing', null, '处理中…')).trim() || dialogUiT('common.processing', null, '处理中…'),
      errorPrefix: String(errorPrefix || '').trim(),
      onConfirm: typeof onConfirm === 'function' ? onConfirm : null,
      busy: false,
    };
    setTimeout(()=>{ try{ kbDangerConfirmBtn.focus(); }catch(_){ } }, 0);
  });
}

function askKbDangerConfirm(options = {}, returnFocusEl = null){
  return openKbDangerModal({ variant:'danger', ...options }, returnFocusEl);
}

function askKbDangerAction(options = {}, action, returnFocusEl = null){
  if(typeof action !== 'function') return askKbDangerConfirm(options, returnFocusEl);
  if(!kbDangerModalEl || !kbDangerModalTitleEl || !kbDangerModalDescEl || !kbDangerCancelBtn || !kbDangerConfirmBtn){
    return (async ()=>{
      const ok = await askKbDangerConfirm(options, returnFocusEl);
      if(!ok) return false;
      await action();
      return true;
    })();
  }
  return openKbDangerModal({
    ...options,
    onConfirm: async () => {
      await action();
    },
  }, returnFocusEl);
}

async function handleKbDangerConfirm(){
  const state = kbDangerModalState;
  if(!state || state.busy) return;
  if(typeof state.onConfirm !== 'function'){
    closeKbDangerModal(true);
    return;
  }
  setKbDangerModalError('');
  setKbDangerModalBusy(true, state.busyText || dialogUiT('common.processing', null, '处理中…'));
  try{
    await state.onConfirm();
    closeKbDangerModal(true, { force:true });
  }catch(err){
    const raw = String(err?.message || err || dialogUiT('common.operation_failed', null, '操作失败')).trim();
    const prefix = state.errorPrefix ? (state.errorPrefix.endsWith('：') ? state.errorPrefix : state.errorPrefix + '：') : '';
    setKbDangerModalError(prefix + raw);
    setKbDangerModalBusy(false);
  }
}

if(kbDangerCancelBtn){
  kbDangerCancelBtn.addEventListener('click', ()=>closeKbDangerModal(false));
}
if(kbDangerConfirmBtn){
  kbDangerConfirmBtn.addEventListener('click', handleKbDangerConfirm);
}
if(kbDangerModalEl){
  kbDangerModalEl.addEventListener('click', (e)=>{
    if(e.target === kbDangerModalEl) closeKbDangerModal(false);
  });
}


function closeSettingsUnsavedExitModal(confirmed = false){
  const state = settingsUnsavedExitState;
  if(!state || !settingsUnsavedExitModalEl) return;
  settingsUnsavedExitState = null;
  settingsUnsavedExitModalEl.classList.remove('open');
  settingsUnsavedExitModalEl.hidden = true;
  settingsUnsavedExitModalEl.setAttribute('aria-hidden', 'true');
  try{ state.resolve(!!confirmed); }catch(_){ }
  try{ state.returnFocusEl?.focus?.(); }catch(_){ }
}

function askSettingsUnsavedExit(returnFocusEl = null){
  if(!settingsUnsavedExitModalEl || !settingsUnsavedReturnBtn || !settingsUnsavedExitBtn){
    return Promise.resolve(confirm(dialogUiT('dialog.unsaved_confirm', null, '确定要退出吗？\n你的更改将不会保存。')));
  }
  if(settingsUnsavedExitState){
    try{ settingsUnsavedExitState.resolve(false); }catch(_){ }
    settingsUnsavedExitState = null;
  }
  settingsUnsavedExitModalEl.hidden = false;
  settingsUnsavedExitModalEl.classList.add('open');
  settingsUnsavedExitModalEl.setAttribute('aria-hidden', 'false');
  return new Promise((resolve)=>{
    settingsUnsavedExitState = { resolve, returnFocusEl: returnFocusEl || null };
    setTimeout(()=>{ try{ settingsUnsavedReturnBtn.focus(); }catch(_){ } }, 0);
  });
}

if(settingsUnsavedReturnBtn){
  settingsUnsavedReturnBtn.addEventListener('click', ()=>closeSettingsUnsavedExitModal(false));
}
if(settingsUnsavedExitBtn){
  settingsUnsavedExitBtn.addEventListener('click', ()=>closeSettingsUnsavedExitModal(true));
}
if(settingsUnsavedExitModalEl){
  settingsUnsavedExitModalEl.addEventListener('click', (e)=>{
    if(e.target === settingsUnsavedExitModalEl) closeSettingsUnsavedExitModal(false);
  });
}

function closeTemporaryChatIntroModal(confirmed = false){
  const state = temporaryChatIntroModalState;
  if(!state || !temporaryChatIntroModalEl) return;
  temporaryChatIntroModalState = null;
  temporaryChatIntroModalEl.classList.remove('open');
  temporaryChatIntroModalEl.hidden = true;
  temporaryChatIntroModalEl.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  if(confirmed){
    try{ localStorage.setItem(TEMPORARY_CHAT_INTRO_SEEN_KEY, '1'); }catch(_){ }
  }
  try{ state.resolve(!!confirmed); }catch(_){ }
  try{ state.returnFocusEl?.focus?.(); }catch(_){ }
}

function askTemporaryChatIntro(returnFocusEl = null){
  try{
    if(localStorage.getItem(TEMPORARY_CHAT_INTRO_SEEN_KEY) === '1') return Promise.resolve(true);
  }catch(_){ }
  if(!temporaryChatIntroModalEl || !temporaryChatIntroCancelBtn || !temporaryChatIntroContinueBtn){
    try{ localStorage.setItem(TEMPORARY_CHAT_INTRO_SEEN_KEY, '1'); }catch(_){ }
    return Promise.resolve(true);
  }
  if(temporaryChatIntroModalState){
    try{ temporaryChatIntroModalState.resolve(false); }catch(_){ }
    temporaryChatIntroModalState = null;
  }
  temporaryChatIntroModalEl.hidden = false;
  temporaryChatIntroModalEl.classList.add('open');
  temporaryChatIntroModalEl.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  return new Promise((resolve)=>{
    temporaryChatIntroModalState = { resolve, returnFocusEl: returnFocusEl || null };
    setTimeout(()=>{ try{ temporaryChatIntroContinueBtn.focus(); }catch(_){ } }, 0);
  });
}

if(temporaryChatIntroCancelBtn){
  temporaryChatIntroCancelBtn.addEventListener('click', ()=>closeTemporaryChatIntroModal(false));
}
if(temporaryChatIntroContinueBtn){
  temporaryChatIntroContinueBtn.addEventListener('click', ()=>closeTemporaryChatIntroModal(true));
}
if(temporaryChatIntroModalEl){
  temporaryChatIntroModalEl.addEventListener('click', (e)=>{
    if(e.target === temporaryChatIntroModalEl) closeTemporaryChatIntroModal(false);
  });
}

function closeDeleteSessionModal(confirmed = false){
  const state = deleteSessionModalState;
  if(!state || !deleteSessionModalEl) return;
  deleteSessionModalState = null;
  deleteSessionModalEl.classList.remove('open');
  deleteSessionModalEl.hidden = true;
  deleteSessionModalEl.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  try{ state.resolve(!!confirmed); }catch(_){ }
  try{ state.returnFocusEl?.focus?.(); }catch(_){ }
}

function askDeleteSessionConfirm(session, returnFocusEl = null){
  const fallbackTitle = String(session?.title || dialogUiT('dialog.new_chat', null, '新对话')).trim() || dialogUiT('dialog.new_chat', null, '新对话');
  const fallbackText = dialogUiT('dialog.delete_chat_desc', {title:fallbackTitle}, `这将删除 ${fallbackTitle}。`);
  if(!deleteSessionModalEl || !deleteSessionModalDescEl || !deleteSessionCancelBtn || !deleteSessionConfirmBtn){
    return Promise.resolve(confirm(fallbackText));
  }
  if(deleteSessionModalState){
    try{ deleteSessionModalState.resolve(false); }catch(_){ }
    deleteSessionModalState = null;
  }
  const sessionTitle = String(session?.title || '').trim() || dialogUiT('dialog.new_chat', null, '新对话');
  deleteSessionModalDescEl.textContent = dialogUiT('dialog.delete_chat_desc', {title:sessionTitle}, `这将删除 ${sessionTitle}。`);
  deleteSessionModalEl.hidden = false;
  deleteSessionModalEl.classList.add('open');
  deleteSessionModalEl.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  return new Promise((resolve)=>{
    deleteSessionModalState = { resolve, returnFocusEl: returnFocusEl || null };
    setTimeout(()=>{ try{ deleteSessionConfirmBtn.focus(); }catch(_){ } }, 0);
  });
}

if(deleteSessionCancelBtn){
  deleteSessionCancelBtn.addEventListener('click', ()=>closeDeleteSessionModal(false));
}
if(deleteSessionConfirmBtn){
  deleteSessionConfirmBtn.addEventListener('click', ()=>closeDeleteSessionModal(true));
}
if(deleteSessionModalEl){
  deleteSessionModalEl.addEventListener('click', (e)=>{
    if(e.target === deleteSessionModalEl) closeDeleteSessionModal(false);
  });
}
document.addEventListener('keydown', (e)=>{
  if(e.key === 'Escape' && deleteSessionModalState){
    e.preventDefault();
    closeDeleteSessionModal(false);
    return;
  }
  if(e.key === 'Escape' && deleteApiKeyModalState){
    e.preventDefault();
    closeDeleteApiKeyModal(false);
    return;
  }
  if(e.key === 'Escape' && kbDangerModalState){
    e.preventDefault();
    closeKbDangerModal(false);
    return;
  }
  if(e.key === 'Escape' && settingsUnsavedExitState){
    e.preventDefault();
    closeSettingsUnsavedExitModal(false);
    return;
  }
  if(e.key === 'Escape' && temporaryChatIntroModalState){
    e.preventDefault();
    closeTemporaryChatIntroModal(false);
    return;
  }
  if(e.key === 'Escape' && document.getElementById('archivedChatsModal')?.classList.contains('open')){
    e.preventDefault();
    setArchivedChatsModalOpen(false);
  }
});

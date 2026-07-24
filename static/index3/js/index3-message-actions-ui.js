/* Message action bar and conversation branch version controls.*/
function messageActionT(key, params, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

class WebaiReadAloudController {
  constructor(){
    this.key = '';
    this.pendingKey = '';
    this.audio = null;
    this.audioUrl = '';
    this.abort = null;
    this.utterance = null;
    this.gestureUtterance = null;
  }

  prepareUserGesture(settings){
    const cfg = settings && typeof settings === 'object' ? settings : {provider:'browser'};
    if(String(cfg.provider || 'browser') !== 'openai_compatible') return;

    // iOS Safari 要求有声音的媒体播放直接由点击触发；先解锁并复用同一个 Audio 实例。
    try{
      const audio = new Audio();
      audio.preload = 'auto';
      audio.loop = true;
      audio.setAttribute('playsinline', '');
      audio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA';
      this.audio = audio;
      const playAttempt = audio.play();
      if(playAttempt && typeof playAttempt.catch === 'function') playAttempt.catch(()=>{});
    }catch(_){ }

    if(!cfg.fallback_browser) return;
    try{
      if(!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance !== 'function') return;
      const unlockUtterance = new SpeechSynthesisUtterance('\u00a0');
      unlockUtterance.lang = 'zh-CN';
      unlockUtterance.volume = 0;
      unlockUtterance.rate = 10;
      unlockUtterance.onend = ()=>{
        if(this.gestureUtterance === unlockUtterance) this.gestureUtterance = null;
      };
      unlockUtterance.onerror = unlockUtterance.onend;
      this.gestureUtterance = unlockUtterance;
      window.speechSynthesis.speak(unlockUtterance);
    }catch(_){ }
  }

  resetButton(btn){
    if(!btn) return;
    btn.disabled = false;
    btn.classList.remove('active', 'is-pending', 'is-read-aloud-locked');
    const label = messageActionT('message.read_aloud', null, 'Read aloud');
    try{ setBubbleActionButtonIcon(btn, 'readaloud', label); }catch(_){ btn.textContent = label; }
  }

  renderPendingButton(btn){
    if(!btn) return;
    btn.textContent = '';
    const spinner = document.createElement('span');
    spinner.className = 'bubble-read-aloud-spinner';
    spinner.setAttribute('aria-hidden', 'true');
    btn.appendChild(spinner);
    const label = messageActionT('message.read_aloud_preparing', null, 'Preparing read aloud');
    btn.setAttribute('aria-label', label);
    btn.title = label;
  }

  syncButton(btn){
    if(!btn) return;
    const locked = !!this.pendingKey;
    const buttonKey = String(btn.dataset.readAloudKey || '');
    const isPendingButton = locked && buttonKey === this.pendingKey;
    if(isPendingButton){
      btn.disabled = true;
      btn.classList.add('is-pending');
      btn.classList.remove('active', 'is-read-aloud-locked');
      if(!btn.querySelector('.bubble-read-aloud-spinner')) this.renderPendingButton(btn);
      return;
    }
    if(locked){
      if(btn.querySelector('.bubble-read-aloud-spinner')) this.resetButton(btn);
      btn.disabled = true;
      btn.classList.remove('active', 'is-pending');
      btn.classList.add('is-read-aloud-locked');
      return;
    }
    if(this.key && buttonKey === this.key){
      btn.disabled = false;
      btn.classList.remove('is-pending', 'is-read-aloud-locked');
      btn.classList.add('active');
      const stopLabel = messageActionT('message.stop_read_aloud', null, 'Stop reading aloud');
      try{ setBubbleActionButtonIcon(btn, 'stop', stopLabel); }catch(_){ btn.textContent = messageActionT('message.stop', null, 'Stop'); }
      return;
    }
    this.resetButton(btn);
  }

  syncPendingButtons(){
    document.querySelectorAll('.bubble-read-aloud-action').forEach(btn=>this.syncButton(btn));
  }

  releaseRemoteMedia({abort=false}={}){
    const ctrl = this.abort;
    const audio = this.audio;
    const audioUrl = this.audioUrl;
    this.abort = null;
    this.audio = null;
    this.audioUrl = '';
    try{ if(abort && ctrl) ctrl.abort(); }catch(_){ }
    try{ if(audio){ audio.onended = null; audio.onerror = null; audio.pause(); audio.currentTime = 0; } }catch(_){ }
    try{ if(audioUrl) URL.revokeObjectURL(audioUrl); }catch(_){ }
  }

  stop(){
    const utterance = this.utterance;
    this.utterance = null;
    this.gestureUtterance = null;
    if(utterance){
      utterance.onstart = null;
      utterance.onend = null;
      utterance.onerror = null;
    }
    try{ if('speechSynthesis' in window) window.speechSynthesis.cancel(); }catch(_){ }
    this.releaseRemoteMedia({abort:true});
    this.key = '';
    this.pendingKey = '';
    document.querySelectorAll('.bubble-read-aloud-action').forEach(btn=>this.resetButton(btn));
  }

  beginPending(key){
    this.pendingKey = String(key || '');
    this.syncPendingButtons();
  }

  setActive(key, btn){
    this.key = String(key || '');
    this.pendingKey = '';
    this.syncPendingButtons();
    if(btn){
      btn.disabled = false;
      btn.classList.remove('is-pending', 'is-read-aloud-locked');
      btn.classList.add('active');
      const stopLabel = messageActionT('message.stop_read_aloud', null, 'Stop reading aloud');
      try{ setBubbleActionButtonIcon(btn, 'stop', stopLabel); }catch(_){ btn.textContent = messageActionT('message.stop', null, 'Stop'); }
    }
  }

  async playBrowser(text, key, btn){
    if(!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance !== 'function'){
      throw new Error(messageActionT('message.read_aloud_unsupported', null, 'This browser does not support system read aloud'));
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.onend = ()=>{ if(this.utterance === utterance) this.stop(); };
    utterance.onerror = (event)=>{
      if(this.utterance !== utterance) return;
      const reason = String(event?.error || '').trim();
      this.stop();
      if(reason && !['canceled', 'interrupted'].includes(reason)){
        try{ toast(messageActionT('message.read_aloud_failed', {error:reason}, `System read aloud failed: ${reason}`)); }catch(_){ }
      }
    };
    this.utterance = utterance;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    this.setActive(key, btn);
  }

  async playBrowserFallback(text, key, btn){
    this.releaseRemoteMedia();
    this.key = '';
    this.beginPending(key);
    await this.playBrowser(text, key, btn);
    try{ toast(messageActionT('message.read_aloud_fallback', null, 'The selected voice is unavailable. Switched to system read aloud.')); }catch(_){ }
  }

  async playRemote(text, key, btn, cfg){
    const apiSettings = (typeof getCurrentApiProfile === 'function') ? getCurrentApiProfile() : {};
    const ctrl = new AbortController();
    this.abort = ctrl;
    const res = await fetch('/api3/read-aloud/speech', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text, read_aloud_settings:cfg, api_settings:apiSettings}),
      signal:ctrl.signal,
    });
    if(!res.ok){
      let message = '';
      try{
        const raw = await res.text();
        try{ message = String(JSON.parse(raw || '{}')?.error || '').trim(); }catch(_){ message = raw.trim(); }
      }catch(_){ }
      throw new Error(message || `Read aloud failed: HTTP ${res.status}`);
    }
    const audioUrl = URL.createObjectURL(await res.blob());
    const audio = this.audio || new Audio();
    try{ audio.pause(); }catch(_){ }
    audio.loop = false;
    audio.preload = 'auto';
    audio.src = audioUrl;
    try{ audio.load(); }catch(_){ }
    this.audioUrl = audioUrl;
    this.audio = audio;
    try{
      await audio.play();
    }catch(err){
      this.releaseRemoteMedia();
      throw err;
    }
    this.abort = null;
    audio.onended = ()=>{ if(this.audio === audio) this.stop(); };
    audio.onerror = async ()=>{
      if(this.audio !== audio) return;
      if(!cfg.fallback_browser){
        this.stop();
        try{ toast(messageActionT('message.read_aloud_playback_failed', null, 'Voice playback failed')); }catch(_){ }
        return;
      }
      try{
        await this.playBrowserFallback(text, key, btn);
      }catch(err){
        this.stop();
        try{ toast(String(err?.message || err || messageActionT('message.read_aloud_fallback_failed', null, 'System read-aloud fallback failed'))); }catch(_){ }
      }
    };
    this.setActive(key, btn);
  }

  async play({text, key, btn, settings}){
    const clean = String(text || '').trim();
    if(!clean) throw new Error(messageActionT('message.read_aloud_empty', null, 'There is no text to read aloud'));
    const cfg = settings && typeof settings === 'object' ? settings : {provider:'browser'};
    if(String(cfg.provider || 'browser') !== 'openai_compatible'){
      await this.playBrowser(clean, key, btn);
      return;
    }
    try{
      await this.playRemote(clean, key, btn, cfg);
    }catch(remoteError){
      if(remoteError?.name === 'AbortError' || !cfg.fallback_browser) throw remoteError;
      await this.playBrowserFallback(clean, key, btn);
    }
  }
}

const webaiReadAloudRuntime = new WebaiReadAloudController();
function stopWebaiReadAloud(){ webaiReadAloudRuntime.stop(); }
function buildBubbleMessageActions(actions, opts={}){
  if(!actions) return actions;
  const role = String(opts?.role || '').toLowerCase();
  const isUser = role === 'user';
  const text = String(opts?.text ?? '');
  const msg = opts?.message || null;
  const msgText = String(opts?.backendText || '').trim() || bubbleMessageTextForComposer(msg || { content:text });
  const activeSessionIdForActions = String(opts?.sessionId || store?.activeId || '').trim();
  const hideAssistantRegenerateAction = !isUser && !!activeSessionIdForActions && isSessionStreamingUiLocked(activeSessionIdForActions);

  if(!opts?.disableCopy){
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'icon-btn bubble-copy';
    const copyLabel = window.AperviaI18n?.t('message.copy') || 'Copy';
    copyBtn.textContent = copyLabel;
    decorateBubbleActionButton(copyBtn, 'copy', copyLabel);
    copyBtn.addEventListener('click', (e)=>{
      e.stopPropagation();
      copyText(msgText || text);
      flashButtonCopied(copyBtn, window.AperviaI18n?.t('message.copied') || 'Copied');
    });
    actions.appendChild(copyBtn);

    if(isUser && messageHasEditableComposerContent(msg || { content: msgText })){
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'icon-btn bubble-copy';
      const editLabel = window.AperviaI18n?.t('message.edit') || 'Edit';
      editBtn.textContent = editLabel;
      decorateBubbleActionButton(editBtn, 'edit', editLabel);
      editBtn.title = window.AperviaI18n?.t('message.edit_title') || 'Edit directly in the conversation';
      editBtn.addEventListener('click', (e)=>{
        e.stopPropagation();
        beginComposerEditMessage(editBtn, opts?.messageIndex, msg || { content: msgText });
      });
      actions.appendChild(editBtn);
    }

    if(!isUser && msgText){
      const likeBtn = document.createElement('button');
      likeBtn.type = 'button';
      likeBtn.className = 'icon-btn bubble-copy';
      likeBtn.textContent = '👍';
      decorateBubbleActionButton(likeBtn, 'like', window.AperviaI18n?.t('message.helpful') || 'This response was helpful');
      likeBtn.title = window.AperviaI18n?.t('message.helpful') || 'This response was helpful';
      likeBtn.addEventListener('click', (e)=>{
        e.stopPropagation();
        flashButtonCopied(likeBtn, window.AperviaI18n?.t('message.recorded') || 'Recorded');
      });
      actions.appendChild(likeBtn);

      const dislikeBtn = document.createElement('button');
      dislikeBtn.type = 'button';
      dislikeBtn.className = 'icon-btn bubble-copy';
      dislikeBtn.textContent = '👎';
      decorateBubbleActionButton(dislikeBtn, 'dislike', window.AperviaI18n?.t('message.improve') || 'This response could be better');
      dislikeBtn.title = window.AperviaI18n?.t('message.improve') || 'This response could be better';
      dislikeBtn.addEventListener('click', (e)=>{
        e.stopPropagation();
        flashButtonCopied(dislikeBtn, window.AperviaI18n?.t('message.recorded') || 'Recorded');
      });
      actions.appendChild(dislikeBtn);

      const readAloudBtn = document.createElement('button');
      readAloudBtn.type = 'button';
      readAloudBtn.className = 'icon-btn bubble-copy bubble-read-aloud-action';
      const readAloudLabel = window.AperviaI18n?.t('message.read_aloud') || 'Read aloud';
      readAloudBtn.textContent = readAloudLabel;
      decorateBubbleActionButton(readAloudBtn, 'readaloud', readAloudLabel);
      const readAloudKey = String(activeSessionIdForActions || '') + ':' + String(opts?.messageIndex ?? 'x');
      readAloudBtn.dataset.readAloudKey = readAloudKey;
      webaiReadAloudRuntime.syncButton(readAloudBtn);
      readAloudBtn.addEventListener('click', async (e)=>{
        e.stopPropagation();
        if(webaiReadAloudRuntime.pendingKey) return;
        if(webaiReadAloudRuntime.key === readAloudKey){ stopWebaiReadAloud(); return; }
        stopWebaiReadAloud();
        try{
          const cfg = (typeof getReadAloudSettings === 'function') ? getReadAloudSettings() : {provider:'browser'};
          webaiReadAloudRuntime.prepareUserGesture(cfg);
          webaiReadAloudRuntime.beginPending(readAloudKey);
          await webaiReadAloudRuntime.play({text:msgText, key:readAloudKey, btn:readAloudBtn, settings:cfg});
        }catch(err){
          stopWebaiReadAloud();
          if(err?.name === 'AbortError') return;
          try{ toast(String(err?.message || err || messageActionT('message.read_aloud_request_failed', null, 'Read aloud failed'))); }catch(_){ }
        }
      });
      actions.appendChild(readAloudBtn);

      if(!hideAssistantRegenerateAction){
        const reuseBtn = document.createElement('button');
        reuseBtn.type = 'button';
        reuseBtn.className = 'icon-btn bubble-copy';
        const continueLabel=messageActionT('message.continue',null,'Continue');
        reuseBtn.textContent=continueLabel;
        decorateBubbleActionButton(reuseBtn,'continue',messageActionT('message.continue_answer',null,'Continue answer'));
        reuseBtn.title=messageActionT('message.continue_title',null,'Continue generating from this response');
        reuseBtn.addEventListener('click', async (e)=>{
          e.stopPropagation();
          await beginContinueAssistantAnswer(reuseBtn, opts?.messageIndex);
        });
        actions.appendChild(reuseBtn);

        const retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'icon-btn bubble-copy bubble-regenerate-action';
        const regenerateLabel=messageActionT('message.regenerate',null,'Regenerate');
        retryBtn.textContent=regenerateLabel;
        decorateBubbleActionButton(retryBtn,'regenerate',regenerateLabel);
        retryBtn.title=messageActionT('message.regenerate_title',null,'Regenerate this response');
        retryBtn.addEventListener('click', async (e)=>{
          e.stopPropagation();
          await beginRegenerateAnswer(retryBtn, opts?.messageIndex);
        });
        actions.appendChild(retryBtn);
      }
    }
  }

  if(!isUser && msg && opts?.messageIndex !== null && opts?.messageIndex !== undefined && Number.isInteger(Number(opts.messageIndex)) && activeSessionIdForActions){
    const shareBtn = document.createElement('button');
    shareBtn.type = 'button';
    shareBtn.className = 'icon-btn bubble-copy bubble-share-action';
    const shareLabel = messageActionT('message.share_through', null, 'Share conversation through this response');
    shareBtn.textContent = shareLabel;
    decorateBubbleActionButton(shareBtn, 'share', shareLabel);
    shareBtn.addEventListener('click', async (e)=>{
      e.stopPropagation();
      if(typeof openChatShareModal === 'function') await openChatShareModal(activeSessionIdForActions, Number(opts.messageIndex), shareBtn);
    });
    actions.appendChild(shareBtn);
  }

  appendWebaiBranchVersionControls(actions, msg || null, isUser ? 'user' : 'assistant', activeSessionIdForActions);
  return actions;
}

function appendWebaiBranchVersionControls(actions, msg, role, sessionId){
  if(!actions || !msg || typeof msg !== 'object') return false;
  const gid = String(msg._webai_conv_branch_id || '').trim();
  if(!gid || msg._webai_conv_branch_control !== true) return false;
  const sidForBranchControls = String(sessionId || store?.activeId || '').trim();
  try{
    if(sidForBranchControls && isSessionStreamingUiLocked(sidForBranchControls)) return false;
  }catch(_){ }
  const session = getActive();
  const group = webaiBranchGroup(session, gid);
  const versions = Array.isArray(group?.versions) ? group.versions : [];
  if(!group || versions.length <= 1) return false;
  const active = Math.max(0, Math.min(versions.length - 1, Number(group.active || 0) || 0));
  const expectedRole = webaiBranchControlRoleForKind(group.kind);
  if(String(role || '').toLowerCase() !== expectedRole) return false;
  const wrap = document.createElement('span');
  wrap.className = 'bubble-version-controls';
  wrap.dataset.webaiBranchControl = '1';
  wrap.dataset.sessionId = String(session?.id || sessionId || store?.activeId || '').trim();
  wrap.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-left:2px;vertical-align:middle;';
  const mkBtn = (label, dir)=>{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn bubble-copy bubble-version-btn';
    btn.textContent = label;
    btn.title=messageActionT(dir<0?'message.previous_version':'message.next_version',null,dir<0?'Previous version':'Next version');
    btn.disabled = dir < 0 ? active <= 0 : active >= versions.length - 1;
    btn.style.cssText = 'min-width:24px;padding:2px 6px;';
    btn.addEventListener('click', async (e)=>{
      e.preventDefault();
      e.stopPropagation();
      const sid = String(session?.id || sessionId || store?.activeId || '').trim();
      try{
        if(sid && isSessionStreamingUiLocked(sid)){
          try{ toast(messageActionT('message.branch_busy', null, 'Wait for generation to finish before switching response versions.')); }catch(_){ }
          return;
        }
      }catch(_){ }
      await webaiBranchSwitchVersion(sid || store?.activeId, gid, active + dir);
    });
    return btn;
  };
  const label = document.createElement('span');
  label.className = 'bubble-version-label';
  label.textContent = `${active + 1} / ${versions.length}`;
  label.style.cssText = 'font-size:12px;color:var(--muted);font-weight:700;white-space:nowrap;';
  wrap.appendChild(mkBtn('‹', -1));
  wrap.appendChild(label);
  wrap.appendChild(mkBtn('›', 1));
  actions.appendChild(wrap);
  return true;
}

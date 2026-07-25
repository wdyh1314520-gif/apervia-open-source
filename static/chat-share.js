(()=>{
  const token = decodeURIComponent(String(location.pathname || '').split('/').filter(Boolean).pop() || '');
  const titleEl = document.getElementById('shareTitle');
  const metaEl = document.getElementById('shareMeta');
  const messagesEl = document.getElementById('shareMessages');
  const errorEl = document.getElementById('shareError');
  const continueBtn = document.getElementById('shareContinueBtn');
  const shareT = (key, params, fallback='')=>window.AperviaI18n?.t(key, params, fallback) || fallback || key;
  const defaultConversationTitle = (value)=>{
    const raw = String(value || '').trim();
    if(!raw || ['New chat', 'New conversation', '新会话', '新对话'].includes(raw)){
      return shareT('nav.new_session', null, 'New conversation');
    }
    return raw;
  };
  const showError = (message)=>{
    titleEl.textContent = shareT('share.open_failed', null, 'Unable to open shared conversation');
    errorEl.textContent = String(message || shareT('share.not_found', null, 'The shared conversation does not exist or has expired.'));
    errorEl.hidden = false;
  };
  fetch('/api3/chat-shares/' + encodeURIComponent(token), { cache:'no-store' })
    .then(async (res)=>{
      const data = await res.json().catch(()=>({}));
      if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
      return data;
    })
    .then((data)=>{
      const displayTitle = defaultConversationTitle(data.title || shareT('share.chat_fallback', null, 'Shared conversation'));
      document.title = `${displayTitle} · Apervia`;
      titleEl.textContent = displayTitle;
      metaEl.textContent = [data.scope === 'message'
        ? shareT('share.scope_message', null, 'Single message')
        : shareT('share.scope_snapshot', null, 'Conversation snapshot'), data.model || ''].filter(Boolean).join(' · ');
      messagesEl.replaceChildren();
      for(const item of (Array.isArray(data.messages) ? data.messages : [])){
        const article = document.createElement('article');
        article.className = `share-message ${item.role === 'user' ? 'user' : 'assistant'}`;
        const content = document.createElement('div');
        content.className = `share-content message-content${item.role === 'assistant' ? ' share-markdown' : ''}`;
        if(item.role === 'assistant' && typeof window.renderChatShareMarkdown === 'function') content.innerHTML = window.renderChatShareMarkdown(item.content || '');
        else content.textContent = String(item.content || '');
        article.appendChild(content);
        messagesEl.appendChild(article);
      }
    })
    .catch((err)=>showError(err?.message || err));

  continueBtn?.addEventListener('click', async ()=>{
    if(!token || continueBtn.disabled) return;
    continueBtn.disabled = true;
    const oldText = continueBtn.textContent;
    continueBtn.textContent = shareT('share.creating_short', null, 'Creating…');
    try{
      const res = await fetch('/api3/chat-shares/' + encodeURIComponent(token) + '/continue', {
        method:'POST',
        credentials:'same-origin',
        headers:{ 'Content-Type':'application/json' },
        body:'{}',
      });
      const data = await res.json().catch(()=>({}));
      if(res.status === 401 || data?.login_required){
        const login = new URL('/login', location.origin);
        login.searchParams.set('next', location.pathname);
        login.searchParams.set('message', shareT('share.login_required', null, 'Sign in to copy the shared content into an independent conversation.'));
        location.assign(login.pathname + login.search);
        return;
      }
      if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
      location.assign(String(data.url || ('/c/' + data.session_id)));
    }catch(err){
      showError(err?.message || err || shareT('share.create_failed', null, 'Unable to create the independent conversation'));
      continueBtn.disabled = false;
      continueBtn.textContent = oldText || shareT('share.continue_action', null, 'Continue conversation');
    }
  });
})();

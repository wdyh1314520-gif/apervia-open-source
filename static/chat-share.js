(()=>{
  const token = decodeURIComponent(String(location.pathname || '').split('/').filter(Boolean).pop() || '');
  const titleEl = document.getElementById('shareTitle');
  const metaEl = document.getElementById('shareMeta');
  const messagesEl = document.getElementById('shareMessages');
  const errorEl = document.getElementById('shareError');
  const continueBtn = document.getElementById('shareContinueBtn');
  const showError = (message)=>{
    titleEl.textContent = '无法打开分享内容';
    errorEl.textContent = String(message || '分享内容不存在或已失效');
    errorEl.hidden = false;
  };
  fetch('/api3/chat-shares/' + encodeURIComponent(token), { cache:'no-store' })
    .then(async (res)=>{
      const data = await res.json().catch(()=>({}));
      if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
      return data;
    })
    .then((data)=>{
  document.title = `${data.title || '分享的聊天'} · Apervia`;
      titleEl.textContent = data.title || '分享的聊天';
      metaEl.textContent = [data.scope === 'message' ? '单条消息' : '聊天快照', data.model || ''].filter(Boolean).join(' · ');
      messagesEl.replaceChildren();
      for(const item of (Array.isArray(data.messages) ? data.messages : [])){
        const article = document.createElement('article');
        article.className = `share-message ${item.role === 'user' ? 'user' : 'assistant'}`;
        const content = document.createElement('div');
        content.className = `share-content${item.role === 'assistant' ? ' share-markdown' : ''}`;
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
    continueBtn.textContent = '正在创建…';
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
        login.searchParams.set('message', '登录后即可把分享内容复制为你的独立聊天。');
        location.assign(login.pathname + login.search);
        return;
      }
      if(!res.ok) throw new Error(data?.error || ('HTTP ' + res.status));
      location.assign(String(data.url || ('/c/' + data.session_id)));
    }catch(err){
      showError(err?.message || err || '创建会话失败');
      continueBtn.disabled = false;
      continueBtn.textContent = oldText || '继续对话';
    }
  });
})();

/* Main composer/chat event binding.*/

(function bindMainComposerAndChatEvents(){
  composerEditCancelEl?.addEventListener("click", ()=>{
    clearComposerEditState();
    inputEl?.focus?.();
  });

  inputEl?.addEventListener("focus", ()=>{
    if(inlineMessageEditState) clearInlineMessageEditState({ render:true });
  });

  composerInputShellEl?.addEventListener("pointerdown", ()=>{
    if(inlineMessageEditState) clearInlineMessageEditState({ render:true });
  }, true);

  composerInputShellEl?.addEventListener("click", (event)=>{
    const target = event.target instanceof Element ? event.target : null;
    if(!target || target === inputEl) return;
    if(target.closest('button,input,textarea,select,a,[role="menu"],.composer-add-menu')) return;
    try{ inputEl?.focus?.({ preventScroll:true }); }catch(_){ try{ inputEl?.focus?.(); }catch(__){ } }
  });

  stopBtn?.addEventListener("click", async ()=>{
    const activeId = store?.activeId;
    if(activeId && isSessionStreaming(activeId)){
      setStatus("停止中…");
      await stopStreamingForAction("manual_stop", activeId);
    }
  });

  setSendButtonMode(isSessionStreaming(store?.activeId) ? "streaming" : "idle");
  sendBtn?.addEventListener("click", async ()=>{
    if(sendBtn?.dataset?.mode === "stop" && isSessionStreaming(store?.activeId)){
      const activeId = store?.activeId;
      if(activeId){
        setStatus("停止中…");
        await stopStreamingForAction("manual_stop", activeId);
      }
      return;
    }
    send();
  });

  scrollBottomBtn?.addEventListener("click", ()=>{
    shouldAutoStickBottom = true;
    scrollChatToBottom(true);
  });

  chatEl?.addEventListener("scroll", ()=>{
    shouldAutoStickBottom = isNearBottom(120);
    if(visibleChatSessionId) saveCurrentChatScrollState(visibleChatSessionId);
    scrollChatToBottom(false);
  });

  window.addEventListener("resize", ()=>{
    requestAnimationFrame(updateHomeEmptyComposerLayout);
  });

  try{
    window.addEventListener('online', ()=>triggerStableForegroundRecovery('online'));
    window.addEventListener('focus', ()=>triggerStableForegroundRecovery('focus'));
    document.addEventListener('visibilitychange', ()=>{
      if(document.visibilityState === 'visible') triggerStableForegroundRecovery('visible');
    });
  }catch(_){ }

  window.addEventListener('pagehide', ()=>{ handlePageExitPersistence(); });
  window.addEventListener('beforeunload', ()=>{ handlePageExitPersistence(); });
  window.addEventListener('online', ()=>{
    try{ ensureAccountRealtimeSync('online'); }catch(_){ }
    try{ pullAccountRealtimeGap('online').catch(()=>{}); }catch(_){ }
    restorePendingCloudSyncForScope(currentAccountEmail, {
      reason:'online_resume',
      delayMs:400,
    });
    refreshCloudStoreIfChanged();
    maybeResumeSessionJob(store?.activeId, { force:true });
  });

  window.addEventListener('focus', ()=>{
    try{ ensureAccountRealtimeSync('focus'); }catch(_){ }
    try{ pullAccountRealtimeGap('focus').catch(()=>{}); }catch(_){ }
    restorePendingCloudSyncForScope(currentAccountEmail, {
      reason:'focus_resume',
      delayMs:400,
    });
    refreshCloudStoreIfChanged();
  });

  window.addEventListener('pageshow', ()=>{
    refreshAccountUi();
    try{ ensureAccountRealtimeSync('pageshow'); }catch(_){ }
    try{ pullAccountRealtimeGap('pageshow').catch(()=>{}); }catch(_){ }
    restorePendingCloudSyncForScope(currentAccountEmail, {
      reason:'pageshow_resume',
      delayMs:500,
    });
    refreshCloudStoreIfChanged();
    maybeResumeSessionJob(store?.activeId, { force:true });
  });

  document.addEventListener('visibilitychange', ()=>{
    if(document.visibilityState === 'visible'){
      refreshAccountUi();
      try{ ensureAccountRealtimeSync('visible'); }catch(_){ }
      try{ pullAccountRealtimeGap('visible').catch(()=>{}); }catch(_){ }
      restorePendingCloudSyncForScope(currentAccountEmail, {
        reason:'visible_resume',
        delayMs:500,
      });
      refreshCloudStoreIfChanged();
      maybeResumeSessionJob(store?.activeId, { force:true });
    }else{
      try{ stopAccountRealtimeSync('hidden'); }catch(_){ }
      try{ persistStreamingDraftsToStore({ immediate:false }); }catch(_){ }
      try{ flushPendingStoreWrites({ cloud:true, keepalive:true, reason:'hidden_persist' }); }catch(_){ }
    }
  });

  setInterval(()=>{
    if(document.visibilityState === 'visible'){
      refreshAccountUi();
      if(hasLocalRuntimeActivityForCloudRefresh()){
        try{ persistStreamingDraftsToStore({ immediate:false }); }catch(_){ }
        return;
      }
      restorePendingCloudSyncForScope(currentAccountEmail, {
        reason:'heartbeat_resume',
        delayMs:600,
      });
      try{ ensureAccountRealtimeSync('heartbeat'); }catch(_){ }
      refreshCloudStoreIfChanged();
    }
  }, 12000);
})();

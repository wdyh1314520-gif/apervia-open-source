/* Mobile shell/sidebar UI split from index3.js. */

const MOBILE_BP = 900;
const isMobileViewport = () => window.innerWidth <= MOBILE_BP;

function closeMobileSidebarAfterNavigation(){
  if(!isMobileViewport() || typeof applySidebarCollapsed !== 'function') return false;
  applySidebarCollapsed(true, false);
  return true;
}
window.closeMobileSidebarAfterNavigation = closeMobileSidebarAfterNavigation;

(function initMobileSidebarUI(){
  let wasMobileViewport = isMobileViewport();
  const backdrop = document.createElement('div');
  backdrop.className = 'mobile-sidebar-backdrop';
  document.body.appendChild(backdrop);

  function refreshMobileSidebarState({forceClose = false, restoreDesktop = false} = {}){
    const isMobile = isMobileViewport();
    document.body.classList.toggle('is-mobile', isMobile);
    if(isMobile){
      if(forceClose || !document.body.classList.contains('sidebar-collapsed')){
        applySidebarCollapsed(true, false);
      }
      document.body.classList.toggle('mobile-sidebar-open', !document.body.classList.contains('sidebar-collapsed'));
    }else{
      document.body.classList.remove('mobile-sidebar-open');
      if(restoreDesktop){
        const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
        applySidebarCollapsed(saved === '1');
      }
    }
  }

  const rawApplySidebarCollapsed = applySidebarCollapsed;
  applySidebarCollapsed = function(collapsed, persist = true){
    rawApplySidebarCollapsed(collapsed, persist);
    if(isMobileViewport()){
      document.body.classList.toggle('mobile-sidebar-open', !document.body.classList.contains('sidebar-collapsed'));
    }else{
      document.body.classList.remove('mobile-sidebar-open');
    }
  };

  backdrop.addEventListener('click', ()=>{
    if(isMobileViewport()) applySidebarCollapsed(true, false);
  });

  window.addEventListener('resize', ()=>{
    const nowMobile = isMobileViewport();
    if(nowMobile && !wasMobileViewport){
      refreshMobileSidebarState({forceClose:true});
    }else if(!nowMobile && wasMobileViewport){
      refreshMobileSidebarState({restoreDesktop:true});
    }else if(nowMobile){
      document.body.classList.toggle('mobile-sidebar-open', !document.body.classList.contains('sidebar-collapsed'));
    }
    wasMobileViewport = nowMobile;
  });

  if(chatListEl){
    chatListEl.addEventListener('click', (event)=>{
      if(!isMobileViewport()) return;
      if(event.target.closest('.item')){
        closeMobileSidebarAfterNavigation();
      }
    });
  }

  if(newChatBtn){
    newChatBtn.addEventListener('click', ()=>{
      closeMobileSidebarAfterNavigation();
    });
  }

  refreshMobileSidebarState({forceClose:isMobileViewport()});
})();



(function enhanceMobileUiOnce(){
  const mainEl = document.getElementById('main');
  const inputElMobile = document.getElementById('input');
  const settingsModalEl = document.getElementById('settingsModal');
  const openSettingsBtnEl = document.getElementById('openSettingsSidebar') || document.getElementById('openSettingsBtn');
  const topbarSecondaryWrapEl = document.getElementById('topbarSecondaryWrap');
  const topbarSecondaryBtnEl = document.getElementById('topbarSecondaryBtn');

  function syncVisualViewportVar(){
    const vv = window.visualViewport;
    const height = Math.round((vv && vv.height) || window.innerHeight || 0);
    if(height > 0){
      document.documentElement.style.setProperty('--vvh', `${height}px`);
    }
    const layoutHeight = Math.round(window.innerHeight || document.documentElement.clientHeight || 0);
    const offsetTop = Math.round((vv && vv.offsetTop) || 0);
    const keyboardInset = Math.max(0, layoutHeight - height - offsetTop);
    document.documentElement.style.setProperty('--settings-keyboard-inset', `${keyboardInset}px`);
  }

  let settingsFocusScrollTimer = 0;
  function isSettingsFormControl(el){
    if(!(el instanceof HTMLElement)) return false;
    if(!settingsModalEl?.contains(el)) return false;
    if(el.matches('textarea,select')) return true;
    if(!el.matches('input')) return false;
    const type = String(el.getAttribute('type') || 'text').toLowerCase();
    return !['checkbox','radio','range','file','hidden','button','submit','reset'].includes(type);
  }

  function keepSettingsFocusVisible(){
    if(!isMobileViewport()) return;
    if(!settingsModalEl?.classList.contains('open')) return;
    const target = document.activeElement;
    if(!isSettingsFormControl(target)) return;
    window.clearTimeout(settingsFocusScrollTimer);
    settingsFocusScrollTimer = window.setTimeout(() => {
      try{
        const scroller = target.closest('.settings-tab-panel.active');
        const scrollTarget = scroller || target;
        if(scroller){
          const scrollerRect = scroller.getBoundingClientRect();
          const targetRect = target.getBoundingClientRect();
          const topGap = targetRect.top - scrollerRect.top;
          const bottomGap = scrollerRect.bottom - targetRect.bottom;
          if(topGap < 18 || bottomGap < 120){
            scroller.scrollBy({
              top: topGap < 18 ? topGap - 18 : 120 - bottomGap,
              behavior:'smooth',
            });
          }
          return;
        }
        scrollTarget.scrollIntoView({ block:'nearest', inline:'nearest', behavior:'smooth' });
      }catch(_){
        try{ target.scrollIntoView(false); }catch(__){ }
      }
    }, 80);
  }

  syncVisualViewportVar();
  window.addEventListener('resize', syncVisualViewportVar, {passive:true});
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize', () => {
      syncVisualViewportVar();
      keepSettingsFocusVisible();
    }, {passive:true});
  }

  mainEl?.addEventListener('pointerdown', (event) => {
    if(!isMobileViewport()) return;
    if(!document.body.classList.contains('mobile-sidebar-open')) return;
    if(event.target.closest('.sidebar')) return;
    closeMobileSidebarAfterNavigation();
  }, {passive:true});

  inputElMobile?.addEventListener('focus', () => {
    closeMobileSidebarAfterNavigation();
  });

  settingsModalEl?.addEventListener('focusin', (event) => {
    if(isSettingsFormControl(event.target)) keepSettingsFocusVisible();
  });

  openSettingsBtnEl?.addEventListener('click', () => {
    closeMobileSidebarAfterNavigation();
  });

  document.addEventListener('keydown', (event) => {
    if(event.key !== 'Escape') return;
    closeMobileSidebarAfterNavigation();
    if(topbarSecondaryWrapEl?.classList.contains('open')){
      topbarSecondaryWrapEl.classList.remove('open');
      topbarSecondaryBtnEl?.setAttribute('aria-expanded', 'false');
    }
  });

  if(settingsModalEl){
    const observer = new MutationObserver(() => {
      if(settingsModalEl.classList.contains('open') && isMobileViewport()){
        closeMobileSidebarAfterNavigation();
      }
    });
    observer.observe(settingsModalEl, {attributes:true, attributeFilter:['class']});
  }
})();

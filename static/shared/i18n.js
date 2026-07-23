(function(global){
  'use strict';

  const SUPPORTED = new Set(['en', 'zh-CN']);
  const STORAGE_KEY = 'apervia_ui_language_v1';

  class AperviaI18nService {
    constructor(){
      this.resources = new Map();
      this.phraseResources = new Map();
      this.originalText = new WeakMap();
      this.originalAttributes = new WeakMap();
      this.language = this.normalize(this.readStoredLanguage()) || 'en';
      this.observer = null;
    }

    normalize(value){
      const raw = String(value || '').trim().replace(/_/g, '-').toLowerCase();
      if(raw === 'en' || raw.startsWith('en-')) return 'en';
      if(raw === 'zh' || raw === 'zh-cn' || raw === 'zh-hans' || raw === 'zh-sg') return 'zh-CN';
      return '';
    }

    readStoredLanguage(){
      try{ return global.localStorage?.getItem(STORAGE_KEY) || ''; }catch(_){ return ''; }
    }

    register(language, messages){
      const normalized = this.normalize(language);
      if(!normalized || !messages || typeof messages !== 'object') return;
      this.resources.set(normalized, Object.freeze({...messages}));
    }

    registerPhrases(language, phrases){
      const normalized = this.normalize(language);
      if(!normalized || !phrases || typeof phrases !== 'object') return;
      this.phraseResources.set(normalized, Object.freeze({...phrases}));
    }

    phrase(value){
      const raw = String(value ?? '');
      const clean = raw.trim();
      if(!clean) return raw;
      const translated = (this.phraseResources.get(this.language) || {})[clean];
      if(translated === undefined) return raw;
      const leading = raw.match(/^\s*/)?.[0] || '';
      const trailing = raw.match(/\s*$/)?.[0] || '';
      return leading + String(translated) + trailing;
    }

    applyPhrases(root){
      const scope = root && root.nodeType ? root : document;
      const skipElement = (element) => element?.closest?.('script,style,code,pre,.bubble,.message-content,[data-message-id],.markdown-body');
      const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
      const textNodes = [];
      while(walker.nextNode()) textNodes.push(walker.currentNode);
      textNodes.forEach((node) => {
        if(skipElement(node.parentElement)) return;
        const current = node.nodeValue || '';
        let record = this.originalText.get(node);
        if(!record || current !== record.rendered) record = {source:current, rendered:current};
        const rendered = this.language === 'zh-CN' ? record.source : this.phrase(record.source);
        record.rendered = rendered;
        this.originalText.set(node, record);
        if(current !== rendered) node.nodeValue = rendered;
      });
      const attributes = ['placeholder','title','aria-label','data-settings-title','data-tooltip'];
      const elements = [];
      if(scope.nodeType === 1) elements.push(scope);
      if(scope.querySelectorAll) elements.push(...scope.querySelectorAll('*'));
      elements.forEach((element) => {
        if(skipElement(element)) return;
        let originals = this.originalAttributes.get(element);
        if(!originals){ originals = {}; this.originalAttributes.set(element, originals); }
        attributes.forEach((attribute) => {
          if(!element.hasAttribute?.(attribute)) return;
          const current = element.getAttribute(attribute) || '';
          let record = originals[attribute];
          if(!record || current !== record.rendered) record = {source:current, rendered:current};
          const rendered = this.language === 'zh-CN' ? record.source : this.phrase(record.source);
          record.rendered = rendered;
          originals[attribute] = record;
          if(current !== rendered) element.setAttribute(attribute, rendered);
        });
      });
    }

    t(key, params, fallback){
      const messages = this.resources.get(this.language) || {};
      const english = this.resources.get('en') || {};
      let value = messages[key];
      if(value === undefined) value = english[key];
      if(value === undefined) value = fallback === undefined ? key : fallback;
      return String(value).replace(/\{([A-Za-z0-9_]+)\}/g, (_match, name) => {
        const replacement = params && Object.prototype.hasOwnProperty.call(params, name) ? params[name] : '';
        return String(replacement ?? '');
      });
    }

    apply(root){
      const scope = root && root.querySelectorAll ? root : document;
      const nodes = [];
      if(scope.nodeType === 1 && scope.matches?.('[data-i18n]')) nodes.push(scope);
      nodes.push(...scope.querySelectorAll('[data-i18n]'));
      nodes.forEach((element) => {
        const key = element.getAttribute('data-i18n');
        if(key) element.textContent = this.t(key, null, element.textContent);
      });
      const attributes = ['placeholder', 'title', 'aria-label'];
      attributes.forEach((attribute) => {
        const marker = `data-i18n-${attribute}`;
        const targets = [];
        if(scope.nodeType === 1 && scope.hasAttribute?.(marker)) targets.push(scope);
        targets.push(...scope.querySelectorAll(`[${marker}]`));
        targets.forEach((element) => {
          const key = element.getAttribute(marker);
          if(key) element.setAttribute(attribute, this.t(key, null, element.getAttribute(attribute) || ''));
        });
      });
      const settingsTitleTargets = [];
      if(scope.nodeType === 1 && scope.hasAttribute?.('data-i18n-settings-title')) settingsTitleTargets.push(scope);
      settingsTitleTargets.push(...scope.querySelectorAll('[data-i18n-settings-title]'));
      settingsTitleTargets.forEach((element) => {
        const key = element.getAttribute('data-i18n-settings-title');
        if(key) element.setAttribute('data-settings-title', this.t(key, null, element.getAttribute('data-settings-title') || ''));
      });
      this.applyPhrases(scope);
    }

    setLanguage(language, options={}){
      const normalized = this.normalize(language);
      if(!SUPPORTED.has(normalized)) throw new Error('Unsupported interface language');
      const changed = normalized !== this.language;
      this.language = normalized;
      try{ global.localStorage?.setItem(STORAGE_KEY, normalized); }catch(_){ }
      document.documentElement.lang = normalized;
      this.apply(document);
      if(changed){
        document.dispatchEvent(new CustomEvent('apervia:languagechange', {detail:{language:normalized}}));
      }
      if(options.persistAccount === true) return this.persistAccountLanguage(normalized);
      return Promise.resolve({ok:true, language:normalized});
    }

    async persistAccountLanguage(language){
      const response = await fetch('/api3/auth/ui-language', {
        method:'POST',
        cache:'no-store',
        credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({language}),
      });
      const data = await response.json().catch(() => ({}));
      if(!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
      return data;
    }

    async syncFromAccount(){
      const response = await fetch('/api3/auth/profile', {cache:'no-store', credentials:'same-origin'});
      if(!response.ok) return null;
      const data = await response.json().catch(() => ({}));
      const language = this.normalize(data?.profile?.ui_language);
      if(language) await this.setLanguage(language);
      return data;
    }

    start(options={}){
      const ready = () => {
        document.documentElement.lang = this.language;
        this.apply(document);
        if(!this.observer && document.body){
          this.observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
              if(mutation.type === 'childList') mutation.addedNodes.forEach((node) => {
                if(node.nodeType === 1) this.apply(node);
                else if(node.nodeType === 3 && node.parentElement) this.applyPhrases(node.parentElement);
              });
              else if(mutation.type === 'characterData' && mutation.target.parentElement){
                this.applyPhrases(mutation.target.parentElement);
              }else if(mutation.type === 'attributes'){
                this.applyPhrases(mutation.target);
              }
            });
          });
          this.observer.observe(document.body, {
            childList:true,
            subtree:true,
            characterData:true,
            attributes:true,
            attributeFilter:['placeholder','title','aria-label','data-tooltip'],
          });
        }
        if(options.syncAccount === true) this.syncFromAccount().catch(() => null);
      };
      if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once:true});
      else ready();
      return this;
    }
  }

  global.AperviaI18n = new AperviaI18nService();
})(window);

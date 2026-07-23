(function initAppLoadingUi(global){
  'use strict';

  class AppLoadingUi {
    static escapeHtml(value){
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    static normalizeOptions(options={}){
      const variant = String(options.variant || 'list').trim().toLowerCase().replace(/[^a-z0-9-]/g, '') || 'list';
      const rows = Math.max(1, Math.min(8, Number(options.rows || 3) || 3));
      const label = String(options.label || '正在加载').trim() || '正在加载';
      return { variant, rows, label };
    }

    static rowMarkup(variant, index){
      if(variant === 'activity' || variant === 'activity-detail'){
        return `<div class="ui-loading-skeleton-row" data-skeleton-row="${index + 1}"><span class="ui-loading-skeleton-marker"></span><span class="ui-loading-skeleton-copy"><span class="ui-loading-skeleton-line ui-loading-skeleton-line-title"></span><span class="ui-loading-skeleton-line ui-loading-skeleton-line-detail"></span></span></div>`;
      }
      if(variant === 'chat'){
        return `<div class="ui-loading-chat-row${index % 2 ? ' is-user' : ''}" data-skeleton-row="${index + 1}"><span class="ui-loading-skeleton-line ui-loading-skeleton-line-title"></span><span class="ui-loading-skeleton-line ui-loading-skeleton-line-detail"></span><span class="ui-loading-skeleton-line ui-loading-skeleton-line-short"></span></div>`;
      }
      if(variant === 'image'){
        return `<div class="ui-loading-image" data-skeleton-row="${index + 1}"></div>`;
      }
      return `<div class="ui-loading-skeleton-row" data-skeleton-row="${index + 1}"><span class="ui-loading-skeleton-thumb"></span><span class="ui-loading-skeleton-copy"><span class="ui-loading-skeleton-line ui-loading-skeleton-line-title"></span><span class="ui-loading-skeleton-line ui-loading-skeleton-line-detail"></span></span><span class="ui-loading-skeleton-action"></span></div>`;
    }

    static html(options={}){
      const opts = this.normalizeOptions(options);
      const rows = Array.from({ length:opts.rows }, (_, index)=>this.rowMarkup(opts.variant, index)).join('');
      return `<div class="ui-loading-skeleton ui-loading-skeleton--${opts.variant}" role="status" aria-label="${this.escapeHtml(opts.label)}"><span class="ui-loading-sr-only">${this.escapeHtml(opts.label)}</span>${rows}</div>`;
    }

    static create(options={}){
      if(typeof document === 'undefined' || typeof document.createElement !== 'function') return null;
      const host = document.createElement('div');
      host.innerHTML = this.html(options);
      return host.firstElementChild || null;
    }

    static render(container, options={}){
      if(!container) return null;
      container.setAttribute?.('aria-busy', 'true');
      if(container.dataset) container.dataset.loadingState = 'skeleton';
      container.innerHTML = this.html(options);
      return container.firstElementChild || null;
    }

    static ready(container){
      if(!container) return;
      container.removeAttribute?.('aria-busy');
      if(container.dataset) delete container.dataset.loadingState;
    }
  }

  global.AppLoadingUi = AppLoadingUi;
})(typeof window !== 'undefined' ? window : globalThis);

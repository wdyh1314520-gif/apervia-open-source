/* Knowledge base and upload file-library UI.*/
(function initKnowledgeBaseUi(){
  const KB_UI_STORAGE_PREFIX = 'webai_kb_ui_v1_';
  const KB_UI_DEFAULTS = { chatUseKnowledgeBase:true, activeSpaceId:'', activeDocId:'', docFilter:'', docSort:'updated_desc', libraryTab:'files', fileFilter:'', fileType:'all', fileSort:'updated_desc' };
  const KB_IMAGE_EXTENSIONS = new Set(['png','jpg','jpeg','webp','gif','bmp','svg','tif','tiff','ico','jfif','heic','heif']);
  const kbRuntime = { state:null, search:null, loaded:false, loading:false, searching:false, fileLibrary:null };
  const FILE_LIBRARY_PAGE_SIZE = 30;
  const fileLibrarySelectedIds = new Set();
  let fileLibraryFilterTimer = null;
  let fileLibraryLoadingMore = false;
  let fileLibraryActionBusy = false;
  let kbImportDialogMode = 'text';
  let kbDirectoryImportMode = 'folder';

  function kbT(key, params, fallback=''){
    return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
  }

  function kbCountLabel(kind, count){
    const value = Math.max(0, Number(count || 0) || 0);
    const form = value === 1 ? 'one' : 'other';
    const fallback = kind === 'documents' ? `${value} 个文档` : `${value} 个片段`;
    return kbT(`library.kb.${kind}.${form}`, {count:value}, fallback);
  }

  function kbDisplaySpaceName(space, fallbackKey='library.kb.fallback_name'){
    const source = space && typeof space === 'object' ? space : {};
    const raw = String(source.name || '').trim();
    if(source.is_default === true || raw === '默认知识库' || raw === 'Default knowledge base'){
      return kbT('library.kb.default_name', null, '默认知识库');
    }
    if(raw) return raw;
    return kbT(fallbackKey, null, fallbackKey === 'library.kb.untitled_name' ? '未命名知识库' : '知识库');
  }

  function kbScopeKey(){
    try{
      const email = String(window.currentAccountEmail || 'local').trim().toLowerCase() || 'local';
      return KB_UI_STORAGE_PREFIX + email;
    }catch(_){
      return KB_UI_STORAGE_PREFIX + 'local';
    }
  }

  window.getKnowledgeBaseUiSettings = function getKnowledgeBaseUiSettings(){
    try{
      const raw = JSON.parse(localStorage.getItem(kbScopeKey()) || '{}');
      return { ...KB_UI_DEFAULTS, ...(raw && typeof raw === 'object' ? raw : {}) };
    }catch(_){
      return { ...KB_UI_DEFAULTS };
    }
  };

  function saveKnowledgeBaseUiSettings(next){
    const merged = { ...KB_UI_DEFAULTS, ...(next && typeof next === 'object' ? next : {}) };
    localStorage.setItem(kbScopeKey(), JSON.stringify(merged));
    return merged;
  }

  function kbNormalizeActiveDocId(docs, requestedDocId=''){
    const items = Array.isArray(docs) ? docs : [];
    const wanted = String(requestedDocId || '').trim();
    if(wanted && items.some(doc => String(doc?.id || '').trim() === wanted)) return wanted;
    if(items.length === 1) return String(items[0]?.id || '').trim();
    return '';
  }

  function kbResolveActiveDoc(state, ui){
    const docs = Array.isArray(state?.documents) ? state.documents : [];
    const docId = kbNormalizeActiveDocId(docs, ui?.activeDocId || '');
    if(!docId) return null;
    return docs.find(doc => String(doc?.id || '').trim() === docId) || null;
  }

  function kbUiIcon(kind='empty'){
    const icons = {
      library:'<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5.5" rx="7.5" ry="3"></ellipse><path d="M4.5 5.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"></path><path d="M4.5 11.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"></path></svg>',
      files:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3.5h7l3 3V19a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5Z"></path><path d="M14 3.5V7h3.5"></path><path d="M8.5 11h6M8.5 14.5h6M8.5 18h3.5"></path></svg>',
      image:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5"></rect><circle cx="8.5" cy="9" r="1.5"></circle><path d="m5.5 17 4.2-4.2a1.5 1.5 0 0 1 2.1 0l1.4 1.4 1.3-1.3a1.5 1.5 0 0 1 2.1 0l2 2"></path></svg>',
      search:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.3"></circle><path d="m15.5 15.5 4.2 4.2"></path></svg>',
      warning:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 4.2 2.8 17.3A2 2 0 0 0 4.5 20h15a2 2 0 0 0 1.7-2.7L13.7 4.2a2 2 0 0 0-3.4 0Z"></path><path d="M12 9v4.5M12 17h.01"></path></svg>',
      empty:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h16M6 7.5l1-3h10l1 3v11a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 18.5Z"></path><path d="M9.5 12h5"></path></svg>',
      loading:'<svg class="is-loading" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.35-5.65"></path><path d="M17.5 3.8v4.5H13"></path></svg>',
    };
    return icons[String(kind || '').trim()] || icons.empty;
  }


  function kbEnsureDom(){
    if(document.getElementById('kbModalMask')) return;
    const modal = document.createElement('div');
    modal.id = 'kbModalMask';
    modal.className = 'kb-modal-mask';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
      <div class="kb-modal" role="region" aria-label="资料库">
        <button id="kbSidebarToggleBtn" class="kb-sidebar-toggle" type="button" title="展开侧边栏" aria-label="展开侧边栏">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="3"></rect><path d="M10 5v14"></path></svg>
        </button>
        <div class="kb-head">
          <div class="kb-head-top">
            <div class="kb-brand">
              <div class="kb-brand-icon" aria-hidden="true">${kbUiIcon('library')}</div>
              <div class="kb-head-title">
                <strong id="kbHeadTitle">文件库</strong>
                <span id="kbHeadSummary">集中管理全部文件。</span>
              </div>
            </div>
            <div class="filelib-head-actions">
              <input id="fileLibraryFilterInput" class="filelib-search" type="search" placeholder="搜索文件" aria-label="搜索文件">
              <button id="fileLibraryUploadBtn" class="filelib-upload-btn" type="button">上传</button>
              <input id="fileLibraryUploadInput" type="file" multiple hidden>
              <div id="fileLibraryProgress" class="filelib-progress" aria-live="polite"></div>
            </div>
          </div>

          <div class="kb-main-tabs" role="tablist" aria-label="资料库区域">
            <button class="kb-main-tab active" type="button" data-library-section-tab="files" data-library-route-tab="all" role="tab" aria-selected="true">文件库</button>
            <button class="kb-main-tab" type="button" data-library-section-tab="knowledge" data-library-route-tab="knowledge" role="tab" aria-selected="false">知识库</button>
          </div>

          <div class="kb-overview">
            <div class="kb-stat-card">
              <span class="kb-stat-label">当前知识库</span>
              <strong id="kbActiveSpaceName">默认知识库</strong>
              <em id="kbActiveSpaceMeta">0 文档 · 0 片段</em>
            </div>
            <div class="kb-stat-card">
              <span class="kb-stat-label">文档规模</span>
              <strong id="kbStatDocs">0</strong>
              <em>已入库文档</em>
            </div>
            <div class="kb-stat-card">
              <span class="kb-stat-label">可检索片段</span>
              <strong id="kbStatChunks">0</strong>
              <em>用于召回和引用</em>
            </div>
            <div class="kb-stat-card">
              <span class="kb-stat-label">聊天模式</span>
              <strong id="kbStatMode">知识库优先</strong>
              <em id="kbStatModeSub">优先查库</em>
            </div>
          </div>

          <div class="kb-toolbar">
            <div class="kb-toolbar-group">
              <label class="kb-field" title="选择知识库">
                <span>知识库</span>
                <select id="kbSpaceSelect"></select>
              </label>
              <button id="kbCreateSpaceBtn" class="kb-action-btn primary" type="button">新建</button>
              <button id="kbDeleteSpaceBtn" class="kb-action-btn danger" type="button">删除</button>
            </div>
            <div class="kb-toolbar-group kb-head-actions">
              <label class="kb-toggle-chip" title="聊天时优先查知识库">
                <input id="kbChatUseToggle" type="checkbox">
                <span class="kb-toggle-copy"><strong>回答先查库</strong><span>优先命中片段再回答</span></span>
              </label>
            </div>
          </div>
        </div>

        <div id="fileLibraryBody" class="kb-body kb-file-library-body">
          <section class="kb-pane filelib-pane">
            <div class="filelib-toolbar">
              <div class="filelib-type-tabs" role="tablist" aria-label="文件类型">
                <button class="filelib-type-tab active" type="button" data-library-route-tab="all" role="tab" aria-selected="true">全部</button>
                <button class="filelib-type-tab" type="button" data-library-route-tab="images" role="tab" aria-selected="false">图片</button>
                <button class="filelib-type-tab" type="button" data-library-route-tab="files" role="tab" aria-selected="false">文档与其他</button>
              </div>
              <span id="fileLibrarySummary" class="filelib-summary">载入中…</span>
              <div class="filelib-toolbar-end">
                <select id="fileLibrarySortSelect" class="kb-doc-sort" aria-label="文件排序">
                  <option value="updated_desc">最近更新</option>
                  <option value="name_asc">名称排序</option>
                  <option value="size_desc">文件最大</option>
                </select>
                <div class="kb-pane-badge" title="文件库连接状态">状态<strong id="fileLibraryBadge">已连接</strong></div>
              </div>
            </div>
            <div id="fileLibraryBulkBar" class="filelib-bulk-bar" hidden>
              <div class="filelib-bulk-left">
                <label class="filelib-select-all"><input id="fileLibrarySelectLoaded" type="checkbox"><span>全选已加载</span></label>
                <span id="fileLibrarySelectedCount" class="filelib-selected-count">未选择</span>
              </div>
              <div class="filelib-bulk-actions">
                <button id="fileLibraryBulkDownloadBtn" type="button">下载</button>
                <button id="fileLibraryBulkImportBtn" type="button">加入知识库</button>
                <button id="fileLibraryBulkDeleteBtn" class="danger" type="button">删除</button>
              </div>
            </div>
            <div id="fileLibraryList" class="kb-scroll">${kbRenderLoadingState('list', 5, '正在载入文件')}</div>
          </section>
        </div>

        <div id="kbKnowledgeBody" class="kb-body" hidden>
          <section class="kb-pane">
            <div class="kb-pane-head">
              <div class="kb-pane-head-copy">
                <strong>文档资产</strong>
                <span id="kbDocSummary">载入中…</span>
              </div>
              <div class="kb-pane-tools"><button id="kbClearSpaceBtn" class="kb-clear-btn" type="button">一键清空</button><div class="kb-pane-badge">状态<strong>已连接</strong></div></div>
            </div>
            <div class="kb-asset-tools">
              <input id="kbDocFilterInput" class="kb-doc-filter" type="search" placeholder="搜索内容">
              <select id="kbDocSortSelect" class="kb-doc-sort" aria-label="排序">
                <option value="updated_desc">最近更新</option>
                <option value="name_asc">名称排序</option>
                <option value="chunks_desc">片段最多</option>
                <option value="size_desc">文件最大</option>
              </select>
              <div id="kbAddWrap" class="kb-add-wrap">
                <button id="kbAddMenuBtn" class="kb-add-btn" type="button" aria-label="添加知识" aria-expanded="false">+</button>
                <div id="kbAddMenu" class="kb-add-menu" role="menu" aria-label="添加知识">
                  <button type="button" role="menuitem" data-kb-import-action="file"><span class="kb-add-icon"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="8.4"></circle><path d="M12 16.2V8.4"></path><path d="M8.9 11.5 12 8.4l3.1 3.1"></path></svg></span><span>上传文件</span></button>
                  <button type="button" role="menuitem" data-kb-import-action="folder"><span class="kb-add-icon"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3.8 7.4h6.1l1.7 2h8.6v7.8a2.2 2.2 0 0 1-2.2 2.2H6a2.2 2.2 0 0 1-2.2-2.2Z"></path><path d="M3.8 8.2V6.9A2.2 2.2 0 0 1 6 4.7h3.1l1.8 2.1"></path></svg></span><span>上传目录</span></button>
                  <button type="button" role="menuitem" data-kb-import-action="sync_folder"><span class="kb-add-icon"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 12a8 8 0 0 0-13.7-5.6"></path><path d="M6.3 3.8v2.6h2.6"></path><path d="M4 12a8 8 0 0 0 13.7 5.6"></path><path d="M17.7 20.2v-2.6h-2.6"></path></svg></span><span>同步目录</span></button>
                  <button type="button" role="menuitem" data-kb-import-action="url"><span class="kb-add-icon"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="8.5"></circle><path d="M3.8 12h16.4"></path><path d="M12 3.5c2.2 2.4 3.3 5.2 3.3 8.5s-1.1 6.1-3.3 8.5"></path><path d="M12 3.5C9.8 5.9 8.7 8.7 8.7 12s1.1 6.1 3.3 8.5"></path></svg></span><span>添加网页</span></button>
                  <button type="button" role="menuitem" data-kb-import-action="text"><span class="kb-add-icon"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 5.5h12"></path><path d="M6 10h12"></path><path d="M6 14.5h7"></path><path d="M4 19h7"></path><path d="M15.5 19h4.5"></path><path d="M17.8 16.7V21"></path></svg></span><span>添加文本内容</span></button>
                </div>
              </div>
              <div id="kbImportProgress" class="kb-import-progress" aria-live="polite"></div>
            </div>
            <input id="kbUploadFileInput" type="file" accept=".txt,.md,.json,.jsonl,.csv,.tsv,.pdf,.doc,.docx,.xls,.xlsx,.pptx,.html,.htm,.xml,.yaml,.yml,.toml,.ini,.log,.cfg,.conf,.py,.js,.ts,.tsx,.jsx,.java,.go,.rs,.php,.rb,.swift,.kt,.cs,.sql,.sh,.bat,.ps1,.zip" multiple hidden>
            <input id="kbUploadDirInput" type="file" multiple hidden>
            <div id="kbDocList" class="kb-scroll">${kbRenderLoadingState('list', 4, '正在载入文档')}</div>
          </section>

          <section class="kb-pane">
            <div class="kb-pane-head">
              <div class="kb-pane-head-copy">
                <strong>检索</strong>
                <span>输入问题，查看命中片段。</span>
              </div>
              <div class="kb-pane-badge">召回<strong id="kbSearchBadge">待检索</strong></div>
            </div>
            <div class="kb-search-wrap">
              <div class="kb-search-row">
                <input id="kbSearchInput" type="text" placeholder="输入问题">
                <button id="kbSearchBtn" type="button">搜索</button>
              </div>
              <div class="kb-search-hint">
                <span></span>
                <span id="kbSearchMetaHint">输入问题后返回结果。</span>
              </div>
            </div>
            <div id="kbSearchResults" class="kb-scroll"><div class="kb-empty-state"><div class="kb-empty-card"><div class="kb-empty-icon">${kbUiIcon('search')}</div><strong>还没有检索结果</strong><p>先输入一个问题，系统会返回最相关的片段和对应引用标签。</p><div class="kb-empty-tip">建议直接问文档里的具体条款、定义、结论或时间点。</div></div></div></div>
          </section>
        </div>

        <div id="kbCreateMask" class="kb-create-mask" aria-hidden="true">
          <div class="kb-create-card" role="dialog" aria-modal="true" aria-label="新建知识库">
            <div class="kb-create-head">
              <strong>新建知识库</strong>
              <span>给这组资料一个清晰的名称，后面上传的文档就能直接沉淀进来。</span>
            </div>
            <div class="kb-create-field">
              <label for="kbCreateNameInput">知识库名称</label>
              <input id="kbCreateNameInput" type="text" placeholder="知识库名称">
            </div>
            <div class="kb-create-actions">
              <button id="kbCreateCancelBtn" type="button">取消</button>
              <button id="kbCreateConfirmBtn" class="primary" type="button">创建知识库</button>
            </div>
          </div>
        </div>

        <div id="kbImportMask" class="kb-create-mask" aria-hidden="true">
          <div class="kb-create-card" role="dialog" aria-modal="true" aria-label="添加知识">
            <div class="kb-create-head">
              <strong id="kbImportDialogTitle">添加知识</strong>
              <span id="kbImportDialogDesc">导入后会进入当前知识库并建立索引。</span>
            </div>
            <div class="kb-import-field">
              <label for="kbImportTitleInput">标题</label>
              <input id="kbImportTitleInput" type="text" placeholder="可选">
            </div>
            <div id="kbImportUrlField" class="kb-import-field" hidden>
              <label for="kbImportUrlInput">网页地址</label>
              <input id="kbImportUrlInput" type="url" placeholder="https://...">
            </div>
            <div id="kbImportTextField" class="kb-import-field" hidden>
              <label for="kbImportTextInput">文本内容</label>
              <textarea id="kbImportTextInput" placeholder="粘贴要入库的内容"></textarea>
            </div>
            <div class="kb-create-actions">
              <button id="kbImportCancelBtn" type="button">取消</button>
              <button id="kbImportConfirmBtn" class="primary" type="button">导入</button>
            </div>
          </div>
        </div>
      </div>`;
    const workspace = document.getElementById('workspace');
    (workspace || document.body).appendChild(modal);
    document.getElementById('kbCreateMask')?.addEventListener('click', (e)=>{
      if(e.target?.id === 'kbCreateMask') kbCloseCreateDialog();
    });
    document.getElementById('kbImportMask')?.addEventListener('click', (e)=>{
      if(e.target?.id === 'kbImportMask') kbCloseImportDialog();
    });

    const sidebarBtn = document.getElementById('openKnowledgeBaseSidebar');
    if(!sidebarBtn){
      const nav = document.querySelector('.ow-sidebar-nav');
      if(nav){
        const btn = document.createElement('button');
        btn.id = 'openKnowledgeBaseSidebar';
        btn.className = 'ow-sidebar-nav-btn';
        btn.type = 'button';
        btn.innerHTML = `<span class="ow-sidebar-nav-icon" aria-hidden="true">${composerFileLibraryIconSvg('library')}</span><span class="ow-sidebar-nav-text" data-i18n="nav.library">${window.AperviaI18n?.t('nav.library') || '资料库'}</span>`;
        nav.insertBefore(btn, document.getElementById('clearAll') || null);
      }
    }

    document.getElementById('openKnowledgeBaseSidebar')?.addEventListener('click', ()=> openLibraryRoute(kbActiveLibraryTab(), { fileType:getKnowledgeBaseUiSettings().fileType || 'all' }));
    document.getElementById('kbSidebarToggleBtn')?.addEventListener('click', ()=>{
      if(typeof applySidebarCollapsed === 'function') applySidebarCollapsed(false);
    });
    document.querySelectorAll('[data-library-route-tab]').forEach((btn)=>{
      btn.addEventListener('click', ()=>{
        const routeTab = String(btn.getAttribute('data-library-route-tab') || 'all').trim().toLowerCase();
        if(routeTab === 'knowledge'){
          kbSetLibraryTab('knowledge');
          return;
        }
        const fileType = routeTab === 'images' ? 'image' : routeTab === 'files' ? 'file' : 'all';
        kbSetLibraryTab('files', { fileType });
      });
    });
    document.getElementById('fileLibraryFilterInput')?.addEventListener('input', (e)=>{
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), fileFilter:String(e.target?.value || '') });
      fileLibraryResetSelection();
      clearTimeout(fileLibraryFilterTimer);
      fileLibraryFilterTimer = setTimeout(()=> fileLibraryLoadState({ silent:true, reset:true }), 220);
    });
    document.getElementById('fileLibrarySortSelect')?.addEventListener('change', (e)=>{
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), fileSort:String(e.target?.value || 'updated_desc') });
      fileLibraryResetSelection();
      fileLibraryLoadState({ silent:true, reset:true });
    });
    document.getElementById('fileLibrarySelectLoaded')?.addEventListener('change', (e)=> fileLibraryToggleLoadedSelection(!!e.target?.checked));
    document.getElementById('fileLibraryBulkDownloadBtn')?.addEventListener('click', fileLibraryDownloadSelected);
    document.getElementById('fileLibraryBulkImportBtn')?.addEventListener('click', fileLibraryImportSelected);
    document.getElementById('fileLibraryBulkDeleteBtn')?.addEventListener('click', fileLibraryDeleteSelected);
    document.getElementById('fileLibraryUploadBtn')?.addEventListener('click', ()=> document.getElementById('fileLibraryUploadInput')?.click());
    document.getElementById('fileLibraryUploadInput')?.addEventListener('change', (e)=> fileLibraryUploadFiles(e.target?.files));
    document.getElementById('kbCreateSpaceBtn')?.addEventListener('click', kbOpenCreateDialog);
    document.getElementById('kbDeleteSpaceBtn')?.addEventListener('click', kbDeleteCurrentSpace);
    document.getElementById('kbCreateCancelBtn')?.addEventListener('click', kbCloseCreateDialog);
    document.getElementById('kbCreateConfirmBtn')?.addEventListener('click', kbHandleCreateSpace);
    document.getElementById('kbClearSpaceBtn')?.addEventListener('click', kbClearCurrentSpace);
    document.getElementById('kbCreateNameInput')?.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); kbHandleCreateSpace(); } });
    document.getElementById('kbAddMenuBtn')?.addEventListener('click', (e)=>{ e.stopPropagation(); kbToggleAddMenu(); });
    document.getElementById('kbAddMenu')?.addEventListener('click', (e)=>{
      const btn = e.target?.closest?.('[data-kb-import-action]');
      if(!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const action = String(btn.getAttribute('data-kb-import-action') || '').trim();
      kbCloseAddMenu();
      if(action === 'file'){
        document.getElementById('kbUploadFileInput')?.click();
      }else if(action === 'folder' || action === 'sync_folder'){
        kbDirectoryImportMode = action;
        document.getElementById('kbUploadDirInput')?.click();
      }else if(action === 'url'){
        kbOpenImportDialog('url');
      }else if(action === 'text'){
        kbOpenImportDialog('text');
      }
    });
    document.addEventListener('click', (e)=>{ if(!e.target?.closest?.('#kbAddWrap')) kbCloseAddMenu(); });
    const kbDirInput = document.getElementById('kbUploadDirInput');
    if(kbDirInput){ kbDirInput.setAttribute('webkitdirectory', ''); kbDirInput.setAttribute('directory', ''); }
    document.getElementById('kbUploadFileInput')?.addEventListener('change', (e)=> kbUploadFilesToCurrentSpace(e.target?.files, { mode:'file' }));
    document.getElementById('kbUploadDirInput')?.addEventListener('change', (e)=> kbUploadFilesToCurrentSpace(e.target?.files, { mode:kbDirectoryImportMode || 'folder' }));
    document.getElementById('kbImportCancelBtn')?.addEventListener('click', kbCloseImportDialog);
    document.getElementById('kbImportConfirmBtn')?.addEventListener('click', kbHandleImportConfirm);
    document.getElementById('kbImportUrlInput')?.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); kbHandleImportConfirm(); } });
    document.getElementById('kbDocFilterInput')?.addEventListener('input', (e)=>{
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), docFilter:String(e.target?.value || '') });
      renderKbState();
    });
    document.getElementById('kbDocSortSelect')?.addEventListener('change', (e)=>{
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), docSort:String(e.target?.value || 'updated_desc') });
      renderKbState();
    });
    document.getElementById('kbSearchBtn')?.addEventListener('click', ()=> kbRunSearch());
    document.getElementById('kbSearchInput')?.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); kbRunSearch(); } });
    document.getElementById('kbSpaceSelect')?.addEventListener('change', async (e)=>{
      const next = saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), activeSpaceId:String(e.target?.value || '').trim(), activeDocId:'' });
      await kbLoadState({ preferSpaceId: next.activeSpaceId || '' });
    });
    document.getElementById('kbChatUseToggle')?.addEventListener('change', (e)=>{
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), chatUseKnowledgeBase: !!e.target?.checked });
      syncKbControlsFromSettings();
      if(typeof setStatus === 'function') setStatus(e.target?.checked
        ? kbT('library.kb.preference_on', null, 'Knowledge-base retrieval will be prioritized in chat.')
        : kbT('library.kb.preference_off', null, 'Priority knowledge-base retrieval is off.'));
    });
  }


  function kbActiveLibraryTab(){
    const ui = getKnowledgeBaseUiSettings();
    return String(ui.libraryTab || 'files').trim() === 'knowledge' ? 'knowledge' : 'files';
  }

  function kbSetLibraryTab(tab, opts={}){
    const nextTab = String(tab || '').trim() === 'knowledge' ? 'knowledge' : 'files';
    const currentUi = getKnowledgeBaseUiSettings();
    const nextFileType = nextTab === 'files'
      ? (String(opts?.fileType || currentUi.fileType || 'all').trim().toLowerCase() || 'all')
      : String(currentUi.fileType || 'all');
    const preserveActiveChatJob = activeChatJobInProgress();
    saveKnowledgeBaseUiSettings({ ...currentUi, libraryTab: nextTab, fileType:nextFileType });
    if(document.getElementById('kbModalMask')?.classList.contains('open')) syncLibraryRoute(nextTab, { replace:false, fileType:nextFileType });
    if(preserveActiveChatJob) keepActiveChatJobAlive('library_tab_switch');
    fileLibraryResetSelection();
    kbRefreshLibraryTabVisibility();
    const loading = nextTab === 'files' ? fileLibraryLoadState({ silent:true, reset:true }) : kbLoadState().catch(()=>{});
    if(preserveActiveChatJob && loading && typeof loading.finally === 'function'){
      loading.finally(()=> keepActiveChatJobAlive('library_tab_loaded'));
    }
  }

  function kbRefreshLibraryTabVisibility(){
    const tab = kbActiveLibraryTab();
    const ui = getKnowledgeBaseUiSettings();
    const fileType = String(ui.fileType || 'all').trim().toLowerCase();
    const modal = document.querySelector('#kbModalMask .kb-modal');
    if(modal){
      modal.classList.toggle('kb-tab-files', tab === 'files');
      modal.classList.toggle('kb-tab-knowledge', tab === 'knowledge');
    }
    const fileBody = document.getElementById('fileLibraryBody');
    const kbBody = document.getElementById('kbKnowledgeBody');
    if(fileBody) fileBody.hidden = tab !== 'files';
    if(kbBody) kbBody.hidden = tab !== 'knowledge';
    const toolbar = document.querySelector('#kbModalMask .kb-toolbar');
    if(toolbar) toolbar.hidden = tab === 'files';
    const overview = document.querySelector('#kbModalMask .kb-overview');
    if(overview) overview.hidden = tab === 'files';
    document.querySelectorAll('[data-library-route-tab]').forEach((btn)=>{
      const routeTab = String(btn.getAttribute('data-library-route-tab') || 'all').trim().toLowerCase();
      const sectionTab = String(btn.getAttribute('data-library-section-tab') || '').trim().toLowerCase();
      const active = sectionTab
        ? tab === sectionTab
        : (tab === 'files' && routeTab === (fileType === 'image' ? 'images' : fileType === 'file' ? 'files' : 'all'));
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    const title = document.getElementById('kbHeadTitle');
    if(title) title.textContent = kbT(tab === 'knowledge' ? 'library.knowledge_title' : 'library.title', null, tab === 'knowledge' ? 'Knowledge base' : 'File library');
    const head = document.getElementById('kbHeadSummary');
    if(head){
      head.textContent = tab === 'knowledge'
        ? kbT('library.summary_knowledge', null, 'Manage searchable documents, knowledge chunks, and chat retrieval.')
        : fileType === 'image'
          ? kbT('library.summary_images', null, 'Browse images in one place. Images are not indexed in the knowledge base.')
          : fileType === 'file'
            ? kbT('library.summary_files', null, 'Manage uploaded and generated files.')
            : kbT('library.summary_all', null, 'Manage all uploaded and generated content.');
    }
    if(tab === 'files') renderFileLibraryState();
    else renderKbState();
  }

  async function fileLibraryApi(path, { method='GET', body=null } = {}){
    const init = { method, headers:{} };
    if(body != null){ init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    const res = await fetch(path, init);
    let data = {};
    try{ data = await res.json(); }catch(_){ }
    if(!res.ok) throw new Error(data?.error || data?.message || ('HTTP ' + res.status));
    return data || {};
  }

  function fileLibrarySetProgress(text=''){
    const el = document.getElementById('fileLibraryProgress');
    if(el) el.textContent = String(text || '');
  }

  function fileLibraryEnsurePreviewDialog(){
    let mask = document.getElementById('fileLibraryPreviewMask');
    if(mask) return mask;
    mask = document.createElement('div');
    mask.id = 'fileLibraryPreviewMask';
    mask.className = 'filelib-preview-mask';
    mask.setAttribute('aria-hidden', 'true');
    mask.innerHTML = `<div class="filelib-preview-card" role="dialog" aria-modal="true" aria-label="${escapeHtml(kbT('library.preview.dialog', null, 'File preview'))}">
      <div class="filelib-preview-head">
        <div class="filelib-preview-title"><strong id="fileLibraryPreviewTitle">${escapeHtml(kbT('library.preview.dialog', null, 'File preview'))}</strong><span id="fileLibraryPreviewMeta"></span></div>
        <button id="fileLibraryPreviewClose" class="filelib-preview-close" type="button">${escapeHtml(kbT('library.preview.close', null, 'Close'))}</button>
      </div>
      <div id="fileLibraryPreviewBody" class="filelib-preview-body">${escapeHtml(kbT('library.preview.loading', null, 'Loading…'))}</div>
      <div id="fileLibraryPreviewNote" class="filelib-preview-note"></div>
    </div>`;
    document.body.appendChild(mask);
    const close = ()=>{
      mask.classList.remove('open');
      mask.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('modal-open');
    };
    mask.addEventListener('click', (e)=>{ if(e.target === mask) close(); });
    mask.querySelector('#fileLibraryPreviewClose')?.addEventListener('click', close);
    document.addEventListener('keydown', (e)=>{
      if(e.key === 'Escape' && mask.classList.contains('open')){
        e.preventDefault();
        close();
      }
    });
    return mask;
  }

  function fileLibraryIsNativePreviewFile(item){
    const ext = String(item?.ext || '').trim().toLowerCase();
    const category = String(item?.category || '').trim();
    if(category === 'image') return true;
    return ext === '.pdf';
  }

  function fileLibraryOpenNewTabUrl(url, emptyMessage=''){
    const href = String(url || '').trim();
    if(!href){
      if(typeof reportAppError === 'function') reportAppError(emptyMessage || kbT('library.preview.no_open_link', null, 'This file has no link that can be opened.'));
      return false;
    }
    try{
      const opened = window.open('about:blank', '_blank');
      if(opened){
        try{ opened.opener = null; }catch(_){ }
        opened.location.href = href;
        return true;
      }
    }catch(_){ }
    try{
      const a = document.createElement('a');
      a.href = href;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      a.remove();
      return true;
    }catch(__){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.preview.open_failed', null, 'Unable to open the link in the browser.'));
      return false;
    }
  }

  function fileLibraryOpenBrowserUrl(url, emptyMessage=''){
    return fileLibraryOpenNewTabUrl(url, emptyMessage);
  }

  function fileLibraryOpenDownloadUrl(url, emptyMessage=''){
    return openWebAiManagedDownloadTab(url, emptyMessage || kbT('library.preview.no_download_link', null, 'This file has no download link.'));
  }

  async function fileLibraryOpenPreview(item){
    const file = item && typeof item === 'object' ? item : {};
    const url = String(file.view_url || file.preview_url || file.download_url || file.url || '').trim();
    fileLibraryOpenBrowserUrl(url, kbT('library.preview.no_preview_link', null, 'This file has no preview link that can be opened.'));
  }

  function fileLibraryFilesForDisplay(files){
    return Array.isArray(files) ? files.slice() : [];
  }

  function fileLibraryFormatTime(value){
    const raw = Number(value || 0) || 0;
    if(!raw) return '';
    try{ return new Date(raw * 1000).toLocaleString('zh-CN', { month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit' }); }catch(_){ return ''; }
  }

  function fileLibraryResetSelection(){
    fileLibrarySelectedIds.clear();
    fileLibraryUpdateBulkBar();
  }

  function fileLibraryLoadedFiles(){
    return Array.isArray(kbRuntime.fileLibrary?.files) ? kbRuntime.fileLibrary.files : [];
  }

  function fileLibraryLoadedIds(){
    return fileLibraryLoadedFiles().map(x => String(x?.file_id || '').trim()).filter(Boolean);
  }

  function fileLibrarySelectedItems(){
    const selected = new Set(Array.from(fileLibrarySelectedIds));
    return fileLibraryLoadedFiles().filter(item => selected.has(String(item?.file_id || '').trim()));
  }

  function fileLibraryCloseRowMenus(except=null){
    document.querySelectorAll('#fileLibraryList .filelib-actions.menu-open').forEach((wrap)=>{
      if(except && wrap === except) return;
      wrap.classList.remove('menu-open');
      wrap.querySelector('[data-filelib-menu]')?.setAttribute('aria-expanded', 'false');
      const menu = wrap.querySelector('.filelib-row-menu');
      if(menu){
        menu.style.left = '';
        menu.style.top = '';
      }
    });
  }

  function fileLibraryPositionRowMenu(wrap){
    const trigger = wrap?.querySelector?.('[data-filelib-menu]');
    const menu = wrap?.querySelector?.('.filelib-row-menu');
    if(!trigger || !menu) return;
    const triggerRect = trigger.getBoundingClientRect();
    const menuWidth = Math.max(180, menu.offsetWidth || 190);
    const menuHeight = Math.max(40, menu.offsetHeight || 0);
    const viewportWidth = Math.max(320, window.innerWidth || document.documentElement.clientWidth || 0);
    const viewportHeight = Math.max(320, window.innerHeight || document.documentElement.clientHeight || 0);
    const left = Math.max(8, Math.min(triggerRect.right - menuWidth, viewportWidth - menuWidth - 8));
    const belowTop = triggerRect.bottom + 6;
    const aboveTop = triggerRect.top - menuHeight - 6;
    const top = belowTop + menuHeight <= viewportHeight - 8 ? belowTop : Math.max(8, aboveTop);
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function fileLibraryKnowledgeImportable(item){
    if(!item || typeof item !== 'object') return false;
    if(item.kb_importable === false) return false;
    if(String(item.category || '').trim().toLowerCase() === 'image') return false;
    const ext = String(item.ext || '').trim().toLowerCase().replace(/^\./, '');
    return !KB_IMAGE_EXTENSIONS.has(ext);
  }

  function fileLibrarySourceLabel(item){
    const source = String(item?.source || '').trim().toLowerCase();
    const namespace = String(item?.namespace || '').trim().toLowerCase();
    if(source === 'generated' || namespace === 'generated'){
      return kbT('library.generated_file', null, 'Generated file');
    }
    if(source === 'pullback'){
      return kbT('library.retrieved_image', null, 'Retrieved image');
    }
    return kbT('library.uploaded_file', null, 'Uploaded file');
  }

  function fileLibraryApplyInteractionState(){
    const body = document.getElementById('fileLibraryBody');
    if(!body) return;
    const selectedCount = fileLibrarySelectedIds.size;
    body.classList.toggle('has-selection', selectedCount > 0);
    body.classList.toggle('is-busy', !!fileLibraryActionBusy);
    body.querySelectorAll('button, input, select, a').forEach((el)=>{
      const tag = String(el.tagName || '').toLowerCase();
      if(fileLibraryActionBusy){
        if(!el.hasAttribute('data-filelib-prev-disabled')){
          el.setAttribute('data-filelib-prev-disabled', (tag !== 'a' && el.disabled) ? '1' : '0');
        }
        if(tag === 'a'){
          if(!el.hasAttribute('data-filelib-prev-tabindex')) el.setAttribute('data-filelib-prev-tabindex', el.getAttribute('tabindex') ?? '');
          el.setAttribute('aria-disabled', 'true');
          el.setAttribute('tabindex', '-1');
        }else{
          el.disabled = true;
        }
      }else{
        const prev = el.getAttribute('data-filelib-prev-disabled');
        if(prev !== null){
          if(tag !== 'a') el.disabled = prev === '1';
          el.removeAttribute('data-filelib-prev-disabled');
        }
        if(tag === 'a'){
          el.removeAttribute('aria-disabled');
          const oldTab = el.getAttribute('data-filelib-prev-tabindex');
          if(oldTab !== null){
            if(oldTab) el.setAttribute('tabindex', oldTab);
            else el.removeAttribute('tabindex');
            el.removeAttribute('data-filelib-prev-tabindex');
          }
        }
      }
    });
  }

  function fileLibrarySetActionBusy(busy){
    fileLibraryActionBusy = !!busy;
    fileLibraryApplyInteractionState();
  }

  function fileLibraryUpdateBulkBar(){
    const loadedIds = fileLibraryLoadedIds();
    for(const id of Array.from(fileLibrarySelectedIds)){
      if(!loadedIds.includes(id)) fileLibrarySelectedIds.delete(id);
    }
    const selectedCount = fileLibrarySelectedIds.size;
    const importableSelectedCount = fileLibrarySelectedItems().filter(item => fileLibraryKnowledgeImportable(item) && !Number(item?.kb_doc_count || 0)).length;
    const bar = document.getElementById('fileLibraryBulkBar');
    const countEl = document.getElementById('fileLibrarySelectedCount');
    const selectLoaded = document.getElementById('fileLibrarySelectLoaded');
    if(bar){
      bar.hidden = !loadedIds.length;
      bar.classList.toggle('has-selection', selectedCount > 0);
    }
    const actions = bar?.querySelector?.('.filelib-bulk-actions');
    if(actions) actions.hidden = selectedCount <= 0;
    if(countEl) countEl.textContent = selectedCount
      ? kbT('library.selected_count', {count:selectedCount}, `${selectedCount} selected`)
      : kbT('library.loaded_selected_count', {count:loadedIds.length}, `${loadedIds.length} loaded`);
    if(selectLoaded){
      selectLoaded.checked = !!loadedIds.length && loadedIds.every(id => fileLibrarySelectedIds.has(id));
      selectLoaded.indeterminate = !!selectedCount && !selectLoaded.checked;
      selectLoaded.disabled = !loadedIds.length || !!fileLibraryActionBusy;
    }
    document.getElementById('fileLibraryBulkDownloadBtn')?.toggleAttribute('disabled', selectedCount <= 0 || !!fileLibraryActionBusy);
    const importBtn = document.getElementById('fileLibraryBulkImportBtn');
    importBtn?.toggleAttribute('disabled', importableSelectedCount <= 0 || !!fileLibraryActionBusy);
    if(importBtn) importBtn.title = importableSelectedCount > 0
      ? kbT('library.importable_title', {count:importableSelectedCount}, `Add ${importableSelectedCount} supported files to the knowledge base`)
      : kbT('library.images_not_supported', null, 'Images are not added to the knowledge base');
    document.getElementById('fileLibraryBulkDeleteBtn')?.toggleAttribute('disabled', selectedCount <= 0 || !!fileLibraryActionBusy);
    fileLibraryApplyInteractionState();
  }

  function fileLibraryToggleLoadedSelection(checked){
    if(fileLibraryActionBusy) return;
    const ids = fileLibraryLoadedIds();
    if(checked){
      ids.forEach(id => fileLibrarySelectedIds.add(id));
    }else{
      ids.forEach(id => fileLibrarySelectedIds.delete(id));
    }
    renderFileLibraryState();
  }

  function fileLibraryStateUrl(offset=0){
    const ui = getKnowledgeBaseUiSettings();
    const params = new URLSearchParams();
    params.set('offset', String(Math.max(0, Number(offset || 0) || 0)));
    params.set('limit', String(FILE_LIBRARY_PAGE_SIZE));
    params.set('type', String(ui.fileType || 'all'));
    params.set('sort', String(ui.fileSort || 'updated_desc'));
    const filter = String(ui.fileFilter || '').trim();
    if(filter) params.set('filter', filter);
    return '/api3/file-library/state?' + params.toString();
  }

  async function fileLibraryDownloadSelected(){
    if(fileLibraryActionBusy) return;
    const items = fileLibrarySelectedItems().filter(item => String(item?.download_url || item?.url || item?.view_url || '').trim());
    if(!items.length){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.selection.no_download_link', null, 'The selected file has no download link.'));
      return;
    }
    for(const item of items){
      const url = String(item.download_url || item.url || item.view_url || '').trim();
      if(!url) continue;
      fileLibraryOpenDownloadUrl(url, kbT('library.selection.no_download_link', null, 'The selected file has no download link.'));
      await new Promise(resolve => setTimeout(resolve, 80));
    }
  }

  async function fileLibraryImportSelected(){
    if(fileLibraryActionBusy) return;
    const selectedItems = fileLibrarySelectedItems();
    const blockedCount = selectedItems.filter(item => !fileLibraryKnowledgeImportable(item)).length;
    const items = selectedItems.filter(item => fileLibraryKnowledgeImportable(item) && !Number(item?.kb_doc_count || 0));
    if(!items.length){
      if(typeof toast === 'function') toast(blockedCount
        ? kbT('library.kb.import_images_skipped', null, 'Images stay in the library and are not added to the knowledge base.')
        : kbT('library.kb.import_all_joined', null, 'All selected files are already in the knowledge base.'));
      return;
    }
    const desc = blockedCount
      ? kbT('library.kb.import_desc_images', {count:items.length, images:blockedCount}, `Add ${items.length} supported files to the current knowledge base. ${blockedCount} images will remain in the library and will not be indexed.`)
      : kbT('library.kb.import_desc', {count:items.length}, `Add ${items.length} files to the current knowledge base.`);
    const ok = await askKbDangerConfirm({ title:kbT('library.kb.import_title', null, 'Add to knowledge base?'), desc, confirmText:kbT('library.kb.import_action', null, 'Add'), cancelText:kbT('common.cancel', null, 'Cancel'), variant:'default' }, document.getElementById('fileLibraryBulkImportBtn'));
    if(!ok) return;
    const btn = document.getElementById('fileLibraryBulkImportBtn');
    const oldText = btn?.textContent || kbT('library.add_to_kb', null, 'Add to knowledge base');
    fileLibrarySetActionBusy(true);
    if(btn){ btn.textContent = kbT('library.kb.importing', null, 'Adding…'); }
    try{
      const spaceId = kbCurrentSpaceId();
      const data = await fileLibraryApi('/api3/file-library/batch-import-to-kb', { method:'POST', body:{ file_ids: items.map(x => x.file_id), space_id:spaceId } });
      fileLibraryResetSelection();
      await Promise.all([fileLibraryLoadState({ silent:true, reset:true }), kbLoadState({ preferSpaceId:spaceId })]);
      const failed = Number(data.failed || 0) || 0;
      if(failed && typeof reportAppError === 'function') reportAppError(kbT('library.bulk.import_partial', {success:Number(data.imported || 0) || 0, failed}, 'Some files could not be added: {success} succeeded, {failed} failed.'));
      else if(typeof toast === 'function') toast(kbT('library.kb.added', null, 'Added to knowledge base'));
    }catch(err){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.bulk.import_failed', {error:err.message}, 'Unable to add the selected files to the knowledge base: {error}'));
    }finally{
      if(btn){ btn.textContent = oldText; }
      fileLibrarySetActionBusy(false);
      fileLibraryUpdateBulkBar();
    }
  }

  async function fileLibraryDeleteSelected(){
    if(fileLibraryActionBusy) return;
    const items = fileLibrarySelectedItems();
    if(!items.length) return;
    const joined = items.filter(item => Number(item?.kb_doc_count || 0) > 0).length;
    const desc = joined
      ? kbT('library.files.delete_joined_desc', {count:items.length, joined}, `Move ${items.length} files and their previews to the shared administrator recycle bin. ${joined} files are in the knowledge base and must be removed there first. Administrators can restore them.`)
      : kbT('library.files.delete_desc', {count:items.length}, `Move ${items.length} files and their previews to the shared administrator recycle bin. Administrators can restore them.`);
    await askKbDangerAction({
      title:kbT('library.files.delete_title', null, 'Delete files?'),
      desc,
      confirmText:kbT('common.delete', null, 'Delete'),
      cancelText:kbT('common.cancel', null, 'Cancel'),
      variant:'danger',
      busyText:kbT('common.deleting', null, 'Deleting…'),
      errorPrefix:kbT('library.bulk.delete_failed', null, 'Unable to delete the selected files')
    }, async ()=>{
      fileLibrarySetActionBusy(true);
      try{
        const data = await fileLibraryApi('/api3/file-library/batch-delete', { method:'POST', body:{ file_ids: items.map(x => x.file_id) } });
        const failed = Number(data.failed || 0) || 0;
        fileLibraryResetSelection();
        await fileLibraryLoadState({ silent:true, reset:true });
        if(failed && typeof reportAppError === 'function') reportAppError(kbT('library.bulk.delete_partial', {success:Number(data.deleted || 0) || 0, failed}, 'Some files could not be deleted: {success} succeeded, {failed} failed.'));
        else if(typeof toast === 'function') toast(kbT('library.files.moved_to_trash', null, 'Moved to the recycle bin'));
      }finally{
        fileLibrarySetActionBusy(false);
        fileLibraryUpdateBulkBar();
      }
    }, document.getElementById('fileLibraryBulkDeleteBtn'));
  }

  function renderFileLibraryState(){
    if(kbActiveLibraryTab() !== 'files') return;
    const state = kbRuntime.fileLibrary || {};
    const files = Array.isArray(state.files) ? state.files : [];
    const display = fileLibraryFilesForDisplay(files);
    const ui = getKnowledgeBaseUiSettings();
    const filterInput = document.getElementById('fileLibraryFilterInput');
    const sortSelect = document.getElementById('fileLibrarySortSelect');
    if(filterInput && filterInput.value !== String(ui.fileFilter || '')) filterInput.value = String(ui.fileFilter || '');
    if(sortSelect) sortSelect.value = String(ui.fileSort || 'updated_desc') || 'updated_desc';
    const stats = state.stats || {};
    const page = state.page || {};
    const totalCount = Number(stats.total || 0) || files.length;
    const filteredTotal = Number(page.filtered_total ?? stats.filtered_total ?? totalCount) || 0;
    const loadedCount = files.length;
    const statLabels = Array.from(document.querySelectorAll('#kbModalMask .kb-stat-label'));
    if(statLabels[0]) statLabels[0].textContent = kbT('library.stat_current', null, 'Current library');
    if(statLabels[1]) statLabels[1].textContent = kbT('library.stat_files', null, 'Files');
    if(statLabels[2]) statLabels[2].textContent = kbT('library.stat_images', null, 'Images');
    if(statLabels[3]) statLabels[3].textContent = kbT('library.stat_usage', null, 'Usage');
    const activeName = document.getElementById('kbActiveSpaceName');
    const activeMeta = document.getElementById('kbActiveSpaceMeta');
    const statDocs = document.getElementById('kbStatDocs');
    const statChunks = document.getElementById('kbStatChunks');
    const modeEl = document.getElementById('kbStatMode');
    const modeSub = document.getElementById('kbStatModeSub');
    if(activeName) activeName.textContent = kbT('library.repository', null, 'Library');
    if(activeMeta) activeMeta.textContent = kbT('library.repository_meta', {count:totalCount, size:fmtBytes(Number(stats.total_size || 0) || 0)}, `${totalCount} files · ${fmtBytes(Number(stats.total_size || 0) || 0)}`);
    if(statDocs) statDocs.textContent = String(Number(stats.files || 0) || 0);
    if(statChunks) statChunks.textContent = String(Number(stats.images || 0) || 0);
    if(modeEl) modeEl.textContent = `${fmtBytes(Number(stats.total_size || 0) || 0)}`;
    if(modeSub) modeSub.textContent = kbT('library.file_usage', null, 'File usage');
    const summary = document.getElementById('fileLibrarySummary');
    if(summary) summary.textContent = filteredTotal === totalCount
      ? kbT('library.loaded_files', {loaded:loadedCount, total:totalCount}, `Loaded ${loadedCount} / ${totalCount} files`)
      : kbT('library.loaded_matches', {loaded:loadedCount, total:filteredTotal}, `Loaded ${loadedCount} / ${filteredTotal} matching files`);
    const badge = document.getElementById('fileLibraryBadge');
    if(badge) badge.textContent = kbT(totalCount ? 'library.synced' : 'library.empty_status', null, totalCount ? 'Synced' : 'Empty');
    const list = document.getElementById('fileLibraryList');
    if(!list) return;
    if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(list);
    if(!display.length){
      fileLibraryUpdateBulkBar();
      if(filteredTotal && typeof AppLoadingUi !== 'undefined') AppLoadingUi.render(list, { variant:'list', rows:5, label:kbT('library.loading_files', null, 'Loading files') });
      else list.innerHTML = kbRenderEmptyState({
        icon:filteredTotal ? 'loading' : 'files',
        title:filteredTotal ? kbT('library.loading_files', null, 'Loading files') : (totalCount ? kbT('library.no_match', null, 'No matching files') : kbT('library.empty_files', null, 'No files')),
        desc:totalCount ? kbT('library.filter_hint', null, 'Try another keyword or category.') : kbT('library.empty_desc', null, 'Uploaded files appear here first and are not added to the knowledge base automatically.'),
        tip:kbT('library.empty_tip', null, 'For long-term retrieval, select Add to knowledge base.'),
      });
      return;
    }
    const hasMore = !!page.has_more;
    const moreHtml = hasMore ? `<div class="filelib-more"><button id="fileLibraryLoadMoreBtn" type="button">${escapeHtml(kbT('library.load_more', null, 'Load more'))}</button><span>${escapeHtml(kbT('library.loaded_count', {loaded:loadedCount, total:filteredTotal || loadedCount}, `Loaded ${loadedCount} / ${filteredTotal || loadedCount}`))}</span></div>` : '';
    list.innerHTML = `<div class="filelib-list"><div class="filelib-table-head" aria-hidden="true"><span></span><span></span><span>${escapeHtml(kbT('library.table_name', null, 'Name'))}</span><span>${escapeHtml(kbT('library.table_modified', null, 'Modified'))}</span><span>${escapeHtml(kbT('library.table_size', null, 'Size'))}</span><span></span></div>${display.map((item)=>{
      const fileIdRaw = String(item.file_id || '').trim();
      const fileId = escapeHtml(fileIdRaw);
      const name = escapeHtml(item.filename || item.saved_filename || kbT('library.unnamed_file', null, 'Untitled file'));
      const ext = escapeHtml(String(item.ext || '').replace(/^\./, '').toUpperCase() || (item.category === 'image' ? 'IMG' : 'FILE'));
      const isImage = String(item.category || '') === 'image';
      const preview = escapeHtml(item.preview_url || item.view_url || item.download_url || item.url || '');
      const download = escapeHtml(item.download_url || item.url || item.view_url || '');
      const kbCount = Number(item.kb_doc_count || 0) || 0;
      const kbImportable = fileLibraryKnowledgeImportable(item);
      const joined = kbImportable && kbCount > 0;
      const selected = fileLibrarySelectedIds.has(fileIdRaw);
      const updated = escapeHtml(fileLibraryFormatTime(item.updated_ts) || '—');
      const size = escapeHtml(fmtBytes(Number(item.size || 0) || 0));
      const meta = [fileLibrarySourceLabel(item)].filter(Boolean).map(escapeHtml).join(' · ');
      const thumb = isImage && preview ? `<img src="${preview}" alt="${name}" loading="lazy" decoding="async">` : kbUiIcon(isImage ? 'image' : 'files');
      return `<article class="filelib-row${selected ? ' is-selected' : ''}" data-filelib-id="${fileId}">
        <label class="filelib-check" aria-label="${escapeHtml(kbT('library.select_file', {name:item.filename || item.saved_filename || kbT('library.unnamed_file', null, 'Untitled file')}, `Select ${item.filename || item.saved_filename || 'Untitled file'}`))}"><input type="checkbox" data-filelib-select="${fileId}" ${selected ? 'checked' : ''}></label>
        <div class="filelib-thumb">${thumb}</div>
        <div class="filelib-main">
          <div class="filelib-name" title="${name}">${name}</div>
          <div class="filelib-meta"><span>${meta}</span><span class="filelib-chip">${ext}</span>${joined ? `<span class="filelib-chip kb">${escapeHtml(kbT('library.joined_kb', null, 'Added to knowledge base'))}</span>` : ''}${!kbImportable ? `<span class="filelib-chip muted">${escapeHtml(kbT('library.image_not_indexed', null, 'Image not indexed'))}</span>` : ''}</div>
        </div>
        <div class="filelib-updated">${updated}</div>
        <div class="filelib-size">${size}</div>
        <div class="filelib-actions">
          <button type="button" class="filelib-menu-trigger" data-filelib-menu="${fileId}" aria-label="${escapeHtml(kbT('library.file_actions', null, 'File actions'))}" aria-expanded="false">•••</button>
          <div class="filelib-row-menu" role="menu" aria-label="${escapeHtml(kbT('library.actions_for', {name:item.filename || item.saved_filename || kbT('library.unnamed_file', null, 'Untitled file')}, `Actions for ${item.filename || item.saved_filename || 'Untitled file'}`))}">
            <button type="button" role="menuitem" data-filelib-preview="${fileId}">${kbUiIcon('search')}<span>${escapeHtml(kbT('library.preview', null, 'Preview'))}</span></button>
            ${download ? `<button type="button" role="menuitem" data-filelib-download="${fileId}">${kbUiIcon('files')}<span>${escapeHtml(kbT('library.download', null, 'Download'))}</span></button>` : ''}
            ${kbImportable ? `<button type="button" role="menuitem" data-filelib-import="${fileId}" ${joined ? 'disabled' : ''}>${kbUiIcon('library')}<span>${escapeHtml(kbT(joined ? 'library.joined_kb' : 'library.add_to_kb', null, joined ? 'Added to knowledge base' : 'Add to knowledge base'))}</span></button>` : ''}
            <button type="button" role="menuitem" class="danger" data-filelib-delete="${fileId}">${kbUiIcon('empty')}<span>${escapeHtml(kbT('common.delete', null, 'Delete'))}</span></button>
          </div>
        </div>
      </article>`;
    }).join('')}</div>${moreHtml}`;
    list.querySelectorAll('[data-filelib-menu]').forEach((btn)=>{
      btn.addEventListener('click', (event)=>{
        event.preventDefault();
        event.stopPropagation();
        const wrap = btn.closest('.filelib-actions');
        if(!wrap) return;
        const opening = !wrap.classList.contains('menu-open');
        fileLibraryCloseRowMenus(wrap);
        wrap.classList.toggle('menu-open', opening);
        btn.setAttribute('aria-expanded', opening ? 'true' : 'false');
        if(opening) fileLibraryPositionRowMenu(wrap);
      });
    });
    list.querySelectorAll('[data-filelib-select]').forEach((box)=>{
      box.addEventListener('change', ()=>{
        if(fileLibraryActionBusy) return;
        const fileId = String(box.getAttribute('data-filelib-select') || '').trim();
        if(!fileId) return;
        if(box.checked) fileLibrarySelectedIds.add(fileId);
        else fileLibrarySelectedIds.delete(fileId);
        const row = box.closest('.filelib-row');
        if(row) row.classList.toggle('is-selected', box.checked);
        fileLibraryUpdateBulkBar();
      });
    });
    list.querySelector('#fileLibraryLoadMoreBtn')?.addEventListener('click', ()=> fileLibraryLoadMore());
    list.querySelectorAll('[data-filelib-preview]').forEach((btn)=>{
      btn.addEventListener('click', async ()=>{
        if(fileLibraryActionBusy) return;
        const fileId = String(btn.getAttribute('data-filelib-preview') || '').trim();
        if(!fileId) return;
        const item = fileLibraryLoadedFiles().find(x => String(x?.file_id || '').trim() === fileId) || {};
        await fileLibraryOpenPreview(item);
      });
    });
    list.querySelectorAll('[data-filelib-download]').forEach((btn)=>{
      btn.addEventListener('click', ()=>{
        if(fileLibraryActionBusy) return;
        const fileId = String(btn.getAttribute('data-filelib-download') || '').trim();
        if(!fileId) return;
        const item = fileLibraryLoadedFiles().find(x => String(x?.file_id || '').trim() === fileId) || {};
        const url = String(item.download_url || item.url || item.view_url || '').trim();
        fileLibraryOpenDownloadUrl(url, kbT('library.preview.no_download_link', null, 'This file has no download link.'));
      });
    });
    list.querySelectorAll('[data-filelib-import]').forEach((btn)=>{
      btn.addEventListener('click', async ()=>{
        if(fileLibraryActionBusy) return;
        const fileId = String(btn.getAttribute('data-filelib-import') || '').trim();
        if(!fileId) return;
        const oldText = btn.textContent;
        fileLibrarySetActionBusy(true);
        btn.textContent = kbT('library.kb.importing', null, 'Adding…');
        try{
          const spaceId = kbCurrentSpaceId();
          await fileLibraryApi('/api3/file-library/import-to-kb', { method:'POST', body:{ file_id:fileId, space_id:spaceId } });
          await Promise.all([fileLibraryLoadState({ silent:true, reset:true }), kbLoadState({ preferSpaceId:spaceId })]);
          if(typeof toast === 'function') toast(kbT('library.kb.added', null, 'Added to knowledge base'));
        }catch(err){
          btn.textContent = oldText || kbT('library.add_to_kb', null, 'Add to knowledge base');
          if(typeof reportAppError === 'function') reportAppError(kbT('library.file.import_failed', {error:err.message}, 'Unable to add the file to the knowledge base: {error}'));
        }finally{
          fileLibrarySetActionBusy(false);
          fileLibraryUpdateBulkBar();
        }
      });
    });
    list.querySelectorAll('[data-filelib-delete]').forEach((btn)=>{
      btn.addEventListener('click', async ()=>{
        if(fileLibraryActionBusy) return;
        const fileId = String(btn.getAttribute('data-filelib-delete') || '').trim();
        if(!fileId) return;
        const row = btn.closest('.filelib-row');
        const filename = row?.querySelector?.('.filelib-name')?.textContent || kbT('library.file.this_file', null, 'this file');
        await askKbDangerAction({
          title:kbT('library.files.delete_title', null, 'Delete files?'),
          desc:kbT('library.files.delete_one_desc', {name:filename}, `Move “${filename}” and its previews to the shared administrator recycle bin. Administrators can restore it.`),
          confirmText:kbT('common.delete', null, 'Delete'),
          cancelText:kbT('common.cancel', null, 'Cancel'),
          variant:'danger',
          busyText:kbT('common.deleting', null, 'Deleting…'),
          errorPrefix:kbT('library.file.delete_failed', null, 'Unable to delete the file')
        }, async ()=>{
          fileLibrarySetActionBusy(true);
          try{
            await fileLibraryApi('/api3/file-library/delete', { method:'POST', body:{ file_id:fileId } });
            fileLibrarySelectedIds.delete(fileId);
            await fileLibraryLoadState({ silent:true, reset:true });
            if(typeof toast === 'function') toast(kbT('library.files.moved_to_trash', null, 'Moved to the recycle bin'));
          }finally{
            fileLibrarySetActionBusy(false);
            fileLibraryUpdateBulkBar();
          }
        }, btn);
      });
    });
    fileLibraryUpdateBulkBar();
  }

  async function fileLibraryLoadState({ silent=false, reset=true } = {}){
    kbEnsureDom();
    const loadingList = document.getElementById('fileLibraryList');
    if(loadingList && (!Array.isArray(kbRuntime.fileLibrary?.files) || !kbRuntime.fileLibrary.files.length) && typeof AppLoadingUi !== 'undefined'){
        AppLoadingUi.render(loadingList, { variant:'list', rows:5, label:kbT('library.loading_files', null, 'Loading files') });
    }
    try{
      const data = await fileLibraryApi(fileLibraryStateUrl(0));
      kbRuntime.fileLibrary = data || {};
      if(reset) fileLibraryResetSelection();
      renderFileLibraryState();
      return data;
    }catch(err){
      const list = document.getElementById('fileLibraryList');
      if(list){
        if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(list);
        list.innerHTML = kbRenderEmptyState({ icon:'warning', title:kbT('library.load_failed', null, 'Unable to load the library'), desc:String(err.message || err || kbT('common.operation_failed', null, 'Operation failed')), tip:kbT('library.retry', null, 'Try again later.') });
      }
      if(!silent && typeof reportAppError === 'function') reportAppError(kbT('library.load_failed_detail', {error:err.message}, 'Unable to load the library: {error}'));
      return {};
    }
  }

  async function fileLibraryLoadMore(){
    if(fileLibraryActionBusy || fileLibraryLoadingMore) return;
    const state = kbRuntime.fileLibrary || {};
    const page = state.page || {};
    if(!page.has_more) return;
    const offset = Number(page.next_offset ?? (Array.isArray(state.files) ? state.files.length : 0)) || 0;
    const btn = document.getElementById('fileLibraryLoadMoreBtn');
    const oldText = btn?.textContent || kbT('library.load_more', null, 'Load more');
    fileLibraryLoadingMore = true;
    if(btn){ btn.disabled = true; btn.textContent = kbT('library.loading_more', null, 'Loading…'); }
    try{
      const data = await fileLibraryApi(fileLibraryStateUrl(offset));
      const oldFiles = Array.isArray(kbRuntime.fileLibrary?.files) ? kbRuntime.fileLibrary.files : [];
      const nextFiles = Array.isArray(data.files) ? data.files : [];
      const seen = new Set(oldFiles.map(item => String(item?.file_id || '').trim()).filter(Boolean));
      const merged = oldFiles.concat(nextFiles.filter(item => {
        const id = String(item?.file_id || '').trim();
        if(!id || seen.has(id)) return false;
        seen.add(id);
        return true;
      }));
      kbRuntime.fileLibrary = { ...(data || {}), files: merged };
      renderFileLibraryState();
    }catch(err){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.load_more_failed', {error:err.message}, `Unable to load more files: ${err.message}`));
      if(btn){ btn.disabled = false; btn.textContent = oldText; }
    }finally{
      fileLibraryLoadingMore = false;
    }
  }


  async function fileLibraryUploadFiles(fileList){
    const files = Array.from(fileList || []).filter(Boolean);
    if(!files.length) return;
    let okCount = 0;
    let failCount = 0;
    const operation=kbT('library.upload.operation.files',null,'File upload');
    fileLibrarySetProgress(kbT('library.upload.progress',{operation,current:0,total:files.length},`${operation}: 0 / ${files.length}`));
    try{
      for(let i = 0; i < files.length; i++){
        const file = files[i];
        fileLibrarySetProgress(kbT('library.upload.progress_file',{operation,current:i+1,total:files.length,name:file?.name||''},`${operation}: ${i+1} / ${files.length} · ${file?.name||''}`));
        try{
          await uploadOneFileRequest(file, null);
          okCount += 1;
        }catch(err){
          failCount += 1;
          console.warn('file library upload failed', file?.name, err);
        }
      }
    }finally{
      const input = document.getElementById('fileLibraryUploadInput');
      if(input) input.value = '';
    }
    await fileLibraryLoadState({ silent:true });
    fileLibrarySetProgress(failCount?kbT('library.upload.complete_partial',{operation,success:okCount,failed:failCount,skipped:''},`${operation} complete: ${okCount} succeeded, ${failCount} failed`):'');
    if(failCount){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.upload.partial_failed',{operation,success:okCount,failed:failCount},`${operation} partially failed: ${okCount} succeeded, ${failCount} failed`));
    }else{
      if(typeof toast === 'function') toast(kbT('library.upload_complete', null, 'Upload complete'));
    }
  }

  async function kbApi(path, { method='GET', body=null } = {}){
    const init = { method, headers:{} };
    if(body != null){
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    let data = {};
    try{ data = await res.json(); }catch(_){ }
    if(!res.ok){
      const localized=typeof normalizeCompactErrorText==='function'?normalizeCompactErrorText(data):'';
      const err=new Error(localized||data?.error||data?.message||(`HTTP ${res.status}`));
      err.code=String(data?.code||data?.error_code||'');
      err.params=data?.params&&typeof data.params==='object'?data.params:{};
      throw err;
    }
    return data;
  }

  function kbRenderEmptyState({ icon='empty', title='', desc='', tip='' } = {}){
    return `
      <div class="kb-empty-state">
        <div class="kb-empty-card">
          <div class="kb-empty-icon">${kbUiIcon(icon)}</div>
          <strong>${escapeHtml(title || '')}</strong>
          <p>${escapeHtml(desc || '')}</p>
          ${tip ? `<div class="kb-empty-tip">${escapeHtml(tip)}</div>` : ''}
        </div>
      </div>`;
  }

  function kbCurrentSpaceId(){
    const ui = getKnowledgeBaseUiSettings();
    const state = kbRuntime.state || {};
    return String(ui.activeSpaceId || state?.active_space?.id || '').trim();
  }

  function kbSetImportProgress(text=''){
    const el = document.getElementById('kbImportProgress');
    if(el) el.textContent = String(text || '');
  }

  function kbCloseAddMenu(){
    const wrap = document.getElementById('kbAddWrap');
    const btn = document.getElementById('kbAddMenuBtn');
    if(wrap) wrap.classList.remove('open');
    if(btn) btn.setAttribute('aria-expanded', 'false');
  }

  function kbToggleAddMenu(){
    const wrap = document.getElementById('kbAddWrap');
    const btn = document.getElementById('kbAddMenuBtn');
    if(!wrap || !btn) return;
    const open = !wrap.classList.contains('open');
    wrap.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function kbOpenImportDialog(mode='text'){
    kbImportDialogMode = mode === 'url' ? 'url' : 'text';
    const mask = document.getElementById('kbImportMask');
    const title = document.getElementById('kbImportDialogTitle');
    const desc = document.getElementById('kbImportDialogDesc');
    const titleInput = document.getElementById('kbImportTitleInput');
    const urlField = document.getElementById('kbImportUrlField');
    const urlInput = document.getElementById('kbImportUrlInput');
    const textField = document.getElementById('kbImportTextField');
    const textInput = document.getElementById('kbImportTextInput');
    const isUrlMode = kbImportDialogMode === 'url';
    if(title) title.textContent=kbT(isUrlMode?'library.import_dialog.url_title':'library.import_dialog.text_title',null,isUrlMode?'Add webpage':'Add text');
    if(desc) desc.textContent=kbT(isUrlMode?'library.import_dialog.url_desc':'library.import_dialog.text_desc',null,isUrlMode?'Enter a webpage URL to retrieve and index its content.':'Save pasted content as a knowledge-base document.');
    if(titleInput) titleInput.value = '';
    if(urlInput){
      urlInput.value = '';
      urlInput.disabled = !isUrlMode;
      urlInput.tabIndex = isUrlMode ? 0 : -1;
    }
    if(textInput){
      textInput.value = '';
      textInput.disabled = isUrlMode;
      textInput.tabIndex = isUrlMode ? -1 : 0;
    }
    if(mask){
      mask.classList.remove('kb-import-mode-url', 'kb-import-mode-text');
      mask.classList.add(isUrlMode ? 'kb-import-mode-url' : 'kb-import-mode-text');
    }
    if(urlField){
      urlField.hidden = !isUrlMode;
      urlField.classList.toggle('is-hidden', !isUrlMode);
      urlField.setAttribute('aria-hidden', isUrlMode ? 'false' : 'true');
      urlField.style.setProperty('display', isUrlMode ? 'grid' : 'none', isUrlMode ? '' : 'important');
    }
    if(textField){
      textField.hidden = isUrlMode;
      textField.classList.toggle('is-hidden', isUrlMode);
      textField.setAttribute('aria-hidden', isUrlMode ? 'true' : 'false');
      textField.style.setProperty('display', isUrlMode ? 'none' : 'grid', isUrlMode ? 'important' : '');
    }
    if(mask){
      mask.classList.add('open');
      mask.setAttribute('aria-hidden', 'false');
    }
    setTimeout(()=>{ try{ (isUrlMode ? urlInput : textInput)?.focus?.(); }catch(_){ } }, 0);
  }

  function kbCloseImportDialog(){
    const mask = document.getElementById('kbImportMask');
    if(mask){
      mask.classList.remove('open', 'kb-import-mode-url', 'kb-import-mode-text');
      mask.setAttribute('aria-hidden', 'true');
    }
    const urlInput = document.getElementById('kbImportUrlInput');
    const textInput = document.getElementById('kbImportTextInput');
    if(urlInput){ urlInput.disabled = false; urlInput.tabIndex = 0; }
    if(textInput){ textInput.disabled = false; textInput.tabIndex = 0; }
  }

  async function kbHandleImportConfirm(){
    const titleInput = document.getElementById('kbImportTitleInput');
    const urlInput = document.getElementById('kbImportUrlInput');
    const textInput = document.getElementById('kbImportTextInput');
    const btn = document.getElementById('kbImportConfirmBtn');
    const oldText = btn ? btn.textContent : '';
    const title = String(titleInput?.value || '').trim();
    const spaceId = kbCurrentSpaceId();
    let body = { title, space_id:spaceId };
    let path = '/api3/kb/import-text';
    if(kbImportDialogMode === 'url'){
      const url = String(urlInput?.value || '').trim();
      if(!url){ try{ urlInput?.focus(); }catch(_){ } return; }
      path = '/api3/kb/import-url';
      body.url = url;
      try{
        if(typeof getWebSettings === 'function'){
          body.web_settings = getWebSettings();
        }
      }catch(_){ }
    }else{
      const text = String(textInput?.value || '').trim();
      if(!text){ try{ textInput?.focus(); }catch(_){ } return; }
      body.text = text;
    }
    const isUrlMode=kbImportDialogMode==='url';
    if(btn){btn.disabled=true;btn.textContent=kbT(isUrlMode?'library.import_dialog.reading':'library.import_dialog.importing',null,isUrlMode?'Reading…':'Importing…');}
    kbSetImportProgress(kbT(isUrlMode?'library.import_dialog.url_progress':'library.import_dialog.text_progress',null,isUrlMode?'Retrieving and indexing the webpage…':'Saving and indexing the text…'));
    try{
      const data = await kbApi(path, { method:'POST', body });
      kbCloseImportDialog();
      await kbLoadState({ preferSpaceId:String(data?.space?.id || data?.state?.active_space?.id || spaceId || '') });
      kbSetImportProgress('');
      if(typeof toast === 'function') toast(kbT('library.knowledge_added', null, 'Knowledge added'));
      if(typeof setStatus === 'function') setStatus(kbT('library.knowledge_added',null,'Knowledge added'));
    }catch(err){
      kbSetImportProgress('');
      if(typeof reportAppError === 'function') reportAppError(kbT('library.import_dialog.failed',{error:err.message},`Knowledge import failed: ${err.message}`));
    }finally{
      if(btn){btn.disabled=false;btn.textContent=oldText||kbT('library.import_dialog.import',null,'Import');}
    }
  }

  function kbUploadFileIsImage(file){
    const mime = String(file?.type || '').trim().toLowerCase();
    if(mime.startsWith('image/')) return true;
    const name = String(file?.name || '').trim().toLowerCase();
    const ext = name.includes('.') ? name.split('.').pop() : '';
    return KB_IMAGE_EXTENSIONS.has(ext);
  }

  function kbRenderLoadingState(variant='list', rows=4, label=kbT('common.loading',null,'Loading…')){
    if(typeof AppLoadingUi !== 'undefined' && typeof AppLoadingUi.html === 'function'){
      return AppLoadingUi.html({ variant, rows, label });
    }
    return kbRenderEmptyState({icon:'loading',title:label,desc:kbT('library.loading_desc',null,'Retrieving data. This may take a moment.')});
  }

  async function kbUploadFilesToCurrentSpace(fileList, { mode='file' } = {}){
    const selectedFiles = Array.from(fileList || []).filter(Boolean);
    const blockedImages = selectedFiles.filter(kbUploadFileIsImage);
    const files = selectedFiles.filter(file => !kbUploadFileIsImage(file));
    if(!files.length){
      const fileInput = document.getElementById('kbUploadFileInput');
      const dirInput = document.getElementById('kbUploadDirInput');
      if(fileInput) fileInput.value = '';
      if(dirInput) dirInput.value = '';
      if(blockedImages.length && typeof toast === 'function') toast(kbT('library.images_upload_from_files', null, 'Images stay in the library. Upload them from the Files page.'));
      return;
    }
    const spaceId = kbCurrentSpaceId();
    const operationKey=mode==='sync_folder'?'sync_folder':(mode==='folder'?'folder':'files');
    const operation=kbT(`library.upload.operation.${operationKey}`,null,mode==='sync_folder'?'Folder sync':(mode==='folder'?'Folder upload':'File upload'));
    let okCount = 0;
    let failCount = 0;
    window.__kbUploadImportOverride = { enabled:true, spaceId };
    kbSetImportProgress(kbT('library.upload.progress',{operation,current:0,total:files.length},`${operation}: 0 / ${files.length}`));
    try{
      for(let i = 0; i < files.length; i++){
        const file = files[i];
        const name=file?.webkitRelativePath||file?.name||'';
        kbSetImportProgress(kbT('library.upload.progress_file',{operation,current:i+1,total:files.length,name},`${operation}: ${i+1} / ${files.length} · ${name}`));
        try{
          await uploadOneFileRequest(file, null);
          okCount += 1;
        }catch(err){
          failCount += 1;
          console.warn('kb import upload failed', file?.name, err);
        }
      }
    }finally{
      try{ delete window.__kbUploadImportOverride; }catch(_){ window.__kbUploadImportOverride = null; }
      const fileInput = document.getElementById('kbUploadFileInput');
      const dirInput = document.getElementById('kbUploadDirInput');
      if(fileInput) fileInput.value = '';
      if(dirInput) dirInput.value = '';
    }
    await kbLoadState({ preferSpaceId:spaceId });
    const skippedText=blockedImages.length?kbT('library.upload.skipped_suffix',{count:blockedImages.length},` · ${blockedImages.length} images skipped`):'';
    kbSetImportProgress(failCount
      ?kbT('library.upload.complete_partial',{operation,success:okCount,failed:failCount,skipped:skippedText},`${operation} complete: ${okCount} succeeded, ${failCount} failed${skippedText}`)
      :(blockedImages.length?kbT('library.upload.complete_skipped',{operation,success:okCount,skipped:skippedText},`${operation} complete: ${okCount} succeeded${skippedText}`):''));
    if(failCount){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.upload.partial_failed',{operation,success:okCount,failed:failCount},`${operation} partially failed: ${okCount} succeeded, ${failCount} failed`));
    }else{
      const doneText=blockedImages.length
        ?kbT('library.upload.success_skipped',{operation,count:blockedImages.length},`${operation} succeeded; ${blockedImages.length} images skipped`)
        :kbT('library.upload.success',{operation},`${operation} succeeded`);
      if(typeof toast === 'function') toast(doneText);
      if(typeof setStatus === 'function') setStatus(doneText);
    }
  }

  function kbDocsForDisplay(docs){
    const ui = getKnowledgeBaseUiSettings();
    const filter = String(ui.docFilter || '').trim().toLowerCase();
    const sort = String(ui.docSort || 'updated_desc').trim() || 'updated_desc';
    let rows = Array.isArray(docs) ? docs.slice() : [];
    if(filter){
      rows = rows.filter(doc => [doc?.filename, doc?.ext, doc?.note, doc?.parse_status, doc?.source].some(v => String(v || '').toLowerCase().includes(filter)));
    }
    rows.sort((a,b)=>{
      if(sort === 'name_asc') return String(a?.filename || '').localeCompare(String(b?.filename || ''), 'zh-Hans-CN');
      if(sort === 'chunks_desc') return (Number(b?.chunk_count || 0) - Number(a?.chunk_count || 0)) || String(a?.filename || '').localeCompare(String(b?.filename || ''), 'zh-Hans-CN');
      if(sort === 'size_desc') return (Number(b?.size_bytes || 0) - Number(a?.size_bytes || 0)) || String(a?.filename || '').localeCompare(String(b?.filename || ''), 'zh-Hans-CN');
      return String(b?.updated_at || '').localeCompare(String(a?.updated_at || '')) || String(b?.created_at || '').localeCompare(String(a?.created_at || ''));
    });
    return rows;
  }

  function kbOpenCreateDialog(){
    kbEnsureDom();
    const mask = document.getElementById('kbCreateMask');
    const input = document.getElementById('kbCreateNameInput');
    if(mask){
      mask.classList.add('open');
      mask.setAttribute('aria-hidden', 'false');
    }
    if(input){
      input.value = '';
      setTimeout(()=>{ try{ input.focus(); }catch(_){ } }, 0);
    }
  }

  function kbCloseCreateDialog(){
    const mask = document.getElementById('kbCreateMask');
    if(mask){
      mask.classList.remove('open');
      mask.setAttribute('aria-hidden', 'true');
    }
  }

  function kbRefreshModeStats(){
    const ui = getKnowledgeBaseUiSettings();
    const modeEl = document.getElementById('kbStatMode');
    const subEl = document.getElementById('kbStatModeSub');
    if(modeEl) modeEl.textContent = ui.chatUseKnowledgeBase !== false
      ? kbT('library.kb.mode_priority', null, 'Knowledge base first')
      : kbT('library.kb.mode_standard', null, 'Standard chat');
    if(subEl) subEl.textContent = ui.chatUseKnowledgeBase !== false
      ? kbT('library.kb.mode_priority_sub', null, 'Search knowledge first')
      : kbT('library.kb.mode_on_demand', null, 'Search as needed');
  }

  function syncKbControlsFromSettings(){
    const ui = getKnowledgeBaseUiSettings();
    const chatEl = document.getElementById('kbChatUseToggle');
    if(chatEl) chatEl.checked = ui.chatUseKnowledgeBase !== false;
    kbRefreshModeStats();
  }

  function renderKbState(){
    if(kbActiveLibraryTab() === 'files'){ renderFileLibraryState(); return; }
    const state = kbRuntime.state || {};
    const statLabels = Array.from(document.querySelectorAll('#kbModalMask .kb-stat-label'));
    if(statLabels[0]) statLabels[0].textContent = kbT('library.kb.stat_current', null, 'Current knowledge base');
    if(statLabels[1]) statLabels[1].textContent = kbT('library.kb.stat_documents', null, 'Document volume');
    if(statLabels[2]) statLabels[2].textContent = kbT('library.kb.stat_chunks', null, 'Searchable chunks');
    if(statLabels[3]) statLabels[3].textContent = kbT('library.kb.stat_mode', null, 'Chat mode');
    const ui = getKnowledgeBaseUiSettings();
    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    const docs = Array.isArray(state.documents) ? state.documents : [];
    const active = state.active_space || {};
    const activeDoc = kbResolveActiveDoc(state, ui);
    const displayDocs = kbDocsForDisplay(docs);
    const docFilterInput = document.getElementById('kbDocFilterInput');
    const docSortSelect = document.getElementById('kbDocSortSelect');
    if(docFilterInput && docFilterInput.value !== String(ui.docFilter || '')) docFilterInput.value = String(ui.docFilter || '');
    if(docSortSelect) docSortSelect.value = String(ui.docSort || 'updated_desc') || 'updated_desc';
    const select = document.getElementById('kbSpaceSelect');
    const docSummary = document.getElementById('kbDocSummary');
    const headSummary = document.getElementById('kbHeadSummary');
    const list = document.getElementById('kbDocList');
    const activeName = document.getElementById('kbActiveSpaceName');
    const activeMeta = document.getElementById('kbActiveSpaceMeta');
    const statDocs = document.getElementById('kbStatDocs');
    const statChunks = document.getElementById('kbStatChunks');
    const searchBadge = document.getElementById('kbSearchBadge');
    const deleteSpaceBtn = document.getElementById('kbDeleteSpaceBtn');
    if(deleteSpaceBtn){
      const activeSpaceId = String(active?.id || '').trim();
      const deletingSpaceId = String(kbRuntime.deletingSpaceId || '').trim();
      const isDeletingSpace = !!deletingSpaceId && deletingSpaceId === activeSpaceId;
      const canDeleteSpace = !!activeSpaceId && !Boolean(active?.is_default);
      deleteSpaceBtn.disabled = isDeletingSpace || !canDeleteSpace;
      deleteSpaceBtn.textContent = isDeletingSpace
        ? kbT('library.kb.deleting', null, 'Deleting…')
        : kbT('library.kb.delete', null, 'Delete');
      deleteSpaceBtn.title = canDeleteSpace
        ? kbT('library.kb.delete_current', null, 'Delete current knowledge base')
        : kbT('library.kb.default_not_deletable', null, 'The default knowledge base cannot be deleted.');
    }
    if(select){
      select.innerHTML = '';
      for(const space of spaces){
        const opt = document.createElement('option');
        opt.value = String(space?.id || '');
        opt.textContent = kbT('library.kb.space_option', {
          name:kbDisplaySpaceName(space, 'library.kb.untitled_name'),
          documents:kbCountLabel('documents', space?.doc_count),
        }, `${space?.name || '未命名知识库'} · ${Number(space?.doc_count || 0)} 个文档`);
        select.appendChild(opt);
      }
      const target = String(ui.activeSpaceId || active?.id || spaces[0]?.id || '').trim();
      if(target) select.value = target;
    }
    const activeNameText = kbDisplaySpaceName(active);
    const docCount = Number(active?.doc_count || 0);
    const chunkCount = Number(active?.chunk_count || 0);
    const countSummary = kbT('library.kb.summary', {
      name:activeNameText,
      documents:kbCountLabel('documents', docCount),
      chunks:kbCountLabel('chunks', chunkCount),
    }, `${activeNameText} · ${docCount} 个文档 · ${chunkCount} 个片段`);
    if(docSummary){
      const filterText = String(ui.docFilter || '').trim();
      const baseSummary = activeDoc
        ? kbT('library.kb.summary_active_document', {
            summary:countSummary,
            document:activeDoc.filename || kbT('library.kb.untitled_document', null, '未命名文档'),
          }, `${countSummary} · 当前文档《${activeDoc.filename || '未命名文档'}》`)
        : countSummary;
      docSummary.textContent = filterText && docs.length
        ? kbT('library.kb.summary_filtered', {summary:baseSummary, count:displayDocs.length}, `${baseSummary} · 当前筛选 ${displayDocs.length} 项`)
        : baseSummary;
    }
    if(headSummary){
      headSummary.textContent = activeDoc
        ? kbT('library.kb.head_active_document', {
            name:activeNameText,
            document:activeDoc.filename || kbT('library.kb.untitled_document', null, '未命名文档'),
          }, `${activeNameText} · 当前文档《${activeDoc.filename || '未命名文档'}》`)
        : kbT('library.kb.head_summary', {name:activeNameText}, `${activeNameText} · 文档检索与问答`);
    }
    if(activeName) activeName.textContent = activeNameText;
    if(activeMeta) activeMeta.textContent = `${kbCountLabel('documents', docCount)} · ${kbCountLabel('chunks', chunkCount)}`;
    if(statDocs) statDocs.textContent = String(docCount);
    if(statChunks) statChunks.textContent = String(chunkCount);
    if(searchBadge) searchBadge.textContent = docs.length
      ? kbT('library.kb.importable', null, 'Searchable')
      : kbT('library.kb.ready_for_import', null, 'Ready for import');
    if(list){
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(list);
      if(!docs.length){
        list.innerHTML = kbRenderEmptyState({
          icon:'files',
          title:kbT('library.kb.empty_title', null, 'No documents yet'),
          desc:kbT('library.kb.empty_desc', null, 'Upload a supported document, add a webpage, or paste text to index content here.'),
          tip:kbT('library.kb.empty_tip', null, 'Images remain in the library and are not indexed for knowledge-base search.')
        });
      }else if(!displayDocs.length){
        list.innerHTML = kbRenderEmptyState({
          icon:'empty',
          title:kbT('library.kb.no_match_title', null, 'No content found'),
          desc:kbT('library.kb.no_match_desc', null, 'No documents match the current search.'),
          tip:String(ui.docFilter || '').trim() ? kbT('library.kb.filter_tip', {query:String(ui.docFilter || '').trim()}, 'Search: {query}') : ''
        });
      }else{
        list.innerHTML = displayDocs.map(doc => {
          const ext = escapeHtml(String(doc.ext || '').replace(/^\./,'').toUpperCase() || 'FILE');
          const parseStatus = escapeHtml(doc.parse_status || 'indexed');
          const docId = String(doc.id || '').trim();
          const isActiveDoc = !!activeDoc && String(activeDoc.id || '').trim() === docId;
          const tags = [
            `<span class="kb-doc-tag">${ext}</span>`,
            `<span class="kb-doc-tag">${fmtBytes(Number(doc.size_bytes || 0))}</span>`,
            `<span class="kb-doc-tag">${escapeHtml(kbT('library.kb.chunk_tag', {count:Number(doc.chunk_count || 0)}, `${Number(doc.chunk_count || 0)} 个片段`))}</span>`,
            isActiveDoc ? `<span class="kb-doc-tag">${escapeHtml(kbT('library.kb.current_document', null, 'Current document'))}</span>` : ''
          ].filter(Boolean).join('');
          return `
            <article class="kb-doc-card${isActiveDoc ? ' active' : ''}">
              <div class="kb-doc-top">
                <div>
                  <div class="kb-doc-name">${escapeHtml(doc.filename || '')}</div>
                  <div class="kb-doc-meta">${escapeHtml(doc.updated_at || '')}</div>
                </div>
                <span class="kb-doc-status">${parseStatus}</span>
              </div>
              <div class="kb-doc-tags">${tags}</div>
              <div class="kb-doc-actions">
                <button type="button" data-kb-activate-doc="${escapeHtml(docId)}">${escapeHtml(isActiveDoc ? kbT('library.kb.clear_current', null, 'Clear current') : kbT('library.kb.set_current', null, 'Set as current'))}</button>
                ${doc.download_url ? `<a class="kb-hit-actions" href="${escapeHtml(doc.download_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(kbT('library.download', null, 'Download'))}</a>` : ''}
                <button type="button" data-kb-delete-doc="${escapeHtml(docId)}">${escapeHtml(kbT('common.delete', null, 'Delete'))}</button>
              </div>
            </article>`;
        }).join('');
        list.querySelectorAll('[data-kb-activate-doc]').forEach(btn => {
          btn.addEventListener('click', ()=>{
            const docId = String(btn.getAttribute('data-kb-activate-doc') || '').trim();
            if(!docId) return;
            const currentUi = getKnowledgeBaseUiSettings();
            const nextDocId = String(currentUi.activeDocId || '').trim() === docId ? '' : docId;
            saveKnowledgeBaseUiSettings({ ...currentUi, activeDocId: nextDocId });
            renderKbState();
            if(typeof setStatus === 'function') setStatus(nextDocId
              ? kbT('library.kb.document_locked', null, 'Current knowledge-base document selected')
              : kbT('library.kb.all_documents', null, 'Searching the whole knowledge base'));
          });
        });
        list.querySelectorAll('[data-kb-delete-doc]').forEach(btn => {
          btn.addEventListener('click', async ()=>{
            const docId = String(btn.getAttribute('data-kb-delete-doc') || '').trim();
            if(!docId) return;
            await askKbDangerAction({
              title:kbT('library.kb.document_delete_title', null, 'Delete this document?'),
              desc:kbT('library.kb.document_delete_desc', null, 'This deletes one knowledge-base document and its search index. If the local file is no longer used elsewhere, it moves to the recycle bin.'),
              confirmText:kbT('common.delete', null, 'Delete'),
              cancelText:kbT('common.cancel', null, 'Cancel'),
              variant:'danger',
              busyText:kbT('common.deleting', null, 'Deleting…'),
              errorPrefix:kbT('library.kb.document_delete_failed', null, 'Unable to delete the knowledge-base document')
            }, async ()=>{
              await kbApi('/api3/kb/document-delete', { method:'POST', body:{ doc_id:docId, space_id:String(active?.id || '') } });
              const currentUi = getKnowledgeBaseUiSettings();
              if(String(currentUi.activeDocId || '').trim() === docId){
                saveKnowledgeBaseUiSettings({ ...currentUi, activeDocId:'' });
              }
              await kbLoadState({ preferSpaceId:String(active?.id || '') });
              if(typeof setStatus === 'function') setStatus(kbT('library.kb.document_deleted', null, 'Knowledge-base document deleted; the eligible local file was moved to the recycle bin.'));
            }, btn);
          });
        });
      }
    }
    syncKbControlsFromSettings();
  }

  function renderKbSearchResults(){
    const wrap = document.getElementById('kbSearchResults');
    const metaHint = document.getElementById('kbSearchMetaHint');
    const searchBadge = document.getElementById('kbSearchBadge');
    if(!wrap) return;
    if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(wrap);
    const result = kbRuntime.search || {};
    const items = Array.isArray(result.results) ? result.results : [];
    const queryText = String(result.query || '').trim();
    const activeDoc = result?.active_document && typeof result.active_document === 'object' ? result.active_document : kbResolveActiveDoc(kbRuntime.state || {}, getKnowledgeBaseUiSettings());
    if(!items.length){
      wrap.innerHTML = kbRenderEmptyState({
        icon: queryText ? 'empty' : 'search',
        title: queryText
          ? kbT('library.kb.no_results', null, 'No results')
          : kbT('library.kb.no_results_yet', null, 'No results yet'),
        desc: queryText
          ? kbT('library.kb.no_results_desc', null, 'Try another question or confirm that the relevant document is indexed.')
          : kbT('library.kb.no_results_yet_desc', null, 'Matching chunks appear here after you enter a question.'),
        tip: queryText ? kbT('library.kb.search.latest', {query:queryText}, `最近一次：${queryText}`) : ''
      });
      if(metaHint) metaHint.textContent = queryText
        ? (activeDoc
            ? kbT('library.kb.search.active_latest', {document:activeDoc.filename || kbT('library.kb.untitled_document', null, '未命名文档'), query:queryText}, `当前文档：${activeDoc.filename || '未命名文档'} · 最近一次：${queryText}`)
            : kbT('library.kb.search.latest', {query:queryText}, `最近一次：${queryText}`))
        : (activeDoc
            ? kbT('library.kb.search.active_document', {document:activeDoc.filename || kbT('library.kb.untitled_document', null, '未命名文档')}, `当前文档：${activeDoc.filename || '未命名文档'}`)
            : kbT('library.kb.search_hint', null, 'Results appear after you enter a question.'));
      if(searchBadge) searchBadge.textContent = queryText
        ? kbT('library.kb.search.hits', {count:0}, '0 matches')
        : (activeDoc ? kbT('library.kb.document_locked_badge', null, 'Document selected') : kbT('library.kb.ready_for_import', null, 'Ready for import'));
      return;
    }
    if(metaHint) metaHint.textContent = queryText
      ? (activeDoc
          ? kbT('library.kb.search.active_latest', {document:activeDoc.filename || kbT('library.kb.untitled_document', null, '未命名文档'), query:queryText}, `当前文档：${activeDoc.filename || '未命名文档'} · 最近一次：${queryText}`)
          : kbT('library.kb.search.latest', {query:queryText}, `最近一次：${queryText}`))
      : kbT('library.kb.search.result_count', {count:items.length}, `已返回 ${items.length} 条结果`);
    if(searchBadge) searchBadge.textContent = activeDoc
      ? kbT('library.kb.search.hits_document', {count:items.length}, `${items.length} 命中 · 文档内`)
      : kbT('library.kb.search.hits', {count:items.length}, `${items.length} 命中`);
    wrap.innerHTML = items.map((item, idx)=> `
      <article class="kb-hit-card">
        <div class="kb-hit-top">
          <div>
            <div class="kb-hit-name">${idx + 1}. ${escapeHtml(item.filename || kbT('library.unnamed_file', null, 'Untitled file'))}</div>
            <div class="kb-hit-meta">${escapeHtml(kbT('library.kb.search.chunk_score', {chunk:Number(item.chunk_order || 0) + 1, score:Number(item.score || 0).toFixed(2)}, `片段 ${Number(item.chunk_order || 0) + 1} · 分数 ${Number(item.score || 0).toFixed(2)}`))}</div>
          </div>
          <div class="kb-score-pill">${escapeHtml(kbT('library.kb.search.score', null, '分数'))}<strong>${Number(item.score || 0).toFixed(2)}</strong></div>
        </div>
        <div class="kb-cite">[${escapeHtml(kbT('library.kb.search.citation', null, '知识库引用'))}: ${escapeHtml(item.citation_label || '')}]</div>
        <div class="kb-hit-snippet">${escapeHtml(item.text || '')}</div>
        <div class="kb-doc-actions">
          ${item.view_url ? `<a class="kb-hit-actions" href="${escapeHtml(item.view_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(kbT('library.kb.view_source', null, 'View source file'))}</a>` : ''}
        </div>
      </article>`).join('');
  }

  async function kbLoadState({ preferSpaceId='' } = {}){
    kbEnsureDom();
    kbRuntime.loading = true;
    const loadingList = document.getElementById('kbDocList');
    if(loadingList && (!Array.isArray(kbRuntime.state?.documents) || !kbRuntime.state.documents.length) && typeof AppLoadingUi !== 'undefined'){
      AppLoadingUi.render(loadingList, { variant:'list', rows:4, label:kbT('library.kb.loading_documents', null, 'Loading documents') });
    }
    const ui = getKnowledgeBaseUiSettings();
    const targetSpaceId = String(preferSpaceId || ui.activeSpaceId || '').trim();
    try{
      const data = await kbApi(`/api3/kb/state${targetSpaceId ? `?space_id=${encodeURIComponent(targetSpaceId)}` : ''}`);
      kbRuntime.state = data || {};
      kbRuntime.loaded = true;
      const activeSpaceId = String(data?.active_space?.id || targetSpaceId || '').trim();
      const nextDocId = kbNormalizeActiveDocId(Array.isArray(data?.documents) ? data.documents : [], ui.activeDocId || '');
      if(activeSpaceId !== String(ui.activeSpaceId || '').trim() || nextDocId !== String(ui.activeDocId || '').trim()){
        saveKnowledgeBaseUiSettings({ ...ui, activeSpaceId, activeDocId: nextDocId });
      }
      renderKbState();
    }catch(err){
      const list = document.getElementById('kbDocList');
      if(list){
        if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(list);
        list.innerHTML = kbRenderEmptyState({
          icon:'warning',
          title:kbT('library.load_failed', null, 'Unable to load the library'),
          desc:String(err.message || err || kbT('common.operation_failed', null, 'Operation failed')),
          tip:kbT('library.retry', null, 'Try again later.'),
        });
      }
      if(typeof reportAppError === 'function') reportAppError(kbT('library.kb.load_failed', {error:err.message}, 'Unable to load the knowledge base: {error}'));
    }finally{
      kbRuntime.loading = false;
    }
  }

  async function kbRunSearch(){
    kbEnsureDom();
    const input = document.getElementById('kbSearchInput');
    const q = String(input?.value || '').trim();
    if(!q){
      kbRuntime.search = { results:[], query:'' };
      renderKbSearchResults();
      return;
    }
    const wrap = document.getElementById('kbSearchResults');
    const metaHint = document.getElementById('kbSearchMetaHint');
    const searchBadge = document.getElementById('kbSearchBadge');
    if(wrap){
      if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.render(wrap, { variant:'list', rows:4, label:kbT('library.kb.search_loading', null, 'Searching the knowledge base') });
      else wrap.innerHTML = kbRenderEmptyState({
        icon:'loading',
        title:kbT('library.kb.search_loading_title', null, 'Searching…'),
        desc:kbT('library.kb.search_loading_desc', null, 'Retrieving relevant chunks.'),
        tip:`${q}`,
      });
    }
    const activeDoc = kbResolveActiveDoc(kbRuntime.state || {}, getKnowledgeBaseUiSettings());
    if(metaHint) metaHint.textContent = activeDoc
      ? kbT('library.kb.search.searching_document', {document:activeDoc.filename || kbT('library.kb.untitled_document', null, '未命名文档'), query:q}, `正在检索《${activeDoc.filename || '未命名文档'}》：${q}`)
      : kbT('library.kb.search.searching', {query:q}, `正在检索：${q}`);
    if(searchBadge) searchBadge.textContent = activeDoc
      ? kbT('library.kb.search.searching_document_badge', null, '文档检索中')
      : kbT('library.kb.search.searching_badge', null, '检索中');
    const ui = getKnowledgeBaseUiSettings();
    try{
      kbRuntime.search = await kbApi('/api3/kb/search', { method:'POST', body:{ query:q, space_id:String(ui.activeSpaceId || '').trim(), doc_id:String(ui.activeDocId || '').trim() } });
      kbRuntime.search = { ...(kbRuntime.search || {}), query:q };
      renderKbSearchResults();
    }catch(err){
      if(wrap){
        if(typeof AppLoadingUi !== 'undefined') AppLoadingUi.ready(wrap);
        wrap.innerHTML = kbRenderEmptyState({
          icon:'warning',
          title:kbT('library.kb.search_failed_title', null, 'Search failed'),
          desc:String(err.message || err || kbT('common.operation_failed', null, 'Operation failed')),
          tip:kbT('library.retry', null, 'Try again later.'),
        });
      }
      if(typeof reportAppError === 'function') reportAppError(kbT('library.kb.search_failed', {error:err.message}, 'Knowledge-base search failed: {error}'));
    }
  }

  async function kbHandleCreateSpace(){
    kbEnsureDom();
    const input = document.getElementById('kbCreateNameInput');
    const name = String(input?.value || '').trim();
    if(!name){
      try{ input?.focus(); }catch(_){ }
      return;
    }
    try{
      const data = await kbApi('/api3/kb/space-create', { method:'POST', body:{ name } });
      const nextSpaceId = String(data?.space?.id || '').trim();
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), activeSpaceId: nextSpaceId });
      kbCloseCreateDialog();
      await kbLoadState({ preferSpaceId: nextSpaceId });
      if(typeof setStatus === 'function') setStatus(kbT('library.kb.created', null, 'Knowledge base created'));
    }catch(err){
      if(typeof reportAppError === 'function') reportAppError(kbT('library.kb.create_failed', {error:err.message}, 'Unable to create the knowledge base: {error}'));
    }
  }

  async function kbDeleteCurrentSpace(){
    kbEnsureDom();
    if(String(kbRuntime.deletingSpaceId || '').trim()) return;
    const state = kbRuntime.state || {};
    const active = state.active_space || {};
    const spaceId = String(active?.id || '').trim();
    const spaceName = String(active?.name || kbT('library.kb.current_name', null, 'Current knowledge base')).trim() || kbT('library.kb.current_name', null, 'Current knowledge base');
    if(!spaceId){
      if(typeof toast === 'function') toast(kbT('library.kb.none_deletable', null, 'There is no knowledge base to delete.'));
      return;
    }
    if(Boolean(active?.is_default)){
      if(typeof toast === 'function') toast(kbT('library.kb.default_not_deletable', null, 'The default knowledge base cannot be deleted.'));
      return;
    }
    const docCount = Number(active?.doc_count || 0);
    const ok = await askKbDangerConfirm({
      title:kbT('library.kb.delete_title', null, 'Delete this knowledge base?'),
      desc:kbT('library.kb.delete_desc', {name:spaceName, count:docCount}, `This will delete “${spaceName}” and its ${docCount} documents.`),
      confirmText:kbT('common.delete', null, 'Delete'),
      cancelText:kbT('common.cancel', null, 'Cancel')
    }, document.getElementById('kbDeleteSpaceBtn'));
    if(!ok) return;
    kbRuntime.deletingSpaceId = spaceId;
    renderKbState();
    try{
      const data = await kbApi('/api3/kb/space-delete', { method:'POST', body:{ space_id:spaceId } });
      const nextSpaceId = String(data?.next_space_id || data?.state?.active_space?.id || '').trim();
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), activeSpaceId: nextSpaceId, activeDocId:'' });
      kbRuntime.search = { results:[], query:'' };
      await kbLoadState({ preferSpaceId: nextSpaceId });
      renderKbSearchResults();
      if(typeof setStatus === 'function') setStatus(data?.already_deleted
        ? kbT('library.kb.already_deleted', null, 'The knowledge base no longer exists. The list has been refreshed.')
        : kbT('library.kb.deleted', null, 'Knowledge base deleted'));
    }catch(err){
      await kbLoadState().catch(()=>{});
      if(typeof reportAppError === 'function') reportAppError(kbT('library.kb.delete_failed', {error:err.message}, 'Unable to delete the knowledge base: {error}'));
    }finally{
      if(String(kbRuntime.deletingSpaceId || '').trim() === spaceId){
        kbRuntime.deletingSpaceId = '';
      }
      renderKbState();
    }
  }

  async function kbClearCurrentSpace(){
    kbEnsureDom();
    const state = kbRuntime.state || {};
    const active = state.active_space || {};
    const docs = Array.isArray(state.documents) ? state.documents : [];
    const activeSpaceId = String(active?.id || '').trim();
    if(!docs.length){
      if(typeof toast === 'function') toast(kbT('library.kb.no_documents', null, 'The current knowledge base has no documents.'));
      return;
    }
    const ok = await askKbDangerConfirm({
      title:kbT('library.kb.clear_title', null, 'Clear the current knowledge base?'),
      desc:kbT('library.kb.clear_desc', {count:docs.length}, `This will delete ${docs.length} documents.`),
      confirmText:kbT('common.confirm', null, 'Confirm'),
      cancelText:kbT('common.cancel', null, 'Cancel')
    }, document.getElementById('kbClearSpaceBtn'));
    if(!ok) return;
    const clearBtn = document.getElementById('kbClearSpaceBtn');
    const oldText = clearBtn ? clearBtn.textContent : '';
    if(clearBtn){
      clearBtn.disabled = true;
      clearBtn.textContent = kbT('library.kb.clearing', null, 'Clearing…');
    }
    try{
      for(const doc of docs){
        const docId = String(doc?.id || '').trim();
        if(!docId) continue;
        await kbApi('/api3/kb/document-delete', { method:'POST', body:{ doc_id:docId, space_id:activeSpaceId } });
      }
      const currentUi = getKnowledgeBaseUiSettings();
      saveKnowledgeBaseUiSettings({ ...currentUi, activeDocId:'' });
      kbRuntime.search = { results:[], query:'' };
      await kbLoadState({ preferSpaceId: activeSpaceId });
      renderKbSearchResults();
      if(typeof setStatus === 'function') setStatus(kbT('library.kb.cleared', null, 'Current knowledge base cleared'));
      if(typeof toast === 'function') toast(kbT('library.kb.cleared', null, 'Current knowledge base cleared'));
    }catch(err){
      if(clearBtn){
        clearBtn.disabled = false;
        clearBtn.textContent = oldText || kbT('library.kb.clear', null, 'Clear');
      }
      if(typeof reportAppError === 'function') reportAppError(kbT('library.kb.clear_failed', {error:err.message}, 'Unable to clear the knowledge base: {error}'));
    }
  }

  window.getKnowledgeBaseUiSettings = getKnowledgeBaseUiSettings;
  window.saveKnowledgeBaseUiSettings = saveKnowledgeBaseUiSettings;

  function kbSetWorkspaceVisibility(open){
    const visible = !!open;
    const modal = document.getElementById('kbModalMask');
    const main = document.getElementById('main');
    const sidebarButton = document.getElementById('openKnowledgeBaseSidebar');
    if(visible && typeof window.closeImagePullbackWorkspace === 'function') window.closeImagePullbackWorkspace();
    if(modal){
      modal.classList.toggle('open', visible);
      modal.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }
    document.body?.classList.toggle('library-open', visible);
    document.querySelectorAll('#workspace > :not(#kbModalMask), #main > .topbar, #main > .composer').forEach((el)=>{
      if(visible){
        if(!el.hasAttribute('data-library-prev-inert')) el.setAttribute('data-library-prev-inert', el.inert ? '1' : '0');
        el.inert = true;
      }else{
        const previous = el.getAttribute('data-library-prev-inert');
        if(previous != null){
          el.inert = previous === '1';
          el.removeAttribute('data-library-prev-inert');
        }
      }
    });
    main?.classList.toggle('library-page-open', visible);
    sidebarButton?.classList.remove('active');
    sidebarButton?.classList.toggle('is-active', visible);
    if(visible) sidebarButton?.setAttribute('aria-current', 'page');
    else sidebarButton?.removeAttribute('aria-current');
  }

  window.openKnowledgeBaseModal = async function openKnowledgeBaseModal(opts={}){
    const preserveActiveChatJob = !!opts?.preserveActiveChatJob || activeChatJobInProgress();
    const routeTab = opts?.libraryTab || getRouteLibraryTab() || kbActiveLibraryTab();
    const routeFileType = String(opts?.fileType || getRouteLibraryFileType?.() || getKnowledgeBaseUiSettings().fileType || 'all').trim().toLowerCase() || 'all';
    if(routeTab === 'knowledge' || routeTab === 'files'){
      saveKnowledgeBaseUiSettings({ ...getKnowledgeBaseUiSettings(), libraryTab: routeTab, fileType:routeFileType });
    }
    if(opts?.syncRoute !== false) syncLibraryRoute(kbActiveLibraryTab(), { replace:!!opts?.replaceRoute, returnUrl:opts?.returnUrl || '', fileType:routeFileType });
    if(preserveActiveChatJob) keepActiveChatJobAlive('library_modal_open');
    kbEnsureDom();
    syncKbControlsFromSettings();
    kbSetWorkspaceVisibility(true);
    kbRefreshLibraryTabVisibility();
    if(kbActiveLibraryTab() === 'files') await fileLibraryLoadState({ silent:true });
    else await kbLoadState();
    if(preserveActiveChatJob){
      keepActiveChatJobAlive('library_modal_loaded');
      return;
    }
    if(kbActiveLibraryTab() === 'files'){
      try{ document.getElementById('fileLibraryFilterInput')?.focus(); }catch(_){ }
    }else{
      try{ document.getElementById('kbSearchInput')?.focus(); }catch(_){ }
    }
  };

  window.closeKnowledgeBaseModal = function closeKnowledgeBaseModal(opts={}){
    const preserveActiveChatJob = !!opts?.preserveActiveChatJob || activeChatJobInProgress();
    kbCloseCreateDialog();
    kbCloseImportDialog();
    kbCloseAddMenu();
    kbSetWorkspaceVisibility(false);
    if(opts?.syncRoute !== false && getRouteLibraryTab()) restoreLibraryReturnRoute({ replace:opts?.replaceRoute !== false });
    if(preserveActiveChatJob) keepActiveChatJobAlive('library_modal_close');
  };

  document.addEventListener('keydown', (e)=>{
    if(e.key === 'Escape') fileLibraryCloseRowMenus();
    if(e.key !== 'Escape') return;
    if(document.getElementById('kbCreateMask')?.classList.contains('open')){
      kbCloseCreateDialog();
      return;
    }
    if(document.getElementById('kbImportMask')?.classList.contains('open')){
      kbCloseImportDialog();
      return;
    }
  });

  kbEnsureDom();
  document.addEventListener('click', ()=> fileLibraryCloseRowMenus());
  document.addEventListener('scroll', ()=> fileLibraryCloseRowMenus(), true);
  window.addEventListener('resize', ()=> fileLibraryCloseRowMenus());
  document.addEventListener('apervia:languagechange', ()=>{
    kbRefreshLibraryTabVisibility();
    if(kbActiveLibraryTab() === 'files') renderFileLibraryState();
    else renderKbState();
  });
  kbRefreshLibraryTabVisibility();
  applyModalRouteFromLocation({ initial:true });
})();

/* Shared rendering, artifact preview, AI title, reasoning panel and stable async helpers.*/
function reasoningUiT(key, params=null, fallback=''){
  return window.AperviaI18n?.t(key, params || {}, fallback) || String(fallback || key || '');
}

function escapeHtml(s){
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

}

const CODE_HTML_ENTITY_RE = /&(?:amp|lt|gt|quot|apos|nbsp|#0*39|#x0*27);/i;
let _htmlEntityDecodeTextarea = null;
function decodeHtmlEntities(text){
  const raw = String(text ?? '');
  if(!raw || raw.indexOf('&') < 0) return raw;
  try{
    if(!_htmlEntityDecodeTextarea) _htmlEntityDecodeTextarea = document.createElement('textarea');
    _htmlEntityDecodeTextarea.innerHTML = raw;
    return String(_htmlEntityDecodeTextarea.value || '').replace(/ /g, ' ');
  }catch(_){
    return raw;
  }
}


function normalizeAssistantSourceFaviconUrl(value){
  const raw = String(value || '').trim();
  if(!raw) return '';
  try{
    if(raw.startsWith('//')){
      return `${window.location.protocol}${raw}`;
    }
    const abs = new URL(raw, window.location.origin).href;
    return /^https?:\/\//i.test(abs) ? abs : '';
  }catch(_){
    return '';
  }
}

function normalizeRunnableCodeSource(text){
  let src = String(text ?? '').replace(/\r\n?/g, '\n');
  let loops = 0;
  while(loops < 2 && CODE_HTML_ENTITY_RE.test(src)){
    const next = decodeHtmlEntities(src);
    if(next === src) break;
    src = next;
    loops += 1;
  }
  return src;
}

const SESSION_TITLE_MIN_DISPLAY_UNITS = 12;
const SESSION_TITLE_MAX_DISPLAY_UNITS = 24;
const SESSION_TITLE_MIN_MEANINGFUL_COMPACT_CHARS = 3;
const SESSION_TITLE_MODEL_MAX_RETRIES = 2;

function sessionTitleCharUnits(ch){
  const s = String(ch || '');
  if(!s) return 0;
  if(/\s/u.test(s)) return 0.5;
  if(/[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/u.test(s)) return 2;
  if(/[\u4E00-\u9FFF\u3400-\u4DBF\u3040-\u30FF\uAC00-\uD7AF]/u.test(s)) return 2;
  if(/[\uFF01-\uFF60\uFFE0-\uFFE6]/u.test(s)) return 2;
  return 1;
}

function sessionTitleDisplayUnits(text){
  let total = 0;
  for(const ch of [...String(text || '')]) total += sessionTitleCharUnits(ch);
  return total;
}

function sessionTitleCompactLength(text){
  return [...String(text || '').replace(/\s+/g, '')].length;
}

function sessionTitleLooksMeaningful(text){
  const s = String(text || '').trim();
  if(!s) return false;
  const compactLen = sessionTitleCompactLength(s);
  if(/[\u4E00-\u9FFF\u3400-\u4DBF\u3040-\u30FF\uAC00-\uD7AF]/u.test(s)) return compactLen >= 4;
  return compactLen >= SESSION_TITLE_MIN_MEANINGFUL_COMPACT_CHARS;
}

function sessionTitleTrimTail(text){
  return String(text || '')
    .replace(/[\s]+$/u, '')
    .replace(/[，,；;：:、。！？!?\-—_./]+$/u, '')
    .trim();
}

function sessionTitleNormalize(text){
  return sessionTitleTrimTail(String(text || '')
    .replace(/[\r\n]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim());
}

function sessionTitleHasQuestionTone(text){
  const s = sessionTitleNormalize(text);
  if(!s) return false;
  return /^(帮我|请问|怎么|如何|可以|能不能|可不可以|why|how|what|can i|could i|should i)\b/iu.test(s)
    || /(吗|呢|呀|吧|\?|？)$/u.test(s);
}

function sessionTitleHasTruncatedFeel(text){
  const s = sessionTitleNormalize(text);
  if(!s) return false;
  if(/[“”"'《》「」『』【】]/u.test(s)) return true;
  if(/[，,；;：:、\-—_/]$/u.test(s)) return true;
  return /(?:^|[\u4E00-\u9FFF])(?:的|了|和|与|及|或|而|并|让|把|将|给|在|对|向|比|按|从|为|跟|用|有)$/u.test(s);
}

function sessionTitleHasMetaLeak(text){
  const s = sessionTitleNormalize(text);
  if(!s) return false;
  if(/```|^\{.*\}$|^\[.*\]$|https?:\/\//i.test(s)) return true;
  if(/^(标题|会话标题|题目|title)[:：\s]/iu.test(s)) return true;
  if(/^(当然可以|好的|下面|这里是|以下是|sure|here(?:'s| is)|the title is)\b/iu.test(s)) return true;
  if(/(用户首条消息|助手首轮回答|输出标题|只输出|严格控制|长度要求|previous title|retry|修正要求)/iu.test(s)) return true;
  if(/(回复我选项|选项如下|代码如下|如下代码|请看下面|参考如下)/u.test(s)) return true;
  return false;
}

function sessionTitleValidateCandidate(text){
  const s = sessionTitleNormalize(text);
  const units = sessionTitleDisplayUnits(s);
  const reasons = [];
  if(!sessionTitleLooksMeaningful(s)) reasons.push('not_meaningful');
  if(units < SESSION_TITLE_MIN_DISPLAY_UNITS) reasons.push('too_short');
  if(units > SESSION_TITLE_MAX_DISPLAY_UNITS) reasons.push('too_long');
  if(sessionTitleHasQuestionTone(s)) reasons.push('question_tone');
  if(sessionTitleHasTruncatedFeel(s)) reasons.push('truncated_feel');
  if(sessionTitleHasMetaLeak(s)) reasons.push('meta_leak');
  return { ok: reasons.length === 0, title: s, units, reasons };
}

function sessionTitleRetryHint(info){
  const reasons = Array.isArray(info?.reasons) ? info.reasons : [];
  if(reasons.includes('too_long')) return '上一个标题偏长。请改写成更凝练但完整的自然短标题，不能截断。';
  if(reasons.includes('too_short')) return '上一个标题过短。请补足成完整自然标题，仍必须控制在目标长度内。';
  if(reasons.includes('question_tone')) return '上一个标题仍像提问句。请改成陈述式主题标题。';
  if(reasons.includes('truncated_feel')) return '上一个标题像残句。请改成完整自然语言标题，不要半句话。';
  if(reasons.includes('meta_leak')) return '上一个输出带有解释、前缀、回复腔或提示词残留。请只输出最终标题本身。';
  return '请直接重写成自然、完整、长度合格的最终标题。';
}

function sessionTitleTryParseJsonTitle(raw){
  const s = String(raw || '').trim();
  if(!s) return '';
  const candidates = [s];
  const codeBlockMatch = s.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if(codeBlockMatch && codeBlockMatch[1]) candidates.push(String(codeBlockMatch[1] || '').trim());
  for(const item of candidates){
    try{
      const obj = JSON.parse(item);
      const title = String(obj?.title || obj?.name || '').trim();
      if(title) return title;
    }catch(_){ }
  }
  return '';
}

function sessionTitleStripLeadPhrases(text){
  let s = String(text || '').trim();
  for(let i = 0; i < 3; i++){
    const prev = s;
    s = s
      .replace(/^```(?:json)?\s*([\s\S]*?)\s*```$/iu, '$1')
      .replace(/^\s*(?:(?:[-*•]+|\d{1,2}[.)、])\s*)?(标题|会话标题|题目|title)[:：\s]+/iu, '')
      .replace(/^\s*(?:(?:[-*•]+|\d{1,2}[.)、])\s*)?(最终标题|建议标题|推荐标题|候选标题)[:：\s]+/u, '')
      .replace(/^\s*(?:(?:[-*•]+|\d{1,2}[.)])\s*)?(?:the )?title is[:：\s]+/iu, '')
      .replace(/^\s*(?:(?:[-*•]+|\d{1,2}[.)])\s*)?(?:here(?:'s| is) (?:the )?title)[:：\s]*/iu, '')
      .replace(/^(当然可以|好的|下面|这里是|以下是|sure|okay|alright)[:：，,\s]+/iu, '')
      .trim();
    if(s === prev) break;
  }
  return s;
}

function normalizeTitleLen(raw){
  let s = sessionTitleTryParseJsonTitle(raw) || String(raw ?? '');
  s = sessionTitleStripLeadPhrases(s);
  s = s.replace(/^['"“”‘’]+|['"“”‘’]+$/g, '');
  s = s.replace(/[\r\n]+/g, '\n');
  const firstNonEmptyLine = s.split(/\n+/).map(x => String(x || '').trim()).find(Boolean) || '';
  s = firstNonEmptyLine || s;
  s = s.replace(/https?:\/\/\S+/g, ' ');
  s = s.replace(/`+/g, ' ');
  s = s.replace(/\s+/g, ' ').trim();
  s = s.replace(/[。！？!?：:;；、]+$/g, '');
  return sessionTitleNormalize(s);
}

const SESSION_TITLE_FALLBACK_NOISE_RE = /^(帮我|请问|怎么|如何|可以|能不能|可不可以|麻烦|请你|我想问下|我想问一下|我发现|我觉得|现在|目前|这个|这个问题|这段代码|这个报错|这个页面|这个功能|当然可以|好的|下面|这里是|以下是|sure|okay|alright)\s*/iu;

function sessionTitleFallbackFragments(text){
  let raw = String(text || '').trim();
  if(!raw) return [];
  raw = raw
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\uFFFC/g, ' ')
    .replace(/[\r\n]+/g, '\n')
    .replace(/\s+/g, ' ')
    .trim();
  const rows = [];
  const push = (value) => {
    let s = String(value || '').trim();
    if(!s) return;
    s = s.replace(SESSION_TITLE_FALLBACK_NOISE_RE, '').trim();
    s = s.replace(/^(用户首条消息|助手首轮回答)[:：\s]+/u, '').trim();
    s = s.replace(/[。！？!?]+$/g, '').trim();
    s = sessionTitleNormalize(s);
    if(!s || rows.includes(s)) return;
    rows.push(s);
  };
  push(raw);
  for(const line of raw.split(/\n+/)) push(line);
  for(const part of raw.split(/[。！？!?；;\n]+/)) push(part);
  for(const part of raw.split(/[，,：:、]/)) push(part);
  return rows;
}

function generateTitleFromText(text){
  const parts = sessionTitleFallbackFragments(text);
  for(const item of parts){
    const verdict = sessionTitleValidateCandidate(item);
    if(verdict.ok) return verdict.title;
  }
  return '新会话';
}

// ====== AI Title (ChatGPT-like) ======
const AI_TITLE_KEY = "webai_ai_title_v1";
let AI_TITLE_ENABLED = true;

function initAiTitleUI(){
  if(!aiTitleToggleEl) return;
  try{
    const saved = localStorage.getItem(AI_TITLE_KEY);
    if(saved === "0") AI_TITLE_ENABLED = false;
    if(saved === "1") AI_TITLE_ENABLED = true;
  }catch(e){}
  aiTitleToggleEl.checked = !!AI_TITLE_ENABLED;
  aiTitleToggleEl.addEventListener("change", (e)=>{
    AI_TITLE_ENABLED = !!e.target.checked;
    try{ localStorage.setItem(AI_TITLE_KEY, AI_TITLE_ENABLED ? "1" : "0"); }catch(_){ }
    try{ if(typeof toast === "function") toast(window.AperviaI18n?.t(AI_TITLE_ENABLED ? 'nav.ai_title_on' : 'nav.ai_title_off') || (AI_TITLE_ENABLED ? 'AI titles: On' : 'AI titles: Off')); }catch(_){ }
  });
}

const pendingAiTitleJobs = new Map();

function isDefaultSessionTitle(title){
  const t = String(title || '').trim();
  return !t || t === '新会话' || t === 'chat->V-VPI' || t === 'chat->V-api';
}

function extractImageReplyTitleSeedText(content){
  const data = content && typeof content === 'object' ? content : {};
  const explicitText = String(data.text || data.answer || '').trim();
  if(explicitText) return explicitText;
  const subject = titleSeedCleanText(data.subject || data.prompt || '', 280);
  const images = Array.isArray(data.images) ? data.images : [];
  const imageCount = images.length;
  const operation = String(data.operation || data.task_mode || '').toLowerCase();
  const actionText = /edit|编辑|modify|variation/.test(operation) ? '已完成图片编辑' : '已完成图片生成';
  if(subject) return actionText + '：' + subject;
  if(imageCount > 0) return actionText + '，共' + imageCount + '张图片';
  return actionText;
}

function extractMessageTitleText(msg){
  if(!msg || !msg.content) return '';
  const content = msg.content;
  let txt = '';
  if(typeof content === 'string') txt = content;
  else if(Array.isArray(content)){
    txt = content
      .filter(x => x && x.type === 'text' && x.text)
      .map(x => x.text)
      .join(' ');
  }else if(content && typeof content === 'object'){
    if(typeof content.text === 'string' && content.text.trim()) txt = content.text;
    else if(typeof content.answer === 'string' && content.answer.trim()) txt = content.answer;
    else if(String(content._kind || '').trim() === 'image_reply') txt = extractImageReplyTitleSeedText(content);
    else if(String(content._kind || '').trim() === 'genfiles') txt = '已生成文件';
    else if(String(content._kind || '').trim() === 'weather') txt = '已更新天气信息';
    else if(String(content._kind || '').trim() === 'memory_event') txt = String(content.title || content.text || '已更新记忆');
  }
  return String(txt || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\uFFFC/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractSessionTitleFirstTurnMessages(session){
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const firstAssistantIdx = messages.findIndex(m => m && m.role === 'assistant');
  return messages.slice(0, firstAssistantIdx >= 0 ? firstAssistantIdx : messages.length);
}

function titleSeedCleanText(text, limit=520){
  let s = String(text || '')
    .replace(/\r\n?/g, '\n')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/下载链接[:：][\s\S]*$/u, ' ')
    .replace(/^以下是用户上传文件《[^》]+》的内容，请在后续对话中参考[:：]?\s*/u, '')
    .replace(/^用户上传了一个文件《[^》]+》[^\n。]*[。.]?\s*/u, '')
    .replace(/\s+/g, ' ')
    .trim();
  const maxLen = Math.max(80, Number(limit || 520) || 520);
  if(s.length > maxLen) s = s.slice(0, maxLen).trim() + '…';
  return s;
}

function titleSeedCleanAssistantText(text, limit=760){
  let s = String(text || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\uFFFC/g, ' ');

  // 标题种子只需要最终主题；代码正文、下载区和后台过程会让命名变泛或跑偏。
  // 这里仅清理标题任务的输入，不影响聊天正文、reasoning 展示或工具链路。
  s = s
    .replace(/```[\s\S]*?```/g, ' 代码内容 ')
    .replace(/~~~[\s\S]*?~~~/g, ' 代码内容 ')
    .replace(/下载链接[:：][\s\S]*$/u, ' ')
    .replace(/(?:^|\n)\s*(?:工具结果摘要|工具调用|工具运行|function_call_output|tool_result)[:：\s（][^\n]*(?=\n|$)/giu, '\n')
    .replace(/(?:^|\n)\s*(?:来源|参考来源|Sources?|References?)[:：]\s*https?:\/\/[^\n]*(?=\n|$)/giu, '\n')
    .replace(/\[[^\]\n]{0,80}\]\(sandbox:\/[^)]+\)/giu, ' ')
    .replace(/sandbox:\/\S+/giu, ' ')
    .replace(/https?:\/\/\S+/g, ' ');

  const rows = [];
  const seen = new Set();
  for(const rawLine of s.split(/\n+/)){
    let line = String(rawLine || '')
      .replace(/^\s*(?:[-*•]+|\d{1,2}[.)、])\s+/u, '')
      .replace(/\s+/g, ' ')
      .trim();
    if(!line) continue;
    if(/^(?:已生成文件|生成文件已完成|文件已生成|已更新天气信息|已更新记忆|记忆已更新|下载|Download)[:：]?$/iu.test(line)) continue;
    if(/^(?:下载|Download|附件|文件列表|生成文件|Sources?|References?|参考来源|来源)[:：]/iu.test(line)) continue;
    const key = line.toLowerCase();
    if(seen.has(key)) continue;
    seen.add(key);
    rows.push(line);
    if(rows.length >= 8) break;
  }

  s = rows.join(' ')
    .replace(/\s+/g, ' ')
    .trim();

  if(/^(?:已生成文件|已更新天气信息|已更新记忆|代码内容)$/u.test(s)) return '';
  const maxLen = Math.max(160, Number(limit || 760) || 760);
  if(s.length > maxLen) s = s.slice(0, maxLen).trim() + '…';
  return s;
}

function extractUserFileTitleContextFromSession(session){
  const firstTurn = extractSessionTitleFirstTurnMessages(session);
  const linkedNotes = new Map();
  for(const m of firstTurn){
    if(!m || m.role !== 'system' || !m._link) continue;
    const note = titleSeedCleanText(m.content || '', 520);
    if(note) linkedNotes.set(String(m._link), note);
  }

  const rows = [];
  const seen = new Set();
  for(const m of firstTurn){
    if(!m || m.role !== 'user') continue;
    const content = m.content;
    if(!content || typeof content !== 'object' || Array.isArray(content) || content._kind !== 'file') continue;

    const filename = String(content.filename || '').trim();
    const fileId = String(content.id || '').trim();
    const ext = String(content.ext || '').trim();
    const dedupKey = fileId || `${filename}|${ext}`;
    if(!filename || seen.has(dedupKey)) continue;
    seen.add(dedupKey);

    const parts = [`文件名：${filename}`];
    if(ext) parts.push(`类型：${ext}`);
    const note = titleSeedCleanText(content.note || '', 180);
    if(note) parts.push(`备注：${note}`);
    const codeSummary = titleSeedCleanText(content.code_summary || '', 260);
    if(codeSummary) parts.push(`摘要：${codeSummary}`);
    const symbols = Array.isArray(content.symbols) ? content.symbols.map(x => String(x || '').trim()).filter(Boolean).slice(0, 10) : [];
    if(symbols.length) parts.push(`符号：${symbols.join('、')}`);
    const linked = fileId ? linkedNotes.get(fileId) : '';
    if(linked) parts.push(`内容：${linked}`);

    rows.push(parts.join('；'));
    if(rows.length >= 8) break;
  }
  return rows.join('\n');
}

function extractFirstUserTextFromSession(session){
  const firstTurn = extractSessionTitleFirstTurnMessages(session);
  for(const m of firstTurn){
    if(!m || m.role !== 'user' || !m.content) continue;
    const text = extractMessageTitleText(m);
    if(text) return text;
  }
  return '';
}

function extractFirstAssistantTextFromSession(session){
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  for(const m of messages){
    if(!m || m.role !== 'assistant' || !m.content) continue;
    const text = titleSeedCleanAssistantText(extractMessageTitleText(m));
    if(text) return text;
  }
  return '';
}

function buildSessionTitleSeedContext(session){
  const firstUserCoreText = extractFirstUserTextFromSession(session);
  const fileContextText = extractUserFileTitleContextFromSession(session);
  const firstAssistantText = extractFirstAssistantTextFromSession(session);
  const userContextParts = [];
  if(firstUserCoreText) userContextParts.push(`用户文本：${firstUserCoreText}`);
  if(fileContextText) userContextParts.push(`用户附件：\n${fileContextText}`);
  const firstUserText = userContextParts.join('\n').trim();
  const fallbackSeedText = firstUserCoreText || fileContextText || firstUserText;
  const heuristicSeedText = (`用户首轮上下文：${firstUserText}\n\n助手首轮回答：${firstAssistantText}`).trim();
  const aiSeedText = heuristicSeedText;
  return {
    firstUserText,
    firstUserCoreText,
    fileContextText,
    firstAssistantText,
    fallbackSeedText,
    heuristicSeedText,
    aiSeedText,
    hasAssistantSeed: !!firstAssistantText,
  };
}

function maybeSeedSessionHeuristicTitle(session){
  if(!session || session.titleAutoLocked) return '';
  const ctx = buildSessionTitleSeedContext(session);
  if(!ctx.hasAssistantSeed) return '';
  const fallbackTitle = generateTitleFromText(ctx.fallbackSeedText || ctx.firstUserText || '');
  if(fallbackTitle && isDefaultSessionTitle(session.title)){
    session.title = fallbackTitle;
  }
  return ctx.aiSeedText;
}

function requestAiTitleForSession(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid) return Promise.resolve('');
  const existing = pendingAiTitleJobs.get(sid);
  if(existing) return existing;

  const session = getSessionById(sid);
  if(!session || isTemporarySession(session) || !AI_TITLE_ENABLED || session.titleAutoLocked || session.aiTitleDone) return Promise.resolve('');

  const ctx = buildSessionTitleSeedContext(session);
  if(!ctx.firstUserText || !ctx.hasAssistantSeed) return Promise.resolve('');

  const heuristicTitle = generateTitleFromText(ctx.fallbackSeedText || ctx.firstUserText || '');
  const baselineTitle = String(session.title || '').trim();
  const model = String(session.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL;

  const job = (async () => {
    let raw = '';
    let finalTitle = '';
    let verdict = { ok:false, title:'', units:0, reasons:['unknown'] };
    for(let attempt = 0; attempt <= SESSION_TITLE_MODEL_MAX_RETRIES; attempt++){
      raw = await fetchTitleByAI({
        firstUserText: ctx.firstUserText,
        firstAssistantText: ctx.firstAssistantText,
        seedText: ctx.aiSeedText,
      }, model, {
        attempt,
        previousTitle: finalTitle || raw,
        retryHint: sessionTitleRetryHint(verdict),
      }).catch(() => '');
      finalTitle = normalizeTitleLen(raw);
      verdict = sessionTitleValidateCandidate(finalTitle);
      if(verdict.ok) break;
    }
    if(!verdict.ok){
      finalTitle = normalizeTitleLen(heuristicTitle);
      verdict = sessionTitleValidateCandidate(finalTitle);
    }
    if(!verdict.ok){
      finalTitle = '新会话';
    }

    await updateSessionById(sid, s => {
      if(!s || s.titleAutoLocked) return;
      const replaceable = isDefaultSessionTitle(s.title)
        || String(s.title || '').trim() === String(baselineTitle || '').trim()
        || String(s.title || '').trim() === String(heuristicTitle || '').trim();
      if(!replaceable) return;
      const finalVerdict = sessionTitleValidateCandidate(finalTitle);
      s.aiTitleDone = !!finalVerdict.ok;
      if(finalVerdict.ok && finalVerdict.title && finalVerdict.title !== s.title){
        s.title = finalVerdict.title;
      }
    }, { skipCompress:true });
    return finalTitle;
  })().catch(() => '').finally(() => {
    pendingAiTitleJobs.delete(sid);
  });

  pendingAiTitleJobs.set(sid, job);
  return job;
}

function queueAiTitleAfterReply(sessionId){
  const sid = String(sessionId || '').trim();
  if(!sid || !AI_TITLE_ENABLED) return Promise.resolve('');
  return requestAiTitleForSession(sid).catch(() => '');
}

function normalizeStreamStatusText(text){
  const s = String(text || "").trim();
  if(!s) return "";
  const t=(key,params,fallback)=>window.AperviaI18n?.t(key,params,fallback)||fallback;
  const exactKey={
    '完成':'stream.done','已完成':'stream.done','已停止':'stream.stopped','连接中断':'stream.connection_interrupted',
    '出错':'stream.error','内容已更新':'stream.content_updated','天气已更新':'stream.weather_updated',
    '思考中…':'stream.thinking','正在思考中':'stream.thinking','就绪':'stream.ready',
  }[s];
  if(exactKey) return t(exactKey,null,s);
  if(s==='文件已生成，正在整理回复…') return t('stream.file_generated_reply',null,'File generated; preparing the response…');
  if(s==='正在处理文件…') return t('stream.processing_files',null,'Processing files…');
  if(/交付文件|生成文件|写入文件|文件已生成/.test(s)) return window.AperviaI18n?.phrase(s)||s;
  if(/等待响应|如果一直卡住/.test(s)) return t('stream.connecting_model',null,'Connecting to the model…');
  if(/当前模型/.test(s)) return s.replace(/（快速模式）/, "").replace(/（代理模式）/, "");
  if(/正在生成图片|生成图片中/.test(s)) return t('stream.generating_image',null,'Generating image…');
  if(/正在编辑图片|编辑图片中/.test(s)) return t('stream.editing_image',null,'Editing image…');
  if(/图片已返回.*加载/.test(s)) return t('stream.loading_image',null,'Image received; loading…');
  if(/抓网中|联网搜索|正在搜索/.test(s)) return t('stream.searching',null,'Searching…');
  if(/读取网页|抓取网页|读取链接/.test(s)) return t('stream.reading_webpage',null,'Reading webpage…');
  if(/生成回复中|生成回答|正在回答/.test(s)) return t('stream.generating_answer',null,'Generating answer…');
  if(/思考中/.test(s)) return t('stream.thinking',null,'Thinking…');
  return window.AperviaI18n?.phrase(s)||s;
}


function _normalizePendingAssistantReasoning(list){
  const out = [];
  const seen = new Set();
  for(const raw of (Array.isArray(list) ? list : [])){
    if(!raw || typeof raw !== 'object') continue;
    const title = String(raw.title || raw.text || '').trim().slice(0, 180);
    const detail = String(raw.detail || '').trim().slice(0, 260);
    const stage = String(raw.stage || 'think').trim() || 'think';
    const stateRaw = String(raw.state || '').trim().toLowerCase();
    const state = /^(active|done|warn|error)$/.test(stateRaw) ? stateRaw : 'done';
    const queries = (Array.isArray(raw.queries) ? raw.queries : [])
      .map(q => String(q || '').trim())
      .filter(Boolean);
    const key = String(raw.key || `${stage}|${title}|${detail}|${queries.join('|')}`).trim().slice(0, 500);
    if(!title || !key || seen.has(key)) continue;
    seen.add(key);
    out.push({
      key,
      title,
      detail,
      stage,
      state,
      queries,
      ts: Number(raw.ts || 0) || 0,
      text: String(raw.text || title || '').trim().slice(0, 260),
    });
    if(out.length >= 18) break;
  }
  return out;
}

function _normalizeReasoningSearchResultItems(items, limit=0){
  const out = [];
  const seen = new Set();
  const parsedLimit = Number(limit || 0) || 0;
  const maxItems = parsedLimit > 0 ? Math.max(1, parsedLimit) : Number.POSITIVE_INFINITY;
  const rows = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const pickUrl = (item)=> trimUrl(
    item.url || item.href || item.link || item.uri ||
    item.source_url || item.sourceUrl || item.page_url || item.pageUrl ||
    item.canonical_url || item.canonicalUrl || ''
  );
  const pickTitle = (item, rawUrl, host)=> normalizeAssistantSourceTitle(
    item.title || item.label || item.name || item.site_name || item.siteName || item.source || item.provider || '',
    rawUrl,
    host
  );
  const pickSnippet = (item)=> String(item.snippet || item.summary || item.description || item.text || item.content || '').trim();
  const pickFavicon = (item)=> normalizeAssistantSourceFaviconUrl(item.favicon || item.icon || item.iconUrl || item.icon_url || '');
  const pushOne = (item)=>{
    if(!item || typeof item !== 'object') return;
    const citation = item.url_citation && typeof item.url_citation === 'object' ? item.url_citation : null;
    const src = citation || item;
    const rawUrl = pickUrl(src);
    if(!isAssistantVisibleCitationUrl(rawUrl)) return;
    const host = String(src.host || src.domain || getAssistantSourceHost(rawUrl) || '').trim().toLowerCase().replace(/^www\./i, '');
    const title = pickTitle(src, rawUrl, host);
    const favicon = pickFavicon(src);
    const snippet = pickSnippet(src);
    const key = `url:${rawUrl.toLowerCase()}`;
    if(seen.has(key)) return;
    seen.add(key);
    out.push({
      title: String(title || host || rawUrl).slice(0, 160),
      url: rawUrl.slice(0, 500),
      host: host.slice(0, 120),
      favicon: favicon.slice(0, 500),
    });
  };
  for(const row of rows){
    if(out.length >= maxItems) break;
    pushOne(row);
  }
  return out.slice(0, maxItems);
}

const REASONING_WEB_SOURCE_ITEMS_LIMIT = 24;
function _reasoningWebSourceItemsLimit(){
  const configured = Number((typeof window !== 'undefined' && window.WEBAI_ACTIVITY_SOURCE_ITEMS_LIMIT) || REASONING_WEB_SOURCE_ITEMS_LIMIT) || REASONING_WEB_SOURCE_ITEMS_LIMIT;
  return Math.max(4, Math.min(configured, 48));
}
function _normalizeReasoningWebSourceItems(items, limit){
  const maxItems = Math.max(1, Math.min(Number(limit || _reasoningWebSourceItemsLimit()) || _reasoningWebSourceItemsLimit(), 48));
  return _normalizeReasoningSearchResultItems(items || [], maxItems);
}

function _normalizeReasoningNativeWebCallItems(items, limit=12){
  const out = [];
  const seen = new Set();
  const maxItems = Math.max(1, Math.min(Number(limit || 12) || 12, 20));
  const stateMap = {
    completed: 'done', complete: 'done', done: 'done', success: 'done', succeeded: 'done',
    error: 'error', failed: 'error', cancelled: 'warn', canceled: 'warn',
    searching: 'active', running: 'active', in_progress: 'active', pending: 'active', queued: 'active',
  };
  const labelMap = {
    completed: '原生搜索已完成', complete: '原生搜索已完成', done: '原生搜索已完成', success: '原生搜索已完成', succeeded: '原生搜索已完成',
    error: '原生搜索出错', failed: '原生搜索出错', cancelled: '原生搜索已取消', canceled: '原生搜索已取消',
    searching: '原生搜索执行中', running: '原生搜索执行中', in_progress: '原生搜索已发起', pending: '原生搜索等待中', queued: '原生搜索排队中',
  };
  const rows = Array.isArray(items) ? items : [];
  for(const raw of rows){
    if(!raw || typeof raw !== 'object') continue;
    const id = String(raw.id || raw.item_id || raw.callId || raw.call_id || '').trim();
    const shortId = String(raw.short_id || raw.shortId || id).trim().slice(-10);
    const status = String(raw.status || raw.state_raw || raw.event_state || raw.event || '').trim().toLowerCase();
    const stateRaw = String(raw.state || '').trim().toLowerCase();
    const state = /^(active|done|warn|error)$/.test(stateRaw) ? stateRaw : (stateMap[status] || 'active');
    const queries = (Array.isArray(raw.queries) ? raw.queries : [])
      .map(q => String(q || '').trim())
      .filter(Boolean);
    const resultCount = Math.max(0, Math.min(999, Number(raw.result_count || raw.resultCount || 0) || 0));
    const sourceCount = Math.max(0, Math.min(999, Number(raw.source_total || raw.sourceTotal || raw.source_count || raw.sourceCount || 0) || 0));
    const sourceItems = _normalizeReasoningWebSourceItems(raw.sourcePreview || raw.source_preview || raw.sourceItems || raw.source_items || raw.searchResults || raw.search_results || raw.searchedResults || raw.searched_results || raw.sources || raw.results || raw.items || []);
    const nativeIndex = Math.max(0, Math.min(99, Number(raw.index || raw.call_index || raw.callIndex || 0) || 0));
    const round = Math.max(0, Math.min(99, Number(raw.round || 0) || 0));
    const outputIndex = Math.max(0, Math.min(99, Number(raw.output_index || raw.outputIndex || 0) || 0));
    const event = String(raw.event || '').trim().slice(0, 120);
    const key = String(id || `${status}|${queries.join('|')}|${round}|${outputIndex}`).slice(0, 500);
    if(!key || seen.has(key)) continue;
    seen.add(key);
    const title = labelMap[status] || (state === 'done' ? '原生搜索已完成' : '原生搜索调用中');
    const detailBits = [];
    if(shortId) detailBits.push(`调用 ${shortId}`);
    if(round) detailBits.push(`第 ${round} 轮`);
    if(resultCount || sourceCount) detailBits.push(`可见来源 ${Math.max(resultCount, sourceCount)} 个`);
    else if(event) detailBits.push(event);
    out.push({
      key,
      id,
      shortId,
      status,
      state,
      title,
      detail: detailBits.join(' · '),
      queries,
      resultCount: Math.max(resultCount, sourceItems.length),
      sourceCount: Math.max(sourceCount, sourceItems.length),
      ...(sourceItems.length ? { sourceItems, source_items: sourceItems } : {}),
      ...(nativeIndex ? { index: nativeIndex } : {}),
      round,
      outputIndex,
      event,
      ts: Number(raw.updated_at || raw.updatedAt || raw.started_at || raw.startedAt || 0) || 0,
    });
    if(out.length >= maxItems) break;
  }
  return out;
}

function _mergeReasoningSearchResultItems(baseItems, incomingItems, limit=_reasoningWebSourceItemsLimit()){
  return _normalizeReasoningSearchResultItems([
    ...(Array.isArray(baseItems) ? baseItems : []),
    ...(Array.isArray(incomingItems) ? incomingItems : []),
  ], limit);
}

function _normalizeReasoningKbResultItems(items, limit=12){
  const out = [];
  const seen = new Set();
  const maxItems = Math.max(1, Math.min(Number(limit || 12) || 12, 20));
  const pushOne = (item)=>{
    if(!item || typeof item !== 'object') return;
    const filename = String(item.filename || item.title || item.document_name || item.doc_name || '知识库片段').trim().slice(0, 220);
    const citation = String(item.citation_label || item.citation || item.ref || '').trim().slice(0, 160);
    const text = String(item.text || item.snippet || item.content || '').replace(/\s+/g, ' ').trim().slice(0, 260);
    const docId = String(item.doc_id || item.document_id || '').trim().slice(0, 120);
    const chunkOrder = Number(item.chunk_order || item.chunk || 0) || 0;
    const scoreRaw = Number(item.score || item.rank_score || 0) || 0;
    const key = `${docId}|${filename}|${citation}|${chunkOrder}|${text}`.toLowerCase().slice(0, 700);
    if(!filename && !citation && !text) return;
    if(seen.has(key)) return;
    seen.add(key);
    out.push({ filename, citation, text, docId, chunkOrder, score: scoreRaw });
  };
  (Array.isArray(items) ? items : []).forEach(pushOne);
  return out.slice(0, maxItems);
}

function _normalizeReasoningWebQueryGroups(items){
  const source = Array.isArray(items) ? items : [];
  const out = [];
  const seen = new Set();
  const stateMap = {
    searched: 'done', completed: 'done', done: 'done',
    error: 'error', failed: 'error',
    searching: 'active', running: 'active', in_progress: 'active', pending: 'active', queued: 'active',
  };
  source.forEach((raw, idx)=>{
    if(!raw || typeof raw !== 'object') return;
    const queries = (Array.isArray(raw.queries) ? raw.queries : [])
      .map(q => String(q || '').trim())
      .filter(Boolean);
    if(!queries.length) return;
    const index = Math.max(1, Number(raw.index || idx + 1) || (idx + 1));
    const round = Math.max(0, Number(raw.round || 0) || 0);
    const status = String(raw.status || '').trim().toLowerCase() || 'searching';
    const stateRaw = String(raw.state || '').trim().toLowerCase();
    const state = /^(active|done|warn|error)$/.test(stateRaw) ? stateRaw : (stateMap[status] || 'active');
    const resultCount = Math.max(0, Number(raw.result_count || raw.resultCount || 0) || 0);
    const sourceCount = Math.max(0, Number(raw.source_total || raw.sourceTotal || raw.source_count || raw.sourceCount || 0) || 0);
    const sourceItems = _normalizeReasoningWebSourceItems(raw.sourcePreview || raw.source_preview || raw.sourceItems || raw.source_items || raw.searchResults || raw.search_results || raw.searchedResults || raw.searched_results || raw.sources || raw.results || raw.items || []);
    const key = `web_query_group|${index}|${round}|${queries.join('|')}`;
    let ts = Number(raw.ts || raw.startedAt || raw.started_at || raw.updatedAt || raw.updated_at || 0) || 0;
    if(ts > 0 && ts < 10000000000) ts *= 1000;
    if(seen.has(key)) return;
    seen.add(key);
    out.push({
      index,
      round,
      status,
      state,
      queries,
      queryCount: queries.length,
      resultCount,
      sourceCount,
      key,
      ts,
      ...(sourceItems.length ? { sourceItems, source_items: sourceItems } : {}),
    });
  });
  return out;
}


function _normalizeActivityRawText(value){
  return String(value == null ? '' : value).replace(/\r\n?/g, '\n');
}

function _normalizeReasoningFileProgressItems(items, limit=16){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const out = [];
  const seen = new Set();
  const maxItems = Math.max(1, Math.min(Number(limit || 16) || 16, 30));
  for(const raw of source){
    if(!raw || typeof raw !== 'object') continue;
    const stage = String(raw.stage || raw.kind || raw.type || '').trim().slice(0, 80) || 'file_progress';
    const message = String(raw.message || raw.text || raw.status || '').trim().replace(/\s+/g, ' ').slice(0, 260);
    if(!message) continue;
    let percent = Number(raw.percent);
    if(!Number.isFinite(percent)) percent = 0;
    percent = Math.max(0, Math.min(100, Math.round(percent)));
    const attempt = Math.max(0, Number(raw.attempt || 0) || 0);
    const targetFilename = String(raw.target_filename || raw.targetFilename || raw.filename || '').trim().slice(0, 180);
    const error = String(raw.error || '').trim().slice(0, 220);
    const savedFiles = (Array.isArray(raw.saved_files) ? raw.saved_files : (Array.isArray(raw.savedFiles) ? raw.savedFiles : []))
      .map(x => String(x || '').trim())
      .filter(Boolean)
      .slice(0, 8);
    const detail = String(raw.detail || raw.description || '').trim().replace(/\s+/g, ' ').slice(0, 320);
    const queries = (Array.isArray(raw.queries) ? raw.queries : (raw.query || raw.search_query ? [raw.query || raw.search_query] : []))
      .map(x => String(x || '').trim())
      .filter(Boolean)
      .slice(0, 8);
    const ts = Number(raw.ts || Date.now()) || Date.now();
    const tool = String(raw.tool || raw.tool_name || raw.name || '').trim().slice(0, 80);
    const progressKey = String(raw.key || raw.progressKey || raw.progress_key || '').trim().slice(0, 700);
    const dedupeKey = (progressKey || `${stage}|${message}|${percent}|${attempt}|${targetFilename}|${savedFiles.join('|')}|${error}|${detail}|${queries.join('|')}`).slice(0, 800);
    if(seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const toolLower = String(tool || '').trim().toLowerCase();
    const stageLower = String(stage || '').trim().toLowerCase();
    const canCarryDebug = ['sandbox_run','sandbox_list_files'].includes(toolLower) || stageLower.includes('sandbox_run') || stageLower.includes('sandbox_list_files');
    const command = canCarryDebug ? _normalizeActivityRawText(raw.command || '').trim() : '';
    const stdout = canCarryDebug ? _normalizeActivityRawText(raw.stdout || '').trim() : '';
    const stderr = canCarryDebug ? _normalizeActivityRawText(raw.stderr || '').trim() : '';
    const exitCode = canCarryDebug ? (raw.exit_code ?? raw.exitCode) : undefined;
    out.push({
      stage, message, percent, attempt, targetFilename, savedFiles, error, detail, queries, ts, tool,
      ...(progressKey ? { key: progressKey } : {}),
      ...(command ? { command } : {}),
      ...(stdout ? { stdout } : {}),
      ...(stderr ? { stderr } : {}),
      ...(exitCode !== undefined && exitCode !== null ? { exitCode } : {}),
    });
  }
  out.sort((a, b)=> (Number(a.ts || 0) || 0) - (Number(b.ts || 0) || 0));
  const compacted = [];
  const stableIndex = new Map();
  for(const item of out){
    const stable = _sandboxProgressStableKey(item);
    if(stable && stableIndex.has(stable)){
      const idx = stableIndex.get(stable);
      const old = compacted[idx];
      compacted[idx] = _mergeReasoningProgressEntry(old, item);
      continue;
    }
    if(stable) stableIndex.set(stable, compacted.length);
    compacted.push(item);
  }
  return compacted.slice(-maxItems);
}

function _normalizeReasoningTimestamp(value, fallback){
  let n = Number(value || 0) || 0;
  if(n > 0 && n < 10000000000) n *= 1000;
  return n > 0 ? n : fallback;
}

function _activityEventRawStage(raw){
  return String(raw?.rawStage || raw?.raw_stage || raw?.kind || raw?.type || raw?.stage || '').trim().toLowerCase();
}

function _activityEventKey(raw){
  return String(raw?.key || raw?.progressKey || raw?.progress_key || '').trim().toLowerCase();
}

function _activityEventOp(raw){
  return String(raw?.activityOp || raw?.activity_op || '').trim().toLowerCase().slice(0, 80);
}

function _activityEventIsRemove(raw){
  const op = _activityEventOp(raw);
  return !!(raw?.remove || raw?.removed || raw?.clear || raw?.cleared || op === 'remove' || op === 'clear');
}

function _activityEventIsStreamRetry(raw){
  return _activityEventRawStage(raw) === 'stream_open_retry' || _activityEventKey(raw).startsWith('stream_retry|');
}

function _activityEventsFromPayload(payload){
  if(Array.isArray(payload?.activity_events)) return payload.activity_events;
  if(Array.isArray(payload?.activityEvents)) return payload.activityEvents;
  return payload?.activity_event ? [payload.activity_event] : [];
}

function _progressEventsFromPayload(payload){
  if(Array.isArray(payload?.progress_events)) return payload.progress_events;
  if(Array.isArray(payload?.progressEvents)) return payload.progressEvents;
  return [];
}

function _normalizeReasoningProgressEvents(items, limit=24){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const maxItems = Math.max(1, Math.min(Number(limit || 24) || 24, 100));
  const compacted = [];
  const byKey = new Map();
  const stateMap = {
    searched: 'done', completed: 'done', done: 'done',
    error: 'error', failed: 'error',
    searching: 'active', running: 'active', in_progress: 'active', pending: 'active', queued: 'active',
  };
  source.forEach((raw, idx)=>{
    if(!raw || typeof raw !== 'object') return;
    let title = String(raw.title || raw.message || raw.text || '').trim().replace(/\s+/g, ' ').slice(0, 260);
    if(!title) return;
    const detail = String(raw.detail || raw.description || '').trim().replace(/\s+/g, ' ').slice(0, 420);
    const queries = (Array.isArray(raw.queries) ? raw.queries : (raw.query || raw.search_query ? [raw.query || raw.search_query] : []))
      .map(q => String(q || '').trim())
      .filter(Boolean)
      .slice(0, 8);
    let stage = String(raw.stage || raw.panelStage || raw.panel_stage || raw.displayStage || raw.display_stage || '').trim().toLowerCase();
    const rawStage = _activityEventRawStage(raw);
    const tool = String(raw.tool || raw.tool_name || raw.name || '').trim().toLowerCase();
    const source = String(raw.source || '').trim().toLowerCase();
    const canonicalActivity = !!(raw.activityEvent || raw.activity_event || String(raw.eventType || raw.event_type || '').trim().toLowerCase() === 'activity_event');
    const activityOp = _activityEventOp(raw);
    const removeEvent = _activityEventIsRemove(raw);
    if(!canonicalActivity){
      if(rawStage === 'native_web_search' || source === 'native_web_search'){
        return;
      }
      if(source === 'web_search' && rawStage !== 'web_query_group'){
        return;
      }
    }
    if(rawStage === 'web_query_group'){
      const n = Number(raw.index || raw.round_index || 0) || 0;
      if(n > 0) title = `第 ${n} 次搜索中`;
    }
    if(!/^(think|search|web|image|file|sandbox|mcp|answer)$/.test(stage)){
      if(/^sandbox_/.test(rawStage) || /^sandbox_/.test(tool) || tool === 'sandbox') stage = 'sandbox';
      else if(/^mcp_/.test(rawStage) || source === 'mcp') stage = 'mcp';
      else if(/^file_/.test(rawStage) || rawStage.includes('read_file')) stage = 'file';
      else if(tool === 'analyze_existing_image' || rawStage.includes('image_analysis')) stage = 'image';
      else if(rawStage.includes('web') || rawStage.includes('search')) stage = 'search';
      else stage = 'answer';
    }
    let state = String(raw.state || '').trim().toLowerCase();
    if(!/^(active|done|warn|error)$/.test(state)){
      const status = String(raw.status || '').trim().toLowerCase();
      state = stateMap[status] || 'done';
    }
    const ts = _normalizeReasoningTimestamp(raw.ts || raw.startedAt || raw.started_at || raw.updatedAt || raw.updated_at, Date.now() + idx);
    const updatedAt = _normalizeReasoningTimestamp(
      raw.updatedAt || raw.updated_at || raw.finishedAt || raw.finished_at || raw.doneAt || raw.done_at || raw.completedAt || raw.completed_at || raw.ts,
      ts
    );
    const doneAt = /^(done|warn|error)$/.test(state)
      ? _normalizeReasoningTimestamp(raw.doneAt || raw.done_at || raw.finishedAt || raw.finished_at || raw.completedAt || raw.completed_at || raw.updatedAt || raw.updated_at || raw.ts, updatedAt)
      : 0;
    const seq = Math.max(0, Number(raw.seq || raw.order || 0) || 0);
    const attempt = Math.max(0, Number(raw.attempt || 0) || 0);
    const attemptTotal = Math.max(0, Number(raw.attemptTotal || raw.attempt_total || 0) || 0);
    let key = String(raw.key || raw.progressKey || raw.progress_key || `${stage}|${rawStage}|${tool}|${title}|${detail}|${queries.join('|')}`).trim().slice(0, 700);
    if(!key) return;
    const command = _normalizeActivityRawText(raw.command || '').trim();
    const stdout = _normalizeActivityRawText(raw.stdout || '').trim();
    const stderr = _normalizeActivityRawText(raw.stderr || '').trim();
    const exitCode = raw.exit_code ?? raw.exitCode;
    const commandLanguage = String(raw.commandLanguage || raw.command_language || raw.language || '').trim().slice(0, 40);
    const showDebug = raw.showDebug !== undefined ? !!raw.showDebug : (raw.show_debug !== undefined ? !!raw.show_debug : undefined);
    const debugAvailable = raw.debugAvailable !== undefined ? !!raw.debugAvailable : (raw.debug_available !== undefined ? !!raw.debug_available : undefined);
    const rawFileNames = Array.isArray(raw.fileNames) ? raw.fileNames : (
      Array.isArray(raw.file_names) ? raw.file_names : (
        Array.isArray(raw.filenames) ? raw.filenames : (
          Array.isArray(raw.files_preview) ? raw.files_preview : (Array.isArray(raw.file_preview) ? raw.file_preview : [])
        )
      )
    );
    const fileNames = rawFileNames.map(x => String(x || '').trim()).filter(Boolean).slice(0, 80);
    const fileNameTotal = Math.max(0, Number(raw.fileNameTotal || raw.file_name_total || raw.fileNameCount || raw.file_name_count || raw.fileCount || raw.file_count || raw.total_count || fileNames.length || 0) || 0);
    const rawImageItems = Array.isArray(raw.imageItems) ? raw.imageItems : (Array.isArray(raw.image_items) ? raw.image_items : []);
    const imageItems = rawImageItems.filter(x => x && (typeof x === 'object' || typeof x === 'string')).slice(0, 8);
    const imageCount = Math.max(0, Number(raw.imageCount || raw.image_count || imageItems.length || 0) || 0);
    const rawDocumentVisualItems = Array.isArray(raw.documentVisualItems) ? raw.documentVisualItems : (Array.isArray(raw.document_visual_items) ? raw.document_visual_items : []);
    const documentVisualItems = rawDocumentVisualItems.filter(x => x && typeof x === 'object').slice(0, 12);
    const documentPageCount = Math.max(0, Number(raw.documentPageCount || raw.document_page_count || documentVisualItems.length || 0) || 0);
    const documentVisualDeferred = !!(raw.documentVisualDeferred || raw.document_visual_deferred);
    const operationKey = String(raw.operationKey || raw.operation_key || '').trim().slice(0, 160);
    const eventSessionId = String(raw.sessionId || raw.session_id || raw.clientSessionId || raw.client_session_id || '').trim().slice(0, 160);
    const eventTurnId = String(raw.activityTurnId || raw.activity_turn_id || raw.turnId || raw.turn_id || '').trim().slice(0, 240);
    const eventSessionTitle = String(raw.clientSessionTitle || raw.client_session_title || raw.sessionTitle || raw.session_title || '').trim().slice(0, 240);
    const resultCount = Math.max(0, Number(raw.result_count || raw.resultCount || raw.source_total || raw.sourceTotal || 0) || 0);
    const sourceItems = _normalizeReasoningWebSourceItems(raw.sourcePreview || raw.source_preview || raw.sourceItems || raw.source_items || raw.searchResults || raw.search_results || raw.searchedResults || raw.searched_results || raw.sources || raw.results || raw.items || []);
    const entry = {
      key,
      title,
      detail,
      queries,
      stage,
      state,
      ts,
      updatedAt,
      updated_at: updatedAt,
      ...(doneAt ? { doneAt, done_at: doneAt } : {}),
      ...(seq > 0 ? { seq } : {}),
      text: String(raw.text || title).trim().slice(0, 260),
      source: source.slice(0, 80),
      rawStage: rawStage || String(raw.rawStage || raw.raw_stage || '').trim().slice(0, 120),
      tool,
      activityEvent: canonicalActivity,
      activity_event: canonicalActivity,
      ...(removeEvent ? { remove: true, removed: true } : {}),
      ...(activityOp ? { activityOp, activity_op: activityOp } : {}),
      ...(attempt ? { attempt } : {}),
      ...(attemptTotal ? { attemptTotal, attempt_total: attemptTotal } : {}),
      ...(resultCount ? { resultCount, result_count: resultCount, sourceTotal: Math.max(resultCount, sourceItems.length), source_total: Math.max(resultCount, sourceItems.length) } : {}),
      ...(sourceItems.length ? { sourceItems, source_items: sourceItems, sourcePreview: sourceItems, source_preview: sourceItems } : {}),
      ...(command ? { command } : {}),
      ...(stdout ? { stdout } : {}),
      ...(stderr ? { stderr } : {}),
      ...(exitCode !== undefined && exitCode !== null ? { exitCode } : {}),
      ...(commandLanguage ? { commandLanguage } : {}),
      ...(showDebug !== undefined ? { showDebug } : {}),
      ...(debugAvailable !== undefined ? { debugAvailable } : {}),
      ...(fileNames.length ? { fileNames } : {}),
      ...(fileNameTotal > 0 ? { fileNameTotal, file_count: fileNameTotal } : {}),
      ...(imageItems.length ? { imageItems, image_items:imageItems } : {}),
      ...(imageCount > 0 ? { imageCount, image_count:imageCount } : {}),
      ...(documentVisualItems.length ? { documentVisualItems, document_visual_items:documentVisualItems } : {}),
      ...(documentPageCount > 0 ? { documentPageCount, document_page_count:documentPageCount } : {}),
      ...(documentPageCount > 0 ? { documentVisualDeferred, document_visual_deferred:documentVisualDeferred } : {}),
      ...(operationKey ? { operationKey } : {}),
      ...(eventSessionId ? { sessionId:eventSessionId, session_id:eventSessionId, clientSessionId:eventSessionId, client_session_id:eventSessionId } : {}),
      ...(eventTurnId ? { activityTurnId:eventTurnId, activity_turn_id:eventTurnId } : {}),
      ...(eventSessionTitle ? { clientSessionTitle:eventSessionTitle, client_session_title:eventSessionTitle } : {}),
    };
    const stableKey = _sandboxProgressStableKey({ ...entry, key, stage: rawStage || stage, tool, title, message:title, text:title });
    if(stableKey){
      entry.key = stableKey;
      key = stableKey;
    }
    if(byKey.has(key)){
      const prevIndex = byKey.get(key);
      const prev = compacted[prevIndex] || {};
      compacted[prevIndex] = _mergeReasoningProgressEntry(prev, entry);
    }else{
      byKey.set(key, compacted.length);
      compacted.push(entry);
    }
  });
  compacted.sort((a, b)=>{
    const as = Number(a.seq || 0) || 0;
    const bs = Number(b.seq || 0) || 0;
    if(as > 0 && bs > 0 && as !== bs) return as - bs;
    if(as > 0 && bs <= 0) return -1;
    if(bs > 0 && as <= 0) return 1;
    return (Number(a.ts || 0) || 0) - (Number(b.ts || 0) || 0);
  });
  return compacted.filter(item => !(item && (item.remove || item.removed || item.clear || item.cleared))).slice(-maxItems);
}

function _progressEventFromFileProgress(progress){
  const entry = _fileProgressReasoningEntry(progress);
  if(!entry) return null;
  return {
    key: entry.key,
    title: entry.title,
    detail: entry.detail,
    queries: entry.queries,
    stage: entry.stage,
    state: entry.state,
    ts: entry.ts,
    text: entry.text,
    source: 'file_progress',
    rawStage: String(progress?.stage || '').trim(),
    tool: String(progress?.tool || progress?.tool_name || progress?.name || '').trim(),
    ...(entry.command ? { command: entry.command } : {}),
    ...(entry.stdout ? { stdout: entry.stdout } : {}),
    ...(entry.stderr ? { stderr: entry.stderr } : {}),
    ...(entry.exitCode !== undefined && entry.exitCode !== null ? { exitCode: entry.exitCode } : {}),
  };
}

function _isSandboxFileProgressItem(item){
  const stage = String(item?.stage || '').trim().toLowerCase();
  const tool = String(item?.tool || '').trim().toLowerCase();
  const message = String(item?.message || item?.text || '').trim();
  return /^sandbox_/.test(stage) || /^sandbox_/.test(tool) || /沙盒|沙盒命令|沙盒文件|沙盒后端/.test(message);
}

function _normalizeReasoningFileEditAudits(items, limit=4){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const out = [];
  const seen = new Set();
  const maxItems = Math.max(1, Math.min(Number(limit || 4) || 4, 8));
  for(const raw of source){
    if(!raw || typeof raw !== 'object') continue;
    const target = String(raw.target_filename || raw.targetFilename || raw.target || '').trim().slice(0, 220);
    const requestedTarget = String(raw.requested_target_filename || raw.requestedTargetFilename || '').trim().slice(0, 220);
    const basisFilename = String(raw.basis_filename || raw.basisFilename || '').trim().slice(0, 220);
    const output = String(raw.output_filename || raw.outputFilename || raw.output || '').trim().slice(0, 220);
    const oldHashFull = String(raw.old_sha256 || raw.oldSha256 || raw.oldHash || '').trim();
    const newHashFull = String(raw.new_sha256 || raw.newSha256 || raw.newHash || '').trim();
    const basisHashFull = String(raw.basis_sha256 || raw.basisSha256 || '').trim();
    const oldHash = oldHashFull.slice(0, 24);
    const newHash = newHashFull.slice(0, 24);
    const verification = raw.verification && typeof raw.verification === 'object' ? raw.verification : {};
    const summary = (Array.isArray(raw.diff_summary) ? raw.diff_summary : (Array.isArray(raw.diffSummary) ? raw.diffSummary : []))
      .map(x => String(x || '').trim().replace(/\s+/g, ' '))
      .filter(Boolean)
      .slice(0, 24);
    const rawDiff = String(raw.diff || raw.unified_diff || raw.unifiedDiff || raw.patch || raw.raw_diff || raw.rawDiff || '').replace(/\r\n/g, '\n').slice(0, 60000);
    const changes = (Array.isArray(raw.changes) ? raw.changes : [])
      .map(x => {
        if(typeof x === 'string') return x.trim();
        try{ return JSON.stringify(x); }catch(_){ return ''; }
      })
      .filter(Boolean)
      .slice(0, 30);
    if(!(target || output || summary.length || oldHash || newHash || rawDiff || changes.length)) continue;
    const key = `${target}|${output}|${oldHash}|${newHash}|${summary.join('|')}|${rawDiff.slice(0, 120)}`.slice(0, 900);
    if(seen.has(key)) continue;
    seen.add(key);
    out.push({
      targetFilename: target,
      requestedTargetFilename: requestedTarget,
      basisFilename,
      outputFilename: output,
      changed: Object.prototype.hasOwnProperty.call(raw, 'changed') ? !!raw.changed : null,
      oldSha256: oldHash,
      newSha256: newHash,
      oldSha256Full: oldHashFull,
      newSha256Full: newHashFull,
      basisSha256Full: basisHashFull,
      oldChars: Number(raw.old_chars || raw.oldChars || 0) || 0,
      newChars: Number(raw.new_chars || raw.newChars || 0) || 0,
      oldLines: Number(raw.old_lines || raw.oldLines || 0) || 0,
      newLines: Number(raw.new_lines || raw.newLines || 0) || 0,
      verificationPassed: Object.prototype.hasOwnProperty.call(verification, 'passed') ? !!verification.passed : null,
      verificationSource: String(verification.source || '').trim().slice(0, 120),
      verificationSummary: String(verification.summary || '').trim().slice(0, 1000),
      verificationIssues: [
        ...((Array.isArray(verification.issues) ? verification.issues : []).map(x => String(x || '').trim()).filter(Boolean)),
        ...((Array.isArray(verification.warnings) ? verification.warnings : []).map(x => String(x || '').trim()).filter(Boolean)),
        ...((Array.isArray(verification.static_errors) ? verification.static_errors : []).map(x => String(x || '').trim()).filter(Boolean)),
      ].slice(0, 12),
      summary,
      rawDiff,
      changes,
      userRequest: String(raw.user_request || raw.userRequest || '').trim().slice(0, 2400),
      reason: String(raw.reason || '').trim().slice(0, 1200),
      createdAt: String(raw.created_at || raw.createdAt || '').trim().slice(0, 80),
    });
    if(out.length >= maxItems) break;
  }
  return out;
}

function _fileProgressReasoningEntry(progress){
  const item = progress && typeof progress === 'object' ? progress : null;
  if(!item) return null;
  const stage = String(item.stage || '').trim().toLowerCase();
  const message = String(item.message || '').trim();
  if(!message) return null;
  const percent = Math.max(0, Math.min(100, Number(item.percent || 0) || 0));
  const attempt = Math.max(0, Number(item.attempt || 0) || 0);
  const target = String(item.targetFilename || '').trim();
  const rawDetail = String(item.detail || '').trim();
  const queries = (Array.isArray(item.queries) ? item.queries : [])
    .map(q => String(q || '').trim())
    .filter(Boolean)
    .slice(0, 8);
  let title = message;
  let detail = rawDetail;
  let state = 'active';

  if(_isSandboxFileProgressItem(item)){
    title = message;
    if(stage.includes('error') || /失败|出错/.test(message)) state = 'error';
    else if(percent >= 100 || stage.includes('done')) state = 'done';
    else state = 'active';
  }else if(stage.includes('file_index_start')) title = '正在准备沙盒文件清单';
  else if(stage.includes('file_index_file')) title = target ? `已列入待导入文件：${target}` : '已列入待导入文件';
  else if(stage.includes('file_index_ready')) title = '沙盒文件清单已就绪';
  else if(stage.includes('file_exact_symbol_available')) title = '发现文件结构线索';
  else if(stage.includes('file_search_start')) title = '正在检索上传文件';
  else if(stage.includes('file_search_query')) title = '已确定文件检索目标';
  else if(stage.includes('file_search_hit')) title = target ? `命中文件：${target}` : '已命中文件';
  else if(stage.includes('file_symbol_context_done')) title = message || '已定位代码片段';
  else if(stage.includes('file_model_read_start')) title = '模型正在按目标读取文件';
  else if(stage.includes('read_file_context_done')) title = '已读取相关文件上下文';
  else if(stage.includes('read_file_done')) title = /完整文件/.test(message) ? '已读取完整文件' : (/代码片段|定位/.test(message) ? '已定位代码片段' : '已读取文件片段');
  else if(stage.includes('read_file')) title = stage.includes('done') ? '已读取文件内容' : '正在读取文件内容';
  else if(stage.includes('model_edit_start')) title = attempt > 1 ? `正在重新生成第 ${attempt} 次文件修改` : '正在生成文件修改';
  else if(stage.includes('model_edit_done')) title = '模型已返回文件修改';
  else if(stage.includes('apply_patch_done')) title = '修改已应用并通过验证';
  else if(stage.includes('apply_patch')) title = '正在应用修改并验证';
  else if(stage.includes('saved')) title = '文件修改已保存';
  else if(stage.includes('failed') || stage.includes('error')) title = '文件处理失败';

  const detailParts = [];
  if(target && !detail.includes(target) && !/^命中文件/.test(title)) detailParts.push(`目标文件：${target}`);
  if(detail) detailParts.push(detail);
  if(item.savedFiles && item.savedFiles.length) detailParts.push(`输出文件：${item.savedFiles.join('、')}`);
  if(item.error) detailParts.push(String(item.error || '').trim());
  detail = detailParts.filter(Boolean).join(' · ');

  if(percent >= 100 || stage.includes('done') || stage.includes('saved') || stage.includes('hit')) state = 'done';
  if(stage.includes('failed') || stage.includes('error') || /失败|出错/.test(message)) state = 'error';
  const stableKey = _sandboxProgressStableKey({ ...item, stage, title, message });
  return {
    key: (stableKey || `file_progress|${stage}|${attempt}|${title}|${detail}|${queries.join('|')}`).slice(0, 700),
    title,
    detail,
    queries,
    stage: _isSandboxFileProgressItem(item) ? 'sandbox' : 'file',
    state,
    ts: Number(item.ts || Date.now()) || Date.now(),
    text: message,
    ...(item.command ? { command: item.command } : {}),
    ...(item.stdout ? { stdout: item.stdout } : {}),
    ...(item.stderr ? { stderr: item.stderr } : {}),
    ...(item.exitCode !== undefined && item.exitCode !== null ? { exitCode: item.exitCode } : {}),
  };
}

function _reasoningHasFileActivity(meta, snapshot, items){
  const m = meta || {};
  const snap = snapshot || {};
  if(_normalizeReasoningFileProgressItems(m.fileProgressItems || snap.fileProgressItems || []).length) return true;
  if(_normalizeReasoningFileEditAudits(m.fileEditAudits || snap.fileEditAudits || []).length) return true;
  const fileToolUsed = !!(m.fileToolUsed || snap.fileToolUsed || Number(m.fileToolRounds || snap.fileToolRounds || 0) > 0);
  if(fileToolUsed) return true;
  const names = Array.isArray(m.artifactFilenames) ? m.artifactFilenames : (Array.isArray(snap.artifactFilenames) ? snap.artifactFilenames : []);
  if(fileToolUsed && names.length) return true;
  return _normalizePendingAssistantReasoning(items || []).some(item => /文件|修改|生成|写入|保存|验证|diff/i.test(`${item?.title || ''} ${item?.detail || ''} ${item?.text || ''}`));
}

function _fileAuditOutputLabel(audit){
  const target = String(audit?.targetFilename || '').trim();
  const output = String(audit?.outputFilename || '').trim();
  if(target && output && target !== output) return `${target} → ${output}`;
  return output || target || '文件修改';
}


function _nativeReasoningSegmentKeyValue(raw){
  if(!raw || typeof raw !== 'object') return '';
  return String(
    raw.segmentKey || raw.segment_key
    || raw.reasoningEventKey || raw.reasoning_event_key
    || raw.nativeReasoningEventKey || raw.native_reasoning_event_key
    || raw.eventKey || raw.event_key
    || raw.itemId || raw.item_id
    || ''
  ).trim().slice(0, 700);
}


function _sanitizeNativeReasoningDisplayText(text){
  let value = String(text == null ? '' : text).replace(/\r\n?/g, '\n');
  if(!value) return '';
  // Markdown HTML comments are non-visible metadata. Some Responses relays
  // include empty comments in reasoning summaries, and old streams may have
  // persisted a marker split across adjacent segments.
  value = value
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<!--[\s\S]*$/g, '')
    .replace(/^\s*-->\s*/g, '')
    .replace(/<!-{0,2}\s*$/g, '');
  return value;
}


function _removeRedundantNativeReasoningSnapshotSegments(items){
  const source = Array.isArray(items) ? items : [];
  const out = [];
  let keyedAggregateText = '';
  let keyedSegmentCount = 0;
  source.forEach(item => {
    if(!item || typeof item !== 'object') return;
    const text = String(item.text || '').replace(/\r\n?/g, '\n');
    const eventKey = _nativeReasoningSegmentKeyValue(item);
    if(eventKey){
      keyedAggregateText += text;
      keyedSegmentCount += 1;
      out.push(item);
      return;
    }
    // reasoning_meta carries the complete accumulated snapshot.  Older clients
    // could replay it through the delta path and create one extra unkeyed row
    // containing every provider-keyed segment seen so far.  Remove only that
    // exact structural duplicate; ordinary keyless reasoning remains untouched.
    if(keyedSegmentCount > 0 && text && text === keyedAggregateText) return;
    out.push(item);
  });
  return out;
}


function _normalizeNativeReasoningSegments(items, limit=80){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const maxItems = Math.max(1, Math.min(Number(limit || 80) || 80, 120));
  const out = [];
  const seen = new Set();
  source.forEach((raw, idx)=>{
    if(!raw || typeof raw !== 'object') return;
    const text = String(raw.text || raw.delta || raw.content || raw.detail || '').replace(/\r\n?/g, '\n');
    if(!text) return;
    const ts = _normalizeReasoningTimestamp(raw.ts || raw.startedAt || raw.started_at || raw.createdAt || raw.created_at || raw.updatedAt || raw.updated_at, Date.now() + idx);
    const updatedAt = _normalizeReasoningTimestamp(raw.updatedAt || raw.updated_at || raw.endedAt || raw.ended_at || raw.ts, ts);
    const source = String(raw.source || raw.nativeReasoningSource || raw.native_reasoning_source || '').trim().slice(0, 40);
    const stateRaw = String(raw.state || '').trim().toLowerCase();
    const state = /^(active|done|warn|error)$/.test(stateRaw) ? stateRaw : 'done';
    const seq = Math.max(0, Number(raw.seq || raw.order || raw._job_seq || 0) || 0);
    const seqEnd = Math.max(seq, Number(raw.seqEnd || raw.seq_end || raw.orderEnd || raw.order_end || raw._job_seq_end || 0) || 0);
    const segmentKey = _nativeReasoningSegmentKeyValue(raw);
    const key = String(raw.key || (segmentKey ? `native_reasoning_segment|${segmentKey}` : `native_reasoning_segment|${seq || ts}|${idx}|${_reasoningTinyHash(text)}`)).trim().slice(0, 700);
    if(!key || seen.has(key)) return;
    seen.add(key);
    out.push({
      key, text, ts, updatedAt, state,
      ...(seq > 0 ? { seq } : {}),
      ...(seqEnd > 0 ? { seqEnd } : {}),
      ...(source ? { source } : {}),
      ...(segmentKey ? { segmentKey, reasoningEventKey:segmentKey } : {}),
    });
  });
  out.sort((a, b)=>{
    const as = Number(a.seq || 0) || 0;
    const bs = Number(b.seq || 0) || 0;
    if(as > 0 && bs > 0 && as !== bs) return as - bs;
    return (Number(a.ts || 0) || 0) - (Number(b.ts || 0) || 0);
  });
  return _removeRedundantNativeReasoningSnapshotSegments(out).slice(-maxItems);
}

function _latestReasoningActivityBoundaryTs(prevMeta){
  const prev = prevMeta && typeof prevMeta === 'object' ? prevMeta : {};
  const rows = [];
  if(Array.isArray(prev.activityEvents)) rows.push(...prev.activityEvents);
  if(Array.isArray(prev.activity_events)) rows.push(...prev.activity_events);
  if(Array.isArray(prev.progressEvents)) rows.push(...prev.progressEvents);
  if(Array.isArray(prev.progress_events)) rows.push(...prev.progress_events);
  const normalized = _normalizeReasoningProgressEvents(rows, 100);
  return normalized.reduce((max, item)=>{
    const stage = String(item?.stage || item?.kind || '').toLowerCase();
    if(stage === 'think') return max;
    return Math.max(
      max,
      Number(item?.doneAt || item?.done_at || 0) || 0,
      Number(item?.updatedAt || item?.updated_at || 0) || 0,
      Number(item?.ts || 0) || 0
    );
  }, 0);
}

function _nativeReasoningSourceKeepsSegments(value){
  const s = String(value || '').trim().toLowerCase();
  // Do not collapse native reasoning into one old aggregate row.  Native
  // reasoning keeps provider event-keyed segments when available, with seq/ts
  // fallback, so tool/search/read events can interleave correctly.
  if(!s) return true;
  if(s === 'legacy_reasoning_group' || s === 'legacy_grouped_reasoning') return false;
  return true;
}

function _nativeReasoningDeltaStartsSectionHeading(text){
  const raw = String(text || '').replace(/\r\n?/g, '\n');
  const match = raw.match(/^\s*(?:\*\*|__)([^*_\n][^\n]{2,110}?)(?:\*\*|__)([\s\S]*)$/);
  if(!match) return false;
  const title = String(match[1] || '').replace(/[`*_#>\[\](){}]/g, '').replace(/\s+/g, ' ').trim();
  const tail = String(match[2] || '');
  if(title.length < 8 || title.length > 92) return false;
  if(/[。！？!?]$/.test(title) || /https?:\/\//i.test(title)) return false;
  if(title.split(/\s+/).filter(Boolean).length > 10) return false;
  const firstLatin = title.match(/[A-Za-z]/);
  if(firstLatin && firstLatin[0] !== firstLatin[0].toUpperCase()) return false;
  // 标题必须独占当前增量的首行；“**强调** 普通正文”仍按行内强调处理。
  if(tail && !/^\s*\n/.test(tail)) return false;
  return true;
}

function _joinNativeReasoningDeltaText(previous, incoming){
  const left = String(previous || '').replace(/\r\n?/g, '\n');
  const right = String(incoming || '').replace(/\r\n?/g, '\n');
  if(!left) return right;
  if(!right) return left;
  const leftTrimmed = left.trimEnd();
  if(
    _nativeReasoningDeltaStartsSectionHeading(right)
    && /[.!?。！？:：]$/.test(leftTrimmed)
  ){
    return `${leftTrimmed}\n\n${right.trimStart()}`;
  }
  return left + right;
}

function _appendNativeReasoningSegment(prevMeta, piece, source='native_field', now=Date.now(), eventOrder=0, eventKey=''){
  const text = String(piece || '').replace(/\r\n?/g, '\n');
  if(!text) return _normalizeNativeReasoningSegments(prevMeta?.nativeReasoningSegments || [], 80);
  const prev = _normalizePendingAssistantReasoningMeta(prevMeta || {});
  const segments = _normalizeNativeReasoningSegments(prev.nativeReasoningSegments || [], 80);
  const lastActivityBoundaryTs = _latestReasoningActivityBoundaryTs(prev);
  const last = segments.length ? segments[segments.length - 1] : null;
  const lastUpdatedAt = Number(last?.updatedAt || last?.ts || 0) || 0;
  const normalizedSource = String(source || prev.nativeReasoningSource || 'native_field').trim().slice(0, 40) || 'native_field';
  const seq = Math.max(0, Number(eventOrder || 0) || 0);
  const incomingEventKey = String(eventKey || '').trim().slice(0, 700);
  const lastEventKey = last ? _nativeReasoningSegmentKeyValue(last) : '';
  const lastSeqEnd = Math.max(0, Number(last?.seqEnd || last?.seq_end || last?.seq || 0) || 0);
  const latestActivitySeq = Math.max(0, ...[
    ...(Array.isArray(prev.activityEvents) ? prev.activityEvents : []),
    ...(Array.isArray(prev.progressEvents) ? prev.progressEvents : []),
  ].map(item => Number(item?.seq || item?.order || 0) || 0));

  // Real provider/native event id wins.  If Responses says several deltas belong
  // to the same reasoning item/summary part, keep them in one Activity row even
  // when punctuation or network timing would otherwise split them.
  const canMergeByEventKey = !!(last && incomingEventKey && lastEventKey && incomingEventKey === lastEventKey);
  const canMergeBySeq = !(seq > 0 && latestActivitySeq > 0 && latestActivitySeq > lastSeqEnd && seq > latestActivitySeq);
  if(last && (canMergeByEventKey || (canMergeBySeq && lastUpdatedAt >= lastActivityBoundaryTs && now - lastUpdatedAt <= 1200))){
    segments[segments.length - 1] = {
      ...last,
      text: _joinNativeReasoningDeltaText(last.text || '', text),
      updatedAt: now,
      state: 'active',
      source: normalizedSource,
      ...(seq > 0 && !Number(last.seq || 0) ? { seq } : {}),
      ...(seq > 0 ? { seqEnd: Math.max(seq, Number(last.seqEnd || last.seq || 0) || 0) } : {}),
      ...(incomingEventKey ? { segmentKey: incomingEventKey, reasoningEventKey: incomingEventKey } : {}),
    };
    return segments.slice(-80);
  }
  segments.push({
    key: incomingEventKey ? `native_reasoning_segment|${incomingEventKey}`.slice(0, 700) : `native_reasoning_segment|${seq || now}|${segments.length}|${_reasoningTinyHash(text)}`.slice(0, 700),
    text,
    ts: now,
    updatedAt: now,
    state: 'active',
    source: normalizedSource,
    ...(seq > 0 ? { seq, seqEnd:seq } : {}),
    ...(incomingEventKey ? { segmentKey: incomingEventKey, reasoningEventKey: incomingEventKey } : {}),
  });
  return segments.slice(-80);
}

function _finalizeNativeReasoningSegments(prevMeta, mergedText, done, source='native_field', now=Date.now()){
  let segments = _normalizeNativeReasoningSegments(prevMeta?.nativeReasoningSegments || [], 80);
  const fullText = String(mergedText || '').replace(/\r\n?/g, '\n');
  const normalizedSource = String(source || prevMeta?.nativeReasoningSource || 'native_field').trim().slice(0, 40) || 'native_field';
  if(!segments.length && fullText){
    segments = [{
      key: `native_reasoning_segment|${Number(prevMeta?.nativeReasoningStartAt || 0) || now}|0|${_reasoningTinyHash(fullText)}`.slice(0, 700),
      text: fullText,
      ts: Number(prevMeta?.nativeReasoningStartAt || 0) || now,
      updatedAt: now,
      state: done ? 'done' : 'active',
      source: normalizedSource,
    }];
  }else{
    segments = segments.map((seg, idx)=>({
      ...seg,
      state: done ? 'done' : (idx === segments.length - 1 ? 'active' : 'done'),
      updatedAt: idx === segments.length - 1 ? now : (Number(seg.updatedAt || seg.ts || 0) || now),
      source: seg.source || normalizedSource,
    }));
  }
  return segments.slice(-80);
}

function _normalizeMcpInlineCards(items, limit=30){
  const source = Array.isArray(items) ? items : (items && typeof items === 'object' ? [items] : []);
  const maxItems = Math.max(1, Math.min(Number(limit || 30) || 30, 50));
  const out = [];
  const byKey = new Map();
  for(const [index, raw] of source.entries()){
    if(!raw || typeof raw !== 'object') continue;
    const type = String(raw.type || raw.cardType || raw.card_type || 'call').trim().toLowerCase() === 'approval' ? 'approval' : 'call';
    const requestId = String(raw.requestId || raw.request_id || raw.activityId || raw.activity_id || '').trim().slice(0, 180);
    const toolName = String(raw.toolName || raw.tool_name || '').trim().slice(0, 200);
    const key = String(raw.key || `${type}|${requestId || toolName || index}`).trim().slice(0, 500);
    if(!key) continue;
    const stateRaw = String(raw.state || (type === 'approval' ? 'pending' : 'running')).trim().toLowerCase();
    const state = ['pending','submitting','allowed','denied','revision','running','done','error'].includes(stateRaw) ? stateRaw : (type === 'approval' ? 'pending' : 'running');
    let argumentsValue = {};
    let resultPreview = null;
    try{
      const encoded = JSON.stringify(raw.arguments && typeof raw.arguments === 'object' ? raw.arguments : {});
      argumentsValue = encoded.length <= 16000 ? JSON.parse(encoded) : { '…':'参数内容较长，请在活动面板中查看摘要' };
    }catch(_){ argumentsValue = {}; }
    try{
      const encoded = JSON.stringify(raw.resultPreview ?? raw.result_preview ?? null);
      resultPreview = encoded && encoded.length <= 12000 ? JSON.parse(encoded) : null;
    }catch(_){ resultPreview = null; }
    const card = {
      key,
      type,
      jobId:String(raw.jobId || raw.job_id || raw._job_id || '').trim().slice(0, 180),
      requestId,
      activityId:String(raw.activityId || raw.activity_id || requestId).trim().slice(0, 180),
      serverId:String(raw.serverId || raw.server_id || '').trim().slice(0, 120),
      serverName:String(raw.serverName || raw.server_name || 'MCP Server').trim().slice(0, 160),
      toolName,
      toolTitle:String(raw.toolTitle || raw.tool_title || toolName || 'MCP 工具').trim().slice(0, 200),
      description:String(raw.description || raw.toolDescription || raw.tool_description || '').trim().slice(0, 2000),
      risk:String(raw.risk || 'high').trim().toLowerCase().slice(0, 20),
      state,
      arguments:argumentsValue,
      resultPreview,
      userRequest:String(raw.userRequest || raw.user_request || '').trim().slice(0, 2000),
      error:String(raw.error || raw.message || '').trim().slice(0, 1200),
      expanded:raw.expanded !== undefined ? !!raw.expanded : type === 'approval',
      ts:Number(raw.ts || raw.createdAt || raw.created_at || Date.now() + index) || Date.now() + index,
      updatedAt:Number(raw.updatedAt || raw.updated_at || raw.ts || Date.now() + index) || Date.now() + index,
    };
    if(byKey.has(key)) out[byKey.get(key)] = { ...out[byKey.get(key)], ...card };
    else{ byKey.set(key, out.length); out.push(card); }
  }
  return out.sort((a,b)=>(Number(a.ts || 0) || 0) - (Number(b.ts || 0) || 0)).slice(-maxItems);
}

function _normalizePendingAssistantReasoningMeta(meta){
  const raw = (meta && typeof meta === 'object') ? meta : {};
  const out = {};
  const sourceCount = Math.max(0, Math.min(99, Number(raw.sourceCount || raw.source_count || 0) || 0));
  const resultCount = Math.max(0, Math.min(99, Number(raw.resultCount || raw.result_count || raw.results || 0) || 0));
  const pageCount = Math.max(0, Math.min(99, Number(raw.pageCount || raw.page_count || raw.pages || 0) || 0));
  const searchRounds = Math.max(0, Math.min(9, Number(raw.searchRounds || raw.search_rounds || 0) || 0));
  if(sourceCount) out.sourceCount = sourceCount;
  if(resultCount) out.resultCount = resultCount;
  if(pageCount) out.pageCount = pageCount;
  if(searchRounds) out.searchRounds = searchRounds;
  const routeMode = String(raw.routeMode || raw.route_mode || '').trim().slice(0, 40);
  const answerStrategy = String(raw.answerStrategy || raw.answer_strategy || '').trim().slice(0, 60);
  const queryStrategy = String(raw.queryStrategy || raw.query_strategy || '').trim().slice(0, 60);
  const useWebResearch = !!(raw.useWebResearch || raw.use_web_research);
  if(routeMode) out.routeMode = routeMode;
  if(answerStrategy) out.answerStrategy = answerStrategy;
  if(queryStrategy) out.queryStrategy = queryStrategy;
  if(useWebResearch) out.useWebResearch = true;
  const queriesUsed = (Array.isArray(raw.queriesUsed) ? raw.queriesUsed : (Array.isArray(raw.queries_used) ? raw.queries_used : []))
    .map(q => String(q || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  if(queriesUsed.length) out.queriesUsed = queriesUsed;
  const plannedFocuses = (Array.isArray(raw.plannedFocuses) ? raw.plannedFocuses : (Array.isArray(raw.planned_focuses) ? raw.planned_focuses : []))
    .map(q => String(q || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  if(plannedFocuses.length) out.plannedFocuses = plannedFocuses;
  const searchResults = _normalizeReasoningSearchResultItems(
    raw.searchPreview || raw.search_preview || raw.searchResults || raw.search_results || raw.searchedResults || raw.searched_results || [],
    _reasoningWebSourceItemsLimit()
  );
  if(searchResults.length) out.searchResults = searchResults;
  const nativeWebCalls = _normalizeReasoningNativeWebCallItems(raw.nativeWebCalls || raw.native_web_calls || [], 12);
  if(nativeWebCalls.length) out.nativeWebCalls = nativeWebCalls;
  const nativeWebCallCount = Math.max(0, Math.min(99, Number(raw.nativeWebCallCount || raw.native_web_call_count || nativeWebCalls.length || 0) || 0));
  if(nativeWebCallCount) out.nativeWebCallCount = nativeWebCallCount;
  const webQueryGroups = _normalizeReasoningWebQueryGroups(raw.webQueryGroups || raw.web_query_groups || []);
  if(webQueryGroups.length) out.webQueryGroups = webQueryGroups;
  const activityEvents = _normalizeReasoningProgressEvents(raw.activityEvents || raw.activity_events || raw.activityTimeline || raw.activity_timeline || [], 80);
  if(activityEvents.length) out.activityEvents = activityEvents;
  const mcpCards = _normalizeMcpInlineCards(raw.mcpCards || raw.mcp_cards || [], 30);
  if(mcpCards.length) out.mcpCards = mcpCards;
  const progressEvents = _normalizeReasoningProgressEvents(raw.progressEvents || raw.progress_events || raw.reasoningTimeline || raw.reasoning_timeline || [], 30);
  if(progressEvents.length) out.progressEvents = progressEvents;

  const useKnowledgeBase = !!(raw.useKnowledgeBase || raw.use_knowledge_base || raw.knowledgeHit || raw.knowledge_hit);
  const kbResultCount = Math.max(0, Math.min(99, Number(raw.kbResultCount || raw.kb_result_count || raw.knowledgeResultCount || raw.knowledge_result_count || 0) || 0));
  const kbDocCount = Math.max(0, Math.min(999, Number(raw.kbDocCount || raw.kb_doc_count || raw.knowledgeDocCount || raw.knowledge_doc_count || 0) || 0));
  const kbChunkCount = Math.max(0, Math.min(99999, Number(raw.kbChunkCount || raw.kb_chunk_count || raw.knowledgeChunkCount || raw.knowledge_chunk_count || 0) || 0));
  const kbQueriesUsed = (Array.isArray(raw.kbQueriesUsed) ? raw.kbQueriesUsed : (Array.isArray(raw.kb_queries_used) ? raw.kb_queries_used : []))
    .map(q => String(q || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  const kbSearchResults = _normalizeReasoningKbResultItems(raw.kbSearchResults || raw.kb_search_results || raw.knowledgeResults || raw.knowledge_results || [], 12);
  if(useKnowledgeBase || kbResultCount > 0 || kbQueriesUsed.length || kbSearchResults.length) out.useKnowledgeBase = true;
  if(kbResultCount) out.kbResultCount = kbResultCount;
  if(kbDocCount) out.kbDocCount = kbDocCount;
  if(kbChunkCount) out.kbChunkCount = kbChunkCount;
  if(kbQueriesUsed.length) out.kbQueriesUsed = kbQueriesUsed;
  if(kbSearchResults.length) out.kbSearchResults = kbSearchResults;

  const useVisual = !!(raw.useVisual || raw.use_visual);
  const visualIntent = String(raw.visualIntent || raw.visual_intent || '').trim().slice(0, 60);
  const imageStage = String(raw.imageStage || raw.image_stage || '').trim().slice(0, 60);
  const imageResultCount = Math.max(0, Math.min(99, Number(raw.imageResultCount || raw.image_result_count || raw.imageResults || raw.image_results || 0) || 0));
  const imageQueriesUsed = (Array.isArray(raw.imageQueriesUsed) ? raw.imageQueriesUsed : (Array.isArray(raw.image_queries_used) ? raw.image_queries_used : []))
    .map(q => String(q || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  if(useVisual) out.useVisual = true;
  if(visualIntent) out.visualIntent = visualIntent;
  if(imageStage) out.imageStage = imageStage;
  if(imageResultCount) out.imageResultCount = imageResultCount;
  if(imageQueriesUsed.length) out.imageQueriesUsed = imageQueriesUsed;

  const rawFileProgressItems = raw.fileProgressItems || raw.file_progress_items || raw.fileProgress || raw.file_progress || [];
  const fileProgressItems = _normalizeReasoningFileProgressItems(rawFileProgressItems, 16);
  if(fileProgressItems.length) out.fileProgressItems = fileProgressItems;
  const fileEditAudits = _normalizeReasoningFileEditAudits(raw.fileEditAudits || raw.file_edit_audits || [], 4);
  if(fileEditAudits.length) out.fileEditAudits = fileEditAudits;
  const fileToolUsed = !!(raw.fileToolUsed || raw.file_tool_used);
  const fileToolRounds = Math.max(0, Math.min(9, Number(raw.fileToolRounds || raw.file_tool_rounds || 0) || 0));
  const artifactCount = Math.max(0, Math.min(99, Number(raw.artifactCount || raw.artifact_count || 0) || 0));
  const artifactFilenames = (Array.isArray(raw.artifactFilenames) ? raw.artifactFilenames : (Array.isArray(raw.artifact_filenames) ? raw.artifact_filenames : []))
    .map(x => String(x || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  if(fileToolUsed) out.fileToolUsed = true;
  if(fileToolRounds) out.fileToolRounds = fileToolRounds;
  if(artifactCount) out.artifactCount = artifactCount;
  if(artifactFilenames.length) out.artifactFilenames = artifactFilenames;

  const webPlanningAt = Number(raw.webPlanningAt || raw.web_planning_at || 0) || 0;
  const webSearchingAt = Number(raw.webSearchingAt || raw.web_searching_at || 0) || 0;
  const webResultsRevealAt = Number(raw.webResultsRevealAt || raw.web_results_reveal_at || 0) || 0;
  const webSourcesRevealAt = Number(raw.webSourcesRevealAt || raw.web_sources_reveal_at || 0) || 0;
  if(webPlanningAt > 0) out.webPlanningAt = webPlanningAt;
  if(webSearchingAt > 0) out.webSearchingAt = webSearchingAt;
  if(webResultsRevealAt > 0) out.webResultsRevealAt = webResultsRevealAt;
  if(webSourcesRevealAt > 0) out.webSourcesRevealAt = webSourcesRevealAt;
  const nativeReasoningConnected = !!(raw.nativeReasoningConnected || raw.native_reasoning_connected);
  const nativeReasoningDone = !!(raw.nativeReasoningDone || raw.native_reasoning_done);
  const nativeReasoningSource = String(raw.nativeReasoningSource || raw.native_reasoning_source || '').trim().slice(0, 40);
  const nativeReasoningText = String(raw.nativeReasoningText || raw.native_reasoning_text || '').replace(/\r\n/g, '\n');
  const nativeReasoningStartAt = Number(raw.nativeReasoningStartAt || raw.native_reasoning_start_at || 0) || 0;
  const nativeReasoningEndAt = Number(raw.nativeReasoningEndAt || raw.native_reasoning_end_at || 0) || 0;
  if(nativeReasoningConnected || nativeReasoningText) out.nativeReasoningConnected = true;
  if(nativeReasoningDone) out.nativeReasoningDone = true;
  if(nativeReasoningSource) out.nativeReasoningSource = nativeReasoningSource;
  if(nativeReasoningText) out.nativeReasoningText = nativeReasoningText;
  if(nativeReasoningStartAt > 0) out.nativeReasoningStartAt = nativeReasoningStartAt;
  if(nativeReasoningEndAt > 0) out.nativeReasoningEndAt = nativeReasoningEndAt;
  const nativeReasoningSegments = _normalizeNativeReasoningSegments(
    raw.nativeReasoningSegments || raw.native_reasoning_segments || raw.nativeReasoningTimeline || raw.native_reasoning_timeline || [],
    80
  );
  if(nativeReasoningSegments.length) out.nativeReasoningSegments = nativeReasoningSegments;
  return out;
}
function _pendingNativeReasoningEntryFromMeta(meta){
  const m = _normalizePendingAssistantReasoningMeta(meta || {});
  const text = String(m.nativeReasoningText || '').trim();
  const connected = !!(m.nativeReasoningConnected || text);
  if(!connected) return null;
  const done = !!m.nativeReasoningDone;
  const preview = text ? text.replace(/\s+/g, ' ').trim().slice(-220) : '';
  return {
    key: 'native_reasoning',
    title: done ? '已完成' : '思考中',
    detail: preview || _reasoningNativeSourceLabel(m.nativeReasoningSource),
    queries: [],
    stage: 'think',
    state: done ? 'done' : 'active',
    ts: Number(m.nativeReasoningEndAt || m.nativeReasoningStartAt || Date.now()) || Date.now(),
    text: done ? '已完成' : '思考中',
  };
}
function _reasoningMetaHasVisibleContent(meta){
  const m = _normalizePendingAssistantReasoningMeta(meta || {});
  if(m.nativeReasoningConnected || String(m.nativeReasoningText || '').trim()) return true;
  if(m.useWebResearch || m.useKnowledgeBase || m.useVisual) return true;
  if(Number(m.sourceCount || 0) || Number(m.resultCount || 0) || Number(m.pageCount || 0) || Number(m.searchRounds || 0)) return true;
  if(Number(m.kbResultCount || 0) || Number(m.kbDocCount || 0) || Number(m.kbChunkCount || 0)) return true;
  if(Number(m.imageResultCount || 0) || Number(m.fileToolRounds || 0) || Number(m.artifactCount || 0)) return true;
  if(Array.isArray(m.queriesUsed) && m.queriesUsed.length) return true;
  if(Array.isArray(m.webQueryGroups) && m.webQueryGroups.length) return true;
  if(Array.isArray(m.activityEvents) && m.activityEvents.length) return true;
  if(Array.isArray(m.mcpCards) && m.mcpCards.length) return true;
  if(Array.isArray(m.progressEvents) && m.progressEvents.length) return true;
  if(Array.isArray(m.kbQueriesUsed) && m.kbQueriesUsed.length) return true;
  if(Array.isArray(m.imageQueriesUsed) && m.imageQueriesUsed.length) return true;
  if(Array.isArray(m.searchResults) && m.searchResults.length) return true;
  if(Array.isArray(m.nativeWebCalls) && m.nativeWebCalls.length) return true;
  if(Array.isArray(m.kbSearchResults) && m.kbSearchResults.length) return true;
  if(Array.isArray(m.fileProgressItems) && m.fileProgressItems.length) return true;
  if(Array.isArray(m.fileEditAudits) && m.fileEditAudits.length) return true;
  if(Array.isArray(m.artifactFilenames) && m.artifactFilenames.length) return true;
  return false;
}
function _mergeNativeReasoningEntry(reasoning, meta){
  const entry = _pendingNativeReasoningEntryFromMeta(meta);
  if(!entry) return _normalizePendingAssistantReasoning(reasoning || []);
  return _upsertReasoningEntry(reasoning || [], entry);
}
function _cleanStreamStatusForReasoning(text){
  let s = String(text || '').trim();
  if(!s) return '';
  s = s.replace(/（快速模式）/g, '').replace(/（代理模式）/g, '').trim();
  s = s.replace(/^[^\s：:]{1,16}\s+(?=(当前模型|正在|已|网络抖动|连接不稳|出错|完成|天气已更新))/,'').trim();
  return s;
}
function _reasoningStageFromStatus(text){
  const s = String(text || '');
  if(/搜索|联网|检索|引用来源/.test(s)) return 'search';
  if(/网页|链接|视觉|图片|天气|工具/.test(s)) return 'web';
  if(/生成|回答|回复|文件|停止|完成|出错|失败/.test(s)) return 'answer';
  return 'think';
}
function _reasoningRouteModeLabel(mode){
  const key = String(mode || '').trim().toLowerCase();
  return {
    direct_answer: '直连快答',
    weather: '天气增强',
    visual: '视觉增强',
    file: '文件交付',
    web_research: '联网研究',
  }[key] || '';
}
function _reasoningAnswerStrategyLabel(mode){
  const key = String(mode || '').trim().toLowerCase();
  return {
    fast_direct: '先直接回答',
    direct_with_caveat: '直接回答并保留边界',
    quick_then_verify: '先给方向再查证',
    research_first: '先研究再回答',
    tool_first: '先用工具再回答',
  }[key] || '';
}
function _reasoningNativeSourceLabel(source){
  const key = String(source || '').trim().toLowerCase();
  if(!key) return '';
  if(key === 'native_field') return '原生推理';
  if(key === 'think_tag') return '<think>推理';
  return key;
}
function _formatReasoningElapsedShort(ms){
  const total = Math.max(0, Math.floor((Number(ms || 0) || 0) / 1000));
  if(total === 0) return window.AperviaI18n?.t('activity.elapsed_few') || 'a few seconds';
  if(total < 60) return window.AperviaI18n?.t('activity.elapsed_seconds', {count:total}) || `${total}s`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return seconds > 0
    ? (window.AperviaI18n?.t('activity.elapsed_minutes_seconds', {minutes, seconds}) || `${minutes}m ${seconds}s`)
    : (window.AperviaI18n?.t('activity.elapsed_minutes', {count:minutes}) || `${minutes}m`);
}
function _reasoningStatusToEntry(raw){
  const s = _cleanStreamStatusForReasoning(raw);
  if(!s) return null;

  let title = '';
  let detail = '';
  let queries = [];
  let state = 'done';
  let stage = _reasoningStageFromStatus(s);

  if(/正在补充网页信息[:：]/.test(s)){
    title = '搜索中';
    detail = s.split(/[:：]/).slice(1).join('：').trim();
    queries = detail ? detail.split(/\s*\|\s*|\s*\/\s*|\s{2,}|\n+/).map(v=>String(v||'').trim()).filter(Boolean).slice(0, 8) : [];
    stage = 'search';
    state = 'active';
  }else if(/正在检索知识库/.test(s)){
    title = '正在检索知识库…';
    stage = 'search';
    state = 'active';
  }else if(/正在读取文件/.test(s)){
    title = '正在读取文件…';
    stage = 'search';
    state = 'active';
  }else if(/正在阅读网页/.test(s)){
    title = '正在阅读网页…';
    stage = 'search';
    state = 'active';
  }else if(/工具完成，继续生成回复/.test(s)){
    title = '工具结果已返回，正在整理回答…';
    stage = 'answer';
    state = 'done';
  }else if(/正在搜索[:：]/.test(s)){
    title = '查询中';
    detail = s.split(/[:：]/).slice(1).join('：').trim();
    queries = detail ? detail.split(/\s*\|\s*|\s*\/\s*|\s{2,}|\n+/).map(v=>String(v||'').trim()).filter(Boolean).slice(0, 8) : [];
    stage = 'search';
    state = 'active';
  }else if(/已找到相关图片/.test(s)){
    title = '已找到相关图片';
    stage = 'web';
    state = 'done';
  }else if(/已命中视觉增强通道/.test(s) || /视觉|图片/.test(s)){
    title = '正在处理图片与视觉信息…';
    stage = 'web';
    state = 'active';
  }else if(/正在查询天气/.test(s) || /天气已更新/.test(s)){
    title = /已更新/.test(s) ? '天气已更新' : '正在查询天气…';
    stage = 'web';
    state = /已更新/.test(s) ? 'done' : 'active';
  }else if(/联网研究|规划搜索|判断联网研究策略/.test(s)){
    title = '已命中联网研究，正在规划搜索…';
    stage = 'search';
    state = 'active';
  }else if(/交付文件|生成文件|写入文件|文件已生成|已确认需要交付文件/.test(s)){
    title = '正在生成文件…';
    stage = 'answer';
    state = 'active';
  }else if(/^已停止$/.test(s)){
    title = '已停止';
    stage = 'answer';
    state = 'warn';
  }else if(/出错|失败/.test(s)){
    title = '本轮处理失败';
    detail = s;
    stage = 'answer';
    state = 'error';
  }else{
    return null;
  }

  const key = `${stage}|${title}|${detail}|${queries.join('|')}`.slice(0, 500);
  return { key, title, detail, queries, stage, state, ts: Date.now(), text: s };
}
function _isFileGenerationStatusText(text){
  const s = _cleanStreamStatusForReasoning(text);
  if(!s) return false;
  return /交付文件|生成文件|写入文件|文件已生成|已确认需要交付文件|准备文件内容|文件交付/.test(s);
}

function _upsertReasoningEntry(list, entry){
  const out = _normalizePendingAssistantReasoning(list);
  if(!entry || !entry.key) return out;
  const last = out[out.length - 1];
  if(last && last.key === entry.key){
    last.state = entry.state || last.state || 'done';
    last.ts = Number(entry.ts || Date.now()) || Date.now();
    if(Array.isArray(entry.queries) && entry.queries.length) last.queries = entry.queries.map(q => String(q || '').trim()).filter(Boolean);
    if(entry.detail) last.detail = entry.detail;
    if(entry.title) last.title = entry.title;
    if(entry.text) last.text = entry.text;
    return out;
  }
  out.push(entry);
  return _normalizePendingAssistantReasoning(out.slice(-18));
}
function _persistSessionRuntimeSnapshot(id){
  const rt = ensureSessionRuntime(id);
  persistPendingAssistantSnapshot(id, {
    draft: rt.draftText,
    process: rt.draftProcessText,
    files: rt.draftFiles,
    imageReplies: rt.draftImageReplies,
    weatherPayload: rt.draftWeatherPayload,
    status: rt.statusText,
    streaming: rt.streaming,
    reasoning: rt.reasoning,
    reasoningMeta: rt.reasoningMeta,
    sources: rt.sources,
  });
  return rt;
}
const _reasoningRevealTimers = Object.create(null);
const _nativeReasoningTickTimers = Object.create(null);
function _setNativeReasoningTickTimer(id, active){
  const sid = String(id || '').trim();
  if(!sid) return;
  const prev = _nativeReasoningTickTimers[sid];
  if(prev){
    clearInterval(prev);
    delete _nativeReasoningTickTimers[sid];
  }
  if(!active) return;
  _nativeReasoningTickTimers[sid] = setInterval(()=>{
    try{
      if(String(store?.activeId || '').trim() === sid) syncVisibleDraftBubble(sid);
    }catch(_err){}
  }, 1000);
}
function _scheduleReasoningRevealRefresh(id, meta){
  const sid = String(id || '').trim();
  if(!sid) return;
  const rawMeta = _normalizePendingAssistantReasoningMeta(meta);
  const targets = [
    Number(rawMeta.webResultsRevealAt || 0) || 0,
    Number(rawMeta.webSourcesRevealAt || 0) || 0,
  ].filter(ts => ts > Date.now());
  if(!targets.length) return;
  if(Array.isArray(_reasoningRevealTimers[sid])){
    _reasoningRevealTimers[sid].forEach(timer => clearTimeout(timer));
  }
  _reasoningRevealTimers[sid] = targets.map(ts => setTimeout(()=>{
    try{
      if(String(store?.activeId || '').trim() === sid) syncVisibleDraftBubble(sid);
    }catch(_err){}
  }, Math.max(0, ts - Date.now()) + 20));
}

function _mergeReasoningSearchResults(prevItems, nextItems, limit=48){
  const merged = [];
  const seen = new Set();
  const add = (rows)=>{
    const normalized = _normalizeReasoningSearchResultItems(rows || [], 0);
    normalized.forEach(item => {
      const key = String(item.url || item.host || item.title || '').toLowerCase();
      if(!key || seen.has(key)) return;
      seen.add(key);
      merged.push(item);
    });
  };
  add(prevItems);
  add(nextItems);
  return merged.slice(0, Math.max(1, Math.min(Number(limit || _reasoningWebSourceItemsLimit()) || _reasoningWebSourceItemsLimit(), 500)));
}

function _mergeReasoningSourceItems(prevItems, nextItems, limit=_reasoningWebSourceItemsLimit()){
  // Search sources are plain website chips.  Keep all URL-bearing rows; callers
  // can normalize them again for display.
  return _mergeReasoningSearchResults(prevItems, nextItems, limit);
}

function _mergeReasoningWebQueryGroups(prevGroups, nextGroups){
  const out = [];
  const byKey = new Map();
  const makeKey = (group, fallbackIndex)=>{
    const queries = (Array.isArray(group?.queries) ? group.queries : [])
      .map(q => String(q || '').trim()).filter(Boolean);
    const round = Number(group?.round || 0) || 0;
    const index = Number(group?.index || fallbackIndex || 0) || 0;
    return queries.length ? `q:${queries.join('\n').toLowerCase()}` : `r:${round}|i:${index}`;
  };
  const addGroup = (group, fallbackIndex)=>{
    if(!group || typeof group !== 'object') return;
    const normalizedRows = _normalizeReasoningWebQueryGroups([group]);
    const normalized = normalizedRows[0];
    if(!normalized || !Array.isArray(normalized.queries) || !normalized.queries.length) return;
    const key = makeKey(normalized, fallbackIndex);
    const existingIndex = byKey.has(key) ? byKey.get(key) : -1;
    const rawSources = [];
    const collect = (row)=>{
      if(!row || typeof row !== 'object') return;
      ['sourceItems','source_items','searchResults','search_results','searchedResults','searched_results','sources','results','items'].forEach(k => {
        if(Array.isArray(row[k])) rawSources.push(...row[k]);
      });
    };
    collect(existingIndex >= 0 ? out[existingIndex] : null);
    collect(group);
    collect(normalized);
    const sourceItems = _mergeReasoningSourceItems([], rawSources, _reasoningWebSourceItemsLimit());
    const merged = {
      ...(existingIndex >= 0 ? out[existingIndex] : {}),
      ...normalized,
      resultCount: Math.max(
        Number(existingIndex >= 0 ? out[existingIndex].resultCount || out[existingIndex].result_count || 0 : 0) || 0,
        Number(group.resultCount || group.result_count || 0) || 0,
        Number(normalized.resultCount || normalized.result_count || 0) || 0,
        sourceItems.length
      ),
      sourceCount: Math.max(
        Number(existingIndex >= 0 ? out[existingIndex].sourceCount || out[existingIndex].source_count || 0 : 0) || 0,
        Number(group.sourceCount || group.source_count || 0) || 0,
        Number(normalized.sourceCount || normalized.source_count || 0) || 0,
        sourceItems.length
      ),
      ...(sourceItems.length ? { sourceItems, source_items: sourceItems } : {}),
    };
    if(existingIndex >= 0) out[existingIndex] = merged;
    else{
      byKey.set(key, out.length);
      out.push(merged);
    }
  };
  (Array.isArray(prevGroups) ? prevGroups : []).forEach((g, i)=>addGroup(g, i + 1));
  (Array.isArray(nextGroups) ? nextGroups : []).forEach((g, i)=>addGroup(g, i + 1));
  return out.slice(0, 24);
}

function _reasoningEventSessionId(item){
  return String(item?.sessionId || item?.session_id || item?.clientSessionId || item?.client_session_id || '').trim();
}

function _reasoningEventBelongsToSession(item, sessionId){
  const sid = String(sessionId || '').trim();
  const eventSid = _reasoningEventSessionId(item);
  return !sid || !eventSid || eventSid === sid;
}

function _tagReasoningEventsForSession(items, sessionId){
  const sid = String(sessionId || '').trim();
  const source = Array.isArray(items) ? items : [];
  return source
    .filter(item => item && typeof item === 'object' && _reasoningEventBelongsToSession(item, sid))
    .map(item => {
      if(!sid || _reasoningEventSessionId(item)) return item;
      return { ...item, sessionId:sid, session_id:sid, clientSessionId:sid, client_session_id:sid };
    });
}

function _reasoningMetaPanelRefreshOpts(activityOnlyPatch, patchHasTerminalActivity){
  const terminal = !!patchHasTerminalActivity;
  if(activityOnlyPatch){
    return { immediate:true, terminal, activityStream:true };
  }
  return { throttleMs:520, terminal, immediate:terminal };
}

function setSessionRuntimeReasoningMeta(id, patch){
  const sid = String(id || '').trim();
  const rt = ensureSessionRuntime(id);
  const rawPatch = (patch && typeof patch === 'object') ? patch : {};
  const rawPatchKeys = Object.keys(rawPatch).filter(k => rawPatch[k] !== undefined);
  const activityOnlyPatch = rawPatchKeys.length > 0 && rawPatchKeys.every(k => /^(activityEvents|activity_events|progressEvents|progress_events)$/.test(k));
  const prev = _normalizePendingAssistantReasoningMeta(rt.reasoningMeta);
  const nextPatch = _normalizePendingAssistantReasoningMeta(patch);
  if(Array.isArray(nextPatch.activityEvents)) nextPatch.activityEvents = _tagReasoningEventsForSession(nextPatch.activityEvents, sid);
  if(Array.isArray(nextPatch.progressEvents)) nextPatch.progressEvents = _tagReasoningEventsForSession(nextPatch.progressEvents, sid);
  if(Array.isArray(prev.activityEvents)) prev.activityEvents = _tagReasoningEventsForSession(prev.activityEvents, sid);
  if(Array.isArray(prev.progressEvents)) prev.progressEvents = _tagReasoningEventsForSession(prev.progressEvents, sid);
  const now = Date.now();
  const patchActivityRows = [
    ...(Array.isArray(nextPatch.activityEvents) ? nextPatch.activityEvents : []),
    ...(Array.isArray(nextPatch.progressEvents) ? nextPatch.progressEvents : []),
  ];
  const patchHasTerminalActivity = patchActivityRows.some(row => {
    const state = String(row?.state || row?.status || '').trim().toLowerCase();
    return /^(done|completed|searched|warn|warning|error|failed)$/.test(state);
  });

  const nextWebQueryGroups = _mergeReasoningWebQueryGroups(prev.webQueryGroups || [], nextPatch.webQueryGroups || []);
  const useWebResearch = !!(nextPatch.useWebResearch || prev.useWebResearch || nextPatch.routeMode === 'web_research' || prev.routeMode === 'web_research' || nextWebQueryGroups.length);
  if(nextWebQueryGroups.length) nextPatch.webQueryGroups = nextWebQueryGroups;
  const nextSearchResults = _mergeReasoningSearchResults(prev.searchResults || [], nextPatch.searchResults || [], 48);
  if(nextSearchResults.length) nextPatch.searchResults = nextSearchResults;
  const nextQueriesUsed = Array.isArray(nextPatch.queriesUsed) ? nextPatch.queriesUsed : (Array.isArray(prev.queriesUsed) ? prev.queriesUsed : []);
  const nextResultCount = Math.max(Number(nextPatch.resultCount || 0) || 0, Number(prev.resultCount || 0) || 0);
  const nextSourceCount = Math.max(Number(nextPatch.sourceCount || 0) || 0, Number(prev.sourceCount || 0) || 0);
  const nextActivityEvents = _normalizeReasoningProgressEvents([
    ...(Array.isArray(prev.activityEvents) ? prev.activityEvents : []),
    ...(Array.isArray(nextPatch.activityEvents) ? nextPatch.activityEvents : []),
  ], 80);
  if(nextActivityEvents.length) nextPatch.activityEvents = nextActivityEvents;

  // ActivityEvent is the canonical timeline.  Only keep legacy progressEvents
  // when the backend did not provide canonical events for this session.
  if(nextActivityEvents.length){
    nextPatch.progressEvents = [];
  }else{
    const nextProgressEvents = _normalizeReasoningProgressEvents([
      ...(Array.isArray(prev.progressEvents) ? prev.progressEvents : []),
      ...(Array.isArray(nextPatch.progressEvents) ? nextPatch.progressEvents : []),
    ], 30);
    if(nextProgressEvents.length) nextPatch.progressEvents = nextProgressEvents;
  }

  if(useWebResearch && !Number(prev.webPlanningAt || 0)){
    nextPatch.webPlanningAt = now;
  }else if(Number(prev.webPlanningAt || 0) > 0 && !Number(nextPatch.webPlanningAt || 0)){
    nextPatch.webPlanningAt = Number(prev.webPlanningAt || 0);
  }

  if(nextQueriesUsed.length){
    nextPatch.webSearchingAt = Number(prev.webSearchingAt || 0) || now;
  }else if(Number(prev.webSearchingAt || 0) > 0 && !Number(nextPatch.webSearchingAt || 0)){
    nextPatch.webSearchingAt = Number(prev.webSearchingAt || 0);
  }

  if(nextResultCount > 0){
    const baseRevealAt = Number(prev.webResultsRevealAt || 0) || (Number(nextPatch.webSearchingAt || 0) > 0 ? (now + 520) : (now + 760));
    nextPatch.webResultsRevealAt = baseRevealAt;
  }else if(Number(prev.webResultsRevealAt || 0) > 0 && !Number(nextPatch.webResultsRevealAt || 0)){
    nextPatch.webResultsRevealAt = Number(prev.webResultsRevealAt || 0);
  }

  if(nextSourceCount > 0){
    const resultRevealAt = Number(nextPatch.webResultsRevealAt || prev.webResultsRevealAt || 0) || (now + 760);
    const baseRevealAt = Number(prev.webSourcesRevealAt || 0) || (resultRevealAt + 420);
    nextPatch.webSourcesRevealAt = baseRevealAt;
  }else if(Number(prev.webSourcesRevealAt || 0) > 0 && !Number(nextPatch.webSourcesRevealAt || 0)){
    nextPatch.webSourcesRevealAt = Number(prev.webSourcesRevealAt || 0);
  }

  rt.reasoningMeta = {
    ...prev,
    ..._normalizePendingAssistantReasoningMeta(nextPatch),
  };
  // Activity/inline rendering now reads nativeReasoning* directly from reasoningMeta.
  // Do not create the old synthetic reasoning[] entry ("思考中/已完成"), because it
  // can appear beside native reasoning as a second grouped推理 source.
  if(!activityOnlyPatch){
    _persistSessionRuntimeSnapshot(id);
  }
  _scheduleReasoningRevealRefresh(id, rt.reasoningMeta);
  try{
    if(typeof refreshActivityPanelForVisibleSession === 'function'){
      refreshActivityPanelForVisibleSession(
        id,
        _reasoningMetaPanelRefreshOpts(activityOnlyPatch, patchHasTerminalActivity),
      );
    }
  }catch(_){ }
  return rt;
}
function pushSessionRuntimeReasoningStatus(id, rawStatus){
  const rt = ensureSessionRuntime(id);
  const entry = _reasoningStatusToEntry(rawStatus);
  if(!entry) return rt;
  rt.reasoning = _upsertReasoningEntry(rt.reasoning, entry);
  _persistSessionRuntimeSnapshot(id);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function pushSessionRuntimeReasoningSources(id, count){
  const n = Math.max(0, Math.min(99, Number(count || 0) || 0));
  const rt = ensureSessionRuntime(id);
  if(n > 0){
    rt.reasoning = _upsertReasoningEntry(rt.reasoning, {
      key: `sources|${n}`,
      title: `检索到 ${n} 个引用来源`,
      detail: '',
      queries: [],
      stage: 'search',
      state: 'done',
      ts: Date.now(),
      text: `检索到 ${n} 个引用来源`,
    });
  }
  rt.reasoningMeta = { ..._normalizePendingAssistantReasoningMeta(rt.reasoningMeta), ...(n > 0 ? { sourceCount:n } : {}) };
  _persistSessionRuntimeSnapshot(id);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function pushSessionRuntimeNativeReasoningDelta(id, text, source='native_field', eventOrder=0, eventKey=''){
  const piece = String(text || '');
  if(!piece) return ensureSessionRuntime(id);
  const rt = ensureSessionRuntime(id);
  const prevMeta = _normalizePendingAssistantReasoningMeta(rt.reasoningMeta);
  const now = Date.now();
  const mergedText = _joinNativeReasoningDeltaText(prevMeta.nativeReasoningText || '', piece);
  const preview = mergedText.replace(/\s+/g, ' ').trim();
  const normalizedSource = String(source || prevMeta.nativeReasoningSource || 'native_field').trim().slice(0, 40) || 'native_field';
  const keepSegments = _nativeReasoningSourceKeepsSegments(normalizedSource);
  rt.reasoningMeta = {
    ...prevMeta,
    nativeReasoningConnected: true,
    nativeReasoningDone: false,
    nativeReasoningSource: normalizedSource,
    nativeReasoningText: mergedText,
    nativeReasoningStartAt: Number(prevMeta.nativeReasoningStartAt || 0) || now,
    nativeReasoningEndAt: 0,
    nativeReasoningSegments: keepSegments ? _appendNativeReasoningSegment(prevMeta, piece, normalizedSource, now, eventOrder, eventKey) : [],
  };
  // Do not mirror native reasoning into legacy reasoning[].  The panel consumes
  // nativeReasoningSegments/nativeReasoningText from reasoningMeta directly.
  _persistSessionRuntimeSnapshot(id);
  _setNativeReasoningTickTimer(id, true);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id, { throttleMs: 900 }); }catch(_){ }
  return rt;
}
function finalizeSessionRuntimeNativeReasoning(id, patch={}){
  const rt = ensureSessionRuntime(id);
  const prevMeta = _normalizePendingAssistantReasoningMeta(rt.reasoningMeta);
  if(!prevMeta.nativeReasoningConnected && !String(prevMeta.nativeReasoningText || '').trim()) return rt;
  const now = Date.now();
  const done = Object.prototype.hasOwnProperty.call(patch, 'nativeReasoningDone') ? !!patch.nativeReasoningDone : true;
  const source = String(patch.nativeReasoningSource || prevMeta.nativeReasoningSource || 'native_field').trim().slice(0, 40) || 'native_field';
  const mergedText = String(prevMeta.nativeReasoningText || '');
  const preview = mergedText.replace(/\s+/g, ' ').trim();
  const keepSegments = _nativeReasoningSourceKeepsSegments(source);
  rt.reasoningMeta = {
    ...prevMeta,
    nativeReasoningConnected: true,
    nativeReasoningDone: done,
    nativeReasoningSource: source,
    nativeReasoningText: mergedText,
    nativeReasoningStartAt: Number(prevMeta.nativeReasoningStartAt || 0) || now,
    nativeReasoningEndAt: done ? (Number(prevMeta.nativeReasoningEndAt || 0) || now) : 0,
    nativeReasoningSegments: keepSegments ? _finalizeNativeReasoningSegments(prevMeta, mergedText, done, source, now) : [],
  };
  // Do not mirror native reasoning into legacy reasoning[].  Keeping only
  // reasoningMeta prevents a duplicate grouped推理 row after completion.
  _persistSessionRuntimeSnapshot(id);
  _setNativeReasoningTickTimer(id, !done);
  try{ if(typeof refreshActivityPanelForVisibleSession === 'function') refreshActivityPanelForVisibleSession(id); }catch(_){ }
  return rt;
}
function _reasoningStepCssState(state){
  const s = String(state || '').trim().toLowerCase();
  if(s === 'active') return 'is-active';
  if(s === 'warn') return 'is-warn';
  if(s === 'error') return 'is-error';
  return '';
}
function _messageReasoningSnapshot(msg){
  const raw = (msg && typeof msg === 'object') ? msg : null;
  if(!raw) return null;
  const reasoningMeta = _normalizePendingAssistantReasoningMeta(raw.reasoningMeta || raw._reasoningMeta || {});
  const reasoning = _mergeNativeReasoningEntry(_normalizePendingAssistantReasoning(raw.reasoning || raw._reasoning || []), reasoningMeta);
  const sourceCount = Math.max(
    Number(reasoningMeta.sourceCount || 0) || 0,
    Array.isArray(raw.sources) ? raw.sources.length : 0
  );
  if(!reasoning.length && !Object.keys(reasoningMeta).length && !sourceCount) return null;
  return {
    reasoning,
    reasoningMeta: reasoningMeta,
    sourceCount,
    sources: normalizeAssistantSourceItems(raw.sources || raw.references || raw.citations || []),
  };
}
function _reasoningQueriesForDisplay(items, meta){
  const out = [];
  const seen = new Set();
  const push = (value)=>{
    const q = String(value || '').trim();
    if(!q) return;
    const key = q.toLowerCase();
    if(seen.has(key)) return;
    seen.add(key);
    out.push(q);
  };
  for(const q of (Array.isArray(meta?.queriesUsed) ? meta.queriesUsed : [])) push(q);
  for(const q of (Array.isArray(meta?.kbQueriesUsed) ? meta.kbQueriesUsed : [])) push(q);
  for(const q of (Array.isArray(meta?.imageQueriesUsed) ? meta.imageQueriesUsed : [])) push(q);
  for(const item of _normalizePendingAssistantReasoning(items)){
    for(const q of (Array.isArray(item?.queries) ? item.queries : [])) push(q);
  }
  return out;
}
function _chunkReasoningQueries(list, size=3){
  const out = [];
  const arr = Array.isArray(list) ? list : [];
  const chunkSize = Math.max(1, Number(size || 3) || 3);
  for(let i = 0; i < arr.length; i += chunkSize){
    out.push(arr.slice(i, i + chunkSize));
  }
  return out;
}

function _reasoningTinyHash(value){
  const s = String(value || '');
  let h = 2166136261;
  for(let i = 0; i < s.length; i += 1){
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function _sandboxProgressStableKey(item){
  const key = String(item?.key || '').trim();
  const stage = String(item?.stage || '').trim().toLowerCase();
  const tool = String(item?.tool || '').trim().toLowerCase();
  const operationKey = String(item?.operation_key || item?.operationKey || '').trim();
  const title = String(item?.title || item?.message || item?.text || '').trim();
  const command = String(item?.command || item?.display_command || item?.displayCommand || '').trim();
  const detailBasis = String(item?.detail || item?.targetFilename || item?.target_filename || title || '').trim();
  if(tool === 'sandbox_run'){
    if(operationKey) return `sandbox_run|${operationKey}`;
    if(command) return `sandbox_run|cmd:${_reasoningTinyHash(command)}`;
    let m = key.match(/^sandbox_run\|(.+)$/i);
    if(m && m[1] && !/^default$/i.test(m[1])) return `sandbox_run|${m[1]}`;
    m = key.match(/^sandbox\|sandbox_run\|([^|]+)/i);
    if(m && m[1] && !/^default$/i.test(m[1])) return `sandbox_run|${m[1]}`;
    return detailBasis ? `sandbox_run|detail:${_reasoningTinyHash(detailBasis)}` : '';
  }
  if(/^sandbox_(progress|result)\|/.test(key)) return key;
  if(tool === 'sandbox_list_files'){
    if(command) return `sandbox_list_files|cmd:${_reasoningTinyHash(command)}`;
    return key ? `sandbox_list_files|${_reasoningTinyHash(key || detailBasis || title)}` : 'sandbox_list_files|default';
  }
  if(/^sandbox\|sandbox_import_files\|[^|]+\|/.test(key)){
    if(detailBasis) return `${key.includes('done') || key.includes('error') ? 'sandbox_result|import_done' : 'sandbox_progress|import_active'}|${_reasoningTinyHash(detailBasis)}`;
    return key;
  }
  if(/^sandbox\|sandbox_(write_file|read_file)\|/.test(key)) return key.includes('done') || key.includes('error') ? 'sandbox_result|file_done' : 'sandbox_progress|file_active';
  if(/^sandbox\|sandbox_publish_files\|/.test(key)) return key.includes('done') || key.includes('error') ? 'sandbox_result|publish_done' : 'sandbox_progress|publish_active';
  if(key.startsWith('sandbox|arguments|')){
    const toolFromKey = key.split('|')[2] || '';
    return `sandbox_progress|sandbox_arguments_streaming|${toolFromKey || 'sandbox'}`;
  }
  if(/^sandbox\|sandbox_create_office_file\|/.test(key)){
    return key.includes('done') ? 'sandbox_result|create_office_done' : 'sandbox_progress|create_office_active';
  }
  if(/^sandbox\|sandbox_write_files?\|/.test(key)){
    return key.includes('done') ? 'sandbox_result|write_done' : 'sandbox_progress|write_active';
  }
  if(stage === 'sandbox_arguments_streaming') return `sandbox_progress|${stage}|${tool || 'sandbox'}`;
  if(stage === 'sandbox_publish_done') return 'sandbox_result|publish_done';
  if(stage === 'sandbox_start' && tool === 'sandbox_import_files'){
    return detailBasis ? `sandbox_progress|import_active|${_reasoningTinyHash(detailBasis)}` : 'sandbox_progress|import_active';
  }
  if((stage === 'sandbox_done' || stage === 'sandbox_error') && tool === 'sandbox_import_files'){
    return detailBasis ? `sandbox_result|import_done|${_reasoningTinyHash(detailBasis)}` : 'sandbox_result|import_done';
  }
  if(stage === 'sandbox_start' && tool === 'sandbox_publish_files') return 'sandbox_progress|publish_active';
  if((stage === 'sandbox_done' || stage === 'sandbox_error') && tool === 'sandbox_publish_files') return 'sandbox_result|publish_done';
  if(tool === 'sandbox_create_office_file'){
    if(stage.includes('done')) return 'sandbox_result|create_office_done';
    return 'sandbox_progress|create_office_active';
  }
  if(tool === 'sandbox_write_file' || tool === 'sandbox_write_files'){
    if(stage.includes('done')) return 'sandbox_result|write_done';
    return 'sandbox_progress|write_active';
  }
  if(tool === 'sandbox_publish_files'){
    if(stage.includes('done')) return 'sandbox_result|publish_done';
    return 'sandbox_progress|publish_active';
  }
  if(/正在准备沙盒工具参数|正在写入沙盒|已接收约/.test(title)) return 'sandbox_progress|create_office_active';
  if(/已生成 Office\/PDF 文件/.test(title)) return 'sandbox_result|create_office_done';
  if(/已发布沙盒文件|沙盒文件已发布|文件已保存/.test(title)) return 'sandbox_result|publish_done';
  return '';
}


function _mergeReasoningProgressEntry(prev, entry){
  const oldItem = prev && typeof prev === 'object' ? prev : {};
  const newItem = entry && typeof entry === 'object' ? entry : {};
  const merged = { ...oldItem, ...newItem, ts: Number(oldItem.ts || 0) || newItem.ts, seq: Number(oldItem.seq || 0) || newItem.seq };
  const tool = String(newItem.tool || oldItem.tool || '').toLowerCase();
  const isSandboxRun = tool === 'sandbox_run' || String(newItem.key || oldItem.key || '').startsWith('sandbox_run|');
  if(!isSandboxRun) return merged;
  const hasOwn = (obj, key)=>Object.prototype.hasOwnProperty.call(obj || {}, key);
  const oldCommand = String(oldItem.command || '').trim();
  const newCommand = String(newItem.command || '').trim();
  const oldOp = String(oldItem.operationKey || oldItem.operation_key || '').trim();
  const newOp = String(newItem.operationKey || newItem.operation_key || '').trim();
  const sameOp = !!(oldOp && newOp && oldOp === newOp);
  const sameCommand = !!(oldCommand && (!newCommand || oldCommand === newCommand));
  const canCarryDebug = sameOp || sameCommand;
  merged.command = hasOwn(newItem, 'command') ? (newItem.command || '') : (canCarryDebug ? (oldItem.command || '') : '');
  merged.stdout = hasOwn(newItem, 'stdout') ? (newItem.stdout || '') : (canCarryDebug ? (oldItem.stdout || '') : '');
  merged.stderr = hasOwn(newItem, 'stderr') ? (newItem.stderr || '') : (canCarryDebug ? (oldItem.stderr || '') : '');
  if(hasOwn(newItem, 'exitCode')) merged.exitCode = newItem.exitCode;
  else if(canCarryDebug && hasOwn(oldItem, 'exitCode')) merged.exitCode = oldItem.exitCode;
  else delete merged.exitCode;
  return merged;
}

function _compressReasoningItemsForDisplay(items, meta, snapshot){
  const list = _normalizePendingAssistantReasoning(items);
  const routeMode = String(meta?.routeMode || snapshot?.routeMode || snapshot?.route_mode || '').trim().toLowerCase();
  const useWebResearch = !!(meta?.useWebResearch || meta?.use_web_research || snapshot?.useWebResearch || snapshot?.use_web_research);
  const useVisual = !!(meta?.useVisual || meta?.use_visual || snapshot?.useVisual || snapshot?.use_visual);
  const visualIntent = String(meta?.visualIntent || meta?.visual_intent || snapshot?.visualIntent || snapshot?.visual_intent || '').trim().toLowerCase();
  const imageStage = String(meta?.imageStage || meta?.image_stage || snapshot?.imageStage || snapshot?.image_stage || '').trim().toLowerCase();
  const imageResultCountRaw = Math.max(Number(meta?.imageResultCount || meta?.image_result_count || 0) || 0, Number(snapshot?.imageResultCount || snapshot?.image_result_count || 0) || 0);
  const imageQueriesUsed = Array.isArray(meta?.imageQueriesUsed) ? meta.imageQueriesUsed : (Array.isArray(snapshot?.imageQueriesUsed) ? snapshot.imageQueriesUsed : []);
  const isGeneratedImageVisual = !!(
    visualIntent === 'image_generation'
    || visualIntent === 'image_generate'
    || visualIntent === 'image_edit'
    || visualIntent === 'image_variation'
    || (imageStage === 'generated' && imageResultCountRaw > 0 && !imageQueriesUsed.length)
  );
  const isVisualSearch = !!(!isGeneratedImageVisual && (useVisual || visualIntent === 'image_search' || imageStage || imageResultCountRaw > 0 || imageQueriesUsed.length));
  const kbQueriesUsed = Array.isArray(meta?.kbQueriesUsed) ? meta.kbQueriesUsed : (Array.isArray(snapshot?.kbQueriesUsed) ? snapshot.kbQueriesUsed : []);
  const kbResultCountRaw = Math.max(Number(meta?.kbResultCount || meta?.kb_result_count || 0) || 0, Number(snapshot?.kbResultCount || snapshot?.kb_result_count || 0) || 0);
  const kbDocCount = Math.max(Number(meta?.kbDocCount || meta?.kb_doc_count || 0) || 0, Number(snapshot?.kbDocCount || snapshot?.kb_doc_count || 0) || 0);
  const kbChunkCount = Math.max(Number(meta?.kbChunkCount || meta?.kb_chunk_count || 0) || 0, Number(snapshot?.kbChunkCount || snapshot?.kb_chunk_count || 0) || 0);
  const kbSearchResults = _normalizeReasoningKbResultItems(meta?.kbSearchResults || snapshot?.kbSearchResults || [], 12);
  const useKnowledgeBase = !!(meta?.useKnowledgeBase || snapshot?.useKnowledgeBase || kbQueriesUsed.length || kbResultCountRaw > 0 || kbSearchResults.length);
  const nativeReasoningText = String(meta?.nativeReasoningText || snapshot?.nativeReasoningText || '').trim();
  const nativeReasoningConnected = !!(meta?.nativeReasoningConnected || snapshot?.nativeReasoningConnected || nativeReasoningText);
  const nativeReasoningDone = !!(meta?.nativeReasoningDone || snapshot?.nativeReasoningDone);
  const nativeReasoningSource = String(meta?.nativeReasoningSource || snapshot?.nativeReasoningSource || '').trim();
  const searchStage = String(meta?.searchStage || meta?.search_stage || snapshot?.searchStage || snapshot?.search_stage || '').trim().toLowerCase();
  const searchResultsForCount = _normalizeReasoningSearchResultItems(meta?.searchResults || snapshot?.searchResults || [], 0);
  const nativeWebCalls = _normalizeReasoningNativeWebCallItems(meta?.nativeWebCalls || snapshot?.nativeWebCalls || [], 12);
  const webQueryGroups = _normalizeReasoningWebQueryGroups(meta?.webQueryGroups || snapshot?.webQueryGroups || []);
  const nativeWebCallCount = Math.max(Number(meta?.nativeWebCallCount || 0) || 0, Number(snapshot?.nativeWebCallCount || 0) || 0, nativeWebCalls.length);
  const sourceCountRaw = Math.max(Number(meta?.sourceCount || 0) || 0, Number(snapshot?.sourceCount || 0) || 0);
  const resultCountRaw = Math.max(Number(meta?.resultCount || 0) || 0, Number(snapshot?.resultCount || 0) || 0, searchResultsForCount.length);
  const pageCount = Math.max(Number(meta?.pageCount || 0) || 0, Number(snapshot?.pageCount || 0) || 0);
  const nowTs = Date.now();
  const resultRevealAt = Math.max(Number(meta?.webResultsRevealAt || meta?.web_results_reveal_at || 0) || 0, Number(snapshot?.webResultsRevealAt || snapshot?.web_results_reveal_at || 0) || 0);
  const sourceRevealAt = Math.max(Number(meta?.webSourcesRevealAt || meta?.web_sources_reveal_at || 0) || 0, Number(snapshot?.webSourcesRevealAt || snapshot?.web_sources_reveal_at || 0) || 0);
  const resultCount = resultCountRaw > 0 && resultRevealAt > nowTs ? 0 : resultCountRaw;
  const sourceCount = sourceCountRaw > 0 && sourceRevealAt > nowTs ? 0 : sourceCountRaw;
  const displayQueries = _reasoningQueriesForDisplay(list, meta);
  const queryGroups = _chunkReasoningQueries(displayQueries, 3);
  const errorItem = [...list].reverse().find(item => String(item?.state || '') === 'error');
  const warnItem = [...list].reverse().find(item => String(item?.state || '') === 'warn');
  const fileItem = [...list].find(item => /文件/.test(String(item?.title || '')));
  const weatherItem = [...list].find(item => /天气/.test(String(item?.title || '')));
  const visualItem = [...list].find(item => /视觉|图片/.test(String(item?.title || '')));
  const planningItem = [...list].reverse().find(item => /联网研究|规划搜索|判断联网研究策略/.test(`${item?.title || ''} ${item?.detail || ''} ${item?.text || ''}`));
  const searchingItem = [...list].reverse().find(item => /搜索中|查询中|补充网页信息|网页信息/.test(`${item?.title || ''} ${item?.detail || ''} ${item?.text || ''}`));
  const fileProgressItems = _normalizeReasoningFileProgressItems(meta?.fileProgressItems || snapshot?.fileProgressItems || [], 16);
  const fileEditAudits = _normalizeReasoningFileEditAudits(meta?.fileEditAudits || snapshot?.fileEditAudits || [], 4);
  const artifactFilenames = (Array.isArray(meta?.artifactFilenames) ? meta.artifactFilenames : (Array.isArray(snapshot?.artifactFilenames) ? snapshot.artifactFilenames : []))
    .map(x => String(x || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  const fileToolUsed = !!(meta?.fileToolUsed || snapshot?.fileToolUsed || Number(meta?.fileToolRounds || snapshot?.fileToolRounds || 0) > 0);
  const artifactCount = fileToolUsed ? Math.max(Number(meta?.artifactCount || 0) || 0, Number(snapshot?.artifactCount || 0) || 0, artifactFilenames.length) : 0;
  const hasSandboxPublishedArtifacts = !!(artifactFilenames.length && !fileEditAudits.length);
  const hasSandboxReasoning = fileProgressItems.some(item => _isSandboxFileProgressItem(item)) || hasSandboxPublishedArtifacts;
  const hasFileReasoning = !!(fileProgressItems.length || fileEditAudits.length || fileToolUsed || fileItem);
  const progressEvents = _normalizeReasoningProgressEvents(meta?.progressEvents || snapshot?.progressEvents || [], 30);
  const hasUnifiedSandboxOrFileTimeline = progressEvents.some(item => {
    const stage = String(item?.stage || '').trim().toLowerCase();
    const rawStage = String(item?.rawStage || item?.raw_stage || '').trim().toLowerCase();
    const tool = String(item?.tool || '').trim().toLowerCase();
    return stage === 'sandbox' || stage === 'file' || /^sandbox_/.test(rawStage) || /^sandbox_/.test(tool) || /^file_/.test(rawStage) || rawStage.includes('read_file');
  });
  if(hasUnifiedSandboxOrFileTimeline){
    const out = progressEvents.map(item => ({
      key: String(item.key || `${item.stage || 'progress'}|${item.title || ''}|${item.detail || ''}`).slice(0, 700),
      title: String(item.title || '').trim(),
      detail: String(item.detail || '').trim(),
      queries: Array.isArray(item.queries) ? item.queries.map(q => String(q || '').trim()).filter(Boolean) : [],
      stage: String(item.stage || 'answer') || 'answer',
      state: String(item.state || 'done') || 'done',
      ts: Number(item.ts || Date.now()) || Date.now(),
      ...(Number(item.seq || 0) > 0 ? { seq: Number(item.seq || 0) } : {}),
      rawStage: String(item.rawStage || item.raw_stage || '').trim(),
      tool: String(item.tool || '').trim(),
      source: String(item.source || '').trim(),
      text: String(item.text || item.title || '').trim(),
    })).filter(item => item.title);
    const hasProgressSearchRound = out.some(item => {
      const key = String(item.key || '').toLowerCase();
      const rawStage = String(item.rawStage || item.raw_stage || '').toLowerCase();
      return String(item.stage || '').toLowerCase() === 'search' || rawStage === 'web_query_group' || key.includes('query_group');
    });
    if(!hasProgressSearchRound && webQueryGroups.length){
      webQueryGroups.forEach((group, index)=>{
        const queries = Array.isArray(group.queries) ? group.queries.map(q => String(q || '').trim()).filter(Boolean) : [];
        if(!queries.length) return;
        const n = Number(group.index || index + 1) || (index + 1);
        out.push({
          key: String(group.key || `web_query_group|${n}|${queries.join('|')}`),
          title: `第 ${n} 次搜索中`,
          detail: '',
          queries,
          stage: 'search',
          state: String(group.state || '').trim() || ((String(group.status || '').toLowerCase() === 'searched') ? 'done' : 'active'),
          ts: Number(group.ts || Date.now() + index + 1) || (Date.now() + index + 1),
          text: `第 ${n} 次搜索中`,
        });
      });
    }
    out.sort((a, b)=>{
      const as = Number(a.seq || 0) || 0;
      const bs = Number(b.seq || 0) || 0;
      if(as > 0 && bs > 0 && as !== bs) return as - bs;
      if(as > 0 && bs <= 0) return -1;
      if(bs > 0 && as <= 0) return 1;
      return (Number(a.ts || 0) || 0) - (Number(b.ts || 0) || 0);
    });
    if(errorItem && !out.some(item => String(item.state || '') === 'error')) out.push(errorItem);
    else if(warnItem && !out.some(item => String(item.state || '') === 'warn')) out.push(warnItem);
    if(out.length) return out.slice(-24);
  }

  if(hasFileReasoning && !(routeMode === 'web_research' || useWebResearch || displayQueries.length || resultCount > 0 || sourceCount > 0)){
    const compact = [];
    const push = (item)=>{
      if(!item) return;
      compact.push({
        key: String(item.key || `${item.title || 'file'}|${item.detail || ''}`).slice(0, 500),
        title: String(item.title || '').trim(),
        detail: String(item.detail || '').trim(),
        queries: Array.isArray(item.queries) ? item.queries : [],
        stage: String(item.stage || 'search') || 'search',
        state: String(item.state || 'done') || 'done',
        ts: Number(item.ts || Date.now()) || Date.now(),
        text: String(item.text || item.title || '').trim(),
      });
    };
    if(fileProgressItems.length){
      for(const item of fileProgressItems){
        push(_fileProgressReasoningEntry(item));
      }
    }else if(fileItem){
      push(fileItem);
    }else{
      push({
        key:hasSandboxReasoning ? 'sandbox|start' : 'file_edit|start',
        title:hasSandboxReasoning ? '沙盒运行中' : '正在处理文件修改',
        detail:'',
        state:(fileEditAudits.length || artifactCount > 0) ? 'done' : 'active',
        ts:Date.now(),
        text:hasSandboxReasoning ? '沙盒运行中' : '正在处理文件修改',
      });
    }
    if(fileEditAudits.length){
      push({
        key:`file_edit_audit|${fileEditAudits.map(_fileAuditOutputLabel).join('|')}`.slice(0, 500),
        title:'已生成变更摘要',
        detail:fileEditAudits.map(_fileAuditOutputLabel).join('、').slice(0, 240),
        state:'done',
        ts:Date.now() + 20,
        text:'已生成变更摘要',
      });
    }
    if(artifactCount > 0 || artifactFilenames.length){
      push({
        key:`${hasSandboxReasoning ? 'sandbox_published' : 'file_saved'}|${artifactFilenames.join('|')}|${artifactCount}`.slice(0, 500),
        title:hasSandboxReasoning ? '沙盒文件已发布' : '文件已发布',
        detail:artifactFilenames.length ? artifactFilenames.join('、').slice(0, 240) : '',
        state:'done',
        ts:Date.now() + 30,
        text:hasSandboxReasoning ? '沙盒文件已发布' : '文件已发布',
      });
    }
    if(errorItem) compact.push(errorItem);
    else if(warnItem) compact.push(warnItem);
    const dedup = [];
    const seen = new Set();
    for(const item of compact){
      if(!item || !item.title) continue;
      const key = `${item.title}|${item.detail || ''}`;
      if(seen.has(key)) continue;
      seen.add(key);
      dedup.push(item);
    }
    if(dedup.length) return dedup;
  }

  if(useKnowledgeBase && !(routeMode === 'web_research' || useWebResearch || resultCountRaw > 0 || sourceCountRaw > 0 || isVisualSearch)){
    const compact = [];
    const kbQueryGroups = _chunkReasoningQueries(kbQueriesUsed, 3);
    const kbStatus = String(meta?.statusText || snapshot?.statusText || '').trim();
    compact.push({
      key: 'kb_search|planning',
      title: kbStatus || '正在检索知识库…',
      detail: kbDocCount || kbChunkCount ? `可检索文档 ${kbDocCount || 0} 个 · 片段 ${kbChunkCount || 0} 个` : '',
      queries: [],
      stage: 'search',
      state: (kbQueryGroups.length || kbResultCountRaw > 0) ? 'done' : 'active',
      ts: Date.now(),
      text: kbStatus || '正在检索知识库…',
    });
    if(kbQueryGroups.length){
      kbQueryGroups.forEach((group, index)=>{
        if(!Array.isArray(group) || !group.length) return;
        compact.push({
          key: `kb_query_group|${index}|${group.join('|')}`.slice(0, 500),
          title: index > 0 ? '补充检索知识库' : '检索知识库',
          detail: '',
          queries: group,
          stage: 'search',
          state: kbResultCountRaw > 0 ? 'done' : 'active',
          ts: Date.now() + index + 1,
          text: index > 0 ? '补充检索知识库' : '检索知识库',
        });
      });
    }
    if(kbResultCountRaw > 0){
      compact.push({
        key: `kb_results|${kbResultCountRaw}`,
        title: `命中 ${kbResultCountRaw} 个知识库片段`,
        detail: kbSearchResults.length ? kbSearchResults.map(x => x.citation || x.filename).filter(Boolean).slice(0, 4).join('、') : '',
        queries: [],
        stage: 'search',
        state: 'done',
        ts: Date.now() + 10,
        text: `命中 ${kbResultCountRaw} 个知识库片段`,
      });
    }
    if(errorItem) compact.push(errorItem);
    else if(warnItem) compact.push(warnItem);
    if(compact.length) return compact.slice(0, 7);
  }

  if(isVisualSearch && !(routeMode === 'web_research' || useWebResearch || resultCountRaw > 0 || pageCount > 0)){
    const compact = [];
    const visualQueries = displayQueries.length ? displayQueries : imageQueriesUsed;
    const visualGroups = _chunkReasoningQueries(visualQueries, 3);
    const visualStatus = String(meta?.statusText || snapshot?.statusText || '').trim();
    compact.push({
      key: 'visual_search|planning',
      title: visualStatus || '正在规划图片搜索…',
      detail: '',
      queries: [],
      stage: 'search',
      state: (visualGroups.length || imageResultCountRaw > 0 || sourceCount > 0 || imageStage === 'searched') ? 'done' : 'active',
      ts: Date.now(),
      text: visualStatus || '正在规划图片搜索…',
    });
    if(visualGroups.length){
      const labels = ['搜索图片中', '补充图片搜索中', '继续搜索图片中'];
      visualGroups.forEach((group, index)=>{
        if(!Array.isArray(group) || !group.length) return;
        compact.push({
          key: `visual_query_group|${index}|${group.join('|')}`.slice(0, 500),
          title: labels[index] || '搜索图片中',
          detail: '',
          queries: group,
          stage: 'search',
          state: (imageResultCountRaw > 0 || sourceCount > 0) ? 'done' : 'active',
          ts: Date.now() + index + 1,
          text: labels[index] || '搜索图片中',
        });
      });
    }
    if(imageResultCountRaw > 0){
      compact.push({
        key: `visual_results|${imageResultCountRaw}`,
        title: `找到 ${imageResultCountRaw} 张图片`,
        detail: '',
        queries: [],
        stage: 'search',
        state: sourceCount > 0 ? 'done' : 'active',
        ts: Date.now() + 10,
        text: `找到 ${imageResultCountRaw} 张图片`,
      });
    }
    if(sourceCount > 0){
      compact.push({
        key: `visual_sources|${sourceCount}`,
        title: `检索到 ${sourceCount} 个图片来源`,
        detail: '',
        queries: [],
        stage: 'search',
        state: 'done',
        ts: Date.now() + 11,
        text: `检索到 ${sourceCount} 个图片来源`,
      });
    }
    if(errorItem) compact.push(errorItem);
    else if(warnItem) compact.push(warnItem);
    if(compact.length) return compact.slice(0, 6);
  }

  if(routeMode === 'web_research' || useWebResearch || webQueryGroups.length || displayQueries.length || resultCount > 0 || sourceCount > 0 || nativeWebCalls.length || nativeWebCallCount > 0){
    const compact = [];
    const push = (item)=>{
      if(!item) return;
      compact.push({
        key: String(item.key || `${item.title || 'step'}|${item.detail || ''}|${(item.queries || []).join('|')}`).slice(0, 500),
        title: String(item.title || '').trim(),
        detail: String(item.detail || '').trim(),
        queries: Array.isArray(item.queries) ? item.queries.map(q => String(q || '').trim()).filter(Boolean) : [],
        stage: String(item.stage || 'search') || 'search',
        state: String(item.state || 'done') || 'done',
        ts: Number(item.ts || Date.now()) || Date.now(),
        text: String(item.text || item.title || '').trim(),
      });
    };

    const planningTitle = String(meta?.statusText || snapshot?.statusText || '').trim() || '已命中联网研究，正在规划搜索…';
    push({
      key: 'web_research|planning',
      title: planningItem?.title || planningTitle,
      detail: planningItem?.detail || '',
      queries: planningItem?.queries || [],
      stage: 'search',
      state: (displayQueries.length || resultCount > 0 || sourceCount > 0 || nativeWebCalls.length || searchStage === 'searched') ? 'done' : 'active',
      ts: planningItem?.ts || Date.now(),
      text: planningItem?.text || planningTitle,
    });

    if(webQueryGroups.length){
      webQueryGroups.forEach((group, index)=>{
        const queries = Array.isArray(group.queries) ? group.queries.map(q => String(q || '').trim()).filter(Boolean) : [];
        if(!queries.length) return;
        const n = Number(group.index || index + 1) || (index + 1);
        compact.push({
          key: String(group.key || `web_query_group|${n}|${queries.join('|')}`),
          title: `第 ${n} 次搜索中`,
          detail: '',
          queries,
          stage: 'search',
          state: String(group.state || '').trim() || ((String(group.status || '').toLowerCase() === 'searched') ? 'done' : 'active'),
          ts: Date.now() + index + 1,
          text: `第 ${n} 次搜索中`,
        });
      });
    }else if(queryGroups.length){
      queryGroups.forEach((group, index)=>{
        if(!Array.isArray(group) || !group.length) return;
        const n = index + 1;
        compact.push({
          key: `query_group|${index}|${group.join('|')}`.slice(0, 500),
          title: `第 ${n} 次搜索中`,
          detail: '',
          queries: group,
          stage: 'search',
          state: (sourceCount > 0 || (resultCount > 0 && index < queryGroups.length - 1)) ? 'done' : 'active',
          ts: Date.now() + index + 1,
          text: `第 ${n} 次搜索中`,
        });
      });
    }else if(resultCount <= 0 && sourceCount <= 0){
      push({
        key: 'web_research|searching',
        title: searchingItem?.title || '搜索中',
        detail: searchingItem?.detail || '',
        queries: searchingItem?.queries || [],
        stage: 'search',
        state: 'active',
        ts: searchingItem?.ts || (Date.now() + 1),
        text: searchingItem?.text || '搜索中',
      });
    }

    if(sourceCount > 0){
      compact.push({
        key: `sources|${sourceCount}`,
        title: `检索到 ${sourceCount} 个引用来源`,
        detail: '',
        queries: [],
        stage: 'search',
        state: 'done',
        ts: Date.now() + 11,
        text: `检索到 ${sourceCount} 个引用来源`,
      });
    }
    if(errorItem) compact.push(errorItem);
    else if(warnItem) compact.push(warnItem);

    const dedup = [];
    const seen = new Set();
    for(const item of compact){
      if(!item) continue;
      const key = `${item.title}|${item.detail || ''}|${(item.queries || []).join('|')}`;
      if(seen.has(key)) continue;
      seen.add(key);
      dedup.push(item);
    }
    if(dedup.length) return dedup;
  }

  if(nativeReasoningConnected || nativeReasoningText){
    const preview = nativeReasoningText.replace(/\s+/g, ' ').trim();
    const nativeItem = {
      key: 'native_reasoning',
      title: nativeReasoningDone ? '已完成' : '思考中',
      detail: preview ? preview.slice(-220) : _reasoningNativeSourceLabel(nativeReasoningSource),
      queries: [],
      stage: 'think',
      state: nativeReasoningDone ? 'done' : 'active',
      ts: Date.now(),
      text: nativeReasoningDone ? '已完成' : '思考中',
    };
    if(errorItem) return [nativeItem, errorItem];
    if(warnItem) return [nativeItem, warnItem];
    return [nativeItem];
  }

  if(fileItem) return [fileItem];
  if(weatherItem) return [weatherItem];
  if(visualItem) return [visualItem];
  if(errorItem) return [errorItem];
  if(warnItem) return [warnItem];
  return [];
}

function _shouldUseWebReasoningPanel(items, meta, snapshot){
  if(_reasoningHasFileActivity(meta, snapshot, items)) return true;
  const routeMode = String(meta?.routeMode || meta?.route_mode || snapshot?.routeMode || snapshot?.route_mode || '').trim().toLowerCase();
  const useWebResearch = !!(meta?.useWebResearch || meta?.use_web_research || snapshot?.useWebResearch || snapshot?.use_web_research);
  const useVisual = !!(meta?.useVisual || meta?.use_visual || snapshot?.useVisual || snapshot?.use_visual);
  const visualIntent = String(meta?.visualIntent || meta?.visual_intent || snapshot?.visualIntent || snapshot?.visual_intent || '').trim().toLowerCase();
  const imageResultCount = Math.max(Number(meta?.imageResultCount || 0) || 0, Number(snapshot?.imageResultCount || 0) || 0);
  if(useVisual || visualIntent === 'image_search' || imageResultCount > 0) return true;
  const nativeReasoningText = String(meta?.nativeReasoningText || snapshot?.nativeReasoningText || '').trim();
  const nativeReasoningConnected = !!(meta?.nativeReasoningConnected || snapshot?.nativeReasoningConnected || nativeReasoningText);
  if(nativeReasoningConnected) return true;
  if(routeMode === 'web_research' || useWebResearch) return true;
  const useKnowledgeBase = !!(meta?.useKnowledgeBase || snapshot?.useKnowledgeBase);
  const kbResultCount = Math.max(Number(meta?.kbResultCount || 0) || 0, Number(snapshot?.kbResultCount || 0) || 0);
  const kbQueriesUsed = Array.isArray(meta?.kbQueriesUsed) ? meta.kbQueriesUsed : (Array.isArray(snapshot?.kbQueriesUsed) ? snapshot.kbQueriesUsed : []);
  const kbSearchResults = _normalizeReasoningKbResultItems(meta?.kbSearchResults || snapshot?.kbSearchResults || [], 12);
  if(useKnowledgeBase || kbResultCount > 0 || kbQueriesUsed.length || kbSearchResults.length) return true;
  const sourceCount = Math.max(Number(meta?.sourceCount || 0) || 0, Number(snapshot?.sourceCount || 0) || 0);
  const resultCount = Math.max(Number(meta?.resultCount || 0) || 0, Number(snapshot?.resultCount || 0) || 0);
  if(sourceCount > 0 || resultCount > 0) return true;
  const searchResults = _normalizeReasoningSearchResultItems(meta?.searchResults || snapshot?.searchResults || [], 0);
  if(Array.isArray(searchResults) && searchResults.length) return true;
  const nativeWebCalls = _normalizeReasoningNativeWebCallItems(meta?.nativeWebCalls || snapshot?.nativeWebCalls || [], 12);
  const webQueryGroups = _normalizeReasoningWebQueryGroups(meta?.webQueryGroups || snapshot?.webQueryGroups || []);
  if(webQueryGroups.length) return true;
  const nativeWebCallCount = Math.max(Number(meta?.nativeWebCallCount || 0) || 0, Number(snapshot?.nativeWebCallCount || 0) || 0, nativeWebCalls.length);
  if(nativeWebCalls.length || nativeWebCallCount > 0) return true;
  const queries = _reasoningQueriesForDisplay(items, meta);
  if(Array.isArray(queries) && queries.length) return true;
  const list = _normalizePendingAssistantReasoning(items);
  return list.some(item => /搜索|查询|网站|来源|网页|联网|知识库|文档|片段|文件|修改|保存|验证|diff/i.test(`${item?.title || ''} ${item?.detail || ''} ${item?.text || ''}`));
}

function _composeReasoningPanelSnapshot(sessionId, opts={}){
  const o = opts || {};
  const rt = sessionId ? ensureSessionRuntime(sessionId) : null;
  const snapshot = (o.reasoningSnapshot && typeof o.reasoningSnapshot === 'object')
    ? o.reasoningSnapshot
    : _messageReasoningSnapshot(o.message || null);
  const hasMessageSnapshot = !!(o.message || o.reasoningSnapshot);
  const useRuntimeSnapshot = !!(rt && !hasMessageSnapshot);
  const reasoningMeta = _normalizePendingAssistantReasoningMeta(useRuntimeSnapshot ? rt.reasoningMeta : (snapshot?.reasoningMeta || {}));
  const reasoning = _mergeNativeReasoningEntry(_normalizePendingAssistantReasoning(useRuntimeSnapshot ? rt.reasoning : (snapshot?.reasoning || [])), reasoningMeta);
  return {
    ...(snapshot && typeof snapshot === 'object' ? snapshot : {}),
    reasoning,
    reasoningMeta,
    sources: normalizeAssistantSourceItems(useRuntimeSnapshot ? rt.sources : (snapshot?.sources || o?.message?.sources || o?.message?.references || o?.message?.citations || [])),
  };
}

const _activityInlinePlaybackState = Object.create(null);
const _activityInlinePlaybackLatest = Object.create(null);

function _activityInlineCleanText(value, fallback=reasoningUiT('stream.thinking', null, 'Thinking…')){
  const s = String(value || '').replace(/\s+/g, ' ').trim();
  return (s || fallback).slice(0, 520);
}

function _activityInlinePlaybackKey(sessionId, playback){
  const sid = String(sessionId || '').trim() || '__global__';
  return `${sid}|${String(playback?.runKey || 'inline_activity')}`.slice(0, 900);
}

function _activityInlineUnitMs(unit){
  const text = String(unit?.text || '');
  const base = String(unit?.kind || '').includes('search') ? 1000 : 900;
  const byLen = text.length * 18;
  const declared = Number(unit?.holdMs || 0) || 0;
  return Math.max(650, Math.min(Math.max(base, byLen, declared), 2400));
}

function _activityInlineResetState(key, playback){
  const st = {
    key,
    runKey:String(playback?.runKey || ''),
    currentKey:'',
    currentStartedAt:Date.now(),
    playedKeys:new Set(),
  };
  _activityInlinePlaybackState[key] = st;
  return st;
}

function _activityInlineGetState(key, playback){
  const runKey = String(playback?.runKey || '');
  let st = _activityInlinePlaybackState[key];
  if(!st || st.runKey !== runKey || !(st.playedKeys instanceof Set)) st = _activityInlineResetState(key, playback);
  return st;
}

function _activityInlineSelectPendingUnit(st, units, nowTs){
  if(st.currentKey){
    const current = units.find(unit => unit && unit.key === st.currentKey);
    if(current) return current;
    st.currentKey = '';
  }
  const next = units.find(unit => unit && unit.key && !st.playedKeys.has(unit.key));
  if(!next) return null;
  st.currentKey = next.key;
  st.currentStartedAt = nowTs;
  return next;
}

function _activityInlinePlaybackUnitIsCompletionNoise(value){
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return /^(?:(?:完成|已完成)|(?:completed|done))(?:\s*[·-]\s*\S+)?$/iu.test(text);
}

function _activityInlineComputePlayback(sessionId, playback, nowTs=Date.now()){
  const units = Array.isArray(playback?.units)
    ? playback.units.filter(unit => unit && String(unit.text || '').trim() && !_activityInlinePlaybackUnitIsCompletionNoise(unit.text))
    : [];
  const active = !!playback?.active;
  const completedText = reasoningUiT('stream.done', null, 'Completed');
  const doneText = _activityInlineCleanText(playback?.doneText || completedText, completedText);
  const key = _activityInlinePlaybackKey(sessionId, playback || {});
  const existingState = _activityInlinePlaybackState[key];
  const st = _activityInlineGetState(key, playback || {});

  const hasUnplayedUnit = ()=>units.some(unit => unit && unit.key && (unit.key === st.currentKey || !st.playedKeys.has(unit.key)));
  if(!active && playback?.finalStatic){
    st.currentKey = '';
    st.completed = true;
    return { key, text:doneText, state:'done', live:false, flowing:false, revealing:false, revealPct:1 };
  }

  // 历史消息/刷新页面不能重新播放。只有当前流式期间已经创建过播放器状态时，
  // 结束态才会 drain 剩余句子；否则直接显示完成。
  if(!active && (!existingState || st.completed || !hasUnplayedUnit())){
    st.currentKey = '';
    st.completed = true;
    return { key, text:doneText, state:'done', live:false, flowing:false, revealing:false, revealPct:1 };
  }

  let guard = 0;
  while(guard < 8){
    guard += 1;
    const unit = _activityInlineSelectPendingUnit(st, units, nowTs);
    if(!unit){
      if(!active){
        st.currentKey = '';
        st.completed = true;
        return { key, text:doneText, state:'done', live:false, flowing:false, revealing:false, revealPct:1 };
      }
      return { key, text:reasoningUiT('stream.thinking', null, 'Thinking…'), state:'active', live:true, flowing:true, revealing:false };
    }
    const totalMs = _activityInlineUnitMs(unit);
    const elapsed = Math.max(0, nowTs - Number(st.currentStartedAt || nowTs));
    const stickyActive = !!unit.stickyActive && String(unit.state || '').toLowerCase() === 'active' && active;
    if(!stickyActive && elapsed >= totalMs){
      st.playedKeys.add(unit.key);
      st.currentKey = '';
      st.currentStartedAt = nowTs;
      continue;
    }
    const stableText = String(unit.text || '').trim();
    return {
      key,
      text:stableText,
      targetText:stableText,
      state:'active',
      live:true,
      flowing:true,
      revealing:false,
      sequential:false,
      revealPct:1
    };
  }
  if(!active){
    st.currentKey = '';
    st.completed = true;
    return { key, text:doneText, state:'done', live:false, flowing:false, revealing:false, revealPct:1 };
  }
  return { key, text:reasoningUiT('stream.thinking', null, 'Thinking…'), state:'active', live:true, flowing:true, revealing:false };
}

function _activityInlineFallbackPlayback(sessionId, opts={}, snapshotArg=null){
  const sid = String(sessionId || '').trim();
  const snapshot = snapshotArg && typeof snapshotArg === 'object' ? snapshotArg : _composeReasoningPanelSnapshot(sid, opts || {});
  const meta = _normalizePendingAssistantReasoningMeta(snapshot?.reasoningMeta || {});
  const isStreaming = !!(sid && ensureSessionRuntime(sid)?.streaming && !opts?.message);
  return {
    sid,
    snapshot,
    units:[],
    active:isStreaming,
    doneText:isStreaming
      ? reasoningUiT('stream.thinking', null, 'Thinking…')
      : reasoningUiT('stream.done', null, 'Completed'),
    runKey:`fallback|${sid}|${Number(meta.nativeReasoningStartAt || snapshot?.nativeReasoningStartAt || 0) || ''}`,
    hasRealActivity:false,
  };
}


function _activityInlineSetTitleText(titleEl, value){
  if(!titleEl) return;
  const nextText = String(value || '');
  let base = titleEl.querySelector(':scope > .activity-inline-title-base');
  let shine = titleEl.querySelector(':scope > .activity-inline-title-shine');
  const needsRebuild = !base || !shine || titleEl.children.length !== 2;
  if(needsRebuild){
    titleEl.textContent = '';
    base = document.createElement('span');
    base.className = 'activity-inline-title-base';
    shine = document.createElement('span');
    shine.className = 'activity-inline-title-shine';
    shine.setAttribute('aria-hidden', 'true');
    titleEl.appendChild(base);
    titleEl.appendChild(shine);
  }
  if(base.textContent !== nextText) base.textContent = nextText;
  if(shine.textContent !== nextText) shine.textContent = nextText;
  if(titleEl.dataset.activityText !== nextText) titleEl.dataset.activityText = nextText;
}

function _activityInlineApplyCueState(btn, cue){
  if(!btn) return;
  const isActive = cue && cue.state === 'active';
  btn.classList.toggle('is-active', isActive);
  btn.classList.toggle('is-flowing', !!cue?.flowing);
  btn.classList.toggle('is-revealing', !!cue?.revealing);
  btn.classList.toggle('is-sequential', !!cue?.sequential);
  btn.dataset.activityState = String(cue?.state || 'done');
  if(isActive){
    btn.dataset.activitySweeping = '1';
  }else{
    delete btn.dataset.activitySweeping;
  }
}

function _activityInlineUpdateOne(btn, nowTs=Date.now()){
  if(!btn || !btn.dataset || btn.dataset.activityLive !== '1') return false;
  const key = String(btn.dataset.activityPlaybackKey || '');
  const payload = key ? _activityInlinePlaybackLatest[key] : null;
  if(!payload) return false;
  const cue = _activityInlineComputePlayback(payload.sessionId, payload.playback, nowTs);
  const titleEl = btn.querySelector('.activity-inline-title');
  if(titleEl){
    const nextText = String(cue.text || '');
    _activityInlineSetTitleText(titleEl, nextText);
    const pct = Math.max(0, Math.min(1, Number(cue.revealPct ?? 1)));
    titleEl.style.setProperty('--activity-inline-reveal', `${(pct * 100).toFixed(2)}%`);
  }
  _activityInlineApplyCueState(btn, cue);
  if(!cue.live){
    delete btn.dataset.activityLive;
    return false;
  }
  return true;
}

let _activityInlineLiveRaf = 0;
function _activityInlineLiveTick(){
  _activityInlineLiveRaf = 0;
  let activeCount = 0;
  try{
    const nodes = document.querySelectorAll('.activity-inline-trigger[data-activity-live="1"]');
    const nowTs = Date.now();
    nodes.forEach(node => { if(_activityInlineUpdateOne(node, nowTs)) activeCount += 1; });
  }catch(_){ activeCount = 0; }
  if(activeCount){
    _activityInlineLiveRaf = setTimeout(_activityInlineLiveTick, 220);
  }
}

function _activityInlineEnsureLiveTimer(){
  if(_activityInlineLiveRaf) return;
  _activityInlineLiveRaf = setTimeout(_activityInlineLiveTick, 220);
}

function _buildActivityReasoningTrigger(sessionId, opts={}, snapshotArg=null){
  const o = opts || {};
  const sid = String(sessionId || '').trim();
  const snapshot = snapshotArg && typeof snapshotArg === 'object' ? snapshotArg : _composeReasoningPanelSnapshot(sid, o);
  let playback = null;
  try{
    if(typeof getActivityInlinePlaybackForSnapshot === 'function'){
      playback = getActivityInlinePlaybackForSnapshot(sid, { ...o, reasoningSnapshot:snapshot, allowRuntimeFallback:true }, snapshot);
    }
  }catch(_){ playback = null; }
  if(!playback) playback = _activityInlineFallbackPlayback(sid, o, snapshot);

  const cue = _activityInlineComputePlayback(sid, playback, Date.now());
  const fallbackText=cue.state==='active'
    ?(window.AperviaI18n?.t('activity.thinking')||'Thinking')
    :(window.AperviaI18n?.t('activity.completed')||'Completed');
  const textValue=_activityInlineCleanText(cue.text,fallbackText);
  if(!textValue) return null;
  const canOpenActivity = !!(playback && (playback.hasRealActivity || playback.context?.streaming || playback.active));

  const wrap = document.createElement('div');
  wrap.className = 'activity-inline-trigger-wrap';
  const summaryBtn = document.createElement('button');
  summaryBtn.type = 'button';
  summaryBtn.className = 'activity-inline-trigger';
  _activityInlineApplyCueState(summaryBtn, cue);
  summaryBtn.dataset.activitySessionId = sid;
  summaryBtn.dataset.activityPlaybackKey = cue.key;
  summaryBtn.dataset.activityCanOpen = canOpenActivity ? '1' : '0';
  summaryBtn.classList.toggle('is-disabled', !canOpenActivity);
  summaryBtn.disabled = !canOpenActivity;
  summaryBtn.setAttribute('aria-disabled', canOpenActivity ? 'false' : 'true');
  summaryBtn.setAttribute('aria-expanded', 'false');
  // Keep an accessible label without using native title. The native browser
  // tooltip has its own shadow and visually conflicts with the inline row.
  summaryBtn.setAttribute('aria-label',canOpenActivity
    ?(window.AperviaI18n?.t('activity.toggle')||'Expand or collapse activity')
    :(window.AperviaI18n?.t('activity.no_expandable')||'No activity details to expand'));

  const text = document.createElement('span');
  text.className = 'activity-inline-title';
  _activityInlineSetTitleText(text, textValue);
  text.style.setProperty('--activity-inline-reveal', `${(Math.max(0, Math.min(1, Number(cue.revealPct ?? 1))) * 100).toFixed(2)}%`);
  summaryBtn.appendChild(text);

  _activityInlinePlaybackLatest[cue.key] = { sessionId:sid, playback };
  if(cue.live){
    summaryBtn.dataset.activityLive = '1';
  }
  wrap.appendChild(summaryBtn);
  if(cue.live){
    _activityInlineUpdateOne(summaryBtn);
    _activityInlineEnsureLiveTimer();
  }

  if(canOpenActivity){
    summaryBtn.addEventListener('click', (ev)=>{
      try{ ev.preventDefault(); ev.stopPropagation(); }catch(_){ }
      if(typeof toggleActivityPanelForMessage === 'function'){
        toggleActivityPanelForMessage(sid, o.message || null, { reasoningSnapshot: snapshot });
      }else if(typeof openActivityPanelForMessage === 'function'){
        openActivityPanelForMessage(sid, o.message || null, { reasoningSnapshot: snapshot });
      }
    });
  }
  return wrap;
}

function buildReasoningPanel(sessionId, opts={}){
  const snapshot = _composeReasoningPanelSnapshot(sessionId, opts);
  return _buildActivityReasoningTrigger(sessionId, { ...(opts || {}), reasoningSnapshot: snapshot }, snapshot);
}

function _isLikelyPrivateIpv4Host(host){
  const raw = String(host || '').trim().toLowerCase();
  if(!raw || !/^\d+\.\d+\.\d+\.\d+$/.test(raw)) return false;
  const parts = raw.split('.').map(v => Number(v));
  if(parts.length !== 4 || parts.some(v => !Number.isFinite(v) || v < 0 || v > 255)) return false;
  const [a, b] = parts;
  if(a === 10 || a === 127) return true;
  if(a === 172 && b >= 16 && b <= 31) return true;
  if(a === 192 && b === 168) return true;
  if(a === 169 && b === 254) return true;
  return false;
}

function isLikelyLocalAppAccess(){
  try{
    const host = String(window.location.hostname || '').trim().toLowerCase();
    if(!host) return false;
    if(host === 'localhost' || host === '127.0.0.1' || host === '::1') return true;
    if(host.endsWith('.local') || host.endsWith('.lan')) return true;
    return _isLikelyPrivateIpv4Host(host);
  }catch(_){
    return false;
  }
}

function isLikelyMobileViewport(){
  try{
    if(window.matchMedia && window.matchMedia('(max-width: 768px)').matches) return true;
  }catch(_){ }
  try{
    if(document.body?.classList?.contains('is-mobile')) return true;
  }catch(_){ }
  const ua = String(navigator.userAgent || '').toLowerCase();
  return /iphone|ipad|android|mobile|windows phone|harmonyos/.test(ua);
}

function getConnectionWeaknessLevel(){
  try{
    const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if(!conn) return '';
    if(conn.saveData) return 'save_data';
    const et = String(conn.effectiveType || '').trim().toLowerCase();
    if(et === 'slow-2g' || et === '2g') return et || '2g';
    if(et === '3g') return et;
  }catch(_){ }
  return '';
}

function shouldPreferStableAsyncPollTransport(){
  if(isLikelyMobileViewport()) return true;
  if(!isLikelyLocalAppAccess()) return true;
  return !!getConnectionWeaknessLevel();
}

function shouldUseWeakNonCriticalMode(){
  return shouldPreferStableAsyncPollTransport() || !isLikelyLocalAppAccess();
}

function scheduleWeakNonCriticalTask(task, opts={}){
  if(typeof task !== 'function') return;
  const o = opts || {};
  if(!shouldUseWeakNonCriticalMode()){
    try{ task(); }catch(_){ }
    return;
  }
  const baseDelay = Math.max(80, Number(o.delayMs || 0) || 0);
  const blockedByStreaming = !o.allowDuringStreaming && anyStreamingActive();
  const blockedByHidden = !o.allowWhenHidden && document.visibilityState === 'hidden';
  if(blockedByStreaming || blockedByHidden){
    const retryDelay = Math.max(baseDelay, blockedByStreaming ? 900 : 1400);
    try{ setTimeout(()=>scheduleWeakNonCriticalTask(task, o), retryDelay); }catch(_){ }
    return;
  }
  const run = ()=>{ try{ task(); }catch(_){ } };
  if(typeof requestIdleCallback === 'function'){
    try{
      requestIdleCallback(run, { timeout: Math.max(900, Math.min(2600, baseDelay || 1400)) });
      return;
    }catch(_){ }
  }
  try{ setTimeout(run, Math.max(120, Math.min(2200, baseDelay || 320))); }catch(_){ run(); }
}

function stableJitterMs(maxMs=450){
  const max = Math.max(0, Number(maxMs || 0) || 0);
  if(!max) return 0;
  return Math.floor(Math.random() * max);
}

function stableBackoffMs(attempt=1, baseMs=1000, maxMs=60000){
  const n = Math.max(1, Number(attempt || 1) || 1);
  const base = Math.max(200, Number(baseMs || 1000) || 1000);
  const max = Math.max(base, Number(maxMs || 60000) || 60000);
  const raw = base * (2 ** Math.min(n - 1, 6));
  return Math.min(max, raw) + stableJitterMs(Math.min(1200, Math.max(180, base * 0.35)));
}

function isNavigatorOffline(){
  try{ return typeof navigator !== 'undefined' && navigator.onLine === false; }catch(_){ return false; }
}

function isSoftNetworkError(err){
  if(isNavigatorOffline()) return true;
  if(isFetchAbortLikeError(err)) return true;
  const message = String(err?.message || err || '').trim().toLowerCase();
  return !!message && (
    message.includes('failed to fetch') ||
    message.includes('networkerror') ||
    message.includes('network error') ||
    message.includes('timeout') ||
    message.includes('timed out') ||
    message.includes('load failed') ||
    message.includes('connection')
  );
}

function stableNetworkReason(err, fallback='network_unstable'){
  if(isNavigatorOffline()) return 'offline';
  if(isFetchAbortLikeError(err)) return 'timeout';
  const msg = String(err?.message || err || '').trim();
  return msg || fallback;
}

function getCloudSyncWeakDebounceMs(baseMs){
  const base = Math.max(600, Number(baseMs || CLOUD_SYNC_DEBOUNCE_MS) || CLOUD_SYNC_DEBOUNCE_MS);
  if(!shouldUseWeakNonCriticalMode()) return base;
  const boosted = Math.max(base, anyStreamingActive() ? 5200 : 2400);
  return Math.min(CLOUD_SYNC_RETRY_MAX_MS, boosted + stableJitterMs(350));
}

function shouldPauseNonCriticalCloudSync(){
  if(authKickRedirecting) return true;
  if(isNavigatorOffline()) return true;
  if(!shouldUseWeakNonCriticalMode()) return false;
  if(anyStreamingActive()) return true;
  if(document.visibilityState === 'hidden') return true;
  return false;
}


function computeWeakFetchTimeoutMs(kind='default'){
  const weak = shouldUseWeakNonCriticalMode();
  const table = {
    auth_me: weak ? 22000 : 15000,
    cloud_get: weak ? 26000 : 18000,
    cloud_post: weak ? 36000 : 24000,
    image_probe: weak ? 16000 : 9000,
    session_get: weak ? 28000 : 18000,
    manifest_get: weak ? 24000 : 16000,
    ops_pull: weak ? 22000 : 14000,
    default: weak ? 17000 : 12000,
  };
  return Number(table[kind] || table.default || 17000);
}


function isFetchAbortLikeError(err){
  const name = String(err?.name || '').trim();
  const message = String(err?.message || err || '').trim().toLowerCase();
  return name === 'AbortError'
    || message.includes('aborted')
    || message.includes('abort')
    || message === 'auth_me_timeout'
    || message.includes('auth_me_timeout');
}

function shouldFlushStreamBuffer(buf, force=false){
  const s = String(buf || "");
  if(!s) return false;
  if(force) return true;
  if(/\n{1,}$/.test(s)) return true;
  if(s.length >= 4 && /[。！？!?；;：:，,、\n]$/.test(s)) return true;
  if(s.length >= 6) return true;
  return false;
}

function canUseAsyncChatJobStreamTransport(){
  // 直连公网边流式优先：不预先依赖全局 ReadableStream 判断。
  // 实际是否可读由 fetch 返回的 res.body.getReader 决定；不可用时自动回 poll。
  return typeof fetch === 'function' && typeof TextDecoder !== 'undefined';
}

const ASYNC_STREAM_TRANSPORT_HEALTH_KEY = "webai_async_stream_transport_health_v1";

function asyncStreamTransportHealthStorageKey(){
  const host = String(location?.host || 'default').trim() || 'default';
  return `${ASYNC_STREAM_TRANSPORT_HEALTH_KEY}:${host}`;
}

function readAsyncStreamTransportHealth(){
  try{
    const raw = localStorage.getItem(asyncStreamTransportHealthStorageKey());
    const data = raw ? JSON.parse(raw) : null;
    return data && typeof data === 'object' ? data : {};
  }catch(_){
    return {};
  }
}

function writeAsyncStreamTransportHealth(data){
  try{
    localStorage.setItem(asyncStreamTransportHealthStorageKey(), JSON.stringify(data || {}));
  }catch(_){ }
}

function shouldSkipAsyncStreamTransportForNow(){
  if(!shouldPreferStableAsyncPollTransport()) return false;
  const data = readAsyncStreamTransportHealth();
  const disabledUntil = Number(data.disabled_until_ms || 0) || 0;
  return disabledUntil > Date.now();
}

function recordAsyncStreamTransportHealth(ok, reason=''){
  const data = readAsyncStreamTransportHealth();
  const now = Date.now();
  if(ok){
    writeAsyncStreamTransportHealth({
      ok: true,
      fail_count: 0,
      disabled_until_ms: 0,
      last_ok_ms: now,
      last_fail_ms: Number(data.last_fail_ms || 0) || 0,
      last_reason: '',
    });
    return;
  }
  const failCount = Math.max(0, Number(data.fail_count || 0) || 0) + 1;
  const cooldownTable = [90000, 180000, 420000, 900000, 1200000];
  const cooldownMs = cooldownTable[Math.min(failCount - 1, cooldownTable.length - 1)] || 1200000;
  writeAsyncStreamTransportHealth({
    ok: false,
    fail_count: failCount,
    disabled_until_ms: now + cooldownMs,
    last_ok_ms: Number(data.last_ok_ms || 0) || 0,
    last_fail_ms: now,
    last_reason: String(reason || '').slice(0, 120),
  });
}

function asyncStreamFirstByteTimeoutMs(){
  if(!shouldPreferStableAsyncPollTransport()) return 0;
  const data = readAsyncStreamTransportHealth();
  const failCount = Math.max(0, Number(data.fail_count || 0) || 0);
  return failCount > 0 ? 4500 : 6500;
}

async function consumeAsyncChatJobEventStream(url, handlers){
  const h = handlers || {};
  const controller = h.controller || null;
  const firstByteTimeoutMs = Math.max(0, Number(h.firstByteTimeoutMs || 0) || 0);
  let firstByteSeen = false;
  let firstByteTimer = null;
  const clearFirstByteTimer = ()=>{
    if(firstByteTimer){
      try{ clearTimeout(firstByteTimer); }catch(_){ }
      firstByteTimer = null;
    }
  };
  if(firstByteTimeoutMs > 0 && controller){
    firstByteTimer = setTimeout(()=>{
      if(!firstByteSeen){
        try{ controller.abort('stream_first_byte_timeout'); }catch(_){ }
      }
    }, firstByteTimeoutMs);
  }

  let res = null;
  try{
    res = await fetch(url, {
      cache:'no-store',
      headers:{ 'Accept':'text/event-stream', 'Cache-Control':'no-cache' },
      signal: controller?.signal,
    });
  }catch(err){
    clearFirstByteTimer();
    throw err;
  }

  const parseErrorPayload = async ()=>{
    const contentType = String(res.headers.get('content-type') || '').toLowerCase();
    if(contentType.includes('application/json')){
      try{ return await res.json(); }catch(_){ }
    }
    try{
      const text = await res.text();
      return { error: String(text || '').trim() || ('HTTP ' + res.status) };
    }catch(_){ }
    return { error: 'HTTP ' + res.status };
  };

  if(!res.ok){
    clearFirstByteTimer();
    return { ok:false, httpStatus: Number(res.status || 0), data: await parseErrorPayload() };
  }
  if(!res.body || typeof res.body.getReader !== 'function'){
    clearFirstByteTimer();
    return { ok:false, httpStatus: Number(res.status || 0), data:{ error:'stream_body_unavailable' } };
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  let dataLines = [];
  let eventCount = 0;

  const dispatchEvent = async ()=>{
    if(!dataLines.length){
      eventName = 'message';
      return;
    }
    const raw = dataLines.join('\n');
    let payload = {};
    if(raw){
      try{ payload = JSON.parse(raw); }catch(_){ payload = { text: raw }; }
    }
    dataLines = [];
    const evt = String(eventName || 'message').trim() || 'message';
    eventName = 'message';
    eventCount += 1;
    if(typeof h.onEvent === 'function') await h.onEvent(evt, payload);
  };

  try{
    while(true){
      if(typeof h.shouldStop === 'function' && h.shouldStop()){
        try{ await reader.cancel(); }catch(_){ }
        return { ok:true, aborted:true, eventCount };
      }
      const { done, value } = await reader.read();
      if(done) break;
      if(value && value.length){
        firstByteSeen = true;
        clearFirstByteTimer();
      }
      buffer += decoder.decode(value || new Uint8Array(), { stream:true });
      while(true){
        const nl = buffer.indexOf('\n');
        if(nl < 0) break;
        let line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        if(line.endsWith('\r')) line = line.slice(0, -1);
        if(!line){
          await dispatchEvent();
          continue;
        }
        if(line.startsWith(':')) continue;
        if(line.startsWith('event:')){
          eventName = line.slice(6).trim() || 'message';
          continue;
        }
        if(line.startsWith('data:')){
          dataLines.push(line.slice(5).replace(/^\s/, ''));
        }
      }
    }
    buffer += decoder.decode();
    if(buffer){
      const lines = buffer.split(/\r?\n/);
      for(let i = 0; i < lines.length; i++){
        const lineRaw = lines[i];
        let line = String(lineRaw || '');
        if(!line){
          await dispatchEvent();
          continue;
        }
        if(line.startsWith(':')) continue;
        if(line.startsWith('event:')){
          eventName = line.slice(6).trim() || 'message';
          continue;
        }
        if(line.startsWith('data:')){
          dataLines.push(line.slice(5).replace(/^\s/, ''));
        }
      }
    }
    await dispatchEvent();
    return { ok:true, eventCount };
  } finally {
    clearFirstByteTimer();
    try{ reader.releaseLock(); }catch(_){ }
  }
}

async function runAsyncPlainTextJob(requestBody, options={}){
  const body = (requestBody && typeof requestBody === 'object') ? requestBody : null;
  if(!body) throw new Error('缺少请求体');
  const o = options || {};
  const totalTimeoutMs = Math.max(12000, Number(o.totalTimeoutMs || 0) || (shouldPreferStableAsyncPollTransport() ? 80000 : 60000));
  const pollTimeoutMs = Math.max(0, Math.min(8000, Number(o.pollTimeoutMs || 8000) || 8000));
  const deadline = Date.now() + totalTimeoutMs;

  let jobId = '';
  let cursor = 0;
  let out = '';

  const startCtl = new AbortController();
  const startTimeoutId = setTimeout(()=>{ try{ startCtl.abort('start_timeout'); }catch(_){} }, Math.min(30000, totalTimeoutMs));
  try{
    const startRes = await fetch('/api3/chat_async/start', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify(body),
      cache:'no-store',
      signal: startCtl.signal,
    });
    const startData = await startRes.json().catch(()=>({}));
    if(!startRes.ok){
      if(handleForcedLogin(startData, startData?.message || startData?.error || ('HTTP ' + startRes.status))) return '';
      throw new Error(startData?.message || startData?.error || ('HTTP ' + startRes.status));
    }
    jobId = String(startData?.job_id || '').trim();
    if(!jobId) throw new Error('后台任务未返回 job_id');
  } finally {
    try{ clearTimeout(startTimeoutId); }catch(_){}
  }

  while(Date.now() < deadline){
    const ctl = new AbortController();
    const pollTimeoutId = setTimeout(()=>{ try{ ctl.abort('poll_timeout'); }catch(_){} }, shouldPreferStableAsyncPollTransport() ? 30000 : 18000);
    let pollRes = null;
    let pollData = {};
    try{
      pollRes = await fetch(`/api3/chat_async/poll?job_id=${encodeURIComponent(jobId)}&cursor=${encodeURIComponent(cursor)}&timeout_ms=${encodeURIComponent(pollTimeoutMs)}`, {
        cache:'no-store',
        signal: ctl.signal,
      });
      pollData = await pollRes.json().catch(()=>({}));
    } finally {
      try{ clearTimeout(pollTimeoutId); }catch(_){}
    }

    if(!pollRes?.ok){
      if(handleForcedLogin(pollData, pollData?.message || pollData?.error || ('HTTP ' + (pollRes?.status || 0)))) return '';
      throw new Error(pollData?.message || pollData?.error || ('HTTP ' + (pollRes?.status || 0)));
    }

    const events = Array.isArray(pollData?.events) ? pollData.events : [];
    for(const item of events){
      const seq = Math.max(0, Number(item?.seq || item?.payload?._job_seq || 0) || 0);
      if(seq > cursor) cursor = seq;
      const eventName = String(item?.event || '').trim();
      const payload = (item?.payload && typeof item.payload === 'object') ? item.payload : {};
      if(eventName === 'delta' && typeof payload.text === 'string'){
        out += payload.text;
      }else if(eventName === 'message' && typeof payload.text === 'string' && !out){
        out = payload.text;
      }else if(eventName === 'error'){
        throw new Error(String(payload?.error || 'unknown error'));
      }
    }

    const fullText = typeof pollData?.full_text === 'string' ? pollData.full_text : '';
    if(fullText && fullText.length >= out.length) out = fullText;

    const status = String(pollData?.status || '').trim().toLowerCase();
    const done = !!pollData?.done || ['done','error','stopped'].includes(status);
    if(done){
      if(status === 'error') throw new Error(String(pollData?.error || 'unknown error'));
      if(status === 'stopped') throw new Error('任务已停止');
      return out;
    }

    const waitMs = Math.max(15, Math.min(180, Number(pollData?.poll_after_ms || 30) || 30));
    if(waitMs > 0) await new Promise(resolve => setTimeout(resolve, waitMs));
  }

  if(out && String(out).trim()) return out;
  throw new Error('后台任务仍在处理中');
}

async function fetchTitleByAI(seedInput, model, options={}){
  const seed = (seedInput && typeof seedInput === 'object') ? seedInput : { firstUserText: String(seedInput ?? ''), firstAssistantText: '', seedText: String(seedInput ?? '') };
  const firstUserText = String(seed.firstUserText || '').trim();
  const firstAssistantText = String(seed.firstAssistantText || '').trim();
  const seedText = String(seed.seedText || '').trim();
  const attempt = Math.max(0, Number(options?.attempt || 0) || 0);
  const previousTitle = String(options?.previousTitle || '').trim();
  const retryHint = String(options?.retryHint || '').trim();
  const promptSys =
`生成聊天侧边栏标题。
只输出一行 JSON：{"title":"..."}。
要求：标题自然完整；中文约 6-12 个汉字；不要问句口吻、回复腔、解释、引号、书名号、结尾标点或 URL；保留主题中的数字、年份、月份、版本号和规格。`;

  const retryText = attempt > 0
    ? `

上一次候选标题：${previousTitle || '（空）'}
修正要求：${retryHint || '请重写为合格标题'}
这次只输出修正后的最终标题。`
    : '';

  const requestSettings = getRequestSettings(model || DEFAULT_MODEL);
  const titleWebSettings = {
    ...((requestSettings && typeof requestSettings.web_settings === 'object' && requestSettings.web_settings) ? requestSettings.web_settings : {}),
    CHAT_THINKING_TYPE: 'disabled',
  };

  const body = {
    ...(requestSettings || {}),
    web_settings: titleWebSettings,
    chat_thinking_type: 'disabled',
    user_time: buildRuntimeTimePayload(),
    model: model || DEFAULT_MODEL,
    messages: [
      { role: "system", content: promptSys },
      { role: "user", content: ((seedText || `用户：${firstUserText}\n助手：${firstAssistantText}`) + retryText).slice(0, 900) }
    ],
    show_steps: false,
    web_enabled: false,
    disable_tools: true,
    skip_prepare_messages: true,
    disable_visual_prefetch: true
  };

  return await runAsyncPlainTextJob(body, { totalTimeoutMs: shouldPreferStableAsyncPollTransport() ? 80000 : 60000, pollTimeoutMs: 8000 });
}

function linkifyTextToHtml(text){
  const escaped = escapeHtml(text ?? "");
  // Convert URLs to clickable links (safe: operates on escaped text)
  const urlRe = /(https?:\/\/[^\s<>"'）\]\)】\u4e00-\u9fff]+)([.,;!?]+)?/g;
  return escaped.replace(urlRe, (m, url, tail) => {
    const u = trimUrl(url);
    const t = tail ? escapeHtml(tail) : "";
    return `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>${t}`;
  });
}

function renderUserTextHtml(text){
  return escapeHtml(String(text ?? "").replace(/\r\n/g, "\n")).replace(/\n/g, "<br>");
}

function renderMessageHtml(role, text, opts={}){
  return role === "user" ? renderUserTextHtml(text) : renderRichTextHtml(text, opts);
}

/* User message collapse UI helpers are loaded from index3-user-message-collapse-ui.js. */
function tryParseArtifactJson(text){
  if(!text) return null;
  let s = String(text).trim();
  if(!s) return null;

  if(s.startsWith("```")){
    s = s.replace(/^```[a-zA-Z0-9_-]*\s*/, "");
    s = s.replace(/\s*```$/, "").trim();
  }

  const normalizeObj = (obj) => {
    if(!obj || typeof obj !== "object" || Array.isArray(obj)) return null;

    if(Array.isArray(obj.artifacts)){
      return {
        answer: String(obj.answer || ""),
        artifacts: obj.artifacts
      };
    }

    // Some smaller models return one artifact object directly instead of
    // wrapping it in { answer, artifacts }.
    if(obj.filename && Object.prototype.hasOwnProperty.call(obj, "data")){
      return {
        answer: String(obj.answer || ""),
        artifacts: [obj]
      };
    }

    return null;
  };

  try{
    const parsed = normalizeObj(JSON.parse(s));
    if(parsed) return parsed;
  }catch(e){}

  for(let i = 0; i < s.length; i += 1){
    if(s[i] !== "{") continue;
    try{
      const parsed = normalizeObj(JSON.parse(s.slice(i)));
      if(parsed) return parsed;
    }catch(e){}
  }

  return null;
}

function looksLikeArtifactJsonInProgress(text){
  const s = String(text || '').trim();
  if(!s) return false;
  if(tryParseArtifactJson(s)) return true;
  const unwrapped = s.startsWith('```') ? s.replace(/^```[a-zA-Z0-9_-]*\s*/, '') : s;
  if(!(unwrapped.startsWith('{') || unwrapped.startsWith('[{'))) return false;
  return /"artifacts"\s*:|"filename"\s*:|"encoding"\s*:|"data"\s*:/.test(unwrapped);
}

function getArtifactDraftPreviewText(text){
  const parsed = tryParseArtifactJson(text);
  if(parsed) return parsed.answer || '正在生成文件…';
  return String(text || '');
}

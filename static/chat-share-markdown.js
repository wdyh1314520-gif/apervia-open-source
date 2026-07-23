/* 公开分享页的安全 Markdown 降级渲染；主聊天弹窗优先使用完整 renderMessageHtml。 */
(()=>{
  const escapeHtml = (value)=>String(value ?? '').replace(/[&<>"']/g, ch=>({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
  const inline = (value)=>{
    const tokens = [];
    let text = String(value ?? '').replace(/`([^`\n]+)`/g, (_m, code)=>{
      const key = `\u0000CODE${tokens.length}\u0000`;
      tokens.push(`<code>${escapeHtml(code)}</code>`);
      return key;
    });
    text = escapeHtml(text);
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_m, label, url)=>`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    text = text.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    tokens.forEach((token, index)=>{ text = text.replace(`\u0000CODE${index}\u0000`, token); });
    return text;
  };
  const render = (source)=>{
    const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    for(let i=0;i<lines.length;){
      const line = lines[i];
      if(!line.trim()){ i += 1; continue; }
      const fence = line.match(/^\s*```([^`]*)$/);
      if(fence){
        const code = [];
        i += 1;
        while(i<lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
        if(i<lines.length) i += 1;
        out.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
        continue;
      }
      const heading = line.match(/^\s*(#{1,3})\s+(.+)$/);
      if(heading){ out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); i += 1; continue; }
      if(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)){ out.push('<hr>'); i += 1; continue; }
      if(/^\s*>\s?/.test(line)){
        const quote = [];
        while(i<lines.length && /^\s*>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
        out.push(`<blockquote>${quote.map(part=>inline(part)).join('<br>')}</blockquote>`);
        continue;
      }
      const listMatch = line.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/);
      if(listMatch){
        const ordered = !!listMatch[2];
        const tag = ordered ? 'ol' : 'ul';
        const items = [];
        while(i<lines.length){
          const item = lines[i].match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/);
          if(!item || (!!item[2]) !== ordered) break;
          items.push(`<li>${inline(item[3])}</li>`);
          i += 1;
        }
        out.push(`<${tag}>${items.join('')}</${tag}>`);
        continue;
      }
      const paragraph = [line.trim()];
      i += 1;
      while(i<lines.length && lines[i].trim() && !/^\s*(?:```|#{1,3}\s|>|[-*+]\s|\d+[.)]\s|(?:-{3,}|\*{3,}|_{3,})\s*$)/.test(lines[i])) paragraph.push(lines[i++].trim());
      out.push(`<p>${paragraph.map(part=>inline(part)).join('<br>')}</p>`);
    }
    return out.join('') || '<p></p>';
  };
  window.renderChatShareMarkdown = render;
})();

'use strict';
const $ = id => document.getElementById(id);
let csrf = '', records = [], selected = '', origin = 'all', offset = 0, querySequence = 0;
function node(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
async function api(path, options = {}) {
  const response = await fetch(path, {credentials:'same-origin', ...options});
  const value = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== '/api/login') showLogin(); throw new Error(typeof value.detail === 'string' ? value.detail : '请求失败，请稍后重试'); }
  return value;
}
function showLogin() { $('workspace').hidden = true; $('login-view').hidden = false; records = []; selected = ''; csrf = ''; $('memory-list').replaceChildren(); $('detail').replaceChildren(); }
async function showWorkspace(session) {
  csrf = session.csrf; $('current-user').textContent = session.username; $('avatar').textContent = session.username.slice(0,1).toUpperCase();
  $('login-view').hidden = true; $('workspace').hidden = false; $('password').value = ''; await load();
}
function date(value) { try { return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'}).format(new Date(value)); } catch { return value.slice(0,10); } }
function overview(value) {
  const s = value.stats;
  $('count-all').textContent = s.total; $('count-feishu').textContent = s.feishu; $('count-agent').textContent = s.agent;
  $('stat-total').textContent = s.total; $('stat-summary').textContent = s.summarized;
  const chart = $('activity'); chart.replaceChildren(); const max = Math.max(1,...value.timeline.map(x => x.count));
  for (const day of value.timeline) { const col = node('div','day'); col.title = `${day.date} · ${day.count} 条`; const level = day.count ? Math.max(1,Math.round(day.count/max*10)) : 0; col.append(node('div',`bar level-${level}`),node('small','',day.date.slice(8))); chart.append(col); }
  const author = $('author'), previous = author.value;
  author.replaceChildren(new Option('所有作者','')); for (const name of value.authors) author.add(new Option(name,name)); author.value = previous;
  const sync = $('sync-status'); sync.classList.toggle('warning',value.warnings.length > 0);
  sync.textContent = value.warnings.length ? value.warnings.join(' · ') : `飞书来源与 Git 整理版合并展示${value.git_synced_at ? ' · Git 最近同步 ' + value.git_synced_at.replace('T',' ').slice(0,19) : ''} · 只读查看`;
}
async function load(append = false) {
  const sequence = ++querySequence; $('workspace-error').textContent = ''; $('refresh').disabled = true;
  if (!append) { offset = 0; $('memory-list').replaceChildren(node('p','notice','正在读取记忆…')); }
  try {
    const params = new URLSearchParams({origin,author:$('author').value,q:$('search').value,offset:String(offset)});
    const value = await api('/api/memories?' + params);
    if (sequence !== querySequence || $('workspace').hidden) return;
    overview(value); records = append ? records.concat(value.records) : value.records;
    $('result-count').textContent = `${value.total} 条记录`; $('load-more').hidden = !value.has_more;
    renderList();
    if (selected && !records.some(r => r.key === selected)) { selected = ''; $('detail').replaceChildren(node('div','notice','选择一条记忆查看详情')); }
  } catch (error) { if (sequence === querySequence) { $('workspace-error').textContent = error.message; $('memory-list').replaceChildren(node('p','notice','暂时无法读取。请检查连接后刷新。')); } }
  finally { if (sequence === querySequence) $('refresh').disabled = false; }
}
function renderList() {
  const list = $('memory-list'); list.replaceChildren();
  if (!records.length) { list.append(node('p','notice',$('search').value ? '没有找到匹配的记忆，试试其他关键词。' : '这里还没有记忆。新的分享会出现在这里。')); return; }
  for (const item of records) {
    const card = node('button','memory-card' + (item.key === selected ? ' selected' : '')); card.type = 'button'; card.setAttribute('aria-pressed',String(item.key===selected));
    const top = node('div','card-top'); top.append(node('span','badge' + (item.origin==='agent'?' agent':''),item.origin==='feishu'?'飞书讨论':item.source || 'Agent'));
    top.append(node('span','',item.summarized?'已整理':'原始记录'));
    const preview = item.preview.replace(/^#.*$/m,'').replace(/\n/g,' ').replace(/[#*`]/g,'').trim();
    const foot = node('div','card-foot'); foot.append(node('span','',item.author),node('span','',date(item.updated)));
    card.append(top,node('h3','card-title',item.title),node('p','card-preview',preview),foot); card.addEventListener('click',()=>openMemory(item.key)); list.append(card);
  }
}
function renderText(container, text) {
  let code = false, codeLines = [], paragraphs = [];
  function flush() { if (paragraphs.length) { container.append(node('p','',paragraphs.join('\n'))); paragraphs = []; } }
  for (const line of text.split('\n')) {
    if (line.trim().startsWith('```')) { flush(); if (code) { container.append(node('pre','',codeLines.join('\n'))); codeLines=[]; } code=!code; continue; }
    if (code) { codeLines.push(line); continue; }
    if (/^#{1,4}\s/.test(line)) { flush(); container.append(node('h3','',line.replace(/^#{1,4}\s+/,''))); }
    else if (!line.trim()) flush(); else paragraphs.push(line);
  }
  flush(); if (codeLines.length) container.append(node('pre','',codeLines.join('\n')));
}
async function openMemory(key) {
  selected=key; renderList(); const detail=$('detail'); detail.replaceChildren(node('p','notice','正在打开…'));
  try {
    const item=await api('/api/memory?key='+encodeURIComponent(key)); if (key!==selected || $('workspace').hidden) return;
    detail.replaceChildren(); detail.append(node('span','badge'+(item.origin==='agent'?' agent':''),item.origin==='feishu'?'飞书讨论':item.source||'Agent'),node('h2','',item.title));
    detail.append(node('div','detail-meta',`${item.author} · ${item.updated.slice(0,19).replace('T',' ')} · ${item.summarized?'已整理':'原始记录'}\n来源 ${item.id} · 版本 ${item.version}`));
    const content=node('div','detail-content'); let body=item.body;
    if (item.summarized && body.includes('## 目的与背景')) body=body.slice(body.indexOf('## 目的与背景'));
    const parts=body.split('## 原始资料（来源数据）'); renderText(content,parts.shift());
    if(parts.length) { const raw=node('details'); raw.append(node('summary','','查看原始资料'),node('pre','',parts.join('## 原始资料（来源数据）').trim())); content.append(raw); }
    detail.append(content);
    if (item.git_url && item.git_url.startsWith('https://github.com/')) { const link=node('a','detail-link','在 GitHub 查看该版本 ↗'); link.href=item.git_url; link.target='_blank'; link.rel='noopener noreferrer'; detail.append(link); }
    if(innerWidth<760) detail.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
  } catch(error) { if(key===selected) detail.replaceChildren(node('p','notice',error.message)); }
}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();$('login-error').textContent='';$('login-button').disabled=true;try{const value=await api('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value.trim(),password:$('password').value})});await showWorkspace(value);}catch(error){$('login-error').textContent=error.message;}finally{$('login-button').disabled=false;}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',headers:{'X-CSRF-Token':csrf}});showLogin();}catch(error){$('workspace-error').textContent=error.message;}});
for(const button of document.querySelectorAll('[data-source]')) button.addEventListener('click',()=>{origin=button.dataset.source;document.querySelectorAll('[data-source]').forEach(b=>b.classList.toggle('active',b===button));$('page-title').textContent={all:'全部记忆',feishu:'飞书讨论',agent:'Agent 归档'}[origin];load();});
let timer; $('search').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>load(),240);});$('author').addEventListener('change',()=>load());$('refresh').addEventListener('click',()=>load());$('load-more').addEventListener('click',()=>{offset=records.length;load(true);});
api('/api/me').then(showWorkspace).catch(()=>{});

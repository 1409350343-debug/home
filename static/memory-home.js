let memoryData={categories:[],memories:{}},all=[],facts=[],activeFilter='all',selectedBubble=null;
const esc=(window.HomeCommon&&HomeCommon.escapeHtml)||((s)=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
const localDay=value=>{const d=new Date(value);if(Number.isNaN(d.getTime()))return String(value||'').slice(0,10);const x=new Date(d.getTime()-d.getTimezoneOffset()*60000);return x.toISOString().slice(0,10)};
const categoryName=id=>(memoryData.categories||[]).find(x=>x.id===id)?.name||id||'未分类';
const hueFor=m=>{const v=Number(m.valence);if(v>.35)return '#e6aa6b';if(v<-.35)return '#859ab0';const colors=['#7da56b','#6f9987','#9b8bb4','#b88d93','#7897a0'];let h=0;for(const c of String(m.category||m.thread||''))h=(h*31+c.charCodeAt(0))%997;return colors[h%colors.length]};
const score=m=>Math.max(1,Number(m.importance||0)*1.2+Math.log2(Number(m.hit_count||0)+1)*1.5+(m.pinned?2:0)+(m.tier==='permanent'?2:0));
const relation=(a,b)=>{let n=0;if(a.category&&a.category===b.category)n+=2;if(a.thread&&a.thread===b.thread)n+=2;const at=new Set(a.tags||[]);(b.tags||[]).forEach(x=>{if(at.has(x))n++});return n};
function setTab(name){
  document.querySelectorAll('.memory-tabs button').forEach(b=>b.classList.toggle('on',b.dataset.tab===name));
  document.querySelectorAll('.memory-view').forEach(v=>v.classList.toggle('on',v.id===name));
  const url=new URL(location.href);url.searchParams.set('tab',name);history.replaceState(null,'',url);
}
function renderHeat(){
  const counts={};all.forEach(m=>{const d=localDay(m.created);if(d)counts[d]=(counts[d]||0)+1});
  const today=new Date(),start=new Date(today);start.setDate(today.getDate()-83-start.getDay());
  const cells=[];let total=0;
  for(let i=0;i<84;i++){const d=new Date(start);d.setDate(start.getDate()+i);const key=localDay(d),n=counts[key]||0;total+=n;const level=n>=8?4:n>=5?3:n>=2?2:n?1:0;cells.push(`<i class="heat-cell l${level}${key===localDay(today)?' today':''}" title="${key} · ${n} 条"></i>`)}
  compactHeat.innerHTML=cells.join('');heatSummary.textContent=`最近 12 周 · ${total} 条`;
}
function bubblePosition(m,i,total){
  let h=7;for(const c of String(m.id||m.title||i))h=(h*37+c.charCodeAt(0))>>>0;
  const angle=((h%360)/180)*Math.PI+i*.73,radius=18+(h%29),cx=50+Math.cos(angle)*radius,cy=50+Math.sin(angle)*radius*.78;
  return {x:Math.max(8,Math.min(92,cx)),y:Math.max(10,Math.min(90,cy))};
}
function renderBubbles(){
  const shown=[...all].sort((a,b)=>score(b)-score(a)).slice(0,22);bubbleCount.textContent=`${all.length} 条`;
  if(!shown.length){bubbleStage.innerHTML='<div class="empty">还没有可展示的记忆</div>';return}
  relationLines.innerHTML='';bubbleStage.querySelectorAll('.memory-bubble').forEach(x=>x.remove());
  shown.forEach((m,i)=>{const p=bubblePosition(m,i,shown.length),size=Math.round(54+Math.min(56,score(m)*7));const b=document.createElement('button');b.className='memory-bubble';b.dataset.id=m.id;b.style.cssText=`width:${size}px;height:${size}px;left:calc(${p.x}% - ${size/2}px);top:calc(${p.y}% - ${size/2}px);background:${hueFor(m)};opacity:${Math.max(.58,1-Math.min(3000,(Date.now()-new Date(m.last_active||m.created||Date.now()))/86400000)/5000)}`;b.innerHTML=`<span>${esc(m.title||m.preview||'一条记忆')}</span>`;b.onclick=()=>selectBubble(m,shown,b);bubbleStage.appendChild(b)});
}
function selectBubble(m,shown,node){
  if(selectedBubble===m.id){openDrawer(m);return}selectedBubble=m.id;
  const related=shown.map(x=>({m:x,n:relation(m,x)})).filter(x=>x.m.id!==m.id&&x.n>0).sort((a,b)=>b.n-a.n).slice(0,5);
  bubbleStage.querySelectorAll('.memory-bubble').forEach(b=>{const hit=related.some(x=>String(x.m.id)===b.dataset.id);b.classList.toggle('selected',b===node);b.classList.toggle('related',hit);b.classList.toggle('dimmed',b!==node&&!hit)});
  relationLines.innerHTML='';requestAnimationFrame(()=>{const sr=bubbleStage.getBoundingClientRect(),nr=node.getBoundingClientRect();related.forEach(({m})=>{const target=bubbleStage.querySelector(`[data-id="${CSS.escape(String(m.id))}"]`);if(!target)return;const tr=target.getBoundingClientRect(),line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('class','relation-line');line.setAttribute('x1',nr.left+nr.width/2-sr.left);line.setAttribute('y1',nr.top+nr.height/2-sr.top);line.setAttribute('x2',tr.left+tr.width/2-sr.left);line.setAttribute('y2',tr.top+tr.height/2-sr.top);relationLines.appendChild(line)})});
  setTimeout(()=>openDrawer(m),180);
}
function renderFilters(){
  const cats=[...new Set(all.map(m=>m.category).filter(Boolean))];filters.innerHTML=[['all','全部'],...cats.map(x=>[x,categoryName(x)])].map(([id,name])=>`<button data-filter="${esc(id)}" class="${id===activeFilter?'on':''}">${esc(name)}</button>`).join('');
  filters.querySelectorAll('button').forEach(b=>b.onclick=()=>{activeFilter=b.dataset.filter;renderFilters();renderLibrary()});
}
function renderLibrary(){
  const q=search.value.trim().toLowerCase();const list=all.filter(m=>(activeFilter==='all'||m.category===activeFilter)&&(!q||JSON.stringify(m).toLowerCase().includes(q)));
  results.innerHTML=list.slice(0,80).map(m=>`<button class="memory-card" data-memory="${esc(m.id)}"><h3>${esc(m.title||'一条记忆')}</h3><p>${esc(m.preview||m.content||'')}</p><footer><span>${esc(categoryName(m.category))}</span><time>${esc(localDay(m.created))}</time></footer></button>`).join('')||'<div class="empty">没有找到符合条件的记忆</div>';
  results.querySelectorAll('[data-memory]').forEach(b=>b.onclick=()=>openDrawer(all.find(m=>String(m.id)===b.dataset.memory)));
}
function renderRiver(){
  const groups={};[...all].sort((a,b)=>new Date(b.created)-new Date(a.created)).forEach(m=>{const key=localDay(m.created)||'时间未定';(groups[key]||(groups[key]=[])).push(m)});
  const keys=Object.keys(groups).slice(0,40);riverCount.textContent=`${keys.length} 个节点`;
  timeRiver.innerHTML=keys.map(key=>`<section class="river-group"><h3 class="river-date">${esc(key)}</h3><div class="river-items">${groups[key].map(m=>`<button class="river-item" data-memory="${esc(m.id)}"><b>${esc(m.title||categoryName(m.category))}</b><p>${esc(m.preview||m.content||'')}</p></button>`).join('')}</div></section>`).join('')||'<div class="empty">时间河流还没有内容</div>';
  timeRiver.querySelectorAll('[data-memory]').forEach(b=>b.onclick=()=>openDrawer(all.find(m=>String(m.id)===b.dataset.memory)));
}
function memoryStrength(m){
  if(m.tier==='permanent'||m.pinned)return 100;
  if(m.status==='archived'||m.tier==='archive')return Math.max(8,Math.min(42,Number(m.importance||3)*4));
  const date=new Date(m.last_active||m.created||Date.now()),age=Math.max(0,(Date.now()-date.getTime())/86400000);
  const halfLife=7+Number(m.importance||5)*4+Math.log2(Number(m.hit_count||0)+1)*7;
  return Math.max(3,Math.min(100,Math.round(100*Math.pow(.5,age/halfLife))));
}
function decayState(m,strength){
  if(m.tier==='permanent'||m.pinned)return'protected';
  if(m.status==='archived'||m.tier==='archive')return'archived';
  if(strength>=68)return'active';if(strength>=34)return'fading';return'sleeping';
}
function renderDecay(){
  const meta={
    active:{name:'活跃',desc:'近期仍然鲜活'},
    fading:{name:'正在淡去',desc:'需要再次召回'},
    sleeping:{name:'沉睡',desc:'暂时不主动浮现'},
    archived:{name:'已归档',desc:'保留但降低召回'},
    protected:{name:'永久保护',desc:'不会随时间淡去'}
  },groups={active:[],fading:[],sleeping:[],archived:[],protected:[]};
  all.forEach(m=>{const strength=memoryStrength(m),state=decayState(m,strength);groups[state].push({m,strength})});
  decaySummary.innerHTML=Object.entries(meta).map(([id,x])=>`<div class="decay-stat"><b>${groups[id].length}</b><small>${x.name}</small></div>`).join('');
  decayList.innerHTML=Object.entries(meta).map(([id,x])=>`<section class="decay-group" data-state="${id}"><div class="decay-group-head"><b>${x.name}</b><span>${x.desc} · ${groups[id].length} 条</span></div><div class="decay-items">${groups[id].sort((a,b)=>b.strength-a.strength).slice(0,24).map(({m,strength})=>`<button class="decay-item" data-memory="${esc(m.id)}"><div class="decay-item-top"><b>${esc(m.title||'一条记忆')}</b><em>${strength}%</em></div><div class="strength-bar"><i style="width:${strength}%"></i></div><p>${id==='protected'?'永久保护':id==='archived'?'已进入归档':`上次活跃：${esc(localDay(m.last_active||m.created))}`}</p></button>`).join('')||'<div class="empty">暂无</div>'}</div></section>`).join('');
  decayList.querySelectorAll('[data-memory]').forEach(b=>b.onclick=()=>openDrawer(all.find(m=>String(m.id)===b.dataset.memory)));
}
function openDrawer(m){
  if(!m)return;drawerTitle.textContent=m.title||'一条记忆';drawerKicker.textContent=m.fact_key?'fact memory':'memory detail';drawerContent.textContent=m.content||m.preview||'';
  drawerReason.textContent=m.why_remembered||'还没有写下为什么要记住它';
  drawerMeta.innerHTML=[categoryName(m.category),m.status,m.tier,localDay(m.created)].filter(Boolean).map(x=>`<span>${esc(x)}</span>`).join('');
  drawerTags.innerHTML=(m.tags||[]).map(x=>`<span># ${esc(x)}</span>`).join('');
  drawerCategory.href='/memory-archive.html';
  const versions=m.fact_key?facts.filter(x=>x.fact_key===m.fact_key):[];factEvolution.hidden=!versions.length;factVersions.innerHTML=versions.map(v=>`<div class="fact-version ${v.is_current_fact?'current':'old'}">${esc(v.fact_value||v.title||v.preview||'')}</div>`).join('');
  drawerMask.classList.add('show');memoryDrawer.classList.add('show');memoryDrawer.setAttribute('aria-hidden','false');if(window.lucide)lucide.createIcons();
}
function closeDrawer(){drawerMask.classList.remove('show');memoryDrawer.classList.remove('show');memoryDrawer.setAttribute('aria-hidden','true')}
document.querySelectorAll('.memory-tabs button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));search.oninput=renderLibrary;drawerClose.onclick=drawerMask.onclick=closeDrawer;addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()});
Promise.all([fetch('/api/memory').then(r=>r.json()),fetch('/api/memory/facts').then(r=>r.ok?r.json():[]).catch(()=>[]),fetch('/brain-data.json?t='+Date.now()).then(r=>r.json()).catch(()=>({}))]).then(([m,f,b])=>{
  memoryData=m||memoryData;all=Object.values(memoryData.memories||{}).flat();facts=Array.isArray(f)?f:(f.facts||[]);
  renderHeat();renderBubbles();renderFilters();renderLibrary();renderRiver();renderDecay();if(b.generated)generated.textContent='更新于 '+new Date(b.generated*1000).toLocaleDateString('zh-CN');if(window.lucide)lucide.createIcons();
}).catch(()=>{bubbleStage.innerHTML='<div class="empty">记忆接口暂时没醒</div>'});
addEventListener('DOMContentLoaded',()=>{renderCoreNav('memory');setTab(new URLSearchParams(location.search).get('tab')||'bubbles');if(window.lucide)lucide.createIcons()});

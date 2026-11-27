/* 协作层：账号 + 我的持仓 + 调仓流水 + 讨论区 + SSE实时 */
(function(){
let ME = null;

async function api(p, method, body){
  const opt = { method: method||'GET', headers: {} };
  if(body !== undefined){ opt.headers['Content-Type']='application/json'; opt.body = JSON.stringify(body); }
  // 智能回退：同源 → 局域网主机 → 本机（应对 workbuddy.link 静态预览/分享链接下 /api 不可达）
  const candidates = [p];
  if(p.startsWith('/')){
    candidates.push('http://10.12.32.58:8905'+p, 'http://127.0.0.1:8905'+p);
  }
  let lastErr = null;
  for(const url of candidates){
    try{
      const r = await fetch(url, opt);
      const d = await r.json().catch(()=>({}));
      if(!r.ok) throw new Error(d.error || ('请求失败 '+r.status));
      return d;
    }catch(e){ lastErr = e; }
  }
  throw lastErr || new Error('服务器不可达');
}
function el(id){ return document.getElementById(id); }
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function toast(t,b){ if(window.showToast) showToast(t,b); }

/* ---------- 用户区 ---------- */
function renderUserArea(){
  const ua = el('user-area');
  if(!ua) return;
  if(ME){
    ua.innerHTML = '<span style="font-size:12.5px;background:rgba(0,160,90,.25);border:1px solid rgba(0,160,90,.5);padding:3px 12px;border-radius:14px;">👤 '+esc(ME)+'</span>'+
      '<a href="javascript:void(0)" onclick="collabLogout()" style="color:#dce9f5;font-size:12px;text-decoration:underline;">退出</a>';
  }else{
    ua.innerHTML = '<a href="javascript:void(0)" onclick="collabShowAuth()" style="color:#fff;font-size:12.5px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.4);padding:5px 14px;border-radius:8px;text-decoration:none;">登录 / 注册</a>';
  }
}
window.collabShowAuth = function(){
  el('auth-modal').classList.add('show');
};
window.collabLogout = async function(){
  await api('/api/logout','POST',{}); ME=null;
  renderUserArea(); renderMine(); renderForum();
  toast('已退出','个人持仓与发言功能已锁定，看板仍可只读浏览。');
};
window.collabDoAuth = async function(mode){
  const username = el('auth-user').value.trim(), password = el('auth-pass').value;
  try{
    const d = await api('/api/'+(mode==='reg'?'register':'login'), 'POST', {username, password});
    ME = d.username;
    el('auth-modal').classList.remove('show');
    renderUserArea(); renderMine(); renderForum();
    toast('欢迎，'+ME, mode==='reg'?'注册成功，已加入协作。':'登录成功。');
  }catch(e){ el('auth-err').textContent = e.message; }
};

/* ---------- 我的持仓 ---------- */
const TRACKS = ['半导体设备','存储芯片','光通信模块','其他','现金'];
function renderMine(){
  const box = el('mine-body');
  if(!box) return;
  if(!ME){
    box.innerHTML = '<div class="section-note" style="margin:0;">登录后记录你的三赛道仓位与调仓流水，并可将风控/信号指令一键记账。<a href="javascript:void(0)" onclick="collabShowAuth()" style="color:#1976d2;">去登录 →</a></div>';
    return;
  }
  api('/api/portfolio').then(pf=>{
    const t = pf.tracks || {};
    const rows = TRACKS.map(k=>{
      const v = t[k] != null ? t[k] : (k==='现金'?10:0);
      return '<div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px dashed var(--line);">'+
        '<span style="width:90px;font-size:13px;">'+k+'</span>'+
        '<input type="number" step="0.1" min="0" max="10" value="'+v+'" data-track="'+k+'" class="pf-input" style="width:80px;border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:13px;">'+
        '<span style="font-size:12px;color:var(--sub);">成</span>'+
        '<div style="flex:1;height:8px;background:#e8eef5;border-radius:4px;overflow:hidden;"><i style="display:block;height:100%;width:'+(v*10)+'%;background:'+(k==='现金'?'#8ba3bd':k==='其他'?'#b9a7d9':k==='半导体设备'?'#f57c00':k==='存储芯片'?'#7b5ea7':'#1976d2')+';"></i></div></div>';
    }).join('');
    box.innerHTML = rows +
      '<div style="display:flex;gap:10px;margin-top:12px;align-items:center;flex-wrap:wrap;">'+
      '<button class="btn" onclick="collabSavePf()">保存持仓</button>'+
      '<span id="pf-sum" style="font-size:12.5px;color:var(--sub);"></span>'+
      (window.DASHBOARD_DATA && DASHBOARD_DATA.riskControl && DASHBOARD_DATA.riskControl.triggered ?
        '<button class="btn" style="background:#e53935;" onclick="collabQuickLog()">⚠️ 按风控指令记账（整体-2成）</button>' : '')+
      '</div>'+
      '<div style="margin-top:14px;font-size:12.5px;color:var(--sub);">手动记账：<input id="log-track" list="tk-list" placeholder="赛道" style="width:110px;border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;"><datalist id="tk-list"><option>半导体设备</option><option>存储芯片</option><option>光通信模块</option><option>其他</option><option>现金</option></datalist> '+
      '<input id="log-delta" type="number" step="0.1" placeholder="+加仓/-减仓（成）" style="width:150px;border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;"> '+
      '<input id="log-reason" placeholder="理由（如：大盘强制风控）" style="width:220px;border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;"> '+
      '<button class="btn ghost" onclick="collabLog()">记一笔</button></div>'+
      '<div id="pf-logs" style="margin-top:14px;"></div>';
    box.querySelectorAll('.pf-input').forEach(inp=>inp.addEventListener('input',()=>{
      const sum = [...box.querySelectorAll('.pf-input')].reduce((a,x)=>a+(+x.value||0),0);
      el('pf-sum').textContent = '合计：'+sum.toFixed(1)+'成'+(Math.abs(sum-10)>0.01?'（须=10）':' ✓');
      el('pf-sum').style.color = Math.abs(sum-10)>0.01 ? '#e53935' : '#00a05a';
    }));
    loadLogs();
  }).catch(()=>{});
}
window.collabSavePf = async function(){
  const tracks = {};
  document.querySelectorAll('.pf-input').forEach(x=>tracks[x.dataset.track]=+x.value||0);
  try{ await api('/api/portfolio','PUT',{tracks}); toast('已保存','持仓配置已同步到协作平台。'); }
  catch(e){ toast('保存失败', e.message); }
};
window.collabLog = async function(){
  const track=el('log-track').value.trim(), delta=el('log-delta').value, reason=el('log-reason').value.trim();
  if(!track||!delta){ toast('提示','请填写赛道与变动量'); return; }
  try{
    await api('/api/portfolio/log','POST',{track, delta:+delta, reason});
    el('log-delta').value=''; el('log-reason').value='';
    toast('已记账',(delta>0?'加仓':'减仓')+track+Math.abs(delta)+'成');
    renderMine();
  }catch(e){ toast('记账失败', e.message); }
};
window.collabQuickLog = async function(){
  const R = DASHBOARD_DATA.riskControl;
  if(!R || !R.triggered) return;
  const assigns = (R.integrated && R.integrated.assigns) || [];
  if(!assigns.length){ toast('提示','无赛道分配数据'); return; }
  try{
    for(const [t,w] of assigns){
      await api('/api/portfolio/log','POST',{track:t, delta:-w, reason:'强制风控整合指令（'+R.integrated.headline+'）'});
    }
    toast('风控记账完成','已按整合指令记录：'+assigns.map(([t,w])=>t+'-'+w).join('、')+'，现金同步增加。');
    renderMine();
  }catch(e){ toast('记账失败', e.message); }
};
function loadLogs(){
  api('/api/portfolio/log').then(list=>{
    el('pf-logs').innerHTML = list.length ?
      '<b style="font-size:13px;color:#0f4c81;">调仓流水（最近'+list.length+'条）</b>'+
      list.slice(0,15).map(l=>'<div style="display:flex;gap:10px;font-size:12.5px;padding:6px 0;border-bottom:1px dashed var(--line);color:var(--sub);">'+
        '<span style="width:130px;">'+new Date(l.t).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})+'</span>'+
        '<span style="width:56px;font-weight:600;color:'+(l.delta>0?'#e53935':'#00a05a')+'">'+l.action+'</span>'+
        '<span style="width:90px;">'+esc(l.track)+'</span>'+
        '<span style="width:70px;">'+(l.delta>0?'+':'')+l.delta+'成</span>'+
        '<span style="flex:1;">'+esc(l.reason||'')+'</span></div>').join('')
      : '<span style="font-size:12.5px;color:#98a7b9;">暂无调仓记录</span>';
  }).catch(()=>{});
}

/* ---------- 讨论区 ---------- */
function renderForum(){
  const box = el('forum-body');
  if(!box) return;
  api('/api/comments').then(list=>{
    const byId = {}; list.forEach(c=>byId[c.id]=c);
    const top = list.filter(c=>!c.parentId).reverse();
    const item = c => {
      const replies = list.filter(r=>r.parentId===c.id);
      return '<div style="padding:9px 0;border-bottom:1px dashed var(--line);" id="cmt-'+c.id+'">'+
        '<div style="display:flex;gap:8px;align-items:center;">'+
        '<span style="width:26px;height:26px;border-radius:50%;background:#0f4c81;color:#fff;font-size:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">'+esc(c.u[0]||'?')+'</span>'+
        '<b style="font-size:12.5px;">'+esc(c.u)+'</b>'+
        '<span style="font-size:11px;color:#98a7b9;">'+new Date(c.t).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})+'</span>'+
        (ME?'<a href="javascript:void(0)" onclick="collabReply(\''+c.id+'\',\''+esc(c.u)+'\')" style="font-size:11.5px;color:#1976d2;text-decoration:none;">回复</a>':'')+
        '</div>'+
        '<div style="font-size:13px;line-height:1.7;margin:5px 0 0 34px;">'+esc(c.body)+'</div>'+
        replies.map(r=>'<div style="margin:6px 0 0 34px;padding:6px 10px;background:#f7fafd;border-radius:8px;font-size:12.5px;"><b>'+esc(r.u)+'</b>：'+esc(r.body)+'<span style="font-size:10.5px;color:#98a7b9;margin-left:8px;">'+new Date(r.t).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})+'</span></div>').join('')+
        '</div>';
    };
    box.innerHTML =
      (ME ? '<div style="display:flex;gap:8px;margin-bottom:10px;"><input id="cmt-input" placeholder="发表看法（500字内）…" style="flex:1;border:1px solid var(--line);border-radius:8px;padding:9px 12px;font-size:13px;" onkeydown="if(event.key===\'Enter\')collabPost()"><button class="btn" onclick="collabPost()">发布</button></div>'+
            '<input id="cmt-parent" type="hidden"><div id="cmt-replying" style="font-size:12px;color:#1976d2;margin-bottom:6px;display:none;"></div>'
          : '<div class="section-note" style="margin:0 0 10px;">登录后可发言。<a href="javascript:void(0)" onclick="collabShowAuth()" style="color:#1976d2;">去登录 →</a></div>') +
      (top.length ? top.map(item).join('') : '<span style="font-size:12.5px;color:#98a7b9;">还没有讨论，来抢沙发。</span>');
  }).catch(()=>{});
}
window.collabPost = async function(){
  const body = el('cmt-input').value.trim();
  const parentId = el('cmt-parent').value || null;
  if(!body) return;
  try{
    await api('/api/comments','POST',{body, parentId});
    el('cmt-input').value=''; el('cmt-parent').value='';
    el('cmt-replying').style.display='none';
    renderForum();
  }catch(e){ toast('发布失败', e.message); }
};
window.collabReply = function(id, username){
  el('cmt-parent').value = id;
  const tag = el('cmt-replying');
  tag.style.display='block';
  tag.innerHTML = '回复 '+username+'：<a href="javascript:void(0)" onclick="collabCancelReply()" style="color:#e53935;">取消</a>';
  el('cmt-input').focus();
};
window.collabCancelReply = function(){
  el('cmt-parent').value=''; el('cmt-replying').style.display='none';
};
// (collabLike 红心已移除，赞功能暂关)
window.collabLike = async function(id){ /* 已删除红心，暂不可用 */ };

/* ---------- SSE 实时 ---------- */
function startSSE(){
  try{
    const es = new EventSource('/api/events');
    es.addEventListener('comment', e=>{
      const c = JSON.parse(e.data);
      if(!ME || c.u !== ME) toast('💬 '+c.u+' 发表了新评论', c.body.slice(0,60));
      renderForum();
    });
    es.addEventListener('notice', e=>{
      const n = JSON.parse(e.data);
      toast('协作动态', n.text);
    });
    es.addEventListener('board', e=>{
      toast('📊 看板数据已更新','数据管道刷新了分析结果，按 Ctrl+F5 或点击「一键更新行情」查看最新。');
    });
    es.onerror = ()=>{ es.close(); setTimeout(startSSE, 10000); };
  }catch(e){}
}

/* ---------- 启动 ---------- */
async function init(){
  renderUserArea(); renderMine(); renderForum();
  try{
    const d = await api('/api/me');
    if(d.username){ ME = d.username; renderUserArea(); renderMine(); renderForum(); }
  }catch(e){}
  startSSE();
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', init);
else init();
})();

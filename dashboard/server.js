// 盯盘协作平台后端（Node 原生模块，零依赖）
// 功能：静态托管 + 账号(注册/登录/scrypt) + 个人持仓与调仓流水 + 讨论区 + SSE实时推送 + 看板数据版本广播
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

let refreshState = { running: false, step: '', lastCode: null, started: 0, finished: 0 };

const ROOT = __dirname;
const DATA_DIR = path.join(ROOT, 'collab_data');
const PORT = process.env.PORT || 8905;
const SESSION_TTL = 7 * 24 * 3600 * 1000;

fs.mkdirSync(DATA_DIR, { recursive: true });
function load(name, def) {
  try { return JSON.parse(fs.readFileSync(path.join(DATA_DIR, name), 'utf-8')); }
  catch (e) { return def; }
}
function save(name, obj) {
  const tmp = path.join(DATA_DIR, name + '.tmp');
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 1));
  fs.renameSync(tmp, path.join(DATA_DIR, name));
}
let users = load('users.json', []);
let sessions = load('sessions.json', {});
let portfolios = load('portfolios.json', {});   // username -> {tracks:{半导体设备:x,存储芯片:x,光通信模块:x,其他:x,现金:x}, updatedAt}
let logs = load('logs.json', []);               // 调仓流水
let comments = load('comments.json', []);

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.css': 'text/css; charset=utf-8', '.md': 'text/markdown; charset=utf-8' };

function hashPass(pass, salt) {
  return crypto.scryptSync(pass, salt, 32).toString('hex');
}
function makeSession(username) {
  const token = crypto.randomBytes(24).toString('hex');
  sessions[token] = { u: username, exp: Date.now() + SESSION_TTL };
  save('sessions.json', sessions);
  return token;
}
function authUser(req) {
  const cookie = req.headers.cookie || '';
  const m = cookie.match(/(?:^|;\s*)wb_token=([a-f0-9]+)/);
  if (!m) return null;
  const s = sessions[m[1]];
  if (!s || s.exp < Date.now()) return null;
  return s.u;
}
function readBody(req) {
  return new Promise((resolve) => {
    let b = '';
    req.on('data', c => { b += c; if (b.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(JSON.parse(b || '{}')); } catch (e) { resolve({}); } });
  });
}
function json(res, code, obj, extraHeaders) {
  res.writeHead(code, Object.assign({
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  }, extraHeaders || {}));
  res.end(JSON.stringify(obj));
}

// ---- SSE ----
const sseClients = new Set();
function sseBroadcast(type, payload) {
  const msg = `event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const res of sseClients) { try { res.write(msg); } catch (e) { sseClients.delete(res); } }
}
setInterval(() => { for (const res of sseClients) { try { res.write(': ping\n\n'); } catch (e) { sseClients.delete(res); } } }, 30000);

// ---- 看板数据版本 ----
function boardVersion() {
  try { return fs.statSync(path.join(ROOT, 'data.js')).mtimeMs; } catch (e) { return 0; }
}
let lastBoardVer = boardVersion();
setInterval(() => {
  const v = boardVersion();
  if (v !== lastBoardVer) { lastBoardVer = v; sseBroadcast('board', { version: v, time: new Date().toISOString() }); }
}, 5000);

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;

  // CORS 预检（跨域调用API，如从 workbuddy.link 预览页访问主机API）
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400',
    });
    return res.end();
  }

  // ---------- API ----------
  if (p === '/api/register' && req.method === 'POST') {
    const { username, password } = await readBody(req);
    if (!username || !/^[一-龥\w]{2,16}$/.test(username)) return json(res, 400, { error: '用户名需2-16位中文/字母/数字' });
    if (!password || password.length < 4) return json(res, 400, { error: '密码至少4位' });
    if (users.find(x => x.u === username)) return json(res, 409, { error: '用户名已存在' });
    const salt = crypto.randomBytes(8).toString('hex');
    users.push({ u: username, s: salt, h: hashPass(password, salt), t: Date.now() });
    save('users.json', users);
    const token = makeSession(username);
    sseBroadcast('notice', { text: `👋 新成员 ${username} 加入协作` });
    return json(res, 200, { ok: true, username }, { 'Set-Cookie': `wb_token=${token}; Path=/; Max-Age=${SESSION_TTL / 1000}; HttpOnly; SameSite=Lax` });
  }
  if (p === '/api/login' && req.method === 'POST') {
    const { username, password } = await readBody(req);
    const usr = users.find(x => x.u === username);
    if (!usr || usr.h !== hashPass(password || '', usr.s)) return json(res, 401, { error: '用户名或密码错误' });
    const token = makeSession(username);
    return json(res, 200, { ok: true, username }, { 'Set-Cookie': `wb_token=${token}; Path=/; Max-Age=${SESSION_TTL / 1000}; HttpOnly; SameSite=Lax` });
  }
  if (p === '/api/logout' && req.method === 'POST') {
    const cookie = req.headers.cookie || '';
    const m = cookie.match(/(?:^|;\s*)wb_token=([a-f0-9]+)/);
    if (m) { delete sessions[m[1]]; save('sessions.json', sessions); }
    return json(res, 200, { ok: true }, { 'Set-Cookie': 'wb_token=; Path=/; Max-Age=0' });
  }
  if (p === '/api/me') {
    const me = authUser(req);
    return json(res, 200, { username: me, members: users.length });
  }
  if (p === '/api/members') {
    return json(res, 200, { members: users.map(x => ({ u: x.u, t: x.t })) });
  }
  // ---------- 一键全量刷新（后台跑 quick_refresh.py 数据管道） ----------
  if (p === '/api/refresh' && req.method === 'POST') {
    if (refreshState.running) return json(res, 200, { ok: true, already: true, step: refreshState.step });
    refreshState = { running: true, step: '启动', started: Date.now() };
    const py = 'C:\\Users\\ASUS\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe';
    const script = path.join(ROOT, '..', 'quick_refresh.py');
    const child = spawn(py, [script], { cwd: path.join(ROOT, '..') });
    child.on('close', code => {
      refreshState.running = false;
      refreshState.lastCode = code;
      refreshState.finished = Date.now();
      if (code === 0) sseBroadcast('notice', { text: '📊 看板数据已完成全量刷新，请查看最新结论' });
    });
    return json(res, 200, { ok: true });
  }
  if (p === '/api/refresh/status') {
    let st = null;
    try { st = JSON.parse(fs.readFileSync(path.join(ROOT, '..', 'data', 'refresh_status.json'), 'utf-8')); } catch (e) {}
    return json(res, 200, { running: refreshState.running, step: st ? st.step : refreshState.step, state: st ? st.state : '', msg: st ? st.msg : '', lastCode: refreshState.lastCode });
  }
  // ---------- 数据来源截图上传（用户上传→AI读取补数） ----------
  if (p === '/api/upload' && req.method === 'POST') {
    const { name, dataBase64, note } = await readBody(req);
    if (!dataBase64) return json(res, 400, { error: '缺少图片数据' });
    const UP_DIR = path.join(ROOT, '..', 'data', 'manual_uploads');
    fs.mkdirSync(UP_DIR, { recursive: true });
    const ext = (name && /\.(png|jpe?g|webp|gif)$/i.test(name)) ? name.slice(name.lastIndexOf('.')) : '.png';
    const ts = new Date();
    const fname = ts.getFullYear() + String(ts.getMonth() + 1).padStart(2, '0') + String(ts.getDate()).padStart(2, '0') + '_' +
      String(ts.getHours()).padStart(2, '0') + String(ts.getMinutes()).padStart(2, '0') + String(ts.getSeconds()).padStart(2, '0') + ext;
    fs.writeFileSync(path.join(UP_DIR, fname), Buffer.from(dataBase64, 'base64'));
    const metaFile = path.join(UP_DIR, 'index.json');
    let uidx = [];
    try { uidx = JSON.parse(fs.readFileSync(metaFile, 'utf-8')); } catch (e) {}
    uidx.push({ file: fname, origName: name || fname, note: note || '', time: ts.toISOString(), status: '待读取' });
    fs.writeFileSync(metaFile, JSON.stringify(uidx, null, 1));
    return json(res, 200, { ok: true, file: fname, tip: '已保存，请在对话中提醒AI「读取上传的截图」以提取数据' });
  }
  if (p === '/api/uploads') {
    const metaFile = path.join(ROOT, '..', 'data', 'manual_uploads', 'index.json');
    let uidx = [];
    try { uidx = JSON.parse(fs.readFileSync(metaFile, 'utf-8')); } catch (e) {}
    return json(res, 200, { uploads: uidx.slice(-30).reverse() });
  }
  // ---------- 风控执行确认（我已执行减仓） ----------
  if (p === '/api/risk/ack' && req.method === 'POST') {
    const me = authUser(req);
    const { items } = await readBody(req);   // [{scope, tier, action, triggerDate}]
    if (!items || !items.length) return json(res, 400, { error: '缺少确认项' });
    let acks = load('risk_ack.json', []);
    const ts = new Date();
    items.forEach(it => {
      if (!acks.find(a => a.scope === it.scope && a.tier === it.tier && a.triggerDate === it.triggerDate)) {
        acks.push({ scope: it.scope, tier: it.tier, action: it.action || '', triggerDate: it.triggerDate || '',
                    user: me || '未登录用户', time: ts.toISOString() });
      }
    });
    save('risk_ack.json', acks);
    sseBroadcast('notice', { text: `✅ ${me || '有成员'}确认已执行风控减仓（${items.map(i => i.scope).join('、')}），进入冷却观察期` });
    return json(res, 200, { ok: true, total: acks.length });
  }
  if (p === '/api/risk/ack') {
    return json(res, 200, { acks: load('risk_ack.json', []) });
  }
  if (p.startsWith('/uploads/')) {
    const fname = path.basename(p);
    const fp = path.join(ROOT, '..', 'data', 'manual_uploads', fname);
    if (!fs.existsSync(fp)) { res.writeHead(404); return res.end(); }
    const ext = path.extname(fname).toLowerCase();
    const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif' }[ext] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'no-cache' });
    return fs.createReadStream(fp).pipe(res);
  }
  if (p === '/api/portfolio') {
    const me = authUser(req);
    if (req.method === 'GET') {
      if (!me) return json(res, 401, { error: '未登录' });
      return json(res, 200, portfolios[me] || { tracks: {}, updatedAt: null });
    }
    if (req.method === 'PUT') {
      if (!me) return json(res, 401, { error: '未登录' });
      const { tracks } = await readBody(req);
      const sum = Object.values(tracks || {}).reduce((a, b) => a + (+b || 0), 0);
      if (Math.abs(sum - 10) > 0.01) return json(res, 400, { error: `各项合计须等于10成（当前${sum.toFixed(1)}）` });
      portfolios[me] = { tracks, updatedAt: Date.now() };
      save('portfolios.json', portfolios);
      return json(res, 200, { ok: true });
    }
  }
  if (p === '/api/portfolio/log') {
    const me = authUser(req);
    if (!me) return json(res, 401, { error: '未登录' });
    if (req.method === 'GET') {
      return json(res, 200, logs.filter(l => l.u === me).slice(-50).reverse());
    }
    if (req.method === 'POST') {
      const { action, track, delta, reason } = await readBody(req);
      if (!track || !delta) return json(res, 400, { error: '缺少赛道或变动量' });
      const entry = { u: me, action: action || (+delta > 0 ? '加仓' : '减仓'), track, delta: +delta, reason: reason || '', t: Date.now() };
      logs.push(entry); save('logs.json', logs);
      // 同步更新持仓
      const pf = portfolios[me] || { tracks: {} };
      pf.tracks = pf.tracks || {};
      pf.tracks[track] = Math.max(0, +(((pf.tracks[track] || 0) + (+delta)).toFixed(2)));
      pf.tracks['现金'] = Math.max(0, +(((pf.tracks['现金'] || 0) - (+delta)).toFixed(2)));
      pf.updatedAt = Date.now();
      portfolios[me] = pf; save('portfolios.json', portfolios);
      sseBroadcast('notice', { text: `📒 ${me} ${entry.action}${track}${Math.abs(entry.delta)}成${reason ? '（' + reason + '）' : ''}` });
      return json(res, 200, { ok: true, tracks: pf.tracks });
    }
  }
  if (p === '/api/comments') {
    if (req.method === 'GET') {
      const list = comments.slice(-80).map(c => ({ ...c, likes: (c.likes || []).length }));
      return json(res, 200, list);
    }
    if (req.method === 'POST') {
      const me = authUser(req);
      if (!me) return json(res, 401, { error: '登录后才能发言' });
      const { body, parentId } = await readBody(req);
      if (!body || !body.trim()) return json(res, 400, { error: '内容为空' });
      if (body.length > 500) return json(res, 400, { error: '单条不超过500字' });
      const c = { id: Date.now() + '_' + Math.random().toString(36).slice(2, 6), u: me, body: body.trim(), parentId: parentId || null, t: Date.now(), likes: [] };
      comments.push(c); save('comments.json', comments);
      sseBroadcast('comment', { ...c, likes: 0 });
      return json(res, 200, { ok: true, id: c.id });
    }
  }
  if (p === '/api/comment/like' && req.method === 'POST') {
    const me = authUser(req);
    if (!me) return json(res, 401, { error: '未登录' });
    const { id } = await readBody(req);
    const c = comments.find(x => x.id === id);
    if (!c) return json(res, 404, { error: '评论不存在' });
    c.likes = c.likes || [];
    const i = c.likes.indexOf(me);
    if (i >= 0) c.likes.splice(i, 1); else c.likes.push(me);
    save('comments.json', comments);
    return json(res, 200, { ok: true, likes: c.likes.length });
  }
  if (p === '/api/events') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
    res.write(': connected\n\n');
    sseClients.add(res);
    req.on('close', () => sseClients.delete(res));
    return;
  }
  if (p === '/api/board/version') {
    return json(res, 200, { version: boardVersion() });
  }

  // ---------- 静态 ----------
  let fp = p === '/' ? '/index.html' : p;
  fp = path.normalize(fp).replace(/^(\.\.[/\\])+/, '');
  const abs = path.join(ROOT, fp);
  if (!abs.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(abs, (err, buf) => {
    if (err) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(abs)] || 'application/octet-stream',
      'Cache-Control': 'no-cache, must-revalidate',
      'Expires': '0',
    });
    res.end(buf);
  });
});

server.listen(PORT, '0.0.0.0', () => {
  const os = require('os');
  const ifs = Object.values(os.networkInterfaces()).flat().filter(x => x && x.family === 'IPv4').map(x => x.address);
  console.log(`协作平台已启动: http://127.0.0.1:${PORT}  局域网: ${ifs.map(ip => 'http://' + ip + ':' + PORT).join(' , ')}`);
});

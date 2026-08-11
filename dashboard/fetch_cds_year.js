// 抓取美国10年期CDS一年日线（英为财情，通过页面会话调内部API）
// 用法: node fetch_cds_year.js  →  更新 ../data/cds_history.json 与 payload_hand.json CDS卡片
const { chromium } = require('C:/Users/ASUS/.workbuddy/binaries/node/workspace/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = 'C:/Users/ASUS/WorkBuddy/2026-08-03-11-17-59';
const CDS_FILE = path.join(BASE, 'data', 'cds_history.json');
const PAYLOAD = path.join(BASE, 'payload_hand.json');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true, args: ['--disable-blink-features=AutomationControlled']
  });
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0',
    locale: 'zh-CN', viewport: { width: 1366, height: 900 }
  });
  await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
  const page = await ctx.newPage();
  await page.goto('https://cn.investing.com/rates-bonds/united-states-cds-10-years-usd', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(9000);

  const res = await page.evaluate(async () => {
    const end = new Date();
    const start = new Date(end.getTime() - 380 * 864e5);
    const fmt = d => d.toISOString().slice(0, 10);
    const r = await fetch(`https://api.investing.com/api/financialdata/historical/1115802?start-date=${fmt(start)}&end-date=${fmt(end)}&time-frame=Daily&add-missing-rows=false`, { headers: { 'domain-id': 'cn' } });
    if (r.status !== 200) return { error: r.status };
    const j = await r.json();
    return { rows: j.data.map(x => [x.rowDateTimestamp.slice(0, 10), parseFloat(x.last_close)]) };
  });
  await browser.close();

  if (res.error || !res.rows || !res.rows.length) { console.error('fetch failed:', JSON.stringify(res).slice(0, 200)); process.exit(1); }
  // 升序排列
  res.rows.sort((a, b) => a[0] < b[0] ? -1 : 1);

  // 合并进 cds_history.json（保留旧数据，去重）
  let old = { dates: [], closes: [], week52: [34.57, 47.19] };
  if (fs.existsSync(CDS_FILE)) old = JSON.parse(fs.readFileSync(CDS_FILE, 'utf-8'));
  const map = new Map(old.dates.map((d, i) => [d, old.closes[i]]));
  for (const [d, c] of res.rows) map.set(d, c);
  const dates = [...map.keys()].sort();
  const out = {
    name: '美国10Y CDS', src: '英为财情',
    url: 'https://cn.investing.com/rates-bonds/united-states-cds-10-years-usd',
    dates, closes: dates.map(d => map.get(d)),
    week52: [Math.min(...map.values()), Math.max(...map.values())].map(v => +v.toFixed(2))
  };
  fs.writeFileSync(CDS_FILE, JSON.stringify(out, null, 0));
  console.log('cds_history.json:', dates.length, 'days', dates[0], '→', dates[dates.length - 1], 'latest', map.get(dates[dates.length - 1]));

  // 同步payload卡片
  if (fs.existsSync(PAYLOAD)) {
    const h = JSON.parse(fs.readFileSync(PAYLOAD, 'utf-8'));
    const n = dates.length;
    const last = map.get(dates[n - 1]), prev = map.get(dates[n - 2]);
    const chg = (last / prev - 1) * 100;
    for (const o of h.overseas || []) {
      if (o.name === '美国10Y CDS') {
        o.val = last.toFixed(2) + 'bp';
        o.chg = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
        o.date = dates[n - 1].slice(5);
        o.src = '英为财情';
        o.note = `最新${last.toFixed(2)}bp（${o.chg}），52周区间${out.week52[0]}-${out.week52[1]}bp——信用环境${last < 45 ? '宽松' : '边际收紧'}`;
      }
    }
    fs.writeFileSync(PAYLOAD, JSON.stringify(h, null, 1));
    console.log('payload CDS card updated:', last, 'bp');
  }
  process.exit(0);
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });

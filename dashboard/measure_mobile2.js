const { chromium } = require('C:/Users/ASUS/.workbuddy/binaries/node/workspace/node_modules/playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
  await page.goto('http://127.0.0.1:8905/index.html', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2500);

  const result = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    // 1) 找"最外层超宽祖先"：自身 scrollWidth>vw 但其父级不超宽（或直接是 body 子级超宽）
    const topOffenders = [];
    document.body.querySelectorAll('*').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.width > vw + 2) {
        const p = el.parentElement;
        const pr = p ? p.getBoundingClientRect() : null;
        if (!pr || pr.width <= vw + 2) {
          const style = getComputedStyle(el);
          topOffenders.push({
            sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + (typeof el.className === 'string' ? el.className.split(' ').join('.') : ''),
            width: Math.round(r.width),
            parentSel: p ? (p.tagName.toLowerCase() + (p.id ? '#' + p.id : '') + '.' + (typeof p.className === 'string' ? p.className.split(' ').join('.') : '')) : 'none',
            parentWidth: pr ? Math.round(pr.width) : 0,
            overflowX: style.overflowX,
            display: style.display,
            text: (el.textContent || '').trim().slice(0, 30),
          });
        }
      }
    });
    // 2) 每个 tbl-wrap 的实际表现
    const wraps = [];
    document.querySelectorAll('.tbl-wrap').forEach(w => {
      const style = getComputedStyle(w);
      wraps.push({
        id: w.querySelector('table') ? (w.querySelector('table').id || 'no-id') : 'empty',
        clientWidth: w.clientWidth,
        scrollWidth: w.scrollWidth,
        overflowX: style.overflowX,
        display: style.display,
        parentChain: (() => { const c = []; let e = w.parentElement; while (e && c.length < 3) { c.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')); e = e.parentElement; } return c.join('<'); })(),
      });
    });
    return { vw, docSW: document.documentElement.scrollWidth, topOffenders: topOffenders.slice(0, 15), wraps };
  });

  console.log('viewport:', result.vw, '| doc scrollWidth:', result.docSW);
  console.log('\n=== 最外层超宽祖先 ===');
  result.topOffenders.forEach(o => {
    console.log(o.sel, '| w=' + o.width, '| parent=' + o.parentSel, 'pw=' + o.parentWidth, '| ox=' + o.overflowX, '| disp=' + o.display, '|', o.text);
  });
  console.log('\n=== tbl-wrap 状态 ===');
  result.wraps.forEach(w => {
    console.log(w.id, '| client=' + w.clientWidth, 'scroll=' + w.scrollWidth, '| ox=' + w.overflowX, w.display, '| parent:', w.parentChain);
  });
  await browser.close();
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });

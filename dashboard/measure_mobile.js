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
    const out = { viewport: vw, docScrollWidth: document.documentElement.scrollWidth, bodyScrollWidth: document.body.scrollWidth, offenders: [] };
    document.querySelectorAll('*').forEach(el => {
      const sw = el.scrollWidth;
      const cw = el.clientWidth;
      const r = el.getBoundingClientRect();
      // 元素右边界超出视口 或 scrollWidth 明显大于 clientWidth 且没有自己的滚动
      const style = getComputedStyle(el);
      const canScrollX = /(auto|scroll)/.test(style.overflowX);
      if ((r.right > vw + 2 || r.left < -2) && !canScrollX) {
        const chain = [];
        let e = el;
        while (e && e !== document.body && chain.length < 4) {
          chain.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ').join('.') : ''));
          e = e.parentElement;
        }
        out.offenders.push({
          chain: chain.join(' < '),
          right: Math.round(r.right),
          left: Math.round(r.left),
          width: Math.round(r.width),
          scrollWidth: sw,
          overflowX: style.overflowX,
          text: (el.textContent || '').trim().slice(0, 40),
        });
      }
    });
    // 只保留最外层的关键 offenders（过滤掉被已记录元素包含的）
    return out;
  });

  console.log('viewport:', result.viewport, '| doc scrollWidth:', result.docScrollWidth, '| body scrollWidth:', result.bodyScrollWidth);
  console.log('offenders:', result.offenders.length);
  // 按宽度排序输出前20个
  result.offenders.sort((a, b) => b.right - a.right).slice(0, 20).forEach(o => {
    console.log('---');
    console.log('chain:', o.chain);
    console.log('  right=' + o.right, 'width=' + o.width, 'scrollW=' + o.scrollWidth, 'overflowX=' + o.overflowX);
    console.log('  text:', o.text);
  });
  await browser.close();
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });

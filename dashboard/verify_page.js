// 看板页面JS冒烟测试：mock最小DOM/BOM环境，执行内联script，捕获运行时错误
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf-8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('FAIL: inline script not found'); process.exit(1); }
const inlineJs = m[1];
const dataJs = fs.readFileSync(path.join(__dirname, 'data.js'), 'utf-8');

// ---- mocks ----
function mockEl() {
  const el = {
    _html: '', _text: '',
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    set textContent(v) { this._text = v; }, get textContent() { return this._text; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, style: {}, value: '',
    insertAdjacentHTML() {}, scrollTop: 0, scrollHeight: 0,
    addEventListener() {}, onclick: null,
  };
  return el;
}
const els = {};
global.document = {
  getElementById(id) { return els[id] || (els[id] = mockEl()); },
  querySelector(sel) { return els[sel] || (els[sel] = mockEl()); },
  querySelectorAll() { return []; },
  createElement() { return mockEl(); },
};
global.window = {
  DASHBOARD_DATA: null,
  addEventListener() {},
  AudioContext: undefined, webkitAudioContext: undefined,
};
global.localStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = v; }, };
global.sessionStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = v; }, removeItem(k) { delete this._s[k]; } };
global.fetch = () => Promise.reject(new Error('mock: no network'));
global.location = { reload() {}, href: '', pathname: '/index.html', hash: '' };
global.navigator = { clipboard: { writeText() { return Promise.resolve(); } } };
global.Notification = undefined;
global.echarts = { init() { return { setOption(opt) { this._opt = opt; }, resize() {} }; } };
global.setInterval = () => 0;
global.setTimeout = (fn) => 0;
global.clearTimeout = () => {};
global.Blob = function () {};
global.URL = { createObjectURL: () => '' };

// ---- run ----
try {
  eval(dataJs);           // window.DASHBOARD_DATA = {...}
  eval(inlineJs);         // page logic
  console.log('PASS: inline script executed without runtime errors');
  console.log('D keys:', Object.keys(global.window.DASHBOARD_DATA).join(', '));
  console.log('charts inited:', Object.keys(require.cache ? {} : {}).length === 0 ? '(mock)' : '');
} catch (e) {
  console.error('FAIL:', e.constructor.name + ':', e.message);
  console.error(e.stack.split('\n').slice(0, 4).join('\n'));
  process.exit(1);
}

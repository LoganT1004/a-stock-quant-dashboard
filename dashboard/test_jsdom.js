// 用 jsdom 真实 DOM 测试看板页面，捕获真实浏览器错误
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const DASH = 'C:\\Users\\ASUS\\WorkBuddy\\2026-08-03-11-17-59\\dashboard';
const html = fs.readFileSync(path.join(DASH, 'index.html'), 'utf-8');

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:8905/index.html',
  runScripts: 'outside-only',
  pretendToBeVisual: true,
});
const { window } = dom;

// mock echarts / storage / fetch / EventSource
window.echarts = { init() { return { setOption() {}, resize() {}, clear() {} }; } };
window.fetch = () => Promise.reject(new Error('no network'));
window.EventSource = class { constructor() {} addEventListener() {} close() {} };
window.AudioContext = undefined;
window.Notification = undefined;
window.scrollTo = () => {};
if (!window.HTMLCanvasElement.prototype.getContext) {
  window.HTMLCanvasElement.prototype.getContext = () => null;
}

const errors = [];
window.addEventListener('error', e => errors.push('window.onerror: ' + e.message));

// 依次执行 data.js / 内联脚本 / collab.js
function run(code, tag) {
  try { window.eval(code); console.log('OK  ' + tag); }
  catch (e) { console.log('ERR ' + tag + ' -> ' + e.message); errors.push(tag + ': ' + e.message); console.log(e.stack.split('\n').slice(0, 8).join('\n')); }
}
run(fs.readFileSync(path.join(DASH, 'data.js'), 'utf-8'), 'data.js');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
run(m[1], 'inline-script');
run(fs.readFileSync(path.join(DASH, 'collab.js'), 'utf-8'), 'collab.js');

// 检查关键区域渲染结果
const coGrid = window.document.getElementById('co-grid');
const riskTbody = window.document.querySelector('#risk-table tbody');
const ovCards = window.document.getElementById('ov-cards');
console.log('\n--- 渲染结果 ---');
console.log('co-grid 子节点数:', coGrid ? coGrid.children.length : 'N/A', coGrid ? ('| innerHTML长度 ' + coGrid.innerHTML.length) : '');
console.log('co-note 内容:', (window.document.getElementById('co-note') || {}).innerHTML || 'N/A');
console.log('risk-table 行数:', riskTbody ? riskTbody.children.length : 'N/A');
console.log('ov-cards 卡片数:', ovCards ? ovCards.children.length : 'N/A');
console.log('margin-chart HTML:', (window.document.getElementById('margin-chart') || {}).innerHTML ? '已渲染' : '空');
console.log('\n错误汇总:', errors.length ? errors : '无');

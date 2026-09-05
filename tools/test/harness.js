// index.html 을 브라우저 없이 돌리는 가짜 DOM.
// 앞서 패치가 함수를 통째로 날려 답변이 안 그려진 적이 있다 —
// 같은 사고를 눈으로만 잡을 수는 없어서 만들었다.
// 검사 파일들이 각자 이걸 불러 쓴다.
const fs = require('fs');
const vm = require('vm');

const base = 'c:/Users/Hala/Desktop/Sec_Obsidian/tools/static/';
const html = fs.readFileSync(base + 'index.html', 'utf8');
const rmd = fs.readFileSync(base + 'restricted-markdown.js', 'utf8');
const app = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).pop();

function mkEl(tag) {
  const cls = new Set();
  return {
    tagName: tag, children: [], attrs: {}, dataset: {},
    // style 은 --splitw 같은 사용자 정의 속성을 읽고 써야 한다
    style: { _p: {}, setProperty(k, v) { this._p[k] = v },
             getPropertyValue(k) { return this._p[k] || '' } },
    className: '', _text: '', id: '', hidden: false, disabled: false,
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); },
    set textContent(v) { this._text = String(v); this.children = []; },
    set innerHTML(v) { this._html = String(v); this._text = String(v).replace(/<[^>]*>/g, ''); this.children = []; },
    get innerHTML() { return this._html || ''; },
    get innerText() { return this.textContent; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    append(...cs) { cs.forEach(c => this.appendChild(c)); },
    replaceChildren(...cs) { this.children = []; this._text = ''; cs.forEach(c => this.appendChild(c)); },
    insertBefore(c) { this.children.unshift(c); c.parentNode = this; return c; },
    remove() { const p = this.parentNode; if (p) p.children = p.children.filter(x => x !== this);
      if (this._id) delete registry[this._id]; },
    setAttribute(k, v) { this.attrs[k] = v; if (k === 'id') this.id = v; },
    getAttribute(k) { return this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; },
    addEventListener() {}, focus() {}, click() {}, scrollIntoView() {},
    querySelector(sel) { return findIn(this, sel); },
    querySelectorAll(sel) { return findAllIn(this, sel); },
    classList: {
      add: c => cls.add(c), remove: c => cls.delete(c),
      toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)),
      contains: c => cls.has(c),
    },
    get ownerDocument() { return doc; },
    get firstChild() { return this.children[0]; },
    get scrollHeight() { return 0; }, scrollTop: 0,
  };
}
function walk(n, out = []) { out.push(n); n.children.forEach(c => walk(c, out)); return out; }
function match(n, sel) {
  if (sel.startsWith('#')) return n.id === sel.slice(1);
  if (sel.startsWith('.')) return n.className && n.className.split(' ').includes(sel.slice(1));
  if (sel.startsWith('[')) return true;
  return n.tagName === sel;
}
function findIn(root, sel) {
  const last = sel.trim().split(/\s+/).pop();
  return walk(root).find(n => n !== root && match(n, last)) || null;
}
function findAllIn(root, sel) {
  const last = sel.trim().split(/\s+/).pop();
  return walk(root).filter(n => n !== root && match(n, last));
}

const registry = {};
const doc = {
  documentElement: mkEl('html'),
  body: mkEl('body'),
  createElement: t => mkEl(t),
  createDocumentFragment: () => mkEl('#fragment'),
  createTextNode: t => { const e = mkEl('#text'); e._text = t; return e; },
  getElementById: id => registry[id] || null,
  // 같은 선택자는 같은 요소를 돌려줘야 한다 — .split 처럼 상태를 들고 있는 게 있다
  querySelector: sel => (sel.startsWith('#') ? registry[sel.slice(1)] || null
    : (registry['__' + sel] = registry['__' + sel] || mkEl('div'))),
  querySelectorAll: () => [],
  addEventListener() {},
};
doc.documentElement.dataset = {};

['qout', 'qq', 'qgo', 'qstop', 'qprofile', 'qshell', 'qsrc', 'qsrc-body',
 'qsrc-toggle', 'qsrc-close', 'qform', 'qnew', 'qhead-title', 'themeToggle',
 'q', 'plist', 'phead', 'pbody', 'stats', 'axisbar', 'axislbl', 'lintsum',
 'stubs', 'queue', 'zot', 'tagchips', 'llmbox', 'pend', 'review', 'steps',
 'jobmsg', 'jobout', 'jobbox', 'findings', 'lintcnt', 'obs', 'obsg', 'saveMsg',
 'qhist-count', 'splitDrag'].forEach(id => { const e = mkEl('div'); e.id = id; registry[id] = e; });
registry.qq.value = '';
registry.qprofile.value = 'precise';

// 앱이 만드는 요소도 id 로 찾을 수 있어야 한다 (qanswer, qsteps, qthink…)
const origCreate = doc.createElement;
doc.createElement = t => {
  const e = origCreate(t);
  const set = Object.getOwnPropertyDescriptor(e, 'id');
  Object.defineProperty(e, 'id', {
    get() { return this._id || ''; },
    set(v) { this._id = v; registry[v] = this; },
  });
  return e;
};

const listeners = {};
class FakeES {
  constructor(url) { this.url = url; }
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); }
  close() {}
}

const ctx = {
  document: doc,
  window: { location: { origin: 'http://x', search: '' }, open() {},
    matchMedia: () => ({ matches: false }), requestAnimationFrame: f => f(),
    scrollTo() {}, localStorage: { getItem: () => null, setItem() {} } },
  console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval,
  // 시작할 때 호출되는 API 들이 빈 객체를 받으면 터진다 — 모양만 채워준다
  fetch: u => Promise.resolve({ json: () => Promise.resolve(
    String(u).includes('/query/start') ? { jid: 't1' } :
    /\/(tags|pages|browse|search)/.test(String(u)) ? [] :
    { axis: {}, lint: null, counts: {}, findings: [], stubs: [], items: [],
      pending: [], open: [], done: 0, exists: false, llm: { ok: true, config: {} },
      pages: 0, raw: 0, needs_source: 0, stable: 0, queue: 0, vault: 'x' }) }),
  EventSource: FakeES, URLSearchParams, JSON, Math, Date, Object, Array, String,
  Number, RegExp, Set, Map, encodeURIComponent, decodeURIComponent, Promise,
  location: { origin: 'http://x', search: '' }, navigator: { clipboard: {} },
  matchMedia: () => ({ matches: false }),
  localStorage: { getItem: () => null, setItem() {} },
  alert: () => {},
};
ctx.window.document = doc;
ctx.globalThis = ctx;
vm.createContext(ctx);

try {
  vm.runInContext(rmd, ctx);
  ctx.window.SecAIRestrictedMarkdown = ctx.SecAIRestrictedMarkdown;
  vm.runInContext(app, ctx);
  console.log('스크립트 실행 통과');
} catch (e) {
  console.log('실행 오류:', e.message);
  process.exit(1);
}

process.on('unhandledRejection', () => {});   // 시작 API 오류는 이 검사 대상이 아니다

const fire = (t, d) => (listeners[t] || []).forEach(f => f({ data: JSON.stringify(d) }));


module.exports = { ctx, doc, registry, listeners, fire, mkEl, findIn, findAllIn };

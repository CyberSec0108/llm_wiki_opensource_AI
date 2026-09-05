// 답변이 실제로 DOM 에 그려지는지 브라우저 없이 확인한다.
// 앞서 패치가 qAnswerBox 함수를 통째로 날려 답변이 안 그려진 적이 있다 —
// 같은 사고를 눈으로만 잡을 수는 없어서 이 검사를 만들었다.
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
    tagName: tag, children: [], attrs: {}, style: {}, dataset: {},
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
  querySelector: sel => (sel.startsWith('#') ? registry[sel.slice(1)] || null : mkEl('div')),
  querySelectorAll: () => [],
  addEventListener() {},
};
doc.documentElement.dataset = {};

['qout', 'qq', 'qgo', 'qstop', 'qprofile', 'qshell', 'qsrc', 'qsrc-body',
 'qsrc-toggle', 'qsrc-close', 'qform', 'qnew', 'qhead-title', 'themeToggle',
 'q', 'plist', 'phead', 'pbody', 'stats', 'axisbar', 'axislbl', 'lintsum',
 'stubs', 'queue', 'zot', 'tagchips', 'llmbox', 'pend', 'review', 'steps',
 'jobmsg', 'jobout', 'jobbox', 'findings', 'lintcnt', 'obs', 'obsg', 'saveMsg',
 'qhist-count'].forEach(id => { const e = mkEl('div'); e.id = id; registry[id] = e; });
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

(async () => {
  try {
    registry.qq.value = '보상 해킹이 뭐야?';
    await ctx.startQuery();
    console.log('등록된 이벤트:', Object.keys(listeners).join(', ') || '(없음)');

    fire('stage', { stage: '질문 확인', step: 0, of: 3 });
    fire('candidates', { pages: [{ ordinal: 1, page: '(AI보호) 보상 해킹' }] });
    fire('stage', { stage: '답변 작성', step: 2, of: 3 });
    console.log('답변작성 단계에서 진행표시 있나:', !!doc.getElementById('qsteps'));

    fire('token', { delta: '# 보상 해킹\n\n' });
    fire('token', { delta: '보상 해킹은 규칙은 지키면서[1] 의도와 다른 결과를 내는 것이다.' });

    await new Promise(r => setTimeout(r, 200));   // 렌더러 throttle(75ms) 대기
    const out = registry.qout;
    const text = out.textContent;
    console.log('첫 토큰 뒤 진행표시 남아있나:', !!doc.getElementById('qsteps'), '(false 여야 함)');
    console.log('#qout 텍스트:', JSON.stringify(text.slice(0, 80)));

    const ansBox = doc.getElementById('qanswer');
    const inner = ansBox && ansBox.children[0];
    const fellBack = inner && inner.attrs && inner.attrs['data-markdown-fallback'];
    console.log('렌더 방식:', fellBack ? '평문 폴백' : '마크다운 렌더');
    console.log('인용 버튼 수:', findAllIn(out, '.ai-citation-ref').length);
    if (text.includes('보상 해킹은')) console.log('==> 답변이 DOM 에 그려진다  OK');
    else { console.log('==> 답변이 안 그려진다  실패'); process.exit(1); }
  } catch (e) {
    console.log('처리 오류:', e.message);
    console.log(e.stack.split('\n').slice(1, 3).join('\n'));
    process.exit(1);
  }
})();

const $ = s => document.querySelector(s);
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c;
  if (x !== undefined) e.textContent = x; return e; };
const get = p => fetch('/api' + p).then(r => r.json());
const post = (p, d) => fetch('/api' + p, { method: 'POST',
  body: new URLSearchParams(d || {}) }).then(r => r.json());

// 다크모드 — OS 설정을 기본으로 따르되, 눌러서 명시적으로 바꿀 수 있다
(() => {
  const btn = $('#themeToggle');
  const apply = t => { document.documentElement.dataset.theme = t;
    try { localStorage.setItem('llmwiki_theme', t); } catch (_) {} };
  btn.onclick = () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
    apply(cur === 'dark' ? 'light' : 'dark');
  };
})();

// 위키 탭 목록 폭 조절 — 손잡이를 끌면 .split 의 --splitw 를 바꾼다.
// 폭은 브라우저에 남겨 다음에 열 때도 유지한다
(() => {
  const sp = document.querySelector('.split');
  const hd = $('#splitDrag');
  if (!sp || !hd) return;
  const BASE = 300, MIN = 190;
  const setW = w => sp.style.setProperty('--splitw', w + 'px');
  // 본문이 너무 좁아지지 않게 상한을 컨테이너 폭에서 계산한다
  const maxW = () => Math.max(MIN, Math.min(680, sp.clientWidth - 340));
  const save = w => { try { localStorage.setItem('llmwiki_splitw', w); } catch (_) {} };

  try { const v = parseInt(localStorage.getItem('llmwiki_splitw'), 10);
    if (v > 0) setW(v); } catch (_) {}

  let on = false;
  hd.addEventListener('pointerdown', e => {
    on = true; hd.classList.add('on'); hd.setPointerCapture(e.pointerId);
    document.body.style.userSelect = 'none'; e.preventDefault();
  });
  hd.addEventListener('pointermove', e => {
    if (!on) return;
    const w = Math.round(Math.min(maxW(),
      Math.max(MIN, e.clientX - sp.getBoundingClientRect().left)));
    setW(w);
  });
  const end = () => { if (!on) return; on = false;
    hd.classList.remove('on'); document.body.style.userSelect = '';
    save(parseInt(sp.style.getPropertyValue('--splitw'), 10) || BASE); };
  hd.addEventListener('pointerup', end);
  hd.addEventListener('pointercancel', end);
  hd.ondblclick = () => { setW(BASE); save(BASE); };   // 두 번 누르면 기본값
})();

document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('section').forEach(s => s.classList.toggle('on', s.id === b.dataset.t));
  // 질문 탭은 3열 대화형 레이아웃이라 다른 탭보다 넓게 쓴다
  // 2열을 쓰는 탭은 더 넓게 — 목록과 본문을 나란히 놓아야 해서 폭이 필요하다
  document.querySelector('main').classList.toggle('wide',
    b.dataset.t === 'query' || b.dataset.t === 'wiki');
  // 화면을 열 때마다 다시 읽는다 — .env 를 고치면 새로고침 없이 반영되도록
  if (b.dataset.t === 'ing') drawIngest();
  if (b.dataset.t === 's') loadStatus();
});

const AX = { 'ai-for-security': ['AI활용', 'a'], 'securing-ai': ['AI보호', 'b'],
             'both': ['공통', ''], 'none': ['기타', ''] };

async function loadStatus() {
  const d = await get('/status');
  const cards = [['페이지', d.pages], ['원본', d.raw], ['미인제스트', d.pending],
                 ['보강대기', d.needs_source], ['stable', d.stable], ['대기열', d.queue]];
  $('#stats').innerHTML = '';
  cards.forEach(([k, v]) => { const c = el('div', 'stat');
    c.appendChild(el('b', '', v)); c.appendChild(el('span', '', k)); $('#stats').appendChild(c); });

  const bar = $('#axisbar'), lbl = $('#axislbl'); bar.innerHTML = ''; lbl.innerHTML = '';
  const tot = Object.values(d.axis).reduce((a, b) => a + b, 0) || 1;
  Object.entries(d.axis).forEach(([k, v]) => {
    const [nm, cl] = AX[k] || [k, ''];
    const i = el('i'); i.style.width = (v / tot * 100) + '%';
    i.style.background = cl === 'a' ? 'var(--a)' : cl === 'b' ? 'var(--b)' : 'var(--line)';
    bar.appendChild(i);
    lbl.appendChild(el('span', 'pill ' + cl, nm + ' ' + v));
  });

  $('#lintsum').innerHTML = '';
  if (d.lint) {
    const c = d.lint.counts, tot2 = (c.E || 0) + (c.W || 0) + (c.I || 0);
    $('#lintsum').append(el('span', '', d.lint.date + '  ·  '),
      el('span', 'sev E', 'Error ' + (c.E || 0)), el('span', '', '   '),
      el('span', 'sev W', 'Warning ' + (c.W || 0)), el('span', '', '   '),
      el('span', 'sev I', 'Info ' + (c.I || 0)),
      el('span', '', tot2 && !c.E && !c.W ? '   구조 이상 없음' : ''));
  } else $('#lintsum').textContent = '아직 실행한 적 없음';

  if (d.vault) {
    const v = encodeURIComponent(d.vault);
    $('#obs').href = 'obsidian://open?vault=' + v;
    // Advanced URI 플러그인이 있으면 그래프까지 한 번에 열린다
    $('#obsg').href = 'obsidian://adv-uri?vault=' + v + '&commandid=graph%3Aopen';
    $('#obsg').title = 'Advanced URI 플러그인으로 그래프 뷰를 바로 엽니다';
  }
  const q = await get('/queue');
  $('#queue').textContent = q.items.length ? q.items.length + '건 대기 중' : '비어 있음';
}

async function loadStubs() {
  const d = await get('/lint');
  const box = $('#stubs'); box.innerHTML = '';
  (d.stubs || []).slice(0, 8).forEach(s => {
    const r = el('div', 'row');
    r.appendChild(el('span', 'pill', s.refs + '곳'));
    const g = el('div', 'grow'); g.appendChild(el('div', '', s.name));
    g.appendChild(el('small', '', s.from.join(' · '))); r.appendChild(g);
    box.appendChild(r);
  });
  if (!box.children.length) box.innerHTML = '<div class="muted">없음</div>';
}

async function loadLint() {
  const d = await get('/lint');
  const c = d.counts || {};
  $('#lintcnt').innerHTML = '';
  $('#lintcnt').append(el('span', 'sev E', '● ' + (c.E || 0) + ' Error   '),
    el('span', 'sev W', '● ' + (c.W || 0) + ' Warning   '),
    el('span', 'sev I', '● ' + (c.I || 0) + ' Info'),
    el('span', 'muted', d.date ? '   (' + d.date + ')' : ''));
  const box = $('#findings'); box.innerHTML = '';
  if (!(d.findings || []).length) {
    box.innerHTML = '<div class="box"><span class="ok">발견된 문제가 없습니다.</span></div>';
    return;
  }
  d.findings.forEach(f => {
    const b = el('div', 'box'); b.style.padding = '13px 16px';
    const top = el('div', 'row'); top.style.borderTop = 'none'; top.style.padding = '0';
    top.appendChild(el('span', 'sev ' + f.severity, f.check));
    const g = el('div', 'grow'); g.appendChild(el('div', '', f.what));
    g.appendChild(el('small', '', f.where + '  →  ' + f.how)); top.appendChild(g);
    const ig = el('button', 'act', '오탐');
    ig.onclick = async () => { await post('/lint/ignore', { check: f.check, where: f.where });
      loadLint(); loadStatus(); };
    top.appendChild(ig); b.appendChild(top); box.appendChild(b);
  });
}

async function runLint() {
  $('#lintcnt').textContent = '실행 중…';
  await post('/lint/run'); loadLint(); loadStatus(); loadStubs();
}

async function loadTags() {
  const tags = await get('/tags'); const box = $('#tagchips'); box.innerHTML = '';
  tags.forEach(t => { const c = el('span', 'chip', t.tag + ' (' + t.n + ')');
    c.onclick = () => { c.classList.toggle('on');
      const cur = $('#f_topics').value.split(',').map(x => x.trim()).filter(Boolean);
      const i = cur.indexOf(t.tag); i < 0 ? cur.push(t.tag) : cur.splice(i, 1);
      $('#f_topics').value = cur.join(', '); };
    box.appendChild(c); });
  if (!tags.length) box.innerHTML = '<span class="muted">아직 태그가 없습니다</span>';
}

async function loadZotero() {
  const d = await get('/zotero'); const box = $('#zot'); box.innerHTML = '';
  if (!d.ok) { box.textContent = d.error; return; }
  d.items.forEach(it => {
    const r = el('div', 'row');
    r.appendChild(el('span', 'pill' + (it.in_vault ? '' : ' a'), it.in_vault ? '있음' : '신규'));
    const g = el('div', 'grow'); g.appendChild(el('div', '', it.title));
    g.appendChild(el('small', '', [it.authors[0], it.date, it.venue].filter(Boolean).join(' · ')));
    r.appendChild(g);
    if (!it.in_vault) { const b = el('button', 'act', '폼에 채우기');
      b.onclick = () => { fill(it); document.querySelector('[data-t=add]').click();
        window.scrollTo(0, 9999); }; r.appendChild(b); }
    box.appendChild(r);
  });
  if (!d.items.length) box.textContent = 'Zotero 라이브러리가 비어 있습니다';
}

function fill(it) {
  $('#f_kind').value = it.itemType === 'conferencePaper' || it.itemType === 'preprint'
    || it.itemType === 'journalArticle' ? 'paper' : 'article';
  $('#f_title').value = it.title; $('#f_authors').value = it.authors.join('; ');
  $('#f_date').value = it.date; $('#f_doi').value = it.doi;
  $('#f_cite').value = it.cite_key; $('#f_venue').value = it.venue; $('#f_url').value = it.url;
  $('#f_filename').value = '';
}

async function save(q) {
  const b = id => $('#f_' + id).value.trim();
  if (!b('title') || !b('why')) { $('#saveMsg').textContent = '제목과 「왜 담았나」는 필수입니다'; return; }
  const r = await post('/source', { kind: b('kind'), title: b('title'), why: b('why'),
    axis: b('axis'), topics: b('topics'), authors: b('authors'), date: b('date'),
    doi: b('doi'), url: b('url'), venue: b('venue'), cite_key: b('cite'),
    filename: b('filename'), queue: q ? '1' : '' });
  $('#saveMsg').textContent = r.ok
    ? '저장됨: ' + r.path + (r.queued ? '  · 대기열 추가' : '') : (r.error || '실패');
  if (r.ok) { ['title', 'why', 'authors', 'date', 'doi', 'cite', 'venue', 'url', 'topics', 'filename']
    .forEach(k => $('#f_' + k).value = '');
    document.querySelectorAll('.chip.on').forEach(c => c.classList.remove('on'));
    loadStatus(); loadTags(); loadZotero(); }
}

let PAGES = [], FILT = '', LAYER = '';
const LAYNAME = { wiki: '위키', raw: '원본', context: '맥락', docs: '문서' };
const layName = k => LAYNAME[k] || k;

async function loadWiki() {
  // 위키와 원본을 한 목록에서 본다. 위키의 서술이 어디서 왔는지
  // 확인하려면 원본을 열어봐야 하기 때문이다.
  PAGES = await get('/browse'); drawList();
}

function drawList(hits) {
  const box = $('#plist'); box.innerHTML = '';
  if (hits) {
    hits.filter(h => !LAYER || h.layer === LAYER).forEach(h => {
      const d = el('div', 'item');
      const r = el('div', 'item-head');
      r.appendChild(el('span', 'lay lay-' + h.layer,
        layName(h.layer)));
      const nm = el('span', 'item-name', h.name);
      nm.title = h.name;              // 잘린 이름은 툴팁으로 확인한다
      r.appendChild(nm);
      d.appendChild(r);
      d.appendChild(el('small', '', h.folder + (h.hits ? ' · ' + h.hits + '회' : '') +
        (h.snippet ? ' · ' + h.snippet : '')));
      if (h.openable) d.onclick = () => openPage(h.path || h.name);
      box.appendChild(d); });
    if (!hits.length) box.innerHTML = '<div class="muted">결과 없음</div>';
    return;
  }
  const rows = PAGES.filter(p =>
    (!LAYER || p.layer === LAYER) && (!FILT || p.axis === FILT));
  rows.forEach(p => {
    const d = el('div', 'item'); d.dataset.n = p.path || p.name;
    const h = el('div', 'item-head');
    h.appendChild(el('span', 'lay lay-' + p.layer, layName(p.layer)));
    const nm = el('span', 'item-name', p.name);
    nm.title = p.name;              // 잘린 이름은 툴팁으로 확인한다
    h.appendChild(nm);
    d.appendChild(h);
    d.appendChild(el('small', '', p.sub || p.status));
    d.onclick = () => openPage(p.path || p.name); box.appendChild(d);
  });
  if (!rows.length) box.innerHTML = '<div class="muted">해당 없음</div>';
}

async function openPage(name) {
  document.querySelectorAll('#plist .item').forEach(i =>
    i.classList.toggle('on', i.dataset.n === name));
  const d = await get('/page?name=' + encodeURIComponent(name));
  if (!d.ok) { $('#pbody').textContent = d.error; return; }
  const h = $('#phead'); h.innerHTML = '';
  const t = el('div'); t.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap';
  t.appendChild(el('span', 'lay lay-' + d.layer, layName(d.layer)));
  t.appendChild(el('b', '', d.name));
  if (d.meta.status) t.appendChild(el('span', 'pill', d.meta.status));
  if (d.layer === 'raw') {
    t.appendChild(el('span', 'pill', d.meta.ingested === 'true' ? '반영됨' : '미인제스트'));
    if (d.meta.axis) t.appendChild(el('span', 'pill', d.meta.axis));
  }
  if (d.meta.needs_source === 'true') t.appendChild(el('span', 'pill', '보강필요'));
  const ob = el('a', 'pill'); ob.textContent = 'Obsidian에서 열기'; ob.style.cursor = 'pointer';
  ob.href = 'obsidian://open?vault=' + encodeURIComponent(d.vault) +
            '&file=' + encodeURIComponent(d.path.replace(/\.md$/, ''));
  t.appendChild(ob); h.appendChild(t);
  if (d.meta.source) h.appendChild(el('small', 'muted', '출처 ' + d.meta.source));
  if (d.meta.why) h.appendChild(el('small', 'muted', '왜 담았나 — ' + d.meta.why));
  if (d.layer === 'raw')
    h.appendChild(el('small', 'muted', '원본은 불변이다. 고치지 않는다.'));
  $('#pbody').innerHTML = d.html;
  const bl = el('div', 'box'); bl.style.marginTop = '18px';
  bl.appendChild(el('h2', '', '이 페이지를 참조하는 곳 (' + d.backlinks.length + ')'));
  d.backlinks.forEach(b => { const a = el('a', 'chip', b);
    a.style.cursor = 'pointer'; a.onclick = () => openPage(b); bl.appendChild(a); });
  if (!d.backlinks.length) bl.appendChild(el('span', 'muted', '없음'));
  $('#pbody').appendChild(bl);
  $('#pbody').querySelectorAll('a.wl').forEach(a =>
    a.onclick = () => openPage(a.dataset.p));
  window.scrollTo(0, 0);
}

document.querySelectorAll('[data-f]').forEach(c => c.onclick = () => {
  document.querySelectorAll('[data-f]').forEach(x => x.classList.toggle('on', x === c));
  FILT = c.dataset.f; $('#q').value = ''; drawList(); });

document.querySelectorAll('[data-layer]').forEach(c => c.onclick = () => {
  document.querySelectorAll('[data-layer]').forEach(x => x.classList.toggle('on', x === c));
  LAYER = c.dataset.layer;
  const v = $('#q').value.trim();
  if (v) get('/search?q=' + encodeURIComponent(v)).then(drawList);
  else drawList(); });

let qt;
$('#q').oninput = e => { clearTimeout(qt); const v = e.target.value.trim();
  qt = setTimeout(async () => v ? drawList(await get('/search?q=' + encodeURIComponent(v)))
    : drawList(), 250); };

loadStatus(); loadStubs(); loadLint(); loadTags(); loadZotero(); loadWiki();

// 새 탭으로 열린 경우 — /?tab=wiki&page=... 를 읽어 그 페이지를 바로 띄운다
(() => {
  const u = new URLSearchParams(location.search);
  const tab = u.get('tab'), page = u.get('page');
  if (!tab) return;
  const btn = document.querySelector('[data-t=' + tab + ']');
  if (btn) btn.click();
  if (page) setTimeout(() => openPage(page), 60);
})();
drawIngest();
/* ===== 질문 ===== */
// 대화는 아래로 쌓인다. 새 질문을 해도 앞의 질문·답변은 그대로 남는다 —
// 이어서 묻다 보면 앞의 답을 다시 봐야 할 때가 많다.
// 턴마다 자기 요소(진행표시·생각·답변·출처)를 따로 들고 있어야 해서
// 고정 id 대신 턴 번호를 붙인다.
const STLABEL = { ok: '자유롭게 인용', warn: '검증 필요', err: '인용 금지' };
const QEXAMPLES = [
  '프롬프트 인젝션을 어떻게 막나?',
  '보상 해킹이 뭐야?',
  'Sysmon 로그의 온톨로지 구성 요소는?',
];

let qES = null, qJID = null, qLastQ = '';
let qTurn = 0;              // 지금까지 만든 턴 수
const T = {};               // 턴 번호 -> 그 턴의 상태

function turn(n) {
  return (T[n] = T[n] || { citeMap: {}, renderer: null, thinkTimer: null,
                           thinkT0: 0, thinkFolded: false, allowedIds: [] });
}

function qScroll() {
  const o = $('#qout');
  o.scrollTop = o.scrollHeight;
}

function drawWelcome() {
  const box = $('#qout');
  if (box.querySelector('.msg-user')) return;   // 대화가 있으면 안 띄운다
  box.innerHTML = '';
  const w = el('div', 'qwelcome');
  w.appendChild(el('strong', '', '이렇게 물어보세요'));
  QEXAMPLES.forEach(ex => {
    const b = el('button', '', ex);
    b.type = 'button';
    b.onclick = () => { $('#qq').value = ex; startQuery(); };
    w.appendChild(b);
  });
  box.appendChild(w);
}

// ── 턴 단위 요소 ──
function qSteps(n, stepIdx) {
  const STEPS = ['질문 확인', '위키 후보 찾기', '답변 작성'];
  let wrap = document.getElementById('qsteps-' + n);
  if (!wrap) {
    wrap = el('div', 'gen'); wrap.id = 'qsteps-' + n;
    wrap.setAttribute('role', 'status');
    wrap.appendChild(el('strong', 'gen-title', '답변을 준비하고 있습니다'));
    wrap.appendChild(document.createElement('ol'));
    $('#qout').appendChild(wrap); qScroll();
  }
  const ol = wrap.querySelector('ol'); ol.innerHTML = '';
  STEPS.forEach((label, i) => {
    const li = document.createElement('li');
    li.dataset.state = i < stepIdx ? 'done' : i === stepIdx ? 'active' : 'pending';
    li.appendChild(el('span', 'gen-dot'));
    li.appendChild(el('span', '', label));
    ol.appendChild(li);
  });
}

function qStepsRemove(n) {
  document.getElementById('qsteps-' + n)?.remove();
}

function qAnswerBox(n) {
  let box = document.getElementById('qanswer-' + n);
  if (!box) {
    box = el('div', 'ans'); box.id = 'qanswer-' + n;
    box.appendChild(el('div', '', ''));
    $('#qout').appendChild(box); qScroll();
  }
  return box.firstChild;
}

function qThinkBox(n) {
  // 모델의 생각은 OpenRouter 공급자에 따라 올 때도 안 올 때도 있다.
  // 안 와도 경과 시간은 보여줘야 멈춘 것처럼 보이지 않는다.
  const t = turn(n);
  let d = document.getElementById('qthink-' + n);
  if (!d) {
    d = document.createElement('details');
    d.className = 'think'; d.id = 'qthink-' + n; d.open = true;
    const sm = document.createElement('summary');
    sm.id = 'qthink-sum-' + n; sm.textContent = '답변을 쓰는 중… 0초';
    const body = el('div', 'think-body'); body.id = 'qthink-body-' + n;
    d.appendChild(sm); d.appendChild(body);
    $('#qout').appendChild(d); qScroll();
    t.thinkT0 = Date.now();
    t.thinkTimer = setInterval(() => {
      const x = document.getElementById('qthink-sum-' + n);
      if (x && !t.thinkFolded) {
        const b = document.getElementById('qthink-body-' + n);
        const has = b && b.textContent.trim().length > 0;
        x.textContent = (has ? '모델이 생각하는 중… ' : '답변을 쓰는 중… ') +
          Math.round((Date.now() - t.thinkT0) / 1000) + '초';
      }
    }, 1000);
  }
  return document.getElementById('qthink-body-' + n);
}

function escapeHtml(unsafe) {
  return (unsafe || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function qThinkAppend(n, delta) {
  const b = qThinkBox(n);
  const t = turn(n);
  if (!t.rawReasoning) t.rawReasoning = '';
  t.rawReasoning += delta;
  
  const lines = t.rawReasoning.split('\n');
  let html = '<div class="think-tree">';
  
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();
    if (!line) continue;
    
    const isList = /^[*-]\s+/.test(line) || /^\d+\.\s+/.test(line);
    if (isList) {
      line = line.replace(/^[*-]\s+/, '').replace(/^\d+\.\s+/, '');
      html += `<div class="think-step think-node"><span class="think-bullet"></span><div>${escapeHtml(line)}</div></div>`;
    } else {
      html += `<div class="think-node">${escapeHtml(line)}</div>`;
    }
  }
  html += '</div>';
  
  b.innerHTML = html;
  b.scrollTop = b.scrollHeight;
}

function qThinkFold(n) {
  const t = turn(n);
  if (t.thinkTimer) { clearInterval(t.thinkTimer); t.thinkTimer = null; }
  const d = document.getElementById('qthink-' + n);
  if (!d || t.thinkFolded) return;
  t.thinkFolded = true;
  const body = document.getElementById('qthink-body-' + n);
  if (!body || !body.textContent.trim()) { d.remove(); return; }   // 빈 상자는 남기지 않는다
  d.open = false;
  const sm = document.getElementById('qthink-sum-' + n);
  if (sm) sm.textContent = '모델의 생각 ' +
    Math.round((Date.now() - t.thinkT0) / 1000) + '초 (눌러서 보기)';
}

// ── 출처 드로어 ──
function qSrcOpen(on) {
  $('#qshell').classList.toggle('src-open', on);
  $('#qsrc-toggle').title = on ? '답변 근거 닫기' : '답변 근거 열기';
}

function qSrcRender(n, rows, note) {
  // 드로어는 하나뿐이라 항상 "지금 보고 있는 턴"의 근거를 보여준다.
  const sb = $('#qsrc-body');
  sb.innerHTML = '';
  if (note) {
    const p = el('p', 'muted', note); p.style.margin = '0 0 10px';
    sb.appendChild(p);
  }
  const t = turn(n);
  t.citeMap = {};
  rows.forEach(r => {
    const card = el('div', 'scard'); card.dataset.n = r.ordinal;
    const head = el('div', 'scard-head');
    head.appendChild(el('span', 'scard-num', '[' + r.ordinal + ']'));
    head.appendChild(el('strong', '', r.page));
    card.appendChild(head);
    if (r.status) {
      const meta = [r.status, STLABEL[r.level] || ''];
      if (r.needs_source) meta.push('보강 필요');
      if (r.derived) meta.push('파생 페이지');
      card.appendChild(el('p', '', meta.filter(Boolean).join(' · ')));
    }
    const a = el('a', '', '위키에서 열기 ↗');
    a.href = '/?tab=wiki&page=' + encodeURIComponent(r.page);
    a.target = '_blank'; a.rel = 'noopener';
    card.appendChild(a);
    t.citeMap[r.ordinal] = card;
    sb.appendChild(card);
  });
  qSrcOpen(true);
}

function onCite(n, citationId) {
  // 인용을 누르면 그 턴의 근거를 드로어에 띄우고 해당 카드를 짚어준다
  const t = turn(n);
  if (t.sources) qSrcRender(n, t.sources);
  const num = (citationId.match(/\d+/) || [])[0];
  const row = turn(n).citeMap[num];
  if (!row) return;
  document.querySelectorAll('.scard.hl').forEach(x => x.classList.remove('hl'));
  row.classList.add('hl');
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  setTimeout(() => row.classList.remove('hl'), 1800);
}

// ── 질의 ──
async function startQuery() {
  const v = $('#qq').value.trim();
  if (!v || qES) return;
  qLastQ = v;
  const n = ++qTurn;
  const t = turn(n);

  document.getElementById('qwelcome')?.remove();
  $('#qout').querySelector('.qwelcome')?.remove();
  $('#qout').appendChild(el('div', 'msg-user', v));   // 앞의 대화는 지우지 않는다
  $('#qhead-title').textContent = v.length > 46 ? v.slice(0, 46) + '…' : v;
  $('#qq').value = '';
  qScroll();

  $('#qgo').disabled = true; $('#qstop').hidden = false;
  qSteps(n, 0);

  const profile = $('#qprofile').value;
  let r;
  try {
    r = await post('/query/start', {
      q: v, use_raw: profile === 'precise' ? 'true' : 'false',
      max_pages: profile === 'fast' ? 2 : 4 });
  } catch (e) { r = { error: String(e) }; }
  if (r.error) { qDone(); showQError(r.error); return; }
  qJID = r.jid; t.jid = r.jid;

  qES = new EventSource('/api/query/events?jid=' + encodeURIComponent(r.jid));
  qES.addEventListener('stage', e => {
    const d = JSON.parse(e.data);
    qSteps(n, d.step);
    if (d.step === 2) qThinkBox(n);
  });
  qES.addEventListener('candidates', e => {
    const pages = JSON.parse(e.data).pages || [];
    t.allowedIds = pages.map(p => '[' + p.ordinal + ']');
    if (pages.length) qSrcRender(n, pages, '읽는 중 ' + pages.length + '쪽 — 답변이 끝나면 실제 인용만 남는다');
  });
  qES.addEventListener('reasoning', e => qThinkAppend(n, JSON.parse(e.data).delta || ''));
  qES.addEventListener('token', e => {
    qStepsRemove(n);          // 첫 토큰이 오면 진행 표시는 사라진다
    qThinkFold(n);
    const d = JSON.parse(e.data);
    const target = qAnswerBox(n);
    if (!t.renderer) {
      t.renderer = window.SecAIRestrictedMarkdown
        ? window.SecAIRestrictedMarkdown.createStreamingRenderer(target,
            { allowedOrigins: [location.origin], allowedCitationIds: t.allowedIds,
              onCitationActivate: id => onCite(n, id) })
        : null;
      if (!t.renderer) target.classList.add('doc');
    }
    if (t.renderer) t.renderer.append(d.delta);
    else target.textContent = (target.textContent || '') + d.delta;
    qScroll();
  });
  qES.addEventListener('done', e => { qDone(); finishAnswer(n, JSON.parse(e.data)); });
  qES.addEventListener('cancelled', e => { qDone(); cancelledAnswer(n); });
  qES.addEventListener('error', e => {
    qDone();
    let msg = '연결이 끊겼다';
    try { msg = JSON.parse(e.data).error || msg; } catch (_) {}
    showQError(msg);
  });
}

function qDone() {
  if (qES) { qES.close(); qES = null; }
  $('#qgo').disabled = false; $('#qstop').hidden = true;
  $('#qstop').disabled = false; $('#qstop').textContent = '■ 중단';
  qJID = null;
}

async function stopQuery() {
  if (!qJID) return;
  $('#qstop').disabled = true; $('#qstop').textContent = '중단 중…';
  await post('/query/stop', { jid: qJID });
}

function showQError(msg) {
  const x = el('div', 'warnbox'); x.textContent = msg;
  $('#qout').appendChild(x); qScroll();
}

function cancelledAnswer(n) {
  const t = turn(n);
  qStepsRemove(n); qThinkFold(n);
  if (t.renderer) t.renderer.complete();
  $('#qout').appendChild(el('div', 'note', '중단됨 — 여기까지만 생성했다.'));
  qScroll();
}

function finishAnswer(n, r) {
  const t = turn(n);
  qThinkFold(n); qStepsRemove(n);
  t.result = r;
  t.sources = r.sources || [];

  // 스트리밍 중에는 후보 번호로만 인용을 인식했다. 끝났으니 실제 인용 번호로
  // 한 번 더 렌더해 확정한다 — 경계 케이스가 있어도 여기서 바로잡힌다.
  const finalIds = (r.sources || []).map(s => '[' + s.ordinal + ']');
  const target = qAnswerBox(n);
  if (window.SecAIRestrictedMarkdown) {
    t.renderer && t.renderer.destroy();
    window.SecAIRestrictedMarkdown.render(target, r.answer || '', {
      allowedOrigins: [location.origin], allowedCitationIds: finalIds,
      onCitationActivate: id => onCite(n, id) });
  } else if (t.renderer) {
    t.renderer.complete();
  }

  if (r.in_wiki === false) {
    const w = el('div', 'warnbox');
    w.innerHTML = '<b>위키에 없음</b><br>' + (r.missing || '이 볼트에 근거가 없다.');
    $('#qout').appendChild(w);
  }
  if ((r.sources || []).length) qSrcRender(n, r.sources);
  else $('#qsrc-body').innerHTML = '<p class="muted">이 답변은 위키 페이지를 인용하지 않았다.</p>';

  if (r.suggest_collect) {
    const c = el('div', 'note');
    c.innerHTML = '<b>모으면 좋을 자료</b><br>' + r.suggest_collect;
    $('#qout').appendChild(c);
  }
  if (r.answer) {
    const f = el('div', 'note');
    f.style.cssText = 'display:flex;gap:8px;align-items:center;border:0;padding:0;margin:4px 0 26px';
    const mk = (label, fn) => { const b = el('button', 'act', label); b.onclick = fn; return b; };
    const msg = el('span', 'muted');
    f.appendChild(mk('Output/ 에 저장', async e => {
      e.target.disabled = true;
      const x = await post('/query/save', { jid: t.jid || '' });
      msg.textContent = x.ok ? ('저장됨 · ' + x.path) : x.error;
      if (!x.ok) e.target.disabled = false;
    }));
    f.appendChild(mk('복사', async e => {
      try { await navigator.clipboard.writeText(qAnswerBox(n).innerText);
        e.target.textContent = '복사됨';
        setTimeout(() => e.target.textContent = '복사', 1500);
      } catch (_) { msg.textContent = '복사 실패 — 직접 드래그해서 복사하라'; }
    }));
    f.appendChild(mk('근거 보기', () => qSrcRender(n, t.sources || [])));
    f.appendChild(msg);
    $('#qout').appendChild(f);
  }
  qScroll();
}

$('#qsrc-toggle').onclick = () => qSrcOpen(!$('#qshell').classList.contains('src-open'));
$('#qsrc-close').onclick = () => qSrcOpen(false);
$('#qhist-toggle').onclick = () => {
  const shell = $('#qshell');
  shell.classList.toggle('hist-collapsed');
  if (window.innerWidth <= 860) {
    shell.classList.toggle('hist-mobile-open');
  }
};
$('#qform').onsubmit = e => { e.preventDefault(); startQuery(); };
$('#qq').onkeydown = e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); startQuery(); } };
$('#qstop').onclick = stopQuery;
$('#qnew').onclick = () => {
  // 새 질문 = 대화를 비우고 처음부터. 이어 묻는 것은 그냥 입력창에 쓰면 된다.
  if (qES) stopQuery();
  Object.keys(T).forEach(k => {
    if (T[k].thinkTimer) clearInterval(T[k].thinkTimer);
    delete T[k];
  });
  qTurn = 0;
  $('#qq').value = '';
  $('#qout').innerHTML = '';
  $('#qhead-title').textContent = '무엇을 확인하고 싶으신가요?';
  $('#qsrc-body').innerHTML = '<p class="muted">답변이 나오면 사용한 위키 페이지가 여기 표시된다.</p>';
  qSrcOpen(false);
  drawWelcome();
  $('#qq').focus();
};
drawWelcome();

/* ===== 인제스트 ===== */
const STEPS = ['읽기', '분석', '작성', '마무리'];
let poll = null;

async function drawIngest() {
  const d = await get('/ingest');
  const L = d.llm, b = $('#llmbox');
  b.innerHTML = '';
  if (!L.ok) {
    const w = el('div', 'warnbox');
    w.innerHTML = '<b>LLM 키가 없어 인제스트를 실행할 수 없다.</b><br>' +
      '1. <a href="' + (L.signup || '#') + '" target="_blank">' + (L.signup || '') +
      '</a> 에서 키를 발급받는다<br>' +
      '2. <code>' + (L.env_path || '.env') + '</code> 를 열어 ' +
      '<code>' + (L.env || '') + '=</code> 뒤에 붙여넣는다<br>' +
      '3. 이 화면을 새로고침한다 (서버는 안 껐다 켜도 된다)' +
      '<br><br>같은 파일에서 <code>LLM_PROVIDER</code>와 <code>LLM_MODEL</code>도 바꾼다.' +
      '<br>현재 &mdash; <code>' + (L.config ? L.config.provider : '') +
      '</code> · <code>' + (L.config ? L.config.model : '') + '</code>';
    b.appendChild(w);
  } else {
    const w = el('div', 'box');
    w.innerHTML = '<h2>LLM</h2><div style="display:flex;align-items:center;gap:10px">' +
      '<div class="grow muted">' + L.provider + ' · <b>' + L.model + '</b> · 키 ' +
      L.key_tail + ' (' + L.from + ')</div>' +
      '<button class="act" id="ptest">연결 시험</button></div>' +
      '<div id="pres"></div>' +
      '<div class="note">제공자·모델·키는 <code>' + L.env_path + '</code> 에서 바꾼다.</div>';
    b.appendChild(w);
    $('#ptest').onclick = async () => {
      $('#pres').innerHTML = '<div class="muted" style="margin-top:8px">확인 중…</div>';
      const r = await post('/llm/test');
      $('#pres').innerHTML = r.ok
        ? '<div class="muted" style="margin-top:8px">통과 · 입력 ' + r.usage.in +
          ' 출력 ' + r.usage.out + ' 토큰</div>'
        : '<div class="warnbox" style="margin-top:8px"><b>' + (r.code || '') + ' ' +
          r.why + '</b><br><small>' + (r.detail || '').replace(/</g, '&lt;') + '</small></div>';
    };
  }
  const pd = $('#pend');
  pd.innerHTML = '';
  if (!d.pending.length) { pd.className = 'muted'; pd.textContent = '없음 — 전부 반영됐다.'; }
  else {
    pd.className = '';
    d.pending.forEach(it => {
      const r = el('div', 'pend');
      const t = el('div', 'grow');
      t.appendChild(el('div', '', it.title));
      t.appendChild(el('div', 'muted', it.path + ' · ' + (it.axis || '축 없음') +
        ' · ' + it.bytes + 'B'));
      r.appendChild(t);
      const g = el('button', 'act', '계획만');
      g.onclick = () => startIngest(it.path, true);
      const bt = el('button', 'act pri', '인제스트');
      bt.onclick = () => startIngest(it.path, false);
      if (!L.ok) { g.disabled = bt.disabled = true; }
      r.appendChild(g); r.appendChild(bt);
      pd.appendChild(r);
    });
  }
  const rv = await get('/review'), rb = $('#review');
  rb.innerHTML = '';
  if (!rv.open.length) { rb.className = 'muted';
    rb.textContent = rv.exists ? '열린 항목 없음 (처리 완료 ' + rv.done + ')' : '아직 없음'; }
  else { rb.className = '';
    rv.open.forEach(x => { const e = el('div', 'rv'); e.innerHTML = x; rb.appendChild(e); }); }
}

async function showPlan(jid, o) {
  const p = await get('/ingest/preview?jid=' + encodeURIComponent(jid));
  const x = el('div', 'box');
  let s = '<h2>편집안 ' + p.edits.length + '건</h2>';
  p.edits.forEach(e => {
    const grew = e.after - e.before;
    s += '<div style="padding:8px 0;border-bottom:1px solid var(--line)">' +
      '<b>' + e.page + '</b> <span class="pill">' + e.mode + '</span> ' +
      '<span class="muted">' + e.before + ' → ' + e.after + '자 (' +
      (grew >= 0 ? '+' : '') + grew + ') · 추가 ' + e.added + '줄 · 삭제 ' +
      e.removed + '줄</span><br><small class="muted">' + (e.why || '') + '</small>';
    // 지우는 줄이 있으면 반드시 보여준다. update 는 더하기만 해야 한다
    if (e.removed_lines.length)
      s += '<div class="warnbox" style="margin-top:7px"><b>지워지는 줄</b><br>' +
        e.removed_lines.map(l => l.replace(/</g, '&lt;')).join('<br>') + '</div>';
    s += '</div>';
  });
  if (p.review.length) {
    s += '<h2 style="margin-top:14px">리뷰 큐로 미룰 것 ' + p.review.length + '건</h2>';
    p.review.forEach(r => { s += '<div class="rv"><b>' + r.action + '</b> · ' +
      (r.subject || '') + '<br><small class="muted">' + (r.detail || '') +
      '</small></div>'; });
  }
  s += '<div class="note">log: ' + (p.log || '') + '</div>' +
       '<button class="act pri" id="doapply" style="margin-top:10px">이대로 적용</button>';
  x.innerHTML = s;
  o.appendChild(x);
  $('#doapply').onclick = async () => {
    $('#doapply').disabled = true;
    $('#doapply').textContent = '적용 중…';
    const r = await post('/ingest/apply', { jid: jid });
    if (!r.ok) { alert(r.error); $('#doapply').disabled = false; return; }
    tick(jid); loadStatus(); loadLint();
  };
}

async function startIngest(path, planOnly) {
  const r = await post('/ingest', { path: path, plan_only: planOnly ? 'true' : 'false' });
  if (r.error) { alert(r.error); return; }
  $('#jobbox').style.display = '';
  if (poll) clearInterval(poll);
  poll = setInterval(() => tick(r.jid), 1200);
  tick(r.jid);
}

async function tick(jid) {
  const d = await get('/ingest/job?jid=' + encodeURIComponent(jid));
  const sv = $('#steps'); sv.innerHTML = '';
  STEPS.forEach((n, i) => {
    const e = el('div', '', (i + 1) + '. ' + n);
    if (d.step > i + 1 || d.done) e.className = 'ok';
    else if (d.step === i + 1) e.className = 'on';
    sv.appendChild(e);
  });
  $('#jobmsg').textContent = (d.error ? '실패 — ' + d.error : d.stage + ' … ' + d.path);
  const o = $('#jobout'); o.innerHTML = '';
  if (d.analysis) {
    const a = d.analysis, x = el('div', 'box');
    let h = '<h2>분석</h2><div class="muted">' + (a.summary || '') + '</div>';
    if (a.axis_check && a.axis_check.agrees === false)
      h += '<div class="warnbox" style="margin-top:9px"><b>축 불일치</b> &mdash; 적힌 것 ' +
        a.axis_check.stated + ' / 판단 ' + a.axis_check.judged + '<br>' +
        (a.axis_check.why || '') + '</div>';
    if ((a.update_targets || []).length)
      h += '<div style="margin-top:9px"><b>갱신 대상</b><br>' +
        a.update_targets.map(t => '· ' + t.page + ' &mdash; ' + t.what).join('<br>') + '</div>';
    if ((a.new_page_candidates || []).length)
      h += '<div style="margin-top:9px"><b>새 페이지 후보</b><br>' +
        a.new_page_candidates.map(c => (c.passes ? '통과 ' : '보류 ') + c.name +
          ' &mdash; ' + c.why).join('<br>') + '</div>';
    if ((a.conflicts || []).length)
      h += '<div style="margin-top:9px"><b>모순 발견 ' + a.conflicts.length +
        '건</b> &mdash; 리뷰 큐로 간다</div>';
    x.innerHTML = h; o.appendChild(x);
  }
  if (d.plan && !d.applied) await showPlan(jid, o);
  if (d.applied) {
    const x = el('div', 'box');
    x.innerHTML = '<h2>반영 완료</h2>' + d.applied.map(a =>
      a.page ? ('· <b>' + a.page + '</b> ' + a.mode)
      : a.review ? ('· 리뷰 큐 ' + a.review + '건')
      : a.raw ? ('· 원본 ingested: true')
      : ('· ' + JSON.stringify(a))).join('<br>') +
      '<div class="note">위키가 바뀌었다. <code>/lint</code> 로 확인하는 것을 권한다.</div>';
    o.appendChild(x);
  }
  if (d.done) { clearInterval(poll); poll = null; drawIngest(); loadStatus(); }
}


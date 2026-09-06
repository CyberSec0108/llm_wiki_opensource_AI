#!/usr/bin/env python3
"""볼트 웹 UI — 1·2단계.

원칙 (루트 CLAUDE.md "도구를 추가할 때"):
  1. 파일이 정본이다. 이 서버가 만드는 상태도 전부 파일이다
     (queue.md, lint-ignore.json, reports/)
  2. 규칙을 코드에 복사하지 않는다 — 인제스트는 tools/ingest.py가
     CLAUDE.md·SKILL.md를 **읽어서** 프롬프트로 쓴다
  3. 이 서버를 꺼도 Obsidian·git·Claude Code가 그대로 동작한다

실행:
    python tools/server.py                  localhost:5000
    python tools/server.py --port 8000
    python tools/server.py --lan            같은 와이파이의 다른 기기에서 접속
"""
import io, os, re, sys, time, json, glob, shutil, sqlite3, tempfile, subprocess, datetime, threading, queue, asyncio
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

# 윈도우의 ProactorEventLoop 는 클라이언트가 이미 끊은 소켓을 닫을 때
# ConnectionResetError 를 콜백에서 그대로 던진다. 서버는 멀쩡한데 콘솔에만
# 긴 traceback 이 찍힌다 — uvicorn on Windows 의 알려진 노이즈다.
# 우리가 잡을 수 있는 지점이 아니라(asyncio 내부 콜백) 여기서 그 예외만 삼킨다.
if sys.platform == 'win32':
    from asyncio.proactor_events import _ProactorBasePipeTransport

    def _quiet_connection_lost(self, exc, _orig=_ProactorBasePipeTransport._call_connection_lost):
        try:
            _orig(self, exc)
        except (ConnectionResetError, ConnectionAbortedError):
            pass

    _ProactorBasePipeTransport._call_connection_lost = _quiet_connection_lost
ZOTERO = os.path.join(os.path.expanduser('~'), 'Zotero')
PREFIX_AXIS = {'ai-for-security': '(AI활용)', 'securing-ai': '(AI보호)',
               'both': '(공통)', '': '(기타)'}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm       # noqa: E402  제공자 계층
import ingest    # noqa: E402  인제스트 파이프라인
import query     # noqa: E402  질의 파이프라인

app = FastAPI(title='LLM Wiki')
app.mount('/static', StaticFiles(directory=os.path.join(ROOT, 'tools', 'static')), name='static')

# 실행 중인 인제스트. 진행 상황 자체는 reports/ 의 파일이 정본이고,
# 이 딕셔너리는 스레드를 붙잡아 두기 위한 것뿐이다.
JOBS = {}
LAST_Q = {}   # 직전 질의 결과. jid 없이 저장을 부르면 이걸 쓴다
# 대화가 아래로 쌓이므로 턴마다 결과를 따로 들고 있어야 한다 —
# 세 번째 답변을 보다가 첫 번째 답변을 저장할 수 있어야 하기 때문이다.
RESULTS = {}

# 실행 중인 질의(스트리밍). 답변 자체는 결과가 아니라 **진행 중인 과정**이라
# reports/ 파일로 남기지 않는다 — 끝나면 의미가 없는 상태다. jid 하나당
# 이벤트 큐(SSE가 소비) + 취소 플래그(중단 버튼이 세팅) 한 쌍을 둔다.
QSTREAMS = {}   # jid -> {'q': queue.Queue, 'cancel': threading.Event}


def rd(p):
    return io.open(p, encoding='utf-8').read()


def wr(p, s):
    os.path.isdir(os.path.dirname(p)) or os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8').write(s)


def fm_of(text):
    e = text.find(NL + '---', 3)
    return text[:e] if e > 0 else ''


def wiki_pages():
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'wiki', '*.md'))):
        b = os.path.basename(p)[:-3]
        if b in ('CLAUDE', 'index', 'log') or '.example' in b:
            continue
        fm = fm_of(rd(p))
        g = lambda k: (re.search(r'^' + k + r':\s*(.+)$', fm, re.M) or [None, ''])[1].strip()
        axis = ('ai-for-security' if 'ai-for-security' in fm else
                'securing-ai' if 'securing-ai' in fm else '')
        out.append({
            'name': b, 'status': g('status'), 'axis': axis,
            'description': g('description').strip('"'),
            'needs_source': 'needs_source: true' in fm,
            'sources': len(re.findall(r'(raw/[^\s]+\.md|[a-z]+\d{4}[A-Za-z]+)', fm)),
        })
    return out


def raw_files():
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'raw', '**', '*.md'), recursive=True)):
        if os.path.basename(p) == 'CLAUDE.md':
            continue
        s = rd(p)
        fm = fm_of(s)
        g = lambda k: (re.search(r'^' + k + r':\s*(.+)$', fm, re.M) or [None, ''])[1].strip()
        out.append({
            'path': os.path.relpath(p, ROOT).replace(chr(92), '/'),
            'name': os.path.basename(p)[:-3],
            'type': g('type').strip('"'), 'axis': g('axis').strip('"'),
            'why': g('why').strip('"'),
            'ingested': 'ingested: true' in fm,
            'topics': re.findall(r'주제/[^\s"\',\]]+', fm),
        })
    return out


def latest_lint():
    js = sorted(glob.glob(os.path.join(ROOT, 'reports', 'lint-*.json')))
    if not js:
        return None
    d = json.loads(rd(js[-1]))
    ig = ignore_set()
    d['findings'] = [f for f in d['findings']
                     if (str(f['check']), f['where']) not in ig]
    for k in 'EWI':
        d['counts'][k] = len([f for f in d['findings'] if f['severity'] == k])
    return d


def ignore_set():
    p = os.path.join(ROOT, 'lint-ignore.json')
    if not os.path.exists(p):
        return set()
    return set((x['check'], x['where']) for x in json.loads(rd(p)))


# ── API ───────────────────────────────────────────────────────
@app.get('/api/status')
def api_status():
    pages, raws = wiki_pages(), raw_files()
    lint = latest_lint()
    axis_count = {}
    for x in pages:
        axis_count[x['axis'] or 'none'] = axis_count.get(x['axis'] or 'none', 0) + 1
    return {
        'pages': len(pages),
        'raw': len(raws),
        'pending': len([r for r in raws if not r['ingested']]),
        'needs_source': len([p for p in pages if p['needs_source']]),
        'stable': len([p for p in pages if p['status'] == 'stable']),
        'axis': axis_count,
        'lint': {'date': lint['date'], 'counts': lint['counts']} if lint else None,
        'queue': len(queue_items()),
        'vault': os.path.basename(ROOT),
    }


@app.get('/api/pages')
def api_pages():
    return wiki_pages()


@app.get('/api/raw')
def api_raw():
    return raw_files()


@app.get('/api/lint')
def api_lint():
    return latest_lint() or {'counts': {}, 'findings': [], 'stubs': []}


@app.post('/api/lint/run')
def api_lint_run():
    r = subprocess.run(['python', os.path.join(ROOT, 'tools', 'lint.py')],
                       cwd=ROOT, capture_output=True, text=True)
    return {'ok': r.returncode == 0, 'out': r.stdout.strip() or r.stderr.strip(),
            'result': latest_lint()}


@app.post('/api/lint/ignore')
def api_lint_ignore(check: str = Form(...), where: str = Form(...)):
    p = os.path.join(ROOT, 'lint-ignore.json')
    cur = json.loads(rd(p)) if os.path.exists(p) else []
    if not any(x['check'] == check and x['where'] == where for x in cur):
        cur.append({'check': check, 'where': where,
                    'at': str(datetime.date.today())})
    wr(p, json.dumps(cur, ensure_ascii=False, indent=2))
    return {'ok': True, 'count': len(cur)}


@app.get('/api/tags')
def api_tags():
    """기존 주제 태그 — 새 태그를 만들기 전에 재사용하라는 규칙의 UI 버전."""
    c = {}
    for r in raw_files():
        for t in r['topics']:
            c[t] = c.get(t, 0) + 1
    return sorted([{'tag': k, 'n': v} for k, v in c.items()],
                  key=lambda x: (-x['n'], x['tag']))


@app.get('/api/zotero')
def api_zotero():
    """Zotero 라이브러리를 읽는다. 원본은 잠겨 있을 수 있어 사본을 뜬다."""
    src = os.path.join(ZOTERO, 'zotero.sqlite')
    if not os.path.exists(src):
        return {'ok': False, 'error': 'Zotero 데이터 폴더를 찾지 못했습니다: ' + ZOTERO}
    tmp = os.path.join(tempfile.gettempdir(), 'zot-copy.sqlite')
    shutil.copy2(src, tmp)
    c = sqlite3.connect(tmp)
    q = lambda s, *a: c.execute(s, a).fetchall()
    have = set()
    for r in raw_files():
        m = re.search(r'^cite_key:\s*(.+)$', fm_of(rd(os.path.join(ROOT, r['path']))), re.M)
        if m:
            have.add(m.group(1).strip())
    # 휴지통에 넣은 항목은 빼야 한다 — 지운 논문이 '신규'로 다시 떠서
    # 정본을 두 번 만들게 된다
    trashed = set(r[0] for r in q('SELECT itemID FROM deletedItems'))

    # 첨부(PDF·스냅샷)는 한 번에 읽어 부모별로 묶는다.
    # 항목마다 따로 질의하면 라이브러리가 커질수록 느려진다
    att_title = dict(q("""SELECT d.itemID, idv.value FROM itemData d
                          JOIN fields f ON f.fieldID=d.fieldID
                          JOIN itemDataValues idv ON idv.valueID=d.valueID
                          WHERE f.fieldName='title'"""))
    atts = {}
    for aid, pid, ctype, path, akey in q(
            """SELECT ia.itemID, ia.parentItemID, ia.contentType, ia.path, ai.key
               FROM itemAttachments ia JOIN items ai ON ai.itemID=ia.itemID
               WHERE ia.parentItemID IS NOT NULL"""):
        if aid in trashed:
            continue
        # path 는 'storage:<파일명>'. 실제 파일은 storage/<첨부키>/<파일명> 에 있다
        path = path or ''
        fn = path.split('storage:', 1)[1] if path.startswith('storage:') else ''
        full = os.path.join(ZOTERO, 'storage', akey, fn) if fn else ''
        ok = bool(full) and os.path.exists(full)
        atts.setdefault(pid, []).append({
            'key': akey, 'title': att_title.get(aid) or fn or '첨부',
            'is_pdf': ctype == 'application/pdf', 'filename': fn,
            'linked': not fn,           # 링크만 걸린 첨부는 우리가 크기를 알 수 없다
            'exists': ok,
            'mb': round(os.path.getsize(full) / 1e6, 1) if ok else 0,
        })

    items = []
    for iid, ikey, itype in q("""SELECT i.itemID, i.key, it.typeName FROM items i
                           JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                           WHERE it.typeName NOT IN ('attachment','note')"""):
        if iid in trashed:
            continue
        f = dict(q("""SELECT fl.fieldName, idv.value FROM itemData d
                      JOIN fields fl ON fl.fieldID=d.fieldID
                      JOIN itemDataValues idv ON idv.valueID=d.valueID
                      WHERE d.itemID=?""", iid))
        au = [ln + ', ' + fn for ln, fn in
              q("""SELECT cr.lastName, cr.firstName FROM itemCreators ic
                   JOIN creators cr ON cr.creatorID=ic.creatorID
                   WHERE ic.itemID=? ORDER BY ic.orderIndex""", iid)]
        key = f.get('citationKey', '')
        a = atts.get(iid, [])
        items.append({
            'itemType': itype, 'title': f.get('title', ''), 'authors': au,
            'date': (f.get('date', '') or '')[:10], 'doi': f.get('DOI', ''),
            'url': f.get('url', ''), 'venue': f.get('proceedingsTitle')
            or f.get('publicationTitle') or f.get('repository', ''),
            'cite_key': key, 'in_vault': key in have,
            # zotero://select/library/items/<항목키> 로 Zotero 를 연다
            'item_key': ikey,
            'attachments': a,
            # 정본에 적어둘 대표 PDF. raw/papers 의 zotero_key 가 이 값이다
            'pdf_key': next((x['key'] for x in a if x['is_pdf'] and x['exists']), ''),
        })
    return {'ok': True, 'items': sorted(items, key=lambda x: x['in_vault'])}


@app.post('/api/source')
def api_source(kind: str = Form(...), title: str = Form(...),
               why: str = Form(''), axis: str = Form(''),
               topics: str = Form(''), authors: str = Form(''),
               date: str = Form(''), doi: str = Form(''), url: str = Form(''),
               venue: str = Form(''), cite_key: str = Form(''),
               zotero_key: str = Form(''),
               filename: str = Form(''), queue: str = Form('')):
    """raw/ 에 정본 .md 를 만든다. PDF는 Zotero가 관리하므로 복사하지 않는다."""
    folder = {'paper': 'papers', 'article': 'articles', 'book': 'books',
              'video': 'videos', 'writeup': 'writeups', 'note': 'notes'}.get(kind, 'inbox')
    name = (filename or title)[:70].strip()
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, ' ')
    name = ' '.join(name.split())
    path = os.path.join(ROOT, 'raw', folder, name + '.md')
    if os.path.exists(path):
        return JSONResponse({'ok': False, 'error': '이미 있는 파일입니다: ' + name}, 400)
    tags = ['raw/' + kind] + [t.strip() for t in topics.split(',') if t.strip()]
    L = ['---', 'type: ' + kind, 'title: ' + title]
    if authors:
        L.append('author:')
        L += ['  - ' + a.strip() for a in authors.split(';') if a.strip()]
    for k, v in (('source', url), ('published', date), ('venue', venue),
                 ('doi', doi), ('cite_key', cite_key),
                 # PDF 첨부키. 이게 있어야 위키에서 원문 PDF 로 되돌아갈 수 있다
                 ('zotero_key', zotero_key)):
        if v:
            L.append(k + ': ' + v)
    L += ['collected: ' + str(datetime.date.today()),
          'why: ' + why, 'axis: ' + axis, 'ingested: false', 'tags:']
    L += ['  - ' + t for t in tags]
    L += ['---', '', '## 본문', '',
          '(PDF는 Zotero가 관리한다. 본문 텍스트나 발췌를 여기 붙인다.)', '']
    wr(path, NL.join(L))
    rel = os.path.relpath(path, ROOT).replace(chr(92), '/')
    if queue:
        add_queue(rel, title)
    return {'ok': True, 'path': rel, 'queued': bool(queue)}


def queue_items():
    p = os.path.join(ROOT, 'queue.md')
    if not os.path.exists(p):
        return []
    return [l for l in rd(p).split(NL) if l.startswith('- [ ]')]


def add_queue(rel, title):
    p = os.path.join(ROOT, 'queue.md')
    head = ('# 인제스트 대기열' + NL * 2 +
            '> 웹 UI가 접수하고 `/ingest`가 처리한다. 처리하면 `- [x]`로 바꾼다.' + NL * 2)
    cur = rd(p) if os.path.exists(p) else head
    io.open(p, 'a' if os.path.exists(p) else 'w', encoding='utf-8').write(
        ('' if os.path.exists(p) else head) +
        '- [ ] `' + rel + '` — ' + title[:60] + '  (' + str(datetime.date.today()) + ')' + NL)


@app.get('/api/queue')
def api_queue():
    return {'items': queue_items()}


# ── 마크다운 렌더링 ───────────────────────────────────────────
# 표준 마크다운으로 처리되지 않는 우리 문법 셋을 먼저 변환한다.
#   [[위키링크]]  ^[출처 마커]  > [!콜아웃]

def _callouts(text):
    """> [!inference] 블록을 div로 바꾼다."""
    out, i, lines = [], 0, text.split(NL)
    while i < len(lines):
        m = re.match(r'^>\s*\[!(\w+)\]\s*(.*)$', lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        kind, title = m.group(1).lower(), m.group(2).strip()
        body, i = [], i + 1
        while i < len(lines) and lines[i].startswith('>'):
            body.append(re.sub(r'^>\s?', '', lines[i])); i += 1
        out.append('<div class="co co-' + kind + '">')
        out.append('<b>' + (title or kind) + '</b>' + NL)
        out.append(NL.join(body))
        out.append('</div>')
    return NL.join(out)


def _inline(html):
    html = re.sub(r'\^\[([^\]]+)\]',
                  lambda m: '<sup class="mk" title="' + m.group(1) + '">출처</sup>', html)
    html = re.sub(r'\[\[([^\]|#]+?)(?:\|([^\]]+))?\]\]',
                  lambda m: '<a class="wl" data-p="' + m.group(1).strip() + '">'
                            + (m.group(2) or m.group(1)).strip() + '</a>', html)
    return html


def render_md(body):
    import markdown as _md
    h = _md.markdown(_callouts(body),
                     extensions=['tables', 'fenced_code', 'sane_lists'])
    return _inline(h)


def find_page(name):
    """이름 하나로 파일을 찾는다. raw/ 도 본다 — 원본을 읽어야
    위키의 서술이 어디서 왔는지 확인할 수 있기 때문이다."""
    if name.endswith('.md') and os.path.exists(os.path.join(ROOT, name)):
        return os.path.join(ROOT, name)          # 경로로 직접 지정한 경우
    for d in ('wiki', 'context', 'docs', 'wiki/_archive', ''):
        q = os.path.join(ROOT, d, name + '.md')
        if os.path.exists(q):
            return q
    for q in glob.glob(os.path.join(ROOT, 'raw', '*', name + '.md')):
        return q
    return None


@app.get('/api/browse')
def api_browse():
    """뷰어 왼쪽 목록. 위키와 원본을 같은 모양으로 돌려준다.

    원본은 `raw/CLAUDE.md`에 따라 불변이므로 읽기만 한다.
    """
    out = []
    for r in wiki_pages():
        out.append({'name': r['name'], 'layer': 'wiki', 'axis': r.get('axis', ''),
                    'status': r.get('status', ''), 'sub': r.get('description', '')})
    for r in raw_files():
        out.append({'name': os.path.basename(r['path'])[:-3], 'layer': 'raw',
                    'axis': r.get('axis', ''),
                    'status': 'ingested' if r.get('ingested') else '미인제스트',
                    'sub': r['path'], 'path': r['path']})
    return out


@app.get('/api/page')
def api_page(name: str):
    p = find_page(name)
    if not p:
        return JSONResponse({'ok': False, 'error': '없는 페이지: ' + name}, 404)
    rel = os.path.relpath(p, ROOT).replace(chr(92), '/')
    text = rd(p)
    fm, body = fm_of(text), text[len(fm_of(text)):]
    meta = dict(re.findall(r'^([a-z_]+):\s*(.*)$', fm, re.M))
    out = sorted(set(re.findall(r'\[\[([^\]|#]+)', re.sub(r'`[^`]*`', '', body))))
    back = []
    for q in glob.glob(os.path.join(ROOT, 'wiki', '*.md')) +             glob.glob(os.path.join(ROOT, 'context', '*.md')) +             glob.glob(os.path.join(ROOT, 'docs', '*.md')):
        b = os.path.basename(q)[:-3]
        if b == name:
            continue
        if re.search(r'\[\[' + re.escape(name) + r'[\]|#]', rd(q)):
            back.append(b)
    # 원본은 위키링크가 아니라 출처 마커 ^[raw/...] 로 인용된다.
    # 그것도 백링크로 쳐야 "이 자료를 근거로 쓴 페이지"를 볼 수 있다.
    if rel.startswith('raw/'):
        # 기사는 경로로, 논문·책은 cite_key로 인용된다. 둘 다 본다
        keys = [rel]
        m = re.search(r'^cite_key:\s*(.+)$', fm, re.M)
        if m:
            keys.append(m.group(1).strip())
        for q in glob.glob(os.path.join(ROOT, 'wiki', '*.md')):
            b = os.path.basename(q)[:-3]
            if b in back or b in ('log', 'index', 'review', 'CLAUDE'):
                continue
            t = rd(q)
            if any(k in t for k in keys):
                back.append(b)
    return {'ok': True, 'name': name, 'layer': rel.split('/')[0],
            'path': rel,
            'meta': meta, 'html': render_md(body),
            'outlinks': [x.strip() for x in out], 'backlinks': sorted(back),
            'vault': os.path.basename(ROOT)}


@app.get('/api/search')
def api_search(q: str):
    """제목·별칭·본문 전체 검색. Obsidian의 Ctrl+Shift+F 대응."""
    ql, hits = q.lower(), []
    for folder in ('wiki', 'raw', 'context', 'docs'):
        for p2 in glob.glob(os.path.join(ROOT, folder, '**', '*.md'), recursive=True):
            b = os.path.basename(p2)[:-3]
            if b == 'CLAUDE':
                continue
            s2 = rd(p2)
            n = s2.lower().count(ql)
            if not n and ql not in b.lower():
                continue
            idx = s2.lower().find(ql)
            snip = ''
            if idx >= 0:
                snip = ' '.join(s2[max(0, idx - 60):idx + 90].split())
            rel2 = os.path.relpath(p2, ROOT).replace(chr(92), '/')
            # 뷰어는 raw 도 연다. 원본은 경로로 열어야 같은 이름 충돌이 없다
            hits.append({'name': b, 'folder': folder, 'hits': n, 'snippet': snip,
                         'layer': rel2.split('/')[0], 'path': rel2,
                         'openable': True})
    return sorted(hits, key=lambda x: -x['hits'])[:40]


@app.get('/api/llm')
def api_llm():
    """LLM을 부를 수 있는 상태인가. UI가 이걸로 버튼을 켠다."""
    return llm.status()


@app.post('/api/llm')
def api_llm_set(provider: str = Form(None), model: str = Form(None)):
    llm.save_config(provider=provider or None, model=model or None)
    return llm.status()


@app.post('/api/llm/test')
def api_llm_test():
    """키가 실제로 통하는지 확인한다. status()는 키가 있는지만 본다 —
    만료·잔액부족·오타는 실제로 불러봐야 안다."""
    return llm.ping()


@app.get('/api/ingest')
def api_ingest_list():
    return {'pending': ingest.pending(), 'llm': llm.status(),
            'running': [k for k, v in JOBS.items() if v.is_alive()]}


@app.post('/api/ingest')
def api_ingest_start(path: str = Form(...), plan_only: bool = Form(False)):
    """인제스트를 백그라운드로 시작하고 작업 번호를 준다.

    긴 작업이라 요청 안에서 끝내면 브라우저가 먼저 끊긴다.
    진행 상황은 reports/ingest-<id>.json 을 폴링해서 본다.
    """
    st = llm.status()
    if not st['ok']:
        return JSONResponse({'error': st['why'], 'llm': st}, status_code=400)
    jid = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    ingest.progress(jid, path=path, stage='대기', step=0, of=4, done=False)

    def work():
        try:
            ingest.run(path, plan_only=plan_only, jid=jid)
        except Exception as e:                      # noqa: BLE001
            ingest.progress(jid, stage='실패', done=True, error=str(e)[:500])

    t = threading.Thread(target=work, daemon=True)
    JOBS[jid] = t
    t.start()
    return {'jid': jid}


@app.get('/api/ingest/job')
def api_ingest_job(jid: str):
    p = os.path.join(ROOT, 'reports', 'ingest-%s.json' % jid)
    if not os.path.exists(p):
        return JSONResponse({'error': '없는 작업'}, status_code=404)
    d = json.loads(rd(p))
    d['alive'] = jid in JOBS and JOBS[jid].is_alive()
    return d


@app.get('/api/ingest/preview')
def api_ingest_preview(jid: str):
    """계획이 무엇을 바꾸는지 미리 본다. 지우는 줄이 있는지가 핵심이다 —
    `mode: update` 는 더하기만 해야 한다."""
    import difflib
    f = os.path.join(ROOT, 'reports', 'ingest-%s.json' % jid)
    if not os.path.exists(f):
        return JSONResponse({'error': '없는 작업'}, status_code=404)
    d = json.loads(rd(f))
    plan = d.get('plan') or {}
    out = []
    for e in plan.get('edits') or []:
        q = os.path.join(ROOT, 'wiki', (e.get('page') or '') + '.md')
        cur = rd(q) if os.path.exists(q) else ''
        new = e.get('content') or ''
        dl = list(difflib.unified_diff(cur.split(NL), new.split(NL), lineterm='', n=0))
        rm = [l[1:] for l in dl if l.startswith('-') and not l.startswith('---') and l[1:].strip()]
        out.append({
            'page': e.get('page'), 'mode': e.get('mode'), 'why': e.get('why'),
            'before': len(cur), 'after': len(new),
            'added': len([l for l in dl if l.startswith('+') and not l.startswith('+++')]),
            'removed': len(rm), 'removed_lines': rm[:12],
        })
    return {'edits': out, 'review': plan.get('review') or [],
            'log': plan.get('log', ''), 'applied': d.get('applied')}


@app.post('/api/ingest/apply')
def api_ingest_apply(jid: str = Form(...)):
    """확인한 계획을 그대로 적용한다. 다시 부르지 않는다 —
    확인한 계획과 적용한 계획이 같아야 한다."""
    try:
        return {'ok': True, 'applied': ingest.apply_saved(jid)}
    except SystemExit as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)


@app.get('/api/review')
def api_review():
    """리뷰 큐 — 자동 인제스트가 판단을 미룬 것들."""
    p = os.path.join(ROOT, 'wiki', 'review.md')
    if not os.path.exists(p):
        return {'open': [], 'done': 0, 'exists': False}
    t = rd(p)
    op = re.findall(r'^- \[ \] (.+)$', t, re.M)
    return {'open': op, 'done': len(re.findall(r'^- \[x\]', t, re.M)),
            'exists': True}


def _sse(event, data):
    return 'event: ' + event + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n'


@app.post('/api/query/start')
def api_query_start(q: str = Form(...), use_raw: bool = Form(False),
                    max_pages: int = Form(4)):
    """질의를 백그라운드로 시작한다. 실제 답변은 /query/events 로 스트리밍된다.

    긴 작업이라 요청 안에서 끝내면 브라우저가 먼저 끊긴다 — 인제스트와 같은 이유.
    """
    st = llm.status()
    if not st['ok']:
        return JSONResponse({'error': st['why'], 'llm': st}, status_code=400)
    jid = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    qu, cancel = queue.Queue(), threading.Event()
    QSTREAMS[jid] = {'q': qu, 'cancel': cancel}

    def work():
        try:
            r = query.run_stream(
                q, use_raw=use_raw, max_pages=max_pages,
                on_event=lambda kind, data: qu.put((kind, data)),
                cancel=cancel.is_set)
            LAST_Q['r'] = r
            RESULTS[jid] = r
        except Exception as e:                       # noqa: BLE001
            qu.put(('error', {'error': str(e)[:400]}))

    threading.Thread(target=work, daemon=True).start()
    return {'jid': jid}


@app.get('/api/query/events')
async def api_query_events(request: Request, jid: str):
    """SSE로 진행 단계·토큰·최종 결과를 흘려보낸다.

    **클라이언트가 떠나면 중단 버튼을 누른 것과 똑같이 처리한다.** 새로고침·탭
    이동으로 연결이 끊겨도 서버가 모르고 계속 기다리면 두 가지가 잘못된다 —
    (1) 아무도 안 보는데 LLM 호출이 끝까지 돌아 요금이 나간다,
    (2) 결국 죽은 소켓에 쓰려다 `ConnectionResetError`가 콘솔에 찍힌다.
    1초마다 `request.is_disconnected()`로 확인해서 두 문제를 한 번에 막는다.
    """
    st = QSTREAMS.get(jid)
    if not st:
        return JSONResponse({'error': '없는 작업'}, status_code=404)

    async def gen():
        t0 = time.monotonic()
        try:
            while True:
                if await request.is_disconnected():
                    st['cancel'].set()   # 떠난 것도 중단과 같다 — 과금을 멈춘다
                    break
                if time.monotonic() - t0 > 600:
                    yield _sse('error', {'error': '응답 시간 초과'})
                    break
                try:
                    kind, data = await asyncio.to_thread(st['q'].get, True, 1.0)
                except queue.Empty:
                    continue
                yield _sse(kind, data)
                if kind in ('done', 'error', 'cancelled'):
                    break
        finally:
            QSTREAMS.pop(jid, None)

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache',
                                      'X-Accel-Buffering': 'no'})


@app.post('/api/query/stop')
def api_query_stop(jid: str = Form(...)):
    """진짜 중단이다 — 플래그만 세우는 게 아니라, chat_stream이 다음 청크에서
    이 플래그를 보고 실제로 연결을 닫아 과금을 멈춘다."""
    st = QSTREAMS.get(jid)
    if not st:
        return JSONResponse({'ok': False, 'error': '없는 작업(이미 끝났을 수 있다)'}, 404)
    st['cancel'].set()
    return {'ok': True}


@app.post('/api/query/save')
def api_query_save(jid: str = Form('')):
    """답변을 Output/ 에 남긴다. SKILL.md: 저장은 확인 뒤에.

    `jid` 를 주면 그 턴의 답변을, 안 주면 직전 답변을 저장한다.
    """
    r = RESULTS.get(jid) or LAST_Q.get('r')
    if not r:
        return JSONResponse({'error': '저장할 답변이 없다'}, status_code=400)
    try:
        return {'ok': True, 'path': query.save(r)}
    except SystemExit as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)


@app.get('/', response_class=HTMLResponse)
def index():
    return rd(os.path.join(ROOT, 'tools', 'static', 'index.html'))


if __name__ == '__main__':
    import sys, uvicorn
    port = 5000
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])
    host = '0.0.0.0' if '--lan' in sys.argv else '127.0.0.1'
    print('  http://localhost:%d' % port)
    if host == '0.0.0.0':
        import socket
        try:
            ip = socket.gethostbyname(socket.gethostname())
            print('  http://%s:%d   (같은 와이파이의 다른 기기)' % (ip, port))
        except Exception:
            pass
    print('  종료: Ctrl+C')
    uvicorn.run(app, host=host, port=port, log_level='warning')

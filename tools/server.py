#!/usr/bin/env python3
"""볼트 웹 UI — 1단계. LLM을 쓰지 않는다.

원칙 (루트 CLAUDE.md "도구를 추가할 때"):
  1. 파일이 정본이다. 이 서버가 만드는 상태도 전부 파일이다
     (queue.md, lint-ignore.json, reports/)
  2. 규칙을 코드에 복사하지 않는다 — 1단계는 규칙 판단을 하지 않으므로 해당 없음
  3. 이 서버를 꺼도 Obsidian·git·Claude Code가 그대로 동작한다

실행:
    python tools/server.py                  localhost:5000
    python tools/server.py --port 8000
    python tools/server.py --lan            같은 와이파이의 다른 기기에서 접속
"""
import io, os, re, json, glob, shutil, sqlite3, tempfile, subprocess, datetime
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)
ZOTERO = os.path.join(os.path.expanduser('~'), 'Zotero')
PREFIX_AXIS = {'ai-for-security': '(AI활용)', 'securing-ai': '(AI보호)',
               'both': '(공통)', '': '(기타)'}

app = FastAPI(title='LLM Wiki')


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
    items = []
    for iid, itype in q("""SELECT i.itemID, it.typeName FROM items i
                           JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                           WHERE it.typeName NOT IN ('attachment','note')"""):
        f = dict(q("""SELECT fl.fieldName, idv.value FROM itemData d
                      JOIN fields fl ON fl.fieldID=d.fieldID
                      JOIN itemDataValues idv ON idv.valueID=d.valueID
                      WHERE d.itemID=?""", iid))
        au = [ln + ', ' + fn for ln, fn in
              q("""SELECT cr.lastName, cr.firstName FROM itemCreators ic
                   JOIN creators cr ON cr.creatorID=ic.creatorID
                   WHERE ic.itemID=? ORDER BY ic.orderIndex""", iid)]
        key = f.get('citationKey', '')
        items.append({
            'itemType': itype, 'title': f.get('title', ''), 'authors': au,
            'date': (f.get('date', '') or '')[:10], 'doi': f.get('DOI', ''),
            'url': f.get('url', ''), 'venue': f.get('proceedingsTitle')
            or f.get('publicationTitle') or f.get('repository', ''),
            'cite_key': key, 'in_vault': key in have,
        })
    return {'ok': True, 'items': sorted(items, key=lambda x: x['in_vault'])}


@app.post('/api/source')
def api_source(kind: str = Form(...), title: str = Form(...),
               why: str = Form(''), axis: str = Form(''),
               topics: str = Form(''), authors: str = Form(''),
               date: str = Form(''), doi: str = Form(''), url: str = Form(''),
               venue: str = Form(''), cite_key: str = Form(''),
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
                 ('doi', doi), ('cite_key', cite_key)):
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
    for d in ('wiki', 'context', 'docs', 'wiki/_archive', ''):
        p = os.path.join(ROOT, d, name + '.md')
        if os.path.exists(p):
            return p
    return None


@app.get('/api/page')
def api_page(name: str):
    p = find_page(name)
    if not p:
        return JSONResponse({'ok': False, 'error': '없는 페이지: ' + name}, 404)
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
    return {'ok': True, 'name': name,
            'path': os.path.relpath(p, ROOT).replace(chr(92), '/'),
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
            hits.append({'name': b, 'folder': folder, 'hits': n, 'snippet': snip,
                         'openable': folder in ('wiki', 'context', 'docs')})
    return sorted(hits, key=lambda x: -x['hits'])[:40]


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

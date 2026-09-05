"""query — 위키를 근거로 답한다.

**규칙을 여기에 복사하지 않는다.** `.claude/skills/query/SKILL.md`와
`context/나의 핵심 맥락.md`를 읽어서 시스템 프롬프트로 넣는다.

검색 엔진으로 대체하지 않는 이유: `status`에 따라 인용 강도를 바꾸는 것이
이 위키의 목적(논문 자료)에 직결된다. 유사도 순위는 그걸 못 한다.

2단계로 나눠 부른다.
  1차 — index와 페이지 목록만 주고 **어느 페이지를 읽을지** 고르게 한다
  2차 — 고른 페이지 전문만 주고 답하게 한다
전체를 넣지 않으므로 싸고, 근거가 명확해진다.

    python tools/query.py "질문"
    python tools/query.py "질문" --raw     원본까지 뒤진다
"""

import datetime
import glob
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RULES = [
    'CLAUDE.md',
    'context/나의 핵심 맥락.md',
    'context/위키 규약.md',
    '.claude/skills/query/SKILL.md',
]

# status 별 인용 강도. SKILL.md의 표를 코드가 아니라 화면이 쓰는 값이다.
STRENGTH = {
    'stable': ('자유롭게 인용', 'ok'),
    'draft': ('인용하되 검증 필요', 'warn'),
    'seed': ('근거로 인용 금지', 'err'),
}

S = {'type': 'string'}


def _obj(props):
    return {'type': 'object', 'additionalProperties': False,
            'properties': props, 'required': list(props)}


PICK_SCHEMA = _obj({
    'axis': {'type': 'string', 'enum': ['ai-for-security', 'securing-ai', 'both', 'unknown']},
    'pages': {'type': 'array', 'items': S},
    'why': S,
    'in_wiki': {'type': 'boolean'},
})

ANSWER_SCHEMA = _obj({
    'answer': S,
    'in_wiki': {'type': 'boolean'},
    'missing': S,
    'sources': {'type': 'array', 'items': _obj({
        'page': S, 'used_for': S})},
    'suggest_collect': S,
})

# 스트리밍 경로(run_stream)가 쓰는 스키마. 답변 본문은 스키마 없이 스트리밍하고,
# 스트리밍이 끝난 뒤 이 작은 스키마로 판단(위키에 있었나·뭐가 빠졌나)만 뽑는다 —
# 전체 페이지를 다시 보내지 않으므로 이 호출은 싸다.
EXTRACT_SCHEMA = _obj({
    'in_wiki': {'type': 'boolean'},
    'missing': S,
    'suggest_collect': S,
})


def rd(p):
    return io.open(p, encoding='utf-8').read()


def fm_of(t):
    e = t.find('\n---', 3)
    return t[:e] if e > 0 else ''


def g(fm, k):
    m = re.search(r'^' + k + r':\s*(.+)$', fm, re.M)
    return m.group(1).strip().strip('"') if m else ''


def build_system():
    parts = ['다음은 이 볼트의 규칙 문서 전문이다. 전부 따른다.\n']
    for rel in RULES:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            parts.append('\n\n===== 파일: %s =====\n%s' % (rel, rd(p)))
    return ''.join(parts)


def catalog():
    """페이지 목록 — 1차 호출에 주는 전부. 본문은 주지 않는다."""
    rows, meta = [], {}
    for p in sorted(glob.glob(os.path.join(ROOT, 'wiki', '*.md'))):
        b = os.path.basename(p)[:-3]
        if b in ('CLAUDE', 'log', 'review') or '.example' in b:
            continue
        fm = fm_of(rd(p))
        st = g(fm, 'status') or '?'
        al = g(fm, 'aliases')
        meta[b] = {'status': st, 'source': g(fm, 'source'),
                   'needs_source': 'needs_source: true' in fm,
                   'derived': 'derived: true' in fm}
        rows.append('- [[%s]] · %s · %s%s' % (
            b, st, (g(fm, 'description') or '')[:100],
            (' · 별칭 ' + al) if al else ''))
    return '\n'.join(rows), meta


def page_text(name):
    for d in ('wiki', 'context'):
        p = os.path.join(ROOT, d, name + '.md')
        if os.path.exists(p):
            return rd(p), os.path.relpath(p, ROOT).replace('\\', '/')
    return None, None


def raw_hits(q):
    """최후 수단. SKILL.md: raw는 양이 많고 정리돼 있지 않다."""
    out = []
    for p in glob.glob(os.path.join(ROOT, 'raw', '**', '*.md'), recursive=True):
        if os.path.basename(p) == 'CLAUDE.md':
            continue
        t = rd(p)
        n = sum(t.lower().count(w.lower()) for w in q.split() if len(w) > 1)
        if n:
            out.append((n, os.path.relpath(p, ROOT).replace('\\', '/'), t))
    out.sort(reverse=True)
    return out[:2]


PICK = """질문: %(q)s

## 위키 페이지 목록 (본문 아님)
%(cat)s

## index.md
```
%(index)s
```

이 질문에 답하려면 **어느 페이지를 읽어야 하는가.** 아직 답하지 마라.

- 최대 %(max)s개까지 고른다. 위키 전체를 읽지 않는 것이 목적이다.
- 목록에 **정확히 있는 이름**만 쓴다. 지어내지 마라.
- 별칭(한국어·영어·약어)도 살펴 고른다.
- 답할 근거가 될 만한 페이지가 하나도 없으면 `in_wiki` 를 false 로 하고
  `pages` 를 비운다. **없는 것을 있다고 하지 마라.**"""

ANSWER = """질문: %(q)s

## 읽은 페이지 전문
%(bodies)s
%(raws)s

위 내용만 근거로 답하라.

- 근거가 된 페이지를 `[[페이지 이름]]` 으로 밝힌다. **읽지 않은 페이지를 링크하지 마라.**
- `status: draft` 인 페이지를 인용하면 **검증이 필요하다고 명시**한다.
  `status: seed` 는 근거로 쓰지 마라.
- 한 페이지에만 있는 서술이면 그렇다고 밝힌다. 단일 출처로 단정하지 마라.
- 개념부터 설명하고 비교 가능한 예시를 든다. 결론만 던지지 마라.
- 위 내용으로 답할 수 없는 부분은 `missing` 에 적고 `in_wiki` 를 false 로 한다.
  **위키에 없는 것을 있는 것처럼 섞지 마라.** 이 구분이 무너지면 위키 전체가 무너진다.
- `suggest_collect` 에는 어떤 자료를 모으면 좋을지 적는다. 없으면 빈 문자열."""


def run(q, use_raw=False, on=None):
    on = on or (lambda **k: None)
    system = build_system()
    cat, meta = catalog()
    idx = os.path.join(ROOT, 'wiki', 'index.md')

    on(stage='후보 선정', step=1, of=2)
    pick, u1 = llm.chat_json(system, PICK % {
        'q': q, 'cat': cat, 'max': 4,
        'index': rd(idx) if os.path.exists(idx) else ''},
        max_tokens=8000, schema=PICK_SCHEMA)

    names = [n for n in (pick.get('pages') or []) if n in meta][:4]
    on(stage='읽기', step=2, of=2, pick=pick, picked=names, usage_pick=u1)

    bodies, used = [], []
    for n in names:
        t, rel = page_text(n)
        if t:
            bodies.append('\n### %s  (status: %s)\n```\n%s\n```' % (n, meta[n]['status'], t))
            used.append(n)
    raws = ''
    if use_raw or not used:
        rh = raw_hits(q)
        if rh:
            raws = '\n## 원본 (최후 수단)\n' + ''.join(
                '\n### %s\n```\n%s\n```' % (p, t[:6000]) for _, p, t in rh)

    if not used and not raws:
        return {'q': q, 'pick': pick, 'answer': None, 'in_wiki': False,
                'missing': '이 볼트에 근거가 없다.', 'sources': [],
                'suggest_collect': '이 주제의 기사나 논문을 raw/ 에 모아라.',
                'usage': u1}

    ans, u2 = llm.chat_json(system, ANSWER % {
        'q': q, 'bodies': ''.join(bodies) or '(없음)', 'raws': raws},
        max_tokens=24000, schema=ANSWER_SCHEMA)

    # 축 접두어의 여는 괄호를 빠뜨리는 일이 잦다 — `[[AI보호) 프롬프트 인젝션]]`.
    # Obsidian에서 열리지 않는 깨진 링크이므로 기계적으로 고친다.
    body = ans.get('answer') or ''
    for n in used:
        if n.startswith('(') and ('[[' + n[1:] + ']]') in body:
            body = body.replace('[[' + n[1:] + ']]', '[[' + n + ']]')
    ans['answer'] = body

    # 링크를 건 페이지가 실제로 읽은 것인지 검사한다.
    # SKILL.md: "링크를 걸었으면 그 페이지를 실제로 읽었어야 한다."
    linked = set(re.findall(r'\[\[([^\]|#]+)', body))
    ghost = sorted(l.strip() for l in linked if l.strip() not in used)

    srcs = []
    for s0 in (ans.get('sources') or []):
        n = s0.get('page', '')
        m = meta.get(n, {})
        st = m.get('status', '?')
        srcs.append({'page': n, 'used_for': s0.get('used_for', ''), 'status': st,
                     'strength': STRENGTH.get(st, ('알 수 없음', 'warn'))[0],
                     'level': STRENGTH.get(st, ('', 'warn'))[1],
                     'needs_source': m.get('needs_source', False),
                     'derived': m.get('derived', False),
                     'read': n in used})
    return {'q': q, 'pick': pick, 'read': used, 'ghost_links': ghost,
            'answer': ans.get('answer'), 'in_wiki': ans.get('in_wiki'),
            'missing': ans.get('missing'), 'sources': srcs,
            'suggest_collect': ans.get('suggest_collect'),
            'usage': {k: u1.get(k, 0) + u2.get(k, 0) for k in set(u1) | set(u2)},
            'at': datetime.datetime.now().isoformat(timespec='seconds')}


STREAM_PROMPT = """질문: %(q)s

## 읽은 페이지 (번호 붙임)
%(bodies)s
%(raws)s

위 내용만 근거로 답하라. **JSON이 아니라 일반 텍스트로 답한다.**

- 인용은 반드시 번호로 한다 — 예: `...라고 서술한다[1].` 두 페이지를 함께
  인용하면 `[1][2]`. **`[[페이지 이름]]` 형태의 위키링크는 쓰지 마라** —
  번호만 쓴다. 주어진 번호(1~%(n)s) 밖의 번호를 지어내지 마라.
- `status: draft` 인 페이지를 인용하면 **검증이 필요하다고 명시**한다.
  `status: seed` 는 근거로 쓰지 마라.
- 한 페이지에만 있는 서술이면 그렇다고 밝힌다. 단일 출처로 단정하지 마라.
- 개념부터 설명하고 비교 가능한 예시를 든다. 결론만 던지지 마라.
- 위 내용으로 답할 수 없는 부분은 **"위키에 없음"이라고 문장으로 명시**한다.
  위키에 없는 것을 있는 것처럼 섞지 마라. 이 구분이 무너지면 위키 전체가 무너진다."""

EXTRACT_PROMPT = """질문: %(q)s

## 방금 작성한 답변
%(answer)s

## 답변이 인용에 쓴 페이지
%(pages)s

이 답변을 근거로 다음만 판단하라 (답변을 다시 쓰지 마라):
- `in_wiki`: 질문에 위키 근거로 답했으면 true, "위키에 없음"이 핵심이면 false
- `missing`: 답변이 다루지 못한 부분. 없으면 빈 문자열
- `suggest_collect`: 보강하면 좋을 자료. 없으면 빈 문자열"""


def run_stream(q, use_raw=False, max_pages=4, on_event=None, cancel=None):
    """실시간 스트리밍 경로. 웹 UI 질문 탭이 쓴다.

    `on_event(kind, data)`를 단계마다 부른다 — kind는
    'stage'(진행 단계) / 'token'(답변 토큰 조각) / 'done'(최종 결과) /
    'cancelled'(중단됨). CLI의 `run()`은 이 함수를 쓰지 않는다 — 인용 문법이
    다르다(번호 `[n]` vs 위키링크 `[[이름]]`). 웹 UI만 번호 인용을 쓴다.
    """
    on_event = on_event or (lambda k, d: None)
    cancel = cancel or (lambda: False)
    system = build_system()
    cat, meta = catalog()
    idx = os.path.join(ROOT, 'wiki', 'index.md')

    on_event('stage', {'stage': '질문 확인', 'step': 0, 'of': 3})
    pick, u1 = llm.chat_json(system, PICK % {
        'q': q, 'cat': cat, 'max': max_pages,
        'index': rd(idx) if os.path.exists(idx) else ''},
        max_tokens=8000, schema=PICK_SCHEMA)

    on_event('stage', {'stage': '위키 후보 찾기', 'step': 1, 'of': 3, 'pick': pick})
    names = [n for n in (pick.get('pages') or []) if n in meta][:max_pages]

    bodies, used = [], []
    for i, n in enumerate(names, 1):
        t, _rel = page_text(n)
        if t:
            bodies.append('\n### [%d] %s  (status: %s)\n```\n%s\n```'
                          % (i, n, meta[n]['status'], t))
            used.append(n)
    raws = ''
    if use_raw or not used:
        rh = raw_hits(q)
        if rh:
            raws = '\n## 원본 (최후 수단, 번호 없음 — 인용하지 마라)\n' + ''.join(
                '\n### %s\n```\n%s\n```' % (p, t[:6000]) for _, p, t in rh)

    if not used and not raws:
        r = {'q': q, 'pick': pick, 'answer': None, 'in_wiki': False,
             'missing': '이 볼트에 근거가 없다.', 'sources': [],
             'suggest_collect': '이 주제의 기사나 논문을 raw/ 에 모아라.',
             'usage': u1, 'read': [], 'ghost_citations': [],
             'at': datetime.datetime.now().isoformat(timespec='seconds')}
        on_event('done', r)
        return r

    # 답변이 나오기 전에 인용 번호가 무엇을 가리키는지 먼저 알려준다.
    # 이게 없으면 클라이언트는 스트리밍 중 나오는 [n]을 어디로 연결할지 모른다
    # — 인용이 "표시는 되는데 클릭이 안 되는" 상태가 된다.
    # 스트리밍 시작 전에 순번표를 먼저 보낸다 — 그래야 클라이언트가 [1][2]를
    # 스트리밍 도중에도 클릭 가능한 버튼으로 렌더링할 수 있다. 이벤트 이름과
    # 필드는 tools/static/index.html 의 'candidates' 리스너와 반드시 맞아야 한다.
    on_event('candidates', {'pages': [
        {'ordinal': i, 'page': n} for i, n in enumerate(used, 1)]})

    on_event('stage', {'stage': '답변 작성', 'step': 2, 'of': 3})
    text, u2, cancelled = llm.chat_stream(
        system, STREAM_PROMPT % {'q': q, 'bodies': ''.join(bodies) or '(없음)',
                                 'raws': raws, 'n': len(used)},
        max_tokens=16000,
        on_delta=lambda d: on_event('token', {'delta': d}),
        cancel=cancel)

    if cancelled:
        r = {'q': q, 'answer': text, 'cancelled': True,
             'usage': {k: u1.get(k, 0) + u2.get(k, 0) for k in set(u1) | set(u2)},
             'at': datetime.datetime.now().isoformat(timespec='seconds')}
        on_event('cancelled', r)
        return r

    # 인용 번호를 우리가 만든 순번표와 대조한다 — 모델이 지어낼 수 없다
    cited = sorted(set(int(m) for m in re.findall(r'\[(\d{1,2})\]', text)))
    ghost = [n for n in cited if n < 1 or n > len(used)]
    srcs = []
    for n in cited:
        if n < 1 or n > len(used):
            continue
        name = used[n - 1]
        m = meta.get(name, {})
        st = m.get('status', '?')
        srcs.append({'ordinal': n, 'page': name, 'status': st,
                     'strength': STRENGTH.get(st, ('알 수 없음', 'warn'))[0],
                     'level': STRENGTH.get(st, ('', 'warn'))[1],
                     'needs_source': m.get('needs_source', False),
                     'derived': m.get('derived', False)})

    pages_desc = ''.join('- [%d] %s (%s)\n' % (n, used[n - 1], meta[used[n - 1]]['status'])
                         for n in range(1, len(used) + 1))
    ext, u3 = llm.chat_json(system, EXTRACT_PROMPT % {
        'q': q, 'answer': text, 'pages': pages_desc or '(없음)'},
        max_tokens=2000, schema=EXTRACT_SCHEMA)

    r = {'q': q, 'pick': pick, 'read': used, 'ghost_citations': ghost,
         'answer': text, 'in_wiki': ext.get('in_wiki'),
         'missing': ext.get('missing'), 'sources': srcs,
         'suggest_collect': ext.get('suggest_collect'),
         'usage': {k: u1.get(k, 0) + u2.get(k, 0) + u3.get(k, 0)
                  for k in set(u1) | set(u2) | set(u3)},
         'at': datetime.datetime.now().isoformat(timespec='seconds')}
    on_event('done', r)
    return r


def save(result, name=None):
    """답변을 `Output/`에 남긴다 — Knowledge Flywheel.

    SKILL.md의 조건을 지킨다.
      - 파생 출처는 raw가 아니라 **wiki 경로**다
      - `derived: true`, `status: draft` 를 넘지 않는다
      - `derived: true` 페이지를 다시 근거로 삼지 않는다 (여기서 걸러낸다)
    호출하는 쪽이 사용자 확인을 받은 뒤에 부른다.
    """
    srcs = [s0['page'] for s0 in result.get('sources') or []]
    derived_src = [s0['page'] for s0 in result.get('sources') or [] if s0.get('derived')]
    if derived_src:
        raise SystemExit('파생 페이지를 근거로 또 파생시킬 수 없다: ' + ', '.join(derived_src))
    q = result['q']
    name = name or re.sub(r'[\\/:*?"<>|]', ' ', q)[:60].strip()
    today = datetime.date.today().isoformat()
    L = ['---', 'title: ' + name,
         'type: note', 'status: draft', 'derived: true',
         'source:'] + ['  - wiki/%s.md' % s0 for s0 in srcs] + [
         'updated: ' + today, 'contested: false', 'contradictions: []',
         'question: ' + q, 'tags: [derived]', '---', '',
         '## 질문', '', q, '', '## 답', '', result.get('answer') or '']
    if result.get('missing'):
        L += ['', '> [!warning] 위키에 없던 부분', '> ' + result['missing']]
    if result.get('suggest_collect'):
        L += ['', '> [!note] 모으면 좋을 자료', '> ' + result['suggest_collect']]
    path = os.path.join(ROOT, 'Output', name + '.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')
    rel = os.path.relpath(path, ROOT).replace('\\', '/')
    with io.open(os.path.join(ROOT, 'wiki', 'log.md'), 'a',
                 encoding='utf-8', newline='\n') as f:
        f.write('%s | query | %s | 질문 "%s" → 근거 %s\n'
                % (today, rel, q[:60], ', '.join(srcs)))
    return rel


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        raise SystemExit('사용법: python tools/query.py "질문"')
    r = run(args[0], use_raw='--raw' in sys.argv,
            on=lambda **k: print('[%s]' % k.get('stage', ''), flush=True))
    print()
    print(r['answer'] or '(답 없음)')
    print()
    if not r.get('in_wiki'):
        print('위키에 없음:', r.get('missing'))
    for s in r['sources']:
        print('  [%s] %s — %s' % (s['status'], s['page'], s['strength']))
    if r.get('ghost_links'):
        print('  주의: 읽지 않은 페이지를 링크했다 →', r['ghost_links'])
    print('  토큰', r.get('usage'))
